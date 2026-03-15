"""
Generic Prep Agent

Analyzes structured generic device descriptions and determines if there's
enough information to search the database. Maps device attributes to
database field names.
"""

import os
import json
from medsync_ai_v2.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFS_DIR = os.path.join(os.path.dirname(__file__), "references")


class GenericPrep(LLMAgent):
    """Determines if generic devices have enough info to search the database."""

    def __init__(self):
        super().__init__(name="generic_prep", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Load field mapping and resolution rules into system prompt."""
        for ref_file in ["field_mapping.md", "resolution_rules.md"]:
            ref_path = os.path.join(REFS_DIR, ref_file)
            if os.path.exists(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    refs = f.read()
                self.system_message += "\n\n" + refs

    async def run(self, input_data: dict, session_state: dict) -> dict:
        original_question = input_data.get("original_question", "")
        generic_devices = input_data.get("generic_devices", [])

        print(f"  [GenericPrep] Evaluating {len(generic_devices)} generic device(s)")

        if not generic_devices:
            return {
                "content": {"devices": [], "has_insufficient": False},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        user_prompt = json.dumps({
            "original_question": original_question,
            "generic_devices": generic_devices,
        })

        messages = [{"role": "user", "content": user_prompt}]

        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {"devices": []}

        devices = content.get("devices", [])
        has_insufficient = any(not d.get("has_info", False) for d in devices)

        print(f"  [GenericPrep] Results:")
        for d in devices:
            status = "SUFFICIENT" if d.get("has_info") else f"INSUFFICIENT: {d.get('reason', '?')}"
            print(f"    - {d.get('raw', '?')}: {status}")

        return {
            "content": {
                "devices": devices,
                "has_insufficient": has_insufficient,
            },
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
