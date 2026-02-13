"""
Clinical Support Engine

Evaluates AIS treatment eligibility against 2026 AHA/ASA guidelines.
Hybrid approach: deterministic Python rules + OpenAI vector search for edge cases.

Pipeline:
    1. PatientParser.parse()        — regex extraction of structured patient data
    2. EligibilityRules.evaluate_all() — Python rule engine (IVT/EVT pathways)
    3. _search_guidelines()         — OpenAI file_search for edge cases (AIS guidelines vector store)
    4. Returns standard engine contract → clinical_output_agent formats response
"""

import asyncio
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

from medsync_ai_v2.base_engine import BaseEngine
from medsync_ai_v2 import config
from .trial_metrics import TrialMetricsLookup
from .context_review import ContextReview


# ═══════════════════════════════════════════════════════════════════
# 1. DATA MODELS
# ═══════════════════════════════════════════════════════════════════

class Eligibility(str, Enum):
    YES = "YES"
    NO = "NO"
    CONDITIONAL = "CONDITIONAL"
    UNCERTAIN = "UNCERTAIN"
    CONTRAINDICATED = "CONTRAINDICATED"

class COR(str, Enum):
    """AHA Class of Recommendation"""
    COR_1 = "1"
    COR_2A = "2a"
    COR_2B = "2b"
    COR_3_NO_BENEFIT = "3: No Benefit"
    COR_3_HARM = "3: Harm"

class LOE(str, Enum):
    """AHA Level of Evidence"""
    A = "A"
    B_R = "B-R"
    B_NR = "B-NR"
    C_LD = "C-LD"
    C_EO = "C-EO"


@dataclass
class PatientPresentation:
    """Structured patient data extracted from natural language input."""
    age: Optional[int] = None
    sex: Optional[str] = None

    # Time
    last_known_well_hours: Optional[float] = None
    wake_up_stroke: bool = False
    unknown_onset: bool = False

    # Clinical scores
    nihss: Optional[int] = None
    mrs_pre: Optional[int] = None
    aspects: Optional[int] = None
    pc_aspects: Optional[int] = None

    # Imaging
    occlusion_location: Optional[str] = None
    occlusion_segment: Optional[str] = None
    occlusion_segment_unspecified: bool = False
    lvo: bool = False
    mvo: bool = False
    anterior_circulation: bool = True
    posterior_circulation: bool = False

    # Perfusion imaging
    has_perfusion_imaging: bool = False
    core_volume_ml: Optional[float] = None
    penumbra_volume_ml: Optional[float] = None
    mismatch_ratio: Optional[float] = None

    # Comorbidities
    on_anticoagulation: bool = False
    anticoagulant_type: Optional[str] = None
    inr: Optional[float] = None
    dementia: bool = False
    recent_surgery: bool = False
    prior_stroke_recent: bool = False

    # Treatment already given
    ivt_given: bool = False
    evt_given: bool = False

    # Raw text for LLM context
    raw_presentation: str = ""


@dataclass
class EligibilityResult:
    """Result of a single eligibility assessment."""
    treatment: str = ""
    eligibility: Eligibility = Eligibility.UNCERTAIN
    cor: Optional[str] = None
    loe: Optional[str] = None
    reasoning: str = ""
    key_criteria: list = field(default_factory=list)
    relevant_trials: list = field(default_factory=list)
    guideline_section: str = ""
    page_references: list = field(default_factory=list)
    caveats: list = field(default_factory=list)
    needs_vector_search: bool = False


@dataclass
class CompletenessResult:
    """Result of checking whether enough data exists to assess each pathway."""
    # Per-pathway assessability
    can_assess_ivt: bool = False
    can_assess_evt: bool = False
    can_assess_extended: bool = False
    can_assess_large_core: bool = False

    # What's missing, organized by tier
    missing_critical: list = field(default_factory=list)    # Tier 1: blocks pathway assessment
    missing_important: list = field(default_factory=list)   # Tier 2: affects but doesn't block
    assumptions_made: list = field(default_factory=list)     # Defaults applied

    # Clarification control
    should_ask_clarification: bool = False
    clarification_questions: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# 2. PATIENT PARSER (Deterministic)
# ═══════════════════════════════════════════════════════════════════

