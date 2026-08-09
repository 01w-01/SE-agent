from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fbw_harness.context import ContextBudgetError, ContextBuilder, ContextInputError
from fbw_harness.llm import LLMDecisionError, OpenAIClientFactory, OpenAICompatibleClient
from fbw_harness.mock_llm import MockLLMExhaustedError, ScriptedMockLLM
from fbw_harness.models import (
    Action,
    ActionKind,
    Feedback,
    FeedbackKind,
    Observation,
    ProjectMemory,
    RawDecision,
    RawToolCall,
    RunRequest,
)
from fbw_harness.parser import ACTION_TOOLS, ActionParseError, ActionParser
from fbw_harness.workspace import FileSnapshot


def test_parser_converts_list_files_tool_call_to_action() -> None:
    decision = RawDecision(tool_calls=(RawToolCall(name="list_files", arguments="{}"),))

    assert ActionParser().parse(decision) == Action(kind=ActionKind.LIST_FILES)


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("read_file", '{"path":"src/app.py"}', Action(ActionKind.READ_FILE, path="src/app.py")),
        (
            "create_file",
            '{"path":"new.py","content":"print(1)"}',
            Action(ActionKind.CREATE_FILE, path="new.py", content="print(1)"),
        ),
        (
            "edit_file",
            ('{"path":"app.py","expected_sha256":"abc","old_text":"before","new_text":"after"}'),
            Action(
                ActionKind.EDIT_FILE,
                path="app.py",
                expected_sha256="abc",
                old_text="before",
                new_text="after",
            ),
        ),
        ("finish", '{"reason":"done"}', Action(ActionKind.FINISH, reason="done")),
    ],
)
def test_parser_converts_each_parameterized_tool_call(
    name: str, arguments: str, expected: Action
) -> None:
    decision = RawDecision(tool_calls=(RawToolCall(name=name, arguments=arguments),))

    assert ActionParser().parse(decision) == expected


def test_parser_accepts_object_fields_in_any_json_order() -> None:
    decision = RawDecision(
        tool_calls=(
            RawToolCall(
                name="edit_file",
                arguments=(
                    '{"new_text":"after","old_text":"before",'
                    '"expected_sha256":"abc","path":"app.py"}'
                ),
            ),
        )
    )

    assert ActionParser().parse(decision) == Action(
        ActionKind.EDIT_FILE,
        path="app.py",
        expected_sha256="abc",
        old_text="before",
        new_text="after",
    )


@pytest.mark.parametrize(
    "calls",
    [
        (),
        (
            RawToolCall(name="list_files", arguments="{}"),
            RawToolCall(name="finish", arguments='{"reason":"done"}'),
        ),
    ],
)
def test_parser_rejects_any_tool_call_count_other_than_one(
    calls: tuple[RawToolCall, ...],
) -> None:
    with pytest.raises(ActionParseError, match=r"^invalid action decision$"):
        ActionParser().parse(RawDecision(tool_calls=calls))


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("shell", "{}"),
        ("list_files", "not-json"),
        ("list_files", "[]"),
        ("list_files", "null"),
        ("list_files", '{"extra":1}'),
        ("read_file", "{}"),
        ("read_file", '{"path":1}'),
        ("read_file", '{"path":"a.py","content":"cross-action"}'),
        ("create_file", '{"path":"a.py"}'),
        ("create_file", '{"path":"a.py","content":false}'),
        (
            "edit_file",
            '{"path":"a.py","expected_sha256":"x","old_text":"old"}',
        ),
        (
            "edit_file",
            '{"path":"a.py","expected_sha256":"x","old_text":"old","new_text":7}',
        ),
        ("finish", "{}"),
        ("finish", '{"reason":null}'),
        ("finish", '{"reason":"done","path":"a.py"}'),
    ],
)
def test_parser_rejects_unknown_missing_cross_action_and_wrong_type_fields(
    name: str, arguments: str
) -> None:
    with pytest.raises(ActionParseError, match=r"^invalid action decision$"):
        ActionParser().parse(RawDecision(tool_calls=(RawToolCall(name=name, arguments=arguments),)))


@pytest.mark.parametrize(
    "arguments",
    [
        '{"path":"first","path":"second"}',
        '{"path":NaN}',
        '{"path":Infinity}',
        '{"path":-Infinity}',
    ],
)
def test_parser_rejects_duplicate_keys_and_non_finite_json(arguments: str) -> None:
    with pytest.raises(ActionParseError, match=r"^invalid action decision$"):
        ActionParser().parse(
            RawDecision(tool_calls=(RawToolCall(name="read_file", arguments=arguments),))
        )


