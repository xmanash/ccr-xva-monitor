"""LangGraph path: policy, planner, tools, critic, output check."""

from __future__ import annotations

import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ccr_xva.agents import explain
from ccr_xva.agents.llm import rewrite
from ccr_xva.agents.planner import plan_query
from ccr_xva.guardrails.grounding import ungrounded_numbers
from ccr_xva.guardrails.policy import check_query
from ccr_xva.models.schemas import MarketScenario, QueryResponse
from ccr_xva.services.risk import RiskService


class AgentState(TypedDict, total=False):
    query: str
    session_id: str
    include_charts: bool
    requested_netting_set: str | None
    scenario: dict | None
    refused: bool
    route: str
    params: dict
    answer: str
    fallback_answer: str
    claims: list
    citations: list
    calculation_id: str | None
    chart: dict | None


def build_graph(service: RiskService):
    def guard_input(state: AgentState) -> AgentState:
        reason = check_query(state["query"])
        if reason:
            answer = f"This request is refused. {reason}"
            return {
                "refused": True,
                "route": "refuse",
                "answer": answer,
                "fallback_answer": answer,
                "claims": [],
                "citations": [],
                "calculation_id": None,
                "chart": None,
            }
        return {"refused": False}

    def planner(state: AgentState) -> AgentState:
        decision = plan_query(
            state["query"],
            service,
            state.get("session_id", "local"),
            state.get("requested_netting_set"),
        )
        if decision["route"] == "refuse":
            answer = f"This request is refused. {decision['reason']}"
            return {
                "refused": True,
                "route": "refuse",
                "answer": answer,
                "fallback_answer": answer,
                "claims": [],
                "citations": [],
            }
        return {"route": decision["route"], "params": decision["params"], "refused": False}

    def execute(state: AgentState) -> AgentState:
        if state.get("refused"):
            return {}
        scenario = None
        if state.get("scenario"):
            scenario = MarketScenario.model_validate(state["scenario"])
        try:
            rendered = _run_route(
                service,
                state["route"],
                state.get("params", {}),
                scenario,
                state["query"],
                state.get("session_id", "local"),
            )
            from ccr_xva.agents.runtime import agent_for_route, record_agent_step

            record_agent_step(
                service,
                agent_for_route(state["route"]),
                state["query"],
                rendered,
                state.get("session_id", "local"),
            )
        except ValueError as exc:
            answer = f"This request cannot be calculated. {exc}"
            if ungrounded_numbers(answer, []):
                answer = "This request cannot be calculated with the trades currently stored."
            return {
                "answer": answer,
                "fallback_answer": answer,
                "claims": [],
                "citations": [],
                "calculation_id": None,
                "chart": None,
            }
        return {
            "answer": rendered["answer"],
            "fallback_answer": rendered["answer"],
            "claims": [claim.model_dump() for claim in rendered["claims"]],
            "citations": [citation.model_dump() for citation in rendered["citations"]],
            "calculation_id": rendered["calculation_id"],
            "chart": rendered["chart"] if state.get("include_charts", True) else None,
        }

    def critic(state: AgentState) -> AgentState:
        claims = [_claim_model(item) for item in state.get("claims", [])]
        candidate = state.get("answer", "")
        if not state.get("refused") and service.settings.llm_enabled:
            prompt = (
                "Rewrite the answer in plain language. Use only numbers that already appear. "
                "Do not add any new number.\n\n"
                f"{candidate}"
            )
            rewritten = rewrite(prompt, service.settings)
            if rewritten and not ungrounded_numbers(rewritten, claims):
                candidate = rewritten
        if ungrounded_numbers(candidate, claims):
            candidate = state.get("fallback_answer", candidate)
        if ungrounded_numbers(candidate, claims):
            candidate = "The draft answer contained a number that is not in the calculation or the cited notes, so it was withheld."
            claims = []
            if ungrounded_numbers(candidate, claims):
                candidate = "The draft answer was withheld because a number could not be grounded."
        return {"answer": candidate, "claims": [claim.model_dump() for claim in claims]}

    def guard_output(state: AgentState) -> AgentState:
        reason = check_query(state.get("answer", ""))
        if reason:
            answer = f"This request is refused. {reason}"
            return {"refused": True, "answer": answer, "claims": [], "chart": None}
        return {}

    graph = StateGraph(AgentState)
    graph.add_node("guard_input", guard_input)
    graph.add_node("planner", planner)
    graph.add_node("execute", execute)
    graph.add_node("critic", critic)
    graph.add_node("guard_output", guard_output)
    graph.set_entry_point("guard_input")
    graph.add_conditional_edges(
        "guard_input",
        lambda state: "end" if state.get("refused") else "planner",
        {"end": END, "planner": "planner"},
    )
    graph.add_edge("planner", "execute")
    graph.add_edge("execute", "critic")
    graph.add_edge("critic", "guard_output")
    graph.add_edge("guard_output", END)
    return graph.compile()


