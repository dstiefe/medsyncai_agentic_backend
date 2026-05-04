from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, computed_field


class NIHSSItems(BaseModel):
    """Individual NIHSS component scores."""
    vision: Optional[int] = Field(None, ge=0, le=3, description="Vision 0-3")
    bestLanguage: Optional[int] = Field(None, ge=0, le=3, description="Best language 0-3")
    extinction: Optional[int] = Field(None, ge=0, le=2, description="Extinction/inattention 0-2")
    motorArmL: Optional[int] = Field(None, ge=0, le=4, description="Motor arm left 0-4")
    motorArmR: Optional[int] = Field(None, ge=0, le=4, description="Motor arm right 0-4")
    motorLegL: Optional[int] = Field(None, ge=0, le=4, description="Motor leg left 0-4")
    motorLegR: Optional[int] = Field(None, ge=0, le=4, description="Motor leg right 0-4")
    facialPalsy: Optional[int] = Field(None, ge=0, le=3, description="Facial palsy 0-3")
    sensory: Optional[int] = Field(None, ge=0, le=2, description="Sensory 0-2")
    ataxia: Optional[int] = Field(None, ge=0, le=2, description="Ataxia 0-2")
    limbAtaxia: Optional[int] = Field(None, ge=0, le=2, description="Limb ataxia 0-2")


