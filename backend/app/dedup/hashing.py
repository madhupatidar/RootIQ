"""Content hashing for exact-match dedup (spec Section 6).

Known limitation: this is exact-match only. Near-duplicate text (same issue, reworded
notes) will NOT hit the cache. Catching those needs embedding similarity - Phase 2.
"""

import hashlib
import re

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Lowercase, trim, and collapse repeated whitespace."""
    return _WHITESPACE.sub(" ", (text or "").strip().lower())


def compute_content_hash(pro_number: str | None, combined_notes_text: str | None) -> str:
    payload = f"{normalize(pro_number)}|{normalize(combined_notes_text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
