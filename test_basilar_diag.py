"""
Diagnostic script — trace why "What are the recommendations for EVT for
basilar occlusion?" pulls noise from 4.7.4/4.7.5 and mis-orders COR within 4.7.3.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.agents.qa.intent_agent import IntentAgent
from app.agents.clinical.ais_clinical_engine.agents.qa.recommendation_agent import RecommendationAgent
from app.agents.clinical.ais_clinical_engine.agents.qa.section_index import build_section_concept_index
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)

QUESTION = "What are the recommendations for EVT for basilar occlusion?"


def build_orchestrator():
    store = EmbeddingStore()
    if store.load():
        print(f"Semantic search: enabled ({store._embeddings.shape[0]} embeddings)")
    else:
        store = None
        print("Semantic search: disabled (no embeddings file)")

    recs = load_recommendations_by_id()
    gk = load_guideline_knowledge()
    print(f"Loaded {len(recs)} recommendations")

    return QAOrchestrator(
        recommendations_store=recs,
        guideline_knowledge=gk,
        embedding_store=store,
    ), recs, gk


async def run():
    orch, recs_store, gk = build_orchestrator()

    # ── 1. Run intent agent standalone to inspect resolved fields ──
    print("\n" + "=" * 70)
    print("STEP 1: INTENT AGENT OUTPUT")
    print("=" * 70)

    all_recs = list(recs_store.values())
    section_concepts = build_section_concept_index(all_recs, gk)
    intent_agent = IntentAgent(section_concepts=section_concepts)
    intent = intent_agent.run(QUESTION)

    print(f"  question_type:          {intent.question_type}")
    print(f"  search_terms:           {intent.search_terms}")
    print(f"  section_refs:           {intent.section_refs}")
    print(f"  topic_sections:         {intent.topic_sections}")
    print(f"  topic_sections_source:  {intent.topic_sections_source}")
    print(f"  suppressed_sections:    {intent.suppressed_sections}")
    print(f"  is_general_question:    {intent.is_general_question}")
    print(f"  is_evidence_question:   {intent.is_evidence_question}")
    print(f"  clinical_vars:          {intent.clinical_vars}")
    print(f"  numeric_context:        {intent.numeric_context}")

    # ── 2. Run recommendation agent standalone to get ALL scored recs ──
    print("\n" + "=" * 70)
    print("STEP 2: RECOMMENDATION AGENT — TOP 15 SCORED RECS")
    print("=" * 70)

    rec_agent = RecommendationAgent(
        recommendations_store=recs_store,
        embedding_store=None,  # deterministic only for clarity
    )
    rec_result = rec_agent.run(intent)

    print(f"  search_method: {rec_result.search_method}")
    print(f"  total scored:  {len(rec_result.scored_recs)}")
    print()

    for i, sr in enumerate(rec_result.scored_recs[:15]):
        text_preview = sr.text[:100].replace("\n", " ")
        print(
            f"  {i+1:2d}. [{sr.rec_id}]  sec={sr.section}  "
            f"score={sr.score}  COR={sr.cor}  LOE={sr.loe}  "
            f"src={sr.source}"
        )
        print(f"      text: {text_preview}...")
        print()

    # Show which sections appear in the top 15
    sections_seen = {}
    for sr in rec_result.scored_recs[:15]:
        sec = sr.section
        if sec not in sections_seen:
            sections_seen[sec] = 0
        sections_seen[sec] += 1
    print("  Sections in top 15:")
    for sec, cnt in sorted(sections_seen.items()):
        print(f"    {sec}: {cnt} rec(s)")

    # ── 3. Run full orchestrator to get audit trail ──
    print("\n" + "=" * 70)
    print("STEP 3: FULL ORCHESTRATOR — AUDIT TRAIL")
    print("=" * 70)

    t0 = time.time()
    result = await orch.answer(QUESTION)
    elapsed = time.time() - t0

    print(f"\n  Time: {elapsed:.1f}s")
    print(f"  needsClarification: {result.get('needsClarification', False)}")

    audit = result.get("auditTrail", [])
    print(f"\n  Audit trail ({len(audit)} entries):")
    for entry in audit:
        step = entry.get("step", "?") if isinstance(entry, dict) else getattr(entry, "step", "?")
        detail = entry.get("detail", {}) if isinstance(entry, dict) else getattr(entry, "detail", {})
        detail_str = json.dumps(detail, default=str)
        # Print full detail for important steps, truncated for others
        if step in ("intent_classification", "rec_search", "scope_gate",
                     "section_resolution", "content_breadth", "topic_sections"):
            print(f"\n  [{step}]")
            # Pretty-print detail
            for k, v in (detail if isinstance(detail, dict) else {}).items():
                v_str = json.dumps(v, default=str) if not isinstance(v, str) else v
                print(f"    {k}: {v_str}")
        else:
            print(f"\n  [{step}] {detail_str[:300]}")

    # ── 4. Print the answer itself ──
    print("\n" + "=" * 70)
    print("STEP 4: FINAL ANSWER (first 1500 chars)")
    print("=" * 70)

    answer = result.get("answer", "")
    print(answer[:1500])
    if len(answer) > 1500:
        print(f"\n  ... ({len(answer)} total chars)")

    related = result.get("relatedSections", [])
    print(f"\n  relatedSections: {related}")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
