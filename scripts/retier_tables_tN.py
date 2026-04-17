"""Full retier migration: canonical T{N}.{i} section_ids for Tables 3-9,
per-subsection titles, plus deduplication of atoms ingested from
multiple sources.

Replaces the earlier `enrich_table_section_paths.py` style ids
(`4.6.1.t8.absolute`) with the cleaner guideline-native notation
(`4.6.T8.3`). Subsection content is identified by the atom's
`category` field; duplicates (same category, same normalized text)
are collapsed to one canonical atom per subsection item.

Master table titles live only in the topic map / catalog — NOT on
each atom's section_title. Per-atom section_title carries the
subsection heading so citations like "§4.6 T8.3" sit alongside the
correct subsection name.

Usage:
    python3 scripts/retier_tables_tN.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)

# ─── Section id mapping ──────────────────────────────────────────────
# (atom.category) → (section_id, section_path, section_title)
# section_path is ["<chapter>", "T<N>[.<i>]", "<subsection heading>"]
# section_title is the subsection heading (NOT the master table title)
#
# For tables WITHOUT subsections (flat), the subsection heading equals
# the table's own title (T5, T6 treat the table itself as the single
# content unit).

_FLAT_TABLE_TITLES: Dict[str, Tuple[str, str, str]] = {
    # category → (section_id, chapter, title_for_atoms)
    "extended_window_imaging_criteria": (
        "4.6.T3", "4.6",
        "Imaging Criteria Used in the Extended Window Thrombolysis Trials",
    ),
    "sich_management": (
        "4.6.T5", "4.6",
        "Management of Symptomatic Intracranial Bleeding Occurring Within 24 Hours After Administration of IV Alteplase or Tenecteplase for Treatment of AIS in Adults",
    ),
    "sich_management_step": (
        "4.6.T5", "4.6",
        "Management of Symptomatic Intracranial Bleeding Occurring Within 24 Hours After Administration of IV Alteplase or Tenecteplase for Treatment of AIS in Adults",
    ),
    "angioedema_management": (
        "4.6.T6", "4.6",
        "Management of Orolingual Angioedema Associated With IV Thrombolytic Administration for AIS in Adults",
    ),
    "angioedema_management_step": (
        "4.6.T6", "4.6",
        "Management of Orolingual Angioedema Associated With IV Thrombolytic Administration for AIS in Adults",
    ),
    "dapt_trial": (
        "4.8.T9", "4.8", "DAPT Trials",
    ),
}

# (category, table_label) → (section_id, chapter, subsection title)
# Tiered tables — subsection heading differs per tier.
_TIERED_SUBSECTION_TITLES: Dict[str, Tuple[str, str, str]] = {
    # Table 4 — Guidance for Determining Deficits to be Clearly Disabling
    "disabling_deficit": (
        "4.6.T4.1", "4.6",
        "Framing: basic activities of daily living and disabling deficit determination",
    ),
    "typically_disabling": (
        "4.6.T4.2", "4.6",
        "Deficits that would typically be considered clearly disabling",
    ),
    "may_not_be_disabling": (
        "4.6.T4.3", "4.6",
        "Deficits that may not be clearly disabling in an individual patient",
    ),
    # Table 7 — Treatment of AIS in Adults: IVT
    "ivt_dosing": (
        "4.6.T7.1", "4.6",
        "IVT dosing: alteplase and tenecteplase",
    ),
    "tenecteplase_weight_band": (
        "4.6.T7.2", "4.6",
        "Tenecteplase weight-based dosing bands",
    ),
    "ivt_administration_step": (
        "4.6.T7.3", "4.6",
        "IVT administration and post-treatment monitoring",
    ),
    # Table 8 — Other situations wherein thrombolysis is Deemed to be considered
    "benefit_greater_than_risk": (
        "4.6.T8.1", "4.6",
        "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding",
    ),
    "relative_contraindication": (
        "4.6.T8.2", "4.6",
        "Conditions That are Relative Contraindications (to IVT)",
    ),
    "absolute_contraindication": (
        "4.6.T8.3", "4.6",
        "Conditions that are Considered Absolute Contraindications (to IVT)",
    ),
}

# Short labels for section_path[1] ("T8.3", "T5", etc.) — the
# citation-worthy id for display.
def _short_label(section_id: str) -> str:
    """'4.6.T8.3' → 'T8.3'; '4.6.T5' → 'T5'; '4.8.T9' → 'T9'."""
    parts = section_id.split(".", 2)
    if len(parts) >= 3:
        return parts[2]
    if len(parts) == 2:
        return parts[1]
    return section_id


def _resolve(category: str) -> Optional[Tuple[str, str, str]]:
    if category in _FLAT_TABLE_TITLES:
        return _FLAT_TABLE_TITLES[category]
    if category in _TIERED_SUBSECTION_TITLES:
        return _TIERED_SUBSECTION_TITLES[category]
    return None


# ─── Dedupe ──────────────────────────────────────────────────────────
# Two atoms are duplicates if they share (section_id, category) and
# their text, normalized, is equal. Prefer the canonical source when
# collapsing: `atom-rss-Table N-*` beats `atom-rss-<concept>-*` beats
# `atom-table<N>-row-*`.

def _norm_text(s: str) -> str:
    # Collapse whitespace and strip surrounding punctuation for
    # comparison. No regex per project rule — plain string ops.
    return " ".join(str(s or "").lower().split()).strip(" .,;:")


_SOURCE_PRIORITY: List[str] = [
    "atom-rss-Table ",   # the table-source ingestion
    "atom-rss-",          # other rss concept-section ingestions
    "atom-table",         # table_row structured ingestion
    "atom-",              # fallback
]


def _source_rank(atom_id: str) -> int:
    for i, prefix in enumerate(_SOURCE_PRIORITY):
        if atom_id.startswith(prefix):
            return i
    return len(_SOURCE_PRIORITY)


def _pick_canonical(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the best atom to keep from a duplicate group."""
    candidates.sort(key=lambda a: _source_rank(a.get("atom_id", "")))
    return candidates[0]


