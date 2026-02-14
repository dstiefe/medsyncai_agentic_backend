"""
MedSync AI v2 - Configuration
Loads environment variables for LLM providers and Firebase.
Supports per-agent provider/model overrides via AGENT_<NAME>_PROVIDER / AGENT_<NAME>_MODEL.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# LLM Provider Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Default model per provider
DEFAULT_MODELS = {
    "openai": "gpt-4.1",
    "anthropic": "claude-sonnet-4-5-20250929",
}

DEFAULT_MODEL = LLM_MODEL or DEFAULT_MODELS.get(LLM_PROVIDER, "gpt-4.1")

# Fast model tier — cheaper/faster model for classification & extraction agents
LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL")

DEFAULT_FAST_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-haiku-4-5-20251001",
}

# Agents that use the fast model by default
FAST_AGENTS = {
    "equipment_extraction",
    "query_classifier",
    "generic_device_structuring",
    "generic_prep",
    "query_spec_agent",
    "query_planner",
    "clarification_output_agent",
}


def get_agent_config(agent_name: str) -> dict:
    """
    Get provider/model config for a specific agent.

    Priority: AGENT_<NAME>_MODEL env > LLM_FAST_MODEL (if fast agent) > LLM_MODEL > DEFAULT_MODELS

    Args:
        agent_name: Agent name (e.g., "query_classifier", "chain_output_agent")

    Returns:
        {"provider": str, "model": str}
    """
    env_key = agent_name.upper()
    provider = os.getenv(f"AGENT_{env_key}_PROVIDER", LLM_PROVIDER)
    model = os.getenv(f"AGENT_{env_key}_MODEL")

    if not model:
        if agent_name in FAST_AGENTS:
            model = LLM_FAST_MODEL or DEFAULT_FAST_MODELS.get(provider)
        if not model:
            model = DEFAULT_MODELS.get(provider, DEFAULT_MODEL)

    return {"provider": provider, "model": model}


# AIS Guidelines Vector Store (clinical_support_engine)
AIS_GUIDELINES_VECTOR_STORE_ID = os.getenv("AIS_GUIDELINES_VECTOR_STORE_ID")

# Firebase Configuration
FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", "./medsyncai.json")
FIREBASE_COLLECTION = os.getenv("FIREBASE_COLLECTION", "search_database")
FIREBASE_USERS_COLLECTION = os.getenv("FIREBASE_USERS_COLLECTION", "users")
