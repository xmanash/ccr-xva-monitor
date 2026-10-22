"""Pydantic contracts for trades, exposures, and grounded answers."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Counterparty(BaseModel):
    id: str
    name: str
    rating: str | None = None
    sector: str | None = None
    country: str | None = None
    pd: float | None = None
    recovery_rate: float = 0.40
    metadata: dict = Field(default_factory=dict)


class Trade(BaseModel):
    trade_id: str
    counterparty_id: str
    product_type: str
    notional: float
    currency: str
    start_date: date
    maturity: date
    fixed_rate: float | None = None
    strike: float | None = None
    direction: Literal["Pay", "Receive", "Buy", "Sell"]
    netting_set_id: str
    collateralized: bool = True
    underlying: str | None = None
    metadata: dict = Field(default_factory=dict)


class CSA(BaseModel):
    csa_id: str
    netting_set_id: str
    threshold: float = 0.0
    mta: float = 0.0
    independent_amount: float = 0.0
    collateral_type: Literal["Cash", "Bonds", "Mixed"] = "Cash"
    frequency: Literal["Daily", "Weekly"] = "Daily"
    currency: str = "USD"
    metadata: dict = Field(default_factory=dict)


class NettingSet(BaseModel):
    netting_set_id: str
    counterparty_id: str
    trade_ids: list[str] = Field(default_factory=list)
    csa_id: str | None = None


class MarketScenario(BaseModel):
    as_of: date
    usd_rate: float = 0.04
    fx_spots: dict[str, float] = Field(default_factory=lambda: {"EURUSD": 1.10, "USDJPY": 150.0})
    fx_vols: dict[str, float] = Field(default_factory=lambda: {"EURUSD": 0.10, "USDJPY": 0.12})
    foreign_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 0.03, "JPY": 0.01})
    hw_a: float = 0.03
    hw_sigma: float = 0.01
    funding_spread: float = 0.005
    own_pd: float = 0.01
    own_recovery: float = 0.40
    n_paths: int = 400
    seed: int = 42
    mpor_days: int = 0


class ExposureProfile(BaseModel):
    netting_set_id: str
    dates: list[date]
    ee: list[float]
    pfe_95: list[float]
    pfe_99: list[float]
    ene: list[float] = Field(default_factory=list)
    epe: float
    effective_epe: float
    calculation_id: str
    drivers: list[dict] = Field(default_factory=list)


class XVAResult(BaseModel):
    netting_set_id: str
    cva: float
    dva: float | None = None
    fva: float | None = None
    total_xva: float
    assumptions: dict = Field(default_factory=dict)
    calculation_id: str


class CalculationTrace(BaseModel):
    calculation_id: str
    kind: str
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)
    created_at: datetime


class MemoryEpisode(BaseModel):
    id: str
    counterparty_id: str
    netting_set_id: str
    as_of: date
    label: str
    peak_pfe: float | None = None
    cva: float | None = None
    calculation_id: str
    summary: str = ""


class NumericClaim(BaseModel):
    name: str
    value: float
    unit: str = "USD"
    source: Literal["engine", "memory", "retrieval"]
    source_id: str


class Citation(BaseModel):
    source: Literal["engine", "memory", "retrieval"]
    source_id: str
    text: str


class QueryRequest(BaseModel):
    query: str
    session_id: str = "local"
    include_charts: bool = True
    netting_set_id: str | None = None
    n_paths: int | None = None
    as_of: date | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    numeric_values: list[NumericClaim] = Field(default_factory=list)
    calculation_id: str | None = None
    chart: dict | None = None
    refused: bool = False
