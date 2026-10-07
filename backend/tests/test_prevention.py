"""Tests for the three prevention tiers (what to watch, notes assist, attention flags)."""

import uuid
from datetime import timedelta

import pytest

from app.models import (
    ClassificationSource,
    ExceptionStatus,
    FlagStatus,
    FoundOn,
    OVException,
    OVInvestigation,
    Recommendation,
    RootCauseClassification,
    utcnow,
)
from app.prevention import attention, risk, similarity
from app.prevention.risk import WatchContext
from app.pro_number import generate_pro


def make_classified(
    db,
    *,
    category,
    origin="ATL",
    destination="MEM",
    commodity="61200",
    package_type="Carton",
    entry_user="jmartin",
    days_ago=1,
    notes="",
):
    created = utcnow() - timedelta(days=days_ago)
    exc = OVException(
        pro_number=generate_pro(),
        origin_terminal=origin,
        destination_terminal=destination,
        shipper_name="Acme",
        consignee_name="Globex",
        od400_pro=generate_pro(),
        found_on=FoundOn.trailer,
        trailer_or_bay_number="48812",
        handling_units=1,
        commodity_code=commodity,
        commodity_description="Test freight",
        package_type=package_type,
        pieces=2,
        weight=120.0,
        value_range=2,
        status=ExceptionStatus.investigation_complete,
        entry_user=entry_user,
        content_hash=uuid.uuid4().hex,
        created_at=created,
        updated_at=created,
    )
    db.add(exc)
    db.flush()
    if notes:
        db.add(
            OVInvestigation(
                ov_exception_id=exc.id, steps=[], combined_notes_text=notes, completed_at=created
            )
        )
    db.add(
        RootCauseClassification(
            ov_exception_id=exc.id,
            content_hash=exc.content_hash,
            category=category,
            confidence=0.9,
            reasoning="test",
            model_used="test",
            source=ClassificationSource.ai_fresh,
            classified_at=created,
        )
    )
    db.commit()
    return exc


# --- Tier 1 -------------------------------------------------------------------------------


def test_watch_is_clear_without_history(db):
    result = risk.evaluate(db, WatchContext(origin_terminal="ATL", commodity_code="61200"))
    assert result["clear"] is True
    assert result["signals"] == []


def test_watch_flags_a_concentrated_pattern(db):
    for _ in range(6):
        make_classified(db, category="Improper Packaging")
    for _ in range(6):
        make_classified(db, category="Missed Scan", origin="DAL", commodity="72330")

    result = risk.evaluate(db, WatchContext(origin_terminal="ATL", commodity_code="61200"))

    assert result["clear"] is False
    assert result["risk_level"] in {"watch", "elevated", "high"}
    categories = [s["category"] for s in result["signals"]]
    assert "Improper Packaging" in categories
    # The floor actions are what the dock actually does about it.
    assert any(item["category"] == "Improper Packaging" for item in result["actions"])


def test_watch_attaches_the_standing_recommendation(db):
    for _ in range(6):
        make_classified(db, category="Improper Packaging")
    db.add(
        Recommendation(
            category="Improper Packaging",
            scope={},
            recommendation_text="Re-wrap at the dock before loading.",
            pattern_addressed="Packaging failures at ATL",
            supporting_exception_ids=[],
        )
    )
    db.commit()

    result = risk.evaluate(db, WatchContext(origin_terminal="ATL", commodity_code="61200"))
    signal = next(s for s in result["signals"] if s["category"] == "Improper Packaging")
    assert signal["prevention_action"] == "Re-wrap at the dock before loading."


# --- Tier 2 -------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_similarity_index():
    similarity.reset_index()
    yield
    similarity.reset_index()


def test_notes_assist_needs_enough_words(db):
    result = similarity.suggest(db, "found box")
    assert result["status"] == "too_short"
    assert result["suggested_category"] is None


def test_notes_assist_suggests_the_nearest_category(db):
    for _ in range(3):
        make_classified(
            db,
            category="Improper Packaging",
            notes="Master carton split at the seam and the stretch wrap was torn, pieces loose on the trailer floor.",
        )
    for _ in range(3):
        make_classified(
            db,
            category="Misrouting",
            origin="DAL",
            notes="Label shows destination CLT but the manifest routed the freight to HOU on linehaul 44.",
        )

    result = similarity.suggest(
        db, "Carton seam had split open and the stretch wrap was torn, loose pieces on the trailer floor"
    )

    assert result["status"] == "ok"
    assert result["suggested_category"] == "Improper Packaging"
    assert result["confidence"] > 0
    assert result["matches"]
    assert result["advisory"] is True


