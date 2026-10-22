"""Request scope and agent handoff records shared by every desk agent."""

from __future__ import annotations

import contextvars
from datetime import date

from ccr_xva.memory.tracing import build_trace, export_langfuse
from ccr_xva.models.schemas import MarketScenario
from ccr_xva.services.risk import RiskService
from shared.ids import new_id

AGENT_CATALOG = [
    {
        "name": "desk",
        "role": "Coordinates the desk and refuses requests that would hide or waive risk.",
        "tools": [],
    },
    {
        "name": "methodology",
        "role": "Retrieves methodology notes and counterparty briefs. Does not calculate a risk number.",
        "tools": ["search_methodology"],
    },
    {
        "name": "exposure",
        "role": "Returns peak PFE and expected exposure from the Monte Carlo engine.",
        "tools": ["peak_pfe"],
    },
    {
        "name": "cva",
        "role": "Returns unilateral CVA from the XVA engine.",
        "tools": ["calculate_cva"],
    },
    {
        "name": "dva",
        "role": "Returns DVA from the XVA engine.",
        "tools": ["calculate_dva"],
    },
    {
        "name": "fva",
        "role": "Returns the teaching FVA from the XVA engine.",
        "tools": ["calculate_fva"],
    },
    {
        "name": "csa",
        "role": "Reads the stored CSA threshold, minimum transfer amount, and independent amount.",
        "tools": ["read_csa"],
    },
    {
        "name": "trends",
        "role": "Plots EE, PFE95, and PFE99 from the exposure engine.",
        "tools": ["graph_trends"],
    },
    {
        "name": "xva",
        "role": "Returns CVA, DVA, and FVA together, including collateral and recovery what-ifs.",
        "tools": ["approximate_xva", "what_if_cva"],
    },
    {
        "name": "memory",
        "role": "Reads stored snapshots and the session. Does not run a new valuation.",
        "tools": ["recall_memory"],
    },
    {
        "name": "market",
        "role": "Reads a live equity or index quote. Does not value the credit book.",
        "tools": [],
    },
]

ROUTE_OWNER = {
    "rag": "methodology",
    "exposure": "exposure",
    "top_pfe": "exposure",
    "top_credit": "cva",
    "cva": "cva",
    "dva": "dva",
    "fva": "fva",
    "csa": "csa",
    "trends": "trends",
    "xva": "xva",
    "what_if": "xva",
    "sensitivity": "xva",
    "compare": "memory",
    "memory": "memory",
    "market": "market",
    "refuse": "desk",
}

_SERVICE: contextvars.ContextVar[RiskService | None] = contextvars.ContextVar("ccr_service", default=None)
_SCENARIO: contextvars.ContextVar[MarketScenario | None] = contextvars.ContextVar("ccr_scenario", default=None)
_SESSION: contextvars.ContextVar[str] = contextvars.ContextVar("ccr_session", default="local")
_CALLS: contextvars.ContextVar[list | None] = contextvars.ContextVar("ccr_tool_calls", default=None)


def bind(service: RiskService, scenario: MarketScenario | None = None, session_id: str = "local") -> tuple:
    """Attach the request-scoped book, scenario, and session for tool calls."""
    return (
        _SERVICE.set(service),
        _SCENARIO.set(scenario),
        _SESSION.set(session_id or "local"),
        _CALLS.set([]),
    )


def unbind(tokens: tuple) -> None:
    service_token, scenario_token, session_token, calls_token = tokens
    _SERVICE.reset(service_token)
    _SCENARIO.reset(scenario_token)
    _SESSION.reset(session_token)
    _CALLS.reset(calls_token)


def current_service() -> RiskService:
    service = _SERVICE.get()
    if service is None:
        from ccr_xva.memory.repository import get_repository
        from shared.settings import get_settings

        settings = get_settings()
        service = RiskService(get_repository(settings.database_url), settings)
    return service


def current_scenario() -> MarketScenario:
    scenario = _SCENARIO.get()
    if scenario is not None:
        return scenario
    return MarketScenario(as_of=date(2026, 10, 5), n_paths=120, seed=7)


def current_session() -> str:
    return _SESSION.get() or "local"


def remember(rendered: dict) -> None:
    calls = _CALLS.get()
    if calls is not None:
        calls.append(rendered)


def recorded_calls() -> list:
    return list(_CALLS.get() or [])


def agent_for_route(route: str) -> str:
    return ROUTE_OWNER.get(route, "desk")


def record_agent_step(service: RiskService, agent: str, query: str, rendered: dict, session_id: str) -> str:
    """Store an agent handoff beside the engine trace and export it when Langfuse is configured."""
    trace = build_trace(
        new_id(),
        f"agent:{agent}",
        {
            "query": query,
            "session_id": session_id,
            "calculation_id": rendered.get("calculation_id"),
            "agent": agent,
        },
        {"answer": str(rendered.get("answer", ""))[:2000]},
        [f"{agent} handled the question"],
    )
    service.repo.save_trace(trace)
    export_langfuse(trace, service.settings)
    return trace.calculation_id
