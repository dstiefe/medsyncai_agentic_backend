"""
Configuration management for MedSync AI Sales Simulation Engine.

Handles environment variables, file paths, and application settings using Pydantic.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env from project root (two levels up from this file)
_env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_path, override=True)


class AppConfig(BaseModel):
    """Application configuration loaded from environment variables and defaults."""

    # Data paths
    data_dir: Path = Path(__file__).parent.parent.parent / "data"

    # LLM Provider configuration
    llm_provider: str = "anthropic"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # Model names
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"

    # Embedding configuration
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # Retrieval configuration
    top_k_retrieval: int = 8

    # Simulation configuration
    max_simulation_turns: int = 20

    def __init__(self, **data):
        """Initialize configuration and ensure data directory exists."""
        super().__init__(**data)
        # Load from environment variables if not provided
        if not self.anthropic_api_key:
            self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.openai_api_key:
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if "data_dir" not in data:
            self.data_dir = Path(__file__).parent.parent.parent / "data"
        # Ensure data directory path is resolved
        self.data_dir = self.data_dir.resolve()


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """
    Get the singleton application configuration.

    Returns:
        AppConfig: The application configuration instance.
    """
    return AppConfig()
