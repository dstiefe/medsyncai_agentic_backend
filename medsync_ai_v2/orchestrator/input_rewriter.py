"""
Input Rewriter - Pre-processing Agent

Normalizes user queries, preserves sentiment, resolves follow-ups.
Ported from vs2/prompts/input_rewriter_prompt.txt.
"""

import json
from medsync_ai_v2.base_agent import LLMAgent


INPUT_REWRITER_PROMPT = """You are the INPUT REWRITER for a medical device compatibility system.

Rules:
- DO NOT invent any new information.
- DO NOT add nouns or device types not present.
- DO NOT hallucinate (e.g., "cat 5 cable" is forbidden).
- DO NOT reinterpret alphanumeric shorthand (e.g., "cat 5", "c5", "p7", "r71") as non-medical objects.
- Only resolve pronouns if clearly supported by recent conversation messages.
- If rewrite is unnecessary, return the input unchanged.
- Identify any explicit source mentions from the user's message (e.g., "IFU", "510k", "company website").
- DO NOT infer or guess sources — only include those explicitly named by the user.

For follow-up queries, use conversation history to:
- Resolve "what about X instead of Y" (substitution)
- Resolve "what if I add X" (addition)
- Resolve "without X" (removal)
- Resolve spec follow-ups to previous device context
- Resolve category swaps while carrying forward device context
- If completely new topic, don't carry forward previous context

Return STRICT JSON:
{
  "rewritten_user_prompt": "<string>",
  "source_filter": ["<string>", ...]
}"""


class InputRewriter(LLMAgent):
    """Normalizes user queries and resolves follow-ups."""

    def __init__(self):
        super().__init__(name="input_rewriter", skill_path=None)
        self.system_message = INPUT_REWRITER_PROMPT

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
