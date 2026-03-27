"""
MedSync AI v2 - Base Engine Class

BaseEngine: Base for sub-orchestrators (chain_engine, database_engine, etc.)
Engines use deterministic Python pipelines internally.
They return structured data via the standard return contract.
"""

from medsync_ai_v2.base_agent import BaseAgent


class BaseEngine(BaseAgent):
    """Base class for sub-orchestrators (chain_engine, database_engine, etc.)"""

    def __init__(self, name: str, skill_path: str = None):
        super().__init__(name, skill_path)
        self.sub_agents = {}

    def register_agent(self, agent):
        self.sub_agents[agent.name] = agent

    async def run(self, input_data: dict, session_state: dict) -> dict:
        """Deterministic pipeline -- override per engine."""
        raise NotImplementedError

    def _build_return(
        self,
        status: str,
        result_type: str,
        data: dict,
        classification: dict,
        confidence: float = 0.9,
    ) -> dict:
        """
        Build the standard return contract that all engines must use.
        The orchestrator relies on this structure to decide what to do next.
        """
        return {
            "status": status,  # "complete" | "error" | "needs_clarification"
            "engine": self.name,
            "result_type": result_type,
            "data": data,
            "classification": classification,
            "confidence": confidence,
        }
