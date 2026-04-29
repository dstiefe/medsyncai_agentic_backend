"""
Query Planner Agent

Lightweight LLM agent that generates multi-engine execution plans.
Only invoked when equipment_extraction detects constraints (manufacturer, etc.)
that require coordinating multiple engines (e.g., database filter → chain compat).

For simple queries without constraints, the orchestrator uses direct routing
and this agent is never called.
"""

import os
import json
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFERENCES_DIR = os.path.join(os.path.dirname(__file__), "references")


class QueryPlanner(LLMAgent):
    """Lightweight planner that generates multi-engine execution plans."""

    def __init__(self):
        super().__init__(name="query_planner", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Append reference files (engines.md, strategies.md) to system_message."""
        for ref_name in ("engines.md", "strategies.md"):
            ref_path = os.path.join(REFERENCES_DIR, ref_name)
            if os.path.exists(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    self.system_message += "\n\n" + f.read()

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Generate an execution plan based on extraction output.

        Input:
            normalized_query, devices, categories, constraints, generic_specs

        Returns:
            {"content": <plan dict>, "usage": {...}}
        """
        normalized_query = input_data.get("normalized_query", "")
        devices = input_data.get("devices", {})
        categories = input_data.get("categories", [])
        constraints = input_data.get("constraints", [])

        # Build context for the planner
        device_info = []
        for name, info in devices.items():
            device_info.append(f'  "{name}": conical_category={info.get("conical_category", "?")}')

        user_prompt = f"""User Question: {normalized_query}

Devices found: {', '.join(devices.keys()) if devices else 'none'}
{chr(10).join(device_info) if device_info else ''}
Categories mentioned: {', '.join(categories) if categories else 'none'}
Constraints: {json.dumps(constraints)}

Generate an execution plan. Respond with ONLY valid JSON."""

        print(f"  [QueryPlanner] Planning for: {normalized_query[:150]}")
        print(f"  [QueryPlanner] Constraints: {constraints}")

        messages = [{"role": "user", "content": user_prompt}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        plan = response.get("content", {})
        strategy = plan.get("strategy", "unknown")
        steps = plan.get("steps", [])
        print(f"  [QueryPlanner] Strategy: {strategy}, {len(steps)} steps")

        return {
            "content": plan,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
