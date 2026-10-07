"""Cache lookup/write logic against the ClassificationCache table (spec Section 6).

The Postgres table *is* the cache for this POC (unique PK on content_hash). No second
in-process/Redis layer is used - add one only if the demo needs to run under load.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ClassificationCache, ClassificationSource, RootCauseClassification, utcnow


@dataclass(slots=True)
class ClassificationResult:
    category: str
    confidence: float
    reasoning: str
    model_used: str
    needs_review: bool = False
    # {factor: bool}; None only until the classifier has filled it in.
    contributing_factors: dict | None = None


def lookup(db: Session, content_hash: str) -> ClassificationCache | None:
    return db.get(ClassificationCache, content_hash)


def record_hit(db: Session, entry: ClassificationCache) -> ClassificationCache:
    entry.hit_count += 1
    entry.last_hit_at = utcnow()
    db.flush()
    return entry


def store(db: Session, content_hash: str, result: ClassificationResult) -> ClassificationCache:
    entry = db.get(ClassificationCache, content_hash)
    if entry is None:
        entry = ClassificationCache(content_hash=content_hash, first_classified_at=utcnow(), hit_count=0)
        db.add(entry)
    entry.category = result.category
    entry.confidence = result.confidence
    entry.reasoning = result.reasoning
    entry.model_used = result.model_used
    entry.needs_review = result.needs_review
    # Text-derived factors are safe to reuse (the hash covers the notes); the handler-scoped
    # training_signal is recomputed per exception on every cache hit.
    entry.contributing_factors = result.contributing_factors
    db.flush()
    return entry


def cache_stats(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(RootCauseClassification)) or 0
    hits = (
        db.scalar(
            select(func.count())
            .select_from(RootCauseClassification)
            .where(RootCauseClassification.source == ClassificationSource.cache_hit)
        )
        or 0
    )
    fresh = (
        db.scalar(
            select(func.count())
            .select_from(RootCauseClassification)
            .where(RootCauseClassification.source == ClassificationSource.ai_fresh)
        )
        or 0
    )
    unique_hashes = db.scalar(select(func.count()).select_from(ClassificationCache)) or 0
    lookups = hits + fresh
    return {
        "total_classification_events": total,
        "cache_hits": hits,
        "ai_fresh_calls": fresh,
        "unique_content_hashes": unique_hashes,
        "cache_hit_rate": round(hits / lookups, 4) if lookups else 0.0,
        "ollama_calls_saved": hits,
    }
