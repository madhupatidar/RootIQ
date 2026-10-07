"""Import real OS&D OV exceptions from the `mock data/` JSON export.

Run (from backend/):
    python -m app.seed.import_mock --reset                 # full 6,500-record load
    python -m app.seed.import_mock --with-notes-only       # only rows that have investigation text
    python -m app.seed.import_mock --limit 300 --dry-run   # preview the mapping

Idempotent on `osdNumber` -> `OVException.source_osd_number`, so re-running updates rather
than duplicating. Only `osdType == "OV"` rows are imported; everything else is out of scope.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clearing_codes import sync_clearing_codes
from app.db import SessionLocal, engine
from app.dedup.hashing import compute_content_hash
from app.models import (
    Base,
    ClassificationCache,
    ClearingCode,
    ExceptionStatus,
    FoundOn,
    OVException,
    OVInvestigation,
    Recommendation,
    RootCauseClassification,
)
from app.questions import build_combined_notes
from app.reference import commodity_code_for, commodity_description_for

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "mock data"

# Export field -> investigation question key (see app/questions.py).
CHECK_FIELDS: list[tuple[str, str]] = [
    ("od400Check", "od400Check"),
    ("billOfLadingCheck", "billOfLadingCheck"),
    ("drCheck", "drCheck"),
    ("psCheck", "psCheck"),
    ("consigneeCheck", "consigneeCheck"),
    ("shipmentCheck", "shipmentCheck"),
]


def _text(value, limit: int | None = None) -> str:
    out = "" if value is None else str(value).strip()
    return out[:limit] if limit else out


def _opt(value, limit: int | None = None) -> str | None:
    out = _text(value, limit)
    return out or None


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_as400_date(value) -> datetime | None:
    """AS400 CYYMMDD -> date.

    Mirrors DateHelper.convertFromAS400Date: the leading digit is the century offset, so
    century = int(date[0]) + 19 and the year is century * 100 + YY.
    1250416 -> century 20, year 2025, month 04, day 16 -> 2025-04-16.
    """
    raw = _text(value)
    if not raw or not raw.isdigit() or int(raw) == 0:
        return None
    raw = raw.zfill(7)  # a leading-zero century arrives as a 6-digit int
    if len(raw) != 7:
        return None
    try:
        year = (int(raw[0]) + 19) * 100 + int(raw[1:3])
        return datetime(year, int(raw[3:5]), int(raw[5:7]), tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_as400_time(value) -> timedelta:
    """AS400 HHMM or HHMMSS -> offset into the day.

    Mirrors DateHelper.convertFromAS400Time: left-pad to 4 (or 6) digits, then read pairs.
    1504 -> 15:04 (3:04 PM); 654 -> 06:54; 135452 -> 13:54:52.
    """
    raw = _text(value)
    if not raw or not raw.isdigit():
        return timedelta()
    raw = raw.zfill(6) if len(raw) > 4 else raw.zfill(4)
    hours, minutes = int(raw[0:2]), int(raw[2:4])
    seconds = int(raw[4:6]) if len(raw) == 6 else 0
    if hours > 23 or minutes > 59 or seconds > 59:
        return timedelta()
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def parse_as400_datetime(date_value, time_value) -> datetime | None:
    stamp = parse_as400_date(date_value)
    return None if stamp is None else stamp + parse_as400_time(time_value)


def parse_entry_datetime(record: dict) -> datetime:
    """Use the AS400 createdDate/createdTime pair; fall back to the entryDate string."""
    stamp = parse_as400_datetime(record.get("createdDate"), record.get("createdTime"))
    if stamp is not None:
        return stamp

    raw_date = _text(record.get("entryDate"))
    if raw_date:
        try:
            return datetime.strptime(raw_date, "%b %d %Y").replace(tzinfo=timezone.utc) + parse_as400_time(
                record.get("entryTime")
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def build_steps(record: dict) -> list[dict]:
    """The 6 Y/N checks + their free-text responses, in export order."""
    steps = []
    for field, key in CHECK_FIELDS:
        answer = _text(record.get(field)).upper() or _text(record.get(f"detail_{field}")).upper()
        note = _text(record.get(f"{field}Response")) or _text(record.get(f"detail_{field}Response"))
        if answer not in {"Y", "N"} and not note:
            continue
        steps.append(
            {
                "question_key": key,
                "answer_yn": answer if answer in {"Y", "N"} else "N",
                "notes_text": note,
            }
        )
    return steps


def build_additional_details(record: dict) -> str:
    """`description` is pipe-delimited (dims||colour|||free text); `remarks` is the clerk's note."""
    segments = [s.strip() for s in _text(record.get("description")).split("|") if s.strip()]
    parts: list[str] = []
    if segments:
        parts.append(f"Dimensions: {segments[0]}")
        if len(segments) > 1:
            parts.append("Description: " + "; ".join(segments[1:]))
    icm = _text(record.get("icm"))
    if icm:
        parts.append(f"Item/carton/model/serial: {icm}")
    remarks = _text(record.get("remarks"))
    if remarks:
        parts.append(f"Remarks: {remarks}")
    return " | ".join(parts)


