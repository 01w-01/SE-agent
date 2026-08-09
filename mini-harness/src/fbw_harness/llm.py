from __future__ import annotations

from openai import APIConnectionError, APITimeoutError, OpenAI

from .models import RawDecision, RawToolCall

_DECISION_ERROR = "LLM decision failed"


class LLMDecisionError(Exception):
    """An LLM attempt failed without exposing transport or response details."""


class OpenAICompatibleClient:
    __slots__ = ("_client", "_max_retries", "_model")

    def __init__(self, *, client: object, model: str, max_retries: int = 2) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-blank string")
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between zero and two")
        self._client = client
        self._model = model
        self._max_retries = max_retries

    def decide(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> RawDecision:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(  # type: ignore[attr-defined]
                    model=self._model,
                    messages=messages,
                    tools=tools,
                    tool_choice="required",
                )
            except Exception as error:  # noqa: BLE001 - SDK boundary is normalized safely.
                retry = _is_transient(error) and attempt < self._max_retries
                failed = True
            else:
                failed = False
            if failed:
                if retry:
                    continue
                raise LLMDecisionError(_DECISION_ERROR)

            try:
                return _to_raw_decision(response)
            except Exception:  # noqa: BLE001 - lazy SDK response fields are untrusted.
                malformed = True
            if malformed:
                raise LLMDecisionError(_DECISION_ERROR)
        raise AssertionError("unreachable")


class OpenAIClientFactory:
    __slots__ = ("_max_retries",)

    def __init__(self, *, max_retries: int = 2) -> None:
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between zero and two")
        self._max_retries = max_retries

    def create(self, *, base_url: str, model: str, api_key: str) -> OpenAICompatibleClient:
        try:
            client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        except Exception:  # noqa: BLE001 - factory must not leak a key-bearing SDK error.
            failed = True
        else:
            failed = False
        if failed:
            raise LLMDecisionError(_DECISION_ERROR)
        return OpenAICompatibleClient(
            client=client,
            model=model,
            max_retries=self._max_retries,
        )


class _MalformedResponse(Exception):
    pass


def _to_raw_decision(response: object) -> RawDecision:
    choices = response.choices  # type: ignore[attr-defined]
    if not isinstance(choices, (list, tuple)) or not choices:
        raise _MalformedResponse
    message = choices[0].message
    tool_calls = message.tool_calls
    if not isinstance(tool_calls, (list, tuple)):
        raise _MalformedResponse

    parsed: list[RawToolCall] = []
    for tool_call in tool_calls:
        function = tool_call.function
        name = function.name
        arguments = function.arguments
        if not isinstance(name, str) or not isinstance(arguments, str):
            raise _MalformedResponse
        parsed.append(RawToolCall(name=name, arguments=arguments))
    content = message.content if isinstance(message.content, str) else ""
    return RawDecision(tool_calls=tuple(parsed), content=content)


def _is_transient(error: Exception) -> bool:
    if isinstance(
        error,
        (TimeoutError, ConnectionError, APITimeoutError, APIConnectionError),
    ):
        return True
    status_code = getattr(error, "status_code", None)
    return type(status_code) is int and (status_code == 429 or 500 <= status_code <= 599)
