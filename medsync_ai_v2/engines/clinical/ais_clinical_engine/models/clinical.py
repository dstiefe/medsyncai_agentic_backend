from typing import List, Literal, Optional
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
    wakeUp: Optional[bool] = None

    # NIHSS
    nihss: Optional[int] = Field(None, ge=0, le=42)
    nihssItems: Optional[NIHSSItems] = None

    # Imaging - vessel and anatomy
    vessel: Optional[str] = None  # M1, M2, ICA, basilar, ACA, PCA, etc.
    side: Optional[str] = None  # left, right, anterior, basilar
    m2Dominant: Optional[bool] = None  # True=dominant proximal M2, False=nondominant/codominant

    # Imaging - extent
    aspects: Optional[int] = Field(None, ge=0, le=10)
    prestrokeMRS: Optional[int] = Field(None, ge=0, le=6)

    # Vitals
    sbp: Optional[int] = Field(None, ge=0)
    dbp: Optional[int] = Field(None, ge=0)

    # Hemorrhage
    hemorrhage: Optional[bool] = None

    # Medications
    onAntiplatelet: Optional[bool] = None
    onAnticoagulant: Optional[bool] = None

    # Conditions
    sickleCell: Optional[bool] = None
    dwiFlair: Optional[bool] = None  # DWI-FLAIR mismatch
    penumbra: Optional[bool] = None

    # Cerebral microbleeds
    cmbs: Optional[bool] = None
    cmbCount: Optional[int] = None

    # Prior interventions
    ivtGiven: Optional[bool] = None
    ivtNotGiven: Optional[bool] = None
    evtUnavailable: Optional[bool] = None
    nonDisabling: Optional[bool] = None

    # Table 8 - Recent procedures/trauma
    recentTBI: Optional[bool] = None
    tbiDays: Optional[int] = None
    recentNeurosurgery: Optional[bool] = None
    neurosurgeryDays: Optional[int] = None
    acuteSpinalCordInjury: Optional[bool] = None

    # Table 8 - CNS neoplasms
    intraAxialNeoplasm: Optional[bool] = None
    extraAxialNeoplasm: Optional[bool] = None

    # Table 8 - Cardiac/vascular
    infectiveEndocarditis: Optional[bool] = None
    aorticArchDissection: Optional[bool] = None
    cervicalDissection: Optional[bool] = None

    # Table 8 - Coagulation
    platelets: Optional[int] = None
    inr: Optional[float] = None
    aptt: Optional[float] = None
    pt: Optional[float] = None

    # Table 8 - Neurological contraindications
    aria: Optional[bool] = None  # amyloid-related imaging abnormalities
    amyloidImmunotherapy: Optional[bool] = None
    priorICH: Optional[bool] = None

    # Table 8 - Stroke history
    recentStroke3mo: Optional[bool] = None

    # Table 8 - Recent trauma/surgery
    recentNonCNSTrauma: Optional[bool] = None
    recentNonCNSSurgery10d: Optional[bool] = None

    # Table 8 - Bleeding
    recentGIGUBleeding21d: Optional[bool] = None

    # Table 8 - Pregnancy
    pregnancy: Optional[bool] = None

    # Table 8 - Malignancy
    activeMalignancy: Optional[bool] = None

    # Table 8 - Imaging findings
    extensiveHypodensity: Optional[bool] = None
    moyaMoya: Optional[bool] = None

    # Table 8 - Vascular lesions
    unrupturedAneurysm: Optional[bool] = None

    # Table 8 - Recent DOAC
    recentDOAC: Optional[bool] = None

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
    def timeWindow(self) -> str:
        """Time window bucket."""
        if self.timeHours is None:
            return "unknown"
        if self.timeHours <= 4.5:
            return "0-4.5"
        elif self.timeHours <= 9:
            return "4.5-9"
        elif self.timeHours <= 24:
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
    question: str
    answer: str
    summary: str = ""
    citations: List[str] = []
    context: Optional[dict] = None
    feedback: str = "thumbs_down"  # "thumbs_up" or "thumbs_down"


class QAValidationResponse(BaseModel):
    """Validation result for a Q&A answer."""
    intentCorrect: bool = True
    recommendationsRelevant: bool = True
    recommendationsVerbatim: bool = True
    summaryAccurate: bool = True
    issues: List[str] = []
    suggestedCorrection: str = ""
    verbatimMismatches: List[str] = []


class ClinicalOverrides(BaseModel):
    """Clinician overrides for interactive decision gates."""
    table8_overrides: dict[str, Literal[
        "confirmed_present", "confirmed_absent"
    ]] = Field(default_factory=dict, description="Per-rule overrides: {ruleId: status}")
    none_absolute: bool = Field(False, description="Bulk override: no absolute contraindications")
    none_relative: bool = Field(False, description="Bulk override: no relative contraindications")
    none_benefit_over_risk: bool = Field(False, description="Bulk override: no benefit-over-risk items")
    table4_override: Optional[bool] = Field(
        None, description="True=disabling, False=non-disabling, None=no override"
    )
    evt_available: Optional[bool] = Field(
        None, description="True=EVT available, False=not available, None=not yet answered"
    )


class ClinicalDecisionState(BaseModel):
    """Single source of truth for all derived clinical decisions.

    Replaces the 10 frontend decision points identified in the migration plan.
    Every field is deterministically computed by DecisionEngine.compute_effective_state().
    """
    # From overrides (#1, #2, #3)
    effective_ivt_eligibility: Literal[
        "eligible", "contraindicated", "caution", "pending"
    ] = "pending"

    # From Table 4 override (#4)
    effective_is_disabling: Optional[bool] = Field(
        None, description="Final disabling assessment after clinician override"
    )

    # From EVT availability (#5)
    primary_therapy: Optional[Literal["IVT", "EVT", "DUAL", "NONE"]] = Field(
        None, description="Primary therapy pathway"
    )

    # Quick answer verdict (#6)
    verdict: Literal[
        "ELIGIBLE", "NOT_ELIGIBLE", "CAUTION", "PENDING"
    ] = "PENDING"

    # Dual reperfusion (#7)
    is_dual_reperfusion: bool = False

    # BP check (#8)
    bp_at_goal: Optional[bool] = Field(
        None, description="True if SBP <=185 and DBP <=110, None if not provided"
    )
    bp_warning: Optional[str] = None

    # Extended window detection (#9)
    is_extended_window: bool = False

    # Pathway visibility (#10)
    visible_sections: List[str] = Field(default_factory=list)

    # CDS banner text
    headline: str = ""
