"""Specialist tools. Each one calls an engine, the RAG index, or stored memory."""

from __future__ import annotations

from ccr_xva.agents import explain
from ccr_xva.agents.runtime import (
    current_scenario,
    current_service,
    current_session,
    record_agent_step,
    remember,
)
from ccr_xva.services.risk import RiskService


def search_methodology(query: str) -> dict:
    """Retrieve methodology notes or counterparty briefs. Does not calculate exposure or XVA."""
    service = current_service()
    hits = service.ensure_corpus().search(query, k=4)
    rendered = explain.retrieval_answer(hits)
    return _finish("methodology", query, rendered, service)


def peak_pfe(counterparty: str) -> dict:
    """Return peak PFE95 and the largest standalone risk driver for a counterparty."""
    service = current_service()
    party = service.find_counterparty(counterparty)
    if party is None:
        return {"error": "No stored counterparty matches that name."}
    netting_sets = service.netting_sets_for(party.id)
    if not netting_sets:
        return {"error": "No trades are stored for that counterparty."}
    profile = service.calculate_exposure(netting_sets[0], current_scenario())
    rendered = explain.exposure_answer(profile, party.name)
    return _finish("exposure", counterparty, rendered, service)


def calculate_cva(counterparty: str) -> dict:
    """Return unilateral CVA for a counterparty. DVA and FVA are computed by their own agents."""
    return _xva_component(counterparty, "cva")


def calculate_dva(counterparty: str) -> dict:
    """Return DVA for a counterparty from the same unilateral XVA engine."""
    return _xva_component(counterparty, "dva")


def calculate_fva(counterparty: str) -> dict:
    """Return the teaching FVA for a counterparty from the same unilateral XVA engine."""
    return _xva_component(counterparty, "fva")


def read_csa(counterparty: str) -> dict:
    """Return the stored CSA threshold, minimum transfer amount, and independent amount."""
    service, party, netting_set_id = _party(counterparty)
    if isinstance(party, dict):
        return party
    csa = service.repo.get_csa(netting_set_id)
    rendered = explain.csa_answer(csa, party.name)
    return _finish("csa", counterparty, rendered, service)


def graph_trends(counterparty: str) -> dict:
    """Plot EE, PFE95, and PFE99 for a counterparty. The series comes from the exposure engine."""
    service, party, netting_set_id = _party(counterparty)
    if isinstance(party, dict):
        return party
    profile = service.calculate_exposure(netting_set_id, current_scenario())
    rendered = explain.trend_answer(profile, party.name)
    return _finish("trends", counterparty, rendered, service)


def cva_view(service: RiskService, name: str, netting_set_id: str, scenario) -> dict:
    return explain.component_answer(service.calculate_xva(netting_set_id, scenario), name, "cva")


def dva_view(service: RiskService, name: str, netting_set_id: str, scenario) -> dict:
    return explain.component_answer(service.calculate_xva(netting_set_id, scenario), name, "dva")


def fva_view(service: RiskService, name: str, netting_set_id: str, scenario) -> dict:
    return explain.component_answer(service.calculate_xva(netting_set_id, scenario), name, "fva")


def csa_view(service: RiskService, name: str, netting_set_id: str) -> dict:
    return explain.csa_answer(service.repo.get_csa(netting_set_id), name)


def trend_view(service: RiskService, name: str, netting_set_id: str, scenario) -> dict:
    return explain.trend_answer(service.calculate_exposure(netting_set_id, scenario), name)


def approximate_xva(counterparty: str) -> dict:
    """Return approximate unilateral CVA, DVA, and FVA for a counterparty."""
    service = current_service()
    party = service.find_counterparty(counterparty)
    if party is None:
        return {"error": "No stored counterparty matches that name."}
    netting_sets = service.netting_sets_for(party.id)
    if not netting_sets:
        return {"error": "No trades are stored for that counterparty."}
    result = service.calculate_xva(netting_sets[0], current_scenario())
    rendered = explain.xva_answer(result, party.name)
    return _finish("xva", counterparty, rendered, service)


def what_if_cva(counterparty: str, threshold_delta: float = 0.0, recovery: float | None = None) -> dict:
    """Recompute CVA after a collateral-threshold change or a new recovery rate."""
    service = current_service()
    party = service.find_counterparty(counterparty)
    if party is None:
        return {"error": "No stored counterparty matches that name."}
    netting_sets = service.netting_sets_for(party.id)
    if not netting_sets:
        return {"error": "No trades are stored for that counterparty."}
    outcome = service.what_if(
        netting_sets[0],
        current_scenario(),
        threshold_delta=threshold_delta or None,
        recovery=recovery,
    )
    rendered = explain.what_if_answer(outcome["base"], outcome["shocked"], party.name, outcome["threshold"])
    return _finish("xva", counterparty, rendered, service)


def recall_memory(counterparty: str = "") -> dict:
    """Read stored exposure and XVA snapshots for a counterparty. Does not run a new valuation."""
    service = current_service()
    rendered = memory_view(service, counterparty, current_session())
    return _finish("memory", counterparty or "book", rendered, service)


def _xva_component(counterparty: str, component: str) -> dict:
    service, party, netting_set_id = _party(counterparty)
    if isinstance(party, dict):
        return party
    result = service.calculate_xva(netting_set_id, current_scenario())
    rendered = explain.component_answer(result, party.name, component)
    return _finish(component, counterparty, rendered, service)


def _party(counterparty: str):
    service = current_service()
    party = service.find_counterparty(counterparty)
    if party is None:
        return service, {"error": "No stored counterparty matches that name."}, None
    netting_sets = service.netting_sets_for(party.id)
    if not netting_sets:
        return service, {"error": "No trades are stored for that counterparty."}, None
    return service, party, netting_sets[0]


def memory_view(service: RiskService, counterparty: str, session_id: str) -> dict:
    party = service.find_counterparty(counterparty) if counterparty else None
    label = party.name if party is not None else (counterparty or "the book")
    episodes = service.repo.list_episodes(None if party is None else party.id)
    service.repo.recent_messages(session_id, limit=6)
    return explain.memory_answer(label, episodes)


def _finish(agent: str, query: str, rendered: dict, service: RiskService) -> dict:
    remember(rendered)
    record_agent_step(service, agent, query, rendered, current_session())
    return {
        "answer": rendered["answer"],
        "calculation_id": rendered.get("calculation_id"),
        "citations": [_dump(item) for item in rendered.get("citations", [])],
        "numeric_values": [_dump(item) for item in rendered.get("claims", [])],
        "agent": agent,
    }


def _dump(item):
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return item
