"""Every number in an answer must match a claim from the engine, memory, or a citation."""

from __future__ import annotations

import re

from ccr_xva.models.schemas import NumericClaim

ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
HEX_ID = re.compile(r"\b[a-f0-9]{8,}\b", re.IGNORECASE)
IDENTIFIER = re.compile(r"\b[A-Za-z]{1,16}-?\d+\b")
NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def extract_numbers(text: str) -> list[float]:
    cleaned = ISO_DATE.sub(" ", text)
    cleaned = HEX_ID.sub(" ", cleaned)
    cleaned = IDENTIFIER.sub(" ", cleaned)
    found: list[float] = []
    for match in NUMBER.finditer(cleaned):
        token = match.group(0)
        percent = token.endswith("%")
        value = float(token.replace("%", "").replace(",", ""))
        found.append(value / 100.0 if percent else value)
        if percent:
            found.append(value)
    return found


def _close(left: float, right: float) -> bool:
    if abs(left - right) <= 1e-4:
        return True
    scale = max(abs(right), 1e-12)
    return abs(left - right) / scale <= 1e-6


def ungrounded_numbers(text: str, claims: list[NumericClaim]) -> list[float]:
    allowed = [claim.value for claim in claims]
    missing = []
    for number in extract_numbers(text):
        if not any(_close(number, candidate) for candidate in allowed):
            missing.append(number)
    return missing


def claims_from_text(text: str, source_id: str) -> list[NumericClaim]:
    return [
        NumericClaim(name="quoted", value=number, unit="text", source="retrieval", source_id=source_id)
        for number in extract_numbers(text)
    ]
