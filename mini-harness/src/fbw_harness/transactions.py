from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import HarnessError
from .models import TransactionRecord
from .workspace import FileSnapshot, Workspace

_DIRECTORY_FSYNC_SUPPORTED = os.name != "nt"


class TransactionError(HarnessError):
    """A file transaction could not safely complete an operation."""


class EditConflictError(HarnessError):
    """An edit no longer applies exactly to the current file."""


class RollbackError(HarnessError):
    """Recovery material could not be applied safely."""


@dataclass(frozen=True, slots=True)
class RollbackReport:
    complete: bool
    failed_paths: tuple[str, ...] = ()
    recovery_root: Path | None = None


class FileTransaction:
    def __init__(self, workspace: Workspace, recovery_root: Path) -> None:
        self._workspace = workspace
        self._recovery_root = Path(os.path.abspath(Path(recovery_root)))
        if _is_within(workspace.root, self._recovery_root):
            raise TransactionError("recovery root must be outside the workspace")
        _reject_reparse_chain(self._recovery_root)

        root_creation_failed = False
        try:
            self._recovery_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            root_creation_failed = True
        if root_creation_failed:
            raise TransactionError("recovery root could not be created")
        _reject_reparse_chain(self._recovery_root)

        transaction_creation_failed = False
        try:
            child = tempfile.mkdtemp(prefix="transaction-", dir=self._recovery_root)
        except OSError:
            transaction_creation_failed = True
            child = ""
        if transaction_creation_failed:
            raise TransactionError("transaction recovery directory could not be created")
        self._transaction_root = Path(child)
        _reject_reparse_chain(self._transaction_root)
        self._transaction_identity = _directory_identity(self._transaction_root)
        self._records: dict[str, TransactionRecord] = {}
        self._written_hashes: dict[str, str] = {}
        self._touch_order: list[str] = []
        self._complete = False
        self._commit_started = False
        self._rollback_started = False
        self._rolled_back = False

    @property
    def touched_paths(self) -> tuple[str, ...]:
        return tuple(self._touch_order)

    def create_file(self, relative: str, content: str) -> FileSnapshot:
        self._require_active()
        target = self._workspace.resolve_safe(relative, must_exist=False)
        if self._target_exists(target):
            raise TransactionError("create target already exists")
        payload = self._encode_text(content)
        new_record = self._record_first_snapshot(relative, None)
        try:
            self._atomic_replace(
                target,
                payload,
                before_replace=lambda: self._require_create_target_absent(target),
            )
        except BaseException:
            if new_record is not None:
                self._discard_record(new_record)
            raise
        normalized = target.relative_to(self._workspace.root).as_posix()
        self._written_hashes[normalized] = hashlib.sha256(payload).hexdigest()
        return self._workspace.read_file(normalized)

    def edit_file(
        self, relative: str, expected_sha256: str, old_text: str, new_text: str
    ) -> FileSnapshot:
        self._require_active()
        target = self._workspace.resolve_safe(relative, must_exist=False)
        if not self._target_exists(target):
            raise EditConflictError("edit target does not exist")
        current = self._workspace.read_file(relative)
        if current.sha256 != expected_sha256:
            raise EditConflictError("edit target hash does not match the expected hash")
        if current.text.count(old_text) != 1:
            raise EditConflictError("old text must occur exactly once")
        updated_text = current.text.replace(old_text, new_text, 1)
        payload = self._encode_text(updated_text)
        new_record = self._record_first_snapshot(relative, current)
        try:
            self._atomic_replace(
                target,
                payload,
                before_replace=lambda: self._require_current_hash(relative, expected_sha256),
            )
        except BaseException:
            if new_record is not None:
                self._discard_record(new_record)
            raise
        normalized = target.relative_to(self._workspace.root).as_posix()
        self._written_hashes[normalized] = hashlib.sha256(payload).hexdigest()
        return self._workspace.read_file(normalized)

    def commit(self) -> None:
        if self._complete:
            return
        if self._rollback_started:
            raise TransactionError("transaction rollback is already in progress")
        self._commit_started = True
        if not self._remove_recovery_tree():
            raise TransactionError("transaction recovery cleanup failed")
        self._complete = True

    def rollback(self) -> RollbackReport:
        if self._rolled_back:
            return RollbackReport(complete=True)
        if self._commit_started:
            raise RollbackError("transaction commit is already in progress")
        self._rollback_started = True
        failed: list[str] = []
        for relative in reversed(self._touch_order):
            record = self._records[relative]
            if record.recovered:
                continue
            if not self._restore_record(record) or not self._remove_recovery_material(
                record.recovery_path
            ):
                failed.append(relative)
            else:
                self._records[relative] = replace(record, recovered=True)
                self._written_hashes.pop(relative, None)
        if failed:
            return RollbackReport(
                complete=False,
                failed_paths=tuple(failed),
                recovery_root=self._transaction_root,
            )
        if not self._remove_recovery_tree():
            return RollbackReport(
                complete=False,
                recovery_root=self._transaction_root,
            )
        self._complete = True
        self._rolled_back = True
        return RollbackReport(complete=True)

    def _require_active(self) -> None:
        if self._complete:
            raise TransactionError("transaction is already complete")
        if self._rollback_started:
            raise TransactionError("transaction rollback is already in progress")
        if self._commit_started:
            raise TransactionError("transaction commit is already in progress")

    def _restore_record(self, record: TransactionRecord) -> bool:
        expected_sha256 = self._written_hashes.get(record.relative_path)
        if expected_sha256 is None:
            return False
        resolution_failed = False
        try:
            target = self._workspace.resolve_safe(record.relative_path, must_exist=False)
        except HarnessError:
            resolution_failed = True
            target = self._workspace.root
        if resolution_failed:
            return False

        if record.originally_existed:
            if record.original_sha256 is None:
                return False
            material_validation_failed = False
            try:
                self._validate_recovery_material(record.recovery_path)
            except TransactionError:
                material_validation_failed = True
            if material_validation_failed:
                return False
            read_failed = False
            try:
                payload = record.recovery_path.read_bytes()
            except OSError:
                read_failed = True
                payload = b""
            if read_failed:
                return False
            if hashlib.sha256(payload).hexdigest() != record.original_sha256:
                return False

            current_read_failed = False
            try:
                current = self._workspace.read_file(record.relative_path)
            except HarnessError:
                current_read_failed = True
                current = None
            if current_read_failed or current is None:
                return False
            if current.sha256 == record.original_sha256:
                return True
            if current.sha256 != expected_sha256:
                return False

            replace_failed = False
            try:
                self._atomic_replace(
                    target,
                    payload,
                    before_replace=lambda: self._require_current_hash(
                        record.relative_path, expected_sha256
                    ),
                )
            except HarnessError:
                replace_failed = True
            if replace_failed:
                return False
            verification_failed = False
            try:
                restored = self._workspace.read_file(record.relative_path)
            except HarnessError:
                verification_failed = True
                restored = None
            return (
                not verification_failed
                and restored is not None
                and restored.sha256 == record.original_sha256
            )

        removal_failed = False
        try:
            exists = self._target_entry_exists(target)
            if exists:
                current = self._workspace.read_file(record.relative_path)
                if current.sha256 != expected_sha256:
                    return False
                target.unlink()
            if self._target_entry_exists(target):
                return False
        except (HarnessError, OSError):
            removal_failed = True
        return not removal_failed

    def _record_first_snapshot(
        self, relative: str, snapshot: FileSnapshot | None
    ) -> TransactionRecord | None:
        normalized = (
            self._workspace.resolve_safe(relative, must_exist=False)
            .relative_to(self._workspace.root)
            .as_posix()
        )
        if normalized in self._records:
            return None
        material_name = (
            f"{len(self._records):04d}-{hashlib.sha256(normalized.encode()).hexdigest()}"
        )
        recovery_path = self._transaction_root / material_name
        payload = b"" if snapshot is None else snapshot.text.encode("utf-8")
        self._validate_transaction_root()
        recovery_failed = False
        try:
            with recovery_path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            recovery_failed = True
        if recovery_failed:
            self._remove_recovery_material(recovery_path, must_exist=False)
            raise TransactionError("recovery material could not be written")
        try:
            self._fsync_recovery_directory()
        except TransactionError:
            self._remove_recovery_material(recovery_path)
            raise
        record = TransactionRecord(
            relative_path=normalized,
            originally_existed=snapshot is not None,
            original_sha256=None if snapshot is None else snapshot.sha256,
            recovery_path=recovery_path,
        )
        self._records[normalized] = record
        self._touch_order.append(normalized)
        return record

    def _fsync_recovery_directory(self) -> None:
        self._validate_transaction_root()
        if not _DIRECTORY_FSYNC_SUPPORTED:
            return

        directory_fd: int | None = None
        synchronization_failed = False
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(self._transaction_root, flags)
        except OSError:
            synchronization_failed = True
        if not synchronization_failed and directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                synchronization_failed = True
            try:
                os.close(directory_fd)
            except OSError:
                synchronization_failed = True
        if synchronization_failed:
            raise TransactionError("recovery directory could not be synchronized")

    def _discard_record(self, record: TransactionRecord) -> None:
        self._records.pop(record.relative_path, None)
        self._written_hashes.pop(record.relative_path, None)
        self._touch_order.remove(record.relative_path)
        self._remove_recovery_material(record.recovery_path)

    def _encode_text(self, text: str) -> bytes:
        invalid = not isinstance(text, str)
        payload = b""
        if not invalid:
            try:
                payload = text.encode("utf-8")
            except UnicodeEncodeError:
                invalid = True
        if invalid or b"\x00" in payload:
            raise TransactionError("file content must be valid UTF-8 text")
        if len(payload) > self._workspace.file_size_limit_bytes:
            raise TransactionError("file content exceeds the workspace size limit")
        return payload

    def _atomic_replace(
        self,
        target: Path,
        payload: bytes,
        *,
        before_replace: Callable[[], None],
    ) -> None:
        temp_path: Path | None = None
        file_descriptor: int | None = None
        temp_failed = False
        try:
            file_descriptor, raw_temp_path = tempfile.mkstemp(
                prefix=".fbw-transaction-", dir=target.parent
            )
            temp_path = Path(raw_temp_path)
            with os.fdopen(file_descriptor, "wb") as stream:
                file_descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            temp_failed = True
        if temp_failed:
            if file_descriptor is not None:
                self._close_file_descriptor_best_effort(file_descriptor)
            if temp_path is not None:
                self._remove_file_best_effort(temp_path)
            raise TransactionError("transaction temporary file could not be written")

        assert temp_path is not None
        try:
            before_replace()
        except BaseException:
            self._remove_file_best_effort(temp_path)
            raise

        replace_failed = False
        try:
            os.replace(temp_path, target)
        except OSError:
            replace_failed = True
        if replace_failed:
            self._remove_file_best_effort(temp_path)
            raise TransactionError("transaction target could not be replaced")

    def _require_create_target_absent(self, target: Path) -> None:
        if self._target_exists(target):
            raise TransactionError("create target already exists")

    def _require_current_hash(self, relative: str, expected_sha256: str) -> None:
        target = self._workspace.resolve_safe(relative, must_exist=False)
        if not self._target_exists(target):
            raise EditConflictError("edit target does not exist")
        current = self._workspace.read_file(relative)
        if current.sha256 != expected_sha256:
            raise EditConflictError("edit target hash does not match the expected hash")

    @staticmethod
    def _target_exists(target: Path) -> bool:
        inspection_failed = False
        try:
            exists = target.exists()
        except OSError:
            inspection_failed = True
            exists = False
        if inspection_failed:
            raise TransactionError("transaction target could not be inspected")
        return exists

    @staticmethod
    def _target_entry_exists(target: Path) -> bool:
        inspection_failed = False
        try:
            os.lstat(target)
        except FileNotFoundError:
            return False
        except OSError:
            inspection_failed = True
        if inspection_failed:
            raise TransactionError("transaction target could not be inspected")
        return True

    @staticmethod
    def _remove_file_best_effort(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _close_file_descriptor_best_effort(file_descriptor: int) -> None:
        try:
            os.close(file_descriptor)
        except OSError:
            pass

    def _validate_transaction_root(self) -> None:
        if _same_path(self._recovery_root, self._transaction_root) or not _is_within(
            self._recovery_root, self._transaction_root
        ):
            raise TransactionError("transaction recovery directory escapes its configured root")
        _reject_reparse_chain(self._transaction_root)
        if _directory_identity(self._transaction_root) != self._transaction_identity:
            raise TransactionError("transaction recovery directory identity changed")

    def _validate_recovery_material(self, path: Path, *, must_exist: bool = True) -> None:
        self._validate_transaction_root()
        if not _same_path(path.parent, self._transaction_root) or not _is_within(
            self._transaction_root, path
        ):
            raise TransactionError("recovery material escapes its transaction directory")
        _reject_reparse_chain(path)

        inspection_failed = False
        missing = False
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            missing = True
            metadata = None
        except OSError:
            inspection_failed = True
            metadata = None
        if inspection_failed:
            raise TransactionError("recovery material cannot be inspected safely")
        if missing:
            if must_exist:
                raise TransactionError("recovery material does not exist")
            return
        assert metadata is not None
        attributes = getattr(metadata, "st_file_attributes", 0)
        if not stat.S_ISREG(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise TransactionError("recovery material is not a safe regular file")

    def _remove_recovery_material(self, path: Path, *, must_exist: bool = True) -> bool:
        validation_failed = False
        try:
            self._validate_recovery_material(path, must_exist=must_exist)
        except TransactionError:
            validation_failed = True
        if validation_failed:
            return False

        removal_failed = False
        try:
            path.unlink(missing_ok=not must_exist)
        except OSError:
            removal_failed = True
        return not removal_failed

    def _remove_recovery_tree(self) -> bool:
        validation_failed = False
        try:
            self._validate_transaction_root()
        except TransactionError:
            validation_failed = True
        if validation_failed:
            return False

        cleanup_failed = False
        try:
            children = tuple(self._transaction_root.iterdir())
        except OSError:
            cleanup_failed = True
            children = ()
        if not cleanup_failed:
            for child in children:
                if not self._remove_recovery_material(child):
                    cleanup_failed = True
                    break
        if not cleanup_failed:
            try:
                self._validate_transaction_root()
            except TransactionError:
                cleanup_failed = True
        if not cleanup_failed:
            try:
                self._transaction_root.rmdir()
            except OSError:
                cleanup_failed = True
        return not cleanup_failed


def _is_within(root: Path, target: Path) -> bool:
    root_text = os.path.normcase(os.path.abspath(root))
    target_text = os.path.normcase(os.path.abspath(target))
    try:
        common = os.path.commonpath((root_text, target_text))
    except ValueError:
        return False
    return os.path.normcase(common) == root_text


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _directory_identity(path: Path) -> tuple[int, int]:
    inspection_failed = False
    try:
        metadata = os.lstat(path)
    except OSError:
        inspection_failed = True
        metadata = None
    if inspection_failed or metadata is None:
        raise TransactionError("transaction recovery directory cannot be inspected safely")
    attributes = getattr(metadata, "st_file_attributes", 0)
    if not stat.S_ISDIR(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise TransactionError("transaction recovery directory is not a safe directory")
    return metadata.st_dev, metadata.st_ino


def _reject_reparse_chain(path: Path) -> None:
    inspection_failed = False
    reparse_found = False
    for current in reversed((path, *path.parents)):
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError:
            inspection_failed = True
            break
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            reparse_found = True
            break
    if inspection_failed:
        raise TransactionError("recovery root cannot be inspected safely")
    if reparse_found:
        raise TransactionError("recovery root must not contain a reparse point")
