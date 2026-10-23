"""HTTP API for books, calculations, grounded queries, and traces."""

from __future__ import annotations

import io
import json
from datetime import date, datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ccr_xva.agents.graph import run_query
from ccr_xva.evals.failures import failure_report
from ccr_xva.evals.suite import run_suite
from ccr_xva.guardrails.csa_parser import parse_csa_text
from ccr_xva.memory.repository import get_repository
from ccr_xva.models.schemas import CSA, Counterparty, MarketScenario, QueryRequest, QueryResponse, Trade
from ccr_xva.services.risk import RiskService, exposure_chart
from shared.settings import get_settings

router = APIRouter()


class CSACreate(BaseModel):
    csa: CSA | None = None
    text: str | None = None
    csa_id: str | None = None
    netting_set_id: str | None = None
    notional: float | None = None
    currency: str = "USD"


class CalculateRequest(BaseModel):
    netting_set_id: str
    scenario: MarketScenario | None = None
    threshold_override: float | None = None
    recovery_override: float | None = None
    save_latest: bool = True


def get_service() -> RiskService:
    settings = get_settings()
    return RiskService(get_repository(settings.database_url), settings)


@router.get("/health")
def health(service: RiskService = Depends(get_service)) -> dict:
    from ccr_xva.agents.llm import llm_status

    try:
        service.repo.list_counterparties()
        database = "ok"
    except Exception as exc:
        database = f"error: {exc}"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "llm": llm_status(service.settings),
        "engine": "quantlib+numpy",
        "embeddings": "pinecone" if (service.settings.pinecone_api_key or "").strip() else "local-hash",
    }


@router.post("/counterparties")
def upsert_counterparty(counterparty: Counterparty, service: RiskService = Depends(get_service)) -> Counterparty:
    return service.store_counterparty(counterparty)


@router.post("/trades/upload")
async def upload_trades(file: UploadFile = File(...), service: RiskService = Depends(get_service)) -> dict:
    raw = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".json"):
        payload = json.loads(raw.decode("utf-8"))
        counterparties = [Counterparty.model_validate(item) for item in payload.get("counterparties", [])]
        raw_trades = payload.get("trades", payload if isinstance(payload, list) else [])
        trades = [_trade_from_mapping(item) for item in raw_trades]
    else:
        frame = pd.read_csv(io.BytesIO(raw))
        counterparties, trades = _from_frame(frame)
    for counterparty in counterparties:
        service.store_counterparty(counterparty)
    for trade in trades:
        service.store_trade(trade)
    netting_sets = sorted({trade.netting_set_id for trade in trades})
    return {"trades": len(trades), "counterparties": len(counterparties), "netting_sets": netting_sets}


@router.post("/sample")
def load_sample(service: RiskService = Depends(get_service)) -> dict:
    """Load the synthetic IRS and FX book. An existing CSA on a netting set is left in place."""
    return service.load_sample_book()


@router.post("/csas")
def create_csa(body: CSACreate, service: RiskService = Depends(get_service)) -> CSA:
    if body.csa is not None:
        return service.store_csa(body.csa)
    if not body.text or not body.csa_id or not body.netting_set_id:
        raise HTTPException(status_code=400, detail="Provide a CSA object or text plus csa_id and netting_set_id")
    parsed = parse_csa_text(body.text, body.csa_id, body.netting_set_id, body.notional, body.currency)
    return service.store_csa(parsed)


@router.post("/calculate/exposure")
def calculate_exposure(body: CalculateRequest, service: RiskService = Depends(get_service)) -> dict:
    try:
        profile = service.calculate_exposure(
            body.netting_set_id,
            body.scenario or MarketScenario(as_of=date.today()),
            csa_override=_threshold_override(service, body),
            save_latest=body.save_latest,
            label="exposure" if body.save_latest else "what-if",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"profile": profile, "chart": exposure_chart(profile)}


@router.post("/calculate/xva")
def calculate_xva(body: CalculateRequest, service: RiskService = Depends(get_service)) -> dict:
    try:
        result = service.calculate_xva(
            body.netting_set_id,
            body.scenario or MarketScenario(as_of=date.today()),
            recovery=body.recovery_override,
            save_latest=body.save_latest,
            csa_override=_threshold_override(service, body),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"xva": result}


@router.post("/query")
def query(body: QueryRequest, service: RiskService = Depends(get_service)) -> QueryResponse:
    scenario = MarketScenario(as_of=body.as_of or date.today(), n_paths=body.n_paths or 200)
    response = run_query(
        service,
        body.query,
        session_id=body.session_id,
        include_charts=body.include_charts,
        netting_set_id=body.netting_set_id,
        scenario=scenario,
    )
    return response


