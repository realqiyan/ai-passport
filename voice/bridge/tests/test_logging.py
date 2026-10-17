import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voice_bridge.audio import AudioBuffer
from voice_bridge.cli import RecordingStats, _run, describe_shortcut, idle_heartbeat, main, run
from voice_bridge.log import StatusLogger, format_status, log, timestamp, persistent_log
from voice_bridge.protocol import PCM, STATUS


STAMP = "2026-10-07 08:09:10.123+08:00"
STATUS_SAMPLE = {
    "ack": 17, "result": "ok", "mic": False, "audio": False,
    "bridge": True, "recording": False, "session": 7, "transport": "wifi",
    "ip": "192.0.2.1", "error": 0, "drops": 0, "modifiers": 3, "key": 25,
    "rate": 16000, "channels": 1, "bits": 16, "power_profile": "idle-v2",
    "battery_pct": 50, "battery_mv": 3943, "uptime_s": 120,
    "screen_off": True, "codec_asleep": True, "wifi_idle": False,
    "usb_host": False, "deep_wakes": 2, "sleep_error": 0,
}


def frame(status):
    return SimpleNamespace(kind=STATUS, payload=json.dumps(status).encode())


def pcm(sequence):
    return SimpleNamespace(kind=PCM, sequence=sequence, payload=b"\x00" * 640)


