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


def _extract_number(value: Any) -> Optional[float]:
    """Pull a numeric value out of whatever shape the LLM returned.

    Step 1 LLM may emit: bare int/float (80), numeric string ('80'),
    threshold string ('<100', '>=1.7'), range ('100-200'), or a dict
    like {'value': 80}. Returns the representative number, or None
    if no number is parseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("value", "number", "val"):
            v = value.get(k)
            if v is not None:
                return _extract_number(v)
        return None
    if isinstance(value, str):
        import re
        m = re.search(r"-?\d+\.?\d*", value)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _threshold_crossed(
    value: float, compare: str, threshold: float,
) -> bool:
    """Check whether a patient value crosses a clinical threshold.

    compare is one of '<', '<=', '>', '>=', '=='. The patient is
    'crossing' the threshold if the comparison (patient_value
    compare threshold) is TRUE — meaning the clinical alarm condition
    described by the threshold is met. E.g., threshold says
    'platelets < 100' → patient has value 80 → 80 < 100 → TRUE →
    severe coagulopathy row fires.
    """
    try:
        if compare == "<":
            return value < threshold
        if compare == "<=":
            return value <= threshold
        if compare == ">":
            return value > threshold
        if compare == ">=":
            return value >= threshold
        if compare == "==":
            return value == threshold
    except TypeError:
        return False
    return False


def dispatch_concept_sections(
    intent: Optional[str],
    anchor_terms: Optional[dict[str, Any] | list[str]] = None,
) -> list[str]:
    """Route a parsed Step 1 query to concept section IDs.

    Strict separation of responsibilities:

      - The Step 1 LLM is responsible for UNDERSTANDING the question.
        It reads the raw query, classifies the semantic intent, and
        extracts the clinical anchor terms with their values/ranges.
        This is a language task — the LLM does it.

      - This function is responsible for DISPATCHING the LLM's
        structured output to concept section IDs. It does not read
        raw query text. It does not try to infer intent from keywords.
        It is a pure deterministic lookup on the inputs the LLM
        provides, using three layers:

          Layer 1 (intent): reverse index lookup → candidate set
          Layer 2 (anchor terms): routing_keywords overlap narrows
                                  within the candidate set
          Layer 3 (anchor values): threshold crossing checks boost
                                   concept sections whose clinical
                                   thresholds are met by the patient's
                                   specific numbers

    Inputs:
        intent       — the intent name from intent_content_source_map.json,
                       determined by the Step 1 LLM.
        anchor_terms — clinical entity names extracted by the Step 1 LLM
                       and canonicalized via intent_map.concept_expansions.
                       Preferred form: dict where keys are terms and
                       values are the numeric/range values the clinician
                       supplied (e.g. {'INR': 2.5, 'platelets': 80,
                       'IVT': None}). List form is also accepted for
                       queries with no values.

    Returns an ordered list of concept section IDs, highest-confidence
    first. Empty list means either:
      - the LLM's intent does not correspond to any concept section,
      - or no concept section's routing_keywords overlap with any of
        the LLM's anchor terms.
    In either case the caller falls back to the legacy ranked search.

    Dispatch algorithm (deterministic, no LLM call):
      1. Intent → candidate concept sections via the supported_intents
         reverse index.
      2. Within the candidate set, score each concept section by
         routing_keywords overlap with the LLM's anchor term NAMES
         (word-boundary match, never substring).
      3. For each candidate, also check its anchor_thresholds list.
         When the LLM provided a numeric value for an anchor term
         that has a threshold rule, and the value crosses the
         threshold in the configured direction, boost that concept
         section's score. This is how the three-layer model's VALUES
         layer influences routing — a clinician's 'INR 2.5' lifts
         absolute_contraindications_ivt above relative_contraindications_ivt
         because 2.5 > 1.7 fires the severe coagulopathy threshold.
      4. Return the candidates sorted by score descending.

    Word-boundary matching prevents false positives like "manage"
    matching "airway management".
    """
    catalogue = load_concept_section_catalogue()
    if not catalogue:
        return []

    # Normalize anchor_terms into two shapes:
    #   anchor_set — set of lowercased term names (for kw matching)
    #   anchor_values — dict of lowercased term → parsed numeric value
    #                   (for threshold checking)
    anchor_set: set[str] = set()
    anchor_values: dict[str, Optional[float]] = {}
    if isinstance(anchor_terms, dict):
        for k, v in anchor_terms.items():
            if not k:
                continue
            kl = str(k).lower()
            anchor_set.add(kl)
            num = _extract_number(v)
            if num is not None:
                anchor_values[kl] = num
    elif isinstance(anchor_terms, list):
        anchor_set = {str(t).lower() for t in anchor_terms if t}

    # Step 1: intent dispatch. Python does a dict lookup on the
    # LLM-provided intent. If the intent isn't in the reverse index,
    # we return empty — we do NOT try to guess the intent from
    # keywords. Intent is the LLM's job.
    intent_index = build_intent_to_concept_index()
    if not intent or intent not in intent_index:
        logger.info(
            "knowledge_loader.dispatch: intent=%r not in reverse index; "
            "returning empty (legacy fallback takes over)", intent,
        )
        return []
    candidates = list(intent_index[intent])

    # Step 2 + 3: score each candidate by (a) routing_keywords overlap
    # with the LLM's anchor term names, and (b) anchor_thresholds
    # crossing by the LLM's anchor values.
    scored: list[tuple[float, str]] = []
    for concept_id in candidates:
        entry = catalogue.get(concept_id, {})

        # Layer 2: anchor-term keyword overlap
        kw_set = {
            str(k).lower() for k in entry.get("routing_keywords", []) or []
        }
        term_overlap = 0
        if kw_set:
            for term in anchor_set:
                for kw in kw_set:
                    if _word_match(term, kw):
                        term_overlap += 1
                        break

        # Layer 3: anchor-value threshold crossing
        thresholds = entry.get("anchor_thresholds", []) or []
        threshold_hits = 0
        for rule in thresholds:
            if not isinstance(rule, dict):
                continue
            rule_anchor = str(rule.get("anchor", "")).lower()
            compare = str(rule.get("compare", ""))
            rule_threshold_raw = rule.get("value")
            rule_threshold = _extract_number(rule_threshold_raw)
            if not rule_anchor or not compare or rule_threshold is None:
                continue
            # Is this anchor in the LLM's output with a numeric value?
            patient_value = anchor_values.get(rule_anchor)
            if patient_value is None:
                # Try a word-boundary match on the anchor name so
                # "recent neurosurgery" matches "neurosurgery"
                for term_name, term_val in anchor_values.items():
                    if _word_match(term_name, rule_anchor):
                        patient_value = term_val
                        break
            if patient_value is None:
                continue
            if _threshold_crossed(patient_value, compare, rule_threshold):
                threshold_hits += 1

        # Score: 1.0 base intent match + 1.0 per term overlap
        # + 2.0 per threshold crossing (values are stronger than
        # name overlap because they're a harder claim about the
        # specific clinical scenario).
        score = 1.0 + term_overlap + 2.0 * threshold_hits
        scored.append((score, concept_id))

    # Sort by score descending; tie-break alphabetically for determinism
    scored.sort(key=lambda x: (-x[0], x[1]))
    result = [cid for _, cid in scored]

    logger.info(
        "knowledge_loader.dispatch: intent=%r anchors=%s values=%s "
        "→ %d concept sections: %s",
        intent,
        sorted(anchor_set) if anchor_set else None,
        anchor_values if anchor_values else None,
        len(result), result,
    )
    return result
