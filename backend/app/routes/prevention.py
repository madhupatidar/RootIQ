"""Prevention endpoints - the three tiers that close the loop from "what happened" to
"don't let it happen again" (what to watch, live assist, attention flags)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AttentionFlag, FlagStatus, PreventionCheck, Recommendation
from app.prevention import attention, effectiveness, risk, similarity, staging
from app.prevention.risk import WatchContext
from app.schemas import (
    AttentionFlagOut,
    AttentionListResponse,
    AttentionScanRequest,
    AttentionScanResponse,
    EffectivenessRequest,
    EffectivenessResponse,
    FlagActionRequest,
    FlagActionResponse,
    LineageResponse,
    NotesAssistRequest,
    NotesAssistResponse,
    PreventionCheckOut,
    QuantityConfirmRequest,
    QuantityCorrectRequest,
    QuantityVerifyRequest,
    QuantityVerifyResponse,
    WatchRequest,
    WatchResponse,
)

router = APIRouter(prefix="/prevention", tags=["prevention"])


# --- Tier 1 -------------------------------------------------------------------------------


@router.post("/watch", response_model=WatchResponse)
def watch(payload: WatchRequest, db: Session = Depends(get_db)):
    """Which root causes are concentrated on this terminal / lane / commodity right now.

    Read before freight is handled, not while an exception is being logged. Deliberately
    cheap: the classification that produced this history ran offline, so nothing here calls
    the model.
    """
    ctx = WatchContext(
        origin_terminal=payload.origin_terminal,
        destination_terminal=payload.destination_terminal,
        commodity_code=payload.commodity_code,
        package_type=payload.package_type,
        value_range=payload.value_range,
        hazmat=payload.hazmat,
        shrink_wrapped=payload.shrink_wrapped,
        handler=payload.handler,
    )
    return risk.evaluate(db, ctx, days=payload.days or None)


# --- Tier 2 -------------------------------------------------------------------------------


@router.post("/notes-assist", response_model=NotesAssistResponse)
def notes_assist(payload: NotesAssistRequest, db: Session = Depends(get_db)):
    """Draft root-cause suggestion from similar past cases while the clerk types."""
    return similarity.suggest(db, payload.text, top_k=payload.top_k)


# --- Prevention form: staging checks ------------------------------------------------------


def _get_check(db: Session, check_id: uuid.UUID) -> PreventionCheck:
    check = db.get(PreventionCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Prevention check not found")
    if staging.is_resolved(check):
        raise HTTPException(status_code=409, detail="This check has already been resolved")
    return check


@router.post("/staging-check/quantity-verify", response_model=QuantityVerifyResponse)
def quantity_verify(payload: QuantityVerifyRequest, db: Session = Depends(get_db)):
    """Verify the scanned piece count against the expected manifest count before staging."""
    return staging.quantity_verify(
        db,
        pro_number=payload.pro_number,
        terminal=payload.terminal,
        scanned_quantity=payload.scanned_quantity,
        actor=payload.actor,
    )


@router.post("/staging-check/quantity-verify/{check_id}/correct", response_model=PreventionCheckOut)
def quantity_verify_correct(
    check_id: uuid.UUID, payload: QuantityCorrectRequest, db: Session = Depends(get_db)
):
    """The worker recounted and fixed the physical count."""
    check = _get_check(db, check_id)
    return staging.record_correction(
        db, check, corrected_quantity=payload.corrected_quantity, actor=payload.actor
    )


@router.post("/staging-check/quantity-verify/{check_id}/confirm", response_model=PreventionCheckOut)
def quantity_verify_confirm(
    check_id: uuid.UUID, payload: QuantityConfirmRequest, db: Session = Depends(get_db)
):
    """The worker confirms the discrepancy is real and gives the reason."""
    check = _get_check(db, check_id)
    return staging.confirm_discrepancy(db, check, reason=payload.reason, actor=payload.actor)


# --- Effectiveness & escalation -----------------------------------------------------------


@router.post("/recommendations/evaluate", response_model=EffectivenessResponse)
def evaluate_effectiveness(
    payload: EffectivenessRequest | None = None, db: Session = Depends(get_db)
):
    payload = payload or EffectivenessRequest()
    outcomes = (
        effectiveness.resolve_outcomes(db, window_days=payload.window_days)
        if payload.resolve_checks
        else None
    )
    try:
        result = effectiveness.evaluate_recommendation_effectiveness(
            db,
            window_days=payload.window_days,
            improvement_threshold=payload.improvement_threshold,
            escalation_ceiling=payload.escalation_ceiling,
        )
    except RuntimeError as exc:
        # The escalation path reuses recommender.py, so an unreachable model surfaces here.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**result, "outcomes": outcomes}


@router.get("/recommendations/{recommendation_id}/lineage", response_model=LineageResponse)
def recommendation_lineage(recommendation_id: uuid.UUID, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return effectiveness.lineage(db, rec)


# --- Tier 3 -------------------------------------------------------------------------------


def _get_flag(db: Session, flag_id: uuid.UUID) -> AttentionFlag:
    flag = db.get(AttentionFlag, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Attention flag not found")
    return flag


@router.get("/attention", response_model=AttentionListResponse)
def list_attention(
    status: FlagStatus | None = None,
    scope_type: str | None = Query(None, pattern="^(terminal|handler)$"),
    category: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    items = attention.list_flags(db, status=status, scope_type=scope_type, category=category, limit=limit)
    return {"summary": attention.summary(db), "items": items}


@router.post("/attention/scan", response_model=AttentionScanResponse)
def scan_attention(payload: AttentionScanRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or AttentionScanRequest()
    return attention.scan(
        db,
        window_days=payload.window_days,
        periods=payload.periods,
        threshold=payload.threshold,
        min_consecutive=payload.min_consecutive,
    )


@router.get("/attention/{flag_id}", response_model=AttentionFlagOut)
def get_attention(flag_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_flag(db, flag_id)


@router.get("/attention/{flag_id}/evidence")
def attention_evidence(flag_id: uuid.UUID, db: Session = Depends(get_db)):
    flag = _get_flag(db, flag_id)
    return {
        "flag_id": str(flag.id),
        "category": flag.category,
        "scope_type": flag.scope_type,
        "scope_value": flag.scope_value,
        "exceptions": attention.evidence(db, flag),
    }


@router.post("/attention/{flag_id}/acknowledge", response_model=FlagActionResponse)
def acknowledge_attention(
    flag_id: uuid.UUID, payload: FlagActionRequest | None = None, db: Session = Depends(get_db)
):
    payload = payload or FlagActionRequest()
    flag = _get_flag(db, flag_id)
    if flag.status == FlagStatus.resolved:
        raise HTTPException(status_code=409, detail="Flag is already resolved")
    flag = attention.acknowledge(db, flag, payload.actor)
    return {
        "flag": flag,
        "confirmation": f"Acknowledged — {flag.scope_value} / {flag.category} is now owned and tracked.",
    }


@router.post("/attention/{flag_id}/resolve", response_model=FlagActionResponse)
def resolve_attention(flag_id: uuid.UUID, payload: FlagActionRequest | None = None, db: Session = Depends(get_db)):
    payload = payload or FlagActionRequest()
    flag = _get_flag(db, flag_id)
    flag = attention.resolve(db, flag, payload.actor, payload.note)
    return {
        "flag": flag,
        "confirmation": f"Resolved — {flag.scope_value} / {flag.category} is closed out. Nice work.",
    }
