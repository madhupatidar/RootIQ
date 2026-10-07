"""Prevention form (staging checks) and the effectiveness/escalation loop."""

import json
from datetime import timedelta

import pytest

from app.ai import ollama_client
from app.models import (
    AttentionFlag,
    ExpectedShipment,
    FlagStatus,
    PreventionCheck,
    PreventionOutcome,
    Recommendation,
    RecommendationStatus,
    VerificationResult,
    utcnow,
)
from app.prevention import effectiveness
from app.pro_number import generate_pro
from tests.test_prevention import make_classified

PRO = "402118834007"


@pytest.fixture()
def expected(db):
    row = ExpectedShipment(pro_number=PRO, terminal="ATL", expected_quantity=6, commodity_code="61200")
    db.add(row)
    db.commit()
    return row


def verify(client, quantity, pro=PRO):
    return client.post(
        "/prevention/staging-check/quantity-verify",
        json={"pro_number": pro, "terminal": "ATL", "scanned_quantity": quantity, "actor": "dwhite"},
    )


# --- Task 2: quantity verification ---------------------------------------------------------


def test_quantity_verify_without_an_expected_record_does_not_guess(client, db):
    response = verify(client, 6, pro=generate_pro())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_expected_record"
    assert body["check"] is None
    assert body["requires_followup"] == []
    assert db.query(PreventionCheck).count() == 0


def test_quantity_verify_match_logs_a_prevention_check(client, db, expected):
    body = verify(client, 6).json()

    assert body["status"] == "match"
    assert body["requires_followup"] == []
    check = body["check"]
    assert check["verification_result"] == "match"
    assert check["outcome"] == "pending"
    assert check["terminal"] == "ATL"
    assert check["commodity_code"] == "61200"
    assert check["actor"] == "dwhite"
    # Coverage is tracked even with no active risk signal on this scope.
    assert body["risk"]["elevated_attention"] is False


def test_quantity_verify_flags_elevated_attention_when_risk_has_a_signal(client, db, expected):
    for _ in range(6):
        make_classified(db, category="Improper Packaging", origin="ATL", commodity="61200")

    body = verify(client, 6).json()

    assert body["risk"]["elevated_attention"] is True
    assert body["risk"]["signals"]
    assert body["check"]["risk_snapshot"]["elevated_attention"] is True


def test_quantity_mismatch_requires_a_follow_up_then_accepts_a_correction(client, db, expected):
    body = verify(client, 4).json()

    assert body["status"] == "mismatch"
    assert body["requires_followup"] == ["correct", "confirm"]
    assert body["check"]["verification_result"] == "mismatch_pending"
    assert body["check"]["resolved_at"] is None

    check_id = body["check"]["id"]
    corrected = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/correct",
        json={"corrected_quantity": 6, "actor": "dwhite"},
    )

    assert corrected.status_code == 200
    assert corrected.json()["verification_result"] == "mismatch_corrected"
    assert corrected.json()["corrected_quantity"] == 6
    assert corrected.json()["resolved_at"] is not None


def test_quantity_mismatch_can_be_confirmed_with_a_reason(client, db, expected):
    check_id = verify(client, 8).json()["check"]["id"]

    confirmed = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/confirm",
        json={"reason": "Shipper over-shipped, consignee will accept the extra two.", "actor": "dwhite"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["verification_result"] == "mismatch_confirmed"
    assert "over-shipped" in confirmed.json()["discrepancy_reason"]


def test_a_confirm_reason_is_required(client, db, expected):
    check_id = verify(client, 8).json()["check"]["id"]
    response = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/confirm", json={"reason": ""}
    )
    assert response.status_code == 422


def test_follow_ups_are_rejected_on_an_already_resolved_check(client, db, expected):
    check_id = verify(client, 4).json()["check"]["id"]
    client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/correct",
        json={"corrected_quantity": 6},
    )

    again = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/correct",
        json={"corrected_quantity": 5},
    )
    confirm = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/confirm",
        json={"reason": "changed my mind"},
    )

    assert again.status_code == 409
    assert confirm.status_code == 409


def test_a_matched_check_is_also_closed_to_follow_ups(client, db, expected):
    check_id = verify(client, 6).json()["check"]["id"]
    response = client.post(
        f"/prevention/staging-check/quantity-verify/{check_id}/correct",
        json={"corrected_quantity": 5},
    )
    assert response.status_code == 409


# --- Task 3: effectiveness, escalation and lineage -----------------------------------------


