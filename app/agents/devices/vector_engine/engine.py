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
from app.base_engine import BaseEngine
from app.shared.vector_client import VectorStoreClient
from app import config

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
        intent = input_data.get("intent", {})

        # Extract primary intent type
        primary_intent = intent.get("intents", [{}])[0].get("type", "") if intent.get("intents") else ""

        print(f"  [VectorEngine] Query: {normalized_query[:150]}")
        print(f"  [VectorEngine] Intent extracted: primary_intent='{primary_intent}', has_ais_client={self.ais_client is not None}")

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

        # Detect prognosis queries (need detailed outcome data with NNT values)
        prognosis_keywords = ["outcome", "prognosis", "expected", "result", "chances", "likelihood", "functional independence", "mortality", "morbidity", "survival"]
        is_prognosis_query = primary_intent == "knowledge_base" and any(kw in normalized_query.lower() for kw in prognosis_keywords)

        # Step 2: Semantic search (sync clients wrapped for async)
        search_tasks = []
        search_ais = False
        hybrid_search_data = None

        # Intent-based store routing: For knowledge_base intents, prioritize AIS guidelines store
        if primary_intent == "knowledge_base" and self.ais_client is not None:
            print(f"  [VectorEngine] Intent=knowledge_base -> searching AIS guidelines store")

            if is_prognosis_query:
                # Hybrid retrieval for prognosis queries to ensure NNT data is retrieved
                print(f"  [VectorEngine] Prognosis query detected -> hybrid retrieval (outcomes + recommendations)")

                # Primary search: original query
                search_tasks.append(
                    asyncio.to_thread(
                        self.ais_client.search,
                        query=normalized_query,
                        max_results=10,
                    )
                )

                # Secondary search: expanded query targeting detailed trial outcomes
                outcome_query = f"{normalized_query} trial outcomes NNT functional independence DAWN DEFUSE-3 AURORA"
                search_tasks.append(
                    asyncio.to_thread(
                        self.ais_client.search,
                        query=outcome_query,
                        max_results=10,
                    )
                )
                search_ais = True
                hybrid_search_data = True  # Flag to merge results differently
            else:
                # Standard search for non-prognosis knowledge_base queries
                search_tasks.append(
                    asyncio.to_thread(
                        self.ais_client.search,
                        query=normalized_query,
                        max_results=20,
                    )
                )
                search_ais = True
        # Device-scoped search: Equipment queries search IFU/device store with filter
        elif variant_ids:
            print(f"  [VectorEngine] Device IDs present -> searching device IFU store with filter")
            search_tasks.append(
                asyncio.to_thread(
                    self.client.search,
                    query=normalized_query,
                    filters=metadata_filter,
                    max_results=20,
                )
            )
            search_ais = False
        # Fallback to AIS guidelines store when no devices
        elif self.ais_client is not None:
            print(f"  [VectorEngine] No devices -> searching AIS guidelines store")
            search_tasks.append(
                asyncio.to_thread(
                    self.ais_client.search,
                    query=normalized_query,
                    max_results=20,
                )
            )
            search_ais = True
        # Final fallback to IFU/device store
        else:
            print(f"  [VectorEngine] Fallback -> searching device IFU store")
            search_tasks.append(
                asyncio.to_thread(
                    self.client.search,
                    query=normalized_query,
                    max_results=20,
                )
            )
            search_ais = False

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

        # Extract results based on which store was searched
        if results and len(results) > 0:
            if hybrid_search_data:
                # Hybrid search: merge and deduplicate two search results
                raw_data1 = results[0].get("data", []) if not isinstance(results[0], Exception) else []
                raw_data2 = results[1].get("data", []) if len(results) > 1 and not isinstance(results[1], Exception) else []

                if isinstance(results[0], Exception) or isinstance(results[1], Exception):
                    print(f"  [VectorEngine] Hybrid search error: {results[0] if isinstance(results[0], Exception) else results[1]}")

                # Combine, deduplicate by file_id, keep highest score for each file
                # Note: Each chunk is a separate file (ais_4.7.2_discussion_1.txt, etc.)
                # so file_id deduplication correctly ensures each unique chunk appears once
                seen_files = {}
                for result in raw_data1 + raw_data2:
                    file_id = result.get("file_id", "")
                    score = result.get("score", 0)
                    if file_id not in seen_files or score > seen_files[file_id].get("score", 0):
                        seen_files[file_id] = result

                # Convert back to list, sort by score, take top 15
                merged_results = sorted(seen_files.values(), key=lambda x: x.get("score", 0), reverse=True)[:15]
                chunks.extend(self._extract_chunks(merged_results, source="ais_guidelines"))
                print(f"  [VectorEngine] Hybrid search: {len(raw_data1)} + {len(raw_data2)} results -> {len(chunks)} unique chunks after merge")
            else:
                # Standard single search
                response = results[0]
                if isinstance(response, Exception):
                    print(f"  [VectorEngine] Search error: {response}")
                else:
                    raw_data = response.get("data", [])
                    if search_ais:
                        # AIS guidelines store was searched
                        chunks.extend(self._extract_chunks(raw_data, source="ais_guidelines"))
                        print(f"  [VectorEngine] AIS store: {len(raw_data)} raw results")
                    else:
                        # IFU/device store was searched
                        chunks.extend(self._extract_chunks(raw_data, source="ifu"))
                        print(f"  [VectorEngine] IFU store: {len(raw_data)} raw results")

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
