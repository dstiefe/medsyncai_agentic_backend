"""
llm_deny_list.py — deterministic pre-check that blocks patient-specific
treatment decisions from ever reaching the general-knowledge fallback.

The in-scope path answers from the 2026 AIS Guidelines byte-exactly.
The out-of-scope fallback answers from Claude's general clinical
knowledge with a disclaimer. There is a third category — questions
that ARE patient-specific treatment decisions but phrased so that the
parser couldn't route them to the guideline. Those must NOT be answered
from general knowledge; they must route to a safe decline.

Examples of things the deny list must block:

    "Should I give tPA to this 78-year-old on apixaban?"
    "How much heparin does a 70kg adult need?"
    "What antiplatelet should I start after EVT?"
    "Can I dose alteplase in a patient on DOAC?"

These are all questions that a guideline or institutional protocol
should answer — not a language model drawing on unsourced knowledge.
The deny list is the safety floor for the fallback path.

Pure Python keyword matching. No LLM. Fast (~microseconds). Runs
before the fallback LLM is called so a denied question never
incurs LLM latency or cost.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------
#
# A question is denied when it matches BOTH:
#   (a) at least one "treatment decision" verb/phrase, AND
#   (b) at least one "drug/procedure" name
#
# The two-signal rule keeps general-knowledge questions like
# "what is a penumbra" or "how does apixaban work" from being blocked.

_DECISION_PATTERNS = [
    r"\bshould i\s+(give|start|dose|order|administer|prescribe|use|continue|stop|hold|reverse)\b",
    r"\bcan i\s+(give|start|dose|order|administer|prescribe|use|thrombolyse|lyse|treat)\b",
    r"\bdo i\s+(give|start|dose|order|administer|prescribe|use|need to)\b",
    r"\bwhat\s+(dose|amount)\s+(do i|should i|of)\b",
    r"\bhow much\s+\w+\s+(for|do i|should i|to give)\b",
    r"\bhow many\s+\w+\s+(for|do i|should i)\b",
    r"\b(is|are|would|will)\s+(it|this|they)\s+(safe|okay|ok|appropriate)\s+to\b",
    r"\bmy patient\b",
    r"\bthis patient\b",
    r"\bfor this (guy|lady|man|woman|kid|child|case)\b",
    r"\bthe patient (needs|should|would|is on|has)\b",
    r"\bgive\s+(him|her|them|the patient)\b",
]

_DRUG_OR_PROCEDURE_PATTERNS = [
    # Thrombolytics
    r"\b(alteplase|tpa|t-pa|tenecteplase|tnk|tnkase|reteplase|activase|metalyse)\b",
    r"\b(thrombolysis|thrombolytic|fibrinolysis|clot[- ]?buster|lyse|lysing|lysed)\b",
    r"\bivt\b",
    # Thrombectomy
    r"\b(thrombectomy|evt|mechanical thrombectomy|stent retriever|clot retrieval)\b",
    # Anticoagulants
    r"\b(heparin|enoxaparin|lmwh|warfarin|coumadin)\b",
    r"\b(apixaban|eliquis|rivaroxaban|xarelto|dabigatran|pradaxa|edoxaban|savaysa)\b",
    r"\b(doac|noac|direct oral anticoagulant)\b",
    # Antiplatelets
    r"\b(aspirin|asa|clopidogrel|plavix|ticagrelor|brilinta|prasugrel|effient)\b",
    r"\b(antiplatelet|dual antiplatelet|dapt)\b",
    # BP drugs
    r"\b(labetalol|nicardipine|clevidipine|hydralazine|nitroprusside|nitroglycerin|esmolol)\b",
    # Reversal agents
    r"\b(prothrombin complex|pcc|kcentra|idarucizumab|praxbind|andexanet|andexxa|vitamin k|ffp|cryoprecipitate|tranexamic acid|txa)\b",
]


_DECISION_REGEX = re.compile("|".join(_DECISION_PATTERNS), re.IGNORECASE)
_DRUG_REGEX = re.compile("|".join(_DRUG_OR_PROCEDURE_PATTERNS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DenyCheckResult:
    """Output of `check_deny_list`.

    - `denied`: True when the question should be blocked from the
      fallback LLM and routed to a safe decline message instead.
    - `reasons`: which signals fired. Surfaced in the audit trail.
    - `matched_decision`: the decision phrase that matched (for logs).
    - `matched_drug`: the drug/procedure phrase that matched (for logs).
    """

    denied: bool
    reasons: List[str]
    matched_decision: str = ""
    matched_drug: str = ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


SAFE_DECLINE_MESSAGE = (
    "I can answer questions about the 2026 AHA/ASA Acute Ischemic Stroke "
    "Guidelines and related clinical concepts, but I can't make patient-"
    "specific treatment decisions. For a dosing or treatment decision on "
    "a specific patient, please consult the guideline directly or your "
    "institution's protocol."
)


def check_deny_list(question: str) -> DenyCheckResult:
    """
    Scan a question for patient-specific treatment-decision signals.

    Returns `denied=True` when the question BOTH contains a decision
    verb/phrase AND names a drug or procedure. Pure regex, no LLM.
    """
    if not question or not question.strip():
        return DenyCheckResult(denied=False, reasons=[])

    decision_match = _DECISION_REGEX.search(question)
    drug_match = _DRUG_REGEX.search(question)

    if decision_match and drug_match:
        return DenyCheckResult(
            denied=True,
            reasons=[
                "treatment_decision_verb_present",
                "drug_or_procedure_named",
            ],
            matched_decision=decision_match.group(0),
            matched_drug=drug_match.group(0),
        )

    return DenyCheckResult(denied=False, reasons=[])


__all__ = [
    "DenyCheckResult",
    "SAFE_DECLINE_MESSAGE",
    "check_deny_list",
]
