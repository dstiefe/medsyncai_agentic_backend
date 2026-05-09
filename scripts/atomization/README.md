# Table Atomization Pipeline

Canonical atomizer for guideline tables (T3, T4, T5, T6, T7, T8, T9).
Replaces the ad-hoc migration scripts (`retier_tables_tN.py`,
`add_row_labels.py`, `enrich_table_section_paths.py`,
`finalize_table_retier.py`) that accumulated across the 2026-04-17
session — each patched around atomization gaps, none was the single
source of truth.

## Files

- **`tables.py`** — declarative source. One Python data structure
  listing every table, every subsection, every row, with:
    - the table's parent chapter (§3.2 / §4.6 / §4.8)
    - master title and subsection titles (verbatim from the guideline)
    - row slug, row label, and verbatim row text
    - intent_affinity per subsection
    - shared anchor terms
- **`build_tables.py`** — atomizer. Reads `tables.py` and regenerates
  every table atom with canonical metadata + a fresh embedding.

## Why

The previous atomization:

- ingested each row multiple times (table-form + narrative-form) with
  different wording, defeating dedupe;
- mis-categorized rows (T4.1 held T4.2 and T4.3 content);
- placed T3 under §4.6 instead of §3.2;
- didn't preserve row labels (condition/step names) or row order;
- polluted anchor matching by putting sibling subsection names into
  `section_title` (Table 8's title lists "Absolute" + "Relative" +
  "Benefits").

All of that was patched by hand after the fact. The patches worked,
but the next guideline revision would trigger another round. The
pipeline in this directory owns the problem at the source.

## Next guideline revision — the whole workflow

1. Open `tables.py`. For each table, update:
   - verbatim row text from the new guideline PDF,
   - add new rows / remove retired rows at the correct position,
   - update any renamed subsection titles.
2. Keep row slugs stable when the underlying clinical concept is
   unchanged. Retrieval references and any bookmarks use the slug.
3. Run:

   ```bash
   python3 scripts/atomization/build_tables.py
   ```

4. Review the per-section census the script prints. Commit
   `tables.py` and the regenerated `guideline_knowledge.atomized.v5.json`
   together.

## What `build_tables.py` does in one pass

1. Loads the current atoms file.
2. **Drops** every table atom it owns:
   - anything already in the `atom-table-*` canonical namespace
   - legacy clean rows: `atom-rss-Table N-*`
   - narrative duplicates: `atom-tableN-row-NN`
   - subsection summaries from the prior pipeline: `atom-tsec-summary-*`
   - legacy concept_section masters whose content is now covered
     (absolute_contraindications_ivt, dapt_trials_evidence, …)
   - any atom still carrying a `"Table N"` flat parent_section
3. **Builds** the canonical set from `TABLES`:
   - one row atom per row, with deterministic id `atom-table-{sec}-{slug}`
     (e.g. `atom-table-T8.3-aria`)
   - one summary atom per subsection (or per flat table)
   - correct `parent_section` in the hierarchical scheme
     (`3.2.T3`, `4.6.T8.3`, `4.8.T9`, …)
   - `section_path` breadcrumb for display
   - `row_order` and `row_label` populated from the declarative source
   - fresh 384-dim sentence-transformer embedding per atom
4. Writes the combined atoms list back.

Non-table atoms (recommendations, rec-level RSS/synopsis/KG,
concept_section atoms outside the tables) pass through unchanged.

## Deterministic atom ids

The old atomization used slugs derived from ingestion quirks:
`atom-rss-Table 8-ct-with-extensive-hypodensity`,
`atom-rss-Table 7-tnk_weight__60_kg`. The new scheme is:

    atom-table-{SectionSuffix}-{RowSlug}

Examples:

| Section                 | Row                                | Atom id                        |
|-------------------------|------------------------------------|--------------------------------|
| 3.2.T3                  | WAKE-UP                            | `atom-table-T3-wake_up`        |
| 4.6.T4.2                | Complete hemianopsia               | `atom-table-T4.2-hemianopsia`  |
| 4.6.T7.2                | <60 kg                             | `atom-table-T7.2-under_60_kg`  |
| 4.6.T8.3                | Amyloid-related imaging abnormalities (ARIA) | `atom-table-T8.3-aria` |
| 4.8.T9                  | CHANCE                             | `atom-table-T9-chance`         |

The summary atom per subsection uses `-summary` as the row slug:
`atom-table-T8.3-summary`.

## Invariants

After a clean `build_tables.py` run:

- Every atom owned by this pipeline has `parent_section` in
  `{3.2.T3, 4.6.T4.1, 4.6.T4.2, 4.6.T4.3, 4.6.T5, 4.6.T6, 4.6.T7.1,
  4.6.T7.2, 4.6.T7.3, 4.6.T8.1, 4.6.T8.2, 4.6.T8.3, 4.8.T9}`.
- Every row atom has `row_order` >= 1 and `row_label` non-empty.
- Row counts match the clinician-confirmed paste:
  T3=7, T4.1=4, T4.2=4, T4.3=7, T5=7, T6=9, T7.1=2, T7.2=5, T7.3=6,
  T8.1=9, T8.2=18, T8.3=10, T9=5. Plus one `-summary` atom per
  subsection.
- No atom in the corpus still has a `"Table N"` flat parent_section.
- No concept_section atom from the legacy overlap list remains.

## Deprecated scripts

These are superseded by this pipeline and can be deleted from
`scripts/` next cleanup:

- `add_row_labels.py`
- `retier_tables_tN.py`
- `enrich_table_section_paths.py`
- `finalize_table_retier.py`

Left in place for this commit so the session's git history reflects
how we got here.
