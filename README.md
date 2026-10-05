# AI Passport：离线时钟

更新日期：2026-10-05。

原目标：配置 AI Passport 开发环境，保留开发手册，并开发离线时钟。用户已确认采用离线时钟和按键校时。

2026-10-05 后续要求“完成并安装时钟应用”。本次在 macOS（Apple Silicon）完成工具链安装、固件构建、写入设备和启动验证，应用镜像已装到设备。

入口：[开发手册](DEVELOPMENT.md)、[时钟源码](clock/main/main.c)、[时钟模型](clock/main/clock_model.c)、[测试](clock/tests/test_clock_model.c)。

## 功能和按键

第一屏显示时间、秒数、日期、星期、电量、时间制式和亮度。启动直接进入时钟，没有官方测试菜单。没有 Wi-Fi、网络校时或闹钟。

| 状态 | 上键短按 | 下键短按 | 确定短按 | 确定长按 |
| --- | --- | --- | --- | --- |
| 看时间 | 切换 12/24 小时 | 循环 25%、50%、80% 亮度 | 无操作 | 进入校时 |
| 校时 | 当前字段加一 | 当前字段减一 | 下一字段；分钟页保存 | 取消草稿 |

校时字段为年、月、日、时、分。范围为 2000—2099 年。调整年或月时，超出该月天数的日期自动缩至月末。字段在范围内循环。保存后秒数归零。

NVS 命名空间为 `clock_v1`。保存最后确认的时间、12/24 小时制式和亮度。只有明确设置时写入 Flash，不按秒保存。设备重启后从最后确认时间开始，提示重新校时。没有独立 RTC 或网络时源，无法知道断电期间经过多久。

存储失败在界面和日志提示，不自动擦除已有 NVS。电量读取失败显示 `--%`。首次时间为 2026-01-01 00:00，必须由用户设置。

## 当前状态

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

- 2026-10-05 用户在设备上确认功能全部生效（显示、按键、校时和设置保存）。
- 长期项目仍需观察：实际走时误差（无 RTC，只能靠人工校时修正）和电量读数的准确度。
- 设备上原有分区表与 `partitions.csv` 不同，若以后要写合并镜像从 `0x0` 开始，会改掉现有分区表和 `cardid`、`easter`、`recovery` 数据。

`source/` 和工具目录保持本地保存并由工作区 Git 忽略。长期源码保存在 `clock/`；恢复方式见手册。工作区版本控制保存源码和文档，固件未发布。
