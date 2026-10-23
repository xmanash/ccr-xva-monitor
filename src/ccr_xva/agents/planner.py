"""Rule planner. The language model does not choose the numbers or the tool inputs."""

from __future__ import annotations

import re

from ccr_xva.agents.market import is_market_query
from ccr_xva.guardrails.policy import check_query
from ccr_xva.services.risk import RiskService

_AMOUNT = re.compile(
    r"threshold by\s+\$?\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|million|bn|mm|m|k)?",
    re.IGNORECASE,
)
_ABSOLUTE_THRESHOLD = re.compile(
    r"threshold to\s+\$?\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|million|bn|mm|m|k)?",
    re.IGNORECASE,
)
_RECOVERY = re.compile(r"recovery(?:\s+rate)?\s+to\s+([0-9]+(?:\.[0-9]+)?)\s*(%|percent)?", re.IGNORECASE)
_TOP_N = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)


def plan_query(query: str, service: RiskService, session_id: str, netting_set_id: str | None = None) -> dict:
    refusal = check_query(query)
    if refusal:
        return {"route": "refuse", "reason": refusal, "params": {}}
    text = query.lower()
    focus_netting, focus_counterparty = service.repo.get_focus(session_id)
    chosen_netting = netting_set_id or focus_netting
    counterparty = service.find_counterparty(query)
    if counterparty is None and focus_counterparty:
        counterparty = service.repo.get_counterparty(focus_counterparty)
    params: dict = {"counterparty_id": None if counterparty is None else counterparty.id, "netting_set_id": chosen_netting}

    if any(phrase in text for phrase in ("recall", "what did we", "session memory", "previous calculation", "last calculation")):
        return {"route": "memory", "params": params}
    if is_book_ranking(query):
        params["limit"] = _ranking_limit(query)
        credit = any(word in text for word in ("credit", "cva", "risky", "riskiest"))
        exposure = "pfe" in text or "exposure" in text
        return {"route": "top_pfe" if exposure and not credit else "top_credit", "params": params}
    if is_market_query(query):
        return {"route": "market", "params": params}
    definitional = bool(re.search(r"\b(what is|define|formula|methodology)\b", text))
    wants_book_number = bool(re.search(r"\b(current|peak|show|calculate|compute|counterparty|netting)\b", text))
    explicit_shock = bool(re.search(r"\b(what if|what-if|what happens|increase|decrease)\b", text))
    if definitional and not wants_book_number and not explicit_shock:
        return {"route": "rag", "params": params}
    if any(word in text for word in ("last week", "compare", "versus yesterday", "vs last")):
        return {"route": "compare", "params": params}
    if any(word in text for word in ("what if", "what-if", "what happens", "increase collateral", "threshold", "recovery rate")) and any(
        word in text for word in ("cva", "xva", "exposure", "pfe", "threshold", "recovery")
    ):
        params.update(_shock_params(query))
        return {"route": "what_if", "params": params}
    if any(word in text for word in ("sensitiv", "volatility")) and "cva" in text:
        return {"route": "sensitivity", "params": params}
    if any(word in text for word in ("chart", "graph", "trend", "plot")):
        return {"route": "trends", "params": params}
    if any(phrase in text for phrase in ("csa", "collateral agreement", "margin terms")):
        return {"route": "csa", "params": params}
    mentioned = [name for name in ("cva", "dva", "fva", "xva") if name in text]
    if len(mentioned) == 1 and mentioned[0] != "xva":
        return {"route": mentioned[0], "params": params}
    if mentioned:
        return {"route": "xva", "params": params}
    if any(word in text for word in ("pfe", "expected exposure", "epe", "exposure")):
        return {"route": "exposure", "params": params}
    return {"route": "rag", "params": params}


def is_book_ranking(query: str) -> bool:
    text = query.lower()
    if "top" in text and "pfe" in text:
        return True
    if "counterpart" not in text:
        return False
    return any(word in text for word in ("risk", "risky", "riskiest", "credit", "cva", "pfe", "exposure"))


def _ranking_limit(query: str) -> int:
    match = _TOP_N.search(query)
    if not match:
        return 5
    return max(1, min(int(match.group(1)), 25))


def _shock_params(query: str) -> dict:
    params: dict = {}
    delta = _AMOUNT.search(query)
    absolute = _ABSOLUTE_THRESHOLD.search(query)
    recovery = _RECOVERY.search(query)
    if delta:
        params["threshold_delta"] = _scaled(delta.group(1), delta.group(2))
    if absolute:
        params["threshold"] = _scaled(absolute.group(1), absolute.group(2))
    if recovery:
        value = float(recovery.group(1))
        if recovery.group(2) or value > 1:
            value = value / 100.0
        params["recovery"] = value
    return params


def _scaled(number: str, suffix: str | None) -> float:
    value = float(number)
    factors = {"k": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
    if suffix:
        value *= factors[suffix.lower()]
    return value
