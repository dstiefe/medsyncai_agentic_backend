"""
Context Review — Pre-output sufficiency check.

Lightweight LLM call that checks whether the engine has gathered enough
guideline context for the output agent to write an accurate narrative.
Only fires for UNCERTAIN/CONDITIONAL pathways.
"""

import json
from medsync_ai_v2.shared.llm_client import get_llm_client
from medsync_ai_v2 import config


CONTEXT_REVIEW_SYSTEM = """You check clinical guideline context for completeness.
You identify specific gaps where guideline text is needed but missing.
Respond ONLY in JSON. Be concise. Only flag gaps that would cause the
narrative to be inaccurate or misleading."""


class ContextReview:
    """Lightweight pre-output context check."""

    def __init__(self):
        self.llm_client = get_llm_client(provider=config.LLM_PROVIDER)
        self.model = config.LLM_FAST_MODEL or config.DEFAULT_FAST_MODELS.get(config.LLM_PROVIDER)

    async def review(
        self,
        patient: dict,
        eligibility: list,
        trial_context: dict,
        vector_context: list,
    ) -> dict:
        """
        Check if context is sufficient for accurate output.

        Returns:
            {
                "sufficient": bool,
                "needs_search": bool,
                "search_queries": [{"pathway": str, "query": str}, ...]
            }
        """
        # Only review pathways marked as edge_case
        edge_pathways = [
            e for e in eligibility
            if e.get("pathway_complexity") == "edge_case"
        ]

        if not edge_pathways:
            return {"sufficient": True, "needs_search": False, "search_queries": []}

        # Build compact summaries for the prompt
        patient_summary = self._summarize_patient(patient)
        eligibility_summary = self._summarize_eligibility(edge_pathways)
        context_summary = self._summarize_context(trial_context, vector_context)

        prompt = f"""PATIENT:
{patient_summary}

ELIGIBILITY RESULTS (UNCERTAIN/CONDITIONAL only):
{eligibility_summary}

GUIDELINE CONTEXT AVAILABLE:
{context_summary}

For each pathway above, check:
1. Does the context contain the SPECIFIC recommendation text (COR/LOE) for the closest matching guideline recommendation?
2. If the patient doesn't fully match a recommendation, does the context contain that recommendation so the narrative can explain WHY it doesn't apply?
3. For trial subgroup data cited in the reasoning, is the actual data present?

Respond in JSON only:
{{"sufficient": true/false, "gaps": [{{"pathway": "...", "missing": "...", "search_query": "..."}}]}}

If no gaps: {{"sufficient": true, "gaps": []}}"""

        try:
            response = await self.llm_client.call_json(
                system_prompt=CONTEXT_REVIEW_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
            )

            content = response.get("content", "")
            if isinstance(content, str):
                result = json.loads(content)
            else:
                result = content

            gaps = result.get("gaps", [])
            return {
                "sufficient": result.get("sufficient", True),
                "needs_search": len(gaps) > 0,
                "search_queries": [
                    {"pathway": g["pathway"], "query": g["search_query"]}
                    for g in gaps
                    if g.get("search_query")
                ],
            }

        except Exception as e:
            print(f"  [ContextReview] Failed: {e} — proceeding without review")
            return {"sufficient": True, "needs_search": False, "search_queries": []}

    def _summarize_patient(self, patient: dict) -> str:
        parts = []
        for key in ["age", "last_known_well_hours", "nihss", "mrs_pre",
                     "aspects", "occlusion_location", "lvo",
                     "posterior_circulation", "dementia",
                     "has_perfusion_imaging", "on_anticoagulation"]:
            val = patient.get(key)
            if val is not None and val != "" and val is not False:
                parts.append(f"{key}: {val}")
        return ", ".join(parts)

    def _summarize_eligibility(self, pathways: list) -> str:
        lines = []
        for e in pathways:
            line = f"- {e['treatment']}: {e['eligibility']}"
            if e.get("reasoning"):
                line += f" — {e['reasoning'][:150]}"
            if e.get("relevant_trials"):
                line += f" (trials: {', '.join(e['relevant_trials'])})"
            lines.append(line)
        return "\n".join(lines)

    def _summarize_context(self, trial_context: dict, vector_context: list) -> str:
        parts = []
        if trial_context:
            trial_names = list(trial_context.keys())
            parts.append(f"Trial metrics available: {', '.join(trial_names)}")
        if vector_context:
            for vc in vector_context:
                parts.append(
                    f"Vector chunk for {vc.get('for_treatment', '?')}: "
                    f"{vc.get('text', '')[:200]}..."
                )
        if not parts:
            parts.append("No additional guideline context available.")
        return "\n".join(parts)
