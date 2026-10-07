import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.classifier import apply_training_signal, classify_ov_exception
from app.ai.taxonomy import CATEGORY_DEFINITIONS, ROOT_CAUSE_TAXONOMY, empty_factors
from app.analytics import recurrence_context
from app.db import get_db
from app.dedup import cache
from app.dedup.cache import ClassificationResult
from app.dedup.hashing import compute_content_hash
from app.models import (
    ClassificationSource,
    ExceptionStatus,
    OVException,
    OVInvestigation,
    RootCauseClassification,
)
from app.questions import answered_flags
from app.routes.exceptions import apply_exception_filters, get_exception_or_404
from app.schemas import BatchClassifyResponse, ClassificationOut, OverrideRequest

router = APIRouter(prefix="/classify", tags=["classify"])


def classification_text(exc: OVException) -> str:
    notes = exc.investigation.combined_notes_text if exc.investigation else ""
    details = (exc.additional_details or "").strip()
    parts = [p for p in (notes.strip(), f"Additional details: {details}" if details else "") if p]
    return "\n".join(parts)


def build_context(db: Session, exc: OVException):
    """Structured multi-factor context for the classifier - reuses the analytics aggregation."""
    steps = exc.investigation.steps if exc.investigation else []
    return recurrence_context(
        db,
        terminal=exc.origin_terminal,
        handler=exc.entry_user,
        exclude_exception_id=str(exc.id),
        investigation_flags=answered_flags(steps),
    )


def classify_one(db: Session, exc: OVException) -> RootCauseClassification:
    """Cache-aware classification (spec Section 6). Appends one audit row either way."""
    notes = exc.investigation.combined_notes_text if exc.investigation else ""
    # NOTE: the hash intentionally covers pro_number + investigation notes only (spec Section 6).
    # additional_details is fed to the model but is not part of the dedup key.
    content_hash = compute_content_hash(exc.pro_number, notes)
    exc.content_hash = content_hash

    context = build_context(db, exc)

    entry = cache.lookup(db, content_hash)
    if entry is not None:
        cache.record_hit(db, entry)
        # The cached factors are text-derived; training_signal is handler-scoped, so it is
        # recomputed for *this* exception rather than inherited from the cached row.
        cached = ClassificationResult(
            category=entry.category,
            confidence=entry.confidence,
            reasoning=entry.reasoning,
            model_used=entry.model_used,
            needs_review=entry.needs_review,
            contributing_factors=dict(entry.contributing_factors or empty_factors()),
        )
        apply_training_signal(cached, context)
        row = RootCauseClassification(
            ov_exception_id=exc.id,
            content_hash=content_hash,
            category=cached.category,
            confidence=cached.confidence,
            reasoning=cached.reasoning,
            model_used=cached.model_used,
            source=ClassificationSource.cache_hit,
            needs_review=cached.needs_review,
            contributing_factors=cached.contributing_factors,
        )
    else:
        result = classify_ov_exception(classification_text(exc), context=context)
        cache.store(db, content_hash, result)
        row = RootCauseClassification(
            ov_exception_id=exc.id,
            content_hash=content_hash,
            category=result.category,
            confidence=result.confidence,
            reasoning=result.reasoning,
            model_used=result.model_used,
            source=ClassificationSource.ai_fresh,
            needs_review=result.needs_review,
            contributing_factors=result.contributing_factors,
        )

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/taxonomy")
def get_taxonomy() -> list[dict]:
    return [{"category": name, "definition": CATEGORY_DEFINITIONS[name]} for name in ROOT_CAUSE_TAXONOMY]


@router.post("/batch", response_model=BatchClassifyResponse)
def classify_batch(
    db: Session = Depends(get_db),
    force: bool = Query(False, description="re-classify exceptions that already have a classification"),
    limit: int = Query(200, ge=1, le=1000),
    with_notes: bool = Query(
        True,
        description="only classify exceptions that have investigation text; without notes the "
        "model has nothing to reason from and returns 'Other', so the AI call is wasted",
    ),
    # Same filters as GET /ov-exceptions, so the UI can classify exactly the current view.
    terminal: str | None = Query(None, description="matches origin OR destination terminal"),
    origin_terminal: str | None = None,
    destination_terminal: str | None = None,
    commodity_code: str | None = None,
    value_range: int | None = Query(None, ge=1, le=3),
    status: ExceptionStatus | None = None,
    clearing_code: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    stmt = select(OVException).order_by(OVException.created_at)
    stmt = apply_exception_filters(
        stmt,
        terminal=terminal,
        origin_terminal=origin_terminal,
        destination_terminal=destination_terminal,
        commodity_code=commodity_code,
        value_range=value_range,
        status=status,
        clearing_code=clearing_code,
        category=category,
        date_from=date_from,
        date_to=date_to,
    )
    if with_notes:
        stmt = stmt.join(OVInvestigation).where(
            OVInvestigation.combined_notes_text.is_not(None),
            OVInvestigation.combined_notes_text != "",
        )
    if not force:
        classified = select(RootCauseClassification.ov_exception_id).distinct()
        stmt = stmt.where(OVException.id.not_in(classified))

    rows = db.scalars(stmt.limit(limit)).all()
    results = [classify_one(db, exc) for exc in rows]

    return BatchClassifyResponse(
        processed=len(results),
        ai_fresh=sum(1 for r in results if r.source == ClassificationSource.ai_fresh),
        cache_hits=sum(1 for r in results if r.source == ClassificationSource.cache_hit),
        needs_review=sum(1 for r in results if r.needs_review),
        results=[ClassificationOut.model_validate(r) for r in results],
    )


@router.post("/{exception_id}", response_model=ClassificationOut)
def classify_exception(exception_id: uuid.UUID, db: Session = Depends(get_db)):
    exc = get_exception_or_404(db, exception_id)
    return classify_one(db, exc)


@router.get("/{exception_id}/history", response_model=list[ClassificationOut])
def classification_history(exception_id: uuid.UUID, db: Session = Depends(get_db)):
    get_exception_or_404(db, exception_id)
    return db.scalars(
        select(RootCauseClassification)
        .where(RootCauseClassification.ov_exception_id == exception_id)
        .order_by(RootCauseClassification.classified_at.desc())
    ).all()


@router.post("/{exception_id}/override", response_model=ClassificationOut)
def override_classification(
    exception_id: uuid.UUID, payload: OverrideRequest, db: Session = Depends(get_db)
):
    """Human-in-the-loop correction. Appended as a new history row - nothing is overwritten."""
    exc = get_exception_or_404(db, exception_id)
    category = payload.category.strip()
    if category not in ROOT_CAUSE_TAXONOMY:
        raise HTTPException(status_code=422, detail=f"Unknown category '{payload.category}'")

    reviewer = payload.reviewer or "human"
    previous = db.scalar(
        select(RootCauseClassification)
        .where(RootCauseClassification.ov_exception_id == exc.id)
        .order_by(RootCauseClassification.classified_at.desc())
        .limit(1)
    )
    row = RootCauseClassification(
        ov_exception_id=exc.id,
        content_hash=exc.content_hash,
        category=category,
        confidence=1.0,
        reasoning=payload.reasoning or f"Manually overridden by {reviewer}",
        model_used=f"human:{reviewer}",
        source=ClassificationSource.human_override,
        needs_review=False,
        contributing_factors=(previous.contributing_factors if previous else None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
