"""
Generic Device Structuring Agent

Structures raw generic device fragments into proper device objects.
The EquipmentExtractionAgent often splits one device into multiple fragments:
    ["100cm wire", "0.014\" wire"] -> should be 1 wire with OD + length

This agent uses the ORIGINAL user question to correctly merge fragments
and produce structured output that GenericPrepAgent expects.

Ported from vs2/agents/equipment_chain_agents.py GenericDeviceStructuringAgent.
"""

import json
from medsync_ai_v2.base_agent import LLMAgent


GENERIC_DEVICE_STRUCTURING_SYSTEM_MESSAGE = """
# Generic Device Structuring Agent

You are parsing generic (unbranded) medical device descriptions from a user's question.

## The Problem

A previous agent extracted generic device references from the user's question, but it often makes mistakes:
- Splits ONE device into multiple fragments (e.g., "100cm wire" and "0.014\" wire" are the SAME wire)
- Misses specs that belong together
- Doesn't structure the attributes properly

## Your Job

Use the **original user question** as the source of truth to:
1. Identify how many DISTINCT generic devices the user mentioned
2. Merge fragments that refer to the same device
3. Extract structured attributes for each device

## Device Types

| Device Type | Common Terms |
|-------------|-------------|
| `wire` | wire, guidewire, microwire |
| `catheter` | catheter, microcatheter, aspiration catheter, guide catheter, intermediate catheter |
| `sheath` | sheath, introducer sheath, access sheath |
| `stent` | stent, stent retriever |
| `balloon` | balloon, balloon catheter, balloon guide catheter |

If you cannot determine the device type, set it to `null`.

## Attributes to Extract

| Attribute | Key | Description | Example Values |
|-----------|-----|-------------|----------------|
| Outer Diameter | `OD` | Outer diameter | 0.014", 0.017", 5Fr, 6mm |
| Inner Diameter | `ID` | Inner diameter | 0.021", 0.068", 6Fr |
| Length | `length` | Working/usable length | 100cm, 150cm, 200cm, 1500mm |
| Size | `size` | Generic size (French, mm) when OD/ID is unclear | 5Fr, 6Fr, 4mm |

Each attribute has a `value` (number) and `unit` (string).

## Units

| Unit | Format |
|------|--------|
| Inches | `"in"` — values like 0.014, 0.017, 0.021, 0.068, 0.074 |
| French | `"Fr"` — values like 4, 5, 6, 7, 8, 9 |
| Millimeters | `"mm"` — values like 2, 3, 4, 5, 6 |
| Centimeters | `"cm"` — values like 100, 115, 125, 132, 150, 200 |

## How to Determine OD vs ID vs Size

### Wires
- Decimal inches (0.014", 0.017", 0.018") → **always OD**
- Wires don't have an ID

### Catheters
- If user says "ID" or "inner diameter" → `ID`
- If user says "OD" or "outer diameter" → `OD`
- French size without specifying OD/ID → `size` (let downstream agent figure it out)
- Small decimals like .021", .027" on microcatheters → likely `ID`
- Larger decimals like .068", .074", .088" on guide/intermediate catheters → likely `ID`
- If ambiguous, use `size`

### Sheaths
- French size is typically **OD** for sheaths
- If user says "ID" → `ID`

### Stents / Balloons
- mm values (4mm, 6mm) → typically `OD` (deployed diameter)
- Length in mm (20mm, 30mm) → `length`

## CRITICAL RULES

1. Use the ORIGINAL question to determine how many devices and which specs belong together
2. Do NOT trust the raw fragments list - it may have split one device into many
3. A single device can have MULTIPLE specs: "100cm .014" wire" = 1 wire with OD + length
4. "a .014 wire and a 6F catheter" = 2 separate devices
5. Extract values as numbers, not strings (0.014 not "0.014")
6. Do NOT invent specs that aren't in the user's question

## Output Format

Respond ONLY with valid JSON:

```json
{
  "generic_devices": [
    {
      "raw": "<combined description from user's question>",
      "device_type": "<wire|catheter|sheath|stent|balloon|null>",
      "attributes": {
        "OD": {"value": <number>, "unit": "<in|mm|Fr>"},
        "ID": {"value": <number>, "unit": "<in|mm|Fr>"},
        "length": {"value": <number>, "unit": "<cm|mm>"},
        "size": {"value": <number>, "unit": "<Fr|mm>"}
      }
    }
  ]
}
```

Only include attributes that are actually mentioned. Empty attributes = `{}`.

## Examples

### Example 1: Two fragments that are ONE device
**Question:** "will a 100cm wire that is .014" work with a trak 21"
**Fragments:** ["100cm wire", "0.014\\" wire"]
```json
{
  "generic_devices": [
    {
      "raw": "100cm .014\\" wire",
      "device_type": "wire",
      "attributes": {
        "OD": {"value": 0.014, "unit": "in"},
        "length": {"value": 100, "unit": "cm"}
      }
    }
  ]
}
```

### Example 2: Two separate devices
**Question:** "can I use a .014 wire and a 6Fr sheath with Neuron Max"
**Fragments:** [".014 wire", "6Fr sheath"]
```json
{
  "generic_devices": [
    {
      "raw": ".014\\" wire",
      "device_type": "wire",
      "attributes": {
        "OD": {"value": 0.014, "unit": "in"}
      }
    },
    {
      "raw": "6Fr sheath",
      "device_type": "sheath",
      "attributes": {
        "size": {"value": 6, "unit": "Fr"}
      }
    }
  ]
}
```

### Example 3: One device with many specs
**Question:** "will a 5Fr 150cm catheter with .058\\" ID fit into the Neuron Max"
**Fragments:** ["5Fr catheter", "150cm catheter", ".058\\" ID catheter"]
```json
{
  "generic_devices": [
    {
      "raw": "5Fr 150cm .058\\" ID catheter",
      "device_type": "catheter",
      "attributes": {
        "OD": {"value": 5, "unit": "Fr"},
        "ID": {"value": 0.058, "unit": "in"},
        "length": {"value": 150, "unit": "cm"}
      }
    }
  ]
}
```

### Example 4: No attributes at all
**Question:** "can I use a microcatheter with the Neuron Max?"
**Fragments:** ["microcatheter"]
```json
{
  "generic_devices": [
    {
      "raw": "microcatheter",
      "device_type": "catheter",
      "attributes": {}
    }
  ]
}
```
"""

