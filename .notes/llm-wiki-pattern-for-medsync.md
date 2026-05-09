# LLM Wiki Pattern for MedSync AI

> Based on [Andrej Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — evaluated for MedSync agent architecture.

---

## What Is the LLM Wiki Pattern?

It's a 3-layer knowledge management architecture where LLMs actively maintain structured wikis rather than passively retrieving information. The key insight: **the wiki is a persistent, compounding artifact** that grows richer with each source added, unlike traditional RAG systems that rediscover knowledge on every query.

### Three Layers

| Layer | Purpose | MedSync Equivalent |
|---|---|---|
| **Raw Sources** | Immutable documents (papers, guidelines) | JSON files (`recommendations.json`, `guideline_knowledge.json`) |
| **Wiki** | LLM-maintained synthesis pages that compound over time | **We don't have this yet** |
| **Schema** | Config that tells the LLM how to maintain the wiki | `SKILL.md` files (partially) |

### Three Operations

| Operation | Description |
|---|---|
| **Ingest** | New source arrives -> LLM reads it, writes summaries, updates entity pages, revises cross-references. A single source might touch 10-15 wiki pages. |
| **Query** | User asks a question -> LLM searches wiki pages -> synthesizes answer with citations. Valuable responses file back into the wiki so explorations compound. |
| **Lint** | Periodic health-check identifies contradictions, stale info, orphaned pages, missing cross-references, and knowledge gaps. |

### Navigation Infrastructure

- **index.md** — Content catalog organized by category, listing each page with summaries. Updated on every ingest.
- **log.md** — Append-only chronological record of all wiki evolution. Helps LLMs maintain continuity across sessions.

---

## How MedSync Clinical Agent Works Today

### Current Strengths

- 5 JSON data files (~760 KB of structured guideline knowledge)
- Deterministic rule evaluation (Table8, Table4, EVT rules)
- Semantic + keyword retrieval for Q&A
- Reference files for output formatting

### Current Gaps (Where Wiki Pattern Helps)

1. **No accumulated clinical reasoning** — Every query starts from scratch. If the system produces a great synthesis about M2 dominant occlusions, that knowledge vanishes after the session.

2. **Knowledge duplication** — The same guideline criterion can live in `recommendations.json`, `ivt_rules.json`, AND hardcoded Python objects. Changes require touching 3 places.

3. **All-or-nothing context loading** — Reference files are concatenated into system prompts at startup. The clinical output agent loads ALL 3 reference files every time, even if the query only needs one pathway.

4. **No cross-linking** — Table rules don't reference recommendations. Checklists don't link back to the data layer. Each agent is an island.

---

## Proposed Adaptation for MedSync

### Per-Agent Wiki Structure

Each agent gets a structured wiki within a `wiki/` folder, alongside existing `data/` and `references/`:

```
app/agents/clinical/ais_clinical_engine/
├── data/                          <-- Raw Sources (immutable, unchanged)
│   ├── recommendations.json
│   ├── guideline_knowledge.json
│   └── ...
├── wiki/                          <-- NEW: LLM-maintained knowledge layer
│   ├── index.md                   <-- Page catalog, updated on every ingest
│   ├── log.md                     <-- Chronological record of wiki changes
│   ├── pathways/
│   │   ├── ivt_standard.md        <-- Synthesized: criteria + edge cases + examples
│   │   ├── evt_extended.md
│   │   ├── evt_large_core.md
│   │   └── m2_occlusion.md
│   ├── entities/
│   │   ├── nihss.md               <-- Everything about NIHSS across all pathways
│   │   ├── aspects.md
│   │   └── vessel_locations.md
│   └── edge_cases/
│       ├── age_over_80.md         <-- Accumulated knowledge about this edge case
│       └── nihss_under_6.md
```

### How Operations Map to MedSync

| Operation | Karpathy's Pattern | MedSync Adaptation |
|---|---|---|
| **Ingest** | New source -> LLM updates 10-15 wiki pages | New guideline update -> update pathway pages, entity pages, cross-references |
| **Query** | Search wiki -> synthesize answer | Q&A agent searches wiki pages first (fast, pre-synthesized), falls back to raw JSON only if needed |
| **Lint** | Periodic health-check for contradictions | Detect when wiki pages contradict `recommendations.json`, flag stale pages after guideline updates |

### Query Flow — Before vs After

**Before (current):**
```
User asks about M2 occlusion ->
  IntentAgent classifies ->
  RecommendationAgent does keyword + embedding search across 202 recs ->
  SupportiveTextAgent fetches RSS ->
  AssemblyAgent synthesizes from scratch
```

**After (wiki pattern):**
```
User asks about M2 occlusion ->
  IntentAgent classifies ->
  Wiki lookup: wiki/pathways/m2_occlusion.md (pre-synthesized, rich) ->
  If wiki page sufficient -> format and return
  If not -> fall back to full retrieval pipeline ->
  Update wiki page with new synthesis
```

The wiki page for M2 occlusion would already contain the synthesized knowledge about dominant vs. nondominant, Class IIa vs Class III, the relevant trials, edge cases — because it was built up over time.

---

## What Does NOT Change

The deterministic layer (scripts/, rule engines) stays exactly as-is. The wiki pattern applies to the **knowledge retrieval and synthesis** layer, not the **threshold matching and eligibility evaluation** layer.

- NIHSS >= 6 logic stays in Python
- Table 8 contraindication checks stay in Python
- EVT eligibility rules stay in Python

**Never put threshold comparisons or boolean logic in a wiki page.**

---

## Benefits for MedSync

1. **Clinical knowledge compounds** — Edge cases, pathway nuances, cross-references between guidelines all get richer over time instead of being re-derived every session.

2. **Reduces redundant LLM work** — Pre-synthesized wiki pages mean the LLM doesn't re-derive the same knowledge every session. Faster responses, lower token cost.

3. **Single source of truth** — Wiki pages link back to raw JSON sources, eliminating the duplication problem across the 3 JSON rule files.

4. **Selective context loading** — Instead of dumping all references into every prompt, load only the wiki page(s) relevant to the current query. Smaller context = better performance.

5. **Auditability** — `log.md` tracks every wiki change. You can trace why a wiki page says what it says.

6. **Scales to other agents** — Same pattern works for journal search, database engine, or any future agent that accumulates domain knowledge.

---

## Compatibility with MedSync 3-Layer Rule

The wiki pattern fits cleanly into the existing architecture:

| MedSync Layer | Wiki Role |
|---|---|
| **SKILL.md** (process only) | Schema layer — tells the agent HOW to use the wiki |
| **references/** (domain knowledge) | Wiki layer — LLM-maintained synthesis pages |
| **scripts/** (deterministic code) | Unchanged — threshold matching, validation, scoring |
| **data/** (raw JSON) | Raw Sources layer — immutable guideline data |

The `references/` folder evolves from static markdown files into an actively maintained wiki. The `data/` folder remains the immutable source of truth that wiki pages are derived from.

---

## Next Steps

1. **Prototype with one pathway** (e.g., M2 occlusion or EVT large core) to validate the pattern
2. **Build wiki loader** — lightweight Python that reads wiki pages by topic, integrates with existing `load_reference()` pattern
3. **Add ingest workflow** — when guideline data changes, trigger wiki page updates
4. **Add lint workflow** — periodic check that wiki pages are consistent with raw JSON sources
5. **Evaluate token savings** — compare context size and response quality before/after
