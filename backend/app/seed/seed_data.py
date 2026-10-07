"""Synthetic OV exception generator (spec Section 12).

Run:  python -m app.seed.seed_data --count 80 --reset

Produces ~80 OV exceptions with realistic investigation text spanning the taxonomy,
a hand-labeled validation subset (`labeled_category`) for the accuracy report, and a
handful of intentional EXACT duplicates so the cache can be demoed hitting.
"""

from __future__ import annotations

import argparse
import random
from datetime import timedelta

from sqlalchemy import delete

from app.clearing_codes import sync_clearing_codes
from app.db import SessionLocal, engine
from app.dedup.hashing import compute_content_hash
from app.models import (
    Base,
    ClassificationCache,
    ExceptionStatus,
    ExpectedShipment,
    FoundOn,
    OVException,
    OVInvestigation,
    PreventionCheck,
    Recommendation,
    RootCauseClassification,
    utcnow,
)
from app.pro_number import generate_pro
from app.questions import build_combined_notes

TERMINALS = ["ATL", "MEM", "DAL", "HOU", "CLT", "JAX", "BHM", "NSH", "STL", "OKC"]
COMMODITIES = ["61200", "72330", "85410", "13050", "49800", "70200", "23400"]
PACKAGE_TYPES = ["Carton", "Skid", "Crate", "Bundle", "Drum", "Roll"]
SHIPPERS = [
    "Northline Supply Co",
    "Piedmont Tool Works",
    "Gulf Coast Plastics",
    "Redstone Components",
    "Blue Ridge Paper",
    "Valley Electric Supply",
    "Cypress Industrial",
]
CONSIGNEES = [
    "Harbor Point Distribution",
    "Maple Grove Hardware",
    "Tri-State Fasteners",
    "Summit Building Supply",
    "Lakeside Grocers",
    "Pinnacle Auto Parts",
    "Ironwood Manufacturing",
]
USERS = ["jmartin", "kpatel", "rsantos", "dwhite", "ahughes"]
CLEARING_CODES_POOL = ["CA", "DA", "RS", "RC", "SV", "RI", "CG", "BE"]

# question_key, Y/N answer, note template
Scenario = tuple[str, list[tuple[str, str, str]]]

