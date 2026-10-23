"""Fixed handoff questions. The scorer checks the planner, not a language model.

Eight questions: definitional notes that must reach methodology, plus shock,
snapshot, and book-number controls that must stay on their current owners.
False policy refusal and resimulated snapshot drift stay open and are not a pass.
"""

from __future__ import annotations

import json
from pathlib import Path

from ccr_xva.agents.planner import plan_query
from ccr_xva.agents.runtime import AGENT_CATALOG, agent_for_route
from ccr_xva.services.risk import RiskService

BASELINE_PATH = Path(__file__).with_name("baseline.json")

TAXONOMY = [
    {
        "name": "wrong_specialist_handoff",
        "label": "Wrong specialist handoff",
        "status": "scored",
    },
    {
        "name": "false_policy_refusal",
        "label": "False policy refusal",
        "status": "open",
    },
    {
        "name": "ungrounded_number_withheld",
        "label": "Ungrounded number withheld",
        "status": "covered",
    },
    {
        "name": "resimulated_snapshot_drift",
        "label": "Resimulated snapshot drift",
        "status": "open",
    },
]

# Known open issues. The eight questions do not score them.
OPEN_FALSE_REFUSAL_COUNT = 1
OPEN_SNAPSHOT_DRIFT_COUNT = 1

FAILURE_SET = [
    {
        "query": "What is the collateral threshold in the methodology?",
        "expected_route": "rag",
        "expected_owner": "methodology",
        "category": "definitional",
    },
    {
        "query": "Define the recovery rate assumption.",
        "expected_route": "rag",
        "expected_owner": "methodology",
        "category": "definitional",
    },
    {
        "query": "Compare the unilateral CVA and DVA formulas in the methodology.",
        "expected_route": "rag",
        "expected_owner": "methodology",
        "category": "definitional",
    },
    {
        "query": "What is the unilateral CVA formula?",
        "expected_route": "rag",
        "expected_owner": "methodology",
        "category": "definitional",
    },
    {
        "query": "What is the current peak PFE for ABC Bank?",
        "expected_route": "exposure",
        "expected_owner": "exposure",
        "category": "book_number",
    },
    {
        "query": "What happens to CVA if we increase the collateral threshold?",
        "expected_route": "what_if",
        "expected_owner": "xva",
        "category": "shock",
    },
    {
        "query": "What if we decrease the recovery rate, what is the new CVA?",
        "expected_route": "what_if",
        "expected_owner": "xva",
        "category": "shock",
    },
    {
        "query": "Recall the last calculation for ABC Bank",
        "expected_route": "memory",
        "expected_owner": "memory",
        "category": "snapshot",
    },
]


def score_failures(service: RiskService, session_id: str = "failure-set") -> dict:
    """Score planner handoffs. Owners come from the route catalog."""
    catalog = {item["name"] for item in AGENT_CATALOG}
    cases = []
    misroutes = 0
    for case in FAILURE_SET:
        decision = plan_query(case["query"], service, session_id)
        route = decision["route"]
        owner = agent_for_route(route)
        misrouted = route != case["expected_route"] or owner != case["expected_owner"] or owner not in catalog
        if misrouted:
            misroutes += 1
        cases.append(
            {
                "query": case["query"],
                "expected_route": case["expected_route"],
                "expected_owner": case["expected_owner"],
                "route": route,
                "owner": owner,
                "category": case["category"],
                "misrouted": misrouted,
            }
        )
    total = len(FAILURE_SET)
    return {
        "cases": cases,
        "misroute_count": misroutes,
        "handoff_accuracy": (total - misroutes) / total,
        "false_refusal_count": OPEN_FALSE_REFUSAL_COUNT,
        "snapshot_drift_count": OPEN_SNAPSHOT_DRIFT_COUNT,
        "taxonomy": TAXONOMY,
    }


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def failure_report(service: RiskService, session_id: str = "failure-set") -> dict:
    """Live score plus the committed baseline, for the eval endpoint and the Check page."""
    scored = score_failures(service, session_id)
    baseline = load_baseline()
    scored["baseline_misroute_count"] = baseline["misroute_count"]
    scored["baseline_handoff_accuracy"] = baseline["handoff_accuracy"]
    return scored
