"""
JSON contracts between Q&A pipeline agents.

Every agent receives and returns one of these typed dicts.
This is the single source of truth for inter-agent data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    search_method: str = "deterministic"    # "deterministic" | "semantic" | "hybrid"


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
        return result
