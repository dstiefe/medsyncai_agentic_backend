# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This package lives under agents/qa_v3/ and is the active v3 copy of
# the Guideline Q&A pipeline. The previous location agents/qa/ has been archived to
# agents/_archive_qa_v2/ and is no longer imported anywhere. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
v3 multi-agent Q&A pipeline for AIS guideline questions.

This namespace is a file-level mirror of the prior agents/qa/ tree plus the v3
deterministic quality layers (anchor vocab, family dedup, content
dispatch, scispaCy lemma bridge, anchor-count section cross-check,
clarification builders). Every module in this package carries a
``# v3 (Q&A v3 namespace)`` header comment so it is obvious from the
first line of any file which namespace a reader is in.

The ``references/`` folder under this package is the sole live copy
of the five scaffolding JSON files (synonym_dictionary, data_dictionary,
guideline_topic_map, intent_map, ais_guideline_section_map) plus the
two LLM prompt schemas (qa_query_parsing_schema.md,
topic_verification_schema.md). The prior agents/qa/references/ has
been moved into agents/_archive_qa_v2/references/ and is no longer
read by any live code.

Architecture (identical to v2 at the module level):

    User Question
         |
    QAQueryParsingAgent    -- LLM parser, 4-file scaffolding in prompt
         |
    TopicVerificationAgent -- LLM verifier, same 4-file scaffolding
         |
    SectionRouter          -- topic -> section (deterministic)
         |
    v3 anchor-count cross-check on the routed section
         |
    Retrieval (recs / RSS / KG via v2 retrieval agents)
         |
    v3 content_dispatch gating (skip focused agents whose output
                                 cannot reach this question_type)
         |
    Focused agents (rec_selection, rss_summary, kg_summary) with
    v3 anchor-survival pre-filters + scispaCy lemma bridge
         |
    v3 empty-survival clarification guard
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
NAMESPACE: str = "qa_v3"
