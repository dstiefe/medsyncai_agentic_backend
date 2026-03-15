"""
DecisionEngine — single source of truth for all derived clinical decisions.

Replaces the 10 frontend decision points that previously lived in JS/TS:
  1. Contraindication overrides (useInteractiveGates.ts:42-67)
  2. Effective IVT eligibility (useInteractiveGates.ts:118-124)
  3. "None of these" bulk override (useInteractiveGates.ts:197-213)
  4. Table 4 disabling override (Table4DisablingGate.tsx:31-33)
  5. EVT availability (EVTAvailabilityGate.tsx:29-48)
  6. Quick answer verdict (useScenario.ts:63-90)
  7. Dual reperfusion eligibility (ClinicalDecisionSummary.tsx:38-42)
  8. BP not at goal (ClinicalDecisionSummary.tsx:43)
  9. Extended window detection (App.tsx:173-174)
  10. IVT pathway visibility (App.tsx:177-182)

All logic is deterministic — no LLM calls.
"""

from typing import Dict, List, Optional

from ..models.clinical import (
    ClinicalDecisionState,
    ClinicalOverrides,
    ParsedVariables,
)
from ..models.table8 import Table8Item, Table8Result


class DecisionEngine:
    """Computes the effective clinical decision state from raw results + clinician overrides."""

    def compute_effective_state(
        self,
        parsed: ParsedVariables,
        ivt_result: dict,
        evt_result: dict,
        overrides: Optional[ClinicalOverrides] = None,
    ) -> ClinicalDecisionState:
        """
        Deterministically compute the full decision state.

        Args:
            parsed: Parsed clinical variables from patient scenario.
            ivt_result: Raw IVT pipeline result from IVTOrchestrator.evaluate().
            evt_result: Raw EVT rule engine result from RuleEngine.evaluate().
            overrides: Clinician overrides from interactive gates (None = no overrides yet).

        Returns:
            ClinicalDecisionState with all 10 decision points resolved.
        """
        if overrides is None:
            overrides = ClinicalOverrides()

        # --- #9: Extended window detection ---
        is_extended = self._is_extended_window(parsed)

        # --- #1, #2, #3: Effective IVT eligibility from overrides ---
        effective_ivt = self._compute_effective_ivt_eligibility(
            ivt_result, overrides
        )

        # --- #4: Effective disabling assessment ---
        effective_disabling = self._compute_effective_disabling(
            ivt_result, overrides
        )

        # --- #8: BP at goal ---
        bp_at_goal, bp_warning = self._compute_bp_status(parsed)

        # --- #5, #7: Primary therapy + dual reperfusion ---
        has_evt_recs = self._has_evt_recommendations(evt_result)
        primary_therapy = self._compute_primary_therapy(
            parsed, effective_ivt, has_evt_recs, overrides
        )
        is_dual = self._compute_dual_reperfusion(
            parsed, effective_ivt, has_evt_recs, overrides
        )

        # --- #6: Quick answer verdict ---
        verdict = self._compute_verdict(effective_ivt, has_evt_recs, overrides)

        # --- #10: Visible sections ---
        visible = self._compute_visible_sections(
            parsed, effective_ivt, has_evt_recs, is_extended, overrides
        )

        # --- Headline ---
        headline = self._compute_headline(
            effective_ivt, has_evt_recs, is_dual, bp_at_goal, overrides
        )

        return ClinicalDecisionState(
            effective_ivt_eligibility=effective_ivt,
            effective_is_disabling=effective_disabling,
            primary_therapy=primary_therapy,
            verdict=verdict,
            is_dual_reperfusion=is_dual,
            bp_at_goal=bp_at_goal,
            bp_warning=bp_warning,
            is_extended_window=is_extended,
            visible_sections=visible,
            headline=headline,
        )

    # ------------------------------------------------------------------
    # #9: Extended window detection
    # ------------------------------------------------------------------

    def _is_extended_window(self, parsed: ParsedVariables) -> bool:
        """Time >4.5h → extended window."""
        if parsed.timeHours is None:
            return False
        return parsed.timeHours > 4.5

    # ------------------------------------------------------------------
    # #1, #2, #3: Effective IVT eligibility
    # ------------------------------------------------------------------

    def _compute_effective_ivt_eligibility(
        self, ivt_result: dict, overrides: ClinicalOverrides
    ) -> str:
        """
        Compute effective IVT eligibility after applying clinician overrides
        to the Table 8 checklist.

        Returns: "eligible", "contraindicated", "caution", or "pending".
        """
        checklist: List[dict] = ivt_result.get("table8Checklist", [])
        if not checklist:
            # No Table 8 data — use raw eligibility
            return "eligible" if ivt_result.get("eligible", False) else "contraindicated"

        # Apply overrides to a copy of the checklist
        effective_items = self._apply_table8_overrides(checklist, overrides)

        # Determine effective risk tier from overridden checklist
        has_absolute = any(
            item["status"] == "confirmed_present" and item["tier"] == "absolute"
            for item in effective_items
        )
        has_relative = any(
            item["status"] == "confirmed_present" and item["tier"] == "relative"
            for item in effective_items
        )
        has_unassessed_absolute = any(
            item["status"] == "unassessed" and item["tier"] == "absolute"
            for item in effective_items
        )

        if has_absolute:
            return "contraindicated"
        if has_unassessed_absolute:
            return "pending"
        if has_relative:
            return "caution"
        return "eligible"

    def _apply_table8_overrides(
        self, checklist: List[dict], overrides: ClinicalOverrides
    ) -> List[dict]:
        """
        Apply individual and bulk overrides to Table 8 checklist items.

        Decision points #1 (individual overrides) and #3 ("none of these" bulk).
        """
        result = []
        for item in checklist:
            item_copy = dict(item)
            rule_id = item_copy["ruleId"]
            tier = item_copy["tier"]

            # #1: Individual override takes priority
            if rule_id in overrides.table8_overrides:
                item_copy["status"] = overrides.table8_overrides[rule_id]
            # #3: Bulk "none of these" override for entire tier
            elif item_copy["status"] == "unassessed":
                if tier == "absolute" and overrides.none_absolute:
                    item_copy["status"] = "confirmed_absent"
                elif tier == "relative" and overrides.none_relative:
                    item_copy["status"] = "confirmed_absent"
                elif tier == "benefit_over_risk" and overrides.none_benefit_over_risk:
                    item_copy["status"] = "confirmed_absent"

            result.append(item_copy)
        return result

    # ------------------------------------------------------------------
    # #4: Effective disabling assessment
    # ------------------------------------------------------------------

    def _compute_effective_disabling(
        self, ivt_result: dict, overrides: ClinicalOverrides
    ) -> Optional[bool]:
        """
        Apply Table 4 clinician override to disabling assessment.

        If clinician provides table4_override, it takes precedence.
        Otherwise use the backend's Table 4 assessment.
        """
        if overrides.table4_override is not None:
            return overrides.table4_override

        disabling_assessment = ivt_result.get("disablingAssessment", {})
        return disabling_assessment.get("isDisabling")

    # ------------------------------------------------------------------
    # #8: BP at goal
    # ------------------------------------------------------------------

    def _compute_bp_status(
        self, parsed: ParsedVariables
    ) -> tuple[Optional[bool], Optional[str]]:
        """
        Check BP against IVT thresholds (SBP <=185, DBP <=110).

        Returns (bp_at_goal, warning_message).
        """
        if parsed.sbp is None and parsed.dbp is None:
            return None, None

        warnings = []
        at_goal = True

        if parsed.sbp is not None and parsed.sbp > 185:
            at_goal = False
            warnings.append(f"SBP {parsed.sbp} > 185 mmHg")
        if parsed.dbp is not None and parsed.dbp > 110:
            at_goal = False
            warnings.append(f"DBP {parsed.dbp} > 110 mmHg")

        warning_text = "LOWER BP BEFORE IVT: " + ", ".join(warnings) if warnings else None
        return at_goal, warning_text

    # ------------------------------------------------------------------
    # #5: Primary therapy pathway
    # ------------------------------------------------------------------

    def _compute_primary_therapy(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> Optional[str]:
        """Determine primary therapy from IVT eligibility + EVT availability."""
        ivt_ok = effective_ivt in ("eligible", "caution")
        evt_ok = overrides.evt_available is True and has_evt_recs

        if ivt_ok and evt_ok:
            return "DUAL"
        if evt_ok:
            return "EVT"
        if ivt_ok:
            return "IVT"

        # EVT not yet answered
        if overrides.evt_available is None and has_evt_recs:
            return None  # pending EVT availability answer

        return "NONE"

    # ------------------------------------------------------------------
    # #7: Dual reperfusion
    # ------------------------------------------------------------------

    def _compute_dual_reperfusion(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> bool:
        """
        LVO + time <=4.5h + IVT eligible + EVT available → dual reperfusion.
        """
        if not parsed.isLVO:
            return False
        if parsed.timeHours is None or parsed.timeHours > 4.5:
            return False
        if effective_ivt not in ("eligible", "caution"):
            return False
        if overrides.evt_available is not True:
            return False
        if not has_evt_recs:
            return False
        return True

    # ------------------------------------------------------------------
    # #6: Quick answer verdict
    # ------------------------------------------------------------------

    def _compute_verdict(
        self,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> str:
        """
        Derive YES/NO eligibility verdict from IVT + EVT results.
        """
        ivt_ok = effective_ivt in ("eligible", "caution")
        evt_ok = overrides.evt_available is True and has_evt_recs

        if effective_ivt == "pending":
            return "PENDING"
        if ivt_ok or evt_ok:
            if effective_ivt == "caution":
                return "CAUTION"
            return "ELIGIBLE"
        return "NOT_ELIGIBLE"

    # ------------------------------------------------------------------
    # #10: Visible sections
    # ------------------------------------------------------------------

    def _compute_visible_sections(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        is_extended: bool,
        overrides: ClinicalOverrides,
    ) -> List[str]:
        """
        Determine which UI sections should be visible based on clinical state.
        """
        sections = ["parsed_variables", "quick_answer"]

        # IVT pathway sections
        if not is_extended or effective_ivt != "contraindicated":
            sections.append("ivt_pathway")
            sections.append("table8_gate")

            if effective_ivt in ("eligible", "caution"):
                sections.append("table4_assessment")
                # BP management relevant when IVT is on the table
                if parsed.sbp is not None or parsed.dbp is not None:
                    sections.append("bp_management")

        # EVT sections
        if has_evt_recs:
            sections.append("evt_results")
            if overrides.evt_available is None:
                sections.append("evt_availability_gate")

        # Dual reperfusion summary
        if "ivt_pathway" in sections and "evt_results" in sections:
            sections.append("dual_reperfusion_summary")

        # Clinical checklists always visible
        sections.append("clinical_checklists")

        return sections

    # ------------------------------------------------------------------
    # Headline
    # ------------------------------------------------------------------

    def _compute_headline(
        self,
        effective_ivt: str,
        has_evt_recs: bool,
        is_dual: bool,
        bp_at_goal: Optional[bool],
        overrides: ClinicalOverrides,
    ) -> str:
        """Compute the CDS banner headline text."""
        evt_ok = overrides.evt_available is True and has_evt_recs
        ivt_ok = effective_ivt in ("eligible", "caution")
        bp_suffix = " \u2014 LOWER BP BEFORE IVT" if bp_at_goal is False and ivt_ok else ""

        if is_dual:
            return f"EVT + IVT RECOMMENDED{bp_suffix}"

        if evt_ok and effective_ivt == "contraindicated":
            return "EVT RECOMMENDED \u2014 IVT CONTRAINDICATED"

        if evt_ok and ivt_ok:
            return f"EVT + IVT RECOMMENDED{bp_suffix}"

        if evt_ok:
            return "EVT RECOMMENDED"

        if ivt_ok:
            caution = " (WITH CAUTION)" if effective_ivt == "caution" else ""
            return f"IVT RECOMMENDED{caution}{bp_suffix}"

        if effective_ivt == "contraindicated":
            if has_evt_recs and overrides.evt_available is None:
                return "IVT CONTRAINDICATED \u2014 ASSESS EVT AVAILABILITY"
            return "IVT CONTRAINDICATED"

        if effective_ivt == "pending":
            return "ASSESSMENT PENDING \u2014 REVIEW CONTRAINDICATIONS"

        return "NOT ELIGIBLE FOR REPERFUSION THERAPY"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_evt_recommendations(evt_result: dict) -> bool:
        """Check whether the EVT rule engine produced any recommendations."""
        recs = evt_result.get("recommendations", {})
        if isinstance(recs, dict):
            return any(len(v) > 0 for v in recs.values())
        if isinstance(recs, list):
            return len(recs) > 0
        return False
