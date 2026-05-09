"""
Sales Training Engine — BaseEngine wrapper for the SSE pipeline.

Handles domain detection from the orchestrator and returns a sales_redirect
event so the frontend can call the sales REST endpoints directly.
"""

import os
from pathlib import Path

from app.base_engine import BaseEngine

SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


class SalesTrainingEngine(BaseEngine):
    """
    Thin orchestrator wrapper for the sales training domain.

    When the domain classifier routes a query here, this engine returns
    a sales_redirect status so the SSE pipeline emits a redirect event.
    The frontend then calls the sales REST endpoints directly.
    """

    def __init__(self):
        super().__init__(name="sales_training_engine", skill_path=SKILL_PATH)

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """
        Return a sales_redirect signal.

        The orchestrator reads this and emits an SSE event telling the
        frontend to switch to the sales UI.
        """
        query = input_data.get("normalized_query", input_data.get("query", ""))

        return self._build_return(
            status="complete",
            result_type="sales_redirect",
            data={
                "message": "This query is related to sales training. Redirecting to the Sales Training interface.",
                "redirect": True,
                "original_query": query,
            },
            classification={
                "domain": "sales",
                "action": "redirect_to_sales_ui",
            },
            confidence=0.95,
        )
