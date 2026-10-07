"""Format bridge events and device status for terminal logs."""
from datetime import datetime
import sys


def timestamp():
    return datetime.now().astimezone().isoformat(sep=" ", timespec="milliseconds")


def log(message, *, file=None):
    """Timestamp every line and flush it, including redirected output."""
    stamp = timestamp()
    for line in str(message).splitlines() or [""]:
        print(f"[{stamp}] {line}", file=sys.stdout if file is None else file, flush=True)


STATUS_GROUPS = (
    ("音频与连接", (
        ("mic", "麦克风开启"), ("audio", "音频传输"), ("bridge", "桥接就绪"),
        ("temporary", "临时输入"), ("session", "会话"),
        ("transport", "传输"), ("ip", "IP"))),
    ("电量与屏幕", (
        ("battery_pct", "电量"), ("battery_mv", "电压"),
        ("screen_off", "屏幕熄灭"), ("codec_asleep", "编码器休眠"))),
    ("省电", (
        ("power_profile", "策略"), ("wifi_idle", "Wi-Fi停用"),
        ("usb_host", "USB主机"), ("deep_wakes", "深睡唤醒次数"),
        ("sleep_error", "休眠错误"), ("uptime_s", "设备运行时间"))),
    ("诊断", (
        ("error", "错误"), ("drops", "丢帧"), ("rate", "采样率"),
        ("channels", "声道"), ("bits", "位深"), ("modifiers", "快捷键修饰"),
        ("key", "键码"), ("ack", "应答编号"), ("result", "结果"))),
)
UNITS = {"battery_pct": "%", "battery_mv": " mV", "uptime_s": " s",
         "rate": " Hz", "bits": " bit"}


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