class PatientParser:
    """Deterministic regex extraction of structured patient data."""

    @staticmethod
    def parse(text: str) -> PatientPresentation:
        p = PatientPresentation(raw_presentation=text)
        t = text.lower()

        # Age
        age_match = re.search(r'(\d{1,3})[\s-]*(?:year|yr|y/?o)', t)
        if age_match:
            p.age = int(age_match.group(1))

        # Sex
        if any(w in t for w in ['female', 'woman', ' f,', ' f ']):
            p.sex = "female"
        elif any(w in t for w in ['male', ' man', ' m,', ' m ']):
            p.sex = "male"

        # Last known well
        lkw_match = re.search(r'last\s+known\s+well\s+(\d+\.?\d*)\s*(hour|hr|h)', t)
        if lkw_match:
            p.last_known_well_hours = float(lkw_match.group(1))
        else:
            lkw_match = re.search(r'(\d+\.?\d*)\s*(hour|hr|h)\s*(?:ago|since|from)', t)
            if lkw_match:
                p.last_known_well_hours = float(lkw_match.group(1))

        # LKW shorthand: "LKW 3h"
        if p.last_known_well_hours is None:
            lkw_short = re.search(r'lkw\s+(\d+\.?\d*)\s*h?', t)
            if lkw_short:
                p.last_known_well_hours = float(lkw_short.group(1))

        if 'wake-up' in t or 'wake up stroke' in t or 'woke up with' in t:
            p.wake_up_stroke = True
            p.unknown_onset = True
        if 'unknown onset' in t or 'unwitnessed' in t:
            p.unknown_onset = True

        # NIHSS
        nihss_match = re.search(r'nihss\s*(?:score\s*)?(?:of\s*)?(\d+)', t)
        if nihss_match:
            p.nihss = int(nihss_match.group(1))

        # Pre-stroke mRS
        mrs_match = re.search(r'(?:pre-?stroke\s+)?m?rs\s*(?:score\s*)?(?:of\s*)?(\d)', t)
        if mrs_match:
            p.mrs_pre = int(mrs_match.group(1))
        else:
            mrs_match = re.search(r'mrs\s+(\d)', t)
            if mrs_match:
                p.mrs_pre = int(mrs_match.group(1))

        # ASPECTS
        aspects_match = re.search(r'aspects?\s*(?:score\s*)?(?:of\s*)?(\d+)', t)
        if aspects_match:
            p.aspects = int(aspects_match.group(1))

        # Occlusion location
        occlusion_patterns = [
            r'(?:left|right|bilateral)\s+(?:mca|m1|m2|m3)',
            r'(?:mca|m1|m2)\s+occlusion',
            r'(?:ica|internal\s+carotid)\s+(?:occlusion|terminus)',
            r'basilar\s+(?:artery\s+)?occlusion',
            r'(?:left|right)\s+(?:ica|mca|aca|pca|vertebral|basilar)',
        ]
        for pattern in occlusion_patterns:
            occ_match = re.search(pattern, t)
            if occ_match:
                p.occlusion_location = occ_match.group(0).strip()
                break

        # CTA mention
        if 'cta' in t or 'ct angio' in t or 'ct-a' in t:
            cta_match = re.search(r'cta\s+(?:shows?|demonstrates?|reveals?|confirms?)\s+(.+?)(?:\.|,|$)', t)
            if cta_match and not p.occlusion_location:
                p.occlusion_location = cta_match.group(1).strip()

        # Vessel segment detection
        if re.search(r'\bm1\b', t):
            p.occlusion_segment = "M1"
            p.lvo = True
        elif re.search(r'\bm2\b', t):
            p.occlusion_segment = "M2"
            p.mvo = True
            p.lvo = False
        elif re.search(r'\bm3\b', t) or re.search(r'\bm4\b', t):
            p.occlusion_segment = "distal"
            p.mvo = True
            p.lvo = False
        elif re.search(r'\bica\b|internal\s+carotid|carotid terminus', t):
            p.occlusion_segment = "ICA"
            p.lvo = True
        elif re.search(r'\bbasilar\b', t):
            p.occlusion_segment = "basilar"
            p.lvo = True
        elif re.search(r'\bmca\b|middle\s+cerebral', t):
            p.occlusion_segment_unspecified = True
            p.lvo = True  # Assume M1, but flag it
            p.occlusion_segment = "MCA (segment unspecified)"

        # LVO fallback — only if not already set by segment detection
        if not p.lvo and not p.mvo:
            lvo_keywords = ['lvo', 'large vessel occlusion']
            if any(k in t for k in lvo_keywords):
                p.lvo = True

        # Circulation
        posterior_keywords = ['basilar', 'posterior', 'vertebral', 'pca', 'sca', 'aica', 'pica']
        if any(k in t for k in posterior_keywords):
            p.posterior_circulation = True
            p.anterior_circulation = False

        # MVO fallback — only if not already set by segment detection
        if not p.mvo and not p.occlusion_segment:
            mvo_keywords = ['mvo', 'medium vessel', 'distal']
            if any(k in t for k in mvo_keywords):
                p.mvo = True

        # Perfusion imaging
        if any(k in t for k in ['ctp', 'ct perfusion', 'perfusion imaging', 'dwi-pwi', 'mismatch']):
            p.has_perfusion_imaging = True

        core_match = re.search(r'core\s*(?:volume\s*)?(?:of\s*)?(\d+\.?\d*)\s*ml', t)
        if core_match:
            p.core_volume_ml = float(core_match.group(1))
            p.has_perfusion_imaging = True

        penumbra_match = re.search(r'penumbra\s*(?:volume\s*)?(?:of\s*)?(\d+\.?\d*)\s*ml', t)
        if penumbra_match:
            p.penumbra_volume_ml = float(penumbra_match.group(1))

        mismatch_match = re.search(r'mismatch\s*(?:ratio\s*)?(?:of\s*)?(\d+\.?\d*)', t)
        if mismatch_match:
            p.mismatch_ratio = float(mismatch_match.group(1))

        # Comorbidities
        if 'anticoagul' in t or 'warfarin' in t or 'doac' in t or 'coumadin' in t:
            p.on_anticoagulation = True
            if 'warfarin' in t or 'coumadin' in t:
                p.anticoagulant_type = "warfarin"
            elif any(d in t for d in ['apixaban', 'rivaroxaban', 'dabigatran', 'edoxaban', 'doac']):
                p.anticoagulant_type = "DOAC"

        inr_match = re.search(r'inr\s*(?:of\s*)?(\d+\.?\d*)', t)
        if inr_match:
            p.inr = float(inr_match.group(1))

        if 'dementia' in t or 'cognitive decline' in t or 'alzheimer' in t:
            p.dementia = True

        return p

    @staticmethod
    def assess_completeness(patient: PatientPresentation) -> CompletenessResult:
        """
        Assess whether enough data exists to evaluate each treatment pathway.

        Tier 1 CRITICAL: blocks pathway assessment if missing
        Tier 2 IMPORTANT: affects determination but can assume defaults
        Tier 3 SUPPLEMENTARY: enriches assessment but not required

        Returns CompletenessResult with per-pathway assessability and missing data lists.
        """
        c = CompletenessResult()

        # ── Tier 1: CRITICAL parameters ──

        # LKW / time information
        has_time = (
            patient.last_known_well_hours is not None
            or patient.unknown_onset
            or patient.wake_up_stroke
        )
        if not has_time:
            c.missing_critical.append({
                "param": "last_known_well",
                "label": "Time from Last Known Well",
                "question": "When was the patient last known to be at neurological baseline? If unknown, is this a wake-up stroke or unwitnessed onset?",
            })

        # NIHSS
        if patient.nihss is None:
            c.missing_critical.append({
                "param": "nihss",
                "label": "NIHSS Score",
                "question": "What is the current NIHSS score?",
            })

        # ASPECTS (for anterior circulation)
        if patient.aspects is None and patient.anterior_circulation:
            c.missing_critical.append({
                "param": "aspects",
                "label": "ASPECTS Score",
                "question": "What is the CT ASPECTS score?",
            })

        # Occlusion / LVO status
        has_lvo_info = patient.lvo or patient.occlusion_location is not None
        if not has_lvo_info:
            c.missing_critical.append({
                "param": "occlusion_location",
                "label": "Vessel Occlusion Status",
                "question": "Has CTA been performed? Is there a large vessel occlusion (LVO)? If so, what is the occlusion location?",
            })

        # Vessel segment specificity (for EVT pathway precision)
        if patient.occlusion_segment_unspecified:
            c.missing_critical.append({
                "param": "occlusion_segment",
                "label": "MCA Occlusion Segment (M1 vs M2)",
                "question": "The MCA occlusion was noted but the segment level was not specified. Is this an M1 (proximal/mainstem) or M2 (branch) occlusion? This determines which EVT recommendation applies.",
            })
            c.assumptions_made.append(
                "MCA occlusion segment not specified — assuming proximal M1. "
                "If this is an M2 occlusion, EVT recommendations differ significantly."
            )
            c.should_ask_clarification = True

        # ── Tier 2: IMPORTANT parameters ──

        if patient.mrs_pre is None:
            c.missing_important.append({
                "param": "mrs_pre",
                "label": "Pre-stroke mRS",
            })
            c.assumptions_made.append(
                "Pre-stroke mRS assumed 0 (functionally independent) — "
                "common default per trial populations"
            )

        if patient.age is None:
            c.missing_important.append({
                "param": "age",
                "label": "Patient Age",
            })

        if not patient.has_perfusion_imaging:
            c.missing_important.append({
                "param": "perfusion_imaging",
                "label": "Perfusion Imaging (CTP/MR DWI-PWI)",
            })

        if patient.on_anticoagulation and patient.anticoagulant_type is None:
            c.missing_important.append({
                "param": "anticoagulant_type",
                "label": "Anticoagulant Type and Timing",
            })

        # ── Determine per-pathway assessability ──

        # IVT: needs time + NIHSS
        c.can_assess_ivt = has_time and patient.nihss is not None

        # EVT standard: needs time + LVO + NIHSS (ASPECTS handled internally by rules)
        c.can_assess_evt = has_time and has_lvo_info and patient.nihss is not None

        # Extended window: needs time info + imaging selection criteria
        has_imaging_selection = patient.has_perfusion_imaging or patient.aspects is not None
        c.can_assess_extended = (has_time or patient.unknown_onset) and has_imaging_selection

        # Large core: needs ASPECTS or core volume + LVO
        has_core_info = patient.aspects is not None or patient.core_volume_ml is not None
        c.can_assess_large_core = has_core_info and has_lvo_info

        # ── Should we ask for full clarification? ──
        can_assess_any = (
            c.can_assess_ivt
            or c.can_assess_evt
            or c.can_assess_extended
            or c.can_assess_large_core
        )
        c.should_ask_clarification = c.should_ask_clarification or not can_assess_any

        if c.should_ask_clarification:
            c.clarification_questions = [
                item["question"] for item in c.missing_critical
            ]

        return c


