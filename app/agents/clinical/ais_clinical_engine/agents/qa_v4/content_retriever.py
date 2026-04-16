# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 3: Content-first search + retrieval.
#
# Pure Python. No LLM. No regex. Deterministic lookups only.
#
# Content Search:
#   Take anchor terms from Step 1, expand with synonyms where known,
#   and search ALL content entries (recs, RSS) for matches.
#   Score each entry by how many distinct anchor concepts it contains.
#   Co-occurrence bonus when 2+ concepts match in the same entry.
#   Top-scoring entries are returned.
#
# Sections are DERIVED from matched content, not pre-selected.
#   Synopsis and knowledge gaps are fetched from derived sections.
#
# Synonym expansion uses synonym_dictionary.json:
#   Known terms (IVT, alteplase, SBP) are expanded to all synonyms.
#   Unknown terms (headache, nausea) are searched as-is.
# ───────────────────────────────────────────────────────────────────────
"""
Step 3: Content-first search — anchor terms search content directly.

Takes validated Step 1 output (intent, topic, anchor_terms) and:
1. Builds synonym-expanded search groups from anchor terms
2. Searches ALL recs and RSS entries for anchor term matches
3. Scores entries by concept match count (co-occurrence bonus)
4. Derives sections from top-scoring entries
5. Fetches synopsis, knowledge gaps, tables, figures from derived sections
6. Returns a RetrievedContent bundle for Step 4 (ResponsePresenter)
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
# the content contains that EXACT number (180), this bonus
# is added. Entries with the specific number the clinician
# asked about score higher than entries with other numbers.
_VALUE_PRECISION_BONUS = 10


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


def _has_specific_number(text: str, term: str, number: int,
                         window: int = 120) -> bool:
    """Check if a specific number appears near a term in the text.

    "blood pressure: >180" + text "SBP is >180 mm Hg" → True
    "blood pressure: >180" + text "SBP lowered to <185" → False
    """
    idx = text.find(term)
    if idx < 0:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    neighborhood = text[start:end]
    # Look for the specific number as a whole token
    # (not as part of a larger number)
    return bool(_re.search(r"(?<!\d)" + str(number) + r"(?!\d)",
                           neighborhood))


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
) -> float:
    """Score a text block by how many anchor concepts it matches.

    Each search_term group represents one clinical concept.
    If any synonym in the group appears in the text, that concept
    is matched. Score = number of distinct concepts matched.

    Value-precision: when an anchor term has a value (e.g.,
    blood pressure: >180), the specific number (180) is checked
    in the text near the matching synonym. If found, a precision
    bonus is added. This makes "SBP >180 mm Hg" score higher
    than "SBP <185 mm Hg" for a query about >180.

    Co-occurrence bonus when 2+ concepts match in the same entry.
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    matched = 0
    precision_hits = 0

    for concept, synonyms in search_terms.items():
        value = (anchor_values or {}).get(concept)
        target_number = _extract_number(value) if value is not None else None

        for syn in synonyms:
            if syn in text_lower:
                matched += 1
                # Value-precision check: does the specific number
                # appear near this synonym in the text?
                if target_number is not None:
                    if _has_specific_number(text_lower, syn,
                                            target_number):
                        precision_hits += 1
                break

    if matched == 0:
        return 0.0

    # Base score: 10 points per concept matched
    score = float(matched * 10)

    # Value-precision bonus: entries with the exact number
    # the clinician asked about score higher
    score += precision_hits * _VALUE_PRECISION_BONUS

    # Co-occurrence bonus: entries matching multiple concepts
    # are disproportionately more relevant
    if matched >= 2:
        score *= (1.0 + _CO_OCCURRENCE_FACTOR * (matched - 1))

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


