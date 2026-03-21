from __future__ import annotations

from typing import Any, Dict, List
from ..models.clinical import FiredRecommendation, ParsedVariables, Recommendation, Note
from ..models.rules import Rule, RuleClause, RuleCondition


class RuleEngine:
    """Rule engine for deterministic EVT decision support."""

    def __init__(self):
        """Initialize rule engine."""
        self.recommendations: Dict[str, Recommendation] = {}
        self.rules: List[Rule] = []

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
            condition_dict = rule_dict.get("condition", {})
            condition = self._dict_to_condition(condition_dict)
            rule_dict["condition"] = condition
            rule = Rule(**rule_dict)
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

        # Optional clauses pass when the variable is unknown
        if getattr(clause, "optional", False) and actual is None:
            return True

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

    # ── EVT Eligibility Evaluation ─────────────────────────────────

    # Computed boolean properties that depend on vessel
    VESSEL_DERIVED_VARS = {"isAnteriorLVO", "isM2", "isBasilar", "isLVO", "isEVTIneligibleVessel", "isAnterior"}

    # Negative recommendation rules — these explicitly say "EVT NOT recommended"
    # (COR 3: No Benefit). All other rules are positive eligibility criteria.
    NEGATIVE_REC_RULES = {"evt-rule-008"}

    # Human-readable labels for variables
    VAR_LABELS = {
        "timeHours": "Time from onset",
        "nihss": "NIHSS",
        "aspects": "ASPECTS",
        "prestrokeMRS": "Pre-stroke mRS",
        "age": "Age",
        "isAnteriorLVO": "Anterior LVO (ICA/M1)",
        "isM2": "M2 occlusion",
        "isBasilar": "Basilar occlusion",
        "wakeUp": "Wake-up stroke",
    }

    def evaluate_evt_eligibility(self, parsed: ParsedVariables) -> Dict:
        """
        Evaluate EVT eligibility using three-valued logic on each rule clause.

        For each EVT rule, each clause is evaluated as:
        - "met": variable provided and satisfies the clause
        - "failed": variable provided and violates the clause
        - "unknown": variable not yet provided

        Rules are classified as:
        - "satisfied": all clauses met (rule would fire)
        - "possible": no failures, but some unknowns (could still qualify)
        - "excluded": at least one clause failed (cannot qualify)

        Aggregate:
        - ANY satisfied → eligible
        - ANY possible → pending (collect missing vars)
        - ALL excluded → excluded (collect reasons)
        """
        rule_results = []

        for rule in self.rules:
            if not rule.enabled:
                continue
            # Only evaluate EVT treatment eligibility rules:
            #   001-008: Anterior LVO (ICA/M1) by time window
            #   011-012: Basilar occlusion
            # Skip technique rules (009-010, 013-019), imaging/workup (020+)
            if not rule.id.startswith("evt-rule-"):
                continue
            rule_num = rule.id.split("-")[-1]
            if not rule_num.isdigit():
                continue
            n = int(rule_num)
            if not (n <= 8 or n in (11, 12)):
                continue

            # For OR conditions, evaluate each branch separately:
            # rule is satisfied if ANY branch is fully met
            if rule.condition.logic == "OR":
                branch_states = []
                all_clause_results = []
                for branch in rule.condition.clauses:
                    if isinstance(branch, RuleCondition) or (isinstance(branch, dict) and "logic" in branch):
                        sub = branch if isinstance(branch, RuleCondition) else self._dict_to_condition(branch)
                        branch_results = self._evaluate_clauses_3val(sub, parsed)
                    elif isinstance(branch, RuleClause):
                        branch_results = [self._evaluate_clause_3val(branch, parsed)]
                    else:
                        sub_clause = RuleClause(**branch)
                        branch_results = [self._evaluate_clause_3val(sub_clause, parsed)]
                    all_clause_results.extend(branch_results)
                    b_failed = [c for c in branch_results if c["state"] == "failed"]
                    b_unknown = [c for c in branch_results if c["state"] == "unknown"]
                    if not b_failed and not b_unknown:
                        branch_states.append("satisfied")
                    elif not b_failed:
                        branch_states.append("possible")
                    else:
                        branch_states.append("excluded")
                # OR: best branch wins
                if "satisfied" in branch_states:
                    state = "satisfied"
                elif "possible" in branch_states:
                    state = "possible"
                else:
                    state = "excluded"
                failed = [c for c in all_clause_results if c["state"] == "failed"]
                unknown = [c for c in all_clause_results if c["state"] == "unknown"]
            else:
                clause_results = self._evaluate_clauses_3val(rule.condition, parsed)
                failed = [c for c in clause_results if c["state"] == "failed"]
                unknown = [c for c in clause_results if c["state"] == "unknown"]

                if failed:
                    state = "excluded"
                elif unknown:
                    state = "possible"
                else:
                    state = "satisfied"

            rule_results.append({
                "ruleId": rule.id,
                "ruleName": rule.name,
                "state": state,
                "failedClauses": failed,
                "unknownVars": [c["var"] for c in unknown],
            })

        # Aggregate
        satisfied = [r for r in rule_results if r["state"] == "satisfied"]
        possible = [r for r in rule_results if r["state"] == "possible"]
        excluded = [r for r in rule_results if r["state"] == "excluded"]

        # Check if any negative recommendation rule (e.g. rule 008 — EVT-ineligible
        # vessel) was satisfied. This is a true "NOT RECOMMENDED" from the guideline.
        negative_fired = any(
            r["ruleId"] in self.NEGATIVE_REC_RULES and r["state"] == "satisfied"
            for r in rule_results
        )

        if satisfied:
            # If a negative rec fired alongside positive recs, the negative
            # rec takes precedence (shouldn't happen in practice).
            if negative_fired and not any(
                r["state"] == "satisfied" and r["ruleId"] not in self.NEGATIVE_REC_RULES
                for r in rule_results
            ):
                status = "excluded"
            else:
                status = "eligible"
        elif possible:
            # Check for universal variable-level exclusions: if a provided
            # variable fails its clause in EVERY rule (both excluded and
            # possible), no amount of missing data can save the patient.
            # Promote to "excluded" in that case.
            # Only count positive eligibility rules (skip negative rec rules).
            positive_rules = [r for r in (excluded + possible)
                              if r["ruleId"] not in self.NEGATIVE_REC_RULES]
            total_rules = len(positive_rules)
            if total_rules > 0:
                # Count how many rules each non-vessel variable fails in
                var_fail_count: Dict[str, int] = {}
                for r in positive_rules:
                    failed_vars_in_rule = set()
                    for c in r["failedClauses"]:
                        v = c["var"]
                        if v not in self.VESSEL_DERIVED_VARS:
                            failed_vars_in_rule.add(v)
                    for v in failed_vars_in_rule:
                        var_fail_count[v] = var_fail_count.get(v, 0) + 1

                universal_blockers = [
                    v for v, count in var_fail_count.items()
                    if count >= total_rules
                ]
                if universal_blockers:
                    # This variable fails every positive rule — no path to eligibility
                    status = "excluded"
                else:
                    status = "pending"
            else:
                status = "pending"
        else:
            # All rules excluded — no guideline recommendation supports EVT
            status = "excluded"

        # Collect missing variables from possible rules only (deduplicated)
        missing_vars = []
        if status == "pending":
            seen = set()
            for r in possible:
                for v in r["unknownVars"]:
                    # Map vessel-derived booleans back to "vessel"
                    display_var = "vessel" if v in self.VESSEL_DERIVED_VARS else v
                    if display_var not in seen:
                        seen.add(display_var)
                        missing_vars.append(display_var)

        # Collect exclusion reasons
        exclusion_reasons = []
        if status == "excluded":
            exclusion_reasons = self._generate_exclusion_reasons(
                excluded + possible if possible else excluded, parsed
            )

        # Build narrowing summary: which recs are satisfied/possible/excluded
        total_rules = len(rule_results)
        satisfied_names = [r["ruleName"] for r in rule_results if r["state"] == "satisfied"]
        possible_names = [r["ruleName"] for r in rule_results if r["state"] == "possible"]
        excluded_names = [r["ruleName"] for r in rule_results if r["state"] == "excluded"]

        # Map rule IDs to recommendation IDs and collect notes for viable rules
        satisfied_rec_ids = []
        possible_rec_ids = []
        evt_notes: List[Dict] = []
        seen_note_texts: set = set()
        for r in rule_results:
            rule_obj = next((rl for rl in self.rules if rl.id == r["ruleId"]), None)
            if rule_obj:
                rec_ids = []
                for action in rule_obj.actions:
                    if isinstance(action, dict) and action.get("type") == "fire":
                        rec_ids.extend(action.get("recIds", []))
                    # Collect warning/info notes from satisfied or possible rules
                    elif isinstance(action, dict) and action.get("type") == "note" and r["state"] in ("satisfied", "possible"):
                        note_text = action.get("text", "")
                        if note_text and note_text not in seen_note_texts:
                            seen_note_texts.add(note_text)
                            evt_notes.append({
                                "severity": action.get("severity", "info"),
                                "text": note_text,
                                "source": r["ruleId"],
                            })
                if r["state"] == "satisfied":
                    satisfied_rec_ids.extend(rec_ids)
                elif r["state"] == "possible":
                    possible_rec_ids.extend(rec_ids)

        return {
            "status": status,
            "missingVariables": missing_vars,
            "exclusionReasons": exclusion_reasons,
            "ruleDetails": rule_results,
            "notes": evt_notes,
            "narrowingSummary": {
                "totalRules": total_rules,
                "satisfiedCount": len(satisfied),
                "possibleCount": len(possible),
                "excludedCount": len(excluded),
                "satisfiedRules": satisfied_names,
                "possibleRules": possible_names,
                "excludedRules": excluded_names,
                "satisfiedRecIds": satisfied_rec_ids,
                "possibleRecIds": possible_rec_ids,
            },
        }

    def _evaluate_clauses_3val(
        self, condition: RuleCondition, parsed: ParsedVariables
    ) -> List[Dict]:
        """
        Evaluate all clauses in a condition with three-valued logic.
        Returns list of {var, op, val, actual, state} for each leaf clause.
        """
        results = []
        for clause in condition.clauses:
            if isinstance(clause, RuleCondition):
                results.extend(self._evaluate_clauses_3val(clause, parsed))
            elif isinstance(clause, RuleClause):
                results.append(self._evaluate_clause_3val(clause, parsed))
            else:
                if "logic" in clause:
                    sub_condition = self._dict_to_condition(clause)
                    results.extend(self._evaluate_clauses_3val(sub_condition, parsed))
                else:
                    sub_clause = RuleClause(**clause)
                    results.append(self._evaluate_clause_3val(sub_clause, parsed))
        return results

    def _evaluate_clause_3val(
        self, clause: RuleClause, parsed: ParsedVariables
    ) -> Dict:
        """
        Evaluate single clause with three outcomes: met, failed, unknown.

        Special handling for vessel-derived booleans (isAnteriorLVO, isM2, isBasilar):
        these return False when vessel is None, but that's "unknown" not "failed".
        """
        var = clause.var
        op = clause.op
        val = clause.val
        actual = getattr(parsed, var, None)

        # Special: vessel-derived computed booleans
        if var in self.VESSEL_DERIVED_VARS and op == "==" and val is True:
            if parsed.vessel is None:
                return {"var": var, "op": op, "val": val, "actual": None, "state": "unknown"}
            # "LVO" (unspecified) = confirmed LVO but specific vessel unknown.
            # isLVO is True, but isAnteriorLVO/isM2/isBasilar are unknown.
            if ParsedVariables._strip_side(parsed.vessel).upper() == "LVO" and var != "isLVO":
                return {"var": var, "op": op, "val": val, "actual": None, "state": "unknown"}
            # vessel is set — use the computed value
            return {"var": var, "op": op, "val": val, "actual": actual,
                    "state": "met" if actual else "failed"}

        # Null check operators
        if op == "is_null":
            return {"var": var, "op": op, "val": val, "actual": actual,
                    "state": "met" if actual is None else "failed"}
        if op == "is_not_null":
            return {"var": var, "op": op, "val": val, "actual": actual,
                    "state": "met" if actual is not None else "failed"}

        # If actual is None, the variable is not yet provided
        if actual is None:
            # Optional clauses: missing value doesn't block eligibility
            # (e.g., pc-ASPECTS for basilar — not always available)
            if getattr(clause, "optional", False):
                return {"var": var, "op": op, "val": val, "actual": None, "state": "met"}
            return {"var": var, "op": op, "val": val, "actual": None, "state": "unknown"}

        # Variable is provided — evaluate normally
        result = self._evaluate_clause(clause, parsed)
        return {"var": var, "op": op, "val": val, "actual": actual,
                "state": "met" if result else "failed"}

    def _generate_exclusion_reasons(
        self, excluded_rules: List[Dict], parsed: ParsedVariables
    ) -> List[str]:
        """
        Generate human-readable exclusion reasons from failed clauses.

        Strategy: Find rules that match the patient's vessel type (if known)
        and report why those specific rules failed. If no rules match the vessel,
        report that the vessel type is not eligible.
        """
        vessel = parsed.vessel
        vessel_type = None
        if vessel:
            stripped = ParsedVariables._strip_side(vessel)
            if stripped.upper() == "LVO":
                # Unspecified LVO: patient has confirmed LVO but specific vessel unknown.
                # Treat as potential anterior LVO for rule matching; will note vessel needed.
                vessel_type = "anteriorLVO"
            elif stripped in ("M1", "ICA", "T-ICA"):
                vessel_type = "anteriorLVO"
            elif stripped == "M2":
                vessel_type = "m2"
            elif stripped == "basilar":
                vessel_type = "basilar"

        # Separate rules into vessel-matching vs vessel-mismatching
        vessel_matching_rules = []
        for rule in excluded_rules:
            failed_vars = {c["var"] for c in rule["failedClauses"]}
            # A rule matches this vessel if it didn't fail on the vessel-type clause
            vessel_clause_failed = failed_vars & self.VESSEL_DERIVED_VARS
            if not vessel_clause_failed:
                vessel_matching_rules.append(rule)

        # If no rules match the vessel type, the vessel itself is the exclusion
        if vessel_type is None and vessel:
            return [f"Vessel {vessel} — EVT not recommended per guidelines. "
                    f"EVT requires anterior LVO (ICA/M1), proximal M2, or basilar occlusion."]

        if not vessel_matching_rules:
            if vessel:
                return [f"Vessel {vessel} — EVT not recommended per guidelines. "
                        f"EVT requires anterior LVO (ICA/M1), proximal M2, or basilar occlusion."]
            return ["No vessel occlusion identified for EVT evaluation."]

        # Report failures from vessel-matching rules only.
        # A variable is a true exclusion reason only if it failed in EVERY
        # vessel-matching rule. If ASPECTS=8 passes in some rules but fails
        # in others (e.g., Rec 3 needs ASPECTS ≤5), the real blocker is
        # a different variable like NIHSS.
        reasons = []
        num_vessel_matching = len(vessel_matching_rules)
        failure_vars: Dict[str, List[Dict]] = {}
        failure_var_rule_count: Dict[str, int] = {}  # how many rules this var failed in
        for rule in vessel_matching_rules:
            failed_vars_in_rule = set()
            for clause in rule["failedClauses"]:
                var = clause["var"]
                if var in self.VESSEL_DERIVED_VARS:
                    continue  # Skip vessel-type mismatches (already filtered)
                if var not in failure_vars:
                    failure_vars[var] = []
                failure_vars[var].append({
                    "rule": rule["ruleName"],
                    "op": clause["op"],
                    "val": clause["val"],
                    "actual": clause["actual"],
                })
                failed_vars_in_rule.add(var)
            for var in failed_vars_in_rule:
                failure_var_rule_count[var] = failure_var_rule_count.get(var, 0) + 1

        # Only include variables that failed in ALL vessel-matching rules
        # (these are the true universal blockers)
        universal_failures = {
            var for var, count in failure_var_rule_count.items()
            if count >= num_vessel_matching
        }

        for var, failures in failure_vars.items():
            if var not in universal_failures:
                continue  # Skip variables that only fail in some rules
            label = self.VAR_LABELS.get(var, var)
            actual = failures[0]["actual"]

            if var == "timeHours":
                time_vals = [f["val"] for f in failures if f["op"] in ("<=", "<")]
                if time_vals:
                    max_window = max(time_vals)
                    reasons.append(
                        f"{label} {actual}h exceeds the {max_window}h EVT window "
                        f"for {vessel or 'this vessel type'}."
                    )
            elif var == "nihss":
                min_vals = [f["val"] for f in failures if f["op"] in (">=", ">")]
                if min_vals:
                    min_required = min(min_vals)
                    reasons.append(
                        f"{label} {actual} is below the minimum of {min_required} "
                        f"required for EVT."
                    )
            elif var == "aspects":
                reasons.append(f"{label} {actual} does not meet EVT ASPECTS criteria.")
            elif var == "prestrokeMRS":
                max_vals = [f["val"] for f in failures if f["op"] in ("<=", "<", "==")]
                if max_vals:
                    max_allowed = max(max_vals)
                    reasons.append(
                        f"{label} {actual} exceeds maximum of {max_allowed} for EVT."
                    )
            elif var == "age":
                reasons.append(f"{label} {actual} does not meet EVT age criteria.")
            else:
                reasons.append(f"{label}: {actual} does not meet EVT criteria.")

        if not reasons:
            reasons.append("No guideline recommendation supports EVT for this clinical scenario.")

        return reasons

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