def derive_status(record: dict, has_notes: bool) -> ExceptionStatus:
    if _int(record.get("cleared")) or _text(record.get("clearingCode")):
        return ExceptionStatus.cleared
    if has_notes:
        return ExceptionStatus.investigation_complete
    if _text(record.get("investigationStatus")) == "1":
        return ExceptionStatus.exception_entry
    return ExceptionStatus.in_progress


def map_record(record: dict, valid_codes: set[str]) -> tuple[dict, list[dict], str] | None:
    """Export record -> (OVException kwargs, investigation steps, combined notes)."""
    if _text(record.get("osdType")).upper() != "OV":
        return None

    steps = build_steps(record)
    combined = build_combined_notes(steps)

    where = _text(record.get("od400WhereFound")).upper()
    found_on = FoundOn.trailer if where == "T" else FoundOn.bay
    location = (
        _text(record.get("od400Trailer"), 20) or _text(record.get("trailer"), 20)
        if found_on == FoundOn.trailer
        else _text(record.get("od400Bay"), 20) or _text(record.get("exceptionLocation"), 20)
    )

    value_range = _int(record.get("valueRange"), 0)
    if value_range not in (1, 2, 3):
        value_range = 1

    dollar_amount = _float(record.get("value1k")) or _float(record.get("totalValue"))
    clearing_code = _text(record.get("clearingCode")).upper() or None
    if clearing_code and clearing_code not in valid_codes:
        clearing_code = None

    pro_number = _text(record.get("proNumber"), 12) or "0"
    created_at = parse_entry_datetime(record)
    commodity_code = commodity_code_for(record.get("commodity"))

    kwargs = {
        "source_osd_number": _int(record.get("osdNumber")),
        "pro_number": pro_number,
        "origin_terminal": _text(record.get("origin"), 8) or "UNK",
        "destination_terminal": _text(record.get("destination"), 8) or "UNK",
        "shipper_name": _text(record.get("shipperName"), 160) or "UNKNOWN",
        "consignee_name": _text(record.get("consigneeName"), 160) or "UNKNOWN",
        "od400_pro": _text(record.get("od400ProNumber"), 12) or "0",
        "manifest_number": _opt(record.get("manifest"), 20),
        "found_on": found_on,
        "trailer_or_bay_number": location or "UNKNOWN",
        "bl_number": _opt(record.get("blNumber"), 30),
        "po_number": _opt(record.get("poNumber"), 30),
        "sn_number": _opt(record.get("snNumber"), 30),
        "hazmat": _text(record.get("hazmat")).upper() == "Y",
        "handling_units": max(_int(record.get("handlingUnits"), 1), 1),
        "commodity_code": commodity_code,
        "commodity_description": commodity_description_for(commodity_code),
        "package_type": _text(record.get("package"), 40) or "UNKNOWN",
        "pieces": max(_int(record.get("pieces"), 1), 1),
        "weight": _float(record.get("weight")),
        "shrink_wrapped": _text(record.get("swOk")).upper() == "Y",
        "item_carton_model_serial": _text(record.get("icm")),
        "value_range": value_range,
        "dollar_amount": dollar_amount or None,
        "manufacturer_brand": _opt(record.get("manufacturerBrand"), 120),
        "additional_details": build_additional_details(record),
        "status": derive_status(record, bool(combined)),
        "clearing_code": clearing_code,
        "cleared_at": parse_as400_datetime(record.get("clearingDate"), record.get("clearingTime")),
        "entry_user": _text(record.get("entryBy"), 60) or "UNKNOWN",
        "assigned_to": _opt(record.get("assignedTo"), 60),
        "content_hash": compute_content_hash(pro_number, combined),
        "created_at": created_at,
        "updated_at": created_at,
    }
    return kwargs, steps, combined


