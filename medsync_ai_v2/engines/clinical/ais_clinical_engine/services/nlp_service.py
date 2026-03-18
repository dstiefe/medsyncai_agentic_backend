import re
import logging
from typing import Optional
from ..models.clinical import ParsedVariables, NIHSSItems
from medsync_ai_v2.shared.llm_client import get_llm_client

logger = logging.getLogger("medsync.nlp")

# Tool schema for clinical variable extraction
EXTRACTION_TOOL = {
    "name": "extract_clinical_variables",
    "description": "Extract structured clinical variables from scenario text",
    "input_schema": {
        "type": "object",
        "properties": {
            "age": {"type": ["integer", "null"], "minimum": 0, "maximum": 120},
            "sex": {"type": ["string", "null"], "description": "Patient sex. Return 'male' or 'female' only."},
            "timeHours": {"type": ["number", "null"], "minimum": 0, "description": "Hours from symptom onset to presentation"},
            "lastKnownWellHours": {"type": ["number", "null"], "minimum": 0, "description": "Hours since last known well/normal (especially for wake-up strokes or unknown onset)"},
            "wakeUp": {"type": ["boolean", "null"]},
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
            "recentDOAC": {"type": ["boolean", "null"]},
            # Additional Table 8 relative contraindications
            "preExistingDisability": {"type": ["boolean", "null"]},
            "intracranialVascularMalformation": {"type": ["boolean", "null"]},
            "recentSTEMI": {"type": ["boolean", "null"]},
            "stemiDays": {"type": ["integer", "null"]},
            "acutePericarditis": {"type": ["boolean", "null"]},
            "cardiacThrombus": {"type": ["boolean", "null"]},
            "recentDuralPuncture": {"type": ["boolean", "null"]},
            "recentArterialPuncture": {"type": ["boolean", "null"]},
            # Additional Table 8 benefit-over-risk conditions
            "angiographicProceduralStroke": {"type": ["boolean", "null"]},
            "remoteGIGUBleeding": {"type": ["boolean", "null"]},
            "historyMI": {"type": ["boolean", "null"]},
            "recreationalDrugUse": {"type": ["boolean", "null"]},
            "strokeMimic": {"type": ["boolean", "null"]}
        },
        "required": []
    }
}

SYSTEM_PROMPT = (
    "You are a clinical information extraction assistant. Your task is to "
    "extract structured clinical information from free-text patient scenarios. "
    "You MUST extract ONLY factual information present in the text. Do NOT make "
    "clinical inferences, recommendations, or assumptions about missing data. "
    "If a value is not mentioned, leave it as null. Return ONLY valid JSON with "
    "fields exactly as specified."
)


