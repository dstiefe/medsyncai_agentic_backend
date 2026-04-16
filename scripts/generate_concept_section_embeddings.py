"""
Generate semantic embeddings for every concept section in
ais_guideline_section_map.json.

Each concept section gets ONE embedding that captures its full
semantic identity:
  - description: the natural-language summary of what it covers
  - routing_keywords: the clinical phrases the dispatcher uses
  - when_to_route: example clinician questions this section answers

Using all-MiniLM-L6-v2 (same model as atoms and recs) at 384 dims,
L2-normalized, so cosine similarity = dot product.

Output: data/concept_section_embeddings.npz with two arrays:
  embeddings: (n_concept_sections, 384)
  metadata: list of {concept_id, content_section_id, category_filter,
                     description, text_embedded}

Run this script whenever concept sections are added/edited.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer

# ── Paths ───────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
_SECTION_MAP_PATH = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references/"
    "ais_guideline_section_map.json",
)
_OUTPUT_PATH = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/data/"
    "concept_section_embeddings.npz",
)

_MODEL_NAME = "all-MiniLM-L6-v2"


def _build_embed_text(concept_id: str, entry: Dict[str, Any]) -> str:
    """Build the text that represents this concept section's semantic identity.

    Includes description, routing keywords, and example clinician
    questions. These together capture what the concept section is
    about and which questions belong there.
    """
    parts: List[str] = []

    # Title and human-readable identifier
    title = entry.get("title", "") or concept_id.replace("_", " ")
    parts.append(title)

    # Description — primary semantic content
    description = entry.get("description", "") or ""
    if description:
        parts.append(description)

    # Routing keywords — clinical phrases associated with this section
    routing_keywords = entry.get("routing_keywords", []) or []
    if routing_keywords:
        parts.append(". ".join(str(k) for k in routing_keywords))

    # When-to-route examples — how clinicians actually ask these questions
    when_to_route = entry.get("when_to_route", []) or []
    if when_to_route:
        parts.append(" ".join(str(q) for q in when_to_route))

    return " | ".join(p for p in parts if p)


def main() -> int:
    # Load the section map
    with open(_SECTION_MAP_PATH, "r") as f:
        section_map = json.load(f)

    concept_sections = section_map.get("concept_sections", {})
    if not isinstance(concept_sections, dict):
        print("ERROR: concept_sections is not a dict", file=sys.stderr)
        return 1

    # Build embedding texts
    concept_ids: List[str] = []
    embed_texts: List[str] = []
    metadata: List[Dict[str, Any]] = []

    for cid, entry in concept_sections.items():
        if not isinstance(entry, dict):
            continue
        text = _build_embed_text(cid, entry)
        if not text:
            print(f"  skipping {cid} — no embeddable text")
            continue
        concept_ids.append(cid)
        embed_texts.append(text)
        metadata.append({
            "concept_id": cid,
            "content_section_id": entry.get("content_section_id", ""),
            "category_filter": entry.get("category_filter", cid),
            "supported_intents": entry.get("supported_intents", []),
            "title": entry.get("title", ""),
            "description": entry.get("description", ""),
            "text_embedded": text,
        })

    print(f"Embedding {len(embed_texts)} concept sections...")

    # Load model and encode
    model = SentenceTransformer(_MODEL_NAME)
    embeddings = model.encode(
        embed_texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype(np.float32)

    # Save
    os.makedirs(os.path.dirname(_OUTPUT_PATH), exist_ok=True)
    np.savez(
        _OUTPUT_PATH,
        embeddings=embeddings,
        metadata=np.array(json.dumps(metadata), dtype=object),
    )

    print(f"Wrote {embeddings.shape[0]} embeddings ({embeddings.shape[1]} dims)")
    print(f"Output: {_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
