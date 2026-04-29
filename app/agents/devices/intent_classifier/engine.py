"""
Intent Classifier Agent

Classifies equipment domain queries into specific intent types
for routing to the correct engine.
"""

import os
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFS_DIR = os.path.join(os.path.dirname(__file__), "references")


class IntentClassifier(LLMAgent):
    """Classifies user intent for equipment domain queries."""

    def __init__(self):
        super().__init__(name="intent_classifier", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Load intent types reference into system prompt."""
        intent_types_path = os.path.join(REFS_DIR, "intent_types.md")
        if os.path.exists(intent_types_path):
            with open(intent_types_path, "r", encoding="utf-8") as f:
                refs = f.read()
            self.system_message += "\n\n## Reference: Intent Types & Rules\n\n" + refs

    async def run(self, input_data: dict, session_state: dict) -> dict:
        normalized_query = input_data.get("normalized_query", "")
        print(f"  [IntentClassifier] Classifying: {normalized_query[:150]}")

        messages = [{"role": "user", "content": normalized_query}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        intents = content.get("intents", [])
        primary = intents[0]["type"] if intents else "general"
        print(f"  [IntentClassifier] Primary intent: {primary}, "
              f"multi={content.get('is_multi_intent', False)}, "
              f"planning={content.get('needs_planning', False)}")

        return {
            "content": content,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