def test_parser_error_does_not_leak_payload_or_chain_underlying_exception() -> None:
    secret = "sk-private-parser-payload"

    with pytest.raises(ActionParseError) as caught:
        ActionParser().parse(
            RawDecision(
                tool_calls=(RawToolCall(name="read_file", arguments=f'{{"path":"{secret}"'),)
            )
        )

    assert str(caught.value) == "invalid action decision"
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_action_tools_schema_matches_all_parser_actions_and_rejects_extra_fields() -> None:
    tools = json.loads(json.dumps(ACTION_TOOLS))
    functions = {item["function"]["name"]: item["function"] for item in tools}

    assert tuple(functions) == tuple(kind.value for kind in ActionKind)
    assert {
        name: (
            tuple(function["parameters"]["properties"]),
            tuple(function["parameters"]["required"]),
        )
        for name, function in functions.items()
    } == {
        "list_files": ((), ()),
        "read_file": (("path",), ("path",)),
        "create_file": (("path", "content"), ("path", "content")),
        "edit_file": (
            ("path", "expected_sha256", "old_text", "new_text"),
            ("path", "expected_sha256", "old_text", "new_text"),
        ),
        "finish": (("reason",), ("reason",)),
    }
    assert all(
        function["parameters"]
        == {
            "type": "object",
            "properties": function["parameters"]["properties"],
            "required": function["parameters"]["required"],
            "additionalProperties": False,
        }
        for function in functions.values()
    )
    assert all(
        schema == {"type": "string"}
        for function in functions.values()
        for schema in function["parameters"]["properties"].values()
    )


class _HTTPFailure(Exception):
    def __init__(self, status_code: int, detail: str = "private transport detail") -> None:
        super().__init__(detail)
        self.status_code = status_code


class _FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeSDK:
    def __init__(self, outcomes: list[object]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(outcomes))


def _sdk_response(
    *calls: tuple[object, object], content: object = "assistant note"
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=[
                        SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))
                        for name, arguments in calls
                    ],
                )
            )
        ]
    )


def test_llm_decide_sends_exact_required_request_and_returns_all_tool_calls() -> None:
    response = _sdk_response(
        ("read_file", '{"path":"app.py"}'),
        ("finish", '{"reason":"done"}'),
    )
    sdk = _FakeSDK([response])
    client = OpenAICompatibleClient(client=sdk, model="deepseek-v4-flash")
    messages = [{"role": "user", "content": "fix it"}]
    tools = [{"type": "function", "function": {"name": "read_file"}}]

    result = client.decide(messages, tools)

    assert result == RawDecision(
        tool_calls=(
            RawToolCall("read_file", '{"path":"app.py"}'),
            RawToolCall("finish", '{"reason":"done"}'),
        ),
        content="assistant note",
    )
    assert sdk.chat.completions.calls == [
        {
            "model": "deepseek-v4-flash",
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
        }
    ]


def test_llm_decide_folds_non_string_content_to_empty_string() -> None:
    client = OpenAICompatibleClient(
        client=_FakeSDK([_sdk_response(("list_files", "{}"), content=[{"text": "no"}])]),
        model="model",
    )

    assert client.decide([], []).content == ""


@pytest.mark.parametrize(
    "transient",
    [TimeoutError("private timeout"), ConnectionError("private connection"), _HTTPFailure(429)],
)
def test_llm_decide_retries_transient_errors_until_third_attempt(
    transient: BaseException,
) -> None:
    sdk = _FakeSDK([transient, transient, _sdk_response(("list_files", "{}"))])
    client = OpenAICompatibleClient(client=sdk, model="model")

    result = client.decide([], [])

    assert result.tool_calls == (RawToolCall("list_files", "{}"),)
    assert len(sdk.chat.completions.calls) == 3


@pytest.mark.parametrize("status", [500, 503])
def test_llm_decide_retries_server_errors(status: int) -> None:
    sdk = _FakeSDK([_HTTPFailure(status), _sdk_response(("list_files", "{}"))])

    OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_llm_decide_does_not_retry_permanent_client_errors(status: int) -> None:
    sdk = _FakeSDK([_HTTPFailure(status)])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$"):
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 1


