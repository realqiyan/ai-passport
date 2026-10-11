"""Exercise automatic selection and stop handling without devices or audio."""
import contextlib
import io
import json
from pathlib import Path
import signal
import select
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voice_bridge.automatic import AutoSelector, can_switch_to_usb, usb_ports
from voice_bridge.cli import (SwitchToUSB, TerminationRequested, _run, execute,
                              graceful_termination, run)
from voice_bridge.log import log, persistent_log
from voice_bridge.protocol import STATUS
from voice_bridge.transport import SerialLink


class AutomaticTests(unittest.TestCase):
    def test_only_native_usb_candidates_are_enumerated_without_opening(self):
        ports = [SimpleNamespace(device='/dev/cu.passport', vid=0x303a, pid=0x1001),
                 SimpleNamespace(device='/dev/cu.other', vid=0x1234, pid=0x1001),
                 SimpleNamespace(device='/dev/cu.unknown', vid=None, pid=None)]
        serial = Mock()
        serial.tools.list_ports.comports.return_value = ports
        with patch.dict('sys.modules', {'serial': serial, 'serial.tools': serial.tools}):
            self.assertEqual(usb_ports(), ['/dev/cu.passport'])
        serial.Serial.assert_not_called()

    def test_usb_cooldown_and_reinsertion(self):
        selector = AutoSelector()
        with patch('voice_bridge.automatic.usb_ports', return_value=['usb']) as ports, \
                patch('voice_bridge.automatic.time.monotonic', return_value=10) as clock:
            self.assertEqual(selector.usb(), 'usb')
            selector.failed('usb')
            clock.return_value = 39
            self.assertIsNone(selector.usb())
            clock.return_value = 40
            self.assertEqual(selector.usb(), 'usb')
            selector.failed('usb')
            ports.return_value = []
            self.assertIsNone(selector.usb())
            ports.return_value = ['usb']
            self.assertEqual(selector.usb(), 'usb')

    def test_multiple_usb_devices_are_not_probed(self):
        with patch('voice_bridge.automatic.usb_ports', return_value=['usb-a', 'usb-b']):
            self.assertIsNone(AutoSelector().usb())

    def test_temporary_usb_enumeration_failure_allows_wifi(self):
        with patch('voice_bridge.automatic.usb_ports', side_effect=OSError('USB unavailable')):
            self.assertIsNone(AutoSelector().usb())

    def test_recording_and_incomplete_status_prevent_switching(self):
        idle = {'mic': False, 'audio': False, 'recording': False}
        self.assertTrue(can_switch_to_usb(idle, None))
        self.assertFalse(can_switch_to_usb(idle, 1))
        self.assertFalse(can_switch_to_usb({}, None))
        for field in idle:
            self.assertFalse(can_switch_to_usb({**idle, field: True}, None))
            missing = dict(idle)
            del missing[field]
            self.assertFalse(can_switch_to_usb(missing, None))

    def test_usb_is_tried_before_wifi_and_failure_falls_back(self):
        args = SimpleNamespace(auto=True, serial=None, host=None, discover=True, token_file=Path('token'))
        selector = Mock()
        selector.usb.side_effect = ['usb', None]
        transports = []
        def attempt(args, **kwargs):
            transports.append(args.serial)
            if args.serial:
                raise ConnectionError('unplugged')
            return 0
        with patch('voice_bridge.cli.AutoSelector', return_value=selector), \
                patch('voice_bridge.cli._run', side_effect=attempt), \
                patch('voice_bridge.cli.read_token', return_value='a' * 64) as token, \
                patch('voice_bridge.cli.time.sleep'):
            self.assertEqual(run(args), 0)
        self.assertEqual(transports, ['usb', None])
        selector.failed.assert_called_once_with('usb')
        token.assert_called_once()

    def test_missing_wifi_token_does_not_prevent_later_usb_connection(self):
        args = SimpleNamespace(auto=True, serial=None, host=None, discover=True, token_file=Path('missing'))
        selector = Mock()
        selector.usb.side_effect = [None, 'usb']
        with patch('voice_bridge.cli.AutoSelector', return_value=selector), \
                patch('voice_bridge.cli.read_token', side_effect=RuntimeError('missing token')), \
                patch('voice_bridge.cli._run', return_value=0) as attempt, \
                patch('voice_bridge.cli.time.sleep'):
            self.assertEqual(run(args), 0)
        attempt.assert_called_once()
        self.assertEqual(args.serial, 'usb')

    def test_wifi_authentication_failure_keeps_auto_waiting_for_usb(self):
        args = SimpleNamespace(auto=True, serial=None, host=None, discover=True, token_file=Path('token'))
        selector = Mock()
        selector.usb.side_effect = [None, 'usb']
        with patch('voice_bridge.cli.AutoSelector', return_value=selector), \
                patch('voice_bridge.cli.read_token', return_value='a' * 64), \
                patch('voice_bridge.cli._run', side_effect=[PermissionError('bad token'), 0]) as attempt, \
                patch('voice_bridge.cli.time.sleep'):
            self.assertEqual(run(args), 0)
        self.assertEqual(attempt.call_count, 2)

    def test_transport_negotiation_discards_old_frames_before_ready(self):
        session = Mock(pending=['old wifi status'])
        session.request.side_effect = [
            {'transport': 'wifi', 'auto_transport': True},
            {'transport': 'usb', 'auto_transport': True}, {}]
        session.receive.side_effect = KeyboardInterrupt
        args = SimpleNamespace(auto=True, serial='usb', output='test', mic_device='')
        with patch('voice_bridge.cli.open_session', return_value=session), \
                patch('voice_bridge.audio.AudioSink'), patch('voice_bridge.cli.Injector'), \
                patch('voice_bridge.cli.trusted', return_value=True):
            with self.assertRaises(KeyboardInterrupt):
                _run(args)
        self.assertEqual(session.pending, [])
        self.assertEqual([call.args[0] for call in session.request.call_args_list],
                         ['status', 'transport', 'ready'])
        self.assertEqual(session.request.call_args_list[1].kwargs,
                         {'mode': 'usb', 'automatic': True})
        session.link.close.assert_called_once()

    def test_busy_firmware_does_not_start_audio_or_claim_ready(self):
        session = Mock()
        session.request.side_effect = [{'transport': 'wifi', 'auto_transport': True},
                                       RuntimeError('transport busy')]
        args = SimpleNamespace(auto=True, serial='usb', output='test', mic_device='')
        with patch('voice_bridge.cli.open_session', return_value=session), \
                patch('voice_bridge.audio.AudioSink') as sink:
            with self.assertRaisesRegex(ConnectionError, 'transport busy'):
                _run(args)
        sink.assert_not_called()
        self.assertNotIn('ready', [call.args[0] for call in session.request.call_args_list])

    def test_wifi_recording_finishes_before_usb_is_probed(self):
        session, selector = Mock(), Mock()
        session.request.return_value = {'transport': 'wifi'}
        checked = []
        idle = {'transport': 'wifi', 'rate': 16000, 'channels': 1, 'bits': 16,
                'mic': False, 'audio': False, 'recording': False}
        statuses = [{**idle, 'mic': True, 'recording': True}, idle]
        def receive():
            status = statuses.pop(0)
            checked.append(status['recording'])
            return [SimpleNamespace(kind=STATUS, payload=json.dumps(status).encode())]
        session.receive.side_effect = receive
        selector.usb.side_effect = lambda: self.assertEqual(checked, [True, False]) or 'usb'
        clock = iter(range(100))
        args = SimpleNamespace(serial=None, host='test', output='test', mic_device='', _selector=selector)
        with patch('voice_bridge.cli.open_session', return_value=session), \
                patch('voice_bridge.audio.AudioSink'), patch('voice_bridge.cli.Injector'), \
                patch('voice_bridge.cli.trusted', return_value=True), \
                patch('voice_bridge.cli.time.monotonic', side_effect=lambda: next(clock)):
            with self.assertRaises(SwitchToUSB):
                _run(args)
        selector.usb.assert_called_once()
        session.link.close.assert_called_once()

    def test_serial_unplug_is_recoverable(self):
        link = SerialLink.__new__(SerialLink)
        link.serial = Mock(in_waiting=1)
        link.serial.read.side_effect = OSError('removed')
        link.serial.write.side_effect = OSError('removed')
        with self.assertRaises(ConnectionError):
            link.read()
        with self.assertRaises(ConnectionError):
            link.write(b'hello')


