"""Persist every calculation locally and optionally export it to Langfuse."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ccr_xva.models.schemas import CalculationTrace
from shared.settings import Settings

logger = logging.getLogger(__name__)


def build_trace(calculation_id: str, kind: str, inputs: dict, outputs: dict, steps: list[str]) -> CalculationTrace:
    return CalculationTrace(
        calculation_id=calculation_id,
        kind=kind,
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


def export_langfuse(trace: CalculationTrace, settings: Settings) -> bool:
    """Best-effort export. Local SQLite remains the source of truth."""
    if not settings.langfuse_host or not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return False
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse is not installed; trace %s stayed in SQLite", trace.calculation_id)
        return False
    try:
        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        client.trace(
            id=trace.calculation_id,
            name=trace.kind,
            input=trace.inputs,
            output=trace.outputs,
            metadata={"steps": trace.steps},
        )
        client.flush()
        return True
    except Exception:
        logger.warning("Langfuse export failed for %s", trace.calculation_id, exc_info=True)
        return False
