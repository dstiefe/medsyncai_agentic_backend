#!/usr/bin/env python3
"""
Atomize ALL sections in guideline_knowledge.json.

Converts every RSS row, synopsis paragraph, and knowledge-gap bullet
into a first-class atom with a pre-computed embedding vector.

No LLM calls. Pure deterministic transformation:
  1. Read guideline_knowledge.json
  2. For each section, split RSS rows / synopsis / KG into atoms
  3. Compute embedding for each atom using sentence-transformers
  4. Write atomized output to guideline_knowledge.atomized.json
  5. Run validators — report failures without writing bad atoms

Usage:
    python scripts/atomization/atomize_all.py

Output:
    app/.../data/guideline_knowledge.atomized.json  (staged)
    scripts/atomization/atomization_report.json      (validation report)
"""

import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_SCRIPT_DIR, os.pardir, os.pardir)
_DATA_DIR = os.path.join(
    _REPO_ROOT,
    "app", "agents", "clinical", "ais_clinical_engine", "data",
)
_SOURCE_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.json")
_OUTPUT_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.json")
_EMBEDDINGS_PATH = os.path.join(_DATA_DIR, "atom_embeddings.npz")
_REPORT_PATH = os.path.join(_SCRIPT_DIR, "atomization_report.json")

# ── Embedding model ───────────────────────────────────────────────────
# Same model already used by embedding_store.py for rec embeddings.
_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None


