"""One-shot re-embedding pass for all atoms.

Used after an embedding-model upgrade (e.g. MiniLM → bge-base) to
replace every atom's `embedding` field with a fresh 768-dim vector
produced by the new model. Reads model from semantic_service so the
source of truth stays in one place.

Usage:
    python3 scripts/atomization/re_embed_atoms.py
    python3 scripts/atomization/re_embed_atoms.py --batch-size 32
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

ATOMS_PATH = REPO_ROOT / (
    "app/agents/clinical/ais_clinical_engine/data/"
    "guideline_knowledge.atomized.v5.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=32,
                        help="atoms per encode call")
    args = parser.parse_args()

    # Lazy import so the model is only loaded when we actually run
    from app.agents.clinical.ais_clinical_engine.agents.qa_v6 import (
        semantic_service,
    )

    with open(ATOMS_PATH, "r") as f:
        data = json.load(f)
    atoms = data.get("atoms", [])
    if not atoms:
        print(f"No atoms in {ATOMS_PATH}")
        return 1

    print(f"Loading model {semantic_service._MODEL_NAME} "
          f"(expects {semantic_service._EMBEDDING_DIM}-dim)...")
    model = semantic_service._get_model()

    total = len(atoms)
    print(f"Re-embedding {total} atoms in batches of {args.batch_size}...")
    start = time.time()
    done = 0

    # Encode in batches for speed. normalize_embeddings=True gives
    # L2-normalized vectors — matches what embed_query produces so
    # cosine similarity is just a dot product at retrieval time.
    for i in range(0, total, args.batch_size):
        batch = atoms[i:i + args.batch_size]
        texts = [a.get("text", "") or "" for a in batch]
        vecs = model.encode(texts, normalize_embeddings=True)
        for atom, vec in zip(batch, vecs):
            atom["embedding"] = [float(x) for x in vec]
        done += len(batch)
        elapsed = time.time() - start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f"  {done}/{total} | elapsed={elapsed:.1f}s eta={eta:.1f}s")

    # Write back
    with open(ATOMS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Re-embedded {total} atoms in {time.time() - start:.1f}s.")
    dim = len(atoms[0].get("embedding", []))
    print(f"Embedding dim: {dim} (expected {semantic_service._EMBEDDING_DIM})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
