"""Monitor Results - did the prevention recommendation actually reduce recurrence?

Two halves:

* `resolve_outcomes()` closes the loop on individual `PreventionCheck` rows: a check whose PRO
  produced no overage inside the observation window counts as 'prevented', one that did counts
  as 'recurred'.
* `evaluate_recommendation_effectiveness()` judges a whole `Recommendation` on exception volume
  in its cohort before vs. after it was generated. A recommendation that did not move the
  number is marked ineffective and escalated - the *existing* recommender writes the
  replacement, and after the escalation ceiling the answer stops being another nudge and
  becomes a tier-3 attention flag.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.recommender import generate_recommendations
from app.analytics import InsightFilters, load_dataframe
from app.models import (
    OVException,
    PreventionCheck,
    PreventionOutcome,
    Recommendation,
    RecommendationStatus,
    utcnow,
)
from app.prevention import attention

DEFAULT_WINDOW_DAYS = 30
# Fewer exceptions than this before the recommendation and there is nothing to improve on.
MIN_BASELINE = 2
# A cohort has to drop by at least this share to count as a real improvement.
DEFAULT_IMPROVEMENT_THRESHOLD = 0.20
DEFAULT_ESCALATION_CEILING = 2
MIN_CHECKS_FOR_RATE = 3


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def resolve_outcomes(db: Session, *, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Pending prevention checks -> prevented / recurred once the window has elapsed."""
    now = utcnow()
    prevented = 0
    recurred = 0

    pending = db.scalars(
        select(PreventionCheck).where(PreventionCheck.outcome == PreventionOutcome.pending)
    ).all()

    for check in pending:
        performed = _as_utc(check.performed_at)
        follow_up = db.scalar(
            select(OVException.id)
            .where(
                OVException.pro_number == check.pro_number,
                OVException.created_at >= check.performed_at,
            )
            .limit(1)
        )
        if follow_up is not None:
            check.outcome = PreventionOutcome.recurred
            recurred += 1
        elif now >= performed + timedelta(days=window_days):
            check.outcome = PreventionOutcome.prevented
            prevented += 1

    db.commit()
    return {
        "resolved_at": now,
        "window_days": window_days,
        "pending_considered": len(pending),
        "prevented": prevented,
        "recurred": recurred,
    }


def _cohort_mask(df: pd.DataFrame, rec: Recommendation) -> pd.Series:
    """Same cohort shape risk.py/analytics use: category, terminal (origin OR dest), commodity."""
    scope = rec.scope or {}
    mask = df["category"] == rec.category
    terminal = scope.get("terminal")
    commodity = scope.get("commodity")
    if terminal:
        mask &= (df["origin_terminal"] == terminal) | (df["destination_terminal"] == terminal)
    if commodity:
        mask &= df["commodity_code"] == commodity
    return mask


def _check_rates(db: Session, rec: Recommendation) -> dict:
    scope = rec.scope or {}
    stmt = select(PreventionCheck).where(
        PreventionCheck.outcome != PreventionOutcome.pending,
        PreventionCheck.performed_at >= rec.generated_at,
    )
    if scope.get("terminal"):
        stmt = stmt.where(PreventionCheck.terminal == scope["terminal"])
    if scope.get("commodity"):
        stmt = stmt.where(PreventionCheck.commodity_code == scope["commodity"])
    rows = db.scalars(stmt).all()

    prevented = sum(1 for r in rows if r.outcome == PreventionOutcome.prevented)
    total = len(rows)
    return {
        "resolved_checks": total,
        "prevented": prevented,
        "recurred": total - prevented,
        "prevented_rate": round(prevented / total, 4) if total else None,
    }


def _measure(db: Session, df: pd.DataFrame, rec: Recommendation, window_days: int) -> dict:
    generated = _as_utc(rec.generated_at)
    start = generated - timedelta(days=window_days)
    end = generated + timedelta(days=window_days)

    cohort = df[_cohort_mask(df, rec)] if not df.empty else df
    if cohort.empty:
        before = after = 0
    else:
        created = cohort["created_at"].map(_as_utc)
        before = int(((created >= start) & (created < generated)).sum())
        after = int(((created >= generated) & (created <= end)).sum())

    improvement = (before - after) / before if before else (0.0 if after else 1.0)
    return {
        "before": before,
        "after": after,
        "improvement": round(float(improvement), 4),
        "checks": _check_rates(db, rec),
    }


def _is_effective(measurement: dict, threshold: float) -> bool:
    if measurement["improvement"] >= threshold:
        return True
    checks = measurement["checks"]
    # A strong prevention-check record can carry a recommendation whose volume barely moved.
    return (
        checks["resolved_checks"] >= MIN_CHECKS_FOR_RATE
        and (checks["prevented_rate"] or 0.0) >= 1 - threshold
    )


