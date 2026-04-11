import json
import re
import logging
from typing import List, Optional
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
                temperature=0,
                system="""You are a clinical information extraction assistant. Your task is to extract structured clinical information from free-text patient scenarios. You MUST extract ONLY factual information present in the text. Do NOT make clinical inferences, recommendations, or assumptions about missing data. If a value is not mentioned, leave it as null. Return ONLY valid JSON with fields exactly as specified.

IMPORTANT extraction rules:
- "unknown onset", "unwitnessed", "found down" = unknown time of onset. Set timeHours to null, wakeUp to null. This is NOT a wake-up stroke.
- "wake-up stroke", "woke with symptoms" = wakeUp is true. Set wakeUp to true.
- "LKW" = last known well. Extract the time value to lastKnownWellHours as HOURS (a number).
  - "LKW 12h" or "LKW 12 hours" → lastKnownWellHours = 12
  - "LKW at 2300" or "LKW 23:00" or "went to bed at 11pm" → These are CLOCK TIMES, not hours.
    You CANNOT convert clock times to hours without knowing the current time.
    Set lastKnownWellHours to null and set lkwClockTime to the clock time string (e.g., "23:00").
  - "LKW yesterday at 10pm" → Set lastKnownWellHours to null, lkwClockTime to "22:00".
- If onset time and LKW are different concepts, extract both separately.
- For wake-up strokes: set wakeUp to true. If a bedtime/LKW clock time is given, extract it to lkwClockTime.
  The system will calculate hours from the clock time separately.
- For vessel: extract the specific vessel name (M1, M2, ICA, basilar, etc.), not just "LVO".
  Do NOT include laterality in the vessel field — laterality goes in "side".
  "right MCA-M1" → vessel = "M1", side = "right"
  "left vertebral" → vessel = "vertebral", side = "left"
  "bilateral ICA" → vessel = "ICA", side = "bilateral"
- For side: extract laterality as a separate field. Valid values: "left", "right", "bilateral". null if not mentioned.
- "proximal M2" or "dominant M2" → vessel = "M2", m2Dominant = true.
- "non-dominant M2" or "codominant M2" → vessel = "M2", m2Dominant = false.""",
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
                                "lastKnownWellHours": {"type": ["number", "null"], "minimum": 0, "description": "Hours since last known well/normal. ONLY use when a duration in hours is given (e.g., 'LKW 12h'). Do NOT convert clock times to hours."},
                                "lkwClockTime": {"type": ["string", "null"], "description": "Clock time of last known well if given as a time of day (e.g., '23:00', '11:00 PM', '2300'). Normalize to 24h format HH:MM."},
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
                                "side": {"type": ["string", "null"], "description": "Laterality of the occlusion: 'left', 'right', or 'bilateral'. Extract separately from the vessel name. null if not mentioned."},
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
                        # Post-process: split side from vessel if LLM absorbed it
                        if result.vessel and result.side is None:
                            side_match = re.match(
                                r"^(left|right|bilateral)\s+(.+)$",
                                result.vessel,
                                re.IGNORECASE,
                            )
                            if side_match:
                                result.side = side_match.group(1).lower()
                                result.vessel = side_match.group(2).strip()
                                logger.info("Post-process: split side='%s' from vessel='%s'", result.side, result.vessel)
                        return result

            # LLM returned no usable extraction
            logger.error("LLM extraction returned no tool_use result")
            return ParsedVariables()

        except Exception as e:
            # API error: return empty rather than risk bad regex extraction
            logger.error("Claude API call failed: %s", e)
            return ParsedVariables()

    async def summarize_qa(
        self, question: str, details: str,
        citations: List[str], patient_context: str = "",
        conversation_history: Optional[List[dict]] = None,
    ) -> dict:
        """
        Use the LLM to generate a clinical answer from section content.

        Returns dict with:
          - "summary": the answer text
          - "cited_recs": list of rec numbers the LLM used (e.g., [2, 7, 9])

        Returns {"summary": "", "cited_recs": []} if API unavailable.
        """
        empty = {"summary": "", "cited_recs": []}
        if not self.client or not details.strip():
            return empty

        # Build patient context block for the prompt
        context_block = ""
        if patient_context:
            context_block = (
                f"Patient Context: {patient_context}\n"
                "IMPORTANT: Tailor your answer to THIS patient's specific situation "
                "(e.g., time window, imaging findings). Do not give generic advice.\n\n"
            )

        # Build conversation history block so the LLM knows prior context
        history_block = ""
        if conversation_history:
            turns = []
            for turn in conversation_history[-6:]:  # last 3 exchanges max
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if content:
                    turns.append(f"{role.capitalize()}: {content}")
            if turns:
                history_block = (
                    "Previous conversation:\n"
                    + "\n".join(turns)
                    + "\n\nAnswer the current question in the context of this conversation.\n\n"
                )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                temperature=0,
                system=(
                    "You are a clinical colleague answering questions about the 2026 AHA/ASA "
                    "AIS Guidelines. Use ONLY the provided guideline content. No outside knowledge.\n\n"
                    "HOW TO ANSWER:\n"
                    "Answer the way a knowledgeable colleague would — directly, conversationally, "
                    "and visually scannable. Clinicians skim; structure the answer so the key "
                    "points jump out.\n\n"
                    "Structure:\n"
                    "1. Open with ONE short lead-in sentence that directly answers the question "
                    "(a number, threshold, yes/no, drug name, or the core clinical bottom line).\n"
                    "2. Follow with a bulleted list of the supporting specifics. Use '- ' for "
                    "bullets. Put a short scan anchor (e.g., 'Before IVT', 'Hypoxic patients') "
                    "at the start of each bullet, followed by ' — ' and the detail.\n"
                    "3. Each bullet is one crisp clause. No filler. No repetition of the lead-in.\n"
                    "4. Aim for 2–6 bullets. If the answer is genuinely one atomic fact, a single "
                    "sentence (no bullets) is fine.\n"
                    "5. If the guideline does not give a definitive answer, say so plainly in the "
                    "lead-in — do not hedge when a clear answer exists.\n\n"
                    "EXAMPLES:\n\n"
                    "Q: What BP threshold makes a patient ineligible for IVT?\n"
                    "A: BP must be controlled below specific thresholds before and after IVT.\n"
                    "- Before IVT — SBP <185 mm Hg and DBP <110 mm Hg (COR 1, LOE B-NR).\n"
                    "- After IVT — maintain BP <180/105 mm Hg for 24 hours (COR 1, LOE B-R).\n\n"
                    "Q: Can I give tPA to a patient already on aspirin?\n"
                    "A: Yes — prior antiplatelet use does not exclude IVT.\n"
                    "- IVT is recommended for eligible patients already on antiplatelet therapy "
                    "(COR 1, LOE B-NR).\n"
                    "- Avoid IV aspirin within 90 minutes of IVT (COR 3: Harm, LOE B-R).\n\n"
                    "Q: What oxygen target should I use?\n"
                    "A: Target SpO2 >94% only when the patient is hypoxic.\n"
                    "- Hypoxic patients — supplemental O2 to maintain SpO2 >94% "
                    "(COR 1, LOE C-LD).\n"
                    "- Non-hypoxic patients ineligible for EVT — supplemental O2 is not "
                    "recommended (COR 3: No Benefit, LOE B-R).\n\n"
                    "RULES:\n"
                    "- Use ONLY the provided text. No outside knowledge.\n"
                    "- Do NOT editorialize ('However', 'Additionally', 'It is important to note').\n"
                    "- Do NOT reference internal document structure (Table 4, Figure 3, "
                    "Section 4.3). Present the content, not the location.\n"
                    "- Copy COR and LOE values exactly (COR 2a stays COR 2a, never COR 2).\n"
                    "- Preserve hedging language from recommendations ('may be reasonable', "
                    "'is uncertain').\n"
                    "- When recommendations have different COR levels for different scenarios, "
                    "put each in its own bullet.\n"
                    "- Do NOT repeat the question.\n"
                    "- Do NOT use markdown bold (**), italics, or headers — the UI renders "
                    "plain text and asterisks appear literally. Use bullets ('- ') only.\n"
                    "- Only cite recommendations that directly answer the question.\n\n"
                    "RESPONSE FORMAT:\n"
                    "Return JSON: {\"summary\": \"answer text\", \"cited_recs\": [5, 7]}\n"
                    "The summary value may contain newlines and '- ' bullets. Keep JSON valid — "
                    "escape embedded newlines as \\n.\n"
                    "cited_recs = integer rec numbers you cited in the answer."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{history_block}"
                            f"{context_block}"
                            f"Question: {question}\n\n"
                            f"Guideline Content:\n{details}\n\n"
                            "Return JSON with summary and cited_recs."
                        ),
                    }
                ],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()

                    # ── Extract JSON from LLM output ──
                    # The LLM sometimes wraps JSON in ```json...``` or
                    # appends free-text after the closing ```.  Extract
                    # the first valid JSON object we can find.
                    json_str = raw

                    # Strategy 1: strip code fences and take content between them
                    fence_match = re.search(
                        r"```(?:json)?\s*(\{.*?\})\s*```",
                        raw,
                        re.DOTALL,
                    )
                    if fence_match:
                        json_str = fence_match.group(1).strip()
                    elif raw.startswith("```"):
                        # Opening fence with no closing — strip it and hope
                        json_str = re.sub(r"^```(?:json)?\s*", "", raw).strip()

                    # Strategy 2: find first { ... } in the text
                    if not json_str.startswith("{"):
                        brace_match = re.search(r"\{.*\}", json_str, re.DOTALL)
                        if brace_match:
                            json_str = brace_match.group(0)

                    # Parse JSON response
                    try:
                        parsed = json.loads(json_str)
                        summary = parsed.get("summary", "")
                        cited = parsed.get("cited_recs", [])
                        # Clean summary text — UI renders plain text, so
                        # strip markdown bold/headers but keep '- ' bullets.
                        summary = summary.replace("**", "")
                        summary = re.sub(r"^#+\s*", "", summary, flags=re.MULTILINE)
                        # Normalize any stray • to '- '
                        summary = summary.replace("• ", "- ").replace("•", "-")
                        summary = summary.strip()
                        return {
                            "summary": summary,
                            "cited_recs": [int(r) for r in cited],
                        }
                    except (json.JSONDecodeError, ValueError):
                        # LLM didn't return valid JSON — strip any JSON/fence
                        # artifacts and return clean text
                        logger.warning("LLM summary not JSON, using raw text: %.100s", raw)
                        text = raw
                        # Remove code fences
                        text = re.sub(r"```(?:json)?", "", text)
                        # Remove JSON wrapper artifacts
                        text = re.sub(r'^\s*\{\s*"summary"\s*:\s*"', "", text)
                        text = re.sub(r'",?\s*"cited_recs"\s*:\s*\[[\d,\s]*\]\s*\}\s*', "\n", text)
                        text = text.replace("**", "")
                        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
                        text = text.strip()
                        return {"summary": text, "cited_recs": []}
            return empty
        except Exception as e:
            logger.error("LLM summarization failed: %s", e)
            return empty

    async def extract_from_section(
        self,
        question: str,
        section_content: dict,
        question_type: str,
    ) -> str:
        """
        Extract an answer from section RSS/synopsis/knowledgeGaps using the LLM.

        question_type: "evidence" or "knowledge_gap"
        Returns extracted answer text, or empty string if API unavailable.
        """
        if not self.client:
            return ""

        # Build the source text block from gathered section content
        text_parts: List[str] = []

        if question_type == "evidence":
            for entry in section_content.get("rss", []):
                rec = entry.get("recNumber", "")
                label = f"[RSS, Rec {rec}]" if rec else "[RSS]"
                text_parts.append(f"{label}\n{entry['text']}")
            for entry in section_content.get("synopsis", []):
                text_parts.append(f"[Synopsis, Section {entry['section']}]\n{entry['text']}")
        elif question_type == "knowledge_gap":
            for entry in section_content.get("knowledge_gaps", []):
                text_parts.append(f"[Knowledge Gaps, Section {entry['section']}]\n{entry['text']}")
            # Include synopsis for additional context
            for entry in section_content.get("synopsis", []):
                text_parts.append(f"[Synopsis, Section {entry['section']}]\n{entry['text']}")

        source_text = "\n\n".join(text_parts)
        if not source_text.strip():
            return ""

        # Truncate to keep context manageable — evidence questions need more
        # room to include all RSS entries from the target section(s).
        max_context = 20000 if question_type == "evidence" else 6000
        if len(source_text) > max_context:
            source_text = source_text[:max_context] + "\n\n[Truncated for length]"

        mode_instruction = {
            "evidence": (
                "Extract the evidence, rationale, and supporting data that answers the "
                "clinician's question. Include specific study names, trial results, and "
                "key findings mentioned in the text. Be specific and cite the data."
            ),
            "knowledge_gap": (
                "Extract the knowledge gaps, areas of uncertainty, and future research "
                "directions that are relevant to the clinician's question. Be specific "
                "about what remains unknown or needs further study."
            ),
        }.get(question_type, "")

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                temperature=0,
                system=(
                    "You are a clinical guideline expert. You answer questions using ONLY "
                    "the provided guideline text. Do not use any outside knowledge.\n\n"
                    f"{mode_instruction}\n\n"
                    "Rules:\n"
                    "- Use only information present in the provided text\n"
                    "- Be concise but thorough (3-5 sentences)\n"
                    "- Use plain clinical language — no bold (**) or headers (##). Bullets and simple tables are OK when helpful.\n"
                    "- If the provided text does not contain relevant information, say so clearly\n"
                    "- Do NOT repeat the question"
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n\n"
                            f"Guideline Text:\n{source_text}\n\n"
                            "Provide a direct answer based only on the text above."
                        ),
                    }
                ],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text.strip()
                    # Strip markdown formatting
                    text = text.replace("**", "")
                    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
                    return text
            return ""
        except Exception as e:
            logger.error("LLM section extraction failed: %s", e)
            return ""

    async def validate_qa_answer(
        self,
        question: str,
        answer: str,
        summary: str,
        citations: List[str],
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
                temperature=0,
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