SCENARIOS: list[Scenario] = [
    (
        "Improper Packaging",
        [
            ("packaging_intact", "N", "Master carton split along the bottom seam and the stretch wrap was torn open on trailer {trailer}."),
            ("labels_present_and_legible", "N", "The {pieces} loose pieces have no pro label - the label was on the outer carton that failed."),
            ("origin_terminal_contacted", "Y", "{origin} confirmed the skid was intact at load time, so the wrap failed in transit."),
        ],
    ),
    (
        "Improper Packaging",
        [
            ("packaging_intact", "N", "Shrink wrap on the skid was loose and cartons had shifted and fallen off during the line-haul run."),
            ("bol_count_matches", "Y", "Remaining skid count matches the BOL, these pieces separated from it."),
            ("shipper_consignee_contacted", "Y", "Shipper acknowledged the wrap job was light for a {pieces} piece skid."),
        ],
    ),
    (
        "Improper Packaging",
        [
            ("packaging_intact", "N", "Banding on the bundle snapped and individual lengths spread across bay {trailer}."),
            ("labels_present_and_legible", "N", "Only the banding carried the pro label so the loose pieces are unlabeled."),
        ],
    ),
    (
        "Missed Scan",
        [
            ("freight_scanned_at_checkpoints", "N", "No origin dock scan and no unload scan exist for PRO {pro}. Freight physically moved but was never scanned at either checkpoint."),
            ("labels_present_and_legible", "Y", "Pro label is present and scannable, so the label was not the problem."),
            ("packaging_intact", "Y", "Packaging is fully intact, nothing came apart."),
        ],
    ),
    (
        "Missed Scan",
        [
            ("freight_scanned_at_checkpoints", "N", "Scan history shows the pallet was never scanned onto trailer {trailer} at {origin}."),
            ("origin_terminal_contacted", "Y", "{origin} dock supervisor confirmed the loader skipped the handheld scan during the shift change."),
        ],
    ),
    (
        "Data Entry / Scan Mismatch",
        [
            ("scan_matches_pro", "N", "Inbound scan posted to PRO {other_pro} but the physical label on the freight reads PRO {pro}."),
            ("freight_scanned_at_checkpoints", "Y", "A scan does exist at the inbound checkpoint, it was simply keyed to the wrong pro."),
            ("bol_count_matches", "Y", "Piece count is right, only the pro number on the record is wrong."),
        ],
    ),
    (
        "Data Entry / Scan Mismatch",
        [
            ("scan_matches_pro", "N", "Clerk manually keyed the pro at {origin} and transposed two digits, so the unit is tied to the wrong shipment record."),
            ("labels_present_and_legible", "Y", "Label is clean and readable - this was a keying error, not a label issue."),
        ],
    ),
    (
        "Misrouting",
        [
            ("origin_terminal_contacted", "Y", "Freight billed to {dest} was found on the {origin} outbound trailer {trailer} and was never on the {dest} manifest."),
            ("possible_load_swap", "N", "No other customer freight involved, this unit was simply dispatched on the wrong line-haul leg."),
            ("labels_present_and_legible", "Y", "Label clearly shows the {dest} destination."),
        ],
    ),
    (
        "Misrouting",
        [
            ("origin_terminal_contacted", "Y", "Load plan sent this skid down the {origin} lane instead of the {dest} lane. Terminal confirmed the routing was keyed wrong."),
            ("freight_scanned_at_checkpoints", "Y", "All scans exist, they just trace a route to the wrong terminal."),
        ],
    ),
    (
        "Load Swap / Co-mingled Shipment",
        [
            ("possible_load_swap", "Y", "Our {pieces} cartons were shrink wrapped together with another consignee's freight on the same skid in trailer {trailer}."),
            ("shipper_load_and_count", "Y", "Shipper loaded two customers on one unit at their dock."),
            ("bol_count_matches", "N", "Unit arrived under the other customer's manifest so our count does not reconcile."),
        ],
    ),
    (
        "Load Swap / Co-mingled Shipment",
        [
            ("possible_load_swap", "Y", "Trailer {trailer} was swapped at the {origin} yard and came in with freight from two different loads mixed together."),
            ("origin_terminal_contacted", "Y", "{origin} confirmed the trailer swap on the dispatch log."),
        ],
    ),
    (
        "Handling Damage",
        [
            ("packaging_intact", "N", "Forklift punctured the side of the crate on the dock at {origin}; contents spilled and separated from the unit."),
            ("labels_present_and_legible", "N", "Label was destroyed by the fork damage."),
            ("shipper_consignee_contacted", "Y", "Shipper confirmed packaging was rated correctly - this was dock handling, not packaging."),
        ],
    ),
    (
        "Handling Damage",
        [
            ("packaging_intact", "N", "Drum was dropped during unload and the contents leaked onto adjacent freight in bay {trailer}."),
            ("origin_terminal_contacted", "Y", "Origin reports the drum was sound on load, damage occurred in our handling."),
        ],
    ),
    (
        "Documentation Errors",
        [
            ("bol_count_matches", "N", "BOL is missing the second page entirely so we cannot confirm what shipped under PRO {pro}."),
            ("labels_present_and_legible", "N", "Paperwork in the pouch is water damaged and illegible."),
            ("shipper_consignee_contacted", "Y", "Shipper is re-sending the BOL; nothing on file identifies this freight today."),
        ],
    ),
    (
        "Documentation Errors",
        [
            ("bol_count_matches", "N", "No delivery receipt or BOL travelled with this unit from {origin}, only a blank pouch."),
            ("shipper_consignee_contacted", "Y", "Neither shipper nor consignee can produce paperwork matching the description."),
        ],
    ),
    (
        "Shipper Load & Count Discrepancy",
        [
            ("shipper_load_and_count", "Y", "Load was shipper load and count out of {origin}."),
            ("bol_count_matches", "N", "BOL states {pieces} cartons but {extra_pieces} physically arrived, all the same part number."),
            ("shipper_consignee_contacted", "Y", "Shipper confirmed they over-shipped and never corrected the BOL."),
        ],
    ),
    (
        "Shipper Load & Count Discrepancy",
        [
            ("shipper_load_and_count", "Y", "Sealed trailer, shipper loaded and counted."),
            ("bol_count_matches", "N", "Physical description on the extra unit does not match anything on the BOL for PRO {pro}."),
        ],
    ),
    (
        "Consignee Issue",
        [
            ("shipper_consignee_contacted", "Y", "Consignee refused the extra unit at delivery and it came back to {dest} as an overage."),
            ("bol_count_matches", "Y", "Our count matches the BOL; the consignee simply would not accept the additional freight."),
        ],
    ),
    (
        "Consignee Issue",
        [
            ("shipper_consignee_contacted", "Y", "Consignee signed for and kept freight belonging to another customer, then returned it a week later."),
            ("origin_terminal_contacted", "N", "Origin trace not required - the issue happened at the consignee dock."),
        ],
    ),
    (
        "Carrier Error",
        [
            ("shipper_consignee_contacted", "Y", "Freight arrived on an interline partner trailer into {dest}."),
            ("bol_count_matches", "N", "Partner delivery receipt shows {pieces} handling units, we received {extra_pieces}. Partner cannot produce paperwork for the extra unit."),
        ],
    ),
    (
        "Carrier Error",
        [
            ("origin_terminal_contacted", "Y", "Interline carrier transferred the load at {origin} and included freight that was never on our manifest."),
            ("freight_scanned_at_checkpoints", "Y", "Our scans are clean from the transfer point forward; the error is upstream at the partner."),
        ],
    ),
    (
        "Labeling Error",
        [
            ("labels_present_and_legible", "N", "Carton carries no pro label at all, only a faded vendor barcode on the side."),
            ("packaging_intact", "Y", "Packaging is undamaged - the label was simply never applied."),
            ("scan_matches_pro", "N", "Nothing on the piece ties it to a shipment so it could not be scanned to a pro."),
        ],
    ),
    (
        "Labeling Error",
        [
            ("labels_present_and_legible", "N", "Pro label on the skid belongs to a shipment that delivered last month; the wrong label was applied at the shipper."),
            ("packaging_intact", "Y", "No packaging failure, the label content is just wrong."),
        ],
    ),
    (
        "Other",
        [
            ("origin_terminal_contacted", "N", "OS&D clerk noted freight found on bay {trailer}. No further investigation notes recorded."),
        ],
    ),
    (
        "Other",
        [
            ("shipper_consignee_contacted", "N", "Unable to reach anyone. No detail available on how the unit got here."),
        ],
    ),
]


