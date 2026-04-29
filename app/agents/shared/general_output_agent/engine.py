"""
General Output Agent

Handles greetings, out-of-scope queries, scope explanations,
and any query that doesn't route to a specialized engine.
Streams tokens in real-time via broker when available.
"""

import os
from datetime import datetime, timezone
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFS_DIR = os.path.join(os.path.dirname(__file__), "references")


class GeneralOutputAgent(LLMAgent):
    """Handles greetings, scope questions, and non-technical queries."""

    def __init__(self):
        super().__init__(name="general_output_agent", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Load shared guidelines into system prompt."""
        guidelines_path = os.path.join(REFS_DIR, "shared_guidelines.md")
        if os.path.exists(guidelines_path):
            with open(guidelines_path, "r", encoding="utf-8") as f:
                guidelines = f.read()
            self.system_message = guidelines + "\n\n" + self.system_message

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        messages = []
        # Include recent conversation history for context
        for msg in session_state.get("conversation_history", [])[-4:]:
            if msg.get("role") in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        user_query = input_data.get("user_query", input_data.get("query", ""))
        messages.append({"role": "user", "content": user_query})

        if broker:
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=self.system_message,
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
            response = await self.llm_client.call(
                system_prompt=self.system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
