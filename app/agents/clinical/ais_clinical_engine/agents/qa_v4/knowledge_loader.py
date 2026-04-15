"""
Knowledge loader — single read path for guideline section content
and concept-section routing.

This module is the qa_v4 wrapper around the canonical guideline data
loader (app/agents/clinical/ais_clinical_engine/data/loader.py) with
three additional responsibilities:

1. Resolve `_alias_of` stubs transparently. When Stage 3 POINTER lands
   and legacy keys like "Table 8" become aliases pointing at
   concept section IDs, `get_section()` and friends will still
   return the merged concept section content as if the legacy key
   were still populated directly. Callers don't need to know
   whether a section is legacy or concept, stub or not.

2. Expose concept-section-aware helpers. `iter_concept_sections()`
   yields only the decomposed concept sections. `get_concept_section()`
   fetches a single concept section by id.

3. Serve the concept-section dispatcher. Given a parsed Step 1 query
   (intent + anchor_terms), resolve to the concept section IDs the
   query should fetch. The dispatcher uses:

     - `intent_to_concept_index`: intent → [concept_section_id, ...]
       computed at load time from
       ais_guideline_section_map.json['concept_sections'][*]
       ['supported_intents']. This is the inversion-of-control
       approach from the handoff doc Q3 — concept sections
       self-declare the intents they answer.

     - `routing_keywords` narrowing: within the candidate set chosen
       by intent, keep concept sections whose `routing_keywords`
       overlap with the query's anchor_terms.

     - Keyword fallback: if intent dispatch returns nothing, fall
       back to pure routing_keywords match across every concept
       section.

Intent dispatch + keyword narrowing is deterministic and auditable.
The Step 1 LLM parser does anchor extraction; this module does the
deterministic lookup. No LLM call inside dispatch.

Important design decisions (locked in the handoff):
- Flat snake_case concept section IDs (Q2 Option A)
- No anchor term catalogue (Q3) — LLMs extract anchors at query
  time, this module only matches them against each concept
  section's small routing_keywords set
- Single read path: content_retriever and response_presenter both
  import from this module. No other code path reads
  guideline_knowledge.json directly.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Iterator, Optional

from ...data.loader import load_guideline_knowledge


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_SECTION_MAP_PATH = os.path.join(_REF_DIR, "ais_guideline_section_map.json")


# ──────────────────────────────────────────────────────────────────
# Section store (cached)
# ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_sections_store() -> dict[str, Any]:
    """Return the guideline sections dict, with aliases pre-resolved.

    Caches the result for the lifetime of the process. The underlying
    load_guideline_knowledge() in data/loader.py is also cached
    (@lru_cache), so this is a thin wrapper that adds alias resolution.
    """
    gk = load_guideline_knowledge()
    sections = gk.get("sections", {}) or {}
    # Alias resolution is on-demand inside get_section() and friends.
    # We don't pre-resolve here because it would require walking every
    # section at load time; a lazy approach is cheaper.
    return sections


def _raw_section(section_id: str) -> Optional[dict[str, Any]]:
    """Return the raw entry for a section, without alias resolution."""
    store = load_sections_store()
    entry = store.get(section_id)
    if not isinstance(entry, dict):
        return None
    return entry


def resolve_alias(entry: dict[str, Any]) -> dict[str, Any]:
    """Follow `_alias_of` if present, returning a merged view.

    A legacy key that has been converted to an alias stub looks like:
        { "_alias_of": ["concept_a", "concept_b"],
          "_deprecation": "..." }

    This function resolves the aliases by merging the pointed-to
    concept section contents:
      - rss rows: concatenated in order
      - synopsis: joined with a blank line between
      - knowledgeGaps: joined with a blank line between
      - sectionTitle: from the first alias target
      - parentChapter / sourceCitation: from the first alias target

    If the entry has no _alias_of, returns it unchanged.
    """
    if not isinstance(entry, dict) or "_alias_of" not in entry:
        return entry

    targets = entry.get("_alias_of", []) or []
    if not isinstance(targets, list):
        return entry

    merged_rss: list[dict[str, Any]] = []
    merged_synopsis: list[str] = []
    merged_kg: list[str] = []
    first_title = ""
    first_chapter = ""
    first_citation = ""

    for target_id in targets:
        target = _raw_section(target_id)
        if target is None:
            logger.warning(
                "knowledge_loader: alias target %r not found while "
                "resolving %r", target_id, targets,
            )
            continue
        if "_alias_of" in target:
            # Nested alias — recurse once. Guard against loops via depth.
            target = resolve_alias(target)
        merged_rss.extend(target.get("rss", []) or [])
        syn = target.get("synopsis", "") or ""
        if syn:
            merged_synopsis.append(syn)
        kg = target.get("knowledgeGaps", "") or ""
        if kg:
            merged_kg.append(kg)
        if not first_title:
            first_title = target.get("sectionTitle", "") or ""
        if not first_chapter:
            first_chapter = target.get("parentChapter", "") or ""
        if not first_citation:
            first_citation = target.get("sourceCitation", "") or ""

    return {
        "sectionTitle": first_title,
        "parentChapter": first_chapter,
        "sourceCitation": first_citation,
        "synopsis": "\n\n".join(merged_synopsis),
        "rss": merged_rss,
        "knowledgeGaps": "\n\n".join(merged_kg),
        "_resolved_from_aliases": targets,
    }


def get_section(section_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single section by id, following _alias_of if present.

    Returns None if the id is not in the store.
    """
    raw = _raw_section(section_id)
    if raw is None:
        return None
    return resolve_alias(raw)


