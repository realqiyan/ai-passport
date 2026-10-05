import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch
from voice_bridge.cli import _run, main
from voice_bridge.protocol import STATUS


def event(ending=False, session=7):
    return SimpleNamespace(kind=STATUS, payload=json.dumps({
        'event': 'shortcut', 'temporary': True, 'session': session,
        'ending': ending, 'modifiers': 3, 'key': 25}).encode())


class TemporaryTests(unittest.TestCase):
    def run_events(self, frames, *, trusted=True, shortcut=None):
        sink, session, injector, switcher = Mock(), Mock(), Mock(), Mock()
        session.request.return_value = {'transport': 'usb'}
        session.receive.side_effect = [[frame] for frame in frames] + [ConnectionError('finished')]
        args = SimpleNamespace(output='BlackHole 2ch', mic_device='Passport Mic',
                               serial='test', shortcut=shortcut)
        order = Mock()
        order.attach_mock(switcher.set, 'select')
        order.attach_mock(injector.send, 'press')
        with patch('voice_bridge.audio.AudioSink', return_value=sink), \
             patch('voice_bridge.cli.open_session', return_value=session), \
             patch('voice_bridge.cli.InputSwitcher', return_value=switcher), \
             patch('voice_bridge.cli.Injector', return_value=injector), \
             patch('voice_bridge.cli.trusted', return_value=trusted):
            with self.assertRaisesRegex(ConnectionError, 'finished'):
                _run(args)
        return session, injector, order

    def test_confirm_start_selects_input_before_shortcut_and_confirm_stop_toggles(self):
        session, injector, order = self.run_events([event(), event(ending=True)])
        self.assertEqual(order.mock_calls[:2], [call.select(True), call.press(3, 25)])
        self.assertEqual(injector.send.call_args_list, [call(3, 25), call(3, 25)])
        self.assertEqual(order.mock_calls[-1], call.select(False))

    def test_end_without_a_successful_start_does_not_open_dictation(self):
        session, injector, _ = self.run_events([event(ending=True)])
        injector.send.assert_not_called()

    def test_old_session_end_does_not_toggle_the_new_input(self):
        session, injector, _ = self.run_events([event(session=8), event(ending=True, session=7)])
        injector.send.assert_called_once_with(3, 25)

    def test_permission_failure_closes_only_the_temporary_session(self):
        session, injector, _ = self.run_events([event()], trusted=False)
        injector.send.assert_not_called()
        self.assertIn(call('stop', session=7), session.send.call_args_list)

    def test_configured_run_shortcut_overrides_both_start_and_end(self):
        _, injector, _ = self.run_events([event(), event(ending=True)], shortcut=(5, 44))
        self.assertEqual(injector.send.call_args_list, [call(5, 44), call(5, 44)])

    def test_cli_accepts_shortcut_option(self):
        with patch('voice_bridge.cli.run') as run:
            self.assertEqual(main(['run', '--serial', 'test', '--shortcut', 'cmd+shift+space']), 0)
        self.assertEqual(run.call_args.args[0].shortcut, (10, 44))
