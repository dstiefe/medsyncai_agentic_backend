"""Dedicated atomizer for guideline tables.

Reads the declarative TABLES source in `tables.py` and regenerates
every table atom in the v5 atoms index. The generated atoms carry
canonical metadata (parent_section, section_path, section_title,
category, row_label, row_order, anchor_terms, intent_affinity) plus
a freshly computed sentence-transformer embedding.

Replaces ALL previously generated table atoms in one pass:
  - Drops any atom whose atom_id begins with `atom-table-` (the new
    canonical namespace this script owns).
  - Drops any legacy table atom the prior atomizer produced — those
    use slug patterns like `atom-rss-Table N-*`, `atom-tableN-row-NN`,
    `atom-tsec-summary-4.6.TN`, `atom-concept-*contraindications_ivt`,
    `atom-concept-dapt_trials_evidence`, etc.

Everything else (recommendations, non-table RSS, synopsis, KG, concept
atoms outside the migrated tables, rec-level atoms) is passed through
unchanged.

Usage:
    python3 scripts/atomization/build_tables.py

Next guideline revision: edit scripts/atomization/tables.py with the
new text/structure, re-run this script, commit. No hand-patching.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tables import TABLES  # noqa: E402  — local import by design

ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)


# ── ID helpers ───────────────────────────────────────────────────

def _section_id(table: str, tier: int = None) -> str:
    """'T8', tier=3 → '4.6.T8.3'. tier=None for flat tables → '4.6.T8'.

    Chapter is resolved from the table entry at call sites — this
    function only assembles the section id suffix and relies on the
    chapter passed explicitly.
    """
    raise NotImplementedError("Use _full_section_id with chapter")


def _full_section_id(chapter: str, table: str, tier: int = None) -> str:
    """'4.6' + 'T8' + tier=3 → '4.6.T8.3'."""
    if tier is None:
        return f"{chapter}.{table}"
    return f"{chapter}.{table}.{tier}"


def _short_label(section_id: str) -> str:
    """'4.6.T8.3' → 'T8.3'; '4.6.T5' → 'T5'."""
    idx = section_id.find(".T")
    if idx >= 0:
        return section_id[idx + 1:]
    return section_id


def _row_atom_id(table: str, tier: int, slug: str) -> str:
    """Deterministic canonical atom_id for a table row.

    Examples:
      T3, tier=None, slug="wake_up"       → atom-table-T3-wake_up
      T8, tier=3,    slug="aria"          → atom-table-T8.3-aria
      T7, tier=2,    slug="under_60_kg"   → atom-table-T7.2-under_60_kg
    """
    sec_suffix = f"{table}.{tier}" if tier is not None else table
    return f"atom-table-{sec_suffix}-{slug}"


def _summary_atom_id(table: str, tier: int) -> str:
    """Summary atom id for a subsection (or flat table)."""
    sec_suffix = f"{table}.{tier}" if tier is not None else table
    return f"atom-table-{sec_suffix}-summary"


# ── Legacy atom predicate — what gets dropped ────────────────────

def _is_legacy_table_atom(atom: Dict[str, Any]) -> bool:
    """True if the atom is a table artefact from a prior pipeline
    (clean-row atoms, narrative duplicates, subsection summaries,
    concept-master atoms) that this script will regenerate."""
    atom_id = str(atom.get("atom_id", "") or "")
    parent = str(atom.get("parent_section", "") or "")
    category = str(atom.get("category", "") or "")

    # Already in canonical namespace — drop so we rebuild fresh
    if atom_id.startswith("atom-table-"):
        return True
    # Clean-row atoms: atom-rss-Table N-*
    if atom_id.startswith("atom-rss-Table "):
        return True
    # Narrative duplicates: atom-tableN-row-NN
    if atom_id.startswith("atom-table") and "-row-" in atom_id:
        return True
    # Prior-pipeline subsection summaries: atom-tsec-summary-<section_id>
    if atom_id.startswith("atom-tsec-summary-"):
        return True
    # Legacy concept masters whose content is now covered by tables
    legacy_concept_cats = {
        "absolute_contraindications_ivt",
        "relative_contraindications_ivt",
        "dapt_trials_evidence",
        "disabling_deficits_assessment",
        "dosing_administration_ivt",
        "angioedema_management_post_ivt",
        "sich_management_post_ivt",
        "extended_window_imaging_criteria",
        "benefit_outweighs_risk_ivt",
    }
    if atom.get("atom_type") == "concept_section" and category in legacy_concept_cats:
        return True
    # Atoms whose parent_section is still a legacy table label
    if parent in {
        "Table 3", "Table 4", "Table 5", "Table 6",
        "Table 7", "Table 8", "Table 9",
    }:
        return True
    return False


# ── Canonical atom builders ──────────────────────────────────────

def _build_row_atom(
    table: str, chapter: str, tier: int,
    subsection_title: str, category: str,
    row_slug: str, row_order: int, row_label: str, text: str,
    subsection_anchors: List[str],
    subsection_intents: List[str],
) -> Dict[str, Any]:
    section_id = _full_section_id(chapter, table, tier)
    short = _short_label(section_id)
    # Merge per-row anchors (the row label as a clinical term) with
    # subsection-shared anchors (useful broad terms).
    anchors = list(dict.fromkeys(
        [row_label] + list(subsection_anchors)
    ))
    return {
        "atom_id": _row_atom_id(table, tier, row_slug),
        "atom_type": "evidence_summary",
        "parent_section": section_id,
        "section_path": [chapter, short, subsection_title],
        "section_title": subsection_title,
        "category": category,
        "row_label": row_label,
        "row_order": row_order,
        "text": text,
        "anchor_terms": anchors,
        "intent_affinity": list(subsection_intents),
        "cor": "",
        "loe": "",
        "value_ranges": {},
        # embedding filled in by _attach_embeddings()
    }


def _build_summary_atom(
    table: str, chapter: str, tier: int,
    subsection_title: str, category: str,
    row_labels_in_order: List[str],
    subsection_anchors: List[str],
    subsection_intents: List[str],
) -> Dict[str, Any]:
    """One-sentence descriptor of a subsection (or flat table)."""
    section_id = _full_section_id(chapter, table, tier)
    short = _short_label(section_id)
    # Build a compact descriptor listing the row labels
    descriptor = (
        f"{subsection_title}. Contents (in guideline order): "
        + "; ".join(row_labels_in_order) + "."
    )
    return {
        "atom_id": _summary_atom_id(table, tier),
        "atom_type": "narrative_context",
        "parent_section": section_id,
        "section_path": [chapter, short, subsection_title],
        "section_title": subsection_title,
        "category": f"{category}_summary" if category else "table_section_summary",
        "text": descriptor,
        "anchor_terms": list(subsection_anchors),
        "intent_affinity": list(subsection_intents),
        "cor": "",
        "loe": "",
        "value_ranges": {},
    }


# ── Embedding ────────────────────────────────────────────────────

def _attach_embeddings(atoms: List[Dict[str, Any]]) -> None:
    """Compute a 384-dim embedding for every atom missing one.

    Lazy import so the module loads without sentence-transformers when
    someone just wants to inspect the code.
    """
    from app.agents.clinical.ais_clinical_engine.agents.qa_v6 import (  # noqa: E402
        semantic_service,
    )
    for a in atoms:
        if a.get("embedding") and len(a["embedding"]) == 384:
            continue
        vec = semantic_service.embed_query(a.get("text", "") or "")
        a["embedding"] = [float(x) for x in vec]


# ── Main ─────────────────────────────────────────────────────────

def build_all() -> List[Dict[str, Any]]:
    """Generate the full set of canonical table atoms from TABLES."""
    out: List[Dict[str, Any]] = []
    for tdef in TABLES:
        table = tdef["table"]
        chapter = tdef["chapter"]
        master_title = tdef["master_title"]

        if tdef.get("flat"):
            tier = None  # flat tables use section_id like "4.6.T5"
            category = tdef.get("category", "")
            subsection_title = master_title
            subsection_anchors = tdef.get("anchor_terms_shared", [])
            subsection_intents = tdef.get("intent_affinity", [])
            row_labels_seen: List[str] = []
            for row_order, (slug, label, text) in enumerate(tdef["rows"], start=1):
                out.append(_build_row_atom(
                    table=table, chapter=chapter, tier=tier,
                    subsection_title=subsection_title,
                    category=category,
                    row_slug=slug, row_order=row_order,
                    row_label=label, text=text,
                    subsection_anchors=subsection_anchors,
                    subsection_intents=subsection_intents,
                ))
                row_labels_seen.append(label)
            out.append(_build_summary_atom(
                table=table, chapter=chapter, tier=tier,
                subsection_title=subsection_title,
                category=category,
                row_labels_in_order=row_labels_seen,
                subsection_anchors=subsection_anchors,
                subsection_intents=subsection_intents,
            ))
        else:
            for sub in tdef.get("subsections", []):
                tier = sub["tier"]
                category = sub["category"]
                subsection_title = sub["title"]
                subsection_anchors = sub.get("anchor_terms_shared", [])
                subsection_intents = sub.get("intent_affinity", [])
                row_labels_seen = []
                for row_order, (slug, label, text) in enumerate(sub["rows"], start=1):
                    out.append(_build_row_atom(
                        table=table, chapter=chapter, tier=tier,
                        subsection_title=subsection_title,
                        category=category,
                        row_slug=slug, row_order=row_order,
                        row_label=label, text=text,
                        subsection_anchors=subsection_anchors,
                        subsection_intents=subsection_intents,
                    ))
                    row_labels_seen.append(label)
                out.append(_build_summary_atom(
                    table=table, chapter=chapter, tier=tier,
                    subsection_title=subsection_title,
                    category=category,
                    row_labels_in_order=row_labels_seen,
                    subsection_anchors=subsection_anchors,
                    subsection_intents=subsection_intents,
                ))
    return out


def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)
    existing = data.get("atoms", [])
    if not existing:
        print(f"No atoms in {ATOMS_PATH}", file=sys.stderr)
        return 1

    # Keep atoms not managed by this script
    kept = [a for a in existing if not _is_legacy_table_atom(a)]
    dropped = len(existing) - len(kept)

    # Build the fresh canonical set from TABLES
    fresh = build_all()

    # Attach embeddings to fresh atoms (loads model once)
    print(f"Computing embeddings for {len(fresh)} fresh atoms...")
    _attach_embeddings(fresh)

    data["atoms"] = kept + fresh
    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"Dropped {dropped} legacy / prior-pipeline table atoms.")
    print(f"Wrote {len(fresh)} canonical table atoms.")
    print(f"Total atoms: {len(data['atoms'])}")
    # Per-section census
    from collections import Counter
    counts = Counter()
    for a in fresh:
        counts[a["parent_section"]] += 1
    print()
    print("Canonical table atom census:")
    for sec, n in sorted(counts.items()):
        print(f"  {sec:12} : {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
