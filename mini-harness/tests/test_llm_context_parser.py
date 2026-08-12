from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fbw_harness.context import ContextBudgetError, ContextBuilder, ContextInputError
from fbw_harness.llm import (
    MAX_ASSISTANT_CONTENT_CHARS,
    MAX_TOOL_ARGUMENT_CHARS,
    MAX_TOOL_CALLS,
    MAX_TOOL_NAME_CHARS,
    LLMDecisionError,
    OpenAIClientFactory,
    OpenAICompatibleClient,
)
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
from fbw_harness.parser import ActionParseError, ActionParser, build_action_tools
from fbw_harness.workspace import FileSnapshot


def _synthetic_api_key(label: str) -> str:
    return "".join(("s", "k", "-", label))  # noqa: FLY002 - avoid tracked key literals.


def _sha(character: str = "a") -> str:
    return character * 64


class _NoFullEncodeText(str):
    def encode(self, *args: object, **kwargs: object) -> bytes:
        raise AssertionError("the complete optional text must not be encoded")

    def __getitem__(self, key: object) -> str:
        return str(super().__getitem__(key))  # type: ignore[index]


class _EncodeTrackingText(str):
    encode_called: bool = False

    def encode(self, *args: object, **kwargs: object) -> bytes:
        self.encode_called = True
        return super().encode(*args, **kwargs)  # type: ignore[arg-type]


