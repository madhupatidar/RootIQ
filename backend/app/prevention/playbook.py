"""Hand-written floor-level playbook: category -> concrete actions.

Deliberately static. The "intelligence" is the aggregation that decides *which* category
applies to a terminal/commodity/handler; the wording of what to physically do about it is
operational policy, not something the model should invent.
"""

from __future__ import annotations

from app.ai.taxonomy import FALLBACK_CATEGORY, ROOT_CAUSE_TAXONOMY

# Actions the dock can take on freight that is still moving - before anything goes missing.
FLOOR_ACTIONS: dict[str, list[dict[str, str]]] = {
    "Improper Packaging": [
        {"key": "inspect_inbound_wrap", "label": "Inspect wrap and banding on inbound before it is staged",
         "why": "A pallet that arrives compromised sheds pieces on the next move, not this one."},
        {"key": "rewrap_before_load", "label": "Re-wrap or re-band anything questionable before it is loaded",
         "why": "Two minutes of wrap prevents the loose piece that becomes an overage."},
        {"key": "flag_repeat_shipper", "label": "Raise repeat offenders with the shipper through your manager",
         "why": "If the packaging leaves the shipper wrong, the dock can only contain it, not fix it."},
    ],
    "Missed Scan": [
        {"key": "scan_every_checkpoint", "label": "Scan at every checkpoint on this lane - no batch scanning at the end",
         "why": "Freight with no scan history is what turns up unidentified at the far end."},
        {"key": "audit_shift_scans", "label": "Audit this shift's scan log against the manifest before close",
         "why": "Catches the gap while the freight is still on your dock."},
    ],
    "Data Entry / Scan Mismatch": [
        {"key": "read_back_pro", "label": "Read the PRO back off the freight before keying it",
         "why": "Transposed digits are the single most common version of this failure."},
        {"key": "verify_od400", "label": "Verify the OD400 record against the physical label at entry",
         "why": "A record that never matched the label cannot be reconciled downstream."},
    ],
    "Misrouting": [
        {"key": "verify_dest_vs_plan", "label": "Verify the destination label against the load plan before loading",
         "why": "Freight on the wrong trailer surfaces as an overage at a terminal that never expected it."},
        {"key": "confirm_door", "label": "Confirm the door assignment before the first piece goes on",
         "why": "One wrong door mis-routes everything loaded behind it."},
    ],
    "Load Swap / Co-mingled Shipment": [
        {"key": "segregate_staging", "label": "Keep a physical gap between shipments staged in the same bay",
         "why": "Co-mingling happens when two shipments touch, not when they are far apart."},
        {"key": "check_bay_tag", "label": "Check each PRO against the bay tag as it is loaded",
         "why": "Stops the piece that belongs to the shipment next to it."},
    ],
    "Handling Damage": [
        {"key": "review_dock_area", "label": "Walk the dock area where the damage keeps being recorded",
         "why": "Repeat damage is usually a layout or traffic problem, not a person problem."},
        {"key": "inspect_after_move", "label": "Inspect freight after each move on this lane",
         "why": "Damage caught on the dock is a repack; damage caught later is an exception."},
    ],
    "Documentation Errors": [
        {"key": "check_bol_at_pickup", "label": "Check the BOL is complete and legible before the driver leaves",
         "why": "Paperwork cannot be corrected once the freight and the shipper have parted."},
        {"key": "reject_illegible", "label": "Get illegible documents re-issued at the dock",
         "why": "An unreadable BOL guarantees the freight cannot be matched later."},
    ],
    "Shipper Load & Count Discrepancy": [
        {"key": "count_at_pickup", "label": "Count the pieces at pickup even when the BOL says shipper load & count",
         "why": "The discrepancy is created at pickup and only discovered at delivery."},
        {"key": "record_both_counts", "label": "Record your count alongside the BOL count on the spot",
         "why": "Two numbers recorded at the same time settle the dispute before it starts."},
    ],
    "Consignee Issue": [
        {"key": "confirm_before_dispatch", "label": "Confirm the appointment and address before dispatch",
         "why": "Refused freight comes back to the dock and becomes an overage there."},
        {"key": "flag_known_consignees", "label": "Flag consignees with a refusal history to dispatch",
         "why": "The pattern is predictable, so the trip can be planned around it."},
    ],
    "Carrier Error": [
        {"key": "inspect_at_transfer", "label": "Inspect and count interline freight at the transfer point before accepting",
         "why": "Once it is accepted without a count, the discrepancy is yours."},
        {"key": "raise_with_partner", "label": "Raise the pattern with the interline partner",
         "why": "A partner-side defect will keep arriving until the partner fixes it."},
    ],
    "Labeling Error": [
        {"key": "check_label_before_leaving", "label": "Check every piece carries a legible label before it leaves the dock",
         "why": "An unlabelled piece is an overage the moment it is separated from its shipment."},
        {"key": "relabel_at_origin", "label": "Re-label at origin rather than passing it down the line",
         "why": "Each subsequent handling makes the piece harder to reunite with its PRO."},
    ],
    "Other": [
        {"key": "tighten_dock_checks", "label": "Tighten identification checks at hand-off on this lane",
         "why": "\"Other\" usually means the freight was never identifiable in the first place."},
    ],
}

