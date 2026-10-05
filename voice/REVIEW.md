# 语音应用稳定性与 Mac 迁移审查

日期：2026-10-05。审查基线：工作区提交 `8316445`。本轮按用户要求审查代码、安装与卸载，并实现自动省电。设备刷写未在本轮执行。

## 临时输入与安装入口更新

用户已确认：关麦时按确认临时开麦，完成输入后再次按确认结束并关麦。不使用静音判断。上键继续负责持续开麦。临时开麦在采集就绪后才投递快捷键；3 秒内无法就绪、链路断开或注入失败时关闭麦克风。

开始和结束发送同一个快捷键，需要输入法将该组合键设置为开始/结束切换。Mac 在开始事件前先选择聚合输入，避免快捷键比状态帧更早到达时选错麦克风。结束事件带会话编号；未成功开始或旧会话的结束事件不会触发新输入。

快捷键可用 `configure.sh [串口] --shortcut <组合键>` 保存到设备，也可用 `start.sh usb|wifi … --shortcut <组合键>` 仅覆盖本次运行。首次配置默认 Ctrl+Shift+V，已有保存值继续生效。设备校验范围与 Mac 支持的键码一致。

新增 `flash.sh <串口> <应用镜像>`。它先检查 ESP32-C3 芯片标识、ESP-IDF 应用描述和项目名称，拒绝引导镜像或合并镜像。读取设备分区后，仅在 `0x10000` 为未加密 factory 分区且容量足够时写入。镜像使用检查前的私有副本，随后执行回读校验。没有擦除或写入 NVS 的命令。

当前验证：桥接 51 项中 49 项通过、2 项需 macOS 而跳过；脚本与刷机固定数据测试 21 项通过。测试覆盖临时输入开始/结束顺序、默认输入选择、旧会话丢弃、注入失败关麦、快捷键覆盖、分区不匹配、合并镜像拒绝，以及检查后源文件变更。C 测试及 UBSan 通过；完整固件门禁和归档校验通过。