def _router_rss_gate(
    matches: List[SectionMatch],
) -> Optional[Set[str]]:
    """When the router's top section is a Table, return the set of
    router-preferred Table sections so RSS retrieval can be gated to
    them.

    Rationale: Tables are atomized short units (e.g. Table 4's
    "Complete hemianopsia"). Long prose sections like §4.6.1 that
    merely discuss the same concept will always out-score short
    atoms on raw text-density. Router boost alone cannot overcome
    that — §4.6.1 has 14 rows of dense prose, each packed with the
    anchor term. When the router has clearly decided the correct
    answer lives in a Table, retrieval must honor that decision by
    restricting the RSS pool to the Table rows, not just nudging
    them up in the global ranking.

    Only fires when the TOP router candidate is a Table. If the top
    candidate is a prose section, no gating — prose search runs as
    normal and tables can still surface via boost.

    Gate set: all Table sections in the router output whose Stage-2
    score is at least 50% of the top score. This allows related
    Table sections (e.g. Table 4 + Table 7 for IVT eligibility
    questions) to co-surface but excludes tables that only trickled
    in via weak matches.

    Returns None when no gating applies.
    """
    if not matches:
        return None
    top = matches[0]
    if top.stage2_score <= 0:
        return None
    if not top.section_id.startswith("Table "):
        return None
    threshold = top.stage2_score * 0.5
    gated: Set[str] = set()
    for m in matches:
        if (
            m.stage2_score >= threshold
            and m.section_id.startswith("Table ")
        ):
            gated.add(m.section_id)
    return gated or None


def _search_all_recs(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    recommendations_store: Dict[str, Any],
    topic_section: Optional[str],
    router_boosts: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Search ALL recs for anchor term matches.

    Scores each rec by concept match count, then applies the
    router's section-level boost so recs in deterministic candidate
    sections float to the top. Returns top results.
    """
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for rec_id, rec in recommendations_store.items():
        # Include COR/LOE in the scored surface so queries about
        # "harm recommendations", "COR 3", or "no benefit" can hit
        # recs even when those terms are only in the metadata.
        scoring_text = _scoring_surface_rec(rec)
        raw_score = _score_content_match(
            scoring_text, search_terms, anchor_values,
        )
        if raw_score <= 0:
            continue
        sec = rec.get("section", "")
        score = _apply_router_boost(raw_score, sec, router_boosts)
        # Tiebreaker: prefer recs from the Step-1 topic section
        if topic_section and sec == topic_section:
            score += 0.1
        scored.append((score, rec))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, rec in scored[:_MAX_RECS_RESULT]:
        results.append({**rec, "_score": score})
    return results


def _search_all_rss(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    sections_data: Dict[str, Any],
    topic_section: Optional[str],
    router_boosts: Dict[str, float],
    restrict_to_sections: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Search RSS entries for anchor term matches.

    Scores each entry by concept match count with value-precision
    bonus, then applies the router's section-level boost.

    When `restrict_to_sections` is supplied, only rows from those
    sections are considered. The router uses this to force Table-
    type retrieval when it has decided the answer lives in an
    atomized Table (see `_router_rss_gate`).
    """
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for sec_id, sec in sections_data.items():
        if restrict_to_sections and sec_id not in restrict_to_sections:
            continue
        for rss_entry in sec.get("rss", []):
            # Scoring surface includes structured fields (condition,
            # category) so a query concept carried only in metadata
            # — e.g. "absolute contraindication" — can still match
            # a row whose narrative text never uses that phrase.
            scoring_text = _scoring_surface_rss(rss_entry)
            raw_score = _score_content_match(
                scoring_text, search_terms, anchor_values,
            )
            if raw_score <= 0:
                continue
            score = _apply_router_boost(raw_score, sec_id, router_boosts)
            if topic_section and sec_id == topic_section:
                score += 0.1
            scored.append((score, {
                "section": sec_id,
                "sectionTitle": sec.get("sectionTitle", ""),
                "recNumber": rss_entry.get("recNumber", ""),
                "category": rss_entry.get("category", ""),
                "condition": rss_entry.get("condition", ""),
                "text": rss_entry.get("text", "") or "",
            }))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, entry in scored[:_MAX_RSS_RESULT]:
        results.append({**entry, "_score": score})
    return results


# ── Topic-guided search ──────────────────────────────────────────

# How many slots to reserve for topic-section content.
# These entries reach Step 4 regardless of global ranking,
# so the LLM can evaluate their semantic relevance.
_TOPIC_SLOTS = 5


def _expand_topic_sections(
    topic_section: Optional[str],
    maps: _RoutingMaps,
) -> List[str]:
    """Expand a topic section to include its associated tables.

    Topic "Post-Treatment Management" maps to section 4.6.2, but
    Table 7 (the actual content) is stored under key "Table 7".
    This function returns both "4.6.2" and "Table 7" so the
    topic-guided search covers both.
    """
    if not topic_section:
        return []
    result = [topic_section]
    # Reverse lookup: which tables belong to this section?
    for table_name, table_sec in maps.table_to_section.items():
        if table_sec == topic_section and table_name not in result:
            result.append(table_name)
    return result


def _search_topic_recs(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    recommendations_store: Dict[str, Any],
    topic_sections: List[str],
) -> List[Dict[str, Any]]:
    """Search ONLY topic-section recs for anchor term matches.

    Symmetric to _search_topic_rss. Ensures recs from the topic
    section identified by Step 1's LLM reach Step 4 for semantic
    evaluation, even if they scored below the global top-N.
    """
    if not topic_sections:
        return []

    topic_set = set(topic_sections)
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for rec_id, rec in recommendations_store.items():
        sec = rec.get("section", "")
        if sec not in topic_set:
            continue
        scoring_text = _scoring_surface_rec(rec)
        score = _score_content_match(
            scoring_text, search_terms, anchor_values,
        )
        if score > 0:
            scored.append((score, {**rec, "_score": score}))

    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:_TOPIC_SLOTS]]