def run_query(
    service: RiskService,
    query: str,
    session_id: str = "local",
    include_charts: bool = True,
    netting_set_id: str | None = None,
    scenario: MarketScenario | None = None,
) -> QueryResponse:
    from ccr_xva.agents.adk_agent import bind, try_model_answer, unbind

    tokens = bind(service, scenario, session_id)
    try:
        modeled = try_model_answer(query, session_id)
    finally:
        unbind(tokens)
    if modeled is not None:
        service.repo.add_message(session_id, "user", query)
        service.repo.add_message(session_id, "assistant", modeled.answer)
        return modeled
    service.repo.add_message(session_id, "user", query)
    graph = build_graph(service)
    state = graph.invoke(
        {
            "query": query,
            "session_id": session_id,
            "include_charts": include_charts,
            "requested_netting_set": netting_set_id,
            "scenario": None if scenario is None else scenario.model_dump(mode="json"),
        }
    )
    response = QueryResponse(
        answer=state.get("answer", ""),
        citations=state.get("citations", []),
        numeric_values=state.get("claims", []),
        calculation_id=state.get("calculation_id"),
        chart=state.get("chart"),
        refused=bool(state.get("refused")),
    )
    service.repo.add_message(session_id, "assistant", response.answer)
    params = state.get("params") or {}
    if params.get("netting_set_id") or params.get("counterparty_id"):
        service.repo.set_focus(session_id, params.get("netting_set_id"), params.get("counterparty_id"))
    return response


def _claim_model(item):
    from ccr_xva.models.schemas import NumericClaim

    if isinstance(item, NumericClaim):
        return item
    return NumericClaim.model_validate(item)


def _run_route(
    service: RiskService,
    route: str,
    params: dict,
    scenario: MarketScenario | None,
    query: str,
    session_id: str = "local",
) -> dict:
    if route == "memory":
        from ccr_xva.agents.specialists import memory_view

        counterparty_name = ""
        if params.get("counterparty_id"):
            party = service.repo.get_counterparty(params["counterparty_id"])
            counterparty_name = party.name if party else ""
        return memory_view(service, counterparty_name, session_id)
    if route == "rag":
        hits = service.ensure_corpus().search(query)
        return explain.retrieval_answer(hits)
    if route == "market":
        from ccr_xva.agents.market import market_answer

        return market_answer(query)

    netting_set_id = _select_netting_set(service, params)
    counterparty = None
    if params.get("counterparty_id"):
        counterparty = service.repo.get_counterparty(params["counterparty_id"])
    name = counterparty.name if counterparty else netting_set_id

    if route == "compare":
        if counterparty is None:
            raise ValueError("Name a counterparty to compare stored snapshots.")
        episodes = [item for item in service.repo.list_episodes(counterparty.id) if item.label == "exposure" and item.peak_pfe is not None]
        if len(episodes) < 2:
            return {
                "answer": f"Only one stored exposure snapshot is available for {counterparty.name}, so a comparison was not produced.",
                "claims": [],
                "citations": [],
                "calculation_id": None,
                "chart": None,
            }
        earlier, later = episodes[0], episodes[-1]
        return explain.compare_answer(
            counterparty.name,
            {"peak_pfe": earlier.peak_pfe, "as_of": earlier.as_of.isoformat(), "calculation_id": earlier.calculation_id},
            {"peak_pfe": later.peak_pfe, "as_of": later.as_of.isoformat(), "calculation_id": later.calculation_id},
        )
    if route == "top_pfe":
        return _top_pfe(service, scenario, int(params.get("limit", 5)))
    if route == "top_credit":
        return _top_credit(service, scenario, int(params.get("limit", 10)))
    if netting_set_id is None:
        raise ValueError("Name a counterparty or netting set.")
    params["netting_set_id"] = netting_set_id
    if route == "csa":
        from ccr_xva.agents.specialists import csa_view

        return csa_view(service, name, netting_set_id)
    if route == "cva":
        from ccr_xva.agents.specialists import cva_view

        return cva_view(service, name, netting_set_id, scenario)
    if route == "dva":
        from ccr_xva.agents.specialists import dva_view

        return dva_view(service, name, netting_set_id, scenario)
    if route == "fva":
        from ccr_xva.agents.specialists import fva_view

        return fva_view(service, name, netting_set_id, scenario)
    if route == "trends":
        from ccr_xva.agents.specialists import trend_view

        return trend_view(service, name, netting_set_id, scenario)
    if route == "what_if":
        result = service.what_if(
            netting_set_id,
            scenario,
            threshold=params.get("threshold"),
            threshold_delta=params.get("threshold_delta"),
            recovery=params.get("recovery"),
        )
        return explain.what_if_answer(result["base"], result["shocked"], name, result["threshold"])
    if route == "sensitivity":
        result = service.sensitivity(netting_set_id, scenario)
        return explain.sensitivity_answer(result["base"], result["shocked"], result["relative_vol_bump"], name)
    if route == "xva":
        result = service.calculate_xva(netting_set_id, scenario)
        return explain.xva_answer(result, name)
    profile = service.calculate_exposure(netting_set_id, scenario)
    return explain.exposure_answer(profile, name)


