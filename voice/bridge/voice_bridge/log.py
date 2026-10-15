"""Format bridge events and device status for terminal logs."""
from datetime import datetime
import contextlib
import logging
from logging.handlers import RotatingFileHandler
import sys
import time

_file_handler = None


@contextlib.contextmanager
def persistent_log(path):
    """Keep bounded diagnostics even when the terminal disappears."""
    global _file_handler
    previous = _file_handler
    handler = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2,
                                      encoding="utf-8")
        _file_handler = handler
    except OSError as error:
        log(f"无法保存日志 {path}：{error}", file=sys.stderr)
    try:
        yield
    finally:
        _file_handler = previous
        if handler:
            handler.close()


def timestamp():
    return datetime.now().astimezone().isoformat(sep=" ", timespec="milliseconds")


def log(message, *, file=None):
    """Timestamp every line and flush it, including redirected output."""
    stamp = timestamp()
    for line in str(message).splitlines() or [""]:
        text = f"[{stamp}] {line}"
        if _file_handler is not None:
            _file_handler.emit(logging.LogRecord("passport-voice", logging.INFO,
                                                "", 0, text, (), None))
        try:
            print(text, file=sys.stdout if file is None else file, flush=True)
        except OSError:
            # Losing a terminal or a log pipe must not stop audio forwarding.
            pass


STATUS_GROUPS = (
    ("音频与连接", (
        ("mic", "麦克风开启"), ("audio", "音频传输"), ("bridge", "桥接就绪"),
        ("recording", "语音输入"), ("session", "会话"),
        ("transport", "传输"), ("ip", "IP"))),
    ("电量与屏幕", (
        ("battery_pct", "电量"), ("battery_mv", "电压"),
        ("screen_off", "屏幕熄灭"), ("codec_asleep", "编码器休眠"))),
    ("省电", (
        ("power_profile", "策略"), ("wifi_idle", "Wi-Fi停用"),
        ("auto_transport", "自动连接"),
        ("usb_host", "USB主机"), ("deep_wakes", "深睡唤醒次数"),
        ("sleep_error", "休眠错误"), ("uptime_s", "设备运行时间"))),
    ("联网时间（启动后）", (
        ("wifi_start_ms", "开始联网"), ("wifi_associated_ms", "关联完成"),
        ("wifi_ip_ms", "取得IP"), ("wifi_ready_ms", "桥接首次就绪"))),
    ("诊断", (
        ("error", "错误"), ("drops", "丢帧"), ("rate", "采样率"),
        ("channels", "声道"), ("bits", "位深"), ("modifiers", "快捷键修饰"),
        ("key", "键码"), ("ack", "应答编号"), ("result", "结果"))),
)
# The default log reports device changes, never snapshots. Run time, voltage
# and screen state stay out of the terminal; --verbose shows the full status.
TRANSITIONS = (
    ("mic", "麦克风", "开启", "关闭"),
    ("audio", "音频传输", "开始", "停止"),
    ("bridge", "桥接就绪", "恢复", "丢失"),
    ("transport", "传输", None, None),
)
UNITS = {"battery_pct": "%", "battery_mv": " mV", "uptime_s": " s",
         "rate": " Hz", "bits": " bit", "wifi_start_ms": " ms",
         "wifi_associated_ms": " ms", "wifi_ip_ms": " ms", "wifi_ready_ms": " ms"}


def display_value(value):
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "未知（null）"
    if isinstance(value, dict):
        items = "; ".join(f"{key}={display_value(item)}" for key, item in value.items())
        return f"({items})" if value else "空对象"
    if isinstance(value, list):
        items = ", ".join(display_value(item) for item in value)
        return f"({items})" if value else "空列表"
    return str(value) if value != "" else "空字符串"


def format_status(status):
    """Keep every reported field, including fields from a newer firmware."""
    lines, shown = [], set()
    for group, fields in STATUS_GROUPS:
        items = []
        for key, label in fields:
            if key not in status:
                continue
            value = status[key]
            if key in ("battery_pct", "battery_mv") and value == -1:
                text = "未知（-1）"
            else:
                text = display_value(value) + UNITS.get(key, "")
            items.append(f"{label}={text}")
            shown.add(key)
        if items:
            lines.append(f"{group} | " + " | ".join(items))
    extra = [f"{key}={display_value(value)}" for key, value in status.items() if key not in shown]
    if extra:
        lines.append("扩展字段 | " + " | ".join(extra))
    return "\n".join(lines)


class StatusLogger:
    """Report actionable changes; retain complete snapshots in verbose mode."""
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.previous = {}
        self.low_battery = False
        self.drops_reported = 0
        self.drops_at = None

    def changes(self, status):
        """List the changed fields that are worth a line without --verbose."""
        changes = []
        for key, label, on_text, off_text in TRANSITIONS:
            if key not in status or key not in self.previous:
                continue  # The first snapshot only sets the baseline.
            value, before = status[key], self.previous[key]
            if value == before:
                continue
            if on_text is None:
                changes.append(f"{label}={display_value(value)}")
            else:
                changes.append(f"{label}={on_text if value else off_text}")
        return changes

    def update(self, status):
        snapshot = {key: value for key, value in status.items() if key not in ("ack", "uptime_s")}
        if self.verbose:
            if snapshot != self.previous:
                log(format_status(status))
        else:
            changes = self.changes(status)
            if changes:
                log("状态变化 | " + " | ".join(changes) + "。")
            for key, label in (("error", "设备错误"), ("sleep_error", "休眠错误")):
                value = status.get(key)
                if isinstance(value, int) and value != self.previous.get(key, 0):
                    log(f"{label}：{value}" if value else f"{label}已恢复。", file=sys.stderr)
            battery = status.get("battery_pct", -1)
            if isinstance(battery, int):
                if 0 <= battery <= 10 and not self.low_battery:
                    log(f"电量低：{battery}%，请充电。", file=sys.stderr)
                    self.low_battery = True
                elif battery > 15:
                    self.low_battery = False
            drops = status.get("drops", 0)
            if isinstance(drops, int) and drops > self.drops_reported:
                now = time.monotonic()
                if self.drops_at is None or now - self.drops_at >= 30:
                    log(f"音频丢帧：累计 {drops} 帧。", file=sys.stderr)
                    self.drops_reported, self.drops_at = drops, now
        self.previous = snapshot
