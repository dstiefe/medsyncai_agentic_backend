"""
Physician Dossier Service for MedSync AI Sales Intelligence Platform.

Manages CRUD operations for physician dossiers with JSON file persistence.
All CMS data stored verbatim — never rounded or paraphrased.
"""

import json
import shutil
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from ..models.physician_dossier import (
    Interaction,
    PhysicianDossier,
    PhysicianDossierSummary,
)


class DossierService:
    """JSON file-based persistence for physician dossiers."""

    FILENAME = "physician_dossiers.json"
    SEED_DIR = "data_pipeline"

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = get_settings().data_dir
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._dossiers: Dict[str, PhysicianDossier] = {}
        self._load_initial()

    def _load_initial(self) -> None:
        """Load dossiers from data dir, falling back to seed data."""
        filepath = self.data_dir / self.FILENAME
        if not filepath.exists():
            # Try to copy seed data from data_pipeline/
            # Check multiple possible locations
            candidates = [
                self.data_dir.parent / self.SEED_DIR / self.FILENAME,
                self.data_dir.parent / "backend" / self.SEED_DIR / self.FILENAME,
                Path(__file__).parent.parent.parent / self.SEED_DIR / self.FILENAME,
            ]
            for seed_path in candidates:
                if seed_path.exists():
                    shutil.copy2(seed_path, filepath)
                    break

        if filepath.exists():
            try:
                with open(filepath, "r") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    for item in raw:
                        dossier = PhysicianDossier(**item)
                        self._dossiers[dossier.id] = dossier
                elif isinstance(raw, dict) and "dossiers" in raw:
                    for item in raw["dossiers"]:
                        dossier = PhysicianDossier(**item)
                        self._dossiers[dossier.id] = dossier
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to load dossiers: {e}")

    def _save(self) -> None:
        """Thread-safe write to JSON file."""
        filepath = self.data_dir / self.FILENAME
        data = [d.model_dump() for d in self._dossiers.values()]
        with self._lock:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)

    def _compute_completion(self, dossier: PhysicianDossier) -> int:
        """Compute % of dossier sections that have data."""
        sections = [
            dossier.clinical_profile,
            dossier.business_intelligence,
            dossier.competitive_landscape,
            dossier.decision_making,
            dossier.relationship,
            dossier.compliance,
        ]
        filled = 0
        total = 0
        for section in sections:
            d = section.model_dump()
            for key, val in d.items():
                total += 1
                if val and val != [] and val != {} and val != "":
                    filled += 1
        return round((filled / total) * 100) if total > 0 else 0

    def _compute_total_procedures(self, dossier: PhysicianDossier) -> int:
        """Sum procedural CPT case volumes (36xxx, 37xxx, 61xxx, 75xxx)."""
        total = 0
        for cv in dossier.business_intelligence.case_volumes:
            code = cv.cpt_code
            if code.startswith(("36", "37", "61", "75")):
                total += cv.annual_services
        return total

    def list_dossiers(self) -> List[PhysicianDossierSummary]:
        """Return lightweight summaries for all dossiers."""
        summaries = []
        for d in self._dossiers.values():
            last_interaction = None
            if d.relationship.interactions:
                dates = [i.date for i in d.relationship.interactions if i.date]
                if dates:
                    last_interaction = max(dates)

            summaries.append(
                PhysicianDossierSummary(
                    id=d.id,
                    name=d.name,
                    specialty=d.specialty,
                    institution=d.institution,
                    city=d.city,
                    state=d.state,
                    npi=d.npi,
                    stroke_center_level=d.stroke_center_level,
                    total_procedures=self._compute_total_procedures(d),
                    years_experience=d.years_experience,
                    last_interaction=last_interaction,
                    completion_pct=self._compute_completion(d),
                )
            )
        return summaries

    def get_dossier(self, physician_id: str) -> Optional[PhysicianDossier]:
        """Get a full dossier by ID."""
        return self._dossiers.get(physician_id)

    def create_dossier(self, dossier: PhysicianDossier) -> PhysicianDossier:
        """Create a new dossier."""
        now = datetime.utcnow().isoformat()
        dossier.created_at = now
        dossier.updated_at = now
        self._dossiers[dossier.id] = dossier
        self._save()
        return dossier

    def update_dossier(
        self, physician_id: str, updates: dict
    ) -> Optional[PhysicianDossier]:
        """Full update of a dossier using dict merge."""
        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        current = existing.model_dump()
        current.update(updates)
        current["updated_at"] = datetime.utcnow().isoformat()
        updated = PhysicianDossier(**current)
        self._dossiers[physician_id] = updated
        self._save()
        return updated

    def update_section(
        self, physician_id: str, section: str, data: dict
    ) -> Optional[PhysicianDossier]:
        """Update a specific section of a dossier."""
        valid_sections = [
            "clinical_profile",
            "business_intelligence",
            "competitive_landscape",
            "decision_making",
            "relationship",
            "compliance",
        ]
        if section not in valid_sections:
            return None

        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        current = existing.model_dump()
        if section in current:
            if isinstance(current[section], dict):
                current[section].update(data)
            else:
                current[section] = data
        current["updated_at"] = datetime.utcnow().isoformat()
        updated = PhysicianDossier(**current)
        self._dossiers[physician_id] = updated
        self._save()
        return updated

    def delete_dossier(self, physician_id: str) -> bool:
        """Delete a dossier by ID."""
        if physician_id in self._dossiers:
            del self._dossiers[physician_id]
            self._save()
            return True
        return False

    def add_interaction(
        self, physician_id: str, interaction: Interaction
    ) -> Optional[PhysicianDossier]:
        """Append an interaction to a dossier's relationship section."""
        existing = self._dossiers.get(physician_id)
        if not existing:
            return None

        existing.relationship.interactions.insert(0, interaction)
        existing.updated_at = datetime.utcnow().isoformat()
        self._save()
        return existing

    def get_prompt_summary(self, physician_id: str) -> Optional[str]:
        """Get LLM-ready text summary for a dossier."""
        dossier = self._dossiers.get(physician_id)
        if not dossier:
            return None
        return dossier.summary_for_prompt()

    async def generate_payer_intelligence(
        self, physician_id: str
    ) -> Optional[PhysicianDossier]:
        """Generate AI-synthesized payer intelligence from all CMS data."""
        import logging
        from .llm_service import LLMService
        from ..models.physician_dossier import PayerIntelligenceSummary

        logger = logging.getLogger(__name__)
        dossier = self._dossiers.get(physician_id)
        if not dossier:
            return None

        # Build comprehensive data prompt from all sources
        bi = dossier.business_intelligence
        data_sections = [f"# Financial Intelligence Data: {dossier.name}"]
        data_sections.append(f"Institution: {dossier.institution}, {dossier.city}, {dossier.state}")
        data_sections.append(f"Specialty: {dossier.specialty}")

        # Physician Medicare utilization
        if bi.case_volumes:
            data_sections.append("\n## Physician Medicare Utilization (CMS PUF)")
            data_sections.append(f"Data Year: {bi.cms_data_year or 'N/A'}")
            data_sections.append(f"NPI: {bi.npi or 'N/A'}")
            total_svc = bi.total_medicare_services or sum(cv.annual_services for cv in bi.case_volumes)
            total_pay = bi.total_medicare_payments or 0
            total_bene = bi.total_beneficiaries or 0
            data_sections.append(f"Total Medicare Services: {total_svc}")
            data_sections.append(f"Total Medicare Payments: ${total_pay:,.2f}")
            data_sections.append(f"Total Beneficiaries: {total_bene}")
            for cv in bi.case_volumes:
                line = f"- CPT {cv.cpt_code} ({cv.description}): {cv.annual_services} services, {cv.beneficiaries} beneficiaries"
                if cv.avg_medicare_payment:
                    line += f", avg payment ${cv.avg_medicare_payment:,.2f}"
                if cv.avg_submitted_charge:
                    line += f", avg charge ${cv.avg_submitted_charge:,.2f}"
                if cv.trend:
                    line += f" [trend: {cv.trend}]"
                data_sections.append(line)

        # Physician payer mix
        if bi.payer_mix:
            pm = bi.payer_mix
            data_sections.append("\n## Physician Payer Mix")
            if pm.medicare_pct is not None:
                data_sections.append(f"- Medicare: {pm.medicare_pct}%")
            if pm.medicaid_pct is not None:
                data_sections.append(f"- Medicaid: {pm.medicaid_pct}%")
            if pm.commercial_pct is not None:
                data_sections.append(f"- Commercial: {pm.commercial_pct}%")
            if pm.uninsured_pct is not None:
                data_sections.append(f"- Uninsured/Other: {pm.uninsured_pct}%")

        # Hospital data
        for h in bi.hospital_affiliations:
            data_sections.append(f"\n## Hospital: {h.name}")
            data_sections.append(f"Location: {h.city}, {h.state}")
            data_sections.append(f"Type: {h.type or 'N/A'}")
            data_sections.append(f"Privilege: {h.privilege_level or 'N/A'}")

            if h.financials:
                hf = h.financials
                data_sections.append(f"\n### Financial Profile (CMS HCRIS {hf.data_year or 'N/A'})")
                if hf.total_beds:
                    data_sections.append(f"- Licensed Beds: {hf.total_beds}")
                if hf.total_discharges:
                    data_sections.append(f"- Total Discharges: {hf.total_discharges:,}")
                if hf.medicare_discharges:
                    data_sections.append(f"- Medicare Discharges: {hf.medicare_discharges:,}")
                if hf.medicaid_discharges:
                    data_sections.append(f"- Medicaid Discharges: {hf.medicaid_discharges:,}")
                if hf.total_patient_revenue:
                    data_sections.append(f"- Total Patient Revenue: ${hf.total_patient_revenue:,.0f}")
                if hf.medicare_inpatient_revenue:
                    data_sections.append(f"- Medicare Inpatient Revenue: ${hf.medicare_inpatient_revenue:,.0f}")
                if hf.medicaid_inpatient_revenue:
                    data_sections.append(f"- Medicaid Inpatient Revenue: ${hf.medicaid_inpatient_revenue:,.0f}")
                if hf.medicare_pct is not None:
                    data_sections.append(f"- Payer Mix: Medicare {hf.medicare_pct}%, Medicaid {hf.medicaid_pct}%, Commercial {hf.commercial_pct}%")
                if hf.case_mix_index:
                    data_sections.append(f"- Case Mix Index: {hf.case_mix_index}")

            if h.quality:
                hq = h.quality
                data_sections.append(f"\n### Quality Profile (CMS Hospital Compare)")
                if hq.overall_star_rating:
                    data_sections.append(f"- CMS Star Rating: {hq.overall_star_rating}/5")
                if hq.ownership_type:
                    data_sections.append(f"- Ownership: {hq.ownership_type}")
                if hq.teaching_status:
                    data_sections.append(f"- Teaching Status: {hq.teaching_status}")
                if hq.accreditation:
                    data_sections.append(f"- Accreditation: {hq.accreditation}")
                if hq.stroke_certification:
                    data_sections.append(f"- Stroke Certification: {hq.stroke_certification}")

        # Contract/GPO
        if bi.contract_status:
            cs = bi.contract_status
            data_sections.append("\n## Contract & GPO Status")
            if cs.gpo_name:
                data_sections.append(f"- GPO: {cs.gpo_name}")
            if cs.idn_name:
                data_sections.append(f"- IDN/Health System: {cs.idn_name}")
            if cs.contract_expiry:
                data_sections.append(f"- Contract Expiry: {cs.contract_expiry}")
            if cs.formulary_status:
                data_sections.append(f"- Formulary Status: {cs.formulary_status}")

        # Competitive landscape context
        cl = dossier.competitive_landscape
        if cl.current_devices:
            data_sections.append("\n## Current Device Stack")
            for d in cl.current_devices:
                data_sections.append(f"- {d.device_name} ({d.manufacturer})")

        data_text = "\n".join(data_sections)

        system_prompt = """You are a medical device sales intelligence analyst for MedSync AI.

Analyze ALL the financial, utilization, quality, and payer mix data provided and synthesize it into actionable intelligence for a neurovascular medical device sales representative.

Your analysis must cross-reference physician utilization data with hospital financials, payer mix, quality metrics, and competitive landscape to generate insights that help the rep sell more effectively.

Respond in EXACTLY this JSON format:
{
  "key_insights": ["insight1", "insight2", "insight3", "insight4", "insight5"],
  "sales_implications": ["implication1", "implication2", "implication3"],
  "payer_narrative": "2-3 paragraph synthesis of the financial intelligence...",
  "risk_factors": ["risk1", "risk2"],
  "opportunities": ["opportunity1", "opportunity2", "opportunity3"]
}

Guidelines:
- key_insights: 4-5 specific insights derived from cross-referencing multiple data sources. Reference actual numbers.
- sales_implications: 3 concrete, actionable recommendations for the sales rep. Be specific about what to say/do.
- payer_narrative: Synthesize how payer mix, hospital financials, case volumes, and quality data connect. Explain what this means for device purchasing decisions.
- risk_factors: 2-3 financial or reimbursement risks the rep should be aware of.
- opportunities: 3 selling opportunities derived from the data patterns.

Focus on neurovascular devices: aspiration catheters, stent retrievers, guide catheters, microcatheters, flow diverters, coils."""

        try:
            llm = LLMService()
            response = await llm.generate(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": data_text}],
                temperature=0.3,
                max_tokens=2000,
            )

            # Parse JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = PayerIntelligenceSummary(
                    generated_at=datetime.utcnow().isoformat(),
                    key_insights=parsed.get("key_insights", []),
                    sales_implications=parsed.get("sales_implications", []),
                    payer_narrative=parsed.get("payer_narrative", ""),
                    risk_factors=parsed.get("risk_factors", []),
                    opportunities=parsed.get("opportunities", []),
                )
                dossier.business_intelligence.payer_intelligence_summary = summary
                dossier.updated_at = datetime.utcnow().isoformat()
                self._save()
                return dossier
            else:
                logger.error("Failed to parse JSON from LLM response")
                return None

        except Exception as e:
            logger.exception(f"Error generating payer intelligence: {e}")
            raise


@lru_cache(maxsize=1)
def get_dossier_service() -> DossierService:
    """Get the singleton DossierService instance."""
    return DossierService()
