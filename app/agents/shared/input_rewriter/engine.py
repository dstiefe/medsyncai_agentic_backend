"""
Input Rewriter Agent

Normalizes user queries, preserves sentiment, resolves follow-ups.
"""

import os
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class InputRewriter(LLMAgent):
    """Normalizes user queries and resolves follow-ups."""

    def __init__(self):
        super().__init__(name="input_rewriter", skill_path=SKILL_PATH)

    async def run(self, input_data: dict, session_state: dict) -> dict:
        # Build messages with conversation history for follow-up resolution
        messages = []
        for msg in session_state.get("conversation_history", [])[-6:]:
            if msg.get("role") in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        raw_query = input_data.get("raw_query", input_data.get("query", ""))
        messages.append({"role": "user", "content": raw_query})

        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
