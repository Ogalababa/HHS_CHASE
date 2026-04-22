"""
Domain exceptions for charging infrastructure (laad-infra).

Rationale: Using explicit domain exceptions makes failure modes part of the
domain language and avoids ambiguous generic exceptions. This improves
traceability in simulations and supports clean error handling at the API layer
without leaking infrastructure concerns into the domain.
"""

from __future__ import annotations


class LaadInfraDomainError(Exception):
    """Base class for laad-infra domain errors."""


class ConnectorOccupiedError(LaadInfraDomainError):
    """Raised when trying to connect a bus to an occupied connector."""

