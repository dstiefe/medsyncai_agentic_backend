from typing import Dict
from ..models.clinical import FiredRecommendation, Note, ParsedVariables
from ..models.table4 import Table4Result
from ..models.table8 import Table8Result
from .table8_agent import Table8Agent
from .table4_agent import Table4Agent
from .ivt_recs_agent import IVTRecsAgent
from .checklist_agent import ClinicalChecklistAgent


class IVTOrchestrator:
    """Orchestrates IVT decision support pipeline."""

    def __init__(self, recommendations_store: Dict = None):
        """Initialize orchestrator with recommendation store."""
        if recommendations_store is None:
            from ..data.loader import load_recommendations_by_id
            recommendations_store = load_recommendations_by_id()
        self.table8_agent = Table8Agent()
        self.table4_agent = Table4Agent()
        self.ivt_recs_agent = IVTRecsAgent(recommendations_store)
        self.checklist_agent = ClinicalChecklistAgent()
        self.recommendations_store = recommendations_store

    def evaluate(self, parsed: ParsedVariables) -> Dict:
        """
        Evaluate clinical scenario through IVT pipeline.

        Returns dict with:
        - eligible: bool
        - riskTier: str
        - disablingAssessment: Table4Result
        - recommendations: list[FiredRecommendation]
        - contraindications: list[str]
        - warnings: list[str]
        - notes: list[Note]
        """
        # Step 1: Evaluate Table 8
        table8_result = self.table8_agent.evaluate(parsed)

        # Step 1b: Evaluate clinical checklists (EVT, imaging, BP, meds, supportive)
        clinical_checklists = self.checklist_agent.evaluate(parsed)
        checklists_output = [s.model_dump() for s in clinical_checklists]

        # Step 3: Evaluate Table 4 (needed even for absolute contraindications for completeness)
        table4_result = self.table4_agent.evaluate(parsed.nihss, parsed.nihssItems, parsed.nonDisabling)

        # Step 2: If absolute contraindication, stop here
        if table8_result.riskTier == "absolute_contraindication":
            return {
                "eligible": False,
                "riskTier": table8_result.riskTier,
                "disablingAssessment": table4_result.model_dump(),
                "recommendations": [],
                "contraindications": table8_result.absoluteContraindications,
                "warnings": table8_result.relativeContraindications,
                "notes": table8_result.notes,
                "table8Checklist": [item.model_dump() for item in table8_result.checklist],
                "unassessedCount": table8_result.unassessedCount,
                "clinicalChecklists": checklists_output,
                "ivtResult": {
                    "eligible": False,
                    "contraindication": "absolute"
                }
            }

        # Step 4: Fire IVT recommendations
        recommendations = self.ivt_recs_agent.evaluate(
            parsed,
            table8_result,
            table4_result
        )

        # Step 5: Compile notes
        all_notes = table8_result.notes.copy()

        # Add warning about relative contraindications
        if table8_result.riskTier == "relative_contraindication":
            for rel_contra in table8_result.relativeContraindications:
                all_notes.append(
                    Note(
                        severity="warning",
                        text=f"Relative contraindication: {rel_contra}",
                        source="Table 8"
                    )
                )

        # Add clinician disclaimer for IVT deficit assessment
        if table4_result.isDisabling is True:
            all_notes.append(
                Note(
                    severity="info",
                    text=(
                        "Deficit severity assessment is system-determined. "
                        "Final determination of whether deficits are clearly disabling "
                        "should be confirmed by the treating clinician per Table 4 "
                        "BATHE criteria (Bathing, Ambulating, Toileting, Hygiene, Eating)."
                    ),
                    source="Table 4"
                )
            )

        # Add info about benefit-over-risk items
        if table8_result.benefitOverRisk:
            for benefit_item in table8_result.benefitOverRisk:
                all_notes.append(
                    Note(
                        severity="info",
                        text=f"Consider benefit vs risk: {benefit_item}",
                        source="Table 8"
                    )
                )

        return {
            "eligible": True,
            "riskTier": table8_result.riskTier,
            "disablingAssessment": table4_result.model_dump(),
            "recommendations": recommendations,
            "contraindications": table8_result.absoluteContraindications,
            "warnings": table8_result.relativeContraindications,
            "notes": all_notes,
            "table8Checklist": [item.model_dump() for item in table8_result.checklist],
            "unassessedCount": table8_result.unassessedCount,
            "clinicalChecklists": checklists_output,
            "ivtResult": {
                "eligible": True,
                "riskTier": table8_result.riskTier,
                "disablingAssessment": table4_result.model_dump(),
                "recommendations": [rec.model_dump() for rec in recommendations]
            }
        }
