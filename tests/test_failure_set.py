"""Route schema and forbidden handoffs for the fixed eight-question set."""

from ccr_xva.agents.adk_agent import DESK_INSTRUCTION
from ccr_xva.agents.planner import plan_query
from ccr_xva.agents.runtime import AGENT_CATALOG, agent_for_route
from ccr_xva.evals.failures import FAILURE_SET, failure_report, load_baseline, score_failures

FORBIDDEN_HANDOFF = {"what_if", "compare", "refuse"}


def test_route_schema(service):
    catalog = {item["name"] for item in AGENT_CATALOG}
    assert len(FAILURE_SET) == 8
    for case in FAILURE_SET:
        decision = plan_query(case["query"], service, "failure-set")
        owner = agent_for_route(decision["route"])
        assert decision["route"] == case["expected_route"]
        assert owner == case["expected_owner"]
        assert case["expected_owner"] in catalog
        assert owner in catalog


def test_forbidden_handoff(service):
    for case in FAILURE_SET:
        decision = plan_query(case["query"], service, "failure-set")
        route = decision["route"]
        owner = agent_for_route(route)
        if case["category"] == "definitional":
            assert route == "rag"
            assert owner == "methodology"
            assert route not in FORBIDDEN_HANDOFF
        elif case["category"] == "shock":
            assert route == "what_if"
            assert owner == "xva"
        elif case["category"] == "snapshot":
            assert route == "memory"
            assert owner == "memory"


def test_misroutes_are_fewer_than_the_committed_baseline(service):
    baseline = load_baseline()
    assert baseline["misroute_count"] == 3
    assert baseline["handoff_accuracy"] == 0.625
    scored = score_failures(service)
    assert scored["misroute_count"] < baseline["misroute_count"]
    assert scored["handoff_accuracy"] > baseline["handoff_accuracy"]
    assert scored["misroute_count"] == 0
    assert scored["handoff_accuracy"] == 1.0
    report = failure_report(service)
    assert report["baseline_misroute_count"] == 3
    assert report["baseline_handoff_accuracy"] == 0.625
    assert report["false_refusal_count"] == 1
    assert report["snapshot_drift_count"] == 1
    assert {item["name"] for item in report["taxonomy"]} == {
        "wrong_specialist_handoff",
        "false_policy_refusal",
        "ungrounded_number_withheld",
        "resimulated_snapshot_drift",
    }


def test_desk_instruction_keeps_definitions_on_methodology():
    assert "methodology_agent" in DESK_INSTRUCTION
    assert "even when it mentions a threshold, a recovery rate, or compare" in DESK_INSTRUCTION
