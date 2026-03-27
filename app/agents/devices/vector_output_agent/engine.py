"""
Vector Output Agent

Formats vector engine results (IFU/510(k) document chunks) into user-facing
responses.  Streams tokens in real-time via broker.

Ported from vs2/agents/vector_search_agents.py (VectorStoreFormatter).
"""

import os
import json
from datetime import datetime, timezone
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")

NO_RESULTS_MESSAGE = "No relevant information was found in the available documentation for this query."


class VectorOutputAgent(LLMAgent):
    """Formats vector search chunks into user-facing responses with source attribution."""

    def __init__(self):
        super().__init__(name="vector_output_agent", skill_path=SKILL_PATH)
        self._references_loaded = False
        self._load_references()

    def _load_references(self):
        """Load reference files and append to system message."""
        refs_dir = os.path.join(os.path.dirname(__file__), "references")
        prognosis_path = os.path.join(refs_dir, "prognosis_rules.md")
        if os.path.exists(prognosis_path):
            with open(prognosis_path, "r", encoding="utf-8") as f:
                prognosis_content = f.read()
            self.system_message = self.system_message + "\n\n" + prognosis_content
        self._references_loaded = True

    def _build_user_prompt(self, input_data: dict) -> str:
        """Build the user prompt from vector engine results."""
        user_query = input_data.get("user_query", "")
        data = input_data.get("data", {})
        chunks = data.get("chunks", [])
        device_context = data.get("device_context", {})

        if not chunks:
            return f"User Question: {user_query}\n\nNo document chunks were found. Respond with: \"{NO_RESULTS_MESSAGE}\""

        # Format chunks for the LLM
        chunk_texts = []
        for i, chunk in enumerate(chunks, 1):
            score = chunk.get("score", 0)
            attrs = chunk.get("attributes", {})
            file_id = chunk.get("file_id", "unknown")
            text = chunk.get("text", "")

            attr_str = ""
            if attrs:
                attr_parts = [f"{k}: {v}" for k, v in attrs.items() if v]
                if attr_parts:
                    attr_str = f" | Attributes: {', '.join(attr_parts)}"

            chunk_texts.append(
                f"[Chunk {i}] (score: {score:.2f}, file: {file_id}{attr_str})\n{text}"
            )

        chunks_formatted = "\n\n---\n\n".join(chunk_texts)

        device_str = ""
        if device_context:
            device_names = list(device_context.keys())
            device_str = f"\nDevices referenced: {', '.join(device_names)}"

        return f"""User Question: {user_query}
{device_str}

Document Data ({len(chunks)} chunks):

{chunks_formatted}

Answer the user's question using ONLY the document data above."""

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the vector output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        data = input_data.get("data", {})
        chunks = data.get("chunks", [])

        # No-results fast path
        if not chunks:
            print(f"  [VectorOutputAgent] No chunks — returning no-results message")
            if broker:
                await broker.put({
                    "type": "final_chunk",
                    "data": {
                        "agent": self.name,
                        "content": NO_RESULTS_MESSAGE,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })
            return {
                "content": {"formatted_response": NO_RESULTS_MESSAGE},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        system_message = self.system_message
        user_prompt = self._build_user_prompt(input_data)
        messages = [{"role": "user", "content": user_prompt}]

        print(f"  [VectorOutputAgent] Formatting {len(chunks)} chunks (top score: {data.get('top_score', 0):.2f})")

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            ):
                if isinstance(chunk, dict):
                    usage = chunk
                else:
                    final_text += chunk
                    await broker.put({
                        "type": "final_chunk",
                        "data": {
                            "agent": self.name,
                            "content": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

            return {
                "content": {"formatted_response": final_text},
                "usage": usage,
            }
        else:
            # Non-streaming fallback
            response = await self.llm_client.call(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
