from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass

from .models import RawDecision


class MockLLMExhaustedError(Exception):
    """The deterministic decision script has no remaining item."""


@dataclass(frozen=True, slots=True)
class MockLLMCall:
    messages: list[dict[str, object]]
    tools: list[dict[str, object]]


class ScriptedMockLLM:
    def __init__(self, decisions: Iterable[RawDecision]) -> None:
        self._decisions = tuple(decisions)
        self._next = 0
        self._calls: list[MockLLMCall] = []

    @property
    def calls(self) -> tuple[MockLLMCall, ...]:
        return tuple(deepcopy(self._calls))

    def decide(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> RawDecision:
        self._calls.append(MockLLMCall(deepcopy(messages), deepcopy(tools)))
        if self._next >= len(self._decisions):
            raise MockLLMExhaustedError("mock LLM script exhausted")
        decision = self._decisions[self._next]
        self._next += 1
        return decision
