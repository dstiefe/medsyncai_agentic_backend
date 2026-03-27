"""
Equipment Extraction Agent

Extracts device names, categories, and generic specs from normalized queries.
Uses Whoosh search to resolve device names to database IDs.
"""

import os
from medsync_ai_v2.base_agent import LLMAgent
from medsync_ai_v2.shared.device_search import DeviceSearchHelper

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
REFS_DIR = os.path.join(os.path.dirname(__file__), "references")


def _extract_search_candidates(query: str) -> list:
    """Extract the full query + word bigrams as Whoosh search candidates."""
    words = query.strip().split()
    if not words:
        return []
    candidates = [query.strip()]
    for i in range(len(words) - 1):
        bigram = f"{words[i]} {words[i+1]}"
        if bigram.lower() != query.strip().lower():
            candidates.append(bigram)
    return candidates


class EquipmentExtraction(LLMAgent):
    """Extracts device names, categories, and specs from queries."""

    def __init__(self):
        super().__init__(name="equipment_extraction", skill_path=SKILL_PATH)
        self._load_references()
        self.search_helper = DeviceSearchHelper()

    def _load_references(self):
        """Load manufacturer list into system prompt."""
        mfr_path = os.path.join(REFS_DIR, "manufacturers.md")
        if os.path.exists(mfr_path):
            with open(mfr_path, "r", encoding="utf-8") as f:
                refs = f.read()
            self.system_message += "\n\n## Reference: Manufacturers\n\n" + refs

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
            # Whoosh fallback: LLM didn't extract any device names,
            # try the raw query and its bigrams against the device index
            print(f"  [EquipmentExtraction] No LLM devices -- trying Whoosh fallback")
            candidates = _extract_search_candidates(normalized_query)
            if candidates:
                fallback_results = await self.search_helper.search_devices(candidates)
                found = fallback_results.get("found", {})
                if found:
                    packaged = self.search_helper.package_devices(found)
                    devices = packaged.get("devices", {})
                    print(f"  [EquipmentExtraction] Whoosh fallback found: {list(devices.keys())}")
                else:
                    print(f"  [EquipmentExtraction] Whoosh fallback: no matches")

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
