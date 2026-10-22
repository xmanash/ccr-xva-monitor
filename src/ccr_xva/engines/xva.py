"""Teaching CVA, DVA, and FVA from an exposure profile.

Unilateral CVA is LGD times the sum of discounted default probabilities times
expected exposure. This is not IMM, SA-CCR, or a bilateral close-out adjustment.
"""

from __future__ import annotations

import math
from datetime import date

from ccr_xva.engines.pricing import discount_factor, year_fraction
from ccr_xva.models.schemas import ExposureProfile, MarketScenario


def hazard_from_pd(pd_1y: float) -> float:
    pd_clamped = min(max(pd_1y, 0.0), 0.999999)
    return -math.log(1.0 - pd_clamped)


def survival(pd_1y: float, time: float) -> float:
    return math.exp(-hazard_from_pd(pd_1y) * time)


def discounted_exposure_integral(
    dates: list[date],
    exposure: list[float],
    as_of: date,
    rate: float,
    pd_1y: float,
) -> float:
    """Sum DF(t_i) * (S(t_{i-1}) - S(t_i)) * EE(t_i) over future buckets."""
    total = 0.0
    previous_survival = 1.0
    for day, ee in zip(dates, exposure):
        time = year_fraction(as_of, day)
        if time <= 0:
            continue
        surv = survival(pd_1y, time)
        default_prob = previous_survival - surv
        total += discount_factor(rate, time) * default_prob * ee
        previous_survival = surv
    return total


def approximate_cva(
    dates: list[date],
    ee: list[float],
    as_of: date,
    rate: float,
    pd_1y: float,
    recovery: float,
) -> float:
    lgd = 1.0 - recovery
    return lgd * discounted_exposure_integral(dates, ee, as_of, rate, pd_1y)


def approximate_fva(
    dates: list[date],
    ee: list[float],
    ene: list[float],
    as_of: date,
    rate: float,
    funding_spread: float,
) -> float:
    """Funding spread times the discounted time integral of EE minus ENE."""
    total = 0.0
    previous = as_of
    for day, expected_positive, expected_negative in zip(dates, ee, ene):
        if day <= as_of:
            previous = day
            continue
        dt = year_fraction(previous, day)
        midpoint = year_fraction(as_of, day)
        total += discount_factor(rate, midpoint) * dt * (expected_positive - expected_negative)
        previous = day
    return funding_spread * total


def xva_from_profile(
    profile: ExposureProfile,
    scenario: MarketScenario,
    pd_1y: float,
    recovery: float,
) -> dict[str, float]:
    ene = profile.ene or [0.0] * len(profile.ee)
    cva = approximate_cva(profile.dates, profile.ee, scenario.as_of, scenario.usd_rate, pd_1y, recovery)
    dva = approximate_cva(
        profile.dates,
        ene,
        scenario.as_of,
        scenario.usd_rate,
        scenario.own_pd,
        scenario.own_recovery,
    )
    fva = approximate_fva(
        profile.dates,
        profile.ee,
        ene,
        scenario.as_of,
        scenario.usd_rate,
        scenario.funding_spread,
    )
    return {
        "cva": cva,
        "dva": dva,
        "fva": fva,
        "total_xva": cva - dva + fva,
    }