当前应用为 1,212,512 字节，SHA-256 `a22d6a641a7be205864d3e4da6713d98f30eefc36a6bc84831769d6ec44cb692`。归档为 `../voice-source/build/firmware/8bd71c1dc3bc17e3e7c900e7c426d648f7d98c254c8b8987d246821f5098003b/`。实际刷写、确认键临时输入和输入法结束行为尚未实机验证。安装命令以 [使用说明](README.md#固件安装) 为准。

以下保留此前稳定性与省电审查的依据和验证记录。

## 结论

源码和安装入口可以按目录迁移。Python 虚拟环境、辅助功能权限和 Wi-Fi 网络信息需要在目标 Mac 重建或重新设置。当前检查覆盖 Linux 上的固定数据测试和脚本沙箱；新 Mac、Intel Mac、实体音频设备与功耗验收仍待执行。

省电实现保留连接和心跳。CPU 允许动态降频，录音时锁定最高频率；关麦后减少轮询，空闲 30 秒熄屏。Mac 在无音频时停止输出流。实际节电量尚未测量。

## 已修复的代码问题

| 问题及影响 | 修复 | 验证依据 |
| --- | --- | --- |
| UI 任务直接发送快捷键帧，与传输任务同时写串口或 TCP；可能交叉写帧或竞争关闭客户端 | 快捷键进入有界队列，只有传输任务发送。超过 500 ms、模式改变或链路失效时丢弃 | 源码调用检查；协议固定数据测试。运行时并发行为需实机验收 |
| Mac 在关麦后仍每 20 ms 播放静音 | 空闲停止输出流；音频到达时恢复，切换前清除旧缓冲 | `bridge/tests/test_power.py` 覆盖空闲、恢复和断线清理 |
| 默认输入恢复失败被静默忽略，且保存状态先被清除 | 原生查询失败时报错；恢复失败保留状态，可重试；退出时输出错误；下一次状态到达时重试失败的输入切换 | `test_hostaudio.py` 覆盖失败、重试和原生查询错误 |
| 用户录音期间自行改变默认输入，退出时仍覆盖该选择 | 只有默认输入仍是桥接选中的设备时才恢复 | `test_hostaudio.py` |
| 同名音频设备可能导致选择错误 | 多个匹配名称时报错，要求先解决歧义 | `test_hostaudio.py` |
| CoreAudio 返回的名称与 UID 字符串未释放，重复查询会累积引用 | 转换后在 `finally` 调用 `CFRelease` | `test_hostaudio.py` 覆盖成功与转换失败 |
| 卸载使用全局进程模式，会停止其他安装目录的桥接 | 用转义后的绝对 CLI 路径匹配本目录进程；其他桥接运行时拒绝删除共享设备 | `tests/test_scripts.py` 覆盖路径空格、方括号和其他目录进程 |
| 卸载前禁止默认输入为 Passport Mic，导致正在开麦的自身桥接不能正常退出 | 允许先停止本目录桥接，再由删除函数检查默认输入 | 沙箱覆盖停止顺序和还原失败后保留文件 |
| 卸载时音频查询失败被当作设备不存在；删除只看名称 | 查询失败停止卸载；删除必须核对应用固定 UID | 脚本测试与 `test_microphone.py` |
| 卸载提示的未引用 heredoc 包含反引号，会执行 `passport-voice configure` | 提示改为普通文本 | 成功卸载沙箱无命令误执行 |
| 安装接受未使用的参数，卸载忽略多余参数 | 拒绝无效参数；仅启动脚本透传桥接选项 | 脚本测试 |
| 构建说明依赖某台 Mac 的绝对路径与临时编译器包装脚本 | `apply_voice.py` 生成 Darwin 链接器适配，文档使用相对路径 | 恢复脚本检查；本轮未在 macOS 执行生成的门禁 |
| 卸载说明误称刷回时钟会清除语音 NVS | 明确刷回时钟保留 `voice_v1`；清除需单独操作 NVS | 时钟和语音源码均保留已有 NVS |

## 省电实现与边界

设备开启 `CONFIG_PM_ENABLE`，频率范围为 40–160 MHz。音频任务在打开麦克风前取得 `ESP_PM_CPU_FREQ_MAX` 锁。关麦、失去桥接心跳或初始化失败时释放。Wi-Fi 与外设仍可通过自身锁提高频率，因此不能保证空闲期间始终为 40 MHz。背光 PWM 改用 XTAL 时钟，避免依赖变化的 APB 频率。依据：[ESP32-C3 电源管理](https://docs.espressif.com/projects/esp-idf/en/latest/esp32c3/api-reference/system/power_management.html)。

关麦后，传输任务每 20 ms 检查一次，音频任务每 100 ms 检查一次。麦克风或音频采集开启时不熄屏。麦克风关闭且 30 秒无按键时关闭背光和 LVGL 定时器。按键唤醒后继续执行原操作。按键初始化失败时保持屏幕可见。固定数据测试覆盖超时边界、活动录音、按键失效和时间逆序。

USB/Wi-Fi 连接继续存在，Mac 心跳仍每秒发送，设备状态仍每 500 ms 发送。Mac 读取超时改为 500 ms，数据到达立即返回。音频输出流暂停后不再运行持续静音回调。

本版禁用自动 Light-sleep，避免 USB Serial/JTAG 连接受影响。依据：[USB Serial/JTAG 与睡眠](https://docs.espressif.com/projects/esp-idf/en/v5.2-rc1/esp32c3/api-guides/usb-serial-jtag-console.html)。没有修改 Wi-Fi 的省电策略，也没有增加重新配网或按键重连流程。

## 验证

- 桥接测试：45 项，43 项通过，2 项因 Linux 缺少 macOS 框架跳过。覆盖协议、TCP、快捷键、聚合设备、输入恢复和音频暂停。
- 脚本测试：13 项通过。使用临时目录和桩程序，不安装驱动，不接触真实音频设备，不停止真实桥接。
- C 固定数据测试：协议、心跳、快捷键和熄屏条件通过；UBSan 通过。
- 官方工作树静态、主机与完整固件门禁：通过。固件布局和归档校验通过。环境为 ESP-IDF 5.5.3、CMake 3.25.1、Ninja 1.13.2。
- Shell 语法检查与 `git diff --check`：通过。

复现命令从工作区根运行：

```bash
PYTHONPATH=projects/ai-passport/voice/bridge python3 -m unittest discover -s projects/ai-passport/voice/bridge/tests -v
python3 -m unittest discover -s projects/ai-passport/voice/tests -v
bash -n projects/ai-passport/voice/install.sh projects/ai-passport/voice/start.sh projects/ai-passport/voice/uninstall.sh
python3 projects/ai-passport/apply_voice.py
# 激活 ESP-IDF 后，在 voice-source 运行 tools/validate.sh
```

固件应用镜像为 1,211,216 字节，小于已记录设备的 3 MB 应用分区。应用 SHA-256 为 `14555fcb4f52bdf415de067944e916abe4a8f5625433b997f4ae34cb16c0d25e`。合并镜像为 1,276,752 字节，归档在 `../voice-source/build/firmware/228421437f7d7892274a75c0904355cbf35b210f7cce365699604cf4b409bd9a/`。ELF map 包含动态调频实现 `esp_pm_impl_switch_mode`。本轮未写入设备；默认构建分区表与此前回读的设备分区表不同，设备更新应沿用已核验的应用分区写入方式。

构建准备中发现磁盘空间不足和 OpenOCD 缺少 libusb。清理可重建的 pip 缓存后，复用项目内 libusb。Python wheel 下载中断，改在 `scratch/ai-passport-voice/build-tools/` 解包 Debian CMake 与运行库，没有安装系统软件包。项目推荐版本仍以 `../requirements-dev.txt` 为准。

## 未决问题与下一步

1. 在 Apple Silicon 和 Intel Mac 分别执行一次全新安装、运行和完整卸载。检查权限、驱动加载、重启后的聚合设备，以及不同 macOS 版本的依赖安装。
2. 实机重复开关麦与快捷键，检查并发发帧、空闲 30 秒熄屏和按键唤醒。特别检查首次开麦延迟与音频首字是否完整。
3. 运行长时间 USB/Wi-Fi 音频，观察丢帧、拔线、电脑睡眠和恢复。当前桥接在断线后退出，需要重新启动。
4. 使用电流测量比较活动、关麦亮屏和关麦熄屏。CPU 锁与外设活动决定实际功耗，不报告未经测量的续航提升。
5. 通过 `python -m voice_bridge.cli run` 自行启动的进程须手动停止。卸载脚本自动识别由绝对 CLI 路径启动的进程。

迁移步骤以 [README](README.md#迁移到其他-mac) 为准。虚拟环境不可直接复制；Python 官方提供适用于 Intel 与 Apple Silicon 的 [macOS 安装包](https://www.python.org/downloads/macos/)。