# ═══════════════════════════════════════════════════════════════════
# 3. ELIGIBILITY RULE ENGINE (Deterministic)
# ═══════════════════════════════════════════════════════════════════

class EligibilityRules:
    """
    Deterministic rule engine based on 2026 AHA/ASA AIS Guidelines.

    Each method evaluates one treatment pathway and returns an EligibilityResult.
    Flags edge cases with needs_vector_search=True for deeper guideline search.
    """

    @staticmethod
    def evaluate_all(patient: PatientPresentation) -> list:
        results = []
        results.append(EligibilityRules.ivt_standard_window(patient))
        results.append(EligibilityRules.ivt_extended_window(patient))
        results.append(EligibilityRules.evt_standard_window(patient))
        results.append(EligibilityRules.evt_extended_window(patient))
        results.append(EligibilityRules.evt_large_core(patient))
        results.append(EligibilityRules.bp_management(patient))
        if patient.posterior_circulation:
            results.append(EligibilityRules.evt_posterior(patient))
        return results

    # ─── IVT: Standard Window (0-4.5h) ───

    @staticmethod
    def ivt_standard_window(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="IVT_standard_window",
            guideline_section="4.6.1 Thrombolysis Decision-Making",
        )

        lkw = patient.last_known_well_hours

        if lkw is None and not patient.unknown_onset:
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = "Last known well time not provided."
            r.needs_vector_search = True
            return r

        if lkw is not None and lkw > 4.5:
            r.eligibility = Eligibility.NO
            r.reasoning = f"Outside standard IVT window. LKW {lkw}h ago (window: 0-4.5h)."
            r.key_criteria = ["Time > 4.5 hours"]
            r.relevant_trials = ["NINDS", "ECASS-III"]
            return r

        if patient.unknown_onset or patient.wake_up_stroke:
            r.eligibility = Eligibility.NO
            r.reasoning = "Unknown onset — not eligible for standard window IVT. See extended window evaluation."
            r.key_criteria = ["Unknown time of onset"]
            return r

        criteria_met = []
        criteria_not_met = []
        caveats = []

        if patient.nihss is not None:
            if patient.nihss >= 6:
                criteria_met.append(f"NIHSS {patient.nihss} >= 6 (clearly disabling)")
            elif patient.nihss >= 1:
                criteria_met.append(f"NIHSS {patient.nihss} — assess if clearly disabling")
                caveats.append("Low NIHSS: clinician should assess if deficits are clearly disabling per Table 4 guidance")
            else:
                criteria_not_met.append(f"NIHSS {patient.nihss} — no measurable deficit")

        if patient.age is not None:
            if patient.age >= 18:
                criteria_met.append(f"Age {patient.age} >= 18")
            else:
                criteria_not_met.append(f"Age {patient.age} < 18 — pediatric pathway")
                caveats.append("Pediatric patient — limited evidence for IVT, consider case-by-case")
                r.needs_vector_search = True

        if patient.on_anticoagulation:
            if patient.anticoagulant_type == "warfarin" and patient.inr is not None:
                if patient.inr > 1.7:
                    criteria_not_met.append(f"INR {patient.inr} > 1.7 on warfarin")
                    r.eligibility = Eligibility.CONTRAINDICATED
                    r.reasoning = f"Warfarin with INR {patient.inr} > 1.7. IVT contraindicated."
                    r.cor = COR.COR_3_HARM.value
                    r.relevant_trials = ["NINDS"]
                    r.key_criteria = criteria_not_met
                    return r
                else:
                    criteria_met.append(f"INR {patient.inr} <= 1.7")
            elif patient.anticoagulant_type == "DOAC":
                caveats.append("On DOAC — IVT may be considered if last dose >48h or drug levels below threshold. Per DOAC-IVT evidence.")
                r.needs_vector_search = True

        if patient.mrs_pre is not None and patient.mrs_pre >= 3:
            caveats.append(f"Pre-stroke mRS {patient.mrs_pre} — limited trial representation. Consider individual benefit.")
            r.needs_vector_search = True

        caveats.append("Tenecteplase 0.25 mg/kg (single bolus) OR alteplase 0.9 mg/kg (COR 1, LOE A). Tenecteplase 0.4 mg/kg NOT recommended (COR 3: Harm).")

        if criteria_not_met:
            r.eligibility = Eligibility.NO
            r.reasoning = f"Does not meet IVT criteria: {'; '.join(criteria_not_met)}"
        else:
            r.eligibility = Eligibility.YES
            r.cor = COR.COR_1.value
            r.loe = LOE.A.value
            r.reasoning = f"Eligible for IVT. LKW {lkw}h, within 4.5h window."
            r.relevant_trials = ["NINDS", "ECASS-III", "AcT", "NOR-TEST"]
            r.page_references = [38, 39, 40, 42, 43]

        r.key_criteria = criteria_met + criteria_not_met
        r.caveats = caveats
        return r

    # ─── IVT: Extended Window (4.5-24h or unknown onset) ───

    @staticmethod
    def ivt_extended_window(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="IVT_extended_window",
            guideline_section="4.6.3 Extended Time Windows for IVT",
        )

        lkw = patient.last_known_well_hours

        if lkw is not None and lkw <= 4.5 and not patient.unknown_onset:
            r.eligibility = Eligibility.NO
            r.reasoning = "Within standard IVT window — extended window evaluation not applicable."
            return r

        if patient.unknown_onset or patient.wake_up_stroke:
            r.eligibility = Eligibility.CONDITIONAL
            r.cor = COR.COR_2A.value
            r.loe = LOE.B_R.value
            r.reasoning = "Wake-up/unknown onset stroke. IVT may be reasonable if DWI-FLAIR mismatch present on MRI (DWI positive, FLAIR negative)."
            r.relevant_trials = ["WAKE-UP", "THAWS"]
            r.key_criteria = [
                "Requires MRI with DWI-FLAIR mismatch",
                "DWI lesion < 1/3 MCA territory",
                "WAKE-UP trial criteria"
            ]
            r.page_references = [44, 45]
            r.needs_vector_search = True
            return r

        if lkw is not None and 4.5 < lkw <= 9:
            r.eligibility = Eligibility.CONDITIONAL
            r.cor = COR.COR_2A.value
            r.loe = LOE.B_R.value
            r.relevant_trials = ["EXTEND", "ECASS-4", "EPITHET"]

            if patient.has_perfusion_imaging:
                r.reasoning = f"LKW {lkw}h. In 4.5-9h window — IVT reasonable with perfusion imaging showing salvageable penumbra."
                r.key_criteria = [
                    "Perfusion mismatch ratio > 1.2",
                    "Mismatch volume > 10 mL",
                    "Ischemic core < 70 mL",
                    "Tmax > 6 sec hypoperfusion map"
                ]
                if patient.core_volume_ml is not None and patient.core_volume_ml >= 70:
                    r.eligibility = Eligibility.NO
                    r.reasoning += f" However, core volume {patient.core_volume_ml} mL >= 70 mL — exceeds trial criteria."
            else:
                r.reasoning = (
                    f"LKW {lkw}h. In 4.5-9h window — IVT may be reasonable. "
                    f"Perfusion imaging (CTP/MR DWI-PWI) can be useful if immediately available "
                    f"to characterize core and penumbra, but is not required per 2026 guidelines."
                )
                r.key_criteria = [
                    "4.5-9h window per EXTEND/ECASS-4/EPITHET criteria",
                    "CTP useful if available but not mandated",
                ]
                r.caveats = [
                    "Perfusion imaging not documented. CTP can strengthen the case "
                    "for IVT by confirming salvageable penumbra."
                ]

            r.page_references = [44, 45]
            return r

        if lkw is not None and 4.5 < lkw <= 24 and patient.lvo:
            r.eligibility = Eligibility.CONDITIONAL
            r.cor = COR.COR_2B.value
            r.loe = LOE.B_R.value
            r.reasoning = f"LKW {lkw}h with LVO. Tenecteplase in 4.5-24h window showed benefit in TRACE-III, but TIMELESS did not show benefit when rapid EVT available."
            r.relevant_trials = ["TRACE-III", "TIMELESS"]
            r.key_criteria = [
                "Most relevant when EVT is delayed or unavailable",
                "TIMELESS showed no added benefit when EVT performed rapidly"
            ]
            r.caveats = ["Consider IVT as bridge to EVT only if EVT will be delayed"]
            if not patient.has_perfusion_imaging:
                r.caveats.append(
                    "Perfusion imaging not documented. CTP can be useful if available "
                    "but is not required for guideline-compliant eligibility."
                )
            r.page_references = [45]
            r.needs_vector_search = True
            return r

        if lkw is not None and lkw > 24:
            r.eligibility = Eligibility.NO
            r.reasoning = f"LKW {lkw}h. Beyond all studied IVT time windows."
            return r

        r.eligibility = Eligibility.UNCERTAIN
        r.reasoning = "Insufficient time or imaging data to determine extended window eligibility."
        r.needs_vector_search = True
        return r

    # ─── EVT: Standard Window (0-6h) ───

    @staticmethod
    def evt_standard_window(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="EVT_standard_window",
            guideline_section="4.7.2 Endovascular Thrombectomy for Adult Patients",
        )

        lkw = patient.last_known_well_hours

        if lkw is None:
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = "Time from LKW not provided."
            r.needs_vector_search = True
            return r

        if lkw > 6:
            r.eligibility = Eligibility.NO
            r.reasoning = f"LKW {lkw}h — outside standard EVT window (0-6h). See extended window."
            return r

        if not patient.lvo:
            r.eligibility = Eligibility.NO
            r.reasoning = "No large vessel occlusion documented. Standard EVT requires LVO of anterior circulation."
            r.key_criteria = ["No LVO identified"]
            return r

        criteria_met = []
        criteria_not_met = []
        caveats = []

        if patient.nihss is not None:
            if patient.nihss >= 6:
                criteria_met.append(f"NIHSS {patient.nihss} >= 6")
            else:
                criteria_not_met.append(f"NIHSS {patient.nihss} < 6 — below landmark trial thresholds")
                caveats.append("Most EVT trials required NIHSS >= 6. Low NIHSS with LVO — consider individual benefit.")
                r.needs_vector_search = True

        if patient.aspects is not None:
            if patient.aspects >= 6:
                criteria_met.append(f"ASPECTS {patient.aspects} >= 6")
            elif patient.aspects >= 3:
                criteria_not_met.append(f"ASPECTS {patient.aspects} — large core territory (3-5). See large core EVT evaluation.")
            else:
                criteria_not_met.append(f"ASPECTS {patient.aspects} < 3 — very large core")
                caveats.append("ASPECTS 0-2: Outside most trial inclusion criteria. Limited evidence for benefit.")

        if patient.mrs_pre is not None:
            if patient.mrs_pre <= 1:
                criteria_met.append(f"Pre-stroke mRS {patient.mrs_pre} (functional independence)")
            elif patient.mrs_pre == 2:
                criteria_met.append(f"Pre-stroke mRS {patient.mrs_pre}")
                caveats.append(
                    f"Pre-stroke mRS 2: COR 2a, LOE B-NR — 'EVT is reasonable' per 2026 "
                    f"AHA/ASA guidelines (requires ASPECTS >= 6). Weaker evidence than "
                    f"mRS 0-1 (COR 1, LOE A)."
                )
            elif patient.mrs_pre <= 4:
                # mRS 3-4: COR 2b, LOE B-NR — "EVT might be reasonable" (0-6h only)
                criteria_met.append(f"Pre-stroke mRS {patient.mrs_pre}")
                caveats.append(
                    f"Pre-stroke mRS {patient.mrs_pre}: COR 2b, LOE B-NR — 'EVT might be "
                    f"reasonable' per 2026 AHA/ASA guidelines (0-6h window only, requires "
                    f"ASPECTS >= 6). Based on observational data; no completed RCTs in this "
                    f"population. This recommendation does NOT extend to the 6-24h window."
                )
            else:
                # mRS >= 5: No guideline recommendation
                caveats.append(
                    f"Pre-stroke mRS {patient.mrs_pre}: No AHA/ASA guideline recommendation "
                    f"exists for EVT in patients with mRS >= 5. The 2026 guideline covers "
                    f"mRS 0-1 (COR 1), mRS 2 (COR 2a), and mRS 3-4 (COR 2b) only."
                )
                r.needs_vector_search = True

        if patient.age is not None and patient.age > 80:
            caveats.append(f"Age {patient.age} > 80 — underrepresented in some trials but HERMES showed benefit across age groups.")

        if patient.occlusion_location:
            criteria_met.append(f"Occlusion: {patient.occlusion_location}")
        criteria_met.append("LVO confirmed")
        criteria_met.append(f"Time: {lkw}h from LKW (within 6h)")

        if patient.mrs_pre is not None and patient.mrs_pre >= 5:
            # No guideline recommendation for mRS >= 5 — overrides other criteria
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = (
                f"LVO within 6h, but pre-stroke mRS {patient.mrs_pre} — "
                f"no AHA/ASA guideline recommendation for EVT with mRS >= 5."
            )
            r.needs_vector_search = True
        elif any("large core" in c.lower() or "very large" in c.lower() for c in criteria_not_met):
            r.eligibility = Eligibility.CONDITIONAL
            r.reasoning = f"LVO within 6h but ASPECTS {patient.aspects} indicates large core. Evaluate under large core EVT criteria."
        elif criteria_not_met:
            r.eligibility = Eligibility.CONDITIONAL
            r.reasoning = f"Some criteria not fully met: {'; '.join(criteria_not_met)}"
        else:
            r.eligibility = Eligibility.YES
            if patient.mrs_pre is not None and patient.mrs_pre >= 3:
                # mRS 3-4: COR 2b, LOE B-NR — "EVT might be reasonable" (requires ASPECTS >= 6)
                if patient.aspects is not None and patient.aspects >= 6:
                    r.cor = COR.COR_2B.value
                    r.loe = LOE.B_NR.value
                    r.reasoning = (
                        f"Eligible for EVT (COR 2b, LOE B-NR). LVO, NIHSS {patient.nihss}, "
                        f"ASPECTS {patient.aspects}, mRS {patient.mrs_pre}, within 6h. "
                        f"Based on observational data; no completed RCTs in this population."
                    )
                else:
                    # mRS 3-4 recommendation requires ASPECTS >= 6
                    r.eligibility = Eligibility.UNCERTAIN
                    r.reasoning = (
                        f"LVO within 6h, mRS {patient.mrs_pre} — the mRS 3-4 recommendation "
                        f"(COR 2b) requires ASPECTS >= 6. ASPECTS {patient.aspects} does not "
                        f"meet this threshold."
                    )
                    r.needs_vector_search = True
            elif patient.mrs_pre is not None and patient.mrs_pre == 2:
                # mRS 2: COR 2a, LOE B-NR — "EVT is reasonable" (requires ASPECTS >= 6)
                if patient.aspects is not None and patient.aspects >= 6:
                    r.cor = COR.COR_2A.value
                    r.loe = LOE.B_NR.value
                    r.reasoning = (
                        f"Eligible for EVT (COR 2a, LOE B-NR). LVO, NIHSS {patient.nihss}, "
                        f"ASPECTS {patient.aspects}, mRS {patient.mrs_pre}, within 6h."
                    )
                else:
                    # mRS 2 recommendation requires ASPECTS >= 6
                    r.eligibility = Eligibility.UNCERTAIN
                    r.reasoning = (
                        f"LVO within 6h, mRS {patient.mrs_pre} — the mRS 2 recommendation "
                        f"(COR 2a) requires ASPECTS >= 6. ASPECTS {patient.aspects} does not "
                        f"meet this threshold."
                    )
                    r.needs_vector_search = True
            else:
                # mRS 0-1 or not provided: standard COR 1, LOE A
                r.cor = COR.COR_1.value
                r.loe = LOE.A.value
                r.reasoning = f"Eligible for EVT. LVO, NIHSS {patient.nihss}, ASPECTS {patient.aspects}, within 6h."

        r.relevant_trials = ["MR CLEAN", "ESCAPE", "REVASCAT", "SWIFT PRIME", "EXTEND-IA", "HERMES"]
        r.key_criteria = criteria_met + criteria_not_met
        r.caveats = caveats
        r.page_references = [53, 54, 55, 56]
        return r

    # ─── EVT: Extended Window (6-24h) ───

    @staticmethod
    def evt_extended_window(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="EVT_extended_window",
            guideline_section="4.7.2 Endovascular Thrombectomy for Adult Patients",
        )

        lkw = patient.last_known_well_hours

        if lkw is None:
            if patient.lvo:
                r.eligibility = Eligibility.CONDITIONAL
                r.reasoning = "Unknown onset with LVO — may qualify for extended window EVT based on clinical-imaging criteria."
                r.relevant_trials = ["DAWN", "DEFUSE-3"]
                r.needs_vector_search = True
                return r
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = "Time from LKW unknown and no LVO documented."
            r.needs_vector_search = True
            return r

        if lkw <= 6:
            r.eligibility = Eligibility.NO
            r.reasoning = "Within standard EVT window — extended window evaluation not applicable."
            return r

        if lkw > 24:
            r.eligibility = Eligibility.NO
            r.reasoning = f"LKW {lkw}h — beyond all studied EVT time windows."
            return r

        if not patient.lvo:
            r.eligibility = Eligibility.NO
            r.reasoning = "No LVO documented. Extended window EVT requires LVO."
            return r

        criteria_met = []
        caveats = []

        criteria_met.append("LVO confirmed")
        criteria_met.append(f"Time: {lkw}h (within 6-24h window)")

        if patient.nihss is not None:
            if patient.nihss >= 6:
                criteria_met.append(f"NIHSS {patient.nihss} >= 6")
            else:
                caveats.append(
                    f"NIHSS {patient.nihss} < 6 — below DAWN/DEFUSE-3 threshold. "
                    f"Extended window trials required NIHSS >= 6."
                )

        if patient.aspects is not None and patient.aspects >= 6:
            criteria_met.append(f"ASPECTS {patient.aspects} >= 6 (suggests smaller core)")

        # Perfusion imaging: enrichment, NOT a gate
        if patient.has_perfusion_imaging:
            criteria_met.append("Perfusion imaging available")

            if patient.core_volume_ml is not None:
                if patient.core_volume_ml < 70:
                    criteria_met.append(f"Core volume {patient.core_volume_ml} mL < 70 mL")
                else:
                    caveats.append(f"Core volume {patient.core_volume_ml} mL >= 70 mL — exceeds DEFUSE-3 criteria. May qualify under large core criteria.")
                    r.needs_vector_search = True

            if patient.mismatch_ratio is not None and patient.mismatch_ratio >= 1.8:
                criteria_met.append(f"Mismatch ratio {patient.mismatch_ratio} >= 1.8")
        else:
            caveats.append(
                "Perfusion imaging (CTP/MR DWI-PWI) not documented. "
                "CTP can be useful if immediately available to further characterize "
                "core and penumbra, but is not required for guideline-compliant EVT eligibility."
            )

        # mRS handling — 2026 guideline recommendation (COR 1, LOE A) covers mRS 0-1 only
        if patient.mrs_pre is not None:
            if patient.mrs_pre <= 1:
                criteria_met.append(f"Pre-stroke mRS {patient.mrs_pre} (within DAWN/DEFUSE-3 populations)")
            elif patient.mrs_pre == 2:
                caveats.append(
                    f"Pre-stroke mRS 2: DEFUSE-3 allowed mRS 0-2, but the extended window "
                    f"guideline recommendation (COR 1, LOE A) is based primarily on DAWN "
                    f"(mRS 0-1). No specific COR/LOE for mRS 2 in the 6-24h window."
                )
                r.needs_vector_search = True
            else:
                # mRS >= 3: COR 2b recommendation exists but only for 0-6h window
                caveats.append(
                    f"Pre-stroke mRS {patient.mrs_pre}: The COR 2b, LOE B-NR recommendation "
                    f"for mRS 3-4 applies to the 0-6h window only. No formal recommendation "
                    f"for mRS >= 3 in the 6-24h extended window."
                )
                r.needs_vector_search = True

        # Determine eligibility based on clinical-imaging criteria
        has_nihss = patient.nihss is not None and patient.nihss >= 6
        has_aspects = patient.aspects is not None and patient.aspects >= 6
        mrs_in_population = patient.mrs_pre is not None and patient.mrs_pre <= 1

        if patient.mrs_pre is not None and patient.mrs_pre >= 3:
            # COR 2b exists for mRS 3-4 but only in 0-6h window — not extended
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = (
                f"LVO at {lkw}h, but pre-stroke mRS {patient.mrs_pre} — "
                f"the COR 2b recommendation for mRS 3-4 applies to the 0-6h window only. "
                f"No guideline recommendation for mRS >= 3 in the 6-24h extended window."
            )
            r.needs_vector_search = True
        elif has_nihss and has_aspects and mrs_in_population:
            r.eligibility = Eligibility.YES
            r.cor = COR.COR_1.value
            r.loe = LOE.A.value
            r.reasoning = (
                f"LVO at {lkw}h, NIHSS {patient.nihss}, ASPECTS {patient.aspects}, "
                f"mRS {patient.mrs_pre}. Meets 2026 guideline criteria for extended window EVT."
            )
        elif has_nihss and has_aspects and patient.mrs_pre is not None and patient.mrs_pre == 2:
            # mRS 2: DEFUSE-3 included, but no specific COR/LOE in extended window
            r.eligibility = Eligibility.CONDITIONAL
            r.reasoning = (
                f"LVO at {lkw}h, NIHSS {patient.nihss}, ASPECTS {patient.aspects}, "
                f"mRS 2. Clinical-imaging criteria met but mRS 2 falls between DAWN "
                f"(mRS 0-1) and DEFUSE-3 (mRS 0-2) populations. No specific COR/LOE "
                f"for mRS 2 in the extended window."
            )
        elif has_nihss and has_aspects:
            r.eligibility = Eligibility.CONDITIONAL
            r.reasoning = (
                f"LVO at {lkw}h, NIHSS {patient.nihss}, ASPECTS {patient.aspects}. "
                f"Clinical-imaging criteria met."
            )
        elif patient.aspects is not None and patient.aspects < 6:
            r.eligibility = Eligibility.CONDITIONAL
            r.reasoning = (
                f"LVO at {lkw}h, ASPECTS {patient.aspects} < 6 suggests larger core. "
                f"Evaluate under large core EVT criteria."
            )
            r.needs_vector_search = True
        else:
            r.eligibility = Eligibility.UNCERTAIN
            r.reasoning = (
                f"LVO at {lkw}h — insufficient NIHSS or ASPECTS data to fully "
                f"determine extended window eligibility."
            )
            r.needs_vector_search = True

        r.relevant_trials = ["DAWN", "DEFUSE-3"]
        r.key_criteria = criteria_met
        r.caveats = caveats
        r.page_references = [54, 55]
        return r

    # ─── EVT: Large Core (ASPECTS 3-5 or core > 50mL) ───

    @staticmethod
    def evt_large_core(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="EVT_large_core",
            guideline_section="4.7.2 Endovascular Thrombectomy for Adult Patients",
        )

        if not patient.lvo:
            r.eligibility = Eligibility.NO
            r.reasoning = "No LVO — large core EVT not applicable."
            return r

        has_large_core = False
        if patient.aspects is not None and patient.aspects <= 5:
            has_large_core = True
        if patient.core_volume_ml is not None and patient.core_volume_ml > 50:
            has_large_core = True

        if not has_large_core:
            r.eligibility = Eligibility.NO
            r.reasoning = "ASPECTS > 5 / core volume not in large core range — standard EVT criteria apply."
            return r

        caveats = []

        if patient.aspects is not None and 3 <= patient.aspects <= 5:
            r.eligibility = Eligibility.YES
            r.cor = COR.COR_1.value
            r.loe = LOE.A.value
            r.reasoning = f"ASPECTS {patient.aspects} (3-5). Multiple RCTs support EVT for large core with ASPECTS 3-5."
            r.relevant_trials = ["SELECT2", "ANGEL ASPECT", "RESCUE LIMIT", "LASTE"]
            r.page_references = [54, 55]

            if patient.core_volume_ml is not None and patient.core_volume_ml >= 26:
                caveats.append(f"SELECT2 exploratory analysis: >=26 mL severe CT hypodensity (<=26 HU) associated with diminished EVT benefit. Core volume: {patient.core_volume_ml} mL.")
                r.needs_vector_search = True

        elif patient.aspects is not None and patient.aspects < 3:
            r.eligibility = Eligibility.UNCERTAIN
            r.cor = COR.COR_2B.value
            r.reasoning = f"ASPECTS {patient.aspects} (0-2). Very large predicted core. TENSION trial enrolled ASPECTS 1-5, but ASPECTS 0-2 subgroup had limited benefit. High risk of cerebral edema and hemicraniectomy."
            r.relevant_trials = ["TENSION", "SELECT2", "ANGEL ASPECT"]
            r.caveats = [
                "ASPECTS 0-2: outside core inclusion of SELECT2 (3-5) and ANGEL ASPECT (3-5)",
                "TENSION enrolled ASPECTS 1-5 but was stopped early",
                "High risk of malignant edema and need for hemicraniectomy",
                "Individual risk-benefit discussion essential"
            ]
            r.needs_vector_search = True
            r.page_references = [54, 55]
            return r

        lkw = patient.last_known_well_hours
        if lkw is not None and lkw > 24:
            r.eligibility = Eligibility.NO
            r.reasoning += f" However, LKW {lkw}h exceeds all trial windows."
        elif lkw is not None and lkw > 6:
            caveats.append(f"LKW {lkw}h in extended window — ANGEL ASPECT and SELECT2 enrolled up to 24h with imaging selection.")

        if patient.mrs_pre is not None and patient.mrs_pre >= 2:
            caveats.append(f"Pre-stroke mRS {patient.mrs_pre} — underrepresented in large core trials.")
            if patient.mrs_pre >= 3:
                r.needs_vector_search = True

        r.caveats = caveats
        return r

    # ─── EVT: Posterior Circulation ───

    @staticmethod
    def evt_posterior(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="EVT_posterior_circulation",
            guideline_section="4.7.3 Posterior Circulation Stroke",
        )

        if not patient.posterior_circulation:
            r.eligibility = Eligibility.NO
            r.reasoning = "Not posterior circulation — this evaluation not applicable."
            return r

        r.eligibility = Eligibility.CONDITIONAL
        r.cor = COR.COR_2A.value
        r.loe = LOE.B_R.value
        r.reasoning = "Posterior circulation LVO (basilar artery occlusion). EVT is reasonable based on ATTENTION and BAOCHE trials."
        r.relevant_trials = ["ATTENTION", "BAOCHE", "BASICS"]
        r.key_criteria = [
            "ATTENTION: EVT beneficial for basilar artery occlusion",
            "BAOCHE: confirmed benefit in Chinese population",
            "BASICS: did not show benefit (but methodological concerns)",
            "Patient selection and timing remain important"
        ]
        r.caveats = [
            "ATTENTION and BAOCHE enrolled within 12h of estimated onset",
            "pc-ASPECTS may be used for posterior circulation assessment",
            "BASICS trial was negative but had enrollment issues"
        ]
        r.needs_vector_search = True
        r.page_references = [59, 60]
        return r

    # ─── Blood Pressure Management ───

    @staticmethod
    def bp_management(patient: PatientPresentation) -> EligibilityResult:
        r = EligibilityResult(
            treatment="BP_management",
            guideline_section="4.3 Blood Pressure Management",
        )

        targets = [
            "Pre-IVT/EVT: SBP < 185 mmHg and DBP < 110 mmHg (COR 1, LOE B-NR)",
            "Post-IVT (24h): maintain BP < 180/105 mmHg (COR 1, LOE B-NR)",
            "Post-IVT: Intensive SBP reduction to <140 NOT recommended (COR 3: No Benefit — ENCHANTED)",
            "Post-EVT with successful recanalization: Intensive SBP <140 is HARMFUL (COR 3: Harm — ENCHANTED2, BP-TARGET, BEST-II)",
            "Post-EVT: maintain SBP < 180 mmHg as standard target",
        ]

        r.eligibility = Eligibility.YES
        r.reasoning = "BP management targets based on treatment received."
        r.key_criteria = targets
        r.relevant_trials = ["ENCHANTED", "ENCHANTED2", "BP-TARGET", "BEST-II", "OPTIMAL-BP"]
        r.page_references = [5, 35, 36]
        r.cor = COR.COR_1.value
        r.loe = LOE.B_R.value
        return r