def _exception_graph_text(error: BaseException) -> str:
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    parts: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        parts.append(repr(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return " ".join(parts)


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
    secret = _synthetic_api_key("private-parser-payload")

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


def test_parser_rejects_non_raw_tool_call_even_if_it_has_matching_attributes() -> None:
    impostor = SimpleNamespace(name="list_files", arguments="{}")
    decision = RawDecision(tool_calls=(impostor,))  # type: ignore[arg-type]

    with pytest.raises(ActionParseError, match=r"^invalid action decision$"):
        ActionParser().parse(decision)


@pytest.mark.parametrize("boundary", ["decision", "call"])
def test_parser_maps_lazy_property_exceptions_without_leaking_graph(boundary: str) -> None:
    secret = f"private-{boundary}-property-detail"

    if boundary == "decision":

        class ExplodingDecision(RawDecision):
            @property
            def tool_calls(self) -> tuple[RawToolCall, ...]:  # type: ignore[override]
                raise RuntimeError(secret)

        decision = object.__new__(ExplodingDecision)
    else:

        class ExplodingCall(RawToolCall):
            @property
            def name(self) -> str:  # type: ignore[override]
                raise RuntimeError(secret)

        call = object.__new__(ExplodingCall)
        decision = RawDecision(tool_calls=(call,))

    with pytest.raises(ActionParseError, match=r"^invalid action decision$") as caught:
        ActionParser().parse(decision)

    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_parser_rejects_tuple_subclass_without_touching_overridden_methods() -> None:
    secret = _synthetic_api_key("lying-parser-calls")
    touched = {"len": False, "iter": False, "getitem": False}

    class LyingCalls(tuple[RawToolCall, ...]):
        def __len__(self) -> int:
            touched["len"] = True
            raise RuntimeError(secret)

        def __iter__(self) -> object:
            touched["iter"] = True
            raise RuntimeError(secret)

        def __getitem__(self, key: object) -> RawToolCall:
            touched["getitem"] = True
            raise RuntimeError(secret)

    calls = LyingCalls((RawToolCall("list_files", "{}"),))

    class LyingDecision(RawDecision):
        @property
        def tool_calls(self) -> tuple[RawToolCall, ...]:  # type: ignore[override]
            return calls

    decision = object.__new__(LyingDecision)

    with pytest.raises(ActionParseError, match=r"^invalid action decision$") as caught:
        ActionParser().parse(decision)

    assert touched == {"len": False, "iter": False, "getitem": False}
    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("field", ["name", "arguments"])
def test_parser_rejects_string_subclass_without_touching_overrides(field: str) -> None:
    secret = _synthetic_api_key(f"lying-parser-{field}")
    touched = {"len": False, "getitem": False, "encode": False}

    class LyingText(str):
        def __len__(self) -> int:
            touched["len"] = True
            raise RuntimeError(secret)

        def __getitem__(self, key: object) -> str:
            touched["getitem"] = True
            raise RuntimeError(secret)

        def encode(self, *args: object, **kwargs: object) -> bytes:
            touched["encode"] = True
            raise RuntimeError(secret)

    name: str = LyingText("read_file") if field == "name" else "read_file"
    arguments: str = LyingText('{"path":"app.py"}') if field == "arguments" else "{}"
    decision = RawDecision((RawToolCall(name, arguments),))

    with pytest.raises(ActionParseError, match=r"^invalid action decision$") as caught:
        ActionParser().parse(decision)

    assert touched == {"len": False, "getitem": False, "encode": False}
    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_parser_accepts_valid_json_at_exact_argument_limit() -> None:
    wrapper_chars = len('{"path":""}')
    arguments = '{"path":"' + "x" * (MAX_TOOL_ARGUMENT_CHARS - wrapper_chars) + '"}'

    action = ActionParser().parse(
        RawDecision((RawToolCall(name="read_file", arguments=arguments),))
    )

    assert action.kind is ActionKind.READ_FILE
    assert action.path is not None
    assert len(action.path) == MAX_TOOL_ARGUMENT_CHARS - wrapper_chars


def test_parser_rejects_argument_limit_plus_one_before_encoding() -> None:
    arguments = _EncodeTrackingText("x" * (MAX_TOOL_ARGUMENT_CHARS + 1))

    with pytest.raises(ActionParseError, match=r"^invalid action decision$") as caught:
        ActionParser().parse(RawDecision((RawToolCall(name="read_file", arguments=arguments),)))

    assert arguments.encode_called is False
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_parser_rejects_overlong_name_before_accessing_argument_payload() -> None:
    arguments = _EncodeTrackingText("{}")
    name = "n" * (MAX_TOOL_NAME_CHARS + 1)

    with pytest.raises(ActionParseError, match=r"^invalid action decision$"):
        ActionParser().parse(RawDecision((RawToolCall(name=name, arguments=arguments),)))

    assert arguments.encode_called is False


def test_parser_rejects_more_than_maximum_tool_calls_with_fixed_error() -> None:
    calls = tuple(RawToolCall("list_files", "{}") for _ in range(MAX_TOOL_CALLS + 1))

    with pytest.raises(ActionParseError, match=r"^invalid action decision$") as caught:
        ActionParser().parse(RawDecision(calls))

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_action_tools_schema_matches_all_parser_actions_and_rejects_extra_fields() -> None:
    tools = json.loads(json.dumps(build_action_tools()))
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


def test_action_tools_are_fresh_and_deep_mutation_cannot_poison_future_schema() -> None:
    first = build_action_tools()
    first[0]["function"]["name"] = "poisoned"  # type: ignore[index]
    first[1]["function"]["parameters"]["properties"]["path"]["type"] = "number"  # type: ignore[index]

    second = build_action_tools()

    assert second[0]["function"]["name"] == "list_files"  # type: ignore[index]
    assert (
        second[1]["function"]["parameters"]["properties"]["path"]  # type: ignore[index]
        == {"type": "string"}
    )
    assert ActionParser().parse(
        RawDecision((RawToolCall("read_file", '{"path":"app.py"}'),))
    ) == Action(ActionKind.READ_FILE, path="app.py")


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


def test_llm_accepts_exact_tool_output_limits_and_sixteen_calls() -> None:
    name = "n" * MAX_TOOL_NAME_CHARS
    arguments = "a" * MAX_TOOL_ARGUMENT_CHARS
    calls = [(name, arguments)] + [("list_files", "{}")] * (MAX_TOOL_CALLS - 1)
    client = OpenAICompatibleClient(client=_FakeSDK([_sdk_response(*calls)]), model="model")

    result = client.decide([], [])

    assert len(result.tool_calls) == MAX_TOOL_CALLS
    assert len(result.tool_calls[0].name) == MAX_TOOL_NAME_CHARS
    assert len(result.tool_calls[0].arguments) == MAX_TOOL_ARGUMENT_CHARS


def test_llm_rejects_seventeenth_tool_call_without_accessing_it() -> None:
    access = {"bomb": False}

    class BombCall:
        @property
        def function(self) -> object:
            access["bomb"] = True
            raise RuntimeError("seventeenth call must not be inspected")

    safe_calls = [
        SimpleNamespace(function=SimpleNamespace(name="list_files", arguments="{}"))
        for _ in range(MAX_TOOL_CALLS)
    ]
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=[*safe_calls, BombCall()])
            )
        ]
    )
    sdk = _FakeSDK([response])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert access["bomb"] is False
    assert len(sdk.chat.completions.calls) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_llm_rejects_list_subclass_without_touching_overridden_methods() -> None:
    secret = _synthetic_api_key("lying-llm-calls")
    touched = {"len": False, "iter": False, "getitem": False}

    class LyingCalls(list[object]):
        def __len__(self) -> int:
            touched["len"] = True
            raise RuntimeError(secret)

        def __iter__(self) -> object:
            touched["iter"] = True
            raise RuntimeError(secret)

        def __getitem__(self, key: object) -> object:
            touched["getitem"] = True
            raise RuntimeError(secret)

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=LyingCalls()))]
    )
    sdk = _FakeSDK([response])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert touched == {"len": False, "iter": False, "getitem": False}
    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("field", ["name", "arguments", "content"])
