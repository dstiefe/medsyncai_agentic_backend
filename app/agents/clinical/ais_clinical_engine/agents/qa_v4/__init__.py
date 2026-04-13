# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This package lives under agents/qa_v4/ and is the active v4 copy of
# the Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 44 intents from
# intent_content_source_map.json, anchor_terms as Dict[str, Any]
# (term → value/range), values_verified, rescoped clarification. All regex
# extractors removed — LLM parser is the single extraction path.
# ───────────────────────────────────────────────────────────────────────
"""
v4 multi-agent Q&A pipeline for AIS guideline questions.

v4 pipeline steps:

Step 1 — Understand the question (LLM):
- 44 intents from intent_content_source_map.json (replaces 28 intents + question_type)
- 38 topics from guideline_topic_map.json (semantic understanding, NOT routing)
- anchor_terms as Dict[str, Any] — term → value/range or None (replaces separate clinical_variables)
- anchor_terms grounded in reference vocabulary (replaces search_keywords)
- values_verified cross-check on extracted numeric values
- Rescoped clarification: understanding-level only (off_topic, vague_with_anchor,
  vague_no_anchor, topic_ambiguity). Routing-level clarification removed.
- All regex extractors deleted — LLM parser is the single extraction path.
- Condensed anchor vocabulary from guideline_anchor_words.json in LLM context.

Step 2 — Validate Step 1 output (Python, deterministic):
- Intent in 44-item enum? Default to clinical_overview if not.
- Topic in 38-item enum? Infer from anchor terms if not.
- Anchor terms in guideline_anchor_words.json? Drop ungrounded.
- Anchor term values in original question text? Drop unverifiable values (keep terms).
- Clarification reason in 4-item enum? Null if not.
- Action: proceed | proceed_low_confidence | stop_clarify | stop_out_of_scope

Architecture:

    User Question
         |
    Step 1: QAQueryParsingAgent  -- LLM parser, 6-source scaffolding
         |
    Step 2: step1_validator      -- Python validation gate
         |                          (stop_out_of_scope → return)
         |                          (stop_clarify → return)
         |                          (proceed → continue)
         |
    Step 3: content_retriever    -- Python routing + narrowed retrieval
         |                          Level 1: topic + anchor terms → scored sections
         |                          Level 2: anchor terms + clinical values → narrowed content
         |                          Sections ranked by anchor match count
         |                          Recs/RSS scored by anchor + clinical value density
         |
    CMI override (patient scenarios → replace Step 3 recs)
         |
    Step 4: ResponsePresenter  -- 1 LLM call writes clinical summary
         |                        Python builds verbatim detail section
         |                        Summary: bullets, COR/LOE, no editorializing
         |                        Detail: exact recs, RSS, KG from guideline
         |
    Final Response
"""

from .orchestrator import QAOrchestrator
from .step1_validator import validate_step1_output, ValidationResult
from .content_retriever import retrieve_content, RetrievedContent

__all__ = [
    "QAOrchestrator",
    "validate_step1_output", "ValidationResult",
    "retrieve_content", "RetrievedContent",
]

# Namespace marker so callers can programmatically confirm which copy
# they imported. The live route is determined by qa_service.py's
# import statement, not by this constant.
NAMESPACE: str = "qa_v4"
