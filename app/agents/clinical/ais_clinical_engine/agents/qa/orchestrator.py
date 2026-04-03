"""
QA Orchestrator — coordinates the multi-agent Q&A pipeline.

Pipeline:
    1. IntentAgent: classify question, extract search parameters
    2. RecommendationAgent + SupportiveTextAgent + KnowledgeGapAgent:
       run all 3 in parallel (asyncio.gather)
    3. AssemblyAgent: combine results, apply scope gate, detect
       clarification, format verbatim recs + summarized RSS/KG

This replaces the monolithic answer_question() function in qa_service.py
with a modular, testable, multi-agent architecture.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from .assembly_agent import AssemblyAgent
from .intent_agent import IntentAgent
from .knowledge_gap_agent import KnowledgeGapAgent
from .recommendation_agent import RecommendationAgent
from .schemas import AssemblyResult
from .supportive_text_agent import SupportiveTextAgent

logger = logging.getLogger(__name__)


class QAOrchestrator:
    """
    Orchestrates the multi-agent Q&A pipeline.

    Usage:
        orchestrator = QAOrchestrator(
            recommendations_store=load_recommendations_by_id(),
            guideline_knowledge=load_guideline_knowledge(),
            rule_engine=rule_engine,
            nlp_service=nlp_service,
        )
        result = await orchestrator.answer(question, context)
    """

    def __init__(
        self,
        recommendations_store: Dict[str, Any],
        guideline_knowledge: Dict[str, Any],
        rule_engine=None,
        nlp_service=None,
        embedding_store=None,
    ):
        self._intent_agent = IntentAgent()
        self._rec_agent = RecommendationAgent(
            recommendations_store=recommendations_store,
            rule_engine=rule_engine,
            embedding_store=embedding_store,
        )
        self._rss_agent = SupportiveTextAgent(
            guideline_knowledge=guideline_knowledge,
        )
        self._kg_agent = KnowledgeGapAgent(
            guideline_knowledge=guideline_knowledge,
        )
        self._assembly_agent = AssemblyAgent(
            nlp_service=nlp_service,
        )

    async def answer(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Answer a clinical question about AIS management.

        This is the main entry point that replaces answer_question()
        in qa_service.py.

        Args:
            question: the user's raw question
            context: optional patient context dict

        Returns:
            dict matching the shape expected by engine.py:
            {
                "answer": str,
                "summary": str,
                "citations": [str],
                "relatedSections": [str],
                "referencedTrials": [str],
                "needsClarification": bool (optional),
                "clarificationOptions": [...] (optional),
                "auditTrail": [...] (optional),
            }
        """
        # ── Step 1: Intent classification (synchronous, deterministic) ──
        intent = self._intent_agent.run(question, context)

        logger.info(
            "QA intent: type=%s sections=%s terms=%d",
            intent.question_type,
            intent.section_refs or intent.topic_sections,
            len(intent.search_terms),
        )

        # ── Step 2: Run all 3 search agents in parallel ─────────────────
        rec_result, rss_result, kg_result = await asyncio.gather(
            asyncio.to_thread(self._rec_agent.run, intent),
            asyncio.to_thread(self._rss_agent.run, intent),
            asyncio.to_thread(self._kg_agent.run, intent),
        )

        logger.info(
            "QA retrieval: recs=%d rss=%d kg=%s method=%s",
            len(rec_result.scored_recs),
            len(rss_result.entries),
            "yes" if kg_result.has_gaps else "no",
            rec_result.search_method,
        )

        # ── Step 3: Assembly (scope gate, clarification, formatting) ────
        result = await self._assembly_agent.run(
            intent, rec_result, rss_result, kg_result
        )

        logger.info(
            "QA assembly: status=%s sections=%s",
            result.status,
            result.related_sections,
        )

        return result.to_dict()
