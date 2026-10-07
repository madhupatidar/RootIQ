"""SQLAlchemy models for the OV Exception root-cause POC (spec Section 3)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class FoundOn(str, enum.Enum):
    trailer = "trailer"
    bay = "bay"


class ExceptionStatus(str, enum.Enum):
    exception_entry = "exception_entry"
    in_progress = "in_progress"
    investigation_complete = "investigation_complete"
    needs_cleared = "needs_cleared"
    cleared = "cleared"


class ClassificationSource(str, enum.Enum):
    ai_fresh = "ai_fresh"
    cache_hit = "cache_hit"
    human_override = "human_override"


class FlagStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class RecommendationStatus(str, enum.Enum):
    active = "active"
    effective = "effective"
    ineffective = "ineffective"
    superseded = "superseded"


class VerificationResult(str, enum.Enum):
    match = "match"
    mismatch_pending = "mismatch_pending"
    mismatch_corrected = "mismatch_corrected"
    mismatch_confirmed = "mismatch_confirmed"


class PreventionOutcome(str, enum.Enum):
    pending = "pending"
    prevented = "prevented"
    recurred = "recurred"


def _enum(enum_cls, name: str) -> Enum:
    # native_enum=False keeps the schema portable (VARCHAR + CHECK) across Postgres/SQLite.
    return Enum(enum_cls, name=name, native_enum=False, values_callable=lambda e: [m.value for m in e])


class ClearingCode(Base):
    """Lookup table seeded from the clearing-code reference API (spec Section 5)."""

    __tablename__ = "clearing_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    full_form: Mapped[str] = mapped_column(String(120), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OVException(Base):
    __tablename__ = "ov_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    pro_number: Mapped[str] = mapped_column(String(12), index=True, nullable=False)
    origin_terminal: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    destination_terminal: Mapped[str] = mapped_column(String(8), index=True, nullable=False)

    # Synthetic values only for the POC - no real PII is stored.
    shipper_name: Mapped[str] = mapped_column(String(160), nullable=False)
    consignee_name: Mapped[str] = mapped_column(String(160), nullable=False)

    od400_pro: Mapped[str] = mapped_column(String(12), nullable=False)
    manifest_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    found_on: Mapped[FoundOn] = mapped_column(_enum(FoundOn, "found_on"), nullable=False)
    trailer_or_bay_number: Mapped[str] = mapped_column(String(20), nullable=False)

    bl_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    po_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sn_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    hazmat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    handling_units: Mapped[int] = mapped_column(Integer, nullable=False)
    # Official commodity master code (app/reference.py); the export only carries the
    # description, so the importer resolves it back to a code and keeps both.
    commodity_code: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    commodity_description: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    package_type: Mapped[str] = mapped_column(String(40), nullable=False)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    shrink_wrapped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    item_carton_model_serial: Mapped[str] = mapped_column(Text, default="", nullable=False)

    value_range: Mapped[int] = mapped_column(Integer, nullable=False)  # 1: $0-250, 2: $250-1000, 3: >$1000
    dollar_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    manufacturer_brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    additional_details: Mapped[str] = mapped_column(Text, default="", nullable=False)

    status: Mapped[ExceptionStatus] = mapped_column(
        _enum(ExceptionStatus, "exception_status"),
        default=ExceptionStatus.exception_entry,
        index=True,
        nullable=False,
    )
    clearing_code: Mapped[str | None] = mapped_column(
        String(8), ForeignKey("clearing_codes.code"), index=True, nullable=True
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry_user: Mapped[str] = mapped_column(String(60), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(60), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # OS&D export key (osdNumber). Set by the mock-data importer, null for synthetic seed rows.
    source_osd_number: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)

    # Hand-labelled ground truth used only by the validation/accuracy report (spec Section 12/14).
    labeled_category: Mapped[str | None] = mapped_column(String(60), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    investigation: Mapped[OVInvestigation | None] = relationship(
        back_populates="ov_exception", uselist=False, cascade="all, delete-orphan"
    )
    classifications: Mapped[list[RootCauseClassification]] = relationship(
        back_populates="ov_exception",
        cascade="all, delete-orphan",
        order_by="RootCauseClassification.classified_at",
    )

    __table_args__ = (
        CheckConstraint("value_range IN (1, 2, 3)", name="ck_ov_value_range"),
    )


class OVInvestigation(Base):
    __tablename__ = "ov_investigations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ov_exception_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ov_exceptions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # [{ "question_key": str, "answer_yn": "Y"|"N", "notes_text": str }, ...]
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    combined_notes_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    ov_exception: Mapped[OVException] = relationship(back_populates="investigation")


class RootCauseClassification(Base):
    """Append-only audit history - one row per classification event (fresh, cached or overridden)."""

    __tablename__ = "root_cause_classifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ov_exception_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ov_exceptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model_used: Mapped[str] = mapped_column(String(80), nullable=False)
    source: Mapped[ClassificationSource] = mapped_column(
        _enum(ClassificationSource, "classification_source"), index=True, nullable=False
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # {factor: bool} - the *why* behind the category (app/ai/taxonomy.py CONTRIBUTING_FACTORS).
    # Nullable: rows classified before this column existed simply carry no factors.
    contributing_factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    ov_exception: Mapped[OVException] = relationship(back_populates="classifications")


class ClassificationCache(Base):
    """One row per unique content_hash ever seen - the dedup lookup (spec Section 6)."""

    __tablename__ = "classification_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model_used: Mapped[str] = mapped_column(String(80), nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contributing_factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    scope: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # {terminal, commodity, time_window}
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_addressed: Mapped[str] = mapped_column(Text, default="", nullable=False)
    supporting_exception_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)

    # Effectiveness loop: a recommendation that did not reduce recurrence is marked ineffective
    # and superseded by a fresh one at the next escalation level.
    status: Mapped[RecommendationStatus] = mapped_column(
        _enum(RecommendationStatus, "recommendation_status"),
        default=RecommendationStatus.active,
        index=True,
        nullable=False,
    )
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recommendations.id"), nullable=True
    )


class AttentionFlag(Base):
    """A repeat-issue signal raised against a terminal or a handler (spec extension: tier 3).

    Distinct from `Recommendation`: a recommendation is generic advice for a category, a flag
    is addressed to a named supervisor scope that breached a threshold in consecutive periods.
    """

    __tablename__ = "attention_flags"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    scope_type: Mapped[str] = mapped_column(String(16), index=True, nullable=False)  # terminal | handler
    scope_value: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(60), index=True, nullable=False)

    severity: Mapped[str] = mapped_column(String(12), default="watch", nullable=False)  # watch | high
    status: Mapped[FlagStatus] = mapped_column(
        _enum(FlagStatus, "flag_status"), default=FlagStatus.open, index=True, nullable=False
    )

    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutive_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_counts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # newest period first
    current_period_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    previous_period_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    pattern_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    supporting_exception_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ExpectedShipment(Base):
    """POC SIMPLIFICATION: a tiny stand-in for the real manifest / OD400 quantity lookup.

    In production the staging check would query the manifest service for the expected piece
    count. For the POC we seed a small reference table alongside the synthetic exceptions so
    the quantity-verify flow has something truthful to compare against.
    """

    __tablename__ = "expected_shipments"

    pro_number: Mapped[str] = mapped_column(String(12), primary_key=True)
    terminal: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    expected_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    commodity_code: Mapped[str] = mapped_column(String(80), index=True, nullable=False)


class PreventionCheck(Base):
    """A prevention action performed at the point of process, before an exception exists.

    `outcome` starts as 'pending' and is resolved later (app/prevention/effectiveness.py) into
    'prevented' or 'recurred' - that is what makes prevention measurable rather than asserted.
    """

    __tablename__ = "prevention_checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    check_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    pro_number: Mapped[str] = mapped_column(String(12), index=True, nullable=False)
    terminal: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    commodity_code: Mapped[str] = mapped_column(String(80), index=True, default="", nullable=False)
    actor: Mapped[str] = mapped_column(String(60), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False
    )
    action_taken: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outcome: Mapped[PreventionOutcome] = mapped_column(
        _enum(PreventionOutcome, "prevention_outcome"),
        default=PreventionOutcome.pending,
        index=True,
        nullable=False,
    )

    verification_result: Mapped[VerificationResult] = mapped_column(
        _enum(VerificationResult, "verification_result"), index=True, nullable=False
    )
    expected_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scanned_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corrected_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discrepancy_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Snapshot of the tier-1 signal that was live when the check ran (risk.py lookup).
    risk_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
