# AI Passport 语音输入应用

更新日期：2026-10-07。

设备通过 USB 或 Wi-Fi 发送音频和按键请求。Mac 桥接把音频写入 BlackHole 2ch，通过聚合设备 `Passport Mic` 供腾讯 Chatterfly 识别，并注入键盘按键。录音时切换系统默认输入，结束或断连后恢复。

Linux 只维护源码和执行不依赖设备的测试。安装、构建、桥接运行与设备验证在 Mac 完成，见[项目规则](../AGENTS.md)。固件构建和刷机步骤集中在[开发手册](../DEVELOPMENT.md)。

## 设备操作

| 按键 | 短按 | 长按 |
| --- | --- | --- |
| 上键 | 开始语音输入；再按一次结束并关麦 | 发送一次键盘 Up |
| 下键 | 发送一次 Backspace | 发送一次键盘 Down |
| 确认键 | 发送一次 Enter | 关麦且音频停止时切换 USB／Wi-Fi |

麦克风默认关闭，不根据静音结束，不自动回车。长按阈值为 500 ms，每次只执行一次动作；双击没有独立动作。Backspace 和 Enter 按当前应用语义执行，选中内容可能被删除，Enter 可能确认候选、换行或发送消息。

开始录音需要桥接 ready。等采集就绪后才发送录音快捷键，启动超时、断线或注入失败会关麦。默认录音快捷键为 `Ctrl+Shift+V`，开始和结束使用同一组合键；输入法需将它设为开始／结束切换。设备不能判断识别是否完成。

常用流程：上键开始 → 说话 → 上键结束 → 等文字完整显示 → 确认键回车。

## Mac 安装与更新

先准备 Python 3.10 或更新版本、pipx 和 BlackHole 2ch。从工作区根运行：

```bash
brew install pipx
pipx ensurepath
brew install --cask blackhole-2ch
pipx install -e projects/ai-passport/voice/bridge
passport-voice setup
```

`ensurepath` 后重新打开终端。BlackHole 需已加载，`setup` 才能创建聚合设备。必要时重启音频服务或 Mac。

授予实际终端或 Python 解释器辅助功能权限，然后重启桥接。输入法选择 `Passport Mic`。部分输入法不显示 BlackHole，且跟随系统默认输入，因此桥接在录音期间代管默认输入。`--mic-device ''` 可关闭此切换。

### pipx 安装与更新

包名为 `passport-voice-bridge`，命令名为 `passport-voice`。可编辑安装的源码修改在重启桥接后生效；依赖或安装来源改变时需重装。

```bash
# 停止桥接后，更新同一源码目录的可编辑安装
pipx install --force -e projects/ai-passport/voice/bridge
passport-voice setup
```

普通安装去掉 `-e`，每次更新都需重装。更换源码目录时，先从原安装执行 `cleanup` 并卸载，再安装新目录。不要复制其他机器的虚拟环境。`install.sh` 会核验 pipx 来源，来源不符时停止。

### 状态目录与旧令牌迁移

Mac 状态目录为 `~/Library/Application Support/passport-voice/`，保存 `token` 和 `host`。令牌权限为 `0600`。可用 `PASSPORT_VOICE_STATE_DIR` 指定其他目录。

已有旧状态时，`setup --legacy-state-dir <旧目录>` 只迁移令牌和地址；不同令牌不会被覆盖。配置新 Wi-Fi 或替换令牌必须通过 USB，密码由终端交互读取，不写入源码或日志。

## USB 与 Wi-Fi 使用

```bash
passport-voice usb          # 唯一 USB 串口，可省略地址
passport-voice usb <串口>   # 多个串口时必须指定
passport-voice wifi         # 自动发现；超时后尝试缓存地址
passport-voice wifi <IP>    # 手动指定设备地址
```

桥接在前台运行，`Ctrl+C` 停止。USB 打开串口可能复位设备一次，普通复位后模式回到 USB。Wi-Fi 输入期间不要用 USB 串口查状态，否则会中断会话。

### Wi-Fi 使用

设备与 Mac 使用可互访的局域网。设备支持 2.4 GHz、WPA2 或更高安全等级的个人网络；不支持开放网络或企业认证。首次配网先停止 USB 桥接并关麦：

```bash
passport-voice configure --serial <串口> --wifi-ssid <网络名>
```

配置只保存网络和令牌。长按确认键切到 Wi-Fi，等屏幕取得 IP，再启动 `passport-voice wifi`。自动发现需要 UDP 8765 广播，音频连接使用 TCP 8765；发现多台设备时需指定 IP。认证成功后才更新缓存地址。

