# ─── v6 (Q&A v6 namespace) ─────────────────────────────────────────────
# This package is the active v6 copy of the Guideline Q&A pipeline.
#
# Architecture:
#
#     User Question
#          |
#     Step 1: QAQueryParsingAgent  — LLM classification (44 intents, anchor
#          |                         terms + values, topic)
#          |
#     Step 2a: step1_validator     — Python validation gate
#          |                         (stop_out_of_scope / stop_clarify /
#          |                          proceed / proceed_low_confidence)
#          |
#     Step 2b: TopicVerificationAgent — LLM sanity-check on topic
#          |
#     Step 3: retrieval.retrieve   — ONE unified scoring pass over every
#          |                         atom in the v5 index (semantic +
#          |                         intent + pinpoint anchors + global
#          |                         anchors + values + value-guided)
#          |
#     (CMI pass if patient scenario present)
#          |
#     Step 4: presenter.present    — LLM renders bedside-ready answer
#          |                         from retrieved atoms
#          |
#     AssemblyResult (JSON)
#
# v6 vs v4:
#   - v4 had 3 retrieval layers (content_retriever → knowledge_loader
#     dispatcher → atom_retriever) with inconsistent scoring, magic
#     numbers, duplicate query embedding, and dead code paths.
#   - v6 has ONE retrieval function scoring every atom in a single
#     pass with unified weights from scoring_config.py, then grouping
#     survivors by atom_type for presentation.
# ───────────────────────────────────────────────────────────────────────
"""v6 multi-agent Q&A pipeline for AIS guideline questions."""

from .orchestrator import QAOrchestrator, run
from .retrieval import retrieve
from .schemas import (
    AssemblyResult,
    AuditEntry,
    ClarificationOption,
    CMIMatchedRecommendation,
    ParsedQAQuery,
    RetrievedContent,
    ScoredAtom,
)
from .step1_validator import ValidationResult, validate_step1_output

__all__ = [
    "QAOrchestrator", "run",
    "retrieve",
    "AssemblyResult", "AuditEntry", "ClarificationOption",
    "CMIMatchedRecommendation", "ParsedQAQuery",
    "RetrievedContent", "ScoredAtom",
    "ValidationResult", "validate_step1_output",
]

NAMESPACE: str = "qa_v6"
