"""
JSON contracts between Q&A pipeline agents.

Every agent receives and returns one of these typed dicts.
This is the single source of truth for inter-agent data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


# ── Intent Agent Output ─────────────────────────────────────────────

@dataclass
class IntentResult:
    """Output of the Intent Agent — everything downstream agents need."""

    question: str
    question_type: str                          # "recommendation" | "evidence" | "knowledge_gap"
    search_terms: List[str] = field(default_factory=list)
    section_refs: List[str] = field(default_factory=list)       # explicit "Section X.X" refs
    topic_sections: List[str] = field(default_factory=list)     # inferred from TOPIC_SECTION_MAP
    topic_sections_source: str = ""                             # "topic_map" | "concept_index" | ""
    suppressed_sections: List[str] = field(default_factory=list)
    numeric_context: Dict[str, Any] = field(default_factory=dict)
    clinical_vars: Dict[str, Any] = field(default_factory=dict)
    is_general_question: bool = False
    is_evidence_question: bool = False
    is_contraindication_question: bool = False
    contraindication_tier: Optional[str] = None  # "Absolute" | "Relative" | "Benefit May Exceed Risk"
    context_summary: str = ""                    # patient context string for display
    topic: Optional[str] = None                  # LLM-classified topic (e.g. "Post-Treatment Management")


# ── Recommendation Agent Output ─────────────────────────────────────

@dataclass
class ScoredRecommendation:
    """A single recommendation with its relevance score."""

    rec_id: str
    section: str
    section_title: str
    rec_number: str
    cor: str
    loe: str
    text: str                   # verbatim guideline text — NEVER modified
    score: int
    source: str = "deterministic"   # "deterministic" | "semantic" | "both"


@dataclass
class RecommendationResult:
    """Output of the Recommendation Agent."""

    scored_recs: List[ScoredRecommendation] = field(default_factory=list)
    search_method: str = "deterministic"    # "deterministic" | "semantic" | "hybrid" | "section_route"


# ── Supportive Text Agent Output ────────────────────────────────────

@dataclass
class SupportiveTextEntry:
    """A single RSS entry from guideline_knowledge.json."""

    section: str
    section_title: str
    rec_number: str
    text: str               # raw RSS text — Assembly Agent may summarize this
    entry_type: str = "rss"  # "rss" | "synopsis"


@dataclass
class SupportiveTextResult:
    """Output of the Supportive Text Agent."""

    entries: List[SupportiveTextEntry] = field(default_factory=list)
    has_content: bool = False


# ── Knowledge Gap Agent Output ──────────────────────────────────────

@dataclass
class KnowledgeGapEntry:
    """A single knowledge gap entry."""

    section: str
    section_title: str
    text: str               # raw KG text — Assembly Agent may summarize this


@dataclass
class KnowledgeGapResult:
    """Output of the Knowledge Gap Agent."""

    entries: List[KnowledgeGapEntry] = field(default_factory=list)
    has_gaps: bool = False
    deterministic_response: Optional[str] = None  # pre-built "no gaps" response


# ── Assembly Agent Output ───────────────────────────────────────────

@dataclass
class ClarificationOption:
    """One option in a clarification prompt."""

    label: str          # e.g. "A"
    description: str    # e.g. "Standard window IVT (0-4.5 hours from onset)"
    section: str
    rec_id: str
    cor: str
    loe: str


@dataclass
class AuditEntry:
    """One step in the audit trail."""

    step: str           # e.g. "intent_classification", "rec_search", "scope_gate"
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyResult:
    """Final output of the Assembly Agent — the response to the user."""

    status: str                     # "complete" | "needs_clarification" | "out_of_scope"
    answer: str                     # formatted answer text
    summary: str                    # concise summary
    citations: List[str] = field(default_factory=list)
    related_sections: List[str] = field(default_factory=list)
    referenced_trials: List[str] = field(default_factory=list)

    # Clarification (populated when status == "needs_clarification")
    clarification_options: List[ClarificationOption] = field(default_factory=list)

    # Audit trail
    audit_trail: List[AuditEntry] = field(default_factory=list)

    # CMI matching metadata (populated when CMI path was used)
    cmi_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to the dict shape expected by engine.py _build_return()."""
        result = {
            "answer": self.answer,
            "summary": self.summary,
            "citations": self.citations,
            "relatedSections": self.related_sections,
            "referencedTrials": self.referenced_trials,
        }
        if self.status == "needs_clarification":
            result["needsClarification"] = True
            result["clarificationOptions"] = [
                {
                    "label": opt.label,
                    "description": opt.description,
                    "section": opt.section,
                    "recId": opt.rec_id,
                    "cor": opt.cor,
                    "loe": opt.loe,
                }
                for opt in self.clarification_options
            ]
        if self.audit_trail:
            result["auditTrail"] = [
                {"step": e.step, "detail": e.detail}
                for e in self.audit_trail
            ]
        if self.cmi_used:
            result["cmiUsed"] = True
        return result


