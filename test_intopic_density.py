"""
Diagnostic: for each test case, show the in-topic rec count
(recs in the topic_sections clusters) vs total qualifying recs.

This helps find the right threshold for within-section vagueness detection.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)
from app.agents.clinical.ais_clinical_engine.agents.qa.intent_agent import IntentAgent
from app.agents.clinical.ais_clinical_engine.agents.qa.recommendation_agent import RecommendationAgent
from app.agents.clinical.ais_clinical_engine.agents.qa.assembly_agent import (
    _section_cluster,
    REC_INCLUSION_MIN_SCORE,
)
from app.agents.clinical.ais_clinical_engine.agents.qa.section_index import build_section_concept_index

from test_qa_breadth_calibration import TEST_CASES


async def main():
    recs_store = load_recommendations_by_id()
    knowledge = load_guideline_knowledge()

    store = EmbeddingStore()
    if not store.load():
        store = None

    # Build section concepts for IntentAgent
    all_recs = list(recs_store.values())
    section_concepts = build_section_concept_index(all_recs, knowledge)
    intent_agent = IntentAgent(section_concepts=section_concepts)
    rec_agent = RecommendationAgent(
        recommendations_store=recs_store,
        embedding_store=store,
    )

    print(f"{'ID':<6} {'Exp':<8} {'TopicSrc':<14} {'TopicSec':<20} "
          f"{'InTopic':>8} {'Total':>6} {'Clusters':>8}  Question")
    print("-" * 120)

    for tc in TEST_CASES:
        intent = intent_agent.run(tc["question"])
        rec_result = rec_agent.run(intent)

        # Count qualifying recs
        qualifying = [
            r for r in rec_result.scored_recs[:15]
            if r.score >= REC_INCLUSION_MIN_SCORE
        ]

        # Count in-topic recs (recs in the topic_sections clusters)
        topic_clusters = set()
        for ts in (intent.topic_sections or []):
            topic_clusters.add(_section_cluster(ts))

        in_topic = 0
        if topic_clusters:
            in_topic = sum(
                1 for r in qualifying
                if _section_cluster(r.section) in topic_clusters
            )

        # Count distinct clusters among qualifying
        clusters = set(_section_cluster(r.section) for r in qualifying)

        topic_str = ",".join(intent.topic_sections[:3]) if intent.topic_sections else "-"
        src = intent.topic_sections_source or "-"

        print(
            f"{tc['id']:<6} {tc['expect']:<8} {src:<14} {topic_str:<20} "
            f"{in_topic:>8} {len(qualifying):>6} {len(clusters):>8}  "
            f"{tc['question'][:60]}"
        )


if __name__ == "__main__":
    asyncio.run(main())