class TerminationTests(unittest.TestCase):
    def test_real_hangup_keeps_process_alive_and_term_reports_reason(self):
        code = '''
import sys, time
from types import SimpleNamespace
from unittest.mock import patch
from voice_bridge.cli import execute
def wait(args, **kwargs):
    print('ready', flush=True)
    try:
        while True:
            time.sleep(0.01)
    finally:
        print('cleanup ran', flush=True)
with patch('voice_bridge.cli._run', side_effect=wait):
    sys.exit(execute(SimpleNamespace(command='run', serial=None, discover=False)))
'''
        process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 3)[0])
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            process.send_signal(signal.SIGHUP)
            time.sleep(0.05)
            self.assertIsNone(process.poll())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 143)
            self.assertIn('cleanup ran', stdout)
            self.assertIn('SIGTERM (15)', stderr)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)

    def test_hangup_is_ignored_and_handlers_are_restored(self):
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        with graceful_termination():
            self.assertEqual(signal.getsignal(signal.SIGHUP), signal.SIG_IGN)
            for sig in (signal.SIGINT, signal.SIGTERM):
                with self.assertRaises(TerminationRequested) as caught:
                    signal.getsignal(sig)(sig, None)
                self.assertEqual(caught.exception.signum, sig)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})

    def test_stop_signal_has_a_specific_log_and_exit_code(self):
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGINT, 0)):
            stderr = io.StringIO()
            with patch('voice_bridge.cli.run', side_effect=TerminationRequested(sig)), \
                    contextlib.redirect_stderr(stderr):
                self.assertEqual(execute(SimpleNamespace(command='run')), code)
            self.assertIn(signal.Signals(sig).name, stderr.getvalue())
            self.assertIn('PID=', stderr.getvalue())

    def test_lost_terminal_does_not_stop_persistent_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.log'
            stream = Mock()
            stream.write.side_effect = BrokenPipeError('terminal closed')
            with persistent_log(path):
                log('bridge still running', file=stream)
            self.assertIn('bridge still running', path.read_text())

    def test_log_rotation_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.log'
            with persistent_log(path), contextlib.redirect_stdout(io.StringIO()):
                for _ in range(5):
                    log('x' * 600000)
            self.assertLessEqual(len(list(Path(directory).glob('bridge.log*'))), 3)
            self.assertTrue(all(p.stat().st_size < 1024 * 1024 for p in Path(directory).iterdir()))
