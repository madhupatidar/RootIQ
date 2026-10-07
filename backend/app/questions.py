"""Investigation steps.

`INVESTIGATION_QUESTIONS` mirrors the six Y/N + free-text checks that actually exist in the
OS&D export (od400Check, billOfLadingCheck, drCheck, psCheck, consigneeCheck, shipmentCheck)
- this is the canonical set the API and UI expose.

`SEED_QUESTIONS` are the richer synthetic steps used only by the fake-data generator; they
stay accepted so the generated dataset and its tests keep working alongside real imports.
"""

INVESTIGATION_QUESTIONS: list[dict[str, str]] = [
    {"key": "od400Check", "prompt": "Was the OD400 checked?"},
    {"key": "billOfLadingCheck", "prompt": "Was the bill of lading checked for errors?"},
    {"key": "drCheck", "prompt": "Was the delivery receipt checked?"},
    {"key": "psCheck", "prompt": "Was a packing slip found and checked?"},
    {"key": "consigneeCheck", "prompt": "Was the consignee contacted?"},
    {"key": "shipmentCheck", "prompt": "Were related shipments checked?"},
]

SEED_QUESTIONS: list[dict[str, str]] = [
    {"key": "freight_scanned_at_checkpoints", "prompt": "Was the freight scanned at every required dock checkpoint?"},
    {"key": "scan_matches_pro", "prompt": "Do the recorded scans match the PRO number physically on the freight?"},
    {"key": "bol_count_matches", "prompt": "Does the BOL count/description match the physical freight?"},
    {"key": "labels_present_and_legible", "prompt": "Are the shipping labels present and legible?"},
    {"key": "packaging_intact", "prompt": "Is the packaging intact (no splits, tears or failed wrap)?"},
    {"key": "possible_load_swap", "prompt": "Is there evidence of a load swap or co-mingled shipment?"},
    {"key": "shipper_load_and_count", "prompt": "Was this shipment loaded and counted by the shipper?"},
    {"key": "origin_terminal_contacted", "prompt": "Was the origin terminal contacted for a trace?"},
    {"key": "shipper_consignee_contacted", "prompt": "Were the shipper and consignee contacted?"},
]

QUESTION_PROMPTS = {q["key"]: q["prompt"] for q in (*INVESTIGATION_QUESTIONS, *SEED_QUESTIONS)}
QUESTION_KEYS = set(QUESTION_PROMPTS)


def answered_flags(steps: list[dict]) -> dict[str, str]:
    """question_key -> Y/N for the checks that were actually answered.

    KNOWN GAP: none of the six canonical checks is a quantity/piece-count verification. The
    closest proxies are billOfLadingCheck and psCheck, so `quantity_mismatch` has to come from
    the free text (or from the staging check in app/prevention/staging.py) rather than a flag.
    """
    return {
        str(step.get("question_key")): str(step.get("answer_yn"))
        for step in steps or []
        if step.get("question_key") and step.get("answer_yn")
    }


def build_combined_notes(steps: list[dict]) -> str:
    """Concatenate the free-text answers - this is the text the AI layer reads."""
    lines = []
    for step in steps:
        note = (step.get("notes_text") or "").strip()
        if not note:
            continue
        prompt = QUESTION_PROMPTS.get(step.get("question_key"), step.get("question_key", ""))
        answer = step.get("answer_yn") or ""
        lines.append(f"{prompt} [{answer}] {note}")
    return "\n".join(lines)
