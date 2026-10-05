"""Check migration, audio cleanup and process ownership with fixed data."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from voice_bridge import lifecycle, microphone, state


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = self.root / 'old', self.root / 'new'
        self.old.mkdir()

    def test_default_directory_does_not_depend_on_package_location(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(state.sys, 'platform', 'darwin'), patch.object(state.Path, 'home', return_value=self.root):
            self.assertEqual(state.directory(), self.root / 'Library/Application Support/passport-voice')

    def test_explicit_directory_is_resolved(self):
        with patch.dict(os.environ, {'PASSPORT_VOICE_STATE_DIR': str(self.new)}):
            self.assertEqual(state.directory(), self.new.resolve())

    def test_migration_keeps_backup_and_token_permissions(self):
        (self.old / 'token').write_text('a' * 64 + '\n')
        (self.old / 'host').write_text('192.0.2.1\n')
        for _ in range(2):
            state.migrate(self.new, self.old)
        self.assertEqual((self.new / 'token').read_bytes(), (self.old / 'token').read_bytes())
        self.assertEqual((self.new / 'token').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.new / 'host').read_text(), '192.0.2.1\n')

    def test_token_conflict_is_checked_before_copying_any_file(self):
        (self.old / 'token').write_text('a' * 64)
        (self.old / 'host').write_text('192.0.2.1')
        self.new.mkdir()
        (self.new / 'token').write_text('b' * 64)
        with self.assertRaisesRegex(RuntimeError, 'State conflict'):
            state.migrate(self.new, self.old)
        self.assertFalse((self.new / 'host').exists())
        self.assertEqual((self.new / 'token').read_text(), 'b' * 64)

    def test_updated_address_cache_does_not_break_repeat_setup(self):
        (self.old / 'token').write_text('a' * 64)
        (self.old / 'host').write_text('192.0.2.1')
        state.migrate(self.new, self.old)
        (self.new / 'host').write_text('192.0.2.2')
        state.migrate(self.new, self.old)
        self.assertEqual((self.new / 'host').read_text(), '192.0.2.2')

    def test_invalid_legacy_token_stops_migration(self):
        (self.old / 'token').write_text('invalid')
        with self.assertRaisesRegex(ValueError, 'Invalid legacy token'):
            state.migrate(self.new, self.old)
        self.assertFalse(self.new.exists())


class ProcessTests(unittest.TestCase):
    def test_alias_module_legacy_and_other_installations(self):
        python = '/pipx env/bin/python'
        legacy = Path('/checkout with spaces/voice/.local')
        listing = '\n'.join([
            '101 /pipx env/bin/python /user bin/passport-voice wifi --output test',
            '102 /pipx env/bin/python -m voice_bridge.cli usb /dev/test',
            '103 /other/bin/python /other/bin/passport-voice run --host test',
            '104 /checkout with spaces/voice/bridge/.venv/bin/python /checkout with spaces/voice/bridge/.venv/bin/passport-voice run --serial test',
            '105 /other/bin/python -m voice_bridge.cli wifi',
            '106 /other/bin/python /other/bin/passport-voice cleanup --yes',
            '107 /other/bin/python /other/bin/passport-voice-helper run',
            '108 /pipx env/bin/python -c print("passport-voice wifi")',
            '109 /bin/bash -c echo passport-voice run',
        ])
        with patch.object(lifecycle.sys, 'executable', python), patch.object(lifecycle.sys, 'argv', ['/pipx env/bin/passport-voice']), patch.object(lifecycle.subprocess, 'run', return_value=Mock(stdout=listing)):
            self.assertEqual(lifecycle.bridge_processes(legacy), ({101, 102, 104}, {103, 105}))

    def test_relative_legacy_directory_recognizes_module_and_python_alias(self):
        legacy = Path('legacy voice/.local')
        python = legacy.absolute().parent / 'bridge/.venv/bin/python3.13'
        with patch.object(lifecycle.subprocess, 'run', return_value=Mock(stdout=f'101 {python} -m voice_bridge.cli run --serial test')):
            self.assertEqual(lifecycle.bridge_processes(legacy), ({101}, set()))

    def test_process_query_failure_is_not_treated_as_no_processes(self):
        with patch.object(lifecycle.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ps')):
            with self.assertRaises(subprocess.CalledProcessError):
                lifecycle.bridge_processes()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved, self.old = self.root / 'saved', self.root / 'old'
        for directory in (self.saved, self.old):
            directory.mkdir()
            (directory / 'token').write_text('a' * 64)
        self.hal = Mock()
        self.hal.find.side_effect = lambda name: 2 if name == microphone.SUBDEVICE else 3
        self.hal.uid.return_value = microphone.DEFAULT_UID
        self.hal.default_input.return_value = 1
        for target, value in [('require_macos', Mock()), ('CoreAudio', Mock(return_value=self.hal)),
                              ('bridge_processes', Mock(return_value=(set(), set()))),
                              ('microphone', Mock(wraps=microphone))]:
            patcher = patch.object(lifecycle, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('DEFAULT_NAME', 'DEFAULT_UID', 'SUBDEVICE'):
            setattr(lifecycle.microphone, name, getattr(microphone, name))
        lifecycle.microphone.describe.return_value = ['Passport Mic: present', 'Default input: Built-in']
        lifecycle.microphone.AggregateHal = Mock()
        lifecycle.microphone.remove = Mock()
        lifecycle.microphone.create = Mock()

    def test_setup_reuses_device_and_migrates_legacy_files(self):
        (self.saved / 'token').unlink()
        lifecycle.setup(self.saved, self.old)
        lifecycle.microphone.create.assert_not_called()
        self.assertTrue((self.saved / 'token').exists())

    def test_setup_creates_missing_aggregate(self):
        self.hal.find.side_effect = lambda name: 2 if name == microphone.SUBDEVICE else None
        lifecycle.setup(self.saved, self.old)
        lifecycle.microphone.create.assert_called_once()

    def test_setup_requires_loaded_blackhole(self):
        self.hal.find.return_value = None
        self.hal.find.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'BlackHole'):
            lifecycle.setup(self.saved, self.old)
        lifecycle.microphone.create.assert_not_called()

    def test_cleanup_cancel_preserves_state(self):
        with patch('builtins.input', return_value='no'):
            lifecycle.cleanup(self.saved, self.old)
        lifecycle.microphone.remove.assert_not_called()
        self.assertTrue((self.saved / 'token').exists())

    def test_cleanup_failure_preserves_state(self):
        lifecycle.microphone.remove.side_effect = RuntimeError('audio failure')
        with self.assertRaisesRegex(RuntimeError, 'audio failure'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        self.assertTrue((self.saved / 'token').exists())
        self.assertTrue((self.old / 'token').exists())

    def test_cleanup_stops_owned_bridge_before_removing_audio(self):
        lifecycle.bridge_processes.side_effect = [({101}, set()), (set(), set())]
        events = []
        lifecycle.microphone.remove.side_effect = lambda *args: events.append('remove')
        with patch.object(lifecycle.os, 'kill', side_effect=lambda *args: events.append(('stop', *args))):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        self.assertEqual(events, [('stop', 101, signal.SIGTERM), 'remove'])
        self.assertFalse((self.saved / 'token').exists())
        self.assertFalse((self.old / 'token').exists())

    def test_other_bridge_stops_cleanup_before_any_change(self):
        lifecycle.bridge_processes.return_value = ({101}, {202})
        with patch.object(lifecycle.os, 'kill') as kill, self.assertRaisesRegex(RuntimeError, 'Another installation'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        kill.assert_not_called()
        lifecycle.microphone.remove.assert_not_called()
        self.assertTrue((self.saved / 'token').exists())

    def test_cleanup_rechecks_default_input_after_stopping(self):
        lifecycle.bridge_processes.side_effect = [({101}, set()), (set(), set())]
        self.hal.default_input.return_value = 3
        lifecycle.microphone.remove = microphone.remove
        with patch.object(lifecycle.os, 'kill'), self.assertRaisesRegex(RuntimeError, 'default input'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        self.assertTrue((self.saved / 'token').exists())

    def test_cleanup_rejects_an_unrelated_device(self):
        self.hal.uid.return_value = 'other-uid'
        with self.assertRaisesRegex(RuntimeError, 'unrelated UID'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        lifecycle.microphone.remove.assert_not_called()

    def test_bridge_stop_timeout_preserves_state(self):
        lifecycle.bridge_processes.return_value = ({101}, set())
        with patch.object(lifecycle.os, 'kill'), patch.object(lifecycle.time, 'monotonic', side_effect=[0, 11]), self.assertRaisesRegex(RuntimeError, 'did not stop'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        lifecycle.microphone.remove.assert_not_called()
        self.assertTrue((self.saved / 'token').exists())

    def test_new_foreign_bridge_preserves_state_after_termination(self):
        lifecycle.bridge_processes.side_effect = [({101}, set()), (set(), {202})]
        with patch.object(lifecycle.os, 'kill'), self.assertRaisesRegex(RuntimeError, 'Another bridge started'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        lifecycle.microphone.remove.assert_not_called()
        self.assertTrue((self.saved / 'token').exists())

    def test_cleanup_without_an_aggregate_still_removes_known_state(self):
        self.hal.find.side_effect = lambda name: 2 if name == microphone.SUBDEVICE else None
        lifecycle.cleanup(self.saved, self.old, yes=True)
        lifecycle.microphone.AggregateHal.assert_not_called()
        self.assertFalse((self.saved / 'token').exists())

    def test_audio_query_failure_preserves_state(self):
        lifecycle.microphone.describe.side_effect = RuntimeError('query failed')
        with self.assertRaisesRegex(RuntimeError, 'query failed'):
            lifecycle.cleanup(self.saved, self.old, yes=True)
        self.assertTrue((self.saved / 'token').exists())

    def test_cleanup_keeps_unknown_files(self):
        (self.saved / 'notes').write_text('keep')
        lifecycle.cleanup(self.saved, self.old, yes=True)
        self.assertEqual((self.saved / 'notes').read_text(), 'keep')
        self.assertFalse((self.saved / 'token').exists())
