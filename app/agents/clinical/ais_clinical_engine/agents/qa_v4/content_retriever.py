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
# Sections are scored by how many anchor terms point to them.
# Sections with more anchor term matches are prioritized higher.
#
# Within matched sections, anchor terms AND clinical variable values
# narrow which recs and RSS entries are relevant. Content that doesn't
# match any anchor term or clinical variable is dropped. Content is
# scored by how many anchor terms it matches — higher scores first.
# ───────────────────────────────────────────────────────────────────────
"""
Step 3: Route to sections and retrieve narrowed content.

Takes validated Step 1 output (intent, topic, anchor_terms) and:
1. Determines which content types the intent needs
2. Finds which sections to search (topic + anchor terms), scored by match count
3. Pulls content from those sections, narrowed and scored by anchor terms
   and clinical variable values
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
                            key = t.lower()
                            if key not in self._anchor_to_sections:
                                self._anchor_to_sections[key] = []
                            if sec_id not in self._anchor_to_sections[key]:
                                self._anchor_to_sections[key].append(sec_id)
        return self._anchor_to_sections

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

        Built from synonym_dictionary.json. Terms that share the same
        family are semantically related (e.g. SBP, DBP, BP → vital_signs;
        IVT, tPA, alteplase → thrombolytic).

        Used for scoring: count unique families, not raw term hits.
        This prevents SBP + DBP + BP from inflating a score to 3 when
        they represent one clinical concept (blood pressure).

        Terms not found in the synonym dictionary keep their own name
        as a singleton family — they still count, just aren't grouped.
        """
        if self._term_to_family is None:
            self._term_to_family = {}
            data = _load_ref_json("synonym_dictionary.json")
            for term_id, info in data.get("terms", {}).items():
                # Family = subcategory if available, else category
                subcat = info.get("subcategory", "")
                cat = info.get("category", "")
                family = subcat if subcat else cat
                if family:
                    self._term_to_family[term_id.lower()] = family
                    # Map synonyms to the same family
                    for syn in info.get("synonyms", []):
                        self._term_to_family[syn.lower()] = family
        return self._term_to_family


# ── Scored section ──────────────────────────────────────────────────

@dataclass
class ScoredSection:
    """A section with its anchor term match count for prioritization."""
    section_id: str
    anchor_match_count: int = 0
    is_topic_primary: bool = False


# ── Retrieved content bundle ─────────────────────────────────────────

