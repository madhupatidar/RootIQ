"""Prevention recommendation generation from aggregated stats (spec Section 8)."""

from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.ai import ollama_client
from app.ai.taxonomy import ROOT_CAUSE_TAXONOMY
from app.analytics import (
    InsightFilters,
    build_aggregates,
    format_stats_for_prompt,
    load_dataframe,
    supporting_ids,
)
from app.models import Recommendation

SYSTEM_PROMPT = (
    "You are an LTL freight operations improvement analyst. You read aggregated OS&D "
    "overage root-cause statistics and propose concrete prevention actions. You answer "
    "only with a single JSON object."
)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def build_prompt(stats_text: str, *, strict: bool = False) -> str:
    strict_note = "\nReturn ONLY valid JSON. No prose, no markdown, no code fences.\n" if strict else ""
    return f"""Below are aggregated root-cause statistics for overage (OV) freight exceptions.

{stats_text}

Write 3 to 5 short, specific, actionable prevention recommendations for dock and OS&D
operations. Each recommendation must:
- address one of the patterns visible in the stats above (name the terminal or commodity when the stats point at one),
- be written in plain English a terminal manager could act on this week,
- be tagged with the root-cause category it addresses, using exactly one of:
{", ".join(ROOT_CAUSE_TAXONOMY)}

Respond with JSON of the form:
{{"recommendations": [{{"category": "...", "pattern_addressed": "...", "recommendation": "..."}}]}}
{strict_note}
JSON:"""


def _parse(raw: str) -> list[dict] | None:
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

    items = data.get("recommendations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None

    parsed: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("recommendation", "")).strip()
        if not text:
            continue
        category = str(item.get("category", "")).strip()
        parsed.append(
            {
                "category": category if category in ROOT_CAUSE_TAXONOMY else "Other",
                "pattern_addressed": str(item.get("pattern_addressed", "")).strip(),
                "recommendation": text,
            }
        )
    return parsed or None


def generate_recommendations(db: Session, filters: InsightFilters) -> list[Recommendation]:
    """Aggregate -> single Ollama call -> persist Recommendation rows with traceable evidence."""
    df = load_dataframe(db, filters)
    aggregates = build_aggregates(df)
    if aggregates["distribution"]["total_classified"] == 0:
        return []

    stats_text = format_stats_for_prompt(aggregates, filters)

    items: list[dict] | None = None
    for strict in (False, True):
        try:
            raw = ollama_client.generate(build_prompt(stats_text, strict=strict), system=SYSTEM_PROMPT)
        except ollama_client.OllamaError as exc:
            raise RuntimeError(f"Recommendation generation failed: {exc}") from exc
        items = _parse(raw)
        if items:
            break

    if not items:
        raise RuntimeError("Recommendation generation failed validation: model returned no usable JSON")

    scope = filters.as_scope()
    rows = [
        Recommendation(
            category=item["category"],
            scope=scope,
            recommendation_text=item["recommendation"],
            pattern_addressed=item["pattern_addressed"],
            supporting_exception_ids=supporting_ids(df, item["category"]),
        )
        for item in items
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


__all__ = ["generate_recommendations", "build_prompt"]
