# OV Exception — AI Root Cause & Prevention POC

Overage (OV) exceptions only. Classifies the root cause of an OV exception from its
investigation text with a **locally-hosted LLM via Ollama**, deduplicates identical inputs
with a SHA-256 content hash, persists every classification event to **PostgreSQL**,
aggregates the results, and turns the aggregate into plain-English prevention
recommendations — all visible in a React dashboard.

> **New to this project?** Read [docs/APPLICATION_GUIDE.md](docs/APPLICATION_GUIDE.md) — a
> step-by-step, plain-language walkthrough of the functional flow, technical architecture,
> API contracts, prompts, AI parameters and a full worked example.
> A shareable Word version lives at `docs/APPLICATION_GUIDE.docx`; rebuild it after editing
> the markdown with `python docs/build_docx.py` (needs Pandoc + Node).

```
ov-rootcause-poc/
├─ backend/                 FastAPI + SQLAlchemy + Ollama + pandas
│  ├─ app/
│  │  ├─ main.py            app factory, CORS, startup (create tables + sync clearing codes)
│  │  ├─ models.py          SQLAlchemy models (spec Section 3)
│  │  ├─ schemas.py         Pydantic request/response models
│  │  ├─ analytics.py       pandas aggregation over classified exceptions
│  │  ├─ clearing_codes.py  15-code lookup seeding (spec Section 5)
│  │  ├─ questions.py       6 real AS400 checks (+ 9 synthetic seed steps)
│  │  ├─ pro_number.py      12-digit PRO + check digit
│  │  ├─ routes/            exceptions.py · classify.py · insights.py
│  │  ├─ ai/                taxonomy.py · classifier.py · recommender.py · ollama_client.py
│  │  ├─ dedup/             hashing.py · cache.py
│  │  └─ seed/              seed_data.py (synthetic) · import_mock.py (real OS&D export)
│  └─ tests/                24 tests, no LLM required (Ollama is mocked)
├─ frontend/                Vite + React dashboard
├─ docs/APPLICATION_GUIDE.md  full functional + technical walkthrough
├─ mock data/               18-file real OS&D export (6,500 OV records)
└─ docker-compose.yml       postgres (+ optional ollama)
```

---

## Quick start

### 1. Infrastructure

**Database** — point `DATABASE_URL` at any Postgres you have, e.g.
`postgresql://postgres:admin@127.0.0.1:5432/RootIQ`, or bring one up with
`docker compose up -d postgres` (exposes 5433). Tables are created on startup.

**Model** — either hosted Ollama Cloud (default in `.env.example`) or a local daemon:

```bash
# Hosted (no local GPU needed) — set in backend/.env:
#   OLLAMA_BASE_URL=https://ollama.com
#   OLLAMA_MODEL=gpt-oss:120b
#   OLLAMA_API_KEY=<key from https://ollama.com/settings/keys>

# ...or local:
ollama pull llama3.1:8b && ollama serve   # OLLAMA_API_KEY stays blank
```

`GET /health` reports which host/model is in use and whether it is reachable.

> No Postgres handy? `DATABASE_URL=sqlite:///./ov_rootcause_poc.db` also works —
> the models are portable — but Postgres is the target for the POC.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
cp .env.example .env

.venv/Scripts/python.exe -m app.seed.seed_data --count 80 --reset
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs> · health (incl. Ollama status): <http://localhost:8000/health>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api -> localhost:8000)
```

### 4. Demo flow

1. **OV Exceptions** tab → 80 seeded exceptions, BRD-style filters (date, terminal, commodity, value range, status, clearing code).
2. Hit **Classify unclassified** → watch the summary: *N fresh AI calls, M cache hits*.
3. Open any exception → category, confidence, collapsible **Why?**, a **fresh vs cache** badge, override control, and the clear action.
4. **Root Cause Dashboard** → distribution chart, cache hit rate, accuracy vs the hand-labeled set, and **Regenerate recommendations** → click a recommendation's *supporting exceptions* to trace it back to evidence.

---

## How the pieces work

### Deduplication & caching (Section 6)

`content_hash = sha256(normalize(pro_number) + "|" + normalize(combined_notes_text))`
where `normalize()` lowercases, trims and collapses whitespace.

Every classification request:

| | |
|---|---|
| **Cache hit** | `ClassificationCache.hit_count++`, `last_hit_at` updated, a new `RootCauseClassification` row is appended with `source=cache_hit`. **No Ollama call.** |
| **Cache miss** | Ollama is called once, `ClassificationCache` row inserted, `RootCauseClassification` appended with `source=ai_fresh`. |

Two tables on purpose: `ClassificationCache` is the fast lookup (one row per unique hash,
updated in place); `RootCauseClassification` is append-only audit history, so no event is
ever lost to an overwrite. The Postgres table *is* the cache — no Redis layer is used for
the POC.

**Known limitation:** exact-match dedup only. Reworded notes describing the same issue will
*not* hit the cache; that needs embedding similarity (Phase 2). `tests/test_hashing.py`
pins this behaviour explicitly.

Also note: the hash covers `pro_number` + investigation notes (per spec). `additional_details`
is fed to the model but is deliberately **not** part of the dedup key.

### Classification (Section 7)

`app/ai/classifier.py::classify_ov_exception(text) -> ClassificationResult` — the single
entry point, so swapping models or moving to a hosted API touches only that file plus
`ollama_client.py`. `ollama_client` sends `Authorization: Bearer $OLLAMA_API_KEY` when the
key is set, which is what makes hosted Ollama Cloud (`https://ollama.com`) work unchanged.

