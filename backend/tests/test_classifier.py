import pytest

from app.ai import classifier, ollama_client
from app.ai.taxonomy import CONTRIBUTING_FACTORS, FEW_SHOT_EXAMPLES, empty_factors
from app.analytics import RecurrenceContext


def test_parses_valid_json(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "generate",
        lambda *a, **k: '{"category": "Missed Scan", "confidence": 0.91, "reasoning": "No scans exist."}',
    )
    result = classifier.classify_ov_exception("No dock scan and no unload scan for this pro.")
    assert result.category == "Missed Scan"
    assert result.confidence == pytest.approx(0.91)
    assert result.needs_review is False


def test_extracts_json_wrapped_in_prose(monkeypatch):
    raw = 'Sure! Here is the result:\n```json\n{"category": "Labeling Error", "confidence": 0.8, "reasoning": "No label."}\n```'
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: raw)
    result = classifier.classify_ov_exception("Carton has no pro label at all.")
    assert result.category == "Labeling Error"


def test_retries_once_then_succeeds(monkeypatch):
    calls: list[str] = []

    def fake_generate(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return "I think this is a missed scan, honestly."
        return '{"category": "Missed Scan", "confidence": 0.7, "reasoning": "No scan."}'

    monkeypatch.setattr(ollama_client, "generate", fake_generate)
    result = classifier.classify_ov_exception("notes")
    assert len(calls) == 2
    assert "Return ONLY valid JSON" in calls[1]
    assert result.category == "Missed Scan"


def test_malformed_response_falls_back_to_other(monkeypatch):
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "not json at all")
    result = classifier.classify_ov_exception("notes")
    assert result.category == "Other"
    assert result.confidence == 0.0
    assert result.reasoning == "Classification failed validation"
    assert result.needs_review is True


def test_category_outside_taxonomy_falls_back(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "generate",
        lambda *a, **k: '{"category": "Alien Abduction", "confidence": 0.99, "reasoning": "x"}',
    )
    result = classifier.classify_ov_exception("notes")
    assert result.category == "Other"
    assert result.needs_review is True


def test_ollama_down_does_not_crash(monkeypatch):
    def boom(*a, **k):
        raise ollama_client.OllamaError("connection refused")

    monkeypatch.setattr(ollama_client, "generate", boom)
    result = classifier.classify_ov_exception("notes")
    assert result.category == "Other"
    assert result.needs_review is True


def test_empty_text_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Ollama should not be called for empty text")

    monkeypatch.setattr(ollama_client, "generate", boom)
    result = classifier.classify_ov_exception("   ")
    assert result.category == "Other"


def test_prompt_contains_taxonomy_and_examples():
    prompt = classifier.build_prompt("some notes")
    assert "Shipper Load & Count Discrepancy" in prompt
    assert "EXAMPLES:" in prompt
    assert "some notes" in prompt


# --- Multi-factor root cause ---------------------------------------------------------------


def test_contributing_factors_are_parsed_and_normalized(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "generate",
        lambda *a, **k: (
            '{"category": "Shipper Load & Count Discrepancy", "confidence": 0.9, '
            '"reasoning": "BOL says 12, 14 arrived.", '
            '"contributing_factors": {"quantity_mismatch": true, "made_up_factor": true}}'
        ),
    )
    result = classifier.classify_ov_exception("BOL states 12 cartons, 14 physically arrived.")

    assert set(result.contributing_factors) == set(CONTRIBUTING_FACTORS)
    assert result.contributing_factors["quantity_mismatch"] is True
    assert result.contributing_factors["documentation_issue"] is False
    assert "made_up_factor" not in result.contributing_factors


def test_fallback_defaults_contributing_factors_to_all_false(monkeypatch):
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "not json at all")
    result = classifier.classify_ov_exception("notes")

    assert result.category == "Other"
    assert result.contributing_factors == empty_factors()
    assert not any(result.contributing_factors.values())


def test_training_signal_overrides_the_model(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "generate",
        lambda *a, **k: (
            '{"category": "Missed Scan", "confidence": 0.8, "reasoning": "No scan.", '
            '"contributing_factors": {"scan_issue": true, "training_signal": false}}'
        ),
    )
    context = RecurrenceContext(
        terminal="ATL", handler="jmartin", handler_counts={"Missed Scan": 4}, handler_total=4
    )

    result = classifier.classify_ov_exception("No dock scan recorded.", context=context)

    # The model said false; four repeats by this handler says otherwise, and the count wins.
    assert result.contributing_factors["training_signal"] is True
    assert result.contributing_factors["scan_issue"] is True


def test_training_signal_stays_false_below_the_threshold(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "generate",
        lambda *a, **k: (
            '{"category": "Missed Scan", "confidence": 0.8, "reasoning": "No scan.", '
            '"contributing_factors": {"training_signal": true}}'
        ),
    )
    context = RecurrenceContext(handler="jmartin", handler_counts={"Missed Scan": 1}, handler_total=1)

    result = classifier.classify_ov_exception("No dock scan recorded.", context=context)
    assert result.contributing_factors["training_signal"] is False


def test_prompt_carries_the_recurrence_context_and_factor_keys():
    context = RecurrenceContext(
        terminal="ATL",
        handler="jmartin",
        terminal_counts={"Missed Scan": 5},
        terminal_total=5,
        investigation_flags={"od400Check": "N"},
    )
    prompt = classifier.build_prompt("some notes", context=context)

    assert "RECURRENCE CONTEXT:" in prompt
    assert "Terminal ATL: 5 classified overages (Missed Scan 5)." in prompt
    assert "od400Check=N" in prompt
    for factor in CONTRIBUTING_FACTORS:
        assert factor in prompt
    # Every few-shot example now carries the field, so the model has a pattern to copy.
    assert prompt.count('"contributing_factors"') >= len(FEW_SHOT_EXAMPLES)
