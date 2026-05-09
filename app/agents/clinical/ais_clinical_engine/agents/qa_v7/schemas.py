"""qa_v7 schemas.

Currently covers Step 1 output only (ParsedQuery). Downstream
schemas (RetrievedContent, AssemblyResult) will be added when
Steps 3-5 are built.

Key differences from v6 ParsedQAQuery:
  - No `topic` field used for routing.
  - No `qualifier` field used for routing. Circulation moves to
    `scenario_variables`. Subtopic narrowing happens semantically
    downstream (Step 3 router), not via a lexical qualifier.
  - No `intent` field is produced by the LLM extractor (Step 1a).
    Intent is classified by a separate embedding-based component
    (Step 1b) and merged into the ParsedQuery after extraction.
  - Explicit `scope` field — in_scope vs out_of_scope — replaces
    the v6 topic verifier's `not_ais` verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ParsedQuery:
    """Structured output of the v7 Step 1 extraction pipeline.

    Step 1a (LLM extraction) populates everything EXCEPT `intent`
    and `intent_description`. Step 1b (embedding classifier)
    populates `intent` and `intent_description`.

    When Step 1a is run standalone (as during Step 1a verification),
    `intent` is None and `intent_description` is None — this is
    expected, not an error.
    """

    # ── Populated by Step 1a (LLM extraction) ─────────────────────
    anchor_terms: Dict[str, Any] = field(default_factory=dict)
    """Lexical anchor concepts + optional values.

    Keys are canonical term strings from anchor_vocabulary.json.
    Values carry a numeric or qualifier when the question provides
    one, else None. Example: {"NIHSS": 18, "DOAC": "apixaban",
    "IVT": None}.
    """

    scenario_variables: Dict[str, Any] = field(default_factory=dict)
    """Structured clinical fields the clinician stated.

    Keys match scenario_variables.json variable names. Values are
    normalized to the canonical unit in that file (e.g. LKW in
    minutes, glucose in mg/dL). Only fields the clinician
    explicitly stated are present — missing = not stated, not
    guessed.
    """

    question_summary: str = ""
    """One-sentence canonical rephrasing of the question.

    Downstream retrieval uses this as the embedding input rather
    than the raw question, so normalization (expanding abbreviations,
    cleaning up phrasing) here improves retrieval. Do NOT include
    routing hints or topic names — just the clinical question.
    """

    scope: str = "in_scope"
    """Either "in_scope" or "out_of_scope".

    in_scope: question is about acute ischemic stroke management
    per the AIS Scope appendix.
    out_of_scope: question is about an unrelated topic (hemorrhagic
    stroke, non-stroke medicine, non-medical).
    """

    extraction_confidence: float = 1.0
    """LLM's self-assessment of how confidently it extracted the
    above fields, on a 0.0–1.0 scale. Below 0.5 indicates the LLM
    could not confidently extract and usually co-occurs with a
    populated `clarification` field.
    """

    clarification: Optional[str] = None
    """Populated ONLY when extraction was blocked (vague question,
    ambiguous, critical info missing). A one-sentence clarifying
    question for the clinician. None when extraction succeeded.
    """

    # ── Populated by Step 1b (intent classifier) ──────────────────
    intent: Optional[str] = None
    """Classified intent. One of the v7 intent enum, or "other".

    Populated by Step 1b (embedding classifier), not by the LLM
    extractor. None when Step 1a is run standalone (before Step 1b
    is wired).
    """

    intent_description: Optional[str] = None
    """Free-text description of what the clinician is trying to
    accomplish. Populated ONLY when intent == "other" (no enum
    intent matched with sufficient confidence). None otherwise.
    """

    # ── Provenance ────────────────────────────────────────────────
    raw_question: str = ""
    """The original clinician question, preserved for downstream
    auditing and for retrieval fallback when question_summary is
    empty.
    """

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_terms": self.anchor_terms,
            "scenario_variables": self.scenario_variables,
            "question_summary": self.question_summary,
            "scope": self.scope,
            "extraction_confidence": self.extraction_confidence,
            "clarification": self.clarification,
            "intent": self.intent,
            "intent_description": self.intent_description,
            "raw_question": self.raw_question,
        }