# ─── Main migration ──────────────────────────────────────────────────

def main() -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)

    atoms: List[Dict[str, Any]] = data.get("atoms", [])
    if not atoms:
        print(f"No atoms in {ATOMS_PATH}")
        return 1

    # Partition atoms: table atoms (to migrate) vs everything else (pass through)
    table_atoms: List[Dict[str, Any]] = []
    other_atoms: List[Dict[str, Any]] = []
    for a in atoms:
        cat = str(a.get("category", "") or "")
        if _resolve(cat) is not None:
            table_atoms.append(a)
        else:
            other_atoms.append(a)

    # Group duplicates by (section_id, normalized text)
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for a in table_atoms:
        cat = a.get("category", "")
        resolved = _resolve(cat)
        if resolved is None:
            continue
        section_id, chapter, subtitle = resolved
        key = (section_id, _norm_text(a.get("text", "")))
        groups.setdefault(key, []).append(a)

    # Pick one canonical per group, assign new fields
    migrated: List[Dict[str, Any]] = []
    dupes_removed = 0
    counts: Dict[str, int] = {}
    for (section_id, _), candidates in groups.items():
        chosen = _pick_canonical(candidates)
        dupes_removed += len(candidates) - 1

        cat = chosen.get("category", "")
        resolved = _resolve(cat)
        if resolved is None:
            migrated.append(chosen)
            continue
        sid, chapter, subtitle = resolved

        chosen["parent_section"] = sid
        chosen["section_path"] = [chapter, _short_label(sid), subtitle]
        chosen["section_title"] = subtitle
        migrated.append(chosen)
        counts[sid] = counts.get(sid, 0) + 1

    # Write back: migrated table atoms + unchanged non-table atoms
    data["atoms"] = other_atoms + migrated
    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Migration complete.")
    print(f"  Table atoms before: {len(table_atoms)}")
    print(f"  Table atoms after:  {len(migrated)}")
    print(f"  Duplicates dropped: {dupes_removed}")
    print()
    print("Counts by new section_id:")
    for sid, n in sorted(counts.items()):
        print(f"  {sid}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
