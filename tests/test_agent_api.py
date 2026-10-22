from datetime import date

from fastapi.testclient import TestClient

from ccr_xva.agents.graph import run_query
from ccr_xva.api.main import create_app
from ccr_xva.evals.suite import run_suite
from ccr_xva.guardrails.grounding import ungrounded_numbers
from ccr_xva.models.schemas import MarketScenario, NumericClaim
from ccr_xva.synthetic.portfolio import build_portfolio
from shared.settings import get_settings


def _load(service, n_paths=40):
    counterparties, trades, csas = build_portfolio(n_counterparties=2, as_of=date(2026, 10, 5), seed=4)
    for counterparty in counterparties:
        service.store_counterparty(counterparty)
    for trade in trades:
        service.store_trade(trade)
    for csa in csas:
        service.store_csa(csa)
    return MarketScenario(as_of=date(2026, 10, 5), n_paths=n_paths, seed=4)


def test_peak_pfe_answer_is_grounded(service):
    scenario = _load(service)
    response = run_query(
        service,
        "What is the current peak PFE for ABC Bank and the main risk drivers?",
        scenario=scenario,
    )
    assert response.refused is False
    assert response.calculation_id
    trace = service.repo.get_trace(response.calculation_id)
    assert trace is not None
    assert trace.kind == "exposure"
    claims = [NumericClaim.model_validate(item) for item in response.numeric_values]
    assert ungrounded_numbers(response.answer, claims) == []
    assert "ABC Bank" in response.answer


def test_what_if_and_definition_and_refusal(service):
    scenario = _load(service)
    shocked = run_query(
        service,
        "What happens to CVA if we increase collateral threshold by $5m or change recovery rate to 40%?",
        scenario=scenario,
        netting_set_id="NS1",
    )
    assert shocked.refused is False
    assert "Shocked CVA" in shocked.answer
    claims = [NumericClaim.model_validate(item) for item in shocked.numeric_values]
    assert ungrounded_numbers(shocked.answer, claims) == []

    formula = run_query(service, "What is the unilateral CVA formula?", scenario=scenario)
    assert formula.calculation_id is None
    assert "recovery" in formula.answer.lower()

    refused = run_query(service, "Please increase the exposure limit.", scenario=scenario)
    assert refused.refused is True
    assert refused.numeric_values == []


