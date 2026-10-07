import random

import pytest

from app.ai.taxonomy import empty_factors
from app.dedup.cache import ClassificationResult
from app.pro_number import generate_pro
from app.routes import classify as classify_route

RNG = random.Random(7)


def make_payload(**overrides) -> dict:
    payload = {
        "pro_number": generate_pro(RNG),
        "origin_terminal": "ATL",
        "destination_terminal": "MEM",
        "shipper_name": "Northline Supply Co",
        "consignee_name": "Harbor Point Distribution",
        "od400_pro": generate_pro(RNG),
        "manifest_number": "M123456",
        "found_on": "trailer",
        "trailer_or_bay_number": "48812",
        "hazmat": False,
        "handling_units": 1,
        "commodity_code": "61200",
        "package_type": "Carton",
        "pieces": 4,
        "weight": 220.5,
        "shrink_wrapped": True,
        "item_carton_model_serial": "MDL-1234",
        "value_range": 1,
        "additional_details": "Blue tape, heat number 449102.",
        "entry_user": "jmartin",
    }
    payload.update(overrides)
    return payload


INVESTIGATION = {
    "steps": [
        {
            "question_key": "freight_scanned_at_checkpoints",
            "answer_yn": "N",
            "notes_text": "No origin dock scan and no unload scan exist for this pro.",
        },
        {
            "question_key": "packaging_intact",
            "answer_yn": "Y",
            "notes_text": "Packaging is fully intact.",
        },
    ]
}


@pytest.fixture()
def stub_model(monkeypatch):
    calls = {"count": 0}

    def fake_classify(text: str, **kwargs) -> ClassificationResult:
        calls["count"] += 1
        calls["context"] = kwargs.get("context")
        return ClassificationResult(
            category="Missed Scan",
            confidence=0.9,
            reasoning="No scans recorded at any checkpoint.",
            model_used="ollama:test-model",
            contributing_factors={**empty_factors(), "scan_issue": True},
        )

    monkeypatch.setattr(classify_route, "classify_ov_exception", fake_classify)
    return calls


def test_invalid_pro_number_rejected(client):
    response = client.post("/ov-exceptions", json=make_payload(pro_number="123456789012"))
    assert response.status_code == 422


def test_dollar_amount_required_for_high_value(client):
    response = client.post("/ov-exceptions", json=make_payload(value_range=3))
    assert response.status_code == 422


def test_content_hash_present_on_creation(client):
    response = client.post("/ov-exceptions", json=make_payload())
    assert response.status_code == 201
    assert len(response.json()["content_hash"]) == 64


def test_end_to_end_flow_with_cache_hit(client, stub_model):
    created = client.post("/ov-exceptions", json=make_payload()).json()
    exception_id = created["id"]

    detail = client.post(f"/ov-exceptions/{exception_id}/investigation", json=INVESTIGATION).json()
    assert detail["status"] == "investigation_complete"
    assert "No origin dock scan" in detail["investigation"]["combined_notes_text"]
    first_hash = detail["content_hash"]
    assert first_hash != created["content_hash"]  # re-hashed once notes landed

    fresh = client.post(f"/classify/{exception_id}").json()
    assert fresh["source"] == "ai_fresh"
    assert fresh["category"] == "Missed Scan"
    assert stub_model["count"] == 1

    cached = client.post(f"/classify/{exception_id}").json()
    assert cached["source"] == "cache_hit"
    assert cached["category"] == "Missed Scan"
    assert stub_model["count"] == 1  # no second model call

    history = client.get(f"/classify/{exception_id}/history").json()
    assert len(history) == 2

    stats = client.get("/insights/cache-stats").json()
    assert stats["cache_hits"] == 1
    assert stats["ai_fresh_calls"] == 1
    assert stats["cache_hit_rate"] == 0.5
    assert stats["ollama_calls_saved"] == 1


def test_duplicate_exception_hits_cache_without_model_call(client, stub_model):
    payload = make_payload()
    first = client.post("/ov-exceptions", json=payload).json()
    client.post(f"/ov-exceptions/{first['id']}/investigation", json=INVESTIGATION)
    client.post(f"/classify/{first['id']}")

    second = client.post("/ov-exceptions", json=payload).json()
    client.post(f"/ov-exceptions/{second['id']}/investigation", json=INVESTIGATION)
    result = client.post(f"/classify/{second['id']}").json()

    assert result["source"] == "cache_hit"
    assert stub_model["count"] == 1


