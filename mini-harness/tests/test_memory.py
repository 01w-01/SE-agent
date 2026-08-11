from __future__ import annotations

import json
from pathlib import Path

from fbw_harness.memory import JsonProjectMemoryStore


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


def test_memory_round_trip_writes_whitelisted_fields(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = JsonProjectMemoryStore(path, enabled=True)

    store.save_success("passed")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"version", "project_notes", "last_success_summary", "updated_at"}
    assert payload["version"] == 1
    assert payload["project_notes"] == ""
    assert payload["last_success_summary"] == "passed"
    assert payload["updated_at"].endswith("Z")
    assert store.load().last_success_summary == "passed"


def test_success_preserves_existing_project_notes(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "project_notes": "keep this note",
                "last_success_summary": "old",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    JsonProjectMemoryStore(path, enabled=True).save_success("new")

    memory = JsonProjectMemoryStore(path, enabled=True).load()
    assert memory is not None
    assert memory.project_notes == "keep this note"
    assert memory.last_success_summary == "new"


def test_invalid_success_summary_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = JsonProjectMemoryStore(path, enabled=True)

    store.save_success("x" * 2_001)
    assert not path.exists()
    store.save_success("api_key=do-not-save")
    assert not path.exists()


def test_invalid_utf8_memory_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_bytes(b"{\xff")

    assert JsonProjectMemoryStore(path, enabled=True).load() is None
    assert not path.exists()
    assert list(tmp_path.glob("memory.json.corrupt-*"))


def test_clear_is_idempotent_and_only_removes_memory_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    store = JsonProjectMemoryStore(path, enabled=True)
    store.save_success("passed")

    store.clear()
    store.clear()

    assert not path.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_memory_does_not_operate_in_a_protected_tree(tmp_path: Path) -> None:
    path = tmp_path / ".git" / "memory.json"

    JsonProjectMemoryStore(path, enabled=True).save_success("passed")

    assert not path.exists()


def test_memory_does_not_follow_a_symlinked_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    JsonProjectMemoryStore(link / "memory.json", enabled=True).save_success("passed")

    assert not (target / "memory.json").exists()
