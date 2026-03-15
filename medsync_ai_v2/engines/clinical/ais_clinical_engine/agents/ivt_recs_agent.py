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

        Paths:
        - Path A: 0-4.5h + disabling -> standard IVT
        - Path B: 0-4.5h + non-disabling -> no benefit
        - Path C: extended + DWI-FLAIR -> wake-up/extended protocol
        - Path D: extended + no DWI-FLAIR -> perfusion-guided
        - Path E: 4.5-24h + LVO + no EVT -> bridging IVT
        - Path F: wake-up + no imaging -> imaging recs
        - Additive: antiplatelet, sickle cell, bridging, BP
        """
        fired = []
        time_window = parsed.timeWindow

        # Path A: Standard 0-4.5h window with disabling deficit
        if time_window == "0-4.5" and table4_result.isDisabling is True:
            rec_ids = [
                "rec-ivt-4.6.1-001",
                "rec-ivt-4.6.1-002",
                "rec-ivt-4.6.1-003",
                "rec-ivt-4.6.1-005",
                "rec-ivt-4.6.1-010",
                "rec-ivt-4.6.2-001",
                "rec-ivt-4.6.2-002",
            ]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path B: 0-4.5h with non-disabling
        elif time_window == "0-4.5" and table4_result.isDisabling is False:
            # Only fire the "no benefit" recommendation
            rec_ids = ["rec-ivt-4.6.1-008"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path C: Extended window with DWI-FLAIR mismatch
        if time_window in ["4.5-9", "9-24"] and parsed.dwiFlair is True:
            rec_ids = ["rec-ivt-4.6.3-001"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path D: Extended window without DWI-FLAIR (perfusion-guided)
        if time_window in ["4.5-9", "9-24"] and parsed.dwiFlair is not True:
            rec_ids = ["rec-ivt-4.6.3-002"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path E: 4.5-24h with LVO
        if time_window in ["4.5-9", "9-24"] and parsed.isLVO and not parsed.evtUnavailable:
            rec_ids = ["rec-ivt-4.6.3-003"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Path F: Wake-up stroke without imaging
        if parsed.wakeUp is True and parsed.aspects is None:
            rec_ids = ["rec-ivt-3.2-006", "rec-ivt-3.2-007"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Additive: Antiplatelet already on
        if parsed.onAntiplatelet is True:
            rec_ids = ["rec-ivt-4.6.1-009"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Additive: Sickle cell
        if parsed.sickleCell is True:
            rec_ids = ["rec-ivt-4.6.5-001"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Additive: LVO bridging
        if parsed.isLVO and not parsed.evtUnavailable:
            rec_ids = ["rec-ivt-4.7.1-001", "rec-ivt-4.7.1-002"]
            fired.extend(self._fire_recommendations(rec_ids))

        # Additive: Blood pressure management
        if parsed.sbp is not None or parsed.dbp is not None:
            rec_ids = ["rec-ivt-4.3-005", "rec-ivt-4.3-007", "rec-ivt-4.3-008"]
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
                    matchedRule="ivt_pathway",
                    ruleId=""
                )
                fired.append(fired_rec)
        return fired
