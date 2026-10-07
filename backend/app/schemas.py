"""Pydantic request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    ClassificationSource,
    ExceptionStatus,
    FlagStatus,
    FoundOn,
    PreventionOutcome,
    RecommendationStatus,
    VerificationResult,
)
from app.pro_number import is_valid_pro
from app.questions import QUESTION_KEYS


class OVExceptionCreate(BaseModel):
    pro_number: str
    origin_terminal: str = Field(min_length=2, max_length=8)
    destination_terminal: str = Field(min_length=2, max_length=8)
    shipper_name: str
    consignee_name: str
    od400_pro: str
    manifest_number: str | None = None
    found_on: FoundOn
    trailer_or_bay_number: str
    bl_number: str | None = None
    po_number: str | None = None
    sn_number: str | None = None
    hazmat: bool = False
    handling_units: int = Field(ge=1)
    commodity_code: str
    package_type: str
    pieces: int = Field(ge=1)
    weight: float = Field(gt=0)
    shrink_wrapped: bool = False
    item_carton_model_serial: str = ""
    value_range: Literal[1, 2, 3]
    dollar_amount: float | None = None
    manufacturer_brand: str | None = None
    additional_details: str = ""
    entry_user: str
    assigned_to: str | None = None
    labeled_category: str | None = None

    @field_validator("pro_number")
    @classmethod
    def _validate_pro(cls, value: str) -> str:
        if not is_valid_pro(value):
            raise ValueError("pro_number must be 12 digits with a valid mod-7 check digit")
        return value

    @model_validator(mode="after")
    def _validate_dollar_amount(self) -> "OVExceptionCreate":
        if self.value_range == 3 and self.dollar_amount is None:
            raise ValueError("dollar_amount is required when value_range is 3 (>$1000)")
        return self


class InvestigationStep(BaseModel):
    question_key: str
    answer_yn: Literal["Y", "N"]
    notes_text: str = ""

    @field_validator("question_key")
    @classmethod
    def _known_key(cls, value: str) -> str:
        if value not in QUESTION_KEYS:
            raise ValueError(f"unknown question_key '{value}'")
        return value


class InvestigationCreate(BaseModel):
    steps: list[InvestigationStep]
    mark_complete: bool = True


class InvestigationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    steps: list[dict]
    combined_notes_text: str
    completed_at: datetime


class ClearRequest(BaseModel):
    clearing_code: str
    cleared_by: str | None = None


class ClearingCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    full_form: str
    synced_at: datetime


class ClassificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ov_exception_id: uuid.UUID
    content_hash: str
    category: str
    confidence: float
    reasoning: str
    model_used: str
    source: ClassificationSource
    needs_review: bool
    contributing_factors: dict | None = None
    classified_at: datetime


class OVExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_osd_number: int | None = None
    pro_number: str
    origin_terminal: str
    destination_terminal: str
    shipper_name: str
    consignee_name: str
    od400_pro: str
    manifest_number: str | None
    found_on: FoundOn
    trailer_or_bay_number: str
    bl_number: str | None
    po_number: str | None
    sn_number: str | None
    hazmat: bool
    handling_units: int
    commodity_code: str
    commodity_description: str = ""
    package_type: str
    pieces: int
    weight: float
    shrink_wrapped: bool
    item_carton_model_serial: str
    value_range: int
    dollar_amount: float | None
    manufacturer_brand: str | None
    additional_details: str
    status: ExceptionStatus
    clearing_code: str | None
    cleared_at: datetime | None
    entry_user: str
    assigned_to: str | None
    content_hash: str
    labeled_category: str | None
    created_at: datetime
    updated_at: datetime


class OVExceptionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_osd_number: int | None = None
    pro_number: str
    origin_terminal: str
    destination_terminal: str
    commodity_code: str
    commodity_description: str = ""
    value_range: int
    status: ExceptionStatus
    clearing_code: str | None
    created_at: datetime
    latest_category: str | None = None
    latest_confidence: float | None = None
    latest_source: ClassificationSource | None = None


class OVExceptionListResponse(BaseModel):
    total: int
    items: list[OVExceptionListItem]


class OVExceptionDetail(OVExceptionOut):
    investigation: InvestigationOut | None = None
    latest_classification: ClassificationOut | None = None


class OverrideRequest(BaseModel):
    category: str
    reasoning: str = ""
    reviewer: str | None = None


class BatchClassifyResponse(BaseModel):
    processed: int
    ai_fresh: int
    cache_hits: int
    needs_review: int
    results: list[ClassificationOut]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    scope: dict
    recommendation_text: str
    pattern_addressed: str
    supporting_exception_ids: list
    generated_at: datetime
    status: RecommendationStatus = RecommendationStatus.active
    escalation_level: int = 0
    superseded_by_id: uuid.UUID | None = None


class GenerateRecommendationsRequest(BaseModel):
    terminal: str | None = None
    commodity_code: str | None = None
    days: int | None = Field(90, ge=0, le=3650, description="0 = all time (no date cutoff)")


# --- Prevention tier 1: what to watch (pre-handling, not pre-logging) ----------------------


class WatchRequest(BaseModel):
    origin_terminal: str | None = None
    destination_terminal: str | None = None
    commodity_code: str | None = None
    package_type: str | None = None
    value_range: Literal[1, 2, 3] | None = None
    hazmat: bool = False
    shrink_wrapped: bool = True
    handler: str | None = None
    days: int | None = Field(365, ge=0, le=3650, description="0 = all time (no date cutoff)")


class WatchSignal(BaseModel):
    cohort: str
    cohort_label: str
    cohort_size: int
    category: str
    count: int
    share: float
    baseline_share: float
    lift: float
    severity: str
    pattern: str
    prevention_action: str | None = None
    recommendation_id: str | None = None
    supporting_exception_ids: list[str] = []


class WatchAction(BaseModel):
    key: str
    label: str
    why: str
    category: str


class OpenFlagBrief(BaseModel):
    id: str
    scope_type: str
    scope_value: str
    category: str
    severity: str
    status: str
    suggested_action: str


class WatchResponse(BaseModel):
    evaluated_at: datetime
    scope: dict
    population: dict
    risk_level: str
    clear: bool
    message: str
    advisory: bool = True
    signals: list[WatchSignal] = []
    actions: list[WatchAction] = []
    open_flags: list[OpenFlagBrief] = []


# --- Prevention tier 2: live investigation assist -----------------------------------------


class NotesAssistRequest(BaseModel):
    text: str = ""
    top_k: int = Field(5, ge=1, le=10)


class SimilarCase(BaseModel):
    exception_id: str
    pro_number: str
    category: str
    similarity: float
    origin_terminal: str
    commodity_code: str
    snippet: str


class CategoryVote(BaseModel):
    category: str
    share: float


class MissingDetail(BaseModel):
    key: str
    label: str


class NotesAssistResponse(BaseModel):
    status: str
    advisory: bool = True
    disclaimer: str
    suggested_category: str | None = None
    confidence: float = 0.0
    basis: str = ""
    corpus_size: int = 0
    matches: list[SimilarCase] = []
    category_votes: list[CategoryVote] = []
    note_prompts: list[str] = []
    missing_details: list[MissingDetail] = []


# --- Prevention tier 3: attention & training signals --------------------------------------


class AttentionFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope_type: str
    scope_value: str
    category: str
    severity: str
    status: FlagStatus
    window_days: int
    threshold: int
    consecutive_periods: int
    period_counts: list
    current_period_count: int
    previous_period_count: int
    total_count: int
    pattern_summary: str
    suggested_action: str
    supporting_exception_ids: list
    first_detected_at: datetime
    last_detected_at: datetime
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str = ""


class AttentionScanRequest(BaseModel):
    window_days: int = Field(30, ge=1, le=365)
    periods: int = Field(3, ge=2, le=12)
    threshold: int = Field(3, ge=1, le=100)
    min_consecutive: int = Field(2, ge=2, le=12)


class AttentionScanResponse(BaseModel):
    scanned_at: datetime
    anchored_at: datetime
    window_days: int
    periods: int
    threshold: int
    min_consecutive: int
    created: int
    updated: int
    cleared: int
    flags: list[AttentionFlagOut]


class AttentionListResponse(BaseModel):
    summary: dict
    items: list[AttentionFlagOut]


class FlagActionRequest(BaseModel):
    actor: str | None = None
    note: str = ""


class FlagActionResponse(BaseModel):
    flag: AttentionFlagOut
    confirmation: str


# --- Prevention form: staging checks (quantity / BOL verification) -------------------------


class QuantityVerifyRequest(BaseModel):
    pro_number: str
    terminal: str = Field(min_length=2, max_length=8)
    scanned_quantity: int = Field(ge=0)
    actor: str


class QuantityCorrectRequest(BaseModel):
    corrected_quantity: int = Field(ge=0)
    actor: str = "dock"


class QuantityConfirmRequest(BaseModel):
    reason: str = Field(min_length=3)
    actor: str = "dock"


class PreventionCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    check_type: str
    pro_number: str
    terminal: str
    commodity_code: str
    actor: str
    performed_at: datetime
    action_taken: str
    outcome: PreventionOutcome
    verification_result: VerificationResult
    expected_quantity: int | None = None
    scanned_quantity: int | None = None
    corrected_quantity: int | None = None
    discrepancy_reason: str = ""
    resolved_at: datetime | None = None
    risk_snapshot: dict | None = None


class StagingRiskBrief(BaseModel):
    elevated_attention: bool
    risk_level: str
    message: str
    signals: list[dict] = []


class QuantityVerifyResponse(BaseModel):
    status: Literal["match", "mismatch", "no_expected_record"]
    pro_number: str
    message: str
    check: PreventionCheckOut | None = None
    risk: StagingRiskBrief | None = None
    requires_followup: list[str] = []


# --- Prevention effectiveness & escalation -------------------------------------------------


class EffectivenessRequest(BaseModel):
    window_days: int = Field(30, ge=1, le=365)
    improvement_threshold: float = Field(0.2, ge=0.0, le=1.0)
    escalation_ceiling: int = Field(2, ge=0, le=10)
    resolve_checks: bool = True


class EffectivenessResponse(BaseModel):
    evaluated_at: datetime
    window_days: int
    improvement_threshold: float
    escalation_ceiling: int
    considered: int
    effective: int
    ineffective: int
    escalated: int
    attention_flags_raised: int
    results: list[dict]
    outcomes: dict | None = None


class LineageEntry(BaseModel):
    id: str
    category: str
    scope: dict
    recommendation_text: str
    pattern_addressed: str
    status: RecommendationStatus
    escalation_level: int
    superseded_by_id: str | None = None
    generated_at: datetime


class LineageResponse(BaseModel):
    recommendation_id: str
    position: int
    length: int
    escalated: bool
    current_id: str
    chain: list[LineageEntry]
