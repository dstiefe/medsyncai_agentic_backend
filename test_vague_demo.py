"""
Vague Question Demo — run 3 broad questions through QAOrchestrator
and inspect the clarification / content breadth response.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from app.agents.clinical.ais_clinical_engine.agents.qa.orchestrator import QAOrchestrator
from app.agents.clinical.ais_clinical_engine.agents.qa.embedding_store import EmbeddingStore
from app.agents.clinical.ais_clinical_engine.data.loader import (
    load_recommendations_by_id,
    load_guideline_knowledge,
)


QUESTIONS = [
    "What's the recommendation for public education programs?",
    "What imaging is required for stroke?",
    "What medications are used to treat stroke?",
]


def build_orchestrator():
    store = EmbeddingStore()
    if store.load():
        print(f"Semantic search: enabled ({store._embeddings.shape[0]} embeddings)")
    else:
        store = None
        print("Semantic search: disabled (no embeddings file)")

    return QAOrchestrator(
        recommendations_store=load_recommendations_by_id(),
        guideline_knowledge=load_guideline_knowledge(),
        embedding_store=store,
    )


async def run():
    orch = build_orchestrator()

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n{'='*70}")
        print(f"QUESTION {i}: {question}")
        print(f"{'='*70}")

        t0 = time.time()
        try:
            result = await orch.answer(question)
            elapsed = time.time() - t0
        except Exception as e:
            elapsed = time.time() - t0
            print(f"ERROR after {elapsed:.1f}s: {e}")
            continue

        needs_clar = result.get("needsClarification", False)
        answer = result.get("answer", "")
        clar_options = result.get("clarificationOptions", [])
        related_sections = result.get("relatedSections", [])

        print(f"\nTime: {elapsed:.1f}s")
        print(f"needsClarification: {needs_clar}")

        print(f"\n--- Answer ---")
        print(answer)

        if clar_options:
            print(f"\n--- Clarification Options ({len(clar_options)}) ---")
            for opt in clar_options:
                if hasattr(opt, "label"):
                    print(f"  - {opt.label}: {opt.description}")
                elif isinstance(opt, dict):
                    print(f"  - {opt.get('label')}: {opt.get('description')}")
                else:
                    print(f"  - {opt}")

        if related_sections:
            print(f"\n--- Related Sections ({len(related_sections)}) ---")
            for sec in related_sections:
                print(f"  - {sec}")

        # Content breadth from audit trail
        breadth_info = None
        for entry in result.get("auditTrail", []):
            if hasattr(entry, "step") and entry.step == "content_breadth":
                breadth_info = entry.detail or {}
                break

        if breadth_info:
            print(f"\n--- Content Breadth (from auditTrail) ---")
            for k, v in breadth_info.items():
                print(f"  {k}: {v}")
        else:
            # Try printing any audit trail entries that exist
            audit = result.get("auditTrail", [])
            if audit:
                print(f"\n--- Audit Trail ({len(audit)} entries) ---")
                for entry in audit:
                    if hasattr(entry, "step"):
                        detail_str = json.dumps(entry.detail, default=str)[:200] if entry.detail else ""
                        print(f"  [{entry.step}] {detail_str}")
                    elif isinstance(entry, dict):
                        detail_str = json.dumps(entry.get("detail", ""), default=str)[:200]
                        print(f"  [{entry.get('step', '?')}] {detail_str}")
                    else:
                        print(f"  {str(entry)[:200]}")

    print(f"\n{'='*70}")
    print("DONE")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(run())
