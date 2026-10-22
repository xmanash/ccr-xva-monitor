from ccr_xva.agents.adk_agent import bind, build_agent, calculate_cva, graph_trends, peak_pfe, read_csa, unbind
from ccr_xva.agents.planner import plan_query
from ccr_xva.agents.runtime import AGENT_CATALOG, agent_for_route
from ccr_xva.agents.graph import run_query
from datetime import date

from ccr_xva.models.schemas import MarketScenario


def test_desk_has_calculation_specialists():
    names = {item["name"] for item in AGENT_CATALOG}
    assert {"desk", "methodology", "exposure", "cva", "dva", "fva", "csa", "trends", "xva", "memory"} <= names
    assert agent_for_route("rag") == "methodology"
    assert agent_for_route("what_if") == "xva"
    assert agent_for_route("compare") == "memory"
    agent = build_agent("gemini-2.5-flash")
    assert agent is not None
    assert {
        "methodology_agent",
        "exposure_agent",
        "cva_agent",
        "dva_agent",
        "fva_agent",
        "csa_agent",
        "trends_agent",
        "xva_agent",
        "memory_agent",
    } <= {child.name for child in agent.sub_agents}


def test_router_assigns_each_specialist(service):
    methodology = plan_query("What is the unilateral CVA formula?", service, "s")
    exposure = plan_query("Show the current peak PFE", service, "s")
    cva = plan_query("Calculate CVA", service, "s")
    dva = plan_query("Calculate DVA", service, "s")
    fva = plan_query("Calculate FVA", service, "s")
    csa = plan_query("Show the CSA", service, "s")
    trends = plan_query("Graph the exposure trend", service, "s")
    combined = plan_query("Calculate CVA DVA and FVA", service, "s")
    memory = plan_query("Recall the last calculation", service, "s")
    assert agent_for_route(methodology["route"]) == "methodology"
    assert agent_for_route(exposure["route"]) == "exposure"
    assert agent_for_route(cva["route"]) == "cva"
    assert agent_for_route(dva["route"]) == "dva"
    assert agent_for_route(fva["route"]) == "fva"
    assert agent_for_route(csa["route"]) == "csa"
    assert agent_for_route(trends["route"]) == "trends"
    assert agent_for_route(combined["route"]) == "xva"
    assert agent_for_route(memory["route"]) == "memory"


def test_exposure_agent_writes_a_trace(service):
    from ccr_xva.synthetic.portfolio import build_portfolio

    counterparties, trades, csas = build_portfolio(n_counterparties=1, as_of=date(2026, 10, 5), seed=3)
    for counterparty in counterparties:
        service.store_counterparty(counterparty)
    for trade in trades:
        service.store_trade(trade)
    for csa in csas:
        service.store_csa(csa)
    tokens = bind(service, MarketScenario(as_of=date(2026, 10, 5), n_paths=20, seed=3), "desk-test")
    try:
        priced = peak_pfe("ABC Bank")
    finally:
        unbind(tokens)
    assert priced["agent"] == "exposure"
    kinds = [trace.kind for trace in service.repo.list_traces()]
    assert "agent:exposure" in kinds

    recalled = run_query(service, "Recall the last calculation for ABC Bank", session_id="desk-test")
    assert recalled.calculation_id
    assert "ABC Bank" in recalled.answer
    assert any(trace.kind == "agent:memory" for trace in service.repo.list_traces())
    tokens = bind(service, MarketScenario(as_of=date(2026, 10, 5), n_paths=20, seed=3), "desk-test")
    try:
        cva = calculate_cva("ABC Bank")
        csa = read_csa("ABC Bank")
        chart = graph_trends("ABC Bank")
    finally:
        unbind(tokens)
    assert cva["agent"] == "cva" and "CVA" in cva["answer"]
    assert csa["agent"] == "csa" and "Threshold" in csa["answer"]
    assert chart["agent"] == "trends"
    assert chart["answer"]