# ═══════════════════════════════════════════════════════════════════
# 4. CLINICAL SUPPORT ENGINE (BaseEngine)
# ═══════════════════════════════════════════════════════════════════

class ClinicalSupportEngine(BaseEngine):
    """
    Evaluates AIS treatment eligibility using deterministic rules + vector search.

    Pipeline:
        1. PatientParser.parse(raw_query)       → structured patient data
        2. EligibilityRules.evaluate_all(patient) → per-pathway eligibility
        3. _search_guidelines(edge_cases)         → OpenAI file_search (edge cases only)
        4. Return standard engine contract        → clinical_output_agent formats
    """

    def __init__(self):
        super().__init__(name="clinical_support_engine")
        self.parser = PatientParser()
        self.rules = EligibilityRules()
        self.trial_lookup = TrialMetricsLookup()
        self.context_review = ContextReview()
        self.ais_vector_store_id = config.AIS_GUIDELINES_VECTOR_STORE_ID
        print(f"  [ClinicalSupportEngine] ais_vector_store_id={self.ais_vector_store_id!r}")

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Main engine entry point.

        Args:
            input_data: {
                "normalized_query": str,
                "raw_query": str,  # original user message — PatientParser reads this
            }

        Returns:
            Standard engine contract via _build_return().
        """
        # Use raw_query to preserve clinical abbreviations
        patient_text = input_data.get("raw_query", input_data.get("normalized_query", ""))

        print(f"\n  [ClinicalSupportEngine] Parsing patient presentation...")

        # Step 1: Parse patient data (deterministic)
        patient = self.parser.parse(patient_text)
        print(f"  [ClinicalSupportEngine] Parsed: age={patient.age}, "
              f"LKW={patient.last_known_well_hours}h, NIHSS={patient.nihss}, "
              f"mRS={patient.mrs_pre}, ASPECTS={patient.aspects}, "
              f"occlusion={patient.occlusion_location}, LVO={patient.lvo}")

        # Step 1b: Assess completeness (deterministic)
        completeness = self.parser.assess_completeness(patient)
        print(f"  [ClinicalSupportEngine] Completeness: "
              f"IVT={completeness.can_assess_ivt}, EVT={completeness.can_assess_evt}, "
              f"extended={completeness.can_assess_extended}, "
              f"large_core={completeness.can_assess_large_core}, "
              f"missing_critical={len(completeness.missing_critical)}, "
              f"ask_clarification={completeness.should_ask_clarification}")

        # Step 1c: Early return if NO pathway can be assessed
        if completeness.should_ask_clarification:
            print(f"  [ClinicalSupportEngine] Cannot assess any pathway — returning clarification")
            return self._build_return(
                status="needs_clarification",
                result_type="clinical_clarification",
                data={
                    "patient": asdict(patient),
                    "completeness": asdict(completeness),
                },
                classification={"intent_type": "clinical_support"},
                confidence=0.0,
            )

        # Step 1d: Apply Tier 2 defaults before rule evaluation
        if patient.mrs_pre is None:
            patient.mrs_pre = 0  # Default per trial populations (recorded in completeness.assumptions_made)

        # Step 2: Run eligibility rules (deterministic)
        results = self.rules.evaluate_all(patient)

        eligible_count = sum(1 for r in results if r.eligibility in (Eligibility.YES, Eligibility.CONDITIONAL))
        print(f"  [ClinicalSupportEngine] {len(results)} pathways evaluated, "
              f"{eligible_count} eligible/conditional")

        # Step 3: Enrich with structured trial metrics (JSON lookup, no API)
        edge_cases = [r for r in results if r.needs_vector_search]
        trial_context = self._enrich_with_trial_metrics(results)
        print(f"  [ClinicalSupportEngine] Trial metrics: {len(trial_context)} trials resolved from JSON")

        # Step 4: Evaluate sufficiency — which edge cases still need vector search?
        still_need_search = self._evaluate_sufficiency(edge_cases, trial_context, patient)
        print(f"  [ClinicalSupportEngine] {len(edge_cases)} edge cases, "
              f"{len(still_need_search)} still need vector search")

        # Step 5: Vector search only for remaining edge cases
        vector_context = []
        confidence = 0.95  # high confidence when JSON alone is sufficient

        if still_need_search and self.ais_vector_store_id:
            print(f"  [ClinicalSupportEngine] Searching guidelines for {len(still_need_search)} edge cases...")
            vector_context = await self._search_guidelines(still_need_search, patient, trial_context)
            confidence = 0.8  # lower when vector search was required
            print(f"  [ClinicalSupportEngine] Vector search returned {len(vector_context)} chunks: "
                  f"{[vc.get('for_treatment', '?') for vc in vector_context]}")

        # Step 5b: Context review — only for UNCERTAIN/CONDITIONAL pathways
        has_edge_cases = any(
            r.eligibility in (Eligibility.UNCERTAIN, Eligibility.CONDITIONAL)
            for r in results
        )

        if has_edge_cases and self.ais_vector_store_id:
            print(f"  [ClinicalSupportEngine] Running context review...")
            review = await self.context_review.review(
                patient=asdict(patient),
                eligibility=[asdict(r) for r in results],
                trial_context=trial_context,
                vector_context=vector_context,
            )
            print(f"  [ClinicalSupportEngine] Context review: sufficient={review['sufficient']}, "
                  f"gaps={len(review.get('search_queries', []))}")

            if review["needs_search"]:
                for sq in review["search_queries"]:
                    print(f"    → Searching for: {sq['query'][:80]}")
                gap_context = await self._search_guidelines_from_queries(
                    review["search_queries"], patient, trial_context
                )
                vector_context.extend(gap_context)
                confidence = 0.75
                print(f"  [ClinicalSupportEngine] Gap search returned {len(gap_context)} additional chunks")

        # Step 6: Return standard contract
        return self._build_return(
            status="complete",
            result_type="clinical_assessment",
            data={
                "patient": asdict(patient),
                "eligibility": [asdict(r) for r in results],
                "edge_cases": [r.treatment for r in edge_cases],
                "trial_context": trial_context,
                "vector_context": vector_context,
                "completeness": asdict(completeness),
            },
            classification={"intent_type": "clinical_support"},
            confidence=confidence,
        )

    def _enrich_with_trial_metrics(self, results: list) -> dict:
        """
        Collect all trial names referenced across eligibility results and
        batch-lookup their structured metrics from the JSON file.

        Returns:
            {trial_name: summary_dict} for all found trials.
        """
        all_trial_names = set()
        for r in results:
            for name in r.relevant_trials:
                all_trial_names.add(name)
        return self.trial_lookup.lookup_all(list(all_trial_names))

    def _evaluate_sufficiency(
        self,
        edge_cases: list,
        trial_context: dict,
        patient: PatientPresentation,
    ) -> list:
        """
        Determine which edge cases still need vector search after JSON enrichment.

        JSON is NOT sufficient when:
        - A referenced trial is missing from the JSON dataset
        - ASPECTS < 3 (subgroup analysis not in structured metrics)
        - Pre-stroke mRS >= 3 (needs guideline text on pre-existing disability)
        - Posterior circulation (conflicting trial interpretations need full context)
        """
        still_need = []

        for edge in edge_cases:
            needs_search = False

            # Check if any referenced trial is missing from JSON
            for trial_name in edge.relevant_trials:
                if not self.trial_lookup.has_trial(trial_name):
                    needs_search = True
                    break

            # ASPECTS < 3 — subgroup analyses aren't captured in structured metrics
            if patient.aspects is not None and patient.aspects < 3:
                needs_search = True

            # Pre-stroke mRS >= 3 — needs guideline text on disability considerations
            if patient.mrs_pre is not None and patient.mrs_pre >= 3:
                needs_search = True

            # Posterior circulation — conflicting trial data needs full context
            if patient.posterior_circulation:
                needs_search = True

            if needs_search:
                still_need.append(edge)

        return still_need

    async def _search_guidelines(self, edge_cases: list, patient: PatientPresentation, trial_context: dict = None) -> list:
        """Search AIS guidelines via OpenAI Vector Store search for edge cases.

        Uses direct REST API (same pattern as shared/vector_client.py) —
        no SDK version dependency, no intermediate LLM call.

        When trial_context is provided, uses page references from JSON data
        to build more targeted search queries.
        """
        import asyncio
        import requests as req

        if trial_context is None:
            trial_context = {}

        url = f"https://api.openai.com/v1/vector_stores/{self.ais_vector_store_id}/search"
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        try:
            results = []

            for edge in edge_cases:
                # Build a targeted query from the edge case context
                query_parts = []
                if edge.guideline_section:
                    query_parts.append(f"Section {edge.guideline_section}")
                query_parts.extend([edge.treatment, edge.reasoning])
                if edge.relevant_trials:
                    query_parts.append(f"Trials: {', '.join(edge.relevant_trials)}")
                if patient.nihss is not None:
                    query_parts.append(f"NIHSS {patient.nihss}")
                if patient.aspects is not None:
                    query_parts.append(f"ASPECTS {patient.aspects}")
                if patient.mrs_pre is not None and patient.mrs_pre >= 2:
                    query_parts.append(f"pre-stroke mRS {patient.mrs_pre}")

                # Add page hints from trial_context JSON data for better retrieval
                page_hints = set()
                for trial_name in edge.relevant_trials:
                    tc = trial_context.get(trial_name)
                    if tc and tc.get("pages"):
                        page_hints.update(tc["pages"])
                if page_hints:
                    sorted_pages = sorted(page_hints)
                    query_parts.append(f"Focus on pages {', '.join(str(p) for p in sorted_pages)}")

                search_query = ". ".join(query_parts)

                # Direct REST call — same pattern as shared/vector_client.py
                payload = {"query": search_query, "max_num_results": 5}
                # Bias retrieval toward recommendation tables for eligibility edge cases
                if edge.eligibility in (Eligibility.UNCERTAIN, Eligibility.CONDITIONAL):
                    payload["filters"] = {
                        "type": "eq",
                        "key": "content_type",
                        "value": "recommendation_table",
                    }
                resp = await asyncio.to_thread(
                    req.post, url, headers=headers, json=payload, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()

                # Extract text from scored chunks
                chunks = data.get("data", [])
                if chunks:
                    # Combine top chunks into a single text block
                    text_parts = []
                    for chunk in chunks:
                        score = chunk.get("score", 0)
                        content = "".join(
                            c.get("text", "") for c in chunk.get("content", [])
                        )
                        if content:
                            text_parts.append(content)
                    combined = "\n\n".join(text_parts)
                    if combined:
                        results.append({
                            "for_treatment": edge.treatment,
                            "text": combined[:2000],
                            "query": search_query,
                            "trials_searched": edge.relevant_trials,
                            "chunk_count": len(chunks),
                            "top_score": chunks[0].get("score", 0),
                        })

            return results

        except Exception as e:
            print(f"  [ClinicalSupportEngine] Vector search failed: {e}")
            return []

    async def _search_guidelines_from_queries(
        self, queries: list, patient: PatientPresentation, trial_context: dict
    ) -> list:
        """
        Search vector store using specific queries from context review.

        Args:
            queries: [{"pathway": str, "query": str}, ...]

        Returns:
            List of vector context dicts (same format as _search_guidelines).
        """
        import asyncio
        import requests as req

        url = f"https://api.openai.com/v1/vector_stores/{self.ais_vector_store_id}/search"
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        results = []
        try:
            for sq in queries:
                payload = {"query": sq["query"], "max_num_results": 3}
                resp = await asyncio.to_thread(
                    req.post, url, headers=headers, json=payload, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()

                chunks = data.get("data", [])
                if chunks:
                    text_parts = []
                    for chunk in chunks:
                        content = "".join(
                            c.get("text", "") for c in chunk.get("content", [])
                        )
                        if content:
                            text_parts.append(content)
                    combined = "\n\n".join(text_parts)
                    if combined:
                        results.append({
                            "for_treatment": sq["pathway"],
                            "text": combined[:2000],
                            "query": sq["query"],
                            "source": "context_review_gap_fill",
                            "chunk_count": len(chunks),
                            "top_score": chunks[0].get("score", 0),
                        })

            return results
        except Exception as e:
            print(f"  [ClinicalSupportEngine] Gap search failed: {e}")
            return []