- taxonomy + definitions + 9 hand-written few-shot examples, `temperature=0`, `format=json`
- **validate → retry once (stricter) → fall back.** A malformed response, an off-taxonomy
  category, or an unreachable Ollama all end at `category="Other"`, `confidence=0.0`,
  `needs_review=True` instead of crashing the pipeline.
- Batch classification is sequential — Ollama serves one model instance and POC scale is
  dozens-to-hundreds.

### Recommendations (Section 8)

pandas aggregates the latest classification per exception (by category, origin/destination
terminal, commodity, rolling window). The **aggregated stats table** — not raw notes — is
fed to a second Ollama call, which returns 3–5 tagged recommendations. Each is stored with
`supporting_exception_ids` so the UI can click through to the evidence.

### Clearing codes (Section 5)

All 15 codes live in the `clearing_codes` lookup table, seeded on startup. `POST
/ov-exceptions/{id}/clear` validates against that table (not free text), sets
`clearing_code` + `cleared_at`, and moves status to `cleared` — it never touches
classification history.

> **TODO before production:** `app/clearing_codes.py` hardcodes the 15 values for POC speed.
> They are owned by the clearing-code reference API — replace the constant with a sync job
> so the table can't silently drift.

---

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/ov-exceptions` | create (validates 12-digit PRO check digit, `dollar_amount` required when `value_range=3`) |
| GET | `/ov-exceptions` | filters: `terminal`, `origin_terminal`, `destination_terminal`, `commodity_code`, `value_range`, `status`, `clearing_code`, `category`, `date_from`, `date_to` |
| GET | `/ov-exceptions/{id}` | detail incl. investigation + latest classification |
| POST | `/ov-exceptions/{id}/investigation` | submit answers; re-computes `content_hash` |
| POST | `/ov-exceptions/{id}/clear` | set clearing code + cleared_at |
| GET | `/clearing-codes` | the 15-code lookup table |
| GET | `/investigation-questions` | the 9 BRD investigation steps |
| POST | `/classify/{id}` | cache-aware single classify |
| POST | `/classify/batch` | cache-aware bulk classify (`?force=true` to re-run) |
| GET | `/classify/{id}/history` | full append-only classification history |
| POST | `/classify/{id}/override` | human-in-the-loop correction (appended, never overwrites) |
| GET | `/classify/taxonomy` | categories + definitions |
| GET | `/insights/distribution` | % breakdown, `?include_breakdowns=true` for terminal/commodity splits |
| GET | `/insights/recommendations` | latest recommendations |
| POST | `/insights/recommendations/generate` | regenerate for a scope |
| GET | `/insights/recommendations/{id}/evidence` | supporting exceptions |
| GET | `/insights/cache-stats` | hit rate, calls saved |
| GET | `/insights/accuracy` | accuracy vs the hand-labeled validation set |
| GET | `/insights/filters` | distinct terminals/commodities for dropdowns |

---

## Seed data (Section 12)

```bash
python -m app.seed.seed_data --count 80 --duplicates 8 --labeled 26 --reset
```

- 72 unique synthetic OV exceptions spanning all 12 categories, with realistic
  step-by-step investigation text (25 scenario templates).
- **8 exact duplicates** (same PRO + identical notes) so the cache demonstrably hits.
- **26 hand-labeled** exceptions (`labeled_category`) driving `/insights/accuracy`.
  Duplicates are deliberately left unlabeled to keep the validation set clean.
- Shipper/consignee names are fabricated — no real PII.

## Real data import (`mock data/`)

The 18-file OS&D export in `mock data/` is loaded **directly from the folder by a CLI
script**, not through a browser upload — it is a bulk backfill, so it needs to be
re-runnable when the mapping changes, not a one-shot multipart POST.

```bash
cd backend
python -m app.seed.migrate                          # one-off DDL (no Alembic in the POC)
python -m app.seed.import_mock --dry-run            # map + count, writes nothing
python -m app.seed.import_mock                      # full load
python -m app.seed.import_mock --with-notes-only    # only rows with investigation text
python -m app.seed.import_mock --limit 300          # small demo slice
python -m app.seed.import_mock --purge-synthetic    # full load + drop the generated seed rows
```

- **6,500 records, all `osdType: "OV"`, zero duplicate `osdNumber`.**
- Idempotent on `osdNumber` → `OVException.source_osd_number`; re-running updates in
  place, so the import can be repeated safely.
- `--purge-synthetic` deletes every exception with no `osdNumber` (the generated seed
  rows) plus their classifications, orphaned cache entries and all recommendations, so
  the database holds real export data only. It also removes the hand-labelled rows, so
  `/insights/accuracy` reports zero evaluated afterwards.
- Dates are AS400 `CYYMMDD` + `HHMM`/`HHMMSS` (`1250416`/`1504` → 2025-04-16 15:04),
  decoded from `createdDate`/`createdTime` and `clearingDate`/`clearingTime`. They are
  terminal wall-clock with no zone, so they are stored as UTC and the UI renders them in
  UTC — otherwise the browser would shift every date by its own offset.
- `commodity` arrives as free text; the importer resolves it against the commodity
  master in `app/reference.py` and stores both `commodity_code` and
  `commodity_description`. Unmatched or blank values become `9999`.
- **3,380 of the 6,500** carry investigation text. The other ~3,120 have no notes for
  the model to read and will classify as `Other` — classify the 3,380 subset, not all.
- The six AS400 checks (`od400Check`, `billOfLadingCheck`, `drCheck`, `psCheck`,
  `consigneeCheck`, `shipmentCheck`) are now the canonical `INVESTIGATION_QUESTIONS`;
  the nine synthetic keys are retained as `SEED_QUESTIONS` for the generator and tests.
- AS400 date formats are decoded on the way in: `entryDate` (`"Jun 02 2026"`) + `entryTime`
  (HHMM) → `created_at`; `clearingDate` CYYMMDD (`1260910` → 2026-09-10) → `cleared_at`.

There is no migration tool in this POC (`create_all` only). The import added two schema
changes — `commodity_code` widened to `VARCHAR(80)` (real commodities are 48-char
descriptions, not codes) and the new `source_osd_number` column. On an existing database
apply them additively rather than dropping:

```sql
ALTER TABLE ov_exceptions ALTER COLUMN commodity_code TYPE VARCHAR(80);
ALTER TABLE ov_exceptions ADD COLUMN IF NOT EXISTS source_osd_number BIGINT;
ALTER TABLE ov_exceptions ADD CONSTRAINT uq_ov_exceptions_source_osd_number UNIQUE (source_osd_number);
```

> **This export contains real PII** — actual shipper/consignee names, street addresses and
> personal email addresses embedded in the investigation text. Classification sends that
> text to `https://ollama.com`. Clear that with data governance before running a bulk
> classify, or scrub the notes first.

