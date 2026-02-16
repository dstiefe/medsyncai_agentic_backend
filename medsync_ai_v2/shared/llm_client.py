"""
MedSync AI v2 - LLM Client
Async provider abstraction layer supporting OpenAI and Anthropic.
Ported from v1/llm/client.py with additions for JSON mode.
"""

import json
import os
from medsync_ai_v2 import config

def _llm_debug_enabled():
    return os.getenv("LLM_DEBUG", "").lower() in ("1", "true", "yes")


class LLMClient:

    def __init__(self, provider: str = "openai", model: str = "gpt-4.1"):
        self.provider = provider
        self.model = model

        if provider == "openai":
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        elif provider == "anthropic":
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        else:
            raise ValueError(f"Unknown provider: {provider}")

    @staticmethod
    def _strip_markdown_json(text: str) -> str:
        """Strip markdown code block wrappers from JSON responses."""
        text = text.strip()
        if text.startswith("```"):
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1:]
            if text.endswith("```"):
                text = text[:-3].rstrip()
        return text

    # ---------------------------------------------------------
    # Debug logging helpers
    # ---------------------------------------------------------
    def _debug_log_input(self, method: str, system_prompt: str, messages: list, model: str):
        if not _llm_debug_enabled():
            return
        import sys
        def _safe(text: str) -> str:
            enc = sys.stdout.encoding or "utf-8"
            return text.encode(enc, errors="replace").decode(enc)
        try:
            print(f"\n{'='*70}")
            print(f"[LLM INPUT] method={method}  model={model}")
            print(f"{'='*70}")
            print(f"[SYSTEM PROMPT]\n{_safe(system_prompt)}")
            print(f"\n[MESSAGES] ({len(messages)} messages)")
            for i, msg in enumerate(messages):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = str(content)
                print(f"  [{i}] {role}: {_safe(content)}")
            print(f"{'='*70}\n")
        except UnicodeEncodeError:
            print(f"[LLM INPUT] method={method} model={model} (debug log truncated: encoding error)")

    def _debug_log_output(self, method: str, content, usage: dict = None):
        if not _llm_debug_enabled():
            return
        import sys
        enc = sys.stdout.encoding or "utf-8"
        def _safe(text: str) -> str:
            return text.encode(enc, errors="replace").decode(enc)
        try:
            print(f"\n{'-'*70}")
            print(f"[LLM OUTPUT] method={method}")
            if usage:
                print(f"  tokens: in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}")
            print(f"{'-'*70}")
            if isinstance(content, dict):
                print(_safe(json.dumps(content, indent=2, default=str)[:8000]))
            else:
                print(_safe(str(content)[:8000]))
            print(f"{'-'*70}\n")
        except UnicodeEncodeError:
            print(f"[LLM OUTPUT] method={method} (debug log truncated: encoding error)")

    # ---------------------------------------------------------
    # Tool-calling interface (for orchestrator)
    # ---------------------------------------------------------
    async def call(self, system_prompt: str, messages: list, tools: list = None, model: str = None, max_tokens: int = 4096) -> dict:
        model = model or self.model
        self._debug_log_input("call", system_prompt, messages, model)
        if self.provider == "openai":
            result = await self._call_openai(system_prompt, messages, tools, model, max_tokens)
        elif self.provider == "anthropic":
            result = await self._call_anthropic(system_prompt, messages, tools, model, max_tokens)
        self._debug_log_output("call", result.get("content", result), result.get("usage"))
        return result

    # ---------------------------------------------------------
    # JSON mode (for sub-agents that return structured data)
    # ---------------------------------------------------------
    async def call_json(self, system_prompt: str, messages: list, model: str = None) -> dict:
        model = model or self.model
        self._debug_log_input("call_json", system_prompt, messages, model)
        if self.provider == "openai":
            result = await self._call_openai_json(system_prompt, messages, model)
        elif self.provider == "anthropic":
            result = await self._call_anthropic_json(system_prompt, messages, model)
        self._debug_log_output(
            "call_json", result.get("content", result),
            {"input_tokens": result.get("input_tokens", 0), "output_tokens": result.get("output_tokens", 0)},
        )
        return result

    # ---------------------------------------------------------
    # OpenAI implementations
    # ---------------------------------------------------------
    async def _call_openai(self, system_prompt: str, messages: list, tools: list = None, model: str = None, max_tokens: int = 4096) -> dict:
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        kwargs = {"model": model or self.model, "messages": openai_messages, "max_tokens": max_tokens}
        if tools:
            kwargs["tools"] = self._format_tools_openai(tools)

        response = await self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message

        usage = self._extract_openai_usage(response)

        if message.tool_calls:
            tool_call = message.tool_calls[0]
            return {
                "type": "tool_use",
                "tool_name": tool_call.function.name,
                "tool_input": json.loads(tool_call.function.arguments),
                "tool_use_id": tool_call.id,
                "usage": usage,
                "raw_message": message,
            }
        else:
            return {
                "type": "text",
                "content": message.content,
                "usage": usage,
                "raw_message": message,
            }

    async def _call_openai_json(self, system_prompt: str, messages: list, model: str = None) -> dict:
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        response = await self.client.chat.completions.create(
            model=model or self.model,
            messages=openai_messages,
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        raw_content = response.choices[0].message.content
        usage = self._extract_openai_usage(response)

        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            # Try stripping markdown code blocks
            stripped = self._strip_markdown_json(raw_content)
            try:
                content = json.loads(stripped)
            except json.JSONDecodeError:
                print(f"  [LLM] OpenAI JSON parse failed. Raw: {raw_content[:300]}")
                content = {"raw_text": raw_content}

        return {
            "content": content,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    def _format_tools_openai(self, tools: list) -> list:
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
        } for t in tools]

    def _extract_openai_usage(self, response) -> dict:
        if response.usage:
            return {
                "input_tokens": response.usage.prompt_tokens or 0,
                "output_tokens": response.usage.completion_tokens or 0,
            }
        return {"input_tokens": 0, "output_tokens": 0}

    # ---------------------------------------------------------
    # Anthropic implementations
    # ---------------------------------------------------------
    async def _call_anthropic(self, system_prompt: str, messages: list, tools: list = None, model: str = None, max_tokens: int = 4096) -> dict:
        kwargs = {
            "model": model or self.model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                for t in tools
            ]

        response = await self.client.messages.create(**kwargs)
        usage = self._extract_anthropic_usage(response)

        # Capture text reasoning alongside tool calls
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                return {
                    "type": "tool_use",
                    "tool_name": block.name,
                    "tool_input": block.input,
                    "tool_use_id": block.id,
                    "text": "".join(text_parts),
                    "usage": usage,
                    "raw_message": response,
                }

        text = "".join(text_parts)
        return {"type": "text", "content": text, "usage": usage, "raw_message": response}

    async def _call_anthropic_json(self, system_prompt: str, messages: list, model: str = None) -> dict:
        system_with_json = system_prompt + "\n\nYou MUST respond with valid JSON only. No other text."
        kwargs = {
            "model": model or self.model,
            "system": system_with_json,
            "messages": messages,
            "max_tokens": 4096,
        }

        response = await self.client.messages.create(**kwargs)
        usage = self._extract_anthropic_usage(response)

        text = "".join(block.text for block in response.content if block.type == "text")

        # Strip markdown code blocks (```json ... ```) that Claude sometimes adds
        text = self._strip_markdown_json(text)

        try:
            content = json.loads(text)
        except json.JSONDecodeError:
            print(f"  [LLM] JSON parse failed. Raw text: {text[:300]}")
            content = {"raw_text": text}

        return {
            "content": content,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    def _extract_anthropic_usage(self, response) -> dict:
        if response.usage:
            return {
                "input_tokens": response.usage.input_tokens or 0,
                "output_tokens": response.usage.output_tokens or 0,
            }
        return {"input_tokens": 0, "output_tokens": 0}

    # ---------------------------------------------------------
    # Streaming text (for output agents)
    # ---------------------------------------------------------
    async def call_stream(self, system_prompt: str, messages: list, model: str = None, max_tokens: int = 4096):
        """
        Async generator that yields text chunks, then a usage dict.

        Yields:
            str: Text chunks as they arrive
            dict: {"type": "usage", "input_tokens": N, "output_tokens": N} at the end
        """
        model = model or self.model
        self._debug_log_input("call_stream", system_prompt, messages, model)

        full_text = ""
        if self.provider == "openai":
            gen = self._stream_openai(system_prompt, messages, model, max_tokens)
        elif self.provider == "anthropic":
            gen = self._stream_anthropic(system_prompt, messages, model, max_tokens)

        async for chunk in gen:
            if isinstance(chunk, dict):
                self._debug_log_output("call_stream", full_text, chunk)
                yield chunk
            else:
                full_text += chunk
                yield chunk

    async def _stream_openai(self, system_prompt: str, messages: list, model: str, max_tokens: int = 4096):
        print(f"  [LLM] OpenAI stream: model={model}, max_tokens={max_tokens}")
        openai_messages = [{"role": "system", "content": system_prompt}]
        openai_messages.extend(messages)

        stream = await self.client.chat.completions.create(
            model=model,
            messages=openai_messages,
            temperature=0.0,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )

        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
                fr = chunk.choices[0].finish_reason
                if fr:
                    print(f"  [LLM] OpenAI stream finish_reason={fr}")
            if chunk.usage:
                yield {
                    "type": "usage",
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                }

    async def _stream_anthropic(self, system_prompt: str, messages: list, model: str, max_tokens: int = 4096):
        print(f"  [LLM] Anthropic stream: model={model}, max_tokens={max_tokens}")
        async with self.client.messages.stream(
            model=model,
            system=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        ) as stream:
            async for text in stream.text_stream:
                yield text
            message = await stream.get_final_message()
            print(f"  [LLM] Anthropic stream stop_reason={message.stop_reason}")
            yield {
                "type": "usage",
                "input_tokens": message.usage.input_tokens or 0,
                "output_tokens": message.usage.output_tokens or 0,
            }

    # ---------------------------------------------------------
    # Tool result formatting (provider-specific)
    # ---------------------------------------------------------
    def format_tool_result(
        self,
        tool_use_id: str,
        tool_name: str,
        result: str,
        tool_input: dict = None,
        assistant_text: str = None,
    ) -> list:
        tool_input = tool_input or {}

        if self.provider == "openai":
            return [
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": tool_use_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(tool_input)}
                    }]
                },
                {"role": "tool", "tool_call_id": tool_use_id, "content": result}
            ]
        elif self.provider == "anthropic":
            assistant_content = []
            if assistant_text:
                assistant_content.append({"type": "text", "text": assistant_text})
            assistant_content.append({
                "type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_input
            })
            return [
                {"role": "assistant", "content": assistant_content},
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}]
                }
            ]


# Module-level registry — one client per provider
_client_registry: dict[str, LLMClient] = {}


def get_llm_client(provider: str = None, model: str = None) -> LLMClient:
    """
    Get (or create) an LLM client for the given provider.

    Clients are cached per provider so both OpenAI and Anthropic
    can be active simultaneously.

    Args:
        provider: "openai" or "anthropic". Defaults to config.LLM_PROVIDER.
        model: Model name. Defaults to the provider's default model.

    Returns:
        LLMClient instance for the requested provider.
    """
    provider = provider or config.LLM_PROVIDER or "openai"
    model = model or config.DEFAULT_MODELS.get(provider, config.DEFAULT_MODEL)

    if provider not in _client_registry:
        _client_registry[provider] = LLMClient(provider=provider, model=model)

    return _client_registry[provider]
