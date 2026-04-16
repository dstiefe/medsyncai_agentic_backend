# ─── v5 (Q&A v5 namespace) ─────────────────────────────────────────────
# Step 3: Two-path content retrieval.
#
# Pure Python. No LLM. No regex. Deterministic lookups only.
#
# Two mutually exclusive retrieval paths for RSS/synopsis/KG:
#
#   Path A — Concept Dispatcher (authoritative when it fires):
#     dispatch_concept_sections(intent, anchor_terms) → concept IDs
#     get_sections_by_ids() → category-filtered rows
#     Atom filtering for atomized sections; anchor-term row filtering
#     for non-atomized sections.
#     Synopsis/KG from concept sections only.
#
#   Path B — Scored Search (fallback when Path A returns empty):
#     Anchor router → section boost multipliers
#     Score all RSS by anchor terms + router boost
#     Semantic retriever supplements with embedding-based hits
#     Synopsis/KG from matched sections.
#
# Recs — unified search for both paths:
#   Score all recs by anchor term matching + router boost.
#   Concept-matched recs boosted to 500,000 when Path A fires.
#   Top 15 returned.
#
# KG is only included when intent is in _KG_INTENTS.
# ───────────────────────────────────────────────────────────────────────
"""
Step 3: Two-path content retrieval — concept dispatcher or scored search.

Takes validated Step 1 output (intent, topic, anchor_terms) and:
1. Attempts concept dispatcher (Path A) for precision retrieval
2. Falls back to scored search (Path B) when dispatcher returns empty
3. Searches recs unified across both paths
4. Fetches synopsis, KG, tables, figures from derived sections
5. Returns a RetrievedContent bundle for Step 4 (ResponsePresenter)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .anchor_router import AnchorRouter, SectionMatch
from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)
logger.info("content_retriever v5.1 loaded — anchor-routed retrieval")

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_DATA_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "data",
)


# ── Content search limits ──────────────────────────────────────────
_MAX_RECS_RESULT = 15
_MAX_RSS_RESULT = 10
_CO_OCCURRENCE_FACTOR = 0.3

# ── Router boost ───────────────────────────────────────────────────
# Multiplier applied to content in a router-selected candidate section.
# Top-ranked candidate gets the strongest boost; lower ranks get a
# smaller nudge. Non-candidates are unchanged (not penalised).
# A multiplier of 1.8 on the top candidate means a single matched
# concept there (score 10) beats a two-concept match elsewhere
# (score 10 * 2 * 1.3 = 26 → 18 vs 26, still loses) but a pinpoint
# match (concept + value 20) beats noise (20 * 1.8 = 36 > 26).
_ROUTER_BOOST_TOP = 1.8
_ROUTER_BOOST_RANK2 = 1.4
_ROUTER_BOOST_RANK3 = 1.2
_ROUTER_BOOST_OTHER = 1.05  # any candidate at all gets a nudge


# ── Reference data (loaded once, cached) ─────────────────────────────

def _load_ref_json(filename: str) -> dict:
    path = os.path.join(_REF_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class _RoutingMaps:
    """Lazy-loaded reference maps for content search and section lookup."""

    _instance: Optional[_RoutingMaps] = None

    def __init__(self):
        self._intent_sources: Optional[Dict[str, List[str]]] = None
        self._intent_to_categories: Optional[Dict[str, Set[str]]] = None
        self._topic_to_section: Optional[Dict[str, str]] = None
        self._table_to_section: Optional[Dict[str, str]] = None
        self._figure_to_section: Optional[Dict[int, str]] = None
        self._term_to_family: Optional[Dict[str, str]] = None
        self._term_to_synonyms: Optional[Dict[str, Set[str]]] = None
        self._semantic_units: Optional[List[Dict[str, Any]]] = None
        self._semantic_by_concept: Optional[Dict[str, List[Dict[str, Any]]]] = None

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
                sources = [s.strip() for s in entry["sources"].split("+")]
                self._intent_sources[entry["intent"]] = sources
        return self._intent_sources

    @property
    def intent_to_categories(self) -> Dict[str, Set[str]]:
        """Intent name → set of aligned concept-section categories.

        Built by inverting the concept section catalogue: each concept
        section declares which intents it serves via supported_intents.
        This inverts to intent → which categories are relevant.
        Used for intent-aligned scoring at the row level.
        """
        if self._intent_to_categories is None:
            section_map = _load_ref_json("ais_guideline_section_map.json")
            concept_sections = section_map.get("concept_sections", {})
            mapping: Dict[str, Set[str]] = {}
            if isinstance(concept_sections, dict):
                for cs_id, cs in concept_sections.items():
                    cat = cs.get("category_filter", cs_id)
                    for intent in cs.get("supported_intents", []):
                        mapping.setdefault(intent, set()).add(cat)
            self._intent_to_categories = mapping
        return self._intent_to_categories

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
        drugs and score separately.
        """
        if self._term_to_family is None:
            self._term_to_family = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                family = term_id.lower()
                self._term_to_family[family] = family
                full_term = info.get("full_term", "")
                if full_term:
                    self._term_to_family[full_term.lower()] = family
                for syn in info.get("synonyms", []):
                    self._term_to_family[syn.lower()] = family
        return self._term_to_family

    @property
    def term_to_synonyms(self) -> Dict[str, Set[str]]:
        """Lowercased anchor term → set of all synonyms (including itself).

        Built from synonym_dictionary.json. Every term in a synonym group
        maps to the full set: IVT → {ivt, thrombolysis, iv thrombolysis,
        intravenous thrombolysis, lytic, clot buster}.

        Used for search expansion: when the question says "IVT", we also
        search for "thrombolysis", "alteplase", etc. in content text.
        """
        if self._term_to_synonyms is None:
            self._term_to_synonyms = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                group: Set[str] = {term_id.lower()}
                full_term = info.get("full_term", "")
                if full_term:
                    group.add(full_term.lower())
                for syn in info.get("synonyms", []):
                    group.add(syn.lower())

                for member in group:
                    if member in self._term_to_synonyms:
                        self._term_to_synonyms[member] |= group
                    else:
                        self._term_to_synonyms[member] = set(group)
        return self._term_to_synonyms

    @property
    def semantic_units(self) -> List[Dict[str, Any]]:
        """Flat list of every semantic index unit with section context.

        Each entry: {id, kind, concept|concepts, meaning, section_key,
        section_topic, supports_rec}. section_key is the guideline
        section id ("4.3", "4.6.1", etc.) that the unit lives in.
        Table and figure units carry section_key "TBL"/"FIG" markers.
        """
        if self._semantic_units is None:
            self._semantic_units = []
            data = _load_ref_json("guideline_semantic_index.json")
            for top_key, top_val in data.items():
                if top_key == "_meta" or not isinstance(top_val, dict):
                    continue
                if top_key == "tables":
                    self._flatten_container(top_val, "TBL")
                    continue
                if top_key == "figures":
                    self._flatten_container(top_val, "FIG")
                    continue
                # section_N
                for sub_key, sub_val in top_val.items():
                    if sub_key == "title" or not isinstance(sub_val, dict):
                        continue
                    # Top-level section concepts (section_N.concept/meaning)
                    section_key = sub_key
                    topic = sub_val.get("topic", "")
                    self._ingest_units(sub_val, section_key, topic)
                    # Nested subtopics (4.6.1, 4.6.2 when inside 4.6)
                    for maybe_sub_num, maybe_sub_val in sub_val.items():
                        if (isinstance(maybe_sub_val, dict)
                                and "units" in maybe_sub_val):
                            inner_topic = maybe_sub_val.get("topic", topic)
                            self._ingest_units(
                                maybe_sub_val, maybe_sub_num, inner_topic,
                            )
        return self._semantic_units

    def _ingest_units(
        self,
        container: Dict[str, Any],
        section_key: str,
        topic: str,
    ) -> None:
        """Append units from a topic/subtopic container to the flat list."""
        if self._semantic_units is None:
            self._semantic_units = []
        for unit in container.get("units", []) or []:
            if not isinstance(unit, dict):
                continue
            self._semantic_units.append({
                **unit,
                "section_key": section_key,
                "section_topic": topic,
            })

    def _flatten_container(
        self,
        container: Dict[str, Any],
        marker: str,
    ) -> None:
        """Flatten the tables/ or figures/ top-level container."""
        if self._semantic_units is None:
            self._semantic_units = []
        for name, val in container.items():
            if not isinstance(val, dict):
                continue
            topic = val.get("title", "")
            self._ingest_units(val, marker, topic)

    @property
    def semantic_by_concept(self) -> Dict[str, List[Dict[str, Any]]]:
        """Concept handle → list of units carrying that concept.

        A unit may expose `concept` (string) or `concepts` (list of
        strings); both forms are indexed.
        """
        if self._semantic_by_concept is None:
            index: Dict[str, List[Dict[str, Any]]] = {}
            for unit in self.semantic_units:
                keys = []
                c = unit.get("concept")
                if isinstance(c, str) and c:
                    keys.append(c)
                cs = unit.get("concepts")
                if isinstance(cs, list):
                    keys.extend(k for k in cs if isinstance(k, str))
                for key in keys:
                    index.setdefault(key, []).append(unit)
            self._semantic_by_concept = index
        return self._semantic_by_concept


