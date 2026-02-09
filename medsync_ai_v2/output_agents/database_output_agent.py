"""
Database Output Agent

Formats database engine results into user-facing responses.
Dynamically builds system message based on result count.
Streams tokens in real-time via broker.

Ported from vs2/agents/direct_query_agents.py (QueryExecutorOutputAgent).
"""

import json
from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent


class DatabaseOutputAgent(LLMAgent):
    """Formats database engine results into user-facing markdown responses."""

    def __init__(self):
        super().__init__(name="database_output_agent", skill_path=None)

    def _build_system_message(self, device_count: int) -> str:
        """Build system message with formatting guidance based on result count."""

        base_message = """You are presenting query results to the user.

## CRITICAL ACCURACY RULES

1. ONLY describe what was actually done. Do NOT embellish or add claims about checks that were not performed.
2. If the query was a spec filter only (no named devices, no compatibility check), say "matching your criteria" or "meeting those specifications" — do NOT say "compatible with" any device.
3. Only mention compatibility if the results explicitly include compatibility data.
4. If no named devices were involved, do NOT reference "specified devices" or "the devices you mentioned."

## Guidelines

1. Answer the user's question directly
2. Be concise but thorough
3. Mention any devices that were not found
4. Do NOT ask follow-up questions
"""

        if device_count == 1:
            format_guidance = """
## FORMAT: Single Device (Inline Prose)

Use natural sentences, no table needed:
"The Headway 21 has an inner diameter of 0.021", outer diameter of 0.026", and length of 150cm."
"""
        elif device_count == 2:
            format_guidance = """
## FORMAT: Two Devices (Comparison Table)

Use a side-by-side comparison table:

| Spec | Device A | Device B |
|------|----------|----------|
| ID | 0.021" | 0.017" |
| OD | 0.026" | 0.029" |
| Length | 150cm | 150cm |
| Manufacturer | MicroVention | Medtronic |
"""
        elif device_count >= 3:
            format_guidance = f"""
## FORMAT: Multiple Devices ({device_count} results) - Use Table

Use a markdown table to display results:

| Device | ID | OD | Length | Manufacturer |
|--------|-----|-----|--------|--------------|
| Headway 21 | 0.021" | 0.026" | 150cm | MicroVention |
| Phenom 21 | 0.021" | 0.028" | 150cm | Medtronic |

- Show up to 15 devices in the table
- Brief intro sentence stating total count
- If more than 15, note that additional options exist
"""
        else:
            format_guidance = """
## FORMAT: No Results

Explain that no devices matched the criteria and suggest alternatives if possible.
"""

        return base_message + format_guidance

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the database output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        user_query = input_data.get("user_query", "")
        summary = input_data.get("summary", "")
        query_spec = input_data.get("query_spec", {})
        device_list = input_data.get("device_list", [])
        not_found = input_data.get("not_found", [])
        generic_specs = input_data.get("generic_specs", [])

        device_count = len(device_list)
        system_message = self._build_system_message(device_count)

        # Build user prompt
        not_found_note = ""
        if not_found:
            suggestions = input_data.get("not_found_suggestions", {})
            not_found_parts = []
            for name in not_found:
                matches = suggestions.get(name, [])
                if matches:
                    alts = ", ".join(m["product_name"] for m in matches[:3])
                    not_found_parts.append(f"'{name}' (did you mean: {alts}?)")
                else:
                    not_found_parts.append(f"'{name}'")
            not_found_note = f"\n\nDevices NOT found in database: {'; '.join(not_found_parts)}"

        generic_note = ""
        if generic_specs:
            generic_note = f"\n\nUser's generic device specs: {json.dumps(generic_specs, indent=2)}"

        user_prompt = f"""User Question: {user_query}

Query Executed:
{json.dumps(query_spec, indent=2)}

Results:
{summary}
{not_found_note}
{generic_note}

Please answer the user's question based on these results."""

        messages = [{"role": "user", "content": user_prompt}]

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            ):
                if isinstance(chunk, dict):
                    usage = chunk
                else:
                    final_text += chunk
                    await broker.put({
                        "type": "final_chunk",
                        "data": {
                            "agent": self.name,
                            "content": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

            # Stream device list in chunks for UI
            if device_list:
                chunk_size = 20
                print(f"  [DatabaseOutputAgent] Streaming {len(device_list)} devices in chunks of {chunk_size}")
                for i in range(0, len(device_list), chunk_size):
                    chunk = device_list[i:i + chunk_size]
                    await broker.put({
                        "type": "query_result_device_chunk",
                        "data": {
                            "agent": self.name,
                            "devices": chunk,
                            "chunk_info": {
                                "chunk_number": i // chunk_size + 1,
                                "chunk_size": len(chunk),
                                "total_devices": len(device_list),
                                "is_final_chunk": (i + chunk_size) >= len(device_list),
                            },
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

            return {
                "content": {"formatted_response": final_text},
                "usage": usage,
            }
        else:
            # Non-streaming fallback
            response = await self.llm_client.call(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