GENERIC_DEVICE_STRUCTURING_USER_PROMPT = """Original user question: "{original_question}"

Raw generic device fragments extracted by previous agent: {raw_fragments}

Using the original question as the source of truth, parse these fragments into distinct generic devices with their correct attributes."""


class GenericDeviceStructuring(LLMAgent):
    """Structures raw generic device fragments into proper device objects."""

    def __init__(self):
        super().__init__(name="generic_device_structuring", skill_path=None)
        self.system_message = GENERIC_DEVICE_STRUCTURING_SYSTEM_MESSAGE

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Input:
            input_data: {"original_question": str, "generic_specs": list}
        Returns:
            {"content": {"generic_devices": [...]}, "usage": {...}}
        """
        original_question = input_data.get("original_question", "")
        raw_fragments = input_data.get("generic_specs", [])

        print(f"  [GenericDeviceStructuring] Original question: {original_question[:150]}")
        print(f"  [GenericDeviceStructuring] Raw fragments: {raw_fragments}")

        if not raw_fragments:
            print("  [GenericDeviceStructuring] No generic devices to structure, skipping")
            return {
                "content": {"generic_devices": []},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        user_prompt = GENERIC_DEVICE_STRUCTURING_USER_PROMPT.format(
            original_question=original_question,
            raw_fragments=json.dumps(raw_fragments),
        )

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
                content = {"generic_devices": []}

        structured_devices = content.get("generic_devices", [])
        print(f"  [GenericDeviceStructuring] Structured {len(raw_fragments)} fragments into {len(structured_devices)} device(s)")
        for d in structured_devices:
            device_type = d.get("device_type", "?")
            attrs = d.get("attributes", {})
            attr_summary = ", ".join(
                f"{k}={v.get('value')}{v.get('unit', '')}" for k, v in attrs.items()
            )
            print(f"    - {device_type}: {attr_summary if attr_summary else 'no attributes'}")

        return {
            "content": {"generic_devices": structured_devices},
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
