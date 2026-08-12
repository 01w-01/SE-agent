# FBW Coding Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Windows 优先、可打包为单文件 CLI 的 Coding Agent Harness，在受控工作区内调用真实或 Mock LLM，执行安全文件操作，以 pytest 反馈驱动多轮修正，并提供可重复的治理、反馈和停机机制演示。

**Architecture:** 采用同步单进程状态机和端口/适配器边界。`CLIAdapter` 只负责终端解析与渲染，`ApplicationService`、`AgentLoop`、治理、事务、测试、反馈和记忆均不依赖终端；真实 LLM 与 Mock LLM 通过同一 `LLMClient` 协议进入同一个循环。

**Tech Stack:** Python 3.13、uv、pytest、OpenAI Python SDK、keyring/Windows Credential Manager、PyInstaller、GitLab CI、GitHub Actions、PowerShell 7。

## Global Constraints

- 目标平台为 Windows 10/11 x64；正式构建固定使用 Python 3.13 x64。
- 首版只实现 CLI，不实现 WebUI；核心包不得导入 `argparse`，不得调用 `input()` 或直接 `print()`。
- 未来界面通过 `RunRequest`、`EventSink`、`ApprovalProvider`、`RunResult` 接入，不创建空 WebUI 占位实现。
- 模型只能请求 `list_files`、`read_file`、`create_file`、`edit_file`、`finish`，每轮只接受一个动作。
- 永久禁止任意 PowerShell/shell、删除、移动、重命名、工作区越界、`.git`、凭据文件和重解析点访问。
- 普通受控读取/创建/精确修改自动执行；依赖、CI、已有脏文件、大范围或危险能力修改需要审批。
- 直接修改目标项目，但每个写动作必须经过规范路径、首次快照、SHA-256、原子替换和失败回滚。
- 每次代码写入后固定运行 pytest；最近测试未通过时拒绝 `finish`。
- 默认最多 6 个模型动作轮、2 次临时网络重试、60 秒 pytest、256 KiB 单文件、200 行普通修改、12,000 字符输出尾部；连续 2 轮相同动作与反馈指纹判定无进展。
- API Key 只由 Windows Credential Manager 保存；不得进入 CLI 参数、环境变量、TOML、`.env`、日志、记忆或新提交。
- 当前 Git 历史不重写；正式编码从 Task 1 开始，每个 task 使用独立 branch + worktree，经测试和两阶段评审后通过 PR 合并到 `main`。
- 每项功能严格执行 `test-driven-development`：先看到目标测试按预期失败，再写最小实现，最后重构并运行相关测试与全量测试。
- 每个 task 的实现提交后，调用 `requesting-code-review` 做“SPEC 合规”和“代码质量”两阶段评审；修正通过后再创建 PR。
- `PLAN.md` 每完成一个 task 必须勾选并记录实现 commit/PR；`AGENT_LOG.md` 同步记录技能、agent、人工修改和验证输出。
- 未解决的 WebUI 课程冲突和历史 Key 冲突不得被描述为已经合规；最终发布必须经过 Task 14 门禁。

---

## 1. 文件结构与职责

```text
mini-harness/
├── pyproject.toml                 项目元数据、依赖、CLI entry point、pytest/ruff 配置
├── uv.lock                        uv 锁文件
├── fbw-harness.spec               PyInstaller 固定构建配置
├── README.md                      Python 包简述并指向根 README
├── src/fbw_harness/
│   ├── __init__.py                版本与公共包边界
│   ├── models.py                  枚举和不可变领域数据模型
│   ├── ports.py                   LLM、凭据、事件、审批协议
│   ├── errors.py                  稳定错误类型与退出语义
│   ├── config.py                  TOML/CLI 非秘密配置与校验
│   ├── credentials.py             Credential Manager 安全存储
│   ├── workspace.py               路径围栏、文件发现与只读工具
│   ├── transactions.py            创建/精确修改、快照、原子写、提交/回滚
│   ├── policy.py                  ALLOW/CONFIRM/DENY 和风险事实
│   ├── testing.py                 固定 pytest 子进程、超时与进程树终止
│   ├── feedback.py                失败分类、脱敏、摘要和稳定指纹
│   ├── context.py                 上下文优先级、预算和反馈回灌
│   ├── parser.py                  单一 tool call 到 Action 的严格解析
│   ├── llm.py                     OpenAI 兼容客户端、重试和工厂
│   ├── mock_llm.py                确定性脚本化 LLM
│   ├── memory.py                  默认关闭的白名单项目记忆
│   ├── loop.py                    AgentLoop 状态机、工具分发和停机
│   ├── app.py                     ApplicationService 组合与 RunResult
│   ├── cli.py                     argparse、隐藏输入、事件渲染和退出码
│   └── demos.py                   三项 Mock 机制演示入口
└── tests/
    ├── fixtures/                  clamp 演示项目模板
    ├── test_package_smoke.py      包、entry point、当前树凭据扫描
    ├── test_models.py             模型约束和序列化禁止字段
    ├── test_config.py             配置优先级与秘密拒绝
    ├── test_credentials.py        凭据生命周期和不回显
    ├── test_workspace.py          路径与只读工具
    ├── test_transactions.py       哈希、原子写、提交与回滚
    ├── test_policy.py             风险分级、审批与禁止项
    ├── test_testing_feedback.py   pytest 采集、分类、脱敏和指纹
    ├── test_llm_context_parser.py LLM 抽象、动作解析和上下文预算
    ├── test_memory.py             白名单记忆与损坏隔离
    ├── test_loop.py               状态机、完成门禁和停止原因
    ├── test_cli.py                CLI 参数、凭据命令、事件和退出码
    └── test_mechanism_demos.py    三项确定性端到端机制演示

README.md                          正式课程 README
.gitlab-ci.yml                     必须包含 unit-test job
.github/workflows/release.yml      Windows 测试、构建和标签发布门禁
scripts/build.ps1                  本地可重复构建与 SHA-256
scripts/demo.ps1                   一键运行三项 Mock 演示
scripts/scan-current-tree.ps1      当前树秘密扫描，只输出 commit/path
scripts/scan-history.ps1           全历史秘密扫描，只输出 commit/path
```

### 公共接口约定

后续 task 必须沿用这些名字和签名；如冷启动验证证明需要修改，先修订 SPEC/PLAN 再实现。

```python
@dataclass(frozen=True)
class RunRequest:
    workspace: Path
    task: str
    base_url: str
    model: str
    config_path: Path | None = None
    config_overrides: Mapping[str, object] = field(default_factory=dict)

class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None:
        raise NotImplementedError

class ApprovalProvider(Protocol):
    def confirm(self, request: ApprovalRequest) -> bool:
        raise NotImplementedError

class CredentialStore(Protocol):
    def get(self) -> str | None:
        raise NotImplementedError
    def set(self, value: str) -> None:
        raise NotImplementedError
    def clear(self) -> bool:
        raise NotImplementedError

class LLMClient(Protocol):
    def decide(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> RawDecision:
        raise NotImplementedError

class LLMClientFactory(Protocol):
    def create(self, *, base_url: str, model: str, api_key: str) -> LLMClient:
        raise NotImplementedError

class ApplicationService:
    def run(self, request: RunRequest) -> RunResult:
        raise NotImplementedError
```

---

## 2. 依赖、并行与 Git 工作流

```text
Task 1 -> Task 2 -> Task 3
                    |-- Task 4  凭据
                    |-- Task 5  工作区
                    |-- Task 8  pytest/反馈
                    |-- Task 9  LLM/上下文/解析
                    `-- Task 10 记忆

Task 5 -> Task 6 事务
Task 5 -> Task 7 治理

Task 4 + 6 + 7 + 8 + 9 + 10 -> Task 11 AgentLoop/ApplicationService
Task 11 -> Task 12 CLI/机制演示
Task 12 -> Task 13 README/CI/打包
Task 13 -> Task 14 最终门禁/发布
```

- Task 4、5、8、9、10 可在 Task 3 合并后并行；Task 6、7 可在 Task 5 合并后并行。
- 每个 task 从最新 `main` 创建 `task/<两位编号>-<短名>` 分支和 `../FBW-worktrees/task-<两位编号>` worktree。
- 创建 worktree 必须调用 `superpowers:using-git-worktrees`；不要手写替代流程。
- 若仓库仍未配置远端，Task 1 执行前停止并向用户索取 NJU Git/GitHub 仓库 URL；不得猜测远端地址。
- 每个 task 使用独立实现 agent；通过两阶段 review 后，调用 `superpowers:finishing-a-development-branch` 创建 PR。
- PR 合并后删除对应 worktree；下一依赖 task 必须从合并后的最新 `main` 开始。

---

## 3. 实现前冷启动门禁

- [x] **Gate 1：选择不同类型的陌生智能体**

  使用非 Codex 类型的全新智能体会话，不导入本对话、memory 或 AGENT_LOG，只提供 `SPEC.md` 和 `PLAN.md`。

- [x] **Gate 2：在可舍弃 worktree 按依赖顺序试做 Task 1 和 Task 2**

  从当前基线开始先完成 Task 1 的红—绿—重构验证；只有 Task 1 全部绿色后才试做 Task 2。明确要求陌生智能体：“遇到不确定处立即暂停提问，不要猜测；不要提交或合并”。试做时间控制在 1–2 小时。Task 5 依赖 Task 2 与 Task 3，不纳入本门禁的实际编码试做；应在正式实现阶段等依赖合并后执行。

- [x] **Gate 3：记录客观缺陷**

  在 `SPEC_PROCESS.md` 记录停顿点、错误解读、产出差距和缺陷归因；在 `AGENT_LOG.md` 记录智能体类型、输入文件、输出摘要和人工判断。

- [x] **Gate 4：修订并重新批准**

  若发现歧义，先修改 `SPEC.md`/`PLAN.md`，给出关键 diff，自检并由用户重新批准。当前确认的缺陷均只影响 PLAN：冷启动任务顺序、Windows Git 路径解码、扫描器 fail-closed、模型深度不可变与动作不变量；不修改已批准 SPEC。每次修订经用户批准后才继续 Gate 2。冷启动 worktree 不合并，验证结束后安全移除。

---

### Task 1: 建立安全、可安装的 Python 包骨架

**Goal:** 把不安全的早期原型替换为可测试的 `src` 包、固定 Python 3.13 配置和无明文 Key 的当前工作树。

**Files:**
- Modify: `mini-harness/pyproject.toml`
- Modify: `mini-harness/.python-version`
- Modify: `mini-harness/README.md`
- Modify: `mini-harness/uv.lock`
- Delete: `mini-harness/agent.py`
- Delete: `mini-harness/test.txt`
- Delete: `detect-api.ps1`
- Create: `mini-harness/src/fbw_harness/__init__.py`
- Create: `mini-harness/tests/test_package_smoke.py`
- Create: `scripts/scan-current-tree.ps1`

**Interfaces:**
- Consumes: Git 当前树和 SPEC 的 Python/凭据约束。
- Produces: 可导入的 `fbw_harness` 包、`__version__ == "0.1.0"`、console script 名 `fbw-harness`、不泄露匹配内容的当前树扫描脚本。

- [x] **Step 1: 写包与秘密扫描失败测试**

```python
from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path