def test_upload_accepts_pay_fixed_direction(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,product_type,notional,currency,start_date,maturity,"
        "fixed_rate,direction,netting_set_id\n"
        "IRS-FIXED,CP-FIXED,IRS,1000000,USD,2026-10-05,2031-10-05,0.04,pay_fixed,NS-FIXED\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    stored = {trade.trade_id: trade.direction for trade in service.repo.list_trades()}
    assert stored["IRS-FIXED"] == "Pay"


def test_upload_accepts_ccs_and_calculation_explains_it(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,product_type,notional,currency,start_date,maturity,"
        "fixed_rate,direction,netting_set_id\n"
        "CCS-1,CP-CCS,CCS,1000000,USD,2026-10-05,2031-10-05,0.04,pay_fixed,NS-CCS\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    stored = {trade.trade_id: trade.product_type for trade in service.repo.list_trades()}
    assert stored["CCS-1"] == "CCS"
    exposure = client.post(
        "/api/v1/calculate/exposure",
        json={"netting_set_id": "NS-CCS", "scenario": {"as_of": "2026-10-05", "n_paths": 10, "seed": 1}},
    )
    assert exposure.status_code == 400
    assert "CCS" in exposure.json()["detail"]


def test_upload_accepts_fx_option(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,product_type,notional,currency,start_date,maturity,"
        "strike,direction,netting_set_id,underlying\n"
        "T1005,CP-OPT,FX_Option,1000000,USD,2026-10-05,2027-10-05,1.10,Buy,NS-OPT,EURUSD\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    stored = {trade.trade_id: trade.product_type for trade in service.repo.list_trades()}
    assert stored["T1005"] == "FX_Option"


def test_upload_keeps_unpriced_product_labels(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,product_type,notional,currency,start_date,maturity,"
        "direction,netting_set_id\n"
        "T1006,CP-EQ,Equity_Option,1000000,USD,2026-10-05,2027-10-05,Buy,NS-EQ\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    stored = {trade.trade_id: trade.product_type for trade in service.repo.list_trades()}
    assert stored["T1006"] == "Equity_Option"


def test_upload_accepts_us_dates(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,product_type,notional,currency,start_date,maturity,"
        "direction,netting_set_id\n"
        "T-DATE,CP-DATE,IRS,1000000,USD,3/15/2023,3/15/2028,pay_fixed,NS-DATE\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200, uploaded.text
    stored = {trade.trade_id: trade for trade in service.repo.list_trades()}
    assert stored["T-DATE"].start_date.isoformat() == "2023-03-15"
    assert stored["T-DATE"].maturity.isoformat() == "2028-03-15"


def test_api_upload_calculate_and_trace(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    csv_text = (
        "trade_id,counterparty_id,counterparty_name,product_type,notional,currency,start_date,maturity,"
        "fixed_rate,strike,direction,netting_set_id,collateralized,underlying,pd,recovery_rate\n"
        "IRS-9,CP9,ABC Bank,IRS,10000000,USD,2026-10-05,2031-10-05,0.05,,Pay,NS9,true,USD-SWAP,0.01,0.4\n"
    )
    uploaded = client.post("/api/v1/trades/upload", files={"file": ("trades.csv", csv_text, "text/csv")})
    assert uploaded.status_code == 200
    created = client.post(
        "/api/v1/csas",
        json={"text": "daily cash collateral, 0 threshold, 10% MTA", "csa_id": "CSA9", "netting_set_id": "NS9", "notional": 10_000_000},
    )
    assert created.status_code == 200
    assert created.json()["mta"] == 1_000_000
    exposure = client.post(
        "/api/v1/calculate/exposure",
        json={"netting_set_id": "NS9", "scenario": {"as_of": "2026-10-05", "n_paths": 30, "seed": 1}},
    )
    assert exposure.status_code == 200
    calculation_id = exposure.json()["profile"]["calculation_id"]
    trace = client.get(f"/api/v1/traces/{calculation_id}")
    assert trace.status_code == 200
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"


def test_exposure_requires_trades_and_sample_book_loads(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    missing = client.post(
        "/api/v1/calculate/exposure",
        json={"netting_set_id": "NS1", "scenario": {"as_of": "2026-10-05", "n_paths": 20, "seed": 1}},
    )
    assert missing.status_code == 400
    assert "No trades are stored for netting set NS1" in missing.json()["detail"]
    loaded = client.post("/api/v1/sample")
    assert loaded.status_code == 200
    assert "NS1" in loaded.json()["netting_sets"]
    exposure = client.post(
        "/api/v1/calculate/exposure",
        json={"netting_set_id": "NS1", "scenario": {"as_of": "2026-10-05", "n_paths": 20, "seed": 1}},
    )
    assert exposure.status_code == 200
    assert exposure.json()["profile"]["netting_set_id"] == "NS1"
    asked = client.post(
        "/api/v1/query",
        json={
            "query": "What is the current peak PFE for ABC bank and risk driver",
            "session_id": "test",
            "include_charts": True,
            "as_of": "2026-10-05",
            "n_paths": 20,
        },
    )
    assert asked.status_code == 200
    body = asked.json()
    assert "ABC Bank" in body["answer"]
    assert body["calculation_id"]


def test_mcp_ask_risk_returns_peak_pfe(service, monkeypatch):
    _ = service
    monkeypatch.setenv("CCR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    from ccr_xva.mcp.tools import ask_risk, load_sample_book

    assert "NS1" in load_sample_book()["netting_sets"]
    answer = ask_risk("What is the current peak PFE for ABC bank and risk driver", n_paths=20)
    assert answer["refused"] is False
    assert "ABC Bank" in answer["answer"]
    assert answer["calculation_id"]


def test_short_eval_suite_passes():
    report = run_suite()
    assert report["passed"], report
