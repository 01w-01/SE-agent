from __future__ import annotations

import json
from typing import NoReturn

from .errors import ModelValidationError
from .models import Action, ActionKind, RawDecision

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


ACTION_TOOLS: tuple[dict[str, object], ...] = tuple(
    _tool_schema(kind, fields) for kind, fields in _FIELDS_BY_ACTION.items()
)


class ActionParseError(Exception):
    """The model decision does not match the fixed action protocol."""


class ActionParser:
    def parse(self, decision: RawDecision) -> Action:
        if not isinstance(decision, RawDecision) or len(decision.tool_calls) != 1:
            raise ActionParseError(_PARSE_ERROR)
        call = decision.tool_calls[0]
        if not isinstance(call.name, str) or not isinstance(call.arguments, str):
            raise ActionParseError(_PARSE_ERROR)
        try:
            call.arguments.encode("utf-8", errors="strict")
            arguments = json.loads(
                call.arguments,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (json.JSONDecodeError, TypeError, ValueError, UnicodeEncodeError):
            arguments = None
        if not isinstance(arguments, dict):
            raise ActionParseError(_PARSE_ERROR)

        try:
            kind = ActionKind(call.name)
        except (ValueError, TypeError):
            kind = None
        if kind is None:
            raise ActionParseError(_PARSE_ERROR)

        fields = _FIELDS_BY_ACTION[kind]
        if set(arguments) != set(fields) or any(
            not isinstance(arguments[field], str) for field in fields
        ):
            raise ActionParseError(_PARSE_ERROR)
        try:
            return Action(kind=kind, **arguments)
        except (ModelValidationError, TypeError, ValueError):
            invalid = True
        if invalid:
            raise ActionParseError(_PARSE_ERROR)
        raise AssertionError("unreachable")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite number")
