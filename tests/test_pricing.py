import math
from datetime import date

import QuantLib as ql
import pytest

from ccr_xva.engines.extensions import price_european_option
from ccr_xva.engines.pricing import flat_df, par_rate, price_fx_forward, price_irs
from ccr_xva.engines.exposure import hw_zero_bond
from ccr_xva.models.schemas import MarketScenario, Trade

AS_OF = date(2026, 10, 5)


def _irs(fixed_rate: float = 0.04) -> Trade:
    return Trade(
        trade_id="IRS-TEST",
        counterparty_id="CP",
        product_type="IRS",
        notional=10_000_000,
        currency="USD",
        start_date=AS_OF,
        maturity=date(2031, 10, 5),
        fixed_rate=fixed_rate,
        direction="Pay",
        netting_set_id="NS",
    )


def test_par_swap_is_near_zero():
    scenario = MarketScenario(as_of=AS_OF, usd_rate=0.04)
    rate = par_rate(AS_OF, date(2031, 10, 5), AS_OF, flat_df(AS_OF, 0.04))
    value = price_irs(_irs(rate), scenario)
    assert abs(value) < 1.0


def test_fx_forward_closed_form():
    scenario = MarketScenario(as_of=AS_OF)
    trade = Trade(
        trade_id="FX-TEST",
        counterparty_id="CP",
        product_type="FX_Forward",
        notional=1_000_000,
        currency="USD",
        start_date=AS_OF,
        maturity=date(2027, 10, 5),
        strike=1.10,
        direction="Buy",
        netting_set_id="NS",
        underlying="EURUSD",
    )
    expected = 1_000_000 * (1.10 * math.exp(-0.03) - 1.10 * math.exp(-0.04))
    assert price_fx_forward(trade, scenario) == pytest.approx(expected, rel=1e-12)


def test_irs_matches_quantlib():
    scenario = MarketScenario(as_of=AS_OF, usd_rate=0.04)
    trade = _irs(0.035)
    ql_value = _quantlib_payer_npv(trade.notional, trade.fixed_rate, 0.04)
    assert price_irs(trade, scenario) == pytest.approx(ql_value, rel=1e-6, abs=1.0)


def test_hull_white_bond_matches_quantlib():
    today = ql.Date(5, 10, 2026)
    ql.Settings.instance().evaluationDate = today
    curve = ql.FlatForward(today, 0.04, ql.Actual365Fixed(), ql.Continuous)
    hw = ql.HullWhite(ql.YieldTermStructureHandle(curve), 0.03, 0.01)
    ours = hw_zero_bond(0.03, 0.01, 0.04, 0.5, 2.0, 0.045)
    assert ours == pytest.approx(hw.discountBond(0.5, 2.0, 0.045), rel=1e-8)


def test_european_option_is_not_implemented():
    trade = _irs().model_copy(update={"product_type": "European_Option", "direction": "Buy", "strike": 1.0})
    with pytest.raises(NotImplementedError):
        price_european_option(trade, MarketScenario(as_of=AS_OF))


def _quantlib_payer_npv(notional: float, fixed_rate: float, rate: float) -> float:
    today = ql.Date(5, 10, 2026)
    ql.Settings.instance().evaluationDate = today
    day_count = ql.Actual365Fixed()
    handle = ql.YieldTermStructureHandle(ql.FlatForward(today, rate, day_count, ql.Continuous))
    calendar = ql.NullCalendar()
    schedule = ql.Schedule(
        today,
        ql.Date(5, 10, 2031),
        ql.Period(ql.Annual),
        calendar,
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Forward,
        False,
    )
    index = ql.IborIndex(
        "USD-ANNUAL",
        ql.Period(ql.Annual),
        0,
        ql.USDCurrency(),
        calendar,
        ql.Unadjusted,
        False,
        day_count,
        handle,
    )
    swap = ql.VanillaSwap(
        ql.VanillaSwap.Payer,
        notional,
        schedule,
        fixed_rate,
        day_count,
        schedule,
        index,
        0.0,
        day_count,
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(handle))
    return float(swap.NPV())
