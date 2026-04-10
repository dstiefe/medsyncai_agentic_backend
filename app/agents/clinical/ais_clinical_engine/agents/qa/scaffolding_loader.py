"""
scaffolding_loader.py — single entry point for the mandatory cognitive
scaffolding used by the v2 Q&A pipeline.

The LLM is NOT allowed to freelance on clinical content. Every question must
be processed with reference to these four files:

    1. data_dictionary.v2.json     — sections, variables, parsed_values,
                                      section-level synonym_term_ids,
                                      review_flags
    2. synonym_dictionary.v2.json  — canonical terms, reverse_index,
                                      overload_table
    3. guideline_topic_map.json    — topic → section (deterministic routing)
    4. intent_catalog.json         — 33 intents: required_slots + answer_shape

The loader also exposes a reconciliation layer for the gtm↔dd.v2 granularity
mismatch: gtm has parent nodes (e.g. 4.7 "Mechanical Thrombectomy") while
dd.v2 stores the sub-sections (4.7.1..4.7.5). Section router callers should
resolve via `resolve_section_family()` which returns all children of a gtm
parent that exist in dd.v2.

This module is pure / side-effect free. All disk reads happen at construction
time. Callers get a single `ScaffoldingBundle` and pass it around.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")


def _load(name: str) -> dict:
    with open(os.path.join(_REF_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class ScaffoldingBundle:
    """In-memory, read-only view of the four scaffolding files."""

    data_dict: Dict[str, Any]
    synonym_dict: Dict[str, Any]
    topic_map: Dict[str, Any]
    intent_catalog: Dict[str, Any]

    # derived indices
    dd_sections: Set[str] = field(default_factory=set)
    gtm_sections: Set[str] = field(default_factory=set)
    gtm_by_section: Dict[str, dict] = field(default_factory=dict)
    gtm_parent_to_children: Dict[str, List[str]] = field(default_factory=dict)
    review_flagged_sections: Set[str] = field(default_factory=set)
    synonym_term_to_sections: Dict[str, Set[str]] = field(default_factory=dict)
    section_to_anchor_terms: Dict[str, Set[str]] = field(default_factory=dict)
    overload_table: Dict[str, dict] = field(default_factory=dict)
    reverse_index: Dict[str, List[str]] = field(default_factory=dict)

    # --- reconciliation helpers -------------------------------------------

    def resolve_section_family(self, section_id: str) -> List[str]:
        """
        Given a section_id that may be a gtm parent (e.g. '4.7') or a dd.v2
        sub-section (e.g. '4.7.3'), return the list of dd.v2 sections to
        actually consult.

        - If section_id exists in dd.v2: return [section_id].
        - If section_id is a gtm parent with children in dd.v2: return
          those children.
        - Otherwise: return []
        """
        if section_id in self.dd_sections:
            return [section_id]
        children = self.gtm_parent_to_children.get(section_id, [])
        return [c for c in children if c in self.dd_sections]

    def is_review_flagged(self, section_id: str) -> bool:
        return section_id in self.review_flagged_sections

    def section_anchor_terms(self, section_id: str) -> Set[str]:
        """Return the section-level synonym_term_ids (term IDs that anchor
        this section for router intersection matching)."""
        return self.section_to_anchor_terms.get(section_id, set())

    def intent(self, name: str) -> Optional[dict]:
        return self.intent_catalog.get("intents", {}).get(name)

    def topic_entry(self, section_id: str) -> Optional[dict]:
        return self.gtm_by_section.get(section_id)

    def overload_entry(self, token: str) -> Optional[dict]:
        return self.overload_table.get(token)


def _build_bundle(
    dd: dict, sd: dict, gtm: dict, ic: dict
) -> ScaffoldingBundle:
    dd_sections = set(dd.get("sections", {}).keys())

    # --- gtm indexing ------------------------------------------------------
    gtm_by_section: Dict[str, dict] = {}
    gtm_sections: Set[str] = set()
    for t in gtm.get("topics", []):
        sec = t.get("section")
        if not sec:
            continue
        gtm_sections.add(sec)
        gtm_by_section[sec] = t

    # --- parent → children map (handles 4.7 → 4.7.1..4.7.5 etc.) ---------
    parent_to_children: Dict[str, List[str]] = {}
    for dd_sec in dd_sections:
        # split on '.' and walk up: "4.7.3" -> candidates "4.7", "4"
        parts = dd_sec.split(".")
        for i in range(len(parts) - 1, 0, -1):
            parent = ".".join(parts[:i])
            if parent == dd_sec:
                continue
            parent_to_children.setdefault(parent, []).append(dd_sec)
    # sort children for stability
    for k in parent_to_children:
        parent_to_children[k] = sorted(set(parent_to_children[k]))

    # --- review_flags ------------------------------------------------------
    review_flagged: Set[str] = set()
    for sid, sec in dd.get("sections", {}).items():
        rf = sec.get("review_flags") or {}
        if rf.get("needs_review"):
            review_flagged.add(sid)

    # --- anchor terms from dd.v2 section-level synonym_term_ids ----------
    section_to_anchor: Dict[str, Set[str]] = {}
    term_to_sections: Dict[str, Set[str]] = {}
    for sid, sec in dd.get("sections", {}).items():
        anchors = set(sec.get("synonym_term_ids") or [])
        if anchors:
            section_to_anchor[sid] = anchors
            for t in anchors:
                term_to_sections.setdefault(t, set()).add(sid)
        # also index intervention-level synonym_term_ids so the router can
        # match interventions too
        iv = sec.get("intervention")
        if isinstance(iv, dict):
            for t in iv.get("synonym_term_ids") or []:
                term_to_sections.setdefault(t, set()).add(sid)

    return ScaffoldingBundle(
        data_dict=dd,
        synonym_dict=sd,
        topic_map=gtm,
        intent_catalog=ic,
        dd_sections=dd_sections,
        gtm_sections=gtm_sections,
        gtm_by_section=gtm_by_section,
        gtm_parent_to_children=parent_to_children,
        review_flagged_sections=review_flagged,
        synonym_term_to_sections=term_to_sections,
        section_to_anchor_terms=section_to_anchor,
        overload_table=sd.get("overload_table") or {},
        reverse_index=sd.get("reverse_index") or {},
    )


def validate_intent_enum_matches_catalog(bundle: ScaffoldingBundle) -> List[str]:
    """
    Confirm the VnIntent enum and intent_catalog.json have the same keys.
    Drift here means someone edited one file without the other — catch it
    at startup so it fails loudly instead of leaking into a silent bug.
    """
    # local import to avoid circular dependency with schemas.py
    from .schemas import VnIntent

    enum_keys = {m.value for m in VnIntent}
    catalog_keys = set(bundle.intent_catalog.get("intents", {}).keys())
    errors: List[str] = []
    missing_from_enum = catalog_keys - enum_keys
    missing_from_catalog = enum_keys - catalog_keys
    if missing_from_enum:
        errors.append(
            f"[enum] intent_catalog has intents not in VnIntent enum: "
            f"{sorted(missing_from_enum)}"
        )
    if missing_from_catalog:
        errors.append(
            f"[enum] VnIntent enum has members not in intent_catalog: "
            f"{sorted(missing_from_catalog)}"
        )
    return errors


def validate_bundle(bundle: ScaffoldingBundle) -> List[str]:
    """
    Run the Step 0 alignment checks and return a list of problems. Empty
    list = all green. Callers (startup hooks, tests) should fail loudly if
    this returns anything.
    """
    errors: List[str] = []

    # enum ↔ catalog drift check (runs first so downstream checks are safe)
    errors.extend(validate_intent_enum_matches_catalog(bundle))

    # 0.1 intent_catalog must not reference sections that don't exist in gtm
    # (catalog currently doesn't hardcode sections — per-intent rules drive
    # routing — but if a future edit adds candidate_sections we still want
    # to catch drift)
    for name, intent in bundle.intent_catalog.get("intents", {}).items():
        for key in ("candidate_sections", "sections", "default_sections"):
            for s in intent.get(key, []) or []:
                if s not in bundle.gtm_sections and s not in bundle.dd_sections:
                    errors.append(
                        f"[0.1] intent '{name}' references unknown section '{s}'"
                    )

    # 0.2 dd.v2 sections should be reachable from gtm (direct or via parent)
    for s in bundle.dd_sections:
        if s in bundle.gtm_sections:
            continue
        # check if any ancestor is a gtm parent
        parts = s.split(".")
        ok = False
        for i in range(len(parts) - 1, 0, -1):
            if ".".join(parts[:i]) in bundle.gtm_sections:
                ok = True
                break
        if not ok:
            errors.append(f"[0.2] dd.v2 section '{s}' has no gtm topic entry")

    # 0.2b gtm sections without a dd.v2 entry and no children in dd.v2
    for s in bundle.gtm_sections:
        if s in bundle.dd_sections:
            continue
        children = bundle.gtm_parent_to_children.get(s, [])
        if not any(c in bundle.dd_sections for c in children):
            errors.append(
                f"[0.2] gtm section '{s}' has no dd.v2 section or children"
            )

    # 0.3 synonym_term_ids referenced by dd.v2 must exist in synonym_dict
    known_terms = set(bundle.synonym_dict.get("terms", {}).keys())
    for sid, sec in bundle.data_dict.get("sections", {}).items():
        for t in sec.get("synonym_term_ids") or []:
            if t not in known_terms:
                errors.append(
                    f"[0.3] section '{sid}' references unknown synonym term "
                    f"'{t}'"
                )
        iv = sec.get("intervention")
        if isinstance(iv, dict):
            for t in iv.get("synonym_term_ids") or []:
                if t not in known_terms:
                    errors.append(
                        f"[0.3] section '{sid}'.intervention references "
                        f"unknown synonym term '{t}'"
                    )

    return errors


@lru_cache(maxsize=1)
def get_scaffolding() -> ScaffoldingBundle:
    """
    Load the scaffolding bundle from disk. Cached so repeated agent
    construction doesn't re-parse the files.
    """
    dd = _load("data_dictionary.v2.json")
    sd = _load("synonym_dictionary.v2.json")
    gtm = _load("guideline_topic_map.json")
    ic = _load("intent_catalog.json")
    return _build_bundle(dd, sd, gtm, ic)


def reset_scaffolding_cache() -> None:
    """Clear the module-level cache (for tests)."""
    get_scaffolding.cache_clear()


__all__ = [
    "ScaffoldingBundle",
    "get_scaffolding",
    "reset_scaffolding_cache",
    "validate_bundle",
]
