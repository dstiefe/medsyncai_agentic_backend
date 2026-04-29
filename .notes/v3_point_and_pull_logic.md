# Point Logic and Pull Logic — Design of Record

**Source:** 8-hour design conversation 2026-04-10/11. This file is the grounded reference. If a later message contradicts it, update this file first, then code.

---

## Two-stage split

The Q&A pipeline is split into **point logic** (routing) and **pull logic** (retrieval). They are separate stages with different responsibilities, different inputs, and different outputs. Never collapse them.

- **Point logic returns a section (or sections).** Nothing more. It does not return rec text, RSS text, or KG text.
- **Pull logic NEVER returns a whole section.** It narrows to the specific recs (by recNumber) and the specific synopsis / KG paragraphs that actually answer the question.

Rule of thumb: if the router hands downstream "all 14 recs of §4.6.1", the system is broken. That was v1's failure mode and the user called it out explicitly ("You're making the same garbage system as v1").

---

## Point logic — section routing

### Inputs
- User question
- LLM parser output (intent, canonical anchors, required slots) from the 4 scaffolding files:
  `data_dictionary.json`, `synonym_dictionary.json`, `intent_map.json`, `ais_guideline_section_map.json`
- Section metadata: rec text + RSS + KG per section

### Candidate set
Union of sections referenced by each canonical anchor's `sections` list in `synonym_dictionary.json`, plus any section whose `routing_keywords` in `ais_guideline_section_map.json` match an anchor. No generic English words — only canonical anchors count as routing signal.

### Scoring rule (anchor count cross-checks intent)
```
total_score = anchor_score + scope_bonus + intent_bonus
```
- **anchor_score** = count of *distinct canonical anchors* from the question that appear in the section's rec/RSS/KG text. Synonyms of the same canonical term_id collapse to 1. (See "Dedup rule" below — unresolved edge case.)
- **scope_bonus** = +2 if any anchor is a scoped field in this section per `data_dictionary.json`. Prevents overview sections from winning on raw anchor count.
- **intent_bonus** = +2 if this section is in `intent_map.json`'s mapping for the classified intent.

Weights are tunable; not sacred.

### Why anchor count is a cross-check, not a replacement
User (04:55): *"A section that matches 3 anchor words is probably more appropriate than a section that matches one anchor word."*
- When intent is right and anchors agree → high confidence.
- When intent is wrong → anchor count alone can still pick the right section (catches parser mistakes).
- When anchors are thin → intent_bonus is the tiebreaker.

This is NOT the v1 keyword counter. v1 counted generic words ("oxygen", "stroke", "patient"). Point logic counts only canonical anchors from the closed-vocab scaffolding. Different signal entirely.

### Tiebreaker
When two sections have the same `total_score`, the section where the most anchors **co-occur in a single rec** wins. If still tied, `intent_bonus` decides. If still tied, → clarification.

### Hard rules from the user
- **No generic words.** User (04:42): *"why would we match generic terms at all."*
- **Context-dependent anchors.** User (04:43): *"oxygen may be an anchor it depends on the context of the question."* → Anchors are only counted when they're canonical in the vocab AND present in the question. A word being in the vocab doesn't mean it's always an anchor; it must come through the parser.
- **No manual overrides.** User (04:38): *"the system before was doing manual overrides for questions not fixing the system."* Never port v1's override list.
- **No regex on clinical prose.** Use token-boundary containment (non-alphanumeric flanking check).

### Output
One section number (winner), or a clarification signal when scoring is ambiguous.

---

## Pull logic — content retrieval

### Inputs
- Section(s) from point logic
- Canonical anchors from the parser
- Intent (drives content-source dispatch)

### Core principle
**Pull NEVER returns whole sections.** It returns:
- Specific recs (by recNumber) from `recommendations_store`
- Specific synopsis paragraphs (blank-line split)
- Specific KG paragraphs (blank-line split)

### Rec-level anchor survival filter
Keep a rec if it contains ≥1 distinct canonical anchor from the question. Rank survivors by:
1. Distinct anchor count (desc)
2. COR strength (Class I > IIa > IIb > III > III-no-benefit > III-harm) as tiebreaker

Implemented in `services/qa_v3_filter.py::filter_recs_by_anchor_survival`. Wired into `rec_selection_agent.py` as `_anchor_prefilter` before the LLM selector.

### Paragraph-level anchor survival filter (RSS + KG)
Split synopsis/KG on blank lines into paragraph units. Keep a paragraph if it contains ≥1 distinct anchor. Same ranking rule minus COR.

Implemented in `qa_v3_filter.py::filter_paragraphs_by_anchor_survival` and `qa_service.py::_split_rss_into_paragraphs` + `gather_section_content_v3`. **Not yet wired** into `rss_summary_agent.py` / `kg_summary_agent.py`.

### Safety fallbacks (don't turn empty survival into a dead end)
- Question yields 0 anchors → pass recs/paragraphs through unchanged (let LLM see everything, same as pre-v3 behavior).
- Filter drops 100% of recs/paragraphs → log warning, pass original list through unchanged. Empty survival is a **clarification trigger** in the future, not a crash site.