def test_contributing_factors_persist_through_fresh_and_cached_paths(client, stub_model):
    created = client.post("/ov-exceptions", json=make_payload()).json()
    client.post(f"/ov-exceptions/{created['id']}/investigation", json=INVESTIGATION)

    fresh = client.post(f"/classify/{created['id']}").json()
    assert fresh["contributing_factors"]["scan_issue"] is True
    assert fresh["contributing_factors"]["quantity_mismatch"] is False
    # Deterministic, not the model's guess: one exception is nowhere near the handler threshold.
    assert fresh["contributing_factors"]["training_signal"] is False

    # The classifier receives structured context, not just the notes text.
    assert stub_model["context"] is not None
    assert stub_model["context"].terminal == "ATL"
    assert stub_model["context"].handler == "jmartin"
    assert stub_model["context"].investigation_flags["freight_scanned_at_checkpoints"] == "N"

    cached = client.post(f"/classify/{created['id']}").json()
    assert cached["source"] == "cache_hit"
    assert cached["contributing_factors"]["scan_issue"] is True


def test_clearing_requires_known_code(client):
    created = client.post("/ov-exceptions", json=make_payload()).json()

    bad = client.post(f"/ov-exceptions/{created['id']}/clear", json={"clearing_code": "ZZ"})
    assert bad.status_code == 422

    good = client.post(f"/ov-exceptions/{created['id']}/clear", json={"clearing_code": "sv"})
    assert good.status_code == 200
    assert good.json()["clearing_code"] == "SV"
    assert good.json()["status"] == "cleared"
    assert good.json()["cleared_at"] is not None


def test_clearing_codes_lookup_has_15_entries(client):
    codes = {c["code"]: c["full_form"] for c in client.get("/clearing-codes").json()}
    assert len(codes) == 15
    assert codes["CLP"] == "Claims Prevention"
    assert codes["SV"] == "Cleared to salvage"


def test_override_appends_history_without_overwriting(client, stub_model):
    created = client.post("/ov-exceptions", json=make_payload()).json()
    client.post(f"/ov-exceptions/{created['id']}/investigation", json=INVESTIGATION)
    client.post(f"/classify/{created['id']}")

    override = client.post(
        f"/classify/{created['id']}/override",
        json={"category": "Labeling Error", "reviewer": "kpatel"},
    ).json()
    assert override["source"] == "human_override"

    history = client.get(f"/classify/{created['id']}/history").json()
    assert [h["source"] for h in history] == ["human_override", "ai_fresh"]

    bad = client.post(f"/classify/{created['id']}/override", json={"category": "Nonsense"})
    assert bad.status_code == 422


def test_distribution_and_accuracy(client, stub_model):
    created = client.post(
        "/ov-exceptions", json=make_payload(labeled_category="Missed Scan")
    ).json()
    client.post(f"/ov-exceptions/{created['id']}/investigation", json=INVESTIGATION)
    client.post(f"/classify/{created['id']}")

    dist = client.get("/insights/distribution").json()
    assert dist["total_classified"] == 1
    assert dist["categories"][0]["category"] == "Missed Scan"
    assert dist["categories"][0]["percentage"] == 100.0

    acc = client.get("/insights/accuracy").json()
    assert acc["evaluated"] == 1
    assert acc["accuracy"] == 1.0


def test_batch_classify_skips_already_classified(client, stub_model):
    payload = make_payload()  # same pro + same notes for all three -> 1 fresh call, 2 cache hits
    for _ in range(3):
        created = client.post("/ov-exceptions", json=payload).json()
        client.post(f"/ov-exceptions/{created['id']}/investigation", json=INVESTIGATION)

    first = client.post("/classify/batch").json()
    assert first["processed"] == 3
    assert first["ai_fresh"] == 1      # identical notes -> 1 fresh call
    assert first["cache_hits"] == 2

    second = client.post("/classify/batch").json()
    assert second["processed"] == 0
