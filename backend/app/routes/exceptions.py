import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.dedup.hashing import compute_content_hash
from app.models import (
    ClearingCode,
    ExceptionStatus,
    OVException,
    OVInvestigation,
    RootCauseClassification,
    utcnow,
)
from app.questions import INVESTIGATION_QUESTIONS, build_combined_notes
from app.pro_number import generate_pro
from app.reference import COMMODITIES, TERMINALS
from app.schemas import (
    ClearingCodeOut,
    ClearRequest,
    InvestigationCreate,
    OVExceptionCreate,
    OVExceptionDetail,
    OVExceptionListItem,
    OVExceptionListResponse,
    OVExceptionOut,
)

router = APIRouter(tags=["ov-exceptions"])


def get_exception_or_404(db: Session, exception_id: uuid.UUID) -> OVException:
    exc = db.get(OVException, exception_id)
    if exc is None:
        raise HTTPException(status_code=404, detail="OV exception not found")
    return exc


def latest_classification(db: Session, exception_id: uuid.UUID) -> RootCauseClassification | None:
    return db.scalar(
        select(RootCauseClassification)
        .where(RootCauseClassification.ov_exception_id == exception_id)
        .order_by(RootCauseClassification.classified_at.desc(), RootCauseClassification.id.desc())
        .limit(1)
    )


def latest_category_ids(category: str):
    """Ids of exceptions whose most recent classification is `category`.

    Written as a max(classified_at) self-join rather than Postgres DISTINCT ON so the same
    query runs on SQLite under test.
    """
    newest = (
        select(
            RootCauseClassification.ov_exception_id.label("exception_id"),
            func.max(RootCauseClassification.classified_at).label("classified_at"),
        )
        .group_by(RootCauseClassification.ov_exception_id)
        .subquery()
    )
    return (
        select(RootCauseClassification.ov_exception_id)
        .join(
            newest,
            (RootCauseClassification.ov_exception_id == newest.c.exception_id)
            & (RootCauseClassification.classified_at == newest.c.classified_at),
        )
        .where(RootCauseClassification.category == category)
    )


