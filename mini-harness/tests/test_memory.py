from __future__ import annotations

import json
import os
import re
import subprocess
import warnings
from pathlib import Path

import pytest

import fbw_harness.memory as memory_module
from fbw_harness.memory import JsonProjectMemoryStore


def test_disabled_memory_never_reads_or_writes(tmp_path: Path) -> None:
    store = JsonProjectMemoryStore(tmp_path / "memory.json", enabled=False)

    assert store.load() is None
    store.save_success("passed")

    assert not (tmp_path / "memory.json").exists()


def test_memory_rejects_secret_and_full_file_fields(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text('{"version":1,"api_key":"value"}', encoding="utf-8")

    with pytest.warns(
        RuntimeWarning, match=re.escape("Project memory was ignored because its file was invalid.")
    ):
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


@pytest.mark.parametrize(
    "secret_text",
    [
        '{"api_key":"synthetic-value"}',
        '{"file_content": "synthetic-value"}',
        'api.key = "synthetic-value"',
        "file-content='synthetic-value'",
    ],
)
def test_secret_shaped_summary_is_not_persisted(tmp_path: Path, secret_text: str) -> None:
    path = tmp_path / "memory.json"

    JsonProjectMemoryStore(path, enabled=True).save_success(secret_text)

    assert not path.exists()


@pytest.mark.parametrize(
    "secret_text",
    [
        '{"api_key":"synthetic-value"}',
        '{"file_content": "synthetic-value"}',
        'api.key = "synthetic-value"',
        "file-content='synthetic-value'",
    ],
)
def test_secret_shaped_project_notes_are_quarantined(tmp_path: Path, secret_text: str) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "project_notes": secret_text,
                "last_success_summary": "passed",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning):
        assert JsonProjectMemoryStore(path, enabled=True).load() is None
    assert list(tmp_path.glob("memory.json.corrupt-*"))


def test_oversized_memory_is_quarantined_before_success_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_bytes(b"x" * 131_073)
    store = JsonProjectMemoryStore(path, enabled=True)

    with pytest.warns(RuntimeWarning):
        assert store.load() is None
    assert not path.exists()
    assert list(tmp_path.glob("memory.json.corrupt-*"))

    store.save_success("passed")
    assert store.load() is not None
    assert store.load().last_success_summary == "passed"


def test_failed_quarantine_never_allows_success_to_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "memory.json"
    original = b"x" * 131_073
    path.write_bytes(original)
    monkeypatch.setattr(memory_module, "_isolate_corrupt", lambda _: False)

    with pytest.warns(RuntimeWarning):
        JsonProjectMemoryStore(path, enabled=True).save_success("passed")

    assert path.read_bytes() == original


@pytest.mark.parametrize("failure", [OSError("read failed"), ValueError("changed while reading")])
def test_read_failure_never_allows_success_to_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    path = tmp_path / "memory.json"
    original = json.dumps(
        {
            "version": 1,
            "project_notes": "keep",
            "last_success_summary": "old",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    ).encode("utf-8")
    path.write_bytes(original)

    def fail_read(_: Path) -> bytes:
        raise failure

    monkeypatch.setattr(memory_module, "_read_bytes", fail_read)
    JsonProjectMemoryStore(path, enabled=True).save_success("passed")

    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["load", "save_success", "clear"])
def test_public_memory_operations_reject_nul_paths_safely(tmp_path: Path, operation: str) -> None:
    path = Path(f"{tmp_path / 'memory.json'}\x00")
    store = JsonProjectMemoryStore(path, enabled=True)

    if operation == "load":
        assert store.load() is None
    elif operation == "save_success":
        store.save_success("passed")
    else:
        store.clear()


def test_invalid_utf8_memory_is_isolated(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_bytes(b"{\xff")

    with pytest.warns(
        RuntimeWarning, match=re.escape("Project memory was ignored because its file was invalid.")
    ):
        assert JsonProjectMemoryStore(path, enabled=True).load() is None
    assert not path.exists()
    assert list(tmp_path.glob("memory.json.corrupt-*"))


def test_corrupt_memory_warning_is_fixed_and_contains_no_path(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text('{"version":1,"unexpected":"secret-value"}', encoding="utf-8")

    with pytest.warns(RuntimeWarning) as captured:
        assert JsonProjectMemoryStore(path, enabled=True).load() is None

    assert len(captured) == 1
    assert str(captured[0].message) == "Project memory was ignored because its file was invalid."
    assert str(path) not in str(captured[0].message)
    assert "secret-value" not in str(captured[0].message)


def test_corrupt_memory_survives_runtime_warning_error_filter(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text('{"version":1,"unexpected":"secret-value"}', encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        assert JsonProjectMemoryStore(path, enabled=True).load() is None

    assert not path.exists()
    assert list(tmp_path.glob("memory.json.corrupt-*"))


@pytest.mark.parametrize(
    "updated_at",
    ["2026-01-01", "2026-01-01T00:00:00", "2026-01-01T00:00:00+00:00", "2026-02-30T00:00:00Z"],
)
def test_memory_rejects_non_utc_z_timestamps(tmp_path: Path, updated_at: str) -> None:
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "project_notes": "",
                "last_success_summary": "passed",
                "updated_at": updated_at,
            }
        ),
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning):
        assert JsonProjectMemoryStore(path, enabled=True).load() is None
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
        pytest.skip("symbolic links are unavailable on this platform")

    JsonProjectMemoryStore(link / "memory.json", enabled=True).save_success("passed")

    assert not (target / "memory.json").exists()


def test_memory_rejects_a_symlinked_target(tmp_path: Path) -> None:
    target = tmp_path / "actual.json"
    target.write_text("do not replace", encoding="utf-8")
    link = tmp_path / "memory.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable on this platform")

    store = JsonProjectMemoryStore(link, enabled=True)
    assert store.load() is None
    store.save_success("passed")
    store.clear()

    assert target.read_text(encoding="utf-8") == "do not replace"
    assert link.is_symlink()


def test_memory_rejects_a_windows_junction_parent(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows junctions are unavailable on this platform")
    target = tmp_path / "actual"
    target.mkdir()
    junction = tmp_path / "junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Windows junction creation is unavailable")

    store = JsonProjectMemoryStore(junction / "memory.json", enabled=True)
    assert store.load() is None
    store.save_success("passed")

    assert not (target / "memory.json").exists()
