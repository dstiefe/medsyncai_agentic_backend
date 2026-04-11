# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This file lives under agents/qa_v3/ and is the active v3 copy of the
# Guideline Q&A pipeline. The previous location agents/qa/ has been archived to
# agents/_archive_qa_v2/ and is no longer imported anywhere. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
Intent Agent — classifies the question and extracts search parameters.

Responsibilities:
    - Classify question type (recommendation / evidence / knowledge_gap)
    - Extract search terms, section references, topic sections
    - Extract numeric context and clinical variables
    - Detect contraindication questions
    - Build the IntentResult that all downstream agents consume

This agent is purely deterministic — no LLM calls.
It wraps the existing classification functions in qa_service.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .schemas import IntentResult
from .section_index import score_question_sections

# Import existing deterministic functions from qa_service
from ...services.qa_service import (
    classify_question_type,
    classify_table8_tier,
    extract_clinical_variables,
    extract_numeric_context,
    extract_search_terms,
    extract_section_references,
    extract_topic_sections,
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
    """Classifies the user's question and extracts search parameters."""

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

        Args:
            question: the user's raw question
            context: optional patient context dict (vessel, nihss, etc.)

        Returns:
            IntentResult with all fields populated
        """
        context = context or {}
        q_lower = question.lower()

        # Core extraction — all deterministic
        search_terms = extract_search_terms(question)
        section_refs = extract_section_references(question)
        topic_sections, suppressed_sections = extract_topic_sections(question)
        numeric_ctx = extract_numeric_context(question)
        clinical_vars = extract_clinical_variables(question)
        question_type = classify_question_type(question)

        # Track where topic_sections came from — the assembly agent
        # trusts TOPIC_SECTION_MAP hits but not concept index hits
        # when deciding whether to ask for clarification.
        topic_sections_source = "topic_map" if topic_sections else ""

        # ── Concept index fallback ────────────────────────────────
        # When TOPIC_SECTION_MAP doesn't resolve to any section,
        # use the data-driven concept index to find the best match.
        # This covers terminology gaps in the hand-curated map.
        # Only applied to recommendation and knowledge_gap questions —
        # evidence questions need wider section coverage.
        if (
            not topic_sections
            and not section_refs
            and self._section_concepts
            and question_type in ("recommendation", "knowledge_gap")
        ):
            concept_hits = score_question_sections(
                question, self._section_concepts, top_k=3
            )
            if concept_hits:
                top_score = concept_hits[0][1]
                # Require minimum score of 10 (at least 2-3 meaningful term matches)
                # and clear separation from runner-up
                if top_score >= 10:
                    topic_sections = [
                        s for s, sc in concept_hits
                        if sc >= top_score * 0.7
                    ]
                    topic_sections_source = "concept_index"

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

        # Merge patient context into search terms (case-specific only)
        context_summary = ""
        if context and not is_general:
            search_terms, clinical_vars, context_summary = self._merge_context(
                search_terms, clinical_vars, context
            )
        elif is_general:
            clinical_vars = extract_clinical_variables(question)

        # Contraindication detection
        is_contra = _detect_contraindication(q_lower)
        contra_tier = classify_table8_tier(question) if is_contra else None

        return IntentResult(
            question=question,
            question_type=question_type,
            search_terms=search_terms,
            section_refs=section_refs,
            topic_sections=topic_sections,
            topic_sections_source=topic_sections_source,
            suppressed_sections=suppressed_sections,
            numeric_context=numeric_ctx,
            clinical_vars=clinical_vars,
            is_general_question=is_general,
            is_evidence_question=is_evidence,
            is_contraindication_question=is_contra,
            contraindication_tier=contra_tier,
            context_summary=context_summary,
        )

    @staticmethod
    def _merge_context(
        search_terms: List[str],
        clinical_vars: Dict[str, Any],
        context: Dict[str, Any],
    ) -> tuple:
        """Merge patient context into search terms and clinical vars."""
        ctx_vessel = context.get("vessel")
        if ctx_vessel:
            vessel_lower = str(ctx_vessel).lower()
            extra = CONCEPT_SYNONYMS.get(vessel_lower, [vessel_lower])
            search_terms = list(set(search_terms + extra))

        if context.get("wakeUp"):
            search_terms = list(set(search_terms + ["wake", "unknown", "onset", "extended"]))

        if context.get("isM2"):
            search_terms = list(set(search_terms + ["m2", "medium vessel", "mevo"]))

        for key in ("nihss", "age", "timeHours", "vessel", "prestrokeMRS", "aspects"):
            if key not in clinical_vars and context.get(key) is not None:
                clinical_vars[key] = context[key]

        # Build display summary
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

        context_summary = ", ".join(parts) if parts else ""
        return search_terms, clinical_vars, context_summary
