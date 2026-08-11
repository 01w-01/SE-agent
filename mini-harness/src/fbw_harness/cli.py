from __future__ import annotations

import argparse
import getpass
import json
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path

from .app import ApplicationService
from .credentials import KeyringCredentialStore
from .demos import run_demo
from .errors import HarnessError
from .llm import OpenAIClientFactory
from .memory import JsonProjectMemoryStore
from .models import ApprovalRequest, RunEvent, RunRequest, RunResult
from .ports import CredentialStore, EventSink


class ConsoleEventSink:
    """Render stable, human-readable state events without retaining run data."""

    def emit(self, event: RunEvent) -> None:
        round_count = event.payload.get("round_count", "-")
        category = _EVENT_CATEGORIES.get(event.stage, "状态")
        print(f"[轮次 {round_count}] {category}: {event.stage}")


_EVENT_CATEGORIES = {
    "requesting_action": "动作",
    "validating_action": "策略",
    "waiting_approval": "策略",
    "verifying": "测试",
    "completed": "停止",
    "failed": "停止",
    "rollback_incomplete": "停止",
}


class JsonlEventSink:
    """Optional RunEvent-only JSONL boundary that rejects unknown object types."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def emit(self, event: RunEvent) -> None:
        if not isinstance(event, RunEvent):
            raise TypeError("JSONL sink accepts RunEvent only")
        record = {
            "run_id": event.run_id,
            "kind": event.kind,
            "stage": event.stage,
            "payload": _json_value(event.payload),
        }
        with self._path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


class ConsoleApprovalProvider:
    def confirm(self, request: ApprovalRequest) -> bool:
        prompt = f"确认 {request.rule_id}: {request.reason} [y/N] "
        try:
            return input(prompt).strip().casefold() in {"y", "yes"}
        except (EOFError, KeyboardInterrupt):
            return False


def _json_value(value: object) -> object:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSONL mappings require string keys")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, frozenset)):
        return [_json_value(item) for item in value]
    raise TypeError(f"JSONL cannot serialize {type(value).__name__}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fbw-harness")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--workspace", required=True)
    run.add_argument("--task", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--config")
    run.add_argument("--jsonl")

    credential = commands.add_parser("credential")
    credential_commands = credential.add_subparsers(dest="credential_command", required=True)
    credential_commands.add_parser("set")
    credential_commands.add_parser("status")
    credential_commands.add_parser("clear")

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_clear = memory_commands.add_parser("clear")
    memory_clear.add_argument("--workspace", required=True)

    demo = commands.add_parser("demo")
    demo.add_argument("name", choices=("guardrail", "feedback", "no-progress", "all"))
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    app: ApplicationService | None = None,
    credential_store: CredentialStore | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    store = credential_store or KeyringCredentialStore()
    try:
        if args.command == "run":
            return _run(args, app=app, credential_store=store)
        if args.command == "credential":
            return _credential(args, store)
        if args.command == "memory":
            return _memory_clear(Path(args.workspace))
        if args.command == "demo":
            return _demo(args.name)
    except (HarnessError, OSError, ValueError, TypeError) as error:
        print(f"error: {type(error).__name__}")
        return 1
    raise AssertionError("unhandled command")


def _run(
    args: argparse.Namespace, *, app: ApplicationService | None, credential_store: CredentialStore
) -> int:
    request = RunRequest(
        workspace=Path(args.workspace),
        task=args.task,
        base_url=args.base_url,
        model=args.model,
        config_path=Path(args.config) if args.config else None,
        config_overrides={"jsonl_log": args.jsonl} if args.jsonl else {},
    )
    service = app or ApplicationService(
        credential_store=credential_store,
        llm_factory=OpenAIClientFactory(),
        event_sink=_event_sink(args.jsonl),
        approval_provider=ConsoleApprovalProvider(),
    )
    result = service.run(request)
    _print_result(result)
    return result.exit_code


def _event_sink(jsonl_path: str | None) -> EventSink:
    if jsonl_path:
        return JsonlEventSink(Path(jsonl_path))
    return ConsoleEventSink()


def _print_result(result: RunResult) -> None:
    print(
        f"{result.status.name}: reason={result.stop_reason}; rounds={result.round_count}; "
        f"files={len(result.touched_files)}; rollback_complete={result.rollback_complete}"
    )


def _credential(args: argparse.Namespace, store: CredentialStore) -> int:
    if args.credential_command == "set":
        value = getpass.getpass("API key: ")
        store.set(value)
        print("credential configured")
        return 0
    if args.credential_command == "status":
        status_method = getattr(store, "status", None)
        if not callable(status_method):
            print(f"configured={store.get() is not None}")
            return 0
        status = status_method()
        print(f"configured={status.configured}; service={status.service}; account={status.account}")
        return 0
    if args.credential_command == "clear":
        cleared = store.clear()
        print("credential cleared" if cleared else "credential was not configured")
        return 0
    raise AssertionError("unhandled credential command")


def _memory_clear(workspace: Path) -> int:
    JsonProjectMemoryStore(workspace / ".fbw-memory.json", enabled=True).clear()
    print("memory cleared")
    return 0


def _demo(name: str) -> int:
    names = ("guardrail", "feedback", "no-progress") if name == "all" else (name,)
    for item in names:
        result = run_demo(item)
        print(f"demo {item}: {'PASS' if result.exit_code == 0 else 'FAIL'}")
        if result.exit_code != 0:
            return result.exit_code
    return 0
