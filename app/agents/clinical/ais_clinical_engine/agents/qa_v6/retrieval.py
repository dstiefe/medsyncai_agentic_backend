"""
qa_v6 unified retrieval.

ONE scoring function. ONE threshold. ONE pass over every atom.

For each atom, combine:
  - Semantic similarity (cosine on pre-computed atom embedding)
  - Intent affinity (query intent in atom.intent_affinity)
  - Pinpoint anchor coverage (specific clinical terms)
  - Global anchor match (generic terms like IVT/stroke — tiebreaker only)
  - Value range satisfaction (query value falls in atom's range)
  - Value-guided bonus (query has value + atom has numeric context)

Then group surviving atoms by atom_type for the presenter:
  - recommendation → rec cards
  - evidence_summary → RSS block (grouped by concept_category)
  - narrative_context → synopsis
  - evidence_gap → KG (only if intent requires)
  - table_row → tables
  - figure → figures

Ambiguity detection: if >MAX_RECS clear threshold AND span multiple
concept_categories AND cluster tightly, surface clarification options
instead of returning a scattered answer.
"""
from __future__ import annotations

import logging
import os
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import ParsedQAQuery, RetrievedContent, ScoredAtom
from . import scoring_config as cfg
from . import semantic_service

logger = logging.getLogger(__name__)

_REFS_DIR = os.path.join(
    os.path.dirname(__file__), "references",
)
_SECTION_MAP_PATH = os.path.join(
    _REFS_DIR, "ais_guideline_section_map.json",
)
_ANCHOR_WORDS_PATH = os.path.join(
    _REFS_DIR, "guideline_anchor_words.json",
)
_TOPIC_MAP_PATH = os.path.join(
    _REFS_DIR, "guideline_topic_map.json",
)


# ── Lazy-loaded reference data ────────────────────────────────────

_concept_sections_cache: Optional[Dict[str, Dict[str, Any]]] = None
_anchor_tiers_cache: Optional[Dict[str, str]] = None
# term_lower → "pinpoint" | "narrow" | "broad" | "global"
_topic_to_section_cache: Optional[Dict[str, str]] = None
# topic_name_lower → primary section number (e.g. "4.8")


def _normalize_topic_name(t: str) -> str:
    """Lowercase + collapse whitespace."""
    return " ".join(str(t or "").lower().split())


# Cached topic embeddings — computed once per process from the topic
# map. The map is a GUIDE, not an absolute: we use embeddings so the
# parser's topic string can match the map entry by semantic similarity
# even if the surface forms differ ("Antiplatelet Treatment" vs
# "Antiplatelet Therapy", "EVT" vs "Endovascular Thrombectomy").
_topic_embeddings_cache: Optional[Dict[str, Any]] = None
# Minimum cosine similarity for a fuzzy topic match. Below this the
# parser topic is too far from any map entry and we don't apply the
# bonus (safer than wrong bonus).
_TOPIC_MATCH_FLOOR = 0.50


