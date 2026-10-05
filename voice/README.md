# AI Passport 语音输入应用

更新日期：2026-10-06。设备使用自带麦克风采集音频，通过 USB 或 Wi-Fi 把音频送到 Mac；按键请求由 Mac 桥接程序注入。Mac 程序把音频写入 BlackHole，语音输入法通过聚合设备 `Passport Mic` 读取音频。

**2026-10-05 设计变更**：原设计的 BLE 键盘投递不可用。macOS 从未把 `Passport Voice` 挂载成 HID 键盘，蓝牙设置里也没有连接入口。快捷键改由桥接程序注入；设备只发送一条 `{"event":"shortcut","modifiers":N,"key":N}` 请求，不参与按键合成。BLE HID 代码已从固件移除，设备不再初始化蓝牙。

2026-10-05 当前版本：支持确认键临时输入、再次确认结束并关麦、保存或临时覆盖快捷键，以及 Wi-Fi 自动发现。完整固件门禁通过；桥接测试 62 项中 60 项通过、2 项因 Linux 缺少 macOS 框架跳过，脚本与刷机测试 26 项通过。本轮未刷写设备。省电规则、迁移步骤及未验证边界见下文和 [审查记录](REVIEW.md)。

2026-10-06 不含自动发现的上一版固件从源码重建并写入设备。本轮在 macOS 重新克隆官方基线（改用 Gitee 镜像，见下文）、运行 `apply_voice.py`，完整门禁通过。应用镜像 1,212,512 字节，SHA-256 `8661b8b0af43e7ec522f92ff0374d977a69a168b8ef076d0aeac630f72f11217`；ELF SHA-256 `c8405d0d…`；归档 `voice-source/build/firmware/bbd52b10be55a7626f5dc0f2f34a13d186190b1d3fe84d642125a6810c94ae01/`，`archive_firmware.py verify` 通过。刷写只写 `0x10000` 应用分区，回读校验一致；启动日志显示 `Loaded app from partition at offset 0x10000`，未见 panic 或重启。设备 MAC 为 `98:c3:77:f5:72:4c`。固件的日志等级在构建时被关闭，串口不输出应用行。本轮未做应用功能实机验收。

2026-10-06 含 Wi-Fi 自动发现的固件重建并写入设备。完整门禁通过（0 失败）；应用镜像 1,213,136 字节，本机 SHA-256 `c0bca8b522b11534110e7cae1d6902e0c2296bcb023e810f2e0749b6b27fa2d0`，ELF SHA-256 `3512193b…`，归档 `voice-source/build/firmware/306f0ccd253bb3ea7f6f63effbf2bd72fc16edd162fb92de776ce36b444b09ea/`，`archive_firmware.py verify` 通过。本机镜像与另一台构建的镜像大小相同、哈希不同。刷写只写 `0x10000` 应用分区，回读校验一致；启动日志显示从该分区加载，未见 panic 或重启。自动发现的实机效果尚未验收。

当前版本是独立应用，固件启动进入语音页面。设备重启后麦克风关闭，音频传输默认为 USB。

## 快速开始

```bash
# 一次性安装（可重复运行）
projects/ai-passport/voice/install.sh

# 首次安装或升级设备固件：先构建，命令见“固件安装”
# 激活 ESP-IDF 后，先列出串口，再只写应用分区
projects/ai-passport/voice/flash.sh --list-ports
projects/ai-passport/voice/flash.sh <串口> <归档目录>/FoloToy-AI-Passport.bin

# 可选：保存与输入法相同的快捷键。先停止 USB 桥接。
projects/ai-passport/voice/configure.sh <串口> --shortcut ctrl+shift+v

# 每次使用，二选一
projects/ai-passport/voice/start.sh usb       # 有线
projects/ai-passport/voice/start.sh wifi      # 无线，自动查找局域网设备
```

安装脚本会建虚拟环境、装桥接程序、检查 BlackHole 2ch，并在缺失时创建聚合设备 `Passport Mic`。它不安装任何系统软件包，缺少 BlackHole 时会给出命令并停止。

安装完成后有**两项只能由人完成**的设置：

