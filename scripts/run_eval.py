"""Run the local evaluation suite and write data/eval_report.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ccr_xva.evals.failures import failure_report  # noqa: E402
from ccr_xva.evals.suite import fx_closed_form_error, run_suite  # noqa: E402
from ccr_xva.memory.repository import get_repository  # noqa: E402
from ccr_xva.services.risk import RiskService  # noqa: E402
from shared.settings import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    service = RiskService(get_repository(settings.database_url), settings)
    report = {
        "short_suite": run_suite(),
        "fx_closed_form": fx_closed_form_error(8000),
        "failure_set": failure_report(service),
    }
    path = ROOT / "data" / "eval_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
