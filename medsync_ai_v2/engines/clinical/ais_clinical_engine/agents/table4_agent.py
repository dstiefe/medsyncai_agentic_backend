from typing import List, Optional, Tuple
from ..models.clinical import NIHSSItems
from ..models.table4 import Table4Result


class Table4Agent:
    """Agent for assessing disabling vs non-disabling deficits."""

    # (field_name, threshold, label)
    DISABLING_CHECKS: List[Tuple[str, int, str]] = [
        ("vision", 2, "vision >= 2"),
        ("bestLanguage", 2, "best language >= 2"),
        ("extinction", 2, "extinction >= 2"),
        ("motorArmL", 2, "motor arm L >= 2"),
        ("motorArmR", 2, "motor arm R >= 2"),
        ("motorLegL", 2, "motor leg L >= 2"),
        ("motorLegR", 2, "motor leg R >= 2"),
    ]

    def evaluate(self, nihss: Optional[int], nihss_items: Optional[NIHSSItems], non_disabling: Optional[bool] = None) -> Table4Result:
        """
        Evaluate disabling vs non-disabling deficits.

        Logic:
        - If nonDisabling is explicitly set: use it directly
        - If NIHSS is None: needs_assessment
        - If NIHSS >= 6: is_disabling = True, standard IVT
        - If NIHSS 0-5 and nihss_items available: check disabling items
        - If NIHSS 0-5 but no nihss_items: needs_assessment
        """
        # If the scenario explicitly states disabling/non-disabling, use that
        if non_disabling is True:
            return Table4Result(
                isDisabling=False,
                rationale="Deficits explicitly described as non-disabling in scenario",
                possiblyNonDisabling=["Explicitly non-disabling per clinical description"],
                recommendation="non_disabling_dapt"
            )
        if non_disabling is False:
            return Table4Result(
                isDisabling=True,
                rationale="Deficits explicitly described as disabling in scenario (e.g., cannot walk, cannot use arm)",
                disablingDeficits=["Explicitly disabling per clinical description"],
                recommendation="standard_ivt"
            )

        if nihss is None:
            return Table4Result(
                isDisabling=None,
                rationale="NIHSS score not provided, assessment needed",
                recommendation="needs_assessment"
            )

        # NIHSS >= 6 is disabling
        if nihss >= 6:
            return Table4Result(
                isDisabling=True,
                rationale=(
                    f"NIHSS {nihss} >= 6 indicates substantial deficit burden consistent with "
                    f"clearly disabling stroke. Deficits should be functionally disabling per "
                    f"Table 4 BATHE criteria (Bathing, Ambulating, Toileting, Hygiene, Eating). "
                    f"Final determination of deficit severity should be confirmed by the "
                    f"treating clinician."
                ),
                disablingDeficits=[f"NIHSS {nihss}"],
                recommendation="standard_ivt"
            )

        # NIHSS 0-5: check items if available
        if nihss_items is not None:
            disabling_items = []
            possibly_non_disabling = []

            for field_name, threshold, label in self.DISABLING_CHECKS:
                value = getattr(nihss_items, field_name, None)
                if value is not None and value >= threshold:
                    disabling_items.append(label)

            if disabling_items:
                return Table4Result(
                    isDisabling=True,
                    rationale=f"Low NIHSS ({nihss}) but has disabling deficits: {', '.join(disabling_items)}",
                    disablingDeficits=disabling_items,
                    recommendation="standard_ivt"
                )
            else:
                return Table4Result(
                    isDisabling=False,
                    rationale=f"NIHSS {nihss} and no disabling items found",
                    possiblyNonDisabling=["All NIHSS items below disabling threshold"],
                    recommendation="non_disabling_dapt"
                )

        # NIHSS 0-5 but no items: needs assessment
        return Table4Result(
            isDisabling=None,
            rationale=f"NIHSS {nihss} but detailed NIHSS items not provided for precise assessment",
            recommendation="needs_assessment"
        )