def _merge_recs(
    global_results: List[Dict[str, Any]],
    topic_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge global and topic-guided rec results, deduplicating."""
    seen = set()
    merged = []

    for entry in global_results:
        key = entry.get("id", "")
        if key and key not in seen:
            seen.add(key)
            merged.append(entry)
        elif not key:
            merged.append(entry)

    for entry in topic_results:
        key = entry.get("id", "")
        if key and key not in seen:
            seen.add(key)
            merged.append(entry)
            logger.info(
                "Step 3 topic path: added rec %s score=%.1f",
                key, entry.get("_score", 0),
            )
        elif not key:
            merged.append(entry)

    return merged


def _search_topic_rss(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    sections_data: Dict[str, Any],
    topic_sections: List[str],
) -> List[Dict[str, Any]]:
    """Search ONLY topic-section RSS entries for anchor term matches.

    This is the topic-guided path. Step 1's LLM identified the
    topic (semantic understanding). Step 3 ensures content from
    that topic reaches Step 4 (the second LLM) for semantic
    evaluation.

    Returns up to _TOPIC_SLOTS entries, scored by concept + value
    matching. Any entry matching at least one anchor concept is
    included — the LLM in Step 4 decides what's relevant.
    """
    if not topic_sections:
        return []

    topic_set = set(topic_sections)
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for sec_id, sec in sections_data.items():
        if sec_id not in topic_set:
            continue
        for rss_entry in sec.get("rss", []):
            scoring_text = _scoring_surface_rss(rss_entry)
            score = _score_content_match(
                scoring_text, search_terms, anchor_values,
            )
            if score > 0:
                scored.append((score, {
                    "section": sec_id,
                    "sectionTitle": sec.get("sectionTitle", ""),
                    "recNumber": rss_entry.get("recNumber", ""),
                    "category": rss_entry.get("category", ""),
                    "condition": rss_entry.get("condition", ""),
                    "text": rss_entry.get("text", "") or "",
                    "_score": score,
                }))

    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:_TOPIC_SLOTS]]


def _merge_rss(
    global_results: List[Dict[str, Any]],
    topic_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge global and topic-guided RSS results, deduplicating.

    Topic results are added to global results if not already
    present. Deduplication is by section + recNumber.
    """
    seen = set()
    merged = []

    for entry in global_results:
        key = (entry.get("section", ""), entry.get("recNumber", ""))
        if key not in seen:
            seen.add(key)
            merged.append(entry)

    for entry in topic_results:
        key = (entry.get("section", ""), entry.get("recNumber", ""))
        if key not in seen:
            seen.add(key)
            merged.append(entry)
            logger.info(
                "Step 3 topic path: added %s(%s) score=%.1f",
                entry.get("section", ""),
                str(entry.get("recNumber", ""))[:40],
                entry.get("_score", 0),
            )

    return merged


# ── Exhaustive structured-list retrieval ───────────────────────────
#
# The ranked top-N search is correct for narrative questions ("what
# evidence supports EVT in large core") but wrong for list questions
# ("what are the absolute contraindications"). A list question wants
# every row of a categorized collection, not a ranked subset.
#
# This path is fully data-driven. It discovers categorized rows by
# scanning sections_data for any rss entry with a non-empty
# 'category' field. It fires for any intent whose declared sources
# include TBL. It does not know Table 8 exists, does not hardcode
# any band name, and does not whitelist any intent.
#
# When a new categorized table is added to guideline_knowledge.json,
# this path picks it up automatically with zero code changes.

# Marker score for exhaustive rows. Chosen so they sort above the
# typical top-N scoring range (single-concept matches are 10,
# two-concept + co-occurrence + top router boost is ~46). Exhaustive
# rows must rank above incidental matches from elsewhere in the
# guideline so the presenter's flat-rank cut preserves them.
_EXHAUSTIVE_SCORE = 10_000.0


def _discover_category_index(
    sections_data: Dict[str, Any],
) -> Dict[str, List[Tuple[str, Dict[str, Any], str]]]:
    """Build an index of every categorized row in the guideline.

    Scans all sections for rss entries with a non-empty 'category'
    field. The index key is the lowercased, humanized category
    label ('absolute_contraindication' → 'absolute contraindication').
    Each value is a list of (section_id, row, section_title) tuples.

    Fully generic: works on any categorized collection the ingest
    pipeline produces, not just Table 8.
    """
    index: Dict[str, List[Tuple[str, Dict[str, Any], str]]] = {}
    for sec_id, sec in sections_data.items():
        if not isinstance(sec, dict):
            continue
        sec_title = sec.get("sectionTitle", "") or ""
        for row in sec.get("rss", []) or []:
            cat_slug = row.get("category", "") or ""
            if not cat_slug:
                continue
            cat_label = _humanize(cat_slug).strip().lower()
            if not cat_label:
                continue
            index.setdefault(cat_label, []).append(
                (sec_id, row, sec_title),
            )
    return index


def _match_query_to_categories(
    raw_query: str,
    category_index: Dict[str, List[Tuple[str, Dict[str, Any], str]]],
) -> List[str]:
    """Return category labels whose humanized form appears in the query.

    Two match modes, both substring-only (no regex):
    1. Full label substring — 'absolute contraindication' in the query
       matches the identically-labeled category.
    2. Head-word fallback — if the query contains the category's
       distinctive first word AND the label's tail is implied (any
       tail word present, or a shared domain word like 'contraindication'
       is present). This lets 'list the absolute contraindications'
       match even if the clinician writes 'contraindications' plural.

    All match logic runs against labels discovered from data. No
    category strings are hardcoded.
    """
    q = (raw_query or "").lower()
    if not q:
        return []
    matched: List[str] = []
    for cat_label in category_index.keys():
        if cat_label in q:
            matched.append(cat_label)
            continue
        words = cat_label.split(" ")
        if not words:
            continue
        head = words[0]
        tail = words[1:]
        # Head word must be specific enough to be a real signal.
        if len(head) < 6:
            continue
        if head not in q:
            continue
        # Require at least one tail word (or a plural form of the
        # tail) present in the query, so 'absolute' alone is not a
        # match against 'absolute contraindication'.
        if not tail:
            matched.append(cat_label)
            continue
        for w in tail:
            if w in q or (w + "s") in q:
                matched.append(cat_label)
                break
    return matched


def _fetch_categorized_rows(
    category_labels: List[str],
    category_index: Dict[str, List[Tuple[str, Dict[str, Any], str]]],
) -> List[Dict[str, Any]]:
    """Return every row for each matched category label.

    Rows are flattened to the same shape that _search_all_rss emits
    so the merge step is trivial. Each row carries _exhaustive=True
    and a high marker _score so downstream truncation preserves them.
    """
    results: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()
    for label in category_labels:
        for sec_id, row, sec_title in category_index.get(label, []):
            key = (
                sec_id,
                row.get("recNumber", "") or "",
                row.get("condition", "") or "",
            )
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "section": sec_id,
                "sectionTitle": sec_title,
                "recNumber": row.get("recNumber", "") or "",
                "category": row.get("category", "") or "",
                "condition": row.get("condition", "") or "",
                "text": row.get("text", "") or "",
                "_score": _EXHAUSTIVE_SCORE,
                "_exhaustive": True,
            })
    return results


