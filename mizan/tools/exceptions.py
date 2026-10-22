class MizanError(Exception):
    """Base exception for deterministic Mizan engine errors."""


class MizanInputError(MizanError, ValueError):
    """Raised when a tool receives an unsupported region, metric, or option."""


class MizanDataError(MizanError, RuntimeError):
    """Raised when an approved source file is absent or fails validation."""
