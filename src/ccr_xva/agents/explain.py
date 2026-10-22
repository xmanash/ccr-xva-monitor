"""Template answers. Every printed number is also returned as a claim."""

from __future__ import annotations

from ccr_xva.guardrails.grounding import claims_from_text
from ccr_xva.models.schemas import Citation, ExposureProfile, NumericClaim, XVAResult
from ccr_xva.services.risk import exposure_chart


def money(value: float) -> tuple[str, float]:
    rounded = round(float(value), 2)
    return f"{rounded:,.2f}", rounded


def _claim(name: str, value: float, source_id: str, source: str = "engine", unit: str = "USD") -> NumericClaim:
    return NumericClaim(name=name, value=value, unit=unit, source=source, source_id=source_id)


def exposure_answer(profile: ExposureProfile, counterparty_name: str) -> dict:
    peak_index = max(range(len(profile.pfe_95)), key=lambda index: profile.pfe_95[index])
    peak_text, peak_value = money(profile.pfe_95[peak_index])
    epe_text, epe_value = money(profile.epe)
    driver = profile.drivers[0] if profile.drivers else None
    claims = [
        _claim("peak_pfe_95", peak_value, profile.calculation_id),
        _claim("epe", epe_value, profile.calculation_id),
    ]
    driver_sentence = "No trade-level driver was available."
    if driver is not None:
        driver_text, driver_value = money(driver["standalone_ee_at_peak_pfe"])
        claims.append(_claim("driver_ee", driver_value, profile.calculation_id))
        driver_sentence = (
            f"The largest standalone driver before collateral is {driver['trade_id']} "
            f"({driver['product_type']}) at {driver_text} USD."
        )
    peak_date = profile.dates[peak_index]
    peak_date_text = peak_date.isoformat() if hasattr(peak_date, "isoformat") else str(peak_date)
    answer = (
        f"Peak PFE95 for {counterparty_name} on netting set {profile.netting_set_id} "
        f"is {peak_text} USD on {peak_date_text}. "
        f"Time-averaged expected positive exposure is {epe_text} USD. "
        f"{driver_sentence} "
        f"Calculation {profile.calculation_id}."
    )
    citations = [
        Citation(
            source="engine",
            source_id=profile.calculation_id,
            text="EE and PFE from Hull-White IRS revaluation and GBM FX forward revaluation.",
        )
    ]
    return {
        "answer": answer,
        "claims": claims,
        "citations": citations,
        "calculation_id": profile.calculation_id,
        "chart": exposure_chart(profile),
    }


def xva_answer(result: XVAResult, counterparty_name: str) -> dict:
    cva_text, cva_value = money(result.cva)
    total_text, total_value = money(result.total_xva)
    claims = [
        _claim("cva", cva_value, result.calculation_id),
        _claim("total_xva", total_value, result.calculation_id),
    ]
    extra = ""
    if result.dva is not None:
        dva_text, dva_value = money(result.dva)
        claims.append(_claim("dva", dva_value, result.calculation_id))
        extra += f" DVA is {dva_text} USD."
    if result.fva is not None:
        fva_text, fva_value = money(result.fva)
        claims.append(_claim("fva", fva_value, result.calculation_id))
        extra += f" Teaching FVA is {fva_text} USD."
    recovery_text, recovery_value = money(float(result.assumptions.get("recovery_rate", 0.0)))
    # Recovery is a rate, not a currency amount. Print the raw rounded decimal without thousands separators.
    recovery_value = round(float(result.assumptions.get("recovery_rate", 0.0)), 4)
    recovery_text = f"{recovery_value:.4f}"
    claims.append(_claim("recovery_rate", recovery_value, result.calculation_id, unit="rate"))
    answer = (
        f"Unilateral CVA for {counterparty_name} on netting set {result.netting_set_id} "
        f"is {cva_text} USD.{extra} "
        f"Total XVA using CVA minus DVA plus FVA is {total_text} USD. "
        f"Recovery rate assumption is {recovery_text}. "
        f"Calculation {result.calculation_id}."
    )
    return {
        "answer": answer,
        "claims": claims,
        "citations": [
            Citation(source="engine", source_id=result.calculation_id, text="CVA is a discounted default-probability bucket sum."),
        ],
        "calculation_id": result.calculation_id,
        "chart": None,
    }


