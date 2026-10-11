import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voice_bridge.cli import _run, main, run
from voice_bridge.log import format_status, log, timestamp
from voice_bridge.protocol import STATUS


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
                patch("voice_bridge.cli.time.sleep"), \
                patch("voice_bridge.cli.time.monotonic", side_effect=[10, 14, 20, 23]), \
                patch("voice_bridge.cli.timestamp", side_effect=[STAMP, "2026-10-07 08:10:00.000+08:00"]):
            self.assertEqual(run(args), 0)
        self.assertEqual(attempts, [False, True, True, True])
        self.assertEqual(summaries, [f"；等待=4.0 s；重试=2 次；等待开始={STAMP}",
                                    "；等待=3.0 s；重试=1 次；等待开始=2026-10-07 08:10:00.000+08:00"])

    def capture_session(self, statuses, *, ready_error=None, shortcut=None):
        session, sink, injector = Mock(), Mock(), Mock()
        stdout, stderr = io.StringIO(), io.StringIO()

        def request(op, **fields):
            if op == "ready":
                self.assertEqual(stderr.getvalue(), "")
                if ready_error:
                    raise ready_error
            return {"transport": "wifi"}

        session.request.side_effect = request
        session.receive.side_effect = [[frame(status)] for status in statuses] + [KeyboardInterrupt]
        args = SimpleNamespace(serial=None, host="192.0.2.1", output="BlackHole 2ch",
                               mic_device="", shortcut=shortcut)
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

    def test_fatal_error_is_visible_and_each_line_has_a_timestamp(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
                patch("voice_bridge.log.timestamp", return_value=STAMP), \
                patch("voice_bridge.cli.run", side_effect=PermissionError("bad token\nconfigure again")):
            self.assertEqual(main(["run", "--host", "192.0.2.1"]), 1)
        self.assertTrue(stderr.getvalue().endswith(
            f"[{STAMP}] Error: bad token\n[{STAMP}] configure again\n"))
        self.assertIn("桥接启动：PID=", stderr.getvalue())
