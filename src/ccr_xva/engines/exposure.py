"""Pathwise Monte Carlo exposure for IRS and FX forwards.

Rates use a Hull-White short rate calibrated to a flat USD curve. FX uses GBM
with deterministic foreign and domestic rates. The same Brownian shocks are
shared by every trade in the netting set. Collateral is applied to the summed
mark-to-market.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np

from ccr_xva.engines.collateral import apply_collateral_path, shift_for_mpor
from ccr_xva.engines.pricing import (
    discount_factor,
    fx_pair_parts,
    irs_npv_from_bonds,
    swap_periods,
    year_fraction,
)
from ccr_xva.models.schemas import CSA, MarketScenario, Trade


def month_grid(start: date, end: date) -> list[date]:
    if end < start:
        return [start]
    dates = [start]
    cursor = start
    while cursor < end:
        year = cursor.year + (cursor.month == 12)
        month = 1 if cursor.month == 12 else cursor.month + 1
        day = min(start.day, _days_in_month(year, month))
        nxt = date(year, month, day)
        if nxt <= cursor:
            break
        if nxt >= end:
            dates.append(end)
            break
        dates.append(nxt)
        cursor = nxt
    if dates[-1] != end:
        dates.append(end)
    return dates


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def hw_zero_bond(a: float, sigma: float, flat_rate: float, t: float, maturity: float, short_rate: float) -> float:
    """P(t, T) in a flat-curve Hull-White model. `t` and `maturity` are year fractions from as-of."""
    if maturity <= t + 1e-14:
        return 1.0
    dt = maturity - t
    if a < 1e-8:
        return math.exp(-flat_rate * dt)
    b_coef = (1.0 - math.exp(-a * dt)) / a
    variance = (sigma**2) / (4.0 * a) * (1.0 - math.exp(-2.0 * a * t)) * b_coef * b_coef
    log_a = -flat_rate * dt + b_coef * flat_rate - variance
    return math.exp(log_a - b_coef * short_rate)


def _alpha(t: float, a: float, sigma: float, flat_rate: float) -> float:
    if a < 1e-8 or sigma == 0.0:
        return flat_rate
    return flat_rate + (sigma**2) / (2.0 * a * a) * (1.0 - math.exp(-a * t)) ** 2


def _simulate_hull_white(times: np.ndarray, a: float, sigma: float, flat_rate: float, normals: np.ndarray) -> np.ndarray:
    """Short rate at each time. `normals` has shape (n_paths, n_steps) for the gaps in `times`."""
    n_paths = normals.shape[0]
    rates = np.empty((n_paths, len(times)))
    x = np.zeros(n_paths)
    rates[:, 0] = flat_rate
    for index in range(1, len(times)):
        dt = float(times[index] - times[index - 1])
        if dt <= 0:
            rates[:, index] = x + _alpha(float(times[index]), a, sigma, flat_rate)
            continue
        decay = math.exp(-a * dt) if a > 1e-8 else 1.0
        if a < 1e-8 or sigma == 0.0:
            shock = 0.0
        else:
            shock = sigma * math.sqrt((1.0 - math.exp(-2.0 * a * dt)) / (2.0 * a))
        x = x * decay + shock * normals[:, index - 1]
        rates[:, index] = x + _alpha(float(times[index]), a, sigma, flat_rate)
    return rates


def _simulate_fx(
    times: np.ndarray,
    spot: float,
    vol: float,
    drift: float,
    normals: np.ndarray,
) -> np.ndarray:
    n_paths = normals.shape[0]
    spots = np.empty((n_paths, len(times)))
    spots[:, 0] = spot
    level = np.full(n_paths, spot)
    for index in range(1, len(times)):
        dt = float(times[index] - times[index - 1])
        if dt <= 0:
            spots[:, index] = level
            continue
        diffusion = 0.0 if vol <= 0 else vol * math.sqrt(dt) * normals[:, index - 1]
        level = level * np.exp((drift - 0.5 * vol * vol) * dt + diffusion)
        spots[:, index] = level
    return spots


def _time_weighted_average(times: np.ndarray, values: np.ndarray, horizon: float | None = None) -> float:
    if len(times) == 1:
        return float(values[0])
    total = 0.0
    weight = 0.0
    for left, right, v_left, v_right in zip(times, times[1:], values, values[1:]):
        if horizon is not None and left >= horizon:
            break
        right_c = right if horizon is None else min(right, horizon)
        dt = float(right_c - left)
        if dt <= 0:
            continue
        # Interpolate the right edge when the horizon cuts a bucket.
        frac = dt / float(right - left) if right != left else 1.0
        v_cut = v_left + (v_right - v_left) * frac
        total += 0.5 * (v_left + v_cut) * dt
        weight += dt
        if horizon is not None and right >= horizon:
            break
    if weight <= 0:
        return float(values[0])
    return total / weight


def _effective_epe(times: np.ndarray, ee: np.ndarray) -> float:
    running = np.maximum.accumulate(ee)
    return _time_weighted_average(times, running, horizon=1.0)


def deterministic_mtm(trade: Trade, scenario: MarketScenario, day: date) -> float:
    """Mark-to-market on the initial curve. Used as the zero-volatility reference."""
    from ccr_xva.engines.pricing import price_trade

    quiet = scenario.model_copy(update={"hw_sigma": 0.0, "fx_vols": {k: 0.0 for k in scenario.fx_vols}})
    return price_trade(trade, quiet, day)


def _hw_bond_vector(a: float, sigma: float, flat: float, t: float, maturity: float, short_rate: np.ndarray) -> np.ndarray:
    if maturity <= t + 1e-14:
        return np.ones_like(short_rate)
    dt = maturity - t
    if a < 1e-8 or sigma == 0.0:
        return np.full_like(short_rate, math.exp(-flat * dt))
    b_coef = (1.0 - math.exp(-a * dt)) / a
    variance = (sigma**2) / (4.0 * a) * (1.0 - math.exp(-2.0 * a * t)) * b_coef * b_coef
    log_a = -flat * dt + b_coef * flat - variance
    return np.exp(log_a - b_coef * short_rate)


def _irs_mtm_on_paths(
    trade: Trade,
    scenario: MarketScenario,
    grid: list[date],
    times: np.ndarray,
    short_rate: np.ndarray,
    time_index: dict[float, int],
) -> np.ndarray:
    _ = times
    periods = swap_periods(trade.start_date, trade.maturity)
    n_paths = short_rate.shape[0]
    values = np.zeros((n_paths, len(grid)))
    as_of = scenario.as_of
    a = scenario.hw_a
    sigma = scenario.hw_sigma
    flat = scenario.usd_rate
    fixed_rate = trade.fixed_rate or 0.0

    def time_of(day: date) -> float:
        return round(year_fraction(as_of, day), 10)

    for date_index, day in enumerate(grid):
        if day >= trade.maturity:
            continue
        t_now = time_of(day)
        r_now = short_rate[:, time_index[t_now]]
        payer = np.zeros(n_paths)
        for left, right, delta in periods:
            if right <= day or delta <= 0:
                continue
            df_pay = _hw_bond_vector(a, sigma, flat, t_now, time_of(right), r_now)
            fixed = trade.notional * fixed_rate * delta * df_pay
            if left >= day:
                if left == day:
                    df_left = np.ones(n_paths)
                else:
                    df_left = _hw_bond_vector(a, sigma, flat, t_now, time_of(left), r_now)
                floating = trade.notional * (df_left - df_pay)
            elif left < as_of:
                p_reset = discount_factor(flat, year_fraction(left, right))
                floating = trade.notional * (1.0 / p_reset - 1.0) * df_pay
            else:
                r_left = short_rate[:, time_index[time_of(left)]]
                p_reset = _hw_bond_vector(a, sigma, flat, time_of(left), time_of(right), r_left)
                floating = trade.notional * (1.0 / np.maximum(p_reset, 1e-12) - 1.0) * df_pay
            payer += floating - fixed
        values[:, date_index] = payer if trade.direction == "Pay" else -payer
    return values


def _fx_mtm_on_paths(
    trade: Trade,
    scenario: MarketScenario,
    grid: list[date],
    spots: np.ndarray,
) -> np.ndarray:
    pair = (trade.underlying or "EURUSD").upper()
    foreign, _domestic = fx_pair_parts(pair)
    rd = scenario.usd_rate
    rf = scenario.foreign_rates.get(foreign, rd)
    sign = 1.0 if trade.direction == "Buy" else -1.0
    values = np.zeros_like(spots)
    for index, day in enumerate(grid):
        if day >= trade.maturity:
            continue
        tau = year_fraction(day, trade.maturity)
        values[:, index] = sign * trade.notional * (
            spots[:, index] * discount_factor(rf, tau) - trade.strike * discount_factor(rd, tau)
        )
    return values


def simulate_exposure(
    trades: list[Trade],
    scenario: MarketScenario,
    csa: CSA | None = None,
    collateralized: bool = True,
) -> dict:
    """Simulate a netting set and return curve statistics plus per-trade standalone EE."""
    if not trades:
        raise ValueError("simulate_exposure requires at least one trade")
    for trade in trades:
        if trade.product_type == "FX_Option":
            raise ValueError(
                f"Trade {trade.trade_id} is an FX option. v0.1 prices USD IRS and FX forwards only."
            )
        if trade.product_type == "CCS":
            raise ValueError(
                f"Trade {trade.trade_id} is a cross-currency swap (CCS). v0.1 prices USD IRS and FX forwards only."
            )
        if trade.product_type == "European_Option":
            from ccr_xva.engines.extensions import price_european_option

            price_european_option(trade, scenario)
        if trade.product_type not in {"IRS", "FX_Forward"}:
            raise ValueError(
                f"Trade {trade.trade_id} has product_type {trade.product_type}. v0.1 prices USD IRS and FX forwards only."
            )
        if trade.currency != "USD":
            raise ValueError("v0.1 exposure supports USD valuation only")

    as_of = scenario.as_of
    maturity = max(trade.maturity for trade in trades)
    grid = month_grid(as_of, maturity)
    extra_times = {0.0}
    for trade in trades:
        if trade.product_type == "IRS":
            for left, right, _delta in swap_periods(trade.start_date, trade.maturity):
                if left >= as_of:
                    extra_times.add(round(year_fraction(as_of, left), 10))
                if right > as_of:
                    extra_times.add(round(year_fraction(as_of, right), 10))
    for day in grid:
        extra_times.add(round(year_fraction(as_of, day), 10))
    times = np.array(sorted(extra_times), dtype=float)
    time_index = {round(float(t), 10): i for i, t in enumerate(times)}

    n_paths = scenario.n_paths
    if n_paths < 2:
        raise ValueError("n_paths must be at least 2")
    if n_paths % 2 == 1:
        n_paths += 1
    half = n_paths // 2
    rng = np.random.default_rng(scenario.seed)
    steps = max(len(times) - 1, 1)
    fx_pairs = sorted({(trade.underlying or "EURUSD").upper() for trade in trades if trade.product_type == "FX_Forward"})
    # Column 0 is the Hull-White factor. Later columns are FX pairs.
    shock = rng.standard_normal((half, steps, 1 + max(len(fx_pairs), 0)))
    shock = np.concatenate([shock, -shock], axis=0)

    short_rate = _simulate_hull_white(times, scenario.hw_a, scenario.hw_sigma, scenario.usd_rate, shock[:, :, 0])
    fx_spots: dict[str, np.ndarray] = {}
    for pair_index, pair in enumerate(fx_pairs):
        foreign, _domestic = fx_pair_parts(pair)
        drift = scenario.usd_rate - scenario.foreign_rates.get(foreign, scenario.usd_rate)
        fx_spots[pair] = _simulate_fx(
            times,
            scenario.fx_spots.get(pair, 1.0),
            scenario.fx_vols.get(pair, 0.10),
            drift,
            shock[:, :, pair_index + 1],
        )

    grid_index = [time_index[round(year_fraction(as_of, day), 10)] for day in grid]
    per_trade = []
    portfolio = np.zeros((n_paths, len(grid)))
    for trade in trades:
        if trade.product_type == "IRS":
            mtm = _irs_mtm_on_paths(trade, scenario, grid, times, short_rate, time_index)
        else:
            pair = (trade.underlying or "EURUSD").upper()
            spots_on_grid = fx_spots[pair][:, grid_index]
            mtm = _fx_mtm_on_paths(trade, scenario, grid, spots_on_grid)
        portfolio += mtm
        per_trade.append((trade, mtm))

    applied = csa if collateralized and csa is not None else None
    if applied is not None and applied.metadata.get("uncollateralized"):
        applied = None
    positive, negative = apply_collateral_path(portfolio, grid, applied)
    positive, negative = shift_for_mpor(positive, negative, grid, scenario.mpor_days)

    ee = positive.mean(axis=0)
    ene = negative.mean(axis=0)
    pfe_95 = np.quantile(positive, 0.95, axis=0)
    pfe_99 = np.quantile(positive, 0.99, axis=0)
    year_times = np.array([year_fraction(as_of, day) for day in grid])
    peak_index = int(np.argmax(pfe_95))
    drivers = []
    for trade, mtm in per_trade:
        standalone = np.maximum(mtm, 0.0).mean(axis=0)
        drivers.append(
            {
                "trade_id": trade.trade_id,
                "product_type": trade.product_type,
                "underlying": trade.underlying,
                "standalone_ee_at_peak_pfe": float(standalone[peak_index]),
            }
        )
    drivers.sort(key=lambda item: item["standalone_ee_at_peak_pfe"], reverse=True)
    return {
        "dates": grid,
        "ee": ee.tolist(),
        "ene": ene.tolist(),
        "pfe_95": pfe_95.tolist(),
        "pfe_99": pfe_99.tolist(),
        "epe": _time_weighted_average(year_times, ee),
        "effective_epe": _effective_epe(year_times, ee),
        "drivers": drivers,
        "n_paths": n_paths,
        "peak_pfe_95": float(pfe_95[peak_index]),
        "peak_pfe_date": grid[peak_index],
    }


def irs_value_reference(trade: Trade, scenario: MarketScenario, as_of: date) -> float:
    """Deterministic IRS value via the shared cashflow formula. Exposed for tests."""
    rate = scenario.usd_rate

    def bond(pay: date) -> float:
        return discount_factor(rate, year_fraction(as_of, pay))

    def reset_bond(left: date, right: date) -> float:
        return discount_factor(rate, year_fraction(left, right))

    return irs_npv_from_bonds(
        trade.notional,
        trade.fixed_rate or 0.0,
        trade.direction,
        swap_periods(trade.start_date, trade.maturity),
        as_of,
        bond,
        reset_bond,
    )
