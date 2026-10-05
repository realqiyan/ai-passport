# AI Passport 语音输入应用

更新日期：2026-10-05。用户已授权实施。设备使用自带麦克风采集音频，通过 BLE 键盘发送快捷键。Mac 程序把 USB 或 Wi-Fi 音频输出到 BlackHole，现有语音输入法从 BlackHole 读取音频。

当前版本是独立应用。固件启动进入语音页面。设备重启后麦克风关闭，音频传输默认为 USB。时钟源码保留在相邻 `clock/` 目录。

## 设备操作

| 操作 | 行为 |
| --- | --- |
| 上键单击 | 开启或关闭麦克风。电脑桥接未就绪时拒绝开启 |
| 确定单击 | 在麦克风采集、电脑桥接和蓝牙键盘均就绪时，发送一次快捷键 |
| 下键单击 | 麦克风关闭时切换 USB 与 Wi-Fi |
| 确定长按 | 麦克风关闭时清除设备蓝牙绑定 |
| 配对确认期间 | 确定接受屏幕上的数字比较，下键拒绝 |

首次使用时，在 Mac 蓝牙设置中配对 `Passport Voice`。只有 Mac 和设备显示相同的六位数字时，才确认配对。若 Mac 忘记设备而设备仍保留绑定，清除两端绑定后重新配对。

页面分别显示麦克风采集、电脑桥接和蓝牙键盘状态。`Shortcut sent` 只表示键盘发送成功，不证明输入法已经开始听写。结束听写的方法按所用输入法设置；本版本没有实现“按住说话、松开结束”。

## Mac 安装与有线验证

在 Mac 的工作区根目录执行：

```bash
brew install blackhole-2ch
python3 -m venv projects/ai-passport/voice/bridge/.venv
projects/ai-passport/voice/bridge/.venv/bin/python -m pip install -e projects/ai-passport/voice/bridge
```

按 BlackHole 安装程序要求完成重启。以下命令使用项目虚拟环境，不要求激活 shell：

```bash
projects/ai-passport/voice/bridge/.venv/bin/passport-voice devices
projects/ai-passport/voice/bridge/.venv/bin/passport-voice ports
```

在语音输入法中选择 `BlackHole 2ch` 为麦克风。若使用 macOS 自带听写，在“系统设置 → 键盘 → 听写”中设置麦克风来源和快捷键。先用电脑键盘确认自定义快捷键能触发听写。

默认设备快捷键为 `Control + Option + Space`。它是首版实现默认值，用户可以改变。Fn 的外接键盘兼容性尚未实现，首版采用普通组合键。

用 `ports` 返回的实际设备路径替换 `<串口>`。先确保设备上的麦克风关闭，再保存快捷键：

```bash
projects/ai-passport/voice/bridge/.venv/bin/passport-voice configure --serial <串口> --shortcut ctrl+alt+space
projects/ai-passport/voice/bridge/.venv/bin/passport-voice run --serial <串口> --output 'BlackHole 2ch'
```

桥接程序就绪后，按上键启用麦克风。等待屏幕显示 `MIC STREAMING`。将光标放入输入框，按确定，再说话。按上键关闭麦克风。按 `Ctrl+C` 停止 Mac 桥接程序。

桥接启动时必须能打开所选音频输出，否则不报告就绪。它不会自动回退到电脑扬声器。输出名称有多个匹配时，用 `devices` 列出的数字索引明确选择。

## Wi-Fi 使用

首版支持与 Mac 在同一局域网的 WPA2 或更高安全等级 Wi-Fi。它不支持开放网络、企业认证或热点自动配网。

先在 USB 模式配置网络。程序交互式读取密码，终端不显示密码：

```bash
projects/ai-passport/voice/bridge/.venv/bin/passport-voice configure --serial <串口> --wifi-ssid <网络名> --shortcut ctrl+alt+space
```

程序生成并保存连接令牌，默认路径为 `voice/.local/token`。令牌文件权限为 `0600`。设备设置保存到 `voice_v1` NVS 命名空间。密码与令牌不写入源码、构建配置或状态输出。

停止 USB 桥接。关闭麦克风，按下键切到 Wi-Fi。等待设备显示 IP 地址，然后执行：

```bash
projects/ai-passport/voice/bridge/.venv/bin/passport-voice run --host <设备IP> --output 'BlackHole 2ch'
```

若令牌保存在其他路径，两次命令均使用 `--token-file <路径>`。Mac 程序连接设备的 TCP `8765` 端口。网络必须允许同一局域网内的设备互访。

Wi-Fi 链路使用令牌校验访问，TCP 音频没有应用层加密。此版本用于可信局域网。只允许 USB 保存配置，网络客户端不能修改密码或快捷键。