### Intent → content-source dispatcher
User (04:59): *"Intent also helps direct the system to either recommendations, RSS, KG or a combination of them."*

User (earlier): *"Why do we use MRI for extended window is RSS."* Rationale/evidence lives in RSS, not in rec statements.

Mapping (first draft, lives in `v2_deferred_decisions.md`):
- **recs-primary** (with optional RSS supplement): eligibility, exclusion, contraindications, indication, drug_choice, treatment_choice, sequencing, dose, route, duration, frequency, time_window, threshold_target, imaging_choice, monitoring, setting_of_care, class_of_recommendation, patient_eligibility, intervention_recommendation, etc. (~28 intents)
- **RSS-primary** (with top rec as citation): `rationale`, `evidence_retrieval`
- **KG-primary**: `knowledge_gap` (pending: add as 34th intent — **already confirmed by user**)
- **Mixed recs + RSS**: `risk_factor`
- **data_dictionary + RSS**: `definition`
- **No pull**: `out_of_scope` → return out-of-scope message

Supplementary items per top rec (1? 2? all surviving?) — pending decision.

### V2 cannot ignore RSS and KG
User (04:04): *"V2 CANNOT IGNORE RSS and KG."* Pull logic must make RSS and KG first-class content sources alongside recs.

---

## Dedup rule (UNRESOLVED — flag for user)

User (02:49): *"SBP and Blood pressure are the same if they are both matched that's not 2 they count as 1 match."*

Current implementation in `qa_v3_filter.py` treats each `term_id` in `synonym_dictionary.json` as independent canonical. SBP (`full_term="systolic blood pressure"`) and BP (`full_term="blood pressure"`) have separate term_ids, so text containing both "SBP" and "blood pressure" would count as 2 distinct anchors, not 1.

**Interpretation options (need user confirmation):**
1. SBP is a child of BP → merge into same canonical at count time
2. Add explicit parent-of relationship in synonym_dictionary.json
3. User meant something narrower (e.g., within a single term_id only — synonyms of BP like "blood pressure measurement" should dedup, but cross-term SBP/BP is fine as 2)

Until resolved, the T2 self-test in `qa_v3_filter.py` (which asserts `[BP, SBP]` = 2) encodes interpretation 3. Flagged for review.

---

## Clarification triggers (driven by anchors + intent, not templates)

User (04:something): *"We also need triggers for clarification. but use the intent or anchors to help build the clarification question."*

Five conditions:
1. **Zero anchors extracted** — parser returned nothing. Offer 3-5 options from `ais_guideline_section_map.json` top-level topics.
2. **Anchors vote for multiple unrelated sections** — tie/near-tie in point scoring. Use top-2 sections' topic strings as labels. Example: TNK + M2 → "Are you asking about IVT agent choice (§4.6.2) or EVT eligibility for medium vessels (§4.7.4)?"
3. **Required slots not filled** — e.g., `eligibility_criteria` intent with no `treatment_or_procedure`. Frame using intent_map's description + required_slots.
4. **Scope mismatch on high-confidence route** — winning section but scope check disagrees. Lean: proceed if `anchor_score ≥ 2` clear winner AND no scope conflict, otherwise clarify.
5. **All routing signals fail** — route to `out_of_scope` intent response.

Reply handling: reuse `_merge_clarification_reply` from commit 74da30b. Max 2 rounds, then best-effort with caveat.

---

## Reversibility requirement

User (earlier): *"I want an easy way to revert back to LLM first if the 'deterministic routing first, LLM fallback' doesn't work."*

Every deterministic stage (point scoring, rec filter, paragraph filter, intent dispatcher) must be behind a flag/env var so we can flip the whole pipeline back to LLM-first in one change. Not yet implemented — track as a requirement for Commits E-I.

---

## What's landed on dev (as of 2026-04-11 ~05:30 UTC)

- Commit A `d390cee` — `temperature=0` on all 4 LLM calls in `nlp_service.py`
- Commit B `f0e05b2` — `gather_section_content_v3()` + `_split_rss_into_paragraphs()` in `qa_service.py`
- Commit C `9cc9d78` — `services/qa_v3_filter.py` (AnchorVocab, rec/paragraph survival filters, 10/10 self-tests, 192 canonical anchors)
- Commit D `7f8e270` — `rec_selection_agent.py` wired with `_anchor_prefilter` + safety fallbacks, smoke test 3→1 on DWI-FLAIR+TNK

## What's still pending (commits E-I)

- **E** — Anchor-based section scoring in section router (the 3-anchor > 1-anchor rule, cross-checking intent)
- **F** — Wire paragraph filter into `rss_summary_agent.py` / `kg_summary_agent.py`
- **G** — Intent → content-source dispatcher in orchestrator
- **H** — Clarification triggers (5 conditions above)
- **I** — Verify `query_parsing_agent.py` consults all 4 scaffolding files
- **Dedup fix** — resolve SBP/BP interpretation with user, update `qa_v3_filter.py` accordingly
- **Reversibility flags** — env vars / config to flip each deterministic stage back to LLM-first