def component_answer(result: XVAResult, counterparty_name: str, component: str) -> dict:
    """Quote one of CVA, DVA, or FVA. The engine still computes the full result."""
    value = getattr(result, component)
    label = component.upper()
    if value is None:
        return {
            "answer": f"{label} was not produced for {counterparty_name}.",
            "claims": [],
            "citations": [],
            "calculation_id": result.calculation_id,
            "chart": None,
        }
    text, rounded = money(value)
    return {
        "answer": (
            f"{label} for {counterparty_name} on netting set {result.netting_set_id} "
            f"is {text} USD. Calculation {result.calculation_id}."
        ),
        "claims": [_claim(component, rounded, result.calculation_id)],
        "citations": [
            Citation(source="engine", source_id=result.calculation_id, text=f"{label} from the unilateral XVA engine."),
        ],
        "calculation_id": result.calculation_id,
        "chart": None,
    }


def csa_answer(csa, counterparty_name: str) -> dict:
    if csa is None:
        return {
            "answer": f"No CSA is stored for {counterparty_name}.",
            "claims": [],
            "citations": [],
            "calculation_id": None,
            "chart": None,
        }
    threshold_text, threshold_value = money(csa.threshold)
    mta_text, mta_value = money(csa.mta)
    ia_text, ia_value = money(csa.independent_amount)
    claims = [
        _claim("threshold", threshold_value, csa.csa_id, source="memory"),
        _claim("mta", mta_value, csa.csa_id, source="memory"),
        _claim("independent_amount", ia_value, csa.csa_id, source="memory"),
    ]
    answer = (
        f"CSA {csa.csa_id} for {counterparty_name} on netting set {csa.netting_set_id} "
        f"is {csa.frequency} {csa.collateral_type.lower()} collateral. "
        f"Threshold is {threshold_text} USD. "
        f"Minimum transfer amount is {mta_text} USD. "
        f"Independent amount is {ia_text} USD."
    )
    return {
        "answer": answer,
        "claims": claims,
        "citations": [Citation(source="memory", source_id=csa.csa_id, text="Stored CSA terms.")],
        "calculation_id": None,
        "chart": None,
    }


def trend_answer(profile: ExposureProfile, counterparty_name: str) -> dict:
    peak_index = max(range(len(profile.pfe_95)), key=lambda index: profile.pfe_95[index])
    peak_text, peak_value = money(profile.pfe_95[peak_index])
    epe_text, epe_value = money(profile.epe)
    peak_date = profile.dates[peak_index]
    peak_date_text = peak_date.isoformat() if hasattr(peak_date, "isoformat") else str(peak_date)
    answer = (
        f"Exposure chart for {counterparty_name} on netting set {profile.netting_set_id} "
        f"plots EE, PFE95, and PFE99. "
        f"Peak PFE95 is {peak_text} USD on {peak_date_text}. "
        f"Time-averaged expected positive exposure is {epe_text} USD. "
        f"Calculation {profile.calculation_id}."
    )
    return {
        "answer": answer,
        "claims": [
            _claim("peak_pfe_95", peak_value, profile.calculation_id),
            _claim("epe", epe_value, profile.calculation_id),
        ],
        "citations": [
            Citation(source="engine", source_id=profile.calculation_id, text="Exposure paths plotted as EE, PFE95, and PFE99."),
        ],
        "calculation_id": profile.calculation_id,
        "chart": exposure_chart(profile),
    }


