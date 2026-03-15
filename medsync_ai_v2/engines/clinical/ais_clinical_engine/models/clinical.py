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
    wakeUp: Optional[bool] = None

    # NIHSS
    nihss: Optional[int] = Field(None, ge=0, le=42)
    nihssItems: Optional[NIHSSItems] = None

    # Imaging - vessel and anatomy
    vessel: Optional[str] = None  # M1, M2, ICA, basilar, ACA, PCA, etc.
    side: Optional[str] = None  # left, right, anterior, basilar

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
        """Whether vessel is large vessel occlusion."""
        if self.vessel is None:
            return False
        lvo_vessels = {"M1", "ICA", "basilar", "T-ICA"}
        return self._strip_side(self.vessel) in lvo_vessels

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
        """Strip leading side prefix (R/L/right/left) from vessel name."""
        v = vessel.strip()
        for prefix in ("R ", "L ", "right ", "left "):
            if v.startswith(prefix):
                return v[len(prefix):]
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
    citations: List[str] = []
    relatedSections: List[str] = []


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
