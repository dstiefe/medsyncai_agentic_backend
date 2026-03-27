"""
EvidenceSynthesizer — LLM agent that produces human-readable answers
from structured trial data returned by the CMI matcher.

Uses haiku-tier model (fast) since it only reads structured data,
not raw trial text.
"""

from __future__ import annotations

import os
import json
from medsync_ai_v2.base_agent import LLMAgent
from ..models.query import ParsedQuery, MatchedTrial


_SKILL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "SKILL.md"
)


class EvidenceSynthesizer(LLMAgent):
    """Synthesizes evidence-based answers from structured trial data."""

    def __init__(self):
        super().__init__(
            name="evidence_synthesizer",
            skill_path=_SKILL_PATH,
        )

    async def synthesize(
        self,
        query: ParsedQuery,
        matches: list[MatchedTrial],
    ) -> tuple[str, dict]:
        """
        Synthesize an evidence-based answer from structured trial data.

        Returns:
            (synthesis_text, usage_dict)
        """
        if not matches:
            return (
                "No trials in the database match the specified criteria. "
                "Consider broadening your search parameters.",
                {"input_tokens": 0, "output_tokens": 0},
            )

        # Build the prompt with structured data only — no raw text
        prompt = self._build_synthesis_prompt(query, matches)

        messages = [
            {"role": "user", "content": prompt},
        ]

        response = await self.llm_client.call(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        usage = {
            "input_tokens": response.get("input_tokens", 0),
            "output_tokens": response.get("output_tokens", 0),
        }

        content = response.get("content", "")

        return str(content), usage

    async def synthesize_comparison(
        self,
        query_a: ParsedQuery,
        query_b: ParsedQuery,
        matches_a: list[MatchedTrial],
        matches_b: list[MatchedTrial],
        label_a: str,
        label_b: str,
    ) -> tuple[str, dict]:
        """Synthesize a side-by-side comparison from two CMI searches."""
        if not matches_a and not matches_b:
            return "No matching trials found in the database for either population.", {"input_tokens": 0, "output_tokens": 0}

        prompt = self._build_comparison_prompt(query_a, query_b, matches_a, matches_b, label_a, label_b)

        messages = [{"role": "user", "content": prompt}]
        response = await self.llm_client.call(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        usage = {
            "input_tokens": response.get("input_tokens", 0),
            "output_tokens": response.get("output_tokens", 0),
        }

        content = response.get("content", "")

        return str(content), usage

    @staticmethod
    def _build_comparison_prompt(
        query_a, query_b, matches_a, matches_b, label_a, label_b
    ) -> str:
        """Build prompt for comparison synthesis."""
        sections = [
            f"## Comparison Question\n{query_a.clinical_question}",
            f"\nCompare **{label_a}** vs **{label_b}**.",
            f"\nPresent the data side by side. Use only data from the matched trials below.",
        ]

        for label, query, matches in [(label_a, query_a, matches_a), (label_b, query_b, matches_b)]:
            sections.append(f"\n\n# === {label} ===")
            prompt_section = EvidenceSynthesizer._build_synthesis_prompt(query, matches)
            sections.append(prompt_section)

        return "\n".join(sections)

    @staticmethod
    def _build_synthesis_prompt(query: ParsedQuery, matches: list[MatchedTrial]) -> str:
        """Build the prompt containing the question and matched trial data."""
        sections = []

        # Clinical question
        sections.append(f"## Clinical Question\n{query.clinical_question}")

        # Query variables (for context)
        query_vars = []
        if query.intervention:
            query_vars.append(f"Intervention: {query.intervention}")
        if query.aspects_range and query.aspects_range.is_set():
            query_vars.append(f"ASPECTS: {query.aspects_range.min}-{query.aspects_range.max}")
        if query.nihss_range and query.nihss_range.is_set():
            query_vars.append(f"NIHSS: {query.nihss_range.min}-{query.nihss_range.max}")
        if query.age_range and query.age_range.is_set():
            query_vars.append(f"Age: {query.age_range.min}-{query.age_range.max}")
        if query.time_window_hours and query.time_window_hours.is_set():
            query_vars.append(f"Time window: {query.time_window_hours.min}-{query.time_window_hours.max}h")
        if query.vessel_occlusion:
            query_vars.append(f"Vessel: {', '.join(query.vessel_occlusion)}")
        if query.circulation:
            query_vars.append(f"Circulation: {query.circulation}")

        if query_vars:
            sections.append("## Query Variables\n" + "\n".join(f"- {v}" for v in query_vars))

        # Matched trials by tier
        for tier in [1, 2, 3, 4]:
            tier_matches = [m for m in matches if m.tier == tier]
            if not tier_matches:
                continue

            tier_label = {
                1: "TIER 1 — Exact Criteria Match",
                2: "TIER 2 — Overlapping Criteria",
                3: "TIER 3 — Related Intervention, Different Range",
                4: "TIER 4 — Same Domain",
            }[tier]

            sections.append(f"\n## {tier_label}")

            for m in tier_matches:
                trial_section = []
                trial_section.append(f"### {m.trial_id} ({m.metadata.get('year', '?')})")
                trial_section.append(f"- **Design:** {m.metadata.get('study_type', '?')}")
                trial_section.append(f"- **Circulation:** {m.metadata.get('circulation', '?')}")
                trial_section.append(f"- **Journal:** {m.metadata.get('journal', '?')}")
                trial_section.append(f"- **Match reason:** {m.tier_reason}")

                if m.intervention:
                    agent = m.intervention.get("agent", "?")
                    comp = m.intervention.get("comparator", "?")
                    dose = m.intervention.get("dose", "")
                    trial_section.append(f"- **Intervention:** {agent} {dose} vs {comp}")

                # Structured results — explicitly show what IS and ISN'T available
                primary = m.results.get("primary_outcome", {})
                if primary and primary.get("metric"):
                    result_parts = [f"**Primary outcome:** {primary['metric']}"]
                    result_parts.append(f"  Intervention: {primary.get('intervention_value') or 'NOT REPORTED'}")
                    result_parts.append(f"  Control: {primary.get('control_value') or 'NOT REPORTED'}")
                    result_parts.append(f"  Effect: {primary.get('effect_type') or '?'} {primary.get('effect_size') or 'NOT REPORTED'}")
                    if primary.get("ci_95"):
                        result_parts.append(f"  95% CI: {primary['ci_95']}")
                    else:
                        result_parts.append(f"  95% CI: NOT REPORTED")
                    result_parts.append(f"  P: {primary.get('p_value') or 'NOT REPORTED'}")
                    trial_section.append("- " + "\n  ".join(result_parts))
                else:
                    trial_section.append("- **Primary outcome:** NOT REPORTED in database")

                safety = m.results.get("safety", {})
                sich_i = safety.get("sich_intervention")
                sich_c = safety.get("sich_control")
                mort_i = safety.get("mortality_90d_intervention")
                mort_c = safety.get("mortality_90d_control")
                trial_section.append(f"- **Safety:** sICH: {sich_i or 'NOT REPORTED'} vs {sich_c or 'NOT REPORTED'}; "
                                     f"Mortality: {mort_i or 'NOT REPORTED'} vs {mort_c or 'NOT REPORTED'}")

                # CRITICAL: All data above is the ONLY data available. Do NOT infer or fill in values.

                sections.append("\n".join(trial_section))

        return "\n\n".join(sections)
