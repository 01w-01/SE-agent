from __future__ import annotations

import json
from typing import NoReturn

from .errors import ModelValidationError
from .llm import MAX_TOOL_ARGUMENT_CHARS, MAX_TOOL_CALLS, MAX_TOOL_NAME_CHARS
from .models import Action, ActionKind, RawDecision, RawToolCall

_PARSE_ERROR = "invalid action decision"
_FIELDS_BY_ACTION: dict[ActionKind, tuple[str, ...]] = {
    ActionKind.LIST_FILES: (),
    ActionKind.READ_FILE: ("path",),
    ActionKind.CREATE_FILE: ("path", "content"),
    ActionKind.EDIT_FILE: ("path", "expected_sha256", "old_text", "new_text"),
    ActionKind.FINISH: ("reason",),
}


def _tool_schema(kind: ActionKind, fields: tuple[str, ...]) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": kind.value,
            "description": f"Perform the fixed {kind.value} harness action.",
            "parameters": {
                "type": "object",
                "properties": {field: {"type": "string"} for field in fields},
                "required": list(fields),
                "additionalProperties": False,
            },
        },
    }


def build_action_tools() -> list[dict[str, object]]:
    """Return a fresh schema graph so one caller cannot poison later decisions."""

    return [_tool_schema(kind, fields) for kind, fields in _FIELDS_BY_ACTION.items()]


class ActionParseError(Exception):
    """The model decision does not match the fixed action protocol."""


class ActionParser:
    def parse(self, decision: RawDecision) -> Action:
        try:
            return _parse_action(decision)
        except Exception:  # noqa: BLE001 - the entire model decision object is untrusted.
            invalid = True
        if invalid:
            raise ActionParseError(_PARSE_ERROR) from None
        raise AssertionError("unreachable")


def _parse_action(decision: object) -> Action:
    if not isinstance(decision, RawDecision):
        raise TypeError("decision type")
    tool_calls = decision.tool_calls
    if len(tool_calls) > MAX_TOOL_CALLS or len(tool_calls) != 1:
        raise ValueError("tool call count")
    call = tool_calls[0]
    if not isinstance(call, RawToolCall):
        raise TypeError("tool call type")
    name = call.name
    raw_arguments = call.arguments
    if not isinstance(name, str) or not isinstance(raw_arguments, str):
        raise TypeError("tool call fields")
    if len(name) > MAX_TOOL_NAME_CHARS or len(raw_arguments) > MAX_TOOL_ARGUMENT_CHARS:
        raise ValueError("tool call field size")
    raw_arguments.encode("utf-8", errors="strict")
    arguments = json.loads(
        raw_arguments,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(arguments, dict):
        raise TypeError("arguments type")
    kind = ActionKind(name)
    fields = _FIELDS_BY_ACTION[kind]
    if set(arguments) != set(fields) or any(
        not isinstance(arguments[field], str) for field in fields
    ):
        raise ModelValidationError("action fields")
    return Action(kind=kind, **arguments)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite number")
