from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import ApprovalRequest, RawDecision, RunEvent


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...


@runtime_checkable
class ApprovalProvider(Protocol):
    def confirm(self, request: ApprovalRequest) -> bool: ...


@runtime_checkable
class CredentialStore(Protocol):
    def get(self) -> str | None: ...

    def set(self, value: str) -> None: ...

    def clear(self) -> bool: ...


@runtime_checkable
class LLMClient(Protocol):
    def decide(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> RawDecision: ...


@runtime_checkable
class LLMClientFactory(Protocol):
    def create(self, *, base_url: str, model: str, api_key: str) -> LLMClient: ...