# ── Data classes ──────────────────────────────────────────────────

@dataclass
class ScoredSection:
    """A section with its tier-weighted score for prioritization."""
    section_id: str
    tier_score: float = 0.0
    matched_term_count: int = 0
    has_discriminating_term: bool = False
    has_primary_role: bool = False
    is_topic_primary: bool = False


@dataclass
class ScoredItem:
    """A content item (rec or RSS) with its relevance score."""
    data: Dict[str, Any]
    score: int = 0


@dataclass
class RetrievedContent:
    """Output of Step 3: everything the presenter needs to answer."""

    raw_query: str
    parsed_query: ParsedQAQuery
    source_types: List[str]
    sections: List[ScoredSection]
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    synopsis: Dict[str, str] = field(default_factory=dict)
    rss: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: Dict[str, str] = field(default_factory=dict)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    figures: List[Dict[str, Any]] = field(default_factory=list)
    semantic_units: List[Dict[str, Any]] = field(default_factory=list)
    # Humanized category labels the exhaustive list path fired for.
    # Empty unless the query matched a categorized collection (e.g.
    # "absolute contraindication", "benefit greater than risk"). The
    # presenter uses this to switch into bullet-list rendering mode
    # regardless of the intent family classification.
    list_mode_categories: List[str] = field(default_factory=list)

    def to_audit_dict(self) -> Dict[str, Any]:
        """Audit trail entry for this retrieval step."""
        return {
            "step": "step3_retrieval",
            "detail": {
                "source_types": self.source_types,
                "sections": [
                    {"id": s.section_id, "tier_score": s.tier_score,
                     "matched_terms": s.matched_term_count,
                     "has_discriminating_term": s.has_discriminating_term,
                     "is_topic_primary": s.is_topic_primary}
                    for s in self.sections
                ],
                "recommendations_count": len(self.recommendations),
                "rss_count": len(self.rss),
                "synopsis_sections": list(self.synopsis.keys()),
                "knowledge_gaps_sections": list(self.knowledge_gaps.keys()),
                "tables_count": len(self.tables),
                "figures_count": len(self.figures),
                "semantic_unit_ids": [
                    u.get("id", "") for u in self.semantic_units
                ],
            },
        }


# ── Content search ─────────────────────────────────────────────────