连接中断时，麦克风采集暂停，快捷键被阻止。恢复连接后重新运行桥接程序。状态心跳期限为三秒。设备不重放断线期间的按键。

## 源码与构建

| 路径 | 用途 |
| --- | --- |
| `firmware/main/main.c` | 独立语音页面、按键和状态显示 |
| `firmware/main/voice_hid.c` | BLE HID、数字比较配对、键盘按下和释放 |
| `firmware/main/voice_runtime.c` | 分块录音、USB/Wi-Fi、配置保存和心跳 |
| `firmware/main/voice_protocol.c` | 有长度限制和 CRC32 的帧协议 |
| `bridge/voice_bridge/` | Mac 音频桥接与配置 CLI |
| `firmware/tests/`、`bridge/tests/` | 固定数据和本地 TCP 测试 |
| `../apply_voice.py` | 将源码应用到独立官方工作树 |

从工作区根目录恢复工作树与源码：

```bash
git -C projects/ai-passport/source worktree add ../voice-source -b feature/voice-input 33d3d1d93a1125b356b47b6d83a7a60121be801e
python3 projects/ai-passport/apply_voice.py
```

工作树已存在时跳过 `worktree add`。应用脚本只接受该官方基线。遇到目标文件被单独修改时停止，避免覆盖修改。

在已配置 ESP-IDF 5.5.3 的 Bash 会话中运行：

```bash
source projects/ai-passport/env.sh
cd projects/ai-passport/voice-source
./tools/validate.sh
```

Linux 上若本地 OpenOCD 缺少 libusb，先按相邻[开发手册](../DEVELOPMENT.md)加载项目内的库路径。构建环境不会把 Wi-Fi 密码编入镜像。

Bridge 测试不依赖 Mac 音频设备：

```bash
PYTHONPATH=projects/ai-passport/voice/bridge python3 -m unittest discover -s projects/ai-passport/voice/bridge/tests -v
```

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

2026-10-05 在 Linux 完成以下验证：

- Build：PASS。ESP-IDF 5.5.3 完整门禁通过，固件合并和分区布局检查通过。
- Host tests：PASS。官方静态与主机测试、语音协议与状态边界测试、8 项 Python 桥接测试通过。桥接程序可安装，CLI 入口有效。
- UBSan：PASS。语音协议、JSON 深度限制、密码格式和心跳边界测试通过。
- ASan：不可用。本环境中只返回零的空程序也退出为 139，不能用它判定应用内存安全。
- Device tests：NOT RUN。当前 Linux 环境没有 Mac 或实体设备访问。麦克风、BLE、BlackHole 和听写均未做端到端验收。

固件归档位于 `../voice-source/build/firmware/9380cb28d7a1e3dd164f1e6ee5882be63c29cc28d2182e2ef6774bd15bfff1a0/`，归档验证通过：

| 产物 | 大小或身份 |
| --- | --- |
| 应用镜像 `FoloToy-AI-Passport.bin` | 1,411,312 字节；写入地址 `0x10000` |
| 应用 SHA-256 | `df946d25c43970c9e401dfc34fcfcc280bb240605fc88e4f2b2c6a2388f3700d` |
| 合并镜像 `FoloToy-AI-Passport-full.bin` | 1,476,848 字节；写入地址 `0x0` |
| 合并镜像 SHA-256 | `9380cb28d7a1e3dd164f1e6ee5882be63c29cc28d2182e2ef6774bd15bfff1a0` |
| 匹配 ELF SHA-256 | `dc90a7bded7748f61b6f8d0bc77cd376220a27701e59eeb79d04db9546cd322a` |

本次 Linux 构建时磁盘空间不足，已用 `TMPDIR=/dev/shm` 存放临时构建文件。语音工作树的门禁支持 `TMPDIR` 并清理自己的临时目录。固件归档仍保存在项目目录，不删除已有工具缓存或历史固件。

固件构建、主机测试和实体设备测试分别记录。首版必须在 Mac 上验证 BlackHole 能被实际输入法使用。麦克风响度、噪声、句首保留、BLE 数字比较配对、快捷键、Wi-Fi/BLE 共存与功耗均需设备实测。

设备当前已有分区表中的应用分区为 `0x10000`、3 MB。后续写入前须核对新应用大小和设备布局。建议只写已核验的应用镜像，保留其它分区。本轮实施授权不包含刷机、全片擦除或发布。

资料：[方案分析](../VOICE-INPUT.md)、[项目状态](../README.md)、[BlackHole](https://github.com/ExistentialAudio/BlackHole)、[macOS 听写](https://support.apple.com/guide/mac-help/use-dictation-mh40584/mac)。