def get_sections_by_ids(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Bulk lookup. Missing ids are omitted from the result."""
    out: dict[str, dict[str, Any]] = {}
    for sid in ids:
        entry = get_section(sid)
        if entry is not None:
            out[sid] = entry
    return out


def iter_concept_sections() -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (id, entry) pairs for every concept section.

    Identifies concept sections by presence of a top-level
    concept_sections[id] entry in ais_guideline_section_map.json,
    NOT by scanning the content store. Concept section IDs follow
    the snake_case descriptive pattern (absolute_contraindications_ivt,
    sich_management_post_ivt, etc.).
    """
    catalogue = load_concept_section_catalogue()
    for concept_id in catalogue:
        entry = get_section(concept_id)
        if entry is not None:
            yield concept_id, entry


# ──────────────────────────────────────────────────────────────────
# Concept section catalogue (routing-layer metadata)
# ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def load_concept_section_catalogue() -> dict[str, dict[str, Any]]:
    """Return the concept_sections{} dict from ais_guideline_section_map.json.

    Each entry has the 8-field schema:
        id, title, description, when_to_route, routing_keywords,
        supported_intents, parentChapter, sourceCitation
    """
    try:
        with open(_SECTION_MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(
            "knowledge_loader: could not load section map at %s: %s",
            _SECTION_MAP_PATH, e,
        )
        return {}
    catalogue = data.get("concept_sections", {}) or {}
    if not isinstance(catalogue, dict):
        return {}
    return catalogue


@lru_cache(maxsize=1)
def build_intent_to_concept_index() -> dict[str, list[str]]:
    """Reverse index: intent name → list of concept section IDs that
    declare they support that intent.

    Built once at load time from the catalogue's `supported_intents`
    field on each concept section entry. Intent taxonomy lives in
    intent_content_source_map.json and is NOT edited by the migration
    — the inversion-of-control pattern means concept sections
    self-declare which intents they answer.
    """
    catalogue = load_concept_section_catalogue()
    index: dict[str, list[str]] = {}
    for concept_id, entry in catalogue.items():
        intents = entry.get("supported_intents", []) or []
        for intent in intents:
            if not isinstance(intent, str):
                continue
            index.setdefault(intent, []).append(concept_id)
    return index


# ──────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────


# Common English words that are NOT clinical entities. Filtered out of
# the dispatch search terms so generic verbs like "manage" don't
# false-match clinical phrases like "airway management".
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "doing", "done",
    "will", "would", "could", "should", "shall", "may", "might",
    "can", "must", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "into", "about", "between", "through",
    "during", "before", "after", "above", "below", "out", "off",
    "over", "under", "up", "down", "than", "too", "very",
    "and", "or", "but", "nor", "so", "yet", "if", "because",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "their", "theirs", "them", "he", "she", "his", "her", "hers",
    "how", "what", "when", "where", "who", "whose", "which", "why",
    "i", "you", "your", "yours", "my", "mine", "we", "us", "our",
    "manage", "management", "treat", "treatment", "treated",
    "give", "giving", "gave", "given", "take", "taking", "taken",
    "use", "used", "using", "make", "making", "made",
    "patient", "patients", "person", "people", "clinician", "doctor",
    "consider", "considered", "considering",
    "need", "needs", "needed", "want", "wants", "wanted",
    "show", "shows", "showed", "shown",
    "recommend", "recommended", "recommendation",
})


