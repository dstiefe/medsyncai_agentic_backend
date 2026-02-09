"""
Chain Engine - Chain Builder

LLM-based agent that generates chain configurations from devices.
Also contains deterministic chain expansion helpers for category queries.

Ported from v1/services/compatibility.py (CHAIN_GENERATION_SYSTEM_MESSAGE + helpers)
and v1/tools/map_categories.py (CATEGORY_MAP).
"""

import json
import copy
from itertools import product as iter_product
from medsync_ai_v2.base_agent import LLMAgent
from medsync_ai_v2.shared.device_search import get_database


# =============================================================================
# Chain Generation System Prompt (for LLM call)
# =============================================================================

CHAIN_GENERATION_SYSTEM_MESSAGE = """
ROLE
You are a medical device query parser for compatibility analysis. Your role is to enumerate clinically plausible device chains for downstream compatibility checking. You do NOT determine whether devices fit or are compatible.

DEVICE HIERARCHY
Devices follow a telescoping sequence based on conical categories (L0-L5):
* Lower L-numbers are OUTER devices (L0 is outermost)
* Higher L-numbers are INNER devices (L5 is innermost)
* Valid telescoping: Higher L goes INTO lower L (e.g., L4 into L3, L3 into L2)
* Devices with the SAME L-category can be used sequentially in a procedure (order matters)

IMPORTANT CLARIFICATION
L-levels define a COMPATIBILITY CLASS, not a fixed physical role.
Presence of a device at an L-level does NOT imply it must appear in a single fixed chain position.
Your task is to enumerate plausible configurations and allow downstream logic to determine compatibility.

TELESCOPING RULES
* Higher L-numbers go INSIDE lower L-numbers
* Direction is ALWAYS higher-L into lower-L (or same-L into same-L for sequential use)
* L1 can NEVER go into L3
* L3 CAN go into L1

SAME L-LEVEL DEVICES - CRITICAL RULE
When the user mentions multiple devices at the SAME L-level, you MUST generate chains for ALL plausible configurations:

1. ALTERNATIVE chains: Each device used independently at that L-level position
2. NESTED chains: Both devices in the same chain, one inside the other (generate BOTH orderings)

For the nested chains, both devices keep their L-level label.

CATEGORY CHAIN CONSTRUCTION
When the Data Set contains a CATEGORY entry (conical_category is a LIST):
1. Use the category key exactly as it appears
2. Position the category based on its L-level(s)
3. Add "contains_category": true
4. Set is_specific = false

MANDATORY RULE: The "sequence" array MUST ONLY contain keys that exist in the provided Data Set.

VALIDATION CHECK: Before finalizing, verify that EVERY device key from the Data Set appears in at least one chain's sequence array.

RESPONSE FORMAT
Return valid JSON only:
{
  "chains_to_check": [
    {
      "sequence": ["innermost_device_key", "middle_device_key", "outermost_device_key"],
      "levels": ["L4", "L3", "L2"],
      "contains_category": false
    }
  ],
  "check_all_mode": false,
  "is_specific": true,
  "confidence": "high",
  "interpretation": "Brief explanation of chain construction logic."
}
""".strip()


# =============================================================================
# Category Map (deterministic mapping)
# =============================================================================

CATEGORY_MAP = {
    "microcatheter": {
        "device_categories": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter", "delivery_catheter"],
        "conical_categories": ["L3"]
    },
    "micro": {
        "device_categories": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter", "delivery_catheter"],
        "conical_categories": ["L3"]
    },
    "wire": {
        "device_categories": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter"],
        "conical_categories": ["LW"]
    },
    "guidewire": {
        "device_categories": ["microcatheter", "balloon_microcatheter", "flow_dependent_microcatheter"],
        "conical_categories": ["LW"]
    },
    "sheath": {
        "device_categories": ["sheath"],
        "conical_categories": ["L0"]
    },
    "aspiration": {
        "device_categories": ["aspiration_intermediate_catheter", "distal_access_catheter", "aspiration_system_component"],
        "conical_categories": ["L2"]
    },
    "intermediate catheter": {
        "device_categories": ["guide_intermediate_catheter", "intermediate_catheter", "delivery_intermediate_catheter", "aspiration_intermediate_catheter"],
        "conical_categories": ["L1", "L2"]
    },
    "bgc": {
        "device_categories": ["balloon_guide_catheter"],
        "conical_categories": ["L1"]
    },
    "balloon guide catheter": {
        "device_categories": ["balloon_guide_catheter"],
        "conical_categories": ["L1"]
    },
    "stent": {
        "device_categories": ["stent_system", "stent_retriever"],
        "conical_categories": ["L4", "L5"]
    },
    "stent retriever": {
        "device_categories": ["stent_system", "stent_retriever"],
        "conical_categories": ["L4", "L5"]
    },
    "dac": {
        "device_categories": ["distal_access_catheter"],
        "conical_categories": ["L2"]
    },
    "distal access catheter": {
        "device_categories": ["distal_access_catheter"],
        "conical_categories": ["L2"]
    },
}