def what_if_answer(base: XVAResult, shocked: XVAResult, counterparty_name: str, threshold: float | None) -> dict:
    base_text, base_value = money(base.cva)
    shocked_text, shocked_value = money(shocked.cva)
    delta_text, delta_value = money(shocked.cva - base.cva)
    claims = [
        _claim("base_cva", base_value, base.calculation_id),
        _claim("shocked_cva", shocked_value, shocked.calculation_id),
        _claim("cva_change", delta_value, shocked.calculation_id),
    ]
    threshold_sentence = ""
    if threshold is not None:
        threshold_text, threshold_value = money(threshold)
        claims.append(_claim("threshold", threshold_value, shocked.calculation_id))
        threshold_sentence = f" Shocked collateral threshold is {threshold_text} USD."
    recovery_value = round(float(shocked.assumptions.get("recovery_rate", 0.0)), 4)
    claims.append(_claim("recovery_rate", recovery_value, shocked.calculation_id, unit="rate"))
    answer = (
        f"Base CVA for {counterparty_name} is {base_text} USD. "
        f"Shocked CVA is {shocked_text} USD. "
        f"The change is {delta_text} USD.{threshold_sentence} "
        f"Recovery rate used for the shock is {recovery_value:.4f}. "
        f"Calculation {shocked.calculation_id}."
    )
    return {
        "answer": answer,
        "claims": claims,
        "citations": [
            Citation(source="engine", source_id=base.calculation_id, text="Base XVA."),
            Citation(source="engine", source_id=shocked.calculation_id, text="Shocked XVA."),
        ],
        "calculation_id": shocked.calculation_id,
        "chart": None,
    }


def sensitivity_answer(base: XVAResult, shocked: XVAResult, bump: float, counterparty_name: str) -> dict:
    base_text, base_value = money(base.cva)
    shocked_text, shocked_value = money(shocked.cva)
    delta_text, delta_value = money(shocked.cva - base.cva)
    bump_value = round(float(bump), 4)
    claims = [
        _claim("base_cva", base_value, base.calculation_id),
        _claim("shocked_cva", shocked_value, shocked.calculation_id),
        _claim("cva_change", delta_value, shocked.calculation_id),
        _claim("relative_vol_bump", bump_value, shocked.calculation_id, unit="relative"),
    ]
    answer = (
        f"Base CVA for {counterparty_name} is {base_text} USD. "
        f"CVA after a relative volatility bump of {bump_value:.4f} is {shocked_text} USD. "
        f"The change is {delta_text} USD. "
        f"Calculation {shocked.calculation_id}."
    )
    return {
        "answer": answer,
        "claims": claims,
        "citations": [
            Citation(source="engine", source_id=shocked.calculation_id, text="Finite-difference volatility bump on Hull-White sigma and FX vols."),
        ],
        "calculation_id": shocked.calculation_id,
        "chart": None,
    }


def ranking_answer(rows: list[dict]) -> dict:
    claims: list[NumericClaim] = []
    parts = []
    citations = []
    for row in rows:
        peak_text, peak_value = money(row["peak_pfe"])
        claims.append(_claim("peak_pfe_95", peak_value, row["calculation_id"]))
        citations.append(Citation(source="engine", source_id=row["calculation_id"], text=row["name"]))
        driver = row.get("driver")
        driver_bit = ""
        if driver:
            driver_text, driver_value = money(driver["standalone_ee_at_peak_pfe"])
            claims.append(_claim("driver_ee", driver_value, row["calculation_id"]))
            driver_bit = f" Largest standalone driver is {driver['trade_id']} at {driver_text} USD."
        parts.append(
            f"{row['name']} peak PFE95 is {peak_text} USD on netting set {row['netting_set_id']}.{driver_bit}"
        )
    answer = "Ranked by peak PFE95. " + " ".join(parts)
    calculation_id = rows[0]["calculation_id"] if rows else None
    return {
        "answer": answer,
        "claims": claims,
        "citations": citations,
        "calculation_id": calculation_id,
        "chart": None,
    }


