"""Tier 2 - live investigation assist.

A nearest-neighbour lookup over past classified investigation notes while the clerk types.
It is explicitly *not* the classification: it is a draft suggestion whose real job is to make
the clerk write better notes, which in turn makes the eventual AI classification better.

TF-IDF cosine, computed in-process. No embedding service, no Ollama call, no extra dependency
beyond what the project already installs.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OVException, OVInvestigation, RootCauseClassification
from app.prevention import playbook

MIN_QUERY_TOKENS = 4
MIN_SIMILARITY = 0.12
STRONG_SIMILARITY = 0.45

_TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """
    a an and any are as at be been being but by check checked confirm confirmed did do does for from
    had has have his her he i if in into is it its no not of on or our out over same she should so
    some such than that the their them then there these they this to too was we were what when where
    which while who will with would yes y n na none n/a
    """.split()
)


@dataclass(slots=True)
class _Doc:
    exception_id: str
    pro_number: str
    category: str
    confidence: float
    origin_terminal: str
    commodity_code: str
    text: str
    vector: dict[str, float]


@dataclass(slots=True)
class _Index:
    fingerprint: tuple
    docs: list[_Doc]
    idf: dict[str, float]


_lock = threading.Lock()
_index: _Index | None = None


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 3 and t not in STOPWORDS]


def _vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    if not tokens:
        return {}
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    raw = {t: (c / len(tokens)) * idf.get(t, 0.0) for t, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in raw.values()))
    if norm == 0:
        return {}
    return {t: v / norm for t, v in raw.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(token, 0.0) for token, weight in a.items())


def _fingerprint(db: Session) -> tuple:
    row = db.execute(
        select(func.count(RootCauseClassification.id), func.max(RootCauseClassification.classified_at))
    ).one()
    return (int(row[0] or 0), str(row[1] or ""))


def _build(db: Session, fingerprint: tuple) -> _Index:
    stmt = (
        select(OVException, OVInvestigation, RootCauseClassification)
        .join(OVInvestigation, OVInvestigation.ov_exception_id == OVException.id)
        .join(RootCauseClassification, RootCauseClassification.ov_exception_id == OVException.id)
        .order_by(RootCauseClassification.classified_at)
    )
    latest: dict[str, tuple] = {}
    for exc, inv, cls in db.execute(stmt).all():
        if not (inv.combined_notes_text or "").strip():
            continue
        latest[str(exc.id)] = (exc, inv, cls)

    tokenized = [(payload, tokenize(payload[1].combined_notes_text)) for payload in latest.values()]
    tokenized = [(payload, tokens) for payload, tokens in tokenized if tokens]

    total = len(tokenized)
    doc_freq: dict[str, int] = {}
    for _, tokens in tokenized:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1
    idf = {token: math.log((total + 1) / (df + 1)) + 1.0 for token, df in doc_freq.items()}

    docs = [
        _Doc(
            exception_id=str(exc.id),
            pro_number=exc.pro_number,
            category=cls.category,
            confidence=cls.confidence,
            origin_terminal=exc.origin_terminal,
            commodity_code=exc.commodity_code,
            text=inv.combined_notes_text,
            vector=_vector(tokens, idf),
        )
        for (exc, inv, cls), tokens in tokenized
    ]
    return _Index(fingerprint=fingerprint, docs=docs, idf=idf)


def _get_index(db: Session) -> _Index:
    global _index
    fingerprint = _fingerprint(db)
    with _lock:
        if _index is None or _index.fingerprint != fingerprint:
            _index = _build(db, fingerprint)
        return _index


def _snippet(text: str, limit: int = 220) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def suggest(db: Session, text: str, *, top_k: int = 5) -> dict:
    tokens = tokenize(text)
    base: dict = {
        "status": "ok",
        "advisory": True,
        "disclaimer": "Draft suggestion from similar past cases — the final root cause is still set by classification.",
        "suggested_category": None,
        "confidence": 0.0,
        "basis": "",
        "matches": [],
        "category_votes": [],
        "note_prompts": [],
        "missing_details": playbook.missing_details(text),
        "corpus_size": 0,
    }

    if len(tokens) < MIN_QUERY_TOKENS:
        base["status"] = "too_short"
        base["basis"] = "Keep typing — a few more words and I can compare this to past cases."
        return base

    index = _get_index(db)
    base["corpus_size"] = len(index.docs)
    if not index.docs:
        base["status"] = "no_corpus"
        base["basis"] = "No classified cases to compare against yet."
        return base

    query = _vector(tokens, index.idf)
    if not query:
        base["status"] = "no_match"
        base["basis"] = "Nothing in these words matches past cases yet."
        return base

    scored = [(doc, _cosine(query, doc.vector)) for doc in index.docs]
    scored = [(doc, sim) for doc, sim in scored if sim >= MIN_SIMILARITY]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    matches = scored[:top_k]

    if not matches:
        base["status"] = "no_match"
        base["basis"] = f"No close match among {len(index.docs)} classified cases — this one may be novel."
        base["note_prompts"] = playbook.note_prompts("Other")
        return base

    votes: dict[str, float] = {}
    for doc, sim in matches:
        votes[doc.category] = votes.get(doc.category, 0.0) + sim
    total_weight = sum(votes.values())
    ranked = sorted(votes.items(), key=lambda pair: pair[1], reverse=True)

    top_category, top_weight = ranked[0]
    best_sim = matches[0][1]
    share = top_weight / total_weight if total_weight else 0.0
    confidence = round(share * min(1.0, best_sim / STRONG_SIMILARITY), 2)

    base["suggested_category"] = top_category
    base["confidence"] = confidence
    base["basis"] = f"{len(matches)} similar case(s) out of {len(index.docs)} classified."
    base["matches"] = [
        {
            "exception_id": doc.exception_id,
            "pro_number": doc.pro_number,
            "category": doc.category,
            "similarity": round(sim, 3),
            "origin_terminal": doc.origin_terminal,
            "commodity_code": doc.commodity_code,
            "snippet": _snippet(doc.text),
        }
        for doc, sim in matches
    ]
    base["category_votes"] = [
        {"category": category, "share": round((weight / total_weight) * 100, 1) if total_weight else 0.0}
        for category, weight in ranked
    ]
    base["note_prompts"] = playbook.note_prompts(top_category)
    return base


def reset_index() -> None:
    """Drop the cached corpus - used by tests and after a reseed."""
    global _index
    with _lock:
        _index = None
