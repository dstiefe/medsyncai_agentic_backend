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

from .schemas import ParsedQAQuery

logger = logging.getLogger(__name__)
logger.info("content_retriever v5.0 loaded — content-first search")

_REF_DIR = os.path.join(os.path.dirname(__file__), "references")
_DATA_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "data",
)


# ── Content search limits ──────────────────────────────────────────
_MAX_RECS_RESULT = 15
_MAX_RSS_RESULT = 10
_CO_OCCURRENCE_FACTOR = 0.3


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


def _has_number_near(text: str, term: str, window: int = 120) -> bool:
    """Token walk: check if a digit appears within `window` chars of `term`.

    In clinical text, a digit near a clinical term is a threshold
    or target value (e.g., "SBP lowered to <185 mm Hg").
    """
    idx = text.find(term)
    if idx < 0:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + len(term) + window)
    neighborhood = text[start:end]
    return any(c.isdigit() for c in neighborhood)


def _score_content_match(
    text: str,
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]] = None,
) -> float:
    """Score a text block by how many anchor concepts it matches.

    Each search_term group represents one clinical concept.
    If any synonym in the group appears in the text, that concept
    is matched. Score = number of distinct concepts matched.

    For terms with values (e.g., SBP: 200), also requires a number
    nearby in the text — confirms the content discusses that metric
    with specific thresholds.

    Co-occurrence bonus when 2+ concepts match in the same entry.
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    matched = 0

    for concept, synonyms in search_terms.items():
        value = (anchor_values or {}).get(concept)
        for syn in synonyms:
            if syn in text_lower:
                if value is not None:
                    # Value filter: text must also have a number nearby
                    if _has_number_near(text_lower, syn):
                        matched += 1
                        break
                else:
                    matched += 1
                    break

    if matched == 0:
        return 0.0

    # Base score: 10 points per concept matched
    score = float(matched * 10)

    # Co-occurrence bonus: entries matching multiple concepts
    # are disproportionately more relevant
    if matched >= 2:
        score *= (1.0 + _CO_OCCURRENCE_FACTOR * (matched - 1))

    return score


def _search_all_recs(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    recommendations_store: Dict[str, Any],
    topic_section: Optional[str],
) -> List[Dict[str, Any]]:
    """Search ALL recs for anchor term matches.

    Scores each rec by concept match count. Returns top results
    sorted by score, with topic section as tiebreaker.
    """
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for rec_id, rec in recommendations_store.items():
        text = rec.get("text", "")
        score = _score_content_match(text, search_terms, anchor_values)
        if score > 0:
            # Tiebreaker: prefer recs from the topic section
            if topic_section and rec.get("section") == topic_section:
                score += 0.1
            scored.append((score, rec))

    scored.sort(key=lambda x: -x[0])
    return [rec for _, rec in scored[:_MAX_RECS_RESULT]]


def _search_all_rss(
    search_terms: Dict[str, Set[str]],
    anchor_values: Optional[Dict[str, Any]],
    sections_data: Dict[str, Any],
    topic_section: Optional[str],
) -> List[Dict[str, Any]]:
    """Search ALL RSS entries for anchor term matches.

    Scores each entry by concept match count. Returns top results
    sorted by score, with topic section as tiebreaker.
    """
    scored: List[Tuple[float, Dict[str, Any]]] = []

    for sec_id, sec in sections_data.items():
        is_topic = topic_section and sec_id == topic_section
        for rss_entry in sec.get("rss", []):
            text = rss_entry.get("text", "")
            score = _score_content_match(
                text, search_terms, anchor_values,
            )
            if score > 0:
                if is_topic:
                    score += 0.1
                scored.append((score, {
                    "section": sec_id,
                    "sectionTitle": sec.get("sectionTitle", ""),
                    "recNumber": rss_entry.get("recNumber", ""),
                    "category": rss_entry.get("category", ""),
                    "condition": rss_entry.get("condition", ""),
                    "text": text,
                }))

    scored.sort(key=lambda x: -x[0])
    return [entry for _, entry in scored[:_MAX_RSS_RESULT]]


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

    # ── Intent → source types ───────────────────────────────────
    source_types = maps.intent_sources.get(
        parsed.intent, ["REC", "SYN"]
    )

    # ── Topic → section (tiebreaker, not primary routing) ───────
    topic_section = None
    if parsed.topic:
        topic_section = maps.topic_to_section.get(parsed.topic)

    # ── Build search terms from anchor terms + raw query ──────
    search_terms = _build_search_terms(
        parsed.anchor_terms, maps.term_to_synonyms, raw_query,
    )

    logger.info(
        "Step 3: intent=%s, topic=%s, anchor_terms=%s, "
        "search_terms=%s",
        parsed.intent, parsed.topic, parsed.anchor_terms,
        {k: sorted(v)[:3] for k, v in search_terms.items()},
    )

    sections_data = guideline_knowledge.get("sections", {})

    # ── Content search: anchor terms → content text ─────────────
    matched_recs = []
    if "REC" in source_types:
        matched_recs = _search_all_recs(
            search_terms, parsed.anchor_terms,
            recommendations_store, topic_section,
        )

    matched_rss = _search_all_rss(
        search_terms, parsed.anchor_terms,
        sections_data, topic_section,
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

    knowledge_gaps: Dict[str, str] = {}
    if "KG" in source_types:
        knowledge_gaps = _fetch_knowledge_gaps(
            section_ids, sections_data,
        )

    tables: List[Dict[str, Any]] = []
    if "TBL" in source_types:
        anchor_lower = {
            t.lower() for t in (parsed.anchor_terms or {})
        }
        tables = _fetch_tables(section_ids, anchor_lower, maps)

    figures: List[Dict[str, Any]] = []
    if "FIG" in source_types:
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
