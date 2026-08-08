from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from fbw_harness import transactions as transactions_module
from fbw_harness.transactions import (
    EditConflictError,
    FileTransaction,
    RollbackError,
    TransactionError,
)
from fbw_harness.workspace import PolicyDeniedError, Workspace


def make_transaction(tmp_path: Path) -> tuple[Workspace, FileTransaction, Path]:
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"value = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    return workspace, FileTransaction(workspace, recovery_root), recovery_root


def transaction_directory(recovery_root: Path) -> Path:
    directories = tuple(recovery_root.iterdir())
    assert len(directories) == 1
    assert directories[0].is_dir()
    return directories[0]


def assert_no_exception_chain(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(("old_text", "occurrences"), [("missing", 0), ("value", 2)])
def test_edit_requires_old_text_to_occur_exactly_once(
    tmp_path: Path, old_text: str, occurrences: int
) -> None:
    """Catches edits accepting absent or ambiguous old text."""
    workspace, transaction, _ = make_transaction(tmp_path)
    if occurrences == 2:
        (workspace.root / "a.py").write_bytes(b"value = 1\nvalue = 2\n")
    current = workspace.read_file("a.py")

    with pytest.raises(EditConflictError, match="exactly once"):
        transaction.edit_file("a.py", current.sha256, old_text, "result")

    assert workspace.read_file("a.py") == current
    assert transaction.touched_paths == ()


def test_edit_rejects_a_stale_hash_without_changing_the_file(tmp_path: Path) -> None:
    """Catches an edit overwriting content that changed after the caller read it."""
    workspace, transaction, _ = make_transaction(tmp_path)
    stale = workspace.read_file("a.py")
    (workspace.root / "a.py").write_bytes(b"value = external\n")

    with pytest.raises(EditConflictError, match="hash"):
        transaction.edit_file("a.py", stale.sha256, "value", "result")

    assert workspace.read_file("a.py").text == "value = external\n"
    assert transaction.touched_paths == ()


def test_edit_rejects_a_missing_target_without_recording_a_touch(tmp_path: Path) -> None:
    """Catches a missing edit target being treated as a file creation."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)

    with pytest.raises(EditConflictError, match="does not exist"):
        transaction.edit_file("missing.py", "0" * 64, "old", "new")

    assert not (workspace.root / "missing.py").exists()
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())


def test_repeated_edits_keep_the_first_snapshot_and_rollback_to_original_bytes(
    tmp_path: Path,
) -> None:
    """Catches a later edit overwriting the first recovery snapshot."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")

    first = transaction.edit_file("a.py", original.sha256, "1", "2")
    second = transaction.edit_file("a.py", first.sha256, "2", "3")

    assert first.text == "value = 2\n"
    assert second.text == "value = 3\n"
    assert transaction.touched_paths == ("a.py",)
    materials = tuple(transaction_directory(recovery_root).iterdir())
    assert len(materials) == 1
    assert materials[0].read_bytes() == b"value = 1\n"

    report = transaction.rollback()

    assert report.complete is True
    assert report.failed_paths == ()
    assert report.recovery_root is None
    assert workspace.read_file("a.py") == original
    assert not any(recovery_root.iterdir())


def test_create_returns_snapshot_and_rollback_removes_the_created_file(tmp_path: Path) -> None:
    """Catches create rollback leaving transaction-owned files behind."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)

    created = transaction.create_file("new.py", "created = True\n")

    assert created.path == "new.py"
    assert created.text == "created = True\n"
    assert transaction.touched_paths == ("new.py",)
    assert (workspace.root / "new.py").read_bytes() == b"created = True\n"
    assert len(tuple(transaction_directory(recovery_root).iterdir())) == 1

    report = transaction.rollback()

    assert report.complete is True
    assert not (workspace.root / "new.py").exists()
    assert not any(recovery_root.iterdir())


def test_editing_a_file_created_by_the_transaction_keeps_the_create_record(
    tmp_path: Path,
) -> None:
    """Catches an edit turning a transaction-created file into an original file."""
    workspace, transaction, _ = make_transaction(tmp_path)
    created = transaction.create_file("new.py", "stage = 1\n")

    edited = transaction.edit_file("new.py", created.sha256, "1", "2")

    assert edited.text == "stage = 2\n"
    assert transaction.touched_paths == ("new.py",)
    assert transaction.rollback().complete is True
    assert not (workspace.root / "new.py").exists()


def test_create_rejects_an_existing_target_without_recording_a_touch(tmp_path: Path) -> None:
    """Catches create silently replacing an existing workspace file."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")

    with pytest.raises(TransactionError, match="already exists"):
        transaction.create_file("a.py", "replacement\n")

    assert workspace.read_file("a.py") == original
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())


