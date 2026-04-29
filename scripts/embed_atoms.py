"""
Generate embeddings for every atom in atoms_intermediate.json.

Uses all-MiniLM-L6-v2 (384-dim, L2-normalized) — same model used
by atoms, recs, and concept sections throughout the system.

For each atom, builds an "embedding text" that includes:
  - type-specific prefix (REC, RSS, SYN, KG, TABLE, FIG, CONCEPT)
  - section context
  - the atom's actual text

This contextual prefix helps the model distinguish a recommendation
from its supporting evidence even when they share most words.

Run: python scripts/embed_atoms.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
_DATA_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/data",
)
_INTERMEDIATE_PATH = os.path.join(_DATA_DIR, "atoms_intermediate.json")

_MODEL_NAME = "all-MiniLM-L6-v2"


def build_embedding_text(atom: Dict[str, Any]) -> str:
    """Build a context-prefixed string for embedding this atom.

    The prefix helps separate semantically similar atoms of different
    types — e.g., a recommendation vs the evidence supporting it will
    still share most anchor terms, but the prefix gives the model a
    small contextual signal to distinguish them.
    """
    atom_type = atom.get("atom_type", "")
    section = atom.get("parent_section", "")
    text = atom.get("text", "")

    prefix_map = {
        "recommendation": f"[RECOMMENDATION §{section}] ",
        "evidence_summary": f"[EVIDENCE §{section}] ",
        "narrative_context": f"[SYNOPSIS §{section}] ",
        "evidence_gap": f"[KNOWLEDGE_GAP §{section}] ",
        "table_row": f"[TABLE §{section}] ",
        "figure": f"[FIGURE §{section}] ",
        "concept_section": f"[CONCEPT §{section or atom.get('concept_id', '')}] ",
    }
    prefix = prefix_map.get(atom_type, f"[{atom_type} §{section}] ")
    return prefix + text


def main() -> int:
    with open(_INTERMEDIATE_PATH, "r") as f:
        data = json.load(f)
    atoms = data["atoms"]
    print(f"Loaded {len(atoms)} atoms")

    # Build input texts
    print("Building embedding texts...")
    texts = [build_embedding_text(a) for a in atoms]

    # Load model
    print(f"Loading model {_MODEL_NAME}...")
    model = SentenceTransformer(_MODEL_NAME)

    # Encode (batched internally)
    print(f"Encoding {len(texts)} atoms...")
    start = time.time()
    embeddings = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype(np.float32)
    elapsed = time.time() - start
    print(f"Encoded in {elapsed:.1f}s ({embeddings.shape})")

    # Attach embeddings to atoms
    for i, atom in enumerate(atoms):
        atom["embedding"] = embeddings[i].tolist()

    # Write back
    with open(_INTERMEDIATE_PATH, "w") as f:
        json.dump({"atoms": atoms}, f, indent=2)

    print(f"Embeddings attached and saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
