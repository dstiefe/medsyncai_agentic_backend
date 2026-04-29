"""
Clarification Output Agent

Generates a natural-language clarification message when one or more
device names from the user's query could not be resolved in the database.
Includes fuzzy match suggestions when available.
"""

import os
from datetime import datetime, timezone
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class ClarificationOutputAgent(LLMAgent):
    """Generates clarification messages for unresolved device names."""

    def __init__(self):
        super().__init__(name="clarification_output_agent", skill_path=SKILL_PATH)

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        user_query = input_data.get("user_query", "")
        resolved = input_data.get("resolved_devices", [])
        not_found = input_data.get("not_found", [])
        suggestions = input_data.get("suggestions", {})

        user_prompt = self._build_user_prompt(user_query, resolved, not_found, suggestions)
        messages = [{"role": "user", "content": user_prompt}]

        print(f"  [ClarificationOutputAgent] not_found={not_found}, resolved={resolved}")

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

    def _build_user_prompt(self, user_query, resolved, not_found, suggestions):
        parts = [f"User's original question: {user_query}"]

        if resolved:
            parts.append(f"Devices found in database: {', '.join(resolved)}")
        else:
            parts.append("Devices found in database: none")

        parts.append(f"Devices NOT found: {', '.join(not_found)}")

        if suggestions:
            suggestion_lines = []
            for name, matches in suggestions.items():
                if matches:
                    match_strs = [m["product_name"] for m in matches[:3]]
                    suggestion_lines.append(f"  '{name}' -> possible matches: {', '.join(match_strs)}")
                else:
                    suggestion_lines.append(f"  '{name}' -> no close matches found")
            parts.append("Close match suggestions:\n" + "\n".join(suggestion_lines))
        else:
            parts.append("Close match suggestions: none available")

        parts.append("Generate a clarification message.")
        return "\n\n".join(parts)