def credit_ranking_answer(rows: list[dict]) -> dict:
    claims: list[NumericClaim] = []
    parts = []
    citations = []
    for row in rows:
        cva_text, cva_value = money(row["cva"])
        pfe_text, pfe_value = money(row["peak_pfe"])
        claims.append(_claim("cva", cva_value, row["calculation_id"]))
        claims.append(_claim("peak_pfe_95", pfe_value, row["calculation_id"]))
        citations.append(Citation(source="engine", source_id=row["calculation_id"], text=row["name"]))
        rating = row.get("rating")
        rating_bit = f" Rating {rating}." if rating else ""
        parts.append(
            f"{row['name']} unilateral CVA is {cva_text} USD and peak PFE95 is {pfe_text} USD "
            f"on netting set {row['netting_set_id']}.{rating_bit}"
        )
    answer = "Ranked by unilateral CVA for the counterparties stored on this desk. " + " ".join(parts)
    return {
        "answer": answer,
        "claims": claims,
        "citations": citations,
        "calculation_id": rows[0]["calculation_id"],
        "chart": None,
    }


def compare_answer(name: str, earlier: dict, later: dict) -> dict:
    earlier_text, earlier_value = money(earlier["peak_pfe"])
    later_text, later_value = money(later["peak_pfe"])
    delta_text, delta_value = money(later["peak_pfe"] - earlier["peak_pfe"])
    claims = [
        _claim("earlier_peak_pfe", earlier_value, earlier["calculation_id"], source="memory"),
        _claim("later_peak_pfe", later_value, later["calculation_id"], source="memory"),
        _claim("pfe_change", delta_value, later["calculation_id"], source="memory"),
    ]
    answer = (
        f"Stored peak PFE95 for {name} on {earlier['as_of']} is {earlier_text} USD. "
        f"Stored peak PFE95 on {later['as_of']} is {later_text} USD. "
        f"The change is {delta_text} USD."
    )
    return {
        "answer": answer,
        "claims": claims,
        "citations": [
            Citation(source="memory", source_id=earlier["calculation_id"], text="Earlier exposure snapshot."),
            Citation(source="memory", source_id=later["calculation_id"], text="Later exposure snapshot."),
        ],
        "calculation_id": later["calculation_id"],
        "chart": None,
    }


def memory_answer(label: str, episodes: list) -> dict:
    """Quote the latest stored snapshot. Message text is not copied, so old numbers are not reintroduced."""
    if not episodes:
        return {
            "answer": f"No exposure or XVA snapshot is stored for {label}.",
            "claims": [],
            "citations": [],
            "calculation_id": None,
            "chart": None,
        }
    latest = episodes[-1]
    claims = []
    sentences = [f"Latest stored snapshot for {label} is {latest.label} on {latest.as_of.isoformat()}."]
    if latest.peak_pfe is not None:
        peak_text, peak_value = money(latest.peak_pfe)
        claims.append(_claim("peak_pfe", peak_value, latest.calculation_id, source="memory"))
        sentences.append(f"Stored peak PFE is {peak_text} USD.")
    if latest.cva is not None:
        cva_text, cva_value = money(latest.cva)
        claims.append(_claim("cva", cva_value, latest.calculation_id, source="memory"))
        sentences.append(f"Stored CVA is {cva_text} USD.")
    return {
        "answer": " ".join(sentences),
        "claims": claims,
        "citations": [Citation(source="memory", source_id=latest.calculation_id, text=latest.summary or latest.label)],
        "calculation_id": latest.calculation_id,
        "chart": None,
    }


def retrieval_answer(hits: list[dict]) -> dict:
    if not hits:
        return {
            "answer": "No methodology notes matched that question.",
            "claims": [],
            "citations": [],
            "calculation_id": None,
            "chart": None,
        }
    top = hits[0]
    section = top.get("title") or ""
    source_line = f"Source {top['source']}"
    if section:
        source_line = f"{source_line}, section {section}"
    answer = f"{source_line}. {top['text']}"
    return {
        "answer": answer,
        "claims": claims_from_text(top["text"], top["id"]),
        "citations": [Citation(source="retrieval", source_id=top["id"], text=top["text"][:500])],
        "calculation_id": None,
        "chart": None,
    }
