# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Stage 2 SWITCH: atom-level retrieval.
#
# Background: the pre-atom retrieval path returned every row of a
# matched table as a block, so a query like "severe headache after
# IVT" dumped all of Table 7 (dosing bullets, line placement, BP,
# imaging, pediatric footnotes) instead of the single row that
# answers the question. The fix is to make the ROW — not the table
# or the section — the retrieval unit.
#
# Stage 1 (ATOMIZE) added an atoms[] array under each migrated
# section in guideline_knowledge.json. Every atom carries its own
# parent_section, parent_display_group, anchor_terms, intent_affinity
# and value_ranges.
#
# This module is the Stage 2 reader. It:
#   1. Lazy-loads a flat index of every atom across every section
#      on first call, keyed by section_id and also stored as a
#      global list (for future cross-section atom search).
#   2. Exposes select_atoms_for_section(section_id, parsed_query, k)
#      which returns ranked atoms from one section, or None if the
#      section has not been atomized yet (legacy fallback).
#
# Ranking weights (locked with user):
#   0.5  — intent affinity match (parsed.intent ∈ atom.intent_affinity)
#   0.4  — anchor-term Jaccard overlap (with concept_expansions applied
#          to the query side so "IVT" resolves to "alteplase" +
#          "tenecteplase" before matching)
#   0.1  — value-range satisfaction (parsed.anchor_values fall inside
#          atom.value_ranges thresholds)
#
# Threshold: an atom must score ≥ 0.15 to be kept. If no atoms clear
# the threshold for a section that IS atomized, we fall back to
# returning every atom in PDF order — the clinician always gets the
# full row set they would have seen under legacy behavior, just in
# atom shape.
# ───────────────────────────────────────────────────────────────────────
"""
Atom-level retrieval for qa_v4 (Stage 2 SWITCH).

Replaces section-level row dumping with row-level selection for any
section that has been migrated to the atom schema.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)


# ── File locations ──────────────────────────────────────────────────

# v5 unified atoms file — preferred. Falls back to legacy atomized
# file if v5 is not present (e.g., during transition).
_V5_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "guideline_knowledge.atomized.v5.json",
)
_LEGACY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "guideline_knowledge.atomized.json",
)
_KNOWLEDGE_PATH = _V5_PATH if os.path.exists(_V5_PATH) else _LEGACY_PATH
_INTENT_MAP_PATH = os.path.join(
    os.path.dirname(__file__),
    "references", "intent_map.json",
)


# ── Scoring weights (locked with user) ──────────────────────────────

_W_INTENT = 0.5
_W_ANCHOR = 0.4
_W_VALUE = 0.1

# Atoms below this score are dropped. Tuned so an atom matching on
# intent alone (0.5) or anchor alone (≥0.375 overlap) survives, but
# an atom that shares only one weak anchor with a long query does not.
_SCORE_THRESHOLD = 0.15


# ── Lazy-loaded indexes ─────────────────────────────────────────────

# Section-keyed atom index: {section_id: [atom, ...]}
_section_atoms_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None

# Flat list of every atom (future cross-section retrieval).
_flat_atom_cache: Optional[List[Dict[str, Any]]] = None

# Concept expansions from intent_map.json, used to widen query-side
# anchor terms before matching atom-side anchors.
_concept_expansions_cache: Optional[Dict[str, List[str]]] = None


def _load_indexes() -> None:
    """Build atom indexes from guideline_knowledge.json on first use.

    Walks sections[].atoms[] and stores every atom both in a section
    map and a flat list. Atoms without the required schema fields are
    skipped with a warning so a bad migration can never silently
    break retrieval.
    """
    global _section_atoms_cache, _flat_atom_cache
    if _section_atoms_cache is not None and _flat_atom_cache is not None:
        return

    section_map: Dict[str, List[Dict[str, Any]]] = {}
    flat: List[Dict[str, Any]] = []

    try:
        with open(_KNOWLEDGE_PATH, "r") as f:
            kb = json.load(f)
    except Exception as e:
        logger.warning(
            "atom_retriever: could not load knowledge store at %s: %s",
            _KNOWLEDGE_PATH, e,
        )
        _section_atoms_cache = {}
        _flat_atom_cache = []
        return

    # Handle two formats:
    #   v5 format: {"atoms": [...]}  — flat list, each atom carries
    #              parent_section and atom_type directly.
    #   legacy:   {"sections": {sec_id: {"atoms": [...]}, ...}}
    v5_atoms = kb.get("atoms")
    if isinstance(v5_atoms, list):
        # v5 flat format — index by parent_section AND by category,
        # so callers can look up atoms by concept section ID
        # (which matches atom.category via category_filter).
        for atom in v5_atoms:
            if not isinstance(atom, dict):
                continue
            if not atom.get("atom_id") or not atom.get("text"):
                logger.warning(
                    "atom_retriever: dropping malformed v5 atom: %r",
                    atom.get("atom_id", "?"),
                )
                continue
            sec_id = atom.get("parent_section", "")
            atom.setdefault(
                "parent_display_group",
                atom.get("section_title", sec_id),
            )
            atom.setdefault("atom_type", "bullet")
            atom.setdefault("anchor_terms", [])
            atom.setdefault("intent_affinity", [])
            atom.setdefault("value_ranges", {})
            section_map.setdefault(sec_id, []).append(atom)
            # Also index by category so concept section IDs resolve.
            # (In v5, atoms tagged category='antiplatelet_ivt_interaction'
            # all live under parent_section='4.8' but should also be
            # findable via section_map['antiplatelet_ivt_interaction'].)
            cat = atom.get("category", "")
            if cat and cat != sec_id:
                section_map.setdefault(cat, []).append(atom)
            flat.append(atom)
    else:
        # Legacy sectioned format
        sections = kb.get("sections", {}) or {}
        for sec_id, sec_body in sections.items():
            atoms = sec_body.get("atoms") or []
            if not atoms:
                continue
            kept: List[Dict[str, Any]] = []
            for atom in atoms:
                if not isinstance(atom, dict):
                    continue
                if not atom.get("atom_id") or not atom.get("text"):
                    logger.warning(
                        "atom_retriever: dropping malformed atom in %s: %r",
                        sec_id, atom.get("atom_id", "?"),
                    )
                    continue
                # Defensive defaults so downstream code never crashes on
                # a partially-tagged atom.
                atom.setdefault("parent_section", sec_id)
                atom.setdefault(
                    "parent_display_group",
                    sec_body.get("sectionTitle", sec_id),
                )
                atom.setdefault("atom_type", "bullet")
                atom.setdefault("anchor_terms", [])
                atom.setdefault("intent_affinity", [])
                atom.setdefault("value_ranges", {})
                kept.append(atom)
                flat.append(atom)
            if kept:
                section_map[sec_id] = kept

    _section_atoms_cache = section_map
    _flat_atom_cache = flat
    logger.info(
        "atom_retriever: indexed %d atoms across %d sections",
        len(flat), len(section_map),
    )


def _load_concept_expansions() -> Dict[str, List[str]]:
    """Load {term: [expanded_terms]} from intent_map.json concept_expansions.

    Keys are normalized to lowercase. Values are lists of lowercased
    target terms. If the file is missing or malformed we return an
    empty dict — expansion is an enhancement, not a requirement.
    """
    global _concept_expansions_cache
    if _concept_expansions_cache is not None:
        return _concept_expansions_cache

    out: Dict[str, List[str]] = {}
    try:
        with open(_INTENT_MAP_PATH, "r") as f:
            im = json.load(f)
        raw = im.get("concept_expansions", {}) or {}
        for term, body in raw.items():
            if isinstance(body, dict):
                targets = body.get("expands_to", []) or []
                syns = body.get("synonyms", []) or []
                all_targets = [t.lower() for t in targets] + [
                    s.lower() for s in syns
                ]
                out[term.lower()] = all_targets
    except Exception as e:
        logger.warning(
            "atom_retriever: could not load concept_expansions at %s: %s",
            _INTENT_MAP_PATH, e,
        )
    _concept_expansions_cache = out
    return out


# ── Scoring primitives ──────────────────────────────────────────────


def _expand_query_anchors(parsed: ParsedQAQuery) -> Set[str]:
    """Return the full set of query-side anchor terms (lowercased).

    Each term in parsed.anchor_terms is added directly and also
    expanded via concept_expansions. "IVT" → {"ivt", "alteplase",
    "tenecteplase", "iv thrombolysis", ...}. This lets an atom whose
    text only contains "alteplase" match a query that only says "IVT".
    """
    expansions = _load_concept_expansions()
    out: Set[str] = set()
    for term in (parsed.anchor_terms or {}).keys():
        low = term.lower()
        out.add(low)
        for e in expansions.get(low, []):
            out.add(e)
    return out


def _score_atom(
    atom: Dict[str, Any],
    parsed: ParsedQAQuery,
    query_anchors: Set[str],
) -> Tuple[float, Dict[str, float]]:
    """Score one atom against the parsed query.

    Returns (total_score, breakdown). Breakdown is returned so the
    audit trail can show why an atom did or did not clear threshold.
    """
    breakdown = {"intent": 0.0, "anchor": 0.0, "value": 0.0}

    # Intent affinity ──────────────────────────────────────────────
    intent = parsed.intent or ""
    if intent and intent in (atom.get("intent_affinity") or []):
        breakdown["intent"] = _W_INTENT

    # Anchor Jaccard ───────────────────────────────────────────────
    atom_anchors = {a.lower() for a in (atom.get("anchor_terms") or [])}
    if query_anchors and atom_anchors:
        overlap = query_anchors & atom_anchors
        union = query_anchors | atom_anchors
        if union:
            breakdown["anchor"] = _W_ANCHOR * (len(overlap) / len(union))

    # Value range satisfaction ─────────────────────────────────────
    # For each anchor term with a value in the parsed query, check
    # whether the atom's value_ranges contains a matching key with a
    # compatible numeric range. This is deliberately lenient —
    # partial matches still earn partial credit — because value
    # range semantics differ per anchor (SBP is a threshold, ASPECTS
    # is a range, dose is a scalar).
    vranges = atom.get("value_ranges") or {}
    anchor_values = parsed.anchor_values if hasattr(parsed, "anchor_values") else {}
    if anchor_values and vranges:
        hits = 0
        checked = 0
        for key, qval in anchor_values.items():
            # Try a few key shapes the atom author might have used.
            candidates = [
                key, key.lower(), key.upper(),
                f"{key}_mmHg", f"{key.upper()}_mmHg",
                f"{key}_max", f"{key.upper()}_max_mmHg",
            ]
            matched_val = None
            for c in candidates:
                if c in vranges:
                    matched_val = vranges[c]
                    break
            if matched_val is None:
                continue
            checked += 1
            try:
                qnum = qval if isinstance(qval, (int, float)) else (
                    qval.get("min") if isinstance(qval, dict) else None
                )
                if qnum is None:
                    continue
                if isinstance(matched_val, (int, float)):
                    # Scalar threshold — match if query value is at
                    # or below the atom's max (SBP 180, max_dose 90).
                    if qnum <= matched_val:
                        hits += 1
                elif isinstance(matched_val, dict):
                    lo = matched_val.get("min")
                    hi = matched_val.get("max")
                    if (lo is None or qnum >= lo) and (hi is None or qnum <= hi):
                        hits += 1
            except Exception:
                continue
        if checked:
            breakdown["value"] = _W_VALUE * (hits / checked)

    total = breakdown["intent"] + breakdown["anchor"] + breakdown["value"]
    return total, breakdown


# ── Public API ──────────────────────────────────────────────────────


def section_has_atoms(section_id: str) -> bool:
    """Return True if the given section has been atomized."""
    _load_indexes()
    assert _section_atoms_cache is not None
    return section_id in _section_atoms_cache


def select_atoms_for_section(
    section_id: str,
    parsed: ParsedQAQuery,
    k: Optional[int] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Rank and return atoms for one section.

    Args:
        section_id: the guideline section id (e.g. "Table 7", "4.3").
        parsed: the Step 1 parsed query.
        k: optional cap on the number of atoms returned. None = no cap.

    Returns:
        - None if the section has not been atomized (caller should
          use legacy path).
        - A list of atom dicts (may be empty) for an atomized section.
          Atoms are ordered by score descending, with ties broken by
          the PDF order they appear in guideline_knowledge.json.

    Legacy-fallback guarantee: if a section IS atomized but no atom
    clears the score threshold, we return every atom for that section
    in PDF order. The clinician always sees the full row set they
    would have seen under legacy rendering — the switch from legacy
    to atoms must never reduce recall to zero.
    """
    _load_indexes()
    assert _section_atoms_cache is not None
    atoms = _section_atoms_cache.get(section_id)
    if atoms is None:
        return None  # not atomized — caller uses legacy path

    query_anchors = _expand_query_anchors(parsed)

    # If the query has no anchors AND no intent, we have nothing to
    # rank on — return PDF order so the legacy behavior is preserved.
    if not query_anchors and not (parsed.intent or ""):
        return list(atoms) if k is None else list(atoms)[:k]

    scored: List[Tuple[float, int, Dict[str, Any], Dict[str, float]]] = []
    for idx, atom in enumerate(atoms):
        total, breakdown = _score_atom(atom, parsed, query_anchors)
        scored.append((total, idx, atom, breakdown))

    # Keep atoms above threshold. When the query has anchors, we
    # also require the atom to share at least one anchor — an
    # intent-only match is too weak to justify surfacing a row. This
    # prevents a query about one row of a 37-row table (Table 8)
    # from leaking every row that happens to share the table's
    # intent affinity (contraindications / eligibility).
    has_query_anchors = bool(query_anchors)
    kept = []
    for t in scored:
        total, _idx, _atom, bd = t
        if total < _SCORE_THRESHOLD:
            continue
        if has_query_anchors and bd["anchor"] <= 0.0:
            continue
        kept.append(t)

    if not kept:
        logger.info(
            "atom_retriever: section %s atomized but no atoms cleared "
            "threshold for query anchors=%s intent=%s — falling back "
            "to full PDF order",
            section_id, sorted(query_anchors), parsed.intent,
        )
        result = list(atoms)
    else:
        # Sort by score desc, then by original PDF index ascending.
        kept.sort(key=lambda t: (-t[0], t[1]))
        result = [t[2] for t in kept]
        logger.info(
            "atom_retriever: section %s selected %d/%d atoms "
            "(query anchors=%s intent=%s)",
            section_id, len(result), len(atoms),
            sorted(query_anchors), parsed.intent,
        )

    if k is not None:
        result = result[:k]
    return result


