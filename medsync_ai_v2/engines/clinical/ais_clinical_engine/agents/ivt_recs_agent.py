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

        # Path B: 0-4.5h with non-disabling
        elif time_window == "0-4.5" and table4_result.isDisabling is False:
            rec_ids = ["rec-4.6.1-008"]
            fired.extend(self._fire_recommendations(rec_ids))

        # ── Extended Window (Section 4.6.3) ──────────────────────────

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