@router.get("/exposures/{netting_set_id}")
def get_exposure(netting_set_id: str, service: RiskService = Depends(get_service)) -> dict:
    profile = service.repo.latest_exposure(netting_set_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No exposure stored for that netting set")
    return {"profile": profile, "chart": exposure_chart(profile)}


@router.get("/xva/{netting_set_id}")
def get_xva(netting_set_id: str, service: RiskService = Depends(get_service)) -> dict:
    result = service.repo.latest_xva(netting_set_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No XVA stored for that netting set")
    return {"xva": result}


@router.get("/memory/counterparties/{counterparty_id}")
def memory(counterparty_id: str, service: RiskService = Depends(get_service)) -> dict:
    counterparty = service.repo.get_counterparty(counterparty_id)
    if counterparty is None:
        raise HTTPException(status_code=404, detail="Unknown counterparty")
    return {"counterparty": counterparty, "episodes": service.repo.list_episodes(counterparty_id)}


@router.get("/traces/{calculation_id}")
def trace(calculation_id: str, service: RiskService = Depends(get_service)) -> dict:
    stored = service.repo.get_trace(calculation_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Unknown calculation")
    return {"trace": stored}


@router.post("/eval/run")
def eval_run(service: RiskService = Depends(get_service)) -> dict:
    report = run_suite()
    report["failure_set"] = failure_report(service)
    return report


def _threshold_override(service: RiskService, body: CalculateRequest) -> CSA | None:
    if body.threshold_override is None:
        return None
    current = service.repo.get_csa(body.netting_set_id)
    if current is None:
        return CSA(csa_id=f"CSA-{body.netting_set_id}", netting_set_id=body.netting_set_id, threshold=body.threshold_override)
    return current.model_copy(update={"threshold": body.threshold_override})


def _from_frame(frame: pd.DataFrame) -> tuple[list[Counterparty], list[Trade]]:
    required = {"trade_id", "counterparty_id", "product_type", "notional", "currency", "start_date", "maturity", "direction", "netting_set_id"}
    missing = required - set(frame.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV is missing columns: {sorted(missing)}")
    counterparties: dict[str, Counterparty] = {}
    trades: list[Trade] = []
    for row in frame.to_dict(orient="records"):
        counterparty_id = str(row["counterparty_id"])
        if counterparty_id not in counterparties:
            counterparties[counterparty_id] = Counterparty(
                id=counterparty_id,
                name=str(row.get("counterparty_name") or counterparty_id),
                rating=_text(row.get("rating")),
                sector=_text(row.get("sector")),
                country=_text(row.get("country")),
                pd=_float(row.get("pd")),
                recovery_rate=_float(row.get("recovery_rate")) if _float(row.get("recovery_rate")) is not None else 0.40,
            )
        trade_id = str(row["trade_id"])
        row = {
            **row,
            "direction": _direction(row["direction"], trade_id),
            "product_type": _product_type(row["product_type"], trade_id),
        }
        trades.append(
            Trade(
                trade_id=str(row["trade_id"]),
                counterparty_id=counterparty_id,
                product_type=row["product_type"],
                notional=float(row["notional"]),
                currency=str(row["currency"]),
                start_date=_as_date(row["start_date"], trade_id, "start_date"),
                maturity=_as_date(row["maturity"], trade_id, "maturity"),
                fixed_rate=_float(row.get("fixed_rate")),
                strike=_float(row.get("strike")),
                direction=row["direction"],
                netting_set_id=str(row["netting_set_id"]),
                collateralized=_bool(row.get("collateralized", True)),
                underlying=_text(row.get("underlying")),
            )
        )
    return list(counterparties.values()), trades


_PRODUCTS = {
    "irs": "IRS",
    "swap": "IRS",
    "interest_rate_swap": "IRS",
    "fx": "FX_Forward",
    "fx_forward": "FX_Forward",
    "fxforward": "FX_Forward",
    "european_option": "European_Option",
    "option": "European_Option",
    "fx_option": "FX_Option",
    "fxoption": "FX_Option",
    "ccs": "CCS",
    "xccy": "CCS",
    "cross_currency_swap": "CCS",
    "other": "Other",
}


_DIRECTIONS = {
    "pay": "Pay",
    "pay_fixed": "Pay",
    "payer": "Pay",
    "receive": "Receive",
    "receive_fixed": "Receive",
    "receiver": "Receive",
    "buy": "Buy",
    "long": "Buy",
    "sell": "Sell",
    "short": "Sell",
}


def _trade_from_mapping(item: dict) -> Trade:
    payload = dict(item)
    trade_id = str(payload.get("trade_id", ""))
    payload["direction"] = _direction(payload.get("direction"), trade_id)
    payload["product_type"] = _product_type(payload.get("product_type"), trade_id)
    payload["start_date"] = _as_date(payload.get("start_date"), trade_id, "start_date")
    payload["maturity"] = _as_date(payload.get("maturity"), trade_id, "maturity")
    return Trade.model_validate(payload)


def _product_type(value, trade_id: str) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        raise HTTPException(status_code=400, detail=f"Trade {trade_id} is missing product_type.")
    key = "_".join(text.lower().replace("-", " ").replace("_", " ").split())
    return _PRODUCTS.get(key, text)


def _direction(value, trade_id: str) -> str:
    key = str(value).strip().lower().replace("-", " ").replace("_", " ")
    key = "_".join(key.split())
    mapped = _DIRECTIONS.get(key)
    if mapped is None:
        raise HTTPException(
            status_code=400,
            detail=f"Trade {trade_id} has direction {value!r}. Use Pay, Receive, Buy, or Sell.",
        )
    return mapped


def _as_date(value, trade_id: str, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        raise HTTPException(status_code=400, detail=f"Trade {trade_id} is missing {field}.")
    head = text.split()[0].replace(".", "/")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Trade {trade_id} has {field} {value!r}. Use YYYY-MM-DD or M/D/YYYY.",
        ) from None


def _float(value):
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return float(value)


def _text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
