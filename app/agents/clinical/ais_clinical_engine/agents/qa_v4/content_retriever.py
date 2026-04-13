# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 3: Route to sections, narrow within sections, retrieve content.
#
# Pure Python. No LLM. No regex. Deterministic lookups only.
#
# Three lookups:
#   1. intent → source types (REC, SYN, RSS, KG, TBL, FIG)
#   2. topic → primary section
#   3. anchor_terms → additional sections (scored by match count)
#
# Two levels of scoring:
#   Level 1 — anchor term match count (concept families).
#     Sections scored by how many unique concept families their anchor
#     terms cover. SBP + DBP + BP = 1 family (vital_signs), not 3.
#     Recs/RSS scored by unique families matched in text.
#
#   Level 2 — value-based narrowing (structured metrics).
#     When the user provides a value (SBP=200, ASPECTS=2), sections
#     whose structured metrics match that value get boosted.
#     ASPECTS=2 boosts sections with "ASPECTS 0-2", not "ASPECTS 6-10".
#     Recs/RSS containing the metric raw string (e.g. "SBP <185 mmHg")
#     get an extra score bump over recs mentioning the term generically.
# ───────────────────────────────────────────────────────────────────────
"""
Step 3: Route to sections and retrieve narrowed content.

Takes validated Step 1 output (intent, topic, anchor_terms) and:
1. Determines which content types the intent needs
2. Finds which sections to search (topic + anchor terms), scored by
   concept family match count + value relevance
3. Pulls content from those sections, narrowed and scored by anchor terms
   and value-matched metric thresholds
4. Returns a RetrievedContent bundle for Step 4 agents
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_DATA_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "data",
)


# ── Reference data (loaded once, cached) ─────────────────────────────

def _load_ref_json(filename: str) -> dict:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class _RoutingMaps:
    """Lazy-loaded routing maps for section resolution."""

    _instance: Optional[_RoutingMaps] = None

    def __init__(self):
        self._intent_sources: Optional[Dict[str, List[str]]] = None
        self._topic_to_section: Optional[Dict[str, str]] = None
        self._anchor_to_sections: Optional[Dict[str, List[str]]] = None
        self._table_to_section: Optional[Dict[str, str]] = None
        self._figure_to_section: Optional[Dict[int, str]] = None
        self._term_to_family: Optional[Dict[str, str]] = None
        self._term_to_synonyms: Optional[Dict[str, Set[str]]] = None
        self._section_metrics: Optional[Dict[str, List[Dict[str, Any]]]] = None

    @classmethod
    def get(cls) -> _RoutingMaps:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def intent_sources(self) -> Dict[str, List[str]]:
        """Intent name → list of source type codes (REC, SYN, RSS, KG, TBL, FIG, FRONT)."""
        if self._intent_sources is None:
            data = _load_ref_json("intent_content_source_map.json")
            self._intent_sources = {}
            for entry in data["intents"]:
                # sources field is like "REC + TBL" or "SYN + RSS"
                sources = [s.strip() for s in entry["sources"].split("+")]
                self._intent_sources[entry["intent"]] = sources
        return self._intent_sources

    @property
    def topic_to_section(self) -> Dict[str, str]:
        """Topic name → primary section number."""
        if self._topic_to_section is None:
            data = _load_ref_json("guideline_topic_map.json")
            self._topic_to_section = {
                e["topic"]: e["section"] for e in data["topics"]
            }
        return self._topic_to_section

    @property
    def anchor_to_sections(self) -> Dict[str, List[str]]:
        """Lowercased anchor term → list of section IDs."""
        if self._anchor_to_sections is None:
            self._anchor_to_sections = {}
            data = _load_ref_json("guideline_anchor_words.json")
            for sec_id, sec_data in data.get("sections", {}).items():
                aw = sec_data.get("anchor_words", {})
                for terms in aw.values():
                    if isinstance(terms, list):
                        for t in terms:
                            # Structured metrics are dicts with a "term" key;
                            # flat entries (drugs, concepts, etc.) are strings.
                            if isinstance(t, dict):
                                key = t.get("term", "").lower()
                            else:
                                key = t.lower()
                            if not key:
                                continue
                            if key not in self._anchor_to_sections:
                                self._anchor_to_sections[key] = []
                            if sec_id not in self._anchor_to_sections[key]:
                                self._anchor_to_sections[key].append(sec_id)
        return self._anchor_to_sections

    @property
    def section_metrics(self) -> Dict[str, List[Dict[str, Any]]]:
        """Section ID → list of structured metric dicts in that section.

        Structured metrics have either:
          operator-based: {"term": "SBP", "operator": "<", "value": 185, ...}
          range-based: {"term": "ASPECTS", "min": 3, "max": 10, ...}

        Both formats include a "raw" key with the original text
        (e.g. "SBP <185 mmHg", "ASPECTS 3-5") for text matching.

        Used by Level 2 value narrowing: when the user provides a value
        for a term, sections whose metrics match that value get boosted.
        """
        if self._section_metrics is None:
            self._section_metrics = {}
            data = _load_ref_json("guideline_anchor_words.json")
            for sec_id, sec_data in data.get("sections", {}).items():
                aw = sec_data.get("anchor_words", {})
                for terms in aw.values():
                    if isinstance(terms, list):
                        for t in terms:
                            if isinstance(t, dict) and "term" in t:
                                if sec_id not in self._section_metrics:
                                    self._section_metrics[sec_id] = []
                                self._section_metrics[sec_id].append(t)
        return self._section_metrics

    @property
    def table_to_section(self) -> Dict[str, str]:
        """Table identifier (e.g. 'Table 3') → section number."""
        if self._table_to_section is None:
            self._table_to_section = {
                "Table 3": "3.2",
                "Table 4": "4.6.1",
                "Table 5": "4.6.1",
                "Table 6": "4.6.1",
                "Table 7": "4.6.2",
                "Table 8": "4.6.1",
                "Table 9": "4.9.1",
            }
        return self._table_to_section

    @property
    def figure_to_section(self) -> Dict[int, str]:
        """Figure number → section number."""
        if self._figure_to_section is None:
            self._figure_to_section = {
                1: "1.0",
                2: "3.2",
                3: "4.7.2",
                4: "4.9.1",
                5: "5.1",
            }
        return self._figure_to_section

    @property
    def term_to_family(self) -> Dict[str, str]:
        """Lowercased anchor term → concept family name.

        Built from synonym_dictionary.json. Each dictionary entry
        (term_id) IS a family. Synonyms within an entry are alternate
        names for the same concept: tPA and alteplase are the same drug,
        SBP and "systolic" are the same measurement.

        Different entries are different concepts, even if they share a
        category: tPA and TNK are both thrombolytics but are different
        drugs and score separately. IVT and tPA are the procedure vs
        a specific drug — different families.

        Used for scoring: count unique families, not raw term hits.
        "SBP" and "systolic" in the same rec = 1 family (same concept).
        "alteplase" and "tenecteplase" in the same rec = 2 families
        (two different drugs being compared).

        Terms not found in the synonym dictionary keep their own name
        as a singleton family — they still count, just aren't grouped.
        """
        if self._term_to_family is None:
            self._term_to_family = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                # Family = the entry's term_id (lowercased).
                # Each entry is a distinct clinical concept.
                family = term_id.lower()

                self._term_to_family[family] = family
                # Map full_term to the same family — "tenecteplase"
                # is TNK's full_term and must resolve to family "tnk".
                full_term = info.get("full_term", "")
                if full_term:
                    self._term_to_family[full_term.lower()] = family
                # Map synonyms to the same family
                for syn in info.get("synonyms", []):
                    self._term_to_family[syn.lower()] = family
        return self._term_to_family

    @property
    def term_to_synonyms(self) -> Dict[str, Set[str]]:
        """Lowercased anchor term → set of all synonyms (including itself).

        Built from synonym_dictionary.json. Every term in a synonym group
        maps to the full set: IVT → {ivt, thrombolysis, iv thrombolysis,
        intravenous thrombolysis, lytic, clot buster}.

        Used for match expansion: when the question says "IVT", we also
        search for "thrombolysis", "alteplase", etc. in rec/RSS text.
        Without this, 12/202 recs that say "thrombolysis" but never "IVT"
        would be missed entirely.
        """
        if self._term_to_synonyms is None:
            self._term_to_synonyms = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                # Build the full synonym set for this entry
                group: Set[str] = {term_id.lower()}
                full_term = info.get("full_term", "")
                if full_term:
                    group.add(full_term.lower())
                for syn in info.get("synonyms", []):
                    group.add(syn.lower())

                # Every member of the group maps to the full group
                for member in group:
                    if member in self._term_to_synonyms:
                        # Merge — a term could appear in multiple entries
                        self._term_to_synonyms[member] |= group
                    else:
                        self._term_to_synonyms[member] = set(group)
        return self._term_to_synonyms


# ── Scored section ──────────────────────────────────────────────────

@dataclass
class ScoredSection:
    """A section with its anchor term match count for prioritization."""
    section_id: str
    anchor_match_count: int = 0
    value_match_count: int = 0       # Level 2: metrics matching user's values
    is_topic_primary: bool = False


# ── Retrieved content bundle ─────────────────────────────────────────

@dataclass
class ScoredItem:
    """A content item (rec or RSS) with its relevance score."""
    data: Dict[str, Any]
    score: int = 0  # number of unique concept families matched


@dataclass
class RetrievedContent:
    """Output of Step 3: everything the agents need to answer the question."""

    raw_query: str
    parsed_query: ParsedQAQuery
    source_types: List[str]                             # e.g. ["REC", "TBL"]
    sections: List[ScoredSection]                       # scored and ordered
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    synopsis: Dict[str, str] = field(default_factory=dict)       # section → text
    rss: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: Dict[str, str] = field(default_factory=dict) # section → text
    tables: List[Dict[str, Any]] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        """Audit trail entry for this retrieval step."""
        return {
            "step": "step3_retrieval",
            "detail": {
                "source_types": self.source_types,
                "sections": [
                    {"id": s.section_id, "anchor_matches": s.anchor_match_count,
                     "value_matches": s.value_match_count,
                     "is_topic_primary": s.is_topic_primary}
                    for s in self.sections
                ],
                "recommendations_count": len(self.recommendations),
                "rss_count": len(self.rss),
                "synopsis_sections": list(self.synopsis.keys()),
                "knowledge_gaps_sections": list(self.knowledge_gaps.keys()),
                "tables_count": len(self.tables),
                "figures_count": len(self.figures),
            },
        }


# ── Main retrieval function ──────────────────────────────────────────

def retrieve_content(
    parsed: ParsedQAQuery,
    raw_query: str,
    recommendations_store: Dict[str, Any],
    guideline_knowledge: Dict[str, Any],
) -> RetrievedContent:
    """
    Route to sections and retrieve narrowed content.

    1. Intent → source types (what to fetch)
    2. Topic + anchor terms → scored sections (where to fetch, prioritized)
    3. Anchor terms (with values) → narrow within sections
       (what's relevant, scored)

    Returns a RetrievedContent bundle with only what the intent needs,
    ordered by relevance.
    """
    maps = _RoutingMaps.get()

    # ── Lookup 1: intent → source types ──────────────────────────
    source_types = maps.intent_sources.get(
        parsed.intent, ["REC", "SYN"]  # safe default
    )

    # ── Lookup 2 + 3: topic + anchor terms → scored sections ────
    # Level 1: sections scored by concept family match count
    # Level 2: sections boosted by value-matched metrics
    scored_sections, section_matched_raws = _resolve_and_score_sections(
        parsed, maps,
    )

    # Extract ordered section IDs (highest score first)
    section_ids = [s.section_id for s in scored_sections]

    logger.info(
        "Step 3: intent=%s → sources=%s, topic=%s + anchors → sections=%s",
        parsed.intent, source_types, parsed.topic,
        [(s.section_id, s.anchor_match_count, s.value_match_count)
         for s in scored_sections],
    )

    # ── Build narrowing terms ───────────────────────────────────
    # Anchor term keys (lowercased) — the clinical concepts.
    # anchor_terms is a Dict[str, Any] — keys are terms, values are
    # their associated values/ranges or None.
    anchor_lower = {t.lower() for t in (parsed.anchor_terms or {})}

    # Expand anchor terms with synonyms for text matching.
    # Section routing uses canonical terms (from guideline_anchor_words.json).
    # But rec/RSS text may use the full form ("thrombolysis") instead of
    # the abbreviation ("IVT"). Expanding ensures we don't miss content
    # that uses a synonym. 12/202 recs say "thrombolysis" without "IVT".
    anchor_expanded = _expand_with_synonyms(anchor_lower, maps.term_to_synonyms)

    # Concept family mapping for semantic scoring
    term_to_family = maps.term_to_family

    logger.info(
        "Step 3 narrowing: %d anchor terms → %d expanded (synonym expansion), "
        "%d sections with value-matched metrics",
        len(anchor_lower), len(anchor_expanded), len(section_matched_raws),
    )

    # ── Fetch content by source type, narrowed and scored ────────
    # Content matching uses anchor_expanded (with synonyms) so that
    # "IVT" also catches recs saying "thrombolysis" or "alteplase".
    # Scoring uses term_to_family so that all BP synonyms still count
    # as one concept family.
    # section_matched_raws provides Level 2 value boosting — recs/RSS
    # containing metric raw strings (e.g. "SBP <185 mmHg") that match
    # the user's values get boosted higher than recs mentioning the
    # term without the specific threshold.
    result = RetrievedContent(
        raw_query=raw_query,
        parsed_query=parsed,
        source_types=source_types,
        sections=scored_sections,
    )

    sections_data = guideline_knowledge.get("sections", {})

    if "REC" in source_types:
        result.recommendations = _fetch_recs(
            section_ids, anchor_expanded,
            term_to_family, recommendations_store,
            section_matched_raws,
        )

    if "SYN" in source_types:
        result.synopsis = _fetch_synopsis(section_ids, sections_data)

    if "RSS" in source_types:
        result.rss = _fetch_rss(
            section_ids, anchor_expanded,
            term_to_family, sections_data,
            section_matched_raws,
        )

    if "KG" in source_types:
        result.knowledge_gaps = _fetch_knowledge_gaps(section_ids, sections_data)

    if "TBL" in source_types:
        result.tables = _fetch_tables(section_ids, anchor_lower, maps)

    if "FIG" in source_types:
        result.figures = _fetch_figures(section_ids, maps)

    # FRONT (What's New) is handled as SYN from the front matter section
    if "FRONT" in source_types and "SYN" not in source_types:
        result.synopsis = _fetch_synopsis(section_ids, sections_data)

    logger.info(
        "Step 3 retrieved: %d recs, %d rss, %d synopsis, %d kg, %d tables, %d figures",
        len(result.recommendations), len(result.rss),
        len(result.synopsis), len(result.knowledge_gaps),
        len(result.tables), len(result.figures),
    )

    return result


# ── Synonym expansion ───────────────────────────────────────────────

def _expand_with_synonyms(
    anchor_lower: Set[str],
    term_to_synonyms: Dict[str, Set[str]],
) -> Set[str]:
    """Expand anchor terms with all synonyms from the synonym dictionary.

    'IVT' expands to {'ivt', 'thrombolysis', 'iv thrombolysis',
    'intravenous thrombolysis', 'lytic', 'clot buster'}.

    Terms not in the synonym dictionary pass through unchanged.
    The original terms are always included in the expanded set.
    """
    expanded: Set[str] = set()
    for term in anchor_lower:
        synonyms = term_to_synonyms.get(term)
        if synonyms:
            expanded |= synonyms
        else:
            expanded.add(term)
    return expanded


# ── Level 2: Value-based narrowing ─────────────────────────────────
#
# When the user provides a value for an anchor term (SBP=200, ASPECTS=2),
# we can score sections and content higher when their structured metrics
# are relevant to that value.
#
# Two metric formats:
#   operator-based: {"term": "SBP", "operator": "<", "value": 185}
#     → any user value for this term is relevant (they need the threshold)
#   range-based: {"term": "ASPECTS", "min": 0, "max": 2}
#     → only relevant when user's value overlaps the range
#
# This distinguishes "section mentions SBP" (Level 1 term match) from
# "section has quantitative SBP threshold that applies to this patient"
# (Level 2 value match).


def _normalize_to_range(value: Any) -> Optional[Tuple[float, float]]:
    """Convert a user's anchor term value to a (min, max) range.

    Scalar 200 → (200.0, 200.0)
    Range {"min": 0, "max": 2} → (0.0, 2.0)
    Non-numeric or None → None
    """
    if value is None:
        return None
    if isinstance(value, dict):
        lo = value.get("min")
        hi = value.get("max")
        try:
            lo = float(lo) if lo is not None else None
            hi = float(hi) if hi is not None else None
        except (TypeError, ValueError):
            return None
        if lo is None and hi is None:
            return None
        # If only one bound, treat as point
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
        return (lo, hi)
    try:
        v = float(value)
        return (v, v)
    except (TypeError, ValueError):
        return None


def _value_matches_metric(user_value: Any, metric: Dict[str, Any]) -> bool:
    """Check if a user's anchor term value is relevant to a structured metric.

    Range-based metrics (ASPECTS 0-2): relevant only when the user's
    value overlaps the metric's range. ASPECTS=2 overlaps 0-2 but not 6-10.

    Operator-based metrics (SBP <185): relevant when the user's value
    satisfies the condition. For scalar values, direct comparison. For
    range values, True if ANY part of the range satisfies the condition.

    This means glucose=250 matches ">180" but NOT "<60" — the patient
    is hyperglycemic, not hypoglycemic. NIHSS=4 matches "≤5" but NOT
    "≥6" — the patient has a mild stroke, not severe.

    Level 1 term matching already ensures the section appears — Level 2
    value matching boosts content whose specific thresholds apply to
    this patient's value.
    """
    user_range = _normalize_to_range(user_value)
    if user_range is None:
        return False
    u_lo, u_hi = user_range

    # Range-based metric: check overlap
    if "min" in metric and "max" in metric:
        m_lo = metric.get("min")
        m_hi = metric.get("max")
        if m_lo is None or m_hi is None:
            return False
        try:
            m_lo, m_hi = float(m_lo), float(m_hi)
        except (TypeError, ValueError):
            return False
        # Overlap: user's max >= metric's min AND user's min <= metric's max
        return u_hi >= m_lo and u_lo <= m_hi

    # Operator-based metric: evaluate the condition against the user's value.
    # For range user values, check if ANY part of the range satisfies:
    #   < / ≤ : use u_lo (low end might satisfy "less than")
    #   > / ≥ : use u_hi (high end might satisfy "greater than")
    if "operator" in metric and "value" in metric:
        try:
            threshold = float(metric["value"])
        except (TypeError, ValueError):
            return False
        op = metric["operator"]
        if op == "<":
            return u_lo < threshold
        if op in ("\u2264", "<="):      # ≤
            return u_lo <= threshold
        if op == ">":
            return u_hi > threshold
        if op in ("\u2265", ">="):      # ≥
            return u_hi >= threshold
        return False

    return False


def _compute_value_bonus(
    anchor_values: Dict[str, Any],
    section_id: str,
    section_metrics: Dict[str, List[Dict[str, Any]]],
) -> Tuple[int, List[str]]:
    """Count how many of a section's structured metrics match the user's values.

    Returns (bonus_count, list_of_matched_raw_strings).
    The raw strings (e.g. "SBP <185 mmHg", "ASPECTS 0-2") are used
    for rec/RSS text boosting — recs containing these strings get
    an extra score bump.
    """
    metrics = section_metrics.get(section_id, [])
    if not metrics or not anchor_values:
        return 0, []

    bonus = 0
    matched_raws: List[str] = []

    for metric in metrics:
        term_lower = metric.get("term", "").lower()
        # Does the user have a value for this metric's term?
        user_val = anchor_values.get(term_lower)
        if user_val is None:
            continue
        if _value_matches_metric(user_val, metric):
            bonus += 1
            raw = metric.get("raw", "")
            if raw:
                matched_raws.append(raw.lower())

    return bonus, matched_raws


# ── Section resolution and scoring ──────────────────────────────────

def _resolve_and_score_sections(
    parsed: ParsedQAQuery,
    maps: _RoutingMaps,
) -> Tuple[List[ScoredSection], Dict[str, List[str]]]:
    """Collect sections from topic mapping + anchor term mappings,
    scored by unique concept families matched + value relevance.

    Two levels of scoring:
      Level 1 — anchor term match count (concept families).
        SBP + DBP + BP all belong to "vital_signs" and count as 1.
      Level 2 — value match count (structured metrics).
        SBP=200 boosts sections that have SBP thresholds (<185, <140).
        ASPECTS=2 boosts sections that have ASPECTS 0-2, not 6-10.

    Returns:
      (scored_sections, section_matched_raws)
      section_matched_raws maps section_id → list of matched metric raw
      strings (e.g. ["sbp <185 mmhg", "aspects 0-2"]). These are passed
      to rec/RSS scoring for text-level value boosting.

    Ordering:
      1. Topic primary section first (if present)
      2. Then by descending (value_match_count, anchor_match_count)
    """
    # Track which families each section matches
    section_families: Dict[str, Set[str]] = {}
    topic_primary: Optional[str] = None
    term_to_family = maps.term_to_family

    # Topic → primary section
    if parsed.topic:
        sec = maps.topic_to_section.get(parsed.topic)
        if sec:
            topic_primary = sec
            section_families[sec] = set()

    # Anchor terms → sections, grouped by family
    for term in (parsed.anchor_terms or {}):
        term_lower = term.lower()
        # Resolve family: use synonym dictionary mapping, or fall back
        # to the term itself as a singleton family
        family = term_to_family.get(term_lower, term_lower)

        term_sections = maps.anchor_to_sections.get(term_lower, [])
        for sec in term_sections:
            if sec not in section_families:
                section_families[sec] = set()
            section_families[sec].add(family)

    # Level 2: value-based scoring — anchor term values vs section metrics
    anchor_values = parsed.anchor_values  # lowercased keys, non-None values only
    section_matched_raws: Dict[str, List[str]] = {}

    # Build scored list — family count + value bonus
    scored: List[ScoredSection] = []
    for sec_id, families in section_families.items():
        value_bonus, matched_raws = _compute_value_bonus(
            anchor_values, sec_id, maps.section_metrics,
        )
        if matched_raws:
            section_matched_raws[sec_id] = matched_raws

        scored.append(ScoredSection(
            section_id=sec_id,
            anchor_match_count=len(families),
            value_match_count=value_bonus,
            is_topic_primary=(sec_id == topic_primary),
        ))

    # Sort: topic primary first, then by descending value matches,
    # then by descending family count
    scored.sort(key=lambda s: (
        not s.is_topic_primary,  # False sorts before True → primary first
        -s.value_match_count,    # more value matches first
        -s.anchor_match_count,   # higher family count next
    ))

    return scored, section_matched_raws


# ── Content scoring and narrowing ───────────────────────────────────

def _score_text(
    text: str,
    anchor_expanded: Set[str],
    term_to_family: Dict[str, str],
    matched_raws: Optional[List[str]] = None,
) -> int:
    """Score a text block by unique concept families matched + value relevance.

    Level 1 (concept families): semantically related anchor terms
    (SBP, DBP, BP → vital_signs) count as one match, not three.
    Each unique family found adds 1.

    Level 2 (value relevance): if the rec text contains a metric raw
    string that matched the user's value (e.g. "SBP <185 mmHg" when
    user said SBP=200), add +1 per matched raw string. This boosts
    recs with the specific threshold numbers over recs that just
    mention the term generically.

    Higher score = more diverse concept coverage + more value
    relevance = more useful for the patient's specific scenario.
    Returns 0 if nothing matches — caller decides whether to include or drop.
    """
    if not text:
        return 0
    text_lower = text.lower()

    # Level 1: concept family matches
    matched_families: Set[str] = set()
    for term in anchor_expanded:
        if term in text_lower:
            family = term_to_family.get(term, term)
            matched_families.add(family)

    score = len(matched_families)

    # Level 2: value-matched metric raw strings in the text
    if matched_raws:
        for raw in matched_raws:
            if raw in text_lower:
                score += 1

    return score


def _text_matches_any(
    text: str,
    anchor_expanded: Set[str],
) -> bool:
    """Check if any anchor term (or synonym) appears in the text.

    If the set is empty (no narrowing possible), returns True for everything.
    """
    if not anchor_expanded:
        return True
    text_lower = text.lower()
    for term in anchor_expanded:
        if term in text_lower:
            return True
    return False


# ── Content fetchers (narrowed by anchor terms + clinical values) ───

def _fetch_recs(
    sections: List[str],
    anchor_expanded: Set[str],
    term_to_family: Dict[str, str],
    recommendations_store: Dict[str, Any],
    section_matched_raws: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Fetch recommendations from matched sections, narrowed by anchor terms
    (with synonyms), ordered by concept family + value relevance score.

    Level 1: recs that match at least one anchor term or synonym are included.
    Level 2: recs containing metric raw strings that match the user's values
    (e.g. "SBP <185 mmHg" when user said SBP=200) get boosted higher.

    If no anchor terms exist (broad question), all recs from matched
    sections are included.
    """
    scored_recs: List[Tuple[int, Dict[str, Any]]] = []
    sections_set = set(sections)

    for rec_id, rec in recommendations_store.items():
        rec_section = rec.get("section", "")
        if rec_section not in sections_set:
            continue

        rec_text = rec.get("text", "")
        if not _text_matches_any(rec_text, anchor_expanded):
            continue

        # Get matched raw strings for this rec's section (if any)
        raws = (section_matched_raws or {}).get(rec_section)
        score = _score_text(rec_text, anchor_expanded, term_to_family, raws)
        scored_recs.append((score, rec))

    # Sort by score descending — most relevant recs first
    scored_recs.sort(key=lambda x: -x[0])
    return [rec for _, rec in scored_recs]


