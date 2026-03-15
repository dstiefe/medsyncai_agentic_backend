from typing import List, Set
from ..models.clinical import ParsedVariables
from ..models.table8 import Table8Item, Table8Result, Table8Rule, Note
from ..data.loader import load_table8_rules


class Table8Agent:
    """Agent for evaluating Table 8 contraindications."""

    def __init__(self):
        """Initialize Table 8 agent with rules from JSON data."""
        self.rules: List[Table8Rule] = [
            Table8Rule(**r) for r in load_table8_rules()
        ]

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
