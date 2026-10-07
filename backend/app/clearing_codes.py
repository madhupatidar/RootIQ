"""Clearing-code lookup seeding (spec Section 5).

TODO: these 15 values are hardcoded for POC speed. They are owned by the clearing-code
reference API - replace `CLEARING_CODES` with a sync job against that API (id/code/full-form)
so this table cannot silently drift out of sync with the source system.
"""

from sqlalchemy.orm import Session

from app.models import ClearingCode, utcnow

CLEARING_CODES: list[tuple[str, str]] = [
    ("BE", "Billing error"),
    ("BS", "Billing Applied, STORAG"),
    ("BW", "Billing Waived, STORAG"),
    ("CA", "Consignee agreed to accept freight"),
    ("CF", "Claim filed"),
    ("CG", "Cleared to cargo"),
    ("CLP", "Claims Prevention"),
    ("CP", "Claim paid"),
    ("CR", "Credit dept holding open"),
    ("DA", "Cleared on free astray"),
    ("FC", "Forced clear by claims due to improper follow-up by terminal"),
    ("RC", "Reconsigned"),
    ("RI", "Returned to interline"),
    ("RS", "Returned to shipper"),
    ("SV", "Cleared to salvage"),
]


def sync_clearing_codes(db: Session) -> int:
    """Upsert the reference codes. Idempotent - safe to call on every startup."""
    existing = {c.code: c for c in db.query(ClearingCode).all()}
    now = utcnow()
    for code, full_form in CLEARING_CODES:
        row = existing.get(code)
        if row is None:
            db.add(ClearingCode(code=code, full_form=full_form, synced_at=now))
        else:
            row.full_form = full_form
            row.synced_at = now
    db.commit()
    return len(CLEARING_CODES)
