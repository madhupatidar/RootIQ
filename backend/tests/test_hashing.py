from app.dedup.hashing import compute_content_hash, normalize
from app.pro_number import compute_check_digit, generate_pro, is_valid_pro


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  Freight   was\tNEVER  scanned \n") == "freight was never scanned"


def test_identical_text_produces_identical_hash():
    a = compute_content_hash("402118834007", "Freight was never scanned at origin.")
    b = compute_content_hash("402118834007", "  freight was NEVER   scanned at origin. ")
    assert a == b


def test_different_pro_produces_different_hash():
    a = compute_content_hash("402118834007", "same notes")
    b = compute_content_hash("402118834008", "same notes")
    assert a != b


def test_reworded_text_is_a_known_miss():
    """Exact-match dedup only - near duplicates are a documented Phase 2 limitation."""
    a = compute_content_hash("402118834007", "Freight was never scanned at origin.")
    b = compute_content_hash("402118834007", "The freight never got scanned at the origin dock.")
    assert a != b


def test_pro_check_digit_roundtrip():
    pro = generate_pro()
    assert is_valid_pro(pro)
    assert compute_check_digit(pro[:11]) == pro[11]


def test_invalid_pro_rejected():
    assert not is_valid_pro("40211883400")       # too short
    assert not is_valid_pro("40211883400X")      # non numeric
    base = "40211883400"
    bad_digit = str((int(compute_check_digit(base)) + 1) % 10)
    assert not is_valid_pro(base + bad_digit)
