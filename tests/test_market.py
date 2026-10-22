from datetime import date

from ccr_xva.agents.adk_agent import try_model_answer
from ccr_xva.agents.graph import run_query
from ccr_xva.models.schemas import MarketScenario
from ccr_xva.synthetic.portfolio import build_portfolio
from ccr_xva.agents.market import is_market_query, market_answer, symbols_for
from ccr_xva.agents.planner import plan_query
from ccr_xva.guardrails.grounding import ungrounded_numbers


def test_risky_counterparties_are_a_credit_ranking_not_a_quote(service):
    decision = plan_query("Top 10 risky counterparties from the market", service, "s")
    assert decision["route"] == "top_credit"
    assert decision["params"]["limit"] == 10
    assert plan_query("top 5 counterparties by PFE", service, "s")["route"] == "top_pfe"
    assert not is_market_query("Top 10 risky counterparties from the market")
    assert try_model_answer("Top 10 risky counterparties from the market", "s") is None


def test_credit_ranking_quotes_engine_cva(service):
    counterparties, trades, csas = build_portfolio(n_counterparties=3, as_of=date(2026, 10, 5), seed=7)
    for counterparty in counterparties:
        service.store_counterparty(counterparty)
    for trade in trades:
        service.store_trade(trade)
    for csa in csas:
        service.store_csa(csa)
    response = run_query(
        service,
        "Top 10 risky counterparties from the market",
        scenario=MarketScenario(as_of=date(2026, 10, 5), n_paths=20, seed=7),
    )
    assert response.answer.startswith("Ranked by unilateral CVA")
    assert "ABC Bank" in response.answer
    assert ungrounded_numbers(response.answer, response.numeric_values) == []


def test_us_and_european_index_question_selects_both_boards():
    symbols = symbols_for("live market index US and European")
    assert symbols[:3] == ["^GSPC", "^DJI", "^IXIC"]
    assert symbols[3:] == ["^STOXX50E", "^GDAXI", "^FCHI", "^FTSE"]
    assert is_market_query("live market index US and European")
    assert symbols_for("European indexes") == ["^STOXX50E", "^GDAXI", "^FCHI", "^FTSE"]
    assert symbols_for("How is the market today?") == ["^GSPC", "^DJI", "^IXIC"]


def test_market_questions_are_not_risk_questions(service):
    assert plan_query("How is the market today?", service, "s")["route"] == "market"
    assert plan_query("Quote AAPL", service, "s")["route"] == "market"
    assert plan_query("What is the unilateral CVA formula?", service, "s")["route"] == "rag"
    assert plan_query("Calculate CVA", service, "s")["route"] == "cva"
    assert is_market_query("How is the market today?")
    assert not is_market_query("What is the peak PFE?")
    assert try_model_answer("How is the market today?", "s") is None


def test_market_answer_quotes_only_the_feed(monkeypatch):
    def fake_get(url: str, params: dict) -> dict:
        symbol = url.rsplit("/", 1)[-1]
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "shortName": "Example",
                            "fullExchangeName": "NasdaqGS",
                            "currency": "USD",
                            "regularMarketPrice": 100.126,
                            "regularMarketChange": -1.2,
                            "regularMarketChangePercent": 1.189,
                            "regularMarketTime": 1792681859,
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr("ccr_xva.agents.market._get", fake_get)
    rendered = market_answer("Quote AAPL")
    assert "100.13 USD" in rendered["answer"]
    assert "-1.20 USD" in rendered["answer"]
    assert "1.19 percent" in rendered["answer"]
    assert ungrounded_numbers(rendered["answer"], rendered["claims"]) == []
    assert rendered["citations"][0].source_id == "yahoo:AAPL"


def test_missing_quote_does_not_invent_a_price(monkeypatch):
    monkeypatch.setattr("ccr_xva.agents.market._get", lambda url, params: {"chart": {"result": None}})
    rendered = market_answer("Quote AAPL")
    assert rendered["claims"] == []
    assert ungrounded_numbers(rendered["answer"], []) == []
