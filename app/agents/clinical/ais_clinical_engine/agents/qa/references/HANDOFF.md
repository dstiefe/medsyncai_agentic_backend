# MedSync QA Reference Files — v2 Handoff

Handoff doc for Claude Code. Covers the v2 updates to `data_dictionary.json` and `synonym_dictionary.json` plus what still needs human/clinical review before merging.

## Files

- `data_dictionary.v2.json` — 46 sections, schema_version 2.0.0
- `synonym_dictionary.v2.json` — 157 terms + 6 preserved v1 inline comments, schema_version 2.0.0
- `transform_refs.py` — the idempotent Python script that produces v2 from v1. Re-run any time v1 is edited.
- `intent_catalog.json` — (from earlier in the session) the 28-intent catalog for the QAQueryParsingAgent
- `medsync_intent_routing_spec.md` — (from earlier) narrative explaining how intents drive retrieval

## Source paths in the repo

```
dstiefe/medsyncai_backend (branch: dev)
app/agents/clinical/ais_clinical_engine/agents/qa/references/
├── data_dictionary.json           ← replace with data_dictionary.v2.json
├── synonym_dictionary.json        ← replace with synonym_dictionary.v2.json
├── guideline_topic_map.json       ← unchanged
├── intent_map.json                ← DELETE (dead, not imported anywhere except a doc)
├── qa_query_parsing_schema.md     ← update to reference intent_catalog.json
├── topic_verification_schema.md
├── section_variable_matrix.json
└── ais_guideline_section_map.json
```

Python consumers that need updating:
- `query_parsing_agent.py` — expects data_dictionary.json and synonym_dictionary.json
- `section_router.py` — expects all three live files
- `topic_verification_agent.py` — expects guideline_topic_map.json

## High-level philosophy of v2

**Conservative migration.** All existing values are preserved. New structured fields are added alongside, not in place of, originals. This keeps v1 behavior stable and lets reviewers compare old and new side-by-side.

**Mechanical fixes only.** Anything that required reading the guideline source text to verify was flagged for human review, not silently changed. Specifically: suspected cross-section value leakage in 4.1 and 4.2 is flagged but the values are NOT deleted.

**High-confidence bug fixes are applied.** Synonym self-duplicates, the ICH↔HT collision, and stent-retriever brand mis-categorization are fixed in the file and logged in `bug_fixes[]` so the change is auditable.

---

## data_dictionary.v2.json — changes

### Schema changes (additive)

Every variable entry now has these new fields:
- `source_rec_ids: []` — empty; populate during review by tracing back to the specific recommendations in `guideline_knowledge.json`
- `synonym_term_ids: []` — populated for `intervention` variables where a high-confidence mapping to synonym_dictionary exists
- `parsed_values` — structured numeric representation for BP, SpO2, time_window, glucose, drug_dose, age, NIHSS variables
- `unlinked_values` — intervention values that couldn't be mapped to a synonym term ID (reviewer decides whether to add a synonym entry or fix the data_dictionary value)

The `type` field is normalized to a canonical v2 taxonomy:
```
categorical, threshold, range, time_window_hours, modality_enum, qualifier_enum,
dose, structured_doses, structured_thresholds, reperfusion_grade_enum,
systolic_bp_threshold, process_metric, volume_range_mL, mixed_needs_review
```

Sections with known or suspected data quality issues now carry a `review_flags` block:
```json
"review_flags": {
  "needs_review": true,
  "concern": "...",
  "review_variables": ["time_window", "vessel"]
}
```

The SectionRouter should treat these sections with lower confidence until the flags are resolved.

### parsed_values — what it buys you

Before (v1):
```json
"BP": {
  "values": {"pre_IVT": "185/110 mmHg"},
  "type": "structured_thresholds"
}
```

After (v2):
```json
"BP": {
  "values": {"pre_IVT": "185/110 mmHg"},
  "type": "structured_thresholds",
  "parsed_values": {
    "pre_IVT": {"operator": "=", "sbp": 185, "dbp": 110, "unit": "mmHg"}
  },
  "source_rec_ids": [],
  "synonym_term_ids": []
}
```

Python code that needs to compare "is the patient's BP below the pre-IVT limit?" can now do arithmetic on `parsed_values.pre_IVT.sbp` instead of re-parsing `"185/110 mmHg"` at runtime. Parser coverage: BP (including `<140 mmHg SBP` style), SpO2 %, time_window (single `4.5h`, range `0-4.5h`, and `min` forms), glucose (with operator), drug_dose (mg/kg + max + bolus/infusion split), age, NIHSS (single and range).

**Reviewer task:** spot-check parsed_values against the original string for every non-null entry. If parsed_values is null but the string looks parseable, extend the parser in `transform_refs.py` and re-run.

### Sections flagged for review (5 total)

