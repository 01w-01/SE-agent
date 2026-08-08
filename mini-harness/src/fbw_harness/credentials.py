from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import keyring

from .errors import HarnessError, InputError


class KeyringBackend(Protocol):
    def get_password(self, service: str, account: str) -> str | None: ...

    def set_password(self, service: str, account: str, value: str) -> None: ...

    def delete_password(self, service: str, account: str) -> None: ...


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    configured: bool
    service: str
    account: str


class CredentialError(HarnessError):
    pass


class KeyringCredentialStore:
    def __init__(
        self,
        *,
        service: str = "fbw-harness",
        account: str = "default",
        backend: KeyringBackend | None = None,
    ) -> None:
        self._service = service
        self._account = account
        self._backend = backend if backend is not None else keyring

    def get(self) -> str | None:
        backend_failed = False
        try:
            return self._backend.get_password(self._service, self._account)
        except Exception:  # noqa: BLE001 - backend exceptions must not leak credential details
            backend_failed = True
        if backend_failed:
            raise CredentialError("Unable to read credential.")

    def set(self, value: str) -> None:
        if not value.strip():
            raise InputError("Credential value must not be blank.")
        backend_failed = False
        try:
            self._backend.set_password(self._service, self._account, value)
        except Exception:  # noqa: BLE001 - backend exceptions must not leak credential details
            backend_failed = True
        if not backend_failed:
            return
        raise CredentialError("Unable to store credential.")

    def clear(self) -> bool:
        backend_failed = False
        try:
            self._backend.delete_password(self._service, self._account)
        except Exception:  # noqa: BLE001 - backend exceptions must not leak credential details
            backend_failed = True
        if not backend_failed:
            return True

        if self.get() is None:
            return False
        raise CredentialError("Unable to clear credential.")

    def status(self) -> CredentialStatus:
        return CredentialStatus(
            configured=self.get() is not None,
            service=self._service,
            account=self._account,
        )