def test_notes_assist_reports_missing_details(db):
    result = similarity.suggest(db, "Something seems wrong with this shipment somewhere")
    keys = {gap["key"] for gap in result["missing_details"]}
    assert "counts" in keys


# --- Tier 3 -------------------------------------------------------------------------------


def test_attention_scan_flags_consecutive_breaches(db):
    # 3 in the current 30-day period and 3 in the previous one, same terminal + handler.
    for days in (2, 4, 6, 32, 34, 36):
        make_classified(db, category="Missed Scan", days_ago=days)

    result = attention.scan(db, window_days=30, periods=3, threshold=3, min_consecutive=2)

    assert result["created"] >= 2  # one for the terminal, one for the handler
    scopes = {(f.scope_type, f.scope_value, f.category) for f in result["flags"]}
    assert ("terminal", "ATL", "Missed Scan") in scopes
    assert ("handler", "jmartin", "Missed Scan") in scopes

    flag = next(f for f in result["flags"] if f.scope_type == "terminal")
    assert flag.consecutive_periods == 2
    assert flag.period_counts[:2] == [3, 3]
    assert flag.suggested_action
    assert flag.supporting_exception_ids


def test_attention_scan_ignores_one_off_spikes(db):
    for days in (2, 4, 6):
        make_classified(db, category="Missed Scan", days_ago=days)

    result = attention.scan(db, window_days=30, periods=3, threshold=3, min_consecutive=2)

    assert result["created"] == 0
    assert result["flags"] == []


def test_resolving_a_flag_closes_it_out(db):
    for days in (2, 4, 6, 32, 34, 36):
        make_classified(db, category="Missed Scan", days_ago=days)
    attention.scan(db, window_days=30, periods=3, threshold=3, min_consecutive=2)

    flag = next(f for f in attention.list_flags(db) if f.scope_type == "terminal")
    resolved = attention.resolve(db, flag, "supervisor", "Training refresh delivered.")

    assert resolved.status == FlagStatus.resolved
    assert resolved.resolution_note == "Training refresh delivered."

    # Re-scanning on unchanged data must not immediately reopen what a supervisor just closed.
    again = attention.scan(db, window_days=30, periods=3, threshold=3, min_consecutive=2)
    assert all(f.id != resolved.id or f.status == FlagStatus.resolved for f in again["flags"])
    reopened = [
        f
        for f in again["flags"]
        if f.scope_type == "terminal" and f.category == "Missed Scan" and f.status != FlagStatus.resolved
    ]
    assert reopened == []


def test_attention_scan_clears_a_pattern_that_stopped(db):
    for days in (2, 4, 6, 32, 34, 36):
        make_classified(db, category="Missed Scan", days_ago=days)
    attention.scan(db, window_days=30, periods=3, threshold=3, min_consecutive=2)

    # A tighter threshold means the same data no longer breaches.
    result = attention.scan(db, window_days=30, periods=3, threshold=6, min_consecutive=2)

    assert result["cleared"] >= 2
    assert attention.summary(db)["open"] == 0


# --- API surface ---------------------------------------------------------------------------


def test_prevention_endpoints(client, db):
    for days in (2, 4, 6, 32, 34, 36):
        make_classified(db, category="Missed Scan", days_ago=days, notes="Scan missing at the outbound checkpoint.")

    watch = client.post(
        "/prevention/watch",
        json={"origin_terminal": "ATL", "commodity_code": "61200", "days": 0},
    )
    assert watch.status_code == 200
    assert watch.json()["clear"] is False

    assist = client.post(
        "/prevention/notes-assist",
        json={"text": "No outbound scan recorded at the checkpoint for this piece"},
    )
    assert assist.status_code == 200
    assert assist.json()["advisory"] is True

    scan = client.post(
        "/prevention/attention/scan",
        json={"window_days": 30, "periods": 3, "threshold": 3, "min_consecutive": 2},
    )
    assert scan.status_code == 200
    flag_id = scan.json()["flags"][0]["id"]

    assert client.get("/prevention/attention").json()["summary"]["open"] >= 1
    assert client.get(f"/prevention/attention/{flag_id}/evidence").status_code == 200

    ack = client.post(f"/prevention/attention/{flag_id}/acknowledge", json={"actor": "supervisor"})
    assert ack.status_code == 200
    assert ack.json()["flag"]["status"] == "acknowledged"

    done = client.post(f"/prevention/attention/{flag_id}/resolve", json={"actor": "supervisor"})
    assert done.status_code == 200
    assert done.json()["flag"]["status"] == "resolved"
    assert "Resolved" in done.json()["confirmation"]
