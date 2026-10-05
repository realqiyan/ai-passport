# AI Passport：离线时钟

更新日期：2026-10-05。

原目标：配置 AI Passport 开发环境，保留开发手册，并开发离线时钟。用户已确认采用离线时钟和按键校时。

2026-10-05 后续要求“完成并安装时钟应用”。本次在 macOS（Apple Silicon）完成工具链安装、固件构建、写入设备和启动验证，应用镜像已装到设备。

入口：[开发手册](DEVELOPMENT.md)、[时钟源码](clock/main/main.c)、[时钟模型](clock/main/clock_model.c)、[测试](clock/tests/test_clock_model.c)。

2026-10-05 用户授权实施[语音输入方案](VOICE-INPUT.md)。独立语音应用和 Mac 音频桥接已实现，支持 BLE HID 快捷键、设备麦克风、USB/Wi-Fi 音频、配置保存与连接心跳。完整固件门禁和 8 项桥接测试通过，尚未刷机或完成 Mac 听写验收。应用镜像 1,411,312 字节，小于设备此前记录的 3 MB 应用分区。使用步骤、固件身份和未验证项见[语音应用说明](voice/README.md)。下一步在 Mac 核验 BlackHole 与实际输入法兼容性，确认设备和刷机授权后只写应用分区，再测试按键、录音和无线连接。当前时钟源码保留。

## 功能和按键

第一屏显示时间、秒数、日期、星期、电量、时间制式和亮度。启动直接进入时钟，没有官方测试菜单。没有 Wi-Fi、网络校时或闹钟。

| 状态 | 上键短按 | 下键短按 | 确定短按 | 确定长按 |
| --- | --- | --- | --- | --- |
| 看时间 | 切换 12/24 小时 | 循环 25%、50%、80% 亮度 | 无操作 | 进入校时 |
| 熄屏 | 唤醒；不改设置 | 唤醒；不改设置 | 唤醒；不改设置 | 唤醒；不进入校时 |
| 校时 | 当前字段加一 | 当前字段减一 | 下一字段；分钟页保存 | 取消草稿 |

默认亮度为 25%；已保存的亮度继续生效。30 秒无输入自动熄屏，校时期间保持亮屏。首次按键只唤醒，之后恢复原按键功能。

校时字段为年、月、日、时、分。范围为 2000—2099 年。调整年或月时，超出该月天数的日期自动缩至月末。字段在范围内循环。保存后秒数归零。

NVS 命名空间为 `clock_v1`。保存最后确认的时间、12/24 小时制式和亮度。只有明确设置时写入 Flash，不按秒保存。设备重启后从最后确认时间开始，提示重新校时。没有独立 RTC 或网络时源，无法知道断电期间经过多久。

存储失败在界面和日志提示，不自动擦除已有 NVS。电量读取失败显示 `--%`。首次时间为 2026-01-01 00:00，必须由用户设置。

## 当前状态

