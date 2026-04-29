"""
Clinical Output Agent

Formats clinical_support_engine results (patient data, eligibility assessments,
guideline context) into a guideline-referenced clinical assessment document.
Streams tokens in real-time via broker.
"""

import os
import re
from datetime import datetime, timezone
from app.base_agent import LLMAgent

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class ClinicalOutputAgent(LLMAgent):
    """Formats clinical eligibility assessments into user-facing responses."""

    def __init__(self):
        super().__init__(name="clinical_output_agent", skill_path=SKILL_PATH)
        self._load_references()

    def _load_references(self):
        """Load reference files and build the full system message."""
        refs_dir = os.path.join(os.path.dirname(__file__), "references")
        ref_files = [
            "routine_format",
            "edge_case_format",
            "clinical_rules",
        ]
        for name in ref_files:
            path = os.path.join(refs_dir, f"{name}.md")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.system_message = self.system_message + "\n\n" + content

    def _strip_trial_names(self, text: str) -> str:
        """Remove trial names and citations from text for routine cases."""

        # List of common trial names to strip
        trial_patterns = [
            r'\bTRACE-III\b', r'\bTIMELESS\b', r'\bDAWN\b', r'\bDEFUSE-3\b', r'\bDEFUSE\b',
            r'\bENCHANTED2\b', r'\bENCHANTED\b', r'\bBP-TARGET\b', r'\bBEST-II\b',
            r'\bHERMES\b', r'\bAURORA\b', r'\bMR CLEAN\b', r'\bESCAPE\b', r'\bREVASCAT\b',
            r'\bSWIFT PRIME\b', r'\bEXTEND IA\b', r'\bTHRACE\b', r'\bSELECT2?\b',
            r'\bANGEL-ASPECT\b', r'\bLASTE\b', r'\bTENSION\b', r'\bOPTIMAL-BP\b'
        ]

        # Remove trial names
        for pattern in trial_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Clean up resulting artifacts
        # Remove "per " or "in " before removed trial name
        text = re.sub(r'\b(per|in|showed benefit in|but|and)\s+', r'\1 ', text)
        # Remove double spaces
        text = re.sub(r'\s+', ' ', text)
        # Remove "per " at end of sentence
        text = re.sub(r'\s+(per|in|but|and)\s*([,.])', r'\2', text)
        # Remove trailing commas/periods with no content
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'\.\s*\.', '.', text)
        # Remove sentences that are now empty or just punctuation
        text = re.sub(r'[,;]\s*[,;]', ',', text)

        return text.strip()

    def _build_user_prompt(self, input_data: dict) -> str:
        """Build the full prompt from engine data."""
        user_query = input_data.get("user_query", "")
        patient = input_data.get("patient", {})
        eligibility = input_data.get("eligibility", [])
        vector_context = input_data.get("vector_context", [])
        complexity = input_data.get("complexity", "edge_case")

        parts = []

        # Patient summary
        parts.append("## PATIENT PRESENTATION")
        parts.append(f"Age: {patient.get('age', 'Unknown')}")
        parts.append(f"Sex: {patient.get('sex', 'Unknown')}")
        parts.append(f"Last Known Well: {patient.get('last_known_well_hours', 'Unknown')} hours")
        parts.append(f"NIHSS: {patient.get('nihss', 'Unknown')}")
        parts.append(f"Pre-stroke mRS: {patient.get('mrs_pre', 'Unknown')}")
        parts.append(f"ASPECTS: {patient.get('aspects', 'Unknown')}")
        parts.append(f"Occlusion: {patient.get('occlusion_location', 'Unknown')}")
        parts.append(f"LVO: {patient.get('lvo', False)}")
        parts.append(f"Dementia: {patient.get('dementia', False)}")
        parts.append(f"Perfusion Imaging: {patient.get('has_perfusion_imaging', False)}")
        parts.append(f"On Anticoagulation: {patient.get('on_anticoagulation', False)}")
        parts.append(f"Raw: {patient.get('raw_presentation', '')}")

        # Eligibility results
        parts.append("\n## ELIGIBILITY ASSESSMENTS")
        for e in eligibility:
            parts.append(f"\n### {e.get('treatment', 'Unknown')}")
            parts.append(f"Eligibility: {e.get('eligibility', 'Unknown')}")
            parts.append(f"Complexity: {e.get('pathway_complexity', 'routine')}")

            cor = e.get('cor') or 'None'
            loe = e.get('loe') or 'None'

            parts.append(f"COR: {cor}")
            parts.append(f"LOE: {loe}")

            # Explicit warning for None COR/LOE
            if cor in ('None', 'N/A', None) and loe in ('None', 'N/A', None):
                parts.append(
                    "\u26a0\ufe0f WARNING: No guideline COR/LOE exists for this pathway. "
                    "Do NOT invent or assume a COR/LOE."
                )

            # For routine cases, simplify reasoning and strip criteria
            reasoning = e.get('reasoning', '')
            elig_status = e.get('eligibility', 'UNCERTAIN')
            treatment = e.get('treatment', '')

            if complexity == "routine":
                # Simplify reasoning for YES/CONDITIONAL, keep full reason for NO
                if elig_status == "YES":
                    reasoning = "Meets guideline criteria."
                elif elig_status == "CONDITIONAL":
                    reasoning = "Conditional recommendation."
                elif reasoning:
                    # For NO, keep the reason but strip trial names
                    reasoning = self._strip_trial_names(reasoning)

            parts.append(f"Reasoning: {reasoning}")

            # Only include criteria for edge cases OR BP management
            if e.get("key_criteria"):
                criteria = e['key_criteria']
                if complexity == "routine":
                    # For routine cases, only include BP management criteria
                    if treatment == "BP_management":
                        criteria = [self._strip_trial_names(c) for c in criteria]
                        criteria = [c for c in criteria if c.strip()]
                    else:
                        criteria = []  # Strip criteria for all other routine pathways
                if criteria:
                    parts.append(f"Criteria: {'; '.join(criteria)}")

            # guideline_uncertainty always passes through (survives routine stripping)
            if e.get("guideline_uncertainty"):
                parts.append(f"Guideline Uncertainty Note: {e['guideline_uncertainty']}")

            # Only include trials and caveats for edge cases
            if complexity == "edge_case":
                if e.get("relevant_trials"):
                    parts.append(f"Trials: {', '.join(e['relevant_trials'])}")
                if e.get("caveats"):
                    parts.append(f"Caveats: {'; '.join(e['caveats'])}")

            if e.get("page_references"):
                parts.append(f"Pages: {e['page_references']}")

        # Note for routine cases
        if complexity == "routine":
            parts.append("\n## NOTE")
            parts.append("This is a ROUTINE case. No trial metrics are provided. "
                         "Use only COR, LOE, eligibility determinations, and patient "
                         "parameters in your response.")

        # Vector search context (only for edge cases)
        if complexity == "edge_case" and vector_context:
            parts.append("\n## ADDITIONAL GUIDELINE CONTEXT (from vector search)")
            for vc in vector_context:
                parts.append(f"\n### For: {vc.get('for_treatment', 'Unknown')}")
                parts.append(vc.get("text", ""))

        # Trial metrics (only for edge cases)
        if complexity == "edge_case":
            trial_context = input_data.get("trial_context", {})
            if trial_context:
                parts.append("\n## TRIAL METRICS (from structured data)")
                for trial_name, info in trial_context.items():
                    parts.append(f"\n### {trial_name}")
                    parts.append(f"Full name: {info.get('full_name', '')}")
                    parts.append(f"Category: {info.get('category', '')}")
                    if info.get("pages"):
                        parts.append(f"Pages: {info['pages']}")
                    for m in info.get("metrics", []):
                        metric_type = m.get("metric_type", "")
                        name = m.get("metric_name", "")
                        if metric_type == "percentage_comparison":
                            parts.append(
                                f"- {name}: intervention {m.get('intervention_value', '')} "
                                f"vs control {m.get('control_value', '')} "
                                f"({m.get('effect_size', '')}, {m.get('ci', '')}, "
                                f"p={m.get('p_value', '')})"
                            )
                        else:
                            effect = m.get("effect_size", "")
                            ci = m.get("ci", "")
                            p = m.get("p_value", "")
                            line = f"- {name}: {effect}"
                            if ci:
                                line += f" ({ci})"
                            if p:
                                line += f", p={p}"
                            parts.append(line)

        # Data completeness (if available)
        completeness = input_data.get("completeness", {})
        if completeness:
            parts.append("\n## DATA COMPLETENESS")

            assessable = []
            not_assessable = []
            for pathway, key in [
                ("IVT (standard + extended)", "can_assess_ivt"),
                ("EVT (standard)", "can_assess_evt"),
                ("Extended Window (IVT/EVT)", "can_assess_extended"),
                ("Large Core EVT", "can_assess_large_core"),
            ]:
                if completeness.get(key, False):
                    assessable.append(pathway)
                else:
                    not_assessable.append(pathway)

            if assessable:
                parts.append(f"CAN ASSESS: {', '.join(assessable)}")
            if not_assessable:
                parts.append(f"CANNOT ASSESS (missing critical data): {', '.join(not_assessable)}")

            missing_critical = completeness.get("missing_critical", [])
            if missing_critical:
                parts.append("\nMISSING CRITICAL PARAMETERS:")
                for item in missing_critical:
                    parts.append(f"  - {item.get('label', item.get('param', 'Unknown'))}")

            missing_important = completeness.get("missing_important", [])
            if missing_important:
                parts.append("\nMISSING IMPORTANT PARAMETERS:")
                for item in missing_important:
                    parts.append(f"  - {item.get('label', item.get('param', 'Unknown'))}")

            assumptions = completeness.get("assumptions_made", [])
            if assumptions:
                parts.append("\nASSUMPTIONS APPLIED:")
                for a in assumptions:
                    parts.append(f"  - {a}")

        pathway_specific_qs = completeness.get("pathway_specific_questions", [])
        if pathway_specific_qs:
            parts.append("\nPATHWAY-SPECIFIC FOLLOW-UP (append after disclaimer):")
            for q in pathway_specific_qs:
                parts.append(f"  - {q}")

        # Complexity flag for output formatting
        complexity = input_data.get("complexity", "edge_case")
        parts.append(f"\n## CASE COMPLEXITY: {complexity.upper()}")

        parts.append(f"\n## USER QUESTION\n{user_query}")
        parts.append("\nSynthesize the above into a guideline-referenced clinical assessment.")

        return "\n".join(parts)

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the clinical output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        user_prompt = self._build_user_prompt(input_data)
        messages = [{"role": "user", "content": user_prompt}]

        patient = input_data.get("patient", {})
        eligibility = input_data.get("eligibility", [])
        print(f"  [ClinicalOutputAgent] Patient age={patient.get('age')}, "
              f"{len(eligibility)} pathways evaluated")

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=self.system_message,
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
                system_prompt=self.system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
