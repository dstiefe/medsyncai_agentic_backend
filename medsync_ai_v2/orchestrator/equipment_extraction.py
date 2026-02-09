"""
Equipment Extraction - Pre-processing Agent

Extracts device names, categories, and generic specs from normalized queries.
Uses Whoosh search to resolve device names to database IDs.
"""

import json
from medsync_ai_v2.base_agent import LLMAgent
from medsync_ai_v2.shared.device_search import DeviceSearchHelper


EXTRACTION_PROMPT = """You are the EQUIPMENT EXTRACTION agent for a medical device compatibility system.

Given a user query about medical devices, extract:
1. **specified_devices**: Exact device names mentioned (e.g., "Vecta 46", "Neuron MAX", "Solitaire")
2. **device_categories**: Generic device type mentions (e.g., "microcatheter", "sheath", "stent retriever")
3. **generic_specs**: Any dimension/spec requirements mentioned (e.g., ".014 wire", ".027 catheter", "6F sheath")
4. **constraints**: Attribute filters that narrow down a category (e.g., manufacturer, material)

Rules:
- Extract device names EXACTLY as the user wrote them
- Do not invent devices not mentioned
- Separate specific device names from generic category mentions
- If a dimension is mentioned with a category (e.g., ".027 microcatheter"), capture both the category and the spec
- If a manufacturer is mentioned as a qualifier for a category (e.g., "Medtronic catheters", "Stryker stent retrievers"), extract it as a constraint
- Do NOT treat manufacturer names as device names — "Medtronic" alone is a constraint, not a device

Common manufacturers: Medtronic, Stryker, MicroVention, Penumbra, Cerenovus, Balt, Integer, Phenox, Rapid Medical, Wallaby Medical, Micrus Endovascular

Return STRICT JSON:
{
    "specified_devices": ["Device Name 1", "Device Name 2"],
    "device_categories": ["microcatheter", "sheath"],
    "generic_specs": [
        {"category": "wire", "spec": ".014", "unit": "inches", "field": "outer_diameter"}
    ],
    "constraints": [
        {"field": "manufacturer", "value": "Medtronic"}
    ]
}

Examples:
- "What Medtronic catheters can I use with an atlas stent?" →
  specified_devices: ["atlas stent"], device_categories: ["catheter"], constraints: [{"field": "manufacturer", "value": "Medtronic"}]
- "Show me Stryker stent retrievers" →
  specified_devices: [], device_categories: ["stent retriever"], constraints: [{"field": "manufacturer", "value": "Stryker"}]
- "What is the OD of the Vecta 46?" →
  specified_devices: ["Vecta 46"], device_categories: [], constraints: []"""


class EquipmentExtraction(LLMAgent):
    """Extracts device names, categories, and specs from queries."""

    def __init__(self):
        super().__init__(name="equipment_extraction", skill_path=None)
        self.system_message = EXTRACTION_PROMPT
        self.search_helper = DeviceSearchHelper()

    async def run(self, input_data: dict, session_state: dict) -> dict:
        normalized_query = input_data.get("normalized_query", "")
        print(f"  [EquipmentExtraction] Input query: {normalized_query[:200]}")

        # Step 1: LLM extraction
        messages = [{"role": "user", "content": normalized_query}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        extraction = response.get("content", {})
        specified_devices = extraction.get("specified_devices", [])
        device_categories = extraction.get("device_categories", [])
        generic_specs = extraction.get("generic_specs", [])
        constraints = extraction.get("constraints", [])

        print(f"  [EquipmentExtraction] LLM extracted devices: {specified_devices}")
        print(f"  [EquipmentExtraction] LLM extracted categories: {device_categories}")
        if "raw_text" in extraction:
            print(f"  [EquipmentExtraction] WARNING: JSON parse failed, raw: {extraction['raw_text'][:200]}")

        # Step 2: Search for specified devices in database
        devices = {}
        not_found = []

        if specified_devices:
            search_results = await self.search_helper.search_devices(specified_devices)
            found = search_results.get("found", {})
            not_found = search_results.get("not_found", [])

            print(f"  [EquipmentExtraction] Search found: {list(found.keys())}")
            print(f"  [EquipmentExtraction] Search not_found: {not_found}")

            # Package found devices
            packaged = self.search_helper.package_devices(found)
            devices = packaged.get("devices", {})

            print(f"  [EquipmentExtraction] Packaged devices: {list(devices.keys())}")
        else:
            print(f"  [EquipmentExtraction] No devices to search")

        if constraints:
            print(f"  [EquipmentExtraction] Constraints: {constraints}")

        return {
            "content": {
                "devices": devices,
                "categories": device_categories,
                "generic_specs": generic_specs,
                "constraints": constraints,
                "not_found": not_found,
            },
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
