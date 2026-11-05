"""Public error contract: usage/schema errors exit 2, missing resources/state conflicts exit 3.

Raising any of these from a command handler aborts the whole call atomically:
no state change, no time change. Mutating calls additionally log one rejected
event (no delta) so the attempt stays visible in evidence.
"""


class OpsError(Exception):
    code = "E_STATE"
    exit_code = 3

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "exit_code": self.exit_code}


class UsageError(OpsError):
    """Malformed or out-of-schema input (``E_USAGE`` or a specific code such as ``E_BAD_DURATION``)."""

    code = "E_USAGE"
    exit_code = 2


class NotFound(OpsError):
    code = "E_NOT_FOUND"
    exit_code = 3


class StateError(OpsError):
    """Conflict or invalid lifecycle transition (``E_STATE`` or a specific code such as ``E_JOB_ACTIVE``)."""

    code = "E_STATE"
    exit_code = 3