def _select_netting_set(service: RiskService, params: dict) -> str | None:
    if params.get("netting_set_id"):
        return params["netting_set_id"]
    if params.get("counterparty_id"):
        sets = service.netting_sets_for(params["counterparty_id"])
        return sets[0] if sets else None
    trades = service.repo.list_trades()
    sets = sorted({trade.netting_set_id for trade in trades})
    return sets[0] if len(sets) == 1 else None


def _top_pfe(service: RiskService, scenario: MarketScenario | None, limit: int) -> dict:
    rows = []
    skipped: list[str] = []
    for counterparty in service.repo.list_counterparties():
        for netting_set_id in service.netting_sets_for(counterparty.id):
            try:
                profile = service.calculate_exposure(netting_set_id, scenario, save_latest=True)
            except (ValueError, NotImplementedError):
                skipped.append(counterparty.name)
                continue
            rows.append(
                {
                    "name": counterparty.name,
                    "netting_set_id": netting_set_id,
                    "peak_pfe": max(profile.pfe_95),
                    "calculation_id": profile.calculation_id,
                    "driver": profile.drivers[0] if profile.drivers else None,
                }
            )
    if not rows:
        return _nothing_ranked()
    rows.sort(key=lambda item: item["peak_pfe"], reverse=True)
    rendered = explain.ranking_answer(rows[:limit])
    return _with_skipped(rendered, skipped, {row["name"] for row in rows})


def _top_credit(service: RiskService, scenario: MarketScenario | None, limit: int) -> dict:
    rows = []
    skipped: list[str] = []
    for counterparty in service.repo.list_counterparties():
        sets = service.netting_sets_for(counterparty.id)
        if not sets:
            skipped.append(counterparty.name)
        for netting_set_id in sets:
            try:
                profile = service.calculate_exposure(netting_set_id, scenario, save_latest=True)
                result = service.calculate_xva(netting_set_id, scenario, profile=profile, save_latest=True)
            except (ValueError, NotImplementedError):
                skipped.append(counterparty.name)
                continue
            rows.append(
                {
                    "name": counterparty.name,
                    "rating": counterparty.rating,
                    "netting_set_id": netting_set_id,
                    "cva": result.cva,
                    "peak_pfe": max(profile.pfe_95) if profile.pfe_95 else 0.0,
                    "calculation_id": result.calculation_id,
                }
            )
    if not rows:
        return _nothing_ranked()
    rows.sort(key=lambda item: item["cva"], reverse=True)
    rendered = explain.credit_ranking_answer(rows[:limit])
    return _with_skipped(rendered, skipped, {row["name"] for row in rows})


def _nothing_ranked() -> dict:
    answer = "No stored counterparty could be priced, so a credit ranking was not produced."
    return {"answer": answer, "claims": [], "citations": [], "calculation_id": None, "chart": None}


def _with_skipped(rendered: dict, skipped: list[str], priced: set[str]) -> dict:
    names = []
    for name in skipped:
        if name not in names and name not in priced and not re.search(r"\d", name):
            names.append(name)
    if names:
        rendered["answer"] += " Not ranked, because those trades cannot be priced: " + ", ".join(names) + "."
    return rendered
