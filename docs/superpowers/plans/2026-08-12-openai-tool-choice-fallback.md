# OpenAI 工具选择兼容降级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让严格 OpenAI 工具调用在学校网关拒绝 `tool_choice="required"`（HTTP 400）时，只对当前 client 学习并降级为省略该参数，同时保留既有解析、安全和错误边界。

**Architecture:** `OpenAICompatibleClient` 初始仍发送 `tool_choice="required"`。一个受限的请求辅助方法只在安全读取得到精确 HTTP 400 时，把实例状态切换为 tools-only 并立即重发一次；后续 `decide()` 直接使用 tools-only，所有响应仍进入原有 `_to_raw_decision()` 上限和唯一工具解析链。

**Tech Stack:** Python 3.12、uv、OpenAI Python SDK、pytest、Ruff、PowerShell 7。

## Global Constraints

- 仅修改 `mini-harness/src/fbw_harness/llm.py`、`mini-harness/tests/test_llm_context_parser.py` 和批准的正式文档。
- 不输出响应正文、异常文本、API Key 或 Base URL；公开构造器、factory 接口和固定错误文本保持不变。
- 仅 HTTP 400 可触发兼容降级；401/403、429、5xx、连接错误、超时和畸形响应保持既有语义。
- 一个 client 只学习一次；新 client 必须重新从严格模式开始。
- 按 RED → GREEN → 全量门禁执行；不得先改生产代码。
- 真实 API 只访问用户已授权的 `https://njusehub.info/v1`；结束时清除 CredentialStore，并只删除已确认位于系统临时目录内的本次 clamp 项目。

---

### Task 1: 用失败测试锁定兼容降级契约

**Files:**
- Modify: `mini-harness/tests/test_llm_context_parser.py`
- Test: `mini-harness/tests/test_llm_context_parser.py`

**Interfaces:**
- Consumes: `OpenAICompatibleClient(client: object, model: str, max_retries: int = 2)`；既有 `_FakeSDK` 与 `_HTTPFailure`。
- Produces: 精确锁定 required 400 降级、实例记忆、错误分类及脱敏异常图的回归测试。

- [ ] **Step 1: 写入 required 400 后同轮 tools-only 成功的失败测试**

```python
def test_client_falls_back_without_tool_choice_after_required_http_400():
    sdk = _FakeSDK([_HTTPFailure(400), _sdk_response(("list_files", "{}"))])
    client = OpenAICompatibleClient(client=sdk, model="model")

    decision = client.decide([], [])

    assert decision.tool_calls[0].name == "list_files"
    assert sdk.chat.completions.calls[0]["tool_choice"] == "required"
    assert "tool_choice" not in sdk.chat.completions.calls[1]
```

- [ ] **Step 2: 写入实例记忆、新实例严格模式与非 400 不降级测试**

```python
def test_client_remembers_tools_only_mode_after_fallback():
    sdk = _FakeSDK([
        _HTTPFailure(400),
        _sdk_response(("list_files", "{}")),
        _sdk_response(("list_files", "{}")),
    ])
    client = OpenAICompatibleClient(client=sdk, model="model")
    client.decide([], [])
    client.decide([], [])
    assert ["tool_choice" in call for call in sdk.chat.completions.calls] == [True, False, False]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_non_400_status_never_uses_compatibility_fallback(status):
    sdk = _FakeSDK([_HTTPFailure(status)] * 3)
    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$"):
        OpenAICompatibleClient(client=sdk, model="model", max_retries=0).decide([], [])
    assert len(sdk.chat.completions.calls) == 1
```

- [ ] **Step 3: 写入第二次 400 和恶意状态属性的固定错误测试**

```python
def test_fallback_failure_is_fixed_and_not_repeated():
    sdk = _FakeSDK([_HTTPFailure(400), _HTTPFailure(400)])
    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])
    assert len(sdk.chat.completions.calls) == 2
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
```

