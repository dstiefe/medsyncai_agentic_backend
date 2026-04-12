# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# This package lives under agents/qa_v4/ and is the active v4 copy of
# the Guideline Q&A pipeline. The previous location agents/qa_v3/ has been
# archived to agents/_archive_qa_v3/ and is no longer imported anywhere.
# v4 changes: unified Step 1 pipeline — 38 intents from
# intent_content_source_map.json, flexible clinical_variables dict,
# anchor_terms, values_verified, rescoped clarification. All regex
# extractors removed — LLM parser is the single extraction path.
# ───────────────────────────────────────────────────────────────────────
"""
v4 multi-agent Q&A pipeline for AIS guideline questions.

v4 Step 1 changes (question understanding):
- 38 intents from intent_content_source_map.json (replaces 28 intents + question_type)
- 38 topics from guideline_topic_map.json (semantic understanding, NOT routing)
- Flexible clinical_variables dict (replaces 14 fixed fields)
- anchor_terms grounded in reference vocabulary (replaces search_keywords)
- values_verified cross-check on extracted numeric values
- Rescoped clarification: understanding-level only (off_topic, vague_with_anchor,
  vague_no_anchor, topic_ambiguity). Routing-level clarification removed.
- All regex extractors deleted — LLM parser is the single extraction path.
- Condensed anchor vocabulary from guideline_anchor_words.json in LLM context.

Architecture:

    User Question
         |
    QAQueryParsingAgent    -- LLM parser, 6-source scaffolding in prompt
         |                    (synonym dict, data dict, topic map, intent map,
         |                     intent content source map, anchor vocabulary)
         |
    TopicVerificationAgent -- LLM verifier (unchanged from v3)
         |
    SectionRouter          -- topic -> section (deterministic, unchanged)
         |
    Retrieval (recs / RSS / KG)
         |
    content_dispatch gating (skip focused agents whose output
                              is not needed for this intent's sources)
         |
    Focused agents (rec_selection, rss_summary, kg_summary)
         |
    QAAssemblyAgent / AssemblyAgent  -- verbatim answer formatting
         |
    Final Response
"""

from .orchestrator import QAOrchestrator

__all__ = ["QAOrchestrator"]

# Namespace marker so callers can programmatically confirm which copy
# they imported. The live route is determined by qa_service.py's
# import statement, not by this constant.
NAMESPACE: str = "qa_v4"