def test_touched_paths_preserves_first_touch_order_as_an_immutable_tuple(tmp_path: Path) -> None:
    """Catches repeat touches reordering or duplicating the public result paths."""
    workspace, transaction, _ = make_transaction(tmp_path)
    original = workspace.read_file("a.py")

    transaction.create_file("z.py", "z = 1\n")
    edited = transaction.edit_file("a.py", original.sha256, "1", "2")
    transaction.edit_file("a.py", edited.sha256, "2", "3")

    assert transaction.touched_paths == ("z.py", "a.py")
    assert isinstance(transaction.touched_paths, tuple)


def test_original_snapshot_is_flushed_and_fsynced_before_editing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an edit replacing its target before the recovery bytes are durable."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")

    def fail_recovery_fsync(file_descriptor: int) -> None:
        assert os.fstat(file_descriptor).st_size == len(b"value = 1\n")
        raise OSError(r"sensitive C:\private\snapshot.txt")

    monkeypatch.setattr(transactions_module.os, "fsync", fail_recovery_fsync)

    with pytest.raises(TransactionError, match="recovery material") as caught:
        transaction.edit_file("a.py", original.sha256, "1", "2")

    assert workspace.read_file("a.py") == original
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())
    assert "sensitive" not in str(caught.value)
    assert_no_exception_chain(caught.value)


