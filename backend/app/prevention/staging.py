"""Prevention Form - point-of-process staging checks.

The first concrete staging check is quantity verification: the worker scans the PRO and keys
the piece count *before* the freight is staged, so a discrepancy is caught while it can still
be fixed rather than logged as an overage afterwards.

Every check is recorded as a `PreventionCheck` with outcome 'pending'; effectiveness.py
resolves it later into 'prevented' or 'recurred'. Coverage matters even when nothing is
flagged - a check with no active risk signal is still evidence for the outcome rate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    ExpectedShipment,
    PreventionCheck,
    PreventionOutcome,
    VerificationResult,
    utcnow,
)
from app.prevention import risk
from app.prevention.risk import WatchContext

CHECK_TYPE = "quantity_verify"

RESOLVED_RESULTS = {
    VerificationResult.match,
    VerificationResult.mismatch_corrected,
    VerificationResult.mismatch_confirmed,
}


def risk_snapshot(db: Session, terminal: str, commodity_code: str) -> dict:
    """Tier-1 lookup for this terminal + commodity - reused as-is, not re-implemented here.

    The check itself always runs; this only decides whether the UI should present it as
    elevated attention.
    """
    result = risk.evaluate(db, WatchContext(origin_terminal=terminal, commodity_code=commodity_code))
    signals = result.get("signals") or []
    return {
        "elevated_attention": bool(signals),
        "risk_level": result["risk_level"],
        "message": result["message"],
        "signals": [
            {"category": s["category"], "severity": s["severity"], "pattern": s["pattern"]}
            for s in signals
        ],
    }


def is_resolved(check: PreventionCheck) -> bool:
    return check.verification_result in RESOLVED_RESULTS


def quantity_verify(
    db: Session, *, pro_number: str, terminal: str, scanned_quantity: int, actor: str
) -> dict:
    expected = db.get(ExpectedShipment, pro_number.strip())
    if expected is None:
        # No manifest record to compare against - say so plainly rather than guessing a count.
        return {
            "status": "no_expected_record",
            "pro_number": pro_number,
            "message": (
                f"No expected shipment record for PRO {pro_number}. Nothing to verify against — "
                "confirm the PRO with the manifest before staging."
            ),
            "check": None,
            "risk": None,
            "requires_followup": [],
        }

    snapshot = risk_snapshot(db, terminal, expected.commodity_code)
    matched = int(scanned_quantity) == int(expected.expected_quantity)
    now = utcnow()

    check = PreventionCheck(
        check_type=CHECK_TYPE,
        pro_number=expected.pro_number,
        terminal=terminal,
        commodity_code=expected.commodity_code,
        actor=actor,
        performed_at=now,
        outcome=PreventionOutcome.pending,
        expected_quantity=expected.expected_quantity,
        scanned_quantity=int(scanned_quantity),
        risk_snapshot=snapshot,
        verification_result=VerificationResult.match if matched else VerificationResult.mismatch_pending,
        action_taken=(
            f"Scanned count {scanned_quantity} verified against the expected {expected.expected_quantity}."
            if matched
            else (
                f"Scanned count {scanned_quantity} does not match the expected "
                f"{expected.expected_quantity} — held for correction or confirmation."
            )
        ),
        resolved_at=now if matched else None,
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    return {
        "status": "match" if matched else "mismatch",
        "pro_number": expected.pro_number,
        "message": (
            "Count matches the expected quantity — freight is clear to stage."
            if matched
            else (
                f"Count mismatch: scanned {scanned_quantity}, expected {expected.expected_quantity}. "
                "Recount and correct, or confirm the discrepancy with a reason, before staging."
            )
        ),
        "check": check,
        "risk": snapshot,
        "requires_followup": [] if matched else ["correct", "confirm"],
    }


def record_correction(
    db: Session, check: PreventionCheck, *, corrected_quantity: int, actor: str
) -> PreventionCheck:
    check.corrected_quantity = int(corrected_quantity)
    check.verification_result = VerificationResult.mismatch_corrected
    check.actor = actor or check.actor
    check.action_taken = (
        f"Physical recount by {actor or check.actor}: corrected to {corrected_quantity} "
        f"against the expected {check.expected_quantity}."
    )
    check.resolved_at = utcnow()
    db.commit()
    db.refresh(check)
    return check


def confirm_discrepancy(db: Session, check: PreventionCheck, *, reason: str, actor: str) -> PreventionCheck:
    check.discrepancy_reason = reason
    check.verification_result = VerificationResult.mismatch_confirmed
    check.actor = actor or check.actor
    check.action_taken = (
        f"Discrepancy confirmed as real by {actor or check.actor}: {reason}"
    )
    check.resolved_at = utcnow()
    db.commit()
    db.refresh(check)
    return check