## Tests

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
```

24 tests covering hashing/normalization, PRO check digits, the classifier's parse →
retry → fallback ladder (Ollama mocked), cache-hit accounting, clearing-code validation,
override history, and the full create → investigate → classify → clear flow.

## Reporting the numbers

```bash
curl localhost:8000/insights/accuracy      # accuracy on the hand-labeled set
curl localhost:8000/insights/cache-stats   # hit rate + Ollama calls saved
```

Both are also surfaced as stat tiles on the dashboard.

Measured run (`gpt-oss:120b` on Ollama Cloud, 80 seeded exceptions):

| Metric | Result |
|---|---|
| Classification accuracy | **26 / 26 = 100%** on the hand-labeled set |
| Cache hit rate | **10%** — 8 hits, 72 fresh calls, 8 Ollama calls saved |
| Malformed-response fallbacks | 0 |
| Recommendations generated | 5, each traceable to 6–9 supporting exceptions |

> Read the accuracy honestly: the seeded investigation text is generated from 25 scenario
> templates, so it is cleaner and more separable than real OS&D notes. Expect the number to
> drop once real investigation text is substituted — re-run the report then before quoting
> it to stakeholders.

## Out of scope for this POC

Live AS400 read/write · real-time processing · auth/roles · model training or fine-tuning ·
semantic (near-duplicate) dedup · exception types other than OV.
