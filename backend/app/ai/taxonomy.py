"""OV root-cause taxonomy, category definitions and few-shot examples (spec Sections 4 & 7)."""

import json

ROOT_CAUSE_TAXONOMY: list[str] = [
    "Improper Packaging",
    "Missed Scan",
    "Data Entry / Scan Mismatch",
    "Misrouting",
    "Load Swap / Co-mingled Shipment",
    "Handling Damage",
    "Documentation Errors",
    "Shipper Load & Count Discrepancy",
    "Consignee Issue",
    "Carrier Error",
    "Labeling Error",
    "Other",
]

FALLBACK_CATEGORY = "Other"

CATEGORY_DEFINITIONS: dict[str, str] = {
    "Improper Packaging": "Packaging failed or came apart in transit, separating pieces from their shipment.",
    "Missed Scan": "Freight was never scanned at a checkpoint where it should have been.",
    "Data Entry / Scan Mismatch": "Freight was scanned but tied to the wrong Pro number or shipment record.",
    "Misrouting": "Freight was sent to the wrong terminal or line-haul destination.",
    "Load Swap / Co-mingled Shipment": "Freight was loaded onto the wrong trailer or physically mixed with another shipment.",
    "Handling Damage": "Physical damage occurred during dock or transit handling, not packaging failure.",
    "Documentation Errors": "Paperwork (BOL, labels) was incomplete, illegible, or otherwise unusable to identify the freight.",
    "Shipper Load & Count Discrepancy": "The BOL's stated count/description doesn't match what physically arrived.",
    "Consignee Issue": "Root cause traces to consignee-side action (refusal, wrong acceptance, address issue).",
    "Carrier Error": "An interline or partner carrier's handling/documentation caused the exception.",
    "Labeling Error": "Shipping label was missing, wrong, or unreadable.",
    "Other": "None of the above applies, or the investigation notes don't contain enough detail to determine a cause.",
}

# The *why* behind the category. A category says what went wrong; these say what drove it, so a
# supervisor reads "recurring quantity-verification issue at ATL" rather than "loaded incorrectly".
CONTRIBUTING_FACTORS: list[str] = [
    "terminal_pattern",
    "handler_pattern",
    "scan_issue",
    "quantity_mismatch",
    "trailer_bay_mismatch",
    "documentation_issue",
    "training_signal",
]

FACTOR_DEFINITIONS: dict[str, str] = {
    "terminal_pattern": "The recurrence context shows this cause repeating at this terminal, not a one-off.",
    "handler_pattern": "The recurrence context shows this cause repeating for this handler.",
    "scan_issue": "A scan was missing, late, or posted against the wrong record.",
    "quantity_mismatch": "Counted/scanned quantity disagrees with the documented quantity.",
    "trailer_bay_mismatch": "Freight was on a trailer or bay other than the one it belonged to.",
    "documentation_issue": "BOL, DR, packing slip or label was missing, wrong or unusable.",
    "training_signal": "Repeat volume for this handler warrants coaching (computed by the system, not the model).",
}


def empty_factors() -> dict[str, bool]:
    return {name: False for name in CONTRIBUTING_FACTORS}


def normalize_factors(raw: object) -> dict[str, bool]:
    """Always the full key set, always booleans - unknown keys from the model are dropped."""
    factors = empty_factors()
    if isinstance(raw, dict):
        for name in CONTRIBUTING_FACTORS:
            factors[name] = bool(raw.get(name, False))
    return factors


def factor_block() -> str:
    return "\n".join(f"- {name}: {FACTOR_DEFINITIONS[name]}" for name in CONTRIBUTING_FACTORS)