def test_supported_recovery_directory_fsync_failure_prevents_target_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches supported directory fsync failures being ignored after material creation."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    per_transaction_root = transaction_directory(recovery_root)
    real_open = os.open
    real_fsync = os.fsync
    real_close = os.close
    directory_fd = 987_654

    def open_directory_or_real(
        path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object
    ) -> int:
        if Path(path) == per_transaction_root:
            return directory_fd
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    def fail_directory_fsync(file_descriptor: int) -> None:
        if file_descriptor == directory_fd:
            raise OSError(r"sensitive C:\external\recovery-directory")
        real_fsync(file_descriptor)

    def close_directory_or_real(file_descriptor: int) -> None:
        if file_descriptor != directory_fd:
            real_close(file_descriptor)

    monkeypatch.setattr(transactions_module, "_DIRECTORY_FSYNC_SUPPORTED", True, raising=False)
    monkeypatch.setattr(transactions_module.os, "open", open_directory_or_real)
    monkeypatch.setattr(transactions_module.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(transactions_module.os, "close", close_directory_or_real)

    with pytest.raises(TransactionError, match="directory could not be synchronized") as caught:
        transaction.edit_file("a.py", original.sha256, "1", "2")

    assert workspace.read_file("a.py") == original
    assert transaction.touched_paths == ()
    assert not any(per_transaction_root.iterdir())
    assert "sensitive" not in str(caught.value)
    assert_no_exception_chain(caught.value)


def test_unsupported_windows_recovery_directory_fsync_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the Windows no-op branch attempting an unsupported directory open."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    per_transaction_root = transaction_directory(recovery_root)
    real_open = os.open

    def reject_directory_open(
        path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object
    ) -> int:
        if Path(path) == per_transaction_root:
            raise AssertionError("Windows directory fsync must be skipped")
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(transactions_module, "_DIRECTORY_FSYNC_SUPPORTED", False, raising=False)
    monkeypatch.setattr(transactions_module.os, "open", reject_directory_open)

    edited = transaction.edit_file("a.py", original.sha256, "1", "2")

    assert edited.text == "value = 2\n"
    assert workspace.read_file("a.py") == edited
    assert len(tuple(per_transaction_root.iterdir())) == 1


def test_target_temp_is_flushed_and_fsynced_before_create_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches create replacing its target before the complete temp payload is durable."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    real_fsync = os.fsync
    fsync_count = 0

    def fail_target_fsync(file_descriptor: int) -> None:
        nonlocal fsync_count
        fsync_count += 1
        if fsync_count == 1:
            real_fsync(file_descriptor)
            return
        assert os.fstat(file_descriptor).st_size == len(b"created = True\n")
        raise OSError("target temp fsync failed")

    monkeypatch.setattr(transactions_module, "_DIRECTORY_FSYNC_SUPPORTED", False)
    monkeypatch.setattr(transactions_module.os, "fsync", fail_target_fsync)

    with pytest.raises(TransactionError, match="temporary file"):
        transaction.create_file("new.py", "created = True\n")

    assert not (workspace.root / "new.py").exists()
    assert transaction.touched_paths == ()
    assert tuple(workspace.root.iterdir()) == (workspace.root / "a.py",)
    assert not any(transaction_directory(recovery_root).iterdir())


def test_replace_failure_preserves_target_cleans_temp_and_redacts_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches failed atomic replacement damaging the target or leaking raw OS details."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    replacement_source: Path | None = None

    def fail_replace(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> None:
        nonlocal replacement_source
        replacement_source = Path(source)
        assert replacement_source.parent == workspace.root
        assert Path(destination) == workspace.root / "a.py"
        raise OSError(r"sensitive C:\external\payload.py")

    monkeypatch.setattr(transactions_module.os, "replace", fail_replace)

    with pytest.raises(TransactionError, match="replace") as caught:
        transaction.edit_file("a.py", original.sha256, "1", "2")

    assert workspace.read_file("a.py") == original
    assert replacement_source is not None
    assert not replacement_source.exists()
    assert tuple(workspace.root.iterdir()) == (workspace.root / "a.py",)
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())
    assert "sensitive" not in str(caught.value)
    assert_no_exception_chain(caught.value)


def test_edit_rechecks_hash_after_temp_fsync_and_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a concurrent edit landing during temp preparation being overwritten."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    real_fsync = os.fsync
    fsync_count = 0

    def change_target_after_temp_fsync(file_descriptor: int) -> None:
        nonlocal fsync_count
        fsync_count += 1
        real_fsync(file_descriptor)
        if fsync_count == 2:
            (workspace.root / "a.py").write_bytes(b"value = external\n")

    monkeypatch.setattr(transactions_module, "_DIRECTORY_FSYNC_SUPPORTED", False)
    monkeypatch.setattr(transactions_module.os, "fsync", change_target_after_temp_fsync)

    with pytest.raises(EditConflictError, match="hash"):
        transaction.edit_file("a.py", original.sha256, "1", "2")

    assert workspace.read_file("a.py").text == "value = external\n"
    assert tuple(workspace.root.iterdir()) == (workspace.root / "a.py",)
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())
    assert transaction.rollback().complete is True
    assert workspace.read_file("a.py").text == "value = external\n"