def test_llm_rejects_string_subclass_without_touching_overrides(field: str) -> None:
    secret = _synthetic_api_key(f"lying-llm-{field}")
    touched = {"len": False, "getitem": False, "encode": False}

    class LyingText(str):
        def __len__(self) -> int:
            touched["len"] = True
            raise RuntimeError(secret)

        def __getitem__(self, key: object) -> str:
            touched["getitem"] = True
            raise RuntimeError(secret)

        def encode(self, *args: object, **kwargs: object) -> bytes:
            touched["encode"] = True
            raise RuntimeError(secret)

    name: object = LyingText("list_files") if field == "name" else "list_files"
    arguments: object = LyingText("{}") if field == "arguments" else "{}"
    content: object = LyingText("assistant note") if field == "content" else ""
    sdk = _FakeSDK([_sdk_response((name, arguments), content=content)])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert touched == {"len": False, "getitem": False, "encode": False}
    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("field", ["name", "arguments"])
def test_llm_rejects_tool_field_limit_plus_one(field: str) -> None:
    name = "n" * (MAX_TOOL_NAME_CHARS + (field == "name"))
    arguments = "a" * (MAX_TOOL_ARGUMENT_CHARS + (field == "arguments"))
    sdk = _FakeSDK([_sdk_response((name, arguments))])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_llm_truncates_string_assistant_content_to_fixed_limit() -> None:
    content = "c" * (MAX_ASSISTANT_CONTENT_CHARS + 1)
    client = OpenAICompatibleClient(
        client=_FakeSDK([_sdk_response(("list_files", "{}"), content=content)]),
        model="model",
    )

    result = client.decide([], [])

    assert result.content == "c" * MAX_ASSISTANT_CONTENT_CHARS


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


@pytest.mark.parametrize("status", [401, 403, 404])
def test_llm_decide_does_not_retry_permanent_client_errors(status: int) -> None:
    sdk = _FakeSDK([_HTTPFailure(status)])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$"):
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 1


def test_llm_falls_back_without_tool_choice_after_required_http_400() -> None:
    sdk = _FakeSDK([_HTTPFailure(400), _sdk_response(("list_files", "{}"))])
    client = OpenAICompatibleClient(client=sdk, model="model")

    result = client.decide([], [])

    assert result.tool_calls == (RawToolCall("list_files", "{}"),)
    assert sdk.chat.completions.calls == [
        {"model": "model", "messages": [], "tools": [], "tool_choice": "required"},
        {"model": "model", "messages": [], "tools": []},
    ]


def test_llm_remembers_tools_only_mode_after_compatibility_fallback() -> None:
    sdk = _FakeSDK(
        [
            _HTTPFailure(400),
            _sdk_response(("list_files", "{}")),
            _sdk_response(("finish", '{"reason":"done"}')),
        ]
    )
    client = OpenAICompatibleClient(client=sdk, model="model")

    client.decide([], [])
    result = client.decide([], [])

    assert result.tool_calls == (RawToolCall("finish", '{"reason":"done"}'),)
    assert ["tool_choice" in call for call in sdk.chat.completions.calls] == [
        True,
        False,
        False,
    ]