def _get_model():
    """Lazy-load the sentence-transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


# ── Atom ID generation ────────────────────────────────────────────────


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s_-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text[:max_len].rstrip("_")


def _make_atom_id(section_id: str, source_type: str, index: int,
                  text: str) -> str:
    """Generate a unique, readable atom_id."""
    sec_slug = section_id.replace(" ", "_").replace(".", "_").lower()
    text_slug = _slugify(text[:60])
    return f"{sec_slug}.{source_type}.{index:03d}.{text_slug}"


# ── Sentence boundary detection ──────────────────────────────────────

_SENTENCE_TERMINATORS = frozenset(".?!:")


def _ends_at_sentence_boundary(text: str) -> bool:
    """Check if text ends at a natural sentence boundary."""
    stripped = text.rstrip()
    if not stripped:
        return False
    # Allow closing parens/brackets after punctuation
    last = stripped[-1]
    if last in ")]\u201d\u2019":
        if len(stripped) >= 2:
            last = stripped[-2]
    return last in _SENTENCE_TERMINATORS


# ── RSS row → atom conversion ────────────────────────────────────────


def _rss_to_atom(
    section_id: str,
    section_title: str,
    rss_row: Dict[str, Any],
    index: int,
) -> Optional[Dict[str, Any]]:
    """Convert one RSS row to an atom dict (without embedding yet)."""
    text = (rss_row.get("text") or "").strip()
    if not text:
        return None

    atom_id = _make_atom_id(section_id, "rss", index, text)

    return {
        "atom_id": atom_id,
        "text": text,
        "parent_section": section_id,
        "parent_display_group": section_title,
        "source_citation": f"2026 AHA/ASA AIS Guideline \u00a7{section_id}",
        "source_type": "rss",
        "atom_type": "evidence_summary",
        "anchor_terms": [],      # populated by enrichment or left for semantic
        "intent_affinity": [],   # populated by enrichment or left for semantic
        "semantic_tags": [],     # populated by enrichment or left for semantic
        "value_ranges": {},
        "category": rss_row.get("category", ""),
        "condition": rss_row.get("condition", ""),
        "recNumber": rss_row.get("recNumber", ""),
    }


def _synopsis_to_atoms(
    section_id: str,
    section_title: str,
    synopsis: str,
) -> List[Dict[str, Any]]:
    """Split a synopsis into paragraph-level atoms."""
    if not synopsis or not synopsis.strip():
        return []

    # Split on double newlines or paragraph breaks
    paragraphs = re.split(r"\n\s*\n", synopsis.strip())
    atoms = []
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para or len(para) < 20:
            continue
        atom_id = _make_atom_id(section_id, "syn", i, para)
        atoms.append({
            "atom_id": atom_id,
            "text": para,
            "parent_section": section_id,
            "parent_display_group": section_title,
            "source_citation": f"2026 AHA/ASA AIS Guideline \u00a7{section_id}",
            "source_type": "synopsis",
            "atom_type": "narrative_context",
            "anchor_terms": [],
            "intent_affinity": [],
            "semantic_tags": [],
            "value_ranges": {},
            "category": "",
            "condition": "",
        })
    return atoms


def _kg_to_atoms(
    section_id: str,
    section_title: str,
    kg_text: str,
) -> List[Dict[str, Any]]:
    """Split knowledge gaps text into bullet-level atoms."""
    if not kg_text or not kg_text.strip():
        return []

    # KG text is often bullet-separated with • or \n•
    bullets = re.split(r"\s*\u2022\s*", kg_text.strip())
    atoms = []
    for i, bullet in enumerate(bullets):
        bullet = bullet.strip()
        if not bullet or len(bullet) < 20:
            continue
        atom_id = _make_atom_id(section_id, "kg", i, bullet)
        atoms.append({
            "atom_id": atom_id,
            "text": bullet,
            "parent_section": section_id,
            "parent_display_group": section_title,
            "source_citation": f"2026 AHA/ASA AIS Guideline \u00a7{section_id}",
            "source_type": "knowledge_gap",
            "atom_type": "evidence_gap",
            "anchor_terms": [],
            "intent_affinity": [],
            "semantic_tags": ["knowledge_gap"],
            "value_ranges": {},
            "category": "",
            "condition": "",
        })
    return atoms


# ── Validation ────────────────────────────────────────────────────────


def _validate_atom(atom: Dict[str, Any]) -> List[str]:
    """Return a list of validation failures (empty = valid)."""
    failures = []

    if not atom.get("atom_id"):
        failures.append("missing atom_id")
    if not atom.get("text"):
        failures.append("missing text")
    if not atom.get("parent_section"):
        failures.append("missing parent_section")
    if not atom.get("source_type"):
        failures.append("missing source_type")

    text = atom.get("text", "")
    if text and not _ends_at_sentence_boundary(text):
        # Warning, not a hard failure — some table rows legitimately
        # end without period (e.g. "Complete hemianopsia")
        failures.append(f"text does not end at sentence boundary: ...{text[-30:]}")

    return failures


# ── Main atomization pipeline ─────────────────────────────────────────


def atomize_all() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atomize every section. Returns (atomized_kb, report)."""

    logger.info("Loading source: %s", _SOURCE_PATH)
    with open(_SOURCE_PATH, "r", encoding="utf-8") as f:
        kb = json.load(f)

    sections = kb.get("sections", {})
    report = {
        "total_sections": len(sections),
        "sections_atomized": 0,
        "sections_already_atomized": 0,
        "sections_skipped_empty": 0,
        "total_atoms_created": 0,
        "total_atoms_preserved": 0,
        "validation_warnings": [],
        "atoms_by_section": {},
    }

    all_atom_texts = []   # for batch embedding
    all_atom_refs = []    # (section_id, atom_index) for mapping back

    for sec_id, sec_body in sections.items():
        section_title = sec_body.get("sectionTitle", sec_id)

        # If already atomized (e.g. Table 8), preserve existing atoms
        existing_atoms = sec_body.get("atoms") or []
        if existing_atoms:
            report["sections_already_atomized"] += 1
            report["total_atoms_preserved"] += len(existing_atoms)
            report["atoms_by_section"][sec_id] = {
                "status": "preserved",
                "count": len(existing_atoms),
            }
            # Still collect texts for embedding if they don't have one
            for i, atom in enumerate(existing_atoms):
                if "embedding" not in atom:
                    all_atom_texts.append(atom.get("text", ""))
                    all_atom_refs.append((sec_id, i, "existing"))
            continue

        # Build atoms from RSS rows, synopsis, knowledge gaps
        new_atoms: List[Dict[str, Any]] = []

        # RSS rows → atoms
        rss = sec_body.get("rss") or []
        for i, row in enumerate(rss):
            atom = _rss_to_atom(sec_id, section_title, row, i)
            if atom:
                new_atoms.append(atom)

        # Synopsis → atoms
        synopsis = sec_body.get("synopsis", "")
        if synopsis:
            syn_atoms = _synopsis_to_atoms(sec_id, section_title, synopsis)
            new_atoms.extend(syn_atoms)

        # Knowledge gaps → atoms
        kg = sec_body.get("knowledgeGaps", "")
        if kg:
            kg_atoms = _kg_to_atoms(sec_id, section_title, kg)
            new_atoms.extend(kg_atoms)

        if not new_atoms:
            report["sections_skipped_empty"] += 1
            report["atoms_by_section"][sec_id] = {
                "status": "skipped_empty",
                "count": 0,
            }
            continue

        # Validate
        for atom in new_atoms:
            warnings = _validate_atom(atom)
            for w in warnings:
                report["validation_warnings"].append(
                    f"{sec_id}/{atom.get('atom_id', '?')}: {w}"
                )

        # Store atoms in section
        sec_body["atoms"] = new_atoms
        report["sections_atomized"] += 1
        report["total_atoms_created"] += len(new_atoms)
        report["atoms_by_section"][sec_id] = {
            "status": "atomized",
            "count": len(new_atoms),
            "source_types": {
                "rss": sum(1 for a in new_atoms if a["source_type"] == "rss"),
                "synopsis": sum(1 for a in new_atoms if a["source_type"] == "synopsis"),
                "knowledge_gap": sum(1 for a in new_atoms if a["source_type"] == "knowledge_gap"),
            }
        }

        # Collect texts for embedding
        for i, atom in enumerate(new_atoms):
            all_atom_texts.append(atom.get("text", ""))
            all_atom_refs.append((sec_id, i, "new"))

    # ── Compute embeddings ────────────────────────────────────────
    # Each atom is embedded as "section_title. text" so the embedding
    # captures BOTH the atom's specific content AND the section context
    # it belongs to. Without this, short table rows like "Complete
    # hemianopsia" would not embed close to a conceptual query like
    # "What defines a non-disabling stroke?" — but with the section
    # title prepended ("Table 4: Guidance for Determining Deficits to
    # be Clearly Disabling at Presentation. Complete hemianopsia..."),
    # the embedding reflects the full semantic context.
    #
    # The `text` field stays verbatim for rendering — this enrichment
    # only affects the embedding vector.
    def _embedding_text(atom: Dict[str, Any]) -> str:
        title = atom.get("parent_display_group", "") or ""
        text = atom.get("text", "")
        if title:
            return f"{title}. {text}"
        return text

    # Rebuild embedding texts with section context
    all_embedding_texts = []
    for sec_id, atom_idx, origin in all_atom_refs:
        if origin == "existing":
            atom = sections[sec_id]["atoms"][atom_idx]
        else:
            atom = sections[sec_id]["atoms"][atom_idx]
        all_embedding_texts.append(_embedding_text(atom))

    logger.info(
        "Computing embeddings for %d atoms (with section context)...",
        len(all_embedding_texts),
    )
    model = _get_model()
    t0 = time.time()
    embeddings = model.encode(
        all_embedding_texts,
        show_progress_bar=True,
        batch_size=64,
        normalize_embeddings=True,  # L2-normalize for cosine similarity
    )
    elapsed = time.time() - t0
    logger.info(
        "Embeddings computed: %d vectors, dim=%d, %.1fs",
        len(embeddings), embeddings.shape[1] if len(embeddings) > 0 else 0,
        elapsed,
    )

    # Map embeddings back to atoms
    for idx, (sec_id, atom_idx, origin) in enumerate(all_atom_refs):
        emb = embeddings[idx].tolist()
        if origin == "existing":
            sections[sec_id]["atoms"][atom_idx]["embedding"] = emb
        else:
            sections[sec_id]["atoms"][atom_idx]["embedding"] = emb

    report["embedding_dim"] = int(embeddings.shape[1]) if len(embeddings) > 0 else 0
    report["embedding_time_s"] = round(elapsed, 1)

    return kb, report


def main():
    kb, report = atomize_all()

    # Write atomized KB
    logger.info("Writing atomized KB to: %s", _OUTPUT_PATH)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)

    # Write report
    logger.info("Writing report to: %s", _REPORT_PATH)
    with open(_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Summary
    print("\n" + "=" * 60)
    print("ATOMIZATION COMPLETE")
    print("=" * 60)
    print(f"  Sections atomized:         {report['sections_atomized']}")
    print(f"  Sections preserved:        {report['sections_already_atomized']}")
    print(f"  Sections skipped (empty):  {report['sections_skipped_empty']}")
    print(f"  Total atoms created:       {report['total_atoms_created']}")
    print(f"  Total atoms preserved:     {report['total_atoms_preserved']}")
    print(f"  Embedding dim:             {report['embedding_dim']}")
    print(f"  Validation warnings:       {len(report['validation_warnings'])}")
    if report["validation_warnings"]:
        print("\n  Warnings (first 10):")
        for w in report["validation_warnings"][:10]:
            print(f"    - {w}")
    print(f"\n  Output: {_OUTPUT_PATH}")
    print(f"  Report: {_REPORT_PATH}")


if __name__ == "__main__":
    main()
