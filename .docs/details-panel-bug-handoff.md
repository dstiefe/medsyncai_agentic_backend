# Details Panel Bug — Handoff

## The Problem

The Details & Citations panel shows ALL 18 RSS rows from §4.8 (Antiplatelet Treatment) when it should show only the 3 rows from the `antiplatelet_ivt_interaction` sub-topic for a query like "Do I give aspirin for a patient with a stroke after IVT."

The **Summary is correct** — it cites only Rec 4.8(2), Rec 4.8(17), and the ARTIS trial evidence. The Details panel ignores what the Summary used and dumps the entire parent section.

## The Diagnostic

I injected a diagnostic line into `_build_detail` in `response_presenter.py` that prints directly into the API response. It shows:

```
[DIAGNOSTIC] rss_from_retrieved=0 rows, has_concept_rows=False,
rec_sections=['4.8'], full_by_section_keys=['4.8'], rss_sections=[]
```

This tells us:
- `rss_from_retrieved=0` — the `RetrievedContent` passed to `_build_detail` has **zero** RSS rows
- `has_concept_rows=False` — no concept-dispatched rows reached `_build_detail`
- `full_by_section_keys=['4.8']` — so `_build_detail` falls back to `_full_rss_for_sections(['4.8'])` which fetches ALL 18 rows from the parent section

## Where the Rows Get Lost

The concept section dispatcher in `content_retriever.py` correctly returns 3 rows from `antiplatelet_ivt_interaction` with `_concept_dispatched=True`. These rows are in `retrieved.rss` — the LLM sees them and writes the correct Summary from them.

The rows disappear between `retrieved` and the `filtered` object passed to `_build_detail`. The filtering happens at approximately line 253-310 in `response_presenter.py`:

```python
filtered = RetrievedContent(
    ...
    rss=_filter_rss_to_relevant(retrieved.rss, entry_ids, relevant_sections),
    ...
)
detail = _build_detail(filtered)
```

The LLM outputs `RELEVANT: 4.8(2), 4.8(17)` — using parent section IDs. The concept-dispatched rows have `section="antiplatelet_ivt_interaction"`. The filter checks if the row's section is in `relevant_sections` (which is `{"4.8"}`). `"antiplatelet_ivt_interaction" != "4.8"` → row dropped.

I tried multiple fixes to resolve this ID mismatch (parentChapter lookup, unconditional pass for concept-dispatched rows, removing the filter entirely). Each fix looked correct in the code but the deployed platform still showed 0 rows. My latest commit (`8f44425`) removes the RELEVANT-based rss filter entirely and disables `_full_rss_for_sections` — but I have no confidence it will work given the pattern.

## What the Correct Architecture Should Be

The user defined it clearly:

1. **Python retriever** sends the LLM exactly the rows it needs (concept section sub-topic rows + matching recs). For "aspirin after IVT" that's 3 rss rows + 3 recs.
2. **LLM** reads those rows, writes the Summary.
3. **Details** = those same rows, rendered verbatim. Not re-fetched. Not re-filtered. Not ID-matched. The exact rows the LLM saw.

The Summary is a summary OF the Details. The Details is the source material. Both come from the same retriever output.

## What Needs to Happen

1. **Trace the actual execution path** from `content_retriever.retrieve_content()` through to `_build_detail()` on the deployed server. Specifically: does `retrieved.rss` have concept-dispatched rows when it enters the presenter? If yes, where exactly do they get dropped?

2. **Make `_build_detail` use `retrieved.rss` directly** without calling `_full_rss_for_sections` to re-fetch from the knowledge store. The re-fetch is what causes the 18-row dump — it goes back to the parent section "4.8" instead of using the sub-topic rows the retriever already provided.

3. **Remove the fragile ID-matching code.** The RELEVANT-based filtering, `_filter_rss_to_relevant`, the parentChapter resolution — all of it exists to solve a problem that shouldn't exist. If `_build_detail` just renders what the retriever returned, no ID matching is needed.

## Files Involved

- `app/agents/clinical/ais_clinical_engine/agents/qa_v4/response_presenter.py` — the presenter, specifically `_build_detail()` and the RELEVANT filtering at lines ~250-310
- `app/agents/clinical/ais_clinical_engine/agents/qa_v4/content_retriever.py` — concept dispatcher at the top of `retrieve_content()`, concept_rss_rows construction
- `app/agents/clinical/ais_clinical_engine/agents/qa_v4/knowledge_loader.py` — concept section catalogue, category_filter resolution

## Current State of origin/dev

HEAD: `8f44425` — my latest attempt which removes the RELEVANT rss filter and disables full_by_section. Untested on the platform (I lost confidence and stopped).

The diagnostic `[DIAGNOSTIC v3]` line is still in the code and will appear in the Details panel output. Look for it to see what `_build_detail` receives.

## What I Got Wrong

I kept adding downstream filters and guards instead of fixing the upstream problem. Every fix was a bandaid on top of a bandaid. The correct approach is structural simplification: Details = retriever output, rendered verbatim. No re-fetching, no re-filtering, no ID matching.