def apply_exception_filters(
    stmt,
    *,
    terminal: str | None = None,
    origin_terminal: str | None = None,
    destination_terminal: str | None = None,
    commodity_code: str | None = None,
    value_range: int | None = None,
    status: ExceptionStatus | None = None,
    clearing_code: str | None = None,
    category: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """Shared filter clauses for any `select(OVException)`.

    Used by both the list endpoint and /classify/batch so the "Classify unclassified"
    button operates on exactly the rows the user is looking at.
    """
    if terminal:
        stmt = stmt.where(
            (OVException.origin_terminal == terminal) | (OVException.destination_terminal == terminal)
        )
    if origin_terminal:
        stmt = stmt.where(OVException.origin_terminal == origin_terminal)
    if destination_terminal:
        stmt = stmt.where(OVException.destination_terminal == destination_terminal)
    if commodity_code:
        stmt = stmt.where(OVException.commodity_code == commodity_code)
    if value_range:
        stmt = stmt.where(OVException.value_range == value_range)
    if status:
        stmt = stmt.where(OVException.status == status)
    if clearing_code:
        stmt = stmt.where(OVException.clearing_code == clearing_code)
    if date_from:
        stmt = stmt.where(OVException.created_at >= date_from)
    if date_to:
        stmt = stmt.where(OVException.created_at <= date_to)
    if category:
        # Filter on the *latest* classification in SQL, otherwise `total` and the page window
        # would both be computed before the filter and pagination would be wrong.
        stmt = stmt.where(OVException.id.in_(latest_category_ids(category)))
    return stmt


@router.get("/investigation-questions")
def list_investigation_questions() -> list[dict]:
    return INVESTIGATION_QUESTIONS


@router.get("/commodities")
def list_commodities() -> list[dict]:
    """Official commodity master (app/reference.py)."""
    return COMMODITIES


@router.get("/terminals")
def list_terminals() -> list[str]:
    """Official terminal master (app/reference.py)."""
    return TERMINALS


@router.get("/pro-number/suggest")
def suggest_pro_number() -> dict:
    """A syntactically valid PRO so the entry form can be exercised without a live AS400."""
    return {"pro_number": generate_pro()}


@router.get("/clearing-codes", response_model=list[ClearingCodeOut])
def list_clearing_codes(db: Session = Depends(get_db)):
    return db.scalars(select(ClearingCode).order_by(ClearingCode.code)).all()


@router.post("/ov-exceptions", response_model=OVExceptionOut, status_code=201)
def create_ov_exception(payload: OVExceptionCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    exc = OVException(**data)
    # content_hash is set at creation and recomputed when investigation notes land.
    exc.content_hash = compute_content_hash(exc.pro_number, "")
    db.add(exc)
    db.commit()
    db.refresh(exc)
    return exc


@router.get("/ov-exceptions", response_model=OVExceptionListResponse)
def list_ov_exceptions(
    db: Session = Depends(get_db),
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
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(OVException)
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

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(OVException.created_at.desc()).limit(limit).offset(offset)
    ).all()

    items: list[OVExceptionListItem] = []
    for exc in rows:
        cls = latest_classification(db, exc.id)
        item = OVExceptionListItem.model_validate(exc)
        if cls is not None:
            item.latest_category = cls.category
            item.latest_confidence = cls.confidence
            item.latest_source = cls.source
        items.append(item)

    return OVExceptionListResponse(total=total, items=items)


@router.get("/ov-exceptions/{exception_id}", response_model=OVExceptionDetail)
def get_ov_exception(exception_id: uuid.UUID, db: Session = Depends(get_db)):
    exc = db.scalar(
        select(OVException)
        .options(selectinload(OVException.investigation))
        .where(OVException.id == exception_id)
    )
    if exc is None:
        raise HTTPException(status_code=404, detail="OV exception not found")

    detail = OVExceptionDetail.model_validate(exc)
    cls = latest_classification(db, exc.id)
    if cls is not None:
        detail.latest_classification = cls  # type: ignore[assignment]
    return detail


@router.post("/ov-exceptions/{exception_id}/investigation", response_model=OVExceptionDetail)
def submit_investigation(
    exception_id: uuid.UUID, payload: InvestigationCreate, db: Session = Depends(get_db)
):
    exc = get_exception_or_404(db, exception_id)

    steps = [step.model_dump() for step in payload.steps]
    combined = build_combined_notes(steps)

    investigation = exc.investigation or OVInvestigation(ov_exception_id=exc.id)
    investigation.steps = steps
    investigation.combined_notes_text = combined
    investigation.completed_at = utcnow()
    exc.investigation = investigation

    # Re-hash now that the investigation text exists - this is what dedup keys on.
    exc.content_hash = compute_content_hash(exc.pro_number, combined)
    exc.status = (
        ExceptionStatus.investigation_complete if payload.mark_complete else ExceptionStatus.in_progress
    )
    db.commit()
    db.refresh(exc)

    detail = OVExceptionDetail.model_validate(exc)
    cls = latest_classification(db, exc.id)
    if cls is not None:
        detail.latest_classification = cls  # type: ignore[assignment]
    return detail


@router.post("/ov-exceptions/{exception_id}/clear", response_model=OVExceptionOut)
def clear_ov_exception(exception_id: uuid.UUID, payload: ClearRequest, db: Session = Depends(get_db)):
    exc = get_exception_or_404(db, exception_id)

    code = db.get(ClearingCode, payload.clearing_code.strip().upper())
    if code is None:
        raise HTTPException(status_code=422, detail=f"Unknown clearing code '{payload.clearing_code}'")

    exc.clearing_code = code.code
    exc.cleared_at = utcnow()
    exc.status = ExceptionStatus.cleared
    if payload.cleared_by:
        exc.assigned_to = payload.cleared_by
    db.commit()
    db.refresh(exc)
    return exc