# Hand-written few-shot examples. Keep them short: local models drift with long prompts.
# "factors" lists only the factors the notes actually support - the rest are filled in as false,
# so the model learns not to affirm a factor the evidence does not carry.
FEW_SHOT_EXAMPLES: list[dict] = [
    {
        "notes": (
            "Found 2 loose cartons on the floor of trailer 48812 with no pro label. Original master "
            "carton had split open at the seam and the stretch wrap was torn. Remaining pieces on the "
            "skid matched PRO 402118834007."
        ),
        "category": "Improper Packaging",
        "confidence": "0.92",
        "reasoning": "The outer carton and wrap failed in transit, which separated the pieces from their skid.",
        "factors": {},
    },
    {
        "notes": (
            "Skid is fully labeled and intact. Checked scan history for the pro - no dock scan at the "
            "origin terminal, and no unload scan on arrival. Freight physically moved but never got "
            "scanned at either checkpoint."
        ),
        "category": "Missed Scan",
        "confidence": "0.9",
        "reasoning": "Freight moved through checkpoints with no scan recorded at any of them.",
        "factors": {"scan_issue": True},
    },
    {
        "notes": (
            "Pallet scanned on the inbound but the scan posted to PRO 402118000001, which is a Dallas "
            "shipment. Physical label on the freight reads PRO 402118880004. Scan was keyed to the "
            "wrong pro number at the dock."
        ),
        "category": "Data Entry / Scan Mismatch",
        "confidence": "0.88",
        "reasoning": "A scan exists, but it was recorded against a different PRO than the one on the freight.",
        "factors": {"scan_issue": True},
    },
    {
        "notes": (
            "Freight tagged for Atlanta was found on the Memphis outbound trailer 51120. Load sheet "
            "shows it was loaded with the wrong line-haul leg and was never on the Atlanta manifest."
        ),
        "category": "Misrouting",
        "confidence": "0.86",
        "reasoning": "The shipment was dispatched to a terminal other than its billed destination.",
        "factors": {"trailer_bay_mismatch": True},
    },
    {
        "notes": (
            "Trailer 33091 was loaded at the shipper dock with two customers' freight on the same "
            "skid. Our 4 cartons were shrink wrapped together with another consignee's cartons and "
            "came in under their manifest."
        ),
        "category": "Load Swap / Co-mingled Shipment",
        "confidence": "0.89",
        "reasoning": "Freight was physically mixed with another shipment on the same unit.",
        "factors": {"trailer_bay_mismatch": True},
    },
    {
        "notes": (
            "BOL states 12 cartons shipper load and count. 14 cartons physically arrived, all matching "
            "the same part number. Shipper confirmed they over-shipped and did not correct the BOL."
        ),
        "category": "Shipper Load & Count Discrepancy",
        "confidence": "0.91",
        "reasoning": "The BOL piece count does not match what physically arrived on a shipper-load-and-count load.",
        "factors": {"quantity_mismatch": True, "documentation_issue": True},
    },
    {
        "notes": (
            "Carton has no pro label at all - only a faded vendor barcode on the side. Nothing on the "
            "piece ties it to a shipment. Label appears to have been rubbed off."
        ),
        "category": "Labeling Error",
        "confidence": "0.87",
        "reasoning": "The shipping label was missing/unreadable, so the freight could not be identified.",
        "factors": {"documentation_issue": True},
    },
    {
        "notes": (
            "Freight came to us on interline partner ABF trailer. Their delivery receipt shows 6 "
            "handling units, we received 7. Partner carrier could not produce paperwork for the extra "
            "unit."
        ),
        "category": "Carrier Error",
        "confidence": "0.84",
        "reasoning": "The overage originated with the interline partner's handling and paperwork.",
        "factors": {"quantity_mismatch": True, "documentation_issue": True},
    },
    {
        "notes": "OS&D clerk noted freight found on bay 12. No further investigation notes recorded.",
        "category": "Other",
        "confidence": "0.3",
        "reasoning": "Not enough detail in the notes to determine a cause.",
        "factors": {},
    },
]


def taxonomy_block() -> str:
    return "\n".join(f"- {name}: {CATEGORY_DEFINITIONS[name]}" for name in ROOT_CAUSE_TAXONOMY)


def few_shot_block() -> str:
    parts = []
    for ex in FEW_SHOT_EXAMPLES:
        factors = json.dumps(normalize_factors(ex.get("factors")))
        parts.append(
            "INVESTIGATION NOTES:\n"
            f"{ex['notes']}\n"
            "JSON:\n"
            f'{{"category": "{ex["category"]}", "confidence": {ex["confidence"]}, '
            f'"reasoning": "{ex["reasoning"]}", "contributing_factors": {factors}}}'
        )
    return "\n\n".join(parts)


def is_valid_category(value: object) -> bool:
    return isinstance(value, str) and value.strip() in ROOT_CAUSE_TAXONOMY
