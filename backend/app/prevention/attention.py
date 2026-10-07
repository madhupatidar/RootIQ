"""Tier 3 - attention & training signals.

Aggregates root causes by *terminal* and by *handler* and raises a distinct flag when the same
category breaches a threshold in consecutive periods. A flag is not a generic recommendation:
it names a scope, carries a concrete suggested action and is addressed to a supervisor who can
acknowledge or resolve it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import InsightFilters, load_dataframe
from app.models import AttentionFlag, FlagStatus, OVException, utcnow
from app.prevention import playbook

DEFAULT_WINDOW_DAYS = 30
DEFAULT_PERIODS = 3
DEFAULT_THRESHOLD = 3
DEFAULT_MIN_CONSECUTIVE = 2

# scope_type -> dataframe column
SCOPES: dict[str, str] = {"terminal": "origin_terminal", "handler": "entry_user"}

MAX_SUPPORTING = 40


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _scope_label(scope_type: str, scope_value: str) -> str:
    return f"Terminal {scope_value}" if scope_type == "terminal" else f"Handler {scope_value}"


def _active_flag(db: Session, scope_type: str, scope_value: str, category: str) -> AttentionFlag | None:
    return db.scalar(
        select(AttentionFlag)
        .where(
            AttentionFlag.scope_type == scope_type,
            AttentionFlag.scope_value == scope_value,
            AttentionFlag.category == category,
            AttentionFlag.status != FlagStatus.resolved,
        )
        .order_by(AttentionFlag.last_detected_at.desc())
        .limit(1)
    )


def _last_resolved(db: Session, scope_type: str, scope_value: str, category: str) -> AttentionFlag | None:
    return db.scalar(
        select(AttentionFlag)
        .where(
            AttentionFlag.scope_type == scope_type,
            AttentionFlag.scope_value == scope_value,
            AttentionFlag.category == category,
            AttentionFlag.status == FlagStatus.resolved,
        )
        .order_by(AttentionFlag.resolved_at.desc())
        .limit(1)
    )


def scan(
    db: Session,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    periods: int = DEFAULT_PERIODS,
    threshold: int = DEFAULT_THRESHOLD,
    min_consecutive: int = DEFAULT_MIN_CONSECUTIVE,
) -> dict:
    now = utcnow()
    df = load_dataframe(db, InsightFilters(days=None))

    rows = [dict(row, created_at=_as_utc(row["created_at"])) for row in df.to_dict(orient="records")]
    window_seconds = window_days * 86400
    # Anchor on the newest classified exception when the data snapshot is stale, otherwise a
    # historical export would always land outside period 0 and never flag anything.
    latest = max((row["created_at"] for row in rows), default=now)
    anchor = latest if (now - latest).total_seconds() > window_seconds else now

    # (scope_type, scope_value, category) -> period index -> [(exception_id, created_at)]
    buckets: dict[tuple[str, str, str], dict[int, list[tuple[str, datetime]]]] = {}
    for row in rows:
        created = row["created_at"]
        period = int((anchor - created).total_seconds() // window_seconds)
        if period < 0 or period >= periods:
            continue
        for scope_type, column in SCOPES.items():
            scope_value = row.get(column)
            if not scope_value:
                continue
            key = (scope_type, str(scope_value), str(row["category"]))
            buckets.setdefault(key, {}).setdefault(period, []).append((str(row["exception_id"]), created))

    created_count = 0
    updated_count = 0
    breaching: set[tuple[str, str, str]] = set()

    for key, by_period in buckets.items():
        scope_type, scope_value, category = key
        counts = {period: len(items) for period, items in by_period.items()}

        consecutive = 0
        while counts.get(consecutive, 0) >= threshold:
            consecutive += 1
        if consecutive < min_consecutive:
            continue

        breaching.add(key)
        supporting = [
            item for period in range(consecutive) for item in sorted(by_period.get(period, []), key=lambda p: p[1])
        ]
        supporting_ids = [exception_id for exception_id, _ in supporting][:MAX_SUPPORTING]
        newest_created = max((created for _, created in supporting), default=now)

        period_counts = [counts.get(period, 0) for period in range(periods)]
        current = period_counts[0]
        previous = period_counts[1] if periods > 1 else 0
        severity = "high" if consecutive >= 3 or current >= threshold * 2 else "watch"
        summary = (
            f"{_scope_label(scope_type, scope_value)} recorded {current} {category} overages in the last "
            f"{window_days} days and {previous} in the {window_days} days before that — "
            f"{consecutive} consecutive periods at or above the threshold of {threshold}."
        )
        action = playbook.training_action(category, scope_type, scope_value)

        flag = _active_flag(db, scope_type, scope_value, category)
        if flag is None:
            resolved = _last_resolved(db, scope_type, scope_value, category)
            if resolved is not None and resolved.resolved_at is not None:
                if newest_created <= _as_utc(resolved.resolved_at):
                    # Nothing new since the supervisor closed it - leave it closed.
                    continue
            flag = AttentionFlag(
                scope_type=scope_type,
                scope_value=scope_value,
                category=category,
                first_detected_at=now,
            )
            db.add(flag)
            created_count += 1
        else:
            updated_count += 1

        flag.severity = severity
        flag.window_days = window_days
        flag.threshold = threshold
        flag.consecutive_periods = consecutive
        flag.period_counts = period_counts
        flag.current_period_count = current
        flag.previous_period_count = previous
        flag.total_count = sum(period_counts)
        flag.pattern_summary = summary
        flag.suggested_action = action
        flag.supporting_exception_ids = supporting_ids
        flag.last_detected_at = now

    # A flag that stopped breaching is a win: close it out rather than leaving it to rot.
    cleared = 0
    for flag in db.scalars(select(AttentionFlag).where(AttentionFlag.status != FlagStatus.resolved)).all():
        if (flag.scope_type, flag.scope_value, flag.category) in breaching:
            continue
        flag.status = FlagStatus.resolved
        flag.resolved_at = now
        flag.resolved_by = "auto"
        flag.resolution_note = (
            f"Pattern cleared: no longer at or above {flag.threshold} {flag.category} overages per "
            f"{flag.window_days}-day period."
        )
        cleared += 1

    db.commit()

    return {
        "scanned_at": now,
        "anchored_at": anchor,
        "window_days": window_days,
        "periods": periods,
        "threshold": threshold,
        "min_consecutive": min_consecutive,
        "created": created_count,
        "updated": updated_count,
        "cleared": cleared,
        "flags": list_flags(db),
    }


def ensure_flag(
    db: Session,
    *,
    scope_type: str,
    scope_value: str,
    category: str,
    pattern_summary: str,
    severity: str = "high",
    window_days: int = DEFAULT_WINDOW_DAYS,
    threshold: int = DEFAULT_THRESHOLD,
    supporting_exception_ids: list[str] | None = None,
) -> AttentionFlag:
    """Open (or refresh) a flag for a scope the scan did not raise on its own.

    Used by the effectiveness loop: repeated ineffective point-of-process guidance is itself
    evidence that a tier-3 training/structural intervention is warranted.
    """
    now = utcnow()
    flag = _active_flag(db, scope_type, scope_value, category)
    if flag is None:
        flag = AttentionFlag(
            scope_type=scope_type,
            scope_value=scope_value,
            category=category,
            first_detected_at=now,
            window_days=window_days,
            threshold=threshold,
        )
        db.add(flag)
    flag.severity = severity
    flag.pattern_summary = pattern_summary
    flag.suggested_action = playbook.training_action(category, scope_type, scope_value)
    flag.last_detected_at = now
    if supporting_exception_ids:
        flag.supporting_exception_ids = supporting_exception_ids[:MAX_SUPPORTING]
    db.flush()
    return flag


def list_flags(
    db: Session,
    *,
    status: FlagStatus | None = None,
    scope_type: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[AttentionFlag]:
    stmt = select(AttentionFlag)
    if status is not None:
        stmt = stmt.where(AttentionFlag.status == status)
    if scope_type:
        stmt = stmt.where(AttentionFlag.scope_type == scope_type)
    if category:
        stmt = stmt.where(AttentionFlag.category == category)
    stmt = stmt.order_by(AttentionFlag.status, AttentionFlag.last_detected_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def summary(db: Session) -> dict:
    flags = list(db.scalars(select(AttentionFlag)).all())
    return {
        "open": sum(1 for f in flags if f.status == FlagStatus.open),
        "acknowledged": sum(1 for f in flags if f.status == FlagStatus.acknowledged),
        "resolved": sum(1 for f in flags if f.status == FlagStatus.resolved),
        "high_severity_active": sum(
            1 for f in flags if f.severity == "high" and f.status != FlagStatus.resolved
        ),
    }


def acknowledge(db: Session, flag: AttentionFlag, actor: str | None) -> AttentionFlag:
    flag.status = FlagStatus.acknowledged
    flag.acknowledged_by = actor
    flag.acknowledged_at = utcnow()
    db.commit()
    db.refresh(flag)
    return flag


def resolve(db: Session, flag: AttentionFlag, actor: str | None, note: str = "") -> AttentionFlag:
    flag.status = FlagStatus.resolved
    flag.resolved_by = actor
    flag.resolved_at = utcnow()
    flag.resolution_note = note
    db.commit()
    db.refresh(flag)
    return flag


def evidence(db: Session, flag: AttentionFlag) -> list[dict]:
    ids: list[uuid.UUID] = []
    for raw in flag.supporting_exception_ids or []:
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return []
    rows = db.scalars(select(OVException).where(OVException.id.in_(ids))).all()
    return [
        {
            "id": str(exc.id),
            "pro_number": exc.pro_number,
            "origin_terminal": exc.origin_terminal,
            "destination_terminal": exc.destination_terminal,
            "commodity_code": exc.commodity_code,
            "entry_user": exc.entry_user,
            "status": exc.status.value,
            "clearing_code": exc.clearing_code,
            "created_at": exc.created_at,
        }
        for exc in rows
    ]
