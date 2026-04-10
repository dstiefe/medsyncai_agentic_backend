"""
Multi-agent Q&A pipeline for AIS guideline questions.

v2 (active): deterministic, scaffolding-driven pipeline. No LLM calls.

    User Question
         │
         ▼
    parse_deterministic        ← keyword intent + topic + synonym sections
         │
         ▼
    verify_parsed_query        ← section family + required_slots contract
         │
         ▼
    route_v2                   ← review_flags guard (routable_only_when)
         │
         ▼
    decide_clarification_v2    ← deterministic slot-based clarifier
         │
         ▼
    dispatch_focused_agent     ← numeric→parsed_values | text→verbatim recs
         │
         ▼
    assemble_v2                ← pure formatter
         │
         ▼
    Final Response (byte-exact to the 2026 AIS Guidelines)

The legacy QAOrchestrator (LLM-heavy) is kept in orchestrator.py as
dead code pending Step 11 archival. New entry point is QAOrchestratorV2.
"""

from .orchestrator_v2 import QAOrchestratorV2

# Backwards-compatible alias so routes.py can import either name.
QAOrchestrator = QAOrchestratorV2

__all__ = ["QAOrchestrator", "QAOrchestratorV2"]
