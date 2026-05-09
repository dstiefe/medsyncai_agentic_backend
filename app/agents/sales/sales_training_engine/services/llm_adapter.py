"""
LLM adapter for the Sales Training Engine.

Wraps MedSync's shared LLMClient to match the sales engine's LLMService interface,
so all migrated services work without changing their call patterns.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator, List

from app.shared.llm_client import get_llm_client


class SalesLLMAdapter:
    """Drop-in replacement for the source LLMService, backed by MedSync's LLMClient."""

    def __init__(self):
        self._client = get_llm_client()

    async def generate(
        self,
        system_prompt: str,
        messages: List[dict],
        context: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        """Generate a text response (mirrors source LLMService.generate)."""
        full_system = f"{context}\n\n{system_prompt}" if context else system_prompt

        result = await self._client.call(
            system_prompt=full_system,
            messages=messages,
            max_tokens=max_tokens,
        )

        content = result.get("content", "")
        if isinstance(content, list):
            # Anthropic may return content blocks
            return "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return str(content)

    async def generate_stream(
        self,
        system_prompt: str,
        messages: List[dict],
        context: str = "",
    ) -> AsyncGenerator[str, None]:
        """Stream text chunks (mirrors source LLMService.generate_stream)."""
        full_system = f"{context}\n\n{system_prompt}" if context else system_prompt

        async for chunk in self._client.call_stream(
            system_prompt=full_system,
            messages=messages,
        ):
            if isinstance(chunk, dict):
                # Final usage dict — skip
                continue
            yield chunk

    async def evaluate(
        self, evaluation_prompt: str, response_to_evaluate: str
    ) -> dict:
        """Low-temperature JSON evaluation (mirrors source LLMService.evaluate)."""
        messages = [
            {
                "role": "user",
                "content": f"{evaluation_prompt}\n\nResponse to evaluate:\n{response_to_evaluate}",
            }
        ]

        result = await self._client.call_json(
            system_prompt="You are an evaluation expert. Respond with valid JSON only.",
            messages=messages,
        )

        content = result.get("content", {})
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"error": "Failed to parse evaluation response", "raw": content}
        return content


def get_llm_adapter() -> SalesLLMAdapter:
    """Get a SalesLLMAdapter instance."""
    return SalesLLMAdapter()
