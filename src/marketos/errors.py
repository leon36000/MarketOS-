"""Domain exception hierarchy."""


class DomainError(RuntimeError):
    """Base class for deterministic MARKET-OS contract failures."""


class InvariantViolation(DomainError):
    """Raised when a hard domain invariant is violated."""


class DuplicateConflict(DomainError):
    """Raised when a stable identifier is reused for different content."""


class ExecutionStateChanged(InvariantViolation):
    """Raised when an authorized execution observes a different durable head."""