# Common English words that are NOT clinical concepts.
# Everything else from the question is a potential search term.
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "shall", "may", "might", "can",
    "must", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "about", "between", "through", "during",
    "before", "after", "above", "below", "up", "down", "out", "off",
    "over", "under", "again", "further", "then", "once", "and",
    "but", "or", "nor", "not", "no", "so", "if", "when", "what",
    "which", "who", "whom", "this", "that", "these", "those", "am",
    "it", "its", "i", "me", "my", "we", "our", "you", "your",
    "he", "she", "they", "them", "his", "her", "how", "why",
    "where", "there", "here", "all", "each", "every", "both",
    "any", "some", "such", "than", "too", "very", "just", "also",
    "now", "already", "still", "even", "only", "own", "same",
    "other", "more", "most", "much", "many", "well", "back",
    "get", "got", "give", "given", "take", "taken", "make",
    "made", "go", "went", "gone", "come", "came", "say", "said",
    "tell", "told", "know", "known", "see", "seen", "think",
    "thought", "find", "found", "want", "need", "use", "used",
    "try", "keep", "let", "put", "set", "run", "pay", "last",
    "long", "great", "old", "new", "first", "way", "part", "good",
    "look", "help", "show", "because", "someone", "something",
    "received", "within", "place",
    # Clinical-generic terms that appear in virtually every
    # medical document and inflate scores without adding signal.
    # Only stopped when they come from raw query extraction —
    # if the LLM parser explicitly extracts them as anchor terms,
    # they're kept (e.g., "is there outcome data comparing males
    # and females" → "male" and "female" are real anchors there).
    "patient", "patients", "male", "female", "men", "women",
    "adult", "adults", "child", "children", "person", "people",
    "treatment", "therapy", "management", "outcome", "outcomes",
    "risk", "benefit", "data", "evidence", "study", "studies",
    "recommend", "recommended", "recommendation",
})


def _extract_query_terms(raw_query: str) -> Set[str]:
    """Extract clinically relevant words from the raw query.

    Splits the query into words, removes stop words, and returns
    the remaining terms. These are the actual words the clinician
    used — if a word is in the question and not a stop word, it
    could be clinically relevant and should be searchable.
    """
    words = raw_query.lower().split()
    # Clean punctuation from edges
    cleaned = set()
    for w in words:
        w = w.strip(".,;:!?()[]{}\"'")
        if w and w not in _STOP_WORDS and len(w) > 2:
            cleaned.add(w)
    return cleaned


def _build_search_terms(
    anchor_terms: Optional[Dict[str, Any]],
    term_to_synonyms: Dict[str, Set[str]],
    raw_query: str = "",
) -> Dict[str, Set[str]]:
    """Build synonym-expanded search groups from anchor terms
    AND raw query terms.

    1. Anchor terms get expanded with synonyms from the dictionary.
    2. Raw query words not already covered by anchor terms are added
       as additional search terms — searched as-is.

    This ensures that clinically relevant words from the question
    (like 'headache', 'nasogastric') are always searchable, even
    if Step 1 failed to extract them as anchor terms.

    Returns: concept_key → set of search strings (all lowercased)
    """
    groups: Dict[str, Set[str]] = {}

    # Anchor terms: expand with synonyms where known
    for term in (anchor_terms or {}):
        term_lower = term.lower()
        synonyms = term_to_synonyms.get(term_lower)
        if synonyms:
            groups[term_lower] = set(synonyms)
        else:
            groups[term_lower] = {term_lower}

    # Raw query terms: add any word not already covered
    if raw_query:
        query_terms = _extract_query_terms(raw_query)
        # Check which query terms are already covered by anchor
        # term synonym sets
        covered = set()
        for syns in groups.values():
            covered |= syns

        for qt in query_terms:
            if qt not in covered:
                # Check if this term has synonyms in the dictionary
                synonyms = term_to_synonyms.get(qt)
                if synonyms:
                    # Only add if not already covered by an anchor term
                    if not synonyms & covered:
                        groups[qt] = set(synonyms)
                else:
                    groups[qt] = {qt}

    return groups


import re as _re

# Value-precision scoring bonus.
# When an anchor term has a value (blood pressure: >180) and
# When the query has an anchor term WITH a value/range (e.g.,
# "BP < 140"), content that discusses the same anchor term
# alongside ANY numeric values/thresholds gets this bonus.
# The value guides toward quantitatively specific content,
# not just content mentioning the term in passing. The exact
# number does NOT need to match — any numeric specificity
# near the anchor term is the signal.
_VALUE_GUIDED_BONUS = 10

# When a row's category aligns with the query's intent (e.g.,
# intent=harm_query and category=absolute_contraindications_ivt),
# the row is about the right clinical scenario, not just matching
# on vocabulary. This multiplier separates "aspirin for secondary
# prevention" from "aspirin after IVT" within the same section.
_INTENT_ALIGNMENT_MULTIPLIER = 2.0

# Score thresholds for gating content. A row or rec must clear
# BOTH the absolute floor AND the relative floor (fraction of the
# top-scoring peer) to survive. Absolute floor excludes rows that
# only trivially match (e.g., one anchor term, no intent alignment).
# Relative floor excludes rows that are much weaker than the best
# match in their section/result set.
#
# For a query like "aspirin after IVT" with 3 anchors:
#   - A row matching all 3 anchors (coverage=1.0) + intent-aligned
#     (×2.0) + co-occurrence (×1.9) scores ~100-200.
#   - A row matching only 1 anchor (coverage=0.33) scores ~3.3-6.
#   - Floor of 20 means the weak matches are dropped even if they
#     happen to be in a dispatched concept section.
_ROW_SCORE_ABSOLUTE_FLOOR = 20.0
_ROW_SCORE_RELATIVE_FLOOR = 0.3   # 30% of top row's score
_REC_SCORE_ABSOLUTE_FLOOR = 20.0
_REC_SCORE_RELATIVE_FLOOR = 0.3