@dataclass
class ScoredItem:
    """A content item (rec or RSS) with its relevance score."""
    data: Dict[str, Any]
    score: int = 0  # number of anchor terms + clinical variables matched


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
    3. Anchor terms + clinical variable values → narrow within sections
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
    scored_sections = _resolve_and_score_sections(parsed, maps)

    # Extract ordered section IDs (highest score first)
    section_ids = [s.section_id for s in scored_sections]

    logger.info(
        "Step 3: intent=%s → sources=%s, topic=%s + anchors → sections=%s",
        parsed.intent, source_types, parsed.topic,
        [(s.section_id, s.anchor_match_count) for s in scored_sections],
    )

    # ── Build narrowing terms ───────────────────────────────────
    # Anchor terms (lowercased) for text matching
    anchor_lower = {t.lower() for t in (parsed.anchor_terms or [])}

    # Concept family mapping for semantic scoring
    term_to_family = maps.term_to_family

    # Clinical variable values (as strings) for additional narrowing
    # These are numeric/string values from the question that should
    # appear in relevant recommendations (e.g., "200" for SBP 200)
    clinical_value_strings = _extract_clinical_value_strings(
        parsed.clinical_variables
    )

    logger.info(
        "Step 3 narrowing: %d anchor terms, %d clinical value strings",
        len(anchor_lower), len(clinical_value_strings),
    )

    # ── Fetch content by source type, narrowed and scored ────────
    result = RetrievedContent(
        raw_query=raw_query,
        parsed_query=parsed,
        source_types=source_types,
        sections=scored_sections,
    )

    sections_data = guideline_knowledge.get("sections", {})

    if "REC" in source_types:
        result.recommendations = _fetch_recs(
            section_ids, anchor_lower, clinical_value_strings,
            term_to_family, recommendations_store,
        )

    if "SYN" in source_types:
        result.synopsis = _fetch_synopsis(section_ids, sections_data)

    if "RSS" in source_types:
        result.rss = _fetch_rss(
            section_ids, anchor_lower, clinical_value_strings,
            term_to_family, sections_data,
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


# ── Section resolution and scoring ──────────────────────────────────

def _resolve_and_score_sections(
    parsed: ParsedQAQuery,
    maps: _RoutingMaps,
) -> List[ScoredSection]:
    """Collect sections from topic mapping + anchor term mappings,
    scored by unique concept families matched.

    Scoring uses concept families (from synonym_dictionary.json) so that
    semantically related terms count as one. SBP + DBP + BP all belong
    to the "vital_signs" family and count as 1, not 3. This prevents
    a section from being inflated by synonym density.

    A section matching 3 unique families (e.g., vital_signs + thrombolytic
    + clinical_time) outranks a section matching only 2 (vital_signs +
    thrombolytic), even if the second section mentions SBP, DBP, and BP
    separately.

    Returns a list of ScoredSection ordered by:
      1. Topic primary section first (if present)
      2. Then remaining sections by descending unique family count
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
    for term in (parsed.anchor_terms or []):
        term_lower = term.lower()
        # Resolve family: use synonym dictionary mapping, or fall back
        # to the term itself as a singleton family
        family = term_to_family.get(term_lower, term_lower)

        term_sections = maps.anchor_to_sections.get(term_lower, [])
        for sec in term_sections:
            if sec not in section_families:
                section_families[sec] = set()
            section_families[sec].add(family)

    # Build scored list — count is unique families, not raw terms
    scored: List[ScoredSection] = []
    for sec_id, families in section_families.items():
        scored.append(ScoredSection(
            section_id=sec_id,
            anchor_match_count=len(families),
            is_topic_primary=(sec_id == topic_primary),
        ))

    # Sort: topic primary first, then by descending unique family count
    scored.sort(key=lambda s: (
        not s.is_topic_primary,  # False sorts before True → primary first
        -s.anchor_match_count,   # higher count first
    ))

    return scored


# ── Clinical variable value extraction ──────────────────────────────

def _extract_clinical_value_strings(
    clinical_variables: Dict[str, Any],
) -> Set[str]:
    """Extract string representations of clinical variable values
    for text-matching within recs and RSS.

    Numbers become their string form. Range dicts produce both min and max.
    Non-numeric values (strings, booleans) are included as-is.
    """
    values: Set[str] = set()
    if not clinical_variables:
        return values

    for key, val in clinical_variables.items():
        if isinstance(val, (int, float)):
            values.add(str(val))
            # Also add integer form of floats (e.g., 200.0 → "200")
            if isinstance(val, float) and val == int(val):
                values.add(str(int(val)))
        elif isinstance(val, dict):
            # Range dict like {"min": 3, "max": 5}
            for subval in val.values():
                if isinstance(subval, (int, float)):
                    values.add(str(subval))
                    if isinstance(subval, float) and subval == int(subval):
                        values.add(str(int(subval)))
        elif isinstance(val, str):
            values.add(val.lower())

    return values


# ── Content scoring and narrowing ───────────────────────────────────

def _score_text(
    text: str,
    anchor_lower: Set[str],
    clinical_value_strings: Set[str],
    term_to_family: Dict[str, str] = None,
) -> int:
    """Score a text block by unique concept families + clinical values matched.

    Uses concept families so that semantically related anchor terms
    (SBP, DBP, BP → vital_signs) count as one match, not three.
    Each unique family found adds 1. Each clinical variable value adds 1.

    Higher score = more relevant to the question.
    Returns 0 if nothing matches — caller decides whether to include or drop.
    """
    if not text:
        return 0
    text_lower = text.lower()

    # Count unique families matched by anchor terms
    matched_families: Set[str] = set()
    for term in anchor_lower:
        if term in text_lower:
            if term_to_family:
                family = term_to_family.get(term, term)
            else:
                family = term
            matched_families.add(family)

    score = len(matched_families)

    # Clinical values are always individual (numeric, not synonyms)
    for val in clinical_value_strings:
        if val in text_lower:
            score += 1
    return score


def _text_matches_any(
    text: str,
    anchor_lower: Set[str],
    clinical_value_strings: Set[str],
) -> bool:
    """Check if any anchor term or clinical value appears in the text.

    If both sets are empty (no narrowing possible), returns True for everything.
    """
    if not anchor_lower and not clinical_value_strings:
        return True
    text_lower = text.lower()
    for term in anchor_lower:
        if term in text_lower:
            return True
    for val in clinical_value_strings:
        if val in text_lower:
            return True
    return False


# ── Content fetchers (narrowed by anchor terms + clinical values) ───

def _fetch_recs(
    sections: List[str],
    anchor_lower: Set[str],
    clinical_value_strings: Set[str],
    term_to_family: Dict[str, str],
    recommendations_store: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch recommendations from matched sections, narrowed by anchor terms
    and clinical values, ordered by relevance score (highest first).

    Scoring uses unique concept families (not raw term count) so that
    semantically related terms like SBP/DBP/BP count as one family match.

    Recs that match at least one anchor term or clinical value are included.
    If no anchor terms or clinical values exist (broad question), all recs
    from matched sections are included.
    """
    scored_recs: List[Tuple[int, Dict[str, Any]]] = []
    sections_set = set(sections)

    for rec_id, rec in recommendations_store.items():
        rec_section = rec.get("section", "")
        if rec_section not in sections_set:
            continue

        rec_text = rec.get("text", "")
        if not _text_matches_any(rec_text, anchor_lower, clinical_value_strings):
            continue

        score = _score_text(rec_text, anchor_lower, clinical_value_strings, term_to_family)
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
    anchor_lower: Set[str],
    clinical_value_strings: Set[str],
    term_to_family: Dict[str, str],
    sections_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch RSS entries from matched sections, narrowed by anchor terms
    and clinical values, ordered by relevance score (highest first).

    Scoring uses unique concept families (not raw term count) so that
    semantically related terms like SBP/DBP/BP count as one family match.

    RSS entries that match at least one anchor term or clinical value are
    included. If no narrowing terms exist, all RSS from matched sections
    are included.
    """
    scored_entries: List[Tuple[int, Dict[str, Any]]] = []

    for sec_id in sections:
        sec = sections_data.get(sec_id, {})
        for rss_entry in sec.get("rss", []):
            rss_text = rss_entry.get("text", "")
            if not _text_matches_any(rss_text, anchor_lower, clinical_value_strings):
                continue

            score = _score_text(rss_text, anchor_lower, clinical_value_strings, term_to_family)
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
