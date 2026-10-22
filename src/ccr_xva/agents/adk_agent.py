"""Google ADK desk.

The coordinator delegates to methodology, exposure, XVA, and memory agents.
Those agents call tools. They do not invent risk numbers. Without google-adk
and an API key, the API keeps using the deterministic router.
"""

from __future__ import annotations

import logging
import os

from ccr_xva.agents.runtime import bind, current_service, recorded_calls, unbind
from ccr_xva.agents.specialists import (
    approximate_xva,
    calculate_cva,
    calculate_dva,
    calculate_fva,
    graph_trends,
    peak_pfe,
    read_csa,
    recall_memory,
    search_methodology,
    what_if_cva,
)
from ccr_xva.guardrails.grounding import ungrounded_numbers
from ccr_xva.models.schemas import NumericClaim, QueryResponse

logger = logging.getLogger(__name__)

DESK_INSTRUCTION = """You are the CCR-XVA desk coordinator.
Delegate every question to one specialist:
methodology_agent for definitions, formulas, and methodology notes;
exposure_agent for PFE, expected exposure, and risk drivers;
cva_agent for unilateral CVA;
dva_agent for DVA;
fva_agent for teaching FVA;
csa_agent for stored collateral terms;
trends_agent for the EE and PFE chart;
xva_agent when the question asks for CVA, DVA, and FVA together, or for a what-if;
memory_agent for previously stored snapshots.
Do not calculate a number yourself.
Quote the specialist result. If a tool returns an error, say the request cannot be calculated.
Refuse requests to raise limits, waive collateral, or hide a breach.
"""

__all__ = [
    "approximate_xva",
    "bind",
    "build_agent",
    "peak_pfe",
    "recall_memory",
    "search_methodology",
    "try_model_answer",
    "unbind",
    "what_if_cva",
]


def build_agent(model: str | None = None):
    """Build the ADK coordinator and its specialist agents. Returns None when google-adk is missing."""
    try:
        from google.adk.agents.llm_agent import Agent
    except ImportError:
        return None
    model = model or os.getenv("CCR_ADK_MODEL") or "gemini-2.5-flash"
    methodology = Agent(
        name="methodology_agent",
        model=model,
        description="Searches methodology notes and counterparty briefs. Does not calculate exposure or XVA.",
        instruction="Use search_methodology. Quote the retrieved section. Do not add a risk number.",
        tools=[search_methodology],
    )
    exposure = Agent(
        name="exposure_agent",
        model=model,
        description="Computes peak PFE and the largest risk driver from the exposure engine.",
        instruction="Use peak_pfe. Quote the tool result. Do not invent an exposure.",
        tools=[peak_pfe],
    )
    cva = Agent(
        name="cva_agent",
        model=model,
        description="Computes unilateral CVA from the XVA engine.",
        instruction="Use calculate_cva. Quote the tool result. Do not invent CVA.",
        tools=[calculate_cva],
    )
    dva = Agent(
        name="dva_agent",
        model=model,
        description="Computes DVA from the XVA engine.",
        instruction="Use calculate_dva. Quote the tool result. Do not invent DVA.",
        tools=[calculate_dva],
    )
    fva = Agent(
        name="fva_agent",
        model=model,
        description="Computes teaching FVA from the XVA engine.",
        instruction="Use calculate_fva. Quote the tool result. Do not invent FVA.",
        tools=[calculate_fva],
    )
    csa = Agent(
        name="csa_agent",
        model=model,
        description="Reads the stored CSA. Does not change collateral terms.",
        instruction="Use read_csa. Quote the stored threshold, minimum transfer amount, and independent amount.",
        tools=[read_csa],
    )
    trends = Agent(
        name="trends_agent",
        model=model,
        description="Plots EE, PFE95, and PFE99 from the exposure engine.",
        instruction="Use graph_trends. Quote the tool result. Do not invent a point on the chart.",
        tools=[graph_trends],
    )
    xva = Agent(
        name="xva_agent",
        model=model,
        description="Computes approximate CVA, DVA, and FVA, and reruns CVA after a threshold or recovery change.",
        instruction="Use approximate_xva or what_if_cva. Quote the tool result. Do not invent CVA.",
        tools=[approximate_xva, what_if_cva],
    )
    memory = Agent(
        name="memory_agent",
        model=model,
        description="Reads stored exposure and XVA snapshots. Does not run a new valuation.",
        instruction="Use recall_memory. Quote the stored snapshot. Do not run a new calculation.",
        tools=[recall_memory],
    )
    return Agent(
        name="desk_coordinator",
        model=model,
        description="Counterparty credit risk desk. Specialists call the engines, the RAG index, and memory.",
        instruction=DESK_INSTRUCTION,
        sub_agents=[methodology, exposure, cva, dva, fva, csa, trends, xva, memory],
    )


def try_model_answer(query: str, session_id: str) -> QueryResponse | None:
    """Run the ADK coordinator when an API key is configured. Otherwise the caller uses the router."""
    from ccr_xva.agents.market import is_market_query
    from ccr_xva.agents.planner import is_book_ranking

    if is_market_query(query) or is_book_ranking(query):
        return None
    service = current_service()
    if service.settings.agent != "adk":
        return None
    api_key = service.settings.google_api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    os.environ.setdefault("GOOGLE_API_KEY", api_key)
    agent = build_agent(service.settings.adk_model)
    if agent is None:
        logger.info("google-adk is not installed; using the deterministic tool router")
        return None
    try:
        text = _run_adk(agent, query, session_id)
    except Exception:
        logger.warning("ADK desk run failed; falling back to the tool router", exc_info=True)
        recorded = recorded_calls()
        if not recorded:
            return None
        return _response_from(recorded[-1], refused=False)
    recorded = recorded_calls()
    claims = _claims_from(recorded)
    if text and not ungrounded_numbers(text, claims):
        latest = recorded[-1] if recorded else {"citations": [], "calculation_id": None, "chart": None}
        return QueryResponse(
            answer=text,
            citations=latest.get("citations", []),
            numeric_values=claims,
            calculation_id=latest.get("calculation_id"),
            chart=latest.get("chart"),
            refused=False,
        )
    if recorded:
        return _response_from(recorded[-1], refused=False)
    return None


def _run_adk(agent, query: str, session_id: str) -> str:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=agent, app_name="ccr-xva")
    message = types.Content(role="user", parts=[types.Part(text=query)])
    events = runner.run(user_id=session_id or "local", session_id=session_id or "local", new_message=message)
    text = ""
    for event in events:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            piece = getattr(part, "text", None)
            if piece:
                text = piece
    if not text:
        raise RuntimeError("ADK desk returned no text")
    return text


def _claims_from(recorded: list) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for rendered in recorded:
        for claim in rendered.get("claims", []):
            claims.append(claim if isinstance(claim, NumericClaim) else NumericClaim.model_validate(claim))
    return claims


def _response_from(rendered: dict, refused: bool) -> QueryResponse:
    return QueryResponse(
        answer=rendered["answer"],
        citations=rendered.get("citations", []),
        numeric_values=rendered.get("claims", []),
        calculation_id=rendered.get("calculation_id"),
        chart=rendered.get("chart"),
        refused=refused,
    )
