"""
Clinical Checklist Agent.

Evaluates all clinical domains against parsed variables to produce
a comprehensive view of what has been assessed vs what still needs
clinician attention.

Domains covered:
- EVT eligibility criteria
- Imaging assessment
- Blood pressure management
- Medication considerations
- General supportive care

Design: Each domain defines a set of checklist rules. For each rule,
the agent checks whether the required variables are present (assessed)
or None (unassessed). If a rule has a trigger, it can also determine
confirmed_present vs confirmed_absent.
"""

from typing import Dict, List, Optional, Set
from ..models.clinical import ParsedVariables
from ..models.checklist import (
    ChecklistItem, ChecklistSummary, ClinicalChecklistRule
)


# ─────────────────────────────────────────────────────────────────────
# EVT ELIGIBILITY CHECKLIST
# ─────────────────────────────────────────────────────────────────────

EVT_RULES: List[ClinicalChecklistRule] = [
    ClinicalChecklistRule(
        id="evt-chk-001",
        domain="evt_eligibility",
        category="vessel",
        condition="Large vessel occlusion (LVO) identified",
        guidance="CTA or MRA should confirm occlusion site. See Section 4.7.2 for EVT eligibility by vessel.",
        variables=["vessel"],
        recIds=["rec-4.7.2-001", "rec-4.7.2-002"],
        sourceTable="Section 4.7.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-002",
        domain="evt_eligibility",
        category="circulation",
        condition="Anterior vs posterior circulation determined",
        guidance="Anterior circulation (ICA, M1/M2) and posterior circulation (basilar) have distinct EVT criteria. See Sections 4.7.2 and 4.7.3.",
        variables=["vessel"],
        recIds=["rec-4.7.2-001", "rec-4.7.3-001"],
        sourceTable="Section 4.7",
    ),
    ClinicalChecklistRule(
        id="evt-chk-003",
        domain="evt_eligibility",
        category="time_window",
        condition="Time from last known normal established",
        guidance="Time window affects EVT eligibility criteria. See Section 4.7.2 Recs 1-6 for time-based criteria.",
        variables=["timeHours"],
        recIds=["rec-4.7.2-001", "rec-4.7.2-003", "rec-4.7.2-004", "rec-4.7.2-005"],
        sourceTable="Section 4.7.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-004",
        domain="evt_eligibility",
        category="imaging",
        condition="ASPECTS score obtained",
        guidance="ASPECTS is used in EVT eligibility criteria. See Section 3.2 for imaging recommendations and Section 4.7.2 for EVT thresholds.",
        variables=["aspects"],
        recIds=["rec-3.2-001", "rec-4.7.2-001"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-005",
        domain="evt_eligibility",
        category="functional_status",
        condition="Pre-stroke functional status (mRS) assessed",
        guidance="Pre-stroke mRS is part of EVT eligibility criteria. See Section 4.7.2 for mRS thresholds by scenario.",
        variables=["prestrokeMRS"],
        recIds=["rec-4.7.2-001", "rec-4.7.2-003", "rec-4.7.2-005"],
        sourceTable="Section 4.7.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-006",
        domain="evt_eligibility",
        category="age",
        condition="Age documented",
        guidance="Age is relevant to EVT eligibility. See Section 4.7.2 for age-related criteria.",
        variables=["age"],
        recIds=["rec-4.7.2-001", "rec-4.7.2-006"],
        sourceTable="Section 4.7.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-007",
        domain="evt_eligibility",
        category="severity",
        condition="Stroke severity (NIHSS) documented",
        guidance="NIHSS score is part of EVT eligibility criteria. See Section 4.7.2 for NIHSS thresholds.",
        variables=["nihss"],
        recIds=["rec-4.7.2-001", "rec-4.7.2-005", "rec-4.7.2-006"],
        sourceTable="Section 4.7.2",
    ),
    ClinicalChecklistRule(
        id="evt-chk-008",
        domain="evt_eligibility",
        category="perfusion",
        condition="Perfusion imaging for extended window",
        guidance="Perfusion imaging (CT perfusion or MRI DWI/PWI) is used for extended-window EVT eligibility. See Section 3.2 and Section 4.7.2 Recs 3-5.",
        variables=["penumbra", "dwiFlair"],
        recIds=["rec-3.2-006", "rec-3.2-007", "rec-4.7.2-003", "rec-4.7.2-004", "rec-4.7.2-005"],
        sourceTable="Section 3.2",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# IMAGING ASSESSMENT CHECKLIST
# ─────────────────────────────────────────────────────────────────────

IMAGING_RULES: List[ClinicalChecklistRule] = [
    ClinicalChecklistRule(
        id="img-chk-001",
        domain="imaging",
        category="hemorrhage",
        condition="Hemorrhage excluded on CT/MRI",
        guidance="Exclude intracranial hemorrhage before reperfusion therapy. See Section 3.2 Rec 1.",
        variables=["hemorrhage"],
        recIds=["rec-3.2-001"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="img-chk-002",
        domain="imaging",
        category="hypodensity",
        condition="Extent of early ischemic changes assessed",
        guidance="Extensive hypodensity on CT may affect IVT eligibility. See Table 8 and Section 3.2.",
        variables=["extensiveHypodensity"],
        recIds=["rec-3.2-001"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="img-chk-003",
        domain="imaging",
        category="vessel_imaging",
        condition="Vascular imaging (CTA/MRA) obtained",
        guidance="Vascular imaging identifies occlusion site for EVT candidacy. See Section 3.2 Recs 2-4.",
        variables=["vessel"],
        recIds=["rec-3.2-002", "rec-3.2-003", "rec-3.2-004"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="img-chk-004",
        domain="imaging",
        category="aspects",
        condition="ASPECTS score documented",
        guidance="ASPECTS assesses early ischemic changes on CT. See Section 3.2 and Section 4.7.2 for thresholds.",
        variables=["aspects"],
        recIds=["rec-3.2-001", "rec-4.7.2-001"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="img-chk-005",
        domain="imaging",
        category="perfusion",
        condition="Perfusion imaging considered (if extended window)",
        guidance="Perfusion imaging identifies salvageable tissue in extended time windows. See Section 3.2 Recs 6-7.",
        variables=["penumbra"],
        recIds=["rec-3.2-006", "rec-3.2-007"],
        sourceTable="Section 3.2",
    ),
    ClinicalChecklistRule(
        id="img-chk-006",
        domain="imaging",
        category="dwi_flair",
        condition="DWI-FLAIR mismatch assessed (if wake-up stroke)",
        guidance="DWI-FLAIR mismatch identifies treatment-window eligibility for wake-up strokes. See Section 4.6.3.",
        variables=["dwiFlair"],
        recIds=["rec-4.6.3-001", "rec-4.6.3-002"],
        sourceTable="Section 4.6.3",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# BLOOD PRESSURE MANAGEMENT CHECKLIST
# ─────────────────────────────────────────────────────────────────────

BP_RULES: List[ClinicalChecklistRule] = [
    ClinicalChecklistRule(
        id="bp-chk-001",
        domain="bp_management",
        category="systolic",
        condition="Systolic blood pressure documented",
        guidance="BP thresholds affect IVT and EVT eligibility. See Section 4.3 for BP management recommendations.",
        variables=["sbp"],
        recIds=["rec-4.3-001", "rec-4.3-002"],
        sourceTable="Section 4.3",
    ),
    ClinicalChecklistRule(
        id="bp-chk-002",
        domain="bp_management",
        category="diastolic",
        condition="Diastolic blood pressure documented",
        guidance="Diastolic BP is part of IVT eligibility thresholds. See Section 4.3 and Table 8.",
        variables=["dbp"],
        recIds=["rec-4.3-001", "rec-4.3-002"],
        sourceTable="Section 4.3",
    ),
    ClinicalChecklistRule(
        id="bp-chk-003",
        domain="bp_management",
        category="ivt_threshold",
        condition="BP eligibility for IVT assessed (< 185/110)",
        guidance="See Section 4.3 Recs 1-2 and Table 8 for BP thresholds before and during IVT.",
        variables=["sbp", "dbp"],
        recIds=["rec-4.3-001", "rec-4.3-002"],
        sourceTable="Table 8",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# MEDICATION / COAGULATION CHECKLIST
# ─────────────────────────────────────────────────────────────────────

MEDICATION_RULES: List[ClinicalChecklistRule] = [
    ClinicalChecklistRule(
        id="med-chk-001",
        domain="medications",
        category="anticoagulant",
        condition="Anticoagulant use assessed",
        guidance="Anticoagulant use affects IVT eligibility. See Table 8 and Section 4.6.1 for specific thresholds.",
        variables=["onAnticoagulant", "recentDOAC"],
        recIds=["rec-4.6.1-009", "rec-4.6.1-010", "rec-4.6.1-011"],
        sourceTable="Table 8",
    ),
    ClinicalChecklistRule(
        id="med-chk-002",
        domain="medications",
        category="antiplatelet",
        condition="Antiplatelet use assessed",
        guidance="See Section 4.6.1 for antiplatelet therapy considerations with IVT.",
        variables=["onAntiplatelet"],
        recIds=["rec-4.6.1-012"],
        sourceTable="Section 4.6.1",
    ),
    ClinicalChecklistRule(
        id="med-chk-003",
        domain="medications",
        category="coagulation",
        condition="Coagulation labs obtained (platelets, INR, aPTT)",
        guidance="See Table 8 for coagulopathy contraindication thresholds and Section 4.6.1 Rec 8 for lab timing.",
        variables=["platelets", "inr", "aptt", "pt"],
        recIds=["rec-4.6.1-008"],
        sourceTable="Table 8",
    ),
    ClinicalChecklistRule(
        id="med-chk-004",
        domain="medications",
        category="glucose",
        condition="Blood glucose checked",
        guidance="Blood glucose is part of the initial stroke workup. See Section 5.3 for glucose management.",
        variables=[],  # glucose not yet in ParsedVariables — flagged as always unassessed
        recIds=["rec-5.3-001", "rec-5.3-002"],
        sourceTable="Section 5.3",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# GENERAL SUPPORTIVE CARE CHECKLIST
# ─────────────────────────────────────────────────────────────────────

SUPPORTIVE_RULES: List[ClinicalChecklistRule] = [
    ClinicalChecklistRule(
        id="supp-chk-001",
        domain="supportive_care",
        category="airway",
        condition="Airway and breathing assessed",
        guidance="See Section 5.1 for airway and oxygenation recommendations.",
        variables=[],  # clinical assessment, not a parsed variable
        recIds=["rec-5.1-001"],
        sourceTable="Section 5.1",
    ),
    ClinicalChecklistRule(
        id="supp-chk-002",
        domain="supportive_care",
        category="functional_status",
        condition="Pre-stroke functional status (mRS) documented",
        guidance="Pre-stroke mRS informs treatment decisions. See Section 3.1.",
        variables=["prestrokeMRS"],
        recIds=["rec-3.1-001"],
        sourceTable="Section 3.1",
    ),
    ClinicalChecklistRule(
        id="supp-chk-003",
        domain="supportive_care",
        category="stroke_severity",
        condition="Stroke severity (NIHSS) documented",
        guidance="NIHSS score guides treatment pathway. See Section 3.1.",
        variables=["nihss"],
        recIds=["rec-3.1-001"],
        sourceTable="Section 3.1",
    ),
    ClinicalChecklistRule(
        id="supp-chk-004",
        domain="supportive_care",
        category="sickle_cell",
        condition="Sickle cell disease screened (if applicable)",
        guidance="See Section 4.6.5 for sickle cell disease considerations with IVT.",
        variables=["sickleCell"],
        recIds=["rec-4.6.5-001", "rec-4.6.5-002"],
        sourceTable="Section 4.6.5",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# Combine all domain rules
# ─────────────────────────────────────────────────────────────────────

ALL_CHECKLIST_RULES: List[ClinicalChecklistRule] = (
    EVT_RULES + IMAGING_RULES + BP_RULES + MEDICATION_RULES + SUPPORTIVE_RULES
)

# Domain labels for UI rendering
DOMAIN_LABELS = {
    "evt_eligibility": "EVT Eligibility Criteria",
    "imaging": "Imaging Assessment",
    "bp_management": "Blood Pressure Management",
    "medications": "Medications & Coagulation",
    "supportive_care": "General Supportive Care",
}


class ClinicalChecklistAgent:
    """
    Evaluates all clinical domains against parsed variables.

    Produces a list of ChecklistSummary objects, one per domain,
    each containing items with assessed/unassessed status.
    """

    def __init__(self):
        self.rules = ALL_CHECKLIST_RULES

    def evaluate(self, parsed: ParsedVariables) -> List[ChecklistSummary]:
        """
        Evaluate all checklist domains and return summaries.
        """
        # Group rules by domain
        domain_rules: Dict[str, List[ClinicalChecklistRule]] = {}
        for rule in self.rules:
            domain_rules.setdefault(rule.domain, []).append(rule)

        summaries = []
        for domain, rules in domain_rules.items():
            items = []
            for rule in rules:
                status = self._assess_item(rule, parsed)
                items.append(ChecklistItem(
                    ruleId=rule.id,
                    domain=rule.domain,
                    category=rule.category,
                    condition=rule.condition,
                    guidance=rule.guidance,
                    status=status,
                    assessedVariables=rule.variables,
                    sourceTable=rule.sourceTable,
                    sourcePage=rule.sourcePage
                ))

            total = len(items)
            unassessed = sum(1 for i in items if i.status == "unassessed")
            present = sum(1 for i in items if i.status == "confirmed_present")
            absent = sum(1 for i in items if i.status == "confirmed_absent")

            reminder = None
            if unassessed > 0:
                reminder = (
                    f"{unassessed} of {total} {DOMAIN_LABELS.get(domain, domain)} "
                    f"item(s) have not yet been assessed. "
                    f"Consider reviewing when clinically appropriate."
                )

            summaries.append(ChecklistSummary(
                domain=domain,
                domainLabel=DOMAIN_LABELS.get(domain, domain),
                totalItems=total,
                assessedItems=present + absent,
                unassessedItems=unassessed,
                confirmedPresent=present,
                confirmedAbsent=absent,
                items=items,
                reminderText=reminder
            ))

        return summaries

    def _assess_item(
        self,
        rule: ClinicalChecklistRule,
        parsed: ParsedVariables
    ) -> str:
        """
        Determine assessment status for a single checklist item.

        - If rule has no variables (clinical assessment items), always "unassessed"
        - If any required variable is None, "unassessed"
        - If all variables present and trigger exists, evaluate trigger
        - If all variables present and no trigger, "confirmed_absent"
          (variable was provided but no specific trigger to match)
        """
        # Items with no variables are clinical assessments — always need manual check
        if not rule.variables:
            return "unassessed"

        # Check if all required variables are present
        all_present = all(
            getattr(parsed, v, None) is not None
            for v in rule.variables
        )

        if not all_present:
            return "unassessed"

        # All variables present
        if rule.trigger:
            # Has a trigger — evaluate it
            triggered = self._evaluate_trigger(rule.trigger, parsed)
            return "confirmed_present" if triggered else "confirmed_absent"

        # No trigger — presence of variables means it's been assessed
        return "confirmed_absent"

    def _evaluate_trigger(self, trigger: dict, parsed: ParsedVariables) -> bool:
        """Evaluate a trigger dict (reuses Table 8 trigger format)."""
        if "logic" in trigger:
            logic = trigger["logic"]
            clauses = trigger.get("clauses", [])
            results = [self._evaluate_trigger(c, parsed) for c in clauses]
            if logic == "AND":
                return all(results)
            elif logic == "OR":
                return any(results)
            return False

        var = trigger.get("var")
        op = trigger.get("op")
        val = trigger.get("val")
        actual = getattr(parsed, var, None)

        if op == "==":
            return actual == val
        elif op == "!=":
            return actual is not None and actual != val
        elif op == "<":
            return actual is not None and actual < val
        elif op == "<=":
            return actual is not None and actual <= val
        elif op == ">":
            return actual is not None and actual > val
        elif op == ">=":
            return actual is not None and actual >= val
        elif op == "in":
            return actual is not None and actual in val
        elif op == "is_null":
            return actual is None
        elif op == "is_not_null":
            return actual is not None

        return False