def load_records(data_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(glob.glob(os.path.join(str(data_dir), "*.json"))):
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        records.extend(rows)
    return records


def reset_data(db: Session) -> None:
    db.execute(delete(Recommendation))
    db.execute(delete(RootCauseClassification))
    db.execute(delete(ClassificationCache))
    db.execute(delete(OVInvestigation))
    db.execute(delete(OVException))
    db.commit()


def purge_synthetic(db: Session) -> int:
    """Drop the generated seed rows (source_osd_number IS NULL) so only real data remains."""
    ids = db.scalars(select(OVException.id).where(OVException.source_osd_number.is_(None))).all()
    if not ids:
        return 0

    db.execute(delete(RootCauseClassification).where(RootCauseClassification.ov_exception_id.in_(ids)))
    db.execute(delete(OVInvestigation).where(OVInvestigation.ov_exception_id.in_(ids)))
    db.execute(delete(OVException).where(OVException.id.in_(ids)))

    # Cache entries whose hash no longer belongs to any exception would skew the hit rate.
    live_hashes = select(OVException.content_hash)
    db.execute(delete(ClassificationCache).where(ClassificationCache.content_hash.not_in(live_hashes)))
    # Recommendations cite exception ids that no longer exist.
    db.execute(delete(Recommendation))
    db.commit()
    return len(ids)


def import_mock_data(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    limit: int | None = None,
    with_notes_only: bool = False,
    reset: bool = False,
    purge_synthetic_rows: bool = False,
    dry_run: bool = False,
) -> dict:
    Base.metadata.create_all(bind=engine)
    records = load_records(data_dir)

    purged = 0
    with SessionLocal() as db:
        sync_clearing_codes(db)
        valid_codes = set(db.scalars(select(ClearingCode.code)).all())
        if reset and not dry_run:
            reset_data(db)
        elif purge_synthetic_rows and not dry_run:
            purged = purge_synthetic(db)

        existing = {
            osd: eid
            for osd, eid in db.execute(
                select(OVException.source_osd_number, OVException.id).where(
                    OVException.source_osd_number.is_not(None)
                )
            ).all()
        }

        created = updated = skipped_no_notes = skipped_non_ov = 0
        with_notes = 0

        for record in records:
            mapped = map_record(record, valid_codes)
            if mapped is None:
                skipped_non_ov += 1
                continue
            kwargs, steps, combined = mapped

            if with_notes_only and not combined:
                skipped_no_notes += 1
                continue
            if combined:
                with_notes += 1

            if dry_run:
                created += 1
            else:
                osd = kwargs["source_osd_number"]
                exc = db.get(OVException, existing[osd]) if osd in existing else None
                if exc is None:
                    exc = OVException(**kwargs)
                    db.add(exc)
                    created += 1
                else:
                    for key, value in kwargs.items():
                        setattr(exc, key, value)
                    updated += 1

                if steps:
                    investigation = exc.investigation or OVInvestigation()
                    investigation.steps = steps
                    investigation.combined_notes_text = combined
                    investigation.completed_at = kwargs["created_at"]
                    exc.investigation = investigation

            if limit and (created + updated) >= limit:
                break

        if not dry_run:
            db.commit()

    return {
        "source_files": len(sorted(glob.glob(os.path.join(str(data_dir), "*.json")))),
        "records_read": len(records),
        "synthetic_rows_purged": purged,
        "created": created,
        "updated": updated,
        "with_investigation_text": with_notes,
        "skipped_no_notes": skipped_no_notes,
        "skipped_non_ov": skipped_non_ov,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OV exceptions from the mock data export")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--with-notes-only",
        action="store_true",
        help="import only records that carry investigation text (the ones worth classifying)",
    )
    parser.add_argument("--reset", action="store_true", help="delete existing POC data first")
    parser.add_argument(
        "--purge-synthetic",
        action="store_true",
        help="delete the generated seed rows (no osdNumber) so only real export data remains",
    )
    parser.add_argument("--dry-run", action="store_true", help="map and count without writing")
    args = parser.parse_args()

    if not args.data_dir.exists():
        raise SystemExit(f"Data directory not found: {args.data_dir}")

    summary = import_mock_data(
        args.data_dir,
        limit=args.limit,
        with_notes_only=args.with_notes_only,
        reset=args.reset,
        purge_synthetic_rows=args.purge_synthetic,
        dry_run=args.dry_run,
    )
    for key, value in summary.items():
        print(f"{key:26s} {value}")


if __name__ == "__main__":
    main()