- [ ] **Step 4: 运行选择测试并确认 RED 原因**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_llm_context_parser.py -k "fallback or tools_only or compatibility" -q`

Expected: 新增测试因现有客户端每次都固定发送 `tool_choice="required"` 而失败；既有测试不应出现收集错误。

### Task 2: 最小实现 client 级 400 兼容状态

**Files:**
- Modify: `mini-harness/src/fbw_harness/llm.py`
- Test: `mini-harness/tests/test_llm_context_parser.py`

**Interfaces:**
- Consumes: OpenAI SDK `chat.completions.create(**kwargs)`；异常的可选内建整数 `status_code`。
- Produces: `OpenAICompatibleClient.decide(...) -> RawDecision`，公开签名不变；新增私有布尔状态与私有安全状态码判断。

- [ ] **Step 1: 给 client 增加严格模式状态**

```python
class OpenAICompatibleClient:
    __slots__ = ("_client", "_max_retries", "_model", "_use_required_tool_choice")

    def __init__(...):
        ...
        self._use_required_tool_choice = True
```

- [ ] **Step 2: 提取单次请求并只对精确 400 降级**

```python
def _create_completion(self, messages, tools):
    kwargs = {"model": self._model, "messages": messages, "tools": tools}
    if self._use_required_tool_choice:
        kwargs["tool_choice"] = "required"
    try:
        return self._client.chat.completions.create(**kwargs)
    except Exception as error:
        if self._use_required_tool_choice and _has_http_status(error, 400):
            self._use_required_tool_choice = False
            return self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
            )
        raise
```

`_has_http_status()` 必须捕获状态属性读取异常，只接受 `type(status_code) is int`，不读取或拼接异常正文。

- [ ] **Step 3: 让 `decide()` 复用单次请求辅助方法**

将循环内直接 SDK 调用替换为 `_create_completion(messages, tools)`；第二次调用失败仍由既有统一异常边界决定是否重试。非瞬态 400 立即映射为固定 `LLMDecisionError`，不再次执行兼容降级。

- [ ] **Step 4: 运行新增测试并确认 GREEN**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_llm_context_parser.py -k "fallback or tools_only or compatibility" -q`

Expected: 新增测试全部通过。

- [ ] **Step 5: 运行完整 Task 9 回归**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_llm_context_parser.py -q`

Expected: 全部通过，无 warning。

### Task 3: 运行门禁并完成真实 API clamp 验证

**Files:**
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/evidence/release-checklist.md`
- Modify: `docs/evidence/ci-last-pass.md`

**Interfaces:**
- Consumes: 已配置 CredentialStore、一次性 clamp 项目、学校 OpenAI-compatible endpoint。
- Produces: 本地自动化门禁、真实 RunResult、pytest 修复结果以及不含凭据/响应正文的正式证据。

- [ ] **Step 1: 运行完整本地门禁**

Run:

```powershell
uv run --project mini-harness pytest -q
uv run --project mini-harness ruff check mini-harness
uv run --project mini-harness ruff format --check mini-harness/src/fbw_harness/llm.py mini-harness/tests/test_llm_context_parser.py
pwsh -File scripts/scan-current-tree.ps1
git diff --check
```

Expected: pytest 0 failures；Ruff、format、秘密扫描、diff check 均 exit 0。

- [ ] **Step 2: 用真实 CLI 修复一次性 clamp 项目**

Run: `uv run --project mini-harness fbw-harness run --workspace <已确认的临时 clamp 目录> --task "修复 clamp 边界错误，使全部单元测试通过" --base-url https://njusehub.info/v1 --model deepseek-v4-flash`

Expected: RunResult 成功，修改路径仅为临时项目内 `clamp.py`，随后该项目 `pytest -q` 为 3 passed。若模型仍失败，只记录结构化失败类别、轮数、修改路径和回滚状态，不记录响应正文。

- [ ] **Step 3: 回写正式证据**

在 `PLAN.md`、`AGENT_LOG.md`、`docs/evidence/release-checklist.md` 和 `docs/evidence/ci-last-pass.md` 记录：兼容根因、设计边界、自动化门禁、真实任务结果，以及 WebUI/历史 Key/干净新机等仍存在的门禁；不得把单次 API 成功描述为公开发布已合规。

- [ ] **Step 4: 最终清理敏感和临时状态**

Run:

```powershell
uv run --project mini-harness fbw-harness credential clear
uv run --project mini-harness fbw-harness credential status
```

Expected: `configured=False`。随后解析并核对临时 clamp 目录确实位于 `$env:TEMP` 且名称精确以 `fbw-real-api-` 开头，再删除该目录；不删除其他临时目录。

- [ ] **Step 5: 最终复验并提交**

Run: 重复 Step 1 全部门禁；检查 `git status --short` 和 staged diff，确保只提交批准范围内文件。

Commit: `fix: 兼容不支持 required 的工具调用网关`

