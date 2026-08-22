"""MARKET-OS deterministic foundation.

The public package intentionally exposes no live-trading adapter.  The first
implementation slice is limited to exact accounting, deterministic replay and
paper execution.
"""

from .errors import DomainError, DuplicateConflict, InvariantViolation

__all__ = ["DomainError", "DuplicateConflict", "InvariantViolation"]
__version__ = "0.1.0"
