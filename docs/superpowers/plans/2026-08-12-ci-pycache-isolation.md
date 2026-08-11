# TestRunner 字节码缓存隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除连续 pytest 轮次因同尺寸、同时间粒度源码改写而复用陈旧 `.pyc` 的间歇失败。

**Architecture:** `TestRunner.run()` 为每次 pytest 子进程创建独立 OS 临时字节码缓存目录，并通过子进程环境变量 `PYTHONPYCACHEPREFIX` 注入；现有进程控制、输出脱敏和公开接口保持不变。回归测试使用真实 TestRunner、真实 pytest、相同文件大小和固定修改时间，稳定证明修复前后的行为差异。

**Tech Stack:** Python 3.13、标准库 `tempfile` / `os` / `subprocess`、pytest、uv、Ruff。

## Global Constraints

- 仅修改 `mini-harness/src/fbw_harness/testing.py`、`mini-harness/tests/test_testing_feedback.py` 及本次过程文档。
- 不删除、遍历或修改用户工作区中的 `__pycache__`。
- 不改变 `TestRunner`、`HarnessConfig`、`TestResult`、`FeedbackEngine` 或 `AgentLoop` 的公开接口。
- 临时目录必须位于 OS 临时目录，并在成功、测试失败、超时和启动失败路径后清理。
- 继续遵守既有安全边界；工作区代码执行仍是已知限制，不新增 denylist 或系统级隔离。
- 必须先观察确定性回归 RED；若旧实现没有因陈旧 `.pyc` 失败，停止实现并返回根因调查。

---

### Task 1: 隔离每次 pytest 的字节码缓存

**Files:**
- Modify: `mini-harness/tests/test_testing_feedback.py`
- Modify: `mini-harness/src/fbw_harness/testing.py`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

**Interfaces:**
- Consumes: `TestRunner(config: HarnessConfig, *, known_secrets: tuple[str, ...]).run(workspace: Path | Workspace) -> TestResult`。
- Produces: 相同公开接口；每次内部 pytest 子进程获得唯一、短生命周期的 `PYTHONPYCACHEPREFIX`。

- [ ] **Step 1: 写入真实陈旧 `.pyc` 回归测试**

在 `test_testing_feedback.py` 新增测试。测试创建 `subject.py` 和 `test_subject.py`，第一次以错误值运行 pytest 生成缓存；随后写入等长正确值，并用 `os.utime(..., ns=...)` 恢复第一次源码时间戳。第二次仍通过同一个真实 `HarnessTestRunner` 运行：

```python
def test_runner_does_not_reuse_stale_bytecode_after_same_size_same_mtime_edit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    module = project / "subject.py"
    module.write_text("VALUE = 'wrong'\n", encoding="utf-8")
    (project / "test_subject.py").write_text(
        "from subject import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 'right'\n",
        encoding="utf-8",
    )
    original_stat = module.stat()
    runner = HarnessTestRunner(
        HarnessConfig(pytest_timeout_seconds=10, pytest_args=("-q",)),
        known_secrets=(),
    )

    first = runner.run(project)
    assert first.passed is False

    module.write_text("VALUE = 'right'\n", encoding="utf-8")
    os.utime(module, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = runner.run(project)

    assert second.passed is True
    assert second.exit_code == 0
    assert not (project / "__pycache__").exists()
```

该测试捕获的生产回归是：移除独立缓存注入后，第二次运行复用错误版 `.pyc` 并失败。

- [ ] **Step 2: 运行回归测试并确认 RED**

Run:

```powershell
uv run --project mini-harness pytest -q mini-harness/tests/test_testing_feedback.py::test_runner_does_not_reuse_stale_bytecode_after_same_size_same_mtime_edit
```

Expected: FAIL；第一轮失败，第二轮仍失败或工作区出现 `__pycache__`。如果测试直接通过，不修改生产代码，回到 systematic-debugging 根因调查。

- [ ] **Step 3: 写入最小生产实现**

在 `testing.py` 导入 `tempfile`。`TestRunner.run()` 先声明 `bytecode_cache: tempfile.TemporaryDirectory[str] | None = None`，再在现有启动异常边界内、构造 `Popen` 前创建 `TemporaryDirectory(prefix="fbw-harness-pycache-")`，复制环境并注入该目录：

```python
bytecode_cache = tempfile.TemporaryDirectory(prefix="fbw-harness-pycache-")
process_environment = os.environ.copy()
process_environment["PYTHONPYCACHEPREFIX"] = bytecode_cache.name
process_options["env"] = process_environment
```

将进程启动后的现有逻辑放入 `try/finally`，所有返回路径都调用一个私有、固定异常边界的清理函数：

```python
def _cleanup_bytecode_cache(cache: tempfile.TemporaryDirectory[str] | None) -> None:
    if cache is None:
        return
    try:
        cache.cleanup()
    except (OSError, ValueError):
        pass
```

临时目录创建、环境构造或 Popen 失败继续返回 `_start_failure(started)`；不得把临时绝对路径或底层异常写入 TestResult。

- [ ] **Step 4: 运行回归与 TestRunner 定向测试并确认 GREEN**

Run:

```powershell
uv run --project mini-harness pytest -q mini-harness/tests/test_testing_feedback.py
uv run --project mini-harness pytest -q mini-harness/tests/test_mechanism_demos.py -k feedback
```

Expected: 全部 PASS；回归测试第二轮通过，feedback 两项通过，无工作区 `__pycache__` 残留。

- [ ] **Step 5: 重复运行 feedback 稳定性测试**

Run:

```powershell
1..10 | ForEach-Object {
    uv run --project mini-harness pytest -q mini-harness/tests/test_mechanism_demos.py -k feedback
    if ($LASTEXITCODE -ne 0) { throw "feedback iteration $_ failed" }
}
```

Expected: 10 轮、20 个 feedback 测试全部 PASS。

- [ ] **Step 6: 运行完整门禁**

Run:

```powershell
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check mini-harness/src mini-harness/tests
uv run --project mini-harness ruff format --check mini-harness/src/fbw_harness/testing.py mini-harness/tests/test_testing_feedback.py
pwsh -NoProfile -File scripts/demo.ps1
pwsh -NoProfile -File scripts/scan-current-tree.ps1
git diff --check
```

Expected: `751 passed, 1 skipped`（新增一项回归测试）、Ruff/format/demo/scan/diff 全部退出 `0`。

- [ ] **Step 7: 更新正式过程证据**

在 `PLAN.md` 的 Task 14 后补充 CI hotfix 记录，在 `AGENT_LOG.md` 新增过程项，至少记录：两份失败 Actions、`.pyc` 根因、RED→GREEN、验证数量、commit 和 PR；不得记录凭据或工作区外绝对临时路径。

- [ ] **Step 8: 提交实现与证据**

Run:

```powershell
git add -- mini-harness/src/fbw_harness/testing.py mini-harness/tests/test_testing_feedback.py PLAN.md AGENT_LOG.md
git diff --cached --check
git commit -m "fix: 隔离 pytest 字节码缓存"
```

Expected: 提交只包含四个白名单文件；设计与计划提交保留为先前独立文档提交。

- [ ] **Step 9: 创建 hotfix PR 并验证远端**

推送 `fix/ci-pycache`，创建 PR；等待 branch push、pull_request 和合并后 main 的 `unit-test` 全部通过。若任何运行再次出现 feedback demo 失败，保留日志并停止合并，不用重跑伪装稳定。