def _extract_number(value: Any) -> Optional[int]:
    """Extract the numeric part from an anchor term value.

    Handles: 200, ">180", "<185", ">=4.5", {"min": 0, "max": 2}.
    Returns the primary number as an integer, or None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = _re.search(r"(\d+)", value)
        if match:
            return int(match.group(1))
    if isinstance(value, dict):
        # Range — use max as the primary number
        for key in ("max", "min"):
            v = value.get(key)
            if v is not None:
                return int(v)
    return None


def _has_numeric_context(text: str, term: str,
                         window: int = 120) -> bool:
    """Check if ANY number/threshold appears near a term in the text.

    When the query has a value (e.g., "BP < 140"), content that
    discusses the same term alongside any numeric specificity is
    a better match than content mentioning the term generically.
    The exact number does not need to match — the presence of
    quantitative context near the anchor term is the signal.

    "blood pressure" + text "SBP target <185 mm Hg" → True
    "blood pressure" + text "manage blood pressure" → False
    """
    idx = text.find(term)
    if idx < 0:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    neighborhood = text[start:end]
    # Any number (integer or decimal) near the term
    return bool(_re.search(r"\d+(?:\.\d+)?", neighborhood))


# ── Scoring surfaces ──────────────────────────────────────────────
#
# The scorer only reads one flat string per entry. Structured fields
# like rss_entry["category"] or rec["cor"] carry the classification
# signal ("absolute_contraindication", "3: Harm") but are invisible
# if we only hand it the narrative text. These helpers concatenate
# the structured fields into the scored surface so a query for
# "absolute contraindications" can match a row whose text never
# says "contraindication" but whose category field does.
#
# Downstream callers still see the raw entry unchanged — the helper
# output is only used for scoring, never for display.

def _humanize(slug: str) -> str:
    """Convert 'absolute_contraindication' → 'absolute contraindication'."""
    if not slug:
        return ""
    return str(slug).replace("_", " ")


def _scoring_surface_rss(rss_entry: Dict[str, Any]) -> str:
    """Build the concept-match surface for an RSS row.

    Includes condition (row label), category (Table 8 band), and
    the body text. Fields are separated by ' | ' so that synonym
    substring matching on the combined string cannot bleed across
    field boundaries in a misleading way.
    """
    parts = [
        rss_entry.get("condition", "") or "",
        _humanize(rss_entry.get("category", "")),
        rss_entry.get("text", "") or "",
    ]
    return " | ".join(p for p in parts if p)


def _scoring_surface_rec(rec: Dict[str, Any]) -> str:
    """Build the concept-match surface for a recommendation entry.

    Includes COR label ('3: Harm', '2a'), LOE ('B-R'), and the
    recommendation text. This lets 'harm recommendation' or 'COR 3'
    queries hit the right recs even when the narrative text never
    uses those terms.
    """
    cor = rec.get("cor", "") or ""
    loe = rec.get("loe", "") or ""
    text = rec.get("text", "") or ""
    cor_label = f"COR {cor}" if cor else ""
    loe_label = f"LOE {loe}" if loe else ""
    parts = [cor_label, loe_label, text]
    return " | ".join(p for p in parts if p)


def _score_content_match(
    text: str,
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]] = None,
    row_category: str = "",
    aligned_categories: Optional[Set[str]] = None,
) -> float:
    """Score a text block by anchor coverage, value guidance, and intent alignment.

    Scoring dimensions:
    1. Anchor term coverage — ratio of query concepts matched.
       3/3 concepts = full match, 1/3 = partial.
    2. Value-guided boost — when the query has a value (e.g.,
       "BP < 140"), content with ANY numeric context near the
       matching term scores higher. The exact value doesn't need
       to match; numeric specificity near the anchor term signals
       the content is about the quantitative aspect, not just
       mentioning the term in passing.
    3. Co-occurrence bonus — entries matching multiple concepts
       are disproportionately more relevant.
    4. Intent alignment — when the row's category matches one of
       the intent-aligned categories, the content is about the
       right clinical scenario (not just matching vocabulary).
       This separates "aspirin for secondary prevention" from
       "aspirin after IVT" within the same section.
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    total_concepts = len(search_terms)
    matched = 0
    value_guided_hits = 0

    for concept, synonyms in search_terms.items():
        value = (anchor_values or {}).get(concept)
        has_value = value is not None

        for syn in synonyms:
            if syn in text_lower:
                matched += 1
                # Value-guided check: when the query has a value
                # for this concept, does the content discuss the
                # same term with any numeric specificity?
                if has_value:
                    if _has_numeric_context(text_lower, syn):
                        value_guided_hits += 1
                break

    if matched == 0:
        return 0.0

    # Base score: 10 points per concept matched
    score = float(matched * 10)

    # Value-guided bonus: content with numeric context near the
    # anchor term is more relevant when the query is value-specific
    score += value_guided_hits * _VALUE_GUIDED_BONUS

    # Co-occurrence bonus: entries matching multiple concepts
    # are disproportionately more relevant
    if matched >= 2:
        score *= (1.0 + _CO_OCCURRENCE_FACTOR * (matched - 1))

    # Coverage ratio: penalize partial matches. 3/3 = 1.0x,
    # 2/3 = 0.67x, 1/3 = 0.33x. This ensures content matching
    # all query concepts ranks far above content matching only one.
    if total_concepts > 0:
        coverage = matched / total_concepts
        score *= coverage

    # Intent alignment: boost rows whose category matches the
    # intent's expected clinical scenario. Without this, all 18
    # rows in §4.8 score similarly on anchor terms alone.
    if aligned_categories and row_category:
        if row_category in aligned_categories:
            score *= _INTENT_ALIGNMENT_MULTIPLIER

    return score


