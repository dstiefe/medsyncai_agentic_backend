"""
Multi-agent Q&A pipeline for AIS guideline questions.

Architecture:
    User Question
         |
    IntentAgent        -- classifies, extracts search terms, builds JSON query
         |
    +----+----+--------+
    |         |        |
  RecAgent  RSSAgent  KGAgent   -- all 3 run simultaneously
    |         |        |
    +----+----+--------+
         |
    AssemblyAgent      -- verbatim recs, scope gate, clarification,
                          summarization guardrails, audit trail
         |
    Final Response
"""

from .orchestrator import QAOrchestrator

__all__ = ["QAOrchestrator"]
