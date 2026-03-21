"""
DecisionEngine — single source of truth for all derived clinical decisions.

All clinical logic lives here. The frontend is a pure display layer —
it sends variables + gate answers, receives fully computed state to render.

All logic is deterministic — no LLM calls.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..models.clinical import (
    ClinicalDecisionState,
    ClinicalOverrides,
    ParsedVariables,
)
from ..models.table8 import Table8Item, Table8Result

POSTERIOR_VESSELS = {"basilar", "ba", "pca", "p1", "p2", "p3", "vertebral", "va"}


class DecisionEngine:
    """Computes the effective clinical decision state from raw results + clinician overrides."""

    def compute_effective_state(
        self,
        parsed: ParsedVariables,
        ivt_result: dict,
        evt_result: dict,
        overrides: Optional[ClinicalOverrides] = None,
    ) -> ClinicalDecisionState:
        if overrides is None:
            overrides = ClinicalOverrides()

        # --- Derived flags ---
        is_extended = self._is_extended_window(parsed)
        is_posterior = bool(parsed.vessel and parsed.vessel.lower() in POSTERIOR_VESSELS)
        is_basilar = bool(parsed.vessel and parsed.vessel.lower() in ("basilar", "ba"))
        bp_at_goal, bp_warning = self._compute_bp_status(parsed)
        bp_not_at_goal = bp_at_goal is False

        # --- IVT ---
        effective_ivt = self._compute_effective_ivt_eligibility(parsed, ivt_result, overrides)
        effective_disabling = self._compute_effective_disabling(parsed, ivt_result, overrides)
        ivt_missing = self._compute_ivt_missing(parsed)

        # --- EVT ---
        has_evt_recs = self._has_evt_recommendations(evt_result)
        backend_evt = evt_result.get("eligibility", {})
        evt_status, evt_reason = self._compute_evt_status(
            parsed, backend_evt, has_evt_recs, overrides
        )
        evt_missing = self._compute_evt_missing(parsed, backend_evt)

        # --- Therapy pathway ---
        primary_therapy = self._compute_primary_therapy(
            parsed, effective_ivt, has_evt_recs, overrides
        )
        is_dual = self._compute_dual_reperfusion(
            parsed, effective_ivt, has_evt_recs, overrides
        )
        verdict = self._compute_verdict(effective_ivt, has_evt_recs, overrides)
        visible = self._compute_visible_sections(
            parsed, effective_ivt, has_evt_recs, is_extended, overrides
        )

        # --- Display text (ALL clinical reasoning for CDS) ---
        headline = self._compute_headline(
            parsed, effective_ivt, evt_status, evt_reason, is_extended,
            bp_not_at_goal, overrides
        )
        description = self._compute_description(
            parsed, effective_ivt, evt_status, evt_reason, is_extended,
            is_posterior, is_basilar, bp_not_at_goal, backend_evt, overrides
        )
        evt_status_text = self._compute_evt_status_text(
            parsed, evt_status, evt_reason, evt_missing, is_basilar,
            backend_evt, overrides
        )
        ivt_status_text = self._compute_ivt_status_text(
            parsed, effective_ivt, evt_status, is_extended, is_posterior,
            is_basilar, bp_not_at_goal, ivt_missing, ivt_result, overrides
        )
        ivt_badge = self._compute_ivt_badge(effective_ivt, bp_not_at_goal)

        # --- EVT COR/LOE (only when recommended) ---
        evt_cor, evt_loe = self._extract_evt_cor_loe(evt_result, evt_status)

        # --- IVT COR/LOE (only when final decision reached) ---
        if effective_ivt in ("eligible", "not_recommended", "contraindicated", "caution"):
            ivt_cor, ivt_loe, ivt_rec_id = self._extract_ivt_cor_loe(ivt_result, effective_ivt)
        else:
            ivt_cor, ivt_loe, ivt_rec_id = None, None, None

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
            description=description,
            evt_status=evt_status,
            evt_status_text=evt_status_text,
            evt_status_reason=evt_reason,
            ivt_status_text=ivt_status_text,
            ivt_badge=ivt_badge,
            evt_missing=evt_missing,
            ivt_missing=ivt_missing,
            is_posterior=is_posterior,
            is_basilar=is_basilar,
            evt_cor=evt_cor,
            evt_loe=evt_loe,
            evt_narrowing=backend_evt.get("narrowingSummary"),
            ivt_cor=ivt_cor,
            ivt_loe=ivt_loe,
            ivt_rec_id=ivt_rec_id,
        )

    # ------------------------------------------------------------------
    # Extended window detection
    # ------------------------------------------------------------------

    def _is_extended_window(self, parsed: ParsedVariables) -> bool:
        if parsed.timeHours is not None and parsed.timeHours > 4.5:
            return True
        return parsed.wakeUp is True

    # ------------------------------------------------------------------
    # Effective IVT eligibility
    # ------------------------------------------------------------------

    def _compute_effective_ivt_eligibility(
        self, parsed: ParsedVariables, ivt_result: dict, overrides: ClinicalOverrides
    ) -> str:
        # Non-disabling low NIHSS → IVT not recommended (Section 4.6.1)
        is_non_disabling = (
            parsed.nonDisabling is True
            or overrides.table4_override is False  # table4_override=False means non-disabling
        )
        if (parsed.nihss is not None and parsed.nihss <= 5 and is_non_disabling):
            return "not_recommended"

        checklist: List[dict] = ivt_result.get("table8Checklist", [])
        if not checklist:
            return "eligible" if ivt_result.get("eligible", False) else "contraindicated"

        effective_items = self._apply_table8_overrides(checklist, overrides)

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
        result = []
        for item in checklist:
            item_copy = dict(item)
            rule_id = item_copy["ruleId"]
            tier = item_copy["tier"]

            if rule_id in overrides.table8_overrides:
                item_copy["status"] = overrides.table8_overrides[rule_id]
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
    # Effective disabling assessment
    # ------------------------------------------------------------------

    def _compute_effective_disabling(
        self, parsed: ParsedVariables, ivt_result: dict, overrides: ClinicalOverrides
    ) -> Optional[bool]:
        # parsed.nonDisabling comes from what-if gate changes
        if parsed.nonDisabling is not None:
            return not parsed.nonDisabling  # nonDisabling=True → isDisabling=False
        if overrides.table4_override is not None:
            return overrides.table4_override
        disabling_assessment = ivt_result.get("disablingAssessment", {})
        return disabling_assessment.get("isDisabling")

    # ------------------------------------------------------------------
    # BP status
    # ------------------------------------------------------------------

    def _compute_bp_status(
        self, parsed: ParsedVariables
    ) -> Tuple[Optional[bool], Optional[str]]:
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
    # EVT status (the core logic formerly in ClinicalDecisionSummary.tsx)
    # ------------------------------------------------------------------

    def _compute_evt_status(
        self,
        parsed: ParsedVariables,
        backend_evt: dict,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> Tuple[str, str]:
        """
        Returns (status, reason) where status is recommended/pending/not_applicable
        and reason is a short machine-readable tag.

        Gate overrides (LKW, M2 dominance) are checked first since they come
        from interactive clinician input and aren't part of the rule engine's
        clause evaluation.  All other variable-level exclusions (NIHSS, mRS,
        ASPECTS, age, time, vessel, etc.) are handled by the rule engine's
        universal-blocker detection — no need to hard-code thresholds here.
        """
        # LKW > 24h or unknown: gate override from clinician
        if overrides.lkw_within_24h is False:
            return "not_applicable", "lkw_excludes"

        # M2 nondominant: from NLP or gate override
        m2_dominant = overrides.m2_is_dominant if overrides.m2_is_dominant is not None else parsed.m2Dominant
        if parsed.isM2 and m2_dominant is False:
            return "not_applicable", "m2_nondominant"

        # M2 pending qualifier — only if dominance not yet determined
        if parsed.isM2 and backend_evt.get("status") != "excluded" and m2_dominant is None:
            return "pending", "m2_pending"

        # Backend says eligible
        if backend_evt.get("status") == "eligible":
            return "recommended", "backend_eligible"

        # Backend says excluded (a negative recommendation explicitly fired,
        # e.g. EVT-ineligible vessel)
        if backend_evt.get("status") == "excluded":
            return "not_applicable", "backend_excluded"

        # Backend says pending
        if backend_evt.get("status") == "pending":
            return "pending", "backend_pending"

        # No LVO
        vessel = parsed.vessel
        if vessel and vessel.lower() == "no lvo":
            return "not_applicable", "no_lvo"

        return "pending", "awaiting_data"

    # ------------------------------------------------------------------
    # Missing variables
    # ------------------------------------------------------------------

    def _compute_evt_missing(self, parsed: ParsedVariables, backend_evt: dict) -> List[str]:
        backend_missing = backend_evt.get("missingVariables", [])
        if backend_missing:
            # Only show user-facing clinical variables; skip internal/derived vars
            # like massEffect, m2Dominant (handled by gates)
            labels = {
                "vessel": "vessel imaging (CTA/MRA)",
                "timeHours": "time from onset / LKW",
                "nihss": "NIHSS",
                "aspects": "ASPECTS score",
                "prestrokeMRS": "pre-stroke mRS",
                "age": "age",
            }
            return [labels[v] for v in backend_missing if v in labels]

        # Client-side fallback
        missing = []
        if not parsed.vessel:
            missing.append("vessel imaging (CTA/MRA)")
        elif parsed.vessel.upper() == "LVO":
            missing.append("specific vessel (CTA/MRA — e.g. ICA, M1, M2, basilar)")
        if parsed.timeHours is None and not parsed.wakeUp and parsed.lastKnownWellHours is None:
            missing.append("time from onset / LKW")
        if parsed.aspects is None:
            missing.append("ASPECTS score")
        if parsed.nihss is None:
            missing.append("NIHSS")
        if parsed.prestrokeMRS is None:
            missing.append("pre-stroke mRS")
        if parsed.age is None:
            missing.append("age")
        return missing

    def _compute_ivt_missing(self, parsed: ParsedVariables) -> List[str]:
        missing = []
        is_unknown = parsed.timeWindow == "unknown"
        if parsed.timeHours is None and not parsed.wakeUp and not is_unknown:
            missing.append("time from onset")
        return missing

    # ------------------------------------------------------------------
    # Headline (fully replaces frontend getHeadline)
    # ------------------------------------------------------------------

    def _compute_headline(
        self,
        parsed: ParsedVariables,
        ivt_status: str,
        evt_status: str,
        evt_reason: str,
        is_extended: bool,
        bp_not_at_goal: bool,
        overrides: ClinicalOverrides,
    ) -> str:
        if evt_status == "recommended":
            if ivt_status == "pending" and bp_not_at_goal:
                return "EVT RECOMMENDED \u2014 IVT PENDING \u2014 LOWER BP"
            if ivt_status == "pending":
                return "EVT RECOMMENDED \u2014 IVT ELIGIBILITY PENDING"
            if ivt_status == "eligible" and bp_not_at_goal:
                return "EVT + IVT RECOMMENDED \u2014 LOWER BP BEFORE IVT"
            if ivt_status == "eligible":
                return "EVT + IVT RECOMMENDED"
            if ivt_status == "contraindicated":
                return "EVT RECOMMENDED \u2014 IVT CONTRAINDICATED"
            if ivt_status == "caution":
                return "EVT RECOMMENDED \u2014 IVT CAUTION"
            return "EVT RECOMMENDED"

        # Both pending
        if evt_status == "pending" and ivt_status == "pending":
            return ("EVALUATING EVT & IVT \u2014 DATA NEEDED" if is_extended
                    else "EVALUATING IVT & EVT \u2014 DATA NEEDED")

        # EVT pending, IVT resolved
        if evt_status == "pending" and ivt_status == "eligible":
            return "IVT RECOMMENDED \u2014 EVT PENDING"
        if evt_status == "pending" and ivt_status == "contraindicated":
            return "IVT CONTRAINDICATED \u2014 EVT PENDING"

        # EVT not applicable
        if evt_status == "not_applicable":
            if ivt_status == "not_recommended":
                return "EVT NOT RECOMMENDED \u2014 IVT NOT RECOMMENDED"
            if ivt_status == "eligible" and bp_not_at_goal:
                return "EVT NOT RECOMMENDED \u2014 IVT: LOWER BP"
            if ivt_status == "eligible":
                return "EVT NOT RECOMMENDED \u2014 IVT RECOMMENDED"
            if ivt_status == "contraindicated":
                return "EVT NOT RECOMMENDED \u2014 IVT CONTRAINDICATED"
            return "EVT NOT RECOMMENDED \u2014 EVALUATING IVT"

        # IVT resolved, no EVT context
        if ivt_status == "not_recommended":
            return "IVT NOT RECOMMENDED \u2014 NON-DISABLING DEFICIT"
        if ivt_status == "eligible" and bp_not_at_goal:
            return "IVT RECOMMENDED \u2014 LOWER BP BEFORE ADMINISTRATION"
        if ivt_status == "eligible":
            return "IVT RECOMMENDED"
        if ivt_status == "contraindicated":
            return "IVT CONTRAINDICATED"
        if ivt_status == "caution":
            return "IVT \u2014 CAUTION"

        return "EVALUATING IVT & EVT \u2014 DATA NEEDED"

    # ------------------------------------------------------------------
    # Description (fully replaces frontend getDescription)
    # ------------------------------------------------------------------

    def _compute_description(
        self,
        parsed: ParsedVariables,
        ivt_status: str,
        evt_status: str,
        evt_reason: str,
        is_extended: bool,
        is_posterior: bool,
        is_basilar: bool,
        bp_not_at_goal: bool,
        backend_evt: dict,
        overrides: ClinicalOverrides,
    ) -> str:
        if evt_status == "recommended" and ivt_status == "pending" and bp_not_at_goal:
            bp = f"SBP {parsed.sbp} mmHg" if parsed.sbp and parsed.sbp > 185 else f"DBP {parsed.dbp} mmHg"
            return (f"Patient meets criteria for EVT. {bp} exceeds IVT threshold "
                    f"(< 185/110) \u2014 initiate BP lowering now. Complete contraindication "
                    f"screen for IVT eligibility. Do not delay EVT initiation (Section 4.7.1).")

        if evt_status == "recommended" and ivt_status == "pending":
            return ("Patient meets criteria for EVT. Complete the contraindication screen "
                    "to determine IVT eligibility. If eligible, IVT should be administered "
                    "without delaying EVT (Section 4.7.1).")

        if evt_status == "recommended" and ivt_status == "eligible" and bp_not_at_goal:
            return (f"No contraindications found for IVT. SBP {parsed.sbp} mmHg exceeds "
                    f"185 mmHg threshold \u2014 lower BP before IVT administration. "
                    f"Do not delay EVT initiation (Section 4.7.1).")

        if evt_status == "recommended" and ivt_status == "eligible":
            return ("Both IVT and EVT are recommended. IVT should be administered as "
                    "rapidly as possible, without delaying EVT initiation (Section 4.7.1).")

        if evt_status == "recommended" and ivt_status == "contraindicated":
            return "EVT recommended. IVT is contraindicated \u2014 proceed directly to EVT."

        if evt_status == "recommended":
            return "Patient meets guideline criteria for endovascular thrombectomy. See IVT status below."

        # EVT not applicable — show reason
        if evt_status == "not_applicable":
            if evt_reason == "m2_nondominant":
                reasons = ["Nondominant/codominant M2 \u2014 EVT is not recommended to improve "
                           "functional outcomes (COR 3: No Benefit, LOE A, Section 4.7.2 Rec 8)."]
                if backend_evt.get("exclusionReasons"):
                    reasons.extend(backend_evt["exclusionReasons"])
                return f"EVT NOT RECOMMENDED: {' '.join(reasons)} Evaluating IVT eligibility."

            if evt_reason == "backend_excluded":
                reasons = " ".join(backend_evt.get("exclusionReasons", [])) or "No guideline recommendation supports EVT for this clinical scenario."
                posterior_note = ""
                if is_extended and is_posterior:
                    posterior_note = (" Note: Extended window IVT evidence is from "
                                     "anterior circulation trials. Applicability to posterior "
                                     "circulation is not established.")
                return f"EVT NOT RECOMMENDED: {reasons} Evaluating IVT eligibility.{posterior_note}"

            if evt_reason == "lkw_excludes":
                return ("Time from onset unknown \u2014 EVT not recommended per 2026 AHA/ASA "
                        "Guidelines (no evidence beyond 24h from LKW). Evaluating IVT "
                        "eligibility. See status below.")

            if evt_reason == "no_lvo":
                return "No large vessel occlusion identified. Evaluating IVT eligibility. See status below."

            return "EVT not applicable. Evaluating IVT eligibility. See status below."

        # Both pending — extended window context
        if is_extended and is_posterior:
            if is_basilar:
                return ("Extended window: EVT is the primary reperfusion therapy for basilar "
                        "occlusion. Extended window IVT evidence is from anterior circulation "
                        "trials. See status for each therapy below.")
            return ("Extended window: Posterior circulation stroke. Extended window IVT evidence "
                    "is from anterior circulation trials. Applicability to posterior circulation "
                    "is not established. See status below.")

        if is_extended:
            return ("Extended window: EVT is the preferred primary therapy if patient is eligible. "
                    "IVT requires separate imaging evidence. "
                    "See status for each therapy below.")

        return "Both IVT and EVT are being assessed in parallel. See status for each therapy below."

    # ------------------------------------------------------------------
    # EVT status text (fully replaces frontend getEvtStatusText)
    # ------------------------------------------------------------------

    def _compute_evt_status_text(
        self,
        parsed: ParsedVariables,
        evt_status: str,
        evt_reason: str,
        evt_missing: List[str],
        is_basilar: bool,
        backend_evt: dict,
        overrides: ClinicalOverrides,
    ) -> str:
        if evt_status == "recommended":
            basilar_note = ""
            if is_basilar and parsed.pcAspects is None:
                basilar_note = (" Per Section 4.7.3: EVT recommendation includes PC-ASPECTS "
                               "\u22656 (mild ischemic damage). PC-ASPECTS not provided \u2014 "
                               "obtain if available.")
            return f"RECOMMENDED \u2014 Patient meets clinical criteria.{basilar_note}"

        if evt_status == "not_applicable":
            if evt_reason == "m2_nondominant":
                reasons = ["Nondominant/codominant M2 \u2014 EVT not recommended "
                           "(COR 3: No Benefit, Section 4.7.2 Rec 8)."]
                if backend_evt.get("exclusionReasons"):
                    reasons.extend(backend_evt["exclusionReasons"])
                return f"NOT RECOMMENDED \u2014 {' '.join(reasons)}"

            if evt_reason == "lkw_excludes":
                return ("Not applicable \u2014 LKW > 24 hours or unknown. "
                        "No EVT evidence supports treatment beyond 24h from last known well.")

            if evt_reason == "backend_excluded":
                reasons = " ".join(backend_evt.get("exclusionReasons", [])) or "No guideline recommendation supports EVT for this clinical scenario."
                return f"NOT RECOMMENDED \u2014 {reasons}"

            if evt_reason == "no_lvo":
                return "Not applicable \u2014 no LVO identified."

            return "Not applicable."

        # Pending states
        if evt_reason == "m2_pending":
            return "M2 occlusion detected \u2014 determine if dominant/proximal to assess EVT eligibility."

        # LVO unspecified — need specific vessel
        if parsed.vessel and parsed.vessel.upper() == "LVO":
            other_missing = [m for m in evt_missing if not m.startswith("specific vessel")]
            extras = f" Also needed: {', '.join(other_missing)}." if other_missing else ""
            return f"LVO confirmed \u2014 specify vessel (ICA, M1, M2, basilar) for EVT eligibility.{extras}"

        if evt_missing:
            return f"Eligibility pending. Still needed: {', '.join(evt_missing)}."

        return "Data provided but EVT criteria not met per guidelines."

    # ------------------------------------------------------------------
    # IVT status text (fully replaces frontend getIvtStatusText)
    # ------------------------------------------------------------------

    def _compute_ivt_status_text(
        self,
        parsed: ParsedVariables,
        ivt_status: str,
        evt_status: str,
        is_extended: bool,
        is_posterior: bool,
        is_basilar: bool,
        bp_not_at_goal: bool,
        ivt_missing: List[str],
        ivt_result: dict,
        overrides: ClinicalOverrides,
    ) -> str:
        is_posterior_extended = is_posterior and is_extended

        if ivt_status == "eligible" and bp_not_at_goal:
            return (f"No contraindications found. Lower BP to < 185/110 "
                    f"(current SBP {parsed.sbp} mmHg) before IVT administration.")

        if ivt_status == "eligible":
            # Extract IVT rec citation
            ivt_cor, ivt_loe, ivt_rid = self._extract_ivt_cor_loe(ivt_result, ivt_status)
            rec_cite = ""
            if ivt_rid and ivt_cor:
                # rec-4.6.1-001 → Sec 4.6.1 Rec 1
                parts = ivt_rid.replace("rec-", "").split("-")
                if len(parts) >= 2:
                    sec = parts[0]
                    rec_num = str(int(parts[1])) if parts[1].isdigit() else parts[1]
                    rec_cite = f" (Section {sec} Rec {rec_num}, COR {ivt_cor}, LOE {ivt_loe})."
            if is_posterior_extended:
                if is_basilar:
                    return ("No contraindications found. Note: Extended window IVT evidence "
                            "(Section 4.6.3) is derived from anterior circulation trials. "
                            "Applicability to basilar occlusion is not established. "
                            "EVT is the primary reperfusion therapy.")
                return ("No contraindications found. Note: Extended window IVT evidence "
                        "(Section 4.6.3) is derived from anterior circulation trials "
                        "(WAKE-UP, EXTEND, TRACE-3). Applicability to posterior "
                        "circulation is not established.")
            if evt_status == "recommended" and not is_extended:
                return (f"No contraindications found. Administer IVT without delaying "
                        f"EVT (Section 4.7.1).{rec_cite}")
            if is_extended:
                return ("No contraindications found. Extended window IVT eligibility "
                        "confirmed via imaging \u2014 administer per Section 4.6.3.")
            if parsed.age is not None and parsed.age < 18:
                return (f"Pediatric patient (age {parsed.age}). IVT with alteplase may be "
                        f"considered — safety demonstrated but efficacy uncertain "
                        f"(Section 4.6.1 Rec 14, COR 2b, LOE C-LD).")
            return f"No contraindications found. Administer IVT{rec_cite}"

        if ivt_status == "not_recommended":
            return ("NIHSS \u22645 with non-disabling deficit. IVT is not recommended "
                    "(Section 4.6.1 Rec 8, COR 3: No Benefit, LOE B-R).")

        if ivt_status == "contraindicated":
            return "Absolute contraindication identified. Do not administer IVT."

        if ivt_status == "caution":
            return "Relative contraindications present. Clinical judgment required."

        # Pending — show what's needed
        if ivt_missing:
            return (f"Cannot determine IVT eligibility. Still needed: "
                    f"{', '.join(ivt_missing)}. Complete contraindication screening once available.")

        # Effective imaging from gate answers
        eff_dwi = parsed.dwiFlair if parsed.dwiFlair is not None else overrides.imaging_dwi_flair
        eff_penumbra = parsed.penumbra if parsed.penumbra is not None else overrides.imaging_penumbra

        # Unknown onset pathway (not wake-up)
        if parsed.timeWindow == "unknown" and not parsed.wakeUp:
            if eff_dwi is True:
                return ("Unknown onset. DWI-FLAIR mismatch present \u2014 IVT can be beneficial "
                        "if within 4.5h of symptom recognition. Confirm symptom "
                        "recognition time and complete contraindication screening below.")
            return ("Unknown onset. Confirm if the patient presented within 4.5 hours of symptom "
                    "recognition. MRI DWI-FLAIR mismatch is required to determine IVT eligibility. "
                    "Complete imaging and contraindication screening below.")

        # Wake-up stroke pathway
        if parsed.wakeUp:
            wakeup_within = overrides.wake_up_within_window
            if wakeup_within is True:
                if eff_dwi is True:
                    return ("Extended window confirmed (midpoint of sleep \u22649h). "
                            "DWI-FLAIR mismatch present \u2014 IVT can be beneficial within "
                            "4.5h of symptom recognition. "
                            "Complete contraindication screening below.")
                if eff_penumbra is True:
                    return ("Extended window confirmed (midpoint of sleep \u22649h). "
                            "Salvageable ischemic penumbra detected \u2014 IVT may be reasonable. "
                            "Complete contraindication screening below.")
                if eff_dwi is False and eff_penumbra is False:
                    return ("Extended window confirmed (midpoint of sleep \u22649h), but no "
                            "DWI-FLAIR mismatch or salvageable penumbra detected. "
                            "Extended-window IVT pathways may not apply.")
                if eff_dwi is False:
                    return ("Extended window confirmed (midpoint of sleep \u22649h). "
                            "No DWI-FLAIR mismatch \u2014 consider CTP for salvageable ischemic "
                            "penumbra. Complete contraindication screening below.")
                return ("Extended window confirmed (midpoint of sleep \u22649h). "
                        "Complete advanced imaging (MRI DWI-FLAIR or CTP) "
                        "and contraindication screening below to determine IVT eligibility.")

            if wakeup_within is False:
                if eff_dwi is True:
                    return ("Time from midpoint of sleep exceeds 9h, but DWI-FLAIR mismatch "
                            "present. IVT may be beneficial within 4.5h of symptom recognition. "
                            "Complete contraindication screening below.")
                if eff_dwi is False and eff_penumbra is True:
                    return ("Time from midpoint of sleep exceeds 9h. No DWI-FLAIR mismatch, "
                            "but salvageable ischemic penumbra detected on automated perfusion "
                            "imaging. IVT may be reasonable in extended window. "
                            "Complete contraindication screening below.")
                return ("Time from midpoint of sleep exceeds 9h. IVT in extended window may not "
                        "apply. Consider DWI-FLAIR mismatch imaging if available.")

            # Wake-up, time gate not yet answered
            if eff_penumbra is True:
                return ("Salvageable ischemic penumbra detected on automated perfusion imaging. "
                        "IVT may be reasonable in extended window. "
                        "Confirm time from midpoint of sleep above. "
                        "Complete contraindication screening below.")
            if eff_dwi is True:
                return ("DWI-FLAIR mismatch confirmed. IVT may be beneficial within 4.5h of "
                        "symptom recognition. "
                        "Complete contraindication screening below.")
            if eff_penumbra is False and eff_dwi is False:
                return ("Wake-up stroke detected. No salvageable ischemic penumbra or DWI-FLAIR "
                        "mismatch detected. Extended-window IVT pathways may not apply. "
                        "Confirm time from midpoint of sleep above.")
            return ("Wake-up stroke detected. Confirm imaging findings and time from midpoint "
                    "of sleep above, then complete contraindication screening below.")

        # BP not at goal
        if bp_not_at_goal:
            bp = f"SBP {parsed.sbp} mmHg" if parsed.sbp and parsed.sbp > 185 else f"DBP {parsed.dbp} mmHg"
            return (f"{bp} exceeds IVT threshold (< 185/110). Initiate BP lowering now. "
                    f"Complete contraindication screen below.")

        # Low NIHSS awaiting disabling assessment
        disabling = ivt_result.get("disablingAssessment", {})
        disabling_resolved = (parsed.nonDisabling is not None
                              or overrides.table4_override is not None)
        if (parsed.nihss is not None and parsed.nihss <= 5
                and disabling
                and not disabling_resolved):
            posterior_note = ""
            if is_posterior_extended:
                posterior_note = (" Extended window IVT evidence is from "
                                  "anterior circulation trials \u2014 applicability to "
                                  "posterior circulation is not established.")
            return (f"No contraindications found. NIHSS {parsed.nihss} \u2014 complete "
                    f"disabling assessment below to determine IVT eligibility."
                    f"{posterior_note}")

        if is_posterior_extended:
            return ("Complete contraindication screen below. Note: Extended window IVT evidence "
                    "is from anterior circulation trials. Applicability to posterior "
                    "circulation is not established.")

        return "Complete contraindication screen below before IVT decision."

    # ------------------------------------------------------------------
    # IVT badge
    # ------------------------------------------------------------------

    def _compute_ivt_badge(self, ivt_status: str, bp_not_at_goal: bool) -> str:
        if ivt_status == "not_recommended":
            return "NOT RECOMMENDED"
        if ivt_status == "eligible" and bp_not_at_goal:
            return "BP NOT AT GOAL"
        if ivt_status == "eligible":
            return "RECOMMENDED"
        if ivt_status == "contraindicated":
            return "CONTRAINDICATED"
        if ivt_status == "caution":
            return "CAUTION"
        if bp_not_at_goal:
            return "ACTION NEEDED \u2014 BP HIGH"
        return "ACTION NEEDED"

    # ------------------------------------------------------------------
    # EVT COR / LOE extraction
    # ------------------------------------------------------------------

    COR_RANK = {"1": 0, "2a": 1, "2b": 2, "3": 3}

    # Categories that contain EVT eligibility recommendations (not technique/process recs)
    EVT_ELIGIBILITY_CATEGORIES = {"evt_adult", "evt_basilar", "evt_posterior", "evt_pediatric"}

    def _extract_evt_cor_loe(
        self, evt_result: dict, evt_status: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract COR/LOE from the EVT eligibility recommendation that fired.

        Only looks at evt_adult/evt_basilar/evt_pediatric categories — NOT
        technique recs (evt_techniques) or concomitant IVT recs (ivt_concomitant),
        which would inflate the COR to 1 for all scenarios.
        """
        if evt_status != "recommended":
            return None, None

        best_cor = None
        best_loe = None
        best_rank = 999

        recs = evt_result.get("recommendations", {})
        if isinstance(recs, dict):
            for cat, cat_recs in recs.items():
                if cat not in self.EVT_ELIGIBILITY_CATEGORIES:
                    continue
                if not isinstance(cat_recs, list):
                    continue
                for rec in cat_recs:
                    cor = None
                    loe = None
                    if hasattr(rec, "cor"):
                        cor = rec.cor
                        loe = rec.loe
                    elif isinstance(rec, dict):
                        cor = rec.get("cor")
                        loe = rec.get("loe")
                    if cor:
                        rank = self.COR_RANK.get(str(cor), 999)
                        if rank < best_rank:
                            best_rank = rank
                            best_cor = str(cor)
                            best_loe = str(loe) if loe else None

        return best_cor, best_loe

    # ------------------------------------------------------------------
    # IVT COR / LOE extraction
    # ------------------------------------------------------------------

    def _extract_ivt_cor_loe(
        self, ivt_result: dict, ivt_status: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract the most relevant COR/LOE from fired IVT recommendations.

        Returns (cor, loe, rec_id). Looks at IVT recommendations that
        match the current IVT status (eligible → standard recs, not_recommended
        → non-disabling rec, etc.).
        """
        best_cor = None
        best_loe = None
        best_rec_id = None
        best_rank = 999

        recs = ivt_result.get("recommendations", [])
        if isinstance(recs, list):
            for rec in recs:
                cor = None
                loe = None
                rec_id = None
                if hasattr(rec, "cor"):
                    cor = rec.cor
                    loe = rec.loe
                    rec_id = rec.id
                elif isinstance(rec, dict):
                    cor = rec.get("cor")
                    loe = rec.get("loe")
                    rec_id = rec.get("id")
                if cor:
                    cor_str = str(cor).split(":")[0]  # "3:No Benefit" → "3"
                    rank = self.COR_RANK.get(cor_str, 999)
                    if rank < best_rank:
                        best_rank = rank
                        best_cor = str(cor)
                        best_loe = str(loe) if loe else None
                        best_rec_id = str(rec_id) if rec_id else None

        return best_cor, best_loe, best_rec_id

    # ------------------------------------------------------------------
    # Primary therapy pathway
    # ------------------------------------------------------------------

    def _compute_primary_therapy(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> Optional[str]:
        ivt_ok = effective_ivt in ("eligible", "caution")
        evt_ok = overrides.evt_available is True and has_evt_recs

        if ivt_ok and evt_ok:
            return "DUAL"
        if evt_ok:
            return "EVT"
        if ivt_ok:
            return "IVT"
        if overrides.evt_available is None and has_evt_recs:
            return None
        return "NONE"

    # ------------------------------------------------------------------
    # Dual reperfusion
    # ------------------------------------------------------------------

    def _compute_dual_reperfusion(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> bool:
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
    # Quick answer verdict
    # ------------------------------------------------------------------

    def _compute_verdict(
        self,
        effective_ivt: str,
        has_evt_recs: bool,
        overrides: ClinicalOverrides,
    ) -> str:
        ivt_ok = effective_ivt in ("eligible", "caution")
        evt_ok = overrides.evt_available is True and has_evt_recs

        if effective_ivt == "pending":
            return "PENDING"
        if ivt_ok or evt_ok:
            if effective_ivt == "caution":
                return "CAUTION"
            return "ELIGIBLE"
        return "NOT_RECOMMENDED"

    # ------------------------------------------------------------------
    # Visible sections
    # ------------------------------------------------------------------

    def _compute_visible_sections(
        self,
        parsed: ParsedVariables,
        effective_ivt: str,
        has_evt_recs: bool,
        is_extended: bool,
        overrides: ClinicalOverrides,
    ) -> List[str]:
        sections = ["parsed_variables", "quick_answer"]

        if not is_extended or effective_ivt != "contraindicated":
            sections.append("ivt_pathway")
            sections.append("table8_gate")

            if effective_ivt in ("eligible", "caution"):
                sections.append("table4_assessment")
                if parsed.sbp is not None or parsed.dbp is not None:
                    sections.append("bp_management")

        if has_evt_recs:
            sections.append("evt_results")
            if overrides.evt_available is None:
                sections.append("evt_availability_gate")

        if "ivt_pathway" in sections and "evt_results" in sections:
            sections.append("dual_reperfusion_summary")

        sections.append("clinical_checklists")
        return sections

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_evt_recommendations(evt_result: dict) -> bool:
        recs = evt_result.get("recommendations", {})
        if isinstance(recs, dict):
            return any(len(v) > 0 for v in recs.values())
        if isinstance(recs, list):
            return len(recs) > 0
        return False
