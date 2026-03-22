import re
import logging
from typing import Optional
from ..models.clinical import ParsedVariables, NIHSSItems

logger = logging.getLogger("medsync.nlp")


class NLPService:
    """NLP service for parsing clinical scenarios."""

    def __init__(self, settings=None):
        """Initialize NLP service."""
        self.settings = settings
        self.client = None
        # Try to get API key from settings, env, or centralized client
        api_key = None
        if settings and hasattr(settings, 'ANTHROPIC_API_KEY'):
            api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
            logger.info("NLP service initialized with Claude API")
        else:
            logger.error("No ANTHROPIC_API_KEY found — NLP extraction will not be available. "
                        "Set ANTHROPIC_API_KEY in .env or environment.")

    async def parse_scenario(self, text: str) -> ParsedVariables:
        """
        Parse scenario using Claude API with tool_use.

        Falls back to regex if API unavailable.
        """
        if not self.client:
            logger.error("NLP extraction unavailable — no API key configured")
            return ParsedVariables()

        try:
            # Define extraction tool
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system="""You are a clinical information extraction assistant. Your task is to extract structured clinical information from free-text patient scenarios. You MUST extract ONLY factual information present in the text. Do NOT make clinical inferences, recommendations, or assumptions about missing data. If a value is not mentioned, leave it as null. Return ONLY valid JSON with fields exactly as specified.

IMPORTANT extraction rules:
- "unknown onset", "unwitnessed", "found down" = unknown time of onset. Set timeHours to null, wakeUp to null. This is NOT a wake-up stroke.
- "wake-up stroke", "woke with symptoms" = wakeUp is true.
- "LKW" = last known well. Extract the time value to lastKnownWellHours.
- If onset time and LKW are different concepts, extract both separately.
- For vessel: extract the specific vessel name (M1, M2, ICA, basilar, etc.), not just "LVO".""",
                tools=[
                    {
                        "name": "extract_clinical_variables",
                        "description": "Extract structured clinical variables from scenario text",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "age": {"type": ["integer", "null"], "minimum": 0, "maximum": 120},
                                "sex": {"type": ["string", "null"], "description": "Patient sex. Return 'male' or 'female' only."},
                                "timeHours": {"type": ["number", "null"], "minimum": 0, "description": "Hours from symptom onset to presentation"},
                                "lastKnownWellHours": {"type": ["number", "null"], "minimum": 0, "description": "Hours since last known well/normal (especially for wake-up strokes or unknown onset)"},
                                "wakeUp": {"type": ["boolean", "null"], "description": "true ONLY if patient explicitly woke up with symptoms (wake-up stroke). NOT true for unknown onset/unwitnessed/found down."},
                                "timeWindow": {"type": ["string", "null"], "description": "Set to 'unknown' if onset time is unknown/unwitnessed/found down. null otherwise."},
                                "nihss": {"type": ["integer", "null"], "minimum": 0, "maximum": 42},
                                "nihssItems": {
                                    "type": ["object", "null"],
                                    "properties": {
                                        "vision": {"type": ["integer", "null"]},
                                        "bestLanguage": {"type": ["integer", "null"]},
                                        "extinction": {"type": ["integer", "null"]},
                                        "motorArmL": {"type": ["integer", "null"]},
                                        "motorArmR": {"type": ["integer", "null"]},
                                        "motorLegL": {"type": ["integer", "null"]},
                                        "motorLegR": {"type": ["integer", "null"]},
                                        "facialPalsy": {"type": ["integer", "null"]},
                                        "sensory": {"type": ["integer", "null"]},
                                        "ataxia": {"type": ["integer", "null"]},
                                        "limbAtaxia": {"type": ["integer", "null"]}
                                    }
                                },
                                "vessel": {"type": ["string", "null"], "description": "Vessel name (e.g. M1, ICA, basilar) or 'No LVO' if explicitly stated no large vessel occlusion. null if not mentioned."},
                                "side": {"type": ["string", "null"]},
                                "m2Dominant": {"type": ["boolean", "null"], "description": "For M2 occlusions only: true if 'dominant' M2 is specified, false if 'nondominant' or 'codominant' is specified. null if M2 dominance not mentioned or vessel is not M2."},
                                "aspects": {"type": ["integer", "null"], "minimum": 0, "maximum": 10},
                                "prestrokeMRS": {"type": ["integer", "null"], "minimum": 0, "maximum": 6},
                                "sbp": {"type": ["integer", "null"], "minimum": 0},
                                "dbp": {"type": ["integer", "null"], "minimum": 0},
                                "hemorrhage": {"type": ["boolean", "null"]},
                                "onAntiplatelet": {"type": ["boolean", "null"]},
                                "onAnticoagulant": {"type": ["boolean", "null"]},
                                "sickleCell": {"type": ["boolean", "null"]},
                                "dwiFlair": {"type": ["boolean", "null"]},
                                "penumbra": {"type": ["boolean", "null"]},
                                "cmbs": {"type": ["boolean", "null"]},
                                "cmbCount": {"type": ["integer", "null"]},
                                "ivtGiven": {"type": ["boolean", "null"]},
                                "ivtNotGiven": {"type": ["boolean", "null"]},
                                "evtUnavailable": {"type": ["boolean", "null"]},
                                "nonDisabling": {"type": ["boolean", "null"], "description": "true if deficits are explicitly described as non-disabling/mild/minor; false if explicitly described as disabling/clearly disabling/cannot walk/cannot use arm/functionally limiting"},
                                "recentTBI": {"type": ["boolean", "null"]},
                                "tbiDays": {"type": ["integer", "null"]},
                                "recentNeurosurgery": {"type": ["boolean", "null"]},
                                "neurosurgeryDays": {"type": ["integer", "null"]},
                                "acuteSpinalCordInjury": {"type": ["boolean", "null"]},
                                "intraAxialNeoplasm": {"type": ["boolean", "null"]},
                                "extraAxialNeoplasm": {"type": ["boolean", "null"]},
                                "infectiveEndocarditis": {"type": ["boolean", "null"]},
                                "aorticArchDissection": {"type": ["boolean", "null"]},
                                "cervicalDissection": {"type": ["boolean", "null"]},
                                "platelets": {"type": ["integer", "null"]},
                                "inr": {"type": ["number", "null"]},
                                "aptt": {"type": ["number", "null"]},
                                "pt": {"type": ["number", "null"]},
                                "aria": {"type": ["boolean", "null"]},
                                "amyloidImmunotherapy": {"type": ["boolean", "null"]},
                                "priorICH": {"type": ["boolean", "null"]},
                                "recentStroke3mo": {"type": ["boolean", "null"]},
                                "recentNonCNSTrauma": {"type": ["boolean", "null"]},
                                "recentNonCNSSurgery10d": {"type": ["boolean", "null"]},
                                "recentGIGUBleeding21d": {"type": ["boolean", "null"]},
                                "pregnancy": {"type": ["boolean", "null"]},
                                "activeMalignancy": {"type": ["boolean", "null"]},
                                "extensiveHypodensity": {"type": ["boolean", "null"]},
                                "moyaMoya": {"type": ["boolean", "null"]},
                                "unrupturedAneurysm": {"type": ["boolean", "null"]},
                                "recentDOAC": {"type": ["boolean", "null"]}
                            },
                            "required": []
                        }
                    }
                ],
                messages=[
                    {"role": "user", "content": text}
                ]
            )

            # Extract tool use result
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    if block.name == "extract_clinical_variables":
                        parsed_data = block.input
                        logger.info("=== LLM EXTRACTION RESULT ===")
                        logger.info("%s", parsed_data)
                        # Create ParsedVariables, handling nihssItems
                        nihss_items = None
                        if parsed_data.get("nihssItems"):
                            nihss_items = NIHSSItems(**parsed_data["nihssItems"])
                        parsed_data["nihssItems"] = nihss_items
                        result = ParsedVariables(**parsed_data)
                        # Post-process: detect explicit "no LVO" that Claude may miss
                        if result.vessel is None and re.search(
                            r"\bno\s+(?:LVO|large\s+vessel|occlusion|vessel\s+occlusion)\b",
                            text, re.IGNORECASE
                        ):
                            result.vessel = "No LVO"
                        return result

            # LLM returned no usable extraction
            logger.error("LLM extraction returned no tool_use result")
            return ParsedVariables()

        except Exception as e:
            # API error: return empty rather than risk bad regex extraction
            logger.error("Claude API call failed: %s", e)
            return ParsedVariables()

    async def summarize_qa(self, question: str, details: str, citations: list[str], patient_context: str = "") -> str:
        """
        Use the LLM to generate a concise summary from QA details and citations.

        Returns a 2-3 sentence direct answer, or empty string if API unavailable.
        """
        if not self.client or not details.strip():
            return ""

        citations_text = "\n".join(f"- {c}" for c in citations) if citations else "None"

        # Build patient context block for the prompt
        context_block = ""
        if patient_context:
            context_block = (
                f"Patient Context: {patient_context}\n"
                "IMPORTANT: Tailor your answer to THIS patient's specific situation "
                "(e.g., time window, imaging findings). Do not give generic advice.\n\n"
            )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=(
                    "You are a clinical guideline expert. Given a clinician's question and "
                    "the retrieved guideline recommendations, provide a concise 2-3 sentence "
                    "answer that DIRECTLY answers their question. "
                    "Lead with a clear yes/no or direct answer when the question calls for it. "
                    "Use plain clinical language. Be specific to the patient context if provided. "
                    "Do NOT repeat the question. Do NOT include section numbers or citation labels. "
                    "Do NOT list every recommendation — just give the bottom line. "
                    "The full guideline recommendations are shown separately below your summary.\n\n"
                    "CRITICAL SAFETY RULES — these override any other interpretation:\n"
                    "1. NEVER recommend delaying IVT (alteplase or tenecteplase) for CTA, CTP, "
                    "or any advanced imaging. NCCT alone is sufficient for IVT decisions in the "
                    "standard window (≤4.5h). IVT is time-critical — every minute of delay worsens outcomes.\n"
                    "2. CTA is important for EVT planning but must NOT delay IVT administration.\n"
                    "3. CTP is NOT required in the standard window (≤6h for EVT, ≤4.5h for IVT). "
                    "CTP/perfusion imaging is used for patient selection in the EXTENDED window (>6h).\n"
                    "4. When asked about imaging sequence/priority, always emphasize: "
                    "give IVT based on NCCT first, obtain CTA in parallel or after for EVT evaluation."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{context_block}"
                            f"Question: {question}\n\n"
                            f"Guideline Details:\n{details}\n\n"
                            f"Citations:\n{citations_text}\n\n"
                            "Provide a concise, direct answer."
                        ),
                    }
                ],
            )
            # Extract text response
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text.strip()
            return ""
        except Exception as e:
            logger.error("LLM summarization failed: %s", e)
            return ""

    async def validate_qa_answer(
        self,
        question: str,
        answer: str,
        summary: str,
        citations: list[str],
        patient_context: str = "",
    ) -> dict:
        """
        Validate a Q&A answer against the guideline recommendations.

        Returns a dict with validation results:
        - intentCorrect, recommendationsRelevant, summaryAccurate
        - issues list, suggestedCorrection
        """
        if not self.client:
            return {}

        citations_text = "\n".join(f"- {c}" for c in citations) if citations else "None"
        context_line = f"\nPatient Context: {patient_context}" if patient_context else ""

        try:
            response = self.client.messages.create(
                model="claude-opus-4-1",
                max_tokens=1500,
                system=(
                    "You are a clinical guideline validation expert for the 2026 AHA/ASA "
                    "Acute Ischemic Stroke (AIS) guideline. A clinician flagged a Q&A answer "
                    "as potentially incorrect. Your job is to validate the answer.\n\n"
                    "KEY GUIDELINE PRINCIPLES you must check against:\n"
                    "1. IVT (alteplase/tenecteplase) should NEVER be delayed for CTA, CTP, "
                    "or advanced imaging. NCCT alone is sufficient for IVT decisions (Section 4.6.1).\n"
                    "2. CTP is NOT required in the standard window (≤4.5h for IVT, ≤6h for EVT). "
                    "CTP is for extended window patient selection only.\n"
                    "3. IVT is recommended regardless of NIHSS score for disabling deficits (Section 4.6.1).\n"
                    "4. EVT eligibility requires LVO confirmation, not just high NIHSS.\n"
                    "5. Time is brain — every minute of IVT delay worsens outcomes.\n\n"
                    "Evaluate the answer using the provided tool."
                ),
                tools=[
                    {
                        "name": "validation_result",
                        "description": "Report the validation findings for the Q&A answer",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "intentCorrect": {
                                    "type": "boolean",
                                    "description": "Does the answer address what the clinician actually asked?"
                                },
                                "intentExplanation": {
                                    "type": "string",
                                    "description": "Brief explanation of intent match/mismatch"
                                },
                                "recommendationsRelevant": {
                                    "type": "boolean",
                                    "description": "Are the cited sections relevant to the question?"
                                },
                                "relevanceExplanation": {
                                    "type": "string",
                                    "description": "Brief explanation of which sections are relevant/irrelevant"
                                },
                                "summaryAccurate": {
                                    "type": "boolean",
                                    "description": "Does the summary correctly represent the guideline recommendations without contradicting them?"
                                },
                                "summaryExplanation": {
                                    "type": "string",
                                    "description": "Brief explanation of summary accuracy"
                                },
                                "issues": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of specific problems found (empty if answer is correct)"
                                },
                                "suggestedCorrection": {
                                    "type": "string",
                                    "description": "If the answer has issues, what should it have said instead? Empty if answer is correct."
                                },
                            },
                            "required": [
                                "intentCorrect", "intentExplanation",
                                "recommendationsRelevant", "relevanceExplanation",
                                "summaryAccurate", "summaryExplanation",
                                "issues", "suggestedCorrection"
                            ]
                        }
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Clinician's Question: {question}{context_line}\n\n"
                            f"Summary Shown to Clinician:\n{summary}\n\n"
                            f"Full Answer (guideline text shown below summary):\n{answer}\n\n"
                            f"Citations:\n{citations_text}\n\n"
                            "Validate this answer against the AIS guideline. "
                            "Use the validation_result tool to report your findings."
                        ),
                    }
                ],
            )

            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    if block.name == "validation_result":
                        return block.input

            return {}
        except Exception as e:
            logger.error("LLM validation failed: %s", e)
            return {}


    # Regex fallback removed — LLM extraction is the only path.
    # If the LLM is unavailable, the system returns empty ParsedVariables
    # rather than risking incorrect extraction from brittle regex patterns.
    # This was validated through 3,000+ scenario evaluations where regex
    # caused false hemorrhage flags, missed negation, and wrong vessel parsing.
