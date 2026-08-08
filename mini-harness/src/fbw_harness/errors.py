from __future__ import annotations


class HarnessError(Exception):
    exit_code = 1


class InputError(HarnessError):
    exit_code = 2


class RollbackIncompleteError(HarnessError):
    exit_code = 3


class ModelValidationError(InputError):
    pass