def _steps_from_scenario(scenario: Scenario, ctx: dict) -> list[dict]:
    _, template = scenario
    return [
        {"question_key": key, "answer_yn": answer, "notes_text": note.format(**ctx)}
        for key, answer, note in template
    ]


def _build_exception(rng: random.Random, scenario: Scenario, labeled: bool) -> tuple[OVException, str]:
    category = scenario[0]
    origin, dest = rng.sample(TERMINALS, 2)
    pieces = rng.randint(2, 14)
    pro = generate_pro(rng)
    ctx = {
        "pro": pro,
        "other_pro": generate_pro(rng),
        "trailer": str(rng.randint(30000, 59999)),
        "origin": origin,
        "dest": dest,
        "pieces": pieces,
        "extra_pieces": pieces + rng.randint(1, 3),
    }

    steps = _steps_from_scenario(scenario, ctx)
    combined = build_combined_notes(steps)

    value_range = rng.choice([1, 1, 2, 2, 3])
    found_on = rng.choice(list(FoundOn))
    created_at = utcnow() - timedelta(days=rng.randint(0, 85), hours=rng.randint(0, 23))

    exc = OVException(
        pro_number=pro,
        origin_terminal=origin,
        destination_terminal=dest,
        shipper_name=rng.choice(SHIPPERS),
        consignee_name=rng.choice(CONSIGNEES),
        od400_pro=generate_pro(rng),
        manifest_number=f"M{rng.randint(100000, 999999)}" if rng.random() < 0.8 else None,
        found_on=found_on,
        trailer_or_bay_number=ctx["trailer"] if found_on == FoundOn.trailer else str(rng.randint(1, 60)),
        bl_number=f"BL{rng.randint(10000, 99999)}" if rng.random() < 0.7 else None,
        po_number=f"PO{rng.randint(10000, 99999)}" if rng.random() < 0.6 else None,
        sn_number=f"SN{rng.randint(10000, 99999)}" if rng.random() < 0.3 else None,
        hazmat=rng.random() < 0.08,
        handling_units=rng.randint(1, 4),
        commodity_code=rng.choice(COMMODITIES),
        package_type=rng.choice(PACKAGE_TYPES),
        pieces=pieces,
        weight=round(rng.uniform(40, 1800), 1),
        shrink_wrapped=rng.random() < 0.6,
        item_carton_model_serial=f"MDL-{rng.randint(1000, 9999)}/SN-{rng.randint(100000, 999999)}",
        value_range=value_range,
        dollar_amount=round(rng.uniform(1001, 8500), 2) if value_range == 3 else None,
        manufacturer_brand=rng.choice(["Ryobi", "Sylvania", "Generic", "Crestline", "Duro", None]),
        additional_details=(
            f"Dimensions approx {rng.randint(20, 48)}x{rng.randint(20, 40)}x{rng.randint(10, 60)} in. "
            f"Color coded {rng.choice(['blue', 'red', 'yellow', 'none'])} tape. "
            f"Heat number {rng.randint(100000, 999999)}."
        ),
        status=ExceptionStatus.investigation_complete,
        entry_user=rng.choice(USERS),
        assigned_to=rng.choice(USERS),
        content_hash=compute_content_hash(pro, combined),
        labeled_category=category if labeled else None,
        created_at=created_at,
        updated_at=created_at,
    )
    exc.investigation = OVInvestigation(
        steps=steps, combined_notes_text=combined, completed_at=created_at + timedelta(hours=4)
    )

    # A slice of the set is already cleared so the UI has clearing codes to show.
    if rng.random() < 0.35:
        exc.status = ExceptionStatus.cleared
        exc.clearing_code = rng.choice(CLEARING_CODES_POOL)
        exc.cleared_at = created_at + timedelta(days=rng.randint(1, 10))
    elif rng.random() < 0.3:
        exc.status = ExceptionStatus.needs_cleared

    return exc, combined