def _build_router_boosts(
    matches: List[SectionMatch],
) -> Dict[str, float]:
    """Convert an ordered router result into section → boost multiplier.

    Only candidates with a positive Stage-2 score are boosted (Stage 2
    is the discriminating pass — if a section only shows up because of
    global terms like "AIS" or "stroke", it's not a real signal).
    """
    boosts: Dict[str, float] = {}
    rank = 0
    for match in matches:
        if match.stage2_score <= 0:
            continue
        rank += 1
        if rank == 1:
            boosts[match.section_id] = _ROUTER_BOOST_TOP
        elif rank == 2:
            boosts[match.section_id] = _ROUTER_BOOST_RANK2
        elif rank == 3:
            boosts[match.section_id] = _ROUTER_BOOST_RANK3
        else:
            boosts[match.section_id] = _ROUTER_BOOST_OTHER
    return boosts


def _apply_router_boost(
    score: float,
    section_id: str,
    router_boosts: Dict[str, float],
) -> float:
    """Multiply a raw content score by its section's router boost."""
    if not router_boosts or not section_id:
        return score
    mult = router_boosts.get(section_id, 1.0)
    return score * mult


def _fetch_tables(
    sections: List[str],
    anchor_lower: Set[str],
    maps: _RoutingMaps,
) -> List[Dict[str, Any]]:
    """Fetch table data for tables that belong to derived sections."""
    from ...data.loader import load_table_by_number

    sections_set = set(sections)
    results = []
    for table_name, table_section in maps.table_to_section.items():
        if table_section in sections_set:
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
    """Fetch figure metadata for figures that belong to derived sections."""
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


# ── KG intent gating ─────────────────────────────────────────────
_KG_INTENTS: frozenset = frozenset({
    "knowledge_gap", "current_understanding_and_gaps",
    "evidence_vs_gaps", "rationale_with_uncertainty",
    "recommendation_with_confidence", "pediatric_specific",
})


# ── RSS row formatter ────────────────────────────────────────────

def _format_rss_row(
    section_id: str,
    section_title: str,
    row: Dict[str, Any],
    score: float = 0.0,
    concept_dispatched: bool = False,
) -> Dict[str, Any]:
    """Build the standard RSS row dict shape used everywhere."""
    result = {
        "section": section_id,
        "sectionTitle": section_title,
        "recNumber": row.get("recNumber", ""),
        "category": row.get("category", ""),
        "condition": row.get("condition", ""),
        "text": row.get("text", "") or "",
        "_score": score,
    }
    if concept_dispatched:
        result["_concept_dispatched"] = True
    return result


# ── Path A: Concept Dispatcher ───────────────────────────────────

def _path_a_retrieve(
    concept_section_ids: List[str],
    search_terms: Dict[str, Set[str]],
    parsed: ParsedQAQuery,
    include_kg: bool,
    aligned_categories: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Dict[str, str]]:
    """Concept dispatcher path — authoritative when it fires.

    1. get_sections_by_ids for category-filtered sections
    2. Atom filtering for atomized sections, anchor-term row
       filtering for non-atomized sections
    3. Synopsis/KG from concept sections only
    """
    from .knowledge_loader import (
        get_sections_by_ids, get_section, load_concept_section_catalogue,
    )
    from . import atom_retriever

    concept_entries = get_sections_by_ids(concept_section_ids)

    # ── Temporal/relational semantic scoring ────────────────────
    # Clinical questions often encode temporal relationships between
    # anchor terms: "aspirin AFTER IVT", "BP BEFORE reperfusion",
    # "within 24 HOURS of onset." These relational words distinguish
    # the clinical scenario — "aspirin after IVT" (timing) vs
    # "aspirin instead of IVT" (substitution).
    #
    # Extract relational words from the query that sit between or
    # near anchor terms. Then boost rows whose text contains the
    # same relational words near the same anchor terms.
    _TEMPORAL_RELATIONAL_WORDS = frozenset({
        "after", "before", "during", "within", "following",
        "prior", "concurrent", "concurrently", "post",
        "hours", "minutes", "days",
        "instead", "substitute", "alternative", "replacement",
    })
    _RELATIONAL_BONUS = 15.0  # per relational word matched in text

    # Extract which relational words appear in the query
    query_text = (parsed.question_summary or "").lower()
    if not query_text:
        query_text = " ".join(
            str(k).lower() for k in (parsed.anchor_terms or {})
        )
    query_relational = {
        w for w in query_text.split()
        if w in _TEMPORAL_RELATIONAL_WORDS
    }

    rss_rows: List[Dict[str, Any]] = []

    for cid, entry in concept_entries.items():
        sec_title = entry.get("sectionTitle", "") or ""
        raw_rss = entry.get("rss", []) or []

        # Atomized sections: let atom_retriever select the best atoms
        if atom_retriever.section_has_atoms(cid):
            atoms = atom_retriever.select_atoms_for_section(
                cid, parsed,
            )
            if atoms is not None:
                for atom in atoms:
                    rss_rows.append(_format_rss_row(
                        cid, sec_title, atom,
                        score=atom.get("_score", 1_000_000.0),
                        concept_dispatched=True,
                    ))
                continue

        # Non-atomized: score rows by anchor terms + temporal/relational
        # semantic match, then gate by score threshold.
        scored_rows: List[Tuple[float, Dict[str, Any]]] = []
        for row in raw_rss:
            scoring_text = _scoring_surface_rss(row)
            score = _score_content_match(
                scoring_text, search_terms, parsed.anchor_terms,
                row_category=row.get("category", ""),
                aligned_categories=aligned_categories,
            )
            # Temporal/relational bonus: if the query has relational
            # words (after, before, during, within, etc.), boost rows
            # that contain the same relational words. This separates
            # "aspirin after IVT" (rec 17) from "aspirin substitute
            # for IVT" (rec 16).
            if query_relational:
                text_lower = (row.get("text") or "").lower()
                text_words = set(text_lower.split())
                shared_relational = query_relational & text_words
                score += len(shared_relational) * _RELATIONAL_BONUS
            scored_rows.append((score, row))
        scored_rows.sort(key=lambda x: -x[0])

        # Score-based gating: a row must clear the absolute floor
        # AND score within a meaningful fraction of this section's
        # top-scoring row. This drops rows that only weakly match
        # (e.g., mention "IVT" but not the question's clinical
        # scenario) even when they're in a dispatched concept section.
        filtered: List[Tuple[float, Dict[str, Any]]] = []
        if scored_rows:
            section_top = scored_rows[0][0]
            section_floor = max(
                _ROW_SCORE_ABSOLUTE_FLOOR,
                section_top * _ROW_SCORE_RELATIVE_FLOOR,
            )
            for score, row in scored_rows:
                if score >= section_floor:
                    filtered.append((score, row))

        # If NO rows in this concept section cleared the threshold,
        # the dispatcher misfired — this section isn't actually about
        # what the clinician asked. Drop the whole section rather
        # than flooding the output with off-topic content.
        if not filtered:
            logger.info(
                "Step 3 Path A: dropping concept section %s — "
                "no rows cleared score threshold (top_score=%.1f)",
                cid, scored_rows[0][0] if scored_rows else 0.0,
            )
            continue

        for score, row in filtered:
            rss_rows.append(_format_rss_row(
                cid, sec_title, row,
                score=max(score, 1_000_000.0),
                concept_dispatched=True,
            ))

    logger.info(
        "Step 3 Path A: %d concept sections → %d rss rows",
        len(concept_entries), len(rss_rows),
    )

    # Synopsis from concept sections
    synopsis: Dict[str, str] = {}
    for cid in concept_section_ids:
        entry = get_section(cid)
        if not entry:
            continue
        syn = entry.get("synopsis", "")
        if isinstance(syn, str) and syn:
            synopsis[cid] = syn
        elif isinstance(syn, dict):
            joined = "\n\n".join(v for v in syn.values() if v)
            if joined:
                synopsis[cid] = joined

    # KG from concept sections, only if intent calls for it
    knowledge_gaps: Dict[str, str] = {}
    if include_kg:
        for cid in concept_section_ids:
            entry = get_section(cid)
            if not entry:
                continue
            kg = entry.get("knowledgeGaps", "")
            if isinstance(kg, str) and kg:
                knowledge_gaps[cid] = kg
            elif isinstance(kg, dict):
                joined = "\n\n".join(v for v in kg.values() if v)
                if joined:
                    knowledge_gaps[cid] = joined

    return rss_rows, synopsis, knowledge_gaps


