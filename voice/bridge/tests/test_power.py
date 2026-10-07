import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from voice_bridge.audio import AudioSink, AudioBuffer
from voice_bridge.cli import _run, run
from voice_bridge.transport import TcpLink
from voice_bridge.protocol import STATUS, PCM
import json


class PowerTests(unittest.TestCase):
    def test_wifi_reconnects_after_idle_and_uses_last_address_first(self):
        args = SimpleNamespace(serial=None, host='192.0.2.1', discover=True)
        attempts = []
        retry_modes = []
        def attempt(_args, **kwargs):
            attempts.append(_args.discover)
            retry_modes.append(getattr(_args, '_reconnecting', False))
            if len(attempts) <= 5:
                raise ConnectionError('asleep')
            return 0
        with patch('voice_bridge.cli._run', side_effect=attempt), patch(
                'voice_bridge.cli.time.sleep') as pause:
            self.assertEqual(run(args), 0)
        self.assertEqual(attempts, [True, False, True, False, True, False])
        self.assertEqual(retry_modes, [False, True, True, True, True, True])
        self.assertEqual([call.args[0] for call in pause.call_args_list], [1, 1, 1, 1, 1])

    def test_wifi_does_not_retry_bad_credentials(self):
        args = SimpleNamespace(serial=None, host='192.0.2.1', discover=False)
        with patch('voice_bridge.cli._run', side_effect=PermissionError('bad token')) as attempt, patch(
                'voice_bridge.cli.time.sleep') as pause:
            with self.assertRaises(PermissionError):
                run(args)
        attempt.assert_called_once()
        pause.assert_not_called()

    def test_usb_disconnect_keeps_existing_exit_behavior(self):
        args = SimpleNamespace(serial='test')
        with patch('voice_bridge.cli._run', side_effect=ConnectionError('unplugged')) as attempt:
            with self.assertRaises(ConnectionError):
                run(args)
        attempt.assert_called_once()

    def test_stop_during_wifi_reconnect_wait_exits(self):
        args = SimpleNamespace(serial=None, host='192.0.2.1')
        with patch('voice_bridge.cli._run', side_effect=TimeoutError('offline')), patch(
                'voice_bridge.cli.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run(args)

    def test_network_unreachable_is_a_connection_error(self):
        with patch('voice_bridge.transport.socket.create_connection', side_effect=OSError('network down')):
            with self.assertRaisesRegex(ConnectionError, 'Wi-Fi connection failed'):
                TcpLink('192.0.2.1')

    def test_sleeping_device_does_not_open_audio_on_reconnect_attempts(self):
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='Passport Mic', serial=None)
        with patch('voice_bridge.cli.open_session', side_effect=ConnectionError('asleep')), \
             patch('voice_bridge.audio.AudioSink') as sink, patch('voice_bridge.cli.InputSwitcher') as switcher:
            with self.assertRaisesRegex(ConnectionError, 'asleep'):
                _run(args)
        sink.assert_not_called()
        switcher.assert_not_called()

    def test_audio_startup_failure_closes_authenticated_connection(self):
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='', serial=None)
        session = Mock()
        session.request.return_value = {'transport': 'wifi'}
        with patch('voice_bridge.cli.open_session', return_value=session), patch(
                'voice_bridge.audio.AudioSink', side_effect=RuntimeError('output unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'output unavailable'):
                _run(args)
        session.send.assert_called_once_with('ready', active=False)
        session.link.close.assert_called_once()

    def test_partial_connection_failure_closes_socket(self):
        channel = Mock()
        channel.setsockopt.side_effect = OSError('network down')
        with patch('voice_bridge.transport.socket.create_connection', return_value=channel):
            with self.assertRaises(ConnectionError):
                TcpLink('192.0.2.1')
        channel.close.assert_called_once()

    def test_network_io_errors_allow_reconnect(self):
        link = TcpLink.__new__(TcpLink)
        link.socket = Mock()
        link.socket.recv.side_effect = OSError('network down')
        link.socket.sendall.side_effect = OSError('network down')
        with self.assertRaises(ConnectionError):
            link.read()
        with self.assertRaises(ConnectionError):
            link.write(b'test')

    def sink(self):
        sink = AudioSink.__new__(AudioSink)
        sink.stream = Mock(active=False)
        sink.stream.start.side_effect = lambda: setattr(sink.stream, 'active', True)
        sink.stream.stop.side_effect = lambda: setattr(sink.stream, 'active', False)
        sink.buffer = AudioBuffer()
        return sink

    def test_idle_stops_callbacks_and_clears_audio_before_restart(self):
        sink = self.sink()
        sink.set_active(False)
        sink.stream.start.assert_not_called()
        sink.buffer.push(1, bytes(640))
        sink.set_active(True)
        self.assertEqual(len(sink.buffer.chunks), 0)
        sink.set_active(True)
        self.assertEqual(sink.stream.start.call_count, 1)
        sink.buffer.push(2, bytes(640))
        sink.set_active(False)
        sink.set_active(False)
        self.assertEqual(sink.stream.stop.call_count, 1)
        self.assertEqual(len(sink.buffer.chunks), 0)
        sink.set_active(True)
        self.assertEqual(sink.stream.start.call_count, 2)
        sink.close()
        sink.stream.close.assert_called_once()

    def test_bridge_survives_idle_then_audio_and_disconnect(self):
        sink = self.sink()
        session = Mock()
        session.request.return_value = {'transport': 'usb'}
        def status(active):
            return SimpleNamespace(kind=STATUS, payload=json.dumps({
                'transport': 'usb', 'rate': 16000, 'channels': 1, 'bits': 16,
                'audio': active, 'mic': active}).encode())
        session.receive.side_effect = [
            [status(False)], [status(True), SimpleNamespace(kind=PCM, sequence=1, payload=bytes(640))],
            [status(False)], ConnectionError('unplugged')]
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='', serial='test')
        with patch('voice_bridge.audio.AudioSink', return_value=sink), \
             patch('voice_bridge.cli.open_session', return_value=session), \
             patch('voice_bridge.cli.Injector'), patch('voice_bridge.cli.trusted', return_value=True):
            with self.assertRaisesRegex(ConnectionError, 'unplugged'):
                _run(args)
        sink.stream.start.assert_called_once()
        sink.stream.stop.assert_called_once()
        sink.stream.close.assert_called_once()
        session.link.close.assert_called_once()

    def test_sink_closes_even_if_transport_cleanup_fails(self):
        sink = self.sink()
        session = Mock()
        session.request.return_value = {'transport': 'usb'}
        session.link.close.side_effect = OSError('close failed')
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='', serial='test')
        with patch('voice_bridge.audio.AudioSink', return_value=sink), \
             patch('voice_bridge.cli.open_session', return_value=session), \
             patch('voice_bridge.cli.Injector'), patch('voice_bridge.cli.trusted', return_value=True):
            with self.assertRaisesRegex(OSError, 'close failed'):
                _run(args)
        sink.stream.close.assert_called_once()

    def test_input_selection_failure_retries_on_the_next_status(self):
        sink = self.sink()
        session = Mock()
        session.request.return_value = {'transport': 'usb'}
        frame = SimpleNamespace(kind=STATUS, payload=json.dumps({
            'transport': 'usb', 'rate': 16000, 'channels': 1, 'bits': 16,
            'audio': False, 'mic': True}).encode())
        session.receive.side_effect = [[frame], [frame], ConnectionError('unplugged')]
        switcher = Mock(name='Passport Mic')
        switcher.set.side_effect = [RuntimeError('temporarily unavailable'), True, True]
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='Passport Mic', serial='test')
        with patch('voice_bridge.audio.AudioSink', return_value=sink), \
             patch('voice_bridge.cli.open_session', return_value=session), \
             patch('voice_bridge.cli.InputSwitcher', return_value=switcher), \
             patch('voice_bridge.cli.Injector'), patch('voice_bridge.cli.trusted', return_value=True):
            with self.assertRaises(ConnectionError):
                _run(args)
        self.assertEqual([call.args for call in switcher.set.call_args_list], [(True,), (True,), (False,)])
