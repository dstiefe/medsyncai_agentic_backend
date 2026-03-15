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
            "sex": {"type": ["string", "null"]},
            "timeHours": {"type": ["number", "null"], "minimum": 0},
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
            "vessel": {"type": ["string", "null"]},
            "side": {"type": ["string", "null"]},
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
            "nonDisabling": {"type": ["boolean", "null"]},
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
                return ParsedVariables(**parsed_data)

            # No tool use in response — fall back to regex
            logger.warning("LLM did not use extraction tool, falling back to regex")
            return self.parse_scenario_regex(text)

        except Exception as e:
            logger.error("LLM call failed, falling back to regex: %s", e)
            return self.parse_scenario_regex(text)

    def parse_scenario_regex(self, text: str) -> ParsedVariables:
        """
        Parse scenario using regex patterns.

        Patterns for common clinical variables.
        """
        parsed = ParsedVariables()

        # Age: "65 year old", "65yo", "age 65", "72-year-old"
        age_match = re.search(r"(\d{1,3})\s*[-\s]*(?:y/?o|year|yr)", text, re.IGNORECASE)
        if age_match:
            parsed.age = int(age_match.group(1))

        # Sex: "male", "female", "woman", "man"
        if re.search(r"\b(male|man|boy)\b", text, re.IGNORECASE):
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

        # Vessel: M1, M2, ICA, basilar, ACA, PCA
        for vessel in ["M1", "M2", "ICA", "basilar", "ACA", "PCA", "T-ICA"]:
            if re.search(rf"\b{vessel}\b", text, re.IGNORECASE):
                parsed.vessel = vessel
                break

        # Time from onset: "2 hours", "2h", "120 minutes"
        time_match = re.search(r"(\d+\.?\d*)\s*(?:h|hour|min)", text, re.IGNORECASE)
        if time_match:
            value = float(time_match.group(1))
            # If in minutes, convert to hours
            if re.search(r"min", text[time_match.start():time_match.end()], re.IGNORECASE):
                value = value / 60
            parsed.timeHours = value

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
            if value < 1000:  # Assume it's in thousands
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
