# AI Passport 开发手册

更新日期：2026-10-05。官方基线：`33d3d1d93a1125b356b47b6d83a7a60121be801e`。目标芯片：ESP32-C3，8 MB Flash，无 PSRAM。工具链：ESP-IDF 5.5.3。

应用操作、Mac 安装与固件写入见[语音说明](voice/README.md)。当前结论与未决问题见[项目入口](README.md)。

## 本地目录

| 路径 | 用途 |
| --- | --- |
| `source/` | 官方基线检出，承载共享 Git 数据及完整工程 |
| `voice-source/` | 独立语音构建工作树 |
| `voice/firmware/`、`voice/bridge/` | 维护的固件、桥接源码与测试 |
| `apply_voice.py` | 安全应用源码和构建配置 |
| `.tools/esp-idf/` | ESP-IDF 5.5.3 源码 |
| `.tools/espressif/` | 编译器、Python 环境与下载缓存 |
| `.venv/`、`requirements-dev.txt` | 项目开发依赖 |
| `env.sh` | Bash 会话的环境入口 |
| `voice-source/build/firmware/` | 固件及匹配 ELF、MAP 的历史归档 |

官方工程和工具由工作区 Git 忽略。构建需使用完整官方工程；应用目录保存我们维护的改动。先修改 `voice/firmware/`，再运行 `apply_voice.py`。脚本遇到独立修改会停止，避免覆盖它们。

## 从空环境安装

在 macOS 上安装 Xcode Command Line Tools，并准备 CMake、Ninja 和 actionlint：

```bash
brew install cmake ninja actionlint
```

### 恢复固件源码

`source/` 和 `voice-source/` 被根仓库忽略，commit/push 不会上传它们。仅执行 `git clone`、`git pull` 或 `git restore` 无法恢复这些目录。此前本机恢复记录不适用于新检出的工作区。

两者都缺失时，从工作区根执行以下命令。先下载固定官方基线，再创建共享 Git 数据的语音工作树，最后应用维护源码：

```bash
git clone --filter=blob:none https://github.com/FoloToy/ai-passport.git projects/ai-passport/source
git -C projects/ai-passport/source checkout --detach 33d3d1d93a1125b356b47b6d83a7a60121be801e
git -C projects/ai-passport/source worktree add ../voice-source -b feature/voice-input 33d3d1d93a1125b356b47b6d83a7a60121be801e
python3 projects/ai-passport/apply_voice.py
```

`source/` 已存在时跳过克隆；先用 `git -C projects/ai-passport/source status --short` 检查本地修改，避免切换基线时覆盖它们。`voice-source/` 已存在时跳过 `worktree add`。分支 `feature/voice-input` 已存在而工作树缺失时，使用 `git -C projects/ai-passport/source worktree add ../voice-source feature/voice-input`。

两者恢复后，用 `git -C projects/ai-passport/source worktree list` 核对目录关系。官方最新分支可能与本基线不同；应用脚本只接受记录的提交。以上步骤恢复源码，不会恢复此前固件归档，也不会安装 ESP-IDF 工具链。

### 安装构建环境

准备项目开发环境与 ESP-IDF：

```bash
mkdir -p projects/ai-passport/.tools
python3 -m venv projects/ai-passport/.venv
projects/ai-passport/.venv/bin/python -m pip install -r projects/ai-passport/requirements-dev.txt
git clone --depth 1 --branch v5.5.3 --shallow-submodules --recursive \
  https://github.com/espressif/esp-idf.git projects/ai-passport/.tools/esp-idf
AI_PASSPORT_PROJECT_ROOT="$(cd projects/ai-passport && pwd)"
export IDF_TOOLS_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/espressif"
"${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/install.sh" esp32c3
```

已有安装先核对版本并复用。下载中断时保留缓存，按需恢复子模块：

```bash
git -C projects/ai-passport/.tools/esp-idf submodule update --init --recursive
```

