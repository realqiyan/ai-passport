# AI Passport 开发手册

更新日期：2026-10-05。适用基线：官方仓库 `33d3d1d93a1125b356b47b6d83a7a60121be801e`。

2026-10-05 已在一台 macOS（Apple Silicon，Darwin 25.6）机器上按本文完成安装、构建和刷机，时钟应用已在设备上启动。下面保留通用流程，本机实际使用的路线见[从空环境安装](#从空环境安装)；当前状态见 [README](README.md)。

## 快速开始

先完成下文的环境安装。从工作区根目录打开 Bash，运行：

```bash
source projects/ai-passport/env.sh
idf.py --version
cd projects/ai-passport/source
./tools/validate.sh
```

`idf.py` 必须显示 `ESP-IDF v5.5.3`。完整检查通过后，合并固件位于 `build/FoloToy-AI-Passport-full.bin`，刷写起始地址为 `0x0`。

在 macOS 上，`idf.py` 还需要 Homebrew 提供的 CMake 和 Ninja（ESP-IDF 在 macOS 不再自带）：`brew install cmake ninja`。

合并镜像从 `0x0` 写入会一并改掉分区表。设备现有分区表可能是 FoloToy 出厂布局（`factory` 只有 3 MB，另有 `cardid`、`easter`、`recovery` 分区），此时应按[刷机和设备验收](#刷机和设备验收)先读分区表，再只写应用分区。

在当前时钟源码上做增量构建：

```bash
idf.py build
```

增量构建不能替代交付检查。交付前运行 `./tools/validate.sh`，并核对本次生成的固件归档。

## 本地目录

| 路径 | 用途 |
| --- | --- |
| `source/` | 官方完整源码；时钟在 `feature/offline-clock` 分支开发 |
| `clock/main/` | 工作区保存的时钟源码和构建配置 |
| `clock/tests/` | 不依赖硬件的时钟测试 |
| `clock/assets/fonts/` | 字体子集、生成代码、字表和许可 |
| `apply_clock.py` | 将保存的时钟源码应用到指定官方基线；遇到冲突停止 |
| `.tools/esp-idf/` | ESP-IDF 5.5.3 源码 |
| `.tools/espressif/` | 编译器、Python 环境和下载缓存 |
| `.venv/` | 项目开发依赖 |
| `env.sh` | 当前 Bash 会话的环境入口 |
| `source/build/firmware/` | 固件与匹配 ELF、MAP 的历史归档 |

`source/` 和工具目录由本地管理，工作区 Git 忽略它们。工作区保存 `clock/`、应用脚本和手册，避免重复收录官方仓库。时钟修改先写入 `clock/`，再运行 `python3 projects/ai-passport/apply_clock.py`。脚本只允许覆盖未修改的官方文件或上次由脚本生成的文件。

直接修改 `source/` 后，先将自己的修改同步回 `clock/`。若两处内容不同，脚本会停止，避免丢失修改。其他应用使用自己的分支和保存目录。

## 从空环境安装

先检查已有安装，只有版本为 5.5.3 时才复用。当前项目将工具放在自身目录，不要求修改系统包、全局 Git 配置或 shell 启动文件。下面先给本次 macOS 实测路线，再保留早先一台 Debian 12 机器的记录。

### macOS（本次实测路线）

1. 主机依赖：Xcode Command Line Tools，以及 `brew install cmake ninja actionlint`。macOS 上 ESP-IDF 的安装脚本不再提供 CMake 和 Ninja。
2. 应用源码：`git clone --depth 1 https://gitee.com/FoloToy/ai-passport.git source`。Gitee 的 HEAD 正好是基线 `33d3d1d93a1125b356b47b6d83a7a60121be801e`，核对后再建分支。
3. ESP-IDF：GitHub 直连超时；`git.espressif.com.cn` 镜像可达，但全历史克隆和逐仓库拉子模块都很慢（实测约 25 KB/s～0.2 MB/s）。改用官方离线归档，dl.espressif.cn 实测约 26 MB/s：

```bash
cd projects/ai-passport
curl -fL -o /tmp/esp-idf-v5.5.3.zip \
  https://dl.espressif.cn/github_assets/espressif/esp-idf/releases/download/v5.5.3/esp-idf-v5.5.3.zip
unzip -q /tmp/esp-idf-v5.5.3.zip -d .tools
mv .tools/esp-idf-v5.5.3 .tools/esp-idf
git -C .tools/esp-idf rev-parse HEAD    # 2c211b236707889e8400c4dc5644dd5c4ee071e0
git -C .tools/esp-idf submodule status  # 23 项，行首不能是 - 或 +
```

归档 1,790,510,329 字节，本地 SHA-256 `d16e6b57b1df1a523aff6a1d0ef2f99cf058cb71e73f694429769eaaea171428`。下载站点没有配套校验文件，所以用提交哈希交叉核对：归档的 HEAD 与 Gitee、`git.espressif.com.cn` 两个来源的 v5.5.3 提交一致，23 个子模块都停在记录提交，工作树干净。

4. 工具链：

```bash
IDF_TOOLS_PATH="$PWD/.tools/espressif" IDF_GITHUB_ASSETS=dl.espressif.cn/github_assets \
  bash .tools/esp-idf/install.sh esp32c3
bash -c 'source env.sh >/dev/null; idf.py --version'   # ESP-IDF v5.5.3
```

本次装出 riscv32-esp-elf、GDB、OpenOCD、esp-rom-elfs 和 Python 环境。不要用 `git submodule update --depth 1 --recursive` 批量取子模块：实测会把子模块停在分支顶端而不是记录的提交，单路径的 `git submodule update --init <路径>` 才停在记录提交。

### Debian 12（早先另一台机器的记录）

从工作区根目录运行：

```bash
mkdir -p projects/ai-passport/.tools
python3 -m venv projects/ai-passport/.venv
projects/ai-passport/.venv/bin/python -m pip install \
  -r projects/ai-passport/requirements-dev.txt

git clone --depth 1 https://gitee.com/FoloToy/ai-passport.git \
  projects/ai-passport/source
git -C projects/ai-passport/source rev-parse HEAD
```

若 Gitee 无法下载，可使用官方 GitHub 仓库 `https://github.com/FoloToy/ai-passport.git`。本次通过 GitHub 下载。运行应用脚本前，核对 HEAD 与本手册的基线一致。最新 `main` 可能已变化；不要对另一版本直接应用旧配置。

安装 ESP-IDF：

```bash
git clone --depth 1 --branch v5.5.3 --shallow-submodules --recursive \
  https://github.com/espressif/esp-idf.git \
  projects/ai-passport/.tools/esp-idf

AI_PASSPORT_PROJECT_ROOT="$(cd projects/ai-passport && pwd)"
export IDF_TOOLS_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/espressif"
export PATH="${AI_PASSPORT_PROJECT_ROOT}/.venv/bin:${PATH}"
"${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/install.sh" esp32c3
```

本机是 Debian 12。首次安装检查发现 OpenOCD 缺少 `libusb-1.0.so.0`。已用现有 APT 软件源下载 `libusb-1.0-0`，并提取到 `.tools/host-libs/`，没有安装系统包。后续重试前，在当前 Bash 会话加载该库：

```bash
export LD_LIBRARY_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/host-libs/usr/lib/$(gcc -print-multiarch):${LD_LIBRARY_PATH:-}"
IDF_GITHUB_ASSETS=dl.espressif.cn/github_assets \
  "${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/install.sh" esp32c3
```

安装成功后，在同一会话加载 `env.sh`。新的会话如需 OpenOCD，也要先设置该本地库路径。另一台机器没有这个目录时，先检查其原有 libusb，不直接照搬本机路径。

当前 ESP-IDF 使用稀疏检出，省略官方文档、示例和部分测试目录；构建源码与官方提交一致。本次逐文件核对 Git blob 身份，并保持检出状态干净。已初始化 `heap/tlsf`、`json/cJSON` 和 `micro-ecc` 子模块，其他子模块尚未补齐。后续按下面的标准子模块命令恢复所需依赖，不将本次下载中的临时脚本作为必需入口。

该标签的 Git tag 对象为 `b31fcc7a314a44ad992b58f589f7d1d8a4fadff6`，源码提交为 `2c211b236707889e8400c4dc5644dd5c4ee071e0`。两者不是同一种 Git 对象。

下载失败时保留已下载的文件。修复子模块后重试安装，不清空工具缓存：

```bash
git -C projects/ai-passport/.tools/esp-idf submodule update --init --recursive
```

官方大陆下载入口可用于当前命令：

```bash
IDF_GITHUB_ASSETS=dl.espressif.cn/github_assets \
  "${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/install.sh" esp32c3
```

组件下载可在当前 shell 设置 `IDF_COMPONENT_STORAGE_URL=https://components-file.espressif.cn`。不要关闭 TLS 校验，也不要自行换成第三方镜像。

安装官方要求的五个技能：

```bash
python3 projects/ai-passport/source/tools/install_passport_skills.py --install
python3 projects/ai-passport/source/tools/install_passport_skills.py --check
```

安装器建立 `source/.agents/skills/` 到官方 `skills/` 的相对链接。确认文件可读后，按任务读取对应 `SKILL.md`；新会话从项目目录开始。

恢复本次时钟：

```bash
git -C projects/ai-passport/source switch -c feature/offline-clock
python3 projects/ai-passport/apply_clock.py
source projects/ai-passport/env.sh
cd projects/ai-passport/source
./tools/validate.sh
```

## 开发下一款应用

1. 读取 `source/AGENTS.md` 和 `source/docs/README.md`。
2. 检查 `git status --short --branch`，保留已有修改。
3. 先定义第一屏、三个按键、数据保存和失败反馈。
4. 从官方基线建立新的 `feature/<应用名>` 分支。
5. 查阅 `docs/reference/README.md` 和相关 `demo/*` 分支。
6. 复用 BSP，在 `main/` 编写应用状态和自己的界面。
7. 为日期、计时、协议等独立逻辑添加主机测试。
8. 运行完整检查，交付固件和未验证项。
9. 经用户同意后，刷写指定固件并检查设备表现。

不要在有时钟未提交修改的目录直接切换到另一个应用。可为官方基线建立另一个工作树，或先由用户决定如何保存当前分支。构建、分支创建和文件修改不等于提交、推送或发布授权。

## 硬件和模块边界

| 能力 | 接口或约束 |
| --- | --- |
| 芯片 | ESP32-C3，8 MB Flash，无 PSRAM |
| 显示 | ST7789P3，240×320，SPI；复用 `bsp_display_*`、`bsp_lvgl_*` |
| 按键 | 上、下、确定，共用 ADC 电阻梯；复用 `bsp_button_init()` |
| 电量 | CW2017；复用 `bsp_battery_*`，读取失败显示未知 |
| 音频 | ES8311；阻塞 PCM 操作放在工作任务 |
| I²C | BSP 持有共享总线；不要再创建同端口总线 |
| 串口 | 原生 USB Serial/JTAG；不要占用 GPIO18/19 |
| 时间 | 本版用 `esp_timer_get_time()` 推进时间，不补算断电时长 |

引脚、电压窗口和面板参数只从 `components/bsp/include/bsp_pins.h` 读取。芯片功能表不能证明板上存在某个接口。

硬件驱动放在 `components/bsp/`。页面、状态、任务和资源放在 `main/` 或应用资源目录。新应用必须设计自己的界面，不能沿用测试菜单或 `ui_pixel` 外壳。

## 任务与 LVGL

按键回调只入队。不要在回调中保存数据、访问 LVGL、播放音频或等待网络。

非 LVGL 任务访问 `lv_*` 前，先成功取得 `bsp_lvgl_lock()`；操作后释放锁。存储和电量读取在锁外执行。删除页面前，停止所有会访问该页面的任务、定时器和回调。

时钟用一个任务处理输入、计时和保存。它每 100 ms 等待一次队列，用单调微秒值计算经过时间，不靠刷新次数计时。电量每 30 秒读取一次。校时草稿与正在运行的时间分开，取消草稿不改变当前时间。

## 中文字体

默认 Montserrat 不含中文。LVGL 内置 Source Han Sans SC 也只是子集。本次检查发现它缺少 16 个所需字符，因此使用 Noto Sans SC 的专用子集。

`clock/assets/fonts/glyphs.txt` 保存 ASCII 和所有固定中文字符。字体来自 Google Fonts 的 Noto Sans SC，遵循同目录 `OFL.txt`。`clock_font_16.c` 是 16 px、4 bpp、未压缩的生成字体。每个中文控件显式选择该字体。

重新生成字体时使用 `lv_font_conv@1.5.3`：

```bash
npm install --prefix projects/ai-passport/.font-tools --save-exact lv_font_conv@1.5.3
node projects/ai-passport/.font-tools/node_modules/lv_font_conv/lv_font_conv.js \
  --font projects/ai-passport/clock/assets/fonts/NotoSansSC-clock.ttf \
  --symbols "$(cat projects/ai-passport/clock/assets/fonts/glyphs.txt)" \
  --size 16 --bpp 4 --format lvgl --no-compress \
  --lv-font-name clock_font_16 --lv-include lvgl.h \
  --output projects/ai-passport/clock/assets/fonts/clock_font_16.c
```

添加新汉字时，先取得包含该字的合法字体。现有 TTF 子集不能生成原来没有的字。核对字体码点、控件绑定和设备实际显示；构建通过不能证明文字可见。

## 验证与交付

| 命令 | 验证内容 |
| --- | --- |
| `./tools/validate.sh --static` | 仓库规则、文档、工作流、BSP 与应用主机测试 |
| `./tools/validate.sh --firmware` | ESP-IDF 构建、合并镜像、分区和字节匹配 |
| `./tools/validate.sh` | 完整交付检查 |
| `python3 tools/archive_firmware.py verify <归档目录>` | 固件与 ELF 等归档文件一致性 |

默认分区为 NVS `0x9000`、PHY `0xF000`、factory 应用 `0x10000`。应用分区容量为 `0x7F0000`。完整镜像包含引导和分区表；应用单独镜像不能写到 `0x0`。

完整检查使用临时构建目录，不读取根目录的本地 `sdkconfig`。交付需要的设置必须写入 `sdkconfig.defaults`。依赖以 `dependencies.lock` 为准，不修改 `managed_components/`。

失败的构建可能留下旧固件。只交付本次成功检查生成的文件，记录完整镜像 SHA-256 和匹配 ELF 的身份。

macOS 的 `ld64` 不接受 `-Wl,--gc-sections`，静态检查里的演示运行时测试会失败。用包装脚本把该参数换成等价的 `-Wl,-dead_strip`，再以 `CC=<包装脚本> ./tools/validate.sh` 运行：

```bash
#!/bin/bash
set -euo pipefail
args=()
for a in "$@"; do
    if [[ "$a" == "-Wl,--gc-sections" ]]; then
        args+=("-Wl,-dead_strip")
    else
        args+=("$a")
    fi
done
exec /usr/bin/cc "${args[@]}"
```

包装脚本只用于本机验收，不进版本控制。`actionlint` 可用 Homebrew 安装（本机 1.7.12）；离线且未提供 `ACTIONLINT_BIN` 时，脚本会尝试 `tools/install-actionlint.sh` 从 GitHub 下载。

## 刷机和设备验收

刷机需要明确指定设备和固件，并取得用户同意。完整镜像从 `0x0` 写入，可能重置 NVS；需要保留数据时，先检查分区兼容性和分段刷写流程。不要默认执行 `erase_flash`。

浏览器安装入口为官方[本地刷机工具](https://ai-passport.folotoy.cn/tools/web-flasher/)。支持串口的电脑浏览器需要 USB 数据线和设备访问权限。

授权后也可在已激活环境运行：

```bash
python -m esptool --chip esp32c3 -p <实际串口> -b 460800 \
  write_flash 0x0 build/FoloToy-AI-Passport-full.bin
idf.py -p <实际串口> monitor
```

退出监视器用 `Ctrl+]`。固件编译或写入成功，均不等于设备测试通过。

只写应用分区时，先读设备现有分区表并核对布局，再写 `0x10000`：

```bash
python -m esptool --chip esp32c3 -p <实际串口> -b 460800 \
  read_flash 0x8000 0x1000 /tmp/device-parttable.bin
python -m esptool --chip esp32c3 -p <实际串口> -b 460800 \
  write_flash 0x10000 <归档目录>/FoloToy-AI-Passport.bin
```

`python -m esptool read_flash` 只能读出二进制，实际布局用 `gen_esp32part.py` 或构建目录的 `partition_table/partition-table.csv` 解析。

本次设备实测（2026-10-05，ESP32-C3，MAC `98:c3:77:f5:72:4c`，`/dev/cu.usbmodem2101`）：

| 分区 | 偏移 / 大小 |
| --- | --- |
| `nvs` | `0x9000` / 24 K |
| `phy_init` | `0xf000` / 4 K |
| `factory` | `0x10000` / 3 M |
| `cardid` | `0x356000` / 16 K |
| `easter` | `0x360000` / 388 K |
| `recovery` | `0x700000` / 1 M |

设备布局与仓库 `partitions.csv` 不同。只写应用分区可保留引导、分区表、NVS、`cardid`、`easter` 和 `recovery`。写入的应用镜像 SHA-256 为 `063c9519d1d94decfff33d170e0c6a5f8b5e5801d72aa3fda7902ed0d5e5a298`，与归档一致。

启动日志可核对三项：应用从 `0x10000` 加载、日志中的 ELF SHA-256 与归档 ELF 相同、程序输出 `Clock ready`。串口日志只证明固件启动，不能证明显示和按键正常。

时钟验收：

1. 上电后进入时钟页面，确认中文和大号时间完整可见。
2. 长按确定，依次调整年、月、日、时、分。
3. 在分钟页按确定，确认秒数归零并开始计时。
4. 测试月底、闰日和跨年进位。
5. 测试取消设置，确认运行时间不被草稿替换。
6. 测试 12/24 小时切换和三个亮度档位。
7. 重启后核对保存设置，并确认出现校时提示。
8. 观察电量、按键响应、长时间运行和实际走时误差。

## 来源

- [用户指定教程](https://ai-passport.folotoy.cn/guides/create-a-play-with-agent/)。
- [官方源码](https://github.com/FoloToy/ai-passport/tree/33d3d1d93a1125b356b47b6d83a7a60121be801e)。
- 本地 `source/AGENTS.md`、`source/docs/development/ai-guide.md` 和工程文档。
- [ESP-IDF 5.5.3](https://github.com/espressif/esp-idf/releases/tag/v5.5.3)。离线归档：`https://dl.espressif.cn/github_assets/espressif/esp-idf/releases/download/v5.5.3/esp-idf-v5.5.3.zip`。
- [LVGL 字体转换器](https://github.com/lvgl/lv_font_conv)。
- [Noto CJK 字体和许可](https://github.com/notofonts/noto-cjk)。

当前实际完成状态与未验证项以 [README](README.md) 为准。
