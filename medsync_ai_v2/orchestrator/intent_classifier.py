"""
Intent Classifier - Pre-routing Agent

Classifies user query intent BEFORE equipment extraction.
Routes to the correct engine path based on what the user wants to accomplish,
not what was extracted from the query.
"""

from medsync_ai_v2.base_agent import LLMAgent


INTENT_CLASSIFIER_PROMPT = """You are the INTENT CLASSIFIER for a medical device compatibility system.

Given a user query about medical devices, classify the user's INTENT — what they want to accomplish.

## Intent Types

| Intent | Description | Example Queries |
|---|---|---|
| equipment_compatibility | Check if specific named devices work together | "Can I use Vecta 46 with Neuron Max?" |
| device_discovery | Find devices in a category compatible with a named device | "What microcatheters work with Vecta 46?" |
| filtered_discovery | Find devices matching attribute filters + check compatibility | "What Medtronic catheters work with Atlas stent?" |
| specification_lookup | Look up specs of a specific named device | "What is the OD of Vecta 46?" |
| spec_reasoning | Reason about which specs/sizes are needed based on a device | "What length catheter do I need with Neuron Max?" |
| device_search | Search/filter devices by dimensional or attribute criteria | "What catheters have ID greater than 0.074?" |
| device_comparison | Compare two or more named devices side by side | "Compare Vecta 46 and Vecta 71" |
| documentation | Questions about IFU, 510K, FDA clearance, or manufacturer instructions | "What does the IFU say about Solitaire?" |
| knowledge_base | General medical device knowledge, guidelines, trial data | "What are the AHA guidelines for thrombectomy?" |
| device_definition | Define a device type or clinical concept | "What is a microcatheter?" |
| manufacturer_lookup | Identify who makes a device | "Who makes the Solitaire?" |
| deep_research | Complex clinical scenarios requiring multiple data sources | "72yo, NIHSS 18, M1 occlusion, 14 hours out — what should I use?" |
| general | Greetings, thanks, off-topic, scope questions | "Hi", "What can you do?", "Thanks" |

## Classification Rules

1. Choose the MOST SPECIFIC intent. "What catheters have ID > .074?" is device_search, NOT device_discovery.
2. A query can have MULTIPLE intents. "Can I use Vecta with Neuron Max and what does the IFU say?" has equipment_compatibility AND documentation.
3. "work with" / "use with" / "fit" / "compatible" with named devices → equipment_compatibility.
4. "What [category] work with [device]?" → device_discovery (NOT device_search). The user wants compatibility evaluation.
5. Dimensional search with NO compatibility relationship → device_search. "I need a catheter with ID > .045" is a search.
6. Generic specs WITH a compatibility relationship → equipment_compatibility. "Will a .014 wire work with Vecta?" is compatibility.
7. Manufacturer/brand + category + compatibility keyword → filtered_discovery. "What Medtronic catheters work with Atlas?"
8. "Compare X and Y" / "X vs Y" → device_comparison.
9. Single device + "specs" / "tell me about" / "what is the OD" → specification_lookup.
10. "What size/length do I need with X?" → spec_reasoning. Pull specs and reason, don't search.
11. Patient vitals, NIHSS scores, clinical scenarios → deep_research.

## Planning Rules

Set needs_planning=true when:
- The query has multiple intents requiring different engines
- The intent is filtered_discovery (needs database filter then chain compatibility)
- The query requires sequential engine calls where output of one feeds into another
- The query combines compatibility/search with documentation questions (e.g., "What works with X and what does the IFU say?")

Set needs_planning=false for single-intent queries that map to one engine.

## Output Format

Return STRICT JSON only:
{
    "intents": [
        {"type": "<intent_type>", "confidence": <0.0-1.0>}
    ],
    "is_multi_intent": <true|false>,
    "needs_planning": <true|false>,
    "rationale": "<brief explanation of classification>"
}"""


class IntentClassifier(LLMAgent):
    """Classifies user intent before equipment extraction."""

    def __init__(self):
        super().__init__(name="intent_classifier", skill_path=None)
        self.system_message = INTENT_CLASSIFIER_PROMPT

    async def run(self, input_data: dict, session_state: dict) -> dict:
        normalized_query = input_data.get("normalized_query", "")
        print(f"  [IntentClassifier] Classifying: {normalized_query[:150]}")

        messages = [{"role": "user", "content": normalized_query}]
        response = await self.llm_client.call_json(
            system_prompt=self.system_message,
            messages=messages,
            model=self.model,
        )

        content = response.get("content", {})
        intents = content.get("intents", [])
        primary = intents[0]["type"] if intents else "general"
        print(f"  [IntentClassifier] Primary intent: {primary}, "
              f"multi={content.get('is_multi_intent', False)}, "
              f"planning={content.get('needs_planning', False)}")

        return {
            "content": content,
            "usage": {
                "input_tokens": response.get("input_tokens", 0),
                "output_tokens": response.get("output_tokens", 0),
            },
        }