def test_llm_decide_stops_after_three_transient_attempts_without_sleeping() -> None:
    sdk = _FakeSDK([_HTTPFailure(500), _HTTPFailure(500), _HTTPFailure(500)])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$"):
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 3


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace()]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x"))]),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="x", tool_calls=[SimpleNamespace()])
                )
            ]
        ),
        _sdk_response((7, "{}")),
        _sdk_response(("list_files", 7)),
    ],
)
def test_llm_decide_maps_malformed_responses_without_retry(response: object) -> None:
    sdk = _FakeSDK([response])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_llm_decide_maps_response_property_exceptions_without_leaking_detail() -> None:
    class ExplodingResponse:
        @property
        def choices(self) -> object:
            raise RuntimeError("private lazy response detail")

    sdk = _FakeSDK([ExplodingResponse()])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert "private lazy response detail" not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(sdk.chat.completions.calls) == 1


def test_llm_error_does_not_leak_key_url_response_or_exception_detail() -> None:
    secrets = (
        "sk-private-llm-key",
        "https://private.example/v1",
        "private response body",
        "private transport detail",
    )
    sdk = _FakeSDK([_HTTPFailure(401, " | ".join(secrets))])

    with pytest.raises(LLMDecisionError) as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    rendered = repr(caught.value)
    assert str(caught.value) == "LLM decision failed"
    assert all(secret not in rendered for secret in secrets)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_openai_factory_uses_no_sdk_retries_and_wrapper_does_not_store_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sdk = _FakeSDK([_sdk_response(("list_files", "{}"))])

    def fake_openai(**kwargs: object) -> _FakeSDK:
        captured.update(kwargs)
        return sdk

    monkeypatch.setattr("fbw_harness.llm.OpenAI", fake_openai)
    key = "sk-private-factory-key"

    client = OpenAIClientFactory().create(
        base_url="https://school.example/v1", model="model", api_key=key
    )

    assert captured == {
        "base_url": "https://school.example/v1",
        "api_key": key,
        "max_retries": 0,
    }
    assert not hasattr(client, "api_key")
    assert key not in repr(client)
    assert client.decide([], []).tool_calls == (RawToolCall("list_files", "{}"),)


def test_scripted_mock_returns_immutable_script_in_order_then_exhausts() -> None:
    first = RawDecision((RawToolCall("list_files", "{}"),))
    second = RawDecision((RawToolCall("finish", '{"reason":"done"}'),))
    source = [first, second]
    client = ScriptedMockLLM(source)
    source.clear()

    assert client.decide([], []) == first
    assert client.decide([], []) == second
    with pytest.raises(MockLLMExhaustedError, match=r"^mock LLM script exhausted$") as caught:
        client.decide([], [])
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_scripted_mock_records_deep_copied_message_and_tool_snapshots() -> None:
    client = ScriptedMockLLM([RawDecision((RawToolCall("list_files", "{}"),))])
    messages = [{"role": "user", "content": {"nested": ["original"]}}]
    tools = [{"type": "function", "function": {"name": "list_files"}}]

    client.decide(messages, tools)
    messages[0]["content"]["nested"][0] = "mutated"  # type: ignore[index]
    tools[0]["function"]["name"] = "mutated"  # type: ignore[index]

    recorded = client.calls[0]
    assert recorded.messages == [{"role": "user", "content": {"nested": ["original"]}}]
    assert recorded.tools == [{"type": "function", "function": {"name": "list_files"}}]


def test_scripted_mock_call_records_cannot_mutate_internal_snapshots() -> None:
    client = ScriptedMockLLM([RawDecision((RawToolCall("list_files", "{}"),))])
    client.decide([{"role": "user", "content": "original"}], [])

    client.calls[0].messages[0]["content"] = "external mutation"

    assert client.calls[0].messages[0]["content"] == "original"


def _request(task: str = "修复 clamp 边界") -> RunRequest:
    return RunRequest(
        workspace=Path(r"C:\private\workspace"),
        task=task,
        base_url="https://private.example/v1",
        model="deepseek-v4-flash",
        config_path=Path(r"C:\private\config.toml"),
        config_overrides={"max_rounds": 3},
    )


def _feedback(output_tail: str = "tests failed") -> Feedback:
    return Feedback(
        kind=FeedbackKind.ASSERTION_FAILURE,
        passed=False,
        exit_code=1,
        summary="Pytest reported an assertion failure.",
        failed_tests=("tests/test_b.py::test_b", "tests/test_a.py::test_a"),
        output_tail=output_tail,
        fingerprint="fingerprint-1",
    )