| Section | Title | Concern | Action |
|---|---|---|---|
| **4.1** | Airway, Breathing, Oxygenation | `time_window` has 8 hour values (2h–72h) and `vessel=[LVO]` — these look like EVT leakage. `SpO2` thresholds (93%, 100%) are legitimate. | Verify `time_window`, `vessel`, and `intervention.EVT` against 4.1 rec text. Likely remove all three. |
| **4.2** | Head Positioning | Has `vessel=[LVO, MCA]`, `NIHSS=4`, `premorbid_mRS=0`, `imaging=[perfusion]` — none of these belong in a head-of-bed-angle section. | Verify all non-positioning variables against 4.2 rec text. Most are likely leakage from HeadPoST-adjacent recs. |
| **4.4** | Temperature Management | v1 metadata flags glucose leakage. Current temperature value 37.5C is legit; verify no glucose values present. | Full diff against 4.4 rec text. |
| **4.5** | Blood Glucose Management | v1 metadata flags temperature leakage. Current glucose values are legit; verify no temperature values present. | Full diff against 4.5 rec text. |
| **4.6.2** | Choice of Thrombolytic Agent | v1 metadata flags: 0 recs in `guideline_knowledge.json`, criteria exist only in `recommendation_criteria.json`. | Backfill 4.6.2 from `recommendation_criteria.json`. |

**Nothing was deleted** from these sections — just flagged. The review_flags block tells downstream code "trust lower".

### Intervention → synonym term ID linking

26 common intervention names are mechanically linked to synonym_dictionary term IDs. Examples:
- `"alteplase"` → `"alteplase"`
- `"tenecteplase"` → `"TNK"`
- `"decompressive surgery"` → `"decompressive_hemicraniectomy"`
- `"pneumatic compression"` → `"IPC"`

Unlinked values are preserved in `unlinked_values[]` so a reviewer can see them and either add a synonym entry or correct the data_dictionary value.

**Reviewer task:** walk every section's `unlinked_values[]` and resolve each one. This is the single biggest thing that will tighten the integration between the two files.

---

## synonym_dictionary.v2.json — changes

### Bug fixes (8 total, all applied automatically)

| Term | Fix | Reason |
|---|---|---|
| **ICH** | Removed `"hemorrhagic transformation"` from synonyms | HT is a separate canonical entry. HT's own `clinical_context` explicitly states it is distinct from ICH. Leaving this synonym on ICH caused the same string to collide with two different canonical concepts, which would break deterministic lookup. |
| **EVT** | Removed brand-name synonyms `["Solitaire", "Trevo"]` | Solitaire and Trevo are specific stent-retriever device brands, not EVT procedure synonyms. They remain on the `stent_retriever` entry. |
| **BP** | Removed self-duplicate synonym `["blood pressure"]` | Entry had `full_term: "blood pressure"` and also listed `"blood pressure"` as a synonym. Noise. |
| **DOAC** | Removed self-duplicate synonym | Same pattern. |
| **ICP** | Removed self-duplicate synonym | Same pattern. |
| **MSU** | Removed self-duplicate synonym | Same pattern. |
| **SpO2** | Removed self-duplicate synonym | Same pattern. |
| **PC-ASPECTS** | Removed self-duplicate synonym | Same pattern. |

All bug fixes are logged in `v2.bug_fixes[]` with term, fix, and reason — auditable.

### New structural additions

- **`reverse_index`** — `{full_term_lowercase: [term_ids]}`. Enables O(1) canonical → abbreviation lookup. Previously the LLM or Python had to scan all terms to go from `"tenecteplase"` back to `"TNK"`.
- **`overload_table`** — abbreviations with alternate medical meanings, so the QAQueryParsingAgent can flag ambiguity. Currently populated for `CT`, `PE`, `HT` (which has a `critical_note` because HT in stroke guidelines means hemorrhagic transformation, NOT hypertension — a real clinical footgun).
- **`duplicate_full_terms_report`** — flags cases where two term IDs claim the same `full_term` string (e.g., `DTAS`/`DTAS_procedure`, `GTN`/`GTN_drug`). The reviewer decides whether to merge or keep distinct.
- **`v1_inline_comments`** — preserves the 6 `_comment_*` string entries from v1 (which v1 used as inline documentation of term groupings). Not terms, but kept for context.

### Category taxonomy reconciliation

**Problem in v1.** The `category_index` block was out of sync with the actual categories used in `terms`:
- 12 categories in `terms` were missing from `category_index`: `clinical_cardiac`, `core_term`, `guideline_framework`, `imaging_finding`, `imaging_physiology`, `organization`, `quality_program`, `reference_standard`, `risk_score`, `route_of_administration`, `study_design`, `systems_process`
- 2 categories in `category_index` had no matching terms: `imaging_concept`, `surgery`

**Fix in v2.** `category_index` is now **rebuilt from the actual terms dict**, so it is always consistent. Any script that uses `category_index` will now see every real category.