def evaluate_recommendation_effectiveness(
    db: Session,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    improvement_threshold: float = DEFAULT_IMPROVEMENT_THRESHOLD,
    escalation_ceiling: int = DEFAULT_ESCALATION_CEILING,
) -> dict:
    now = utcnow()
    cutoff = now - timedelta(days=window_days)

    candidates = db.scalars(
        select(Recommendation)
        .where(
            Recommendation.status == RecommendationStatus.active,
            Recommendation.generated_at <= cutoff,
        )
        .order_by(Recommendation.generated_at)
    ).all()

    df = load_dataframe(db, InsightFilters(days=None))
    evaluated: list[dict] = []
    effective = ineffective = escalated = flagged = 0

    for rec in candidates:
        measurement = _measure(db, df, rec, window_days)
        entry = {
            "recommendation_id": str(rec.id),
            "category": rec.category,
            "scope": rec.scope,
            "escalation_level": rec.escalation_level,
            **measurement,
        }

        if measurement["before"] < MIN_BASELINE and measurement["after"] == 0:
            entry["verdict"] = "insufficient_evidence"
            evaluated.append(entry)
            continue

        if _is_effective(measurement, improvement_threshold):
            rec.status = RecommendationStatus.effective
            entry["verdict"] = "effective"
            effective += 1
            evaluated.append(entry)
            continue

        rec.status = RecommendationStatus.ineffective
        ineffective += 1

        if rec.escalation_level >= escalation_ceiling:
            # More point-of-process wording is not the answer at this point - escalate to tier 3.
            scope_value = (rec.scope or {}).get("terminal")
            if scope_value:
                attention.ensure_flag(
                    db,
                    scope_type="terminal",
                    scope_value=scope_value,
                    category=rec.category,
                    pattern_summary=(
                        f"{rec.escalation_level + 1} prevention recommendations for {rec.category} at "
                        f"{scope_value} have not reduced recurrence "
                        f"({measurement['before']} → {measurement['after']} in {window_days} days). "
                        "Point-of-process guidance is not working; this needs training or a "
                        "structural change."
                    ),
                    supporting_exception_ids=[str(v) for v in (rec.supporting_exception_ids or [])],
                )
                flagged += 1
                entry["verdict"] = "ceiling_reached_flagged"
            else:
                entry["verdict"] = "ceiling_reached_no_terminal_scope"
            evaluated.append(entry)
            continue

        scope = rec.scope or {}
        replacement = _escalate(db, rec, scope)
        if replacement is None:
            entry["verdict"] = "ineffective_no_replacement"
        else:
            escalated += 1
            entry["verdict"] = "escalated"
            entry["superseded_by_id"] = str(replacement.id)
            entry["new_escalation_level"] = replacement.escalation_level
        evaluated.append(entry)

    db.commit()
    return {
        "evaluated_at": now,
        "window_days": window_days,
        "improvement_threshold": improvement_threshold,
        "escalation_ceiling": escalation_ceiling,
        "considered": len(candidates),
        "effective": effective,
        "ineffective": ineffective,
        "escalated": escalated,
        "attention_flags_raised": flagged,
        "results": evaluated,
    }


def _escalate(db: Session, rec: Recommendation, scope: dict) -> Recommendation | None:
    """Reuse recommender.py for the replacement - there is no second generation path."""
    filters = InsightFilters(terminal=scope.get("terminal"), commodity_code=scope.get("commodity"), days=None)
    rows = generate_recommendations(db, filters)
    if not rows:
        return None
    replacement = next((r for r in rows if r.category == rec.category), rows[0])
    replacement.escalation_level = rec.escalation_level + 1
    rec.superseded_by_id = replacement.id
    db.flush()
    return replacement


def lineage(db: Session, rec: Recommendation) -> dict:
    """Walk the supersede chain both ways: 'rec 1 → didn't work → rec 2 (current)'."""

    def _brief(row: Recommendation) -> dict:
        return {
            "id": str(row.id),
            "category": row.category,
            "scope": row.scope,
            "recommendation_text": row.recommendation_text,
            "pattern_addressed": row.pattern_addressed,
            "status": row.status.value,
            "escalation_level": row.escalation_level,
            "superseded_by_id": str(row.superseded_by_id) if row.superseded_by_id else None,
            "generated_at": row.generated_at,
        }

    seen: set[uuid.UUID] = {rec.id}

    ancestors: list[Recommendation] = []
    cursor = rec
    while True:
        parent = db.scalar(select(Recommendation).where(Recommendation.superseded_by_id == cursor.id).limit(1))
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        ancestors.append(parent)
        cursor = parent
    ancestors.reverse()

    descendants: list[Recommendation] = []
    cursor = rec
    while cursor.superseded_by_id is not None:
        child = db.get(Recommendation, cursor.superseded_by_id)
        if child is None or child.id in seen:
            break
        seen.add(child.id)
        descendants.append(child)
        cursor = child

    chain = [*ancestors, rec, *descendants]
    return {
        "recommendation_id": str(rec.id),
        "position": len(ancestors) + 1,
        "length": len(chain),
        "escalated": len(chain) > 1,
        "current_id": str(chain[-1].id),
        "chain": [_brief(row) for row in chain],
    }
