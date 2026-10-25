"""Startup failure and cleanup regressions; no AWS requests or app mutations."""
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

import dev


class StartupTests(unittest.TestCase):
    def test_occupied_port_fails_without_disturbing_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            listener.listen()
            with self.assertRaisesRegex(dev.StartupError, 'already in use'):
                dev.check_ports([port])
            self.assertEqual(listener.getsockname()[1], port)

    def test_auth_failure_has_recovery_and_hides_raw_output(self):
        failure = subprocess.CompletedProcess([], 255, '', 'sensitive diagnostic')
        with patch.object(dev.subprocess, 'run', return_value=failure):
            with self.assertRaises(dev.StartupError) as error:
                dev.check_credentials('arbitr', 'eu-north-1', {})
        self.assertIn('./dev --login', str(error.exception))
        self.assertNotIn('sensitive diagnostic', str(error.exception))

    def test_only_live_matching_region_can_be_ready(self):
        cap = dict(provider='AWS', status='READY', configuredRegions=['eu-north-1'], offerings=[{}])
        quotes = dict(status='READY', quotes=[dict(region='eu-north-1', dataKind='OBSERVED')])
        self.assertTrue(dev.live_ready(cap, quotes, 'eu-north-1'))
        quotes['quotes'][0]['dataKind'] = 'SIMULATED'
        self.assertFalse(dev.live_ready(cap, quotes, 'eu-north-1'))
        quotes['quotes'][0]['dataKind'] = 'OBSERVED'
        self.assertFalse(dev.live_ready(cap, quotes, 'eu-west-1'))
        cap['status'] = 'UNAVAILABLE'
        self.assertFalse(dev.live_ready(cap, quotes, 'eu-north-1'))

    def test_child_failure_is_reported_and_other_owned_child_stops(self):
        running = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        failed = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(7)'], start_new_session=True)
        processes = [('backend', running), ('frontend', failed)]
        try:
            failed.wait(timeout=5)
            with self.assertRaisesRegex(dev.StartupError, r'frontend stopped \(exit 7\)'):
                dev.check_processes(processes)
        finally:
            dev.stop_processes(processes)
        self.assertIsNotNone(running.poll())

    def test_old_shell_credentials_cannot_override_named_profile(self):
        with patch.dict(os.environ, AWS_ACCESS_KEY_ID='old', AWS_SECRET_ACCESS_KEY='old', AWS_SESSION_TOKEN='old'):
            env = dev.aws_environment('arbitr', 'eu-north-1')
        self.assertEqual(env['AWS_PROFILE'], 'arbitr')
        self.assertNotIn('AWS_ACCESS_KEY_ID', env)
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertNotIn('AWS_SESSION_TOKEN', env)


if __name__ == '__main__':
    unittest.main()
