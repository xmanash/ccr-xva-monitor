from ccr_xva.agents.adk_agent import bind, peak_pfe, search_methodology, unbind
from ccr_xva.rag.retriever import build_retriever


def test_cva_question_hits_the_cva_section():
    hits = build_retriever(chroma_path=None).search("What is the unilateral CVA formula?", k=1)
    assert hits
    assert hits[0]["title"] == "Unilateral CVA"


def test_adk_tools_retrieve_and_price(service):
    from datetime import date

    from ccr_xva.models.schemas import MarketScenario
    from ccr_xva.synthetic.portfolio import build_portfolio

    counterparties, trades, csas = build_portfolio(n_counterparties=1, as_of=date(2026, 10, 5), seed=3)
    for counterparty in counterparties:
        service.store_counterparty(counterparty)
    for trade in trades:
        service.store_trade(trade)
    for csa in csas:
        service.store_csa(csa)
    tokens = bind(service, MarketScenario(as_of=date(2026, 10, 5), n_paths=20, seed=3))
    try:
        note = search_methodology("What is the unilateral CVA formula?")
        assert "section Unilateral CVA" in note["answer"]
        assert "recovery" in note["answer"].lower()
        priced = peak_pfe("ABC Bank")
        assert "ABC Bank" in priced["answer"]
        assert priced["calculation_id"]
    finally:
        unbind(tokens)
