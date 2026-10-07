"""pandas aggregation over classified OV exceptions (spec Section 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OVException, RootCauseClassification, utcnow

DEFAULT_RECURRENCE_WINDOW_DAYS = 90
MAX_RECURRENCE_CATEGORIES = 5


@dataclass(slots=True)
class InsightFilters:
    terminal: str | None = None
    commodity_code: str | None = None
    days: int | None = 90

    @property
    def time_window(self) -> str:
        return f"last {self.days} days" if self.days else "all time"

    def as_scope(self) -> dict:
        return {"terminal": self.terminal, "commodity": self.commodity_code, "time_window": self.time_window}


COLUMNS = [
    "exception_id",
    "pro_number",
    "category",
    "confidence",
    "source",
    "origin_terminal",
    "destination_terminal",
    "commodity_code",
    "package_type",
    "value_range",
    "status",
    "clearing_code",
    "entry_user",
    "assigned_to",
    "created_at",
    "classified_at",
    "contributing_factors",
]


def load_dataframe(db: Session, filters: InsightFilters) -> pd.DataFrame:
    """One row per exception, carrying its *latest* classification."""
    stmt = (
        select(OVException, RootCauseClassification)
        .join(RootCauseClassification, RootCauseClassification.ov_exception_id == OVException.id)
        .order_by(RootCauseClassification.classified_at)
    )
    if filters.terminal:
        stmt = stmt.where(
            (OVException.origin_terminal == filters.terminal)
            | (OVException.destination_terminal == filters.terminal)
        )
    if filters.commodity_code:
        stmt = stmt.where(OVException.commodity_code == filters.commodity_code)
    if filters.days:
        cutoff = utcnow() - timedelta(days=filters.days)
        stmt = stmt.where(OVException.created_at >= cutoff)

    latest: dict[str, dict] = {}
    for exc, cls in db.execute(stmt).all():
        latest[str(exc.id)] = {
            "exception_id": str(exc.id),
            "pro_number": exc.pro_number,
            "category": cls.category,
            "confidence": cls.confidence,
            "source": cls.source.value,
            "origin_terminal": exc.origin_terminal,
            "destination_terminal": exc.destination_terminal,
            "commodity_code": exc.commodity_code,
            "package_type": exc.package_type,
            "value_range": exc.value_range,
            "status": exc.status.value,
            "clearing_code": exc.clearing_code,
            "entry_user": exc.entry_user,
            "assigned_to": exc.assigned_to,
            "created_at": exc.created_at,
            "classified_at": cls.classified_at,
            "contributing_factors": cls.contributing_factors or {},
        }

    if not latest:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(list(latest.values()), columns=COLUMNS)


def _counts(df: pd.DataFrame, by: list[str]) -> list[dict]:
    if df.empty:
        return []
    grouped = df.groupby(by, dropna=False).size().reset_index(name="count")
    grouped = grouped.sort_values("count", ascending=False)
    records = grouped.to_dict(orient="records")
    for record in records:
        for key, value in list(record.items()):
            if pd.isna(value):
                record[key] = None
    return records


def factor_counts(df: pd.DataFrame) -> list[dict]:
    """Tally the true contributing factors across a (sub)set of classified exceptions."""
    total = int(len(df))
    if total == 0:
        return []
    tally: dict[str, int] = {}
    for factors in df["contributing_factors"]:
        for name, present in (factors or {}).items():
            if present:
                tally[name] = tally.get(name, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"factor": name, "count": count, "percentage": round(count / total * 100, 2)}
        for name, count in ranked
    ]


def build_distribution(df: pd.DataFrame) -> dict:
    total = int(len(df))
    if total == 0:
        return {"total_classified": 0, "categories": [], "factors": []}
    counts = df["category"].value_counts()
    categories = [
        {
            "category": str(category),
            "count": int(count),
            "percentage": round(float(count) / total * 100, 2),
            "avg_confidence": round(float(df.loc[df["category"] == category, "confidence"].mean()), 3),
            "factors": factor_counts(df.loc[df["category"] == category]),
        }
        for category, count in counts.items()
    ]
    return {"total_classified": total, "categories": categories, "factors": factor_counts(df)}


def build_aggregates(df: pd.DataFrame) -> dict:
    return {
        "distribution": build_distribution(df),
        "by_origin_terminal": _counts(df, ["origin_terminal", "category"]),
        "by_destination_terminal": _counts(df, ["destination_terminal", "category"]),
        "by_commodity": _counts(df, ["commodity_code", "category"]),
        "by_clearing_code": _counts(df, ["clearing_code", "category"]),
    }


def _table(title: str, rows: list[dict], limit: int = 12) -> str:
    if not rows:
        return f"{title}: (none)"
    lines = [f"{title}:"]
    for row in rows[:limit]:
        pairs = ", ".join(f"{k}={v}" for k, v in row.items() if k != "count")
        lines.append(f"  - {pairs} -> {row['count']}")
    return "\n".join(lines)


def format_stats_for_prompt(aggregates: dict, filters: InsightFilters) -> str:
    dist = aggregates["distribution"]
    lines = [
        f"Scope: terminal={filters.terminal or 'all'}, commodity={filters.commodity_code or 'all'}, "
        f"window={filters.time_window}",
        f"Total classified OV exceptions: {dist['total_classified']}",
        "Root cause distribution:",
    ]
    for item in dist["categories"]:
        lines.append(f"  - {item['category']}: {item['count']} ({item['percentage']}%)")
    lines.append(_table("Category by origin terminal", aggregates["by_origin_terminal"]))
    lines.append(_table("Category by destination terminal", aggregates["by_destination_terminal"]))
    lines.append(_table("Category by commodity code", aggregates["by_commodity"]))
    return "\n".join(lines)


def supporting_ids(df: pd.DataFrame, category: str, limit: int = 25) -> list[str]:
    if df.empty:
        return []
    subset = df.loc[df["category"] == category, "exception_id"]
    return [str(v) for v in subset.head(limit).tolist()]


# --- Multi-factor classification context --------------------------------------------------


@dataclass(slots=True)
class RecurrenceContext:
    """Structured context handed to the classifier so it can explain *why*, not just *what*.

    Built from the same `load_dataframe` aggregation every other insight uses - there is no
    second counting path.
    """

    terminal: str | None = None
    handler: str | None = None
    window_days: int = DEFAULT_RECURRENCE_WINDOW_DAYS
    terminal_counts: dict[str, int] = field(default_factory=dict)
    handler_counts: dict[str, int] = field(default_factory=dict)
    terminal_total: int = 0
    handler_total: int = 0
    # question_key -> "Y"/"N" from OVInvestigation.steps, reused as-is (app/questions.py).
    investigation_flags: dict[str, str] = field(default_factory=dict)

    def recurrence_at_terminal(self, category: str) -> int:
        return int(self.terminal_counts.get(category, 0))

    def recurrence_by_handler(self, category: str) -> int:
        return int(self.handler_counts.get(category, 0))

    def as_prompt_block(self) -> str:
        def _top(counts: dict[str, int]) -> str:
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:MAX_RECURRENCE_CATEGORIES]
            return ", ".join(f"{name} {count}" for name, count in ranked) or "none"

        lines = [f"Trailing window: last {self.window_days} days of classified overages."]
        if self.terminal:
            lines.append(
                f"Terminal {self.terminal}: {self.terminal_total} classified overages "
                f"({_top(self.terminal_counts)})."
            )
        if self.handler:
            lines.append(
                f"Handler {self.handler}: {self.handler_total} classified overages "
                f"({_top(self.handler_counts)})."
            )
        if self.investigation_flags:
            answered = ", ".join(f"{key}={value}" for key, value in self.investigation_flags.items())
            lines.append(f"Investigation checks answered: {answered}.")
        return "\n".join(lines)


def recurrence_context(
    db: Session,
    *,
    terminal: str | None,
    handler: str | None,
    window_days: int = DEFAULT_RECURRENCE_WINDOW_DAYS,
    exclude_exception_id: str | None = None,
    investigation_flags: dict[str, str] | None = None,
) -> RecurrenceContext:
    ctx = RecurrenceContext(
        terminal=terminal,
        handler=handler,
        window_days=window_days,
        investigation_flags=investigation_flags or {},
    )
    if not terminal and not handler:
        return ctx

    df = load_dataframe(db, InsightFilters(days=window_days or None))
    if df.empty:
        return ctx
    if exclude_exception_id:
        df = df[df["exception_id"] != str(exclude_exception_id)]

    if terminal:
        subset = df[(df["origin_terminal"] == terminal) | (df["destination_terminal"] == terminal)]
        ctx.terminal_counts = {str(k): int(v) for k, v in subset["category"].value_counts().items()}
        ctx.terminal_total = int(len(subset))
    if handler:
        subset = df[df["entry_user"] == handler]
        ctx.handler_counts = {str(k): int(v) for k, v in subset["category"].value_counts().items()}
        ctx.handler_total = int(len(subset))
    return ctx