def atoms_to_rss_rows(
    atoms: List[Dict[str, Any]],
    section_title: str = "",
) -> List[Dict[str, Any]]:
    """Convert atom dicts to the RSS row shape used by _build_detail.

    The Details panel renderer expects rows with keys:
        section, sectionTitle, recNumber, category, condition, text

    Atoms are an evolved schema with no recNumber and no free-form
    category. We map:
        section      <- atom["parent_section"]
        sectionTitle <- atom["parent_display_group"] (or provided)
        recNumber    <- atom["atom_id"]  (so citations can trace back)
        category     <- atom["atom_type"]
        condition    <- ""  (atoms are self-contained rows)
        text         <- atom["text"]
    """
    out: List[Dict[str, Any]] = []
    for atom in atoms:
        text = (atom.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "section": atom.get("parent_section", ""),
            "sectionTitle": (
                atom.get("parent_display_group") or section_title
            ),
            "recNumber": atom.get("atom_id", ""),
            "category": atom.get("atom_type", ""),
            "condition": "",
            "text": text,
            "_atom": True,  # marker so callers know this row is atom-derived
        })
    return out


def reset_caches() -> None:
    """Testing hook: clear all in-memory caches."""
    global _section_atoms_cache, _flat_atom_cache, _concept_expansions_cache
    _section_atoms_cache = None
    _flat_atom_cache = None
    _concept_expansions_cache = None
