"""Synthetic counterparties, IRS, FX forwards, and cash CSAs.

Rating-to-PD values are illustrative teaching numbers, not a vendor table.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from ccr_xva.engines.pricing import flat_df, par_rate
from ccr_xva.models.schemas import CSA, Counterparty, MarketScenario, Trade

RATING_PD = {
    "AAA": 0.0002,
    "AA": 0.0005,
    "A": 0.0012,
    "BBB": 0.0040,
    "BB": 0.0180,
    "B": 0.0500,
    "CCC": 0.1500,
}

_NAMES = [
    ("ABC Bank", "A", "Financials", "US"),
    ("Northwind Energy", "BBB", "Energy", "US"),
    ("Helios Metals", "BB", "Materials", "DE"),
    ("Cinder Retail", "B", "Consumer", "GB"),
    ("Lumen Telecom", "BBB", "Telecom", "FR"),
    ("Orchid Health", "A", "Health", "US"),
]


def build_portfolio(
    n_counterparties: int = 4,
    seed: int = 7,
    as_of: date | None = None,
    usd_rate: float = 0.04,
) -> tuple[list[Counterparty], list[Trade], list[CSA]]:
    as_of = as_of or date(2026, 10, 5)
    scenario = MarketScenario(as_of=as_of, usd_rate=usd_rate)
    rng = np.random.default_rng(seed)
    counterparties: list[Counterparty] = []
    trades: list[Trade] = []
    csas: list[CSA] = []
    curve = flat_df(as_of, usd_rate)
    for index, (name, rating, sector, country) in enumerate(_NAMES[:n_counterparties]):
        counterparty_id = f"CP{index + 1}"
        netting_set_id = f"NS{index + 1}"
        counterparties.append(
            Counterparty(
                id=counterparty_id,
                name=name,
                rating=rating,
                sector=sector,
                country=country,
                pd=RATING_PD[rating],
                recovery_rate=0.40,
                metadata={"synthetic": True},
            )
        )
        start = as_of
        irs_maturity = date(start.year + int(rng.integers(3, 8)), start.month, start.day)
        fair = par_rate(start, irs_maturity, as_of, curve)
        fixed = fair if index % 2 == 0 else fair + 0.01
        notional = float(rng.choice([5_000_000, 10_000_000, 25_000_000]))
        trades.append(
            Trade(
                trade_id=f"IRS-{index + 1}",
                counterparty_id=counterparty_id,
                product_type="IRS",
                notional=notional,
                currency="USD",
                start_date=start,
                maturity=irs_maturity,
                fixed_rate=round(fixed, 6),
                direction="Pay" if index % 2 == 0 else "Receive",
                netting_set_id=netting_set_id,
                collateralized=True,
                underlying="USD-SWAP",
            )
        )
        pair = "EURUSD" if index % 2 == 0 else "USDJPY"
        spot = scenario.fx_spots[pair]
        fx_notional = float(rng.choice([2_000_000, 5_000_000]))
        trades.append(
            Trade(
                trade_id=f"FX-{index + 1}",
                counterparty_id=counterparty_id,
                product_type="FX_Forward",
                notional=fx_notional,
                currency="USD",
                start_date=start,
                maturity=date(start.year + 1, start.month, start.day),
                strike=round(spot * (1.0 if index % 2 == 0 else 1.02), 4),
                direction="Buy",
                netting_set_id=netting_set_id,
                collateralized=True,
                underlying=pair,
            )
        )
        threshold = 0.0 if index % 2 == 0 else 1_000_000.0
        csas.append(
            CSA(
                csa_id=f"CSA-{index + 1}",
                netting_set_id=netting_set_id,
                threshold=threshold,
                mta=100_000.0 if threshold else 0.0,
                independent_amount=0.0,
                collateral_type="Cash",
                frequency="Daily",
                currency="USD",
            )
        )
    return counterparties, trades, csas
