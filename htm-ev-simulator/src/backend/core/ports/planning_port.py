"""
Planning provider port (contract).

Rationale: The simulation core must not depend on Excel/Parquet/Pandas or any
specific data source. This port defines the minimal planning data the core
needs (blocks with journeys and points), allowing adapters to supply it from
any external system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.planning.block import Block


class PlanningProviderPort(ABC):
    """
    Provide planning data to the core.

    Implementations are expected to return domain models (`Block`, `Journey`,
    `PointInSequence`) already populated and internally consistent.
    """

    @abstractmethod
    def get_blocks(self) -> list[Block]:
        """
        Return all blocks for the simulation horizon.

        Rationale: Blocks are the natural aggregate for operational planning in
        this codebase and already contain the journeys and points required for
        simulation.
        """