# ── CMI Query Parsing Output ──────────────────────────────────────

@dataclass
class RangeFilter:
    """Numeric range with optional min/max bounds."""

    min: Optional[float] = None
    max: Optional[float] = None

    def is_set(self) -> bool:
        return self.min is not None or self.max is not None


@dataclass
class ParsedQAQuery:
    """
    Output of LLM-based query parsing for Guideline Q&A.

    One JSON shape every time. clinical_variables always present
    (all null when no patient data). This is the primary object
    that flows through the entire pipeline.
    """

    # Classification (from LLM classifier — Step 1)
    intent: Optional[str] = None                   # one of 28 defined intents
    topic: Optional[str] = None                    # one topic from the Topic Guide
    qualifier: Optional[str] = None                # subtopic qualifier
    question_type: str = "recommendation"          # "recommendation" | "evidence" | "knowledge_gap"
    question_summary: Optional[str] = None         # plain-language restatement
    search_keywords: Optional[List[str]] = None    # clinically-informed search terms
    clarification: Optional[str] = None            # clarifying question when ambiguous

    # Clinical variables — always present, null when no patient data
    age: Optional[int] = None
    nihss: Optional[int] = None
    vessel_occlusion: Optional[Any] = None         # str or list: "M1", ["ICA", "M1"]
    time_from_lkw_hours: Optional[float] = None
    aspects: Optional[int] = None
    pc_aspects: Optional[int] = None
    premorbid_mrs: Optional[int] = None
    core_volume_ml: Optional[float] = None
    mismatch_ratio: Optional[float] = None
    sbp: Optional[int] = None
    dbp: Optional[int] = None
    inr: Optional[float] = None
    platelets: Optional[int] = None
    glucose: Optional[int] = None

    # Legacy fields for backward compatibility with CMI matcher
    # TODO: remove once CMI matcher is updated to use flat fields
    is_criterion_specific: bool = False
    intervention: Optional[str] = None
    circulation: Optional[str] = None
    time_window_hours: Optional[Dict[str, Any]] = None
    aspects_range: Optional[Dict[str, Any]] = None
    pc_aspects_range: Optional[Dict[str, Any]] = None
    nihss_range: Optional[Dict[str, Any]] = None
    age_range: Optional[Dict[str, Any]] = None
    extraction_confidence: float = 0.0
    target_sections: Optional[List[str]] = None

    def has_clinical_variables(self) -> bool:
        """Return True if any clinical variable is populated."""
        return any(v is not None for v in [
            self.age, self.nihss, self.vessel_occlusion,
            self.time_from_lkw_hours, self.aspects, self.pc_aspects,
            self.premorbid_mrs, self.core_volume_ml, self.mismatch_ratio,
            self.sbp, self.dbp, self.inr, self.platelets, self.glucose,
        ])

    def get_scenario_variables(self) -> List[str]:
        """Return list of variable names that the user specified."""
        variables = []
        # New flat fields
        if self.age is not None:
            variables.append("age_range")
        if self.nihss is not None:
            variables.append("nihss_range")
        if self.vessel_occlusion is not None:
            variables.append("vessel_occlusion")
        if self.time_from_lkw_hours is not None:
            variables.append("time_window_hours")
        if self.aspects is not None:
            variables.append("aspects_range")
        if self.pc_aspects is not None:
            variables.append("pc_aspects_range")
        if self.premorbid_mrs is not None:
            variables.append("premorbid_mrs")
        if self.core_volume_ml is not None:
            variables.append("core_volume_ml")
        if self.intervention:
            variables.append("intervention")
        if self.circulation:
            variables.append("circulation")
        # Legacy range fields (backward compat)
        for field_name in [
            "time_window_hours", "aspects_range", "pc_aspects_range",
            "nihss_range", "age_range",
        ]:
            val = getattr(self, field_name)
            if val and isinstance(val, dict):
                if val.get("min") is not None or val.get("max") is not None:
                    if field_name not in variables:
                        variables.append(field_name)
        return variables


# ── CMI Matched Recommendation ────────────────────────────────────

@dataclass
class CMIMatchedRecommendation:
    """A recommendation matched via CMI tiering — analog of MatchedTrial."""

    rec_id: str
    tier: int                   # 1-4 (lower = better match)
    scope_index: float          # 0.0-1.0 (fraction of query vars addressed)
    tier_reason: str = ""
    match_details: Dict[str, Any] = field(default_factory=dict)
    rec_data: Dict[str, Any] = field(default_factory=dict)   # full recommendation dict