class ParsedVariables(BaseModel):
    """All parsed clinical variables from patient scenario."""

    # Demographics
    age: Optional[int] = Field(None, ge=0, le=120)
    sex: Optional[str] = None

    # Presentation timing
    timeHours: Optional[float] = Field(None, ge=0)
    lastKnownWellHours: Optional[float] = Field(None, ge=0, description="Hours since last known well/normal")
    lkwClockTime: Optional[str] = Field(None, description="Clock time of LKW in 24h format HH:MM (e.g., '23:00' for 11pm)")
    wakeUp: Optional[bool] = None

    # NIHSS
    nihss: Optional[int] = Field(None, ge=0, le=42)
    nihssItems: Optional[NIHSSItems] = None

    # Imaging - vessel and anatomy
    vessel: Optional[str] = None  # M1, M2, ICA, basilar, ACA, PCA, etc.
    side: Optional[str] = None  # left, right, bilateral
    m2Dominant: Optional[bool] = None  # True=dominant proximal M2, False=nondominant/codominant

    # Imaging - extent
    aspects: Optional[int] = Field(None, ge=0, le=10)
    pcAspects: Optional[int] = Field(None, ge=0, le=10, description="Posterior circulation ASPECTS (pc-ASPECTS)")
    massEffect: Optional[bool] = Field(None, description="Whether mass effect is present on imaging")
    prestrokeMRS: Optional[int] = Field(None, ge=0, le=6)

    # Vitals
    sbp: Optional[int] = Field(None, ge=0)
    dbp: Optional[int] = Field(None, ge=0)

    # Hemorrhage
    hemorrhage: Optional[bool] = Field(
        None,
        description="true if user reports acute intracranial hemorrhage on imaging (ICH, intraparenchymal bleed, SAH, IVH, 'blood on CT', hemorrhagic stroke). false if user explicitly states no hemorrhage on imaging. null if imaging or hemorrhage status not mentioned.",
    )

    # Medications
    onAntiplatelet: Optional[bool] = Field(
        None,
        description="true if user reports the patient is currently taking single or dual antiplatelet therapy (aspirin, clopidogrel, ticagrelor, prasugrel, dipyridamole, DAPT). false if user explicitly states the patient is not on antiplatelets. null if medication status not mentioned.",
    )
    onAnticoagulant: Optional[bool] = Field(
        None,
        description="true if user reports the patient is currently taking an anticoagulant (warfarin, apixaban, rivaroxaban, dabigatran, edoxaban, heparin, LMWH/enoxaparin). false if explicitly stated not on anticoagulants. null if not mentioned. Use recentDOAC for DOAC-specific 48h timing.",
    )

    # Conditions
    sickleCell: Optional[bool] = Field(
        None,
        description="true if user reports known sickle cell disease (HbSS, HbSC, sickle cell). false if explicitly ruled out. null if not mentioned.",
    )

    # Imaging — composite findings (set when user names the finding directly)
    dwiFlair: Optional[bool] = Field(
        None,
        description="True if user reports DWI-FLAIR mismatch directly. For discrete criteria use dwiLesionPresent + flairMarkedSignalChange.",
    )
    penumbra: Optional[bool] = Field(
        None,
        description="True if user reports salvageable ischemic penumbra detected on automated perfusion imaging (CTP or MR perfusion).",
    )

    # Imaging — strict §4.6.3 criteria (each set ONLY if user explicitly states it)
    imagingModality: Optional[str] = Field(
        None,
        description="Advanced imaging modality the user reports was performed. Values: 'mri', 'ctp', 'both'. Null if not stated.",
    )
    dwiLesionPresent: Optional[bool] = Field(
        None,
        description="True if user reports a DWI lesion on MRI; False if user reports DWI is negative; null if DWI not mentioned. Rec 4.6.3-001 criterion.",
    )
    dwiLesionSmallerThanThirdMca: Optional[bool] = Field(
        None,
        description="True if user reports the DWI lesion is smaller than one-third of the MCA territory; False if larger / extensive / frank hypodensity; null if size not stated. Rec 4.6.3-001 criterion — do NOT infer from territory mention alone.",
    )
    flairMarkedSignalChange: Optional[bool] = Field(
        None,
        description="True if user reports marked/visible FLAIR signal change in the territory of acute ischemia; False if FLAIR is negative / unchanged; null if FLAIR not mentioned. Rec 4.6.3-001 criterion.",
    )
    mriUnavailable: Optional[bool] = Field(
        None,
        description="True if user states MRI is not available, contraindicated, or cannot be obtained for this patient. Null if not mentioned.",
    )
    ctpUnavailable: Optional[bool] = Field(
        None,
        description="True if user states CTP / CT perfusion is not available or cannot be obtained. Null if not mentioned.",
    )

    # Cerebral microbleeds
    cmbs: Optional[bool] = Field(
        None,
        description="true if user reports cerebral microbleeds (CMBs) on prior MRI. false if user explicitly states no CMBs / clean prior MRI. null if not mentioned. Use cmbCount for a specific number.",
    )
    cmbCount: Optional[int] = None
    cmbBurden: Optional[int] = None  # cerebral microbleed count (None = unknown)

    # Glucose
    glucoseCorrected: Optional[bool] = None

    # Imaging findings - early ischemic change
    earlyIschemicChange: Optional[bool] = None

    # Prior interventions
    ivtGiven: Optional[bool] = None
    ivtNotGiven: Optional[bool] = None
    evtUnavailable: Optional[bool] = Field(
        None,
        description="true if user states EVT/endovascular thrombectomy is not accessible at this facility (e.g. 'no EVT capability', 'not a thrombectomy center', 'awaiting transfer for EVT'). null if not mentioned. Do NOT set this from clinical exclusions like time out of window or low ASPECTS — those are evaluated by the rule engine.",
    )
    nonDisabling: Optional[bool] = None

    # Table 8 - Recent procedures/trauma
    recentTBI: Optional[bool] = Field(
        None,
        description="true if user reports moderate-to-severe traumatic brain injury within 14 days (head trauma with LOC >30 min, GCS <13, or hemorrhage/contusion/skull fracture on neuroimaging). false if user explicitly rules out. null if no head trauma mentioned, OR head trauma mentioned without severity/timing details. Use tbiDays for the specific number of days. When in doubt, leave null.",
    )
    tbiDays: Optional[int] = None
    recentNeurosurgery: Optional[bool] = Field(
        None,
        description="true if user reports intracranial or spinal surgery within the past 14 days. false if explicitly ruled out. null if not mentioned. Use neurosurgeryDays for specific number of days.",
    )
    neurosurgeryDays: Optional[int] = None
    acuteSpinalCordInjury: Optional[bool] = Field(
        None,
        description="true if user reports spinal cord injury within the past 3 months. false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - CNS neoplasms
    intraAxialNeoplasm: Optional[bool] = Field(
        None,
        description="True if user reports an intra-axial (parenchymal) intracranial neoplasm. Examples: glioblastoma, GBM, glioma, astrocytoma, oligodendroglioma, ependymoma, medulloblastoma, primary CNS lymphoma, brain metastasis. False only if user explicitly rules out. Null if not mentioned OR location ambiguous (e.g. 'brain tumor' without specifier).",
    )
    extraAxialNeoplasm: Optional[bool] = Field(
        None,
        description="True if user reports an extra-axial intracranial neoplasm. Examples: meningioma, schwannoma, vestibular schwannoma / acoustic neuroma, pituitary adenoma, craniopharyngioma. False only if user explicitly rules out. Null if not mentioned OR location ambiguous.",
    )

    # Table 8 - Cardiac/vascular
    infectiveEndocarditis: Optional[bool] = Field(
        None,
        description="true if user reports infective endocarditis (IE, bacterial endocarditis, vegetations on echo, or AIS with fever + new murmur clinically consistent with IE). false if explicitly ruled out. null if not mentioned.",
    )
    aorticArchDissection: Optional[bool] = Field(
        None,
        description="true if user reports known or suspected aortic arch dissection. false if explicitly ruled out. null if not mentioned.",
    )
    cervicalDissection: Optional[bool] = Field(
        None,
        description="true if user reports cervical artery dissection (carotid artery dissection, vertebral artery dissection, neck dissection). false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Coagulation
    platelets: Optional[int] = None
    inr: Optional[float] = None
    aptt: Optional[float] = None
    pt: Optional[float] = None

    # Table 8 - Neurological contraindications
    aria: Optional[bool] = Field(
        None,
        description="true if user reports amyloid-related imaging abnormalities (ARIA, ARIA-E edema, ARIA-H microhemorrhages, typically in a patient on amyloid immunotherapy). false if explicitly ruled out. null if not mentioned.",
    )
    amyloidImmunotherapy: Optional[bool] = Field(
        None,
        description="true if user reports the patient is currently on amyloid-targeting immunotherapy (lecanemab, aducanumab, donanemab, anti-amyloid antibody for Alzheimer's disease). false if explicitly ruled out. null if not mentioned.",
    )
    priorICH: Optional[bool] = Field(
        None,
        description="true if user reports a prior intracerebral hemorrhage (history of ICH, prior hemorrhagic stroke, prior intraparenchymal bleed). false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Stroke history
    recentStroke3mo: Optional[bool] = Field(
        None,
        description="true if user reports an ischemic stroke within the past 3 months separate from the current presentation. false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Recent trauma/surgery
    recentNonCNSTrauma: Optional[bool] = Field(
        None,
        description="true if user reports significant non-CNS trauma (major trauma, fall with injury, MVA causing systemic injury). false if explicitly ruled out. null if not mentioned.",
    )
    recentNonCNSSurgery10d: Optional[bool] = Field(
        None,
        description="true if user reports major non-CNS surgery within the past 10 days. false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Bleeding
    recentGIGUBleeding21d: Optional[bool] = Field(
        None,
        description="true if user reports gastrointestinal or genitourinary bleeding within the past 21 days (recent GI bleed, hematochezia, melena, hematuria, GU bleed). false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Pregnancy
    pregnancy: Optional[bool] = Field(
        None,
        description="true if user states the patient is pregnant. false if user states the patient is not pregnant. null if pregnancy status not mentioned (do not infer from sex alone).",
    )

    # Table 8 - Malignancy
    activeMalignancy: Optional[bool] = Field(
        None,
        description="true if user reports active malignancy (cancer currently being treated, metastatic disease, recent diagnosis of cancer). false if user explicitly states 'no cancer history' or rules it out. null if not mentioned.",
    )

    # Table 8 - Imaging findings
    extensiveHypodensity: Optional[bool] = Field(
        None,
        description="true if user reports extensive hypodensity on initial CT corresponding to the symptomatic stroke territory ('frank hypodensity', 'extensive low attenuation', clear established infarct on CT — density greater than contralateral unaffected white matter). false if explicitly ruled out. null if not mentioned. Per Table 8 this is an absolute contraindication.",
    )
    moyaMoya: Optional[bool] = Field(
        None,
        description="true if user reports moyamoya disease or moyamoya syndrome. false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Vascular lesions
    unrupturedAneurysm: Optional[bool] = Field(
        None,
        description="true if user reports a known unruptured intracranial aneurysm. false if explicitly ruled out. null if not mentioned.",
    )

    # Table 8 - Recent DOAC
    recentDOAC: Optional[bool] = Field(
        None,
        description="true if user reports the patient took a direct oral anticoagulant (DOAC — apixaban, rivaroxaban, dabigatran, edoxaban) within the past 48 hours. false if explicitly ruled out / last DOAC dose >48h ago. null if DOAC use timing not specified.",
    )

    # Table 8 - Additional relative contraindications
    preExistingDisability: Optional[bool] = None
    intracranialVascularMalformation: Optional[bool] = None
    recentSTEMI: Optional[bool] = None
    stemiDays: Optional[int] = None
    acutePericarditis: Optional[bool] = None
    cardiacThrombus: Optional[bool] = None  # left atrial or ventricular thrombus
    recentDuralPuncture: Optional[bool] = None
    recentArterialPuncture: Optional[bool] = None

    # Table 8 - Additional benefit-over-risk conditions
    angiographicProceduralStroke: Optional[bool] = None
    remoteGIGUBleeding: Optional[bool] = None
    historyMI: Optional[bool] = None
    recreationalDrugUse: Optional[bool] = None
    strokeMimic: Optional[bool] = None

    def compute_derived(self) -> None:
        """Compute derived fields from raw variables."""
        # These are accessed as properties
        pass

    @computed_field
    @property
    def isAdult(self) -> bool:
        """Whether patient is adult (age >= 18)."""
        if self.age is None:
            return False
        return self.age >= 18

    @computed_field
    @property
    def isLVO(self) -> bool:
        """Whether vessel is large vessel occlusion.
        'LVO' (unspecified) counts as True — patient has confirmed LVO,
        specific vessel unknown."""
        if self.vessel is None:
            return False
        stripped = self._strip_side(self.vessel)
        if stripped.upper() == "LVO":
            return True
        lvo_vessels = {"M1", "ICA", "basilar", "T-ICA"}
        return stripped in lvo_vessels

    @computed_field
    @property
    def isAnteriorLVO(self) -> bool:
        """Whether vessel is anterior circulation proximal LVO (ICA or M1)."""
        if self.vessel is None:
            return False
        anterior_lvo_vessels = {"M1", "ICA", "T-ICA"}
        return self._strip_side(self.vessel) in anterior_lvo_vessels

    @computed_field
    @property
    def isM2(self) -> bool:
        """Whether vessel is M2 segment of MCA."""
        if self.vessel is None:
            return False
        return self._strip_side(self.vessel) == "M2"

    @computed_field
    @property
    def isEVTIneligibleVessel(self) -> bool:
        """Whether vessel is one where EVT is not recommended (COR 3: No Benefit, LOE A, Section 4.7.2 Rec 8).
        Includes distal MCA (M3+), ACA segments, PCA segments, and vertebral artery.
        Note: M2 requires a separate dominant/nondominant qualifier."""
        if self.vessel is None:
            return False
        evt_ineligible = {"M3", "M4", "M5", "A1", "A2", "A3", "PCA", "P1", "P2", "vertebral"}
        return self._strip_side(self.vessel) in evt_ineligible

    @computed_field
    @property
    def isBasilar(self) -> bool:
        """Whether vessel is basilar artery."""
        if self.vessel is None:
            return False
        return self._strip_side(self.vessel) == "basilar"

    @computed_field
    @property
    def isAnterior(self) -> bool:
        """Whether vessel is anterior circulation."""
        if self.vessel is None:
            return False
        anterior_vessels = {"M1", "M2", "ICA", "ACA"}
        return self._strip_side(self.vessel) in anterior_vessels

    @staticmethod
    def _strip_side(vessel: str) -> str:
        """Strip leading side prefix and normalize vessel name."""
        v = vessel.strip()
        for prefix in ("R ", "L ", "right ", "left "):
            if v.lower().startswith(prefix.lower()):
                v = v[len(prefix):]
                break
        # Normalize compound vessel names from LLM parsing
        # e.g., "MCA M1" → "M1", "MCA M2" → "M2", "ICA terminus" → "T-ICA"
        v_lower = v.lower()
        if "m1" in v_lower:
            return "M1"
        if "m2" in v_lower:
            return "M2"
        if "ica" in v_lower and ("termin" in v_lower or "t-ica" in v_lower):
            return "T-ICA"
        if "ica" in v_lower:
            return "ICA"
        if "basilar" in v_lower:
            return "basilar"
        if "pca" in v_lower or "posterior cerebral" in v_lower:
            return "PCA"
        if "aca" in v_lower or "anterior cerebral" in v_lower:
            return "ACA"
        return v

    @computed_field
    @property
    def effectiveTimeHours(self) -> Optional[float]:
        """Best available time anchor: LKW is the primary clinical time anchor
        for all treatment window decisions (IVT, EVT, extended window).
        Falls back to timeHours (symptom recognition) only when LKW is unknown."""
        return self.lastKnownWellHours if self.lastKnownWellHours is not None else self.timeHours

    @computed_field
    @property
    def timeWindow(self) -> str:
        """Time window bucket based on effective time anchor (LKW preferred)."""
        t = self.effectiveTimeHours
        if t is None:
            return "unknown"
        if t <= 4.5:
            return "0-4.5"
        elif t <= 9:
            return "4.5-9"
        elif t <= 24:
            return "9-24"
        else:
            return ">24"


class Recommendation(BaseModel):
    """Clinical recommendation from guideline."""
    id: str
    guidelineId: str
    section: str
    sectionTitle: str = ""
    recNumber: str
    cor: str  # Class of Recommendation: I, IIa, IIb, III
    loe: str  # Level of Evidence: A, B, C
    category: str
    text: str
    sourcePages: List[int] = []
    evidenceKey: str = ""
    prerequisites: List[str] = []


class FiredRecommendation(Recommendation):
    """Recommendation that fired based on rule matching."""
    matchedRule: str = ""
    ruleId: str = ""
    # True only for the rec that defines THE eligibility pathway for this
    # scenario (e.g. rec-4.6.3-002 for 4.5–9h penumbra mismatch). Process,
    # dosing, and supporting recs stay False so the badge selector can pick
    # the pathway COR/LOE instead of being shadowed by COR 1 process recs.
    is_primary_pathway: bool = False


class Note(BaseModel):
    """Clinical note or warning."""
    severity: Literal["danger", "warning", "info"]
    text: str
    source: str


class CriteriaCheck(BaseModel):
    """Result of a single criteria check."""
    criterion: str
    met: bool
    detail: str = ""


class ScenarioRequest(BaseModel):
    """Request to evaluate clinical scenario."""
    text: str
    sessionId: Optional[str] = None


class ScenarioResponse(BaseModel):
    """Response with clinical decision support."""
    parsedVariables: ParsedVariables
    ivtResult: Optional[dict] = None
    evtResult: Optional[dict] = None
    recommendations: List[FiredRecommendation] = []
    notes: List[Note] = []
    trace: dict = {}


class QARequest(BaseModel):
    """Request for Q&A on guidelines."""
    question: str
    context: Optional[dict] = None


class QAResponse(BaseModel):
    """Response to Q&A request."""
    answer: str
    summary: str = ""
    citations: List[str] = []
    relatedSections: List[str] = []
    referencedTrials: List[str] = []


class QAValidationRequest(BaseModel):
    """Request to validate a Q&A answer."""
    uid: str
    session_id: Optional[str] = None
    question: str
    answer: str
    summary: str = ""
    citations: List[str] = []
    context: Optional[dict] = None
    feedback: str = "thumbs_down"  # "thumbs_up" or "thumbs_down"


class QAValidationResponse(BaseModel):
    """Validation result for a Q&A answer."""
    session_id: str = ""
    intentCorrect: bool = True
    recommendationsRelevant: bool = True
    recommendationsVerbatim: bool = True
    summaryAccurate: bool = True
    issues: List[str] = []
    suggestedCorrection: str = ""
    verbatimMismatches: List[str] = []


class ClinicalOverrides(BaseModel):
    """Clinician overrides for interactive decision gates."""
    table8_overrides: dict = Field(default_factory=dict, description="Per-rule overrides: {ruleId: status}")
    none_absolute: bool = Field(False, description="Bulk override: no absolute contraindications")
    none_relative: bool = Field(False, description="Bulk override: no relative contraindications")
    none_benefit_over_risk: bool = Field(False, description="Bulk override: no benefit-over-risk items")
    table4_override: Optional[bool] = Field(
        None, description="True=disabling, False=non-disabling, None=no override"
    )
    evt_available: Optional[bool] = Field(
        None, description="True=EVT available, False=not available, None=not yet answered"
    )
    # Frontend gate answers
    lkw_within_24h: Optional[bool] = Field(
        None, description="True=LKW <24h, False=LKW >24h or unknown, None=not yet answered"
    )
    m2_is_dominant: Optional[bool] = Field(
        None, description="True=dominant/proximal M2, False=nondominant/codominant, None=not yet answered"
    )
    imaging_dwi_flair: Optional[bool] = Field(
        None, description="True=DWI-FLAIR mismatch confirmed, False=no mismatch, None=not yet done"
    )
    imaging_penumbra: Optional[bool] = Field(
        None, description="True=salvageable penumbra, False=no penumbra, None=not yet done"
    )
    symptom_recognition_within_window: Optional[bool] = Field(
        None, description="True=within 4.5h of symptom recognition, False=outside, None=not yet answered"
    )
    wake_up_within_window: Optional[bool] = Field(
        None, description="True=midpoint of sleep <=9h, False=>9h, None=not yet answered"
    )


class ClinicalDecisionState(BaseModel):
    """Single source of truth for all derived clinical decisions."""
    effective_ivt_eligibility: Literal[
        "eligible", "contraindicated", "caution", "pending", "not_recommended"
    ] = "pending"
    effective_is_disabling: Optional[bool] = Field(
        None, description="Final disabling assessment after clinician override"
    )
    primary_therapy: Optional[Literal["IVT", "EVT", "DUAL", "NONE"]] = Field(
        None, description="Primary therapy pathway"
    )
    verdict: Literal[
        "ELIGIBLE", "NOT_RECOMMENDED", "CAUTION", "PENDING"
    ] = "PENDING"
    is_dual_reperfusion: bool = False
    bp_at_goal: Optional[bool] = Field(
        None, description="True if SBP <=185 and DBP <=110, None if not provided"
    )
    bp_warning: Optional[str] = None
    is_extended_window: bool = False
    visible_sections: List[str] = Field(default_factory=list)
    headline: str = ""
    # ── CDS display fields (moved from frontend) ──
    description: str = Field("", description="CDS description text below headline")
    evt_status: Literal[
        "recommended", "pending", "not_applicable"
    ] = "pending"
    evt_status_text: str = Field("", description="EVT status line detail text")
    evt_status_reason: str = Field("", description="Short reason for EVT status (e.g. 'nihss_too_low')")
    ivt_status_text: str = Field("", description="IVT status line detail text")
    ivt_badge: str = Field("ACTION NEEDED", description="IVT badge label")
    evt_missing: List[str] = Field(default_factory=list, description="Missing variables for EVT")
    ivt_missing: List[str] = Field(default_factory=list, description="Missing variables for IVT")
    is_posterior: bool = False
    is_basilar: bool = False
    evt_cor: Optional[str] = Field(None, description="COR level when EVT is recommended (e.g. '1', '2a', '2b')")
    evt_loe: Optional[str] = Field(None, description="LOE when EVT is recommended (e.g. 'A', 'B-R', 'B-NR')")
    evt_narrowing: Optional[Dict[str, Any]] = Field(None, description="Rule narrowing summary showing which EVT recs are viable/excluded")
    ivt_cor: Optional[str] = Field(None, description="COR level for the IVT recommendation that fired")
    ivt_loe: Optional[str] = Field(None, description="LOE for the IVT recommendation that fired")
    ivt_rec_id: Optional[str] = Field(None, description="Specific IVT recommendation ID that fired (e.g. 'rec-4.6.1-001')")
