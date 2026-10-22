"""Single-curve IRS and closed-form FX forward pricing.

IRS uses an annual fixed leg and a matching annual floating leg so the floating
leg telescopes on one discount curve. Future Monte Carlo revaluation uses the
same formula on Hull-White discount factors. v0.1 values everything in USD.
"""

from __future__ import annotations

import math
from datetime import date

from ccr_xva.engines.extensions import price_european_option
from ccr_xva.models.schemas import MarketScenario, Trade


def year_fraction(start: date, end: date) -> float:
    return (end - start).days / 365.0


def discount_factor(rate: float, time: float) -> float:
    return math.exp(-rate * max(time, 0.0))


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def annual_schedule(start: date, maturity: date) -> list[date]:
    """Start plus each following anniversary, ending on maturity."""
    if maturity <= start:
        return [start, maturity] if maturity != start else [start]
    dates = [start]
    years = 1
    while True:
        nxt = _add_years(start, years)
        if nxt >= maturity:
            if dates[-1] != maturity:
                dates.append(maturity)
            break
        dates.append(nxt)
        years += 1
    return dates


def swap_periods(start: date, maturity: date) -> list[tuple[date, date, float]]:
    """Annual accrual periods as (start, end, year fraction)."""
    schedule = annual_schedule(start, maturity)
    return [
        (left, right, year_fraction(left, right))
        for left, right in zip(schedule, schedule[1:])
        if right > left
    ]


def irs_npv_from_bonds(
    notional: float,
    fixed_rate: float,
    direction: str,
    periods: list[tuple[date, date, float]],
    as_of: date,
    bond,
    reset_bond=None,
) -> float:
    """Single-curve dirty NPV.

    `bond(pay_date)` is P(as_of, pay_date). For a period that has already started,
    `reset_bond(left, right)` is the discount bond P(left, right) that locked the
    floating fixing. On a reset date the current period uses the live telescope.
    """
    if direction not in {"Pay", "Receive"}:
        raise ValueError(f"IRS direction must be Pay or Receive, got {direction}")
    payer = 0.0
    for left, right, delta in periods:
        if right <= as_of or delta <= 0:
            continue
        df_pay = bond(right)
        fixed = notional * fixed_rate * delta * df_pay
        if left >= as_of:
            df_left = 1.0 if left == as_of else bond(left)
            floating = notional * (df_left - df_pay)
        else:
            if reset_bond is None:
                raise ValueError("reset_bond is required once a floating period has started")
            p_reset = reset_bond(left, right)
            floating = notional * (1.0 / p_reset - 1.0) * df_pay
        payer += floating - fixed
    return payer if direction == "Pay" else -payer


def par_rate(start: date, maturity: date, as_of: date, bond) -> float:
    """Par fixed rate when every remaining floating period still starts on or after as_of."""
    annuity = 0.0
    floating = 0.0
    for left, right, delta in swap_periods(start, maturity):
        if right <= as_of:
            continue
        if left < as_of:
            raise ValueError("par_rate expects a valuation on or before the current reset")
        df_pay = bond(right)
        df_left = 1.0 if left == as_of else bond(left)
        annuity += delta * df_pay
        floating += df_left - df_pay
    if annuity <= 0:
        return 0.0
    return floating / annuity


def flat_df(as_of: date, rate: float):
    def df(day: date) -> float:
        return discount_factor(rate, year_fraction(as_of, day))

    return df


def price_irs(trade: Trade, scenario: MarketScenario, as_of: date | None = None) -> float:
    if trade.product_type != "IRS":
        raise ValueError("price_irs expects an IRS")
    if trade.fixed_rate is None:
        raise ValueError(f"IRS {trade.trade_id} is missing fixed_rate")
    if trade.currency != "USD":
        raise ValueError("v0.1 IRS pricing supports USD only")
    valued = as_of or scenario.as_of
    if valued >= trade.maturity:
        return 0.0
    rate = scenario.usd_rate
    curve = flat_df(valued, rate)

    def reset_bond(left: date, right: date) -> float:
        # Deterministic curve: the fixing is known from the flat rate alone.
        return discount_factor(rate, year_fraction(left, right))

    return irs_npv_from_bonds(
        trade.notional,
        trade.fixed_rate,
        trade.direction,
        swap_periods(trade.start_date, trade.maturity),
        valued,
        curve,
        reset_bond,
    )


def fx_pair_parts(pair: str) -> tuple[str, str]:
    pair = pair.upper()
    if len(pair) != 6:
        raise ValueError(f"FX pair must be six letters, got {pair}")
    return pair[:3], pair[3:]