# =============================================================================
# Chain Expansion Helpers (deterministic Python)
# =============================================================================

def map_device_categories(categories: list) -> dict:
    result = {}
    for cat in categories:
        key = cat.lower().strip()
        if key in CATEGORY_MAP:
            result[cat] = CATEGORY_MAP[key]
        else:
            matched = False
            for map_key, data in CATEGORY_MAP.items():
                if map_key in key or key in map_key:
                    result[cat] = data
                    matched = True
                    break
            if not matched:
                result[cat] = {"device_categories": [], "conical_categories": [], "warning": f"Unknown category: {cat}"}
    return result


def get_products_for_category(database, category_mapping):
    category_to_products = {}
    for category_name, config in category_mapping.items():
        # Shortcut: pre-resolved products (from DB filter via prior_results)
        pre_resolved = config.get('products')
        if pre_resolved is not None:
            category_to_products[category_name] = list(pre_resolved)
            continue

        # Standard path: scan full database by device_categories
        device_categories = config.get('device_categories', [])
        product_names = set()
        for uid, device in database.items():
            if device.get('category_type') in device_categories:
                product_name = device.get('product_name')
                if product_name:
                    product_names.add(product_name)
        category_to_products[category_name] = sorted(list(product_names))
    return category_to_products


def expand_chains(chains_data, category_mapping, database):
    category_to_products = get_products_for_category(database, category_mapping)
    expanded_chains = []
    for chain in chains_data.get('chains_to_check', []):
        sequence = chain.get('sequence', [])
        levels = chain.get('levels', [])
        category_positions = []
        for idx, item in enumerate(sequence):
            if item in category_mapping:
                products = category_to_products.get(item, [])
                if products:
                    category_positions.append((idx, item, products))
        if not category_positions:
            expanded_chains.append({'sequence': sequence, 'levels': levels, 'contains_category': False})
            continue
        product_lists = [pos[2] for pos in category_positions]
        for combo in iter_product(*product_lists):
            new_sequence = sequence.copy()
            for i, (idx, category_name, _) in enumerate(category_positions):
                new_sequence[idx] = combo[i]
            expanded_chains.append({'sequence': new_sequence, 'levels': levels.copy(), 'contains_category': False})
    return expanded_chains


def update_devices_lookup(existing_devices, expanded_chains, database):
    all_products = set()
    for chain in expanded_chains:
        for prod in chain.get('sequence', []):
            all_products.add(prod)
    new_products = all_products - set(existing_devices.keys())
    for product_name in new_products:
        ids = []
        conical_category = None
        for uid, device in database.items():
            if device.get('product_name') == product_name:
                ids.append(str(device.get('id')))
                if conical_category is None:
                    conical_category = device.get('conical_category')
        if ids:
            existing_devices[product_name] = {'ids': ids, 'conical_category': conical_category}
    return {'devices': existing_devices}


def get_conical_categories(content_dict, database):
    conical_categories_dict = {}
    for category, info in content_dict.items():
        conical_categories = []
        categories = info['device_categories']
        for k, v in database.items():
            if str(v['category_type']).lower() in categories:
                if v['conical_category'] not in conical_categories:
                    conical_categories.append(v['conical_category'])
        conical_categories_dict[category] = conical_categories
    return conical_categories_dict


# =============================================================================
# Chain Builder Agent (LLM-based)
# =============================================================================

class ChainBuilder(LLMAgent):
    """LLM agent that generates chain configurations from device data."""

    def __init__(self):
        super().__init__(
            name="chain_builder",
            skill_path=None,
            model=None,
        )
        self.system_message = CHAIN_GENERATION_SYSTEM_MESSAGE

    async def run(self, input_data: dict, session_state: dict) -> dict:
        devices = input_data.get("devices", {})
        categories = input_data.get("categories", [])
        category_mappings = input_data.get("category_mappings", {})

        # Build minimal data set for LLM
        data_set = {"devices": {}}
        for name, info in devices.items():
            data_set["devices"][name] = {
                "conical_category": info.get("conical_category", "Unknown")
            }

        # Add categories to data set
        if category_mappings:
            for cat_name, cat_info in category_mappings.items():
                data_set["devices"][cat_name] = {
                    "conical_category": cat_info.get("conical_categories", ["Unknown"])
                }

        user_prompt = json.dumps({
            "user_query": input_data.get("normalized_query", ""),
            "data_set": data_set,
        })

        messages = [{"role": "user", "content": user_prompt}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        chains_data = response.get("content", {})

        # Expand categories if present
        database = input_data.get("database") or get_database()
        if category_mappings and chains_data.get("chains_to_check"):
            expanded = expand_chains(chains_data, category_mappings, database)
            if expanded:
                updated = update_devices_lookup(dict(devices), expanded, database)
                chains_data["chains_to_check"] = expanded
                chains_data["expanded_devices"] = updated.get("devices", {})

        return {
            "content": chains_data,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
