# Routing Mistakes Analysis — platform_test_60 (2026-04-05)

## What the test report showed vs what's actually happening

The test report says 58/60 (97%) before audit, 54/60 (90%) after audit. That's optimistic. A deterministic scan of the 60 question blocks shows **12 of 60 questions (20%) returned a primary recommendation from a different section than the test key expected**. The audit marked 6 of those as "correct anyway" because multi-section search surfaced the right content in the summary. That hides the routing problem — the fact that multi-section search papered over 6 wrong primary routes means the primary router is wrong 20% of the time, not 10%.

## Classification of the 12 section mismatches

| # | ID | Fix path | Status |
|---|---|---|---|
| Q4 | fix-Q4-QA-70262 | test_key_repair | Platform right, test wrong (IVT ≠ EVT) |
| Q7 | fix-Q7-QA-70017 | test_key_repair | Platform right, test wrong (neuroprotection → 4.11, not 2.3) |
| Q18 | fix-Q18-QA-70381 | **v2 auto-fix** | Posterior/basilar/vertebrobasilar synonym gap |
| Q22 | fix-Q22-QA-70821 | **v2 auto-fix + test key repair** | FAST/public_education synonym gap + test key wrong |
| Q23 | fix-Q23-QA-70051 | test_key_expand | Legitimate multi-section (2.2 + 5.1) |
| Q24 | fix-Q24-QA-70837 | test_key_expand | Legitimate multi-section (2.3 + 2.4) |
| Q29 | fix-Q29-QA-71018 | **v2 auto-fix** | Needs `out_of_scope` intent path |
| Q42 | fix-Q42-QA-71032 | test_key_repair | Platform right, test wrong |
| Q44 | fix-Q44-QA-70319 | test_key_expand | Legitimate multi-section (2.4 + 4.7.2) |
| Q48 | fix-Q48-QA-70331 | **v2 auto-fix** | stroke_scale/NIHSS → 3.1 link missing |
| Q50 | fix-Q50-QA-70339 | **blocked on review_flags** | 4.1 leakage |
| Q56 | fix-Q56-QA-70353 | **blocked on review_flags** | 4.4/4.5 glucose↔temperature leakage |

Plus from test40 COR/LOE checks:
- Q45 (2.5 MSU) — within-section rec picker picked rec-2.5-004 instead of rec-2.5-001
- Q7 (2.8 telestroke) — within-section rec picker, may be test key issue
- Q10 (3.2 imaging) — within-section rec picker

## What this means for the v2 work

**v2 fixes 4 mistakes deterministically** (Q18, Q22, Q29, Q48). Four more (Q4, Q7, Q42, plus Q22 dual) need test key corrections, which are editorial not code. Three (Q23, Q24, Q44) need the test key expanded to multi-section because the questions legitimately span multiple sections — the `candidate_sections: List[str]` field in `intent_catalog.output_schema` is already designed for exactly this, but the fixture needs to express the ambiguity.

**Two mistakes are blocked on human review of the PDF** (Q50, Q56). These are the concrete cost of the review_flags on 4.1 and 4.4/4.5 — they're not theoretical. Q56 in particular is the canonical 4.4/4.5 glucose↔temperature leakage bug showing up in a real user question. Until someone reads the PDF and deletes the leaked fields, the router cannot reliably distinguish glucose management from temperature management.

**Within-section rec picking is a second class of bug** (Q45, test40-Q7, test40-Q10) that the fixture now tracks separately. Section routing can be 100% correct and the user still gets the wrong rec if the focused agent picks the wrong rec within the section. Step 8 of the implementation plan (focused agents iterate all recs with intent-driven field selection, not top-scoring) is what fixes this. The parsed-values roundtrip test in Step 13 is specifically designed to catch regressions here.

## Specific claude_code_action items surfaced by this fixture

These are concrete edits to `synonym_dictionary.v2.json` and `data_dictionary.v2.json` that the fixture forces Claude Code to make:

1. **Q22 forces a synonym addition.** Add `FAST`, `public stroke education`, `stroke mnemonic` as terms under `category=public_health_tool` with `section_hint='2.1'`. Link in `data_dictionary.v2.json` section 2.1 as `synonym_term_ids`.

2. **Q18 forces a vessel territory addition.** Add `posterior circulation`, `basilar`, `vertebrobasilar` under `category=vessel_territory` with `section_hint='4.7.3'`. Link in `data_dictionary.v2.json` section 4.7.3.

3. **Q48 forces a stroke scale linking.** The NIHSS term already exists in synonym_dictionary.v2 but is not linked as a 3.1-anchoring term. Add synonym_term_ids for NIHSS/stroke_scale to `data_dictionary.v2.json` section 3.1.

4. **Q29 forces the out_of_scope intent.** Verify `out_of_scope` exists in `intent_catalog.intents`. If not, add it with `required_slots: []` and `answer_shape: 'not_addressed_in_guideline'`. The scaffolding_verifier must set this when no required_slots can be populated from any candidate section.

5. **Q45 forces a focused-agent behavior change.** The focused agent must iterate all recs in a matched section and rank them by intent+slot match, not by keyword score. Add a pytest case asserting `returned_rec == 'rec-2.5-001'` for the MSU prehospital thrombolysis question.

## What I'd add to the fixture before Claude Code runs it

The fixture as written has 14 entries covering the real mistakes. Before running Steps 6–13 against it, add one passing question per review_flagged section so the suite detects when human review clears 4.1/4.2/4.4/4.5/4.6.2. Those are listed in `coverage_gaps_to_add_later` in the JSON. Also add the overload_table disambiguation test ("what is the management for HT?") which should produce `vague=true, missing_slots=['overload_disambiguation_HT']` — this is the canonical overload_table test and it's not exercised anywhere else in the plan.

## One observation that changes the priority order

Q56 (glucose → 4.6.1) and Q50 (O2 sat → 4.7.3) both land in the review_flagged bucket. **The human PDF review of sections 4.1, 4.2, 4.4, 4.5 is not a nice-to-have that can wait — it's blocking two real user-facing mistakes that the v2 code changes cannot fix on their own**. If you want to graduate these out of the fixture's "blocked" list, the PDF review needs to happen in parallel with Steps 6–13, not after.