# ── Semantic index search ──────────────────────────────────────────

# Max semantic units returned to Step 4.
# The semantic index is hand-labeled with one unit per clinical
# decision point, so matches are high-precision and a small N is
# enough for the presenter.
_MAX_SEMANTIC_UNITS = 12


# Concept-handle keywords that signal a unit is about a numeric
# threshold / target / cutoff / dose / range. When the query carries
# a numeric anchor value (SBP 200, NIHSS 18, LKW 2h, dose 0.9), these
# units should float higher than narrative units on the same topic.
_THRESHOLD_CONCEPT_TOKENS = frozenset({
    "target", "threshold", "cutoff", "dose", "dosing", "range",
    "limit", "window", "criterion", "criteria", "eligibility",
    "contraindication", "max", "min", "below", "above",
})

# Score bonus when (a) query has at least one numeric anchor value
# and (b) the unit concept contains a threshold token. This rewards
# hand-labeled threshold units when the clinician asks "can I give
# IVT with SBP 200?" — the 4.3.5 pre_ivt_bp_target unit wins even
# without an exact number match against "185".
_THRESHOLD_UNIT_BONUS = 6.0


def _has_any_numeric_value(anchor_values: Optional[Dict[str, Any]]) -> bool:
    """True when any anchor value resolves to a concrete number."""
    if not anchor_values:
        return False
    for v in anchor_values.values():
        if _extract_number(v) is not None:
            return True
    return False