def _fetch_synopsis(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch synopsis text for matched sections.

    Synopsis is the section-level narrative — not narrowed by anchor
    terms because it's context for the whole section, not per-rec.
    Sections are already ordered by priority from _resolve_and_score_sections.
    """
    result = {}
    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        synopsis = sec.get("synopsis", "")
        if synopsis:
            result[sec_id] = synopsis
    return result


def _fetch_rss(
    sections: List[str],
    anchor_expanded: Set[str],
    term_to_family: Dict[str, str],
    sections_data: Dict[str, Any],
    section_matched_raws: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Fetch RSS entries from matched sections, narrowed by anchor terms
    (with synonyms), ordered by concept family + value relevance score.

    Level 1: RSS entries that match at least one anchor term or synonym.
    Level 2: entries containing value-matched metric raw strings get boosted.

    If no anchor terms exist, all RSS from matched sections are included.
    """
    scored_entries: List[Tuple[int, Dict[str, Any]]] = []

    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        raws = (section_matched_raws or {}).get(sec_id)
        for rss_entry in sec.get("rss", []):
            rss_text = rss_entry.get("text", "")
            if not _text_matches_any(rss_text, anchor_expanded):
                continue

            score = _score_text(rss_text, anchor_expanded, term_to_family, raws)
            scored_entries.append((score, {
                "section": sec_id,
                "sectionTitle": sec.get("sectionTitle", ""),
                "recNumber": rss_entry.get("recNumber", ""),
                "text": rss_text,
            }))

    # Sort by score descending — most relevant RSS entries first
    scored_entries.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored_entries]