def price_fx_forward(trade: Trade, scenario: MarketScenario, as_of: date | None = None, spot: float | None = None) -> float:
    """Domestic value of an FX forward. Notional is foreign currency units.

    Buy means buy foreign currency (receive foreign, pay strike in USD).
    """
    if trade.product_type != "FX_Forward":
        raise ValueError("price_fx_forward expects an FX_Forward")
    if trade.strike is None:
        raise ValueError(f"FX forward {trade.trade_id} is missing strike")
    if trade.currency != "USD":
        raise ValueError("v0.1 FX forwards settle in USD")
    valued = as_of or scenario.as_of
    if valued >= trade.maturity:
        return 0.0
    pair = (trade.underlying or "EURUSD").upper()
    foreign, domestic = fx_pair_parts(pair)
    if domestic != "USD":
        raise ValueError("v0.1 FX forwards must be quoted as XXXUSD")
    rd = scenario.usd_rate
    rf = scenario.foreign_rates.get(foreign, scenario.usd_rate)
    if spot is None:
        elapsed = year_fraction(scenario.as_of, valued)
        spot_value = scenario.fx_spots[pair] * math.exp((rd - rf) * max(elapsed, 0.0))
    else:
        spot_value = spot
    tau = year_fraction(valued, trade.maturity)
    value = trade.notional * (
        spot_value * discount_factor(rf, tau) - trade.strike * discount_factor(rd, tau)
    )
    if trade.direction == "Buy":
        return value
    if trade.direction == "Sell":
        return -value
    raise ValueError(f"FX forward direction must be Buy or Sell, got {trade.direction}")


def price_trade(trade: Trade, scenario: MarketScenario, as_of: date | None = None) -> float:
    if trade.product_type == "IRS":
        return price_irs(trade, scenario, as_of)
    if trade.product_type == "FX_Forward":
        return price_fx_forward(trade, scenario, as_of)
    if trade.product_type == "European_Option":
        return price_european_option(trade, scenario, as_of)
    if trade.product_type == "FX_Option":
        raise ValueError(f"Trade {trade.trade_id} is an FX option. v0.1 prices USD IRS and FX forwards only.")
    if trade.product_type == "CCS":
        raise ValueError(
            f"Trade {trade.trade_id} is a cross-currency swap (CCS). v0.1 prices USD IRS and FX forwards only."
        )
    raise ValueError(
        f"Trade {trade.trade_id} has product_type {trade.product_type}. v0.1 prices USD IRS and FX forwards only."
    )


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fx_expected_positive_exposure(
    trade: Trade,
    scenario: MarketScenario,
    horizon: date,
) -> float:
    """Closed-form EE of one uncollateralized FX forward under GBM rates-deterministic dynamics."""
    if trade.product_type != "FX_Forward" or trade.strike is None:
        raise ValueError("closed-form EE expects an FX forward")
    as_of = scenario.as_of
    if horizon <= as_of:
        return max(price_fx_forward(trade, scenario, as_of), 0.0)
    if horizon >= trade.maturity:
        return 0.0
    pair = (trade.underlying or "EURUSD").upper()
    foreign, _domestic = fx_pair_parts(pair)
    spot = scenario.fx_spots[pair]
    vol = scenario.fx_vols.get(pair, 0.10)
    rd = scenario.usd_rate
    rf = scenario.foreign_rates.get(foreign, rd)
    t = year_fraction(as_of, horizon)
    tau = year_fraction(horizon, trade.maturity)
    sign = 1.0 if trade.direction == "Buy" else -1.0
    # Value = sign * N * (S * df_f - K * df_d) = A * S - B, with A carrying the sign.
    df_f = discount_factor(rf, tau)
    df_d = discount_factor(rd, tau)
    a_coeff = sign * trade.notional * df_f
    b_coeff = sign * trade.notional * trade.strike * df_d
    return _expected_positive_linear(spot, vol, rd - rf, t, a_coeff, b_coeff)


def _expected_positive_linear(spot: float, vol: float, drift: float, t: float, a_coeff: float, b_coeff: float) -> float:
    """E[max(A*S_t - B, 0)] for lognormal S with E[S_t] = spot*exp(drift*t)."""
    if t <= 0 or vol <= 1e-12:
        expected_spot = spot * math.exp(drift * t)
        return max(a_coeff * expected_spot - b_coeff, 0.0)
    mu_s = spot * math.exp(drift * t)
    # max(A S - B, 0). If A < 0 this is a put-like payoff on S.
    if abs(a_coeff) < 1e-18:
        return max(-b_coeff, 0.0)
    if a_coeff > 0:
        strike = b_coeff / a_coeff
        expectation = a_coeff * _call_expectation(mu_s, strike, vol, t)
        return expectation
    strike = b_coeff / a_coeff
    # A < 0: max(A(S - K), 0) = |A| * max(K - S, 0)
    return abs(a_coeff) * _put_expectation(mu_s, strike, vol, t)


def _call_expectation(mu_s: float, strike: float, vol: float, t: float) -> float:
    if strike <= 0:
        return mu_s - strike
    sigma = vol * math.sqrt(t)
    if sigma < 1e-12:
        return max(mu_s - strike, 0.0)
    d1 = (math.log(mu_s / strike) + 0.5 * sigma * sigma) / sigma
    d2 = d1 - sigma
    return mu_s * norm_cdf(d1) - strike * norm_cdf(d2)


def _put_expectation(mu_s: float, strike: float, vol: float, t: float) -> float:
    # E[max(K-S,0)] = E[max(S-K,0)] - mu_s + K
    return _call_expectation(mu_s, strike, vol, t) - mu_s + strike
