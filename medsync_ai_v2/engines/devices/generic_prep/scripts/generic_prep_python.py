"""
Generic Prep Python Agent

Pure Python agent (no LLM) that creates synthetic database records from
the GenericPrep agent's search_criteria output. Injects these records into
the in-memory DATABASE so the chain engine can evaluate compatibility.

Ported from vs2/agents/equipment_chain_agents.py GenericPrepPythonAgent.
"""

import json
from medsync_ai_v2.base_agent import BaseAgent
from medsync_ai_v2.shared.device_search import get_database


# All standard fields a DATABASE record can have
STANDARD_FIELDS = [
    "id",
    "manufacturer",
    "device_name",
    "category_type",
    "conical_category",
    "fit_logic",
    "logic_category",
    "specification_inner-diameter_in",
    "specification_inner-diameter_mm",
    "specification_inner-diameter_F",
    "specification_outer-diameter-distal_in",
    "specification_outer-diameter-distal_mm",
    "specification_outer-diameter-distal_F",
    "specification_outer-diameter-proximal_in",
    "specification_outer-diameter-proximal_mm",
    "specification_outer-diameter-proximal_F",
    "specification_length_cm",
    "compatibility_wire_max_outer-diameter_in",
    "compatibility_wire_max_outer-diameter_mm",
    "compatibility_wire_max_outer-diameter_F",
    "compatibility_catheter_max_outer-diameter_in",
    "compatibility_catheter_max_outer-diameter_mm",
    "compatibility_catheter_max_outer-diameter_F",
    "compatibility_catheter_req_inner-diameter_in",
    "compatibility_catheter_req_inner-diameter_mm",
    "compatibility_catheter_req_inner-diameter_F",
    "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_in",
    "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_mm",
    "compatibility_guide_or_catheter_or_sheath_min_inner-diameter_F",
    "product_name",
    "file_path_source_has_doc",
    "Specifications_Pic_has_pic",
    "file_path_source_FDA_has_doc",
]


class GenericPrepPython(BaseAgent):
    """Creates synthetic DATABASE records for generic devices and injects them."""

    def __init__(self):
        super().__init__(name="generic_prep_python", skill_path=None)

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Input:
            input_data: {
                "devices": [GenericPrep devices with has_info=True and search_criteria],
                "uid": str,
                "session_id": str
            }
        Returns:
            {
                "content": {
                    "synthetic_devices": dict  (id -> device record for chain engine),
                    "injected_count": int
                },
                "usage": {"input_tokens": 0, "output_tokens": 0}
            }
        """
        devices = input_data.get("devices", [])
        uid = input_data.get("uid", "0000")
        session_id = input_data.get("session_id", "0000")

        print(f"  [GenericPrepPython] Processing {len(devices)} device(s)")

        database = input_data.get("database")
        if database is None:
            database = get_database()
        synthetic_devices = {}

        for device in devices:
            if not device.get("has_info", False):
                continue

            search_criteria = dict(device.get("search_criteria", {}))

            # Fill in all standard fields with defaults
            for field in STANDARD_FIELDS:
                if field not in search_criteria:
                    if field == "id":
                        search_criteria[field] = uid[:4] + session_id[:4]
                    elif field == "product_name":
                        search_criteria[field] = device.get("device_type", "")
                    elif field == "device_name":
                        search_criteria[field] = device.get("raw", "")
                    elif field == "file_path_source_has_doc":
                        search_criteria[field] = False
                    elif field == "Specifications_Pic_has_pic":
                        search_criteria[field] = False
                    elif field == "file_path_source_FDA_has_doc":
                        search_criteria[field] = False
                    elif field == "fit_logic":
                        search_criteria[field] = "math"
                    elif field == "logic_category":
                        search_criteria[field] = device.get("device_type", "")
                    else:
                        search_criteria[field] = ""

            record_id = search_criteria["id"]
            database[record_id] = search_criteria
            synthetic_devices[record_id] = search_criteria

            print(f"  [GenericPrepPython] Injected synthetic record: id={record_id}, "
                  f"device={search_criteria.get('device_name', '?')}")

        return {
            "content": {
                "synthetic_devices": synthetic_devices,
                "injected_count": len(synthetic_devices),
            },
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
