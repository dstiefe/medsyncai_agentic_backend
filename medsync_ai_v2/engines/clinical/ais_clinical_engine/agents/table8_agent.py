from typing import List, Set, Tuple
from ..models.clinical import ParsedVariables
from ..models.table8 import Table8Item, Table8Result, Table8Rule, Note


class Table8Agent:
    """Agent for evaluating Table 8 contraindications."""

    TABLE_8_RULES: List[Table8Rule] = [
        # ═══════════════════════════════════════════════════════════════
        # ABSOLUTE CONTRAINDICATIONS (10)
        # ═══════════════════════════════════════════════════════════════
        Table8Rule(
            id="t8-001",
            tier="absolute",
            condition="CT with extensive hypodensity",
            trigger={"var": "extensiveHypodensity", "op": "==", "val": True},
            guidance="IV thrombolysis should not be administered to patients whose brain imaging exhibits regions of clear hypodensity that appear to be responsible for the clinical symptoms of stroke. Clear hypodensity is when the degree of hypodensity is greater than the density of contralateral unaffected white matter.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-002",
            tier="absolute",
            condition="CT with hemorrhage",
            trigger={"var": "hemorrhage", "op": "==", "val": True},
            guidance="IV thrombolysis should not be administered to patients whose CT brain imaging reveals an acute intracranial hemorrhage.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-003",
            tier="absolute",
            condition="Moderate to severe traumatic brain injury <14 days",
            trigger={"logic": "AND", "clauses": [
                {"var": "recentTBI", "op": "==", "val": True},
                {"var": "tbiDays", "op": "<", "val": 14}
            ]},
            guidance="IV thrombolysis is likely contraindicated in AIS patients with recent moderate to severe traumatic brain injury (within 14 days) that incurred >30 minutes of unconsciousness and Glasgow Coma Scale of <13 OR evidence of hemorrhage, contusion, or skull fracture on neuroimaging.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-004",
            tier="absolute",
            condition="Neurosurgery <14 days",
            trigger={"logic": "AND", "clauses": [
                {"var": "recentNeurosurgery", "op": "==", "val": True},
                {"var": "neurosurgeryDays", "op": "<", "val": 14}
            ]},
            guidance="For patients with AIS and a history of intracranial/spinal surgery within 14 days, IV thrombolysis is potentially harmful and should not be administered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-005",
            tier="absolute",
            condition="Acute spinal cord injury within 3 months",
            trigger={"var": "acuteSpinalCordInjury", "op": "==", "val": True},
            guidance="IV thrombolysis is likely contraindicated in AIS patients with spinal cord injury within 3 months.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-006",
            tier="absolute",
            condition="Intra-axial neoplasm",
            trigger={"var": "intraAxialNeoplasm", "op": "==", "val": True},
            guidance="For patients with AIS who harbor an intra-axial intracranial neoplasm, treatment with IV thrombolysis is potentially harmful and should not be administered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-007",
            tier="absolute",
            condition="Infective endocarditis",
            trigger={"var": "infectiveEndocarditis", "op": "==", "val": True},
            guidance="For patients with AIS and symptoms consistent with infective endocarditis, treatment with IV thrombolysis should not be administered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-008",
            tier="absolute",
            condition="Severe coagulopathy or thrombocytopenia",
            trigger={"logic": "OR", "clauses": [
                {"var": "platelets", "op": "<", "val": 100000},
                {"var": "inr", "op": ">", "val": 1.7},
                {"var": "aptt", "op": ">", "val": 40},
                {"var": "pt", "op": ">", "val": 15}
            ]},
            guidance="The safety and efficacy of IV thrombolysis for AIS in patients with platelets <100,000/mm\u00b3, INR >1.7, aPTT >40s, or PT >15s is unknown though may substantially increase risk of harm and should not be administered. In patients without recent use of warfarin or heparin, treatment with IV thrombolysis can be initiated before availability of coagulation test results but should be discontinued if INR >1.7, PT, or PTT is abnormal by local laboratory standards.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-009",
            tier="absolute",
            condition="Aortic arch dissection",
            trigger={"var": "aorticArchDissection", "op": "==", "val": True},
            guidance="For patients with AIS and known or suspected aortic arch dissection, treatment with IV thrombolysis is potentially harmful and should not be administered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-010",
            tier="absolute",
            condition="Amyloid-related imaging abnormalities (ARIA)",
            trigger={"logic": "OR", "clauses": [
                {"var": "aria", "op": "==", "val": True},
                {"var": "amyloidImmunotherapy", "op": "==", "val": True}
            ]},
            guidance="The risk of thrombolysis related ICH in patients on amyloid immunotherapy or with ARIA is unknown and IV thrombolysis should be avoided in such patients.",
            sourcePage=0
        ),
        # ═══════════════════════════════════════════════════════════════
        # RELATIVE CONTRAINDICATIONS (18)
        # ═══════════════════════════════════════════════════════════════
        Table8Rule(
            id="t8-011",
            tier="relative",
            condition="DOAC exposure (<48 hours)",
            trigger={"var": "recentDOAC", "op": "==", "val": True},
            guidance="In patients with disabling symptoms and recent DOAC exposure (<48 hours) who are within the window for alteplase/tenecteplase, the safety of IV thrombolysis is unknown. Emerging but limited observational data suggest IV thrombolysis may be considered after a thorough benefit vs risk analysis on an individual basis. Benefit vs risk assessments should include considering the timing of the last DOAC administration, renal function, stroke severity, and availability of endovascular thrombectomy as well as availability of DOAC reversal agents and DOAC-specific anti-factor Xa/thrombin time assays acknowledging the potential for delay in thrombolysis and potential increased thrombotic risk. All aspects of DOAC management (timing, reversal agent use, assay results), should be recorded carefully to facilitate ongoing safety analyses. Definitive clinical trials are needed to establish the safety of IV thrombolysis in DOAC patients.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-012",
            tier="relative",
            condition="Ischemic stroke within 3 months",
            trigger={"var": "recentStroke3mo", "op": "==", "val": True},
            guidance="Use of IV thrombolysis in patients presenting with AIS who have had a prior ischemic stroke within 3 months may be at increased risk of intracranial hemorrhage. Potential increased risk as a result of the timing and size of the stroke should be weighed against the benefits of offering IV thrombolysis in an individualized manner in such patients.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-013",
            tier="relative",
            condition="Prior intracranial hemorrhage",
            trigger={"var": "priorICH", "op": "==", "val": True},
            guidance="IV thrombolysis administration in patients who have a history of ICH may increase the risk of symptomatic hemorrhage. Patients with known amyloid angiopathy may be considered as having higher risk than patients with ICH due to modifiable conditions (e.g. HTN, coagulopathy). IV thrombolysis may have greater treatment benefit than risk in these latter patients. Treatment should be determined on an individual basis.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-014",
            tier="relative",
            condition="Recent major non-CNS trauma (14 days to 3 months)",
            trigger={"var": "recentNonCNSTrauma", "op": "==", "val": True},
            guidance="Patients with recent major trauma between 14 days and 3 months of their AIS may be at increased risk of harm and serious systemic hemorrhage requiring transfusion from IV thrombolysis. Individual consideration of risk vs benefit, involved areas, and consultation with surgical experts are appropriate.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-015",
            tier="relative",
            condition="Recent major non-CNS surgery within 10 days",
            trigger={"var": "recentNonCNSSurgery10d", "op": "==", "val": True},
            guidance="Patients with recent major surgery within 10 days of AIS may be at increased risk of harm from IV thrombolysis. Individual consideration of risk vs benefit, surgical area, and consultation with surgical experts are appropriate.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-016",
            tier="relative",
            condition="Recent GI/GU bleeding within 21 days",
            trigger={"var": "recentGIGUBleeding21d", "op": "==", "val": True},
            guidance="Patients with recent GI or GU bleeding within 21 days of their AIS may be at increased risk of harm from IV thrombolysis. Individual consideration of risk vs benefit and consultation with GI or GU experts to determine if the GI/GU bleeding has been treated and risk modified/reduced is recommended.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-017",
            tier="relative",
            condition="Intracranial arterial dissection",
            trigger={"var": "cervicalDissection", "op": "==", "val": True},
            guidance="The safety of IV thrombolysis in patients with AIS due to intracranial arterial dissection is unknown.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-018",
            tier="relative",
            condition="Pregnancy and post-partum period",
            trigger={"var": "pregnancy", "op": "==", "val": True},
            guidance="IV thrombolysis may be considered in pregnancy and post-partum period when the benefits of treating moderate or severe stroke outweighs the anticipated risk of uterine bleeding. Emergent obstetrical consultation is warranted.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-019",
            tier="relative",
            condition="Systemic active malignancy",
            trigger={"var": "activeMalignancy", "op": "==", "val": True},
            guidance="The safety of IV thrombolysis in patients with systemic active malignancy is unknown. Emergent consultation with oncology to assess risk/benefit is warranted. Consideration of type, stage, and active complications of cancer to determine the risk vs benefit is warranted.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-024",
            tier="relative",
            condition="Pre-existing disability",
            trigger={"var": "preExistingDisability", "op": "==", "val": True},
            guidance="The benefits vs risks of offering IV thrombolysis in patients with pre-existing disability and/or frailty remain uncertain. Treatment should be determined on an individual basis.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-025",
            tier="relative",
            condition="Intracranial vascular malformations",
            trigger={"var": "intracranialVascularMalformation", "op": "==", "val": True},
            guidance="The safety of IV thrombolysis for patients presenting with AIS who are known to harbor an unruptured and untreated intracranial vascular malformation is unknown.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-026",
            tier="relative",
            condition="Recent STEMI within 3 months",
            trigger={"var": "recentSTEMI", "op": "==", "val": True},
            guidance="Patients with recent STEMI may be at risk for increased harm from IVT. For patients with history of STEMI within 3 months, individual consideration of risk and benefit should be determined in conjunction with an emergent cardiology consultation. For patients with very recent STEMI (previous several days), the risk of hemopericardium should be considered relative to potential benefit. For patients presenting with concurrent AIS and acute STEMI, treatment with IV thrombolysis should be at a dose appropriate for cerebral ischemia and in conjunction with emergent cardiology consultation. Consideration of timing, type and severity of STEMI to determine the risk vs benefit is warranted.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-027",
            tier="relative",
            condition="Acute pericarditis",
            trigger={"var": "acutePericarditis", "op": "==", "val": True},
            guidance="IV thrombolysis for patients with major AIS likely to produce severe disability and acute pericarditis, may be reasonable in individual cases. Emergent cardiologic consultation is warranted.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-028",
            tier="relative",
            condition="Left atrial or ventricular thrombus",
            trigger={"var": "cardiacThrombus", "op": "==", "val": True},
            guidance="IV thrombolysis for patients with known left atrial or ventricular thrombus presenting with major AIS likely to produce severe disability may be reasonable in individual cases. Emergent cardiologic consultation is warranted.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-029",
            tier="relative",
            condition="Dural puncture within 7 days",
            trigger={"var": "recentDuralPuncture", "op": "==", "val": True},
            guidance="IV thrombolysis for patients with AIS post-dural puncture may be considered in individual cases, even in instances when they may have undergone a lumbar dural puncture in the preceding 7 days.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-030",
            tier="relative",
            condition="Arterial puncture within 7 days",
            trigger={"var": "recentArterialPuncture", "op": "==", "val": True},
            guidance="The safety of IV thrombolysis in patients with AIS who have had an arterial puncture of a noncompressible blood vessel (e.g., subclavian artery line) in the 7 days preceding the stroke symptoms is unknown.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-031",
            tier="relative",
            condition="Moderate to severe traumatic brain injury \u226514 days to 3 months",
            trigger={"logic": "AND", "clauses": [
                {"var": "recentTBI", "op": "==", "val": True},
                {"var": "tbiDays", "op": ">=", "val": 14},
                {"var": "tbiDays", "op": "<=", "val": 90}
            ]},
            guidance="IV thrombolysis may be considered in AIS patients with recent moderate to severe traumatic brain injury (between 14 days and 3 months). Careful consideration should be made based on the type and severity of traumatic injury and in consultation with neurosurgical and neurocritical care team members.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-032",
            tier="relative",
            condition="Neurosurgery \u226514 days to 3 months",
            trigger={"logic": "AND", "clauses": [
                {"var": "recentNeurosurgery", "op": "==", "val": True},
                {"var": "neurosurgeryDays", "op": ">=", "val": 14},
                {"var": "neurosurgeryDays", "op": "<=", "val": 90}
            ]},
            guidance="For patients with AIS and a history of intracranial/spinal surgery between 14 days and 3 months, IV thrombolysis may be considered on an individual basis. Consultation with neurosurgical team members is recommended.",
            sourcePage=0
        ),
        # ═══════════════════════════════════════════════════════════════
        # BENEFIT EXCEEDS RISK (9)
        # ═══════════════════════════════════════════════════════════════
        Table8Rule(
            id="t8-020",
            tier="benefit_over_risk",
            condition="Extracranial cervical dissections",
            trigger={"var": "cervicalDissection", "op": "==", "val": True},
            guidance="IV thrombolysis in AIS known or suspected to be associated with extracranial cervical arterial dissection is reasonably safe within 4.5 h and probably recommended.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-021",
            tier="benefit_over_risk",
            condition="Extra-axial intracranial neoplasms",
            trigger={"var": "extraAxialNeoplasm", "op": "==", "val": True},
            guidance="The risk of harm of IV thrombolysis in patients with AIS and extra-axial intracranial neoplasm is likely low. Benefit likely outweighs risk in this population and IV thrombolysis should be considered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-022",
            tier="benefit_over_risk",
            condition="Unruptured intracranial aneurysm",
            trigger={"var": "unrupturedAneurysm", "op": "==", "val": True},
            guidance="The risk of harm of IV thrombolysis in patients with AIS and unruptured intracranial aneurysm is likely low. Benefit likely outweighs risk in this population and treatment with IV thrombolysis should be considered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-023",
            tier="benefit_over_risk",
            condition="Moya-Moya disease",
            trigger={"var": "moyaMoya", "op": "==", "val": True},
            guidance="IV thrombolysis in AIS patients with Moya-Moya disease does not appear to have an increased risk of ICH and likely provides benefit that outweighs risk.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-033",
            tier="benefit_over_risk",
            condition="Angiographic procedural stroke",
            trigger={"var": "angiographicProceduralStroke", "op": "==", "val": True},
            guidance="IV thrombolysis in patients with AIS during or immediately post-angiography should be considered as benefit likely outweighs risk in this population.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-034",
            tier="benefit_over_risk",
            condition="History of GI/GU bleeding",
            trigger={"var": "remoteGIGUBleeding", "op": "==", "val": True},
            guidance="IV thrombolysis in AIS patients with previous remote history of GI or GU bleeding that is stable may be candidates for IV thrombolysis. Consideration of benefit and risk on an individual basis in conjunction with GI or GU consultation is appropriate.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-035",
            tier="benefit_over_risk",
            condition="History of MI",
            trigger={"var": "historyMI", "op": "==", "val": True},
            guidance="IV thrombolysis in AIS patients with remote history of MI probably has greater benefit than risk.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-036",
            tier="benefit_over_risk",
            condition="Recreational drug use",
            trigger={"var": "recreationalDrugUse", "op": "==", "val": True},
            guidance="IV thrombolysis in AIS patients with known recreational drug use probably has greater benefit than risk in most patients and should be considered.",
            sourcePage=0
        ),
        Table8Rule(
            id="t8-037",
            tier="benefit_over_risk",
            condition="Uncertainty of stroke diagnosis / stroke mimics",
            trigger={"var": "strokeMimic", "op": "==", "val": True},
            guidance="When uncertain if a patient is presenting with symptoms due to stroke vs a stroke mimic, unless there are absolute contraindications, the risk of harm with IV thrombolysis is low. The benefit of IV thrombolysis likely outweighs risk in these patients.",
            sourcePage=0
        ),
    ]

    def __init__(self):
        """Initialize Table 8 agent."""
        self.rules = self.TABLE_8_RULES

    def evaluate(self, parsed: ParsedVariables) -> Table8Result:
        """
        Evaluate contraindications against Table 8 rules.
        Returns highest severity tier found plus a full checklist
        showing which items are confirmed_present, confirmed_absent,
        or unassessed (clinical variable was None / not provided).
        """
        absolutes = []
        relatives = []
        benefits = []
        notes = []
        checklist: List[Table8Item] = []

        for rule in self.rules:
            # Collect the variable names this rule depends on
            rule_vars = self._collect_trigger_vars(rule.trigger)

            # First, try to evaluate the trigger — if it fires, it's
            # confirmed_present regardless of whether all vars are assessed.
            # This handles OR rules where one present variable is enough.
            triggered = self._evaluate_trigger(rule.trigger, parsed)

            if triggered:
                # Rule fired — at least one trigger path matched
                pass  # fall through to confirmed_present below
            else:
                # Rule didn't fire. But is that because the variables
                # were assessed and negative, or because they were never provided?
                # For the rule to be confirmed_absent, we need ALL variables assessed.
                all_assessed = all(
                    getattr(parsed, v, None) is not None for v in rule_vars
                )
                if not all_assessed:
                    checklist.append(Table8Item(
                        ruleId=rule.id,
                        tier=rule.tier,
                        condition=rule.condition,
                        guidance=rule.guidance,
                        status="unassessed",
                        assessedVariables=list(rule_vars)
                    ))
                    continue

            if triggered:
                checklist.append(Table8Item(
                    ruleId=rule.id,
                    tier=rule.tier,
                    condition=rule.condition,
                    guidance=rule.guidance,
                    status="confirmed_present",
                    assessedVariables=list(rule_vars)
                ))
                note = Note(
                    severity="danger" if rule.tier == "absolute" else (
                        "warning" if rule.tier == "relative" else "info"
                    ),
                    text=rule.guidance,
                    source=f"Table 8 - {rule.condition}"
                )
                notes.append(note)

                if rule.tier == "absolute":
                    absolutes.append(rule.condition)
                elif rule.tier == "relative":
                    relatives.append(rule.condition)
                elif rule.tier == "benefit_over_risk":
                    benefits.append(rule.condition)
            else:
                checklist.append(Table8Item(
                    ruleId=rule.id,
                    tier=rule.tier,
                    condition=rule.condition,
                    guidance=rule.guidance,
                    status="confirmed_absent",
                    assessedVariables=list(rule_vars)
                ))

        # Count unassessed
        unassessed_count = sum(1 for item in checklist if item.status == "unassessed")

        # Add a gentle reminder note when items are unassessed
        if unassessed_count > 0:
            unassessed_absolutes = [
                item.condition for item in checklist
                if item.status == "unassessed" and item.tier == "absolute"
            ]
            unassessed_relatives = [
                item.condition for item in checklist
                if item.status == "unassessed" and item.tier == "relative"
            ]
            if unassessed_absolutes:
                notes.append(Note(
                    severity="warning",
                    text=(
                        f"{len(unassessed_absolutes)} absolute contraindication(s) not yet assessed: "
                        f"{', '.join(unassessed_absolutes)}. "
                        "Please review before proceeding."
                    ),
                    source="Table 8 Checklist"
                ))
            if unassessed_relatives:
                notes.append(Note(
                    severity="info",
                    text=(
                        f"{len(unassessed_relatives)} relative contraindication(s) not yet assessed: "
                        f"{', '.join(unassessed_relatives)}. "
                        "Consider reviewing when clinically appropriate."
                    ),
                    source="Table 8 Checklist"
                ))

        # Determine overall risk tier
        if absolutes:
            risk_tier = "absolute_contraindication"
        elif relatives:
            risk_tier = "relative_contraindication"
        elif benefits:
            risk_tier = "benefit_over_risk"
        else:
            risk_tier = "no_contraindications"

        return Table8Result(
            riskTier=risk_tier,
            absoluteContraindications=absolutes,
            relativeContraindications=relatives,
            benefitOverRisk=benefits,
            notes=notes,
            checklist=checklist,
            unassessedCount=unassessed_count
        )

    def _collect_trigger_vars(self, trigger: dict) -> Set[str]:
        """Recursively collect all variable names referenced by a trigger."""
        variables: Set[str] = set()
        if "logic" in trigger:
            for clause in trigger.get("clauses", []):
                variables.update(self._collect_trigger_vars(clause))
        elif "var" in trigger:
            variables.add(trigger["var"])
        return variables

    def _evaluate_trigger(self, trigger: dict, parsed: ParsedVariables) -> bool:
        """Evaluate a trigger dict recursively."""
        if "logic" in trigger:
            # Complex condition with AND/OR
            logic = trigger["logic"]
            clauses = trigger.get("clauses", [])
            results = [self._evaluate_trigger(clause, parsed) for clause in clauses]
            if logic == "AND":
                return all(results)
            elif logic == "OR":
                return any(results)
            return False
        else:
            # Simple clause: var, op, val
            return self._evaluate_clause(trigger, parsed)

    def _evaluate_clause(self, clause: dict, parsed: ParsedVariables) -> bool:
        """Evaluate a single clause."""
        var = clause.get("var")
        op = clause.get("op")
        val = clause.get("val")

        actual = getattr(parsed, var, None)

        if op == "==":
            return actual == val
        elif op == "!=":
            if actual is None:
                return True  # None is not equal to anything
            return actual != val
        elif op == "<":
            if actual is None:
                return False
            return actual < val
        elif op == "<=":
            if actual is None:
                return False
            return actual <= val
        elif op == ">":
            if actual is None:
                return False
            return actual > val
        elif op == ">=":
            if actual is None:
                return False
            return actual >= val
        elif op == "in":
            if actual is None:
                return False
            return actual in val
        elif op == "not_in":
            if actual is None:
                return True
            return actual not in val
        elif op == "is_null":
            return actual is None
        elif op == "is_not_null":
            return actual is not None

        return False