**Conservative consolidation applied:**
- `clinical_cardiac` → `clinical_condition` (cardiac conditions are a subdomain of clinical conditions)
- `outcome_scale` → `outcome_measure` (genuine duplicate)

Terms affected by consolidation preserve the original category in `_v1_category` for traceability.

**Still needs human review (not auto-consolidated):**
- `assessment_scale` vs `screening_scale` — is the distinction "assessing severity" vs "screening for presence"? Document the rule or merge.
- `clinical_finding` vs `clinical_condition` — boundary unclear.
- `clinical_time` vs `process_metric` — both cover time metrics.
- `imaging_finding` vs `imaging_physiology` — sub-types of imaging; may or may not warrant separate categories.

### Things not fixed in v2 (by design — need human judgment)

1. **Term coverage.** 157 terms is thin for a specialty this dense. Expect gaps on tail queries. Expanding to several hundred terms is a human authoring task.
2. **Overloaded abbreviation prompting.** `overload_table` exists but the QAQueryParsingAgent prompt needs a new rule: "if the question contains a term from `overload_table`, check the `guideline_context` and disambiguate before classifying topic."
3. **Typo / fuzzy match handling.** Clinicians type "teneceplase", "NHISS", "altplase". No fuzzy normalization pass exists. Adding one (rapidfuzz or similar, threshold ~85) would catch most.
4. **Synonym frequency weighting.** Some synonyms are much more common than others ("TNK" vs formal "Tenecteplase"). A frequency rank would help the QAAssemblyAgent pick the idiomatic form.
5. **Per-term versioning.** When the 2027 guideline drops, there's no way to track which terms were edited when. Consider adding `last_updated` per term.

---

## Additional items for Claude Code (not a file, but on the roadmap)

### 1. Delete `intent_map.json`

Verified during inspection that this file is referenced ONLY in `.docs/CLINICAL_AGENTS.md` — it is not imported by any Python file. Deletion is safe, but also update the doc reference so future readers don't go looking for it.

### 2. Add `intent_catalog.json`

The `intent_catalog.json` file (produced earlier in the session) should be added to the same `qa/references/` directory. Consumers:
- `query_parsing_agent.py` needs a new rule to load and use it for intent classification
- Focused agents need a rule to read `answer_shape` for extraction target selection
- QAAssemblyAgent needs to format answers according to `answer_shape`

Path suggestion: place it next to the other reference files as `intent_catalog.json`. Do not rename as `intent_map.json` (even after deleting the dead one) — that filename carries stale associations.

### 3. Add a data_dictionary test harness

A simple test file under `qa/tests/` that spot-checks `parsed_values` against the original string for every non-null entry would catch parser regressions. Roughly:

```python
def test_parsed_values_roundtrip():
    dd = json.load(open("data_dictionary.v2.json"))
    for sec_id, sec in dd["sections"].items():
        for var_name, var in sec.items():
            if not isinstance(var, dict): continue
            if "parsed_values" not in var: continue
            assert parsed_matches_values(var["values"], var["parsed_values"]), \
                f"{sec_id}.{var_name} parsed/raw mismatch"
```

### 4. Wire `synonym_term_ids` into the SectionRouter

The SectionRouter currently does concept intersection on string values. With v2, it can do intersection on term IDs, which is more robust to casing/spacing variations. Roughly:

```python
# v1
section_concepts = set(data_dict[section]["intervention"]["values"])
match = question_concepts & section_concepts  # fragile string match

# v2
section_concepts = set(data_dict[section]["intervention"]["synonym_term_ids"])
question_concepts = {expand_via_synonym_dict(w) for w in question}
match = question_concepts & section_concepts  # term ID match
```

---

## Re-running the transform

`transform_refs.py` is idempotent and fast. If v1 files get edited upstream, just:

```bash
python3 transform_refs.py
```

It reads from `/sessions/lucid-affectionate-bohr/medsync_refs/` (the cached v1 copies) and writes to `/sessions/lucid-affectionate-bohr/mnt/outputs/`. Edit the `SRC` and `OUT` paths at the top of the script for production use.

All fix lists (`LEAKAGE_SUSPECTS`, `INTERVENTION_TO_TERM_ID`, `OVERLOAD_NOTES`, `CATEGORY_CONSOLIDATION`) are defined as top-of-file dicts so they can be edited in place without touching the transform logic.

## Verification done in this session

- v1 term count (163) = v2 term count (157) + v2 v1_inline_comments (6). No terms lost.
- All 46 sections from v1 are present in v2.
- BP parsed_values spot-checked against original `"185/110 mmHg"` style strings — parser matches.
- SpO2 parsed_values `{operator: "=", value: 93, unit: "%"}` matches the original `"93%"`.
- ICH no longer claims `"hemorrhagic transformation"` as a synonym.
- EVT no longer claims `"Solitaire"` or `"Trevo"` as synonyms.
- `category_index` rebuilt from actual terms — no more orphan categories.
