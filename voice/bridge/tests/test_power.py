import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from voice_bridge.audio import AudioSink, AudioBuffer
from voice_bridge.cli import _run
from voice_bridge.protocol import STATUS, PCM
import json


class PowerTests(unittest.TestCase):
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
        session.request.return_value = {'transport': 'wifi'}
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