def _get_topic_embeddings() -> Dict[str, Any]:
    """Lazy-load: embed each map topic once, using topic name +
    addresses description. {normalized_topic: vec}.

    The `addresses` field in guideline_topic_map.json describes what
    each topic covers (e.g. "Endovascular thrombectomy, mechanical
    thrombectomy, endovascular therapy for AIS..."). Embedding the
    combined text makes semantic matching robust across surface forms
    (short acronym ↔ long phrase, e.g. "EVT" ↔ "Endovascular
    Thrombectomy") without a hand-maintained alias list.
    """
    global _topic_embeddings_cache
    if _topic_embeddings_cache is not None:
        return _topic_embeddings_cache
    out: Dict[str, Any] = {}
    if not os.path.exists(_TOPIC_MAP_PATH) or not semantic_service.is_available():
        _topic_embeddings_cache = out
        return out
    try:
        with open(_TOPIC_MAP_PATH, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("topic map load failed: %s", e)
        _topic_embeddings_cache = out
        return out
    for entry in data.get("topics", []):
        topic = _normalize_topic_name(entry.get("topic") or "")
        if not topic:
            continue
        addresses = str(entry.get("addresses") or "").strip()
        # Combine topic name with its description for richer semantic
        # surface. Fall back to topic name alone if no addresses.
        combined = f"{entry.get('topic')}. {addresses}" if addresses else entry.get("topic") or topic
        try:
            out[topic] = semantic_service.embed_query(combined)
        except Exception as e:
            logger.debug("topic embed failed for %s: %s", topic, e)
    _topic_embeddings_cache = out
    return out


def _resolve_topic_to_section(topic: str) -> Optional[str]:
    """Resolve a parser topic string to a section, treating the topic
    map as a GUIDE not an absolute.

    Resolution order:
      1. Exact normalized match → use that
      2. Semantic nearest neighbour (cosine similarity across embedded
         map topics) → use that if similarity ≥ _TOPIC_MATCH_FLOOR
      3. None — no bonus applied (silent, not an error)

    No hand-maintained alias list. No string rules. Semantic proximity
    is the bridge between parser wording and map wording.
    """
    if not topic:
        return None
    m = _load_topic_to_section()
    if not m:
        return None
    norm = _normalize_topic_name(topic)

    # 1. Exact normalized match
    if norm in m:
        return m[norm]

    # 2. Semantic nearest neighbour
    try:
        import numpy as np
        if not semantic_service.is_available():
            return None
        q_emb = semantic_service.embed_query(norm)
        best_sim = 0.0
        best_topic = None
        for map_topic, emb in _get_topic_embeddings().items():
            sim = float(np.dot(q_emb, emb))
            if sim > best_sim:
                best_sim = sim
                best_topic = map_topic
        if best_topic and best_sim >= _TOPIC_MATCH_FLOOR:
            logger.debug(
                "topic fuzzy match: %r → %r (sim=%.2f)",
                topic, best_topic, best_sim,
            )
            return m[best_topic]
    except Exception as e:
        logger.debug("topic fuzzy match failed: %s", e)

    return None


def _load_topic_to_section() -> Dict[str, str]:
    """topic name (normalized) → primary section number ("4.7", "4.8" …).

    Read from guideline_topic_map.json. Used by the topic-alignment
    bonus so a Step 2b-confirmed topic actually influences scoring.
    Keys are normalized via _normalize_topic_name for lookup tolerance.
    """
    global _topic_to_section_cache
    if _topic_to_section_cache is not None:
        return _topic_to_section_cache
    if not os.path.exists(_TOPIC_MAP_PATH):
        logger.warning("Topic map missing at %s", _TOPIC_MAP_PATH)
        _topic_to_section_cache = {}
        return _topic_to_section_cache
    with open(_TOPIC_MAP_PATH, "r") as f:
        data = json.load(f)
    out: Dict[str, str] = {}
    for entry in data.get("topics", []):
        topic = _normalize_topic_name(entry.get("topic") or "")
        section = str(entry.get("section") or "").strip()
        if topic and section:
            out[topic] = section
    _topic_to_section_cache = out
    return out


def _topic_alignment_bonus(atom_section: str, topic_section: str) -> float:
    """Bonus when atom's parent_section matches the topic's primary section.

    Exact match                      → 1.0
    Atom is descendant of topic sec  → 1.0 (e.g. 4.7.4 within 4.7)
    Atom is ancestor of topic sec    → 0.5 (partial)
    No relationship                  → 0.0
    """
    if not atom_section or not topic_section:
        return 0.0
    a = str(atom_section).strip()
    t = str(topic_section).strip()
    if not a or not t:
        return 0.0
    if a == t:
        return 1.0
    if a.startswith(t + "."):
        return 1.0   # descendant — fully on-topic
    if t.startswith(a + "."):
        return 0.5   # ancestor — partial
    return 0.0


def _load_concept_sections() -> Dict[str, Dict[str, Any]]:
    """Load the concept section catalogue (one-shot, cached)."""
    global _concept_sections_cache
    if _concept_sections_cache is not None:
        return _concept_sections_cache
    if not os.path.exists(_SECTION_MAP_PATH):
        logger.warning("Section map missing at %s", _SECTION_MAP_PATH)
        _concept_sections_cache = {}
        return _concept_sections_cache
    with open(_SECTION_MAP_PATH, "r") as f:
        data = json.load(f)
    _concept_sections_cache = data.get("concept_sections", {}) or {}
    return _concept_sections_cache


def _load_anchor_tiers() -> Dict[str, str]:
    """Load the canonical anchor term tier map.

    Returns {term_lower: tier_name}. When a term appears in multiple
    sections with different tiers, keep the most discriminating one
    (pinpoint > narrow > broad > global).
    """
    global _anchor_tiers_cache
    if _anchor_tiers_cache is not None:
        return _anchor_tiers_cache

    tier_rank = {"pinpoint": 4, "narrow": 3, "broad": 2, "global": 1}
    tiers: Dict[str, str] = {}

    if not os.path.exists(_ANCHOR_WORDS_PATH):
        logger.warning(
            "anchor words file missing at %s", _ANCHOR_WORDS_PATH,
        )
        _anchor_tiers_cache = {}
        return _anchor_tiers_cache

    with open(_ANCHOR_WORDS_PATH, "r") as f:
        data = json.load(f)

    def _ingest(entries):
        if not isinstance(entries, list):
            return
        for e in entries:
            if not isinstance(e, dict):
                continue
            term = str(e.get("term", "")).lower()
            tier = str(e.get("tier", "broad")).lower()
            if not term:
                continue
            current = tiers.get(term)
            if current is None or tier_rank.get(tier, 0) > tier_rank.get(
                current, 0,
            ):
                tiers[term] = tier

    for sec_body in (data.get("sections") or {}).values():
        if not isinstance(sec_body, dict):
            continue
        words = sec_body.get("anchor_words", {})
        if isinstance(words, dict):
            for entries in words.values():
                _ingest(entries)

    _anchor_tiers_cache = tiers
    return tiers


# ── Query-side anchor classification ──────────────────────────────

# CMI schema field names that the parser uses as dict keys. The VALUE
# under these keys is the clinical content (an integer for numerics, an
# enum string for occlusion/intervention/circulation). The KEY itself
# is a variable name and is NOT a clinical term — it must not be fed
# into anchor string matching against the atom corpus.
# Parser intent → atom intent_affinity synonyms. The parser uses the
# 44-intent vocabulary from intent_content_source_map.json; atoms were
# classified with a broader freeform affinity list. Map parser intents
# to the atom-side synonyms they should hit.
_INTENT_SYNONYMS: Dict[str, Set[str]] = {
    "eligibility_check":       {"eligibility_criteria", "patient_specific_eligibility"},
    "eligibility_criteria":    {"eligibility_check", "patient_specific_eligibility"},
    "threshold_query":         {"threshold_target", "threshold", "blood_pressure_target"},
    "harm_query":              {"harm", "contraindication", "no_benefit_query"},
    "no_benefit_query":        {"harm_query", "no_benefit"},
    "dosing_regimen":          {"dosing_protocol", "dose", "drug_dose"},
    "time_window":             {"time_window_query", "extended_window"},
    "clinical_overview":       {"overview", "recommendation_lookup"},
    "complication_management": {"post_treatment_care", "adverse_event_management"},
}


_CMI_NUMERIC_FIELDS: Set[str] = {
    "age", "nihss", "aspects", "pc_aspects", "premorbid_mrs",
    "time_from_lkw_hours", "core_volume_ml", "mismatch_ratio",
    "sbp", "dbp", "inr", "platelets", "glucose",
}

_CMI_ENUM_FIELDS: Set[str] = {
    "vessel_occlusion", "intervention", "circulation",
}

# For enum fields, synthesize compound anchor strings the atoms use.
# Example: vessel_occlusion="M1" also searches for "M1 occlusion".
_ENUM_COMPOUND_SUFFIX: Dict[str, List[str]] = {
    "vessel_occlusion": ["occlusion"],
}

# The parser uses the clinician's words for concept names (per its
# schema: "Use the clinician's words for the concept name"). Atoms and
# the numeric comparator use CMI schema field names. This map bridges
# the two. Any clinician term not in this map falls through as-is.
_CONCEPT_TO_CMI_FIELD: Dict[str, str] = {
    "blood pressure":  "sbp",   # default to SBP; DBP handled below
    "bp":              "sbp",
    "systolic":        "sbp",
    "systolic bp":     "sbp",
    "diastolic":       "dbp",
    "diastolic bp":    "dbp",
    # Already-matching aliases (no transformation needed but listed
    # here for clarity):
    "sbp":             "sbp",
    "dbp":             "dbp",
    "age":             "age",
    "nihss":           "nihss",
    "aspects":         "aspects",
    "inr":             "inr",
    "platelets":       "platelets",
    "platelet":        "platelets",
    "glucose":         "glucose",
    "time from lkw":   "time_from_lkw_hours",
    "lkw":             "time_from_lkw_hours",
    "time since onset": "time_from_lkw_hours",
}


def _try_float(s: str) -> Optional[float]:
    """Parse a numeric token or return None.

    Handles prose noise around numbers without regex:
      - Strips trailing punctuation ("24," → 24, "6." → 6)
      - Removes thousands separator ("100,000" → 100000)
      - Takes the systolic half of BP slash pairs ("180/105" → 180)
        because when the guideline writes "<180/105" the systolic
        is what anchors the constraint in our schema
    """
    if not isinstance(s, str):
        return None
    cleaned = s.strip().rstrip(".,;:)!?")
    if not cleaned:
        return None
    # BP slash form — take systolic (left of /)
    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[0]
    # Thousands separator — require strict "X,YYY(,YYY)*" pattern so
    # "100,000" parses as 100000 but "2,5" is not treated as 25.
    if "," in cleaned:
        parts = cleaned.split(",")
        head = parts[0]
        tail = parts[1:]
        is_thousands = (
            head.isdigit() and 1 <= len(head) <= 3
            and all(p.isdigit() and len(p) == 3 for p in tail)
        )
        if is_thousands:
            cleaned = "".join(parts)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_comparison_string(s: Any) -> Optional[Tuple[str, float]]:
    """Parse '>180', '<=185', '≥6', '> 180', '=200' into (op, number).

    Returns None if `s` isn't a parseable comparison. Used by both
    Step 2a value verification and Step 3 numeric comparator so
    comparison-string values are first-class, not opaque.

    Walks characters — no regex.
    """
    if not isinstance(s, str):
        return None
    # Normalize unicode comparators to ASCII
    text = s.strip().replace("≥", ">=").replace("≤", "<=")
    if not text:
        return None

    # Strip leading operator. Two-char ops must be checked before one-char.
    if text.startswith(">="):
        op, rest = ">=", text[2:]
    elif text.startswith("<="):
        op, rest = "<=", text[2:]
    elif text[0] in (">", "<", "="):
        op, rest = text[0], text[1:]
    else:
        return None

    num = _try_float(rest)
    if num is None:
        return None
    return op, num


def _find_numeric_claims(
    text: str,
) -> List[Tuple[str, Any, Any]]:
    """Find range and comparator numeric claims in a text window.

    Returns a list of tuples in discovery order:
      - ("range", lo, hi)    — "N to N", "N through N", "N-N"
      - ("cmp", op, num)     — ">=", "<=", ">", "<", "=" before a number

    Normalizes unicode ops and multi-word ops ("at least", "no more than")
    to ASCII comparators, then walks tokens. No regex.
    """
    if not text:
        return []

    # Normalize operators before tokenization. Wrap in spaces so that
    # stuck-together forms like "≥6" become "≥ 6" → ">= 6".
    lower = text.lower()
    lower = (
        lower.replace("≥", " >= ")
             .replace("≤", " <= ")
             .replace("–", " - ")
    )
    # Pad with spaces so multi-word operators at string boundaries
    # still match. Strip before tokenizing.
    lower = f" {lower} "
    lower = (
        lower.replace(" at least ", " >= ")
             .replace(" no more than ", " <= ")
    )
    lower = lower.strip()

    tokens = lower.split()
    claims: List[Tuple[str, Any, Any]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # Case 1: token is a bare number — check for a following range
        num = _try_float(tok)
        if num is not None:
            if i + 2 < len(tokens):
                sep = tokens[i + 1]
                if sep in ("to", "through", "-"):
                    num2 = _try_float(tokens[i + 2])
                    if num2 is not None:
                        claims.append(("range", num, num2))
                        i += 3
                        continue
            i += 1
            continue

        # Case 2: token is a comparator operator, number in next token
        if tok in (">=", "<=", ">", "<", "="):
            if i + 1 < len(tokens):
                n2 = _try_float(tokens[i + 1])
                if n2 is not None:
                    claims.append(("cmp", tok, n2))
                    i += 2
                    continue
            i += 1
            continue

        # Case 3: op stuck to its number — ">=180", ">180"
        op = None
        rest = None
        if tok.startswith(">="):
            op, rest = ">=", tok[2:]
        elif tok.startswith("<="):
            op, rest = "<=", tok[2:]
        elif tok and tok[0] in (">", "<", "="):
            op, rest = tok[0], tok[1:]
        if op is not None and rest:
            n2 = _try_float(rest)
            if n2 is not None:
                claims.append(("cmp", op, n2))
                i += 1
                continue

        # Case 4: stuck-together range "6-24" (single hyphen, two numbers)
        if "-" in tok and tok.count("-") == 1:
            left_part, right_part = tok.split("-", 1)
            n1 = _try_float(left_part)
            n2 = _try_float(right_part)
            if n1 is not None and n2 is not None:
                claims.append(("range", n1, n2))
                i += 1
                continue

        i += 1
    return claims


def _query_numeric_values(
    anchor_terms: Dict[str, Any],
) -> Dict[str, Tuple[Optional[str], float]]:
    """Flatten every numeric anchor value into a uniform
    {cmi_field: (operator_or_None, number)} shape.

    Handles ALL four value shapes the parser emits:
      {"age": 65}                     → {"age":  (None, 65)}
      {"SBP": {"min":180, "max":220}} → {"sbp":  ("range_mid", 200)}
      {"blood pressure": ">180"}      → {"sbp":  (">", 180)}
      {"aspirin": null}               → (no entry)

    Concept names are normalized to CMI field names via
    _CONCEPT_TO_CMI_FIELD. Keys already in CMI-canonical form pass
    through unchanged.
    """
    out: Dict[str, Tuple[Optional[str], float]] = {}
    for key, val in (anchor_terms or {}).items():
        k_lower = str(key).lower()
        field = _CONCEPT_TO_CMI_FIELD.get(k_lower, k_lower)
        if field not in _CMI_NUMERIC_FIELDS:
            continue

        if isinstance(val, (int, float)):
            out[field] = (None, float(val))
        elif isinstance(val, dict):
            lo = val.get("min")
            hi = val.get("max")
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                out[field] = ("range_mid", (float(lo) + float(hi)) / 2.0)
            elif isinstance(lo, (int, float)):
                out[field] = (">=", float(lo))
            elif isinstance(hi, (int, float)):
                out[field] = ("<=", float(hi))
        elif isinstance(val, str):
            parsed = _parse_comparison_string(val)
            if parsed:
                out[field] = parsed
    return out


def _extract_query_anchor_terms(
    anchor_terms: Dict[str, Any],
) -> Set[str]:
    """Flatten the parser's anchor_terms dict into a set of clinical
    terms suitable for string-matching against atom anchor_terms.

    The parser uses two conventions in the same dict:
      (a) key = clinical term, value = None
          e.g. {"aspirin": null} — the key IS the term.
      (b) key = CMI schema field, value = number or enum string
          e.g. {"age": 65, "vessel_occlusion": "M1"} — the VALUE is
          the clinical content.

    This helper detects which convention each entry uses and extracts
    the clinical term side. Numbers are dropped from the anchor set
    entirely — they belong to the numeric comparator, not string
    matching.
    """
    out: Set[str] = set()
    for key, val in (anchor_terms or {}).items():
        k_lower = str(key).lower()
        # Concept names may need CMI-field normalization for the
        # numeric-field check (so "blood pressure" → "sbp").
        canonical = _CONCEPT_TO_CMI_FIELD.get(k_lower, k_lower)

        if canonical in _CMI_NUMERIC_FIELDS:
            # Numeric schema field: the VALUE (number or comparison
            # string) is handled by _query_numeric_values / the numeric
            # comparator. The concept NAME still joins the anchor set
            # so the atom's mention of the concept scores as a match.
            out.add(k_lower)
            continue

        if k_lower in _CMI_ENUM_FIELDS:
            if isinstance(val, str) and val.strip():
                v_lower = val.strip().lower()
                out.add(v_lower)
                for suffix in _ENUM_COMPOUND_SUFFIX.get(k_lower, []):
                    out.add(f"{v_lower} {suffix}")
            continue

        # Default: key IS the clinical term (e.g. {"aspirin": null}).
        out.add(k_lower)

        # If the value is a string, include it as an anchor ONLY if
        # it's a real clinical term. Comparison strings like ">180"
        # are not anchors — they go to the numeric comparator.
        if isinstance(val, str) and val.strip():
            if _parse_comparison_string(val) is None:
                out.add(val.strip().lower())

    return out


def _classify_anchors(
    anchor_terms: Dict[str, Any],
) -> Tuple[Set[str], Set[str]]:
    """Split query anchor terms into (pinpoint, global) sets.

    - Pinpoint: discriminating clinical concepts (aspirin, M1 occlusion,
      ASPECTS) — high weight
    - Global: broad terms (IVT, stroke, AIS) — low weight, tie-breaker

    Terms not in the vocabulary default to 'pinpoint' — novel terms
    can't be assumed global.

    Input is the raw parser dict. This function delegates term
    extraction to _extract_query_anchor_terms so the (key, value)
    interpretation logic lives in one place.
    """
    tiers = _load_anchor_tiers()
    pinpoint: Set[str] = set()
    glob: Set[str] = set()

    for term in _extract_query_anchor_terms(anchor_terms):
        low = term.lower()
        if low in cfg.GLOBAL_ANCHOR_TERMS:
            glob.add(low)
            continue
        tier = tiers.get(low, "pinpoint")
        if tier == "global":
            glob.add(low)
        else:
            pinpoint.add(low)

    return pinpoint, glob


# ── Scoring ───────────────────────────────────────────────────────

def _anchor_jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    overlap = a & b
    union = a | b
    return len(overlap) / len(union) if union else 0.0


def _anchor_coverage(query_anchors: Set[str], atom_anchors: Set[str]) -> float:
    """Fraction of query's anchor terms present in the atom's anchor terms.

    Coverage is asymmetric: we care how many of THE QUERY'S anchors
    the atom covers, not the reverse. An atom can have many other
    anchors and still get 1.0 here if it covers all of the query's.
    """
    if not query_anchors:
        return 0.0
    overlap = query_anchors & atom_anchors
    return len(overlap) / len(query_anchors)


def _value_satisfaction(
    query_values: Dict[str, Any],
    atom_value_ranges: Dict[str, Any],
) -> float:
    """Fraction of query's anchor values that fall inside atom's ranges.

    query_values: {term: value} where value is a number or {min, max}
    atom_value_ranges: atom['value_ranges'] — same shape

    Returns 0.0 if either side is empty.
    """
    if not query_values or not atom_value_ranges:
        return 0.0
    hits = 0
    checked = 0
    for key, q_val in query_values.items():
        candidates = [key, key.lower(), key.upper()]
        matched = None
        for c in candidates:
            if c in atom_value_ranges:
                matched = atom_value_ranges[c]
                break
        if matched is None:
            continue
        checked += 1
        try:
            qnum = (
                q_val if isinstance(q_val, (int, float))
                else q_val.get("min") if isinstance(q_val, dict)
                else None
            )
            if qnum is None:
                continue
            if isinstance(matched, (int, float)):
                if qnum <= matched:
                    hits += 1
            elif isinstance(matched, dict):
                lo = matched.get("min")
                hi = matched.get("max")
                if (lo is None or qnum >= lo) and (
                    hi is None or qnum <= hi
                ):
                    hits += 1
        except Exception:
            continue
    return hits / checked if checked else 0.0


def _value_guided_hit(
    query_has_value: bool,
    atom_text: str,
    query_anchor_terms: Set[str],
) -> float:
    """Returns 1.0 if query has a value AND atom text has numeric
    context near any of the query's anchor terms. Else 0.

    This is a guide, not a filter — an atom with no number but
    a semantic match still scores; this just boosts atoms that
    quantify the concept.
    """
    if not query_has_value:
        return 0.0
    if not atom_text or not query_anchor_terms:
        return 0.0
    text_lower = atom_text.lower()
    window = 80
    for anchor in query_anchor_terms:
        idx = text_lower.find(anchor.lower())
        if idx < 0:
            continue
        start = max(0, idx - window)
        end = min(len(text_lower), idx + len(anchor) + window)
        neighborhood = text_lower[start:end]
        # Any digit in the neighborhood means numeric context is present.
        if any(c.isdigit() for c in neighborhood):
            return 1.0
    return 0.0


# ── Numeric range comparison against atom prose ──────────────────────

# Map parser field keys to the atom-text labels the guideline uses.
# Multiple labels are acceptable — any match triggers a comparison.
_FIELD_LABEL_ALIASES: Dict[str, List[str]] = {
    "age":                  ["age"],
    "nihss":                ["nihss"],
    "aspects":              ["aspects"],
    "pc_aspects":           ["pc-aspects", "pc aspects"],
    "time_from_lkw_hours":  ["hours", "hour"],
    "premorbid_mrs":        ["mrs", "modified rankin"],
    "core_volume_ml":       ["ml", "cc"],
    "mismatch_ratio":       ["mismatch"],
    "sbp":                  ["sbp", "systolic"],
    "dbp":                  ["dbp", "diastolic"],
    "inr":                  ["inr"],
    "platelets":            ["platelet", "plt"],
    "glucose":              ["glucose"],
}


def _numeric_comparator_score(
    anchor_terms: Dict[str, Any],
    atom_text: str,
) -> float:
    """Score how well the atom's numeric claims align with the query's
    numeric values/ranges/comparisons.

    For each query numeric field, look in atom text for a threshold or
    range statement on the same variable. Score based on direction:

      - Query "NIHSS=18" + atom "NIHSS >=6"    → satisfied (18>=6) = hit
      - Query "age=65"   + atom "age <80"      → satisfied (65<80) = hit
      - Query "SBP >180" + atom "SBP <185"     → hit (patient's lower bound
                                                  falls near atom's upper bound
                                                  → topically on-target)
      - Query "SBP >180" + atom "NIHSS >=6"    → different field, skip
      - Query has field, atom makes no claim    → skip (not scored)

    Handles all four parser value shapes by delegating to
    _query_numeric_values.
    """
    if not anchor_terms or not atom_text:
        return 0.0

    q_values = _query_numeric_values(anchor_terms)
    if not q_values:
        return 0.0

    checked = 0
    hits = 0
    for field, (q_op, q_num) in q_values.items():
        labels = _FIELD_LABEL_ALIASES.get(field, [field])
        best = None
        for lbl in labels:
            r = _numeric_constraint_aligned(q_op, q_num, lbl, atom_text)
            if r is not None:
                best = r if best is None else (best or r)
        if best is None:
            continue
        checked += 1
        if best:
            hits += 1

    return hits / checked if checked else 0.0


def _numeric_constraint_aligned(
    q_op: Optional[str],
    q_num: float,
    label: str,
    atom_text: str,
) -> Optional[bool]:
    """Check if the query value/comparison aligns with a numeric claim
    about the same variable in atom text.

    Returns True if the atom's threshold/range is on-topic for this
    query value, False if explicitly contradicted, None if the atom
    text makes no numeric claim about this label.

    "On-topic" is deliberately permissive: an atom saying "SBP <185"
    is relevant to a query "SBP >180" because both describe the same
    clinical decision point (elevated BP after IVT). We do NOT require
    the atom's range to strictly contain the query value — the atom
    might be expressing a threshold the patient has crossed.

    Uses _find_numeric_claims (token walk, no regex) to extract ranges
    and comparators from the 80-char window following each label
    occurrence. When both a range and a comparator are present in the
    same window, the range takes precedence.
    """
    if not atom_text:
        return None
    text = atom_text.lower()
    label_lower = label.lower()

    idx = 0
    best: Optional[bool] = None
    while True:
        pos = text.find(label_lower, idx)
        if pos < 0:
            break
        right = text[pos + len(label_lower):pos + len(label_lower) + 80]

        claims = _find_numeric_claims(right)
        # Prefer a range claim over a comparator when both exist in the
        # same window (matches the prior m_range / elif m_cmp behavior).
        range_claim = next(
            (c for c in claims if c[0] == "range"), None,
        )
        cmp_claim = next(
            (c for c in claims if c[0] == "cmp"), None,
        )
        chosen = range_claim or cmp_claim

        ok: Optional[bool] = None
        if chosen and chosen[0] == "range":
            lo, hi = chosen[1], chosen[2]
            if q_op is None or q_op == "=":
                ok = lo <= q_num <= hi
            elif q_op in (">=", ">"):
                # Query is a lower-bound scenario (e.g. BP>180).
                # Atom's range is on-topic if the query lower
                # bound isn't absurdly far from atom's range.
                ok = q_num <= hi or _within_tolerance(q_num, lo, hi)
            elif q_op in ("<=", "<"):
                ok = q_num >= lo or _within_tolerance(q_num, lo, hi)
            else:
                ok = lo <= q_num <= hi
        elif chosen and chosen[0] == "cmp":
            atom_op, atom_n = chosen[1], chosen[2]
            if q_op is None or q_op == "=":
                # Query has a single value — does it satisfy the
                # atom's explicit constraint?
                ok = _eval_comparison(q_num, atom_op, atom_n)
            else:
                # Query is itself a comparison (e.g. >180). Score
                # on topical proximity: atom's threshold is
                # on-topic if it's in the same numeric neighborhood
                # as the query's value.
                ok = _numbers_on_topic(q_num, atom_n)

        if ok is not None:
            best = (best or False) or ok
        idx = pos + len(label_lower)

    return best


def _eval_comparison(value: float, op: str, threshold: float) -> bool:
    """Check value satisfies the op-threshold constraint."""
    if op in (">=", "at least"):
        return value >= threshold
    if op in ("<=", "no more than"):
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    if op == "=":
        return abs(value - threshold) < 0.01
    return False


def _numbers_on_topic(q_num: float, atom_num: float) -> bool:
    """Two numbers are 'on topic' if they share a clinical neighborhood.

    Heuristic: within ±30% of each other OR within an absolute tolerance
    appropriate for the magnitude. Good enough that SBP 180 and SBP 185
    are on-topic; SBP 180 and NIHSS 6 aren't.
    """
    if q_num == 0 and atom_num == 0:
        return True
    if q_num == 0 or atom_num == 0:
        return False
    ratio = min(q_num, atom_num) / max(q_num, atom_num)
    return ratio >= 0.7


def _within_tolerance(q_num: float, lo: float, hi: float) -> bool:
    """Query value near (but not in) [lo, hi] — topical relevance."""
    if lo <= q_num <= hi:
        return True
    # Within 30% of either endpoint
    return _numbers_on_topic(q_num, lo) or _numbers_on_topic(q_num, hi)


def _score_atom(
    atom: Dict[str, Any],
    query_embedding,
    semantic_score: float,
    intent: str,
    pinpoint_anchors: Set[str],
    global_anchors: Set[str],
    query_values: Dict[str, Any],
    query_has_value: bool,
    raw_anchor_terms: Optional[Dict[str, Any]] = None,
    topic_section: Optional[str] = None,
) -> Tuple[float, Dict[str, float]]:
    """Score one atom against the query. Returns (total, breakdown).

    `raw_anchor_terms` is the parser's original dict (preserving both
    keys and values) used by the numeric comparator. The pinpoint/
    global sets fed in are the already-flattened clinical-term sets.
    """
    atom_anchor_set = {
        str(a).lower() for a in (atom.get("anchor_terms") or [])
    }
    atom_intent_set = set(atom.get("intent_affinity") or [])
    atom_text = atom.get("text", "") or ""
    atom_value_ranges = atom.get("value_ranges") or {}

    # Each component is in [0, 1]
    sem = max(0.0, min(1.0, float(semantic_score)))

    # Intent match: exact hit OR synonym hit.
    if intent and intent in atom_intent_set:
        intent_match = 1.0
    elif intent and _INTENT_SYNONYMS.get(intent, set()) & atom_intent_set:
        intent_match = 1.0
    else:
        intent_match = 0.0
    pinpoint_cov = _anchor_coverage(pinpoint_anchors, atom_anchor_set)
    global_cov = _anchor_coverage(global_anchors, atom_anchor_set)
    value_sat = _value_satisfaction(query_values, atom_value_ranges)

    # Real numeric comparator: does the atom text satisfy the query's
    # numeric constraints? Falls back to the proximity heuristic if
    # the atom doesn't express a numeric constraint on any query field.
    numeric_cov = _numeric_comparator_score(
        raw_anchor_terms or {}, atom_text,
    )
    if numeric_cov > 0.0:
        value_guided = numeric_cov
    else:
        value_guided = _value_guided_hit(
            query_has_value, atom_text,
            pinpoint_anchors | global_anchors,
        )

    # Topic alignment — if Step 2b confirmed a topic, atoms in the
    # topic's section (or its descendants) get a bonus. When topic_section
    # is None (verifier unavailable or wrong_topic without suggestion),
    # the bonus is 0 and the signal is silent.
    topic_align = 0.0
    if topic_section:
        topic_align = _topic_alignment_bonus(
            str(atom.get("parent_section", "")),
            topic_section,
        )

    breakdown = {
        "semantic": cfg.W_SEMANTIC * sem,
        "intent": cfg.W_INTENT * intent_match,
        "pinpoint": cfg.W_PINPOINT * pinpoint_cov,
        "topic": cfg.W_TOPIC * topic_align,
        "global": cfg.W_GLOBAL * global_cov,
        "value": cfg.W_VALUE * value_sat,
        "value_guided": cfg.W_VALUE_GUIDED * value_guided,
    }
    total = sum(breakdown.values())
    return total, breakdown


# ── Main retrieval ────────────────────────────────────────────────

def retrieve(
    parsed: ParsedQAQuery,
    raw_query: str,
    verified_topic: Optional[str] = None,
) -> RetrievedContent:
    """Unified single-pass retrieval.

    1. Embed the query once (question_summary preferred over raw).
    2. Classify anchor terms into pinpoint vs global.
    3. Resolve effective topic → section for topic-alignment bonus.
    4. Score every atom via _score_atom.
    5. Drop atoms below SCORE_THRESHOLD.
    6. Drop atoms whose ONLY signal is intent (too weak).
    7. Group survivors by atom_type.
    8. Ambiguity check on recs.

    Args:
        parsed:         Step 1 output (after Step 2a validation).
        raw_query:      the clinician's original question string.
        verified_topic: topic confirmed (or suggested) by Step 2b. When
                        provided and it resolves to a section, atoms in
                        that section get the topic-alignment bonus.
                        When None, the pipeline falls back to parsed.topic.
    """
    intent = parsed.intent or ""

    # ── Embed query once ──────────────────────────────────────────
    semantic_query = (
        parsed.question_summary or raw_query or ""
    ).strip()

    if not semantic_service.is_available() or not semantic_query:
        logger.warning(
            "Step 3: semantic unavailable or empty query — retrieval "
            "will degrade to lexical-only",
        )
        # Graceful degradation: return empty content
        return RetrievedContent(
            raw_query=raw_query,
            parsed_query=parsed,
            intent=intent,
        )

    q_emb = semantic_service.embed_query(semantic_query)

    # ── Classify query anchors ────────────────────────────────────
    pinpoint_anchors, global_anchors = _classify_anchors(
        parsed.anchor_terms,
    )

    # ── Resolve topic → section for the topic bonus ───────────────
    # Prefer Step 2b's verified topic; fall back to Step 1's topic.
    # Resolution is semantic (topic map is a guide, not a key).
    effective_topic = verified_topic or parsed.topic or ""
    topic_section: Optional[str] = _resolve_topic_to_section(effective_topic)

    # ── Query-side value payload ──────────────────────────────────
    query_values = parsed.anchor_values  # {k: v} for v is not None
    query_has_value = parsed.has_anchor_values()

    # ── Score every atom ──────────────────────────────────────────
    all_scored = semantic_service.score_all_atoms(q_emb)
    # all_scored: [(atom, cosine_score), ...] in atom order

    # KG gating: only include KG atoms when intent calls for it
    include_kg = intent in cfg.KG_INTENTS

    survivors: List[ScoredAtom] = []
    for atom, sem_score in all_scored:
        atype = atom.get("atom_type", "")
        # Skip KG atoms unless the intent is about gaps
        if atype == "evidence_gap" and not include_kg:
            continue
        total, breakdown = _score_atom(
            atom, q_emb, sem_score, intent,
            pinpoint_anchors, global_anchors,
            query_values, query_has_value,
            raw_anchor_terms=parsed.anchor_terms,
            topic_section=topic_section,
        )
        if total < cfg.SCORE_THRESHOLD:
            continue
        # Drop atoms whose only signal is intent (too weak alone)
        non_intent_sum = total - breakdown["intent"]
        if non_intent_sum < cfg.SEMANTIC_SIGNAL_FLOOR * cfg.W_SEMANTIC:
            # No semantic, no pinpoint, no value — just intent match
            continue
        survivors.append(ScoredAtom(atom=atom, score=total, breakdown=breakdown))

    # Sort by score descending (stable)
    survivors.sort(key=lambda s: -s.score)

    # ── Group by atom_type ────────────────────────────────────────
    by_type: Dict[str, List[ScoredAtom]] = {}
    for s in survivors:
        t = s.atom.get("atom_type", "")
        by_type.setdefault(t, []).append(s)

    # ── Build output groups ───────────────────────────────────────
    # Ambiguity detector is suppressed when the query is scenario-
    # specific (has anchor values). Rationale: structured queries
    # are disambiguated DETERMINISTICALLY by CMI downstream, not by
    # retrieval's fuzzy tight-band heuristic. Free-form queries
    # without values still use retrieval ambiguity as the guardrail.
    suppress_ambiguity = parsed.has_anchor_values()

    recs_final, needs_clarification, clarification_opts = (
        _build_recs(
            by_type.get("recommendation", []),
            suppress_ambiguity=suppress_ambiguity,
        )
    )
    rss_final = _build_rss(by_type.get("evidence_summary", []))
    synopsis_final = _build_synopsis(by_type.get("narrative_context", []))
    kg_final = _build_kg(
        by_type.get("evidence_gap", []) if include_kg else [],
    )
    tables_final = _build_tables(by_type.get("table_row", []))
    figures_final = _build_figures(by_type.get("figure", []))

    # Concept categories represented in output
    categories_set: Set[str] = set()
    for s in survivors[:50]:  # sample top-50 for performance
        cat = s.atom.get("category", "")
        if cat:
            categories_set.add(cat)

    logger.info(
        "qa_v6 retrieve: intent=%s, pinpoint=%s, global=%s, "
        "survivors=%d, recs=%d, rss=%d, syn=%d, kg=%d, "
        "needs_clarification=%s",
        intent, sorted(pinpoint_anchors), sorted(global_anchors),
        len(survivors), len(recs_final), len(rss_final),
        len(synopsis_final), len(kg_final), needs_clarification,
    )

    return RetrievedContent(
        raw_query=raw_query,
        parsed_query=parsed,
        intent=intent,
        recommendations=recs_final,
        rss=rss_final,
        synopsis=synopsis_final,
        knowledge_gaps=kg_final,
        tables=tables_final,
        figures=figures_final,
        concept_categories=sorted(categories_set),
        needs_clarification=needs_clarification,
        clarification_options=clarification_opts,
    )


# ── Group builders ────────────────────────────────────────────────

def _build_recs(
    scored_recs: List[ScoredAtom],
    suppress_ambiguity: bool = False,
) -> Tuple[List[Dict[str, Any]], bool, List[Dict[str, Any]]]:
    """Build final rec list and detect ambiguity.

    Returns (recs_list, needs_clarification, clarification_options).

    Cap at MAX_RECS (3). If >MAX_RECS cleared threshold AND the
    cluster is tight (top and rank-4 within REC_TIGHT_BAND) AND they
    span multiple concept categories, trigger clarification.

    When `suppress_ambiguity` is True, skip the clarification check
    and always return top MAX_RECS. Used for scenario-specific queries
    where CMI disambiguates deterministically downstream.
    """
    if not scored_recs:
        return [], False, []

    top_score = scored_recs[0].score

    # Recs that cleared threshold AND are within the tight band
    tight_cluster = [
        s for s in scored_recs
        if s.score >= top_score * cfg.REC_TIGHT_BAND
    ]

    # Categories represented in the tight cluster
    cluster_categories = {
        s.atom.get("category", "") for s in tight_cluster
        if s.atom.get("category", "")
    }

    needs_clarification = (
        not suppress_ambiguity
        and len(tight_cluster) > cfg.MAX_RECS
        and len(cluster_categories) >= 2
    )

    if needs_clarification:
        # Build clarification options from the represented categories
        clar_opts: List[Dict[str, Any]] = []
        seen_cats: Set[str] = set()
        for s in tight_cluster:
            cat = s.atom.get("category", "")
            if not cat or cat in seen_cats:
                continue
            seen_cats.add(cat)
            clar_opts.append({
                "label": chr(ord("A") + len(clar_opts)),
                "description": _category_description(cat),
                "section": s.atom.get("parent_section", ""),
                "rec_id": s.atom.get("atom_id", ""),
                "cor": s.atom.get("cor", ""),
                "loe": s.atom.get("loe", ""),
                "category": cat,
            })
        return [], True, clar_opts

    # No ambiguity: return top MAX_RECS
    out = []
    for s in scored_recs[:cfg.MAX_RECS]:
        a = s.atom
        out.append({
            "id": a.get("atom_id", "").replace("atom-", "")
                  if a.get("atom_id", "").startswith("atom-") else a.get("atom_id", ""),
            "atom_id": a.get("atom_id", ""),
            "section": a.get("parent_section", ""),
            "sectionTitle": a.get("section_title", ""),
            "recNumber": a.get("recNumber", ""),
            "cor": a.get("cor", ""),
            "loe": a.get("loe", ""),
            "category": a.get("category", ""),
            "text": a.get("text", ""),
            "_score": s.score,
            "_breakdown": s.breakdown,
        })
    return out, False, []


def _build_rss(
    scored_rss: List[ScoredAtom],
) -> List[Dict[str, Any]]:
    """Build RSS list, capped at MAX_RSS, preserving score order."""
    out = []
    for s in scored_rss[:cfg.MAX_RSS]:
        a = s.atom
        out.append({
            "section": a.get("parent_section", ""),
            "sectionTitle": a.get("section_title", ""),
            "recNumber": a.get("recNumber", ""),
            "category": a.get("category", ""),
            "condition": a.get("condition", ""),
            "text": a.get("text", ""),
            "_score": s.score,
            "_breakdown": s.breakdown,
        })
    return out


def _build_synopsis(
    scored_syn: List[ScoredAtom],
) -> Dict[str, str]:
    """Build synopsis dict: {section_or_category: text}.

    One synopsis atom per section/category. If multiple synopsis atoms
    for the same section survive (shouldn't happen but defensive),
    keep the highest-scoring one.
    """
    out: Dict[str, str] = {}
    seen: Set[str] = set()
    for s in scored_syn:
        a = s.atom
        key = a.get("category", "") or a.get("parent_section", "")
        if not key or key in seen:
            continue
        seen.add(key)
        out[key] = a.get("text", "")
    return out


def _build_kg(
    scored_kg: List[ScoredAtom],
) -> Dict[str, str]:
    """Build KG dict: {section_or_category: concatenated text}.

    Multiple KG bullets can share a section — join with newlines.
    """
    out: Dict[str, List[str]] = {}
    for s in scored_kg:
        a = s.atom
        key = a.get("category", "") or a.get("parent_section", "")
        if not key:
            continue
        out.setdefault(key, []).append(a.get("text", ""))
    return {k: "\n".join(v) for k, v in out.items()}


def _build_tables(
    scored_tables: List[ScoredAtom],
) -> List[Dict[str, Any]]:
    out = []
    for s in scored_tables[:cfg.MAX_TABLES]:
        a = s.atom
        out.append({
            "section": a.get("parent_section", ""),
            "sectionTitle": a.get("section_title", ""),
            "text": a.get("text", ""),
            "_score": s.score,
        })
    return out


def _build_figures(
    scored_figures: List[ScoredAtom],
) -> List[Dict[str, Any]]:
    out = []
    for s in scored_figures[:cfg.MAX_FIGURES]:
        a = s.atom
        out.append({
            "section": a.get("parent_section", ""),
            "sectionTitle": a.get("section_title", ""),
            "text": a.get("text", ""),
            "_score": s.score,
        })
    return out


def _category_description(category: str) -> str:
    """Human-readable description of a concept category for clarification prompts."""
    cat_map = _load_concept_sections()
    entry = cat_map.get(category)
    if entry:
        title = entry.get("title", "")
        desc = entry.get("description", "")
        if title and desc:
            return f"{title}: {desc}"
        if title:
            return title
    # Fallback: prettify the category id
    return category.replace("_", " ").title()
