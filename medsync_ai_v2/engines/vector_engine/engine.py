"""
Vector Engine

Searches OpenAI Vector Store for IFU/510(k) document chunks relevant
to the user's query.  Uses device IDs from equipment_extraction to
build metadata filters that scope the search to the correct documents.

When no device IDs are present (e.g., knowledge_base queries), also
searches the AIS guidelines vector store if configured.

Pipeline:
  1. Build metadata filter from device IDs
  2. Semantic search via VectorStoreClient (+ AIS store if applicable)
  3. Score-threshold filtering + grouping
  4. Return structured chunks to output agent
"""

import os
import asyncio
from medsync_ai_v2.base_engine import BaseEngine
from medsync_ai_v2.shared.vector_client import VectorStoreClient
from medsync_ai_v2 import config

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")

# Chunks below this relevance score are dropped as noise
MIN_SCORE = 0.4
MAX_CHUNKS = 10


class VectorEngine(BaseEngine):
    """Engine for IFU/documentation and AIS guidelines vector search."""

    def __init__(self):
        super().__init__(name="vector_engine", skill_path=SKILL_PATH)
        self.client = VectorStoreClient()

        # AIS guidelines store (optional — only if env var is set)
        self.ais_client = None
        if config.AIS_GUIDELINES_VECTOR_STORE_ID:
            self.ais_client = VectorStoreClient(
                vector_store_id=config.AIS_GUIDELINES_VECTOR_STORE_ID
            )
            print(f"  [VectorEngine] AIS guidelines store: {config.AIS_GUIDELINES_VECTOR_STORE_ID}")

    def _extract_chunks(self, raw_results: list, source: str = "") -> list:
        """Extract and filter chunks from a raw search response."""
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
                    "source": source,
                })
        return chunks

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

        # Step 2: Semantic search (sync clients wrapped for async)
        search_tasks = []

        # Always search the IFU/device documents store
        search_tasks.append(
            asyncio.to_thread(
                self.client.search,
                query=normalized_query,
                filters=metadata_filter,
                max_results=20,
            )
        )

        # Also search AIS guidelines store when no device-specific filter
        search_ais = not variant_ids and self.ais_client is not None
        if search_ais:
            print(f"  [VectorEngine] Also searching AIS guidelines store")
            search_tasks.append(
                asyncio.to_thread(
                    self.ais_client.search,
                    query=normalized_query,
                    max_results=10,
                )
            )

        try:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        except Exception as e:
            print(f"  [VectorEngine] Search error: {e}")
            return self._build_return(
                status="error",
                result_type="vector_search",
                data={"message": f"Vector store search failed: {e}", "chunks": []},
                classification=classification,
                confidence=0.0,
            )

        # Step 3: Extract, filter by score threshold, merge results
        chunks = []

        # IFU/device docs
        ifu_response = results[0]
        if isinstance(ifu_response, Exception):
            print(f"  [VectorEngine] IFU search error: {ifu_response}")
        else:
            ifu_raw = ifu_response.get("data", [])
            chunks.extend(self._extract_chunks(ifu_raw, source="ifu"))
            print(f"  [VectorEngine] IFU store: {len(ifu_raw)} raw results")

        # AIS guidelines
        if search_ais and len(results) > 1:
            ais_response = results[1]
            if isinstance(ais_response, Exception):
                print(f"  [VectorEngine] AIS search error: {ais_response}")
            else:
                ais_raw = ais_response.get("data", [])
                chunks.extend(self._extract_chunks(ais_raw, source="ais_guidelines"))
                print(f"  [VectorEngine] AIS store: {len(ais_raw)} raw results")

        # Sort by score descending, cap at MAX_CHUNKS
        chunks.sort(key=lambda c: c["score"], reverse=True)
        chunks = chunks[:MAX_CHUNKS]

        total_raw = len(chunks)
        top_score = chunks[0]["score"] if chunks else 0
        print(f"  [VectorEngine] {total_raw} chunks after filtering (min_score={MIN_SCORE}, top={top_score:.2f})")

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
