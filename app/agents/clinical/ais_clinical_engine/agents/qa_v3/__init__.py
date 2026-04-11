# ─── v3 (Q&A v3 namespace) ─────────────────────────────────────────────
# This package lives under agents/qa_v3/ and is the active v3 copy of
# the Guideline Q&A pipeline. Edits made here do NOT affect agents/qa/
# which remains as the v2 baseline. To switch the live route to v3,
# update the import at services/qa_service.py or routes.py accordingly.
# ───────────────────────────────────────────────────────────────────────
"""
v3 multi-agent Q&A pipeline for AIS guideline questions.

This namespace is a file-level mirror of agents/qa/ plus the v3
deterministic quality layers (anchor vocab, family dedup, content
dispatch, scispaCy lemma bridge, anchor-count section cross-check,
clarification builders). Every module in this package carries a
``# v3 (Q&A v3 namespace)`` header comment so it is obvious from the
first line of any file which namespace a reader is in.

The v3 and v2 namespaces intentionally share the same ``references/``
folder via a filesystem symlink so a single edit to scaffolding JSON
(synonym_dictionary, data_dictionary, guideline_topic_map, intent_map,
ais_guideline_section_map) affects both namespaces simultaneously.
The source-of-truth is the real ``qa/references/`` folder; the
``qa_v3/references`` entry in this package is a symlink to it.

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
