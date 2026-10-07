# RootIQ V1 - OV Prevention Business Requirements

**From historical root causes to action before the next overage**

| Field | Value |
|---|---|
| Product | RootIQ |
| Owner | Saia LTL Freight — OS&D Operations |
| Scope | V1 only: Overage (OV) prevention |
| Status | Draft for client review; existing capabilities and proposed process steps are distinguished |
| Document type | Business requirements and client demonstration flow |
| Baseline | Retain the existing root-cause classifier, 12 categories and review workflow |
| Revision date | 6 October 2026 |

---

## Contents

1. [Business background](#1-business-background)
2. [Scope](#2-scope)
3. [Users](#3-users)
4. [Functional requirements — step by step](#4-functional-requirements--step-by-step)
   - [Step 1 — Log an OV exception](#step-1--log-an-ov-exception)
   - [Step 2 — Browse and filter exceptions](#step-2--browse-and-filter-exceptions)
   - [Step 3 — Deduplicate before spending a model call](#step-3--deduplicate-before-spending-a-model-call)
   - [Step 4 — Classify the root cause (AI)](#step-4--classify-the-root-cause-ai)
   - [Step 5 — Review and clear the exception](#step-5--review-and-clear-the-exception)
   - [Step 6 — Aggregate and visualise](#step-6--aggregate-and-visualise)
   - [Step 7 — Generate prevention recommendations](#step-7--generate-prevention-recommendations)
     - [How AI selects an action](#how-ai-selects-an-action)
     - [What a prevention recommendation must contain](#what-a-prevention-recommendation-must-contain)
   - [Step 8 — Prevent at the point of work](#step-8--prevent-at-the-point-of-work-three-tiers)
     - [Input factors and data availability](#input-factors-and-data-availability)
     - [Root cause to prevention matrix](#root-cause-to-prevention-matrix)
     - [Where the recommendation appears](#where-the-recommendation-appears)
     - [V1 end-to-end workflow](#v1-end-to-end-workflow)
     - [Client example: piece count](#client-example-piece-count)
     - [Client examples: weight and dimensions](#client-examples-weight-and-dimensions)
   - [Step 9 — Measure whether prevention worked](#step-9--measure-whether-prevention-worked)
   - [Step 10 — Load data](#step-10--load-data)
   - [Client demonstration and acceptance](#client-demonstration-and-acceptance)
5. [Business rules summary](#5-business-rules-summary)
6. [Data model (as built)](#6-data-model-as-built)
7. [Interfaces (API surface)](#7-interfaces-api-surface)
8. [Non-functional requirements](#8-non-functional-requirements)
9. [Success criteria (POC)](#9-success-criteria-poc)
10. [V1 decisions and deferred work](#10-v1-decisions-and-deferred-work)

---

## 1. Business background

When freight arrives at a terminal that does not belong to any manifested shipment, OS&D
raises an **Overage (OV) exception**. Today a clerk logs the exception, works through a set of
investigation checks, writes free-text notes, and finally clears the exception with a
clearing code.

RootIQ already classifies investigation notes and aggregates the results. The remaining
business question for this V1 discussion is how that knowledge reaches the employee who
can interrupt the same failure on the next shipment, while the freight is still under
operational control.

### Problem statement

1. A root-cause label alone does not tell the employee when or where to intervene.
2. A recommendation shown only after an OV is logged is too late for that occurrence.
3. A dashboard suggestion does not establish that an employee performed the action.
4. A completed check or a lower exception count alone does not prove that an OV was prevented.

### Business objective

V1 builds on the existing root-cause implementation. Its focus is to explain how the
cause of a past OV selects a practical verification or corrective action for a different,
currently moving shipment, before an OV exception needs to be created for that shipment.

**Historical OV -> Root cause -> Historical pattern -> Prevention point ->
Prevention recommendation -> Employee action -> Expected outcome.**

Every recommendation must state why it applies, when and where to act, who is responsible,
which operational screen should present it, and what permits the shipment to continue.
AI identifies and explains the pattern; business-approved rules govern the physical action
and any release decision. The model does not independently stop or release freight.

An existing OV cannot be prevented retrospectively. A discrepancy found and corrected
before the next handoff is a preventive intervention, not proof that an OV was avoided.
Unresolved discrepancies still follow the normal OS&D process; the POC must not hide or
suppress an exception that business policy requires.

---

## 2. Scope

### V1 delivery boundary

This revision is a prevention-focused business design, not the earlier V2 expansion.
The existing classifier, taxonomy, cache and human-review behavior remain unchanged.
"Existing" below means present in the application; "proposed" means a V1 process or
integration requirement, not a feature delivered by this document update.

| Capability | Existing POC | V1 prevention requirement or limitation |
|---|---|---|
| Root cause and recommendations | Classification, aggregate-based AI recommendations and supporting exception links | Retain; connect advice to an operational checkpoint and responsible role |
| Historical watch list | Terminal/commodity, lane, commodity, origin-terminal and package-type cohorts | Shipper-specific matching is proposed; the current watch query does not group by shipper |
| Quantity verification | Manual PRO/count entry, expected-count lookup, recorded mismatch and follow-up | Demonstrate before staging; pickup/receiving delivery is a proposed operational extension |
| Weight and dimensions | Exception records include one weight value; no declared-versus-measured verification workflow | Define checks, units, tolerances and receiving/measurement handoff; not yet implemented |
| Scans, labels and routing | Root causes and corresponding playbook advice | Live event validation, missing-scan alerts and load-system gates are not implemented |
| Process control | Standalone RootIQ screens and recorded employee actions | No integrated shipment hold/release or automatic delivery into a handheld/driver application |
| Follow-up | On-demand attention scans and a count-based effectiveness POC | Treat results as follow-up signals, not proof of shipment-level risk or causal reduction |

### In scope (built)

- OV exception logging, investigation capture, and clearing.
- AI root-cause classification into a fixed 12-category taxonomy.
- Contributing-factor tagging (the *why* behind the category).
- Exact-match deduplication / caching of classification results.
- Append-only classification audit history with human override.
- Analytics dashboard: distribution, terminal/commodity breakdowns, cache savings, accuracy.
- AI-generated prevention recommendations traceable to supporting exceptions.
- Three prevention tiers: pre-handling watch list, live notes assist, supervisor attention flags.
- Point-of-process staging quantity check.
- Recommendation effectiveness evaluation with automatic escalation.
- Synthetic seed data and a bulk importer for the real OS&D export.

### Out of scope (POC limitations, documented deliberately)

- Shortage / damage / refused exception types — OV only.
- Authentication, authorisation and role-based access control.
- Live integration with AS400 / OD400, the manifest service, or the clearing-code reference API
  (all are stubbed or hardcoded).
- Semantic (embedding) deduplication — matching is exact-text only.
- Database migration tooling (schema is created/extended by a DDL list, not Alembic).
- Real customer PII in the client demonstration; use synthetic or approved anonymised examples.

V1 does not require a trained risk model, a new 0-100 risk score, additional exception
types, a cost-avoided dashboard, or a rebuild of root-cause classification. Production
integrations and workflow enforcement require separate implementation and business approval.

---

## 3. Users

| Role | What they do in the app |
|---|---|
| **OS&D clerk** | Logs the OV exception, answers investigation checks, writes notes, clears the exception. |
| **OS&D analyst** | Reviews AI classifications, overrides wrong ones, reads the dashboard. |
| **Dock worker** | Runs the staging quantity check before freight is staged. |
| **Terminal supervisor** | Reads the watch list before handling, works attention flags, acknowledges/resolves them. |
| **Operations leadership** | Consumes distribution trends, recommendations and prevention effectiveness. |

---

## 4. Functional requirements — step by step

### Step 1 — Log an OV exception

**Screen:** `Log exception` (`/log`)

The clerk records the shipment and freight facts in four blocks:

| Block | Captured fields |
|---|---|
| Shipment | PRO number, origin terminal, destination terminal, shipper, consignee, OD400 PRO, manifest number, found on (trailer / bay) + trailer or bay number, BL / PO / SN numbers |
| Freight | Hazmat, handling units, commodity code + description, package type, pieces, weight, shrink-wrapped, item/carton/model/serial, value range, dollar amount, manufacturer/brand, additional details |
| Investigation | The six canonical AS400 checks, each Y/N plus free text |
| Who | Entry user, assigned to |

**Rules**

- `pro_number` must be a valid 12-digit PRO and pass the check-digit validation.
- `dollar_amount` is mandatory when `value_range = 3` (> $1,000). Ranges are 1 = $0–250, 2 = $250–1,000, 3 = > $1,000.
- `found_on` must be `trailer` or `bay`.
- On creation the exception enters status `exception_entry`.
- A `content_hash` is computed immediately (see Step 3).

**Investigation checks (the canonical six)**

1. Was the OD400 checked?
2. Was the bill of lading checked for errors?
3. Was the delivery receipt checked?
4. Was a packing slip found and checked?
5. Was the consignee contacted?
6. Were related shipments checked?

The free-text answers are concatenated into `combined_notes_text`. The classifier also
receives `additional_details` and recurrence context; the existing inputs are retained.

> **Known gap (documented):** none of the six checks is a piece-count verification, so a
> quantity mismatch has to be inferred from free text or captured by the staging check (Step 8).

**Live assistance:** while the clerk types notes, the **Notes Assist** panel (prevention tier 2)
suggests a likely root cause based on TF-IDF similarity against past resolved cases. It is
advisory only and never auto-fills the classification.

---

### Step 2 — Browse and filter exceptions

**Screen:** `OV Exceptions` (`/exceptions`)

A filterable work queue over every exception. Filters: date from/to, terminal, origin terminal,
destination terminal, commodity code, value range, status, clearing code, and root-cause category.

Stored status values (this is not a claim that every transition is enforced by the UI):

```
exception_entry → in_progress → investigation_complete → needs_cleared → cleared
```

---

### Step 3 — Deduplicate before spending a model call

Every classification request first computes:

```
content_hash = sha256( normalize(pro_number) + "|" + normalize(combined_notes_text) )
normalize() = lowercase + trim + collapse whitespace
```

| Outcome | System behaviour |
|---|---|
| **Cache hit** | `ClassificationCache.hit_count++`, `last_hit_at` updated, a new classification row is appended with `source = cache_hit`. **No model call is made.** |
| **Cache miss** | The model is called once; a cache row is inserted and a classification row appended with `source = ai_fresh`. |

**Design decisions**

- Two tables on purpose: `classification_cache` is the fast single-row-per-hash lookup;
  `root_cause_classifications` is append-only audit history so no event is ever overwritten.
- The Postgres table *is* the cache — no Redis layer in the POC.
- `additional_details` is fed to the model but is deliberately **excluded** from the dedup key.
- **Limitation:** exact-match only. Reworded notes describing the same issue will not hit the cache.

---

### Step 4 — Classify the root cause (AI)

Single entry point: `classify_ov_exception(text)`.

**Taxonomy — 12 categories**

| # | Category | Meaning |
|---|---|---|
| 1 | Improper Packaging | Packaging failed in transit, separating pieces from the shipment. |
| 2 | Missed Scan | Freight was never scanned at a required checkpoint. |
| 3 | Data Entry / Scan Mismatch | Freight was scanned but tied to the wrong PRO / record. |
| 4 | Misrouting | Sent to the wrong terminal or line-haul destination. |
| 5 | Load Swap / Co-mingled Shipment | Loaded on the wrong trailer or mixed with another shipment. |
| 6 | Handling Damage | Dock or transit handling damage (not packaging failure). |
| 7 | Documentation Errors | BOL/labels incomplete, illegible or unusable. |
| 8 | Shipper Load & Count Discrepancy | BOL count/description does not match what arrived. |
| 9 | Consignee Issue | Root cause traces to consignee-side action. |
| 10 | Carrier Error | Interline/partner carrier handling or documentation caused it. |
| 11 | Labeling Error | Label missing, wrong or unreadable. |
| 12 | Other | Not covered above, or insufficient detail. |

**Contributing factors — 7 boolean flags** returned alongside the category:
`terminal_pattern`, `handler_pattern`, `scan_issue`, `quantity_mismatch`,
`trailer_bay_mismatch`, `documentation_issue`, `training_signal`.

These answer *why*, so a supervisor reads "recurring quantity-verification issue at ATL"
rather than just "loaded incorrectly".

- `training_signal` is **computed deterministically by the system**, not by the model. It
  overrides the model's value, logs any disagreement, and is re-applied on cache hits.
- Recurrence context (how often this cause has already occurred at this terminal / for this
  handler) is injected into the prompt from the same aggregation that powers the dashboard.

**Reliability requirements**

- Deterministic settings: `temperature = 0`, `format = json`, taxonomy + definitions + 9
  hand-written few-shot examples in the prompt.
- **Validate → retry once with a stricter prompt → fall back.** A malformed response, an
  off-taxonomy category, or an unreachable model all resolve to
  `category = "Other"`, `confidence = 0.0`, `needs_review = true` — the pipeline never crashes.
- Batch classification is sequential (one model instance; POC scale is dozens to hundreds).

**Operations**

| Action | Behaviour |
|---|---|
| Classify one | Cache-aware classification of a single exception. |
| Classify batch | Cache-aware bulk run; returns *N fresh calls / M cache hits*; `force=true` re-runs. |
| View history | Full append-only event history for the exception. |
| Override | Human correction appended with `source = human_override`; never overwrites prior rows. |

---

### Step 5 — Review and clear the exception

**Screen:** `Exception detail` (`/exceptions/:id`)

Shows: investigation notes, full exception detail, the current root-cause classification
(category, confidence, collapsible **Why?** reasoning, contributing-factor badges, and a
**fresh vs cache** source badge), the override control, the clear action, and the complete
classification history.

**Clearing rules**

- Clearing code must exist in the 15-code `clearing_codes` lookup table — free text is rejected.
- Clearing sets `clearing_code` + `cleared_at` and moves status to `cleared`.
- Clearing **never** modifies classification history.

**The 15 clearing codes:** BE, BS, BW, CA, CF, CG, CLP, CP, CR, DA, FC, RC, RI, RS, SV.

> **TODO before production:** these 15 values are hardcoded. They are owned by the clearing-code
> reference API and must be replaced with a sync job so the table cannot silently drift.

---

### Step 6 — Aggregate and visualise

**Screen:** `Root Cause Dashboard` (`/dashboard`)

Aggregation (pandas) takes the **latest classification per exception** and groups by category,
origin/destination terminal, commodity and rolling time window.

Dashboard sections:

| Section | Content |
|---|---|
| Root cause mix | Percentage distribution across the 12 categories, with contributing-factor badges. |
| Where overages originate | Terminal breakdown. |
| Freight most affected | Commodity breakdown. |
| Cache statistics | Hit rate and model calls saved. |
| Accuracy | Measured against the hand-labelled validation set. |
| Prevention actions | The generated recommendations (Step 7). |
| Supporting exceptions | Click-through evidence drawer for any recommendation. |

---

### Step 7 — Generate prevention recommendations

#### How AI selects an action

There are two separate decisions: **which recurring problem deserves attention**, and
**which operational control is appropriate**. V1 combines AI with business-owned actions;
it does not ask the model to invent a hold policy, a measurement tolerance or a shipment identity.

1. **Classify a historical OV.** The existing AI reads the investigation and identifies the
  root cause, reasoning, confidence and contributing factors. The analyst can review it.
2. **Find repeat evidence.** The application groups classified OVs by the supported scope.
  It identifies causes concentrated on a lane, origin terminal, commodity or package type.
  A proposed shipper view would use a stable shipper identifier, not an assumed name match.
3. **Explain the pattern.** The recommendation model receives the aggregated statistics,
  not the entire set of raw notes. Its prompt requests 3-5 short, category-tagged actions.
  The application queries the supporting exception IDs; the model does not supply those IDs.
4. **Choose the preventive control.** The current floor playbook maps the category to concrete
  actions. For Shipper Load & Count Discrepancy, these are counting at pickup and recording
  both the physical and BOL counts. This action mapping is static operational guidance.
5. **Match the next shipment.** Before handling, use available shipment context to look up the
  relevant historical signal. The existing watch lookup makes no new model call. V1's
  proposed operational handoff also checks that the shipment is at the right stage for the action.
6. **Present and execute.** Show the action where the employee can perform it. A supervisor
  approves any mandatory verification or release rule. The employee records the real result;
  AI advice alone neither performs the check nor authorises movement.

The current watch list measures the **share of a root cause among classified OVs**, compared
with the network's classified OV mix. It is not an OV rate over all shipments or a prediction
that a particular shipment will become an OV. No matching pattern means insufficient specific
guidance, not a guarantee that the shipment is safe; ordinary checks still apply.

The existing generated recommendation is optional context for a watch signal. Its scope
must be reviewed before applying it to a shipment; V1 must not imply that every stored
recommendation is already precisely matched to the shipper, stage and current load.

#### What a prevention recommendation must contain

This is the proposed **operational instruction**, not a claim that all fields are already
stored in the current recommendation table.

| Field | Example for count verification |
|---|---|
| Root cause | Shipper Load & Count Discrepancy |
| Pattern and evidence | Repeated BOL/physical-count differences in the selected history; supporting OV IDs and time window |
| Applicability | Relevant shipper or supported lane/terminal/commodity scope; identify the source of the match |
| When and where | At pickup before acceptance, or receiving before staging; staging is the current POC checkpoint |
| Responsible employee | Pickup driver or receiving clerk; supervisor handles unresolved discrepancies |
| Presentation point | Pickup/receiving workflow; use the RootIQ Staging check screen for the existing quantity demonstration |
| Action | Compare BOL pieces with the physical count; record both; recount and verify any difference |
| Decision rule | Confirm the correct shipment and reconcile the discrepancy before the next handoff under the approved SOP |
| Evidence of completion | PRO, checkpoint, declared/actual quantity, employee, time, correction and unresolved issue |
| Expected outcome | Extra or wrongly associated freight is identified before it travels as unaccounted-for freight |

Each recommendation stores: `category`, `scope` (terminal / commodity / time window),
`recommendation_text`, `pattern_addressed`, and `supporting_exception_ids` so every
recommendation is traceable back to the exceptions that justify it.

Recommendation status: `active` → `effective` | `ineffective` | `superseded`, plus an
`escalation_level` and a `superseded_by_id` link (see Step 9). These are POC measurement
states, not an implemented employee assignment/approval/release workflow.

---

### Step 8 — Prevent at the point of work (three tiers)

| Capability | Timing | Existing business role |
|---|---|---|
| What to watch | Before handling, when requested | Supervisor reviews concentrated historical causes and floor actions on Attention & Training |
| Notes Assist | During investigation after discovery | Helps note quality and future learning; does not prevent the OV already being logged |
| Staging check | Before staging, when the worker submits the check | Compares a manually entered count with the expected-shipment reference and records follow-up |
| Attention flags | On-demand scan of recurring issues | Supervisor acknowledges/resolves repeat-issue flags and reviews supporting cases |

> **Design rule:** Tier 1 must **not** appear on the exception log form. By the time an
> exception is logged the overage has already happened; the watch list is a pre-handling,
> supervisor-facing signal.

#### Input factors and data availability

The following factors inform the V1 prevention design. Missing data is unknown, not a
passed check. Historical exception fields must not be mistaken for live receiving inputs.

| Factor | Check and relevance to OV | Availability in the current POC |
|---|---|---|
| Piece count | Compare physical pieces with the BOL/manifest count using the same unit, not cartons versus pallets | Expected-count reference and manual quantity-check workflow exist; no live manifest feed |
| Weight | Compare declared and measured weight in the same units with known tare and approved tolerance; investigate unexpected freight or bad information | One exception weight field exists; paired weight readings and a verification workflow do not |
| Dimensions | Compare declared and actual length, width and height for the same handling unit; check whether units or loads were mixed | Structured dimension readings and a verification workflow are not implemented |
| Shipment/BOL details | Check PRO, shipper, consignee, quantity and destination before acceptance | Investigation captures these concerns; no live document-completeness gate |
| Scan history | Check required checkpoint events and PRO mapping; distinguish a duplicate event from an additional piece | Missing/mismatched scans can be described in notes; there is no live scan-event feed or duplicate-event rule |
| Labels | Match a readable physical label to the verified shipment; re-label only after identity is established | Labeling root cause and playbook exist; no label-reader validation workflow |
| Origin and destination | Compare the planned lane and destination against the proposed trailer/door | Lane/origin-based history exists; current watch "terminal" means origin, not a separate found-at terminal |
| Shipper history | Identify repeated OV mechanisms for the same shipper, supported by actual historical cases | Shipper names are stored on exceptions; shipper-cohort watch matching is not implemented |
| Historical patterns | Find repeat categories in similar freight and retain the supporting cases | Existing terminal, lane, commodity and package-type cohorts; not a trained predictive model |
| Loading/unloading | Reconcile the freight, PRO, bay, trailer and checkpoint event at each handoff | Trailer/bay details and playbook actions exist; there is no live loading/unloading event integration |

Weight and dimension differences are **verification signals, not new V1 taxonomy values**.
They do not by themselves prove extra freight or establish an OV. Where the investigation
supports it, the existing classifier may identify documentation, shipment-count, mixing or
another existing cause. Do not force every weight/dimension discrepancy into one category.

#### Root cause to prevention matrix

This is the proposed V1 business mapping. Existing playbook advice supports the 12 categories;
the detailed checkpoint checks and external application controls are not all implemented.

| Root cause or signal | When and where | Preventive action before the next handoff | Responsible role |
|---|---|---|---|
| Shipper Load & Count Discrepancy / piece-count difference | Pickup before acceptance; receiving before staging | Compare physical and BOL counts; recount; verify identity of surplus pieces; reconcile with the shipper/authorised owner | Driver or receiving clerk; supervisor for unresolved cases |
| Weight discrepancy (signal) | Receiving/weighing before loading | Verify units, tare and scale reading; reweigh; investigate the declared/actual difference and correct authorised shipment information | Receiving/weighing operator |
| Dimension discrepancy (signal) | Receiving/measurement before the next move | Measure the correct handling unit; verify units and orientation; resolve incorrect records or a mixed load | Receiving/measurement operator |
| Labeling Error | Pickup/receiving before a piece separates from its shipment | Match readable labels and PRO; establish identity before applying an authorised replacement label | Driver or receiving clerk |
| Missed Scan | Each required scan checkpoint before its movement completes | Verify the checkpoint event; rescan when physically verified and permitted; escalate a missing/unavailable event | Checkpoint operator |
| Data Entry / Scan Mismatch | Scanning before accepting the scan-to-shipment association | Compare physical PRO with the selected shipment; correct the association; do not count a duplicate scan as another piece | Scanner operator |
| Documentation Errors | Pickup/receiving before acceptance or handoff | Validate required BOL/shipment details; obtain corrected documents from the authorised owner | Driver or receiving clerk |
| Misrouting | Outbound loading before loading/departure | Match destination, PRO, load plan and trailer/door; route the freight to the correct assignment | Loader or dispatch |
| Load Swap / Co-mingled Shipment | Unloading/staging and again at loading | Segregate shipments; reconcile each piece with the bay tag and PRO before loading | Dock worker |
| Improper Packaging | Receiving and before loading | Inspect wrap/banding; secure loose pieces and rewrap/reband under the approved handling procedure | Receiving clerk or dock worker |
| Handling Damage | Immediately after a move, before the next handoff | Inspect compromised freight and retain piece identity; use approved repack/rehandling procedure | Dock worker; supervisor when needed |
| Carrier Error | Interline transfer before acceptance | Reconcile received pieces and labels with transfer documents; confirm discrepancies with the partner | Transfer clerk |
| Consignee Issue | Dispatch and any return-to-terminal handoff | Verify appointment/address and maintain shipment identity on refused/returned freight | Dispatch or delivery operations |
| Other / insufficient evidence | Receiving or handoff | Perform normal identification/document checks and request supervisor review; do not invent a cause-specific instruction | Receiving clerk and supervisor |

Only OV prevention is in scope. Handling damage or a consignee issue is included here as
an existing cause of an OV, not as a new damage/refusal exception module. Controls can
reduce unidentified or surplus freight; they cannot guarantee that every OV is avoided.

#### Where the recommendation appears

Operational application names and ownership must be confirmed with Saia. The targets below
describe functions, not integrations already delivered or claims about a particular product.

| Process point | Employee-facing delivery target | V1 POC representation |
|---|---|---|
| Before pickup/shift | Pickup planning or supervisor briefing | RootIQ Attention & Training: What to watch |
| Pickup/receiving count check | Driver pickup or receiving/handheld workflow | RootIQ Staging check demonstrates the expected-versus-actual quantity interaction; pickup/receiving embedding is proposed |
| Weighing and dimension capture | Scale/measurement station or receiving application | Business walkthrough with labelled sample readings; no working verification screen yet |
| Checkpoint scan/label check | Scanner workflow at that checkpoint | Playbook recommendation; live alert/scan validation requires an event interface |
| Loading | Loading scanner, load plan or dispatch workflow | Playbook recommendation; trailer/door release gate is not connected |
| Repeated unresolved issue | Supervisor work queue and operating review | RootIQ attention flags and recommendation evidence |

The dashboard is the **planning and evidence view**, not the physical control point.
For a POC, a supervisor can use the watch list at a pre-shift briefing and direct workers
to the standalone check screen. For normal operations, the recommendation must be delivered
in the application used at the handoff or in an explicitly owned manual SOP. An operational
hold is enforced by that process/application, not merely by displaying a RootIQ message.

#### V1 end-to-end workflow

The historical learning loop and the new-shipment loop are separate:

```text
Past OV -> Root cause -> Repeat pattern -> Relevant preventive control
```

```text
New shipment / BOL recorded (no OV exception)
  -> Pickup or receiving: identify PRO and applicable watch signal
  -> Count / scan / weight / dimension checks for that stage
  -> Compare evidence with expected values and approved rules
  -> Show the relevant prevention instruction before the next move
  -> Employee verifies and corrects, or escalates the discrepancy
  -> Authorised handoff; continue only under the approved SOP
  -> Record the action and follow up for any later OV
```

A watch signal can request extra attention **before** measurement; an actual discrepancy
triggers verification even when there is no historical pattern. A loading action should
not be delayed until the exception form, and a pickup action should not first appear
after the freight has departed.

| Verification result | Business response | What the current quantity POC does |
|---|---|---|
| Values agree | Record the check and follow the normal handoff; this is not a counted prevention by itself | Stores `match` |
| Values differ | Recount/recheck while freight remains controlled; do not silently change records to make them agree | Stores `mismatch_pending`; offers recount or confirmation |
| Physical or entry error corrected | Record the true final quantity and the correction; confirm the authorised handoff conditions | Stores `mismatch_corrected`; does not enforce equality with expected quantity or an external release gate |
| Difference is genuine and unresolved | Refer to the supervisor/shipper; apply the existing OS&D policy where required | Stores `mismatch_confirmed` with a reason; does not authorise release or automatically create a review task |
| No expected shipment reference | Verify PRO and obtain the manifest/BOL; report unknown, not passed | Returns `no_expected_record`; no prevention-check row is stored |

Each stored check includes a snapshot of the historical watch signal and starts with a
pending follow-up outcome. Follow-up on an already resolved check is rejected. A real
operational release must not be inferred from the POC's saved recount or confirmation.

#### Client example: piece count

**Illustrative business scenario, not measured production results.** Use a synthetic
shipper, separate historical PROs and a new demonstration PRO. A same-shipper pattern is
part of the target story; the existing watch list can demonstrate terminal/commodity or
lane concentration, not automatic shipper-specific matching.

1. **Historical OV.** An earlier investigation says: "BOL showed 12 cartons. Fourteen
  matching cartons arrived. The shipper confirmed two extra cartons were tendered."
  The existing classifier can identify **Shipper Load & Count Discrepancy**, with
  quantity/documentation evidence and reasoning. The analyst verifies the result.
2. **Historical pattern.** The analyst reviews several similar OVs from the illustrative
  shipper. The system's supported cohort view supplies category concentration and supporting
  cases; do not present a manually assembled shipper example as an implemented shipper model.
3. **Selected control.** The recommendation is: "At pickup or receiving, compare the
  physical piece count with the BOL. Verify any difference before the shipment proceeds."
  The playbook explains why counting at the source interrupts the recurring failure.
4. **New shipment, no OV yet.** The new BOL declares 12 cartons. At pickup the employee
  counts 14. The pickup/receiving process displays the instruction, or the POC presenter
  uses the standalone quantity screen at its supported pre-staging checkpoint.
5. **Employee intervention.** Recount confirms 14. The employee verifies the labels and
  contacts the shipper/supervisor. Under the approved procedure, the shipper retains the
  two surplus cartons before acceptance and they are kept separate from this shipment.
  Alternatively, the authorised owner can correct the shipment documents when all 14
  should travel. That document-change path is not implemented by the quantity screen.
6. **Verified handoff.** In the retained-carton branch, 12 cartons now physically leave
  against the BOL count of 12. Record the true recount and retain the operational reason
  and approval in the responsible process. Do not type 12 while 14 still travel.
7. **Expected outcome.** The destination receives the identified 12 cartons instead of
  two unexplained extra cartons. The failure mechanism was interrupted before an OV
  was created for the new shipment; the historical OV remains in the learning data.
8. **Follow-up.** Record the intervention and monitor later OV records for the new PRO.
  Demonstrate "discrepancy detected and corrected" immediately, not "proven OV prevented".

For the **existing screen demonstration**, a miscount branch is also supported: enter 14
against an expected 12, recount and find that two cartons were counted twice, then file the
true recount of 12. If 14 genuinely belong to the shipment and cannot be reconciled, choose
**Confirm discrepancy**, record the reason and follow the normal operational escalation.
Confirmation is not prevention and must not be presented as clearance to load.

#### Client examples: weight and dimensions

**Weight, proposed receiving check.** A synthetic BOL declares 1,000 lb but the receiving
scale reads 1,150 lb. First verify that the readings use the same units and tare basis,
then reweigh. If the difference exceeds the business-approved tolerance, verify piece
identity and shipment information before loading. Extra freight is segregated or incorrect
data is corrected by its authorised owner. The intended outcome is reconciled freight and
records before handoff, not an automatic "Weight Discrepancy" root-cause classification.

**Dimensions, proposed measurement check.** A synthetic handling unit is declared as
48 x 40 x 48 inches but measures 48 x 40 x 60 inches. Verify the same unit, orientation,
packaging and measurement basis. If the approved tolerance is exceeded, check for mixed
freight or incorrect shipment details and resolve them before the next move. A size
difference alone is not evidence of an OV; the expected result is verified unit identity
and accurate shipment information. This is not a working dimension-check feature today.

Tolerance values, units, measuring equipment and who may approve a correction must be
agreed by operations. The examples do not establish production thresholds.

**Attention flags (tier 3)**

- Scoped to a **terminal** or a **handler** and a specific category.
- Raised when the count breaches a threshold over a configurable number of consecutive periods.
- Carries severity (`watch` / `high`), period counts, pattern summary, suggested supervisor
  action and supporting exception IDs.
- Workflow: `open` → `acknowledged` → `resolved`, each with actor and timestamp, plus a
  resolution note. Evidence is viewable per flag.

---

### Step 9 — Measure whether prevention worked

**Screen:** `Attention & Training` → "Are the prevention actions working?"

**Existing POC behavior**

1. The user triggers evaluation; no scheduled monitoring or automatic client notification
  is currently provided.
2. The recommendation evaluator compares category/scope **exception counts** before and
  after the recommendation's generated date, with a default 30-day window. It does not
  track when an employee actually implemented the action or divide by shipment volume.
3. Check outcomes are marked `recurred` if a later OV is found for the same PRO, or
  `prevented` after the waiting period if none is found. The current lookup does not cap
  the later OV search at the end of the observation window, and applies to pending checks
  regardless of whether the result was a match, correction or confirmed discrepancy.
4. Recommendation evaluation considers count improvement and resolved-check results. It
  can mark a recommendation effective or ineffective and generate an escalated replacement.
5. At the escalation ceiling (default 2), it can raise an attention flag when the
  recommendation has a terminal scope. Lineage links the generated replacements.

**V1 business interpretation**

The stored label `prevented` is a simplified POC outcome, **not proof of a prevented OV**.
Do not present every matched check or confirmed discrepancy without a later record as
a successful intervention. A record may also be absent because follow-up data is incomplete.

| Evidence level | What the client can conclude |
|---|---|
| Instruction displayed | The employee was given a relevant action at the intended checkpoint |
| Check completed | Expected and actual observations were compared; a matching check alone is not prevention |
| Discrepancy corrected before handoff | A documented operational intervention interrupted an identified failure mechanism |
| No later OV observed for the PRO | No recurrence was found in the stated observation period and available data; not a causal guarantee |
| Similar cases continue to occur | Review action execution, data quality and the operating procedure; consider supervisor escalation |

For the V1 demonstration, show the check, original values, real correction, actor and
timestamp, then describe the **expected** outcome. Keep the correction reason and release
approval in the responsible operational process where the current POC lacks those fields.
Follow-up should state the observation dates and data coverage. Do not claim shipment-level
OV-rate improvement, savings or causal impact from the current count-based evaluator.

---

### Step 10 — Load data

| Path | Purpose |
|---|---|
| Synthetic seed | The existing default demo recipe provides 80 exceptions, 8 duplicate inputs and 26 hand-labelled examples. These are fixture settings, not claims about the current database or achieved accuracy. Expected-shipment reference data supports the quantity demonstration. |
| OS&D export import | The existing CLI can load the supplied export folder. Confirm data-use approval and anonymisation before using real examples in a client demo or sending notes to a hosted model. |

Use a **new, valid PRO with an expected-shipment record** for the prevention demonstration,
separate from the already-created historical OV. Select a known reference count and adapt
the illustrative 12-versus-14 numbers if necessary. Do not invent a successful reference
lookup or create an OV simply to run a prevention check. Clearly label synthetic shipper
history and the proposed weight/dimension readings.

### Client demonstration and acceptance

The demonstration has a working POC path and a clearly labelled operational walkthrough.
Passing the walkthrough is not evidence that its proposed integrations are implemented.

| Step | Presenter action | Evidence or acceptance condition |
|---|---|---|
| 1. Explain the past OV | Open an existing quantity-related OV and its classification | Category, investigation reasoning and confidence explain the original incident; the classifier is unchanged |
| 2. Show repeat evidence | Open the dashboard and relevant What to watch scope | Explain category count/share and supporting cases; distinguish a supported cohort from the illustrative shipper story |
| 3. Explain the action | Show the generated recommendation and corresponding floor action | The count check directly addresses the identified mechanism; name pickup/receiving and the pre-staging demo checkpoint |
| 4. Identify the employee and screen | Walk through pickup/receiving responsibility and open Staging check | The clerk/worker receives the instruction before the next handoff; no risk prompt is placed on Log exception |
| 5. Check a new shipment | Enter a referenced PRO, terminal, physical quantity and employee | A mismatch shows the expected/actual values and offers follow-up without creating an OV |
| 6. Demonstrate resolution | File a truthful corrected count in the recount branch | A correction is stored; do not claim the app itself verified physical equality or released a real trailer |
| 7. Demonstrate unresolved and unknown cases | Use separate checks for a genuine mismatch and a missing reference | A confirmed mismatch follows the SOP; an unknown reference is not a pass; neither is counted as proven prevention |
| 8. Walk through other stages | Use labelled weight/dimension examples and the label/scan/loading matrix | Each instruction has a stage, responsible role, data source and decision rule; unbuilt integrations are identified |
| 9. Close the loop | Show the recorded check and explain follow-up/effectiveness | Distinguish expected outcome, observed recurrence and causal proof; no unsupported probability or savings claim |

Client acceptance should answer: **What problem are we addressing? Why this shipment?
Who acts? At which stage and in which screen? What must they do? What evidence permits
the next handoff? What was observed afterward?**

---

## 5. Business rules summary

| ID | Rule |
|---|---|
| BR-01 | Only Overage (OV) exceptions are handled. |
| BR-02 | PRO number must be 12 digits and pass check-digit validation. |
| BR-03 | `dollar_amount` is required when `value_range = 3`. |
| BR-04 | Classification history is append-only; nothing is ever overwritten, including overrides. |
| BR-05 | A cache hit must not trigger a model call. |
| BR-06 | Classifier failures use `Other` / `0.0` / `needs_review = true`. New recommendation generation and AI-dependent escalation can still report model errors. |
| BR-07 | The category must always be one of the 12 taxonomy values. |
| BR-08 | Clearing codes must come from the lookup table, not free text. |
| BR-09 | Clearing an exception must not alter classification data. |
| BR-10 | `training_signal` is system-computed and overrides the model's value. |
| BR-11 | Recommendations must store their supporting exception IDs (traceability to evidence). |
| BR-12 | Tier-1 risk signals must not appear on the exception log form. |
| BR-13 | A resolved staging check cannot be modified further. |
| BR-14 | Escalation stops at the ceiling and converts into an attention flag. |
| BR-15 | AI output is advisory and must be reviewable/overridable by an analyst. |

**V1 prevention requirements (operational design, not additional delivered features)**

| ID | Rule |
|---|---|
| PV-01 | Apply the lessons of historical OVs to a new shipment before its next relevant handoff; never describe the already-created historical exception as prevented. |
| PV-02 | Every operational recommendation identifies the cause/pattern, evidence, applicable scope, checkpoint, responsible role, action and condition for proceeding. |
| PV-03 | AI explains the pattern; business-approved procedures determine mandatory checks, tolerances and release authority. |
| PV-04 | Count, weight and dimensions must compare like-for-like units and the same shipment/handling unit; missing reference data is unknown, not passed. |
| PV-05 | Weight and dimension differences remain verification signals; V1 retains the 12 existing root-cause categories. |
| PV-06 | A real discrepancy requires verification even without a historical watch signal. Lack of a pattern does not waive routine checks. |
| PV-07 | Save true observations. Do not change a count or shipment record solely to make a mismatch disappear; only the authorised owner may correct source information. |
| PV-08 | An unresolved discrepancy follows the existing OS&D procedure, including creating an OV when required. Prevention never means suppressing a required exception. |
| PV-09 | A stored confirmation, recount or recommendation does not by itself authorise freight movement; the owning process controls the handoff. |
| PV-10 | Link the performed action to the PRO, stage, operator, timestamp and available supporting evidence; distinguish requested, performed, corrected and observed outcomes. |
| PV-11 | Synthetic examples and proposed integrations must be explicitly labelled. Do not present category concentration as a shipment probability. |
| PV-12 | Notes Assist remains investigation support; preventive advice belongs at pickup, receiving, scanning, measurement, staging or loading as appropriate. |

---

## 6. Data model (as built)

| Entity | Purpose |
|---|---|
| `ov_exceptions` | The OV exception master record, status, clearing code, content hash, optional hand label. |
| `ov_investigations` | One per exception: the Y/N + notes steps and the combined notes text. |
| `root_cause_classifications` | Append-only classification events (`ai_fresh` / `cache_hit` / `human_override`). |
| `classification_cache` | One row per unique content hash: result, hit count, last hit. |
| `clearing_codes` | The 15-code reference lookup, synced on startup. |
| `recommendations` | Generated prevention actions, scope, evidence IDs, status, escalation lineage. |
| `attention_flags` | Repeat-issue signals per terminal/handler + category, with the supervisor workflow. |
| `expected_shipments` | POC stand-in for the manifest/OD400 expected piece count. |
| `prevention_checks` | Point-of-process checks, verification result, quantities, outcome, risk snapshot. |

Enums are stored as portable `VARCHAR + CHECK` so the schema runs on both Postgres and SQLite.

---

## 7. Interfaces (API surface)

**Meta** — `GET /health` (reports model host/model and reachability).

**Reference** — `GET /investigation-questions`, `/commodities`, `/terminals`,
`/pro-number/suggest`, `/clearing-codes`.

**Exceptions** — `POST /ov-exceptions`, `GET /ov-exceptions` (filterable),
`GET /ov-exceptions/{id}`, `POST /ov-exceptions/{id}/investigation`,
`POST /ov-exceptions/{id}/clear`.

**Classification** — `GET /classify/taxonomy`, `POST /classify/batch`, `POST /classify/{id}`,
`GET /classify/{id}/history`, `POST /classify/{id}/override`.

**Insights** — `GET /insights/distribution`, `/cache-stats`, `/accuracy`, `/filters`,
`/recommendations`, `POST /insights/recommendations/generate`,
`GET /insights/recommendations/{id}/evidence`.

**Prevention** — `POST /prevention/watch`, `POST /prevention/notes-assist`,
`POST /prevention/staging-check/quantity-verify` (+ `/{id}/correct`, `/{id}/confirm`),
`POST /prevention/recommendations/evaluate`, `GET /prevention/recommendations/{id}/lineage`,
`GET /prevention/attention`, `POST /prevention/attention/scan`,
`GET /prevention/attention/{id}` (+ `/evidence`), `POST /prevention/attention/{id}/acknowledge`,
`POST /prevention/attention/{id}/resolve`.

---

## 8. Non-functional requirements

| Area | Existing behavior and V1 constraint |
|---|---|
| Availability of AI | Classification has a fallback; watch lookup and quantity checks do not call the model. Fresh recommendations and AI-dependent escalation can fail and must not be presented as available offline. |
| Consistency | `temperature = 0` and JSON-constrained output reduce variation; they do not guarantee identical answers across models or versions. |
| Cost control | Exact-match caching eliminates repeat model calls; aggregation (not raw notes) is sent for recommendations. |
| Auditability | Every classification event is retained with source, model used, confidence and timestamp. |
| Portability | Runs on Postgres (target) or SQLite; LLM can be hosted Ollama Cloud or a local daemon. |
| Testability | Automated test suite runs with the model mocked — no live LLM required. |
| Privacy | Use synthetic or approved anonymised demo data. Obtain appropriate approval before exposing real notes or customer information to a hosted model. |
| Transparency | Classification exposes reasoning, confidence and review controls; recommendations link to evidence. Distinguish AI-generated wording from the static operational playbook. |
| Operational ownership | Agree the screen, employee and release authority for each checkpoint. The current POC has no cross-application hold/release enforcement or role-based access control. |

---

## 9. Success criteria (POC)

| Criterion | V1 acceptance | Evidence |
|---|---|---|
| Existing foundation retained | Keep the implemented classifier, taxonomy, cache and analyst review | Existing classification, history and accuracy/cache views; no new accuracy claim in this document |
| Root cause to action | Explain a practical count control using historical OV evidence | Count scenario, generated advice and playbook mapping |
| Correct time and place | Name a preventive checkpoint for every mapped category/signal | Root-cause matrix and process-screen mapping |
| Action before an OV | Demonstrate an expected/actual quantity mismatch and truthful follow-up on a new shipment | Standalone Staging check and recorded result; no OV creation by that check |
| Honest exceptions | Explain the genuine-mismatch and missing-reference paths | Operational escalation walkthrough; neither treated as a successful prevention |
| Accountable business process | Identify the performing employee and authority for the next handoff | Client agreement on the relevant SOP and operational application |
| Evidence and outcome | Distinguish correction, expected outcome and later observed recurrence | Recorded action, supporting cases and labelled observation window |
| Clear implementation boundary | Client can distinguish working POC screens from proposed receiving, weight, dimension and scan integrations | Demonstration labels and the V1 scope table |

---

## 10. V1 decisions and deferred work

### Decisions to confirm with operations

| Decision | Required agreement |
|---|---|
| Count ownership | Who verifies at pickup and receiving, including sealed or inaccessible shipper-load-and-count freight, and who contacts the shipper? |
| Presentation point | Which driver, receiving, scanner, measurement and loading applications are actually used, and who owns the temporary manual SOP? |
| Source of truth | Which BOL/manifest provides expected values, who may revise it, and how is the correct PRO/handling unit confirmed? |
| Verification standards | What count units, weight/tare basis, dimension basis and tolerances apply? What happens when measurements or references are unavailable? |
| Escalation and movement | Who decides the next handoff for a genuine discrepancy, and when must the normal OS&D exception process begin? |
| Historical applicability | Is a reliable shipper identifier available? Which origin/lane/commodity scope should be used until shipper matching is implemented? |
| Evidence and follow-up | Where are reasons and approvals recorded, what observation period is used, and how complete are later OV records? |
| Client demonstration data | Which synthetic or approved anonymised history and expected-shipment references may be used? |

### Implementation work not delivered by this document

- Embedding recommendations into pickup/receiving, measurement, scanner or load-plan applications.
- Shipper-specific cohort matching and structured weight/dimension verification.
- Live BOL/manifest and scan-event inputs, including required checkpoints and duplicate-scan rules.
- Enforced handoff approval, source-document correction and complete operational action auditing.
- Stricter reconciliation and outcome rules before the POC's saved recounts or `prevented` labels
  can be used as production business controls or performance measures.

These are explicit gaps between the current software and the proposed operating process,
not claims that the requirements are already implemented. The existing quantity workflow
is the concrete V1 demonstration; other checkpoints are a labelled business walkthrough
until their delivery scope and operational owners are agreed.

### Deferred beyond this V1 discussion

Additional exception types, classifier redesign, trained risk models, semantic deduplication,
cost-avoided claims, multi-application rollout and production-scale scheduled automation are
not added by this revision. Authentication/RBAC, production integrations and security/data
approval remain deployment prerequisites. Attention scans and effectiveness evaluation
remain on demand in the current application.
