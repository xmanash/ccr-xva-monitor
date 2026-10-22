"""Risk tools shared by the MCP server. Numbers come from the calculation engines."""

from __future__ import annotations

from datetime import date

from ccr_xva.agents.graph import run_query
from ccr_xva.memory.repository import get_repository
from ccr_xva.models.schemas import MarketScenario
from ccr_xva.services.risk import RiskService, exposure_chart
from shared.settings import get_settings


def _service() -> RiskService:
    settings = get_settings()
    return RiskService(get_repository(settings.database_url), settings)


def _scenario(as_of: str, n_paths: int) -> MarketScenario:
    return MarketScenario(as_of=date.fromisoformat(as_of), n_paths=n_paths, seed=7)


def list_book() -> dict:
    """List stored counterparties and netting sets."""
    service = _service()
    trades = service.repo.list_trades()
    return {
        "counterparties": [item.model_dump(mode="json") for item in service.repo.list_counterparties()],
        "netting_sets": sorted({trade.netting_set_id for trade in trades}),
        "trades": len(trades),
    }


def load_sample_book() -> dict:
    """Load the synthetic IRS and FX sample book. Existing CSAs are kept."""
    return _service().load_sample_book()


def calculate_exposure(netting_set_id: str, as_of: str = "2026-10-05", n_paths: int = 200) -> dict:
    """Compute EE, PFE95, and PFE99 for one netting set."""
    profile = _service().calculate_exposure(netting_set_id, _scenario(as_of, n_paths))
    return {"profile": profile.model_dump(mode="json"), "chart": exposure_chart(profile)}


def calculate_xva(netting_set_id: str, as_of: str = "2026-10-05", n_paths: int = 200) -> dict:
    """Compute approximate unilateral CVA, DVA, and FVA for one netting set."""
    result = _service().calculate_xva(netting_set_id, _scenario(as_of, n_paths))
    return {"xva": result.model_dump(mode="json")}


def list_agents() -> dict:
    """List the desk agents and the tool each one is allowed to call."""
    from ccr_xva.agents.runtime import AGENT_CATALOG

    return {"agents": AGENT_CATALOG}


def recall_memory(counterparty: str = "", session_id: str = "mcp") -> dict:
    """Read stored exposure and XVA snapshots. Does not run a new valuation."""
    from ccr_xva.agents.runtime import bind, unbind
    from ccr_xva.agents.specialists import recall_memory as recall

    tokens = bind(_service(), session_id=session_id)
    try:
        return recall(counterparty)
    finally:
        unbind(tokens)


def search_methodology(query: str) -> dict:
    """Search methodology notes and counterparty briefs. Does not calculate a risk number."""
    from ccr_xva.agents.adk_agent import bind, search_methodology as retrieve
    from ccr_xva.agents.adk_agent import unbind

    tokens = bind(_service())
    try:
        return retrieve(query)
    finally:
        unbind(tokens)


def ask_risk(
    query: str,
    as_of: str = "2026-10-05",
    n_paths: int = 120,
    session_id: str = "mcp",
) -> dict:
    """Ask a grounded risk question. Every number is checked against the engine or cited notes."""
    response = run_query(
        _service(),
        query,
        session_id=session_id,
        include_charts=True,
        scenario=_scenario(as_of, n_paths),
    )
    return response.model_dump(mode="json")
