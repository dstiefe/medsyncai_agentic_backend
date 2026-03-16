"""
Physician dossier models for MedSync AI Sales Intelligence Platform.

Comprehensive physician intelligence — clinical profile, business data,
competitive landscape, decision-making patterns, relationship tracking,
and compliance information. Backed by real CMS Medicare Provider Utilization data.

All CMS numbers, IFU specs, and regulatory data are stored verbatim — never rounded.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# --- Sub-models: Clinical Profile ---


class BoardCertification(BaseModel):
    board: str = Field(default="", description="Certifying board (e.g., ABNS, ABR)")
    specialty: str = Field(default="", description="Board specialty")
    expiry: Optional[str] = Field(default=None, description="Expiration date YYYY-MM")


class Publication(BaseModel):
    title: str = Field(default="", description="Publication title")
    journal: str = Field(default="", description="Journal name")
    year: Optional[int] = Field(default=None, description="Publication year")
    pmid: Optional[str] = Field(default=None, description="PubMed ID")


class SpeakingEngagement(BaseModel):
    event: str = Field(default="", description="Conference or event name")
    topic: Optional[str] = Field(default=None, description="Talk topic")
    date: Optional[str] = Field(default=None, description="Date YYYY-MM-DD")


class ClinicalProfile(BaseModel):
    fellowship_training: Optional[str] = Field(default=None, description="Fellowship details")
    board_certifications: List[BoardCertification] = Field(default_factory=list)
    publications: List[Publication] = Field(default_factory=list)
    clinical_trial_involvement: List[str] = Field(
        default_factory=list, description="e.g., ['DAWN site PI', 'DEFUSE-3 enrolling site']"
    )
    kol_status: Optional[str] = Field(
        default=None, description="national, regional, local, or none"
    )
    speaking_engagements: List[SpeakingEngagement] = Field(default_factory=list)
    preferred_techniques: List[str] = Field(
        default_factory=list, description="e.g., ['direct aspiration', 'stent retriever first']"
    )
    society_memberships: List[str] = Field(
        default_factory=list, description="e.g., ['SNIS', 'SVIN', 'AANS']"
    )


# --- Sub-models: Business Intelligence ---


class CaseVolumeByCPT(BaseModel):
    """CMS Medicare Provider Utilization data per CPT code. All numbers verbatim from CMS."""

    cpt_code: str = Field(..., description="CPT/HCPCS code")
    description: str = Field(default="", description="Procedure description")
    annual_services: int = Field(default=0, description="Total services (from CMS Tot_Srvcs)")
    beneficiaries: int = Field(default=0, description="Unique beneficiaries (from CMS Tot_Benes)")
    avg_medicare_payment: Optional[float] = Field(
        default=None, description="Avg Medicare payment per service (verbatim from CMS)"
    )
    avg_submitted_charge: Optional[float] = Field(
        default=None, description="Avg submitted charge per service (verbatim from CMS)"
    )
    avg_allowed_amount: Optional[float] = Field(
        default=None, description="Avg Medicare allowed amount (verbatim from CMS)"
    )
    place_of_service: Optional[str] = Field(
        default=None, description="F=Facility, O=Office"
    )
    trend: Optional[str] = Field(
        default=None, description="increasing, stable, or declining"
    )


class PayerMix(BaseModel):
    medicare_pct: Optional[float] = Field(default=None, description="Medicare %")
    medicaid_pct: Optional[float] = Field(default=None, description="Medicaid %")
    commercial_pct: Optional[float] = Field(default=None, description="Commercial %")
    uninsured_pct: Optional[float] = Field(default=None, description="Uninsured/other %")


class HospitalAffiliation(BaseModel):
    name: str = Field(default="", description="Hospital/facility name")
    type: Optional[str] = Field(
        default=None, description="comprehensive_stroke_center, primary_stroke_center, etc."
    )
    privilege_level: Optional[str] = Field(
        default=None, description="primary, secondary, or courtesy"
    )
    npi: Optional[str] = Field(default=None, description="Facility NPI")
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)


class ContractStatus(BaseModel):
    gpo_name: Optional[str] = Field(default=None, description="GPO name (e.g., Vizient, Premier)")
    idn_name: Optional[str] = Field(default=None, description="IDN/health system name")
    contract_expiry: Optional[str] = Field(default=None, description="Contract expiry YYYY-MM")
    formulary_status: Optional[str] = Field(
        default=None, description="on_formulary, off_formulary, pending_review"
    )


class BusinessIntelligence(BaseModel):
    cms_data_year: Optional[int] = Field(default=None, description="CMS data reporting year")
    npi: Optional[str] = Field(default=None, description="National Provider Identifier")
    case_volumes: List[CaseVolumeByCPT] = Field(default_factory=list)
    total_medicare_services: Optional[int] = Field(default=None)
    total_medicare_payments: Optional[float] = Field(default=None)
    total_beneficiaries: Optional[int] = Field(default=None)
    payer_mix: Optional[PayerMix] = Field(default=None)
    hospital_affiliations: List[HospitalAffiliation] = Field(default_factory=list)
    asc_vs_hospital: Optional[str] = Field(
        default=None, description="Preference: hospital_only, asc_preferred, both"
    )
    contract_status: Optional[ContractStatus] = Field(default=None)


# --- Sub-models: Competitive Landscape ---


class DeviceOnShelf(BaseModel):
    device_name: str = Field(default="", description="Device name")
    manufacturer: str = Field(default="", description="Manufacturer")
    category: Optional[str] = Field(default=None, description="Device category")
    years_using: Optional[int] = Field(default=None)
    satisfaction: Optional[int] = Field(
        default=None, description="Satisfaction 1-5"
    )
    notes: Optional[str] = Field(default=None)


class EvalEvent(BaseModel):
    device_name: str = Field(default="")
    manufacturer: Optional[str] = Field(default=None)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    outcome: Optional[str] = Field(
        default=None, description="adopted, rejected, pending, no_decision"
    )
    notes: Optional[str] = Field(default=None)


class CompetingRep(BaseModel):
    company: str = Field(default="")
    rep_name: Optional[str] = Field(default=None)
    relationship_strength: Optional[int] = Field(
        default=None, description="1-5 scale"
    )
    notes: Optional[str] = Field(default=None)


class CompetitiveLandscape(BaseModel):
    current_devices: List[DeviceOnShelf] = Field(default_factory=list)
    evaluation_history: List[EvalEvent] = Field(default_factory=list)
    competing_reps: List[CompetingRep] = Field(default_factory=list)
    known_objections: List[str] = Field(default_factory=list)
    pain_points: List[str] = Field(default_factory=list)


# --- Sub-models: Decision-Making ---


class Influencer(BaseModel):
    name: str = Field(default="")
    role: Optional[str] = Field(
        default=None,
        description="cath_lab_manager, materials_mgmt, vac_committee, department_chair, admin, other",
    )
    influence_level: Optional[int] = Field(default=None, description="1-5 scale")
    contact: Optional[str] = Field(default=None)


class Gatekeeper(BaseModel):
    name: str = Field(default="")
    role: Optional[str] = Field(default=None)
    contact: Optional[str] = Field(default=None)


class DecisionMakingProfile(BaseModel):
    influencers: List[Influencer] = Field(default_factory=list)
    decision_style: Optional[str] = Field(
        default=None,
        description="evidence_driven, peer_influenced, price_sensitive, early_adopter, conservative",
    )
    preferred_contact: Optional[str] = Field(
        default=None, description="in_person, phone, email, text"
    )
    best_contact_time: Optional[str] = Field(default=None)
    gatekeepers: List[Gatekeeper] = Field(default_factory=list)


# --- Sub-models: Relationship Tracking ---


class Interaction(BaseModel):
    date: str = Field(default="", description="YYYY-MM-DD")
    type: Optional[str] = Field(
        default=None,
        description="in_person, phone, email, case_support, dinner, conference, lunch_learn",
    )
    notes: Optional[str] = Field(default=None)
    follow_up: Optional[str] = Field(default=None, description="Follow-up action if any")


class SampleLoaner(BaseModel):
    device_name: str = Field(default="")
    manufacturer: Optional[str] = Field(default=None)
    date_out: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    return_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    status: Optional[str] = Field(
        default=None, description="out, returned, converted_to_purchase"
    )


class UpcomingCase(BaseModel):
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    procedure: Optional[str] = Field(default=None)
    hospital: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)


class RelationshipTracking(BaseModel):
    interactions: List[Interaction] = Field(default_factory=list)
    follow_ups_owed: List[str] = Field(default_factory=list)
    samples_loaners: List[SampleLoaner] = Field(default_factory=list)
    upcoming_cases: List[UpcomingCase] = Field(default_factory=list)
    personal_notes: List[str] = Field(
        default_factory=list, description="Rapport items — hobbies, family, alma mater"
    )


# --- Sub-models: Compliance ---


class TransferOfValue(BaseModel):
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    amount: Optional[float] = Field(default=None)
    category: Optional[str] = Field(
        default=None, description="food_beverage, consulting, travel, education, research"
    )
    description: Optional[str] = Field(default=None)


class VendorCredentialing(BaseModel):
    required: bool = Field(default=True)
    status: Optional[str] = Field(
        default=None, description="active, expired, pending"
    )
    provider: Optional[str] = Field(
        default=None, description="Reptrax, Vendormate, GHX, other"
    )
    expiry_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")


class ComplianceInfo(BaseModel):
    open_payments_total: Optional[float] = Field(
        default=None, description="CMS Open Payments total transfer of value (verbatim)"
    )
    open_payments_year: Optional[int] = Field(default=None)
    open_payments_history: List[TransferOfValue] = Field(default_factory=list)
    tov_institutional_limit: Optional[float] = Field(
        default=None, description="Institution's annual limit on industry interactions"
    )
    vendor_credentialing: Optional[VendorCredentialing] = Field(default=None)
    access_restrictions: List[str] = Field(
        default_factory=list, description="e.g., 'No lunch access', 'OR only with invitation'"
    )


# --- Sub-models: Procedure Setup (from existing design) ---


class ProcedureSetup(BaseModel):
    procedure_type: str = Field(default="", description="e.g., EVT, coiling, flow_diversion")
    frequency: Optional[str] = Field(
        default=None, description="primary, regular, occasional"
    )
    cases_per_year: Optional[int] = Field(default=None)
    approach: Optional[str] = Field(
        default=None, description="e.g., direct_aspiration, stent_retriever_first, combined"
    )
    devices_used: List[DeviceOnShelf] = Field(default_factory=list)


# --- Top-Level Dossier Model ---


class PhysicianDossier(BaseModel):
    """
    Comprehensive physician dossier for sales intelligence.

    All CMS data, device specifications, and regulatory information
    are stored verbatim — never paraphrased or rounded.
    """

    id: str = Field(..., description="Unique physician identifier (kebab-case)")
    name: str = Field(..., description="Full name with credentials")
    credentials: Optional[str] = Field(default=None, description="e.g., MD, DO, PhD")
    specialty: str = Field(default="", description="Primary specialty")
    subspecialty: Optional[str] = Field(default=None)
    npi: Optional[str] = Field(default=None, description="National Provider Identifier")
    institution: str = Field(default="")
    institution_type: Optional[str] = Field(
        default=None, description="academic, community, private_practice"
    )
    stroke_center_level: Optional[str] = Field(
        default=None, description="comprehensive, primary, thrombectomy_capable, none"
    )
    years_experience: Optional[int] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)

    # Dossier sections
    clinical_profile: ClinicalProfile = Field(default_factory=ClinicalProfile)
    business_intelligence: BusinessIntelligence = Field(default_factory=BusinessIntelligence)
    competitive_landscape: CompetitiveLandscape = Field(default_factory=CompetitiveLandscape)
    decision_making: DecisionMakingProfile = Field(default_factory=DecisionMakingProfile)
    relationship: RelationshipTracking = Field(default_factory=RelationshipTracking)
    compliance: ComplianceInfo = Field(default_factory=ComplianceInfo)

    # Procedure setups
    procedure_setups: List[ProcedureSetup] = Field(default_factory=list)

    # Personality traits (for simulation integration)
    personality_traits: Dict[str, float] = Field(
        default_factory=dict, description="Trait scores 0-1 for LLM persona"
    )

    # Metadata
    created_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp",
    )

    def summary_for_prompt(self) -> str:
        """Generate a concise text summary for LLM system prompt injection (~500 tokens)."""
        lines = [f"## Physician Dossier: {self.name}"]

        # Basic info
        parts = []
        if self.specialty:
            parts.append(self.specialty)
        if self.subspecialty:
            parts.append(self.subspecialty)
        if self.years_experience:
            parts.append(f"{self.years_experience} years experience")
        if parts:
            lines.append(f"- Specialty: {', '.join(parts)}")

        inst_parts = []
        if self.institution:
            inst_parts.append(self.institution)
        if self.stroke_center_level:
            inst_parts.append(f"({self.stroke_center_level.replace('_', ' ').title()})")
        if self.city and self.state:
            inst_parts.append(f"— {self.city}, {self.state}")
        if inst_parts:
            lines.append(f"- Institution: {' '.join(inst_parts)}")

        # Clinical profile
        cp = self.clinical_profile
        if cp.kol_status and cp.kol_status != "none":
            lines.append(f"- KOL Status: {cp.kol_status.title()}")
        if cp.publications:
            lines.append(f"- Publications: {len(cp.publications)} papers")
        if cp.clinical_trial_involvement:
            lines.append(f"- Trial Involvement: {', '.join(cp.clinical_trial_involvement[:3])}")
        if cp.preferred_techniques:
            lines.append(f"- Techniques: {', '.join(cp.preferred_techniques)}")
        if cp.society_memberships:
            lines.append(f"- Societies: {', '.join(cp.society_memberships)}")

        # Business intelligence — CMS data verbatim
        bi = self.business_intelligence
        if bi.case_volumes:
            vol_parts = []
            for cv in bi.case_volumes[:4]:
                vol_parts.append(f"{cv.cpt_code}: {cv.annual_services} services")
            lines.append(f"- Case Volumes (CMS {bi.cms_data_year or 'N/A'}): {'; '.join(vol_parts)}")
        if bi.total_medicare_payments:
            lines.append(f"- Total Medicare Payments: ${bi.total_medicare_payments:,.2f}")
        if bi.hospital_affiliations:
            hosp_names = [h.name for h in bi.hospital_affiliations[:2]]
            lines.append(f"- Hospital Affiliations: {', '.join(hosp_names)}")
        if bi.contract_status and bi.contract_status.gpo_name:
            gpo = bi.contract_status
            exp = f", expires {gpo.contract_expiry}" if gpo.contract_expiry else ""
            lines.append(f"- GPO/IDN: {gpo.gpo_name or ''} {gpo.idn_name or ''}{exp}")

        # Competitive landscape
        cl = self.competitive_landscape
        if cl.current_devices:
            dev_strs = [f"{d.device_name} ({d.manufacturer})" for d in cl.current_devices[:4]]
            lines.append(f"- Current Devices: {', '.join(dev_strs)}")
        if cl.known_objections:
            lines.append(f"- Known Objections: {'; '.join(cl.known_objections[:3])}")
        if cl.pain_points:
            lines.append(f"- Pain Points: {'; '.join(cl.pain_points[:3])}")

        # Decision making
        dm = self.decision_making
        if dm.decision_style:
            lines.append(f"- Decision Style: {dm.decision_style.replace('_', ' ').title()}")
        if dm.influencers:
            inf_strs = [f"{i.name} ({i.role})" for i in dm.influencers[:2]]
            lines.append(f"- Key Influencers: {', '.join(inf_strs)}")

        # Relationship
        rel = self.relationship
        if rel.interactions:
            last = rel.interactions[0]
            lines.append(f"- Last Interaction: {last.date} ({last.type})")
        if rel.follow_ups_owed:
            lines.append(f"- Follow-ups Owed: {'; '.join(rel.follow_ups_owed[:2])}")

        # Compliance
        comp = self.compliance
        if comp.open_payments_total is not None and comp.tov_institutional_limit:
            lines.append(
                f"- Compliance: ${comp.open_payments_total:,.2f}/${comp.tov_institutional_limit:,.2f} "
                f"Sunshine Act limit used"
            )

        return "\n".join(lines)


class PhysicianDossierSummary(BaseModel):
    """Lightweight summary for list views."""

    id: str
    name: str
    specialty: str = ""
    institution: str = ""
    city: Optional[str] = None
    state: Optional[str] = None
    npi: Optional[str] = None
    stroke_center_level: Optional[str] = None
    total_procedures: Optional[int] = None
    years_experience: Optional[int] = None
    last_interaction: Optional[str] = None
    completion_pct: Optional[int] = Field(
        default=None, description="% of dossier fields populated"
    )
