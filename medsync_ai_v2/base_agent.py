"""
MedSync AI v2 - Base Agent Classes

BaseAgent: Base for all agents (LLM or Python).
LLMAgent: Agent that makes LLM calls with SKILL.md system prompts.
"""

import os
import json
from medsync_ai_v2.shared.llm_client import get_llm_client
from medsync_ai_v2 import config


class BaseAgent:
    """Base class for all agents (LLM or Python)."""

    def __init__(self, name: str, skill_path: str = None):
        self.name = name
        self.system_message = self._load_skill(skill_path)

    def _load_skill(self, path: str) -> str:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    async def run(self, input_data: dict, session_state: dict) -> dict:
        raise NotImplementedError


class LLMAgent(BaseAgent):
    """Agent that makes LLM calls using a SKILL.md system prompt."""

    def __init__(self, name: str, skill_path: str = None, model: str = None, provider: str = None):
        super().__init__(name, skill_path)
        # Per-agent config from env vars (AGENT_<NAME>_PROVIDER / AGENT_<NAME>_MODEL)
        agent_config = config.get_agent_config(name)
        self.provider = provider or agent_config["provider"]
        self.model = model or agent_config["model"]
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            self._llm_client = get_llm_client(provider=self.provider, model=self.model)
        return self._llm_client

    async def run(self, input_data: dict, session_state: dict) -> dict:
        messages = self._build_messages(input_data, session_state)
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )
        return self._parse_response(response)

    def _build_messages(self, input_data: dict, session_state: dict) -> list:
        messages = []
        # Add conversation history if available
        for msg in session_state.get("conversation_history", []):
            if msg.get("role") in ("user", "assistant"):
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })
        # Add current input
        messages.append({
            "role": "user",
            "content": json.dumps(input_data) if isinstance(input_data, dict) else str(input_data),
        })
        return messages

    def _parse_response(self, response: dict) -> dict:
        content = response.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {"raw_text": content}
        return {
            "content": content,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
