"""Local accuracy, grounding, and retrieval checks.

GitHub-hosted CI runs this short suite. The high-path FX comparison lives in
the pytest slow marker and in scripts/run_eval.py.
"""

from __future__ import annotations

from datetime import date

from ccr_xva.engines.exposure import simulate_exposure
from ccr_xva.engines.pricing import fx_expected_positive_exposure, price_fx_forward
from ccr_xva.guardrails.csa_parser import parse_csa_text
from ccr_xva.guardrails.grounding import ungrounded_numbers
from ccr_xva.models.schemas import MarketScenario, NumericClaim, Trade
from ccr_xva.rag.retriever import build_retriever


def run_suite() -> dict:
    checks = {
        "csa_parser": _csa_parser(),
        "grounding_rejects_unknown_number": _grounding(),
        "fx_zero_vol_matches_revaluation": _fx_zero_vol(),
        "methodology_retrieval": _retrieval(),
        "agent_roster": _agent_roster(),
    }
    checks["passed"] = all(item["passed"] for key, item in checks.items() if isinstance(item, dict))
    return checks


def _csa_parser() -> dict:
    csa = parse_csa_text("daily cash collateral, 0 threshold, 10% MTA", "CSA-1", "NS-1", notional=1_000_000)
    passed = csa.frequency == "Daily" and csa.collateral_type == "Cash" and csa.threshold == 0 and abs(csa.mta - 100_000) < 1e-6
    return {"passed": passed, "mta": csa.mta, "threshold": csa.threshold}


def _grounding() -> dict:
    claims = [NumericClaim(name="cva", value=10.0, unit="USD", source="engine", source_id="calc")]
    missing = ungrounded_numbers("CVA is 99999.00 USD.", claims)
    return {"passed": missing == [99999.0], "missing": missing}


def _fx_zero_vol() -> dict:
    as_of = date(2026, 10, 5)
    scenario = MarketScenario(as_of=as_of, n_paths=80, seed=3, fx_vols={"EURUSD": 0.0, "USDJPY": 0.0}, hw_sigma=0.0)
    trade = Trade(
        trade_id="FX-EVAL",
        counterparty_id="CP",
        product_type="FX_Forward",
        notional=1_000_000,
        currency="USD",
        start_date=as_of,
        maturity=date(2027, 10, 5),
        strike=1.08,
        direction="Buy",
        netting_set_id="NS",
        collateralized=False,
        underlying="EURUSD",
    )
    result = simulate_exposure([trade], scenario, csa=None, collateralized=False)
    errors = []
    for day, ee in zip(result["dates"], result["ee"]):
        reference = max(price_fx_forward(trade, scenario, day), 0.0)
        if reference > 1.0:
            errors.append(abs(ee - reference) / reference)
        else:
            errors.append(abs(ee - reference))
    worst = max(errors) if errors else 0.0
    return {"passed": worst < 0.02, "worst_relative_or_absolute": worst}


def _agent_roster() -> dict:
    from ccr_xva.agents.runtime import AGENT_CATALOG, ROUTE_OWNER

    names = {item["name"] for item in AGENT_CATALOG}
    needed = {"desk", "methodology", "exposure", "cva", "dva", "fva", "csa", "trends", "xva", "memory"}
    owners = set(ROUTE_OWNER.values())
    return {"passed": needed <= names and owners <= names, "agents": sorted(names)}


def _retrieval() -> dict:
    retriever = build_retriever(chroma_path=None)
    hits = retriever.search("unilateral CVA recovery rate formula", k=3)
    text = " ".join(hit["text"] for hit in hits).lower()
    return {"passed": "recovery" in text and bool(hits), "hits": len(hits)}


def fx_closed_form_error(n_paths: int = 12000) -> dict:
    """Relative error of Monte Carlo EE versus the GBM positive-exposure formula."""
    as_of = date(2026, 10, 5)
    scenario = MarketScenario(as_of=as_of, n_paths=n_paths, seed=11, fx_vols={"EURUSD": 0.12, "USDJPY": 0.12})
    trade = Trade(
        trade_id="FX-BENCH",
        counterparty_id="CP",
        product_type="FX_Forward",
        notional=5_000_000,
        currency="USD",
        start_date=as_of,
        maturity=date(2028, 10, 5),
        strike=1.10,
        direction="Buy",
        netting_set_id="NS",
        collateralized=False,
        underlying="EURUSD",
    )
    result = simulate_exposure([trade], scenario, collateralized=False)
    horizon = date(2027, 10, 5)
    index = result["dates"].index(horizon)
    model = fx_expected_positive_exposure(trade, scenario, horizon)
    simulated = result["ee"][index]
    relative = abs(simulated - model) / model if model else abs(simulated - model)
    return {"ee": simulated, "closed_form": model, "relative_error": relative, "passed": relative <= 0.02}
