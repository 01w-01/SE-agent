# FBW Coding Agent Harness

FBW 是面向 Windows 的 Python Coding Agent Harness。它把 OpenAI 兼容 LLM 的一次决策置于可测试的应用层、策略层与文件事务之内，用于在用户指定的 Python 工作区中完成受控的小型修复。

首版是**纯 CLI**，不提供 WebUI。CLI 只是适配器；`ApplicationService`、结构化事件、审批和运行结果保持 UI 无关，未来可增加其他入口而不重写核心。

## 获取与安装

### Windows x64 发行物（无需安装 Python）

从 GitHub Release 下载 `fbw-harness.exe` 与 `fbw-harness.exe.sha256` 到同一目录，并在 PowerShell 复核：

```powershell
$expected = (Get-Content .\fbw-harness.exe.sha256).Split()[0]
$actual = (Get-FileHash .\fbw-harness.exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'SHA-256 verification failed' }
.\fbw-harness.exe --help
```

首版未进行代码签名，Windows SmartScreen 可能显示警告；只应从项目 Release 获取文件，先完成 SHA-256 校验，再按组织的安全政策决定是否运行。

### 源码方式（开发与测试）

需要 Windows、Python 3.13 和 [uv](https://docs.astral.sh/uv/)：

```powershell
uv run --project mini-harness fbw-harness --help
uv run --project mini-harness pytest -q
```

## 首次安全配置 Key

真实任务使用 Windows Credential Manager，而不是命令行参数、环境变量、TOML、`.env` 或日志。首次运行请在可信的本地终端输入：

```powershell
fbw-harness credential set
fbw-harness credential status
```

`credential set` 通过隐藏输入读取 Key；`status` 只显示是否配置，不回显 Key。需要移除凭据时运行：

```powershell
fbw-harness credential clear
```

## 运行命令与示例

离线机制演示不需要网络、真实 Key 或用户项目：

```powershell
fbw-harness demo guardrail
fbw-harness demo feedback
fbw-harness demo no-progress
fbw-harness demo all
```

对一个专门准备的临时 Python 项目运行真实任务：

```powershell
fbw-harness run `
  --workspace D:\temp\example-project `
  --task '修复 clamp 的边界条件并通过 pytest' `
  --base-url https://api.example.invalid/v1 `
  --model deepseek-v4-flash
```

只有可信、可丢弃或已备份的工作区才适合运行真实任务。高风险动作会显示规则和原因并等待确认；禁止动作会在工具调用前被拒绝。

## 目录结构

```text
mini-harness/             Python 包、测试、PyInstaller spec
scripts/                  当前树/历史凭据扫描、演示与本地构建
.github/workflows/        Windows 验证与 tag 发布工作流
.gitlab-ci.yml            课程要求的 unit-test job
SPEC.md                   已批准规格与风险登记
AI4SE_Final_Project_A_Coding_Agent_Harness.md  课程任务说明
```

## 测试与三项机制演示

```powershell
pwsh -NoProfile -File scripts/scan-current-tree.ps1
uv run --project mini-harness ruff check mini-harness/src mini-harness/tests
uv run --project mini-harness pytest -q
pwsh -NoProfile -File scripts/demo.ps1
```

三项离线演示分别覆盖：

- `guardrail`：危险或越界动作被策略和人工确认关卡拦截；
- `feedback`：真实 pytest 反馈驱动下一轮受控修改；
- `no-progress`：重复无进展时停止并回滚。

`pytest` 会以当前 Windows 用户权限执行工作区代码；它不是 OS 沙箱，不能把演示或测试当成针对不可信代码的隔离措施。

## 分发与本地构建

在源码工作树生成 Windows x64 单文件与校验文件：

```powershell
pwsh -NoProfile -File scripts/build.ps1
.\dist\fbw-harness.exe --help
.\dist\fbw-harness.exe demo all
Get-FileHash .\dist\fbw-harness.exe -Algorithm SHA256
```

构建脚本先执行单元测试和当前树凭据扫描；成功后才发布 `dist/fbw-harness.exe` 与只含 SHA-256 和文件名的 `dist/fbw-harness.exe.sha256`。`dist/` 是本地验证产物，不提交到 Git。

## 安全边界与凭据威胁模型

本项目的正式安全边界仅包括三项：

1. 工作区路径围栏；
2. 动作级策略分类与高风险操作的 HITL；
3. 逐文件事务与回滚。

API Key 仅由 Windows Credential Manager 保存；CLI、配置、JSONL、记忆、控制台事件与测试输出不应记录 Key、请求头或完整敏感上下文。当前树扫描在每次验证中运行；完整历史扫描在 tag/release 前运行，任何命中都会阻断发布，且只输出 commit SHA 与路径，不输出匹配文本。

能力 denylist/模式扫描只是 best-effort 提示层，不是完整安全保证。`pytest` 以当前用户权限执行工作区代码，明确不在以上三项安全边界内；需要隔离不可信代码时应使用容器、独立虚拟机或系统级沙箱。

## 已知限制与课程偏离

- 首版仅支持 Windows 10/11 x64、纯 CLI 和 Python/pytest 项目；不提供 WebUI、macOS 或 Linux 发行物。
- PyInstaller 产物尚未代码签名，需处理 SmartScreen 提示并自行复核 SHA-256。
- 路径与哈希检查不能消除本地恶意进程的 TOCTOU 风险。
- 当前完整 Git 历史含用户接受的临时学校 API Key。`scripts/scan-history.ps1` 因此会退出 `1` 并阻断 tag/release；在历史被合规处理前，项目不具备发布就绪状态。

## 第三方依赖与许可证

运行时依赖为 [OpenAI Python SDK](https://github.com/openai/openai-python)（Apache-2.0）和 [keyring](https://github.com/jaraco/keyring)（MIT）。开发/发行依赖包括 [pytest](https://github.com/pytest-dev/pytest)（MIT）、[Ruff](https://github.com/astral-sh/ruff)（MIT）、[PyInstaller](https://pyinstaller.org/)（GPL-2.0-or-later，含其运行时例外）与 [uv](https://github.com/astral-sh/uv)（MIT 或 Apache-2.0）。以各上游仓库随版本发布的许可证文本为准。

仓库目前未单独附带本项目源码许可证；使用、复制或发布前请先取得作者授权。

## 课程文档索引

- [正式规格](SPEC.md)
- [课程任务说明](AI4SE_Final_Project_A_Coding_Agent_Harness.md)
- [过程记录](SPEC_PROCESS.md)
- [实现日志](AGENT_LOG.md)
- [机制设计](docs/superpowers/specs/2026-08-08-coding-agent-harness-demo-design.md)