def _duplicate_of(source: OVException) -> OVException:
    """Exact duplicate: same pro_number + identical notes => same content_hash => cache hit."""
    steps = list(source.investigation.steps)
    combined = source.investigation.combined_notes_text
    clone = OVException(
        pro_number=source.pro_number,
        origin_terminal=source.origin_terminal,
        destination_terminal=source.destination_terminal,
        shipper_name=source.shipper_name,
        consignee_name=source.consignee_name,
        od400_pro=source.od400_pro,
        manifest_number=source.manifest_number,
        found_on=source.found_on,
        trailer_or_bay_number=source.trailer_or_bay_number,
        bl_number=source.bl_number,
        po_number=source.po_number,
        sn_number=source.sn_number,
        hazmat=source.hazmat,
        handling_units=source.handling_units,
        commodity_code=source.commodity_code,
        package_type=source.package_type,
        pieces=source.pieces,
        weight=source.weight,
        shrink_wrapped=source.shrink_wrapped,
        item_carton_model_serial=source.item_carton_model_serial,
        value_range=source.value_range,
        dollar_amount=source.dollar_amount,
        manufacturer_brand=source.manufacturer_brand,
        additional_details=source.additional_details,
        status=ExceptionStatus.investigation_complete,
        entry_user=source.entry_user,
        assigned_to=source.assigned_to,
        content_hash=compute_content_hash(source.pro_number, combined),
        labeled_category=None,  # keep duplicates out of the validation set
        created_at=source.created_at + timedelta(days=1),
        updated_at=source.created_at + timedelta(days=1),
    )
    clone.investigation = OVInvestigation(
        steps=steps, combined_notes_text=combined, completed_at=source.created_at + timedelta(days=1)
    )
    return clone