class LoggingTests(unittest.TestCase):
    def test_timestamp_has_milliseconds_and_timezone(self):
        local = datetime(2026, 10, 7, 8, 9, 10, 123456,
                         tzinfo=timezone(timedelta(hours=8)))
        with patch("voice_bridge.log.datetime") as clock:
            clock.now.return_value.astimezone.return_value = local
            self.assertEqual(timestamp(), STAMP)

    def test_every_output_line_is_timestamped_and_flushed(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("voice_bridge.log.timestamp", return_value=STAMP), \
                contextlib.redirect_stdout(stdout):
            log("状态一\n状态二")
            log("错误一\n错误二", file=stderr)
            stream = Mock()
            log("重连成功", file=stream)
        self.assertEqual(stdout.getvalue(), f"[{STAMP}] 状态一\n[{STAMP}] 状态二\n")
        self.assertEqual(stderr.getvalue(), f"[{STAMP}] 错误一\n[{STAMP}] 错误二\n")
        stream.flush.assert_called_once()

    def test_status_keeps_every_firmware_field_in_readable_groups(self):
        expected = (
            "音频与连接 | 麦克风开启=否 | 音频传输=否 | 桥接就绪=是 | 语音输入=否"
            " | 会话=7 | 传输=wifi | IP=192.0.2.1\n"
            "电量与屏幕 | 电量=50% | 电压=3943 mV | 屏幕熄灭=是 | 编码器休眠=是\n"
            "省电 | 策略=idle-v2 | Wi-Fi停用=否 | USB主机=否 | 深睡唤醒次数=2"
            " | 休眠错误=0 | 设备运行时间=120 s\n"
            "诊断 | 错误=0 | 丢帧=0 | 采样率=16000 Hz | 声道=1 | 位深=16 bit"
            " | 快捷键修饰=3 | 键码=25 | 应答编号=17 | 结果=ok"
        )
        self.assertEqual(format_status(STATUS_SAMPLE), expected)

    def test_unknown_and_unavailable_fields_are_kept_without_json(self):
        status = {
            "battery_pct": -1, "battery_mv": -1, "new_sensor": {
                "valid": False, "samples": [0, 2], "name": "温度"},
            "missing": None, "empty_text": "", "empty_list": [], "empty_object": {},
        }
        self.assertEqual(format_status(status),
                         "电量与屏幕 | 电量=未知（-1） | 电压=未知（-1）\n"
                         "扩展字段 | new_sensor=(valid=否; samples=(0, 2); name=温度)"
                         " | missing=未知（null） | empty_text=空字符串"
                         " | empty_list=空列表 | empty_object=空对象")

    def test_wake_timing_and_voltage_remain_visible_while_soc_is_unknown(self):
        status = {"battery_pct": -1, "battery_mv": 3850,
                  "wifi_start_ms": 250, "wifi_associated_ms": 700,
                  "wifi_ip_ms": 950, "wifi_ready_ms": 0}
        self.assertEqual(format_status(status),
                         "电量与屏幕 | 电量=未知（-1） | 电压=3850 mV\n"
                         "联网时间（启动后） | 开始联网=250 ms | 关联完成=700 ms"
                         " | 取得IP=950 ms | 桥接首次就绪=0 ms")

    def test_discovery_timeout_and_cached_address_retries_are_silent(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            token_file, host_file = Path(directory) / "token", Path(directory) / "host"
            token_file.write_text("a" * 64)
            host_file.write_text("192.0.2.1\n")
            args = SimpleNamespace(serial=None, host=None, discover=True,
                                   token_file=token_file, host_file=host_file)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                    patch("voice_bridge.cli.discover_host", side_effect=TimeoutError("no discovery")), \
                    patch("voice_bridge.cli.TcpLink", side_effect=ConnectionError("asleep")) as link, \
                    patch("voice_bridge.cli.AnnounceListener", return_value=None), \
                    patch("voice_bridge.cli.time.sleep", side_effect=[None, None, None, KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    run(args)
            self.assertEqual(link.call_count, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_each_reconnection_summarizes_its_own_wait(self):
        args = SimpleNamespace(serial=None, host="192.0.2.1", discover=True)
        summaries, attempts = [], []

        def attempt(args, *, on_connected):
            attempts.append(args._reconnecting if hasattr(args, "_reconnecting") else False)
            if len(attempts) in (1, 2):
                raise TimeoutError("asleep")
            summaries.append(on_connected())
            self.assertFalse(args._reconnecting)
            self.assertTrue(args.discover)
            if len(attempts) == 3:
                raise ConnectionError("asleep again")
            return 0

        with patch("voice_bridge.cli._run", side_effect=attempt), \
                patch("voice_bridge.cli.AnnounceListener", return_value=None), \
                patch("voice_bridge.cli.time.sleep"), \
                patch("voice_bridge.cli.time.monotonic",
                      side_effect=[10, 10, 10.01, 10.5, 10.51, 11, 14, 20, 20.01, 20.5, 23]), \
                patch("voice_bridge.cli.timestamp", side_effect=[STAMP, "2026-10-07 08:10:00.000+08:00"]):
            self.assertEqual(run(args), 0)
        self.assertEqual(attempts, [False, True, True, True])
        self.assertEqual(summaries, [f"；等待=4.0 s；重试=2 次；等待开始={STAMP}",
                                    "；等待=3.0 s；重试=1 次；等待开始=2026-10-07 08:10:00.000+08:00"])

    def capture_session(self, statuses, *, ready_error=None, shortcut=None, verbose=True,
                        injector=None):
        session, sink = Mock(), Mock()
        sink.buffer = AudioBuffer()  # Real counters, no audio hardware.
        injector = injector or Mock()
        stdout, stderr = io.StringIO(), io.StringIO()

        def request(op, **fields):
            if op == "ready":
                self.assertEqual(stderr.getvalue(), "")
                if ready_error:
                    raise ready_error
            return {"transport": "wifi"}

        session.request.side_effect = request
        session.receive.side_effect = [[frame(status) if isinstance(status, dict) else status]
                                       for status in statuses] + [KeyboardInterrupt]
        args = SimpleNamespace(serial=None, host="192.0.2.1", output="BlackHole 2ch",
                               mic_device="", shortcut=shortcut, verbose=verbose)
        expected_error = type(ready_error) if ready_error else KeyboardInterrupt
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                patch("voice_bridge.log.timestamp", return_value=STAMP), \
                patch("voice_bridge.cli.open_session", return_value=session), \
                patch("voice_bridge.audio.AudioSink", return_value=sink), \
                patch("voice_bridge.cli.Injector", return_value=injector), \
                patch("voice_bridge.cli.trusted", return_value=True):
            with self.assertRaises(expected_error):
                _run(args)
        session.link.close.assert_called_once()
        sink.close.assert_called_once()
        return stdout.getvalue(), stderr.getvalue(), injector

    def test_connection_is_announced_only_after_ready(self):
        _, stderr, _ = self.capture_session([])
        self.assertEqual(stderr, f"[{STAMP}] 连接已建立：wifi 192.0.2.1\n")

    def test_failed_ready_does_not_announce_a_connection(self):
        stdout, stderr, _ = self.capture_session([], ready_error=TimeoutError("not ready"))
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_heartbeat_only_changes_are_quiet_but_all_changed_fields_are_logged(self):
        heartbeat = {**STATUS_SAMPLE, "ack": 18, "uptime_s": 121}
        changed = {**heartbeat, "battery_pct": 49, "uptime_s": 122}
        extended = {**changed, "new_sensor": 23, "uptime_s": 123}
        stdout, _, _ = self.capture_session([STATUS_SAMPLE, heartbeat, changed, extended])
        expected = "".join(f"[{STAMP}] {line}\n" for status in (STATUS_SAMPLE, changed, extended)
                           for line in format_status(status).splitlines())
        self.assertEqual(stdout, expected)
        self.assertIn("应答编号=18", stdout)
        self.assertIn("设备运行时间=122 s", stdout)
        self.assertIn("扩展字段 | new_sensor=23", stdout)

    def test_shortcut_log_keeps_request_fields_and_effective_override(self):
        status = {"event": "recording", "session": 7,
                  "ending": False, "modifiers": 3, "key": 25, "extra": "保留"}
        stdout, _, injector = self.capture_session([status], shortcut=(5, 44))
        self.assertEqual(stdout, f"[{STAMP}] 快捷键已发送 | event=recording"
                         " | session=7 | ending=否 | modifiers=3 | key=25 | extra=保留"
                         " | 实际修饰键=5 | 实际键码=44\n")
        injector.send.assert_called_once_with(5, 44)

    def test_default_status_noise_does_not_reach_terminal_or_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bridge.log'
            with persistent_log(path):
                statuses = [{**STATUS_SAMPLE, 'battery_mv': 3900 + i % 3,
                             'battery_pct': 98 - i // 30, 'ack': i, 'uptime_s': i,
                             'screen_off': i >= 30, 'new_sensor': i} for i in range(120)]
                stdout, stderr, _ = self.capture_session(statuses, verbose=False)
            self.assertEqual(stdout, '')
            self.assertEqual(len(stderr.splitlines()), 1)  # Connection established.
            self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_default_recording_reports_the_session_and_successful_keys_stay_quiet(self):
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        end = {**start, 'ending': True}
        key = {'event': 'key', 'modifiers': 0, 'key': 40}
        stdout, _, injector = self.capture_session([start, key, end], verbose=False)
        lines = stdout.splitlines()
        self.assertEqual(lines[0], f'[{STAMP}] 录音开始：会话 7；快捷键 ctrl+shift+v。')
        self.assertRegex(lines[1], rf'^\[{re.escape(STAMP)}\] 录音结束：会话 7；'
                                   r'时长=0\.\d+ s；音频=无（未收到 PCM）。$')
        self.assertEqual(len(lines), 2)
        self.assertEqual(injector.send.call_count, 3)

    def test_recording_start_names_the_override_in_use(self):
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        stdout, _, injector = self.capture_session([start, {**start, 'ending': True}],
                                                   verbose=False, shortcut=(5, 44))
        self.assertEqual(stdout.splitlines()[0],
                         f'[{STAMP}] 录音开始：会话 7；快捷键 ctrl+alt+space（--shortcut 覆盖）。')
        injector.send.assert_called_with(5, 44)

    def test_recording_summary_reports_frames_and_bridge_counters(self):
        stats = RecordingStats(7, 10.0, (0, 0, 0))
        stats.frame(11.0)
        stats.frame(11.5)
        self.assertEqual(stats.summary(12.0, (2, 3, 4)),
                         '录音结束：会话 7；时长=2.00 s；音频=0.04 s（2 帧）；'
                         '末尾延迟=500 ms；丢帧=2；欠载=3；缺口=4。')

    def test_default_recording_counts_received_audio(self):
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        stdout, _, _ = self.capture_session([start, pcm(1), pcm(2), pcm(3), {**start, 'ending': True}],
                                            verbose=False)
        self.assertRegex(stdout.splitlines()[1], rf'^\[{re.escape(STAMP)}\] 录音结束：会话 7；'
                                                  r'时长=0\.\d+ s；音频=0\.06 s（3 帧）；'
                                                  r'末尾延迟=\d+ ms；丢帧=0；欠载=0；缺口=0。$')

    def test_expired_recording_end_is_reported_without_a_press(self):
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        stale = {**start, 'session': 8, 'ending': True}
        stdout, _, injector = self.capture_session([start, stale], verbose=False)
        self.assertEqual(stdout.splitlines()[1], f'[{STAMP}] 忽略录音结束：事件会话=8；当前会话=7。')
        self.assertEqual(injector.send.call_count, 1)

    def test_verbose_expired_recording_end_keeps_the_event_fields(self):
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        stale = {**start, 'session': 8, 'ending': True}
        stdout, _, _ = self.capture_session([start, stale], verbose=True)
        self.assertIn('忽略过期结束快捷键 | event=recording | session=8 | ending=是', stdout)

    def test_a_start_that_could_not_be_injected_explains_its_ending_event(self):
        injector = Mock()
        injector.send.side_effect = RuntimeError('macOS does not trust this process')
        start = {'event': 'recording', 'session': 7, 'ending': False, 'modifiers': 3, 'key': 25}
        stdout, stderr, _ = self.capture_session([start, {**start, 'ending': True}],
                                                 verbose=False, injector=injector)
        self.assertEqual(stdout, '')
        self.assertIn('Shortcut not sent: macOS does not trust this process', stderr)
        self.assertNotIn('忽略录音结束', stderr)

    def test_shortcut_names_keep_codes_that_have_no_name(self):
        self.assertEqual(describe_shortcut(3, 25), 'ctrl+shift+v')
        self.assertEqual(describe_shortcut(1, 0x2c), 'ctrl+space')
        self.assertEqual(describe_shortcut(16, 0x52), '修饰键 0x10+键码 0x52')
        self.assertEqual(describe_shortcut(None, 25), '修饰键=未知（null），键码=25')

    def test_default_state_changes_are_reported_once(self):
        reporter = StatusLogger()
        with patch('voice_bridge.log.log') as output:
            for status in ({'mic': False, 'audio': False, 'bridge': True, 'transport': 'wifi'},
                           {'mic': False, 'audio': False, 'bridge': True, 'transport': 'wifi'},
                           {'mic': True, 'audio': False, 'bridge': True, 'transport': 'wifi'},
                           {'mic': True, 'audio': True, 'bridge': True, 'transport': 'wifi'},
                           {'mic': False, 'audio': False, 'bridge': False, 'transport': 'usb'}):
                reporter.update(status)
        self.assertEqual([call.args[0] for call in output.call_args_list],
                         ['状态变化 | 麦克风=开启。',
                          '状态变化 | 音频传输=开始。',
                          '状态变化 | 麦克风=关闭 | 音频传输=停止 | 桥接就绪=丢失 | 传输=usb。'])

    def test_default_state_changes_keep_voltage_screen_and_unknown_fields_quiet(self):
        reporter = StatusLogger()
        with patch('voice_bridge.log.log') as output:
            reporter.update({'battery_mv': 3900, 'screen_off': False, 'new_sensor': 1})
            reporter.update({'battery_mv': 3890, 'screen_off': True, 'new_sensor': 2})
        output.assert_not_called()

    def test_default_errors_and_recovery_are_not_hidden_or_repeated(self):
        reporter = StatusLogger()
        with patch('voice_bridge.log.log') as output:
            for error in (0, 17, 17, 0, 0):
                reporter.update({'error': error, 'sleep_error': 0})
            reporter.update({'error': 0, 'sleep_error': 5})
        self.assertEqual([c.args[0] for c in output.call_args_list],
                         ['设备错误：17', '设备错误已恢复。', '休眠错误：5'])

    def test_low_battery_alert_uses_hysteresis_and_ignores_unknown(self):
        reporter = StatusLogger()
        with patch('voice_bridge.log.log') as output:
            for battery in (-1, 98, 10, 9, -1, 11, 10, 16, 10):
                reporter.update({'battery_pct': battery})
        self.assertEqual([c.args[0] for c in output.call_args_list],
                         ['电量低：10%，请充电。'] * 2)

    def test_continuous_drops_are_reported_at_most_every_thirty_seconds(self):
        reporter = StatusLogger()
        with patch('voice_bridge.log.log') as output, \
                patch('voice_bridge.log.time.monotonic', side_effect=[0, 1, 29, 30]):
            for drops in (0, 1, 2, 3, 4):
                reporter.update({'drops': drops})
        self.assertEqual([c.args[0] for c in output.call_args_list],
                         ['音频丢帧：累计 1 帧。', '音频丢帧：累计 4 帧。'])

    def test_reconnect_errors_stay_quiet_until_connected_unless_verbose(self):
        for verbose, count in ((False, 2), (True, 5)):
            args = SimpleNamespace(auto=True, serial=None, host=None, discover=True,
                                   token_file=Path('token'), verbose=verbose)
            selector = Mock()
            selector.usb.return_value = None
            errors = iter(ConnectionError(message) for message in (
                'Device disconnected', 'timed out', 'No route to host',
                'Host is down', 'Device disconnected'))
            attempts = 0

            def attempt(args, *, on_connected):
                nonlocal attempts
                attempts += 1
                if attempts == 5:
                    on_connected()
                if attempts == 6:
                    return 0
                raise next(errors)
            with patch('voice_bridge.cli.AutoSelector', return_value=selector), \
                    patch('voice_bridge.cli.read_token', return_value='a' * 64), \
                    patch('voice_bridge.cli.AnnounceListener', return_value=None), \
                    patch('voice_bridge.cli._run', side_effect=attempt), \
                    patch('voice_bridge.cli.time.monotonic', side_effect=range(0, 3600, 60)), \
                    patch('voice_bridge.cli.time.sleep'), patch('voice_bridge.cli.log') as output:
                self.assertEqual(run(args), 0)
            self.assertEqual(output.call_count, count)
            if not verbose:
                self.assertEqual([call.args[0] for call in output.call_args_list],
                                 ['连接暂不可用，继续等待：Device disconnected'] * 2)

    def test_idle_heartbeat_requires_capability_and_known_inactive_state(self):
        idle = dict(STATUS_SAMPLE, idle_heartbeat=True)
        self.assertTrue(idle_heartbeat(idle))
        for key in ('idle_heartbeat', 'screen_off', 'mic', 'audio', 'recording'):
            changed = dict(idle)
            changed.pop(key)
            self.assertFalse(idle_heartbeat(changed))
            changed[key] = not idle[key]
            self.assertFalse(idle_heartbeat(changed))

    def test_idle_heartbeat_negotiates_immediately_and_resumes_active_timeout(self):
        session, sink = Mock(), Mock()
        session.request.return_value = {'transport': 'wifi'}
        args = SimpleNamespace(serial=None, host='192.0.2.1', output='test',
                               mic_device='', shortcut=None)
        clock = [0]
        idle = dict(STATUS_SAMPLE, idle_heartbeat=True)
        steps = iter([(0, [frame(idle)]), (4, []), (5, []),
                      (6, [frame(dict(idle, screen_off=False))]), (10, [])])

        def receive():
            clock[0], frames = next(steps)
            return frames

        session.receive.side_effect = receive
        with patch('voice_bridge.cli.open_session', return_value=session), \
                patch('voice_bridge.audio.AudioSink', return_value=sink), \
                patch('voice_bridge.cli.Injector'), patch('voice_bridge.cli.trusted', return_value=True), \
                patch('voice_bridge.cli.time.monotonic', side_effect=lambda: clock[0]), \
                patch('voice_bridge.cli.log'):
            with self.assertRaisesRegex(TimeoutError, '3 seconds'):
                _run(args)
        self.assertEqual([call.kwargs for call in session.send.call_args_list],
                         [{'active': True, 'idle': True},
                          {'active': True, 'idle': True},
                          {'active': True, 'idle': False}, {'active': False}])

    def test_silent_idle_device_times_out_and_legacy_keeps_fast_heartbeat(self):
        for capability, end, timeout in ((True, 16, 15), (False, 4, 3)):
            with self.subTest(capability=capability):
                session = Mock()
                session.request.return_value = {'transport': 'wifi'}
                args = SimpleNamespace(serial=None, host='192.0.2.1', output='test',
                                       mic_device='', shortcut=None)
                clock = [0]
                steps = iter([(0, [frame(dict(STATUS_SAMPLE, idle_heartbeat=capability))]),
                              (1, []), (end, [])])

                def receive():
                    clock[0], frames = next(steps)
                    return frames

                session.receive.side_effect = receive
                with patch('voice_bridge.cli.open_session', return_value=session), \
                        patch('voice_bridge.audio.AudioSink'), patch('voice_bridge.cli.Injector'), \
                        patch('voice_bridge.cli.trusted', return_value=True), \
                        patch('voice_bridge.cli.time.monotonic', side_effect=lambda: clock[0]), \
                        patch('voice_bridge.cli.log'):
                    with self.assertRaisesRegex(TimeoutError, f'{timeout} seconds'):
                        _run(args)
                expected = {'active': True, 'idle': True} if capability else {'active': True}
                self.assertEqual(session.send.call_args_list[0].kwargs, expected)

    def test_fatal_error_is_visible_and_each_line_has_a_timestamp(self):
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
                patch("voice_bridge.cli.state.directory", return_value=Path(directory)), \
                contextlib.redirect_stderr(stderr), \
                patch("voice_bridge.log.timestamp", return_value=STAMP), \
                patch("voice_bridge.cli.run", side_effect=PermissionError("bad token\nconfigure again")):
            self.assertEqual(main(["run", "--host", "192.0.2.1"]), 1)
        self.assertTrue(stderr.getvalue().endswith(
            f"[{STAMP}] Error: bad token\n[{STAMP}] configure again\n"))
        self.assertIn("桥接启动：PID=", stderr.getvalue())
