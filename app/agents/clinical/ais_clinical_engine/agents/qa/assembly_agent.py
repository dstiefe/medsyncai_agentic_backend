"""
Assembly Agent — formats the final response from all search agents' outputs.

Responsibilities:
    1. VERBATIM REC ASSEMBLY — recommendation text is returned character-for-character,
       never paraphrased, never summarized, never blended across recs.
    2. SCOPE GATE — if no recs score above the confidence threshold, explicitly
       refuse rather than letting the LLM fill the gap.
    3. CLARIFICATION DETECTION — when top recs have conflicting COR values in
       the same section, present options instead of guessing.
    4. SUMMARIZATION GUARDRAILS — RSS and KG text may be summarized, but with
       strict rules: no invented numbers, no dropped qualifiers, no blending
       across recs' supportive text.
    5. AUDIT TRAIL — log every decision made during response assembly.

Rules:
    - Recommendations → VERBATIM, untouched
    - Supportive Text (RSS) → may be summarized (LLM)
    - Knowledge Gaps → may be summarized (LLM)
    - The LLM frames, it does not rephrase recommendations.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .schemas import (
    AssemblyResult,
    AuditEntry,
    ClarificationOption,
    IntentResult,
    KnowledgeGapResult,
    RecommendationResult,
    ScoredRecommendation,
    SupportiveTextResult,
)

# Import helpers from qa_service
from ...services.qa_service import (
    clean_pdf_text,
    extract_trial_names,
    strip_rec_prefix_from_rss,
    truncate_text,
)


# ── Scope Gate Thresholds ───────────────────────────────────────────

# Minimum score for the top recommendation to be considered "in scope"
SCOPE_GATE_MIN_SCORE = 3

# Minimum score for a rec to be included in the response
REC_INCLUSION_MIN_SCORE = 1

# Maximum recommendations to DISPLAY to the user — the conversational
# summary is the primary answer; verbatim recs are the evidence backing it
# Legacy cap — only applies to non-section-routed (keyword fallback) results.
# Section-routed results show ALL recs from the section.
MAX_RECS_DISPLAYED_FALLBACK = 3

# Maximum recommendations the LLM sees for summarization context —
# Legacy cap for non-section-routed (keyword fallback) LLM context.
MAX_RECS_FOR_LLM = 5

# Maximum supporting text entries — RSS only shown if it adds
# something the rec text doesn't already cover
MAX_SUPPORTING_TEXT = 1


# ── Clarification Rules (hardcoded for known ambiguity patterns) ────

_ELIGIBILITY_KEYWORDS = {
    "recommend", "recommended", "indication", "indicated", "eligible",
    "eligibility", "candidate", "appropriate",
    "can i give", "is it safe", "should i give", "should we give",
    "is ivt recommended", "is thrombolysis recommended",
}

CLARIFICATION_RULES = [
    {
        "topic_terms": ["m2"],
        "distinguishing_var": "m2Dominant",
        "question_keywords": [
            "dominant", "nondominant", "non-dominant", "codominant",
            "proximal", "m3",
        ],
        "sections": ["4.7.2"],
        "options": [
            ClarificationOption(
                label="A",
                description="Dominant proximal M2 — EVT is reasonable within 6 hours",
                section="4.7.2",
                rec_id="rec-4.7.2-007",
                cor="2a",
                loe="B-NR",
            ),
            ClarificationOption(
                label="B",
                description="Non-dominant or codominant M2 — EVT is NOT recommended",
                section="4.7.2",
                rec_id="rec-4.7.2-008",
                cor="3: No Benefit",
                loe="B-R",
            ),
        ],
        "clarification_text": (
            "The M2 recommendation depends on whether it's a dominant proximal "
            "or non-dominant/codominant occlusion — the guidance is quite different:\n\n"
            "- A — Dominant proximal M2: EVT is reasonable within 6 hours "
            "(Section 4.7.2 Rec 7, COR 2a, LOE B-NR)\n"
            "- B — Non-dominant or codominant M2: EVT is NOT recommended "
            "(Section 4.7.2 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
            "Which type are you asking about?"
        ),
    },
    {
        "topic_terms": ["ivt", "thrombolysis", "tpa", "alteplase"],
        "distinguishing_var": "nonDisabling",
        "question_keywords": [
            "disabling", "non-disabling", "nondisabling", "mild",
        ],
        "sections": ["4.6.1"],
        "options": [
            ClarificationOption(
                label="A",
                description="Disabling deficit — IVT is recommended regardless of NIHSS",
                section="4.6.1",
                rec_id="rec-4.6.1-001",
                cor="1",
                loe="A",
            ),
            ClarificationOption(
                label="B",
                description="Non-disabling deficit (NIHSS 0-5) — IVT is NOT recommended",
                section="4.6.1",
                rec_id="rec-4.6.1-008",
                cor="3: No Benefit",
                loe="B-R",
            ),
        ],
        "clarification_text": (
            "This depends on whether the deficit is disabling or "
            "non-disabling — the recommendation changes significantly:\n\n"
            "- A — Disabling deficit: IVT is recommended regardless of NIHSS "
            "(Section 4.6.1 Rec 1, COR 1, LOE A)\n"
            "- B — Non-disabling deficit (NIHSS 0-5): IVT is NOT recommended "
            "(Section 4.6.1 Rec 8, COR 3: No Benefit, LOE B-R)\n\n"
            "Is the deficit disabling or non-disabling?"
        ),
    },
]


# ── Section Descriptions (user-facing guidance for follow-up) ──────

_SECTION_DESCRIPTIONS = {
    "2.1": "Public stroke awareness and education campaigns",
    "2.2": "EMS stroke recognition scales and dispatch protocols",
    "2.3": "Prehospital assessment, field management, and notification",
    "2.4": "EMS destination selection — which hospital to transport to",
    "2.5": "Mobile stroke units (MSUs) — prehospital CT and treatment",
    "2.6": "Hospital stroke certification and capability levels",
    "2.7": "Emergency department evaluation, door-to-imaging, stroke teams",
    "2.8": "Telemedicine/telestroke for remote stroke assessment",
    "2.9": "Organization of stroke systems of care and networks",
    "2.10": "Stroke registries, quality improvement, performance metrics",
    "3.1": "Stroke severity scales (NIHSS) and clinical assessment",
    "3.2": "Brain imaging — CT, CTA, MRI, perfusion for acute stroke",
    "3.3": "Laboratory tests before treatment (CBC, INR, glucose, etc.)",
    "4.1": "Airway management, supplemental oxygen, intubation",
    "4.2": "Head-of-bed positioning (flat vs elevated)",
    "4.3": "Blood pressure management — targets before/during/after treatment",
    "4.4": "Temperature management — fever control and hypothermia",
    "4.5": "Blood glucose management — hyperglycemia and hypoglycemia",
    "4.6.1": "IV thrombolysis (IVT/tPA) — eligibility, timing, and decision-making",
    "4.6.2": "Choice of thrombolytic agent — tenecteplase vs alteplase",
    "4.6.3": "Extended time window IVT — wake-up stroke, imaging-based selection",
    "4.6.4": "Other IV fibrinolytics (streptokinase, IA thrombolysis, sonothrombolysis)",
    "4.6.5": "IVT in special circumstances (sickle cell, pregnancy, CRAO, etc.)",
    "4.7.1": "Bridging therapy — IVT before EVT, direct-to-EVT decisions",
    "4.7.2": "Endovascular thrombectomy (EVT) — eligibility, time windows, patient selection",
    "4.7.3": "Posterior circulation stroke — basilar artery thrombectomy",
    "4.7.4": "EVT techniques — devices, anesthesia, door-to-groin times",
    "4.7.5": "EVT in pediatric patients",
    "4.8": "Antiplatelet therapy — aspirin, clopidogrel, DAPT, timing",
    "4.9": "Anticoagulation — heparin, DOACs, argatroban in acute stroke",
    "4.10": "Volume expansion, hemodilution, hemodynamic augmentation",
    "4.11": "Neuroprotective agents (magnesium, etc.)",
    "4.12": "Emergency carotid endarterectomy/stenting (without intracranial clot)",
    "5.1": "Stroke unit admission and level of care",
    "5.2": "Dysphagia screening — swallowing assessment before oral intake",
    "5.3": "Nutrition — tube feeding, enteral route selection",
    "5.4": "DVT prophylaxis — compression devices, anticoagulation",
    "5.5": "Post-stroke depression — screening and treatment",
    "5.6": "Other in-hospital management — antibiotics, catheters, fluoxetine",
    "5.7": "Rehabilitation — timing, intensity, early mobilization",
    "6.1": "Brain swelling — monitoring and general management",
    "6.2": "Brain swelling — medical management (osmotic therapy)",
    "6.3": "Decompressive craniectomy — surgical management of cerebral edema",
    "6.4": "Cerebellar infarction — surgical management",
    "6.5": "Seizure management — prophylaxis and treatment after stroke",
}

# ── Content Breadth ────────────────────────────────────────────────
# Measures the TOTAL VOLUME of qualifying content the search retrieved.
# A vague question pulls back a lot of content — many recs, many RSS
# entries, across many sections or within a single dense section.
# A specific question pulls back focused content — 1-2 recs, 1-2 RSS.
#
# The content breadth score has THREE components:
#
# 1. Section spread: how many distinct section clusters have results
# 2. Rec count: how many qualifying recommendations were found
# 3. RSS count: how many supportive text entries were retrieved
#
# Triggers (any one fires → ask clarification):
#   - 3+ section clusters with qualifying recs (cross-section breadth)
#   - More than 2 qualifying recs (rec-level breadth)
#   - Large RSS volume supporting the recs (content depth)
#
# The follow-up message adapts:
#   - Cross-section: "Which area are you asking about?" → section options
#   - Within-section: "This section covers multiple scenarios" → rec options
#
# TOPIC_SECTION_MAP override: when the map resolved to ≤2 sections
# AND the content volume is low, trust the routing.

# Thresholds
BREADTH_SECTION_THRESHOLD = 3    # 3+ section clusters → too broad
BREADTH_REC_THRESHOLD = 2        # more than 2 qualifying recs → too broad
BREADTH_MIN_SCORE_FRACTION = 0.33  # noise filter for section clusters
IN_TOPIC_REC_THRESHOLD = 6      # ≥6 in-topic recs = dense section

# ── Narrowing qualifiers ──────────────────────────────────────────
# Terms that narrow a question to a specific clinical aspect beyond
# the topic keyword. Their presence means the user is asking about
# a particular parameter, timing, drug, or scenario — NOT about the
# entire topic. Used to distinguish "What is the tenecteplase DOSE?"
# (specific) from "What are the EVT recommendations?" (broad).
_NARROWING_QUALIFIERS = [
    # Clinical parameters
    "dose", "dosing", "target", "threshold", "level", "goal",
    # Temporal qualifiers (specific enough to narrow, not generic "after X")
    "before", "within", "prior to",
    # Time units
    "hours", "minutes", "hour",
    # Procedures / assessments
    "screening", "prophylaxis",
    # Process metrics
    "door-to-needle", "door-to-groin",
    # Positioning
    "flat", "elevated",
    # Quantity / type
    "dual",
    # Route / intake
    "oral intake",
    # Patient selection
    "eligibility", "eligible", "candidate",
    # Specific scenarios
    "large mca", "large infarct", "wake-up", "wake up", "unknown onset",
    "pregnancy", "pregnant", "pediatric", "sickle cell",
    # Specific anatomy (narrows within broader EVT topic)
    "basilar", "posterior", "m1", "m2", "m3", "ica",
    "carotid", "distal mca", "aca", "pca", "lvo",
    "a2", "a3", "p2", "p3",
    # Specific drugs / devices (narrows within broader treatment topic)
    "tpa", "alteplase", "tenecteplase",
    "ipc", "aspirin", "clopidogrel", "heparin",
    "supplemental", "mannitol", "hypertonic", "glibenclamide",
    "labetalol", "nicardipine", "warfarin",
    # Specific conditions (narrows within broader complication topic)
    "angioedema", "sich", "seizure",
    # Specific numeric references
    "185", "220", "0.9 mg", "0.25 mg",
    # Imaging criteria (narrows EVT questions)
    "aspects", "pc-aspects", "aspect score",
    # Imaging modalities (narrows to specific imaging type)
    "mri", "ct ", "cta", "ctp", "ct perfusion", "mr perfusion",
    "mra", "ncct", "dwi", "flair", "angiography",
    # Time windows (narrows EVT/IVT questions)
    "6 hours", "24 hours", "10 hours", "12 hours",
    "6h", "24h", "10h", "12h",
    "lkw", "last known well",
]

# ── Specific question patterns ──────────────────────────────────
# Questions with clear intent that should be answered directly,
# even if the retrieval spans multiple sections. These patterns
# indicate the user has a specific yes/no or factual question.
_SPECIFIC_QUESTION_PATTERNS = [
    re.compile(r"do i need\b", re.IGNORECASE),
    re.compile(r"is .+ (required|necessary|needed|mandatory)", re.IGNORECASE),
    re.compile(r"is .+ (recommended|beneficial|harmful|safe|effective|indicated|contraindicated)", re.IGNORECASE),
    re.compile(r"is .+ an? (option|contraindication)", re.IGNORECASE),
    re.compile(r"should i (use|give|administer|order|get|perform|start|treat|check|screen|intubate|lower|target|keep|hold)", re.IGNORECASE),
    re.compile(r"can i (use|give|administer|skip|avoid|delay|lower|still)", re.IGNORECASE),
    re.compile(r"can .+ (be given|be used|receive|get)", re.IGNORECASE),
    re.compile(r"when (should|do|can) i\b", re.IGNORECASE),
    re.compile(r"how (long|quickly|fast|soon|should)\b", re.IGNORECASE),
    re.compile(r"what (dose|dosing|drug|agent|device|bp|imaging|lab)\b", re.IGNORECASE),
    re.compile(r"what is the (recommended|bp|dose|target|threshold|cutoff)", re.IGNORECASE),
    re.compile(r"my patient has .+\. (can|should|is)", re.IGNORECASE),
    re.compile(r"(should|does) the guideline\b", re.IGNORECASE),
    re.compile(r"are .+ (recommended|harmful|beneficial|safe|effective)", re.IGNORECASE),
]


# ── Extract rec numbers cited in LLM summary ──────────────────────
def _extract_cited_rec_numbers(summary: str) -> set:
    """
    Parse the LLM summary to find which recommendation numbers it cited.

    Matches patterns like:
      - "Recommendation 7", "Recommendation #7", "Rec 7", "Rec #7"
      - "Recommendation 7 (COR 2a)", "Recommendations 7 and 9"
      - "#7", "#9" (when in context of recommendations)
    """
    import re
    cited = set()

    # "Recommendation(s) 7", "Rec 7", "Rec #7", "recommendation 7"
    for m in re.finditer(
        r'(?:recommendation|rec)s?\s*#?\s*(\d+)', summary, re.IGNORECASE
    ):
        cited.add(m.group(1))

    # "#7" standalone (common in LLM output like "per #7 and #9")
    for m in re.finditer(r'#(\d+)', summary):
        cited.add(m.group(1))

    # Numbers following "and/or" near an already-cited rec reference
    # e.g., "Recommendations 1, 7, and 9" — catches the 9
    for m in re.finditer(r'(?:,|and|or|&)\s*#?\s*(\d+)', summary):
        num = m.group(1)
        # Only include if it looks like a rec number (1-20 range)
        # and there's already a cited rec nearby (within 60 chars before)
        start = max(0, m.start() - 60)
        prefix = summary[start:m.start()].lower()
        if int(num) <= 20 and re.search(r'(?:recommendation|rec)', prefix, re.IGNORECASE):
            cited.add(num)

    return cited


# ── Section hierarchy for clustering ─────────────────────────────
def _section_cluster(section: str) -> str:
    """Get the parent cluster for a section (e.g., '4.6.1' → '4.6')."""
    parts = section.split(".")
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}"  # 4.6.1 → 4.6
    if len(parts) == 2:
        return section  # 4.3 → 4.3
    return section  # fallback


def _compute_content_breadth(
    scored_recs: List["ScoredRecommendation"],
    rss_entries: list,
    top_n: int = 15,
) -> Dict[str, Any]:
    """
    Measure the total volume of content the search retrieved.

    Returns a dict with all three breadth dimensions:
        {
            "n_clusters": int,        # distinct section clusters
            "n_qualifying_recs": int,  # recs above inclusion threshold
            "n_rss_entries": int,      # supportive text entries
            "total_content_items": int, # recs + RSS combined
            "cluster_data": dict,      # cluster → {best_rec, total_score, rec_count}
            "trigger": str | None,     # which threshold triggered, or None
        }
    """
    result = {
        "n_clusters": 0,
        "n_qualifying_recs": 0,
        "n_rss_entries": len(rss_entries) if rss_entries else 0,
        "total_content_items": 0,
        "cluster_data": {},
        "trigger": None,
    }

    if not scored_recs:
        return result

    # Count qualifying recs and group by cluster
    qualifying_recs = [
        r for r in scored_recs[:top_n]
        if r.score >= REC_INCLUSION_MIN_SCORE
    ]
    result["n_qualifying_recs"] = len(qualifying_recs)
    result["total_content_items"] = len(qualifying_recs) + result["n_rss_entries"]

    if not qualifying_recs:
        return result

    # Group by section cluster
    cluster_data: Dict[str, dict] = {}
    for rec in qualifying_recs:
        cluster = _section_cluster(rec.section)
        if cluster not in cluster_data:
            cluster_data[cluster] = {
                "best_rec": rec,
                "total_score": 0,
                "rec_count": 0,
            }
        cluster_data[cluster]["total_score"] += rec.score
        cluster_data[cluster]["rec_count"] += 1

    # Filter to meaningful clusters (noise filter)
    top_cluster_score = max(
        cd["best_rec"].score for cd in cluster_data.values()
    )
    min_score = top_cluster_score * BREADTH_MIN_SCORE_FRACTION
    meaningful = {
        k: v for k, v in cluster_data.items()
        if v["best_rec"].score >= min_score
    }

    result["n_clusters"] = len(meaningful)
    result["cluster_data"] = meaningful

    # Determine which trigger fired (if any)
    if result["n_clusters"] >= BREADTH_SECTION_THRESHOLD:
        result["trigger"] = "cross_section"
    elif result["n_qualifying_recs"] > BREADTH_REC_THRESHOLD:
        result["trigger"] = "within_section"

    return result


def _build_within_section_clarification(
    target_recs: List[ScoredRecommendation],
    target_section: str,
) -> Dict[str, Any]:
    """
    Build a within-section clarification for a dense topic_map target.

    Used when topic_map confidently identified the section but it has
    too many recs to show all at once. Unlike the cross-section
    clarification, this ONLY shows recs from the target section —
    no noise from unrelated sections.
    """
    top_title = target_recs[0].section_title if target_recs else ""

    cor_order = {"1": 0, "2a": 1, "2b": 2, "3: No Benefit": 3,
                 "3:No Benefit": 3, "3: Harm": 4, "3:Harm": 4}
    target_recs_sorted = sorted(target_recs, key=lambda r: (
        cor_order.get(r.cor, 9), -r.score
    ))

    parts = [
        f"There are several recommendations in Section {target_section} "
        f"({top_title}) covering different scenarios. "
        f"Which one are you asking about?\n"
    ]
    options: List[ClarificationOption] = []
    labels = "ABCDEFGH"
    seen_texts: set = set()

    for rec in target_recs_sorted[:8]:
        text_key = rec.text[:80]
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        if len(options) >= 6:
            break

        label = labels[len(options)]
        text_preview = rec.text[:150]
        if len(rec.text) > 150:
            text_preview += "..."

        parts.append(
            f"- {label} — Rec {rec.rec_number} "
            f"(COR {rec.cor}, LOE {rec.loe})\n"
            f"  {text_preview}"
        )
        options.append(ClarificationOption(
            label=label,
            description=f"Rec {rec.rec_number} (COR {rec.cor}, LOE {rec.loe})",
            section=rec.section,
            rec_id=rec.rec_id,
            cor=rec.cor,
            loe=rec.loe,
        ))

    parts.append(
        "\nOr, if you can give me more detail — like a specific "
        "patient scenario, time window, or imaging modality — "
        "I can go straight to the right recommendation."
    )

    return {
        "text": "\n".join(parts),
        "sections": [target_section],
        "options": options,
        "reason": (
            f"within_section_topic_map: {len(target_recs)} recs "
            f"in target section {target_section}"
        ),
    }


class AssemblyAgent:
    """
    Assembles the final response from all search agents' outputs.

    The scope gate, clarification detection, and audit trail all live here
    because only after retrieval do we know whether the guideline covers
    the question and whether the results are ambiguous.
    """

    def __init__(self, nlp_service=None, guideline_knowledge=None, recommendations_store=None):
        self._nlp_service = nlp_service
        self._guideline_knowledge = guideline_knowledge or {}
        self._recommendations_store = recommendations_store or {}

    async def run(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
    ) -> AssemblyResult:
        """
        Assemble the final response.

        Args:
            intent: from IntentAgent
            rec_result: from RecommendationAgent
            rss_result: from SupportiveTextAgent
            kg_result: from KnowledgeGapAgent

        Returns:
            AssemblyResult with the formatted response
        """
        audit: List[AuditEntry] = []

        # Log intent
        audit.append(AuditEntry(
            step="intent_classification",
            detail={
                "question_type": intent.question_type,
                "target_sections": intent.section_refs or intent.topic_sections,
                "search_terms_count": len(intent.search_terms),
                "is_contraindication": intent.is_contraindication_question,
                "is_general": intent.is_general_question,
            },
        ))

        # Log retrieval results
        audit.append(AuditEntry(
            step="retrieval",
            detail={
                "rec_count": len(rec_result.scored_recs),
                "rec_top_score": rec_result.scored_recs[0].score if rec_result.scored_recs else 0,
                "rec_search_method": rec_result.search_method,
                "rss_count": len(rss_result.entries),
                "kg_has_gaps": kg_result.has_gaps,
            },
        ))

        # ── 1. Knowledge Gap deterministic response ─────────────────
        if intent.question_type == "knowledge_gap" and not kg_result.has_gaps:
            audit.append(AuditEntry(
                step="knowledge_gap_deterministic",
                detail={"response": "no_gaps_documented"},
            ))
            sections = intent.section_refs or intent.topic_sections
            return AssemblyResult(
                status="complete",
                answer=kg_result.deterministic_response or "",
                summary=kg_result.deterministic_response or "",
                citations=[
                    f"Section {s} -- Knowledge Gaps (none documented)"
                    for s in sections
                ],
                related_sections=sorted(sections),
                audit_trail=audit,
            )

        # ── 1b. Table 8 listing (general contraindication questions) ──
        # When the user asks about IVT contraindications generically
        # (no specific condition), show Table 8 directly instead of
        # trying to answer from recs/RSS which don't contain the table.
        # This triggers for listing questions like "What are the absolute
        # contraindications?" regardless of whether contraindication_tier
        # is set — the key is that no specific clinical condition is named.
        if intent.is_contraindication_question and self._is_table8_listing_question(intent):
            table8_result = self._format_table8_listing(intent)
            if table8_result:
                audit.append(AuditEntry(
                    step="table8_listing",
                    detail={"reason": "general_contraindication_question"},
                ))
                return table8_result

        # ── 2. SCOPE GATE (topic coverage) ──────────────────────────
        # Dynamic check: extract key terms from question, search
        # retrieved recs/RSS/KG. If not found, search the ENTIRE
        # guideline. If found elsewhere, offer redirect.
        coverage = self.check_topic_coverage(
            intent.question, rec_result.scored_recs,
            rss_result=rss_result, kg_result=kg_result,
        )
        if not coverage["covered"]:
            key_terms = coverage["key_terms"]
            found_elsewhere = coverage["found_elsewhere"]
            # Build a natural topic phrase from the question, not raw key terms
            # Use the original question's core topic for readability
            topic_phrase = "this topic"
            if key_terms:
                # Use at most 2 key terms for readability
                topic_phrase = " and ".join(key_terms[:2])

            # Build response based on whether term exists elsewhere
            if found_elsewhere:
                # Term exists in a different section — offer redirect
                elsewhere_parts = []
                seen_sections = set()
                for hit in found_elsewhere[:3]:  # max 3 redirect suggestions
                    sec = hit["section"]
                    if sec not in seen_sections:
                        seen_sections.add(sec)
                        elsewhere_parts.append(
                            f"Section {sec} — {hit['title']}"
                        )
                elsewhere_text = "; ".join(elsewhere_parts)
                answer_text = (
                    f"The 2026 AHA/ASA AIS Guidelines do not specifically "
                    f"address {topic_phrase} in the context you asked about. "
                    f"However, this topic is referenced in: {elsewhere_text}. "
                    f"Would you like me to look into that?"
                )
                related = sorted(seen_sections)
            else:
                # Term not found anywhere in the guideline
                answer_text = (
                    f"The 2026 AHA/ASA Guidelines for Acute Ischemic Stroke "
                    f"do not address {topic_phrase}. I searched the guideline "
                    f"recommendations, supportive text, and knowledge gaps "
                    f"across all sections and did not find any content on "
                    f"this topic."
                )
                related = []

            audit.append(AuditEntry(
                step="scope_gate_rejected",
                detail={
                    "reason": "topic_not_in_guideline",
                    "key_terms_searched": key_terms[:5],
                    "sources_checked": ["recommendations", "supportive_text", "knowledge_gaps", "full_guideline"],
                    "found_elsewhere": found_elsewhere[:3],
                    "top_score": rec_result.scored_recs[0].score if rec_result.scored_recs else 0,
                },
            ))
            return AssemblyResult(
                status="out_of_scope",
                answer=answer_text,
                summary="",
                related_sections=related,
                audit_trail=audit,
            )

        # ── 3. Clarification check (hardcoded rules) ───────────────
        clarification = self._check_clarification_rules(intent)
        if clarification:
            audit.append(AuditEntry(
                step="clarification_triggered",
                detail={"rule": clarification["rule_topic"]},
            ))
            return AssemblyResult(
                status="needs_clarification",
                answer=clarification["text"],
                summary=clarification["text"].split("\n")[0],
                related_sections=clarification["sections"],
                clarification_options=clarification["options"],
                audit_trail=audit,
            )

        # ── 3b. Content breadth + vagueness follow-up ────────────
        # Measures TOTAL content volume: recs + RSS + section spread.
        # Vague questions retrieve a lot of content. Specific questions
        # retrieve focused content. Logged on every recommendation Q.
        if rec_result.scored_recs and intent.question_type == "recommendation":
            content_breadth = _compute_content_breadth(
                rec_result.scored_recs, rss_result.entries
            )
            audit.append(AuditEntry(
                step="content_breadth",
                detail={
                    "n_clusters": content_breadth["n_clusters"],
                    "n_qualifying_recs": content_breadth["n_qualifying_recs"],
                    "n_rss_entries": content_breadth["n_rss_entries"],
                    "total_content_items": content_breadth["total_content_items"],
                    "trigger": content_breadth["trigger"],
                    "clusters": sorted(content_breadth["cluster_data"].keys()),
                    "topic_sections_override": bool(
                        intent.topic_sections and len(intent.topic_sections) <= 2
                        and intent.topic_sections_source == "topic_map"
                    ),
                },
            ))

        vague_followup = self._detect_vague_question(
            intent, rec_result, rss_result
        )
        if vague_followup:
            audit.append(AuditEntry(
                step="vague_question_followup",
                detail={
                    "reason": vague_followup["reason"],
                    "suggested_sections": vague_followup["sections"],
                },
            ))
            return AssemblyResult(
                status="needs_clarification",
                answer=vague_followup["text"],
                summary=vague_followup["text"].split("\n")[0],
                related_sections=vague_followup["sections"],
                clarification_options=vague_followup["options"],
                audit_trail=audit,
            )

        # ── 4. Generic ambiguity detection (CMI pattern) ────────────
        # SKIP when topic_map resolved to a narrow section AND the
        # section has FEW qualifying recs (≤3). In that case the user
        # asked about a specific topic (e.g., "basilar EVT" → 4.7.3
        # with only 2 recs) and wants ALL recs shown, even if they
        # have different COR values. Dense sections (like 4.7.2 with
        # 10+ recs) still need ambiguity detection.
        #
        # Key-term bypass: if the question has distinctive clinical
        # terms, the user knows what they're asking about. Skip
        # ambiguity detection — conflicting COR values in the results
        # are real (different recs for different scenarios), not
        # routing ambiguity.
        _key_terms_present = bool(self.extract_key_terms(intent.question))
        _skip_ambiguity = _key_terms_present  # specific question → skip

        if not _skip_ambiguity and (
            intent.topic_sections
            and len(intent.topic_sections) <= 2
            and intent.topic_sections_source == "topic_map"
            and rec_result.scored_recs
        ):
            target_set = set(intent.topic_sections)
            in_target_recs = [
                r for r in rec_result.scored_recs[:15]
                if r.score >= REC_INCLUSION_MIN_SCORE
                and r.section in target_set
            ]
            if len(in_target_recs) <= 5:
                _skip_ambiguity = True
            else:
                q_lower = intent.question.lower()
                _skip_ambiguity = any(
                    nq in q_lower for nq in _NARROWING_QUALIFIERS
                )

        if rec_result.scored_recs and not _skip_ambiguity:
            ambiguity = self._detect_generic_ambiguity(rec_result.scored_recs)
            if ambiguity:
                audit.append(AuditEntry(
                    step="ambiguity_detected",
                    detail={
                        "section": ambiguity["section"],
                        "conflicting_cors": ambiguity["cors"],
                    },
                ))
                return AssemblyResult(
                    status="needs_clarification",
                    answer=ambiguity["text"],
                    summary=ambiguity["text"].split("\n")[0],
                    related_sections=[ambiguity["section"]],
                    clarification_options=ambiguity["options"],
                    audit_trail=audit,
                )

        # ── 5. Section-level ambiguity detection ─────────────────────
        # When top-scored recs come from DIFFERENT sections with close
        # scores and no single section dominates, ask the user which
        # clinical area they're asking about rather than guessing wrong.
        # Only applies to recommendation questions — evidence and KG
        # questions naturally span sections.
        if rec_result.scored_recs and intent.question_type == "recommendation":
            section_ambiguity = self._detect_section_ambiguity(
                rec_result.scored_recs, intent
            )
            if section_ambiguity:
                audit.append(AuditEntry(
                    step="section_ambiguity_detected",
                    detail={
                        "competing_sections": section_ambiguity["sections"],
                    },
                ))
                return AssemblyResult(
                    status="needs_clarification",
                    answer=section_ambiguity["text"],
                    summary=section_ambiguity["text"].split("\n")[0],
                    related_sections=section_ambiguity["sections"],
                    clarification_options=section_ambiguity["options"],
                    audit_trail=audit,
                )

        # ── 6. SCOPE GATE (score threshold) ────────────────────────
        # Section-routed results bypass the score gate: the section
        # itself is the scope gate — if we resolved to a section, the
        # question is in scope by definition.
        is_section_routed = rec_result.search_method == "section_route"
        top_score = rec_result.scored_recs[0].score if rec_result.scored_recs else 0
        has_rss = rss_result.has_content
        has_kg = kg_result.has_gaps

        if not is_section_routed and top_score < SCOPE_GATE_MIN_SCORE and not has_rss and not has_kg:
            audit.append(AuditEntry(
                step="scope_gate_rejected",
                detail={
                    "reason": "low_score_no_content",
                    "top_score": top_score,
                    "threshold": SCOPE_GATE_MIN_SCORE,
                },
            ))
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically address "
                    "this question. This may be covered in other guidelines, "
                    "local institutional protocols, or prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        audit.append(AuditEntry(
            step="scope_gate_passed",
            detail={"top_score": top_score},
        ))

        # ── 7. ASSEMBLE RESPONSE ───────────────────────────────────
        # Route to the appropriate assembly path
        if intent.question_type in ("evidence", "knowledge_gap"):
            return await self._assemble_evidence_response(
                intent, rec_result, rss_result, kg_result, audit
            )
        else:
            return await self._assemble_recommendation_response(
                intent, rec_result, rss_result, kg_result, audit
            )

    # ── Recommendation response assembly ────────────────────────────

    async def _assemble_recommendation_response(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
        audit: List[AuditEntry],
    ) -> AssemblyResult:
        """Assemble response for recommendation questions — recs are VERBATIM."""
        answer_parts: List[str] = []
        citations: List[str] = []
        sections: set = set()
        all_trial_names: List[str] = []

        # Patient context header
        if intent.context_summary:
            answer_parts.append(f"For this patient ({intent.context_summary}):")

        # Contraindication tier classification
        if intent.is_contraindication_question and intent.contraindication_tier:
            tier = intent.contraindication_tier
            answer_parts.append(
                f"Table 8 — IVT Contraindication Classification: {tier}\n\n"
                f"Per Table 8 of the 2026 AHA/ASA AIS Guidelines, this is classified as "
                f"an {tier} contraindication to IVT."
            )
            citations.append(f"Table 8 -- IVT Contraindications and Special Situations ({tier})")
            sections.add("Table 8")

        # Numeric alerts (platelets, INR)
        self._add_numeric_alerts(intent, answer_parts, citations, sections)

        # ── VERBATIM RECOMMENDATIONS ────────────────────────────────
        # Each recommendation is shown individually with its full text,
        # section, COR, LOE. The text is NEVER modified or summarized.
        #
        # TOPIC-FOCUSED FILTERING: when topic_map resolved to a narrow
        # section (e.g., "basilar" → 4.7.3), only show recs from that
        # section. This prevents noise from sibling sections (4.7.4,
        # 4.7.5) bleeding into the response.
        _topic_target_sections = None
        if (
            intent.topic_sections
            and len(intent.topic_sections) <= 2
            and intent.topic_sections_source == "topic_map"
        ):
            _topic_target_sections = set(intent.topic_sections)

        included_rec_sections: set = set()
        included_rec_texts: List[str] = []

        # Section-routed results: ALL recs from the section go to both
        # the LLM (for context) and the user (in Details & Citations).
        # Recs are pre-ordered by keyword relevance so the most relevant
        # appear first. Non-section-routed (keyword fallback) results
        # use the legacy cap.
        is_section_routed = rec_result.search_method == "section_route"
        rec_parts_for_llm: List[str] = []

        # Filter to target sections when topic-routed
        candidate_recs = rec_result.scored_recs
        if _topic_target_sections:
            filtered = [
                r for r in candidate_recs
                if r.score >= REC_INCLUSION_MIN_SCORE
                and r.section in _topic_target_sections
            ]
            if filtered:
                candidate_recs = filtered
                logger.info(
                    "Topic filter: %d recs from sections %s",
                    len(filtered), _topic_target_sections,
                )
            else:
                logger.info(
                    "Topic filter: no recs in %s, using unfiltered",
                    _topic_target_sections,
                )

        # Build LLM context with ALL section recs (ordered by keyword
        # relevance). The user-visible answer_parts will be filtered
        # AFTER the LLM summary is generated, to show only cited recs.
        max_recs = len(candidate_recs) if is_section_routed else MAX_RECS_FOR_LLM

        # Track all qualifying recs for post-summary filtering
        all_qualifying_recs: List[ScoredRecommendation] = []

        for i, rec in enumerate(candidate_recs[:max_recs]):
            if rec.score < REC_INCLUSION_MIN_SCORE:
                continue

            rec_block = (
                f"RECOMMENDATION [{rec.rec_id}] Rec {rec.rec_number}\n"
                f"Section {rec.section} — {rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  Level of Evidence: {rec.loe}\n\n"
                f"\"{rec.text}\""
            )

            rec_parts_for_llm.append(rec_block)
            all_qualifying_recs.append(rec)
            all_trial_names.extend(extract_trial_names(rec.text))
            sections.add(rec.section)

        audit.append(AuditEntry(
            step="recs_included",
            detail={
                "count": len(included_rec_sections),
                "sections": sorted(included_rec_sections),
                "verbatim": True,
            },
        ))

        # ── Build ALL supporting text for LLM context ─────────────
        rss_parts_for_llm: List[str] = []
        seen_rss_keys: set = set()
        all_rss_by_rec: dict = {}  # rec_number → list of RSS text blocks

        for entry in rss_result.entries:
            if entry.entry_type == "rss":
                rss_key = f"{entry.section}:{entry.rec_number}"
                if rss_key in seen_rss_keys:
                    continue
                seen_rss_keys.add(rss_key)

                cleaned = clean_pdf_text(entry.text)
                if len(cleaned.strip()) < 40:
                    continue

                label = f"Supporting Evidence, Section {entry.section}"
                if entry.rec_number:
                    label += f" Rec {entry.rec_number}"
                rss_block = f"{label}: {cleaned}"
                rss_parts_for_llm.append(rss_block)

                # Index by rec number for post-summary filtering
                rn = str(entry.rec_number) if entry.rec_number else ""
                all_rss_by_rec.setdefault(rn, []).append({
                    "block": f"{label}: {truncate_text(cleaned, max_chars=300)}",
                    "citation": (
                        f"Section {entry.section} -- {entry.section_title} "
                        f"(Recommendation-Specific Supportive Text)"
                    ),
                    "entry": entry,
                })

            elif entry.entry_type == "synopsis":
                cleaned = clean_pdf_text(entry.text)
                rss_parts_for_llm.append(f"Synopsis: {cleaned}")

            all_trial_names.extend(extract_trial_names(entry.text))
            sections.add(entry.section)

        # ── Knowledge gaps for LLM context ─────────────────────────
        kg_parts_for_llm: List[str] = []
        if kg_result.has_gaps:
            for kg_entry in kg_result.entries:
                cleaned = clean_pdf_text(kg_entry.text)
                kg_parts_for_llm.append(
                    f"Knowledge Gaps, Section {kg_entry.section}: {cleaned}"
                )
                sections.add(kg_entry.section)

        # ── LLM SUMMARY — sees ALL section content ────────────────
        llm_context_parts = rec_parts_for_llm + rss_parts_for_llm + kg_parts_for_llm
        summary = ""
        cited_recs_from_llm = []
        if self._nlp_service and llm_context_parts:
            try:
                patient_ctx = intent.context_summary or ""
                all_content_for_summary = "\n\n".join(llm_context_parts)
                max_chars = 20000 if is_section_routed else 4000
                if len(all_content_for_summary) > max_chars:
                    all_content_for_summary = all_content_for_summary[:max_chars]
                logger.info(
                    "Calling LLM summarize_qa: question=%s, llm_recs=%d, rss=%d, chars=%d",
                    intent.question[:60], len(rec_parts_for_llm),
                    len(rss_parts_for_llm), len(all_content_for_summary),
                )
                llm_result = await self._nlp_service.summarize_qa(
                    question=intent.question,
                    details=all_content_for_summary,
                    citations=[],  # citations built after filtering
                    patient_context=patient_ctx,
                )
                summary = llm_result.get("summary", "")
                cited_recs_from_llm = llm_result.get("cited_recs", [])
                if summary:
                    logger.info("LLM summary generated: %d chars, cited_recs=%s",
                                len(summary), cited_recs_from_llm)
                else:
                    logger.warning("LLM summarize_qa returned empty summary")
            except Exception as e:
                logger.error("LLM summary failed, using deterministic: %s", e)
        elif not llm_context_parts:
            logger.warning(
                "No content for LLM summary — nlp_service=%s, scored_recs=%d",
                bool(self._nlp_service), len(rec_result.scored_recs),
            )

        if not summary:
            summary = self._generate_summary(rec_result.scored_recs, intent)

        # ── POST-SUMMARY FILTERING ─────────────────────────────────
        # Use the cited_recs returned by the LLM (structured JSON output)
        # to show only those recs (+ their RSS) in Details & Citations.
        # This keeps the user-facing output focused on what the summary
        # actually discusses, so the clinician can verify.
        if is_section_routed and summary:
            # Use LLM's structured cited_recs; fall back to regex if empty
            cited_rec_numbers = {str(r) for r in cited_recs_from_llm} if cited_recs_from_llm else _extract_cited_rec_numbers(summary)
            logger.info("LLM cited rec numbers: %s (from_structured=%s)",
                        cited_rec_numbers, bool(cited_recs_from_llm))

            if cited_rec_numbers:
                # Show only cited recs
                for rec in all_qualifying_recs:
                    rn = str(rec.rec_number).strip()
                    if rn in cited_rec_numbers:
                        rec_block = (
                            f"RECOMMENDATION [] Section {rec.section} — "
                            f"{rec.section_title} "
                            f"Class of Recommendation: {rec.cor}  |  "
                            f"Level of Evidence: {rec.loe}\n\n"
                            f"\"{rec.text}\""
                        )
                        answer_parts.append(rec_block)
                        citations.append(
                            f"Section {rec.section} -- {rec.section_title} "
                            f"(COR {rec.cor}, LOE {rec.loe})"
                        )
                        included_rec_sections.add(rec.section)
                        included_rec_texts.append(rec.text)

                # Show RSS for cited recs only
                for rn in cited_rec_numbers:
                    for rss_info in all_rss_by_rec.get(rn, []):
                        answer_parts.append(rss_info["block"])
                        citations.append(rss_info["citation"])
            else:
                # LLM didn't cite specific recs — show top 3 by score
                for rec in all_qualifying_recs[:3]:
                    rec_block = (
                        f"RECOMMENDATION [] Section {rec.section} — "
                        f"{rec.section_title} "
                        f"Class of Recommendation: {rec.cor}  |  "
                        f"Level of Evidence: {rec.loe}\n\n"
                        f"\"{rec.text}\""
                    )
                    answer_parts.append(rec_block)
                    citations.append(
                        f"Section {rec.section} -- {rec.section_title} "
                        f"(COR {rec.cor}, LOE {rec.loe})"
                    )
                    included_rec_sections.add(rec.section)
                    included_rec_texts.append(rec.text)
        else:
            # Non-section-routed (fallback): show top N by score
            max_displayed = MAX_RECS_DISPLAYED_FALLBACK
            displayed_count = 0
            for rec in all_qualifying_recs[:max_displayed]:
                rec_block = (
                    f"RECOMMENDATION [{rec.rec_id}]\n"
                    f"Section {rec.section} — {rec.section_title}\n"
                    f"Class of Recommendation: {rec.cor}  |  "
                    f"Level of Evidence: {rec.loe}\n\n"
                    f"\"{rec.text}\""
                )
                answer_parts.append(rec_block)
                citations.append(
                    f"Section {rec.section} -- {rec.section_title} "
                    f"(COR {rec.cor}, LOE {rec.loe})"
                )
                included_rec_sections.add(rec.section)
                included_rec_texts.append(rec.text)
                displayed_count += 1

            # Legacy RSS cap for fallback
            supporting_count = 0
            for entry in rss_result.entries:
                if supporting_count >= MAX_SUPPORTING_TEXT:
                    break
                if entry.entry_type != "rss":
                    continue
                cleaned = clean_pdf_text(entry.text)
                cleaned = strip_rec_prefix_from_rss(cleaned, included_rec_texts)
                text = truncate_text(cleaned, max_chars=300)
                if len(text.strip()) < 40:
                    continue
                label = f"Supporting Evidence, Section {entry.section}"
                if entry.rec_number:
                    label += f" Rec {entry.rec_number}"
                answer_parts.append(f"{label}: {text}")
                citations.append(
                    f"Section {entry.section} -- {entry.section_title} "
                    f"(Recommendation-Specific Supportive Text)"
                )
                supporting_count += 1

        # ── Knowledge gaps in user display ──────────────────────────
        if kg_result.has_gaps:
            kg_limit = len(kg_result.entries) if is_section_routed else 1
            for kg_entry in kg_result.entries[:kg_limit]:
                cleaned = clean_pdf_text(kg_entry.text)
                text = truncate_text(cleaned, max_chars=300)
                answer_parts.append(
                    f"Knowledge Gaps, Section {kg_entry.section}: {text}"
                )
                citations.append(
                    f"Section {kg_entry.section} -- {kg_entry.section_title} "
                    f"(Knowledge Gaps)"
                )

        # Referenced trials
        unique_trials = self._deduplicate_trials(all_trial_names)
        if unique_trials:
            answer_parts.append(
                "Referenced Studies/Articles: " + ", ".join(unique_trials)
            )

        # Handle empty results
        if not answer_parts:
            return AssemblyResult(
                status="out_of_scope",
                answer=(
                    "The 2026 AHA/ASA AIS Guideline does not specifically address "
                    "this question. This may be covered in other guidelines, "
                    "local institutional protocols, or prescribing information."
                ),
                summary="",
                audit_trail=audit,
            )

        answer = "\n\n".join(answer_parts)
        citations_deduped = list(dict.fromkeys(citations))

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=summary,
            citations=citations_deduped,
            related_sections=sorted(s for s in sections if s),
            referenced_trials=unique_trials,
            audit_trail=audit,
        )

    # ── Evidence / Knowledge Gap response assembly ──────────────────

    async def _assemble_evidence_response(
        self,
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: SupportiveTextResult,
        kg_result: KnowledgeGapResult,
        audit: List[AuditEntry],
    ) -> AssemblyResult:
        """Assemble response for evidence/KG questions — RSS summarized, recs verbatim."""
        answer_parts: List[str] = []
        citations: List[str] = []
        sections: set = set(intent.section_refs or intent.topic_sections or [])
        all_trial_names: List[str] = []

        type_label = "Evidence" if intent.question_type == "evidence" else "Knowledge Gaps"

        # ── Evidence / KG content (may be summarized) ───────────────
        # For evidence questions, RSS IS the answer — show the top 2
        # most relevant entries (enough for the LLM summary to work with)
        evidence_parts: List[str] = []
        if intent.question_type == "evidence" and rss_result.has_content:
            for entry in rss_result.entries[:2]:
                cleaned = clean_pdf_text(entry.text)
                text = truncate_text(cleaned, max_chars=400)
                if len(text.strip()) < 40:
                    continue
                label = f"Evidence for Section {entry.section}"
                if entry.rec_number:
                    label += f", Rec {entry.rec_number}"
                evidence_parts.append(f"{label}: {text}")
                answer_parts.append(f"{label}: {text}")
                all_trial_names.extend(extract_trial_names(entry.text))
                sections.add(entry.section)

        if intent.question_type == "knowledge_gap" and kg_result.has_gaps:
            for kg_entry in kg_result.entries[:1]:
                cleaned = clean_pdf_text(kg_entry.text)
                text = truncate_text(cleaned, max_chars=300)
                answer_parts.append(
                    f"Knowledge Gaps, Section {kg_entry.section}: {text}"
                )
                sections.add(kg_entry.section)

        # Source citations
        for s in (intent.section_refs or intent.topic_sections or []):
            sd = {}
            sections_data = {}
            try:
                from ...data.loader import load_guideline_knowledge
                sections_data = load_guideline_knowledge().get("sections", {})
                sd = sections_data.get(s, {})
            except Exception:
                pass
            title = sd.get("sectionTitle", "")
            if intent.question_type == "evidence":
                citations.append(
                    f"Section {s} -- {title} (Recommendation-Specific Supportive Text)"
                )
            else:
                citations.append(f"Section {s} -- {title} (Knowledge Gaps)")

        # ── Verbatim rec for context (1 max) ──────────────────────────
        for rec in rec_result.scored_recs[:1]:
            if rec.score < REC_INCLUSION_MIN_SCORE:
                continue
            answer_parts.append(
                f"RECOMMENDATION [{rec.rec_id}]\n"
                f"Section {rec.section} — {rec.section_title}\n"
                f"Class of Recommendation: {rec.cor}  |  Level of Evidence: {rec.loe}\n\n"
                f"\"{rec.text}\""
            )
            citations.append(
                f"Section {rec.section} -- {rec.section_title} "
                f"(COR {rec.cor}, LOE {rec.loe})"
            )
            all_trial_names.extend(extract_trial_names(rec.text))
            sections.add(rec.section)

        unique_trials = self._deduplicate_trials(all_trial_names)
        if unique_trials:
            answer_parts.append(
                "Referenced Studies/Articles: " + ", ".join(unique_trials)
            )

        answer = "\n\n".join(answer_parts)
        citations_deduped = list(dict.fromkeys(citations))

        # Conversational LLM summary — grounded in the evidence/KG
        # content (not the full answer with rec blocks appended)
        summary = ""
        summary_source = "\n\n".join(evidence_parts) if evidence_parts else answer
        if self._nlp_service and summary_source.strip():
            try:
                llm_result = await self._nlp_service.summarize_qa(
                    question=intent.question,
                    details=summary_source,
                    citations=citations_deduped,
                )
                summary = llm_result.get("summary", "")
            except Exception as e:
                logger.error("LLM summary failed for evidence Q: %s", e)

        if not summary:
            summary = answer_parts[0] if answer_parts else ""

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=summary,
            citations=citations_deduped,
            related_sections=sorted(s for s in sections if s),
            referenced_trials=unique_trials,
            audit_trail=audit,
        )

    # ── Clarification helpers ───────────────────────────────────────

    def _check_clarification_rules(
        self, intent: IntentResult,
    ) -> Optional[Dict[str, Any]]:
        """Check hardcoded clarification rules (M2, IVT disabling)."""
        q_lower = intent.question.lower()

        # Skip if this is a contraindication question
        if intent.is_contraindication_question:
            return None

        for rule in CLARIFICATION_RULES:
            topic_match = any(t in q_lower for t in rule["topic_terms"])
            already_specified = any(
                kw in q_lower for kw in rule["question_keywords"]
            )
            var_in_context = (
                intent.clinical_vars.get(rule["distinguishing_var"]) is not None
            )

            # Skip if topic sections point away from this rule
            rule_sections = set(rule.get("sections", []))
            if intent.topic_sections:
                if set(intent.topic_sections) - rule_sections:
                    continue

            has_eligibility = any(ek in q_lower for ek in _ELIGIBILITY_KEYWORDS)

            if (
                topic_match
                and not already_specified
                and not var_in_context
                and has_eligibility
            ):
                return {
                    "text": rule["clarification_text"],
                    "sections": sorted(rule.get("sections", [])),
                    "options": rule["options"],
                    "rule_topic": rule["topic_terms"][0],
                }

        return None

    @staticmethod
    def _detect_vague_question(
        intent: IntentResult,
        rec_result: RecommendationResult,
        rss_result: Optional[SupportiveTextResult] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Content Breadth: measures total volume of content retrieved.

        A vague question pulls back a lot of content — many recs, many
        RSS entries, across sections or within a single dense section.
        A specific question pulls back focused content.

        Two triggers (either fires → ask clarification):

        1. CROSS-SECTION: 3+ section clusters with qualifying recs
           → "Which area are you asking about?" with section options

        2. WITHIN-SECTION: ≤2 clusters but more than 2 qualifying recs
           → "This section covers multiple scenarios" with rec options

        TOPIC_SECTION_MAP override: when the map resolved to ≤2 sections
        AND the content volume is low (≤2 recs, few clusters), trust
        the routing. But when content volume is high, the search data
        overrides the map.
        """
        # Only for recommendation questions — evidence/KG naturally span
        if intent.question_type != "recommendation":
            return None

        # Skip contraindication questions — specific pathway
        if intent.is_contraindication_question:
            return None

        # Skip if user explicitly referenced a section ("Section 4.3")
        if intent.section_refs:
            return None

        # Skip if the question has a specific intent pattern (yes/no,
        # factual, do-I-need, should-I-use, etc.). These questions
        # should be answered directly even if retrieval spans sections.
        if any(p.search(intent.question) for p in _SPECIFIC_QUESTION_PATTERNS):
            return None

        # ── Key-term specificity check ──────────────────────────────
        # If the question contains a distinctive clinical term (not
        # generic stroke vocabulary), the question IS specific — the
        # user knows what they're asking about. Don't fire vague
        # detection just because the search returned broad results.
        #
        # Examples of distinctive terms: "levetiracetam", "neuroprotective",
        # "stent", "tenecteplase", "perfusion", "troponin"
        # Examples of generic terms: "stroke", "treatment", "recommended"
        #
        # This replaces fragile regex patterns with a systematic check.
        key_terms = AssemblyAgent.extract_key_terms(intent.question)
        if key_terms:
            return None  # question has distinctive terms → answer directly

        # No results = nothing to evaluate
        if not rec_result.scored_recs:
            return None

        # ── Compute content breadth ────────────────────────────────
        rss_entries = rss_result.entries if rss_result else []
        breadth = _compute_content_breadth(
            rec_result.scored_recs, rss_entries
        )

        trigger = breadth["trigger"]

        # No trigger = content is focused → answer directly
        if not trigger:
            return None

        # TOPIC_SECTION_MAP override: when the hand-curated map
        # confidently resolved to ≤2 sections, the question contains
        # specific clinical terms that identified the right area.
        #
        # The concept-index fallback is less reliable — it matches on
        # generic word overlap, so vague questions like "stroke treatment"
        # can get spurious topic_sections. Do NOT trust concept-index
        # hits for the override.
        #
        # WITHIN-SECTION DENSITY CHECK: some sections are dense —
        # imaging (3.2), EVT (4.7.2), brain swelling (6.1/6.2) —
        # with many recs covering different modalities/scenarios.
        # A generic question like "What are the EVT recommendations?"
        # maps to the right section but is still vague WITHIN it.
        #
        # When in-topic rec density is high (≥ IN_TOPIC_REC_THRESHOLD),
        # check if the question has narrowing qualifiers (dose, target,
        # before, within X hours, specific drug, etc.). If NO qualifiers
        # → the question asks about the ENTIRE topic → let the breadth
        # trigger fire. If qualifiers present → trust the routing.
        if (
            intent.topic_sections
            and len(intent.topic_sections) <= 2
            and intent.topic_sections_source == "topic_map"
        ):
            # Count recs that fall within the topic section clusters
            topic_clusters = {
                _section_cluster(ts) for ts in intent.topic_sections
            }
            qualifying = [
                r for r in rec_result.scored_recs[:15]
                if r.score >= REC_INCLUSION_MIN_SCORE
            ]
            in_topic_count = sum(
                1 for r in qualifying
                if _section_cluster(r.section) in topic_clusters
            )

            if in_topic_count >= IN_TOPIC_REC_THRESHOLD:
                # Dense section. Only override if the question has
                # narrowing qualifiers that indicate specificity.
                q_lower = intent.question.lower()
                has_narrow = any(nq in q_lower for nq in _NARROWING_QUALIFIERS)
                if has_narrow:
                    return None  # Specific despite dense section
                # No qualifier → generic within-section question.
                # IMPORTANT: force within-section clarification for the
                # TARGET section only. Do NOT fall through to the cross-
                # section trigger — it would show noise from unrelated
                # sections found by embeddings. The topic_map told us
                # the right section; the user just needs to narrow
                # within it.
                target_sections = set(intent.topic_sections)
                target_recs = [
                    r for r in qualifying
                    if r.section in target_sections
                ]
                if target_recs:
                    return _build_within_section_clarification(
                        target_recs, intent.topic_sections[0]
                    )
                # If no in-target recs survived, fall through
            else:
                return None  # Low density → trust the routing

        cluster_data = breadth["cluster_data"]

        # ── CROSS-SECTION follow-up ────────────────────────────────
        # 3+ clusters: present section-level options
        if trigger == "cross_section":
            ranked = sorted(
                cluster_data.items(),
                key=lambda x: -x[1]["total_score"],
            )

            parts = [
                "I found a few different areas in the guidelines that "
                "address this. Which one would you like to focus on?\n"
            ]
            options: List[ClarificationOption] = []
            labels = "ABCDEFGH"

            for i, (cluster, cdata) in enumerate(ranked[:6]):
                label = labels[i]
                best_rec = cdata["best_rec"]
                section = best_rec.section
                title = best_rec.section_title
                desc = _SECTION_DESCRIPTIONS.get(section, title)

                parts.append(
                    f"- {label} — {title} (Section {section})\n"
                    f"  {desc}"
                )
                options.append(ClarificationOption(
                    label=label,
                    description=f"{title} — {desc}",
                    section=section,
                    rec_id=best_rec.rec_id,
                    cor=best_rec.cor,
                    loe=best_rec.loe,
                ))

            parts.append(
                "\nOr, if you can give me more detail — like a specific "
                "drug, time window, patient scenario, or procedure — "
                "I can go straight to the right recommendation."
            )

            return {
                "text": "\n".join(parts),
                "sections": [cd["best_rec"].section for _, cd in ranked[:6]],
                "options": options,
                "reason": (
                    f"cross_section: {breadth['n_clusters']} clusters, "
                    f"{breadth['n_qualifying_recs']} recs, "
                    f"{breadth['n_rss_entries']} RSS"
                ),
                "breadth": breadth,
            }

        # ── WITHIN-SECTION follow-up ───────────────────────────────
        # 1-2 clusters but many recs: present the individual recs
        # as options so the user can pick the right scenario.
        if trigger == "within_section":
            # Get the qualifying recs (top-scoring, above inclusion min)
            qualifying = [
                r for r in rec_result.scored_recs[:15]
                if r.score >= REC_INCLUSION_MIN_SCORE
            ]

            # Find the dominant section for the header
            top_cluster = max(
                cluster_data.items(),
                key=lambda x: x[1]["total_score"],
            )
            top_section = top_cluster[1]["best_rec"].section
            top_title = top_cluster[1]["best_rec"].section_title
            desc = _SECTION_DESCRIPTIONS.get(top_section, top_title)

            parts = [
                f"There are several recommendations in Section {top_section} "
                f"({top_title}) covering different scenarios. "
                f"Which one are you asking about?\n"
            ]
            options: List[ClarificationOption] = []
            labels = "ABCDEFGH"

            # Show up to 6 distinct recs as options
            seen_texts: set = set()
            for rec in qualifying[:8]:
                # Deduplicate by first 80 chars of text
                text_key = rec.text[:80]
                if text_key in seen_texts:
                    continue
                seen_texts.add(text_key)

                if len(options) >= 6:
                    break

                label = labels[len(options)]
                text_preview = rec.text[:150]
                if len(rec.text) > 150:
                    text_preview += "..."

                parts.append(
                    f"- {label} — Rec {rec.rec_number} "
                    f"(COR {rec.cor}, LOE {rec.loe})\n"
                    f"  {text_preview}"
                )
                options.append(ClarificationOption(
                    label=label,
                    description=f"Rec {rec.rec_number} (COR {rec.cor}, LOE {rec.loe})",
                    section=rec.section,
                    rec_id=rec.rec_id,
                    cor=rec.cor,
                    loe=rec.loe,
                ))

            parts.append(
                "\nOr just tell me the specific clinical scenario "
                "and I'll pull up the right recommendation."
            )

            return {
                "text": "\n".join(parts),
                "sections": [top_section],
                "options": options,
                "reason": (
                    f"within_section: {breadth['n_qualifying_recs']} recs "
                    f"in {breadth['n_clusters']} cluster(s), "
                    f"{breadth['n_rss_entries']} RSS"
                ),
                "breadth": breadth,
            }

        return None

    def _detect_generic_ambiguity(
        self,
        scored_recs: List[ScoredRecommendation],
        threshold: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect when top-scored recs have conflicting COR in the same section.

        This is the generic CMI-pattern clarification. Unlike the hardcoded
        rules above, this fires dynamically based on retrieval results.
        """
        if not scored_recs or scored_recs[0].score <= 0:
            return None

        top = scored_recs[0]
        close_recs = [
            r for r in scored_recs
            if r.section == top.section
            and r.score >= top.score - threshold
            and r.score > 0
        ]

        cors = set(r.cor for r in close_recs)
        if len(cors) <= 1:
            return None

        # Group best rec per COR
        by_cor: Dict[str, ScoredRecommendation] = {}
        for r in close_recs:
            if r.cor not in by_cor:
                by_cor[r.cor] = r

        parts = [
            f"Section {top.section} ({top.section_title}) has recommendations "
            f"that vary depending on the clinical scenario:\n"
        ]
        options: List[ClarificationOption] = []
        labels = "ABCDEFGH"

        for i, (cor, r) in enumerate(sorted(by_cor.items())):
            label = labels[i] if i < len(labels) else str(i + 1)
            text_preview = r.text[:200]
            parts.append(
                f"- {label} — Rec {r.rec_number} [COR {cor}, LOE {r.loe}]: "
                f"{text_preview}"
            )
            options.append(ClarificationOption(
                label=label,
                description=f"Rec {r.rec_number} (COR {cor}, LOE {r.loe})",
                section=r.section,
                rec_id=r.rec_id,
                cor=r.cor,
                loe=r.loe,
            ))

        parts.append(
            "\nCan you tell me more about the specific clinical "
            "scenario? That will help me narrow it down."
        )

        return {
            "text": "\n".join(parts),
            "section": top.section,
            "cors": sorted(cors),
            "options": options,
        }

    # ── Section-level ambiguity detection ─────────────────────────

    # Minimum score gap between top section and runner-up to be
    # considered "clear winner". Below this, we ask for clarification.
    _SECTION_AMBIGUITY_THRESHOLD = 5

    # Minimum score for the top rec to trigger section ambiguity
    # (if scores are very low, we fall through to the scope gate instead)
    _SECTION_AMBIGUITY_MIN_SCORE = 5

    @staticmethod
    def _detect_section_ambiguity(
        scored_recs: List[ScoredRecommendation],
        intent: IntentResult,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect when top recs span multiple sections with close scores.

        Unlike _detect_generic_ambiguity (conflicting COR within ONE section),
        this catches routing ambiguity ACROSS sections — when the question is
        too vague for the system to confidently pick one clinical area.

        Example: "antiepileptic drugs after stroke" matches both section 6.5
        (seizure management) and 4.8 (antiplatelet). Rather than guessing,
        ask the user which area they mean.

        Fires only when:
        1. Top recs come from 2+ different sections
        2. Score gap between top section and runner-up is small
        3. The intent agent didn't resolve to a single topic section
        4. The question doesn't already contain disambiguating terms
        """
        if not scored_recs or scored_recs[0].score < AssemblyAgent._SECTION_AMBIGUITY_MIN_SCORE:
            return None

        # Skip if intent already resolved to specific section(s)
        # — TOPIC_SECTION_MAP was confident, trust it
        if intent.section_refs:
            return None

        # Skip if TOPIC_SECTION_MAP resolved to a narrow set (1-2 sections)
        # — these are clear enough
        if intent.topic_sections and len(intent.topic_sections) <= 2:
            return None

        # Skip if the question has distinctive clinical terms — the user
        # knows what they're asking about. Multi-section scoring is a
        # retrieval artifact, not genuine ambiguity.
        key_terms = AssemblyAgent.extract_key_terms(intent.question)
        if key_terms:
            return None

        # Group top recs by section, find the best score per section
        section_best: Dict[str, ScoredRecommendation] = {}
        for rec in scored_recs[:10]:
            if rec.score < REC_INCLUSION_MIN_SCORE:
                break
            if rec.section not in section_best:
                section_best[rec.section] = rec

        # Need at least 2 competing sections
        if len(section_best) < 2:
            return None

        # Sort sections by their best score
        ranked = sorted(section_best.items(), key=lambda x: -x[1].score)
        top_section, top_rec = ranked[0]
        runner_section, runner_rec = ranked[1]

        # Only trigger if the gap is small
        gap = top_rec.score - runner_rec.score
        if gap > AssemblyAgent._SECTION_AMBIGUITY_THRESHOLD:
            return None

        # Build clarification with section-level options
        parts = [
            "This could fall under a few different sections. "
            "Which area are you interested in?\n"
        ]
        options: List[ClarificationOption] = []
        labels = "ABCDEFGH"

        for i, (section, rec) in enumerate(ranked[:4]):
            label = labels[i] if i < len(labels) else str(i + 1)
            parts.append(
                f"- {label} — Section {rec.section}: {rec.section_title} "
                f"(COR {rec.cor}, LOE {rec.loe})"
            )
            options.append(ClarificationOption(
                label=label,
                description=f"Section {rec.section} — {rec.section_title}",
                section=rec.section,
                rec_id=rec.rec_id,
                cor=rec.cor,
                loe=rec.loe,
            ))

        return {
            "text": "\n".join(parts),
            "sections": [s for s, _ in ranked[:4]],
            "options": options,
        }

    # ── Numeric alerts ──────────────────────────────────────────────

    @staticmethod
    def _add_numeric_alerts(
        intent: IntentResult,
        answer_parts: List[str],
        citations: List[str],
        sections: set,
    ) -> None:
        """Add Table 8 numeric alerts for platelet count, INR."""
        plt = intent.numeric_context.get("platelets")
        if plt is not None and plt < 100000:
            answer_parts.append(
                f"Platelet count {plt:,}/\u00b5L is below the 100,000/\u00b5L threshold. "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT. "
                "Thresholds: platelets <100,000/\u00b5L, INR >1.7, aPTT >40 s, or PT >15 s."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

        inr = intent.numeric_context.get("inr")
        if inr is not None and inr > 1.7:
            answer_parts.append(
                f"INR {inr} exceeds the 1.7 threshold. "
                "Per Table 8, severe coagulopathy is an absolute contraindication to IVT."
            )
            citations.append("Table 8 -- Absolute Contraindication: Severe coagulopathy")
            sections.add("Table 8")

    # ── Table 8 listing ──────────────────────────────────────────────

    @staticmethod
    def _is_table8_listing_question(intent: IntentResult) -> bool:
        """
        Detect whether this is a listing/enumeration question about
        contraindications (e.g., "What are the absolute contraindications?")
        vs. a question about a specific condition (e.g., "Is pregnancy
        a contraindication?").

        Listing questions should show Table 8 data directly.
        Specific-condition questions should use the tier classification path.
        """
        q_lower = intent.question.lower()

        # Listing phrases — user wants an enumeration
        _LISTING_PHRASES = [
            "what are the", "list the", "list all", "show me the",
            "what contraindication", "what are absolute",
            "what are relative", "name the",
            "tell me the contraindication", "tell me about the contraindication",
            "what does table 8", "what's in table 8",
        ]
        has_listing = any(p in q_lower for p in _LISTING_PHRASES)

        if not has_listing:
            return False

        # Check if the question also mentions a specific clinical condition
        # from Table 8. If it does, it's NOT a listing question — it's
        # asking about that specific condition.
        from .intent_agent import _TABLE8_CONDITIONS
        has_specific_condition = any(c in q_lower for c in _TABLE8_CONDITIONS)

        return not has_specific_condition

    @staticmethod
    def _format_table8_listing(intent: IntentResult) -> Optional[AssemblyResult]:
        """
        Format Table 8 contraindication data as a direct answer.

        Called for general contraindication questions like "What are
        the absolute contraindications for IVT?" — pulls data directly
        from Table8Agent.TABLE_8_RULES instead of trying to answer
        from recommendations/RSS.
        """
        from ..table8_agent import Table8Agent

        rules = Table8Agent.TABLE_8_RULES
        q_lower = intent.question.lower()

        # Determine which tier(s) the user is asking about
        wants_absolute = "absolute" in q_lower
        wants_relative = "relative" in q_lower
        wants_benefit = any(t in q_lower for t in [
            "benefit", "benefit over risk", "benefit outweigh",
        ])
        # If no specific tier requested, show all
        wants_all = not (wants_absolute or wants_relative or wants_benefit)

        parts: List[str] = []

        if wants_all or wants_absolute:
            absolute_rules = [r for r in rules if r.tier == "absolute"]
            parts.append(
                f"Absolute Contraindications ({len(absolute_rules)}):"
            )
            for r in absolute_rules:
                parts.append(f"  - {r.condition}")

        if wants_all or wants_relative:
            relative_rules = [r for r in rules if r.tier == "relative"]
            if parts:
                parts.append("")
            parts.append(
                f"Relative Contraindications ({len(relative_rules)}):"
            )
            for r in relative_rules:
                parts.append(f"  - {r.condition}")

        if wants_all or wants_benefit:
            benefit_rules = [r for r in rules if r.tier == "benefit_over_risk"]
            if parts:
                parts.append("")
            parts.append(
                f"Benefit Likely Exceeds Risk ({len(benefit_rules)}):"
            )
            for r in benefit_rules:
                parts.append(f"  - {r.condition}")

        if not parts:
            return None

        answer = "\n".join(parts)

        # Build a conversational summary
        tier_label = "absolute" if wants_absolute else (
            "relative" if wants_relative else "IVT"
        )
        total = sum(1 for _ in parts if _.startswith("  - "))
        summary = (
            f"The 2026 AHA/ASA AIS Guidelines list the contraindications "
            f"for IVT in Table 8. Here are the {tier_label} contraindications."
        )

        return AssemblyResult(
            status="complete",
            answer=answer,
            summary=summary,
            citations=["Table 8 -- IVT Contraindications and Special Situations"],
            related_sections=["Table 8", "4.6.1"],
            audit_trail=[],
        )

    # ── Summary generation ──────────────────────────────────────────

    @staticmethod
    def _generate_summary(
        scored_recs: List[ScoredRecommendation],
        intent: IntentResult,
    ) -> str:
        """
        Generate a concise, conversational summary from the top rec.

        This is the deterministic fallback when the LLM summary fails.
        It focuses on the single best recommendation and what it says,
        not on counting sections or listing metadata.
        """
        top_recs = [r for r in scored_recs[:5] if r.score >= REC_INCLUSION_MIN_SCORE]
        if not top_recs:
            return ""

        cor_strength = {
            "1": "is recommended",
            "2a": "is reasonable",
            "2b": "may be reasonable",
        }

        best = top_recs[0]
        strength = cor_strength.get(best.cor, "")
        if best.cor.startswith("3") and "Harm" in best.cor:
            strength = "is not recommended (causes harm)"
        elif best.cor.startswith("3"):
            strength = "is not recommended (no benefit)"

        # Use the actual rec text to build a meaningful summary.
        # Truncate to first sentence or 150 chars for the summary.
        rec_text = best.text or ""
        first_sentence = rec_text.split(". ")[0].rstrip(".") + "." if rec_text else ""
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:147] + "..."

        if strength and first_sentence:
            return (
                f"Per the 2026 AHA/ASA AIS Guidelines (COR {best.cor}, LOE {best.loe}), "
                f"this {strength}. {first_sentence}"
            )
        elif strength:
            return (
                f"Per the 2026 AHA/ASA AIS Guidelines (COR {best.cor}, LOE {best.loe}), "
                f"this {strength}. See the recommendation below for full details."
            )
        return (
            f"The guideline addresses this in Section {best.section} "
            f"({best.section_title}). See the recommendation below for details."
        )

    # ── Trial deduplication ─────────────────────────────────────────

    @staticmethod
    def _deduplicate_trials(trial_names: List[str]) -> List[str]:
        """Deduplicate trial names, case-insensitive."""
        seen: set = set()
        unique: List[str] = []
        for t in trial_names:
            key = t.upper().replace("-", " ").replace("  ", " ")
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    # ── Summarization guardrails ────────────────────────────────────

    @staticmethod
    def validate_summary(summary: str, source_texts: List[str]) -> List[str]:
        """
        Validate an LLM-generated summary of RSS/KG text against source.

        Checks:
            1. No invented numbers — any number in the summary must appear
               in at least one source text
            2. No invented percentages — same check for % values
            3. No invented drug names — clinical terms in summary must be
               traceable to source
            4. No blending — each sentence should be attributable to a single
               source entry (not mixing facts from multiple sources)

        Returns a list of violation descriptions. Empty list = clean.
        """
        if not summary or not source_texts:
            return []

        violations: List[str] = []
        source_combined = " ".join(source_texts).lower()

        # Check 1: Numbers in summary must appear in source
        summary_numbers = re.findall(r'\b\d+(?:\.\d+)?\b', summary)
        for num in summary_numbers:
            if num not in source_combined:
                violations.append(
                    f"Number '{num}' in summary not found in source text"
                )

        # Check 2: Percentages
        summary_pcts = re.findall(r'\d+(?:\.\d+)?%', summary)
        for pct in summary_pcts:
            if pct not in source_combined:
                violations.append(
                    f"Percentage '{pct}' in summary not found in source text"
                )

        # Check 3: Clinical threshold patterns (e.g., "≤185/110", ">1.7")
        threshold_pattern = r'[<>≤≥]\s*\d+(?:\.\d+)?(?:/\d+)?'
        summary_thresholds = re.findall(threshold_pattern, summary)
        for thresh in summary_thresholds:
            # Normalize whitespace for comparison
            normalized = thresh.replace(" ", "")
            if normalized not in source_combined.replace(" ", ""):
                violations.append(
                    f"Threshold '{thresh}' in summary not found in source text"
                )

        # Check 4: Time durations (e.g., "24 hours", "4.5 hours")
        time_pattern = r'\d+(?:\.\d+)?\s*(?:hours?|minutes?|days?|weeks?|months?)'
        summary_times = re.findall(time_pattern, summary, re.IGNORECASE)
        for t in summary_times:
            t_normalized = t.lower().strip()
            if t_normalized not in source_combined:
                # Try without space
                t_compact = re.sub(r'\s+', '', t_normalized)
                source_compact = re.sub(r'\s+', '', source_combined)
                if t_compact not in source_compact:
                    violations.append(
                        f"Time duration '{t}' in summary not found in source text"
                    )

        return violations

    @staticmethod
    def extract_key_terms(question: str) -> List[str]:
        """
        Extract distinctive key terms from a question, filtering out
        generic stroke/clinical terms. These are the terms that identify
        what the user is actually asking about.
        """
        _GENERIC_TERMS = {
            # Stroke / clinical domain
            "stroke", "ais", "ischemic", "acute", "patient", "patients",
            "treatment", "therapy", "management", "recommended",
            "guideline", "guidelines", "recommendation", "should",
            "given", "used", "safe", "beneficial", "harmful",
            "effective", "indicated", "contraindicated", "option",
            "brain", "cerebral", "vascular", "clinical",
            "hospital", "prehospital", "assessment", "evaluation",
            "reperfusion", "thrombolysis", "thrombectomy",
            # Common verbs / function words
            "give", "giving", "need", "before", "after", "within",
            "during", "what", "when", "where", "which", "does",
            "have", "make", "take", "keep", "start", "stop",
            "treat", "check", "monitor", "screen", "test",
            "hours", "minutes", "days", "time", "quickly",
            "best", "appropriate", "necessary", "required",
            "eligible", "candidate", "consider",
            # Common clinical terms that appear in many recs
            "blood", "pressure", "level", "dose", "imaging",
            "intravenous", "endovascular", "artery", "occlusion",
        }
        # Short clinical abbreviations that are distinctive despite being <4 chars.
        # These appear in guideline text and are meaningful search anchors.
        _SHORT_CLINICAL_TERMS = {
            "o2", "spo2", "bp", "sbp", "dbp", "hr", "lvo", "ica", "mca",
            "evt", "ivt", "tpa", "tnk", "cta", "ctp", "mri", "dwi", "aki",
            "ich", "sah", "dvt", "vte", "afib", "msu", "ems", "nihss",
            "dtn", "mrs", "tici", "sich", "oac", "doac", "inr",
        }
        q_lower = question.lower()
        words = re.findall(r"[a-zA-Z]{4,}", q_lower)
        key = [w for w in words if w not in _GENERIC_TERMS]
        # Also capture short clinical abbreviations present in the question
        short_words = re.findall(r"\b[a-zA-Z0-9]{2,3}\b", q_lower)
        for sw in short_words:
            if sw in _SHORT_CLINICAL_TERMS and sw not in key:
                key.append(sw)
        return key

    def check_topic_coverage(
        self,
        question: str,
        scored_recs: List[ScoredRecommendation],
        rss_result: Optional[SupportiveTextResult] = None,
        kg_result: Optional[KnowledgeGapResult] = None,
    ) -> Dict[str, Any]:
        """
        Dynamic scope gate: does the guideline actually address this topic?

        Process:
        1. Extract distinctive key terms from the question
        2. Search the retrieved results (recs, RSS, KG) for those terms
        3. If not found → search the ENTIRE guideline for the term
        4. If found elsewhere → return redirect suggestion with section info
        5. If not found anywhere → return "not in guideline"

        Returns:
            {
                "covered": True/False,
                "key_terms": [...],
                "found_elsewhere": [{"section": "X.X", "title": "...", "source": "rss|rec|kg"}],
            }
        """
        result = {"covered": True, "key_terms": [], "found_elsewhere": []}

        if not scored_recs:
            result["covered"] = False
            return result

        key_terms = self.extract_key_terms(question)
        result["key_terms"] = key_terms

        # If no distinctive key terms, the question is purely about
        # generic AIS topics — let it through
        if not key_terms:
            return result

        # ── Search retrieved results (recs, RSS, KG) ────────────
        search_corpus_parts = []

        # 1. Recommendations — check ALL recs above minimum score,
        # not just top 5, because the right rec might be scored lower
        # but still present (e.g., "rehabilitation" appears in rec #15)
        for r in scored_recs:
            if r.score >= REC_INCLUSION_MIN_SCORE:
                search_corpus_parts.append(r.text.lower())

        # 2. RSS / supportive text
        if rss_result and rss_result.entries:
            for entry in rss_result.entries:
                search_corpus_parts.append(entry.text.lower())

        # 3. Knowledge gaps
        if kg_result and kg_result.entries:
            for entry in kg_result.entries:
                search_corpus_parts.append(entry.text.lower())

        search_corpus = " ".join(search_corpus_parts)

        # Check if at least one key term appears in retrieved results
        found_in_results = any(kt in search_corpus for kt in key_terms)
        if found_in_results:
            return result  # covered = True

        # ── Not found in targeted results — search entire guideline ──
        # Search ALL guideline content: recs store + guideline_knowledge
        # (RSS, synopsis, knowledge gaps)
        result["covered"] = False
        found_sections = []
        seen_sections = set()

        # 1. Search recommendations store (separate from guideline_knowledge)
        for rec_id, rec_data in self._recommendations_store.items():
            rec_text = (rec_data.get("text", "") or "").lower()
            sec = rec_data.get("section", "")
            for kt in key_terms:
                if kt in rec_text and sec not in seen_sections:
                    seen_sections.add(sec)
                    found_sections.append({
                        "section": sec,
                        "title": rec_data.get("sectionTitle", ""),
                        "source": "recommendation",
                        "matched_term": kt,
                    })
                    break

        # 2. Search guideline_knowledge (RSS, synopsis, knowledge gaps)
        sections = self._guideline_knowledge.get("sections", {})
        for sec_num, sec_data in sections.items():
            if sec_num in seen_sections:
                continue  # already found via rec

            sec_title = sec_data.get("sectionTitle", "")
            sec_text_parts = []

            # RSS entries
            for rss_entry in sec_data.get("rss", []):
                rss_text = rss_entry.get("text", "")
                if rss_text:
                    sec_text_parts.append(rss_text.lower())

            # Synopsis
            synopsis = sec_data.get("synopsis", "")
            if synopsis:
                sec_text_parts.append(synopsis.lower())

            # Knowledge gaps
            kg_text = sec_data.get("knowledgeGaps", "")
            if kg_text:
                sec_text_parts.append(kg_text.lower())

            section_corpus = " ".join(sec_text_parts)

            for kt in key_terms:
                if kt in section_corpus:
                    # Determine which source type contained the match
                    source_type = "supportive_text"
                    for rss_entry in sec_data.get("rss", []):
                        if kt in rss_entry.get("text", "").lower():
                            break
                    else:
                        if kt in (sec_data.get("synopsis", "") or "").lower():
                            source_type = "synopsis"
                        elif kt in (sec_data.get("knowledgeGaps", "") or "").lower():
                            source_type = "knowledge_gaps"

                    seen_sections.add(sec_num)
                    found_sections.append({
                        "section": sec_num,
                        "title": sec_title,
                        "source": source_type,
                        "matched_term": kt,
                    })
                    break  # one match per section is enough

        result["found_elsewhere"] = found_sections
        return result
