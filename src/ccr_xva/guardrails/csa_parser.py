"""Deterministic parser for short CSA descriptions.

An LLM may propose text, but only a result that validates as CSA is accepted.
Percent amounts become absolute when the netting-set notional is supplied.
"""

from __future__ import annotations

import re

from ccr_xva.models.schemas import CSA

AMOUNT = r"(\$?\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|bn|billion|million|mm|m|k)?)"


def parse_csa_text(
    text: str,
    csa_id: str,
    netting_set_id: str,
    notional: float | None = None,
    currency: str = "USD",
) -> CSA:
    lowered = text.lower()
    frequency = "Weekly" if "weekly" in lowered else "Daily"
    if "bond" in lowered and "cash" in lowered:
        collateral_type = "Mixed"
    elif "bond" in lowered:
        collateral_type = "Bonds"
    else:
        collateral_type = "Cash"
    metadata: dict = {"source_text": text}
    threshold, threshold_fraction = _keyword_amount(text, "threshold", notional)
    mta, mta_fraction = _keyword_amount(text, "mta", notional)
    independent, independent_fraction = _keyword_amount(text, "independent amount", notional)
    if threshold_fraction is not None:
        metadata["threshold_fraction"] = threshold_fraction
    if mta_fraction is not None:
        metadata["mta_fraction"] = mta_fraction
    if independent_fraction is not None:
        metadata["independent_amount_fraction"] = independent_fraction
    return CSA(
        csa_id=csa_id,
        netting_set_id=netting_set_id,
        threshold=threshold or 0.0,
        mta=mta or 0.0,
        independent_amount=independent or 0.0,
        collateral_type=collateral_type,
        frequency=frequency,
        currency=currency,
        metadata=metadata,
    )


def _keyword_amount(text: str, keyword: str, notional: float | None) -> tuple[float | None, float | None]:
    pattern = re.compile(
        rf"(?:{AMOUNT}\s+{keyword}|{keyword}\s*(?:of|=|:)?\s*{AMOUNT})",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None, None
    token = next(group for group in match.groups() if group)
    return _parse_amount(token, notional)


def _parse_amount(token: str, notional: float | None) -> tuple[float | None, float | None]:
    cleaned = token.replace("$", "").replace(",", "").strip().lower()
    percent = cleaned.endswith("%")
    if percent:
        cleaned = cleaned[:-1].strip()
    multiplier = 1.0
    for suffix, factor in (("billion", 1e9), ("million", 1e6), ("bn", 1e9), ("mm", 1e6), ("m", 1e6), ("k", 1e3)):
        if cleaned.endswith(suffix):
            multiplier = factor
            cleaned = cleaned[: -len(suffix)].strip()
            break
    value = float(cleaned) * multiplier
    if percent:
        fraction = value / 100.0
        if notional is None:
            return None, fraction
        return fraction * notional, fraction
    return value, None
