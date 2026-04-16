"""
Unified atom pipeline for the 2026 AIS Guidelines.

Reads all source files and produces a single atomized knowledge file
with every piece of retrievable clinical content represented as an atom.

Pipeline stages:
  1. Extract atoms from each source type (this script)
  2. LLM metadata classification (classify_atom_metadata.py)
  3. Embedding generation (this script, final stage)
  4. Assembly to guideline_knowledge.atomized.v5.json

Every atom has the same schema:
  atom_id, atom_type, text, parent_section, section_title,
  recNumber, cor, loe, category, anchor_terms, intent_affinity,
  source_citation, embedding (added later)

Run: python scripts/atomize_guideline.py --stage extract
     python scripts/atomize_guideline.py --stage classify
     python scripts/atomize_guideline.py --stage embed
     python scripts/atomize_guideline.py --stage assemble
     python scripts/atomize_guideline.py --stage all
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_HERE)
_DATA_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/data",
)
_REFS_DIR = os.path.join(
    _BACKEND_ROOT,
    "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references",
)

_GUIDELINE_KNOWLEDGE_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.json")
_RECOMMENDATIONS_PATH = os.path.join(_DATA_DIR, "recommendations.json")
_SECTION_MAP_PATH = os.path.join(_REFS_DIR, "ais_guideline_section_map.json")

# Intermediate file — atoms without metadata/embeddings yet
_INTERMEDIATE_PATH = os.path.join(_DATA_DIR, "atoms_intermediate.json")
# Final output
_OUTPUT_PATH = os.path.join(_DATA_DIR, "guideline_knowledge.atomized.v5.json")

_CITATION_PREFIX = "2026 AHA/ASA AIS Guideline"


def _load_json(path: str) -> Any:
    with open(path, "r") as f:
        return json.load(f)


# ── Extraction functions per source type ───────────────────────────


def extract_recommendations() -> List[Dict[str, Any]]:
    """Every rec in recommendations.json → one atom each."""
    data = _load_json(_RECOMMENDATIONS_PATH)
    recs = data.get("recommendations", [])
    atoms = []
    for rec in recs:
        rid = rec.get("id", "")
        if not rid:
            continue
        text = rec.get("text", "")
        if not text:
            continue
        sec = rec.get("section", "")
        # rid is already "rec-4.8-001" shape; don't double-prefix
        atom_id = rid if rid.startswith("rec-") else f"rec-{rid}"
        atoms.append({
            "atom_id": f"atom-{atom_id}",
            "atom_type": "recommendation",
            "text": text,
            "parent_section": sec,
            "section_title": rec.get("sectionTitle", ""),
            "recNumber": rec.get("recNumber", ""),
            "cor": rec.get("cor", ""),
            "loe": rec.get("loe", ""),
            "category": rec.get("concept_category", "") or rec.get("category", ""),
            "source_citation": f"{_CITATION_PREFIX}, §{sec}",
        })
    return atoms


def extract_rss_synopsis_kg() -> List[Dict[str, Any]]:
    """From guideline_knowledge.json, extract:
      - RSS rows → evidence_summary atoms
      - synopsis (flat or dict) → narrative_context atoms
      - knowledgeGaps (flat or dict) → evidence_gap atoms
    """
    data = _load_json(_GUIDELINE_KNOWLEDGE_PATH)
    sections = data.get("sections", {})
    atoms = []

    for sec_id, sec in sections.items():
        if not isinstance(sec, dict):
            continue
        sec_title = sec.get("sectionTitle", "")

        # RSS rows
        for i, row in enumerate(sec.get("rss", []) or []):
            text = row.get("text", "")
            if not text:
                continue
            rec_num = str(row.get("recNumber", "")).strip()
            category = row.get("category", "")
            atom_id = (
                f"atom-rss-{sec_id}-{rec_num}"
                if rec_num
                else f"atom-rss-{sec_id}-{i}"
            )
            atoms.append({
                "atom_id": atom_id,
                "atom_type": "evidence_summary",
                "text": text,
                "parent_section": sec_id,
                "section_title": sec_title,
                "recNumber": rec_num,
                "cor": "",
                "loe": "",
                "category": category,
                "condition": row.get("condition", ""),
                "source_citation": f"{_CITATION_PREFIX}, §{sec_id}",
            })

        # Synopsis — can be string or dict (per-concept-section split)
        synopsis = sec.get("synopsis", "")
        if isinstance(synopsis, str) and synopsis:
            atoms.append({
                "atom_id": f"atom-syn-{sec_id}",
                "atom_type": "narrative_context",
                "text": synopsis,
                "parent_section": sec_id,
                "section_title": sec_title,
                "recNumber": "",
                "cor": "",
                "loe": "",
                "category": "",
                "source_citation": f"{_CITATION_PREFIX}, §{sec_id} (Synopsis)",
            })
        elif isinstance(synopsis, dict):
            for cat, text in synopsis.items():
                if not text:
                    continue
                atoms.append({
                    "atom_id": f"atom-syn-{sec_id}-{cat}",
                    "atom_type": "narrative_context",
                    "text": text,
                    "parent_section": sec_id,
                    "section_title": sec_title,
                    "recNumber": "",
                    "cor": "",
                    "loe": "",
                    "category": cat,
                    "source_citation": f"{_CITATION_PREFIX}, §{sec_id} (Synopsis — {cat})",
                })

        # Knowledge gaps — can be string or dict
        kg = sec.get("knowledgeGaps", "")
        if isinstance(kg, str) and kg:
            # Split bullets if the string has them
            bullets = _split_kg_bullets(kg)
            for i, bullet in enumerate(bullets):
                if not bullet:
                    continue
                atoms.append({
                    "atom_id": f"atom-kg-{sec_id}-{i}",
                    "atom_type": "evidence_gap",
                    "text": bullet,
                    "parent_section": sec_id,
                    "section_title": sec_title,
                    "recNumber": "",
                    "cor": "",
                    "loe": "",
                    "category": "",
                    "source_citation": f"{_CITATION_PREFIX}, §{sec_id} (Knowledge Gaps)",
                })
        elif isinstance(kg, dict):
            for cat, text in kg.items():
                if not text:
                    continue
                # Split bullets within each sub-topic's KG
                bullets = _split_kg_bullets(text)
                for i, bullet in enumerate(bullets):
                    if not bullet:
                        continue
                    atoms.append({
                        "atom_id": f"atom-kg-{sec_id}-{cat}-{i}",
                        "atom_type": "evidence_gap",
                        "text": bullet,
                        "parent_section": sec_id,
                        "section_title": sec_title,
                        "recNumber": "",
                        "cor": "",
                        "loe": "",
                        "category": cat,
                        "source_citation": f"{_CITATION_PREFIX}, §{sec_id} (Knowledge Gaps — {cat})",
                    })

    return atoms


def _split_kg_bullets(text: str) -> List[str]:
    """Split a KG string on bullet markers (• or - prefix)."""
    if not text:
        return []
    # Normalize bullets
    text = text.replace("•", "\n•")
    # Split on bullet or newline + dash
    parts = re.split(r"(?:^|\n)\s*[•\-]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def extract_concept_sections() -> List[Dict[str, Any]]:
    """Every concept section in section_map → one atom each.

    Text = title + description + routing_keywords + when_to_route,
    since the concept section's semantic identity is all of those
    combined.
    """
    data = _load_json(_SECTION_MAP_PATH)
    concept_sections = data.get("concept_sections", {})
    atoms = []

    for cid, entry in concept_sections.items():
        if not isinstance(entry, dict):
            continue
        title = entry.get("title", "") or cid.replace("_", " ")
        description = entry.get("description", "") or ""
        routing_kws = entry.get("routing_keywords", []) or []
        when_to_route = entry.get("when_to_route", []) or []

        parts = [title]
        if description:
            parts.append(description)
        if routing_kws:
            parts.append("Keywords: " + "; ".join(str(k) for k in routing_kws))
        if when_to_route:
            parts.append("Example questions: " + " ".join(str(q) for q in when_to_route))

        text = " | ".join(p for p in parts if p)

        parent_section = entry.get("content_section_id", "") or ""
        atoms.append({
            "atom_id": f"atom-concept-{cid}",
            "atom_type": "concept_section",
            "text": text,
            "parent_section": parent_section,
            "section_title": title,
            "recNumber": "",
            "cor": "",
            "loe": "",
            "category": entry.get("category_filter", cid),
            "concept_id": cid,
            "supported_intents": entry.get("supported_intents", []),
            "description": description,
            "routing_keywords": routing_kws,
            "when_to_route": when_to_route,
            "source_citation": entry.get(
                "sourceCitation",
                f"{_CITATION_PREFIX}, concept_section {cid}",
            ),
        })
    return atoms


def extract_tables_and_figures() -> List[Dict[str, Any]]:
    """Tables and figures from the PDF supplement.

    guideline_knowledge.json already has Table 2-9 and Figure 2, 3, 4
    atomized as sections. extract_rss_synopsis_kg() handles those as
    regular sections. This function adds Table 1, Figure 1, Figure 5
    which are in the PDF but not in guideline_knowledge.json.
    """
    try:
        from pdf_supplement_atoms import _build_supplement_atoms
    except ImportError:
        # Same directory import
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pdf_supplement_atoms",
            os.path.join(_HERE, "pdf_supplement_atoms.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _build_supplement_atoms = mod._build_supplement_atoms
    return _build_supplement_atoms()


# ── Main pipeline ────────────────────────────────────────────────


def stage_extract() -> None:
    """Extract all atoms from source files (no metadata/embeddings)."""
    print("Stage 1: Extracting atoms from source files...")

    atoms = []
    atoms.extend(extract_recommendations())
    print(f"  Recommendations: {sum(1 for a in atoms if a['atom_type'] == 'recommendation')} atoms")

    new_count = len(atoms)
    atoms.extend(extract_rss_synopsis_kg())
    rss_synopsis_kg = len(atoms) - new_count
    by_type = {}
    for a in atoms[new_count:]:
        t = a["atom_type"]
        by_type[t] = by_type.get(t, 0) + 1
    print(f"  From guideline_knowledge.json: {rss_synopsis_kg} atoms")
    for t, c in by_type.items():
        print(f"    {t}: {c}")

    new_count = len(atoms)
    atoms.extend(extract_concept_sections())
    print(f"  Concept sections: {len(atoms) - new_count} atoms")

    new_count = len(atoms)
    atoms.extend(extract_tables_and_figures())
    print(f"  PDF supplement (Table 1, Figures 1+5): {len(atoms) - new_count} atoms")

    print(f"\n  TOTAL before metadata/embeddings: {len(atoms)} atoms")

    # Write intermediate file
    with open(_INTERMEDIATE_PATH, "w") as f:
        json.dump({"atoms": atoms}, f, indent=2)
    print(f"  Wrote intermediate atoms to {_INTERMEDIATE_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["extract", "classify", "embed", "assemble", "all"],
        default="all",
    )
    args = parser.parse_args()

    if args.stage in ("extract", "all"):
        stage_extract()

    if args.stage in ("classify", "all"):
        print("Stage 2 (classify) not yet implemented in this script")
        # TODO: call classify_atom_metadata.py

    if args.stage in ("embed", "all"):
        print("Stage 3 (embed) not yet implemented in this script")
        # TODO: embedding generation

    if args.stage in ("assemble", "all"):
        print("Stage 4 (assemble) not yet implemented in this script")
        # TODO: final assembly

    return 0


if __name__ == "__main__":
    sys.exit(main())
