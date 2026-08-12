# 高输出压力测试超时余量修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 2 MB 双 pipe 压力强度，同时为 Windows CI 的逐字节流式脱敏提供与产品默认值一致的合理测试超时余量。

**Architecture:** 不修改产品 reader。只把目标压力测试的 Harness timeout 从 10 秒提高到 30 秒，依靠既有真实进程测试继续验证双 pipe、内存有界和输出截断，并以三类 GitHub CI 证明稳定性。

**Tech Stack:** Python 3.13、uv、pytest、Ruff、PowerShell 7。

## Global Constraints

- 只修改目标测试以及本 hotfix 的设计/计划文档。
- 保留 stdout/stderr 各 1 MB；不得降低压力强度。
- 不修改产品默认 60 秒 timeout、reader、脱敏或进程终止逻辑。
- 既有 branch push 的 10.17 秒 timeout 是真实 RED 证据。
- 若 30 秒仍失败，停止并重新设计，禁止继续增加 timeout。

---

### Task 1: 调整压力测试预算并恢复 CI

**Files:**
- Modify: `mini-harness/tests/test_testing_feedback.py`

**Interfaces:**
- Consumes: `HarnessConfig(pytest_timeout_seconds=...)` 与真实 `HarnessTestRunner`。
- Produces: 2 MB 双 pipe 压力测试在慢 Windows CI 上仍有界完成；产品接口不变。

- [x] **Step 1: 记录 RED 证据**

GitHub Actions run `31596557096`：目标测试 `timed_out=True`、exit 124、duration 10.17 秒；同提交 pull_request run 通过，表明是测试预算边界而非文档行为变更。

- [x] **Step 2: 做唯一测试变更**

```python
config = HarnessConfig(
    pytest_timeout_seconds=30,
    output_tail_chars=256,
    pytest_args=("-q", "-s"),
)
```

- [x] **Step 3: 连续运行压力测试 10 次**

循环执行目标 test node，记录 exit code 与 wall time。Expected: 10/10 passed、无 timeout。

- [x] **Step 4: 运行完整门禁**

```powershell
uv run --project mini-harness pytest mini-harness/tests/test_testing_feedback.py -q
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check mini-harness
uv run --project mini-harness ruff format --check mini-harness/tests/test_testing_feedback.py
pwsh -NoProfile -File scripts/scan-current-tree.ps1
git diff --check
```

- [ ] **Step 5: 提交、审查和 Hotfix PR**

Commit: `test: 放宽高输出压力测试超时余量`。独立审查无 Critical/Important 后创建 PR；branch/pull_request 两类 CI绿色后合并，main CI也必须绿色。

- [ ] **Step 6: 更新并恢复 PR #18**

将 `fix/history-secret-cleanup` rebase 到 hotfix 合并后的 main；用分支级 `force-with-lease` 更新 PR #18。两类 CI均绿色后才合并设计/计划基线并继续历史清理。