def make_recommendation(db, *, days_ago=60, escalation_level=0, category="Missed Scan"):
    rec = Recommendation(
        category=category,
        scope={"terminal": "ATL", "commodity": None, "time_window": "last 90 days"},
        recommendation_text="Scan at every checkpoint on this lane.",
        pattern_addressed="Missed scans at ATL",
        supporting_exception_ids=[],
        generated_at=utcnow() - timedelta(days=days_ago),
        escalation_level=escalation_level,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def seed_unchanged_volume(db, category="Missed Scan"):
    """Four exceptions in the 30 days before the recommendation, four in the 30 days after."""
    for days in (70, 75, 80, 85, 40, 45, 50, 55):
        make_classified(db, category=category, days_ago=days)


@pytest.fixture()
def stub_recommender(monkeypatch):
    calls = {"count": 0}

    def fake_generate(prompt, **kwargs):
        calls["count"] += 1
        return json.dumps(
            {
                "recommendations": [
                    {
                        "category": "Missed Scan",
                        "pattern_addressed": "Missed scans still concentrated at ATL",
                        "recommendation": "Audit one shift of ATL scan logs against the manifest daily.",
                    }
                ]
            }
        )

    monkeypatch.setattr(ollama_client, "generate", fake_generate)
    return calls


def test_ineffective_recommendation_is_escalated_by_the_existing_recommender(
    db, stub_recommender
):
    rec = make_recommendation(db)
    seed_unchanged_volume(db)

    result = effectiveness.evaluate_recommendation_effectiveness(db, window_days=30)

    assert stub_recommender["count"] == 1  # the existing recommender, not a second path
    assert result["ineffective"] == 1
    assert result["escalated"] == 1

    db.refresh(rec)
    assert rec.status == RecommendationStatus.ineffective
    assert rec.superseded_by_id is not None

    replacement = db.get(Recommendation, rec.superseded_by_id)
    assert replacement.escalation_level == 1
    assert replacement.status == RecommendationStatus.active


def test_effective_recommendation_is_not_escalated(db, stub_recommender):
    rec = make_recommendation(db)
    for days in (70, 75, 80, 85):
        make_classified(db, category="Missed Scan", days_ago=days)

    result = effectiveness.evaluate_recommendation_effectiveness(db, window_days=30)

    assert result["effective"] == 1
    assert result["escalated"] == 0
    assert stub_recommender["count"] == 0
    db.refresh(rec)
    assert rec.status == RecommendationStatus.effective
    assert rec.superseded_by_id is None


def test_escalation_ceiling_raises_an_attention_flag_instead_of_another_nudge(db, stub_recommender):
    rec = make_recommendation(db, escalation_level=2)
    seed_unchanged_volume(db)

    result = effectiveness.evaluate_recommendation_effectiveness(
        db, window_days=30, escalation_ceiling=2
    )

    assert result["escalated"] == 0
    assert result["attention_flags_raised"] == 1
    assert stub_recommender["count"] == 0  # no third recommendation

    db.refresh(rec)
    assert rec.status == RecommendationStatus.ineffective
    assert rec.superseded_by_id is None

    flag = db.query(AttentionFlag).one()
    assert flag.scope_type == "terminal"
    assert flag.scope_value == "ATL"
    assert flag.category == "Missed Scan"
    assert flag.status == FlagStatus.open
    assert flag.suggested_action


def test_lineage_walks_the_chain_both_ways(client, db, stub_recommender):
    rec = make_recommendation(db)
    seed_unchanged_volume(db)
    effectiveness.evaluate_recommendation_effectiveness(db, window_days=30)
    db.refresh(rec)

    lineage = client.get(f"/prevention/recommendations/{rec.id}/lineage").json()
    assert lineage["escalated"] is True
    assert lineage["length"] == 2
    assert lineage["position"] == 1
    assert lineage["current_id"] == str(rec.superseded_by_id)

    from_child = client.get(f"/prevention/recommendations/{rec.superseded_by_id}/lineage").json()
    assert from_child["position"] == 2
    assert from_child["chain"][0]["id"] == str(rec.id)


def test_resolve_outcomes_scores_pending_checks(db, expected):
    old = utcnow() - timedelta(days=45)
    prevented = PreventionCheck(
        check_type="quantity_verify",
        pro_number=PRO,
        terminal="ATL",
        commodity_code="61200",
        actor="dwhite",
        performed_at=old,
        verification_result=VerificationResult.match,
    )
    recurred = PreventionCheck(
        check_type="quantity_verify",
        pro_number=generate_pro(),
        terminal="ATL",
        commodity_code="61200",
        actor="dwhite",
        performed_at=old,
        verification_result=VerificationResult.mismatch_confirmed,
    )
    db.add_all([prevented, recurred])
    db.commit()

    follow_up = make_classified(db, category="Missed Scan", days_ago=10)
    follow_up.pro_number = recurred.pro_number
    db.commit()

    result = effectiveness.resolve_outcomes(db, window_days=30)

    assert result["prevented"] == 1
    assert result["recurred"] == 1
    db.refresh(prevented)
    db.refresh(recurred)
    assert prevented.outcome == PreventionOutcome.prevented
    assert recurred.outcome == PreventionOutcome.recurred


def test_evaluate_endpoint_reports_the_escalation(client, db, stub_recommender):
    make_recommendation(db)
    seed_unchanged_volume(db)

    response = client.post("/prevention/recommendations/evaluate", json={"window_days": 30})

    assert response.status_code == 200
    body = response.json()
    assert body["escalated"] == 1
    assert body["outcomes"]["pending_considered"] == 0
    assert body["results"][0]["verdict"] == "escalated"