自动发现不能恢复令牌。换 Mac 或清理状态后，迁移已有令牌，或通过 USB 重新配网生成新令牌。设备上替换令牌后，其他 Mac 也需同步。仅刷写应用不会在 Mac 上生成令牌。TCP 音频没有应用层加密，仅在可信局域网使用。

### 快捷键配置

```bash
# 停止 USB 桥接、关麦后保存到设备
passport-voice configure --serial <串口> --shortcut ctrl+shift+v
# 仅覆盖本次运行
passport-voice wifi --shortcut ctrl+shift+v
```

`--shortcut` 只覆盖开始／结束录音，不影响 Enter、Backspace、Up 或 Down。省略配置选项时，设备保留已有快捷键。

## 自动省电

关麦空闲 30 秒后熄屏，Wi-Fi 空闲 60 秒后停无线，并在安全条件满足时进入深睡。USB 主机连接或录音期间不深睡。

深睡后短按上键并松开，先恢复 Wi-Fi，等桥接 ready 后再短按上键录音。唤醒键不执行输入动作。其他两键的深睡唤醒能力待测。已深睡时单独插 USB 不会由应用唤醒；普通复位回 USB，深睡按键唤醒恢复 Wi-Fi。

Mac 每秒重试 Wi-Fi 连接；1 秒是重试间隔，不是总恢复时间。功耗依据和验收步骤见[耗电排查](POWER.md)。

## 桥接日志

日志每行带本地时间、毫秒和 UTC 偏移，可直接保存：

```bash
passport-voice wifi 2>&1 | tee -a passport-voice.log
```

断连期间静默重试，认证及音频就绪后汇总等待时间与次数。状态按音频、电量、省电和诊断分组，保留上报字段。只有心跳或运行时间变化时不重复输出。设备的按键提示只表示请求入队，实际注入以日志中的“按键已发送”或“快捷键已发送”为准。

## 卸载

```bash
passport-voice cleanup && pipx uninstall passport-voice-bridge
```

`cleanup` 先停止当前桥接，再清理聚合设备和默认状态。它会要求确认；失败时不要继续卸载。自定义令牌和地址文件不会自动删除。

## 常用命令与脚本

| 入口 | 用途 |
| --- | --- |
| `passport-voice inputs`、`devices` | 查看 Mac 音频输入、输出 |
| `passport-voice microphone [--create]` | 检查或创建聚合设备 |
| `passport-voice ports` | 只读枚举串口 |
| `passport-voice run --help` | 底层运行选项 |
| `install.sh`、`uninstall.sh` | 核验来源后的安装、卸载入口 |
| `start.sh usb\|wifi …` | 向桥接转交参数 |
| `configure.sh <串口> …` | 保存设备快捷键或 Wi-Fi 配置 |
| `flash.sh` | 只写应用分区，步骤见[开发手册](../DEVELOPMENT.md#mac-刷机与验收) |

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 按键注入失败 | 检查辅助功能权限，授权后重启桥接 |
| 输入法不出字 | 检查 `Passport Mic` 和系统默认输入；缺聚合设备时运行 `setup` |
| 桥接未 ready | 检查传输模式、网络和令牌，等连接恢复后开始录音 |
| USB 打开后模式变化或屏幕闪 | 串口打开引起复位；停止反复轮询，Wi-Fi 状态用屏幕查看 |
| 找到 IP 但缺令牌 | 迁移已有令牌，或停桥接后通过 USB 配网 |
| 传输模式改变 | 关麦后选择对应模式，再重启对应 USB／Wi-Fi 桥接 |

## 音频与协议

固件采集 16 kHz、16 bit、单声道 PCM，每帧 640 字节。Mac 转为双声道送入 BlackHole。缓冲有界，满时丢弃旧音频。

协议和 CRC32 见[固件协议](firmware/main/voice_protocol.h)与[桥接协议](bridge/voice_bridge/protocol.py)。`recording` 事件携带会话、开始／结束及录音快捷键；`key` 事件投递普通按键，不选择音频输入。过期会话、断线和超过 500 ms 的设备按键请求不重放。

## 当前验收

依据：2026-10-07 目标 Mac 的三键部署记录，工作区提交 `2300e0f`。

| 检查 | 结果 |
| --- | --- |
| 固件完整门禁、归档校验 | 通过 |
| 应用分区刷写、回读与启动 | 通过；设备运行 `idle-v2`，麦克风关闭 |
| Mac 桥接与安装 | 120 项测试通过，pipx 已更新 |
| Mac 脚本固定数据测试 | 18 项通过，8 项路径断言失败；记录指向 `/var` 与 `/private/var` 差异，待修复 |
| 六键动作、深睡唤醒、实际续航 | 尚未实机验收 |

逐次构建日志和旧镜像身份不再重复记录。固件身份以 Mac 归档中的 `manifest.json` 为准，待办见[项目入口](../README.md#下一步)。