# ── Path B: Scored Search ────────────────────────────────────────

def _path_b_retrieve(
    search_terms: Dict[str, Set[str]],
    parsed: ParsedQAQuery,
    raw_query: str,
    router_boosts: Dict[str, float],
    sections_data: Dict[str, Any],
    include_kg: bool,
    aligned_categories: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], Dict[str, str]]:
    """Scored search fallback — runs when Path A returns empty.

    1. Semantic retriever for embedding-based hits
    2. Score all RSS rows by anchor terms + router boost
    3. Merge, dedup, keep top _MAX_RSS_RESULT
    4. Synopsis/KG from derived sections
    """
    from . import semantic_retriever

    # Semantic retriever: embedding-based search
    semantic_rss = semantic_retriever.search_rss_rows(
        raw_query, parsed, k=15,
    )
    if semantic_rss:
        logger.info(
            "Step 3 Path B semantic: %d atoms (top_score=%.3f)",
            len(semantic_rss),
            semantic_rss[0].get("_score", 0.0),
        )

    # Score all RSS rows in sections_data
    anchor_scored: List[Tuple[float, Dict[str, Any]]] = []
    for sec_id, sec in sections_data.items():
        sec_title = sec.get("sectionTitle", "") or ""
        for rss_entry in sec.get("rss", []) or []:
            scoring_text = _scoring_surface_rss(rss_entry)
            raw_score = _score_content_match(
                scoring_text, search_terms, parsed.anchor_terms,
                row_category=rss_entry.get("category", ""),
                aligned_categories=aligned_categories,
            )
            if raw_score <= 0:
                continue
            score = _apply_router_boost(raw_score, sec_id, router_boosts)
            anchor_scored.append((score, _format_rss_row(
                sec_id, sec_title, rss_entry, score=score,
            )))

    anchor_scored.sort(key=lambda x: -x[0])

    # Score-based gating for anchor-scored rows. Same unified rule
    # as Path A: row must clear absolute floor AND relative floor
    # (fraction of top anchor-scored row).
    if anchor_scored:
        top_score = anchor_scored[0][0]
        score_floor = max(
            _ROW_SCORE_ABSOLUTE_FLOOR,
            top_score * _ROW_SCORE_RELATIVE_FLOOR,
        )
        anchor_scored = [
            (s, r) for s, r in anchor_scored if s >= score_floor
        ]

    # Merge: semantic results first, then gated anchor-scored,
    # dedup by (section, recNumber)
    seen: Set[Tuple[str, str]] = set()
    merged: List[Dict[str, Any]] = []

    for row in semantic_rss:
        key = (row.get("section", ""), row.get("recNumber", ""))
        if key not in seen:
            seen.add(key)
            merged.append(row)

    for _score, row in anchor_scored:
        key = (row.get("section", ""), row.get("recNumber", ""))
        if key not in seen:
            seen.add(key)
            merged.append(row)

    rss_rows = merged[:_MAX_RSS_RESULT]

    # Derive sections from matched RSS
    derived_sections: Set[str] = set()
    for row in rss_rows:
        sec = row.get("section", "")
        if sec:
            derived_sections.add(sec)

    # Synopsis from derived sections
    synopsis: Dict[str, str] = {}
    for sec_id in derived_sections:
        sec = sections_data.get(sec_id, {})
        syn = sec.get("synopsis", "")
        if isinstance(syn, str) and syn:
            synopsis[sec_id] = syn
        elif isinstance(syn, dict):
            joined = "\n\n".join(v for v in syn.values() if v)
            if joined:
                synopsis[sec_id] = joined

    # KG from derived sections, only if intent calls for it
    knowledge_gaps: Dict[str, str] = {}
    if include_kg:
        for sec_id in derived_sections:
            sec = sections_data.get(sec_id, {})
            kg = sec.get("knowledgeGaps", "")
            if isinstance(kg, str) and kg:
                knowledge_gaps[sec_id] = kg
            elif isinstance(kg, dict):
                joined = "\n\n".join(v for v in kg.values() if v)
                if joined:
                    knowledge_gaps[sec_id] = joined

    logger.info(
        "Step 3 Path B: %d semantic + %d anchor-scored → %d merged rss",
        len(semantic_rss), len(anchor_scored), len(rss_rows),
    )

    return rss_rows, synopsis, knowledge_gaps


