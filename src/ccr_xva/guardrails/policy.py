"""Scope and prompt-injection checks. These are product policies, not a security boundary."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache
def _rules() -> dict:
    path = Path(__file__).with_name("policy.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_query(query: str) -> str | None:
    """Return a refusal reason, or None when the query may proceed."""
    text = query.lower()
    rules = _rules()
    for needle in rules.get("injection_if", []):
        if needle in text:
            return "The query looks like an attempt to override the assistant instructions."
    for rule in rules.get("refuse_if", []):
        if re.search(rule["pattern"], text):
            return rule["reason"]
    return None