def _concept_contains_threshold_token(unit: Dict[str, Any]) -> bool:
    """True when the unit's concept handle carries a threshold keyword."""
    handles: List[str] = []
    c = unit.get("concept")
    if isinstance(c, str):
        handles.append(c)
    cs = unit.get("concepts")
    if isinstance(cs, list):
        handles.extend(str(x) for x in cs if isinstance(x, str))
    for handle in handles:
        tokens = handle.lower().split("_")
        if any(t in _THRESHOLD_CONCEPT_TOKENS for t in tokens):
            return True
    return False


def _search_semantic_index(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    semantic_units: List[Dict[str, Any]],
    source_types: List[str],
    topic_section: Optional[str],
    router_boosts: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Score hand-labeled semantic units by anchor concept match.

    Each unit has a short `meaning` sentence and a concept handle.
    Both are searched as lowercased text. Because the meaning text
    is deliberately terse (one clinical decision point per unit),
    matches are precise and carry far less noise than rec/RSS
    full-text hits.

    Filters units to the source types requested by the intent
    (rec, rss, synopsis, kg, table_row, figure_node → REC, RSS,
    SYN, KG, TBL, FIG).
    """
    if not semantic_units or not search_terms:
        return []

    kind_to_source = {
        "rec": "REC",
        "rss": "RSS",
        "synopsis": "SYN",
        "kg": "KG",
        "table_row": "TBL",
        "figure_node": "FIG",
        "table": "TBL",
        "figure": "FIG",
    }

    source_set = set(source_types)
    scored: List[Tuple[float, Dict[str, Any]]] = []

    # Query-level flag: does the clinician supply a number anywhere?
    query_has_number = _has_any_numeric_value(anchor_values)

    for unit in semantic_units:
        kind = unit.get("kind", "")
        required_source = kind_to_source.get(kind)
        if required_source and required_source not in source_set:
            continue

        # Build the searchable text: concept handle + meaning.
        # The concept handle is snake_case, so underscores become
        # spaces to let single-word anchor terms match.
        concept_text = ""
        c = unit.get("concept")
        if isinstance(c, str):
            concept_text = c.replace("_", " ")
        cs = unit.get("concepts")
        if isinstance(cs, list):
            concept_text = " ".join(
                str(x).replace("_", " ") for x in cs
            )
        searchable = f"{concept_text} {unit.get('meaning', '')}"

        raw_score = _score_content_match(
            searchable, search_terms, anchor_values,
        )
        if raw_score <= 0:
            continue

        # Router boost — strongest signal.
        section_key = unit.get("section_key", "")
        score = _apply_router_boost(raw_score, section_key, router_boosts)

        # Threshold-unit bonus: clinician has a number and this unit
        # is about a target/threshold/dose/range. Additive so it
        # composes with the router boost rather than competing.
        if query_has_number and _concept_contains_threshold_token(unit):
            score += _THRESHOLD_UNIT_BONUS

        # Legacy tiebreaker: Step 1 LLM topic section.
        if topic_section and section_key == topic_section:
            score += 0.5

        scored.append((score, unit))

    scored.sort(key=lambda x: -x[0])

    results: List[Dict[str, Any]] = []
    for score, unit in scored[:_MAX_SEMANTIC_UNITS]:
        results.append({**unit, "_score": score})
    return results


# ── Main retrieval function ──────────────────────────────────────────

def retrieve_content(
    parsed: ParsedQAQuery,
    raw_query: str,
    recommendations_store: Dict[str, Any],
    guideline_knowledge: Dict[str, Any],
) -> RetrievedContent:
    """
    Content-first retrieval: anchor terms search content directly,
    sections are derived from matching content.

    1. Build synonym-expanded search groups from anchor terms
    2. Search ALL recs and RSS entries for anchor term matches
    3. Score entries by concept match count (co-occurrence bonus)
    4. Derive sections from top-scoring entries
    5. Fetch synopsis, knowledge gaps, tables, figures from derived sections
    """
    maps = _RoutingMaps.get()

    # ── Retrieve every source type, every time ───────────────────
    # Intent is a classification signal for Step 4's presentation,
    # not a retrieval gate. A post-IVT BP query wants the rec
    # (REC 4.3.7), the narrative (§4.3 synopsis), AND the protocol
    # row (Table 7: "Increase BP measurement frequency if SBP >180").
    # Gating on intent would drop one or more of those. Scoring
    # plus the Step 4 LLM filter decide what actually surfaces.
    source_types = ["REC", "SYN", "RSS", "KG", "TBL", "FIG"]
    # Keep the intent's declared sources on the audit trail so we
    # can see what the map would have returned, without letting it
    # gate anything.
    declared_sources = maps.intent_sources.get(
        parsed.intent, ["REC", "SYN"],
    )

    # ── Topic → section (tiebreaker, not primary routing) ───────
    topic_section = None
    if parsed.topic:
        topic_section = maps.topic_to_section.get(parsed.topic)

    # ── Build search terms from anchor terms + raw query ──────
    search_terms = _build_search_terms(
        parsed.anchor_terms, maps.term_to_synonyms, raw_query,
    )

    # ── Anchor-word deterministic router ─────────────────────────
    # Feeds guideline_anchor_words.json the anchor_terms from Step 1
    # and returns a ranked set of candidate sections. These become
    # the primary routing signal. Every search path applies a
    # section-level boost so content inside a candidate section
    # floats to the top; non-candidates still compete but have to
    # beat the boost to win.
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

    # Read sections through the shared knowledge_loader so alias
    # resolution (added in Stage 3 POINTER) happens in exactly one
    # place. load_sections_store() wraps the canonical cached loader
    # in data/loader.py — same underlying dict that the caller's
    # `guideline_knowledge` parameter points at. The parameter is
    # still accepted for backwards compat with orchestrator.py but
    # is no longer read here.
    from .knowledge_loader import (
        load_sections_store,
        dispatch_concept_sections,
        get_sections_by_ids,
    )
    sections_data = load_sections_store()

    # ── Path 0: Concept-section dispatcher (Stage 2b) ────────────
    #
    # Given the parsed intent + anchor_terms, route to concept
    # section IDs via the deterministic dispatcher in knowledge_loader.
    # If the dispatcher returns ≥1 concept sections, their rows become
    # the authoritative primary result — prepended to matched_rss with
    # a high marker score. The legacy ranked search below still runs
    # to pull related §4.x prose evidence, but any rows from legacy
    # ex-table/figure keys (Table 2..9, Figure 2..4) are suppressed
    # in post-processing so they don't duplicate concept section
    # content.
    concept_section_ids: List[str] = []
    concept_rss_rows: List[Dict[str, Any]] = []
    try:
        # Strict split: Python only dispatches, never infers. The
        # Step 1 LLM determined parsed.intent and parsed.anchor_terms;
        # we hand both to the dispatcher unchanged. The dispatcher
        # does NOT see raw query text and does NOT fall back to
        # keyword matching if the LLM's intent returns nothing.
        concept_section_ids = dispatch_concept_sections(
            intent=parsed.intent,
            anchor_terms=parsed.anchor_terms,
        )
    except Exception as e:  # pragma: no cover — dispatcher is pure python
        logger.warning("Step 3 dispatcher failed: %s", e)
        concept_section_ids = []

    if concept_section_ids:
        concept_entries = get_sections_by_ids(concept_section_ids)
        for cid, entry in concept_entries.items():
            sec_title = entry.get("sectionTitle", "") or ""
            for row in entry.get("rss", []) or []:
                concept_rss_rows.append({
                    "section": cid,
                    "sectionTitle": sec_title,
                    "recNumber": row.get("recNumber", ""),
                    "category": row.get("category", "") or "",
                    "condition": row.get("condition", "") or "",
                    "text": row.get("text", "") or "",
                    "_score": 1_000_000.0,
                    "_concept_dispatched": True,
                })
        logger.info(
            "Step 3 Path 0 dispatcher: intent=%s → %d concept sections "
            "(%s) → %d rss rows",
            parsed.intent,
            len(concept_entries),
            list(concept_entries.keys()),
            len(concept_rss_rows),
        )

    # ── Content search: two-path retrieval ────────────────────────
    #
    # Path 1 (Global + router-boosted): search ALL content by
    #   concept + value, with a section-level boost from the
    #   deterministic anchor router.
    # Path 2 (Topic-guided fallback): only runs when the router
    #   finds nothing, to catch questions where anchor extraction
    #   is weak but the Step-1 LLM still guessed a reasonable topic.

    # Expand topic section to include associated tables
    topic_sections = _expand_topic_sections(topic_section, maps)
    if topic_sections:
        logger.info(
            "Step 3: topic sections expanded: %s", topic_sections,
        )

    # Path 1 — Legacy ranked search, now split into two layers:
    #
    #   (a) Rec search ALWAYS runs. Recommendations live in
    #       recommendations.json (a separate data source from
    #       guideline_knowledge.json) and the concept dispatcher
    #       does not replace this layer — every query needs
    #       recommendation retrieval because the dispatcher only
    #       returns rss rows from concept sections, not COR/LOE
    #       recommendation statements.
    #
    #   (b) RSS ranked search, router RSS gate, exhaustive-list
    #       path, and topic-guided fallback ALL skip when the
    #       concept dispatcher in Path 0 returned non-empty.
    #       The concept dispatcher is the authoritative source for
    #       rss row content — we trust the LLM's intent
    # Recommendation search — always runs. Recs live in
    # recommendations.json, a separate data source from the
    # concept sections. Every query needs rec retrieval.
    matched_recs = _search_all_recs(
        search_terms, parsed.anchor_terms,
        recommendations_store, topic_section, router_boosts,
    )

    # RSS content comes from concept sections ONLY.
    # The concept dispatcher already found the right sections;
    # there is no legacy keyword-ranked RSS search, no exhaustive-
    # list path, no topic-guided RSS fallback, and no cross-band
    # suppression. All of those were removed because the concept
    # dispatcher is the authoritative source for RSS content.
    matched_rss: List[Dict[str, Any]] = []

    # Concept-dispatched rows ARE the matched_rss. No legacy rows
    # to merge, suppress, or deduplicate — the legacy keyword-ranked
    # RSS search has been removed.
    if concept_rss_rows:
        matched_rss = concept_rss_rows
        logger.info(
            "Step 3 Path 0: %d concept-dispatched rss rows",
            len(concept_rss_rows),
        )

    # ── Semantic index search (concept-level hand-labeled units) ──
    #
    # Runs alongside the full-text rec/RSS search. Each unit is one
    # hand-labeled clinical decision point with a short meaning
    # sentence, so matches are precise. The router boost and
    # threshold-unit bonus let pinpoint units dominate rec text
    # matches when the clinician supplies a specific number.
    matched_semantic = _search_semantic_index(
        search_terms,
        parsed.anchor_terms,
        maps.semantic_units,
        source_types,
        topic_section,
        router_boosts,
    )
    if matched_semantic:
        logger.info(
            "Step 3 semantic index: %d unit hits (top concept: %s)",
            len(matched_semantic),
            matched_semantic[0].get("concept")
            or matched_semantic[0].get("concepts"),
        )

    # ── Derive sections from matched content ────────────────────
    content_sections: Set[str] = set()
    for rec in matched_recs:
        sec = rec.get("section", "")
        if sec:
            content_sections.add(sec)
    for rss in matched_rss:
        sec = rss.get("section", "")
        if sec:
            content_sections.add(sec)
    for unit in matched_semantic:
        sec = unit.get("section_key", "")
        # Skip the TBL/FIG markers — those aren't guideline section ids
        if sec and sec not in ("TBL", "FIG"):
            content_sections.add(sec)

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

    # ── Fetch section-level content from derived sections ────────
    synopsis = _fetch_synopsis(section_ids, sections_data)

    knowledge_gaps = _fetch_knowledge_gaps(section_ids, sections_data)

    anchor_lower = {
        t.lower() for t in (parsed.anchor_terms or {})
    }
    tables = _fetch_tables(section_ids, anchor_lower, maps)

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
        semantic_units=matched_semantic,
        list_mode_categories=[],
    )

    logger.info(
        "Step 3 retrieved: %d recs, %d rss, %d synopsis, %d kg, "
        "%d tables, %d figures, %d semantic units (sections: %s)",
        len(result.recommendations), len(result.rss),
        len(result.synopsis), len(result.knowledge_gaps),
        len(result.tables), len(result.figures),
        len(result.semantic_units),
        section_ids,
    )

    return result


# ── Section-level content fetchers ─────────────────────────────────
# These fetch from derived sections (sections found via content search)

def _fetch_synopsis(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch synopsis text for derived sections."""
    result = {}
    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        synopsis = sec.get("synopsis", "")
        if synopsis:
            result[sec_id] = synopsis
    return result


def _fetch_knowledge_gaps(
    sections: List[str],
    sections_data: Dict[str, Any],
) -> Dict[str, str]:
    """Fetch knowledge gap text for derived sections."""
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
