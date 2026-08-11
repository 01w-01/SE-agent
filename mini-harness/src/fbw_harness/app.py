from __future__ import annotations

import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from .config import load_config
from .context import ContextBuilder
from .errors import InputError
from .feedback import FeedbackEngine
from .loop import AgentLoop, ToolDispatcher
from .memory import JsonProjectMemoryStore
from .models import RunRequest, RunResult, RunStatus
from .parser import ActionParser
from .policy import PolicyEngine
from .ports import ApprovalProvider, CredentialStore, EventSink, LLMClientFactory
from .testing import TestRunner
from .transactions import FileTransaction
from .workspace import Workspace

_CONTEXT_MAX_CHARS = 12_000


class ApplicationService:
    """Validate inputs and compose one isolated AgentLoop run."""

    def __init__(
        self,
        *,
        credential_store: CredentialStore,
        llm_factory: LLMClientFactory,
        event_sink: EventSink,
        approval_provider: ApprovalProvider,
        user_config: Path | None = None,
        recovery_root_factory: Callable[[str], Path] | None = None,
    ) -> None:
        self._credential_store = credential_store
        self._llm_factory = llm_factory
        self._event_sink = event_sink
        self._approval_provider = approval_provider
        self._user_config = Path(user_config) if user_config is not None else None
        self._recovery_root_factory = recovery_root_factory or _default_recovery_root

    def run(self, request: RunRequest) -> RunResult:
        if not isinstance(request, RunRequest):
            raise InputError("run request is invalid")

        run_id = uuid.uuid4().hex
        config = load_config(request, user_config=self._user_config)
        api_key = self._credential_store.get()
        if not isinstance(api_key, str) or not api_key or not api_key.isascii():
            raise InputError("API credential is not configured")
        known_secrets = (api_key,)

        llm = self._llm_factory.create(
            base_url=request.base_url,
            model=request.model,
            api_key=api_key,
        )
        workspace = Workspace(request.workspace, config.file_size_limit_bytes)
        recovery_root = Path(self._recovery_root_factory(run_id))
        transaction = FileTransaction(workspace, recovery_root)
        memory_store = JsonProjectMemoryStore(
            config.memory_path,
            enabled=config.memory_enabled,
        )
        try:
            memory = memory_store.load()
        except Exception:  # noqa: BLE001 - optional memory must never block a run.
            memory = None

        loop = AgentLoop(
            llm=llm,
            parser=ActionParser(),
            context_builder=ContextBuilder(max_chars=_CONTEXT_MAX_CHARS),
            policy=PolicyEngine(workspace, config.normal_change_line_limit),
            dispatcher=ToolDispatcher(workspace, transaction),
            test_runner=TestRunner(config, known_secrets=known_secrets),
            feedback_engine=FeedbackEngine(
                config.output_tail_chars,
                known_secrets=known_secrets,
            ),
            event_sink=self._event_sink,
            approval_provider=self._approval_provider,
            config=config,
            recovery_path=recovery_root,
            memory=memory,
            run_id=run_id,
        )
        result = loop.run(request)
        if result.status is RunStatus.COMPLETED:
            summary = (
                f"status=completed; rounds={result.round_count}; files={len(result.touched_files)}"
            )
            try:
                memory_store.save_success(summary)
            except Exception:  # noqa: BLE001 - optional memory must not alter success.
                return result
        return result


def _default_recovery_root(run_id: str) -> Path:
    return Path(tempfile.gettempdir()) / "fbw-harness" / run_id