def _word_match(term: str, kw: str) -> bool:
    """True if term matches kw as a whole word (either direction).

    Requires word-boundary matching so "manage" doesn't match
    "management" and "ich" doesn't match "rich". Exact equality
    also counts.
    """
    if not term or not kw:
        return False
    if term == kw:
        return True
    import re
    # Allow the shorter string to appear as a whole word in the longer
    if len(term) >= 4 and re.search(rf"\b{re.escape(term)}\b", kw):
        return True
    if len(kw) >= 4 and re.search(rf"\b{re.escape(kw)}\b", term):
        return True
    return False


def dispatch_concept_sections(
    intent: Optional[str],
    anchor_terms: Optional[dict[str, Any] | list[str]] = None,
    raw_query: Optional[str] = None,
) -> list[str]:
    """Route a parsed Step 1 query to concept section IDs.

    Inputs:
        intent       — the intent name from intent_content_source_map.json,
                       e.g. "contraindications", "dosing_protocol".
        anchor_terms — clinical entity names extracted by the Step 1 LLM
                       (canonicalized via intent_map.concept_expansions).
                       Accepts either a dict (keys = terms, values =
                       anchor values) or a list of bare term strings.
        raw_query    — optional full query text as a keyword-match
                       fallback when anchor_terms is empty or sparse.

    Returns an ordered list of concept section IDs to fetch. Ordered
    by match score descending — the highest-confidence match first.
    Empty list means no concept section match; the caller should fall
    back to the legacy ranked-search path.

    Dispatch algorithm:
      1. Intent → candidate concept sections via reverse index.
      2. Within candidates, score each by routing_keywords overlap
         with (anchor_terms ∪ raw_query words).
      3. If intent match returned no candidates, fall back to scoring
         every concept section on routing_keywords alone.
      4. Return the sorted candidate IDs (highest score first).

    This is deterministic and auditable. No LLM call.
    """
    catalogue = load_concept_section_catalogue()
    if not catalogue:
        return []

    # Normalize anchor_terms to a lowercase set of strings
    anchor_set: set[str] = set()
    if isinstance(anchor_terms, dict):
        anchor_set = {str(k).lower() for k in anchor_terms.keys() if k}
    elif isinstance(anchor_terms, list):
        anchor_set = {str(t).lower() for t in anchor_terms if t}

    # Harvest keywords from raw query text as a fallback source.
    # Filter out common English stopwords so generic verbs and
    # function words don't false-match clinical phrases.
    query_words: set[str] = set()
    if raw_query:
        import re
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-/]{2,}", raw_query):
            t = tok.lower()
            if t not in _STOP_WORDS:
                query_words.add(t)

    # Also drop stopwords from anchor_set (defensive; the Step 1 LLM
    # should not emit stopwords as anchors, but guard anyway)
    anchor_set = {a for a in anchor_set if a not in _STOP_WORDS}

    search_terms = anchor_set | query_words

    # Step 1: intent dispatch
    intent_index = build_intent_to_concept_index()
    candidates: list[str] = []
    if intent and intent in intent_index:
        candidates = list(intent_index[intent])

    # Step 2: score candidates by routing_keywords overlap
    scored: list[tuple[float, str]] = []
    for concept_id in candidates:
        entry = catalogue.get(concept_id, {})
        kw_set = {
            str(k).lower() for k in entry.get("routing_keywords", []) or []
        }
        if not kw_set:
            # Concept has no routing keywords; use intent match alone as a
            # low-confidence signal
            scored.append((0.1, concept_id))
            continue
        overlap = 0
        for term in search_terms:
            for kw in kw_set:
                if _word_match(term, kw):
                    overlap += 1
                    break
        # Intent-match score + overlap count
        scored.append((1.0 + overlap, concept_id))

    # Step 3: fallback — if intent dispatch returned nothing AND we have
    # search terms, score every concept section by keyword overlap only
    if not scored and search_terms:
        for concept_id, entry in catalogue.items():
            kw_set = {
                str(k).lower() for k in entry.get("routing_keywords", []) or []
            }
            if not kw_set:
                continue
            overlap = 0
            for term in search_terms:
                for kw in kw_set:
                    if _word_match(term, kw):
                        overlap += 1
                        break
            if overlap > 0:
                scored.append((float(overlap), concept_id))

    if not scored:
        return []

    # Sort by score descending, then id for determinism
    scored.sort(key=lambda x: (-x[0], x[1]))
    result = [cid for _, cid in scored]

    logger.info(
        "knowledge_loader.dispatch: intent=%r anchors=%s → %d concept "
        "sections: %s",
        intent, sorted(anchor_set) if anchor_set else None,
        len(result), result,
    )
    return result
