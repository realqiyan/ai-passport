# AI Passport：语音输入

更新日期：2026-10-05。

目标：使用设备自带麦克风，通过 USB 或 Wi-Fi 向 Mac 语音输入法传送音频，并用设备按键触发输入。

入口：[语音应用与安装说明](voice/README.md)、[开发手册](DEVELOPMENT.md)、[稳定性与迁移审查](voice/REVIEW.md)、[方案分析](VOICE-INPUT.md)。

## 当前状态

设备独立语音应用和 Mac 桥接已实现。音频通过 BlackHole 2ch 和聚合设备 `Passport Mic` 送入输入法；快捷键由 Mac 注入。此前在 Apple Silicon Mac 上实测 USB 与 Wi-Fi 出字，拔掉 USB 后电池供电的 Wi-Fi 输入也通过。

当前代码支持确认键临时输入：关麦时确认开始，再次确认结束并关麦。上键保留持续开麦。快捷键可保存到设备或在启动时覆盖。省电功能包括动态降频、关麦后减少轮询、30 秒空闲熄屏，以及 Mac 暂停音频输出。

此前完整固件门禁通过，应用镜像 1,212,512 字节。桥接测试 51 项中 49 项通过，2 项需 macOS 框架而跳过；脚本与刷机固定数据测试 25 项通过。当前临时输入与省电版本尚未实机刷写，验收边界见[审查记录](voice/REVIEW.md)。

## 源码与构建目录

| 路径 | 用途 |
| --- | --- |
| `voice/firmware/` | 维护的应用源码与 C 测试 |
| `voice/bridge/` | Mac 音频桥接与 Python 测试 |
| `apply_voice.py` | 将应用源码应用到固定官方基线 |
| `source/` | 官方基线仓库，承载共享 Git 数据和完整驱动、组件、构建工程 |
| `voice-source/` | 语音应用构建工作树及固件归档 |
| `.tools/`、`env.sh` | ESP-IDF 工具链与环境入口 |

当前编译依赖完整官方工程。先运行 `apply_voice.py`，再在 `voice-source/` 构建。`source/` 保持官方基线，工作树关系和语音归档已核验。

`source/` 和 `voice-source/` 均在 `.gitignore` 中。根仓库的 commit/push 不包含它们，`git clone`、`git pull` 和 `git restore` 也不会恢复它们。此前恢复仅发生在当时的本机工作区，不代表其他机器已有这些目录。

首次检出、换机器或目录缺失时，按[开发手册的恢复步骤](DEVELOPMENT.md#恢复固件源码)下载固定官方基线、创建语音工作树，再运行 `apply_voice.py`。ESP-IDF 工具链需另行安装；维护源码和文档由根仓库保存。

## 打开 USB 串口会复位设备

ESP32-C3 的 USB Serial/JTAG 在主机打开串口时可能复位设备。本设备实测出现 `rst:0x15 (USB_UART_CHIP_RESET)`；这与崩溃复位不同。

- USB 桥接每次启动可能复位设备一次。反复打开串口会造成连续重启的表象。
- 复位后传输模式回到 USB。Wi-Fi 输入期间用串口查状态，会中断会话；改用设备屏幕或网络通道。
- `flash.sh --list-ports` 只枚举串口，不打开设备。

## 未决问题与下一步

- 实机验证确认键临时输入、结束快捷键、反复开关麦、空闲熄屏与按键唤醒。
- 在全新 Apple Silicon 和 Intel Mac 上验证安装、权限、完整卸载及重启后的聚合设备。
- 观察长时间 USB/Wi-Fi 输入、丢帧、电脑睡眠和断线恢复，并测量实际耗电。
- 设备已有分区表与官方默认不同。使用 `flash.sh` 读取分区并只写应用，保留引导、分区表和 NVS。