def test_new_llm_client_starts_in_required_mode_after_another_client_falls_back() -> None:
    first_sdk = _FakeSDK([_HTTPFailure(400), _sdk_response(("list_files", "{}"))])
    OpenAICompatibleClient(client=first_sdk, model="model").decide([], [])
    second_sdk = _FakeSDK([_sdk_response(("list_files", "{}"))])

    OpenAICompatibleClient(client=second_sdk, model="model").decide([], [])

    assert second_sdk.chat.completions.calls == [
        {"model": "model", "messages": [], "tools": [], "tool_choice": "required"}
    ]


def test_llm_maps_second_http_400_without_repeating_compatibility_fallback() -> None:
    sdk = _FakeSDK([_HTTPFailure(400), _HTTPFailure(400)])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 2
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


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


@pytest.mark.parametrize("boundary", ["tool_call", "function"])
def test_llm_maps_lazy_tool_property_exceptions_without_leaking_graph(boundary: str) -> None:
    secret = _synthetic_api_key(f"lazy-{boundary}")

    if boundary == "tool_call":

        class ExplodingCall:
            @property
            def function(self) -> object:
                raise RuntimeError(secret)

        call: object = ExplodingCall()
    else:

        class ExplodingFunction:
            @property
            def name(self) -> str:
                raise RuntimeError(secret)

        call = SimpleNamespace(function=ExplodingFunction())

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call]))]
    )
    sdk = _FakeSDK([response])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(sdk.chat.completions.calls) == 1


