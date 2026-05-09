"""
Domain Classifier Agent

First routing step after input_rewriter. Classifies queries into:
  - equipment: medical device queries
  - clinical: AIS clinical guideline queries
  - other: greetings, off-topic, scope questions
"""

import os
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFS_DIR = os.path.join(os.path.dirname(__file__), "references")


class DomainClassifier(LLMAgent):
    """Classifies query domain: equipment, clinical, or other."""

    def __init__(self):
        super().__init__(name="domain_classifier", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Load domain definitions into system prompt."""
        defs_path = os.path.join(REFS_DIR, "domain_definitions.md")
        if os.path.exists(defs_path):
            with open(defs_path, "r", encoding="utf-8") as f:
                defs = f.read()
            self.system_message += "\n\n## Reference: Domain Definitions\n\n" + defs

    async def run(self, input_data: dict, session_state: dict) -> dict:
        normalized_query = input_data.get("normalized_query", "")
        print(f"  [DomainClassifier] Query: {normalized_query[:200]}")

        messages = [{"role": "user", "content": normalized_query}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        domain = content.get("domain", "other")
        confidence = content.get("confidence", 0.5)

        print(f"  [DomainClassifier] Result: domain={domain}, confidence={confidence}")

        return {
            "content": {
                "domain": domain,
                "confidence": confidence,
            },
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
