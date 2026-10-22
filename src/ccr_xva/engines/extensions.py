"""Phase 7 extension points. v0.1 does not implement these calculations."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ccr_xva.models.schemas import Counterparty, ExposureProfile, MarketScenario, Trade


def price_european_option(trade: Trade, scenario: MarketScenario, as_of: date | None = None) -> float:
    """European options are a typed product but not priced in v0.1."""
    _ = (trade, scenario, as_of)
    raise NotImplementedError(
        "European_Option pricing is a Phase 7 extension. v0.1 prices IRS and FX_Forward only."
    )


class RevaluationSurrogate(Protocol):
    """Optional fast replacement for pathwise full revaluation."""

    def revalue(self, trades: list[Trade], scenario: MarketScenario, grid: list[date]) -> list[list[float]]:
        """Return mark-to-market rows aligned to `grid`."""


class WrongWayRiskModel(Protocol):
    """Correlation-proxy wrong-way flag. Not used by the v0.1 agent."""

    def flag(self, counterparty: Counterparty, profile: ExposureProfile) -> dict:
        """Return a flag payload with a reason and a score in [0, 1]."""


def extension_status() -> dict[str, str]:
    return {
        "european_option": "not_implemented",
        "revaluation_surrogate": "protocol_only",
        "wrong_way_risk": "protocol_only",
        "multi_currency_collateral": "not_implemented",
    }