def test_package_exposes_version() -> None:
    package = importlib.import_module("fbw_harness")
    assert package.__version__ == "0.1.0"


def test_tracked_worktree_has_no_api_key_pattern() -> None:
    root = Path(__file__).resolve().parents[2]
    raw_files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    files = [path.decode("utf-8") for path in raw_files.split(b"\0") if path]
    pattern = re.compile(rb"sk-[A-Za-z0-9]{12,}")
    hits = [path for path in files if pattern.search((root / path).read_bytes())]
    assert hits == []


def test_secret_scan_fails_closed_when_git_is_unavailable(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/scan-current-tree.ps1"
    assert script.is_file()
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "secret scan failed"
```

- [x] **Step 2: 运行测试并确认按预期失败**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_package_smoke.py -v`

Expected: FAIL；至少包含 `ModuleNotFoundError: fbw_harness`，并列出当前树中旧原型文件命中。

- [x] **Step 3: 配置项目与包入口**

将 `mini-harness/pyproject.toml` 固定为 `requires-python = ">=3.13,<3.14"`，项目名改为 `fbw-harness`，添加运行依赖 `openai>=2.44,<3`、`keyring>=25.6,<26`，开发依赖 `pytest>=8.4,<9`、`pytest-timeout>=2.4,<3`、`ruff>=0.12,<1`、`pyinstaller>=6.15,<7`，并配置：

```toml
[project.scripts]
fbw-harness = "fbw_harness.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"

[tool.ruff]
target-version = "py313"
line-length = 100
```

`mini-harness/README.md` 必须包含指向根目录正式说明的相对链接 `[项目总 README](../README.md)`。在 `mini-harness/src/fbw_harness/__init__.py` 写入：

```python
__version__ = "0.1.0"
```

- [x] **Step 4: 移除当前树旧原型并添加安全扫描脚本**

Run: `git rm -- mini-harness/agent.py mini-harness/test.txt detect-api.ps1`

`scripts/scan-current-tree.ps1` 使用 `git grep -I -l -E 'sk-[A-Za-z0-9]{12,}' -- .`，只输出命中文件路径，不得打印匹配行或 Key。必须先保存原生命令退出码并精确分支：`0` 表示有命中，输出路径后返回 `1`；`1` 表示无命中，返回 `0`；其他退出码必须抑制原生 Git stderr，只向 stderr 输出固定文本 `secret scan failed` 并返回 `2`。不得把 Git 不可用、非仓库、权限或仓库损坏误报为安全。这只清理当前树，不重写既有 commit。

- [x] **Step 5: 更新锁文件并运行绿色验证**

Run: `uv lock --project mini-harness --python 3.13`

Run: `uv run --project mini-harness pytest mini-harness/tests/test_package_smoke.py -v`

Run: `pwsh -NoProfile -File scripts/scan-current-tree.ps1`

Expected: 两条命令均 PASS/退出 `0`，扫描输出不含秘密值。

- [x] **Step 6: 运行格式检查并提交**

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

Expected: `All checks passed!`

```powershell
git add -- mini-harness scripts/scan-current-tree.ps1
git commit -m "chore: 建立安全项目骨架"
```

**实现记录（2026-08-09）：** 实现提交 `c5ed568`；独立评审后的修复提交
`1c8c001`。验证为 `6 passed`、Ruff、当前树扫描和 `git diff --check` 均通过；独立
review/fix round 1 clean。PR：[PR #1](https://github.com/01w-01/SE-agent/pull/1)。

---

### Task 2: 定义领域模型、错误和端口协议

**Goal:** 建立后续模块共享的类型、状态和依赖反转边界，不包含任何真实 I/O。

**Files:**
- Create: `mini-harness/src/fbw_harness/models.py`
- Create: `mini-harness/src/fbw_harness/ports.py`
- Create: `mini-harness/src/fbw_harness/errors.py`
- Create: `mini-harness/tests/test_models.py`

**Interfaces:**
- Consumes: Task 1 的 Python 包。
- Produces: `ActionKind`、`PolicyLevel`、`FeedbackKind`、`RunStatus`、`Action`、`PolicyContext`、`PolicyDecision`、`Observation`、`Feedback`、`TestResult`、`SessionState`、`TransactionRecord`、`ProjectMemory`、`RunRequest`、`RunEvent`、`ApprovalRequest`、`RawToolCall`、`RawDecision`、`RunResult`；以及 §1 的五个 Protocol。`ApplicationService` 在 Task 11 的 `app.py` 实现，不在 `ports.py` 重复声明同名 Protocol。

- [x] **Step 1: 写模型不变量失败测试**

```python
@pytest.mark.parametrize("expected_sha256", [None, ""])
def test_edit_action_requires_non_empty_hash(expected_sha256: str | None) -> None:
    with pytest.raises(ModelValidationError, match="expected_sha256"):
        Action(
            kind=ActionKind.EDIT_FILE,
            path="src/a.py",
            expected_sha256=expected_sha256,
            old_text="x",
            new_text="y",
        )


def test_run_request_rejects_blank_task() -> None:
    with pytest.raises(ModelValidationError, match="task"):
        RunRequest(Path("project"), " ", "https://example.test/v1", "model")


def test_run_event_payload_rejects_secret_field() -> None:
    with pytest.raises(ModelValidationError, match="secret field"):
        RunEvent("run-1", "state", "start", {"api_key": "value"})


def test_run_event_rejects_nested_case_insensitive_secret_field() -> None:
    with pytest.raises(ModelValidationError, match="secret field"):
        RunEvent("run-1", "state", "start", {"meta": {"Authorization": "value"}})


def test_run_event_defensively_freezes_nested_payload() -> None:
    source = {"meta": {"summary": "ok"}}
    event = RunEvent("run-1", "state", "start", source)
    source["meta"]["summary"] = "mutated"  # type: ignore[index]
    assert event.payload["meta"]["summary"] == "ok"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["late"] = "value"  # type: ignore[index]


def test_run_request_rejects_secret_and_freezes_overrides() -> None:
    source = {"nested": {"limit": 1}}
    request = RunRequest(
        Path("project"),
        "task",
        "https://example.test/v1",
        "model",
        config_overrides=source,
    )
    source["nested"]["limit"] = 2  # type: ignore[index]
    assert request.config_overrides["nested"]["limit"] == 1  # type: ignore[index]
    with pytest.raises(ModelValidationError, match="secret field"):
        RunRequest(
            Path("project"),
            "task",
            "https://example.test/v1",
            "model",
            config_overrides={"nested": {"HEADERS": "value"}},
        )


def test_recursive_container_is_rejected_without_recursion_error() -> None:
    recursive: dict[str, object] = {}
    recursive["self"] = recursive
    with pytest.raises(ModelValidationError, match="recursive"):
        RunEvent("run-1", "state", "start", recursive)


def test_non_string_mapping_key_and_unsupported_object_are_rejected() -> None:
    with pytest.raises(ModelValidationError, match="string key"):
        RunEvent("run-1", "state", "start", {1: "value"})  # type: ignore[dict-item]
    with pytest.raises(ModelValidationError, match="unsupported"):
        RunEvent("run-1", "state", "start", {"value": object()})


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        (ActionKind.READ_FILE, {}),
        (ActionKind.CREATE_FILE, {"content": "x"}),
        (
            ActionKind.EDIT_FILE,
            {"expected_sha256": "0" * 64, "old_text": "x", "new_text": "y"},
        ),
    ],
)
@pytest.mark.parametrize("path", [None, ""])
def test_path_actions_require_non_empty_path(
    kind: ActionKind, kwargs: dict[str, object], path: str | None
) -> None:
    with pytest.raises(ModelValidationError, match="path"):
        Action(kind=kind, path=path, **kwargs)


@pytest.mark.parametrize(
    ("kwargs", "missing_field"),
    [
        ({"kind": ActionKind.CREATE_FILE, "path": "src/a.py"}, "content"),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "new_text": "y",
            },
            "old_text",
        ),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": "",
                "new_text": "y",
            },
            "old_text",
        ),
        (
            {
                "kind": ActionKind.EDIT_FILE,
                "path": "src/a.py",
                "expected_sha256": "0" * 64,
                "old_text": "x",
            },
            "new_text",
        ),
        ({"kind": ActionKind.FINISH}, "reason"),
    ],
)
def test_actions_reject_each_missing_required_field(
    kwargs: dict[str, object], missing_field: str
) -> None:
    with pytest.raises(ModelValidationError, match=missing_field):
        Action(**kwargs)  # type: ignore[arg-type]


def test_fixed_result_models_require_all_contract_fields() -> None:
    with pytest.raises(TypeError):
        RawDecision()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RunResult(RunStatus.COMPLETED, "ok", 0)  # type: ignore[call-arg]


def test_approval_request_normalizes_sequence_fields() -> None:
    request = ApprovalRequest("R01", "reason", ["fact"], ["src/a.py"])  # type: ignore[arg-type]
    assert request.risk_facts == ("fact",)
    assert request.affected_paths == ("src/a.py",)
```

- [x] **Step 2: 运行测试并确认缺少模型**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_models.py -v`

Expected: FAIL with import error for `fbw_harness.models`.

- [x] **Step 3: 实现枚举与不可变 dataclass**

所有外部可见模型使用 `@dataclass(frozen=True, slots=True)`。所有 `Mapping`、list、tuple、set/frozenset 输入必须在构造时递归防御性复制并冻结：Mapping 变为只读 Mapping，序列变为 tuple，集合变为 frozenset；调用者后续修改原对象不得改变模型。`RunRequest.config_overrides` 与 `RunEvent.payload` 在任意嵌套层级按大小写不敏感方式拒绝键名 `api_key`、`authorization`、`headers`、`file_content`。循环容器、非字符串 Mapping 键或无法冻结的对象形成 `ModelValidationError`，不得递归失控。只读 Mapping 不要求能被标准 `json.dumps` 直接处理；Task 12 的 JSONL 输出边界负责递归转换为普通 JSON 容器。

`Action.__post_init__` 校验分类型必填字段：`read_file` 要求非空 `path`；`create_file` 要求非空 `path` 且 `content is not None`；`edit_file` 要求非空 `path`、`expected_sha256`、非空 `old_text` 且 `new_text is not None`；`finish` 要求非空 `reason`；`list_files` 无额外必填字段。路径是否越界仍由 Workspace/Policy 判断；JSON 未知字段和 `finish` 只允许 reason 仍由 Task 9 `ActionParser` 判断，不在模型层重复解析职责。所有声明为 tuple/frozenset 的字段在构造时规范化为对应不可变类型。`SessionState` 可变且只保存运行期计数、动作签名、反馈指纹和触碰路径。

后续 task 依赖的字段固定为：

```python
@dataclass(frozen=True, slots=True)
class RawToolCall:
    name: str
    arguments: str

@dataclass(frozen=True, slots=True)
class RawDecision:
    tool_calls: tuple[RawToolCall, ...]
    content: str = ""

@dataclass(frozen=True, slots=True)
class TestResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    failed_tests: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class PolicyContext:
    dirty_paths: frozenset[str] = frozenset()
    changed_line_count: int = 0
    dangerous_capabilities: frozenset[str] = frozenset()

@dataclass(frozen=True, slots=True)
class Observation:
    kind: str
    success: bool
    summary: str
    exit_code: int | None = None
    output_tail: str = ""

@dataclass(frozen=True, slots=True)
class Feedback:
    kind: FeedbackKind
    passed: bool | None
    exit_code: int | None
    summary: str
    failed_tests: tuple[str, ...] = ()
    output_tail: str = ""
    fingerprint: str = ""

@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    stop_reason: str
    exit_code: int
    round_count: int
    touched_files: tuple[str, ...]
    last_test_passed: bool | None
    rollback_complete: bool
    recovery_path: Path | None
```

稳定错误层次：

```python
class HarnessError(Exception):
    exit_code = 1

class InputError(HarnessError):
    exit_code = 2

class RollbackIncompleteError(HarnessError):
    exit_code = 3

class ModelValidationError(InputError):
    pass
```

- [x] **Step 4: 定义 Protocol 并验证运行期替身**

`ports.py` 只定义 EventSink、ApprovalProvider、CredentialStore、LLMClient、LLMClientFactory 五个 `@runtime_checkable` Protocol，并使用 §1 的精确签名；不得提前定义 `ApplicationService` Protocol。新增：

```python
class LLMClientFactory(Protocol):
    def create(self, *, base_url: str, model: str, api_key: str) -> LLMClient:
        raise NotImplementedError
```

测试 Fake EventSink、ApprovalProvider、CredentialStore、LLMClient 和 LLMClientFactory 均可通过 `isinstance(fake, ProtocolType)`。

- [x] **Step 5: 运行模型测试和全量测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_models.py -v`

Run: `uv run --project mini-harness pytest -q`

Expected: PASS。

- [x] **Step 6: 重构、lint 并提交**

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

```powershell
git add -- mini-harness/src/fbw_harness/models.py mini-harness/src/fbw_harness/ports.py mini-harness/src/fbw_harness/errors.py mini-harness/tests/test_models.py
git commit -m "feat: 定义 Harness 核心契约"
```

**实现记录（2026-08-09）：** 实现提交 `901533a`；两轮独立评审后的修复提交
`3f75989`、`37e28ee`。最终验证为模型测试 `59 passed`、全量测试 `65 passed`、
Ruff 和 `git diff --check` 均通过；review/fix round 2 clean。PR：
[PR #2](https://github.com/01w-01/SE-agent/pull/2)。

---

### Task 3: 实现非秘密配置与应用入口解析

**Goal:** 将 CLI 值、项目 TOML、用户 TOML 和默认值合并为确定的 `HarnessConfig`，在任何 I/O 前拒绝危险或秘密配置。

**Files:**
- Create: `mini-harness/src/fbw_harness/config.py`
- Create: `mini-harness/tests/test_config.py`

**Interfaces:**
- Consumes: `InputError`、`RunRequest`。
- Produces: `HarnessConfig`、`load_config(request: RunRequest, *, user_config: Path | None) -> HarnessConfig`。

- [x] **Step 1: 写优先级、默认值和拒绝测试**

```python
def write_toml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def make_request(*, config_path: Path | None = None, overrides: dict[str, object] | None = None) -> RunRequest:
    return RunRequest(
        workspace=Path("project"),
        task="fix tests",
        base_url="https://example.test/v1",
        model="model",
        config_path=config_path,
        config_overrides=overrides or {},
    )


def test_config_priority_is_cli_project_user_default(tmp_path: Path) -> None:
    user = write_toml(tmp_path / "user.toml", "max_rounds = 4\n")
    project = write_toml(tmp_path / "project.toml", "max_rounds = 5\n")
    request = make_request(config_path=project, overrides={"max_rounds": 6})
    assert load_config(request, user_config=user).max_rounds == 6


@pytest.mark.parametrize("name", ["api_key", "authorization", "secret"])
def test_config_rejects_secret_fields(tmp_path: Path, name: str) -> None:
    config = write_toml(tmp_path / "bad.toml", f'{name} = "value"\n')
    with pytest.raises(InputError, match="secret"):
        load_config(make_request(config_path=config), user_config=None)
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_config.py -v`

Expected: FAIL because `fbw_harness.config` does not exist.

- [x] **Step 3: 实现配置模型和确定优先级**

```python
@dataclass(frozen=True, slots=True)
class HarnessConfig:
    max_rounds: int = 6
    api_retries: int = 2
    pytest_timeout_seconds: int = 60
    repeat_limit: int = 2
    file_size_limit_bytes: int = 262_144
    normal_change_line_limit: int = 200
    output_tail_chars: int = 12_000
    pytest_args: tuple[str, ...] = ("-q",)
    jsonl_log: Path | None = None
    memory_enabled: bool = False
    memory_path: Path | None = None
```

只接受明确定义字段；整数必须为正；`pytest_args` 是参数列表，不经过 shell；拒绝 `;`、`|`、`&`、换行和以 `--rootdir`、`-c` 开头的参数。

- [x] **Step 4: 运行边界测试并补充错误消息**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_config.py -v`

Expected: PASS；错误消息包含配置来源和字段名，但不包含字段值。

- [x] **Step 5: 全量验证并提交**

Run: `uv run --project mini-harness pytest -q`

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

```powershell
git add -- mini-harness/src/fbw_harness/config.py mini-harness/tests/test_config.py
git commit -m "feat: 添加声明式安全配置"
```

**实现记录（2026-08-09）：** 实现提交 `81e6c58`；独立评审后的修复提交
`a9a3586`。最终验证为配置测试 `28 passed`、全量测试 `93 passed`、Ruff 和
`git diff --check` 均通过；review/fix round 1 clean。PR：
[PR #3](https://github.com/01w-01/SE-agent/pull/3)。

---

### Task 4: 实现 Windows Credential Manager 凭据生命周期

**Goal:** 安全完成 API Key 的隐藏录入、状态、更新、读取和清除，不把值写入输出或配置。

**Files:**
- Create: `mini-harness/src/fbw_harness/credentials.py`
- Create: `mini-harness/tests/test_credentials.py`

**Interfaces:**
- Consumes: `CredentialStore` Protocol、`InputError`。
- Produces: `KeyringCredentialStore(service="fbw-harness", account="default")`，方法 `get/set/clear/status`。

- [x] **Step 1: 用 Fake keyring 写失败测试**

```python
class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if self.values.pop((service, account), None) is None:
            raise PasswordDeleteError("not found")


class FailingKeyring(FakeKeyring):
    def __init__(self, leaked_value: str) -> None:
        super().__init__()
        self.leaked_value = leaked_value

    def set_password(self, service: str, account: str, value: str) -> None:
        raise RuntimeError(f"backend rejected {self.leaked_value}")


def test_credential_lifecycle_never_returns_value_from_status() -> None:
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend=backend)
    store.set("temporary-value")
    assert store.status() == CredentialStatus(configured=True, service="fbw-harness", account="default")
    assert store.get() == "temporary-value"
    assert store.clear() is True
    assert store.get() is None


def test_keyring_error_does_not_include_secret() -> None:
    store = KeyringCredentialStore(backend=FailingKeyring("temporary-value"))
    with pytest.raises(CredentialError) as error:
        store.set("temporary-value")
    assert "temporary-value" not in str(error.value)
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_credentials.py -v`

Expected: FAIL because credential implementation is absent.

- [x] **Step 3: 实现 keyring 适配器**

调用 `keyring.get_password/set_password/delete_password`；空白 Key 抛 `InputError`；`delete_password` 的“凭据不存在”转换为 `False`；其他后端异常转换为不含原值的 `CredentialError`。

- [x] **Step 4: 验证真实后端的手动测试保持隔离**

自动测试只使用 Fake，不写开发者 Credential Manager。创建 pytest marker `manual_windows`，默认测试集合不运行真实钥匙串；README 后续给出手动验证命令。

- [x] **Step 5: 运行测试、lint 并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_credentials.py -v`

Run: `uv run --project mini-harness pytest -q`

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

```powershell
git add -- mini-harness/src/fbw_harness/credentials.py mini-harness/tests/test_credentials.py mini-harness/pyproject.toml
git commit -m "feat: 添加安全凭据存储"
```

**实现记录（2026-08-09）：** 实现提交 `4e7fdc0`；独立评审后的修复提交
`1ec3d3f`。最终验证为凭据测试 `9 passed`、全量测试 `102 passed`、Ruff 和
`git diff --check` 均通过；review/fix round 1 clean。`status()` 后端失败缺少直接
测试记录为 deferred Minor，留待最终整分支审查。PR：
[PR #4](https://github.com/01w-01/SE-agent/pull/4)。

---

### Task 5: 实现工作区围栏和只读文件工具

**Goal:** 只允许在安全工作区内发现和读取有限普通文本文件，并在 I/O 前拒绝越界、保护路径和重解析点。

**Files:**
- Create: `mini-harness/src/fbw_harness/workspace.py`
- Create: `mini-harness/tests/test_workspace.py`

**Interfaces:**
- Consumes: `HarnessConfig.file_size_limit_bytes`、`InputError`、`Action`。
- Produces: `Workspace(root: Path)`、`resolve_safe(relative: str, *, must_exist: bool) -> Path`、`list_files() -> tuple[str, ...]`、`read_file(relative: str) -> FileSnapshot`。

**用户裁决（2026-08-09）：** 保留 `Path.resolve + commonpath + 逐级重解析点检查` 的
路径式围栏，不升级为 Windows 原生文件/目录句柄级沙箱。该围栏面向误操作、普通路径越界和
静态链接，不承诺抵御同一用户下其他进程的恶意并发替换。实现仍须在路径式范围内先做纯语法
与逐级 `lstat`/文件属性检查，再 resolve；读取时比较 path-stat、opened-handle `fstat` 和读后
`fstat` 的文件身份、大小及修改时间，变化即稳定失败。目录枚举每次 `scandir` 前重新检查完整
链，但其剩余竞态按 SPEC R-09 记录，不以句柄级 API 解决。

文件发现固定最多返回 1,000 个文件、最多检查 10,000 个目录项；任一上限达到时抛稳定的
`WorkspaceLimitError`，不静默截断。保护/忽略集合除原规则外覆盖 `.credentials`、`.secrets`、
`.aws`、`.ssh`、`.azure`、`credentials.json`、`build`、`dist`、`.eggs` 和 `*.egg-info`；
root 的完整既存祖先链也必须检查重解析点，root 不得位于受保护目录树内。解码和路径错误不得
保留可能含外部文件内容的异常链。

- [x] **Step 1: 写路径攻击和正常读取失败测试**

```python
@pytest.mark.parametrize("path", ["../outside.py", "C:/outside.py", ".git/config", ".env"])
def test_workspace_rejects_forbidden_paths(tmp_path: Path, path: str) -> None:
    workspace = Workspace(tmp_path)
    with pytest.raises(PolicyDeniedError):
        workspace.resolve_safe(path, must_exist=False)


def test_read_file_returns_relative_path_hash_and_text(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    snapshot = Workspace(tmp_path).read_file("a.py")
    assert snapshot.path == "a.py"
    assert snapshot.text == "x = 1\n"
    assert len(snapshot.sha256) == 64
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_workspace.py -v`

Expected: FAIL because `Workspace` is undefined.

- [x] **Step 3: 实现规范路径和保护规则**

使用 `Path.resolve(strict=False)` 与 `os.path.commonpath` 双重确认目标位于 root；逐级调用 Windows 文件属性/`Path.is_symlink()` 拒绝 symlink、junction 和其他 reparse point；拒绝绝对路径、`..`、磁盘根、用户主目录、`.git`、`.env*`、凭据/恢复目录。

- [x] **Step 4: 实现有界发现和 UTF-8 读取**

`list_files` 排序返回相对 POSIX 路径，跳过忽略目录和二进制文件；`read_file` 在读取前后检查大小不超过 262,144 bytes，以 `utf-8` 严格解码，返回文本和 SHA-256；解码失败形成稳定 `UnsupportedFileError`。

- [x] **Step 5: 在 Windows 可用时测试 junction 拒绝**

测试用临时目录创建 junction；若当前账户不能创建，使用 mock 的 reparse 属性分支断言拒绝，而不是跳过核心规则。

- [x] **Step 6: 全量验证并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_workspace.py -v`

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/workspace.py mini-harness/tests/test_workspace.py
git commit -m "feat: 添加工作区安全围栏"
```

**实现记录（2026-08-09）：** 实现提交 `d69365d`；用户选择路径式方案 B 后，
修复提交 `830a2a7`。最终验证为工作区测试 `62 passed`、全量测试 `164 passed`、
Ruff、format 和 `git diff --check` 均通过；review/fix round 1 clean。原生句柄级
TOCTOU 防护未实现，残余风险按 SPEC R-09 保留。PR：
[PR #5](https://github.com/01w-01/SE-agent/pull/5)。

---

### Task 6: 实现逐文件事务、原子写入和失败回滚

**Goal:** 对创建和精确修改提供首次快照、并发哈希检查、原子替换、提交与可验证回滚。

**Files:**
- Create: `mini-harness/src/fbw_harness/transactions.py`
- Create: `mini-harness/tests/test_transactions.py`

**Interfaces:**
- Consumes: `Workspace.resolve_safe/read_file`、`TransactionRecord`。
- Produces: `FileTransaction(workspace, recovery_root)`，方法 `create_file`、`edit_file`、`commit`、`rollback -> RollbackReport`。

**用户裁决（2026-08-10）：** 沿用路径式方案 B，不实现平台专用条件更新或目录句柄事务。
`expected_sha256` 复查、rollback 当前哈希与 `os.replace`/`unlink` 之间的极窄跨进程
TOCTOU 作为 SPEC R-10 已知限制。现有方案仍须校验恢复材料的原始 SHA-256，并在恢复后
复核目标哈希；`commit()` 一旦开始即进入不可写状态，只允许幂等清理重试；恢复文件落盘后
在平台支持时尽力 fsync 其父目录；每次写入、恢复或清理恢复材料前重新验证恢复目录完整链、
目录身份和非重解析点。任何验证失败保留材料并报告失败，不得误报完成。

- [x] **Step 1: 写精确替换、哈希冲突和回滚失败测试**

```python
def make_transaction(tmp_path: Path) -> tuple[Workspace, FileTransaction]:
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_text("value = 1\n", encoding="utf-8")
    workspace = Workspace(workspace_root)
    return workspace, FileTransaction(workspace, tmp_path / "recovery")


def test_edit_requires_exactly_one_old_text_and_current_hash(tmp_path: Path) -> None:
    workspace, transaction = make_transaction(tmp_path)
    file_snapshot = workspace.read_file("a.py")
    with pytest.raises(EditConflictError, match="exactly once"):
        transaction.edit_file("a.py", file_snapshot.sha256, "missing", "new")


def test_rollback_restores_original_and_removes_created_file(tmp_path: Path) -> None:
    workspace, transaction = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    transaction.create_file("new.py", "created = True\n")
    report = transaction.rollback()
    assert report.complete is True
    assert workspace.read_file("a.py").text == original.text
    assert not (workspace.root / "new.py").exists()
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_transactions.py -v`

Expected: FAIL because `FileTransaction` is undefined.

- [x] **Step 3: 实现首次快照和原子替换**

每个相对路径第一次写入前保存“是否存在、原始 SHA-256、恢复材料”；后续写入不能覆盖首次记录。临时文件创建在目标同目录，写入 UTF-8、flush 后 `os.fsync`，再用 `os.replace` 替换；替换前重新比对期望 SHA-256。

- [x] **Step 4: 实现提交与逆序回滚**

`commit()` 清理成功事务恢复材料；`rollback()` 按触碰逆序恢复原文件并移除本事务创建文件。任何恢复失败都保留恢复目录、返回失败路径，并由调用方转换为退出码 `3`。

- [x] **Step 5: 注入 os.replace/权限故障验证不误报成功**

使用 monkeypatch 让第二次恢复失败，断言 `RollbackReport.complete is False`、恢复目录存在、失败路径为相对路径，且不会删除仍需手工恢复的材料。

- [x] **Step 6: 运行全量测试并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_transactions.py -v`

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/transactions.py mini-harness/tests/test_transactions.py
git commit -m "feat: 添加文件事务与回滚"
```

**实现记录（2026-08-10）：** 实现提交 `c67d2ac`；用户选择路径式方案 B 后，
修复提交 `b4d7c1a`。最终验证为事务测试 `49 passed`、全量测试 `213 passed`、
Ruff、定向 format 和 `git diff --check` 均通过；review/fix round 1 clean。
平台级条件更新未实现，残余竞态按 SPEC R-10 保留。PR：
[PR #6](https://github.com/01w-01/SE-agent/pull/6)。

---

### Task 7: 实现治理、风险分级和 HITL

**Goal:** 在工具调用前确定性输出 ALLOW、CONFIRM 或 DENY，并证明拒绝动作没有触达工具层。

**Files:**
- Create: `mini-harness/src/fbw_harness/policy.py`
- Create: `mini-harness/tests/test_policy.py`

**Interfaces:**
- Consumes: `Action`、`Workspace`、`HarnessConfig.normal_change_line_limit`、`ApprovalProvider`。
- Produces: `PolicyEngine.evaluate(action, context) -> PolicyDecision`、`authorize(decision, provider) -> bool`。

- [x] **Step 1: 写规则表失败测试**

```python
def edit_action(path: str) -> Action:
    return Action(
        kind=ActionKind.EDIT_FILE,
        path=path,
        expected_sha256="0" * 64,
        old_text="old",
        new_text="new",
        reason="test",
    )


@pytest.mark.parametrize("path", ["../outside.py", ".git/config", ".env"])
def test_forbidden_path_is_denied_before_tool(path: str) -> None:
    engine = PolicyEngine()
    action = Action(kind=ActionKind.READ_FILE, path=path, reason="test")
    decision = engine.evaluate(action, PolicyContext())
    assert decision.level is PolicyLevel.DENY
    assert decision.rule_id


@pytest.mark.parametrize(
    ("action", "context"),
    [
        (edit_action("pyproject.toml"), PolicyContext()),
        (edit_action(".github/workflows/ci.yml"), PolicyContext()),
        (edit_action("src/a.py"), PolicyContext(dirty_paths=frozenset({"src/a.py"}))),
        (edit_action("src/a.py"), PolicyContext(changed_line_count=201)),
        (edit_action("src/a.py"), PolicyContext(dangerous_capabilities=frozenset({"network"}))),
    ],
)
def test_high_risk_fact_requires_confirmation(action: Action, context: PolicyContext) -> None:
    assert PolicyEngine().evaluate(action, context).level is PolicyLevel.CONFIRM
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_policy.py -v`

Expected: FAIL because policy engine is absent.

- [x] **Step 3: 实现稳定规则顺序**

ActionParser 先拒绝未知动作、任意命令和删除/移动/重命名工具名；PolicyEngine 对合法 Action 先判 DENY：绝对/越界、`.git`、凭据、重解析点；再判 CONFIRM：依赖/锁文件、CI/发布文件、任务开始已有脏文件、超过 200 行、网络/进程/注册表等危险能力；其余受控文件动作 ALLOW。首个匹配规则写入稳定 `rule_id`，所有风险事实保留供 UI 和 LLM 使用。

- [x] **Step 4: 实现审批端口且不允许 reason 覆盖规则**

只有 CONFIRM 调用 `ApprovalProvider.confirm(ApprovalRequest)`；DENY 永不请求审批，ALLOW 永不打扰用户。模型的 `Action.reason` 只显示，不参与降级。

- [x] **Step 5: 运行测试、lint 并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_policy.py -v`

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/policy.py mini-harness/tests/test_policy.py
git commit -m "feat: 添加治理与人工审批"
```

**实现记录（2026-08-10）：** 实现提交 `fc9e8d7`；独立评审后的修复提交
`309cc15`。最终验证为策略测试 `51 passed`、全量测试 `264 passed`、Ruff、
format 和 `git diff --check` 均通过；review/fix round 1 clean。真实 ToolDispatcher
零调用证明按依赖关系留到 Task 11。PR：
[PR #7](https://github.com/01w-01/SE-agent/pull/7)。

---

### Task 8: 实现固定 pytest 执行与结构化反馈

**Goal:** 把 pytest 的确定结果采集、分类、脱敏、截断并转换成可回灌的稳定 Feedback。

**Files:**
- Create: `mini-harness/src/fbw_harness/testing.py`
- Create: `mini-harness/src/fbw_harness/feedback.py`
- Create: `mini-harness/tests/test_testing_feedback.py`

**Interfaces:**
- Consumes: `HarnessConfig.pytest_args/pytest_timeout_seconds/output_tail_chars`、`TestResult`、`Feedback`。
- Produces: `TestRunner(config, *, known_secrets).run(workspace) -> TestResult`、`FeedbackEngine.from_test/from_policy/from_tool`、`fingerprint(feedback) -> str`。

实现约束：`known_secrets` 必须是非空 ASCII 字符串组成的 tuple；Task 11 必须把同一个 tuple 同时注入 TestRunner 与 FeedbackEngine。pytest 双流以有界 reader 排空，原始 chunk 先提取固定诊断事实，再按 `mapping -> global -> sk-token -> known-secret` 流式脱敏，最后截取安全尾部。mapping 容器深度最多 64，超限 fail-closed；所有 reader、taskkill 和回收等待均有固定时限。

- [x] **Step 1: 写通过、断言、收集、语法、导入、超时和脱敏失败测试**

```python
def failed_result(output: str) -> TestResult:
    return TestResult(
        passed=False,
        exit_code=1,
        stdout=output,
        stderr="",
        duration_seconds=0.1,
        timed_out=False,
        failed_tests=(),
    )


def secret_output() -> str:
    fake_key = "sk-" + ("A" * 20)
    return f"Authorization: Bearer {fake_key}\nFAILED tests/test_a.py::test_x"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("FAILED tests/test_a.py::test_x - assert 1 == 2", FeedbackKind.ASSERTION_FAILURE),
        ("ERROR collecting tests/test_a.py", FeedbackKind.COLLECTION_FAILURE),
        ("SyntaxError: invalid syntax", FeedbackKind.SYNTAX_ERROR),
        ("ModuleNotFoundError: missing", FeedbackKind.IMPORT_ERROR),
    ],
)
def test_feedback_classifies_known_pytest_failures(output, expected) -> None:
    assert FeedbackEngine().from_test(failed_result(output)).kind is expected


def test_feedback_redacts_key_and_truncates_tail() -> None:
    feedback = FeedbackEngine(output_tail_chars=40).from_test(failed_result(secret_output()))
    assert "sk-" not in feedback.output_tail
    assert len(feedback.output_tail) <= 40
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_testing_feedback.py -v`

Expected: FAIL because runner and feedback engine are absent.

- [x] **Step 3: 实现固定子进程和 Windows 超时终止**

命令固定为 `[sys.executable, "-m", "pytest", *config.pytest_args]`，`cwd` 固定为工作区，不使用 shell。以新进程组启动；超时后在 Windows 使用 `taskkill /T /F /PID <pid>`，捕获 UTF-8 replacement stdout/stderr、exit code 和 duration。

- [x] **Step 4: 实现保守分类、摘要、脱敏和指纹**

分类优先级固定为 timeout、collection、syntax、import、assertion、unknown、pass；只在可靠时提取失败测试名。先脱敏 `Authorization`、Bearer、Key 模式和已知 CredentialStore 值，再截取尾部。指纹只由 kind、exit code、排序后的失败测试名、规范化摘要计算 SHA-256。

- [x] **Step 5: 运行真实临时 pytest 集成测试**

创建临时 Python 项目分别通过、断言失败和超时；断言 runner 不读取模型命令、不越过 cwd，反馈多次生成指纹相同。

Run: `uv run --project mini-harness pytest mini-harness/tests/test_testing_feedback.py -v`

- [x] **Step 6: 全量测试并提交**

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/testing.py mini-harness/src/fbw_harness/feedback.py mini-harness/tests/test_testing_feedback.py
git commit -m "feat: 添加测试反馈闭环基础"
```

**实现记录（2026-08-10）：** 首版与五轮安全修复提交为 `45800ad`、
`842ee04`、`9b47845`、`97a42f9`、`4788d56`、`b4e4d65`；达到 review
上限后停止叠补丁，以 `f60bb4c` 重构两层流式脱敏，再以 `247135a` 收紧
quoted fragment 与 ASCII known-secret 契约。最终验证 Task 8 `234 passed, 1 skipped`、
全量 `498 passed, 1 skipped`，Ruff、format、秘密扫描和累计 diff check 通过；
独立 review 为 0 Critical / 0 Important / 0 Minor。PR：
[PR #8](https://github.com/01w-01/SE-agent/pull/8)。

---

### Task 9: 实现 LLM 抽象、动作解析和上下文构建

**Goal:** 用底层 OpenAI Chat Completions 获取一个动作，严格解析唯一 tool call，并把最新反馈高优先级回灌。

**Files:**
- Create: `mini-harness/src/fbw_harness/llm.py`
- Create: `mini-harness/src/fbw_harness/mock_llm.py`
- Create: `mini-harness/src/fbw_harness/parser.py`
- Create: `mini-harness/src/fbw_harness/context.py`
- Create: `mini-harness/tests/test_llm_context_parser.py`

**Interfaces:**
- Consumes: `LLMClient`、`LLMClientFactory`、`RawDecision`、`Action`、`Feedback`、`ProjectMemory`。
- Produces: `OpenAICompatibleClient`、`OpenAIClientFactory`、`ScriptedMockLLM`、`ActionParser.parse`、`ContextBuilder.build`、固定工具 schema。

- [x] **Step 1: 写解析与反馈优先级失败测试**

```python
def test_parser_requires_exactly_one_known_tool_call() -> None:
    with pytest.raises(ActionParseError, match="exactly one"):
        ActionParser().parse(RawDecision(tool_calls=()))


def test_latest_feedback_survives_context_budget() -> None:
    request = RunRequest(Path("project"), "fix clamp", "https://example.test/v1", "model")
    observations = [
        Observation("tool", True, f"old-{index}", output_tail=f"old-observation-{index}-full-body")
        for index in range(20)
    ]
    feedback = Feedback(
        kind=FeedbackKind.ASSERTION_FAILURE,
        passed=False,
        exit_code=1,
        summary="LATEST_FEEDBACK",
        failed_tests=("tests/test_clamp.py::test_upper",),
        fingerprint="f" * 64,
    )
    messages = ContextBuilder(max_chars=800).build(
        request=request, observations=observations,
        feedback=feedback, memory=None, files=[]
    )
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "LATEST_FEEDBACK" in serialized
    assert "old-observation-0-full-body" not in serialized
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_llm_context_parser.py -v`

Expected: FAIL because parser/context/LLM modules are absent.

- [x] **Step 3: 实现严格 parser 和固定工具 schema**

只接受一个 function call；工具名必须属于五种 ActionKind；JSON 必须是 object 且无未知字段；`finish` 只接受 reason。解析错误形成 `ActionParseError`，原始文本先截断和脱敏，不执行自由文本。

- [x] **Step 4: 实现 ContextBuilder**

顺序固定为系统规则、任务与预算、工具协议、项目记忆摘要、相关文件、旧观察摘要、最新 Feedback。超过字符预算时依次丢弃旧观察全文、非相关文件、旧摘要；不得丢弃系统安全规则、任务和最新 Feedback。

- [x] **Step 5: 实现真实与脚本化 LLM**

`OpenAICompatibleClient` 只调用一次 `client.chat.completions.create`，重试仅覆盖 timeout/connection/429/5xx，最多 2 次；鉴权和格式错误不重试。`ScriptedMockLLM` 按队列返回 RawDecision，记录每次 messages，耗尽时抛稳定错误。

- [x] **Step 6: 用 Fake OpenAI SDK 验证无网络行为**

断言 Base URL、model、messages、tools 正确传入；API Key 不出现在 RawDecision、异常或事件。默认测试不得访问网络。

- [x] **Step 7: 全量验证并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_llm_context_parser.py -v`

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/llm.py mini-harness/src/fbw_harness/mock_llm.py mini-harness/src/fbw_harness/parser.py mini-harness/src/fbw_harness/context.py mini-harness/tests/test_llm_context_parser.py
git commit -m "feat: 添加 LLM 决策与上下文构建"
```

**实现记录（2026-08-10）：** 首版 `419c762`；review fix 提交 `5d513d0`、
`53f29a8`、`80ca933`，补齐惰性异常统一映射、先限界后脱敏、最旧项完整淘汰、
schema 防污染、LLM 输出硬上限及伪装内建类型拒绝。最终验证 Task 9
`113 passed`、全量 `611 passed, 1 skipped`，Ruff、format、秘密扫描和累计
diff check 通过；独立 review 为 0 Critical / 0 Important；集成见
[PR #9](https://github.com/01w-01/SE-agent/pull/9)。

---

### Task 10: 实现可选白名单项目记忆

**Goal:** 默认不持久化；显式启用时只保存用户项目说明和最近成功摘要，并安全隔离损坏文件。

**Files:**
- Create: `mini-harness/src/fbw_harness/memory.py`
- Create: `mini-harness/tests/test_memory.py`

**Interfaces:**
- Consumes: `HarnessConfig.memory_enabled/memory_path`、`ProjectMemory`、`RunResult`。
- Produces: `JsonProjectMemoryStore.load() -> ProjectMemory | None`、`save_success(summary)`、`clear()`。

- [x] **Step 1: 写默认关闭、白名单和损坏隔离失败测试**

```python
def test_disabled_memory_never_reads_or_writes(tmp_path: Path) -> None:
    store = JsonProjectMemoryStore(tmp_path / "memory.json", enabled=False)
    assert store.load() is None
    store.save_success("passed")
    assert not (tmp_path / "memory.json").exists()


def test_memory_rejects_secret_and_full_file_fields(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text('{"version":1,"api_key":"value"}', encoding="utf-8")
    assert JsonProjectMemoryStore(path, enabled=True).load() is None
    assert list(tmp_path.glob("memory.json.corrupt-*"))
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_memory.py -v`

Expected: FAIL because memory store is absent.

- [x] **Step 3: 实现版本化 schema 和原子写入**

JSON 只允许 `version`、`project_notes`、`last_success_summary`、`updated_at`；未知或禁止字段使文件移动为带 UTC 时间戳的 `.corrupt-*`，并返回无记忆运行。写入使用同目录临时文件和 `os.replace`。

- [x] **Step 4: 验证按需注入与长度限制**

项目说明和成功摘要分别限制 2,000 字符；失败运行不得写记忆；ContextBuilder 仅在 enabled 且 load 成功时注入。

- [x] **Step 5: 全量验证并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_memory.py -v`

Run: `uv run --project mini-harness pytest -q`

```powershell
git add -- mini-harness/src/fbw_harness/memory.py mini-harness/tests/test_memory.py
git commit -m "feat: 添加受控项目记忆"
```

**实现记录（2026-08-11）：** 首版 `c1befd5`；task review fix 提交
`de99cac`、`44c8f12`，补齐固定损坏提示、UTC 时间、静态 reparse 覆盖和
warning-as-error 回退；最终累计 review fix `5eeb08a` 补齐 quoted JSON/TOML/env
秘密字段、读取状态区分与畸形路径安全失败。控制器最终验证 Task 10 `32 passed`、
全量 `643 passed, 1 skipped`，Ruff、format、秘密扫描和累计 diff check 通过；
最终 review 为 Ready to merge。Task 11 负责只在成功运行后调用 `save_success()`，
并仅在 enabled 且 `load()` 成功时把记忆注入 ContextBuilder。集成见
[PR #10](https://github.com/01w-01/SE-agent/pull/10)。

---

### Task 11: 实现 AgentLoop、工具分发和 ApplicationService

**Goal:** 把所有模块组合成同一个显式状态机，实现动作校验、执行、测试、反馈、完成门禁、停止和回滚。

**Files:**
- Create: `mini-harness/src/fbw_harness/loop.py`
- Create: `mini-harness/src/fbw_harness/app.py`
- Create: `mini-harness/tests/test_loop.py`

**Interfaces:**
- Consumes: Tasks 2–10 的全部稳定接口。
- Produces: `ToolDispatcher(workspace, transaction).execute(action) -> Observation`、`AgentLoop(llm, parser, context_builder, policy, dispatcher, test_runner, feedback_engine, event_sink, approval_provider, config).run(request) -> RunResult`、`ApplicationService.run(request) -> RunResult`。

- [x] **Step 1: 写完成门禁、反馈修正和无进展失败测试**

```python
class RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class AlwaysApprove:
    def confirm(self, request: ApprovalRequest) -> bool:
        return True


def tool_decision(name: str, arguments: dict[str, object]) -> RawDecision:
    return RawDecision((RawToolCall(name, json.dumps(arguments)),))


def write_clamp_project(root: Path) -> tuple[str, str, str]:
    root.mkdir()
    initial = "def clamp(value, lower, upper):\n    return value\n"
    wrong = "def clamp(value, lower, upper):\n    return max(value, lower)\n"
    correct = "def clamp(value, lower, upper):\n    return max(lower, min(value, upper))\n"
    (root / "clamp.py").write_text(initial, encoding="utf-8")
    (root / "test_clamp.py").write_text(
        "from clamp import clamp\n\n"
        "def test_bounds():\n"
        "    assert clamp(-1, 0, 10) == 0\n"
        "    assert clamp(11, 0, 10) == 10\n",
        encoding="utf-8",
    )
    return initial, wrong, correct


def build_loop(root: Path, decisions: list[RawDecision]) -> tuple[AgentLoop, ScriptedMockLLM]:
    config = HarnessConfig()
    workspace = Workspace(root)
    transaction = FileTransaction(workspace, root.parent / "recovery")
    llm = ScriptedMockLLM(decisions)
    loop = AgentLoop(
        llm=llm,
        parser=ActionParser(),
        context_builder=ContextBuilder(max_chars=12_000),
        policy=PolicyEngine(),
        dispatcher=ToolDispatcher(workspace, transaction),
        test_runner=TestRunner(config),
        feedback_engine=FeedbackEngine(config.output_tail_chars),
        event_sink=RecordingEventSink(),
        approval_provider=AlwaysApprove(),
        config=config,
    )
    return loop, llm


def test_finish_is_rejected_until_latest_test_passes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    initial, wrong, correct = write_clamp_project(root)
    initial_hash = hashlib.sha256(initial.encode()).hexdigest()
    wrong_hash = hashlib.sha256(wrong.encode()).hexdigest()
    decisions = [
        tool_decision("edit_file", {"path": "clamp.py", "expected_sha256": initial_hash, "old_text": "return value", "new_text": "return max(value, lower)", "reason": "first attempt"}),
        tool_decision("finish", {"reason": "premature"}),
        tool_decision("edit_file", {"path": "clamp.py", "expected_sha256": wrong_hash, "old_text": "return max(value, lower)", "new_text": "return max(lower, min(value, upper))", "reason": "use failure feedback"}),
        tool_decision("finish", {"reason": "tests passed"}),
    ]
    loop, llm = build_loop(root, decisions)
    result = loop.run(RunRequest(root, "fix clamp", "https://example.test/v1", "mock"))
    assert result.status is RunStatus.COMPLETED
    assert "assertion_failure" in json.dumps(llm.calls[1], ensure_ascii=False)
    assert result.last_test_passed is True


def test_repeated_action_and_feedback_rolls_back(tmp_path: Path) -> None:
    root = tmp_path / "project"
    initial, _, _ = write_clamp_project(root)
    initial_hash = hashlib.sha256(initial.encode()).hexdigest()
    invalid = tool_decision("edit_file", {"path": "clamp.py", "expected_sha256": initial_hash, "old_text": "missing text", "new_text": "bad", "reason": "invalid"})
    loop, _ = build_loop(root, [invalid, invalid])
    result = loop.run(RunRequest(root, "fix clamp", "https://example.test/v1", "mock"))
    assert result.stop_reason == "no_progress"
    assert result.rollback_complete is True
    assert (root / "clamp.py").read_text(encoding="utf-8") == initial
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_loop.py -v`

Expected: FAIL because AgentLoop is absent.

- [x] **Step 3: 实现 ToolDispatcher 且治理先于工具**

分发 `list_files/read_file/create_file/edit_file/finish`；每次分发前必须已有 PolicyDecision。DENY 和未获批准的 CONFIRM 只产生 Feedback，工具调用计数保持不变。写操作委托 FileTransaction，禁止直接 `Path.write_text`。

- [x] **Step 4: 实现状态迁移和每轮一个动作**

严格按 `INITIALIZING -> REQUESTING_ACTION -> VALIDATING_ACTION -> WAITING_APPROVAL（仅 CONFIRM） -> EXECUTING -> VERIFYING（仅代码写入） -> FEEDBACK -> REQUESTING_ACTION / COMPLETED / FAILED / ROLLING_BACK`。解析、策略、工具和测试错误均转为结构化 Feedback；代码写入自动 VERIFYING；最近测试失败时 finish 形成反馈而不完成。

- [x] **Step 5: 实现所有停止和恢复路径**

覆盖 success、max_rounds、no_progress、3 次格式错误、用户拒绝、中断、API 失败、pytest 超时、内部异常。成功 commit 事务；其他路径 rollback。回滚不完整返回 `RunStatus.ROLLBACK_INCOMPLETE` 和退出语义 `3`。

- [x] **Step 6: 实现 ApplicationService 组合边界**

`ApplicationService` 校验 RunRequest、加载配置、读取 CredentialStore、由 LLMClientFactory 创建客户端、建立 Workspace/Transaction/Loop。每个状态通过 EventSink 发 RunEvent；审批只经 ApprovalProvider；核心不导入 CLI 模块。

- [x] **Step 7: Ctrl+C 与异常注入测试**

直接向 loop 注入 `KeyboardInterrupt` 和工具异常，断言恢复调用、事件顺序、退出语义和恢复材料路径；事件 payload 不含 Key 或完整文件。

- [x] **Step 8: 全量验证并提交**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_loop.py -v`

Run: `uv run --project mini-harness pytest -q`

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

```powershell
git add -- mini-harness/src/fbw_harness/loop.py mini-harness/src/fbw_harness/app.py mini-harness/tests/test_loop.py
git commit -m "feat: 实现 Agent 主循环"
```

**实现记录（2026-08-11）：** Task 11 以 `e102edc`、`de4c48e`、`c654dc6` 完成 AgentLoop、ApplicationService、治理/审批、反馈闭环、终态与恢复路径。最终审查提出的有限 capability token 表被用户裁决为已知限制：它只提供 best-effort `CONFIRM` 提示，不是安全边界，不要求完备，也不继续扩表或重构。终态后的恢复目录清理另以 TDD 收口并提交 `4cd4cb4`，保证清理阶段的 `KeyboardInterrupt` 不推翻已确定的提交或完整回滚结果。正式安全边界统一为工作区路径围栏、动作级策略/HITL、逐文件事务与回滚；工作区代码由 pytest 以当前用户权限执行，明确不在安全边界内，见 SPEC R-12。最终门禁：定向 `227 passed`、全量 `729 passed, 1 skipped`、Ruff、8 文件 format、当前树秘密扫描和累计 diff check 均通过。

**Task 12–14 审查约束（用户裁决）：** reviewer 必须按上述 SPEC 威胁模型审查。工作区内代码执行相关问题只记已知限制，不判实现缺陷；不要求任何 denylist 或模式表完备。Critical 仅限数据丢失、回滚失败、凭据泄漏和越界写入；其他问题按 Important 及以下记录为 TODO/已知限制且不阻断 PR。每个 task 最多一轮修复，不做第二轮复审。集成见 [PR #11](https://github.com/01w-01/SE-agent/pull/11)。

---

### Task 12: 实现 CLI 和三项 Mock 机制演示

**Goal:** 提供真正可运行的 CLI、凭据命令、稳定事件输出，以及不依赖网络/Key 的治理、反馈修正和无进展演示。

**Files:**
- Create: `mini-harness/src/fbw_harness/cli.py`
- Create: `mini-harness/src/fbw_harness/demos.py`
- Create: `mini-harness/tests/fixtures/clamp_project/clamp.py`
- Create: `mini-harness/tests/fixtures/clamp_project/test_clamp.py`
- Create: `mini-harness/tests/test_cli.py`
- Create: `mini-harness/tests/test_mechanism_demos.py`
- Create: `scripts/demo.ps1`

**Interfaces:**
- Consumes: `ApplicationService`、`KeyringCredentialStore`、`ScriptedMockLLM`。
- Produces: `main(argv: Sequence[str] | None = None, *, app: ApplicationService | None = None, credential_store: CredentialStore | None = None) -> int`；注入参数仅供测试/组合根使用；子命令 `run`、`credential set/status/clear`、`memory clear`、`demo guardrail/feedback/no-progress/all`。

- [x] **Step 1: 写 CLI 边界与无终端核心失败测试**

```python
class FakeApplication:
    def run(self, request: RunRequest) -> RunResult:
        return RunResult(
            status=RunStatus.COMPLETED,
            stop_reason="success",
            exit_code=0,
            round_count=1,
            touched_files=("clamp.py",),
            last_test_passed=True,
            rollback_complete=True,
            recovery_path=None,
        )


def test_run_maps_structured_result_to_exit_code(capsys) -> None:
    fake_app = FakeApplication()
    code = main(["run", "--workspace", "project", "--task", "fix", "--base-url", "https://example.test/v1", "--model", "m"], app=fake_app)
    assert code == 0
    assert "COMPLETED" in capsys.readouterr().out


def test_key_is_never_accepted_as_cli_argument() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--api-key", "value"])
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_cli.py mini-harness/tests/test_mechanism_demos.py -v`

Expected: FAIL because CLI/demos are absent.

- [x] **Step 3: 实现 CLIAdapter、ConsoleEventSink 和 ConsoleApprovalProvider**

`credential set` 使用 `getpass.getpass`；status 只显示 configured/service/account；run 必填 workspace/task/base-url/model。ConsoleEventSink 渲染 `[轮次] 动作/策略/测试/停止`；JSONL sink 可选且只写 RunEvent。JSONL sink 在输出边界递归把只读 Mapping 转为 dict、tuple/frozenset 转为 list、Path/Enum 转为字符串值，遇到其他对象拒绝写出；不得为方便序列化而把领域模型改回可变容器。Ctrl+C 返回 ApplicationService 的回滚结果。

- [x] **Step 4: 实现三个确定性演示**

1. `guardrail`：Mock 请求 `../outside.txt`，断言 DENY 且文件工具未调用。
2. `feedback`：首次写入错误 clamp，真实 pytest 失败；最新 Feedback 进入第二次请求；第二次正确修改并通过。
3. `no-progress`：相同错误动作和指纹连续两次，停止原因为 `no_progress` 并恢复原文件。

演示复制 fixture 到 pytest 临时目录，绝不修改用户工作区；`scripts/demo.ps1` 依次调用三个子命令并在任一非零时失败。

- [x] **Step 5: 验证真实/Mock 共用 AgentLoop**

测试 monkeypatch 组合根，断言 demo 和 run 注入不同 LLMClientFactory，但 `ApplicationService` 与 `AgentLoop` 类型完全相同，不允许 demos 自建循环。

- [x] **Step 6: 运行 CLI、演示和全量测试**

Run: `uv run --project mini-harness fbw-harness --help`

Run: `uv run --project mini-harness fbw-harness demo all`

Run: `uv run --project mini-harness pytest -q`

Expected: help 退出 `0`；三个 demo 均显示稳定结果并退出 `0`；测试 PASS。

- [x] **Step 7: 提交**

```powershell
git add -- mini-harness/src/fbw_harness/cli.py mini-harness/src/fbw_harness/demos.py mini-harness/tests scripts/demo.ps1
git commit -m "feat: 添加 CLI 与机制演示"
```

**实现记录（2026-08-11）：** 首版 `473b32a feat: 添加 CLI 与机制演示` 提供真实 CLI、凭据/记忆命令、稳定事件输出和三个使用既有 ApplicationService/AgentLoop 的确定性演示。唯一 task review 为 0 Critical、质量/安全 APPROVED，并把两项 Important 记为非阻断 TODO：guardrail 指标需取自真实执行、共享组合根测试需观察实际 factory/loop 构造。按用户设定的一轮上限，以 TDD 集中修复并追加 `4ab5134 fix: 强化演示机制验证`，不再进行第二轮复审。控制器最终验证：Task 12 定向 `11 passed`、全量 `743 passed, 1 skipped`，CLI help、`demo all`、`scripts/demo.ps1`、Ruff、本任务 format、当前树秘密扫描和累计 diff check 全部通过。集成见 [PR #12](https://github.com/01w-01/SE-agent/pull/12)。合并后 Windows checkout 将 fixture 转为 CRLF，暴露 `read_text()` 换行规范化导致 expected SHA 与真实磁盘字节不一致；以显式 CRLF RED 测试定位后追加 `e9b1cd9 fix: 保留演示 fixture 的 CRLF 换行`，全量增至 `744 passed, 1 skipped`，补充集成见 [PR #13](https://github.com/01w-01/SE-agent/pull/13)。

---

### Task 13: 完成 README、CI、Windows 打包和本地发行物

**Goal:** 让源码和 Windows x64 单文件产物都能一键测试、构建和运行，并提供课程要求的文档与 CI 配置。

**Files:**
- Create: `README.md`
- Modify: `mini-harness/README.md`
- Create: `mini-harness/fbw-harness.spec`
- Create: `scripts/build.ps1`
- Create: `.gitlab-ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `scripts/scan-history.ps1`
- Create: `mini-harness/tests/test_distribution_files.py`

**Interfaces:**
- Consumes: Task 12 的 console script 和 demo。
- Produces: `dist/fbw-harness.exe`、`dist/fbw-harness.exe.sha256`、GitLab `unit-test` job、Windows tag workflow、完整用户文档。

- [x] **Step 1: 写交付文件和 CI 合同失败测试**

```python
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_required_distribution_files_exist() -> None:
    root = repo_root()
    required = ["README.md", ".gitlab-ci.yml", ".github/workflows/release.yml", "mini-harness/fbw-harness.spec", "scripts/build.ps1"]
    assert [path for path in required if not (root / path).is_file()] == []


def test_gitlab_has_exact_unit_test_job() -> None:
    text = (repo_root() / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^unit-test:\s*$", text)
    assert "uv run --project mini-harness pytest" in text
```

- [x] **Step 2: 运行失败测试**

Run: `uv run --project mini-harness pytest mini-harness/tests/test_distribution_files.py -v`

Expected: FAIL listing missing distribution files.

- [x] **Step 3: 写正式 README**

根 README 必须包含：项目简介、获取与安装、首次安全配置 Key、运行命令与示例、目录结构、测试与三项机制演示、分发命令、安全边界、凭据威胁模型摘要、已知限制、第三方依赖/许可证、课程文档索引。明确 pytest 以用户权限执行而非 OS 沙箱，首版不提供 WebUI。

- [x] **Step 4: 实现确定性 PyInstaller 构建脚本**

`fbw-harness.spec` 收集 keyring Windows backend；`scripts/build.ps1` 先运行测试和当前树扫描，再执行 PyInstaller，最后用 `Get-FileHash -Algorithm SHA256` 生成只含 hash 与文件名的 `.sha256`。构建失败不得保留被误认为成功的新产物。

- [x] **Step 5: 配置 GitLab 和 GitHub Actions**

`.gitlab-ci.yml` 的 `unit-test` 在 Python 3.13/uv 环境运行当前树扫描、ruff、pytest。GitHub workflow 使用 Windows runner、`fetch-depth: 0`，push/PR 运行测试；tag 时额外运行历史扫描、build、exe `--help` 和 demo，再上传 exe、SHA-256、说明。任何一步失败都不创建 Release。

- [x] **Step 6: 实现不泄露匹配内容的历史扫描**

`scripts/scan-history.ps1` 遍历 `git rev-list --all`，对每个 commit 使用 `git grep -I -l -E 'sk-[A-Za-z0-9]{12,}' <commit> -- .`；日志只输出 commit SHA 和路径，绝不输出匹配行。当前已知历史会返回 `1`，因此只在 tag/release 门禁执行。

- [x] **Step 7: 运行本地构建和冷净命令验证**

Run: `pwsh -NoProfile -File scripts/build.ps1`

Run: `./dist/fbw-harness.exe --help`

Run: `./dist/fbw-harness.exe demo all`

Expected: 构建和两次运行退出 `0`，SHA-256 可用 `Get-FileHash` 复核；不需要系统 Python、网络或 Key 运行 help/demo。

- [x] **Step 8: 全量验证并提交**

Run: `uv run --project mini-harness pytest -q`

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

```powershell
git add -- README.md mini-harness/README.md mini-harness/fbw-harness.spec mini-harness/tests/test_distribution_files.py scripts .gitlab-ci.yml .github/workflows/release.yml
git commit -m "build: 添加 CI 与 Windows 分发"
```

**实现记录（2026-08-11）：** `852db5e build: 添加 CI 与 Windows 分发` 完成根 README、包内 README、GitLab/GitHub CI、PyInstaller spec、确定性 build、历史扫描和分发合同。真实构建逐步暴露并修复包入口相对导入、fixture 缺失、冻结 exe 不能处理 `-m pytest` 三个冻结边界，最终单文件 help/demo 无需系统 Python、网络或 Key。唯一 task review 为规格 PASS、质量/安全 APPROVED、0 Critical；两项 Important/TODO 与一项 Minor 在唯一 fix round 1/1 中以 `84d4527 fix: 收紧分发构建清理门禁` 集中处理：staging 清理失败统一删除已发布 exe/SHA，合同测试覆盖 spec/workflow/历史输出，README 命令统一从仓库根运行；不做第二轮复审。控制器最终验证：分发合同 `6 passed`、全量 `750 passed, 1 skipped`、Ruff、format、当前树扫描、完整 build、exe help/demo、SHA 和累计 diff 通过。现有历史扫描按已接受的临时 Key 风险真实退出 `1`，因此 tag/Release 继续被阻断，未弱化或伪装通过。集成见 [PR #14](https://github.com/01w-01/SE-agent/pull/14)。

---

### Task 14: 执行真实 API、新机、CI 和最终发布门禁

**Goal:** 用客观证据判断产品是否可交付；已知凭据历史或 WebUI 冲突未解决时明确停止，不伪造完成状态。

**Files:**
- Modify: `README.md`（仅补充已验证版本/限制，不记录 Key）
- Modify: `AGENT_LOG.md`
- Modify: `PLAN.md`
- Create: `docs/evidence/release-checklist.md`
- Create: `docs/evidence/ci-last-pass.md`

**Interfaces:**
- Consumes: Task 13 的 exe、SHA-256、CI 配置和安全脚本。
- Produces: 真实 API 冒烟、新 Windows 环境、最终 CI 的可审计证据；只有所有强制门禁通过才产生 Release。

- [x] **Step 1: 运行离线总验证**

Run: `uv run --project mini-harness pytest -q`

Run: `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`

Run: `pwsh -NoProfile -File scripts/demo.ps1`

Run: `pwsh -NoProfile -File scripts/build.ps1`

Expected: 全部退出 `0`；把命令、版本、通过数量和产物 SHA-256 记录到 `docs/evidence/release-checklist.md`。

**验收记录（2026-08-11）：** 四条命令均退出 `0`；全量测试 `750 passed, 1 skipped`，Ruff 与三项 demo 通过，构建产物 SHA-256 已复核，详见 `docs/evidence/release-checklist.md`。

- [ ] **Step 2: 手动真实 API 冒烟**

通过 `fbw-harness credential set` 隐藏录入学校 Key，status 不回显；对专用临时 Python 项目运行一次受控修复。证据只记录模型、Base URL 主机名、RunResult、修改相对路径和测试摘要，不记录 Key、请求头或完整 prompt。

**未完成：** CredentialStore 最终状态为 `configured=False`。自动从 Git 历史读取凭据并联网的操作被安全审批拒绝，且本次没有完成必要的人工隐藏输入；未发起请求，因而没有 RunResult、修改路径或真实 API 测试摘要。临时项目已删除，CredentialStore 无残留。

- [ ] **Step 3: 在干净 Windows 10/11 x64 环境验证发行物**

目标机不得安装本项目 Python/uv 环境。下载/复制 exe 与 SHA-256，复核 hash，依次运行 `--help`、`credential set/status/clear`、`demo all` 和一次真实任务；记录 SmartScreen 行为、退出码和清理结果。

**未完成：** 本次机器是已安装 Python/uv 的现有 Windows 11 开发机。当前机 exe `--help`、`demo all` 和 SHA-256 复核只能作为本地冒烟，不能替代干净 Windows 10/11 x64 证据；SmartScreen、凭据生命周期和真实任务均未在目标机验证。

- [x] **Step 4: 获取最后一次 GitLab CI pass 证据**

保存 pipeline URL、commit SHA、`unit-test` job 名和 pass 时间到 `docs/evidence/ci-last-pass.md`。若无远端或 CI 未 pass，本 task 保持未完成，不用本地结果冒充 CI。

**验收记录（2026-08-12）：** 完整 `main@762b738` 已推送到 NJU GitLab；用户登录后确认 [Pipeline #320523](https://git.nju.edu.cn/wyl510/se-agent/-/pipelines/320523) 的 `unit-test` 为绿色 passed。证据见 `docs/evidence/ci-last-pass.md`。

- [x] **Step 5: 执行已知会失败的历史凭据门禁**

Run: `pwsh -NoProfile -File scripts/scan-history.ps1`

Expected under current accepted history: exit `1`，只显示 `77da924` 相关 commit/path，不显示 Key。立即停止 Release，不运行历史重写。只有用户以后明确授权修复、Key 已处理且扫描退出 `0`，AC-24 才能勾选。

**验收记录（2026-08-11）：** 脚本按预期退出 `1`，输出仅含 commit/path 元数据并包含 `77da924`；没有输出匹配内容。未重写历史，AC-24 保持未完成，Release 被阻断。

- [ ] **Step 6: 检查 WebUI 课程冲突**

若课程方书面确认 A 项可用纯 CLI，记录确认来源；若没有确认，`release-checklist.md` 必须标记“WebUI 最终清单项未满足”，不得声称课程要求全部完成。实现 WebUI 属于新的 SPEC 变更，不在本 PLAN 偷加。

**未完成：** 未找到课程方书面豁免，且仓库明确只有 CLI；“WebUI 最终清单项未满足”。本 task 未增加 WebUI 或修改 SPEC。

- [ ] **Step 7: 所有门禁通过后才发布**

仅当离线测试、真实 API、新机、GitLab CI、当前树扫描、历史扫描以及 WebUI 例外/实现均有通过证据时，创建版本 tag 并让 GitHub Actions 发布。任一项失败则保留本地可运行产物，但不创建公开 Release。

**未完成且禁止发布：** GitLab CI 已通过；真实 API、干净新机、历史零凭据和 WebUI 门禁仍未满足，未创建 tag 或 Release。

- [x] **Step 8: 更新过程证据并提交**

在 `PLAN.md` 标记完成项和 commit/PR，在 `AGENT_LOG.md` 记录技能、agent、人工干预和验证输出。不得把 `REFLECTION.md` 交给 AI 代写。

```powershell
git add -- README.md PLAN.md AGENT_LOG.md docs/evidence
git commit -m "docs: 记录最终验收证据"
```

**实现记录（2026-08-11）：** 本提交更新 README、PLAN、AGENT_LOG 与 `docs/evidence`，如实记录当前不可发布状态；没有创建 `REFLECTION.md`、tag 或 Release。最终证据集成见 [PR #15](https://github.com/01w-01/SE-agent/pull/15)；外部 CI 与其他发布阻塞仍保持未完成。

### CI 稳定性 Hotfix：隔离 pytest 字节码缓存

PR #14/#15 的 branch push 检查曾间歇失败，而同提交 PR 或 main 检查通过。失败均发生在 feedback demo：错误版与修正版 `clamp.py` 大小相同、修改间隔很短，第二次 pytest 可能复用第一次生成的陈旧 `.pyc`，导致修正后仍失败并在下一轮耗尽 Mock LLM。

采用已批准设计：每次 `TestRunner.run()` 为 pytest 子进程设置唯一的临时 `PYTHONPYCACHEPREFIX`，结束后清理；不删除或遍历用户工作区的 `__pycache__`，不改变公开接口。真实回归通过同尺寸改写并恢复相同 mtime 稳定复现旧实现 RED，最小实现后 GREEN。门禁为 TestRunner/feedback `235 passed, 1 skipped`、feedback 连续 10 轮共 20 项通过、全量 `751 passed, 1 skipped`，Ruff、两个白名单文件 format、三项 demo、当前树扫描和 diff check 均通过。代价是全量测试增至约 199 秒，单次 feedback 仍低于 60 秒 pytest 超时。集成见 [PR #16](https://github.com/01w-01/SE-agent/pull/16)。

---

## 4. 每个 Task 的统一收尾检查

每个 task 的实现 agent 在请求 review 前必须执行：

1. 运行该 task 指定测试，确认目标用例 PASS；
2. 运行 `uv run --project mini-harness pytest -q`；
3. 运行 `uv run --project mini-harness ruff check mini-harness/src mini-harness/tests`；
4. 运行 `git diff --check`；
5. 检查 `git status --short`，确保没有 `.env`、凭据、恢复材料、构建产物或无关用户文件；
6. 调用 `requesting-code-review`，先检查 SPEC/PLAN 合规，再检查代码质量；
7. 修正 review 问题并重新运行全部验证；
8. 在同一 task branch 更新 PLAN/AGENT_LOG 证据，创建 PR；
9. PR 合并后确认 `main` CI pass，再安全移除 worktree。

## 5. 完成定义

- Tasks 1–13 全部完成并经 PR 合并，Task 14 的可执行验证均有证据；
- `uv run --project mini-harness pytest` 可在无网络、无真实 Key 情况下一键通过；
- 三项 Mock 机制演示确定、重复运行一致；
- 真实和 Mock LLM 共用同一 AgentLoop；
- Windows x64 exe 在干净环境可运行；
- README、SPEC、PLAN、SPEC_PROCESS、AGENT_LOG、CI、机制演示和分发配置齐全；
- 任何回滚不完整、凭据扫描命中、CI 失败或课程冲突未解决，都必须报告实际状态，不能标记“全部完成”；
- `REFLECTION.md` 由学生本人完成，AI 只可按课程规则辅助润色并注明。

## 6. SPEC 可追踪矩阵

| SPEC 范围 | 实现 task | 主要验证 |
|---|---|---|
| F-01 CLI、应用入口与配置 | 2、3、11、12 | config、loop、CLI 测试；核心不导入 CLI |
| F-02 凭据管理 | 4、12、14 | Fake keyring、隐藏输入、新机生命周期 |
| F-03 上下文与 LLM 决策 | 9、11 | parser/context/Fake SDK、真实 API 冒烟 |
| F-04 文件发现与读取 | 5 | 越界、保护路径、reparse、大小/编码测试 |
| F-05 创建与精确修改 | 6 | 唯一匹配、哈希冲突、原子写测试 |
| F-06 治理与 HITL | 7、11、12 | ALLOW/CONFIRM/DENY、未调用工具、guardrail demo |
| F-07 pytest 执行器 | 8 | 真实临时 pytest、超时和进程树测试 |
| F-08 反馈闭环 | 8、9、11、12 | 分类、脱敏、指纹、回灌和 clamp demo |
| F-09 文件事务与回滚 | 6、11、12 | 故障注入、回滚不完整、no-progress demo |
| F-10 记忆 | 10、11、12 | 默认关闭、白名单、损坏隔离、CLI clear |
| F-11 可观测性 | 2、11、12 | RunEvent、Console/JSONL sink、禁止字段 |
| F-12 分发与首次运行 | 13、14 | exe、SHA-256、CI、新 Windows 环境 |
| 六个 harness 维度 | 2–13 | Mock LLM 下对决策/工具/记忆/治理/反馈/配置的确定性测试 |
| 反馈闭环重点贡献 | 8、9、11、12 | 失败分类、最新反馈优先、动作变化、完成/停机门禁 |
| 三项机制演示 | 12 | guardrail、feedback、no-progress |
| 安全与凭据威胁模型 | 1、4–8、11、13、14 | 当前树/历史扫描、路径/事务/审批、Credential Manager |
| 性能与可靠性 | 3、5、8、11、13、14 | 固定上限、超时、无进展、启动/构建/新机记录 |
| AC-01–AC-15 产品验收 | 4–14 | 对应模块测试、机制演示、真实 API 和新机验证 |
| AC-16–AC-23 工程验收 | 1–14 | 模块边界、TDD、CI、README、课程文档和发行物 |
| AC-24 历史零凭据 | 14 | 当前已知失败；未经用户授权不重写历史、不发布 |
