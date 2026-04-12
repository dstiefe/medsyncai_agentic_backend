# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v4/ and is the active v4 copy of the
# Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: removed regex extractors (extract_search_terms,
# extract_section_references, extract_topic_sections, extract_numeric_context,
# extract_clinical_variables). The LLM parser in query_parsing_agent.py
# is the primary classifier. This agent is now a minimal fallback only.
# ───────────────────────────────────────────────────────────────────────
"""
Intent Agent — deterministic question classifier (FALLBACK ONLY).

In v4, the LLM-based QAQueryParsingAgent is the primary classifier.
This agent is the fallback when the LLM is unavailable. It provides:
    - Question type classification (recommendation / evidence / knowledge_gap)
    - Contraindication detection
    - General question detection

It does NOT extract search terms, section references, topic sections,
numeric context, or clinical variables — those are all handled by
the LLM parser in v4.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schemas import IntentResult
from .section_index import score_question_sections

# Import only the deterministic classifiers that remain in qa_service.py
from ...services.qa_service import (
    classify_question_type,
    classify_table8_tier,
    CONCEPT_SYNONYMS,
)


# ── General question detection phrases ──────────────────────────────

_GENERAL_QUESTION_PHRASES = [
    "in general", "not regarding", "not about this patient",
    "not for this patient", "not this patient",
    "what is the", "what are the", "what's the",
    "when is", "when should", "when can",
    "is there a recommendation", "what does the guideline say",
    "regardless of", "for any patient",
]

# ── Contraindication detection terms ────────────────────────────────

_EXPLICIT_CONTRA_TERMS = [
    "contraindication", "contraindicated", "table 8",
    "absolute", "relative",
    "benefit may exceed risk", "benefit over risk", "benefit outweigh",
    "benefit exceed", "benefit likely outweigh",
    "tier of", "tier for", "tier does", "what tier",
    "classified as", "classification",
]

_IVT_CONTEXT = ["ivt", "thrombolysis", "alteplase", "thrombolytic", "tpa"]

_TABLE8_CONDITIONS = [
    "extra-axial", "extraaxial", "extra-axial intracranial neoplasm",
    "unruptured aneurysm", "unruptured intracranial aneurysm",
    "moya-moya", "moyamoya",
    "procedural stroke", "angiographic procedural",
    "remote gi", "remote gu", "history of gi bleeding",
    "history of myocardial infarction", "remote mi", "history of mi",
    "recreational drug", "cocaine", "methamphetamine", "illicit drug",
    "substance use", "substance abuse",
    "stroke mimic", "mimic",
    "seizure at onset",
    "cerebral microbleed", "microbleed", "cmb",
    "menstruation", "diabetic retinopathy",
    "intracranial hemorrhage", "active internal bleeding",
    "extensive hypodensity", "hypodensity", "multilobar infarction",
    "traumatic brain injury", "tbi",
    "neurosurgery", "spinal cord injury",
    "intra-axial", "intraaxial", "brain tumor", "glioma",
    "infective endocarditis", "endocarditis",
    "severe coagulopathy", "coagulopathy",
    "aortic dissection", "aortic arch dissection",
    "aria", "amyloid", "lecanemab", "aducanumab",
    "glucose <50", "blood glucose less than 50",
    "doac within 48", "recent doac",
    "prior intracranial hemorrhage", "prior ich",
    "arterial dissection", "cervical dissection",
    "pregnancy", "pregnant", "postpartum", "post-partum",
    "active malignancy", "active cancer",
    "pre-existing disability", "preexisting disability", "prior disability",
    "vascular malformation", "avm", "cavernoma",
    "pericarditis", "cardiac thrombus",
    "dural puncture", "lumbar puncture",
    "arterial puncture", "noncompressible",
    "amyloid angiopathy",
    "hepatic failure", "liver failure",
    "pancreatitis", "septic embolism",
    "dementia", "dialysis",
]


def _detect_contraindication(q_lower: str) -> bool:
    """Detect whether this is a contraindication question (explicit or implicit)."""
    is_explicit = any(ct in q_lower for ct in _EXPLICIT_CONTRA_TERMS)

    has_ivt = any(t in q_lower for t in _IVT_CONTEXT)
    has_t8 = any(t in q_lower for t in _TABLE8_CONDITIONS)
    is_implicit = has_ivt and has_t8

    is_eligibility_with_condition = (
        ("can ivt be" in q_lower or "can thrombolysis be" in q_lower or
         "is ivt safe" in q_lower or "eligible for ivt" in q_lower or
         "ivt eligible" in q_lower)
        and has_t8
    )

    return is_explicit or is_implicit or is_eligibility_with_condition


class IntentAgent:
    """Deterministic question classifier — fallback when LLM is unavailable.

    In v4, the LLM parser handles all extraction (search terms, clinical
    variables, topic sections, etc.). This agent only provides:
    - question_type classification
    - contraindiction detection
    - general/evidence question detection
    """

    def __init__(self, section_concepts: Optional[Dict[str, Any]] = None):
        """
        Args:
            section_concepts: pre-built section concept index from
                build_section_concept_index(). If None, the concept
                index fallback is disabled.
        """
        self._section_concepts = section_concepts

    def run(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        Analyze the question and return structured intent data.

        In v4, this is FALLBACK ONLY — the LLM parser is primary.
        This agent provides basic classification without clinical
        variable extraction (that's the LLM's job).

        Args:
            question: the user's raw question
            context: optional patient context dict (vessel, nihss, etc.)

        Returns:
            IntentResult with classification fields populated.
            search_terms, section_refs, topic_sections, numeric_context,
            and clinical_vars will be empty (LLM parser handles these).
        """
        context = context or {}
        q_lower = question.lower()

        # Basic classification — deterministic
        question_type = classify_question_type(question)

        # General question detection
        is_general = any(phrase in q_lower for phrase in _GENERAL_QUESTION_PHRASES)

        # Evidence question detection
        is_evidence = any(
            term in q_lower
            for term in [
                "study", "studies", "trial", "data", "evidence",
                "research", "rct", "provided", "why",
            ]
        )

        # Contraindication detection
        is_contra = _detect_contraindication(q_lower)
        contra_tier = classify_table8_tier(question) if is_contra else None

        # Build context summary from patient context if provided
        context_summary = ""
        if context and not is_general:
            context_summary = self._build_context_summary(context)

        return IntentResult(
            question=question,
            question_type=question_type,
            search_terms=[],
            section_refs=[],
            topic_sections=[],
            topic_sections_source="",
            suppressed_sections=[],
            numeric_context={},
            clinical_vars={},
            is_general_question=is_general,
            is_evidence_question=is_evidence,
            is_contraindication_question=is_contra,
            contraindication_tier=contra_tier,
            context_summary=context_summary,
        )

    @staticmethod
    def _build_context_summary(context: Dict[str, Any]) -> str:
        """Build display summary from patient context."""
        parts = []
        if context.get("age"):
            parts.append(f"{context['age']}y")
        if context.get("sex"):
            parts.append("M" if str(context["sex"]).lower() == "male" else "F")
        if context.get("nihss") is not None:
            parts.append(f"NIHSS {context['nihss']}")
        if context.get("vessel"):
            parts.append(str(context["vessel"]))
        if context.get("wakeUp"):
            parts.append("wake-up stroke")
        elif context.get("lastKnownWellHours") is not None:
            parts.append(f"LKW {context['lastKnownWellHours']}h")
        elif context.get("timeHours") is not None:
            parts.append(f"{context['timeHours']}h from symptom recognition")

        return ", ".join(parts) if parts else ""