def test_failed_later_edit_keeps_the_original_snapshot_for_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a failed repeat edit discarding recovery for an earlier successful edit."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    first = transaction.edit_file("a.py", original.sha256, "1", "2")

    def fail_replace(source: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> None:
        del source, destination
        raise OSError("repeat replace failed")

    monkeypatch.setattr(transactions_module.os, "replace", fail_replace)

    with pytest.raises(TransactionError, match="replace"):
        transaction.edit_file("a.py", first.sha256, "2", "3")

    assert workspace.read_file("a.py") == first
    assert transaction.touched_paths == ("a.py",)
    material = next(iter(transaction_directory(recovery_root).iterdir()))
    assert material.read_bytes() == b"value = 1\n"


@pytest.mark.parametrize(
    ("operation", "invalid_text"), [("create", "bad\ud800"), ("edit", "bad\x00")]
)
def test_writes_reject_non_workspace_utf8_text_before_touching_files(
    tmp_path: Path, operation: str, invalid_text: str
) -> None:
    """Catches invalid transaction text reaching the workspace or recovery state."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")

    with pytest.raises(TransactionError, match="UTF-8") as caught:
        if operation == "create":
            transaction.create_file("new.py", invalid_text)
        else:
            transaction.edit_file("a.py", original.sha256, "1", invalid_text)

    assert workspace.read_file("a.py") == original
    assert not (workspace.root / "new.py").exists()
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())
    assert_no_exception_chain(caught.value)


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_writes_enforce_the_workspace_byte_size_limit_before_touching_files(
    tmp_path: Path, operation: str
) -> None:
    """Catches transaction writes bypassing the workspace's configured byte limit."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"x = 1\n")
    workspace = Workspace(workspace_root, file_size_limit_bytes=8)
    recovery_root = tmp_path / "recovery"
    transaction = FileTransaction(workspace, recovery_root)
    original = workspace.read_file("a.py")

    with pytest.raises(TransactionError, match="size limit"):
        if operation == "create":
            transaction.create_file("new.py", "123456789")
        else:
            transaction.edit_file("a.py", original.sha256, "1", "123456789")

    assert workspace.read_file("a.py") == original
    assert not (workspace.root / "new.py").exists()
    assert transaction.touched_paths == ()
    assert not any(transaction_directory(recovery_root).iterdir())


def test_commit_removes_only_its_unique_transaction_directory_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """Catches commit deleting sibling recovery material or failing when repeated."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"value = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"

    first = FileTransaction(workspace, recovery_root)
    first_directory = transaction_directory(recovery_root)
    second = FileTransaction(workspace, recovery_root)
    transaction_directories = set(recovery_root.iterdir())
    second_directory = (transaction_directories - {first_directory}).pop()
    original = workspace.read_file("a.py")
    first.edit_file("a.py", original.sha256, "1", "2")

    first.commit()
    first.commit()

    assert workspace.read_file("a.py").text == "value = 2\n"
    assert not first_directory.exists()
    assert second_directory.is_dir()
    assert set(recovery_root.iterdir()) == {second_directory}

    second.commit()
    assert not any(recovery_root.iterdir())


@pytest.mark.parametrize(
    ("terminal", "operation"),
    [("commit", "create"), ("commit", "edit"), ("rollback", "create"), ("rollback", "edit")],
)
def test_completed_transaction_rejects_future_writes_without_changing_files(
    tmp_path: Path, terminal: str, operation: str
) -> None:
    """Catches writes after commit or complete rollback escaping recovery coverage."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    edited = transaction.edit_file("a.py", original.sha256, "1", "2")
    if terminal == "commit":
        transaction.commit()
    else:
        assert transaction.rollback().complete is True
    before_attempt = workspace.read_file("a.py")

    with pytest.raises(TransactionError, match="already complete"):
        if operation == "create":
            transaction.create_file("late.py", "late = True\n")
        else:
            transaction.edit_file("a.py", before_attempt.sha256, "value", "late")

    assert workspace.read_file("a.py") == before_attempt
    assert not (workspace.root / "late.py").exists()
    assert not any(recovery_root.iterdir())
    if terminal == "commit":
        assert before_attempt == edited
    else:
        assert before_attempt == original


def test_rollback_is_reverse_ordered_and_retains_failed_second_restore_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches rollback stopping early, reporting absolute paths, or deleting failed material."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"a = 1\n")
    (workspace_root / "b.py").write_bytes(b"b = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    transaction = FileTransaction(workspace, recovery_root)
    original_a = workspace.read_file("a.py")
    original_b = workspace.read_file("b.py")
    transaction.edit_file("a.py", original_a.sha256, "1", "2")
    transaction.edit_file("b.py", original_b.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    real_replace = os.replace
    restore_count = 0

    def fail_second_restore(
        source: os.PathLike[str] | str, destination: os.PathLike[str] | str
    ) -> None:
        nonlocal restore_count
        restore_count += 1
        if restore_count == 2:
            raise OSError(r"sensitive C:\external\restore.py")
        real_replace(source, destination)

    with monkeypatch.context() as replace_patch:
        replace_patch.setattr(transactions_module.os, "replace", fail_second_restore)
        report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert report.recovery_root.is_dir()
    assert workspace.read_file("b.py") == original_b
    assert workspace.read_file("a.py").text == "a = 2\n"
    assert any(path.read_bytes() == b"a = 1\n" for path in per_transaction_root.iterdir())
    assert all(not path.name.startswith(".fbw-transaction-") for path in workspace.root.iterdir())

    retry = transaction.rollback()

    assert retry.complete is True
    assert retry.failed_paths == ()
    assert retry.recovery_root is None
    assert workspace.read_file("a.py") == original_a
    assert workspace.read_file("b.py") == original_b
    assert not per_transaction_root.exists()
    assert transaction.rollback() == retry


@pytest.mark.parametrize("operation", ["create", "edit_recovered", "edit_failed", "commit"])
def test_incomplete_rollback_allows_only_rollback_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Catches writes or commit corrupting state between partial rollback and retry."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"a = 1\n")
    (workspace_root / "b.py").write_bytes(b"b = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    transaction = FileTransaction(workspace, recovery_root)
    original_a = workspace.read_file("a.py")
    original_b = workspace.read_file("b.py")
    transaction.edit_file("a.py", original_a.sha256, "1", "2")
    transaction.edit_file("b.py", original_b.sha256, "1", "2")
    real_replace = os.replace
    restore_count = 0

    def fail_second_restore(
        source: os.PathLike[str] | str, destination: os.PathLike[str] | str
    ) -> None:
        nonlocal restore_count
        restore_count += 1
        if restore_count == 2:
            raise OSError("second restore failed")
        real_replace(source, destination)

    with monkeypatch.context() as replace_patch:
        replace_patch.setattr(transactions_module.os, "replace", fail_second_restore)
        report = transaction.rollback()

    assert report.complete is False
    before_a = workspace.read_file("a.py")
    before_b = workspace.read_file("b.py")
    with pytest.raises(TransactionError, match="rollback is already in progress"):
        if operation == "create":
            transaction.create_file("late.py", "late = True\n")
        elif operation == "edit_recovered":
            transaction.edit_file("b.py", before_b.sha256, "1", "9")
        elif operation == "edit_failed":
            transaction.edit_file("a.py", before_a.sha256, "2", "9")
        else:
            transaction.commit()

    assert workspace.read_file("a.py") == before_a
    assert workspace.read_file("b.py") == before_b
    assert not (workspace.root / "late.py").exists()
    assert report.recovery_root is not None
    assert any(path.read_bytes() == b"a = 1\n" for path in report.recovery_root.iterdir())

    assert transaction.rollback().complete is True
    assert workspace.read_file("a.py") == original_a
    assert workspace.read_file("b.py") == original_b


def test_rollback_accumulates_path_resolution_failure_and_continues_restoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches one unsafe recovery path aborting restoration of all remaining files."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"a = 1\n")
    (workspace_root / "b.py").write_bytes(b"b = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    transaction = FileTransaction(workspace, recovery_root)
    original_a = workspace.read_file("a.py")
    original_b = workspace.read_file("b.py")
    transaction.edit_file("a.py", original_a.sha256, "1", "2")
    transaction.edit_file("b.py", original_b.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    real_resolve_safe = workspace.resolve_safe

    def deny_b(relative: str, *, must_exist: bool) -> Path:
        if relative == "b.py":
            raise PolicyDeniedError("workspace path cannot be resolved safely")
        return real_resolve_safe(relative, must_exist=must_exist)

    with monkeypatch.context() as resolution_patch:
        resolution_patch.setattr(workspace, "resolve_safe", deny_b)
        report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("b.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py") == original_a
    assert workspace.read_file("b.py").text == "b = 2\n"
    assert any(path.read_bytes() == b"b = 1\n" for path in per_transaction_root.iterdir())


def test_rollback_does_not_overwrite_an_externally_modified_edited_file(tmp_path: Path) -> None:
    """Catches rollback replacing external content written after a transaction edit."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    (workspace.root / "a.py").write_bytes(b"value = external\n")
    per_transaction_root = transaction_directory(recovery_root)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py").text == "value = external\n"
    assert any(path.read_bytes() == b"value = 1\n" for path in per_transaction_root.iterdir())


def test_rollback_does_not_delete_an_externally_modified_created_file(tmp_path: Path) -> None:
    """Catches rollback deleting external content written over a transaction-created file."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    transaction.create_file("new.py", "created = True\n")
    (workspace.root / "new.py").write_bytes(b"external = True\n")
    per_transaction_root = transaction_directory(recovery_root)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("new.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("new.py").text == "external = True\n"
    assert len(tuple(per_transaction_root.iterdir())) == 1


def test_rollback_rejects_corrupted_recovery_material_before_target_mutation(
    tmp_path: Path,
) -> None:
    """Catches corrupted recovery bytes replacing a valid transaction target."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    edited = transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    material.write_bytes(b"corrupted recovery bytes\n")

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py") == edited
    assert material.read_bytes() == b"corrupted recovery bytes\n"


def test_rollback_verifies_restored_hash_before_deleting_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches rollback reporting success after the restored target changes again."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    real_replace = os.replace

    def replace_then_change_target(
        source: os.PathLike[str] | str, destination: os.PathLike[str] | str
    ) -> None:
        real_replace(source, destination)
        Path(destination).write_bytes(b"external after restore\n")

    monkeypatch.setattr(transactions_module.os, "replace", replace_then_change_target)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py").text == "external after restore\n"
    assert material.read_bytes() == b"value = 1\n"


def test_rollback_verifies_created_target_remains_absent_before_deleting_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches rollback reporting success after a removed created file is recreated."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    transaction.create_file("new.py", "created = True\n")
    target = workspace.root / "new.py"
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    real_unlink = Path.unlink

    def unlink_then_recreate(path: Path, *, missing_ok: bool = False) -> None:
        real_unlink(path, missing_ok=missing_ok)
        if path == target:
            path.write_bytes(b"external after removal\n")

    monkeypatch.setattr(Path, "unlink", unlink_then_recreate)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("new.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("new.py").text == "external after removal\n"
    assert material.exists()


def test_rollback_detects_a_dangling_entry_recreated_after_created_file_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches Path.exists treating a recreated dangling entry as safely absent."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    transaction.create_file("new.py", "created = True\n")
    target = workspace.root / "new.py"
    missing_target = workspace.root / "missing-target.py"
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    real_unlink = Path.unlink
    real_exists = Path.exists
    simulate_dangling = False

    def unlink_then_recreate_entry(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal simulate_dangling
        real_unlink(path, missing_ok=missing_ok)
        if path != target:
            return
        try:
            path.symlink_to(missing_target)
        except OSError:
            path.write_bytes(b"simulated dangling entry")
            simulate_dangling = True

    def exists_with_dangling_semantics(path: Path) -> bool:
        if simulate_dangling and path == target:
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "unlink", unlink_then_recreate_entry)
    monkeypatch.setattr(Path, "exists", exists_with_dangling_semantics)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("new.py",)
    assert report.recovery_root == per_transaction_root
    assert os.path.lexists(target)
    assert material.exists()


def test_recovery_root_inside_workspace_is_rejected_before_creating_material(
    tmp_path: Path,
) -> None:
    """Catches recovery data being placed where workspace operations can modify it."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    workspace = Workspace(workspace_root)
    unsafe_root = workspace.root / "nested" / ".." / "recovery"

    with pytest.raises(TransactionError, match="outside the workspace"):
        FileTransaction(workspace, unsafe_root)

    assert not (workspace.root / "recovery").exists()


def test_recovery_root_reparse_point_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a reparse recovery root redirecting durable material elsewhere."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    recovery_root.mkdir()
    real_lstat = os.lstat

    def lstat_with_reparse(path: os.PathLike[str] | str) -> os.stat_result | SimpleNamespace:
        result = real_lstat(path)
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(recovery_root)):
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return result

    monkeypatch.setattr(transactions_module.os, "lstat", lstat_with_reparse)

    with pytest.raises(TransactionError, match="reparse point"):
        FileTransaction(workspace, recovery_root)

    assert not any(recovery_root.iterdir())


def test_recovery_root_inspection_error_is_redacted_without_exception_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches recovery validation exposing raw external paths through an OS exception."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    recovery_root.mkdir()
    real_lstat = os.lstat

    def failing_lstat(path: os.PathLike[str] | str) -> os.stat_result:
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(recovery_root)):
            raise OSError(r"sensitive C:\external\recovery")
        return real_lstat(path)

    monkeypatch.setattr(transactions_module.os, "lstat", failing_lstat)

    with pytest.raises(TransactionError, match="inspected safely") as caught:
        FileTransaction(workspace, recovery_root)

    assert "sensitive" not in str(caught.value)
    assert_no_exception_chain(caught.value)
    assert not any(recovery_root.iterdir())


def test_recovery_directory_replacement_is_rejected_before_material_write(
    tmp_path: Path,
) -> None:
    """Catches first snapshots being written through a replaced transaction directory."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    per_transaction_root = transaction_directory(recovery_root)
    displaced_root = recovery_root / "displaced-original"
    per_transaction_root.rename(displaced_root)
    per_transaction_root.mkdir()

    with pytest.raises(TransactionError, match="recovery directory") as caught:
        transaction.edit_file("a.py", original.sha256, "1", "2")

    assert workspace.read_file("a.py") == original
    assert transaction.touched_paths == ()
    assert not any(per_transaction_root.iterdir())
    assert not any(displaced_root.iterdir())
    assert_no_exception_chain(caught.value)


def test_recovery_directory_replacement_is_rejected_before_material_read(
    tmp_path: Path,
) -> None:
    """Catches rollback trusting copied material in a replacement directory."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    edited = transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    material_name = material.name
    material_bytes = material.read_bytes()
    displaced_root = recovery_root / "displaced-original"
    per_transaction_root.rename(displaced_root)
    per_transaction_root.mkdir()
    (per_transaction_root / material_name).write_bytes(material_bytes)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py") == edited
    assert (displaced_root / material_name).read_bytes() == b"value = 1\n"
    assert (per_transaction_root / material_name).read_bytes() == b"value = 1\n"


def test_recovery_directory_replacement_before_material_delete_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a restored file being reported complete after its material directory changes."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material_name = next(iter(per_transaction_root.iterdir())).name
    displaced_root = recovery_root / "displaced-after-restore"
    real_replace = os.replace

    def replace_then_replace_recovery_directory(
        source: os.PathLike[str] | str, destination: os.PathLike[str] | str
    ) -> None:
        real_replace(source, destination)
        per_transaction_root.rename(displaced_root)
        per_transaction_root.mkdir()

    monkeypatch.setattr(transactions_module.os, "replace", replace_then_replace_recovery_directory)

    report = transaction.rollback()

    assert report.complete is False
    assert report.failed_paths == ("a.py",)
    assert report.recovery_root == per_transaction_root
    assert workspace.read_file("a.py") == original
    assert (displaced_root / material_name).read_bytes() == b"value = 1\n"
    assert per_transaction_root.is_dir()


def test_recovery_directory_reparse_is_rejected_before_commit_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches commit cleanup operating through a newly introduced reparse point."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    real_lstat = os.lstat

    def lstat_with_reparse(path: os.PathLike[str] | str) -> os.stat_result | SimpleNamespace:
        result = real_lstat(path)
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(per_transaction_root)):
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_dev=result.st_dev,
                st_ino=result.st_ino,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return result

    monkeypatch.setattr(transactions_module.os, "lstat", lstat_with_reparse)

    with pytest.raises(TransactionError, match="cleanup") as caught:
        transaction.commit()

    assert material.read_bytes() == b"value = 1\n"
    assert per_transaction_root.is_dir()
    assert_no_exception_chain(caught.value)


def test_recovery_filename_does_not_include_user_path_text(tmp_path: Path) -> None:
    """Catches user-controlled path text becoming a recovery filename."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    nested = workspace.root / "nested"
    nested.mkdir()
    secret_path = nested / "customer-secret.py"
    secret_path.write_bytes(b"token = 1\n")
    original = workspace.read_file("nested/customer-secret.py")

    transaction.edit_file("nested\\customer-secret.py", original.sha256, "1", "2")

    materials = tuple(transaction_directory(recovery_root).iterdir())
    assert transaction.touched_paths == ("nested/customer-secret.py",)
    assert len(materials) == 1
    assert "nested" not in materials[0].name
    assert "customer" not in materials[0].name
    assert materials[0].read_bytes() == b"token = 1\n"


def test_commit_cleanup_error_is_redacted_retains_material_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches commit losing recovery data or leaking raw cleanup errors on failure."""
    workspace, transaction, recovery_root = make_transaction(tmp_path)
    original = workspace.read_file("a.py")
    transaction.edit_file("a.py", original.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    material = next(iter(per_transaction_root.iterdir()))
    real_unlink = Path.unlink

    def fail_material_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == material:
            raise OSError(r"sensitive C:\external\recovery-material")
        real_unlink(path, missing_ok=missing_ok)

    with monkeypatch.context() as cleanup_patch:
        cleanup_patch.setattr(Path, "unlink", fail_material_unlink)
        with pytest.raises(TransactionError, match="cleanup") as caught:
            transaction.commit()

    assert material.read_bytes() == b"value = 1\n"
    assert per_transaction_root.is_dir()
    assert "sensitive" not in str(caught.value)
    assert_no_exception_chain(caught.value)

    transaction.commit()
    transaction.commit()
    assert not per_transaction_root.exists()


@pytest.mark.parametrize("operation", ["create", "edit", "rollback"])
def test_partially_cleaned_commit_allows_only_idempotent_commit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Catches writes or rollback after commit has irreversibly deleted some material."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    (workspace_root / "a.py").write_bytes(b"a = 1\n")
    (workspace_root / "b.py").write_bytes(b"b = 1\n")
    workspace = Workspace(workspace_root)
    recovery_root = tmp_path / "recovery"
    transaction = FileTransaction(workspace, recovery_root)
    original_a = workspace.read_file("a.py")
    original_b = workspace.read_file("b.py")
    edited_a = transaction.edit_file("a.py", original_a.sha256, "1", "2")
    edited_b = transaction.edit_file("b.py", original_b.sha256, "1", "2")
    per_transaction_root = transaction_directory(recovery_root)
    real_unlink = Path.unlink
    deleted_materials = 0

    def fail_second_material_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal deleted_materials
        if path.parent == per_transaction_root:
            if deleted_materials == 1:
                raise OSError("second recovery material cleanup failed")
            real_unlink(path, missing_ok=missing_ok)
            deleted_materials += 1
            return
        real_unlink(path, missing_ok=missing_ok)

    with monkeypatch.context() as cleanup_patch:
        cleanup_patch.setattr(Path, "unlink", fail_second_material_unlink)
        with pytest.raises(TransactionError, match="cleanup"):
            transaction.commit()

    assert len(tuple(per_transaction_root.iterdir())) == 1
    before_a = workspace.read_file("a.py")
    error_type = RollbackError if operation == "rollback" else TransactionError
    with pytest.raises(error_type, match="commit is already in progress"):
        if operation == "create":
            transaction.create_file("late.py", "late = True\n")
        elif operation == "edit":
            transaction.edit_file("a.py", before_a.sha256, "2", "9")
        else:
            transaction.rollback()

    assert workspace.read_file("a.py") == edited_a
    assert workspace.read_file("b.py") == edited_b
    assert not (workspace.root / "late.py").exists()
    assert len(tuple(per_transaction_root.iterdir())) == 1

    transaction.commit()
    transaction.commit()
    assert not per_transaction_root.exists()
