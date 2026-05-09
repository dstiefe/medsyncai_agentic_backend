"""
Assemble the final unified atom index from atoms_intermediate.json.

Takes the intermediate file (atoms with metadata and embeddings) and
writes the production-ready unified file:
  data/guideline_knowledge.atomized.v5.json

Output schema:
  {
    "_metadata": {
      "version": "v5",
      "created_at": iso timestamp,
      "atom_count": N,
      "embedding_model": "all-MiniLM-L6-v2",
      "embedding_dim": 384,
      "counts_by_type": {...}
    },
    "atoms": [...]
  }

Validates:
  - every atom has atom_id, atom_type, text, embedding (384 floats)
  - every recommendation has cor, loe, recNumber
  - no duplicate atom_ids
  - atom_type values are from the known enum
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
_DATA_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/data",
)
_INTERMEDIATE_PATH = os.path.join(_DATA_DIR, "atoms_intermediate.json")
_OUTPUT_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.v5.json")

_VALID_ATOM_TYPES = {
    "recommendation", "evidence_summary", "narrative_context",
    "evidence_gap", "table_row", "figure", "concept_section",
}


def validate(atoms: list) -> list:
    """Return a list of validation errors; empty if all good."""
    errors = []
    seen_ids = set()

    for i, atom in enumerate(atoms):
        aid = atom.get("atom_id", "")
        if not aid:
            errors.append(f"atom[{i}]: missing atom_id")
            continue
        if aid in seen_ids:
            errors.append(f"atom[{i}]: duplicate atom_id {aid}")
        seen_ids.add(aid)

        at = atom.get("atom_type", "")
        if at not in _VALID_ATOM_TYPES:
            errors.append(f"{aid}: invalid atom_type {at!r}")

        if not atom.get("text"):
            errors.append(f"{aid}: missing text")

        emb = atom.get("embedding", [])
        if not emb:
            errors.append(f"{aid}: missing embedding")
        elif len(emb) != 384:
            errors.append(f"{aid}: embedding dim {len(emb)} != 384")

        if at == "recommendation":
            if not atom.get("cor"):
                errors.append(f"{aid}: rec missing cor")
            if not atom.get("loe"):
                errors.append(f"{aid}: rec missing loe")
            if not atom.get("recNumber"):
                errors.append(f"{aid}: rec missing recNumber")

    return errors


def main() -> int:
    with open(_INTERMEDIATE_PATH, "r") as f:
        data = json.load(f)
    atoms = data["atoms"]
    print(f"Loaded {len(atoms)} atoms")

    errors = validate(atoms)
    if errors:
        print(f"VALIDATION FAILED: {len(errors)} errors")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        return 1

    # Counts by type
    counts = {}
    for a in atoms:
        counts[a["atom_type"]] = counts.get(a["atom_type"], 0) + 1

    output = {
        "_metadata": {
            "version": "v5",
            "created_at": dt.datetime.utcnow().isoformat() + "Z",
            "atom_count": len(atoms),
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_dim": 384,
            "counts_by_type": counts,
        },
        "atoms": atoms,
    }

    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {len(atoms)} atoms to {_OUTPUT_PATH}")
    print("Counts by type:")
    for t, c in sorted(counts.items()):
        print(f"  {t}: {c}")
    print(f"\nValidation: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