1. **辅助功能权限。** 系统设置 → 隐私与安全性 → 辅助功能，允许运行桥接的终端应用，或直接允许 `voice/bridge/.venv/bin/python`。**授权后必须重启桥接程序**，macOS 在进程启动时固定这个授权。
2. **在输入法里把麦克风选为 `Passport Mic`。** 详见[输入设备](#输入设备聚合设备与自动切换)。

### 脚本用法

| 命令 | 说明 |
| --- | --- |
| `install.sh` | 安装或更新 Mac 侧。只写自己目录内的文件和聚合设备 |
| `start.sh usb [串口]` | 有线链路。串口省略时使用唯一的 `/dev/cu.usbmodem*` |
| `start.sh wifi [IP]` | 无线链路。IP 省略时自动发现设备；发现超时后尝试 `voice/.local/host` 中的上次地址 |
| `configure.sh [串口] --shortcut <组合键>` | 保存设备快捷键；可同时设置 Wi-Fi |
| `flash.sh --list-ports` | 列出串口、设备描述及 USB 标识；不打开串口 |
| `flash.sh <串口> <应用镜像>` | 检查设备分区，只刷应用并回读校验 |
| `uninstall.sh` | 卸载 Mac 侧，即 `install.sh` 的逆操作 |

只有 `start.sh` 把额外参数原样转给 `passport-voice run`，例如 `start.sh usb --output 'BlackHole 2ch'`。`start.sh` 在前台运行，用 `Ctrl+C` 停止；退出时会还原系统默认输入设备。

脚本按自身所在目录解析路径，可以在任何工作目录下调用。

### 卸载

```bash
projects/ai-passport/voice/uninstall.sh          # 先列出要做什么，回答 yes 才执行
projects/ai-passport/voice/uninstall.sh --yes    # 跳过确认
```

它会停止桥接、删除聚合设备 `Passport Mic`、删除 Wi-Fi 令牌与 `.local`、删除虚拟环境和构建残留。

脚本只停止本目录安装的桥接。桥接退出后重新检查默认输入；仍为 `Passport Mic` 时拒绝删除。其他目录的桥接仍在运行时也拒绝删除共享聚合设备。音频状态读取失败时停止卸载。

以下项目不会被改动，脚本会给出提示：

| 项目 | 原因 |
| --- | --- |
| BlackHole 2ch | 可能被其他程序共用；卸载命令为 `brew uninstall --cask blackhole-2ch` |
| 辅助功能授权 | 需要手动在“隐私与安全性”里移除 |
| 输入法的麦克风选择 | 需要手动改回 |
| 设备固件与 NVS | 设备仍保存 Wi-Fi 配置和令牌；清除配置需另行擦除对应 NVS 数据 |

## 自动省电

本次代码默认启用，无需额外开关：

- 设备 CPU 动态频率范围为 40–160 MHz。录音期间持有 160 MHz 锁；关麦后释放，实际频率由 ESP-IDF 和外设锁决定。
- 关麦后，传输任务轮询从 2 ms 改为 20 ms；音频任务的空闲检查从 20 ms 改为 100 ms。
- 麦克风关闭且 30 秒没有按键时，关闭背光并停止 LVGL 定时器。按键唤醒后仍执行该键原动作。开麦或采集期间保持亮屏。按键初始化失败时不熄屏。
- Mac 桥接在无音频状态下停止输出流，清除旧缓冲；收到音频时自动恢复。空闲链路读取最多阻塞 500 ms，连接和每秒心跳保留。

设备不进入 Light-sleep 或 Deep-sleep。USB Serial/JTAG 在睡眠期间无法工作，现阶段优先保留随时开麦的连接。[Espressif USB 睡眠说明](https://docs.espressif.com/projects/esp-idf/en/v5.2-rc1/esp32c3/api-guides/usb-serial-jtag-console.html)。实际节电幅度和首次开麦延迟需实机测量。

## 迁移到其他 Mac

源码和脚本按自身目录寻址，没有 `/Users/<用户名>`、Homebrew 安装前缀或固定设备号依赖。安装与启动的路径测试已覆盖空格和方括号。兼容目标为 Apple Silicon 与 Intel Mac；本次没有在新 Mac 实测，不能据此承诺所有 macOS 版本。

1. 复制源码目录，排除 `bridge/.venv`、`*.egg-info` 和 `__pycache__`。虚拟环境含机器路径和本机依赖，必须在目标 Mac 重建。
2. 安装 Python 3.10 或更新版本。可用 Python 官方的 [universal2 安装包](https://www.python.org/downloads/macos/)。需要指定解释器时运行 `PYTHON=/路径/python3 ./install.sh`。
3. 安装 BlackHole 2ch：`brew install --cask blackhole-2ch`。没有 Homebrew 时先安装它，或使用 BlackHole 官方安装包。确认系统已经加载驱动，再运行 `./install.sh`。
4. 在目标 Mac 重新授权辅助功能，并把输入法麦克风设为 `Passport Mic`。权限不会随源码迁移。
5. USB 串口自动枚举。Wi-Fi 地址要按新网络重新指定。继续连接同一设备时，可安全转移 `.local/token` 并保留 `0600` 权限；否则经 USB 重新运行 `configure`。

卸载只删除本目录的环境和本地状态，以及 UID 为 `com.ai-passport.aggregate.mic` 的聚合设备。BlackHole、系统权限和设备 NVS 需要分别处理。通过 `python -m voice_bridge.cli run` 自行启动的进程需先手动停止；脚本按绝对 CLI 路径识别它启动的桥接。

审查依据、修复和验证边界见 [稳定性与迁移审查](REVIEW.md)。

## 每次使用的流程

1. 启动桥接：`start.sh usb` 或 `start.sh wifi`。等它打印 `Audio output ready`。
2. 把光标放进要输入文字的输入框。
3. 麦克风关闭时按**确定**，设备临时开麦。音频采集就绪后，桥接选择 `Passport Mic` 并发送输入快捷键。
4. 说话。输入完成后再次按**确定**，桥接发送同一个快捷键结束输入，设备关闭麦克风，Mac 还原默认输入。
5. 在终端按 `Ctrl+C` 停止桥接。

这里采用用户确认的“再次确认结束”，不根据静音自动结束。输入法中的快捷键应设置为开始/结束切换；设备不能读取识别完成状态，也不能确认输入法是否接受了结束快捷键。

如果需要连续输入，用**上键**持续开麦，按确定发送快捷键，用上键关麦。上键关麦只关闭音频，不额外触发输入法快捷键。

临时开麦等待采集最长 3 秒。启动失败、桥接断开或快捷键注入失败时自动关麦。快速再次确认可取消尚未开始的临时输入。旧会话的结束请求不会关闭或触发新会话。

设备屏幕提示表示请求已入队。实际快捷键注入以 Mac 的 `Shortcut sent` 为准。

## 设备操作

| 操作 | 行为 |
| --- | --- |
| 上键单击 | 开启或关闭麦克风。电脑桥接未就绪时拒绝开启 |
| 确定单击 | 关麦时开始临时输入；临时输入时结束并关麦；持续开麦时发送快捷键 |
| 下键单击 | 麦克风关闭时切换 USB 与 Wi-Fi |

固件不再有蓝牙配对、数字比较确认和清除绑定，确定键长按不再有动作。macOS 蓝牙列表里若还留着一个 `Passport Voice`，那是系统缓存的历史条目，可以在蓝牙设置里移除；设备已不再广播。

页面分别显示麦克风采集和电脑桥接状态。

## 快捷键投递链

一次完整触发经过四段，任一段失败都不会出字：

| 段 | 就绪条件 | 失败表现 |
| --- | --- | --- |
| 设备录音 | 上键已开麦、桥接心跳在 3 秒内 | 屏幕 `Need mic and bridge` |
| 设备发请求 | 桥接就绪 | 屏幕 `Shortcut failed` |
| 桥接注入 | 辅助功能已授权 | 桥接打印 `Shortcut not sent` |
| 输入法取音频 | 默认输入为 `Passport Mic` | 桥接打印 `Default input: Passport Mic` |

首次启动默认快捷键为 `Control + Shift + V`。已有 NVS 中保存的快捷键继续生效。

保存快捷键到设备，重启后仍有效；修改前先停止 USB 桥接并关麦：

```bash
projects/ai-passport/voice/configure.sh <串口> --shortcut ctrl+shift+v
```

串口省略时自动选择唯一的 `/dev/cu.usbmodem*`。也可仅对本次运行覆盖，支持 USB 与 Wi-Fi：

```bash
projects/ai-passport/voice/start.sh wifi <IP> --shortcut ctrl+alt+space
```

开始和结束使用同一组合键。支持 `ctrl`、`shift`、`alt`、`cmd`，以及字母、`space`、`enter`、`escape`、`tab`、`f1`–`f12`。Fn 尚未支持。输入法快捷键需与这里一致；程序不会改写输入法设置。

## 安装细节

### 辅助功能权限

桥接程序用 `CGEventPost` 把按键注入当前前台应用，因此必须获得 macOS 辅助功能授权，否则注入被系统静默丢弃：

1. 打开“系统设置 → 隐私与安全性 → 辅助功能”。
2. 允许运行桥接的终端应用，或直接允许 `voice/bridge/.venv/bin/python`。
3. **重启桥接程序。** macOS 在进程启动时固定这个授权，运行中的进程不会取得新授予的权限。

未授权时桥接程序在启动和每次按键请求时打印提示。设备屏幕显示 `Shortcut sent` 只代表请求已发出，这种情况以桥接程序的输出为准。

### 输入设备：聚合设备与自动切换

桥接把音频写入 `BlackHole 2ch`。部分语音输入法不列出虚拟设备，因此需要一个聚合设备：

- 名称 `Passport Mic`，UID `com.ai-passport.aggregate.mic`，传输类型 `grup`，子设备为 `BlackHole 2ch`。
- 实测腾讯 Chatterfly 的麦克风列表里没有 `BlackHole 2ch`——尽管它在 AVFoundation 的 `.microphone` 设备类型中可见——重启输入法也不出现；`Passport Mic` 会出现。
- 聚合设备以 `private => 0` 创建，记录在 `/Library/Preferences/Audio/com.apple.audio.SystemSettings.plist` 的 `Meta_UIDList`，重启后保留。重新安装 BlackHole 会改变子设备 UID，届时需重建。
- 创建和查状态用 `passport-voice microphone`，缺了加 `--create`。命令行只提供创建，不提供删除：创建是随时可用的恢复动作，删除则由 `uninstall.sh` 统一负责，也仍可用“音频 MIDI 设置”。

Chatterfly 跟随**系统默认输入设备**，不保存自己选中的设备：二进制中存在 `kSGSpeechAudioInputDeviceUID` 与 `setSelectedDeviceUID:`，但该键在 `~/Library` 下没有任何落盘记录，下拉框的选择在默认设备被改动后即失效。因此桥接程序代管这个开关，且只在该开的时候开：

| 设备状态 | 桥接程序动作 |
| --- | --- |
| 上键开麦（`mic` 变为 true） | 把默认输入设备切到 `Passport Mic` |
| 关麦、拔线或桥接退出 | 默认输入仍由桥接控制时，还原为切换前的设备 |

副作用只在录音期间存在：平时默认输入仍是电脑自带麦克风，视频会议等程序不受影响。`SIGTERM`、`SIGHUP` 和 `Ctrl+C` 都走同一套还原逻辑，实测退出码 0。用 `--mic-device` 换设备名，传空字符串则完全不改默认输入。

排查设备列表用 `inputs`（输入，星号标出当前系统默认）和 `devices`（输出）。本机实测 `inputs` 会列出 `BlackHole 2ch` 和 `Passport Mic`，而 Chatterfly 自己的列表只显示 `Passport Mic`——过滤发生在输入法一侧，不是系统设备缺失。

### 固件中的一处调用顺序

固件在麦克风关闭后再次开启时，必须先调用 `bsp_audio_wake()` 再调用 `bsp_audio_init()`。`bsp_audio_sleep()` 会把编解码器留在低功耗态，而 `bsp_audio_set_format()` 以 `if (s_sleeping) return ESP_ERR_INVALID_STATE;` 开头；缺少唤醒调用时第二次开麦会失败并返回 `0x103`（259），麦克风再也开不起来。

## Wi-Fi 使用

首版支持与 Mac 在同一局域网的 WPA2 或更高安全等级 Wi-Fi。它不支持开放网络、企业认证或热点自动配网，设备只支持 **2.4 GHz**。若路由器把两个频段拆成不同名字，必须填 2.4 GHz 那个。

先在 USB 模式配置网络。程序交互式读取密码，终端不显示密码：

```bash
projects/ai-passport/voice/bridge/.venv/bin/passport-voice configure \
    --serial <串口> --wifi-ssid <网络名>
```

`--shortcut` 可以省略，此时设备保留当前快捷键；只有显式给出才会改写。配置 Wi-Fi 前必须**先停掉 USB 桥接**，串口不能被两个进程同时占用。SSID 须为 1–32 字节，密码须为 8–63 字节或 64 位十六进制 PSK。

程序生成并保存连接令牌，默认路径为 `voice/.local/token`，权限 `0600`。不在默认路径时用 `--token-file <路径>`。设备设置保存到 `voice_v1` NVS 命名空间。密码与令牌不写入源码、构建配置或状态输出。

### 找到设备但缺少令牌

自动发现只能查到 IP，不能恢复连接令牌。`voice/.local/` 被 Git 忽略；换电脑、换工作区或卸载桥接后，本机可能没有 `.local/token`。仅刷写应用保留设备 NVS，也不会在 Mac 上生成令牌。

本机令牌缺失时，先接好 USB 数据线、停止 USB 桥接并关闭麦克风，再从 `voice/` 目录运行：

```bash
./flash.sh --list-ports
./configure.sh <串口> --wifi-ssid <NETWORK_NAME>
```

程序交互式读取密码，生成新令牌并保存到 Mac 和设备。无需重刷固件，省略 `--shortcut` 会保留设备快捷键。新令牌替换设备原令牌，其他 Mac 若使用原令牌也需同步。完成后按下键切回 Wi-Fi，等待设备取得 IP，再运行 `./start.sh wifi`。

若原令牌仍在本机其他目录，可直接运行 `./start.sh wifi --token-file '<原令牌路径>'`。不要手动创建空令牌文件；随机生成但未写入设备的令牌也无法连接。

### 启动无线桥接

配置完成后停止 USB 桥接，关闭麦克风，按下键切到 Wi-Fi，然后：

```bash
projects/ai-passport/voice/start.sh wifi
```

自动发现需要安装包含发现功能的新固件，并更新 Mac 桥接程序（重新运行 `install.sh`）。配网只保存网络和令牌；设备重启仍进入 USB 模式，需关麦后按下键切到 Wi-Fi。等待屏幕显示已取得 IP，再启动无线桥接。

桥接程序在启动时向局域网广播 UDP `8765` 请求，最多等待 3 秒。每次启动重新查找，路由器更换设备 IP 后也可连接。发现报文只有协议标识和随机请求编号，不包含密码或令牌；TCP 连接仍验证已保存的令牌。验证成功后保存新 IP。找到多台设备时停止并列出 IP，不自动选择。

发现超时后尝试上次保存的地址，兼容旧固件。首次使用旧固件、广播被路由器阻止或找到多台设备时，可手动指定屏幕上的地址：`start.sh wifi <设备IP>`。上次地址失效时也需手动指定。macOS 若提示本地网络访问，应允许运行桥接的终端访问。

Mac 程序连接设备的 TCP `8765` 端口，网络必须允许同一局域网内的设备互访；自动发现还需允许 UDP 广播。Wi-Fi 链路使用令牌校验访问，TCP 音频没有应用层加密，此版本用于可信局域网。只允许 USB 保存配置，网络客户端不能修改密码或快捷键。

连接中断时，麦克风采集暂停，快捷键被阻止。恢复连接后重新运行桥接程序，状态心跳期限为三秒，设备不重放断线期间的按键。

### 切到 Wi-Fi 后不要再用 USB 串口查状态

**打开 `/dev/cu.usbmodem*` 会让 ESP32-C3 复位**（`rst:0x15 USB_UART_CHIP_RESET`，不是崩溃），而复位会把传输模式退回 USB。因此：

- Wi-Fi 模式下不要用 `--serial` 的工具查状态，会立刻把设备打回 USB 模式。改用屏幕，或直接 `--host` 连 TCP。
- 反复开关串口会形成表面上的“不停重启”：设备每秒被复位一次，屏幕持续闪。这不是固件故障。
- USB 模式下，每次启动桥接都会复位设备一次（`start.sh` 会提示）。桥接能自行恢复，但这是已知代价。

详见[设备级说明](../README.md#打开-usb-串口会复位设备)。

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 屏幕不停闪，像在反复重启 | 有工具在反复打开串口 | 停止轮询。Wi-Fi 模式下改看屏幕或连 TCP |
| 桥接打印 `Shortcut not sent` | 未获辅助功能授权 | 授权后**重启桥接** |
| 桥接打印 `Default input unchanged: No input device is named 'Passport Mic'` | 聚合设备缺失 | `passport-voice microphone --create` |
| 桥接没打印 `Default input: Passport Mic`，输入法不出字 | 默认输入没切过去 | 检查 `--mic-device`，用 `inputs` 看当前默认 |
| 桥接报 `Select usb on the device with DOWN` | 设备传输模式与参数不符 | 关麦后按下键切换，再重启桥接 |
| 桥接报 `Device changed audio transport` | 运行中切换了传输 | 重启桥接（这是刻意的安全检查） |
| 屏幕 `Need mic and bridge` | 未开麦或桥接未就绪 | 先启动桥接，再按上键开麦 |
| 屏幕 `Shortcut failed` | 请求没送出去 | 检查链路，USB 看串口、Wi-Fi 看 IP |
| 桥接报 `No route to host` | Wi-Fi 瞬时不可达 | 直接重试；实测重试即成功 |
| 桥接报 `No device frames for 3 seconds` | 链路断开 | 检查设备屏幕与网络，重新启动桥接 |

## 源码与构建

| 路径 | 用途 |
| --- | --- |
| `install.sh`、`start.sh`、`configure.sh`、`uninstall.sh` | Mac 侧安装、启动、配置与卸载入口 |
| `flash.sh`、`flash_firmware.py` | 设备应用分区检查、刷写和校验 |
| `firmware/main/main.c` | 独立语音页面、按键和状态显示 |
| `firmware/main/voice_runtime.c` | 分块录音、USB/Wi-Fi、配置保存、心跳和快捷键请求 |
| `firmware/main/voice_protocol.c` | 有长度限制和 CRC32 的帧协议 |
| `bridge/voice_bridge/cli.py` | 桥接主循环、命令入口和默认输入切换时机 |
| `bridge/voice_bridge/shortcut.py` | HID 用法码到 macOS 虚拟键码，以及 `CGEventPost` 注入 |
| `bridge/voice_bridge/hostaudio.py` | CoreAudio 设备名、设备 UID 与默认输入的读写 |
| `bridge/voice_bridge/microphone.py` | 聚合输入设备的描述、创建与状态报告 |
| `bridge/voice_bridge/audio.py`、`protocol.py`、`transport.py` | 播放缓冲、帧协议和串口/TCP 链路 |
| `firmware/tests/`、`bridge/tests/` | 固定数据和本地 TCP 测试，桥接侧不依赖真实音频设备 |
| `../apply_voice.py` | 将源码应用到独立官方工作树 |

2026-10-05 曾在当时的本机工作区恢复 `source/` 和 `voice-source/`，并校验语音固件归档。这是本机记录，不代表其他机器已具备这些目录。

两者均在 `.gitignore` 中，根仓库的 commit/push 不包含它们，`git clone`、`git pull` 和 `git restore` 也不会恢复它们。当前编译依赖官方完整工程；`voice/firmware/` 保存应用改动，需通过 `apply_voice.py` 同步到 `voice-source/` 后构建。下面的恢复流程用于目录缺失或换机器的情况。

从工作区根目录恢复工作树与源码。`source/` 缺失时，先恢复官方仓库并固定基线：

```bash
# source/ 不存在时执行
git clone --filter=blob:none https://github.com/FoloToy/ai-passport.git projects/ai-passport/source
git -C projects/ai-passport/source checkout --detach 33d3d1d93a1125b356b47b6d83a7a60121be801e

# voice-source/ 不存在时执行
git -C projects/ai-passport/source worktree add ../voice-source -b feature/voice-input 33d3d1d93a1125b356b47b6d83a7a60121be801e
python3 projects/ai-passport/apply_voice.py
```

工作树已存在时跳过 `worktree add`。分支 `feature/voice-input` 已存在而工作树缺失时，使用 `git -C projects/ai-passport/source worktree add ../voice-source feature/voice-input`。应用脚本只接受该官方基线，遇到目标文件被单独修改时停止，避免覆盖修改。

恢复后用 `git -C projects/ai-passport/source worktree list` 核对两个目录。上述命令恢复源码，不会恢复此前固件归档；ESP-IDF 工具链需按[开发手册](../DEVELOPMENT.md#安装构建环境)另行安装。

克隆地址可用 Gitee 镜像 `https://gitee.com/FoloToy/ai-passport.git`。2026-10-06 实测：该镜像 `main` HEAD 等于基线 `33d3d1d`，完整克隆约 10 秒、约 1.8 MB/s；GitHub 直连约 27 KB/s。同日实测 `--filter=blob:none` 的部分克隆因按需逐文件取 blob 而极慢（约 20 KB/s），恢复时改用完整克隆。

在已配置 ESP-IDF 5.5.3 的 Bash 会话中运行。需先激活项目内的 ESP-IDF 环境。恢复后的门禁会自动处理 macOS 链接器参数：

```bash
export IDF_TOOLS_PATH="$PWD/projects/ai-passport/.tools/espressif"
source projects/ai-passport/.tools/esp-idf/export.sh
cd projects/ai-passport/voice-source
./tools/validate.sh
```

`apply_voice.py` 生成的门禁在 macOS 上把 `-Wl,--gc-sections` 换成 `-Wl,-dead_strip`，无需机器专用的临时包装脚本。构建还需要项目 [requirements-dev.txt](../requirements-dev.txt) 中的 CMake 与 Ninja。Linux 的 OpenOCD 若缺少 libusb，按相邻[开发手册](../DEVELOPMENT.md)加载项目内的库路径。构建环境不会把 Wi-Fi 密码编入镜像。

Bridge 测试不依赖 Mac 音频设备：

```bash
PYTHONPATH=projects/ai-passport/voice/bridge python3 -m unittest discover -s projects/ai-passport/voice/bridge/tests -v
```

## 固件安装

`install.sh` 安装 Mac 桥接；`flash.sh` 安装设备固件。刷机前停止桥接和其他串口工具，USB 数据线需连接设备。必须明确指定串口与应用镜像。

先按上面的“源码与构建”恢复源码并运行门禁。门禁会把应用镜像保存在 `voice-source/build/firmware/<合并镜像哈希>/FoloToy-AI-Passport.bin`。

在已经激活 ESP-IDF 的会话中，从工作区根目录运行。先用 `--list-ports` 找到设备串口，再将它填入刷机命令。枚举不会打开串口或复位设备：

```bash
projects/ai-passport/voice/flash.sh --list-ports
projects/ai-passport/voice/flash.sh /dev/cu.usbmodemXXXX \
  projects/ai-passport/voice-source/build/firmware/<归档哈希>/FoloToy-AI-Passport.bin
```

只有固件镜像、没有 ESP-IDF 环境时，可在已经安装的桥接环境中安装刷机工具。此方式不需要编译工具链：

```bash
projects/ai-passport/voice/bridge/.venv/bin/python -m pip install esptool==4.12.0
PYTHON=projects/ai-passport/voice/bridge/.venv/bin/python \
  projects/ai-passport/voice/flash.sh /dev/cu.usbmodemXXXX <应用镜像路径>
```

脚本先检查 ESP32-C3 镜像，再读取设备 `0x8000` 的分区表。只有 `0x10000` 为未加密的 factory 应用分区，且镜像能放下时才执行写入。随后运行 `verify_flash`。镜像在检查前复制到临时目录，防止检查后源文件被替换。

应用镜像大小为 1,212,512 字节。2026-10-06 刷写使用本轮归档 `bbd52b10be55a7626f5dc0f2f34a13d186190b1d3fe84d642125a6810c94ae01`，应用 SHA-256 `8661b8b0af43e7ec522f92ff0374d977a69a168b8ef076d0aeac630f72f11217`；历史归档为 `8bd71c1dc3bc17e3e7c900e7c426d648f7d98c254c8b8987d246821f5098003b`。不同机器重建可能产生不同哈希。脚本不写 `0x0` 的合并镜像，不改引导、分区表或 NVS。

## 音频与协议

设备采集 16 kHz、16 bit、单声道 PCM。每帧包含 320 个采样，共 640 字节，即 20 ms。固件队列最多四帧；桥接队列最多八帧。缓冲满时丢弃旧音频，避免延迟持续增长。Mac 程序把单声道复制到两个输出声道。

帧头为 16 字节，所有整数按小端编码：

| 字段 | 大小 | 值 |
| --- | --- | --- |
| magic | 4 | ASCII `VP01` |
| type | 1 | `1` PCM、`2` JSON 命令、`3` JSON 状态 |
| flags | 1 | `0` |
| length | 2 | 载荷长度，最大 1024 字节 |
| sequence | 4 | PCM 连续序号，或命令序号 |
| CRC32 | 4 | 前 12 字节帧头与载荷的 IEEE CRC32 |

状态中的 `ack` 对应命令序号，`result` 报告结果。PCM 序号用于检测缺帧。帧解析器能跳过启动日志、错误帧和过长载荷。USB 音频期间禁用普通日志输出。

## 验收与边界

### 2026-10-05 在 Linux 完成

- Build：PASS。ESP-IDF 5.5.3 完整门禁通过，固件合并和分区布局检查通过。
- Host tests：PASS。官方静态与主机测试、语音协议与状态边界测试、8 项 Python 桥接测试通过。桥接程序可安装，CLI 入口有效。
- UBSan：PASS。语音协议、JSON 深度限制、密码格式和心跳边界测试通过。
- ASan：不可用。本环境中只返回零的空程序也退出为 139，不能用它判定应用内存安全。
- Device tests：NOT RUN。该 Linux 环境没有 Mac 或实体设备访问。麦克风、BLE、BlackHole 和听写均未做端到端验收。

### 2026-10-05 在目标 Mac（Apple Silicon，Darwin 25.6.0）完成

- Install：PASS。Homebrew cask `blackhole-2ch` 安装 0.7.1。驱动位于 `/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver`，标识 `audio.existential.BlackHole2ch`。
- Load：PASS。执行 `sudo killall coreaudiod` 后，`passport-voice devices` 列出 `BlackHole 2ch`（2 进 2 出），未重启电脑。重启后的持久性未验证。
- Bridge install：PASS。`voice/bridge/.venv` 由 Python 3.12.9 创建，`pip install -e` 装入 pyserial 3.5 与 sounddevice 0.5.6。`passport-voice devices` 与 `ports` 返回正常。
- Host tests：PASS。本机虚拟环境中桥接测试通过。
- Output open：PASS。`AudioSink` 以 16 kHz、2 声道、blocksize 320 打开 `BlackHole 2ch`，`check_output_settings` 通过。驱动默认采样率为 48 kHz。
- Loopback：PASS。测试脚本经项目 `AudioSink` 写入约 2.4 秒 440 Hz 单声道音频，从 `BlackHole 2ch` 输入录回 38,720 帧，`gaps` 为 0。
- Loopback level：PASS。源信号半满幅对应峰值 16,383、RMS 11,585。回环测得的 RMS 比值为 0.998 与 0.999，说明回环不改变音量。单次测得的峰值偏高（最高 +8%）不能复现：同一频率重复测量给出 +0% 到 +7%。该尖峰来自测试脚本输入流与输出流未同步产生的边界跳变，不是 BlackHole 的稳定特性。设备麦克风增益仍是唯一需要控制的电平因素。
- Dictation setup：PASS。系统听写偏好记录 `DictationIMMicrophoneName` 为 `BlackHole 2ch`（标识 `BlackHole2ch_UID`），语言为 `zh_CN`，自定义快捷键为 Control+Option+Space（`keyChar` 32，`modifiers` 786432）。当时误判输入法为 macOS 自带听写，实际生效的是 Chatterfly。
- Audio injection：PASS。用 `say` 生成 9.16 秒 16 kHz 单声道中文语音，播入 `BlackHole 2ch`，从输入录回后可见约 t=2 s 至 t=11 s 的语音段，与源时长一致。
- Passport device：部分验证。`ports` 只列出 `/dev/cu.usbmodem2101`（USB JTAG/serial debug unit）。

### 2026-10-05 固件构建与刷机（含 BLE HID 版本）

- Worktree：`projects/ai-passport/voice-source`，分支 `feature/voice-input`，基线 `33d3d1d9`。`apply_voice.py` 当时应用 13 个文件；移除 HID 后为 11 个。
- Gate：PASS。用 `CC=scratch/ai-passport-voice/cc-macos`（把 `-Wl,--gc-sections` 换成 `-Wl,-dead_strip`）运行 `./tools/validate.sh`，退出码 0。仓库检查扫描 273 个文本文件；BSP 按键、LVGL、音频、音频工作线程、低功耗、BLE、Wi-Fi 回滚与主机测试全部通过；固件布局检查包含 3 MB `factory` at `0x10000` 一项。目标编译器为 riscv32-esp-elf GCC 14.2.0。
- Artifact（含 BLE HID）：应用镜像 1,411,312 字节，SHA-256 `00e91471…`；合并镜像 1,476,848 字节，SHA-256 `e1b4e555…`；ELF SHA-256 `857dc3b9…`。归档为 `voice-source/build/firmware/e1b4e555…/`。
- 与 Linux 构建的差异：大小完全相同（1,411,312 / 1,476,848 字节），哈希不同（Linux 应用镜像 `df946d25…`、合并镜像 `9380cb28…`、ELF `dc90a7bd…`）。跨机器构建不保证逐字节一致，两个归档各自自洽。
- 设备分区表（刷写前回读）：`nvs` `0x9000`/24K、`phy_init` `0xf000`/4K、`factory` app `0x10000`/3M、`cardid` `0x356000`/16K、`easter` `0x360000`/388K、`recovery` `0x700000`/1M。
- Flash：PASS。只写 `0x10000` 处的应用镜像，未做全片擦除，未改分区表、NVS、`cardid`、`easter` 与 `recovery`。`verify_flash` 回读摘要一致。
- Boot：部分验证。串口只有二级引导日志，其中 `Loaded app from partition at offset 0x10000` 证明应用从应用分区加载。应用层日志按配置关闭（`CONFIG_LOG_DEFAULT_LEVEL_NONE`），没有应用日志可核对。

回环测试中的 37 次 `underruns` 来自测试脚本的固定间隔喂数与启动前的空缓冲，不是桥接缺陷。

### 2026-10-05 端到端联调

投递链四段全部实测通过：

- Shortcut injection：PASS。`shortcut.py` 把 HID 用法码映射为 macOS 虚拟键码，用 `CGEventPost` 注入到 `kCGHIDEventTap`。`ctrl+shift+v` 的按键序列实测为键码 59（Control）、56（Shift）、9（V）依次按下再逆序释放，事件标志位依次为 1、3、3、3、1、0。
- Accessibility：PASS。授权前桥接打印 `Shortcut not sent: macOS does not trust this process`；授权后必须重启桥接才对运行中的程序生效，与“macOS 在进程启动时固定授权”一致。
- 设备端触发：PASS。按下设备确定键后屏幕显示 `Shortcut sent`，桥接打印 `Shortcut sent`，输入法开始听写并出字。
- 麦克风恢复：PASS。补上 `bsp_audio_wake()` 后，麦克风关闭再开启可重复工作，不再返回 `0x103`。
- 聚合设备与默认输入切换：PASS。Chatterfly 的麦克风列表出现 `Passport Mic`；桥接在开麦时打印 `Default input: Passport Mic`、关麦时打印 `Default input restored`，系统默认输入随之改变和还原。
- 进程清理：PASS。麦克风处于开启状态时发送 `SIGTERM`，默认输入仍还原为 `MacBook Pro麦克风`，Python 进程退出码 0。
- 未验证：实际重启后聚合设备与辅助功能授权是否保持；设备长时间开麦的稳定性。

### 2026-10-05 移除 BLE 键盘并重刷

- 变更：删除 `firmware/main/voice_hid.c` 与 `voice_hid.h`（237 行）；`main/CMakeLists.txt` 从 `SRCS` 去掉该文件、从 `REQUIRES` 去掉 `bt`；`main.c` 去掉 HID 头文件、`hid_label` 状态行、配对确认分支、确定键长按清除绑定和 `voice_hid_init()`；`voice_runtime.c` 的状态 JSON 去掉 `hid` 字段，桥接程序的 `brief` 同步去掉；`apply_voice.py` 不再追加 `CONFIG_BT_NIMBLE_NVS_PERSIST` 与 `CONFIG_BT_NIMBLE_SM_SC`。屏幕的地址行与消息行上移到 137 和 172，补上原有空位。
- Gate：PASS。ESP-IDF 5.5.3 完整门禁退出码 0，固件布局检查 `app 1205920 / 8323072 bytes in 'factory' at 0x10000`。
- Artifact：应用镜像 1,205,920 字节（较上一版减少 205,392 字节，即移除的 BLE 栈），SHA-256 `2fb24bb4…`；合并镜像 1,271,456 字节，SHA-256 `d2d8400d…`；ELF SHA-256 `84d2f33d…`。归档 `voice-source/build/firmware/d2d8400d…/`，`manifest.json` 记录的哈希与实际文件一致。
- Flash：PASS。只写 `0x10000` 处的应用镜像，未做全片擦除。`verify_flash` 回读摘要一致。
- 分区表（刷写后回读）：`nvs` `0x9000`/24K、`phy_init` `0xf000`/4K、`factory` `0x10000`/3072K、`cardid` `0x356000`/16K、`easter` `0x360000`/388K、`recovery` `0x700000`/1024K，与刷写前一致。
- 桌面核验：PASS。桥接程序启动后状态不含 `hid` 字段。macOS 蓝牙列表仍显示 `Passport Voice`，但只有地址、没有连接状态，属于系统缓存的历史条目。
- 设备界面与按键：PASS。用户确认重刷后屏幕显示、上键开关麦、确定键触发和按下键切换传输均正常。

### 2026-10-05 Wi-Fi 链路端到端验收

- Configure：PASS。`configure --wifi-ssid` 在设备处于 USB 模式、麦克风关闭时写入 SSID、密码与令牌；令牌落到 `voice/.local/token`（64 位十六进制，权限 0600）。设备原有快捷键未被改写，仍为 `modifiers=3`、`key=25`（Ctrl+Shift+V）。
- 关联：PASS。设备下键切到 Wi-Fi 后取得地址 `192.0.2.2`（Mac 侧为 `192.0.2.1`，同网段）。ICMP 3/3 可达，但往返延迟 66–253 ms，抖动明显。
- TCP：PASS。8765 端口 `create_connection` 耗时 0.10 秒。
- 语音输入：PASS。桥接以 `--host 192.0.2.2` 启动后 `bridge: true`，开麦后 `mic` 与 `audio` 均为 true，快捷键注入并出字。
- 丢帧：**`drops` 为 0**。尽管 ICMP 延迟抖动很大，20 ms 一块的音频经 Wi-Fi 未丢帧。
- 离线性：PASS。**拔掉 USB 线后由电池供电，语音输入仍然出字**，这是 Wi-Fi 模式的主要目的。
- 未验证：长时间连续说话的丢帧、休眠与断线重连、Wi-Fi 模式的续航。

### 2026-10-05 安装与启动脚本

- 聚合设备脚本化：PASS。`passport-voice microphone --create` 用 pyobjc 的 `AudioHardwareCreateAggregateDevice` 建出设备，实测新建后 `/Library/Preferences/Audio/com.apple.audio.SystemSettings.plist` 中的定义与手工建立的逐字段一致（`name`、`uid`、`private` 为 false、`stacked` 为 false、子设备 `BlackHole2ch_UID`）。设备号每次枚举会变（实测出现过 120、124、149、153），因此桥接按名称寻址而不是设备号。
- 安装脚本：PASS。`install.sh` 重复运行返回 0，已存在的聚合设备不被改动。
- 启动脚本：PASS。用桩程序验证 8 种参数组合：无参数、未知模式、指定串口、自动识别串口、透传桥接选项、指定 IP、沿用记住的 IP、IP 与透传混用；另验证聚合设备缺失告警和未安装桥接两种分支。
- Host tests：PASS。桥接测试 35 项通过，新增聚合设备描述、创建、删除、上报与 pyobjc 调用契约的边界。
- 卸载脚本：PASS。用桩程序在沙箱中验证 31 项，覆盖正常卸载、默认输入未改时拒绝执行、聚合设备缺失、虚拟环境缺失、回答 no 取消、回答 yes 执行、未知参数、有桥接在跑时先停止八种情况。沙箱不接触真实环境，以免删建虚拟环境影响已有的辅助功能授权。
- 未验证：在全新 Mac 上从零运行的完整流程；在真实设备上执行一次完整卸载。
- 删除接口的取舍：`microphone --remove` 曾作为命令行开关存在，但其“不得删除默认输入”的保护只覆盖一种情况，实测能绕过并删掉正在使用的设备，因此撤下。删除逻辑改由 `uninstall.sh` 单独调用，并在脚本最前面做预检。

资料：[方案分析](../VOICE-INPUT.md)、[项目状态](../README.md)、[BlackHole](https://github.com/ExistentialAudio/BlackHole)、[macOS 听写](https://support.apple.com/guide/mac-help/use-dictation-mh40584/mac)。
