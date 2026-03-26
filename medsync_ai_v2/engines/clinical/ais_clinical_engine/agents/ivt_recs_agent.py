from __future__ import annotations

from typing import Dict, List
from ..models.clinical import FiredRecommendation, ParsedVariables, Recommendation
from ..models.table4 import Table4Result
from ..models.table8 import Table8Result


class IVTRecsAgent:
    """Agent for firing IVT recommendations based on clinical pathways."""

    def __init__(self, recommendations_store: Dict[str, Recommendation]):
        """
        Initialize IVT agent.

        Args:
            recommendations_store: Dict[rec_id] -> Recommendation
        """
        self.recommendations = recommendations_store

    def evaluate(
        self,
        parsed: ParsedVariables,
        table8_result: Table8Result,
        table4_result: Table4Result
    ) -> List[FiredRecommendation]:
        """
        Fire recommendations based on clinical pathway.

        Standard window (0-4.5h):
        - Path A: disabling deficit → standard IVT (4.6.1)
        - Path B: non-disabling → no benefit (4.6.1-008)

        Extended window (Section 4.6.3):
        - Path C: Unknown onset + DWI-FLAIR mismatch → 4.6.3-001
        - Path D: Penumbra + (4.5-9h OR wake-up) → 4.6.3-002
        - Path E: LVO + penumbra + 4.5-24h + no EVT → 4.6.3-003

        Imaging (Section 3.2):
        - Path F: Wake-up / unknown time → imaging recs

        Additive: antiplatelet, sickle cell, concomitant IVT+EVT, BP
        """
        fired = []
        time_window = parsed.timeWindow

        # ── Standard Window ──────────────────────────────────────────

        # Path A: Standard 0-4.5h window with disabling deficit
        if time_window == "0-4.5" and table4_result.isDisabling is True:

            if parsed.isAdult is False:
                # Pediatric pathway: fire Rec 14 ONLY (COR 2b, LOE C-LD)
                # Do NOT fire adult COR 1 recs — different recommendation applies
                fired.extend(self._fire_recommendations(["rec-4.6.1-014"]))
            else:
                # Adult pathway: standard COR 1 recs
                rec_ids = [
                    "rec-4.6.1-001",
                    "rec-4.6.1-002",
                    "rec-4.6.1-003",
                    "rec-4.6.1-005",
                    "rec-4.6.1-010",
                    "rec-4.6.2-001",
                    "rec-4.6.2-002",
                ]
                fired.extend(self._fire_recommendations(rec_ids))

                # rec-4.6.1-007: Early ischemic change informational note
                fired.extend(self._fire_recommendations(["rec-4.6.1-007"]))

                # rec-4.6.1-011: Unknown CMB burden — proceed without MRI to exclude CMBs
                if parsed.cmbBurden is None:
                    fired.extend(self._fire_recommendations(["rec-4.6.1-011"]))

                # rec-4.6.1-012: Low CMB burden (1-10)
                if parsed.cmbBurden is not None and parsed.cmbBurden <= 10:
                    fired.extend(self._fire_recommendations(["rec-4.6.1-012"]))

                # rec-4.6.1-013: High CMB burden (>10)
                if parsed.cmbBurden is not None and parsed.cmbBurden > 10:
                    fired.extend(self._fire_recommendations(["rec-4.6.1-013"]))

        # Path B: 0-4.5h with non-disabling
        elif time_window == "0-4.5" and table4_result.isDisabling is False:
            rec_ids = ["rec-4.6.1-008"]
            fired.extend(self._fire_recommendations(rec_ids))

            # Non-disabling → fire DAPT recommendations (Section 4.8)
            # Patient didn't get IVT, so DAPT is the primary treatment
            dapt_recs = [
                "rec-4.8-001",   # Aspirin within 48h (COR 1, LOE A)
                "rec-4.8-012",   # DAPT aspirin+clopidogrel within 24h for NIHSS<=3 (COR 1, LOE A)
            ]
            # NIHSS <=5 opens additional DAPT window (24-72h)
            if parsed.nihss is not None and parsed.nihss <= 5:
                dapt_recs.append("rec-4.8-014")  # DAPT for NIHSS<=5, 24-72h (COR 2a, LOE B-R)
            # Ticagrelor alternative
            dapt_recs.append("rec-4.8-013")  # Ticagrelor+aspirin alternative (COR 2b, LOE B-R)
            # Pharmacogenomic consideration
            dapt_recs.append("rec-4.8-015")  # CYP2C19 allele consideration (COR 2b, LOE B-R)
            # General antiplatelet guidance
            dapt_recs.extend([
                "rec-4.8-005",   # Antiplatelet preferred over anticoag for noncardioembolic (COR 1)
                "rec-4.8-006",   # Individualize antiplatelet selection (COR 1, LOE A)
            ])
            fired.extend(self._fire_recommendations(dapt_recs))

        # ── Extended Window: General IVT recs that apply regardless ───
        # For extended window patients with disabling deficits, fire the
        # time-independent IVT recs from 4.6.1 (adverse effects, glucose,
        # early ischemic change, CMBs). Do NOT fire 4.6.1-002 (within 4.5h)
        # or 4.6.1-010 (don't delay for labs within 4.5h) — those are
        # standard-window-specific.
        is_extended_time_window = time_window in ["4.5-9", "9-24", "unknown"]
        if is_extended_time_window and table4_result.isDisabling is True and parsed.isAdult is not False:
            general_ivt_recs = [
                "rec-4.6.1-001",   # Faster treatment improves outcomes (COR 1, LOE A)
                "rec-4.6.1-003",   # Prepared for adverse effects (COR 1, LOE B-NR)
                "rec-4.6.1-005",   # Check glucose before IVT (COR 1, LOE B-NR)
                "rec-4.6.1-007",   # Early ischemic change on imaging (COR 1, LOE A)
                "rec-4.6.2-001",   # Tenecteplase 0.25 mg/kg or alteplase (COR 1, LOE A)
                "rec-4.6.2-002",   # Tenecteplase 0.4 mg/kg NOT recommended (COR 3, LOE A)
            ]
            fired.extend(self._fire_recommendations(general_ivt_recs))

            # CMB burden recs apply regardless of time window
            if parsed.cmbBurden is None:
                fired.extend(self._fire_recommendations(["rec-4.6.1-011"]))
            elif parsed.cmbBurden <= 10:
                fired.extend(self._fire_recommendations(["rec-4.6.1-012"]))
            elif parsed.cmbBurden > 10:
                fired.extend(self._fire_recommendations(["rec-4.6.1-013"]))

        # ── Extended Window (Section 4.6.3) ──────────────────────────
        # Extended window = time > 4.5h, wake-up stroke, or unknown onset.
        # Per guideline, IVT in extended window ALWAYS requires imaging:
        #   - DWI-FLAIR mismatch (4.6.3-1) for unknown onset
        #   - Salvageable penumbra on CTP/MRI (4.6.3-2) for 4.5-9h / wake-up
        #   - LVO + penumbra + no EVT (4.6.3-3) for 4.5-24h
        #
        # When imaging is confirmed, fire the specific recommendation.
        # When imaging is NOT yet provided, fire the recommendation as
        # conditional (the decision_engine IVT status text already states
        # "requires imaging evidence per Section 4.6.3") so the clinician
        # receives guideline citations rather than an empty response.

        is_extended_time = time_window in ["4.5-9", "9-24"]
        is_any_extended = is_extended_time or parsed.wakeUp is True or time_window == "unknown"

        # Path C: DWI-FLAIR mismatch pathway (4.6.3-1)
        # Unknown onset, within 4.5h of symptom recognition, DWI-FLAIR mismatch
        if parsed.dwiFlair is True and (
            parsed.wakeUp is True or time_window == "unknown"
        ):
            rec_ids = ["rec-4.6.3-001"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path D: Penumbral imaging pathway (4.6.3-2)
        # Salvageable penumbra AND (4.5-9h from LKW OR wake-up stroke)
        # For wake-up: guideline says "within 9 hours from midpoint of sleep"
        # — we fire the rec and let the provider verify the 9h midpoint rule
        if parsed.penumbra is True and (
            time_window == "4.5-9"
            or (parsed.wakeUp is True and time_window == "unknown")
        ):
            rec_ids = ["rec-4.6.3-002"]
            fired.extend(self._fire_recommendations(rec_ids))
        # Path D fallback: time is 4.5-9h but imaging not yet provided
        # Fire 4.6.3-2 so clinician sees the guideline rec (imaging required)
        elif time_window == "4.5-9" and parsed.penumbra is None:
            rec_ids = ["rec-4.6.3-002"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path E: LVO + penumbra + 4.5-24h + cannot receive EVT (4.6.3-3)
        # "In patients with AIS due to LVO with salvageable ischemic penumbra,
        #  presenting within 4.5 to 24 hours ... and who cannot receive EVT"
        if (parsed.penumbra is True
            and parsed.isLVO
            and time_window in ["4.5-9", "9-24"]
            and parsed.evtUnavailable is True):
            rec_ids = ["rec-4.6.3-003"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Also fire 4.6.3-3 for wake-up LVO with penumbra when EVT unavailable
        if (parsed.penumbra is True
            and parsed.isLVO
            and parsed.wakeUp is True
            and time_window == "unknown"
            and parsed.evtUnavailable is True):
            rec_ids = ["rec-4.6.3-003"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Extended window 9-24h: fire 4.6.3-3 conditionally when imaging not yet provided
        # This ensures clinician sees the LVO extended window pathway
        if (time_window == "9-24"
            and parsed.isLVO
            and parsed.penumbra is None):
            rec_ids = ["rec-4.6.3-003"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Extended window general: if time > 4.5h and NO extended recs fired yet,
        # fire the applicable 4.6.3 rec so the response is never empty.
        # This covers Pattern D/E cases that had zero recs.
        # Route to the correct rec based on time window:
        #   4.5-9h → Rec 2 (penumbra pathway)
        #   9-24h → Rec 3 (LVO + penumbra + no EVT pathway)
        #   unknown → Rec 1 (DWI-FLAIR) or Rec 2 (penumbra) depending on context
        extended_rec_ids = {"rec-4.6.3-001", "rec-4.6.3-002", "rec-4.6.3-003"}
        fired_ids = {r.id for r in fired}
        if is_any_extended and not (fired_ids & extended_rec_ids):
            if time_window == "4.5-9":
                fired.extend(self._fire_recommendations(["rec-4.6.3-002"]))
            elif time_window == "9-24":
                fired.extend(self._fire_recommendations(["rec-4.6.3-003"]))
            elif time_window == "unknown":
                # Unknown onset: default to DWI-FLAIR pathway (Rec 1)
                fired.extend(self._fire_recommendations(["rec-4.6.3-001"]))

        # ── Patient Discussion (rec-4.6.1-004) ────────────────────────
        # Fire in ALL eligible IVT pathways (standard + extended)
        # Check if any IVT-related rec has already fired
        ivt_rec_ids = {r.id for r in fired}
        ivt_pathway_active = bool(
            ivt_rec_ids & {
                "rec-4.6.1-001", "rec-4.6.3-001",
                "rec-4.6.3-002", "rec-4.6.3-003",
            }
        )
        if ivt_pathway_active:
            fired.extend(self._fire_recommendations(["rec-4.6.1-004"]))

        # ── Glucose Correction (rec-4.6.1-006) ────────────────────────
        if parsed.glucoseCorrected is True:
            fired.extend(self._fire_recommendations(["rec-4.6.1-006"]))

        # ── Imaging Recommendations (Section 3.2) ───────────────────

        # Path F: Wake-up / unknown time — recommend advanced imaging
        if parsed.wakeUp is True and parsed.dwiFlair is not True and parsed.penumbra is not True:
            rec_ids = ["rec-3.2-006", "rec-3.2-007"]
            fired.extend(self._fire_recommendations(rec_ids))

        # ── Additive Recommendations ─────────────────────────────────

        # Antiplatelet already on
        if parsed.onAntiplatelet is True:
            rec_ids = ["rec-4.6.1-009"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Sickle cell
        if parsed.sickleCell is True:
            rec_ids = ["rec-4.6.5-001"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Concomitant IVT+EVT (IVT should not delay EVT)
        # NOTE: EVT recs (rec-4.7.1-001/002) are fired by the EVT rule
        # engine when full EVT criteria are met (ASPECTS, time, NIHSS, mRS,
        # vessel). Do NOT fire them here — the IVT agent lacks visibility into
        # whether EVT eligibility has been confirmed.

        # Blood pressure management
        if parsed.sbp is not None or parsed.dbp is not None:
            rec_ids = ["rec-4.3-005", "rec-4.3-007", "rec-4.3-008"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Remove duplicates while preserving order
        seen_ids = set()
        unique_fired = []
        for rec in fired:
            if rec.id not in seen_ids:
                seen_ids.add(rec.id)
                unique_fired.append(rec)

        return unique_fired

    def _fire_recommendations(self, rec_ids: List[str]) -> List[FiredRecommendation]:
        """Convert recommendation IDs to FiredRecommendation objects."""
        fired = []
        for rec_id in rec_ids:
            if rec_id in self.recommendations:
                base_rec = self.recommendations[rec_id]
                # Support both dict and Pydantic model access
                def _get(obj, key, default=None):
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)

                fired_rec = FiredRecommendation(
                    id=_get(base_rec, "id", rec_id),
                    guidelineId=_get(base_rec, "guidelineId", ""),
                    section=_get(base_rec, "section", ""),
                    recNumber=_get(base_rec, "recNumber", ""),
                    cor=_get(base_rec, "cor", ""),
                    loe=_get(base_rec, "loe", ""),
                    category=_get(base_rec, "category", ""),
                    text=_get(base_rec, "text", ""),
                    sourcePages=_get(base_rec, "sourcePages", []),
                    evidenceKey=_get(base_rec, "evidenceKey"),
                    prerequisites=_get(base_rec, "prerequisites", []),
                    matchedRule="ivt_pathway",
                    ruleId=""
                )
                fired.append(fired_rec)
        return fired
