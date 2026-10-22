"""Write a sample book and optionally load it into SQLite."""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ccr_xva.synthetic.portfolio import build_portfolio  # noqa: E402


def main() -> None:
    as_of = date(2026, 10, 5)
    counterparties, trades, csas = build_portfolio(n_counterparties=4, as_of=as_of, seed=7)
    out = ROOT / "data" / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    trade_path = out / "sample_trades.csv"
    with trade_path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "trade_id",
            "counterparty_id",
            "counterparty_name",
            "rating",
            "sector",
            "country",
            "pd",
            "recovery_rate",
            "product_type",
            "notional",
            "currency",
            "start_date",
            "maturity",
            "fixed_rate",
            "strike",
            "direction",
            "netting_set_id",
            "collateralized",
            "underlying",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        names = {item.id: item for item in counterparties}
        for trade in trades:
            party = names[trade.counterparty_id]
            writer.writerow(
                {
                    "trade_id": trade.trade_id,
                    "counterparty_id": trade.counterparty_id,
                    "counterparty_name": party.name,
                    "rating": party.rating,
                    "sector": party.sector,
                    "country": party.country,
                    "pd": party.pd,
                    "recovery_rate": party.recovery_rate,
                    "product_type": trade.product_type,
                    "notional": trade.notional,
                    "currency": trade.currency,
                    "start_date": trade.start_date.isoformat(),
                    "maturity": trade.maturity.isoformat(),
                    "fixed_rate": "" if trade.fixed_rate is None else trade.fixed_rate,
                    "strike": "" if trade.strike is None else trade.strike,
                    "direction": trade.direction,
                    "netting_set_id": trade.netting_set_id,
                    "collateralized": str(trade.collateralized).lower(),
                    "underlying": trade.underlying or "",
                }
            )
    csa_path = out / "sample_csas.csv"
    with csa_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["csa_id", "netting_set_id", "threshold", "mta", "independent_amount", "frequency"])
        writer.writeheader()
        for csa in csas:
            writer.writerow(
                {
                    "csa_id": csa.csa_id,
                    "netting_set_id": csa.netting_set_id,
                    "threshold": csa.threshold,
                    "mta": csa.mta,
                    "independent_amount": csa.independent_amount,
                    "frequency": csa.frequency,
                }
            )
    print(f"Wrote {trade_path} and {csa_path}")


if __name__ == "__main__":
    main()
