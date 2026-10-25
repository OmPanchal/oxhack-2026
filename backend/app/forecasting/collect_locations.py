"""Read-only regional exports with bounded uncompressed storage and receipts."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from app.forecasting.collect_expanded import collect_expanded, validate_config
from app.forecasting.collect_spot import stamp, utc


def write_json(path, value):
    pending=path.with_suffix('.pending.json')
    pending.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
    pending.replace(path)


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def archive_tree(directory, destination, *, compressed=True):
    """Archive only a new run's own regular files; commit after CRC verification."""
    if destination.exists():
        raise ValueError('Archive already exists; choose a new output name')
    pending=destination.with_name(destination.name+'.pending')
    with ZipFile(pending,'x',compression=ZIP_DEFLATED if compressed else ZIP_STORED) as archive:
        for file in sorted(directory.rglob('*')):
            if file.is_symlink():
                raise ValueError('Refusing symlinks in an export')
            if file.is_file():
                archive.write(file,Path(directory.name)/file.relative_to(directory))
    with ZipFile(pending) as archive:
        if archive.testzip() is not None:
            raise OSError('Archive CRC verification failed')
    pending.replace(destination)


def collect_locations(client_factory, config, output, *, end=None, retrieved_at=None, work_directory=None):
    validate_config(config)
    output=Path(output)
    archive_path=Path(str(output)+'.zip')
    if output.exists() or archive_path.exists():
        raise ValueError('Output exists; choose a fresh run name')
    now=utc(retrieved_at or datetime.now(timezone.utc))
    end=utc(end) if end is not None else now.replace(minute=0,second=0,microsecond=0)
    # The underlying collector validates the same fixed end/window for every region.
    from datetime import timedelta
    if end.minute or end.second or end.microsecond or not now-timedelta(days=90)<=end-timedelta(days=config['days'])<end<=now:
        raise ValueError('Collection needs an hourly UTC window within the preceding 90 days')
    output.mkdir(parents=True,exist_ok=False)
    receipt=dict(schemaVersion='multi-region-spot-export-v1',status='COLLECTING',
        startTime=stamp(end-timedelta(days=config['days'])),endTime=stamp(end),retrievedAt=stamp(now),
        requestedRegions=config['regions'],requestedInstanceTypes=config['instanceTypes'],regions=[],
        dataKind='OBSERVED',hasCapacityObservations=False,
        limitations=['Offerings and price history do not establish free capacity or interruption risk.',
                     'Denied/not-offered/empty pools are exclusions, not observed zero prices.',
                     'Each regional ZIP contains a standard expanded-collector export.'])
    write_json(output/'requested-config.json',config)
    write_json(output/'receipt.json',receipt)
    for region in config['regions']:
        try:
            # Only one region is expanded on disk. Completed regional ZIPs persist.
            with TemporaryDirectory(prefix='compute-spot-',dir=work_directory) as temporary:
                directory=Path(temporary)/region
                regional_config=dict(config,regions=[region])
                regional=collect_expanded(client_factory,regional_config,directory,end=end,retrieved_at=now)
                destination=output/f'{region}.zip'
                archive_tree(directory,destination)
                codes=Counter(p['errorCode'] for p in regional['pairs'] if 'errorCode' in p)
                receipt['regions'].append(dict(region=region,status=regional['status'],
                    collectedPairCount=regional['collectedPairCount'],requestedPairCount=regional['requestedPairCount'],
                    priceEventCount=regional['priceEventCount'],errorCodes=dict(codes),
                    archive=destination.name,archiveSha256=checksum(destination)))
            write_json(output/'receipt.json',receipt)
            print(f"REGION {region}: {regional['collectedPairCount']}/{regional['requestedPairCount']} hardware pairs",flush=True)
        except OSError:
            receipt['status']='FILESYSTEM_ERROR'
            write_json(output/'receipt.json',receipt)
            raise
    receipt['regionsWithData']=[r['region'] for r in receipt['regions'] if r['collectedPairCount']]
    receipt['collectedPairCount']=sum(r['collectedPairCount'] for r in receipt['regions'])
    receipt['requestedPairCount']=len(config['regions'])*len(config['instanceTypes'])
    receipt['status']=('NO_DATA' if not receipt['regionsWithData'] else
        'COMPLETE' if all(r['status']=='COMPLETE' for r in receipt['regions']) else 'PARTIAL')
    write_json(output/'receipt.json',receipt)
    archive_tree(output,archive_path,compressed=False)
    return receipt,archive_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--regions',help='Optional comma-separated override, e.g. us-east-1,eu-west-1')
    parser.add_argument('--profile',help='Optional local AWS profile; omit in CloudShell')
    parser.add_argument('--end',help='Optional fixed UTC end hour, e.g. 2026-10-25T00:00:00Z')
    parser.add_argument('--work-directory',type=Path,help='Scratch directory for one uncompressed region')
    args=parser.parse_args()
    try:
        config=json.loads(args.config.read_text())
        if args.regions:
            config['regions']=[r.strip() for r in args.regions.split(',')]
        validate_config(config)
        import boto3
        from botocore.config import Config
        session=boto3.Session(profile_name=args.profile)
        clients={}
        def factory(region):
            if region not in clients:
                clients[region]=session.client('ec2',region_name=region,
                    config=Config(retries={'mode':'standard','max_attempts':4},connect_timeout=10,read_timeout=30))
            return clients[region]
        receipt,archive=collect_locations(factory,config,args.output,end=args.end,work_directory=args.work_directory)
    except ImportError:
        parser.exit(1,'Install boto3 first: python3 -m pip install --user boto3\n')
    except (ValueError,KeyError,OSError) as exc:
        parser.exit(1,f'Collection rejected: {exc}\n')
    print(f"{receipt['status']}: {len(receipt['regionsWithData'])}/{len(config['regions'])} regions have data.")
    print('REGIONS WITH DATA: '+', '.join(receipt['regionsWithData']))
    print('DOWNLOAD THIS FILE: '+str(archive.resolve()))
    print('Check receipt.json and regional receipts for permissions, unsupported types and empty history.')
    if len(receipt['regionsWithData'])<2:
        print('Multi-location coverage was not achieved. Account permission/offerings failures remain in the receipt.')
    if not receipt['regionsWithData']:
        parser.exit(2,'No usable history collected. The archive still contains diagnostic receipts.\n')

if __name__=='__main__':
    main()