def test_llm_treats_exploding_status_property_as_non_transient_and_redacts_graph() -> None:
    secret = "private-status-property-detail"

    class ExplodingStatusError(Exception):
        @property
        def status_code(self) -> int:
            raise RuntimeError(secret)

    sdk = _FakeSDK([ExplodingStatusError("private-sdk-detail")])

    with pytest.raises(LLMDecisionError, match=r"^LLM decision failed$") as caught:
        OpenAICompatibleClient(client=sdk, model="model").decide([], [])

    assert len(sdk.chat.completions.calls) == 1
    assert secret not in _exception_graph_text(caught.value)
    assert "private-sdk-detail" not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_llm_error_does_not_leak_key_url_response_or_exception_detail() -> None:
    secrets = (
        _synthetic_api_key("private-llm-key"),
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
    key = _synthetic_api_key("private-factory-key")

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


@pytest.mark.parametrize(("max_retries", "attempts"), [(0, 1), (1, 2), (2, 3)])
def test_openai_factory_per_call_retry_override_covers_single_wrapper(
    monkeypatch: pytest.MonkeyPatch, max_retries: int, attempts: int
) -> None:
    sdk = _FakeSDK([_HTTPFailure(500)] * attempts)
    monkeypatch.setattr("fbw_harness.llm.OpenAI", lambda **_kwargs: sdk)
    client = OpenAIClientFactory(max_retries=2).create(
        base_url="https://school.example/v1",
        model="model",
        api_key=_synthetic_api_key("per-call-retry"),
        max_retries=max_retries,
    )

    with pytest.raises(LLMDecisionError):
        client.decide([], [])

    assert len(sdk.chat.completions.calls) == attempts


def test_openai_factory_omitted_retry_uses_constructor_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdk = _FakeSDK([_HTTPFailure(500), _HTTPFailure(500)])
    monkeypatch.setattr("fbw_harness.llm.OpenAI", lambda **_kwargs: sdk)
    client = OpenAIClientFactory(max_retries=1).create(
        base_url="https://school.example/v1",
        model="model",
        api_key=_synthetic_api_key("factory-default-retry"),
    )

    with pytest.raises(LLMDecisionError):
        client.decide([], [])

    assert len(sdk.chat.completions.calls) == 2


@pytest.mark.parametrize("max_retries", [-1, 3, True, "1"])
def test_openai_factory_rejects_invalid_per_call_retry_override(
    max_retries: object,
) -> None:
    with pytest.raises(ValueError, match="max_retries"):
        OpenAIClientFactory().create(
            base_url="https://school.example/v1",
            model="model",
            api_key=_synthetic_api_key("invalid-retry"),
            max_retries=max_retries,  # type: ignore[arg-type]
        )


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
        FileSnapshot("src/z.py", "z = 1", _sha("f")),
        FileSnapshot("src/a.py", "a = 1", _sha("a")),
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
            FileSnapshot("z.py", "最后", _sha("f")),
            FileSnapshot("a.py", "最先", _sha("a")),
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
        FileSnapshot(
            f"src/{index}.py",
            f"FILE-{index}-" + "F" * 3_000,
            f"{index:064x}",
        )
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

    messages = ContextBuilder(2_100).build(
        request=_request(),
        observations=observations,
        feedback=_feedback(),
        memory=None,
        files=[],
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert "OLDEST-BODY" not in serialized
    assert "NEWEST-BODY" in serialized


def test_context_removes_oldest_file_after_its_body_before_touching_newer_file() -> None:
    files = [
        FileSnapshot("a.py", "OLDEST-FILE-" + "x" * 700, _sha("a")),
        FileSnapshot("b.py", "NEWEST-FILE-" + "y" * 700, _sha("b")),
    ]

    messages = ContextBuilder(2_100).build(
        request=_request(),
        observations=[],
        feedback=_feedback(),
        memory=None,
        files=files,
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert "OLDEST-FILE" not in serialized
    assert "NEWEST-FILE" in serialized


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
            files=[FileSnapshot(path, "text", _sha())],
        )


def test_context_redacts_secrets_urls_and_absolute_paths_from_declared_text() -> None:
    token = _synthetic_api_key("abcdefghijklmnopqrstuvwxyz123456")
    sensitive = (
        "PRIVATE_API_VALUE",
        token,
        "https://secret.example/v1",
        r"C:\Users\secret\project\app.py",
        "/home/secret/project/app.py",
    )
    output = (
        'api_key="PRIVATE_API_VALUE" '
        f"{token} "
        "https://secret.example/v1 "
        r"C:\Users\secret\project\app.py "
        "/home/secret/project/app.py"
    )

    messages = ContextBuilder(20_000).build(
        request=_request("fix safely"),
        observations=[Observation("test", False, output, output_tail=output)],
        feedback=_feedback(output),
        memory=ProjectMemory(project_notes=output),
        files=[FileSnapshot("app.py", output, _sha())],
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
        api_key=_synthetic_api_key("extra-memory-secret"),
        headers={"Authorization": "secret"},
    )
    file = SimpleNamespace(
        path="app.py",
        text="safe",
        sha256=_sha(),
        recovery_path=r"C:\private\recovery",
        base_url="https://private.example/v1",
    )

    messages = ContextBuilder(20_000).build(
        request=_request(), observations=[], feedback=None, memory=memory, files=[file]
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert _synthetic_api_key("extra-memory-secret") not in serialized
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
        files=[FileSnapshot("huge.py", huge_file, _sha())],
    )
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    assert _serialized_length(messages) <= 20_000
    assert "-FILE-END" not in serialized
    assert "-OBS-END" not in serialized


@pytest.mark.parametrize("boundary", ["task", "feedback"])
def test_context_rejects_huge_mandatory_text_before_encoding(boundary: str) -> None:
    huge = _NoFullEncodeText("x" * 20_000)
    request = _request(huge if boundary == "task" else "normal")
    feedback = _feedback(huge if boundary == "feedback" else "normal")

    with pytest.raises(ContextBudgetError, match=r"^context budget exceeded$"):
        ContextBuilder(200_000).build(
            request=request,
            observations=[],
            feedback=feedback,
            memory=None,
            files=[],
        )


def test_context_limits_optional_text_before_encoding_full_values() -> None:
    huge = _NoFullEncodeText("x" * 100_000)

    messages = ContextBuilder(50_000).build(
        request=_request(),
        observations=[Observation(huge, False, huge, output_tail=huge)],
        feedback=_feedback(),
        memory=ProjectMemory(
            project_notes=huge,
            last_success_summary=huge,
            updated_at=huge,
        ),
        files=[FileSnapshot("large.py", huge, _sha())],
    )
    sections = {section["section"]: section for section in _sections(messages)}

    assert len(sections["project_memory"]["memory"]["project_notes"]) <= 4_000
    assert len(sections["project_memory"]["memory"]["last_success_summary"]) <= 4_000
    assert len(sections["project_memory"]["memory"]["updated_at"]) <= 4_000
    assert len(sections["files"]["files"][0]["text"]) <= 8_000
    observation = sections["observations"]["observations"][0]
    assert len(observation["kind"]) <= 2_000
    assert len(observation["summary"]) <= 2_000
    assert len(observation["output_tail"]) <= 4_000


@pytest.mark.parametrize("collection", ["files", "observations", "failed_tests"])
def test_context_rejects_collection_item_101_with_fixed_input_error(collection: str) -> None:
    files: object = []
    observations: object = []
    feedback = _feedback()
    if collection == "files":
        files = [FileSnapshot(f"{index}.py", "x", _sha()) for index in range(101)]
    elif collection == "observations":
        observations = [Observation("test", False, str(index)) for index in range(101)]
    else:
        feedback = Feedback(
            kind=FeedbackKind.ASSERTION_FAILURE,
            passed=False,
            exit_code=1,
            summary="failed",
            failed_tests=tuple(f"tests/t.py::test_{index}" for index in range(101)),
            output_tail="failed",
            fingerprint="fp",
        )

    with pytest.raises(ContextInputError, match=r"^invalid context input$"):
        ContextBuilder(200_000).build(
            request=_request(),
            observations=observations,  # type: ignore[arg-type]
            feedback=feedback,
            memory=None,
            files=files,  # type: ignore[arg-type]
        )


def test_context_accepts_512_char_path_and_normalizes_uppercase_sha256() -> None:
    path = "a" * 509 + ".py"

    messages = ContextBuilder(20_000).build(
        request=_request(),
        observations=[],
        feedback=None,
        memory=None,
        files=[FileSnapshot(path, "text", _sha("A"))],
    )

    file_data = _sections(messages)[-1]["files"][0]
    assert file_data == {"path": path, "text": "text", "sha256": _sha("a")}


@pytest.mark.parametrize(
    ("path", "sha256"),
    [
        ("a" * 510 + ".py", _sha()),
        ("app.py", "a" * 63),
        ("app.py", "g" * 64),
    ],
)
def test_context_rejects_overlong_path_and_invalid_sha256(path: str, sha256: str) -> None:
    with pytest.raises(ContextInputError):
        ContextBuilder(20_000).build(
            request=_request(),
            observations=[],
            feedback=None,
            memory=None,
            files=[FileSnapshot(path, "text", sha256)],
        )


@pytest.mark.parametrize(
    "boundary",
    [
        "request",
        "memory",
        "file_item",
        "observation_item",
        "feedback",
        "files_sequence",
        "observations_sequence",
    ],
)
def test_context_maps_lazy_input_exceptions_to_fixed_unchained_error(boundary: str) -> None:
    secret = f"private-{boundary}-lazy-detail"

    class ExplodingObject:
        def __getattr__(self, _name: str) -> object:
            raise RuntimeError(secret)

    class ExplodingSequence:
        def __iter__(self) -> object:
            raise RuntimeError(secret)

    request: object = _request()
    memory: object = None
    files: object = []
    observations: object = []
    feedback: object = _feedback()
    if boundary == "request":
        request = ExplodingObject()
    elif boundary == "memory":
        memory = ExplodingObject()
    elif boundary == "file_item":
        files = [ExplodingObject()]
    elif boundary == "observation_item":
        observations = [ExplodingObject()]
    elif boundary == "feedback":
        feedback = ExplodingObject()
    elif boundary == "files_sequence":
        files = ExplodingSequence()
    else:
        observations = ExplodingSequence()

    with pytest.raises(ContextInputError, match=r"^invalid context input$") as caught:
        ContextBuilder(20_000).build(
            request=request,  # type: ignore[arg-type]
            observations=observations,  # type: ignore[arg-type]
            feedback=feedback,  # type: ignore[arg-type]
            memory=memory,  # type: ignore[arg-type]
            files=files,  # type: ignore[arg-type]
        )

    assert secret not in _exception_graph_text(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