def reset_data(db) -> None:
    db.execute(delete(PreventionCheck))
    db.execute(delete(ExpectedShipment))
    db.execute(delete(Recommendation))
    db.execute(delete(RootCauseClassification))
    db.execute(delete(ClassificationCache))
    db.execute(delete(OVInvestigation))
    db.execute(delete(OVException))
    db.commit()


def seed_expected_shipments(db, rng: random.Random, exceptions: list[OVException], extra: int = 12) -> int:
    """POC stand-in for the manifest/OD400 quantity lookup used by the staging check.

    Half of the rows deliberately disagree with the physical piece count so the quantity-verify
    demo has both a match and a mismatch path.
    """
    rows: dict[str, ExpectedShipment] = {}
    for exc in rng.sample(exceptions, min(extra, len(exceptions))):
        if exc.pro_number in rows:
            continue
        drift = rng.choice([0, 0, 1, -1, 2])
        rows[exc.pro_number] = ExpectedShipment(
            pro_number=exc.pro_number,
            terminal=exc.origin_terminal,
            expected_quantity=max(1, exc.pieces + drift),
            commodity_code=exc.commodity_code,
        )

    # A few PROs that were never an exception, so a clean scan can be demoed too.
    for _ in range(extra // 2):
        pro = generate_pro(rng)
        rows.setdefault(
            pro,
            ExpectedShipment(
                pro_number=pro,
                terminal=rng.choice(TERMINALS),
                expected_quantity=rng.randint(2, 14),
                commodity_code=rng.choice(COMMODITIES),
            ),
        )

    for row in rows.values():
        db.merge(row)
    return len(rows)


def seed(count: int = 80, duplicates: int = 8, labeled: int = 26, reset: bool = False, seed_value: int = 42) -> dict:
    Base.metadata.create_all(bind=engine)
    rng = random.Random(seed_value)

    with SessionLocal() as db:
        sync_clearing_codes(db)
        if reset:
            reset_data(db)

        base_count = max(count - duplicates, 1)
        # Spread labels evenly across the taxonomy so the accuracy report is not skewed.
        label_slots = {i for i in rng.sample(range(base_count), min(labeled, base_count))}

        created: list[OVException] = []
        for i in range(base_count):
            scenario = SCENARIOS[i % len(SCENARIOS)] if i < len(SCENARIOS) else rng.choice(SCENARIOS)
            exc, _ = _build_exception(rng, scenario, labeled=i in label_slots)
            db.add(exc)
            created.append(exc)

        dupes = [_duplicate_of(src) for src in rng.sample(created, min(duplicates, len(created)))]
        for clone in dupes:
            db.add(clone)

        db.commit()
        expected = seed_expected_shipments(db, rng, created)
        db.commit()

        return {
            "exceptions_created": len(created) + len(dupes),
            "exact_duplicates": len(dupes),
            "labeled_for_validation": len(label_slots),
            "expected_shipments": expected,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic OV exceptions")
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--duplicates", type=int, default=8)
    parser.add_argument("--labeled", type=int, default=26)
    parser.add_argument("--reset", action="store_true", help="delete existing POC data first")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    summary = seed(
        count=args.count,
        duplicates=args.duplicates,
        labeled=args.labeled,
        reset=args.reset,
        seed_value=args.seed,
    )
    print(summary)


if __name__ == "__main__":
    main()
