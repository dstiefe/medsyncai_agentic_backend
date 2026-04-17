"""Rewrite every atom's `intent_affinity` from the declarative
category→intents mapping in `category_intents.py`.

Replaces the prior lexical / keyword-proximity tagging produced by
the LLM in `classify_atom_metadata.py`. After this script runs, an
atom's intent_affinity is a pure function of its category — no
freeform LLM judgment at runtime.

Atoms without a category, or with a category not in the mapping,
keep the conservative UNMAPPED_FALLBACK (`recommendation_lookup`
only) and are logged so curation can extend the mapping incrementally.

Usage:
    python3 scripts/atomization/rewire_intents.py
    python3 scripts/atomization/rewire_intents.py --dry-run   # just report
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from category_intents import (  # noqa: E402
    ATOM_TYPE_INTENTS, CATEGORY_INTENTS, UNMAPPED_FALLBACK,
    get_intents, get_intents_by_type, get_status,
)

ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)


def main(dry_run: bool = False) -> int:
    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)
    atoms = data.get("atoms", [])
    if not atoms:
        print(f"No atoms in {ATOMS_PATH}")
        return 1

    changed = 0
    unchanged = 0
    skipped_unmapped = 0
    unmapped_cats: Counter = Counter()
    status_counts: Counter = Counter()
    by_type_fallback_count = 0

    for a in atoms:
        category = str(a.get("category", "") or "")

        if category:
            # Atom has a category — use the declarative mapping
            status = get_status(category)
            status_counts[status] += 1
            if status == "UNMAPPED":
                skipped_unmapped += 1
                unmapped_cats[category] += 1
                continue
            new_intents = get_intents(category)
        else:
            # Atom has no category — fall back to the atom_type
            # intent set (clean defaults per structural role).
            atom_type = str(a.get("atom_type", "") or "")
            if atom_type in ATOM_TYPE_INTENTS:
                new_intents = get_intents_by_type(atom_type)
                status_counts["TYPE_FALLBACK"] += 1
                by_type_fallback_count += 1
            else:
                # Unknown atom_type — keep existing intents
                status_counts["NO_CATEGORY_NO_TYPE"] += 1
                continue

        old_intents = sorted(a.get("intent_affinity", []) or [])
        if sorted(new_intents) != old_intents:
            if not dry_run:
                a["intent_affinity"] = new_intents
            changed += 1
        else:
            unchanged += 1

    if not dry_run:
        with open(ATOMS_PATH, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # Report
    print(f"Atoms examined: {len(atoms)}")
    print(f"  intent_affinity rewritten: {changed}")
    print(f"  intent_affinity already matched: {unchanged}")
    print(f"  via atom_type fallback:  {by_type_fallback_count}")
    print(f"  skipped (category unmapped): {skipped_unmapped}")
    print()
    print("Status tally:")
    for status, n in sorted(status_counts.items()):
        print(f"  {status:20} : {n}")
    if unmapped_cats:
        print()
        print(f"Unmapped categories kept as-is ({len(unmapped_cats)} distinct):")
        for cat, n in unmapped_cats.most_common(20):
            print(f"  {cat}: {n} atoms")
    if dry_run:
        print()
        print("DRY RUN — atoms file not written.")
    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    raise SystemExit(main(dry_run=dry))
