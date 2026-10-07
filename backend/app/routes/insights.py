import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.recommender import generate_recommendations
from app.analytics import InsightFilters, build_aggregates, build_distribution, load_dataframe
from app.db import get_db
from app.dedup import cache
from app.models import ClassificationSource, OVException, Recommendation, RootCauseClassification
from app.schemas import GenerateRecommendationsRequest, RecommendationOut

router = APIRouter(prefix="/insights", tags=["insights"])


def _filters(terminal: str | None, commodity_code: str | None, days: int | None) -> InsightFilters:
    # days=0 (or None) means "no cutoff" - normalised here so as_scope() reports "all time".
    return InsightFilters(terminal=terminal, commodity_code=commodity_code, days=days or None)


@router.get("/distribution")
def distribution(
    db: Session = Depends(get_db),
    terminal: str | None = None,
    commodity_code: str | None = None,
    days: int | None = Query(90, ge=0, le=3650, description="0 = all time (no date cutoff)"),
    include_breakdowns: bool = False,
):
    filters = _filters(terminal, commodity_code, days)
    df = load_dataframe(db, filters)
    payload = {"scope": filters.as_scope(), **build_distribution(df)}
    if include_breakdowns:
        payload["breakdowns"] = {k: v for k, v in build_aggregates(df).items() if k != "distribution"}
    return payload


@router.get("/cache-stats")
def cache_statistics(db: Session = Depends(get_db)):
    return cache.cache_stats(db)


@router.get("/accuracy")
def accuracy(db: Session = Depends(get_db)):
    """Classification accuracy against the hand-labeled validation set (spec Section 14)."""
    labeled = db.scalars(
        select(OVException).where(OVException.labeled_category.is_not(None))
    ).all()

    evaluated: list[dict] = []
    for exc in labeled:
        predicted = db.scalar(
            select(RootCauseClassification)
            .where(
                RootCauseClassification.ov_exception_id == exc.id,
                RootCauseClassification.source != ClassificationSource.human_override,
            )
            .order_by(RootCauseClassification.classified_at.desc())
            .limit(1)
        )
        if predicted is None:
            continue
        evaluated.append(
            {
                "exception_id": str(exc.id),
                "pro_number": exc.pro_number,
                "expected": exc.labeled_category,
                "predicted": predicted.category,
                "confidence": predicted.confidence,
                "correct": predicted.category == exc.labeled_category,
            }
        )

    correct = sum(1 for r in evaluated if r["correct"])
    return {
        "validation_set_size": len(labeled),
        "evaluated": len(evaluated),
        "correct": correct,
        "accuracy": round(correct / len(evaluated), 4) if evaluated else 0.0,
        "misclassified": [r for r in evaluated if not r["correct"]],
    }


@router.get("/filters")
def filter_options(db: Session = Depends(get_db)):
    origins = db.scalars(select(OVException.origin_terminal).distinct()).all()
    destinations = db.scalars(select(OVException.destination_terminal).distinct()).all()
    commodities = db.scalars(select(OVException.commodity_code).distinct()).all()
    entry_users = db.scalars(select(OVException.entry_user).distinct()).all()
    return {
        "terminals": sorted({*origins, *destinations}),
        "origin_terminals": sorted(set(origins)),
        "destination_terminals": sorted(set(destinations)),
        "commodity_codes": sorted(set(commodities)),
        "entry_users": sorted({u for u in entry_users if u}),
    }


@router.get("/recommendations", response_model=list[RecommendationOut])
def latest_recommendations(db: Session = Depends(get_db), limit: int = Query(10, ge=1, le=50)):
    return db.scalars(
        select(Recommendation).order_by(Recommendation.generated_at.desc()).limit(limit)
    ).all()


@router.post("/recommendations/generate", response_model=list[RecommendationOut])
def regenerate_recommendations(
    payload: GenerateRecommendationsRequest | None = None, db: Session = Depends(get_db)
):
    payload = payload or GenerateRecommendationsRequest()
    filters = _filters(payload.terminal, payload.commodity_code, payload.days)
    try:
        rows = generate_recommendations(db, filters)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not rows:
        raise HTTPException(status_code=409, detail="No classified exceptions in scope - classify first")
    return rows


@router.get("/recommendations/{recommendation_id}/evidence")
def recommendation_evidence(recommendation_id: uuid.UUID, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    ids = [uuid.UUID(v) for v in rec.supporting_exception_ids]
    rows = db.scalars(select(OVException).where(OVException.id.in_(ids))).all() if ids else []
    return {
        "recommendation_id": str(rec.id),
        "category": rec.category,
        "exceptions": [
            {
                "id": str(e.id),
                "pro_number": e.pro_number,
                "origin_terminal": e.origin_terminal,
                "destination_terminal": e.destination_terminal,
                "commodity_code": e.commodity_code,
                "status": e.status.value,
                "clearing_code": e.clearing_code,
            }
            for e in rows
        ],
    }
