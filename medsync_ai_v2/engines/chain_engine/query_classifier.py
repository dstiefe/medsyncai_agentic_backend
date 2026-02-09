"""
Chain Engine - Query Classifier

LLM-based agent that classifies compatibility queries into:
- query_mode: exploratory | discovery | comparison | specific | stack_validation
- response_framing: positive | negative | neutral
- query_structure: two_device | multi_device | named_plus_category | single_device | category_only
"""

import json
from medsync_ai_v2.base_agent import LLMAgent


CLASSIFIER_SYSTEM_PROMPT = """You are a medical device query classifier. Given a user query and extracted device information, classify the query along three dimensions.

## Classification Schema

### query_mode — what is the user trying to accomplish?
- "exploratory": Open-ended, "what works with", "what can I use", wants options
- "specific": Named devices, yes/no question, "can I use X with Y"
- "comparison": "X or Y", "which is better", comparing options
- "discovery": Wants to find devices in a category that work with a named device
- "stack_validation": 3+ named devices, full setup check

### response_framing — what tone does the user expect?
- "positive": User expects/hopes it works ("Can I use X with Y?", hopeful tone)
- "negative": User expects it won't work ("I don't think X works with Y", skeptical)
- "neutral": No expectation either way ("Check if X works with Y", "List...")

### query_structure — what shape does the input take?
- "two_device": Exactly 2 named devices, no categories
- "multi_device": 3+ named devices
- "named_plus_category": At least 1 named device + at least 1 category mention
- "single_device": 1 named device, asking about its specs or what works with it
- "category_only": Only category mentions, no named devices

## Response Format
Return valid JSON only:
{
    "query_mode": "exploratory|specific|comparison|discovery|stack_validation",
    "framing": "positive|negative|neutral",
    "structure": "two_device|multi_device|named_plus_category|single_device|category_only",
    "sub_type": "COMPATIBILITY_CHECK|DEVICE_DISCOVERY|STACK_VALIDATION|SPEC_LOOKUP",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation of classification"
}"""


class QueryClassifier(LLMAgent):
    """Classifies compatibility queries into mode, framing, and structure."""

    def __init__(self):
        super().__init__(
            name="query_classifier",
            skill_path=None,
            model=None,
        )
        self.system_message = CLASSIFIER_SYSTEM_PROMPT

    async def run(self, input_data: dict, session_state: dict) -> dict:
        user_prompt = json.dumps({
            "user_query": input_data.get("normalized_query", ""),
            "devices": input_data.get("devices", {}),
            "categories": input_data.get("categories", []),
        })

        messages = [{"role": "user", "content": user_prompt}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        return {
            "content": content,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
