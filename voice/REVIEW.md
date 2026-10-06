# 语音应用稳定性与 Mac 迁移审查

日期：2026-10-05。审查基线：工作区提交 `8316445`。本轮按用户要求审查代码、安装与卸载，并实现自动省电。设备刷写未在本轮执行。

2026-10-06 更新：已完成新的耗电排查，并按用户确认的续航优先取舍实现空闲停 Wi-Fi、自动浅睡眠、面板休眠与 Mac 自动重连。验证通过，新固件已在目标 Mac 重建并刷入设备，冷启动状态符合预期；功能与续航验收未做。最新省电结论、固件身份和验收计划见[耗电报告](POWER.md)；下文 2026-10-05 的省电说明保留为历史记录。

## Mac 令牌缺失提示修复

用户运行自动发现后已找到设备 IP，但本机缺少 `voice/.local/token`。该文件由 USB 配网生成，不随 Git 或设备应用刷写恢复。现在 Wi-Fi 会话先检查本地令牌，再执行发现或 TCP 连接；缺失时提示 USB 重新配网或指定已有令牌路径。

Host tests：PASS。桥接 62 项中 60 项通过、2 项因 Linux 缺少 macOS 框架跳过。新增测试验证手动 IP 和自动发现均在缺失令牌时停止连接，以及 USB 配网会生成权限 `0600` 的令牌并同步到设备命令，保留快捷键。固件未修改，未重复构建。用户 Mac 的 USB 配网与真实 Wi-Fi 认证仍待执行，恢复步骤见[说明](README.md#找到设备但缺少令牌)。

## Wi-Fi 自动发现更新

2026-10-05：此前配网只保存网络与令牌，`start.sh wifi` 首次运行还需要手动输入 IP。现在省略 IP 时，桥接向局域网发送 UDP `8765` 发现请求，等待 3 秒。每次启动重新发现；找到多台设备时停止并要求指定 IP。发现超时后尝试上次地址，兼容旧固件。

请求带随机编号，设备只响应格式有效的请求，最多每 100 毫秒响应一次。设备复用现有网络任务，不新增任务或定时器；退出 Wi-Fi 或丢失 IP 后关闭发现端口。发现报文不含配置或令牌，实际 TCP 会话仍校验令牌。自动发现成功且认证通过后才更新缓存地址。

Build：PASS。ESP-IDF 5.5.3 完整门禁和归档校验通过。应用 1,213,136 字节，SHA-256 `a3ae182fb8715bfa8a5c8fd2e2034e6ee1231742459016f5c071d36d2679d16a`。归档为 `../voice-source/build/firmware/c3fdf9fdaff86753adcf3c615bc14d7331f3fa3847dca6c481da0eb81a29d35e/`，完整镜像哈希与目录名一致。匹配 ELF SHA-256 为 `6fbb9e6bf7d08030c039e883f54a429fe87fbd4e18c02b68f9def6707a49f475`。已有设备使用 `flash.sh` 只写应用，保留分区与 NVS。

2026-10-06 本机重建并刷写：镜像大小同为 1,213,136 字节，哈希不同——应用 SHA-256 `c0bca8b522b11534110e7cae1d6902e0c2296bcb023e810f2e0749b6b27fa2d0`，ELF SHA-256 `3512193b…`，归档 `306f0ccd…`，门禁 0 失败、归档校验通过。`flash.sh` 只写 `0x10000` 应用分区，回读校验一致；启动日志显示从该分区加载，无 panic。Wi-Fi 自动发现的实机效果尚未验收。

Host tests：PASS。桥接 59 项中 57 项通过、2 项因 Linux 缺少 macOS 框架跳过；脚本与刷机测试 26 项通过，固件主机测试通过。新增检查覆盖本地 UDP 收发、错误编号丢弃、重复回复、多设备拒绝、旧地址更新、认证失败保留缓存、旧固件回退和带空格路径。

Device tests：NOT RUN。当前环境未发现串口设备。Unverified：Mac 本地网络权限、真实路由器广播、设备断线重连与 DHCP 地址变化。需同时更新 Mac 桥接与固件；使用旧固件时可手动指定 IP。操作见[Wi-Fi 使用](README.md#wi-fi-使用)。

## 命令安装入口（pipx）

2026-10-06：Mac 侧此前只有 `install.sh` 建的虚拟环境和 `start.sh <模式>`。按用户要求改为托管命令安装：桥接包 `passport-voice-bridge` 新增 `usb` 与 `wifi` 两个子命令，可用 `pipx install -e <voice>/bridge` 装到 pipx 的 bin 目录（本机为 `~/.local/bin`）。命令名保持 `passport-voice`，不新增别名。

`usb` 省略串口时取唯一的 `/dev/cu.usbmodem*`，零个或多个都停止并说明原因；`wifi` 给出地址时写入 `voice/.local/host` 并直连，省略时走自动发现。两者都先检查聚合设备是否存在，缺失只告警、不阻止启动。参数准备完成后用 `os.execv` 替换自身进程，实际运行的是 `passport-voice run …`，因此 `uninstall.sh` 仍按绝对 CLI 路径识别进程，只是模式同时覆盖项目虚拟环境和 pipx 两条路径。

`start.sh` 改为只转发参数的薄包装。`uninstall.sh` 增加 pipx 检测，确认后执行 `pipx uninstall passport-voice-bridge`；音频设备查询和聚合设备删除改用当前存在的那个环境。脚本沙箱为 `uninstall.sh` 提供 pipx 桩，避免测试触到真实安装。

Host tests：PASS。桥接 70 项、脚本与刷机固定数据测试 26 项在本机 macOS 全部通过。新增 8 项桥接测试覆盖串口选择、地址与选项分离、`host` 记忆和未知子命令；脚本测试覆盖参数原样转发、未安装桥接时的提示，以及 pipx 卸载的存在与缺失两种分支。

Device tests：NOT RUN。`pipx install -e` 已实测完成：`~/.local/bin/passport-voice` 指向 pipx 虚拟环境，帮助里出现 `usb` 与 `wifi`，无设备时 `usb` 给出预期提示并退出 1，给出串口时经 `exec` 进入 `run`。可编辑安装下默认路径仍解析到本项目的 `voice/.local/token` 与 `voice/.local/host`，未生成第二份状态目录。pipx 虚拟环境的 `bin/python` 解析到 Homebrew Python 3.14（`/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/bin/python3.14`），辅助功能授权需覆盖该解释器或运行它的终端；用 pipx 命令跑通一次完整出字尚未执行。

## pipx 迁移复查（2026-10-05）

此节保留修复前的发现与建议。当前结果见[迁移修复](#pipx-迁移修复2026-10-05)。

审查基线：`a02a358`。本轮在 Linux 审查入口、安装和卸载。仅更新审查文档，未修复运行代码，未执行真实安装或卸载。此前 macOS 的安装实测记录保留在上节。

### 已复现的问题

1. **P1：卸载未核验 pipx 包的源码归属。** `uninstall.sh` 第 17–19 行只按包名定位全局环境，第 45–46 行把其命令路径加入本目录进程匹配，第 123–125 行按包名卸载。若 pipx 安装指向目录 B，在目录 A 运行卸载仍会移除 B 的包；进程匹配也会把 B 当作本目录安装。沙箱在全局环境写入指向另一个源码目录的 `pipx_metadata.json` 后，卸载退出 0，并调用 `pipx uninstall passport-voice-bridge`。真实进程终止未执行；误停止的判断依据是构造的路径匹配规则。建议在停止进程或卸载之前，核验可编辑安装的实际源码路径与当前 `bridge` 路径一致。无法核验时保留该 pipx 安装。
2. **P2：省略地址时无法传入桥接选项。** `voice_bridge/cli.py` 第 373–379 行用 `argparse.REMAINDER` 接收参数。直接调用 `main(['wifi', '--shortcut', 'ctrl+shift+v'])` 或 `main(['usb', '--output', 'BlackHole 2ch'])`，均报 `unrecognized arguments` 并退出 2。显式地址加选项可正常进入 `launch`。现有 `test_launch.py` 直接调用 `usb`、`wifi`，因此绕过了出错的解析入口。建议让三个运行入口共用选项定义，并通过 `main(argv)` 检查省略地址、显式地址、带空格选项及未知选项。
3. **P2：模块启动方式在 usb/wifi 下失败。** `launch` 第 311–312 行把 `sys.argv[0]` 当脚本执行。经 `python -m voice_bridge.cli usb|wifi` 启动时，这个路径是包内 `cli.py`。子进程直接执行该文件，在 `from . import microphone` 处报 `ImportError: attempted relative import with no known parent package`。本轮捕获其 exec 参数，再在子进程执行，复现退出 1。此问题不影响当前控制台脚本入口。建议显式支持模块启动，或说明 usb/wifi 只支持控制台脚本；若改 exec 方式，需同步调整卸载的进程识别。

### 改进建议（尚未实施）

- **统一安装流程。** 当前是项目虚拟环境与 pipx 并存，`install.sh` 仍负责 BlackHole 检查和聚合设备创建；`start.sh`、`configure.sh` 仍只读取项目虚拟环境。因此只执行 pipx 安装不能完成现有快速开始流程。若目标是替代脚本，建议由 pipx 管理 Python 环境，并把系统检查、聚合设备准备和清理放入明确的应用子命令。旧脚本只保留参数转发。不要在包构建阶段创建系统设备。
- **明确清理顺序。** 直接 `pipx uninstall passport-voice-bridge` 不等于原来的完整卸载，它只移除 pipx 环境及导出的入口。聚合设备、源码目录中的令牌和地址缓存仍需应用清理步骤。先停止桥接并清理，再卸载包。[pipx 1.8.0 卸载实现](https://github.com/pypa/pipx/blob/1.8.0/src/pipx/commands/uninstall.py)支持此结论。
- **区分首次安装与更新。** README 的“可重复运行”不应被理解成更新依赖、入口元数据或切换源码目录。已存在的环境下，普通 `pipx install -e` 会保留原安装；源码文件修改可立即生效，元数据变化需要重装。参考 [pipx 1.8.0 安装实现](https://github.com/pypa/pipx/blob/1.8.0/src/pipx/commands/install.py)与 [pip 可编辑安装说明](https://pip.pypa.io/en/stable/topics/local-project-installs/)。
- **明确状态目录契约。** `DEFAULT_TOKEN` 按包文件位置计算，目前依赖可编辑安装。普通安装会把默认状态放入 pipx 环境的 `lib/pythonX.Y/.local/`，不再使用源码树的 `voice/.local/`。若要支持普通安装，建议使用固定的用户数据目录，并提供旧令牌迁移；若仅支持 `-e`，应明确这个限制。

### 验证与下一步

现有桥接测试运行 70 项：68 项通过，2 项因缺 macOS 框架跳过。脚本与刷机固定数据测试 26 项全部通过。命令如下：

```bash
PYTHONPATH=projects/ai-passport/voice/bridge python3 -m unittest discover -s projects/ai-passport/voice/bridge/tests -v
python3 -m unittest discover -s projects/ai-passport/voice/tests -v
```

额外复现使用 `unittest.mock` 与既有 `ScriptTests` 临时目录。没有修改系统音频、真实 pipx 环境或设备。当前环境没有 pipx；真实 pipx 生命周期、macOS 权限与完整语音输入仍待实机验证。

下一步：先修复卸载归属和 CLI 参数解析，再确定是否完成 pipx 单环境迁移。补测应覆盖 `main(argv)`、只存在 pipx 环境、其他源码目录的 pipx 安装，以及清理失败时保留状态。

## pipx 迁移修复（2026-10-05）

用户已授权修改上述全部发现与建议。本轮完成代码、兼容脚本、回归测试和使用说明；没有提交、推送或操作用户的 Mac 安装。

### 当前结果

- `usb`、`wifi`、`run` 共用选项定义。省略地址、带空格选项及未知选项都通过 `main(argv)` 测试。两个快捷入口直接调用运行函数，移除了依赖 `sys.argv[0]` 的 exec，模块启动不再直接执行包文件。
- `state.py` 负责用户状态目录和旧状态迁移。macOS 默认目录为 `~/Library/Application Support/passport-voice`。普通安装和可编辑安装共用这个目录，也可用 `PASSPORT_VOICE_STATE_DIR` 指定独立位置。令牌复制采用权限 `0600` 的临时文件，并发布完整文件，保留旧备份。令牌冲突或无效时停止；已有地址缓存优先，避免旧地址使重复 setup 失败。
- `lifecycle.py` 负责 `setup` 和 `cleanup`。setup 检查已加载的 BlackHole、核验已有聚合设备 UID、迁移旧状态，并按需创建设备。cleanup 在确认后停止当前环境及指定旧目录的桥接，等待退出，重新读取音频状态，再删除聚合设备及已知状态文件。进程或音频查询失败、其他安装仍运行、停止超时或默认输入未还原时停止。未知文件与自定义令牌路径保留。
- 清理覆盖控制台脚本的 `run`、`usb`、`wifi`、符号链接入口和模块启动。识别保留虚拟环境的解释器目录，避免将解释器符号链接解析到系统 Python 后混淆不同环境。普通命令参数中出现命令名称不会被当作桥接进程。
- 兼容脚本改用 pipx。共享 `bridge-command.sh` 核验实际包源码路径。其他目录、普通安装或无法核验的 pipx 环境会使仓库脚本停止；普通安装直接使用应用命令。uninstall 仅在 cleanup 成功后卸载包，再移除当前目录的旧环境。只有旧项目环境时，也先核验其源码来源。
- install 的首次安装与更新分开处理。已有同源环境使用 `--force` 刷新元数据和依赖；指定 `PYTHON` 时使用 `pipx reinstall --python`，避免 force 忽略解释器选择。脚本不再创建项目虚拟环境。
- README 说明首次安装、更新、解释器切换、状态迁移和清理顺序。取消 cleanup 返回非零状态，`cleanup && pipx uninstall` 不会继续卸载。相关知识文档已标注旧状态路径和旧进程形态的适用边界。

### 验证

Linux 固定数据验证：桥接 95 项中 93 项通过，2 项因缺 macOS 框架跳过。脚本与刷机测试 26 项全部通过。新增检查覆盖其他源码目录、只存在 pipx、首次安装、重复更新、解释器切换、迁移冲突、缓存更新、取消清理、清理失败、停止超时及清理后再卸载。Shell 语法检查和 `git diff --check` 通过。

隔离的真实安装验证：使用 pipx 1.8.0、Python 3.13.13，在包含空格的源码与环境目录中完成可编辑和普通安装。两种安装均可调用 `usb`、`wifi`、`setup`、`cleanup` 的帮助，模块入口可用；省略 USB 地址并传 `--output` 不再报解析错误，而是正常提示没有串口。两种安装使用同一指定用户状态路径。可编辑安装的 start 包装可转发参数。两种临时包均已通过 pipx 卸载。该验证使用 scratch 中的源码副本，不修改用户真实安装。

验证命令：

```bash
PYTHONPATH=projects/ai-passport/voice/bridge python3 -m unittest discover -s projects/ai-passport/voice/bridge/tests -v
python3 -m unittest discover -s projects/ai-passport/voice/tests -v
bash -n projects/ai-passport/voice/{install,uninstall,start,configure,bridge-command}.sh
git diff --check
```

实机边界：本轮没有执行 macOS 音频设备操作、辅助功能授权、真实串口连接或语音输入。下一步在 Mac 先停止旧桥接，安装或更新 pipx 包并执行 setup；核对令牌迁移、USB/Wi-Fi 出字、默认输入还原和完整卸载。固件未改动，未重复构建或刷写。

## 临时输入与安装入口更新（此前记录）

用户已确认：关麦时按确认临时开麦，完成输入后再次按确认结束并关麦。不使用静音判断。上键继续负责持续开麦。临时开麦在采集就绪后才投递快捷键；3 秒内无法就绪、链路断开或注入失败时关闭麦克风。

开始和结束发送同一个快捷键，需要输入法将该组合键设置为开始/结束切换。Mac 在开始事件前先选择聚合输入，避免快捷键比状态帧更早到达时选错麦克风。结束事件带会话编号；未成功开始或旧会话的结束事件不会触发新输入。

快捷键可用 `configure.sh [串口] --shortcut <组合键>` 保存到设备，也可用 `start.sh usb|wifi … --shortcut <组合键>` 仅覆盖本次运行。首次配置默认 Ctrl+Shift+V，已有保存值继续生效。设备校验范围与 Mac 支持的键码一致。

新增 `flash.sh --list-ports`，按路径列出串口、描述和 USB VID/PID，不打开设备。空列表会提示检查 USB 数据线，缺少 pyserial 会提示激活 ESP-IDF 或安装 esptool。缺少刷机参数时提示先枚举串口。固定数据测试覆盖列表、空列表、依赖缺失和无效参数。Linux 本机调用通过，当前没有串口设备。

新增 `flash.sh <串口> <应用镜像>`。它先检查 ESP32-C3 芯片标识、ESP-IDF 应用描述和项目名称，拒绝引导镜像或合并镜像。读取设备分区后，仅在 `0x10000` 为未加密 factory 分区且容量足够时写入。镜像使用检查前的私有副本，随后执行回读校验。没有擦除或写入 NVS 的命令。

当前验证：桥接 51 项中 49 项通过、2 项需 macOS 而跳过；脚本与刷机固定数据测试 25 项通过。测试覆盖临时输入开始/结束顺序、默认输入选择、旧会话丢弃、注入失败关麦、快捷键覆盖、分区不匹配、合并镜像拒绝，以及检查后源文件变更。C 测试及 UBSan 通过；完整固件门禁和归档校验通过。

当前应用为 1,212,512 字节，SHA-256 `a22d6a641a7be205864d3e4da6713d98f30eefc36a6bc84831769d6ec44cb692`。归档为 `../voice-source/build/firmware/8bd71c1dc3bc17e3e7c900e7c426d648f7d98c254c8b8987d246821f5098003b/`。实际刷写、确认键临时输入和输入法结束行为尚未实机验证。安装命令以 [使用说明](README.md#固件安装) 为准。

2026-10-06 更新：该应用已重建并刷入设备（归档 `bbd52b10…`，应用 SHA-256 `8661b8b0af43e7ec522f92ff0374d977a69a168b8ef076d0aeac630f72f11217`），回读校验一致、启动正常。确认键临时输入和输入法结束行为仍未实机验证。

2026-10-05 构建目录曾移入回收站，随后按用户要求恢复。Git 工作树关系正常；`apply_voice.py` 成功应用 12 个文件，当前语音固件归档校验通过。应用改动目录需要配合官方完整工程才能编译。

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

## 省电实现与边界（2026-10-05 历史版本）

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
