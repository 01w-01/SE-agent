from __future__ import annotations

import traceback

import pytest
from keyring.errors import PasswordDeleteError

from fbw_harness.credentials import CredentialError, CredentialStatus, KeyringCredentialStore
from fbw_harness.errors import InputError
from fbw_harness.ports import CredentialStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if self.values.pop((service, account), None) is None:
            raise PasswordDeleteError("not found")


class FailingKeyring(FakeKeyring):
    def __init__(self, operation: str, leaked_value: str) -> None:
        super().__init__()
        self.operation = operation
        self.leaked_value = leaked_value

    def get_password(self, service: str, account: str) -> str | None:
        if self.operation == "get":
            raise RuntimeError(f"backend rejected {self.leaked_value}")
        return super().get_password(service, account)

    def set_password(self, service: str, account: str, value: str) -> None:
        if self.operation == "set":
            raise RuntimeError(f"backend rejected {self.leaked_value}")
        super().set_password(service, account, value)

    def delete_password(self, service: str, account: str) -> None:
        if self.operation == "clear":
            raise RuntimeError(f"backend rejected {self.leaked_value}")
        super().delete_password(service, account)


class DeleteDeniedKeyring(FakeKeyring):
    def __init__(self, backend_text: str) -> None:
        super().__init__()
        self.backend_text = backend_text

    def delete_password(self, service: str, account: str) -> None:
        raise PasswordDeleteError(self.backend_text)


def assert_exception_is_sanitized(
    error: BaseException, *, secret: str, backend_text: str
) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        details = "".join(
            (
                str(current),
                repr(current),
                "".join(
                    traceback.format_exception(
                        type(current), current, current.__traceback__, chain=False
                    )
                ),
            )
        )
        assert secret not in details
        assert backend_text not in details
        assert current.__context__ is None
        assert current.__cause__ is None
        for related in (current.__context__, current.__cause__):
            if related is not None:
                pending.append(related)


def test_credential_lifecycle_never_returns_value_from_status() -> None:
    backend = FakeKeyring()
    store = KeyringCredentialStore(backend=backend)

    store.set("temporary-value")

    assert store.status() == CredentialStatus(
        configured=True, service="fbw-harness", account="default"
    )
    assert store.get() == "temporary-value"
    assert store.clear() is True
    assert store.get() is None


def test_default_service_and_account_are_reported() -> None:
    store = KeyringCredentialStore(backend=FakeKeyring())

    assert store.status() == CredentialStatus(
        configured=False, service="fbw-harness", account="default"
    )


def test_blank_key_is_rejected_before_it_is_stored() -> None:
    store = KeyringCredentialStore(backend=FakeKeyring())

    with pytest.raises(InputError):
        store.set(" \t\n")

    assert store.get() is None


def test_clearing_a_missing_credential_returns_false() -> None:
    store = KeyringCredentialStore(backend=FakeKeyring())

    assert store.clear() is False


@pytest.mark.parametrize("operation", ["get", "set", "clear"])
def test_keyring_errors_do_not_include_secret(operation: str) -> None:
    secret = "temporary-value"
    backend = FailingKeyring(operation, secret)
    store = KeyringCredentialStore(backend=backend)
    backend_text = f"backend rejected {secret}"

    if operation == "clear":
        backend.values[("fbw-harness", "default")] = secret

    with pytest.raises(CredentialError) as error:
        if operation == "get":
            store.get()
        elif operation == "set":
            store.set(secret)
        else:
            store.clear()

    assert_exception_is_sanitized(
        error.value,
        secret=secret,
        backend_text=backend_text,
    )


def test_clear_raises_sanitized_error_when_present_credential_cannot_be_deleted() -> None:
    secret = "temporary-value"
    backend_text = f"access denied for {secret}"
    backend = DeleteDeniedKeyring(backend_text)
    backend.values[("fbw-harness", "default")] = secret
    store = KeyringCredentialStore(backend=backend)

    with pytest.raises(CredentialError) as error:
        store.clear()

    assert_exception_is_sanitized(
        error.value,
        secret=secret,
        backend_text=backend_text,
    )


def test_store_satisfies_credential_store_protocol() -> None:
    store = KeyringCredentialStore(backend=FakeKeyring())

    assert isinstance(store, CredentialStore)
