# Anchor Semantics — qa_v6 Pipeline Doctrine

Single source of truth for how anchor terms are interpreted in routing and
retrieval. If this document and the code disagree, the code wins — but
don't let that happen. Update both.

## The doctrine in one sentence

**Anchor terms are evaluated in combination, never in isolation. Pinpoint
anchors act as a conjunctive AND-gate. Global anchors are tiebreakers only,
and only when paired with a pinpoint anchor or a value/range.**

## Anchor tiers

Every anchor term in `guideline_anchor_words.json` is classified as one of
four tiers. Only two matter at runtime:

| Tier       | Role                                         | Runtime weight |
|------------|----------------------------------------------|----------------|
| `pinpoint` | Discriminating clinical concept              | AND-gate       |
| `narrow`   | Treated as pinpoint                          | AND-gate       |
| `broad`    | Treated as pinpoint                          | AND-gate       |
| `global`   | Generic AIS term (stroke, IVT, AIS, TPA...)  | Tiebreaker     |

Terms not found in the tier map default to **pinpoint** — novel clinical
terms cannot be assumed to be global.

`GLOBAL_ANCHOR_TERMS` in [`scoring_config.py`](../scoring_config.py) is
the authoritative set of global anchors. Additions go there.

## Rule 1 — Pinpoint anchors are a conjunctive AND-gate

If the parser extracts any pinpoint anchors from the query, every eligible
atom must contain **all** of them in its `anchor_terms`. Missing even one
pinpoint anchor forces `score = 0`, which drops the atom below
`SCORE_THRESHOLD` and removes it from every downstream decision.

Rationale: a bedside clinician asking "what imaging do I need for stroke"
is asking about **imaging** in the context of **stroke**. A rec about
hospital organization (§2.9) that mentions "stroke" but not "imaging" is
not a partial answer — it is a different answer to a different question.
Partial match is not partial answer.

Enforced in [`retrieval._score_atom`](../retrieval.py) (the scoring
function). The gate runs before any score component is computed.

## Rule 2 — Global anchors count only WITH pinpoint or value signal

Global anchors (stroke, IVT, AIS, thrombolysis, alteplase, tenecteplase,
TPA, EVT, thrombectomy, endovascular thrombectomy, cerebral ischemia,
patient, patients) appear in nearly every AIS atom. Alone they cannot
discriminate — `stroke` trivially matches everything.

Global coverage contributes to the score **only** when the query also
brings:
- a pinpoint anchor (something to discriminate on), **or**
- an anchor value / range (a specific scenario to match against)

If the query is purely global, `global_cov` is silently zeroed. Semantic
similarity and intent affinity then drive ranking — anchor signal plays
no role.

Enforced in [`retrieval._score_atom`](../retrieval.py) immediately after
anchor coverage is computed.

## Rule 3 — Clarification clusters inherit the gate

The ambiguity detector in `retrieval._build_recs` clusters recommendations
that cleared `SCORE_THRESHOLD` and fall within `REC_TIGHT_BAND` of the
top score. Because Rule 1 gated every scored atom upstream, every rec in
a clarification cluster necessarily shares the full pinpoint anchor set
with the query and with each other.

Result: clarification options are always topically coherent — they
differ in **category**, not in **subject**. A clarification prompt never
mixes imaging recs with organization recs; it might mix "general brain
imaging" with "EVT advanced imaging" (both genuinely under §3.2).

## Rule 4 — Scope follows the user, not the query embedding

When the user replies to a clarification menu by clicking an option,
retrieval runs with `is_clarification_reply=True`. The ambiguity detector
is suppressed on reply turns: the user has already narrowed scope.
Re-triggering the menu would create a loop.

Enforced in [`retrieval.retrieve`](../retrieval.py) via the
`is_clarification_reply` parameter, passed by
[`orchestrator.run`](../orchestrator.py).

## Where each rule is enforced

| Rule | Component | Function |
|------|-----------|----------|
| 1. Pinpoint AND-gate       | retrieval.py   | `_score_atom` (early return on missing pinpoint) |
| 2. Global-only-with-others | retrieval.py   | `_score_atom` (zero `global_cov` when no pinpoint and no values) |
| 3. Cluster coherence       | retrieval.py   | `_build_recs` (inherits from Rule 1) |
| 4. Reply scope-lock        | orchestrator.py → retrieval.py | `is_clarification_reply` parameter |

## What the doctrine does NOT do

- It does not replace semantic similarity. Semantic is still the primary
  signal (`W_SEMANTIC = 0.40`). The gate simply removes atoms that are
  semantically close but topically wrong.
- It does not require every clinical term the clinician mentioned to be
  in the guideline vocabulary. Unknown terms default to pinpoint and
  gate accordingly — if the atom doesn't have the term, the atom is out.
- It does not replace value-based matching (CMI). Patient-scenario
  queries still route through `recommendation_matcher` for tiered
  matching; the anchor gate only affects which atoms the retrieval
  surface returns.

## Change log

- **2026-04-17** — Pinpoint AND-gate added; global-only-with-others
  added; documented. Previously, atoms scoring high on semantic alone
  (with a single shared global anchor like "stroke") could cluster
  into clarification menus with unrelated sections, creating noise.