def _fetch_knowledge_gaps(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch knowledge gap text for matched sections.

    KG is section-level — not narrowed by anchor terms.
    Most sections have no KG content.
    """
    result = {}
    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        kg = sec.get("knowledgeGaps", "")
        if kg:
            result[sec_id] = kg
    return result


def _fetch_tables(
    sections: List[str],
    anchor_lower: Set[str],
    maps: _RoutingMaps,
) -> List[Dict[str, Any]]:
    """Fetch table data for tables that belong to matched sections."""
    from ...data.loader import load_table_by_number

    sections_set = set(sections)
    results = []
    for table_name, table_section in maps.table_to_section.items():
        if table_section in sections_set:
            # Extract table number from name (e.g. "Table 3" → 3)
            parts = table_name.split()
            if len(parts) == 2 and parts[1].isdigit():
                table_num = int(parts[1])
                table_data = load_table_by_number(table_num)
                if table_data:
                    results.append({
                        "table_name": table_name,
                        "table_number": table_num,
                        "section": table_section,
                        "data": table_data,
                    })
    return results


def _fetch_figures(
    sections: List[str],
    maps: _RoutingMaps,
) -> List[Dict[str, Any]]:
    """Fetch figure metadata for figures that belong to matched sections."""
    from ...data.loader import load_figure

    sections_set = set(sections)
    results = []
    for fig_num, fig_section in maps.figure_to_section.items():
        if fig_section in sections_set:
            fig_data = load_figure(fig_num)
            if fig_data:
                results.append({
                    "figure_number": fig_num,
                    "section": fig_section,
                    "data": fig_data,
                })
    return results