# ── Unified rec search ───────────────────────────────────────────

def _search_recs(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    recommendations_store: Dict[str, Any],
    topic_section: Optional[str],
    router_boosts: Dict[str, float],
    concept_section_ids: Optional[List[str]] = None,
    aligned_categories: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Single unified rec search for both paths.

    1. Score all recs by anchor term matching + router boost +
       intent alignment (via concept_category → aligned_categories)
    2. When concept_section_ids is provided, boost concept-matched
       recs to 500,000 and auto-include any missed ones
    3. Sort by score descending, return top _MAX_RECS_RESULT
    """
    concept_cat_set = set(concept_section_ids or [])

    # Score all recs
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for rec_id, rec in recommendations_store.items():
        scoring_text = _scoring_surface_rec(rec)
        raw_score = _score_content_match(
            scoring_text, search_terms, anchor_values,
            row_category=rec.get("concept_category", ""),
            aligned_categories=aligned_categories,
        )
        if raw_score <= 0:
            continue
        sec = rec.get("section", "")
        score = _apply_router_boost(raw_score, sec, router_boosts)
        if topic_section and sec == topic_section:
            score += 0.1
        scored.append((score, {**rec, "_score": score}))

    scored.sort(key=lambda x: -x[0])

    if concept_cat_set:
        # Path A: concept-matched recs are the primary answer.
        # Supplementary recs must clear BOTH the absolute floor
        # AND the relative floor (fraction of top score) to be
        # included. Same unified gating as rows.
        concept_recs: List[Dict[str, Any]] = []
        supplementary_recs: List[Dict[str, Any]] = []

        # Collect ALL concept-matched recs from the store
        for rec_id, rec in recommendations_store.items():
            cc = rec.get("concept_category", "")
            if cc in concept_cat_set:
                rec_score = 0.0
                for s, r in scored:
                    if r.get("id") == rec_id:
                        rec_score = s
                        break
                concept_recs.append({
                    **rec, "_score": max(rec_score, 500_000.0),
                    "_concept_boosted": True,
                })

        concept_recs.sort(key=lambda x: -x.get("_score", 0))

        top_score = scored[0][0] if scored else 1.0
        score_floor = max(
            _REC_SCORE_ABSOLUTE_FLOOR,
            top_score * _REC_SCORE_RELATIVE_FLOOR,
        )
        concept_ids = {r.get("id") for r in concept_recs}
        for _score, rec in scored:
            if rec.get("id") in concept_ids:
                continue
            if _score >= score_floor:
                supplementary_recs.append(rec)

        logger.info(
            "Step 3 recs Path A: %d concept + %d supplementary "
            "(floor=%.1f, top=%.1f)",
            len(concept_recs), len(supplementary_recs),
            score_floor, top_score,
        )
        results = concept_recs + supplementary_recs
    else:
        # Path B: apply same unified gating — absolute floor + relative
        top_score = scored[0][0] if scored else 1.0
        score_floor = max(
            _REC_SCORE_ABSOLUTE_FLOOR,
            top_score * _REC_SCORE_RELATIVE_FLOOR,
        )
        gated = [(s, r) for s, r in scored if s >= score_floor]
        results = [entry for _, entry in gated[:_MAX_RECS_RESULT]]
        logger.info(
            "Step 3 recs Path B: %d/%d recs cleared floor=%.1f (top=%.1f)",
            len(results), len(scored), score_floor, top_score,
        )

    return results


# ── Main retrieval function ──────────────────────────────────────────

def retrieve_content(
    parsed: ParsedQAQuery,
    raw_query: str,
    recommendations_store: Dict[str, Any],
    guideline_knowledge: Dict[str, Any],
) -> RetrievedContent:
    """
    Two-path content retrieval: concept dispatcher (Path A) when it
    fires, scored search (Path B) as fallback. Recs searched unified.

    1. Attempt concept dispatcher for precision retrieval
    2. Fall back to scored search when dispatcher returns empty
    3. Search recs unified across both paths
    4. Fetch tables, figures from derived sections
    5. Build RetrievedContent for Step 4
    """
    maps = _RoutingMaps.get()

    # ── Source type gating by intent ────────────────────────────────
    # The intent map declares which content types each intent needs.
    # We only fetch what's declared — no "retrieve everything, filter
    # later." This is how Python knows which parts to go to.
    declared_sources = set(maps.intent_sources.get(
        parsed.intent, ["REC", "SYN"],
    ))
    include_recs = "REC" in declared_sources
    include_rss = True  # always — clinicians need supporting evidence
    include_syn = "SYN" in declared_sources
    include_kg = (parsed.intent or "") in _KG_INTENTS
    include_tbl = "TBL" in declared_sources
    include_fig = "FIG" in declared_sources

    # For audit trail / RetrievedContent metadata
    source_types = sorted(declared_sources)

    # ── Topic → section (tiebreaker, not primary routing) ────────
    topic_section = None
    if parsed.topic:
        topic_section = maps.topic_to_section.get(parsed.topic)

    # ── Build search terms from anchor terms + raw query ─────────
    search_terms = _build_search_terms(
        parsed.anchor_terms, maps.term_to_synonyms, raw_query,
    )

    # ── Anchor-word deterministic router ─────────────────────────
    router_anchor_terms = list((parsed.anchor_terms or {}).keys())
    router_matches = AnchorRouter.get().route(router_anchor_terms)
    router_boosts = _build_router_boosts(router_matches)
    if router_matches:
        logger.info(
            "Step 3 router: %s",
            [f"{m.section_id}(s2={m.stage2_score:.1f})"
             for m in router_matches[:5]],
        )

    logger.info(
        "Step 3: intent=%s (declared_sources=%s), topic=%s, "
        "anchor_terms=%s, search_terms=%s, router_top=%s",
        parsed.intent, declared_sources, parsed.topic,
        parsed.anchor_terms,
        {k: sorted(v)[:3] for k, v in search_terms.items()},
        router_matches[0].section_id if router_matches else None,
    )

    # ── Load sections data ───────────────────────────────────────
    from .knowledge_loader import (
        load_sections_store,
        dispatch_concept_sections,
        load_concept_section_catalogue,
    )
    sections_data = load_sections_store()

    # ── Intent-aligned categories for scoring ─────────────────────
    # Rows whose category matches the intent's expected clinical
    # scenario get a scoring boost. This separates "aspirin for
    # secondary prevention" from "aspirin after IVT" even when
    # both mention the same anchor terms.
    aligned_categories = maps.intent_to_categories.get(
        parsed.intent or "", set(),
    )

    # ── Concept dispatcher: try Path A ───────────────────────────
    concept_section_ids: List[str] = []
    try:
        concept_section_ids = dispatch_concept_sections(
            intent=parsed.intent,
            anchor_terms=parsed.anchor_terms,
        )
    except Exception as e:
        logger.warning("Step 3 dispatcher failed: %s", e)
        concept_section_ids = []

    # ── PATH DECISION ────────────────────────────────────────────
    # RSS/synopsis/KG: gated by declared_sources AND path decision.
    matched_rss: List[Dict[str, Any]] = []
    synopsis: Dict[str, str] = {}
    knowledge_gaps: Dict[str, str] = {}

    needs_rss_or_syn = include_rss or include_syn
    if concept_section_ids and needs_rss_or_syn:
        matched_rss, synopsis, knowledge_gaps = _path_a_retrieve(
            concept_section_ids, search_terms, parsed, include_kg,
            aligned_categories=aligned_categories,
        )
        # Gate: drop content types not declared by intent
        if not include_rss:
            matched_rss = []
        if not include_syn:
            synopsis = {}
        logger.info(
            "Step 3 took Path A: %d concept sections (%s)",
            len(concept_section_ids), concept_section_ids,
        )
    elif needs_rss_or_syn:
        matched_rss, synopsis, knowledge_gaps = _path_b_retrieve(
            search_terms, parsed, raw_query, router_boosts,
            sections_data, include_kg,
            aligned_categories=aligned_categories,
        )
        if not include_rss:
            matched_rss = []
        if not include_syn:
            synopsis = {}
        logger.info("Step 3 took Path B (scored search fallback)")
    else:
        logger.info(
            "Step 3: skipping RSS/SYN retrieval "
            "(declared_sources=%s)", declared_sources,
        )

    # ── Recs: gated by include_recs ─────────────────────────────
    matched_recs: List[Dict[str, Any]] = []
    if include_recs:
        matched_recs = _search_recs(
            search_terms, parsed.anchor_terms,
            recommendations_store, topic_section, router_boosts,
            concept_section_ids=concept_section_ids or None,
            aligned_categories=aligned_categories,
        )

    # ── Derive content_sections for tables/figures ───────────────
    # For recs, exclude parent sections covered by concept sections
    # to avoid dumping entire section content.
    concept_parent_sections: Set[str] = set()
    if concept_section_ids:
        catalogue = load_concept_section_catalogue()
        for cid in concept_section_ids:
            entry = catalogue.get(cid, {})
            parent = entry.get("content_section_id", "")
            if parent:
                concept_parent_sections.add(parent)

    content_sections: Set[str] = set()
    for rec in matched_recs:
        sec = rec.get("section", "")
        if sec and sec not in concept_parent_sections:
            content_sections.add(sec)
    for rss in matched_rss:
        sec = rss.get("section", "")
        if sec:
            content_sections.add(sec)
    for cid in concept_section_ids:
        content_sections.add(cid)

    # Fallback: if content search found nothing, use topic section
    if not content_sections and topic_section:
        content_sections.add(topic_section)
        logger.info(
            "Step 3: no content matches, falling back to "
            "topic section %s", topic_section,
        )

    section_ids = list(content_sections)

    # ── Build scored sections for audit trail ────────────────────
    scored_sections = [
        ScoredSection(
            section_id=s,
            is_topic_primary=(s == topic_section),
        )
        for s in section_ids
    ]

    # ── Fetch tables and figures (gated by declared sources) ─────
    tables: List[Dict[str, Any]] = []
    figures: List[Dict[str, Any]] = []
    if include_tbl:
        anchor_lower = {
            t.lower() for t in (parsed.anchor_terms or {})
        }
        tables = _fetch_tables(section_ids, anchor_lower, maps)
    if include_fig:
        figures = _fetch_figures(section_ids, maps)

    result = RetrievedContent(
        raw_query=raw_query,
        parsed_query=parsed,
        source_types=source_types,
        sections=scored_sections,
        recommendations=matched_recs,
        synopsis=synopsis,
        rss=matched_rss,
        knowledge_gaps=knowledge_gaps,
        tables=tables,
        figures=figures,
        semantic_units=[],
        list_mode_categories=[],
    )

    logger.info(
        "Step 3 retrieved: %d recs, %d rss, %d synopsis, %d kg, "
        "%d tables, %d figures (sections: %s)",
        len(result.recommendations), len(result.rss),
        len(result.synopsis), len(result.knowledge_gaps),
        len(result.tables), len(result.figures),
        section_ids,
    )

    return result
