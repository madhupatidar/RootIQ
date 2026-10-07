"""Root-cause classification against a local Ollama model (spec Section 7).

`classify_ov_exception(text, context=...)` is the only entry point - keep it that way so the
model (or the provider) can be swapped without touching the rest of the system. The optional
`context` carries recurrence counts and the investigation-step answers, so the output can say
*why* ("recurring quantity-verification issue at ATL") and not only *what*.
"""

from __future__ import annotations

import json
import logging
import re

from app.ai import ollama_client
from app.ai.taxonomy import (
    FALLBACK_CATEGORY,
    ROOT_CAUSE_TAXONOMY,
    empty_factors,
    factor_block,
    few_shot_block,
    is_valid_category,
    normalize_factors,
    taxonomy_block,
)
from app.analytics import RecurrenceContext
from app.config import get_settings
from app.dedup.cache import ClassificationResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an LTL freight OS&D analyst. You classify the root cause of OVERAGE (OV) "
    "exceptions from investigation notes. You answer only with a single JSON object."
)

# Same convention as attention.py: a module default the caller may override per call.
DEFAULT_TRAINING_SIGNAL_THRESHOLD = 3

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def build_prompt(text: str, *, context: RecurrenceContext | None = None, strict: bool = False) -> str:
    strict_note = (
        "\nReturn ONLY valid JSON. No prose, no markdown, no code fences, no explanation "
        "outside the JSON object.\n"
        if strict
        else ""
    )
    context_block = f"\nRECURRENCE CONTEXT:\n{context.as_prompt_block()}\n" if context is not None else ""
    return f"""Classify the root cause of this overage (OV) freight exception.

ALLOWED CATEGORIES (use the exact string, nothing else):
{taxonomy_block()}

CONTRIBUTING FACTORS (report every key as true/false):
{factor_block()}

EXAMPLES:
{few_shot_block()}

Rules:
- "category" MUST be exactly one of the allowed category strings above.
- "confidence" is a float between 0 and 1.
- "reasoning" is one or two sentences citing the evidence in the notes.
- "contributing_factors" must contain every factor key listed above.
- Mark a factor true ONLY where the notes or the recurrence context actually support it. An
  unsupported factor is worse than a false one - do not affirm a factor to be helpful.
- terminal_pattern and handler_pattern come from the recurrence context, not from the notes.
- training_signal is recomputed by the system from handler volume; answer it honestly, but the
  computed value wins.
- If the notes are too thin to determine a cause, use "Other" with a low confidence and leave
  every factor false.
{strict_note}{context_block}
INVESTIGATION NOTES:
{text.strip()}

JSON:"""


def _parse(raw: str) -> ClassificationResult | None:
    if not raw or not raw.strip():
        return None
    candidate = raw.strip()
    if not candidate.startswith("{"):
        match = _JSON_OBJECT.search(candidate)
        if not match:
            return None
        candidate = match.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not is_valid_category(data.get("category")):
        return None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return ClassificationResult(
        category=str(data["category"]).strip(),
        confidence=min(max(confidence, 0.0), 1.0),
        reasoning=str(data.get("reasoning", "")).strip(),
        model_used=get_settings().model_identifier,
        contributing_factors=normalize_factors(data.get("contributing_factors")),
    )


def _fallback(reason: str) -> ClassificationResult:
    return ClassificationResult(
        category=FALLBACK_CATEGORY,
        confidence=0.0,
        reasoning=reason,
        model_used=get_settings().model_identifier,
        needs_review=True,
        contributing_factors=empty_factors(),
    )


def apply_training_signal(
    result: ClassificationResult,
    context: RecurrenceContext | None,
    *,
    threshold: int = DEFAULT_TRAINING_SIGNAL_THRESHOLD,
) -> ClassificationResult:
    """training_signal is a count, not a judgement - the deterministic answer always wins."""
    factors = dict(result.contributing_factors or empty_factors())
    recurrence = context.recurrence_by_handler(result.category) if context is not None else 0
    computed = recurrence >= threshold
    if factors.get("training_signal") != computed:
        logger.info(
            "training_signal disagreement: model=%s computed=%s handler=%s category=%s count=%s threshold=%s",
            factors.get("training_signal"),
            computed,
            context.handler if context is not None else None,
            result.category,
            recurrence,
            threshold,
        )
    factors["training_signal"] = computed
    result.contributing_factors = factors
    return result


def classify_ov_exception(
    text: str,
    *,
    context: RecurrenceContext | None = None,
    training_threshold: int = DEFAULT_TRAINING_SIGNAL_THRESHOLD,
) -> ClassificationResult:
    """Single cache-miss classification call, with validate-and-retry then graceful fallback."""
    def _finish(result: ClassificationResult) -> ClassificationResult:
        return apply_training_signal(result, context, threshold=training_threshold)

    if not (text or "").strip():
        return _finish(_fallback("No investigation text available to classify"))

    for strict in (False, True):
        try:
            raw = ollama_client.generate(
                build_prompt(text, context=context, strict=strict), system=SYSTEM_PROMPT, temperature=0.0
            )
        except ollama_client.OllamaError as exc:
            return _finish(_fallback(f"Classification failed validation: {exc}"))
        result = _parse(raw)
        if result is not None:
            return _finish(result)

    return _finish(_fallback("Classification failed validation"))


__all__ = [
    "classify_ov_exception",
    "apply_training_signal",
    "build_prompt",
    "ClassificationResult",
    "ROOT_CAUSE_TAXONOMY",
]
