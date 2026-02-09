"""
General Output Agent

Handles greetings, out-of-scope queries, scope explanations,
and any query that doesn't route to a specialized engine.
Streams tokens in real-time via broker when available.
"""

import os
import json
from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent

GUIDELINES_PATH = os.path.join(os.path.dirname(__file__), "shared_guidelines.md")

GENERAL_OUTPUT_PROMPT = """You are a medical device compatibility assistant.

{guidelines}

## What You Handle

1. **Greetings**: "Hi", "Hello", "Hey there"
   -> Respond warmly but briefly. Mention you help with medical device compatibility.

2. **Scope questions**: "What can you do?", "What devices do you know about?"
   -> Explain: You help physicians check whether neurointerventional medical devices are physically compatible (fit together) based on dimensional specifications. You can check specific device pairs, validate multi-device stacks, and discover compatible devices by category.

3. **Out-of-scope**: Questions about drug interactions, clinical protocols, pricing, non-medical topics
   -> Politely redirect: "I specialize in medical device compatibility checking based on physical specifications. For [topic], please consult [appropriate resource]."

4. **Clarification needed**: Ambiguous device references, unclear intent
   -> Ask a specific clarifying question. Don't guess.

5. **Thanks/acknowledgment**: "Thanks!", "Got it"
   -> Brief acknowledgment. Offer to help with more device questions."""


class GeneralOutputAgent(LLMAgent):
    """Handles greetings, scope questions, and non-technical queries."""

    def __init__(self):
        super().__init__(name="general_output_agent", skill_path=None)
        self.system_message = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        guidelines = ""
        if os.path.exists(GUIDELINES_PATH):
            with open(GUIDELINES_PATH, "r", encoding="utf-8") as f:
                guidelines = f.read()
        return GENERAL_OUTPUT_PROMPT.format(guidelines=guidelines)

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
            # Stream tokens in real-time via broker
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
            # Non-streaming fallback
            response = await self.llm_client.call(
                system_prompt=self.system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