def _sections(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    return [json.loads(message["content"]) for message in messages]  # type: ignore[arg-type]


def _serialized_length(messages: list[dict[str, object]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False, sort_keys=True))


def test_context_orders_sections_and_serializes_only_declared_fields() -> None:
    memory = ProjectMemory(
        version=2,
        project_notes="Use pytest.",
        last_success_summary="Baseline passed.",
        updated_at="2026-08-09T00:00:00Z",
    )
    files = [
        FileSnapshot("src/z.py", "z = 1", "sha-z"),
        FileSnapshot("src/a.py", "a = 1", "sha-a"),
    ]
    observations = [
        Observation("read_file", True, "read a", output_tail="ok"),
        Observation("test", False, "test failed", exit_code=1, output_tail="failure"),
    ]

    messages = ContextBuilder(20_000).build(
        request=_request(),
        observations=observations,
        feedback=_feedback(),
        memory=memory,
        files=files,
    )
    sections = _sections(messages)

    assert [section["section"] for section in sections] == [
        "safety",
        "task",
        "tool_protocol",
        "project_memory",
        "files",
        "observations",
        "latest_feedback",
    ]
    assert [message["role"] for message in messages[:3]] == ["system", "user", "system"]
    assert sections[1] == {
        "section": "task",
        "task": "修复 clamp 边界",
        "context_budget_chars": 20_000,
    }
    assert set(sections[3]) == {"section", "memory"}
    assert sections[3]["memory"] == {
        "version": 2,
        "project_notes": "Use pytest.",
        "last_success_summary": "Baseline passed.",
        "updated_at": "2026-08-09T00:00:00Z",
    }
    assert [item["path"] for item in sections[4]["files"]] == ["src/a.py", "src/z.py"]
    assert set(sections[4]["files"][0]) == {"path", "text", "sha256"}
    assert set(sections[5]["observations"][0]) == {
        "kind",
        "success",
        "summary",
        "exit_code",
        "output_tail",
    }
    assert set(sections[-1]["feedback"]) == {
        "kind",
        "passed",
        "exit_code",
        "summary",
        "failed_tests",
        "fingerprint",
        "output_tail",
    }
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    assert "https://private.example/v1" not in serialized
    assert r"C:\private\workspace" not in serialized
    assert r"C:\private\config.toml" not in serialized
    assert "config_overrides" not in serialized


def test_context_normalizes_sets_order_and_unicode_stably() -> None:
    feedback = Feedback(
        kind=FeedbackKind.ASSERTION_FAILURE,
        passed=False,
        exit_code=1,
        summary="你好🙂",
        failed_tests=("b.py::test_b", "a.py::test_a", "b.py::test_b"),
        output_tail="失败🙂",
        fingerprint="same",
    )
    builder = ContextBuilder(20_000)
    kwargs = {
        "request": _request("处理 Unicode 🙂"),
        "observations": [Observation("test", False, "你好🙂")],
        "feedback": feedback,
        "memory": None,
        "files": [
            FileSnapshot("z.py", "最后", "z"),
            FileSnapshot("a.py", "最先", "a"),
        ],
    }

    first = builder.build(**kwargs)
    second = builder.build(**kwargs)
    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)

    assert first == second
    assert "你好🙂" in serialized
    assert "\\u4f60" not in serialized
    feedback_data = _sections(first)[-1]["feedback"]
    assert feedback_data["failed_tests"] == ["a.py::test_a", "b.py::test_b"]


def test_context_remains_within_budget_and_preserves_latest_feedback_last() -> None:
    feedback = _feedback("LATEST-FEEDBACK-MUST-REMAIN")
    observations = [
        Observation("test", False, f"observation-{index}", output_tail="O" * 2_000)
        for index in range(20)
    ]
    files = [
        FileSnapshot(f"src/{index}.py", f"FILE-{index}-" + "F" * 3_000, f"sha-{index}")
        for index in range(5)
    ]

    messages = ContextBuilder(2_000).build(
        request=_request(),
        observations=observations,
        feedback=feedback,
        memory=ProjectMemory(project_notes="optional memory"),
        files=files,
    )
    sections = _sections(messages)
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert _serialized_length(messages) <= 2_000
    assert sections[-1]["section"] == "latest_feedback"
    assert sections[-1]["feedback"]["output_tail"] == "LATEST-FEEDBACK-MUST-REMAIN"
    assert "FILE-0-" not in serialized
    assert "O" * 200 not in serialized


