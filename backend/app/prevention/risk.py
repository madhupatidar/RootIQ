"""Tier 1 - what to watch, before freight is handled.

Answers "which root causes are currently concentrated on this terminal / lane / commodity,
and what should the dock do about them" - so the exception never gets created. It is a
*lookup* against history the classifier already produced, not a new inference: the expensive
part (classifying every past exception) ran offline, so this stays a sub-second query with
no Ollama call.

Deliberately not wired into the exception form: by the time an OV exception is being logged
the overage has already happened, and a warning there prevents nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import InsightFilters, load_dataframe
from app.models import AttentionFlag, FlagStatus, Recommendation, utcnow
from app.prevention import playbook

# A cohort smaller than this is noise, not a pattern.
MIN_COHORT = 4
MIN_COUNT = 2
SHARE_FLOOR = 0.25
LIFT_FLOOR = 1.15
# A cause this dominant is worth surfacing even when the network baseline is just as skewed.
DOMINANT_SHARE = 0.50

SEVERITY_ORDER = {"clear": 0, "watch": 1, "elevated": 2, "high": 3}


@dataclass(slots=True)
class WatchContext:
    origin_terminal: str | None = None
    destination_terminal: str | None = None
    commodity_code: str | None = None
    package_type: str | None = None
    value_range: int | None = None
    hazmat: bool = False
    shrink_wrapped: bool = True
    handler: str | None = None

    def as_scope(self) -> dict:
        return {
            "origin_terminal": self.origin_terminal,
            "destination_terminal": self.destination_terminal,
            "commodity_code": self.commodity_code,
            "package_type": self.package_type,
            "value_range": self.value_range,
        }


@dataclass(slots=True)
class _Cohort:
    key: str
    label: str
    description: str
    specificity: int
    mask: pd.Series = field(repr=False)


def _cohorts(df: pd.DataFrame, ctx: WatchContext) -> list[_Cohort]:
    out: list[_Cohort] = []
    if ctx.origin_terminal and ctx.commodity_code:
        out.append(
            _Cohort(
                key="terminal_commodity",
                label=f"{ctx.origin_terminal} · {ctx.commodity_code}",
                description=f"this commodity handled at {ctx.origin_terminal}",
                specificity=4,
                mask=(df["origin_terminal"] == ctx.origin_terminal) & (df["commodity_code"] == ctx.commodity_code),
            )
        )
    if ctx.origin_terminal and ctx.destination_terminal:
        out.append(
            _Cohort(
                key="lane",
                label=f"{ctx.origin_terminal} → {ctx.destination_terminal}",
                description=f"the {ctx.origin_terminal} → {ctx.destination_terminal} lane",
                specificity=3,
                mask=(df["origin_terminal"] == ctx.origin_terminal)
                & (df["destination_terminal"] == ctx.destination_terminal),
            )
        )
    if ctx.commodity_code:
        out.append(
            _Cohort(
                key="commodity",
                label=str(ctx.commodity_code),
                description=f"commodity {ctx.commodity_code} network-wide",
                specificity=2,
                mask=df["commodity_code"] == ctx.commodity_code,
            )
        )
    if ctx.origin_terminal:
        out.append(
            _Cohort(
                key="terminal",
                label=str(ctx.origin_terminal),
                description=f"terminal {ctx.origin_terminal}",
                specificity=2,
                mask=df["origin_terminal"] == ctx.origin_terminal,
            )
        )
    if ctx.package_type:
        out.append(
            _Cohort(
                key="package_type",
                label=str(ctx.package_type),
                description=f"{ctx.package_type} freight network-wide",
                specificity=1,
                mask=df["package_type"] == ctx.package_type,
            )
        )
    return out


def _severity(share: float, lift: float, count: int) -> str:
    if share >= 0.45 and count >= 3 and lift >= 1.3:
        return "high"
    if share >= 0.30 or lift >= 1.50:
        return "elevated"
    return "watch"


def _recommendation_index(db: Session) -> dict[str, Recommendation]:
    rows = db.scalars(select(Recommendation).order_by(Recommendation.generated_at.desc())).all()
    index: dict[str, Recommendation] = {}
    for rec in rows:
        index.setdefault(rec.category, rec)
    return index


def _open_flags(db: Session, ctx: WatchContext) -> list[AttentionFlag]:
    scopes = [v for v in (ctx.origin_terminal, ctx.handler) if v]
    if not scopes:
        return []
    return list(
        db.scalars(
            select(AttentionFlag)
            .where(AttentionFlag.scope_value.in_(scopes))
            .where(AttentionFlag.status != FlagStatus.resolved)
            .order_by(AttentionFlag.last_detected_at.desc())
        ).all()
    )


def evaluate(db: Session, ctx: WatchContext, *, days: int | None = 365, max_signals: int = 3) -> dict:
    df = load_dataframe(db, InsightFilters(days=days))
    total = int(len(df))

    result: dict = {
        "evaluated_at": utcnow(),
        "scope": ctx.as_scope(),
        "population": {"classified_exceptions": total, "window_days": days},
        "risk_level": "clear",
        "signals": [],
        "actions": [],
        "open_flags": [],
        "clear": True,
        "message": "",
        "advisory": True,
    }

    if total < MIN_COHORT:
        result["message"] = (
            "Not enough classified history yet to say what to watch for on this scope."
        )
        return result

    baseline = df["category"].value_counts(normalize=True).to_dict()

    # Best (most specific, then strongest) signal per category.
    best: dict[str, dict] = {}
    for cohort in _cohorts(df, ctx):
        subset = df[cohort.mask]
        cohort_size = int(len(subset))
        if cohort_size < MIN_COHORT:
            continue
        for category, count in subset["category"].value_counts().items():
            count = int(count)
            share = count / cohort_size
            base_share = float(baseline.get(category, 0.0)) or 1e-6
            lift = share / base_share
            outlier = share >= SHARE_FLOOR and lift >= LIFT_FLOOR
            dominant = share >= DOMINANT_SHARE and count >= 3
            if count < MIN_COUNT or not (outlier or dominant):
                continue
            signal = {
                "cohort": cohort.key,
                "cohort_label": cohort.label,
                "cohort_size": cohort_size,
                "category": str(category),
                "count": count,
                "share": round(share * 100, 1),
                "baseline_share": round(base_share * 100, 1),
                "lift": round(lift, 2),
                "severity": _severity(share, lift, count),
                "pattern": (
                    f"{count} of the last {cohort_size} classified overages on "
                    f"{cohort.description} were {category} ({round(share * 100)}% vs "
                    f"{round(base_share * 100)}% network-wide)."
                ),
                "specificity": cohort.specificity,
                "supporting_exception_ids": [
                    str(v) for v in subset.loc[subset["category"] == category, "exception_id"].head(15).tolist()
                ],
            }
            current = best.get(str(category))
            if current is None or (signal["specificity"], signal["lift"]) > (
                current["specificity"],
                current["lift"],
            ):
                best[str(category)] = signal

    signals = sorted(
        best.values(),
        key=lambda s: (SEVERITY_ORDER[s["severity"]], s["specificity"], s["lift"]),
        reverse=True,
    )[:max_signals]

    recs = _recommendation_index(db)
    actions: list[dict] = []
    seen_actions: set[str] = set()
    for signal in signals:
        rec = recs.get(signal["category"])
        signal["prevention_action"] = rec.recommendation_text if rec else None
        signal["recommendation_id"] = str(rec.id) if rec else None
        signal.pop("specificity", None)
        for action in playbook.floor_actions(signal["category"]):
            if action["key"] in seen_actions:
                continue
            seen_actions.add(action["key"])
            actions.append({**action, "category": signal["category"]})

    flags = _open_flags(db, ctx)
    result["open_flags"] = [
        {
            "id": str(flag.id),
            "scope_type": flag.scope_type,
            "scope_value": flag.scope_value,
            "category": flag.category,
            "severity": flag.severity,
            "status": flag.status.value,
            "suggested_action": flag.suggested_action,
        }
        for flag in flags
    ]

    result["signals"] = signals
    result["actions"] = actions
    result["clear"] = not signals
    if signals:
        result["risk_level"] = max(signals, key=lambda s: SEVERITY_ORDER[s["severity"]])["severity"]
        lead = signals[0]
        result["message"] = (
            f"Known pattern on {lead['cohort_label']}: {lead['category']}. "
            f"Work the actions below on the freight that is still moving."
        )
    else:
        result["message"] = (
            "No root cause is concentrated on this scope — nothing specific to watch for today."
        )
    return result
