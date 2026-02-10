"""
Chain Output Agent

Formats chain engine results into user-facing responses.
Dynamically builds system message based on classification sub-type,
response framing, and query mode. Streams tokens in real-time via broker.

Ported from vs2 MultipleConstraintsGetChainsAgentOutput.
"""

import json
from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent


class ChainOutputAgent(LLMAgent):
    """Formats chain engine results into user-facing markdown responses."""

    def __init__(self):
        super().__init__(name="chain_output_agent", skill_path=None)

    def _build_system_message(self, input_data: dict) -> str:
        """Build system message dynamically based on classification context."""

        classification = input_data.get("classification", {})
        result_type = input_data.get("result_type", "compatibility_check")
        query_mode = classification.get("query_mode", "exploratory")
        response_framing = input_data.get("response_framing", classification.get("framing", "neutral"))

        flat_data = input_data.get("flat_data", [])
        device_count = len(flat_data)

        # ----------------------------------------------------------
        # Base context
        # ----------------------------------------------------------
        base_context = """You are a medical device compatibility assistant helping physicians with device selection.
- DISTAL = innermost device (closest to treatment site)
- PROXIMAL = outermost device (closest to access point)
- Use "configuration" instead of "chain"
- Data provided is verified from device specifications - don't add outside knowledge
- Be concise and clinically relevant
- Answer naturally - avoid starting with blunt "YES" or "NO" responses
- Stay neutral and clinical - no marketing language
- AVOID words like: "popular", "best", "commonly used", "leading", "preferred", "top", "recommended"
- Do not favor any manufacturer over another
- Present all options objectively based on specifications

CRITICAL - HANDLING MULTI-SIZE DEVICES:
When a device (like Trevo NXT, Solitaire, etc.) has MULTIPLE SIZES with DIFFERENT specifications:
- Present the FULL RANGE across all sizes, not just one size's specs
- Use phrasing like: "[Device name] (depending on size) requires..." or "[Device name] sizes range from..."
- If compatibility varies by size, state: "Some sizes of [Device] are compatible while others are not"
- NEVER cherry-pick just one size's requirements - this is misleading
- Example: If data shows Trevo NXT sizes require 0.017-0.021", 0.017-0.027", and 0.021-0.027", report the FULL range as 0.017-0.027\""""

        # ----------------------------------------------------------
        # Sub-type specific instructions
        # ----------------------------------------------------------
        if result_type == "compatibility_check":
            sub_type_instructions = """
TASK: Answer a compatibility question between specific devices.

FORMAT: Use inline prose (no tables) for 2-device checks. Example:
"The Vecta 46 OD (0.058") fits within the Neuron MAX ID (0.088"), with the 132cm length extending past the 80cm sheath."

STRUCTURE:
1. Lead with a natural, direct answer that flows conversationally
2. Include the dimensional fit inline (OD → ID)
3. Note any length considerations if relevant
4. Keep it to 2-3 sentences max

MULTI-SIZE HANDLING FOR COMPATIBILITY:
- If the data shows multiple sizes with different requirements, consolidate into the full range
- Example: "The Trevo NXT ProVue Retriever (depending on size) requires a microcatheter with ID of 0.017-0.027 inches"
- If some sizes are compatible and others aren't, state this clearly:
  "Some Trevo NXT sizes (3x32, 4x28) are compatible, while larger sizes (4x41, 6x37) are not"

GOOD OPENINGS:
- "The Vecta 46 is compatible with the Neuron MAX..."
- "These devices work well together..."
- "Actually, these are compatible..."
- "This configuration won't work because..."
- "Unfortunately, these aren't compatible..."

RESPONSE QUALITY RULES:
- SAFETY: When the analysis says "Not Compatible", report it as Not Compatible. Do NOT re-evaluate or override the verdict based on dimensional proximity. The compatibility engine has already applied the correct evaluation logic — your job is to present its findings, not second-guess them.
- Do NOT repeat the same numbers twice — state the dimensional mismatch once, clearly
- When a connection fails on a clear blocker (e.g. ID mismatch), do NOT mention irrelevant passing checks (e.g. length) — focus on the reason it fails
- Add brief clinical context when relevant — e.g. "The Solitaire is designed to be delivered through a microcatheter, not directly through an intermediate catheter like the Vecta 46" — explain the *why*, not just the numbers
- Keep it to 2-3 sentences. Every sentence should add new information
"""

        elif result_type == "device_discovery":
            if device_count >= 3:
                sub_type_instructions = f"""
TASK: Present compatible devices found for the source device.

FORMAT: Use a markdown table for {device_count} results:

| Device | ID | OD | Length | Manufacturer |
|--------|-----|-----|--------|--------------|
| Headway 21 | 0.021" | 0.026" | 150cm | MicroVention |
| Phenom 21 | 0.021" | 0.028" | 150cm | Medtronic |

STRUCTURE:
1. Brief intro stating the source device requirements (1 sentence)
2. Neutral transition like: "The following meet these requirements:" or "Compatible options include:"
3. Markdown table with up to 10-15 options
4. Note total count if more exist: "There are X compatible devices in total."

MULTI-SIZE HANDLING FOR DISCOVERY:
- If the source device has multiple sizes, state the range: "The [Device] (depending on size) requires ID of X-Y inches"
- If only some sizes of the source device are compatible, note which ones

LANGUAGE RULES:
- Stay neutral and clinical - no marketing language
- NEVER use: "commonly used", "popular", "best", "recommended", "leading", "preferred", "top choices", "key options"
- NEVER imply one device or manufacturer is better than another
- USE: "compatible", "meet the requirements", "within specifications", "available options"
- List devices alphabetically by manufacturer or by specification, not by preference
"""
            else:
                sub_type_instructions = """
TASK: Present compatible devices found for the source device.

FORMAT: Use inline prose for few results.

STRUCTURE:
1. Briefly state what the source device requires (ID range, length)
2. List the compatible devices with key specs inline
3. Keep it concise

MULTI-SIZE HANDLING:
- If the source device has multiple sizes with different requirements, present the full range

LANGUAGE RULES:
- Stay neutral and clinical - no marketing language
- NEVER use: "commonly used", "popular", "best", "recommended"
- USE: "compatible", "meet the requirements"
"""

        elif result_type == "stack_validation":
            sub_type_instructions = """
TASK: Validate a multi-device configuration (3+ devices).

CRITICAL - CHECK FOR N-1 SCENARIOS:
If NOT all requested devices can fit in a single configuration:
1. FIRST clearly state: "All X devices cannot be used in a single configuration."
2. EXPLAIN WHY - identify which devices conflict and the reason:
   - "Device A and Device B are both proximal sheaths - they serve the same role and cannot nest inside each other"
   - "Device X's OD (0.085") is larger than Device Y's ID (0.046") - they cannot connect"
3. THEN present the valid subset configurations as labeled options
4. Note which device is EXCLUDED in each option

MULTI-SIZE HANDLING FOR STACKS:
- If a device in the stack has multiple sizes, and compatibility varies by size:
  - State which sizes work and which don't
  - Example: "The Trevo NXT 3x32 and 4x28 sizes fit through Headway 21, but larger sizes (4x41, 6x37) require a larger microcatheter"
- When showing specs in tables, if sizes vary, show the range or note "varies by size"

EXAMPLE FOR N-1 SCENARIO:
"All 5 devices cannot be used in a single configuration. The Paragon 8F and Neuron MAX are both proximal access sheaths - these serve the same role and cannot nest inside each other.

Here are two valid 4-device configurations:

**Option A (excludes Neuron MAX):**
Trak 21 -> Vecta 46 -> Vecta 71 -> Paragon 8F

| Connection | Distal OD | Proximal ID | Status |
|------------|-----------|-------------|--------|
| Trak 21 -> Vecta 46 | 0.035" | 0.046" | Compatible |
| Vecta 46 -> Vecta 71 | 0.058" | 0.071" | Compatible |
| Vecta 71 -> Paragon 8F | 0.085" | 0.087" | Compatible |

**Option B (excludes Paragon 8F):**
Trak 21 -> Vecta 46 -> Vecta 71 -> Neuron MAX

Both configurations are valid options."

FORMAT FOR STANDARD STACK (all devices fit):
1. Natural opening stating the configuration works
2. Show device order: [distal] -> ... -> [proximal]
3. Markdown table showing each connection with dimensions
4. If incompatible, clearly mark which connection fails

| Connection | Distal OD | Proximal ID | Status |
|------------|-----------|-------------|--------|
| Solitaire -> Phenom 17 | 0.024" | 0.017" | Compatible |
| Phenom 17 -> Neuron MAX | 0.029" | 0.088" | Compatible |

GOOD OPENINGS (when all fit):
- "This configuration works..."
- "All devices are compatible in this order..."

GOOD OPENINGS (when n-1):
- "All X devices cannot be used in a single configuration..."
- "Not all devices can fit together because..."
- "These devices include two [sheaths/microcatheters/etc.] that serve the same role..."
"""

        else:
            sub_type_instructions = """
TASK: Provide compatibility analysis.

FORMAT:
- For single device or 2-device checks: Use inline prose
- For multiple devices (3+): Use markdown table
- For comparisons: Use side-by-side table

| Spec | Device A | Device B |
|------|----------|----------|
| ID | 0.021" | 0.017" |
| OD | 0.026" | 0.029" |

MULTI-SIZE HANDLING:
- Always present the full range of specifications across all sizes
- Never cherry-pick just one size's specs

LANGUAGE RULES:
- Stay neutral - no marketing language
- Present specifications objectively
"""

        # ----------------------------------------------------------
        # Response framing adjustments
        # ----------------------------------------------------------
        if response_framing == "negative":
            framing_note = """
NOTE: The user expressed doubt or skepticism about compatibility.
- If devices ARE compatible: Gently correct with "Actually, these are compatible..." or "Contrary to what you might expect..."
- If devices are NOT compatible: Confirm their intuition with "You're right, these won't work together because..."
- If n-1 scenario: Acknowledge their concern was valid - not all devices fit together
- If multi-size device: Note if their doubt applies to all sizes or just some"""
        elif response_framing == "positive":
            framing_note = """
NOTE: The user expects/hopes for compatibility.
- If compatible: Confirm naturally "These work well together..."
- If NOT compatible: Be direct but gentle "Unfortunately, these aren't compatible because..."
- If n-1 scenario: Acknowledge partial success - "While not all devices fit in one configuration, here are valid options..."
- If multi-size device: Clarify if compatibility applies to all sizes or just some"""
        else:
            framing_note = ""

        # ----------------------------------------------------------
        # Query mode adjustments
        # ----------------------------------------------------------
        if query_mode == "discovery":
            mode_note = """
MODE: Discovery - user is exploring options. Use a table to help them compare. Present all options neutrally without ranking or preference."""
        elif query_mode == "comparison":
            mode_note = """
MODE: Comparison - user is comparing options. Use a side-by-side table showing specifications. Present differences objectively without recommending one over another.

| Spec | Option A | Option B |
|------|----------|----------|
| ID | 0.021" | 0.017" |
| OD | 0.026" | 0.029" |
| Length | 150cm | 150cm |

Let the specifications speak for themselves - do not state which is "better"."""
        else:
            mode_note = ""

        return f"{base_context}\n{sub_type_instructions}\n{framing_note}\n{mode_note}".strip()

    def _format_subset(self, subset_analysis) -> str:
        """Format N-1 subset results for inclusion in the LLM prompt."""
        lines = []
        if isinstance(subset_analysis, list):
            subsets = subset_analysis
        else:
            subsets = subset_analysis.get("subsets", [])
        for subset in subsets:
            excluded = subset.get("excluded_device", "unknown")
            status = subset.get("status", "unknown")
            label = "Valid" if status == "pass" else "Invalid"
            lines.append(f"  Excluding {excluded}: {label}")
            if status == "pass" and subset.get("chain_path"):
                lines.append(f"    Order: {' -> '.join(subset['chain_path'])}")
        return "\n".join(lines) if lines else "No subset data available."

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the chain output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        Always returns the full text and usage for orchestrator tracking.
        """
        system_message = self._build_system_message(input_data)

        # Build user prompt with rich compatibility analysis
        user_query = input_data.get("user_query", "")
        text_summary = input_data.get("text_summary", "")
        user_prompt = f"User Question: {user_query}\n\nCompatibility Analysis:\n\n{text_summary}"

        # Append subset analysis for N-1 scenarios
        subset = input_data.get("subset_analysis")
        if subset:
            user_prompt += f"\n\nN-1 Subset Configurations:\n{self._format_subset(subset)}"

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
