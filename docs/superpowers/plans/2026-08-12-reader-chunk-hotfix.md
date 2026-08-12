# 高输出 reader 分块性能修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 pipe 读取粒度与输出尾部保留上限解耦，避免高输出测试在 CI 性能波动下超过固定 pytest 超时。

**Architecture:** `_TailReader` 仍通过后台线程持续 drain、先流式脱敏再保留有界尾部，只把每次 `read()` 请求大小改为固定 8192 bytes。一个内存 stream 测试直接锁定真实 read 行为，既有双 pipe 集成测试继续验证进程、内存和输出结果。

**Tech Stack:** Python 3.13、uv、pytest、Ruff、PowerShell 7。

## Global Constraints

- 只修改 `testing.py`、对应测试和本 hotfix 设计/计划文档。
- 不增加 `pytest_timeout_seconds`，不减少 stdout/stderr 各 1 MB 的压力输出。
- 不改变 tail 上限、先脱敏后截断、诊断扫描、双线程、进程终止或固定错误语义。
- 必须先看到确定性测试按预期 RED，再写生产改动。
- branch push、pull_request、main 三类 CI 都必须绿色，之后才能恢复 PR #18。

---

### Task 1: 固定 pipe 读取块并验证压力边界

**Files:**
- Modify: `mini-harness/src/fbw_harness/testing.py`
- Modify: `mini-harness/tests/test_testing_feedback.py`

**Interfaces:**
- Consumes: `_TailReader(stream: BinaryIO | None, limit: int, known_secrets: tuple[str, ...])`。
- Produces: reader 对任何合法 tail limit 都以 8192 bytes 请求 pipe read；最终输出仍不超过 tail limit。

- [ ] **Step 1: 写确定性的失败测试**

```python
def test_tail_reader_uses_efficient_reads_independent_of_tail_limit() -> None:
    class RecordingStream(BytesIO):
        def __init__(self, payload: bytes) -> None:
            super().__init__(payload)
            self.requested_sizes: list[int] = []

        def read(self, size: int = -1) -> bytes:
            self.requested_sizes.append(size)
            return super().read(size)

    stream = RecordingStream(b"x" * 20_000)
    reader = testing_module._TailReader(stream, 256, ())
    reader.start()

    output = reader.finish()

    assert stream.requested_sizes == [8192, 8192, 8192, 8192]
    assert output == "x" * 256
```

四次请求分别读取 8192、8192、剩余 3616、EOF；旧实现会记录大量 256，测试必须 RED。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_testing_feedback.py::test_tail_reader_uses_efficient_reads_independent_of_tail_limit -q`

Expected: 仅 read-size 断言失败，实际首个请求为 256。

- [ ] **Step 3: 写最小生产修复**

```python
_PIPE_READ_CHUNK_BYTES = 8192


def _drain(self) -> None:
    ...
    while chunk := self._stream.read(_PIPE_READ_CHUNK_BYTES):
        ...
```

删除局部 `chunk_size = min(8192, self._limit)`；其他代码不改。

- [ ] **Step 4: 运行确定性测试确认 GREEN**

重复 Step 2 命令。Expected: 1 passed。

- [ ] **Step 5: 连续运行真实双 pipe 压力测试 10 次**

循环执行 `test_runner_bounds_stdout_and_stderr_while_draining_both_pipes`，记录每次 exit code 与 wall time。Expected: 10/10 passed，没有 `timed_out=True`。

- [ ] **Step 6: 运行完整门禁**

```powershell
uv run --project mini-harness pytest mini-harness/tests/test_testing_feedback.py -q
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check mini-harness
uv run --project mini-harness ruff format --check mini-harness/src/fbw_harness/testing.py mini-harness/tests/test_testing_feedback.py
pwsh -NoProfile -File scripts/scan-current-tree.ps1
git diff --check
```

Expected: pytest 0 failures；其余全部 exit 0。

- [ ] **Step 7: 提交、独立审查与 PR**

Commit: `fix: 提高高输出 reader 处理效率`。独立审查只检查本 hotfix；无 Critical/Important 后推送并创建 PR，等待 branch/pull_request 两类 CI绿色后合并，再等待 main CI绿色。

- [ ] **Step 8: 恢复 PR #18**

将 `fix/history-secret-cleanup` rebase 到 hotfix 合并后的新 main，使用带租约的普通分支 force-with-lease 更新 PR #18；两类 CI均绿色后才继续历史清理 Task 1。
