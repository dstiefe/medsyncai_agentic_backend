from typing import Any, Dict, List
from ..models.clinical import FiredRecommendation, ParsedVariables, Recommendation, Note
from ..models.rules import Rule, RuleClause, RuleCondition
from ..data.loader import load_recommendations, load_evt_rules


class RuleEngine:
    """Rule engine for deterministic EVT decision support."""

    def __init__(self):
        """Initialize rule engine with data from JSON loader."""
        self.recommendations: Dict[str, Recommendation] = {}
        self.rules: List[Rule] = []
        self.load_from_dicts(load_recommendations(), load_evt_rules())

    def load_from_dicts(
        self,
        recs_list: List[Dict],
        rules_list: List[Dict]
    ) -> None:
        """
        Load recommendations and rules from dicts.

        Args:
            recs_list: List of recommendation dicts
            rules_list: List of rule dicts
        """
        # Load recommendations
        for rec_dict in recs_list:
            rec = Recommendation(**rec_dict)
            self.recommendations[rec.id] = rec

        # Load rules - need to reconstruct complex condition objects
        for rule_dict in rules_list:
            # Convert condition dict to RuleCondition
            rule_copy = dict(rule_dict)
            condition_dict = rule_copy.get("condition", {})
            condition = self._dict_to_condition(condition_dict)
            rule_copy["condition"] = condition
            rule = Rule(**rule_copy)
            self.rules.append(rule)

    def evaluate(self, parsed: ParsedVariables) -> Dict:
        """
        Evaluate all enabled rules against parsed variables.

        Returns dict with:
        - recommendations: dict (category -> list of FiredRecommendation)
        - notes: list[Note]
        - trace: dict with evaluation details
        """
        fired_recs: List[FiredRecommendation] = []
        notes: List[Note] = []
        trace = {"rules_evaluated": 0, "rules_fired": 0}

        for rule in self.rules:
            if not rule.enabled:
                continue

            trace["rules_evaluated"] += 1

            # Evaluate rule condition
            if self._evaluate_condition(rule.condition, parsed):
                trace["rules_fired"] += 1

                # Process actions
                for action in rule.actions:
                    if action.type == "fire" and action.recIds:
                        for rec_id in action.recIds:
                            fired_recs.extend(
                                self._fire_recommendation(rec_id, rule.id)
                            )
                    elif action.type == "note" and action.text:
                        notes.append(
                            Note(
                                severity=action.severity or "info",
                                text=action.text,
                                source=f"Rule: {rule.name}"
                            )
                        )

        # Group recommendations by category
        recs_by_category: Dict[str, List[FiredRecommendation]] = {}
        for rec in fired_recs:
            if rec.category not in recs_by_category:
                recs_by_category[rec.category] = []
            recs_by_category[rec.category].append(rec)

        return {
            "recommendations": recs_by_category,
            "notes": notes,
            "trace": trace
        }

    def _evaluate_condition(
        self,
        condition: RuleCondition,
        parsed: ParsedVariables
    ) -> bool:
        """
        Recursively evaluate condition with AND/OR logic.

        Args:
            condition: RuleCondition with logic and clauses
            parsed: ParsedVariables to evaluate against

        Returns:
            bool: Whether condition is satisfied
        """
        results = []
        for clause in condition.clauses:
            if isinstance(clause, RuleCondition):
                # Recursive condition
                results.append(self._evaluate_condition(clause, parsed))
            elif isinstance(clause, RuleClause):
                # Single clause
                results.append(self._evaluate_clause(clause, parsed))
            else:
                # Dict form (from loaded rules)
                if "logic" in clause:
                    sub_condition = self._dict_to_condition(clause)
                    results.append(self._evaluate_condition(sub_condition, parsed))
                else:
                    sub_clause = RuleClause(**clause)
                    results.append(self._evaluate_clause(sub_clause, parsed))

        if condition.logic == "AND":
            return all(results) if results else False
        elif condition.logic == "OR":
            return any(results) if results else False
        return False

    def _evaluate_clause(self, clause: RuleClause, parsed: ParsedVariables) -> bool:
        """
        Evaluate single clause.

        Operators:
        - ==, !=, >=, <=, >, <
        - in, not_in
        - is_null, is_not_null

        Special: != returns True if actual is None
        """
        var = clause.var
        op = clause.op
        val = clause.val

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

    def _fire_recommendation(
        self,
        rec_id: str,
        rule_id: str
    ) -> List[FiredRecommendation]:
        """Create FiredRecommendation from stored recommendation."""
        if rec_id not in self.recommendations:
            return []

        base_rec = self.recommendations[rec_id]
        fired_rec = FiredRecommendation(
            id=base_rec.id,
            guidelineId=base_rec.guidelineId,
            section=base_rec.section,
            recNumber=base_rec.recNumber,
            cor=base_rec.cor,
            loe=base_rec.loe,
            category=base_rec.category,
            text=base_rec.text,
            sourcePages=base_rec.sourcePages,
            evidenceKey=base_rec.evidenceKey,
            prerequisites=base_rec.prerequisites,
            matchedRule="evt_rule",
            ruleId=rule_id
        )
        return [fired_rec]

    def _dict_to_condition(self, condition_dict: Dict) -> RuleCondition:
        """Convert dict to RuleCondition object."""
        if not condition_dict:
            return RuleCondition(logic="AND", clauses=[])

        logic = condition_dict.get("logic", "AND")
        clauses = condition_dict.get("clauses", [])

        processed_clauses = []
        for clause in clauses:
            if isinstance(clause, dict):
                if "logic" in clause:
                    processed_clauses.append(self._dict_to_condition(clause))
                else:
                    processed_clauses.append(RuleClause(**clause))
            else:
                processed_clauses.append(clause)

        return RuleCondition(logic=logic, clauses=processed_clauses)
