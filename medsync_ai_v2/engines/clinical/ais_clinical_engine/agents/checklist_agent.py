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

from typing import Dict, List
from ..models.clinical import ParsedVariables
from ..models.checklist import (
    ChecklistItem, ChecklistSummary, ClinicalChecklistRule
)
from ..data.loader import load_all_checklist_rules, load_domain_labels


class ClinicalChecklistAgent:
    """
    Evaluates all clinical domains against parsed variables.

    Produces a list of ChecklistSummary objects, one per domain,
    each containing items with assessed/unassessed status.
    """

    def __init__(self):
        self.rules: List[ClinicalChecklistRule] = [
            ClinicalChecklistRule(**r) for r in load_all_checklist_rules()
        ]
        self.domain_labels: Dict[str, str] = load_domain_labels()

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
                    f"{unassessed} of {total} {self.domain_labels.get(domain, domain)} "
                    f"item(s) have not yet been assessed. "
                    f"Consider reviewing when clinically appropriate."
                )

            summaries.append(ChecklistSummary(
                domain=domain,
                domainLabel=self.domain_labels.get(domain, domain),
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