此前 macOS 使用官方离线归档 `https://dl.espressif.cn/github_assets/espressif/esp-idf/releases/download/v5.5.3/esp-idf-v5.5.3.zip`。ESP-IDF 源码提交为 `2c211b236707889e8400c4dc5644dd5c4ee071e0`。使用离线包时核对版本、提交和子模块，再安装工具链。

下载工具时，可对当前命令设置 `IDF_GITHUB_ASSETS=dl.espressif.cn/github_assets`。组件下载可在当前 shell 设置 `IDF_COMPONENT_STORAGE_URL=https://components-file.espressif.cn`。保留 TLS 校验。

Linux 上若 OpenOCD 提示缺少 libusb，先检查系统库。当前主机保留了项目内的库，可在加载环境前设置：

```bash
export LD_LIBRARY_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/host-libs/usr/lib/$(gcc -print-multiarch):${LD_LIBRARY_PATH:-}"
```

官方工程要求的技能可通过已有安装器核验和安装：

```bash
python3 projects/ai-passport/source/tools/install_passport_skills.py --install
python3 projects/ai-passport/source/tools/install_passport_skills.py --check
```

## 构建与验证

从工作区根打开 Bash，运行：

```bash
python3 projects/ai-passport/apply_voice.py
source projects/ai-passport/env.sh
idf.py --version
cd projects/ai-passport/voice-source
./tools/validate.sh
```

`idf.py` 应显示 `ESP-IDF v5.5.3`。恢复后的门禁自动适配 macOS 链接器参数，无需临时编译器包装脚本。

| 命令 | 检查范围 |
| --- | --- |
| `./tools/validate.sh --static` | 仓库规则、工作流、BSP 与应用主机测试 |
| `./tools/validate.sh --firmware` | ESP-IDF 构建、镜像合并与分区检查 |
| `./tools/validate.sh` | 完整交付门禁 |
| `python3 tools/archive_firmware.py verify <归档目录>` | 固件与匹配 ELF、MAP 的归档一致性 |

完整门禁使用隔离构建目录，配置来自 `sdkconfig.defaults`。依赖以 `dependencies.lock` 为准；应用设置由 `apply_voice.py` 生成。保持 `managed_components/` 原样。

增量调试可运行 `idf.py build`。交付使用完整门禁生成的归档，记录应用哈希及匹配 ELF 身份。此前失败构建留下的镜像不能作为新交付。

## 开发约束

先读官方工程的 `AGENTS.md` 和相关说明。硬件引脚以 `components/bsp/include/bsp_pins.h` 为准，公共接口以 BSP 头文件为准。

- 驱动放在 `components/bsp/`；应用界面、状态和任务放在 `main/`。
- 按键回调只入队，音频和网络操作放在工作任务。
- 访问 LVGL 前取得 `bsp_lvgl_lock()`，操作后释放锁。
- 音频缓冲保持有界，断线后不重放旧快捷键。
- 保存配置失败时报告错误，保留已有 NVS。

## 刷机和设备验收

按[语音固件安装](voice/README.md#固件安装)指定串口与应用镜像。`flash.sh --list-ports` 只枚举设备，`flash.sh <串口> <应用镜像>` 检查分区后写入并回读校验。

此前设备回读布局为：

| 分区 | 偏移 / 大小 |
| --- | --- |
| `nvs` | `0x9000` / 24 KB |
| `phy_init` | `0xf000` / 4 KB |
| `factory` | `0x10000` / 3 MB |
| `cardid` | `0x356000` / 16 KB |
| `easter` | `0x360000` / 388 KB |
| `recovery` | `0x700000` / 1 MB |

此布局与官方默认不同。写入已核验的应用分区可保留引导、分区表和数据。完整镜像从 `0x0` 写入会改变布局，应按具体设备和授权另行处理。

固件构建和回读校验不能替代实机验收。检查页面、按键、音频、快捷键、输入设备还原、USB/Wi-Fi 连接及实际功耗。实体设备验证边界见[语音审查](voice/REVIEW.md)。
