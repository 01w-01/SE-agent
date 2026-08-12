# 干净 Windows EXE 自动验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用手动 GitHub Actions 在全新 Windows runner 上验证单文件 EXE 的离线运行、SHA 与无凭据状态，并留下可下载 artifact 和正式证据。

**Architecture:** 新增独立 `workflow_dispatch` 工作流和一个只负责 EXE 运行期验收的 PowerShell 脚本。构建继续复用 `scripts/build.ps1`；验收脚本在隔离临时目录和不含 Python/uv 的 PATH 中运行 exe，工作流只读且不创建 tag/Release。

**Tech Stack:** GitHub Actions、Windows Server hosted runner、PowerShell 7、uv、PyInstaller、pytest。

## Global Constraints

- 不使用或读取 LLM API Key，不执行真实任务。
- 不创建 tag、Release 或持久凭据。
- 运行 EXE 的子进程 PATH 只含 Windows System32、Windows、Wbem 和 PowerShell 7。
- hosted runner PASS 不冒充 Explorer SmartScreen、实体 Windows 10/11、交互 `credential set` 或真实 API 验收。
- artifact 只包含 exe、SHA 和固定字段摘要。

---

### Task 1: 工作流合同与运行期验收脚本

**Files:**
- Create: `.github/workflows/clean-windows-acceptance.yml`
- Create: `scripts/verify-clean-windows.ps1`
- Modify: `mini-harness/tests/test_distribution_files.py`

**Interfaces:**
- Consumes: `scripts/build.ps1` 生成的 `dist/fbw-harness.exe` 与 `.sha256`。
- Produces: `scripts/verify-clean-windows.ps1 -Artifact <exe> -Checksum <sha> -Summary <txt>`；成功 exit 0，失败抛固定验收错误。

- [ ] **Step 1: 写合同 RED**

在 `test_distribution_files.py` 新增测试，要求独立 workflow：仅 `workflow_dispatch`、`contents: read`、调用 build/verify、上传三项 artifact、不含 release action；并要求验收脚本包含 SHA、受限 PATH、`--help`、`demo all`、`credential status` 与临时目录 finally 清理。

- [ ] **Step 2: 运行 RED**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_distribution_files.py -q`

Expected: FAIL，缺少 workflow/验收脚本。

- [ ] **Step 3: 实现最小验收脚本**

脚本校验输入文件、解析两列 SHA、复制 artifact 到唯一 `$env:RUNNER_TEMP/fbw-clean-<guid>`，以 `System.Diagnostics.ProcessStartInfo` 为每个命令设置受限 PATH 并捕获退出码；依次运行 `--help`、`demo all`、`credential status`，写固定摘要，finally 删除临时目录。输出不得包含命令完整 stdout/stderr 或环境变量。

- [ ] **Step 4: 实现手动 workflow**

`windows-latest` checkout `fetch-depth: 0`，setup-uv Python 3.13，运行双扫描、`build.ps1`、验收脚本，上传 `dist/fbw-harness.exe`、SHA 和摘要；只使用 `actions/checkout@v4`、`astral-sh/setup-uv@v6`、`actions/upload-artifact@v4`。

- [ ] **Step 5: GREEN 与门禁**

Run:

```powershell
uv run --project mini-harness pytest mini-harness/tests/test_distribution_files.py -q
uv run --project mini-harness ruff check mini-harness
pwsh -NoProfile -File scripts/scan-current-tree.ps1
pwsh -NoProfile -File scripts/scan-history.ps1
git diff --check
```

Expected: 全部 exit 0。

- [ ] **Step 6: 提交、PR 与真实 workflow**

提交 `ci: 添加干净 Windows EXE 验收`，创建 PR；branch/pull_request CI 绿色后合并。用 `gh workflow run clean-windows-acceptance.yml --ref main` 手动触发；必须等待 build、SHA、三个 EXE 命令和 artifact 全部绿色。

### Task 2: 回写验收证据并收尾

**Files:**
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `README.md`
- Modify: `docs/evidence/release-checklist.md`
- Create: `docs/evidence/clean-windows-exe.md`

**Interfaces:**
- Consumes: 手动 workflow run URL、main SHA、artifact 名称和步骤结论。
- Produces: 明确区分 PASS 与未覆盖范围的课程验收证据。

- [ ] **Step 1: 写证据**

记录 workflow URL、main SHA、runner、build/SHA/help/demo/status/artifact 结论；将“GitHub hosted clean Windows EXE”改为 PASS。SmartScreen、实体 Windows 10/11、交互凭据和真实 API 保持未覆盖；不记录环境详情或秘密。

- [ ] **Step 2: 更新发布结论**

README/PLAN/AGENT_LOG/清单明确：云端离线 EXE 验收已通过；WebUI 有意偏离仍阻止声称课程清单完全满足。是否创建 tag/Release仍需用户单独决定。

- [ ] **Step 3: 验证并提交**

运行双扫描、分发合同、Ruff、diff check；提交 `docs: 记录干净 Windows EXE 验收`，推送同一分支或后续小 PR，并等待 GitHub CI绿色。

- [ ] **Step 4: 同步与清理**

合并证据 PR，普通推送 NJU main；用户确认最新 Pipeline绿色后删除功能分支/worktree。根仓库只保留main与三份未跟踪进度文件。
