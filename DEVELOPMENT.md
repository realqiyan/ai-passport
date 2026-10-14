# AI Passport 开发手册

更新日期：2026-10-14。目标：ESP32-C3，8 MB Flash，无 PSRAM。ESP-IDF：5.5.3。

Linux 只维护源码、文档和不依赖设备的 Python 测试。以下恢复、安装、构建与刷机步骤仅在 Mac 执行。环境规则见 [AGENTS.md](AGENTS.md)，应用操作见[语音说明](voice/README.md)。所有命令从本仓库根目录执行，除非明确要求切换目录。

## 源码归属

维护源码在 `voice/firmware/` 与 `voice/bridge/`。`apply_voice.py` 将固件应用到固定官方基线，遇到独立修改时停止。

`source/` 是固定版本的官方源码子模块，通过 `git clone --recurse-submodules` 或 `git submodule update --init source` 恢复。它包含上游许可、BSP、构建脚本和文档。不要直接在子模块中修改或构建。

`voice-source/`、`.tools/`、虚拟环境与固件归档不纳入本仓库。Linux 只保留 `source/` 作 BSP 参考，不创建构建工作树或安装工具链。

## 恢复固件源码

在 Mac 执行。已有目录时先检查本地修改，已有工作树时跳过创建步骤。

```bash
git submodule update --init source
git -C source worktree add ../voice-source -b feature/voice-input 33d3d1d93a1125b356b47b6d83a7a60121be801e
python3 apply_voice.py
```

GitHub 下载受限时，可用 `git -c submodule.source.url=https://gitee.com/FoloToy/ai-passport.git submodule update --init source`。分支已存在而工作树缺失时，使用 `git -C source worktree add ../voice-source feature/voice-input`。用 `git -C source worktree list` 核对目录关系。以上步骤不恢复旧固件归档。

## 安装构建环境

先准备 Xcode Command Line Tools。已有工具链时核对版本并复用。

```bash
brew install cmake ninja actionlint
mkdir -p .tools
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
git clone --depth 1 --branch v5.5.3 --shallow-submodules --recursive \
  https://github.com/espressif/esp-idf.git .tools/esp-idf
AI_PASSPORT_PROJECT_ROOT="$(pwd)"
export IDF_TOOLS_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/espressif"
"${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/install.sh" esp32c3
```

官方工程的技能要求见 `source/AGENTS.md`。Mac 从本仓库根目录用 `python3 source/tools/install_passport_skills.py --install` 安装，再用 `--check` 核验。Linux 不执行此安装。

## Mac 构建与验证

从本仓库根目录打开 Bash：

```bash
python3 apply_voice.py
source env.sh
idf.py --version
cd voice-source
./tools/validate.sh
```

`idf.py` 应报告 5.5.3。完整门禁使用 `sdkconfig.defaults`、`dependencies.lock` 和隔离构建目录；不修改 `managed_components/`。

| 命令 | 用途 |
| --- | --- |
| `./tools/validate.sh --static` | 静态检查和主机测试 |
| `./tools/validate.sh --firmware` | 固件构建、合并镜像和分区校验 |
| `./tools/validate.sh` | 完整固件门禁 |
| `python3 tools/archive_firmware.py verify build/firmware/<归档哈希>` | 核对镜像及匹配 ELF、MAP |

交付使用本次成功门禁生成的归档。失败构建遗留的镜像不能作为新交付。固件身份保存在归档的 `manifest.json`，不在文档中重复复制哈希或构建日志。

## Linux 固定数据测试

从本仓库根目录运行。测试使用模拟对象或本地测试服务，不连接实体设备或操作系统音频设备。当前 Python 环境需已安装桥接依赖，可在项目虚拟环境中用 `python3 -m pip install -e ./voice/bridge` 安装。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=voice/bridge \
  python3 -m unittest discover -s voice/bridge/tests
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s voice/tests
git diff --check
```

需要 macOS 框架的测试会跳过。Linux 不运行固件门禁，不为测试安装 ESP-IDF。

## 开发约束

- 引脚与接口以 `source/components/bsp/include/` 为准；应用状态和任务放在 `voice/firmware/main/`。
- 按键回调只入队，音频、存储和网络工作由任务处理。访问 LVGL 时持有锁。
- 音频缓冲有界，断线后不重放旧按键，保存配置失败时保留已有 NVS。
- 再次开麦时先调用 `bsp_audio_wake()`，再初始化音频，避免休眠 codec 拒绝格式设置。

## Mac 刷机与验收

停止桥接和其他串口工具，使用 USB 数据线连接设备。先枚举串口，再指定应用镜像：

```bash
voice/flash.sh --list-ports
voice/flash.sh <串口> \
  voice-source/build/firmware/<归档哈希>/FoloToy-AI-Passport.bin
```

已有设备使用 `flash.sh`，只写 `0x10000` 应用分区并回读校验。脚本要求 ESP32-C3、未加密的 factory 分区及足够容量。此前设备的应用分区为 3 MB；不覆盖引导、分区表或 NVS。不要把合并镜像当应用镜像写入，也不执行全芯片擦除。

构建、刷写、启动检查和功能验收分别报告。设备功能按[按键表](voice/README.md#设备操作)和[省电验收](voice/POWER.md#实机验收)检查。
