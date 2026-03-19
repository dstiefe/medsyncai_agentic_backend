"""
LLM service for MedSync AI Sales Simulation Engine.

Provider-agnostic service for language model generation (Anthropic Claude or OpenAI GPT).
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, List, Optional

from anthropic import Anthropic
from openai import AsyncOpenAI

from ..config import get_settings


class LLMService:
    """Provider-agnostic service for LLM generation."""

    def __init__(self, config=None):
        """
        Initialize LLMService with configured provider.

        Args:
            config: Optional configuration object. If None, uses default settings.
        """
        self.config = config or get_settings()

        # Initialize clients based on configuration
        self.anthropic_client = None
        self.openai_client = None

        if self.config.anthropic_api_key:
            self.anthropic_client = Anthropic(
                api_key=self.config.anthropic_api_key
            )

        if self.config.openai_api_key:
            self.openai_client = AsyncOpenAI(
                api_key=self.config.openai_api_key
            )

        # Default to Anthropic if available
        self.provider = (
            "anthropic"
            if self.anthropic_client
            else ("openai" if self.openai_client else None)
        )

        if not self.provider:
            raise ValueError(
                "No LLM provider configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY"
            )

    async def generate(
        self,
        system_prompt: str,
        messages: List[dict],
        context: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> str:
        """
        Generate a response from the LLM.

        Args:
            system_prompt: System prompt to guide LLM behavior
            messages: List of message dicts with 'role' and 'content' keys
            context: Additional context to prepend to system prompt
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens in response

        Returns:
            The generated response text
        """
        # Prepend context to system prompt if provided
        full_system_prompt = system_prompt
        if context:
            full_system_prompt = f"{context}\n\n{system_prompt}"

        if self.provider == "anthropic":
            return await self._generate_anthropic(
                full_system_prompt, messages, temperature, max_tokens
            )
        elif self.provider == "openai":
            return await self._generate_openai(
                full_system_prompt, messages, temperature, max_tokens
            )
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    async def _generate_anthropic(
        self,
        system_prompt: str,
        messages: List[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate using Anthropic's Claude API."""
        # Wrap synchronous Anthropic client in thread to avoid blocking event loop
        message = await asyncio.to_thread(
            self.anthropic_client.messages.create,
            model=self.config.anthropic_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
        )

        return message.content[0].text

    async def _generate_openai(
        self,
        system_prompt: str,
        messages: List[dict],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate using OpenAI's API."""
        # Prepend system message to messages list
        all_messages = [{"role": "system", "content": system_prompt}] + messages

        response = await self.openai_client.chat.completions.create(
            model=self.config.openai_model,
            messages=all_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content

    async def generate_stream(
        self,
        system_prompt: str,
        messages: List[dict],
        context: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Generate a response from the LLM with streaming.

        Yields chunks of response text as they arrive.

        Args:
            system_prompt: System prompt to guide LLM behavior
            messages: List of message dicts with 'role' and 'content' keys
            context: Additional context to prepend to system prompt

        Yields:
            Chunks of response text
        """
        # Prepend context to system prompt if provided
        full_system_prompt = system_prompt
        if context:
            full_system_prompt = f"{context}\n\n{system_prompt}"

        if self.provider == "anthropic":
            async for chunk in self._generate_stream_anthropic(
                full_system_prompt, messages
            ):
                yield chunk

        elif self.provider == "openai":
            async for chunk in self._generate_stream_openai(
                full_system_prompt, messages
            ):
                yield chunk

    async def _generate_stream_anthropic(
        self,
        system_prompt: str,
        messages: List[dict],
    ) -> AsyncGenerator[str, None]:
        """Stream generate using Anthropic's Claude API."""
        import queue
        import threading

        q: queue.Queue = queue.Queue()

        def _run_stream():
            try:
                with self.anthropic_client.messages.stream(
                    model=self.config.anthropic_model,
                    max_tokens=1500,
                    system=system_prompt,
                    messages=messages,
                ) as stream:
                    for text in stream.text_stream:
                        q.put(text)
            finally:
                q.put(None)  # sentinel

        thread = threading.Thread(target=_run_stream, daemon=True)
        thread.start()

        while True:
            chunk = await asyncio.to_thread(q.get)
            if chunk is None:
                break
            yield chunk

    async def _generate_stream_openai(
        self,
        system_prompt: str,
        messages: List[dict],
    ) -> AsyncGenerator[str, None]:
        """Stream generate using OpenAI's API."""
        # Prepend system message
        all_messages = [{"role": "system", "content": system_prompt}] + messages

        async with await self.openai_client.chat.completions.create(
            model=self.config.openai_model,
            messages=all_messages,
            stream=True,
        ) as response:
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    async def evaluate(
        self, evaluation_prompt: str, response_to_evaluate: str
    ) -> dict:
        """
        Evaluate a response using low temperature for scoring.

        Expects JSON output from the LLM.

        Args:
            evaluation_prompt: Prompt requesting JSON evaluation output
            response_to_evaluate: The response to evaluate

        Returns:
            Parsed JSON dictionary from evaluation
        """
        messages = [
            {
                "role": "user",
                "content": f"{evaluation_prompt}\n\nResponse to evaluate:\n{response_to_evaluate}",
            }
        ]

        response_text = await self.generate(
            system_prompt="You are an evaluation expert. Respond with valid JSON only.",
            messages=messages,
            temperature=0.2,
            max_tokens=1000,
        )

        # Parse JSON from response
        try:
            # Try to extract JSON from response
            response_text = response_text.strip()

            # If response starts with markdown code block, extract content
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            return json.loads(response_text)

        except json.JSONDecodeError:
            # If JSON parsing fails, return error structure
            return {"error": "Failed to parse evaluation response", "raw": response_text}
