"""Run the local terminal with verified live AWS data; no cloud provisioning."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / '.arbitr'


class StartupError(Exception):
    pass


def run(command, **kwargs):
    result = subprocess.run(command, **kwargs)
    if result.returncode:
        raise StartupError(f"Command failed: {command[0]} (exit {result.returncode}).")
    return result


def aws_environment(profile, region):
    env = os.environ.copy()
    # Named profiles must not be overridden by credentials from an old shell.
    for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                'AWS_SECURITY_TOKEN', 'AWS_DEFAULT_PROFILE', 'AWS_ROLE_ARN',
                'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_SESSION_NAME'):
        env.pop(key, None)
    env.update(AWS_PROFILE=profile, AWS_DEFAULT_REGION=region, AWS_REGION=region,
               AWS_PAGER='', AWS_CLI_AUTO_PROMPT='off')
    return env


def check_credentials(profile, region, env):
    command = ['aws', 'sts', 'get-caller-identity', '--profile', profile,
               '--region', region, '--output', 'json', '--no-cli-pager']
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise StartupError('AWS authentication check timed out. Check your internet connection and retry.') from exc
    if result.returncode:
        raise StartupError(
            'AWS authentication failed (missing/expired credentials, profile or network access).\n'
            'Run ./dev --login to sign in again, then select your project.\n'
            f'For details: aws sts get-caller-identity --profile {profile} --region {region}')
    print('AWS credentials verified.', flush=True)


def check_ports(ports):
    for port in ports:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as exc:
                raise StartupError(
                    f'Port {port} is already in use. Stop the existing server first; '
                    f'./dev will not kill it. Inspect with: lsof -nP -iTCP:{port} -sTCP:LISTEN') from exc


def live_ready(capabilities, quotes, region):
    return (capabilities.get('provider') == 'AWS'
            and capabilities.get('status') == 'READY'
            and capabilities.get('configuredRegions') == [region]
            and bool(capabilities.get('offerings'))
            and quotes.get('status') == 'READY'
            and any(q.get('region') == region and q.get('dataKind') == 'OBSERVED'
                    for q in quotes.get('quotes', [])))


def read_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def wait_ready(processes, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check_processes(processes)
        try:
            read_json('http://127.0.0.1:8000/api/health')
            return
        except (OSError, ValueError):
            time.sleep(.5)
    raise StartupError('Backend startup timed out. See .arbitr/backend.log.')


def check_processes(processes):
    for name, proc in processes:
        code = proc.poll()
        if code is not None:
            raise StartupError(f'{name} stopped (exit {code}). See .arbitr/{name}.log.')


def stop_processes(processes):
    # Each owned child has its own group, including Next.js/npm descendants.
    for _, proc in processes:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 8
    for _, proc in processes:
        try:
            proc.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Install dependencies into backend/.venv and frontend/node_modules.')
    parser.add_argument('--login', action='store_true', help='Open AWS browser sign-in before starting.')
    parser.add_argument('--check', action='store_true', help='Check dependencies and AWS credentials without starting servers.')
    parser.add_argument('--profile', default='arbitr')
    parser.add_argument('--region', default='eu-north-1')
    parser.add_argument('--ml', action='store_true', help='Enable selected LightGBM models and fixed instance/AZ price pools.')
    args = parser.parse_args()
    processes = []
    handles = []
    try:
        if os.name != 'posix':
            raise StartupError('This launcher supports macOS/Linux. See docs/AWS_MARKET.md for Windows commands.')
        for tool in ('aws', 'node', 'npm'):
            if not shutil.which(tool):
                raise StartupError(f'Missing {tool}. Install it before running ./dev; see docs/STARTUP.md.')
        node = run(['node', '-p', 'process.versions.node'], capture_output=True, text=True).stdout.strip()
        if tuple(map(int, node.split('.')[:2])) < (20, 9):
            raise StartupError('Node.js 20.9 or newer is required.')
        aws_version = run(['aws', '--version'], capture_output=True, text=True)
        version = re.search(r'aws-cli/(\d+)\.(\d+)\.(\d+)', aws_version.stdout + aws_version.stderr)
        if not version or tuple(map(int, version.groups())) < (2, 32, 0):
            raise StartupError('AWS CLI v2.32 or newer is required for project browser login; see docs/STARTUP.md.')
        if not args.check or args.setup:
            check_ports((8000, 3000))
        venv = ROOT / 'backend/.venv/bin/python'
        if args.setup:
            if not venv.exists():
                run([sys.executable, '-m', 'venv', str(ROOT / 'backend/.venv')])
            extras = '.[dev,aws,ml]' if args.ml else '.[dev,aws]'
            run([str(venv), '-m', 'pip', 'install', '-e', extras, 'botocore[crt]'], cwd=ROOT / 'backend')
            run(['npm', 'ci'], cwd=ROOT / 'frontend')
        python = str(venv) if venv.exists() else sys.executable
        probe = subprocess.run([python, '-c',
            'import sys; assert sys.version_info >= (3,11); import fastapi, uvicorn, pydantic, boto3, awscrt'],
            capture_output=True, text=True)
        if probe.returncode or not (ROOT / 'frontend/node_modules/next/package.json').exists():
            raise StartupError('Dependencies are missing or Python is below 3.11. Run ./dev --setup (Python 3.11/3.12 recommended).')
        if args.ml:
            model_check = subprocess.run([python, '-c',
                'import os; from app.engine.ml_integration import ModelLoader; ModelLoader(os.getenv("PRICE_FORECAST_CONFIG"), os.getenv("PRICE_MODEL_DIR")).load()'],
                cwd=ROOT / 'backend', capture_output=True, text=True)
            if model_check.returncode:
                if 'libomp' in model_check.stderr:
                    raise StartupError('LightGBM needs OpenMP on macOS. Run brew install libomp, then ./dev --ml. See docs/STARTUP.md.')
                raise StartupError('ML artifacts/dependencies failed validation. Run ./dev --setup --ml; check data/forecast-serving.md and any PRICE_MODEL_DIR override.')
        env = aws_environment(args.profile, args.region)
        if args.login:
            run(['aws', 'login', '--region', args.region, '--profile', args.profile], env=env)
        check_credentials(args.profile, args.region, env)
        if args.check:
            print('Dependency and credential checks passed. No servers started.')
            return 0
        LOGS.mkdir(exist_ok=True)
        backend_env = env.copy()
        for key in ('COMPUTE_MARKET_FILE', 'COMPUTE_ORIGIN_UTC'):
            backend_env.pop(key, None)
        backend_env.update(COMPUTE_MARKET_SOURCE='aws', COMPUTE_AWS_REGIONS=args.region,
                           COMPUTE_AWS_INSTANCE_TYPES='g4dn.xlarge,g5.xlarge',
                           COMPUTE_TICK_SECONDS='2', COMPUTE_ALLOW_LOCAL_DISPATCH='0')
        backend_env['COMPUTE_ENABLE_ML'] = '1' if args.ml else '0'
        backend_env.setdefault('COMPUTE_WAITING_POLICY', 'CAUTIOUS')
        frontend_env = env.copy()
        frontend_env.update(API_PROXY_TARGET='http://127.0.0.1:8000',
                            NEXT_PUBLIC_API_BASE_URL='', NEXT_PUBLIC_USE_MOCKS='false')
        for name, command, directory, child_env in [
            ('backend', [python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], ROOT / 'backend', backend_env),
            ('frontend', ['npm', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000'], ROOT / 'frontend', frontend_env),
        ]:
            handle = (LOGS / f'{name}.log').open('w')
            handles.append(handle)
            proc = subprocess.Popen(command, cwd=directory, env=child_env,
                                    stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append((name, proc))
            print(f'Starting {name}; log: .arbitr/{name}.log', flush=True)
        wait_ready(processes)
        print('Waiting for authenticated AWS prices and the frontend proxy…', flush=True)
        deadline = time.monotonic() + 120
        last_codes = []
        while time.monotonic() < deadline:
            check_processes(processes)
            try:
                cap = read_json('http://127.0.0.1:3000/api/capabilities')
                quotes = read_json('http://127.0.0.1:3000/api/market/aws/spot')
                last_codes = sorted({str(e.get('code', 'UNKNOWN')) for d in (cap, quotes) for e in d.get('errors', [])})
                if live_ready(cap, quotes, args.region):
                    if args.ml:
                        status = read_json('http://127.0.0.1:3000/api/models/status')
                        history = status.get('history') or {}
                        if not status.get('engineEnabled') or history.get('status') != 'READY':
                            last_codes = sorted({p.get('errorCode') for p in history.get('pools', []) if p.get('errorCode')}) or ['MODEL_HISTORY_INCOMPLETE']
                            time.sleep(1)
                            continue
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise StartupError('Live AWS readiness timed out. Error codes: '
                               + (', '.join(last_codes) or 'no ready quotes received')
                               + '. Check .arbitr/backend.log and docs/STARTUP.md; no preview fallback was used.')
        print('\nArbitr ready: http://127.0.0.1:3000\nSelect Backend data → Market.\n'
              'Live prices; check forecast mode in the app; AWS capacity unknown.\n'
              + ('ML historical inputs ready.\n' if args.ml else '') +
              'Ctrl+C stops both servers. Logs: .arbitr/backend.log and .arbitr/frontend.log', flush=True)
        while True:
            check_processes(processes)
            time.sleep(1)
    except (StartupError, OSError) as exc:
        print(f'\nStartup failed: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nStopping Arbitr…', flush=True)
        return 0
    finally:
        stop_processes(processes)
        for handle in handles:
            handle.close()


def interrupted(*_):
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
