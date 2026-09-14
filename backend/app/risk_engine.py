"""
Section 36 -- Risk Engine (REVISED), and Section 35.4's automatic-hold rule.

36.1 Combination formula:
    For each Category C in {SCHEDULE, RESOURCE, MACHINE_HEALTH, QUALITY}:
        CategoryScore(C) = MAX(score of every currently-active factor in C)
    RawScore = SUM over all categories C of CategoryScore(C)
    FinalScore = MIN(100, MAX(0, RawScore))
    Classification: 0-24 LOW, 25-49 MEDIUM, 50-74 HIGH, 75-100 CRITICAL

Factor scores are the illustrative examples from Table 20 of the spec, kept
here as configurable defaults (matching the "thresholds configurable, not
categories" instruction of Section 29/36).
"""
import json
import datetime as dt

from sqlalchemy.orm import Session as OrmSession

from . import models
from .config import settings

# Table 20 -- Risk Factor -> Category -> example score
FACTOR_DEFINITIONS = {
    "DEADLINE_CLOSE":            {"category": "SCHEDULE",       "score": 20},
    "PREDICTED_DEADLINE_MISS":   {"category": "SCHEDULE",       "score": 30},
    "MATERIAL_SHORTAGE":         {"category": "RESOURCE",       "score": 25},
    "OPERATOR_UNAVAILABLE":      {"category": "RESOURCE",       "score": 15},
    "MACHINE_FAULT":             {"category": "MACHINE_HEALTH", "score": 30},
    "MACHINE_WARNING":           {"category": "MACHINE_HEALTH", "score": 15},
    "HIGH_DEFECT_RATE":          {"category": "QUALITY",        "score": 20},
    "QUALITY_HOLD":              {"category": "QUALITY",        "score": 30},
}

# Section 35.4 -- these specific factors, when contributing to a CRITICAL
# classification for a ProductionRun, trigger an *automatic* hold rather than
# merely raising an alert, because they represent output that may already be
# unsafe/non-conforming.
AUTO_HOLD_FACTORS = {"MACHINE_FAULT", "QUALITY_HOLD", "PREDICTED_DEADLINE_MISS"}


def classify(score: int) -> str:
    for label, (lo, hi) in settings.RISK_THRESHOLDS.items():
        if lo <= score <= hi:
            return label
    return "CRITICAL" if score > 100 else "LOW"


def combine_factors(active_factors: list[str]) -> dict:
    """active_factors: list of FACTOR_DEFINITIONS keys currently active.
    Returns {score, classification, contributing_factors, auto_hold_trigger}."""
    by_category: dict[str, tuple[str, int]] = {}
    for code in active_factors:
        definition = FACTOR_DEFINITIONS.get(code)
        if not definition:
            continue
        cat = definition["category"]
        sc = definition["score"]
        if cat not in by_category or sc > by_category[cat][1]:
            by_category[cat] = (code, sc)

    raw_score = sum(sc for _, sc in by_category.values())
    final_score = max(0, min(100, raw_score))
    classification = classify(final_score)

    contributing = [
        {"category": cat, "factorCode": code, "score": sc}
        for cat, (code, sc) in by_category.items()
    ]

    auto_hold_trigger = None
    if classification == "CRITICAL":
        for cat, (code, sc) in by_category.items():
            if code in AUTO_HOLD_FACTORS:
                auto_hold_trigger = code
                break

    return {
        "score": final_score,
        "classification": classification,
        "contributing_factors": contributing,
        "auto_hold_trigger": auto_hold_trigger,
    }


def save_risk_score(db: OrmSession, entity_type: str, entity_id: str, result: dict) -> models.RiskScore:
    existing = (
        db.query(models.RiskScore)
        .filter(models.RiskScore.entity_type == entity_type, models.RiskScore.entity_id == entity_id)
        .first()
    )
    if existing is None:
        existing = models.RiskScore(entity_type=entity_type, entity_id=entity_id)
        db.add(existing)
    existing.score = result["score"]
    existing.classification = result["classification"]
    existing.calculated_at = dt.datetime.utcnow()
    existing.contributing_factors = json.dumps(result["contributing_factors"])
    return existing