def test_context_removes_oldest_observation_body_before_newer_body() -> None:
    observations = [
        Observation("test", False, "old", output_tail="OLDEST-BODY-" + "x" * 700),
        Observation("test", False, "new", output_tail="NEWEST-BODY-" + "y" * 700),
    ]

    messages = ContextBuilder(2_300).build(
        request=_request(),
        observations=observations,
        feedback=_feedback(),
        memory=None,
        files=[],
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert "OLDEST-BODY" not in serialized
    assert "NEWEST-BODY" in serialized


@pytest.mark.parametrize("max_chars", [1, 10, 100])
def test_context_raises_fixed_error_when_required_sections_exceed_budget(
    max_chars: int,
) -> None:
    with pytest.raises(ContextBudgetError, match=r"^context budget exceeded$") as caught:
        ContextBuilder(max_chars).build(
            request=_request(), observations=[], feedback=_feedback(), memory=None, files=[]
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("task", "feedback"),
    [
        ("T" * 100_000, _feedback()),
        ("normal", _feedback("F" * 100_000)),
    ],
    ids=("huge-task", "huge-feedback"),
)
def test_context_rejects_unbounded_required_task_or_feedback(task: str, feedback: Feedback) -> None:
    with pytest.raises(ContextBudgetError, match=r"^context budget exceeded$"):
        ContextBuilder(200_000).build(
            request=_request(task),
            observations=[],
            feedback=feedback,
            memory=None,
            files=[],
        )


@pytest.mark.parametrize(
    "path",
    [
        r"C:\outside\file.py",
        "/outside/file.py",
        "../escape.py",
        "src/../escape.py",
        "src/./file.py",
        "src/file.py/",
        ".",
    ],
)
def test_context_rejects_unsafe_file_snapshot_paths(path: str) -> None:
    with pytest.raises(ContextInputError, match=r"^invalid context file path$"):
        ContextBuilder(20_000).build(
            request=_request(),
            observations=[],
            feedback=None,
            memory=None,
            files=[FileSnapshot(path, "text", "sha")],
        )


def test_context_redacts_secrets_urls_and_absolute_paths_from_declared_text() -> None:
    sensitive = (
        "PRIVATE_API_VALUE",
        "[REDACTED-HISTORICAL-TOKEN]",
        "https://secret.example/v1",
        r"C:\Users\secret\project\app.py",
        "/home/secret/project/app.py",
    )
    output = (
        'api_key="PRIVATE_API_VALUE" '
        "[REDACTED-HISTORICAL-TOKEN] "
        "https://secret.example/v1 "
        r"C:\Users\secret\project\app.py "
        "/home/secret/project/app.py"
    )

    messages = ContextBuilder(20_000).build(
        request=_request("fix safely"),
        observations=[Observation("test", False, output, output_tail=output)],
        feedback=_feedback(output),
        memory=ProjectMemory(project_notes=output),
        files=[FileSnapshot("app.py", output, "sha")],
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert all(value not in serialized for value in sensitive)
    assert "[REDACTED]" in serialized
    assert "[PATH]" in serialized
    assert "[URL]" in serialized


def test_context_ignores_extra_runtime_attributes_instead_of_serializing_object_dicts() -> None:
    memory = SimpleNamespace(
        version=1,
        project_notes="notes",
        last_success_summary="ok",
        updated_at="now",
        api_key="sk-extra-memory-secret",
        headers={"Authorization": "secret"},
    )
    file = SimpleNamespace(
        path="app.py",
        text="safe",
        sha256="sha",
        recovery_path=r"C:\private\recovery",
        base_url="https://private.example/v1",
    )

    messages = ContextBuilder(20_000).build(
        request=_request(), observations=[], feedback=None, memory=memory, files=[file]
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert "sk-extra-memory-secret" not in serialized
    assert "Authorization" not in serialized
    assert "recovery_path" not in serialized
    assert "https://private.example/v1" not in serialized


def test_context_bounds_single_huge_optional_file_and_observation() -> None:
    huge_file = "FILE-START-" + "f" * 100_000 + "-FILE-END"
    huge_observation = "OBS-START-" + "o" * 100_000 + "-OBS-END"

    messages = ContextBuilder(20_000).build(
        request=_request(),
        observations=[Observation("test", False, huge_observation, output_tail=huge_observation)],
        feedback=_feedback(),
        memory=None,
        files=[FileSnapshot("huge.py", huge_file, "sha")],
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert _serialized_length(messages) <= 20_000
    assert "-FILE-END" not in serialized
    assert "-OBS-END" not in serialized
