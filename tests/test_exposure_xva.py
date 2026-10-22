from datetime import date

import pytest

from ccr_xva.engines.collateral import apply_collateral_path
from ccr_xva.engines.exposure import simulate_exposure
from ccr_xva.engines.pricing import price_irs, price_trade
from ccr_xva.engines.xva import approximate_cva
from ccr_xva.evals.suite import fx_closed_form_error
from ccr_xva.models.schemas import CSA, MarketScenario, Trade

AS_OF = date(2026, 10, 5)


def _swap(fixed_rate: float, direction: str = "Pay") -> Trade:
    return Trade(
        trade_id="IRS-1",
        counterparty_id="CP1",
        product_type="IRS",
        notional=10_000_000,
        currency="USD",
        start_date=AS_OF,
        maturity=date(2030, 10, 5),
        fixed_rate=fixed_rate,
        direction=direction,
        netting_set_id="NS1",
        collateralized=False,
    )


def test_zero_volatility_irs_matches_full_revaluation():
    scenario = MarketScenario(as_of=AS_OF, hw_sigma=0.0, n_paths=20, seed=1)
    trade = _swap(0.05)
    result = simulate_exposure([trade], scenario, collateralized=False)
    for day, ee in zip(result["dates"], result["ee"]):
        reference = max(price_irs(trade, scenario, day), 0.0)
        assert ee == pytest.approx(reference, rel=1e-6, abs=1.0)


def test_higher_threshold_does_not_reduce_exposure():
    import numpy as np

    mtm = np.array([[0.0, 5_000_000.0, 12_000_000.0], [0.0, -2_000_000.0, 8_000_000.0]])
    dates = [AS_OF, date(2027, 10, 5), date(2028, 10, 5)]
    low = CSA(csa_id="A", netting_set_id="NS", threshold=0.0, mta=0.0)
    high = low.model_copy(update={"threshold": 5_000_000.0})
    low_positive, _ = apply_collateral_path(mtm, dates, low)
    high_positive, _ = apply_collateral_path(mtm, dates, high)
    assert np.all(high_positive + 1e-8 >= low_positive)


def test_cva_hand_buckets_and_zero_pd():
    dates = [AS_OF, date(2027, 10, 5), date(2028, 10, 5), date(2029, 10, 5)]
    ee = [0.0, 100.0, 80.0, 40.0]
    assert approximate_cva(dates, ee, AS_OF, 0.04, 0.0, 0.40) == pytest.approx(0.0, abs=1e-12)
    base = approximate_cva(dates, ee, AS_OF, 0.04, 0.02, 0.40)
    doubled_lgd = approximate_cva(dates, ee, AS_OF, 0.04, 0.02, 0.0)
    # Recovery 0 means LGD 1, versus LGD 0.60, so the ratio is 1/0.6.
    assert doubled_lgd == pytest.approx(base / 0.60, rel=1e-12)


@pytest.mark.slow
def test_fx_monte_carlo_within_two_percent():
    report = fx_closed_form_error(8000)
    assert report["passed"], report


def test_option_book_is_rejected():
    trade = _swap(0.04).model_copy(update={"product_type": "European_Option", "direction": "Buy", "strike": 100.0})
    with pytest.raises(NotImplementedError):
        simulate_exposure([trade], MarketScenario(as_of=AS_OF, n_paths=10))


def test_future_fx_spot_is_rolled_when_volatility_is_zero():
    scenario = MarketScenario(as_of=AS_OF, fx_vols={"EURUSD": 0.0, "USDJPY": 0.0})
    trade = Trade(
        trade_id="FX-1",
        counterparty_id="CP",
        product_type="FX_Forward",
        notional=1_000_000,
        currency="USD",
        start_date=AS_OF,
        maturity=date(2028, 10, 5),
        strike=1.10,
        direction="Buy",
        netting_set_id="NS",
        underlying="EURUSD",
        collateralized=False,
    )
    result = simulate_exposure([trade], scenario.model_copy(update={"n_paths": 16, "hw_sigma": 0.0}), collateralized=False)
    for day, ee in zip(result["dates"], result["ee"]):
        reference = max(price_trade(trade, scenario, day), 0.0)
        assert ee == pytest.approx(reference, rel=1e-6, abs=0.5)
