"""Cash CSA applied to netting-set mark-to-market.

Variation margin is max(0, MtM - threshold - independent amount). A call smaller
than the minimum transfer amount is skipped. Independent amount is treated as
already held and always reduces positive exposure. Weekly frequency keeps calls
only on dates at least 7 days after the previous call date; other dates reuse
the last collateral balance.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from ccr_xva.models.schemas import CSA


def uncollateralized_csa(netting_set_id: str) -> CSA:
    return CSA(
        csa_id=f"UNC-{netting_set_id}",
        netting_set_id=netting_set_id,
        threshold=0.0,
        mta=0.0,
        independent_amount=0.0,
        collateral_type="Cash",
        frequency="Daily",
        metadata={"uncollateralized": True},
    )


def _call_amount(mtm: np.ndarray, threshold: float, independent_amount: float, mta: float) -> np.ndarray:
    vm_call = np.maximum(0.0, mtm - threshold - independent_amount)
    return np.where(vm_call < mta, 0.0, vm_call)


def apply_collateral_path(mtm: np.ndarray, dates: list[date], csa: CSA | None) -> tuple[np.ndarray, np.ndarray]:
    """Return positive and negative exposure for one path or a vector of paths.

    `mtm` shape is (n_dates,) or (n_paths, n_dates). Negative exposure is the
    uncollateralized amount we would owe, used for the DVA teaching calculation.
    """
    values = np.asarray(mtm, dtype=float)
    single = values.ndim == 1
    if single:
        values = values[None, :]
    if csa is None or csa.metadata.get("uncollateralized"):
        positive = np.maximum(values, 0.0)
        negative = np.maximum(-values, 0.0)
        return (positive[0], negative[0]) if single else (positive, negative)

    n_paths, n_dates = values.shape
    collateral = np.zeros_like(values)
    last_call_date: date | None = None
    for index, day in enumerate(dates):
        allow_call = True
        if csa.frequency == "Weekly" and last_call_date is not None:
            allow_call = (day - last_call_date).days >= 7
        if allow_call:
            vm = _call_amount(values[:, index], csa.threshold, csa.independent_amount, csa.mta)
            collateral[:, index] = csa.independent_amount + vm
            last_call_date = day
        else:
            collateral[:, index] = collateral[:, index - 1] if index else csa.independent_amount
    positive = np.maximum(values - collateral, 0.0)
    negative = np.maximum(-values, 0.0)
    return (positive[0], negative[0]) if single else (positive, negative)


def shift_for_mpor(positive: np.ndarray, negative: np.ndarray, dates: list[date], mpor_days: int) -> tuple[np.ndarray, np.ndarray]:
    """Use the exposure `mpor_days` later as a margin-period lag. Zero leaves arrays unchanged."""
    if mpor_days <= 0:
        return positive, negative
    shifted_pos = positive.copy()
    shifted_neg = negative.copy()
    for index, day in enumerate(dates):
        target = None
        for later in range(index, len(dates)):
            if (dates[later] - day).days >= mpor_days:
                target = later
                break
        if target is None:
            target = len(dates) - 1
        shifted_pos[:, index] = positive[:, target]
        shifted_neg[:, index] = negative[:, target]
    return shifted_pos, shifted_neg
