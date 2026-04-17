"""Migrate the v5 atoms file so every Table row carries a canonical
hierarchical section id.

Option A — full data migration:
  - `parent_section`: rewritten from the flat label "Table N" to the
    canonical hierarchical id "<chapter>.t<N>[.<subsection-slug>]".
    Examples:
        "Table 8" absolute row   → "4.6.1.t8.absolute"
        "Table 8" relative row   → "4.6.1.t8.relative"
        "Table 3" imaging row    → "4.6.3.t3.criteria"
        "Table 9" DAPT row       → "4.8.t9.trials"
  - `section_path`: new list for human-readable breadcrumb display,
    e.g. ["4.6.1", "Table 8", "Absolute Contraindications"].
  - `section_title` is left unchanged — it still carries the full
    descriptive title from atomization.

All other atom types and fields are untouched. Running the script
again is idempotent — atoms already holding the canonical id for
their table/category pair are skipped.

Usage:
    python3 scripts/enrich_table_section_paths.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)

# Mapping: original parent_section label → (chapter_section, table_slug, short_label)
# `short_label` is the clinician-facing table reference used in citations
# ("Table 8"), not the full descriptive title. The descriptive title is
# already stored on each atom as `section_title` and is left untouched.
_TABLE_META: Dict[str, Tuple[str, str, str]] = {
    "Table 3": ("4.6.3", "t3", "Table 3"),
    "Table 4": ("4.6.1", "t4", "Table 4"),
    "Table 5": ("4.6.1", "t5", "Table 5"),
    "Table 6": ("4.6.1", "t6", "Table 6"),
    "Table 7": ("4.6.1", "t7", "Table 7"),
    "Table 8": ("4.6.1", "t8", "Table 8"),
    "Table 9": ("4.8",   "t9", "Table 9"),
}

# Mapping: (original parent_section, category) → (subsection_slug, subsection_display)
# When the category is not listed the atom gets only the table-level
# id with no subsection segment.
_SUBSECTION_META: Dict[Tuple[str, str], Tuple[str, str]] = {
    # Table 3 — imaging criteria for extended window
    ("Table 3", "extended_window_imaging_criteria"): (
        "criteria", "Extended Window Imaging Criteria",
    ),
    # Table 4 — disabling deficit assessment
    ("Table 4", "disabling_deficit"): (
        "disabling", "Disabling Deficits",
    ),
    ("Table 4", "typically_disabling"): (
        "typically-disabling", "Typically Disabling",
    ),
    ("Table 4", "may_not_be_disabling"): (
        "may-not-be-disabling", "May Not Be Disabling",
    ),
    # Table 5 — sICH management
    ("Table 5", "sich_management"): (
        "management", "sICH Management",
    ),
    ("Table 5", "sich_management_step"): (
        "steps", "sICH Management Steps",
    ),
    # Table 6 — angioedema management
    ("Table 6", "angioedema_management"): (
        "management", "Angioedema Management",
    ),
    ("Table 6", "angioedema_management_step"): (
        "steps", "Angioedema Management Steps",
    ),
    # Table 7 — IVT dosing
    ("Table 7", "ivt_dosing"): (
        "dosing", "IVT Dosing",
    ),
    ("Table 7", "ivt_administration_step"): (
        "administration", "IVT Administration Steps",
    ),
    ("Table 7", "tenecteplase_weight_band"): (
        "tenecteplase-weight", "Tenecteplase Weight Bands",
    ),
    # Table 8 — contraindications (the high-value one)
    ("Table 8", "absolute_contraindication"): (
        "absolute", "Absolute Contraindications",
    ),
    ("Table 8", "relative_contraindication"): (
        "relative", "Relative Contraindications",
    ),
    ("Table 8", "benefit_greater_than_risk"): (
        "benefits-may-exceed-risks", "Benefits May Exceed Risks",
    ),
    # Table 9 — DAPT trials
    ("Table 9", "dapt_trial"): (
        "trials", "DAPT Trials",
    ),
}


def _derive(atom: dict) -> Optional[Tuple[str, List[str]]]:
    """Compute (new parent_section, section_path) for this atom.

    Returns None when the atom isn't one of the tables we migrate.
    """
    parent = str(atom.get("parent_section") or "")
    if parent not in _TABLE_META:
        return None
    chapter, table_slug, table_display = _TABLE_META[parent]
    category = str(atom.get("category") or "")
    sub_meta = _SUBSECTION_META.get((parent, category))

    if sub_meta:
        sub_slug, sub_display = sub_meta
        new_parent = f"{chapter}.{table_slug}.{sub_slug}"
        path = [chapter, table_display, sub_display]
    else:
        new_parent = f"{chapter}.{table_slug}"
        path = [chapter, table_display]

    return new_parent, path


def _is_already_migrated(atom: dict, canonical_parent: str) -> bool:
    """True when the atom's parent_section already holds a dot-path that
    matches (or is a descendant of) the canonical one we'd assign.
    Used for idempotence — re-running the script on a migrated file
    leaves it alone.
    """
    current = str(atom.get("parent_section") or "")
    return current == canonical_parent


def enrich_atom(atom: dict) -> bool:
    """Migrate a single atom in place. Returns True if modified."""
    derived = _derive(atom)
    if derived is None:
        # Not a table atom we handle, OR already migrated (since the
        # rewritten parent_section will no longer be "Table N")
        return False
    new_parent, path = derived
    if _is_already_migrated(atom, new_parent) and atom.get("section_path") == path:
        return False
    atom["parent_section"] = new_parent
    atom["section_path"] = path
    return True


def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms = data.get("atoms", [])
    if not atoms:
        print(f"No atoms found in {ATOMS_PATH}")
        return 1

    by_table: Dict[str, int] = {}
    modified = 0
    for atom in atoms:
        orig_parent = atom.get("parent_section")
        if enrich_atom(atom):
            modified += 1
            by_table[orig_parent] = by_table.get(orig_parent, 0) + 1

    if modified == 0:
        print("No atoms needed migration (file is already up-to-date).")
        return 0

    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Migrated {modified} atoms across {len(by_table)} tables:")
    for table, n in sorted(by_table.items()):
        print(f"  {table}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
