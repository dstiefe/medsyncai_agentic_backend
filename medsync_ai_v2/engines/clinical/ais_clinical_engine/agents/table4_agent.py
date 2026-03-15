from typing import List, Optional, Tuple
from ..models.clinical import NIHSSItems
from ..models.table4 import Table4Result
from ..data.loader import load_table4_checks, load_table4_logic


class Table4Agent:
    """Agent for assessing disabling vs non-disabling deficits."""

    def __init__(self):
        """Initialize Table 4 agent with checks from JSON data."""
        raw_checks = load_table4_checks()
        self.disabling_checks: List[Tuple[str, int, str]] = [
            (c["field"], c["threshold"], c["label"]) for c in raw_checks
        ]
        self.nihss_threshold: int = load_table4_logic()["nihss_disabling_threshold"]

    def evaluate(self, nihss: Optional[int], nihss_items: Optional[NIHSSItems]) -> Table4Result:
        """
        Evaluate disabling vs non-disabling deficits.

        Logic:
        - If NIHSS is None: needs_assessment
        - If NIHSS >= threshold (6): is_disabling = True, standard IVT
        - If NIHSS 0-5 and nihss_items available: check disabling items
        - If NIHSS 0-5 but no nihss_items: needs_assessment
        """
        if nihss is None:
            return Table4Result(
                isDisabling=None,
                rationale="NIHSS score not provided, assessment needed",
                recommendation="needs_assessment"
            )

        # NIHSS >= threshold is disabling
        if nihss >= self.nihss_threshold:
            return Table4Result(
                isDisabling=True,
                rationale=(
                    f"NIHSS {nihss} >= {self.nihss_threshold} indicates substantial deficit burden consistent with "
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

            for field_name, threshold, label in self.disabling_checks:
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