2026-10-05 省电版本：四项改动已写入源码，并已同步到本地官方检出。详细方法见[开发手册](DEVELOPMENT.md#时钟低功耗方法)。

- 默认背光 25%，保留已保存设置；按整秒等待且仅更新有变化的控件。
- CPU 动态降频 40–80 MHz；背光 PWM 使用 XTAL 时钟。亮屏阻止 Light-sleep，熄屏停止 LVGL 定时器并允许自动 Light-sleep。
- 空闲 30 秒熄屏，校时期间不熄屏；三个按键均可唤醒，首次按键不改设置。
- 静态门禁与全部主机测试通过；新增时钟模型测试也通过 ASan/UBSan，并已纳入 `validate.sh`。
- 固件构建（macOS arm64）：`CC=<包装脚本> ./tools/validate.sh` 退出码 0。应用镜像 754,128 字节，SHA-256 `ed3f0c8d3b7ab7d08b734324c6bd562657d3770739891487250d4698cc185353`；合并镜像 819,664 字节；ELF SHA-256 `98122d19…`；归档 `source/build/firmware/eab1c9cb…`，`archive_firmware.py verify` 通过。
- 省电配置核对：独立重新配置生成的 `sdkconfig` 含 `CONFIG_PM_ENABLE=y`、`CONFIG_PM_POWER_DOWN_CPU_IN_LIGHT_SLEEP=y`、`CONFIG_FREERTOS_USE_TICKLESS_IDLE=y`、`CONFIG_FREERTOS_IDLE_TIME_BEFORE_SLEEP=2`。
- 已刷入设备（同前，只写应用分区 `0x10000`）。启动日志：ELF SHA `98122d19f…` 与归档一致、`pm: Frequency switching config: CPU_MAX: 80, APB_MAX: 80, APB_MIN: 40, Light sleep: ENABLED`、`clock: Power: 40-80 MHz; automatic Light-sleep enabled when screen off`、各外设就绪、`Clock ready`；上电后 30.188 秒输出 `clock: Screen off`；熄屏后连续观察 60 秒无错误、无重启、无异常日志。实际功耗与按键唤醒尚未验证。

以下保留原版时钟的 macOS 构建和设备记录，与上面省电版本区分：

2026-10-05 在本机（macOS arm64）完成安装、构建和刷机。

- 官方源码在 `source/`，基线 `33d3d1d93a1125b356b47b6d83a7a60121be801e`（Gitee 镜像 HEAD 与该提交相同）；分支 `feature/offline-clock`；时钟覆盖 12 个文件，五个官方技能已安装并验证可读。
- ESP-IDF 5.5.3 来自官方离线归档 `esp-idf-v5.5.3.zip`（dl.espressif.cn，1,790,510,329 字节，本地 SHA-256 `d16e6b57b1df1a523aff6a1d0ef2f99cf058cb71e73f694429769eaaea171428`）。下载站点未提供官方校验文件；改用提交哈希交叉核对：检出 HEAD 为 `2c211b23…`，23 个子模块固定在记录提交且工作树干净。
- 工具链：`IDF_TOOLS_PATH` 指向 `.tools/espressif`（riscv32-esp-elf、GDB、OpenOCD、Python 环境）。macOS 上 ESP-IDF 不再自带 CMake 和 Ninja，已用 Homebrew 安装 cmake 4.4.4 和 ninja 1.13.2，与 `requirements-dev.txt` 版本一致。
- 构建：`./tools/validate.sh --firmware` 通过。应用镜像 727,824 字节，合并镜像 793,360 字节（SHA-256 `f0bd279a70bbdfd9cc0d911ee92038f678f0e4afee7719cbb1b4fc3eac4e62aa`），ELF SHA-256 `db549da7…`，归档在 `source/build/firmware/f0bd279a…`，`archive_firmware.py verify` 通过。
- 静态检查：`check_repo.py`、actionlint 1.7.12（Homebrew）、全部 C 主机测试和 5 个 Python 测试通过；字体覆盖 38 个中文码点在字表、生成字体、TTF 与运行时断言四处一致。macOS 的 ld64 不支持 `-Wl,--gc-sections`，用等价 `-Wl,-dead_strip` 的编译器包装脚本运行，脚本留在 `scratch/`，未进版本控制。
- 完整门禁：`CC=<包装脚本> ./tools/validate.sh` 退出码 0，静态检查和固件检查全部 PASS，重建的合并镜像同为 793,360 字节。
- 设备：ESP32-C3，MAC `98:c3:77:f5:72:4c`，端口 `/dev/cu.usbmodem2101`。设备现有分区表与官方默认不同：`nvs 0x9000/24K`、`phy_init 0xf000/4K`、`factory 0x10000/3M`、`cardid 0x356000/16K`、`easter 0x360000/388K`、`recovery 0x700000/1M`。按此只写应用分区 `0x10000`（用户选定），不动引导、分区表和其它数据。
- 写入的应用镜像 SHA-256 `063c9519d1d94decfff33d170e0c6a5f8b5e5801d72aa3fda7902ed0d5e5a298`，与归档一致。启动日志确认从 `0x10000` 加载、ELF SHA 与归档相同、CW2017 电量计识别成功、显示和 LVGL 就绪、按键就绪，并输出 `Clock ready`；无缺字和存储错误。

## 未验证与下一步

省电版本需要人工确认：

- 25% 背光下的可读性和中文显示；已保存 80% 亮度的设备须按下键切到 25%。
- 三个按键分别唤醒：第一次按键只唤醒，不改制式、亮度或校时状态；熄屏时长按确定只唤醒。
- 校时期间不熄屏；多次熄屏唤醒后显示、按键与存储正常。
- 跨分钟与跨日走时精度，以及长时间熄屏后的时间是否正确。
- 电流测量比较 80%/50%/25% 背光、减少更新、动态降频和熄屏的平均电流；USB 供电和充电电流不算应用耗电。

原版时钟遗留：

- 2026-10-05 用户在原版上确认功能全部生效（显示、按键、校时和设置保存）。
- 长期项目仍需观察：实际走时误差（无 RTC，只能靠人工校时修正）和电量读数的准确度。
- 设备上原有分区表与 `partitions.csv` 不同，若以后要写合并镜像从 `0x0` 开始，会改掉现有分区表和 `cardid`、`easter`、`recovery` 数据。

`source/` 和工具目录保持本地保存并由工作区 Git 忽略。长期源码保存在 `clock/`；恢复方式见手册。工作区版本控制保存源码和文档，固件未发布。
