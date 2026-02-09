"""
Vector Store Client — OpenAI Vector Stores API wrapper.

Provides semantic search over IFU/510(k) documents stored in
OpenAI's Vector Stores. Used by the VectorEngine.
"""

import os
import json
import requests


VECTOR_STORE_ID = os.getenv(
    "VECTOR_STORE_ID", "vs_691fa5db72588191bc6ad42ecfdf8489"
)


class VectorStoreClient:
    """Searches OpenAI Vector Store for relevant document chunks."""

    def __init__(self, vector_store_id: str = None):
        self.vector_store_id = vector_store_id or VECTOR_STORE_ID
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = f"https://api.openai.com/v1/vector_stores/{self.vector_store_id}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2",
        }

    def search(self, query: str, filters: dict = None, max_results: int = 20) -> dict:
        """
        Semantic search over vector store.

        Args:
            query: Search query text.
            filters: Optional metadata filter (e.g., containsany on device_variant_id).
            max_results: Maximum number of results to return.

        Returns:
            Raw OpenAI response with data[] array of scored chunks.
        """
        url = f"{self.base_url}/search"
        payload = {"query": query, "max_num_results": max_results}
        if filters:
            payload["filters"] = filters

        response = requests.post(
            url,
            headers=self.headers,
            data=json.dumps(payload),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