# Wording used when a terminal or handler crosses the repeat-issue threshold.
TRAINING_ACTIONS: dict[str, str] = {
    "Improper Packaging": (
        "Run a packaging-acceptance refresher: what a compliant pallet wrap looks like, when to "
        "re-wrap at the dock, and how to refuse freight that arrives already compromised."
    ),
    "Missed Scan": (
        "Refresh scan-discipline at every checkpoint and audit one shift of scan logs against the "
        "manifest to show where the gaps occur."
    ),
    "Data Entry / Scan Mismatch": (
        "Refresher on PRO verification: read back the PRO from the freight before keying, and "
        "double-check transposed digits on manual entry."
    ),
    "Misrouting": (
        "Review load-plan and destination-label verification with the outbound loaders on this shift."
    ),
    "Load Swap / Co-mingled Shipment": (
        "Refresher on trailer segregation and staging discipline; audit the bay layout for shipments "
        "that are being staged too close together."
    ),
    "Handling Damage": (
        "Forklift and dock handling refresher, plus a walk-through of the areas where the damage is "
        "being recorded."
    ),
    "Documentation Errors": (
        "Paperwork-completeness refresher at pickup: required BOL fields and what to do when the "
        "document is illegible."
    ),
    "Shipper Load & Count Discrepancy": (
        "Coach the team on count-verification at pickup and on how to record shipper load & count "
        "on the BOL."
    ),
    "Consignee Issue": (
        "Review delivery and contact procedure with the drivers serving this consignee base."
    ),
    "Carrier Error": (
        "Escalate the pattern to the interline partner and review transfer-point inspection with the team."
    ),
    "Labeling Error": (
        "Refresher on label application and legibility checks before freight leaves the dock; raise "
        "repeat offenders with the shipper."
    ),
    "Other": (
        "Coach on investigation-note quality: repeated \"Other\" classifications mean the notes are "
        "not carrying enough physical detail to determine a cause."
    ),
}

# What good notes for this category should mention - shown as a nudge while typing.
NOTE_PROMPTS: dict[str, list[str]] = {
    "Improper Packaging": ["state of the wrap/banding", "whether the carton seam split", "how many pieces separated"],
    "Missed Scan": ["last checkpoint that did scan", "checkpoint where the scan is missing", "who re-scanned it"],
    "Data Entry / Scan Mismatch": ["PRO on the freight", "PRO on the record", "which system was keyed"],
    "Misrouting": ["destination on the label", "destination on the manifest", "line-haul that brought it in"],
    "Load Swap / Co-mingled Shipment": ["trailer/bay number", "other PROs staged alongside", "seal status"],
    "Handling Damage": ["where on the dock it happened", "type of damage", "equipment involved"],
    "Documentation Errors": ["which document", "which fields are wrong or missing", "who supplied it"],
    "Shipper Load & Count Discrepancy": ["BOL piece count", "physical piece count", "shipper load & count marking"],
    "Consignee Issue": ["who was contacted", "when", "what they said"],
    "Carrier Error": ["interline carrier name", "transfer point", "paperwork received"],
    "Labeling Error": ["missing or unreadable", "what the label did show", "other pieces from the same shipper"],
    "Other": ["physical description of the freight", "where it was found", "what has already been checked"],
}

# Generic completeness checks over the free text - keyword presence only, no model call.
COVERAGE_HINTS: list[dict] = [
    {"key": "location", "label": "Where the freight was found (trailer, bay, dock area)",
     "keywords": ("trailer", "bay", "dock", "floor", "staging", "door")},
    {"key": "identifiers", "label": "Identifiers checked (PRO, BOL, label, packing slip)",
     "keywords": ("pro", "bol", "label", "packing slip", "manifest", "od400")},
    {"key": "counts", "label": "Piece counts or quantities",
     "keywords": ("piece", "pieces", "carton", "cartons", "pallet", "skid", "count", "qty", "units")},
    {"key": "condition", "label": "Physical condition of the freight and packaging",
     "keywords": ("intact", "torn", "split", "damaged", "wrap", "banded", "crushed", "sealed", "open")},
    {"key": "actions", "label": "Who was contacted or what was already checked",
     "keywords": ("contacted", "called", "checked", "verified", "confirmed", "traced", "emailed")},
]


def floor_actions(category: str) -> list[dict[str, str]]:
    return FLOOR_ACTIONS.get(category, FLOOR_ACTIONS[FALLBACK_CATEGORY])


def training_action(category: str, scope_type: str, scope_value: str) -> str:
    base = TRAINING_ACTIONS.get(category, TRAINING_ACTIONS[FALLBACK_CATEGORY])
    who = f"terminal {scope_value}" if scope_type == "terminal" else f"{scope_value}"
    return f"{base} Addressed to {who}."


def note_prompts(category: str) -> list[str]:
    return NOTE_PROMPTS.get(category, NOTE_PROMPTS[FALLBACK_CATEGORY])


def missing_details(text: str) -> list[dict[str, str]]:
    """Coverage gaps in the clerk's free text - the nudge that improves the input."""
    lowered = (text or "").lower()
    return [
        {"key": hint["key"], "label": hint["label"]}
        for hint in COVERAGE_HINTS
        if not any(word in lowered for word in hint["keywords"])
    ]


KNOWN_CATEGORIES = set(ROOT_CAUSE_TAXONOMY)