class NLPService:
    """NLP service for parsing clinical scenarios using v2's LLMClient."""

    def __init__(self):
        """Initialize NLP service with v2's LLMClient."""
        self.llm_client = get_llm_client()
        logger.info("NLP service initialized with LLMClient (provider=%s)", self.llm_client.provider)

    async def parse_scenario(self, text: str) -> ParsedVariables:
        """
        Parse scenario using LLMClient with tool_use.

        Falls back to regex if API call fails.
        """
        try:
            response = await self.llm_client.call(
                system_prompt=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                tools=[EXTRACTION_TOOL],
            )

            # LLMClient returns {"type": "tool_use", "tool_input": {...}} directly
            if response.get("type") == "tool_use" and response.get("tool_name") == "extract_clinical_variables":
                parsed_data = response["tool_input"]
                logger.info("=== LLM EXTRACTION RESULT ===")
                logger.info("%s", parsed_data)

                # Create ParsedVariables, handling nihssItems
                nihss_items = None
                if parsed_data.get("nihssItems"):
                    nihss_items = NIHSSItems(**parsed_data["nihssItems"])
                parsed_data["nihssItems"] = nihss_items
                result = ParsedVariables(**parsed_data)

                # Post-process: detect explicit "no LVO" that LLM may miss
                if result.vessel is None and re.search(
                    r"\bno\s+(?:LVO|large\s+vessel|occlusion|vessel\s+occlusion)\b",
                    text, re.IGNORECASE
                ):
                    result.vessel = "No LVO"

                return result

            # No tool use in response — fall back to regex
            logger.warning("LLM did not use extraction tool, falling back to regex")
            return self.parse_scenario_regex(text)

        except Exception as e:
            logger.error("LLM call failed, falling back to regex: %s", e)
            return self.parse_scenario_regex(text)

    async def summarize_qa(
        self, question: str, details: str, citations: list[str], patient_context: str = ""
    ) -> str:
        """
        Use the LLM to generate a concise summary from QA details and citations.

        Returns a 2-3 sentence direct answer, or empty string if unavailable.
        """
        if not details.strip():
            return ""

        citations_text = "\n".join(f"- {c}" for c in citations) if citations else "None"

        context_block = ""
        if patient_context:
            context_block = (
                f"Patient Context: {patient_context}\n"
                "IMPORTANT: Tailor your answer to THIS patient's specific situation "
                "(e.g., time window, imaging findings). Do not give generic advice.\n\n"
            )

        try:
            result = await self.llm_client.call(
                system_prompt=(
                    "You are a clinical guideline expert. Given a clinician's question and "
                    "the retrieved guideline recommendations, provide a concise 2-3 sentence "
                    "answer that DIRECTLY answers their question. "
                    "Lead with a clear yes/no or direct answer when the question calls for it. "
                    "Use plain clinical language. Be specific to the patient context if provided. "
                    "Do NOT repeat the question. Do NOT include section numbers or citation labels. "
                    "Do NOT list every recommendation — just give the bottom line.\n\n"
                    "CRITICAL SAFETY RULES:\n"
                    "1. NEVER recommend delaying IVT for CTA, CTP, or any advanced imaging.\n"
                    "2. CTA is important for EVT planning but must NOT delay IVT.\n"
                    "3. CTP is NOT required in the standard window.\n"
                    "4. IVT based on NCCT first, CTA in parallel or after for EVT evaluation."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"{context_block}"
                        f"Question: {question}\n\n"
                        f"Guideline Details:\n{details}\n\n"
                        f"Citations:\n{citations_text}\n\n"
                        "Provide a concise, direct answer."
                    ),
                }],
                max_tokens=300,
            )
            return result.get("content", "")

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

        Returns a dict with validation results.
        """
        citations_text = "\n".join(f"- {c}" for c in citations) if citations else "None"
        context_line = f"\nPatient Context: {patient_context}" if patient_context else ""

        validation_tool = {
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
                        "description": "Does the summary correctly represent the guideline recommendations?"
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
                        "description": "If the answer has issues, what should it have said instead? Empty if correct."
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

        try:
            result = await self.llm_client.call(
                system_prompt=(
                    "You are a clinical guideline validation expert for the 2026 AHA/ASA "
                    "Acute Ischemic Stroke (AIS) guideline. A clinician flagged a Q&A answer "
                    "as potentially incorrect. Your job is to validate the answer.\n\n"
                    "KEY GUIDELINE PRINCIPLES you must check against:\n"
                    "1. IVT (alteplase/tenecteplase) should NEVER be delayed for CTA, CTP, "
                    "or advanced imaging. NCCT alone is sufficient for IVT decisions (Section 4.6.1).\n"
                    "2. CTP is NOT required in the standard window (<=4.5h for IVT, <=6h for EVT).\n"
                    "3. IVT is recommended regardless of NIHSS score for disabling deficits (Section 4.6.1).\n"
                    "4. EVT eligibility requires LVO confirmation, not just high NIHSS.\n"
                    "5. Time is brain — every minute of IVT delay worsens outcomes.\n\n"
                    "Evaluate the answer using the provided tool."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Clinician's Question: {question}{context_line}\n\n"
                        f"Summary Shown to Clinician:\n{summary}\n\n"
                        f"Full Answer (guideline text shown below summary):\n{answer}\n\n"
                        f"Citations:\n{citations_text}\n\n"
                        "Validate this answer against the AIS guideline. "
                        "Use the validation_result tool to report your findings."
                    ),
                }],
                tools=[validation_tool],
                max_tokens=1500,
            )

            if result.get("type") == "tool_use" and result.get("tool_name") == "validation_result":
                return result["tool_input"]

            return {}
        except Exception as e:
            logger.error("LLM validation failed: %s", e)
            return {}

    def parse_scenario_regex(self, text: str) -> ParsedVariables:
        """
        Parse scenario using regex patterns.

        Enhanced with patterns from PM's backend.
        """
        parsed = ParsedVariables()

        # Age: "65 year old", "65yo", "age 65", "72-year-old"
        age_match = re.search(r"(\d{1,3})\s*[-\s]*(?:y/?o|year|yr)", text, re.IGNORECASE)
        if age_match:
            parsed.age = int(age_match.group(1))

        # Sex: "male", "female", "65/M", "65/F", "woman", "man"
        age_sex_match = re.search(r"\d{1,3}\s*/\s*([MF])\b", text)
        if age_sex_match:
            parsed.sex = "male" if age_sex_match.group(1).upper() == "M" else "female"
        elif re.search(r"\b(male|man|boy)\b", text, re.IGNORECASE):
            parsed.sex = "male"
        elif re.search(r"\b(female|woman|girl)\b", text, re.IGNORECASE):
            parsed.sex = "female"

        # NIHSS: "NIHSS 18", "nihss of 18"
        nihss_match = re.search(r"nihss\s*(?:of|:)?\s*(\d+)", text, re.IGNORECASE)
        if nihss_match:
            parsed.nihss = int(nihss_match.group(1))

        # ASPECTS: "ASPECTS 7", "aspects of 7"
        aspects_match = re.search(r"aspects\s*(?:of|:)?\s*(\d+)", text, re.IGNORECASE)
        if aspects_match:
            parsed.aspects = int(aspects_match.group(1))

        # Vessel: explicit "no LVO" first, then named vessels
        if re.search(r"\bno\s+(?:LVO|large\s+vessel|occlusion|vessel\s+occlusion)\b", text, re.IGNORECASE):
            parsed.vessel = "No LVO"
        else:
            for vessel in ["M1", "M2", "M3", "M4", "M5", "ICA", "T-ICA", "basilar", "ACA", "A1", "A2", "A3", "PCA", "P1", "P2", "vertebral"]:
                if re.search(rf"\b{vessel}\b", text, re.IGNORECASE):
                    parsed.vessel = vessel
                    break

        # M2 dominant/nondominant qualifier
        if parsed.vessel and parsed.vessel.upper() == "M2":
            if re.search(r"\b(?:nondominant|non-dominant|codominant|co-dominant)\b", text, re.IGNORECASE):
                parsed.m2Dominant = False
            elif re.search(r"\bdominant\b", text, re.IGNORECASE):
                parsed.m2Dominant = True

        # Time from onset: "2 hours", "2h", "120 minutes"
        time_match = re.search(r"(\d+\.?\d*)\s*(?:h|hour|min)", text, re.IGNORECASE)
        if time_match:
            value = float(time_match.group(1))
            if re.search(r"min", text[time_match.start():time_match.end()], re.IGNORECASE):
                value = value / 60
            parsed.timeHours = value

        # Last known well: "LKW 8h ago", "last known well 10 hours", "last seen normal 6h"
        lkw_match = re.search(r"(?:lkw|last\s+known\s+well|last\s+seen\s+normal|last\s+normal)\s*(?:of|:)?\s*(\d+\.?\d*)\s*(?:h|hour|hr)", text, re.IGNORECASE)
        if lkw_match:
            parsed.lastKnownWellHours = float(lkw_match.group(1))

        # mRS: "mRS 1", "mrs of 1"
        mrs_match = re.search(r"m?rs\s*(?:of|:)?\s*(\d)", text, re.IGNORECASE)
        if mrs_match:
            parsed.prestrokeMRS = int(mrs_match.group(1))

        # Blood pressure: "140/90", "sbp 140"
        bp_match = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", text)
        if bp_match:
            parsed.sbp = int(bp_match.group(1))
            parsed.dbp = int(bp_match.group(2))

        # Hemorrhage: "hemorrhage", "bleed"
        if re.search(r"\b(hemorrhage|bleed|hematoma|ICH)\b", text, re.IGNORECASE):
            parsed.hemorrhage = True

        # Antiplatelet: "aspirin", "clopidogrel", "on aspirin"
        if re.search(r"\b(aspirin|clopidogrel|plavix|antiplatelet)\b", text, re.IGNORECASE):
            parsed.onAntiplatelet = True

        # Anticoagulant: "warfarin", "apixaban", "on coumadin"
        if re.search(r"\b(warfarin|apixaban|dabigatran|edoxaban|rivaroxaban|coumadin|anticoagulant|doac)\b", text, re.IGNORECASE):
            parsed.onAnticoagulant = True

        # Sickle cell: "sickle cell"
        if re.search(r"\bsickle\s*cell\b", text, re.IGNORECASE):
            parsed.sickleCell = True

        # DWI-FLAIR: "dwi-flair mismatch"
        if re.search(r"\bdwi\s*-?\s*flair\b", text, re.IGNORECASE):
            parsed.dwiFlair = True

        # Penumbra: "penumbra"
        if re.search(r"\bpenumbra\b", text, re.IGNORECASE):
            parsed.penumbra = True

        # Wake-up stroke: "wake-up", "woke up with"
        if re.search(r"\b(wake\s*-?\s*up|woke\s+up|awoke)\b", text, re.IGNORECASE):
            parsed.wakeUp = True

        # Platelets: "platelets 80k", "platelets 80000"
        plat_match = re.search(r"platelets\s*(?:of|:)?\s*(\d+\.?\d*)\s*[kK]?", text, re.IGNORECASE)
        if plat_match:
            value = float(plat_match.group(1))
            if value < 1000:
                value *= 1000
            parsed.platelets = int(value)

        # INR, aPTT, PT
        inr_match = re.search(r"inr\s*(?:of|:)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        if inr_match:
            parsed.inr = float(inr_match.group(1))

        aptt_match = re.search(r"aptt\s*(?:of|:)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        if aptt_match:
            parsed.aptt = float(aptt_match.group(1))

        pt_match = re.search(r"\bpt\s*(?:of|:)?\s*(\d+\.?\d*)", text, re.IGNORECASE)
        if pt_match:
            parsed.pt = float(pt_match.group(1))

        return parsed
