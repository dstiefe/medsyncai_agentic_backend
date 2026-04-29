"""
Chain Output Agent

Formats chain engine results into user-facing responses.
Dynamically builds system message based on classification sub-type,
response framing, and query mode. Streams tokens in real-time via broker.

Ported from vs2 MultipleConstraintsGetChainsAgentOutput.
"""

import os
import json
from datetime import datetime, timezone
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class ChainOutputAgent(LLMAgent):
    """Formats chain engine results into user-facing markdown responses."""

    def __init__(self):
        super().__init__(name="chain_output_agent", skill_path=SKILL_PATH)
        self._refs = {}
        self._load_references()

    def _load_references(self):
        """Load all reference files for dynamic system message building."""
        refs_dir = os.path.join(os.path.dirname(__file__), "references")
        ref_files = [
            "compatibility_check",
            "device_discovery",
            "stack_validation",
            "response_framing",
            "query_modes",
            "shared_guidelines",
        ]
        for name in ref_files:
            path = os.path.join(refs_dir, f"{name}.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self._refs[name] = f.read()

    def _build_system_message(self, input_data: dict) -> str:
        """Build system message dynamically based on classification context."""

        classification = input_data.get("classification", {})
        result_type = input_data.get("result_type", "compatibility_check")
        query_mode = classification.get("query_mode", "exploratory")
        response_framing = input_data.get("response_framing", classification.get("framing", "neutral"))

        flat_data = input_data.get("flat_data", [])
        device_count = len(flat_data)

        # ----------------------------------------------------------
        # Base context from SKILL.md
        # ----------------------------------------------------------
        base_context = self.system_message

        # ----------------------------------------------------------
        # Sub-type specific instructions from references
        # ----------------------------------------------------------
        if result_type == "compatibility_check":
            sub_type_instructions = self._refs.get("compatibility_check", "")

        elif result_type == "device_discovery":
            discovery_content = self._refs.get("device_discovery", "")
            if device_count >= 3:
                # Use the multiple results section - inject device count
                sub_type_instructions = discovery_content.split("# Device Discovery - Few Results")[0]
                sub_type_instructions = sub_type_instructions.replace(
                    "Use a markdown table for multiple results:",
                    f"Use a markdown table for {device_count} results:"
                )
            else:
                # Use the few results section
                parts = discovery_content.split("# Device Discovery - Few Results")
                sub_type_instructions = parts[1] if len(parts) > 1 else discovery_content

        elif result_type == "stack_validation":
            sub_type_instructions = self._refs.get("stack_validation", "")

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
        # Response framing adjustments from references
        # ----------------------------------------------------------
        framing_content = self._refs.get("response_framing", "")
        framing_note = ""
        if response_framing == "negative" and "## Negative Framing" in framing_content:
            start = framing_content.index("## Negative Framing")
            end = framing_content.index("## Positive Framing") if "## Positive Framing" in framing_content else len(framing_content)
            framing_note = "\nNOTE: " + framing_content[start:end].replace("## Negative Framing\n", "").strip()
        elif response_framing == "positive" and "## Positive Framing" in framing_content:
            start = framing_content.index("## Positive Framing")
            end = framing_content.index("## Neutral Framing") if "## Neutral Framing" in framing_content else len(framing_content)
            framing_note = "\nNOTE: " + framing_content[start:end].replace("## Positive Framing\n", "").strip()

        # ----------------------------------------------------------
        # Query mode adjustments from references
        # ----------------------------------------------------------
        modes_content = self._refs.get("query_modes", "")
        mode_note = ""
        if query_mode == "discovery" and "## Discovery Mode" in modes_content:
            start = modes_content.index("## Discovery Mode")
            end = modes_content.index("## Comparison Mode") if "## Comparison Mode" in modes_content else len(modes_content)
            mode_note = "\nMODE: Discovery - " + modes_content[start:end].replace("## Discovery Mode\n", "").strip()
        elif query_mode == "comparison" and "## Comparison Mode" in modes_content:
            start = modes_content.index("## Comparison Mode")
            end = modes_content.index("## Default Mode") if "## Default Mode" in modes_content else len(modes_content)
            mode_note = "\nMODE: Comparison - " + modes_content[start:end].replace("## Comparison Mode\n", "").strip()

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
