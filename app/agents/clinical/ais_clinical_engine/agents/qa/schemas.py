"""
JSON contracts between Q&A pipeline agents.

Every agent receives and returns one of these typed dicts.
This is the single source of truth for inter-agent data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


# ── VnIntent enum ───────────────────────────────────────────────────
#
# Symbolic representation of every intent in intent_catalog.json.
# v2 code paths reference these enum members instead of string literals
# so typos fail at import time rather than at runtime. The string value
# is the catalog key; use VnIntent.PATIENT_ELIGIBILITY.value when
# serializing to JSON and VnIntent(raw_string) when deserializing.
#
# If intent_catalog.json gains or loses an entry, update this enum to
# match. validate_intent_enum_matches_catalog() in scaffolding_loader
# should catch any drift at startup.


class VnIntent(str, Enum):
    ALTERNATIVE_OPTION = "alternative_option"
    CLASS_OF_RECOMMENDATION = "class_of_recommendation"
    COMPLICATION_MANAGEMENT = "complication_management"
    CONTRAINDICATIONS = "contraindications"
    DEFINITION = "definition"
    DIAGNOSTIC_TEST = "diagnostic_test"
    DOSE = "dose"
    DRUG_CHOICE = "drug_choice"
    DURATION = "duration"
    ELIGIBILITY_CRITERIA = "eligibility_criteria"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    EXCLUSION_CRITERIA = "exclusion_criteria"
    FREQUENCY = "frequency"
    IMAGING_CHOICE = "imaging_choice"
    INDICATION = "indication"
    INTERVENTION_RECOMMENDATION = "intervention_recommendation"
    MONITORING = "monitoring"
    ONSET_TO_TREATMENT = "onset_to_treatment"
    OUT_OF_SCOPE = "out_of_scope"
    PATIENT_ELIGIBILITY = "patient_eligibility"
    POST_TREATMENT_CARE = "post_treatment_care"
    PROCEDURAL_TIMING = "procedural_timing"
    RATIONALE = "rationale"
    REASSESSMENT = "reassessment"
    REVERSAL = "reversal"
    RISK_FACTOR = "risk_factor"
    ROUTE = "route"
    SCREENING = "screening"
    SEQUENCING = "sequencing"
    SETTING_OF_CARE = "setting_of_care"
    THRESHOLD_TARGET = "threshold_target"
    TIME_WINDOW = "time_window"
    TREATMENT_CHOICE = "treatment_choice"


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
    clarification_reason: Optional[str] = None     # "topic_ambiguity" | "missing_clinical_context" | "multiple_interpretations"

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


# ── ParsedQAQueryV2 (intent-driven, v2 migration) ─────────────────
#
# The v2 query shape is orthogonal to the legacy ParsedQAQuery above.
# It is produced by QAQueryParsingAgent.parse_v2(), verified by
# scaffolding_verifier.verify_parsed_query(), and consumed by the v2
# focused agents. The legacy ParsedQAQuery is still used by the CMI
# matcher and the old rec pipeline and is scheduled for removal in
# Step 11 of the v2 migration.
#
# Shape contract (mirrors intent_catalog.json output_schema):
#   - intent: one of the 33 intents in intent_catalog.json
#   - sections: list of section IDs (gtm parents OR dd.v2 children);
#               scaffolding_verifier resolves these before downstream use
#   - slots: dict of concrete slot values (keys match the required_slots
#            of the classified intent)
#   - sub_questions: populated only when the classifier splits the
#                    question into multiple intents; each sub-question
#                    is itself a ParsedQAQueryV2 dict
#   - topic / qualifier: raw topic_map classification output, used by
#                        the TopicVerificationAgent re-scorer
#   - citations: emitted by focused agents for byte-exact verification;
#                empty on the parser's first pass


@dataclass
class CitationClaim:
    """A claim from a focused agent that some text came from a specific rec."""

    section_id: str
    rec_number: int
    quote: str


@dataclass
class ParsedQAQueryV2:
    """v2 query shape — see module docstring above."""

    question: str
    intent: VnIntent = VnIntent.OUT_OF_SCOPE
    sections: List[str] = field(default_factory=list)
    slots: Dict[str, Any] = field(default_factory=dict)

    # Multi-intent expansion (catalog output_schema -> sub_questions[])
    sub_questions: List[Dict[str, Any]] = field(default_factory=list)

    # Topic router context (consumed by TopicVerificationAgent re-scorer)
    topic: Optional[str] = None
    qualifier: Optional[str] = None

    # Populated by focused agents after retrieval (byte-exact verified)
    citations: List[CitationClaim] = field(default_factory=list)

    # Clarification loop state
    clarification: Optional[str] = None
    clarification_reason: Optional[str] = None   # "topic_ambiguity" | "missing_slots" | "multiple_interpretations"
    previous_turns: List[Dict[str, Any]] = field(default_factory=list)

    # Parser confidence / scaffolding trace
    scaffolding_trace: Dict[str, Any] = field(default_factory=dict)
    parser_confidence: float = 0.0

    def is_out_of_scope(self) -> bool:
        return self.intent == VnIntent.OUT_OF_SCOPE

    def needs_clarification(self) -> bool:
        return bool(self.clarification)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent.value if isinstance(self.intent, VnIntent) else self.intent,
            "sections": list(self.sections),
            "slots": dict(self.slots),
            "sub_questions": list(self.sub_questions),
            "topic": self.topic,
            "qualifier": self.qualifier,
            "citations": [
                {"section_id": c.section_id, "rec_number": c.rec_number, "quote": c.quote}
                for c in self.citations
            ],
            "clarification": self.clarification,
            "clarification_reason": self.clarification_reason,
            "previous_turns": list(self.previous_turns),
            "scaffolding_trace": dict(self.scaffolding_trace),
            "parser_confidence": self.parser_confidence,
        }


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
