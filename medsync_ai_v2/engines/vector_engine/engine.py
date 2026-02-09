"""
Vector Engine

Searches OpenAI Vector Store for IFU/510(k) document chunks relevant
to the user's query.  Uses device IDs from equipment_extraction to
build metadata filters that scope the search to the correct documents.

Pipeline:
  1. Build metadata filter from device IDs
  2. Semantic search via VectorStoreClient
  3. Score-threshold filtering + grouping
  4. Return structured chunks to output agent
"""

import os
import asyncio
from medsync_ai_v2.base_engine import BaseEngine
from medsync_ai_v2.shared.vector_client import VectorStoreClient

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")

# Chunks below this relevance score are dropped as noise
MIN_SCORE = 0.4
MAX_CHUNKS = 10


class VectorEngine(BaseEngine):
    """Engine for IFU/documentation vector search."""

    def __init__(self):
        super().__init__(name="vector_engine", skill_path=SKILL_PATH)
        self.client = VectorStoreClient()

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Search the vector store for relevant document chunks.

        Input:
            normalized_query, devices, categories (optional),
            classification (optional)

        Returns standard engine contract via _build_return().
        """
        normalized_query = input_data.get("normalized_query", "")
        devices = input_data.get("devices", {})
        classification = input_data.get("classification", {})

        print(f"  [VectorEngine] Query: {normalized_query[:150]}")

        # Step 1: Build metadata filter from device IDs
        variant_ids = []
        for name, info in devices.items():
            ids = info.get("ids", [])
            variant_ids.extend([str(i) for i in ids])

        metadata_filter = None
        if variant_ids:
            metadata_filter = {
                "type": "containsany",
                "key": "device_variant_id",
                "value": variant_ids,
            }
            print(f"  [VectorEngine] Filtering by {len(variant_ids)} device IDs")
        else:
            print(f"  [VectorEngine] No device IDs — searching without metadata filter")

        # Step 2: Semantic search (sync client wrapped for async)
        try:
            search_response = await asyncio.to_thread(
                self.client.search,
                query=normalized_query,
                filters=metadata_filter,
                max_results=20,
            )
        except Exception as e:
            print(f"  [VectorEngine] Search error: {e}")
            return self._build_return(
                status="error",
                result_type="vector_search",
                data={"message": f"Vector store search failed: {e}", "chunks": []},
                classification=classification,
                confidence=0.0,
            )

        # Step 3: Extract, filter by score threshold, group by file
        raw_results = search_response.get("data", [])
        chunks = []

        for result in raw_results:
            score = result.get("score", 0)
            if score < MIN_SCORE:
                continue

            file_id = result.get("file_id", "")
            attributes = result.get("attributes", {})

            for item in result.get("content", []):
                if item.get("type") != "text":
                    continue
                chunks.append({
                    "text": item["text"],
                    "file_id": file_id,
                    "score": score,
                    "attributes": attributes,
                })

        # Sort by score descending, cap at MAX_CHUNKS
        chunks.sort(key=lambda c: c["score"], reverse=True)
        chunks = chunks[:MAX_CHUNKS]

        total_raw = len(raw_results)
        top_score = chunks[0]["score"] if chunks else 0
        print(f"  [VectorEngine] {total_raw} raw results → {len(chunks)} chunks after filtering (min_score={MIN_SCORE}, top={top_score:.2f})")

        # Step 4: Build return
        status = "complete" if chunks else "no_results"
        confidence = min(top_score, 0.95) if chunks else 0.1

        return self._build_return(
            status=status,
            result_type="vector_search",
            data={
                "query": normalized_query,
                "chunks": chunks,
                "device_context": {name: {"ids": info.get("ids", [])} for name, info in devices.items()},
                "chunk_count": len(chunks),
                "top_score": top_score,
            },
            classification=classification,
            confidence=confidence,
        )
