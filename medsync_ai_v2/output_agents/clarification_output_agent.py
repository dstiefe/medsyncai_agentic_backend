"""
Clarification Output Agent

Generates a natural-language clarification message when one or more
device names from the user's query could not be resolved in the database.
Includes fuzzy match suggestions when available.

Used for RELATIONAL intents (comparison, compatibility) where partial
results are misleading. Streams tokens in real-time via broker.
"""

from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent


CLARIFICATION_SYSTEM_PROMPT = """You are a medical device compatibility assistant. \
The user asked a question that references one or more devices you could not find \
in your device database.

Your job: Write a SHORT, helpful clarification message.

Rules:
1. Acknowledge what you DID find (if anything).
2. For each unresolved device name, explain it was not found.
3. If close-match suggestions are provided, present them naturally:
   - One suggestion: "Did you mean **[suggestion]**?"
   - Multiple suggestions: "Did you mean one of these: **[A]**, **[B]**, or **[C]**?"
4. If NO suggestions exist, ask the user to verify the full product name or check spelling.
5. Keep it conversational — one short paragraph, no bullet lists.
6. Do NOT attempt to answer the original question. Just ask for clarification.
7. Do NOT apologize excessively. Be direct and helpful.
8. Use **bold** for device names."""


class ClarificationOutputAgent(LLMAgent):
    """Generates clarification messages for unresolved device names."""

    def __init__(self):
        super().__init__(name="clarification_output_agent", skill_path=None)

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate a clarification response.

        input_data keys:
            user_query: The original user question.
            resolved_devices: Device names that WERE found.
            not_found: Device names that were NOT found.
            suggestions: Map of not_found_name -> list of close match dicts.
        """
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
                system_prompt=CLARIFICATION_SYSTEM_PROMPT,
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
                system_prompt=CLARIFICATION_SYSTEM_PROMPT,
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
