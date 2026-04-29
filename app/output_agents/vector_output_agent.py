"""
Vector Output Agent

Formats vector engine results (IFU/510(k) document chunks) into user-facing
responses.  Streams tokens in real-time via broker.

Ported from vs2/agents/vector_search_agents.py (VectorStoreFormatter).
"""

import json
from datetime import datetime, timezone
from app.base_agent import LLMAgent


VECTOR_SYSTEM_MESSAGE = """You are a medical information assistant.

Your job:
Present information from the provided IFU/510(k) document data to answer the user's question.

Rules:
- Present document content VERBATIM — use the exact wording from the source documents. Do NOT paraphrase or summarize.
- Organize the verbatim content using bullet points where it improves readability (e.g., lists of indications, contraindications, specifications, steps).
- ALWAYS attribute the source based on the document type:
  -> For clinical guidelines (identified by COR/LOE recommendations, trial names like DAWN/DEFUSE-3, section numbers like "4.7.2"): Say "Per the guideline..." or "The 2026 AHA/ASA guidelines state..." or "Per [trial name]..."
  -> For device documentation (IFU, 510(k), DFU): Say "Per the IFU..." or "The 510(k) states..." or "Per the instructions for use..."
- If the document explicitly states something is "None known" or "None" (e.g., contraindications), clearly report that:
  -> Example: "Per the IFU, Contraindications: None known."
- If the information is NOT mentioned or NOT found in the provided data, say:
  -> "No information found in the available IFU/510(k) documentation."
- Never guess or infer — only report what the documents explicitly state.
- Do NOT use your training knowledge about medical devices. Answer strictly from the provided document chunks.
- If vector search returned document chunks, ALWAYS synthesize the available information. Never say "no information found" or "the documents do not contain" when you have retrieved content that addresses the topic—even if it doesn't fully answer the exact question asked.
- If the retrieved content partially addresses the question, present what is available and explicitly state what is missing or not provided.
- When multiple document sources cover the same topic, present each source's exact language with attribution.
- When sources conflict, note both sources and their exact statements.
- Include device specifications (dimensions, materials) when relevant to the question.

## Prognosis and Outcome Questions

When the user asks about expected outcomes, prognosis, recovery, functional independence, or treatment results for a clinical scenario:

DO:
- Present trial-level outcome data from the retrieved chunks: NNT (number needed to treat), functional independence rates, mRS score distributions, mortality differences, odds ratios, confidence intervals
- Name the specific trials (DAWN, DEFUSE-3, HERMES, SELECT, AURORA, etc.) and cite their key findings
- State the Class of Recommendation (COR) and Level of Evidence (LOE) if present
- Frame outcomes in terms of trial populations, not individual patients. Use language like: "In the DAWN trial, 49% of EVT patients achieved functional independence (mRS 0-2) at 90 days compared to 13% in the control group, giving an NNT of 2.8"

DO NOT:
- Say "no information found" when trial outcome data exists in the retrieved chunks
- Provide patient-specific probability predictions (the guideline does not support individualized predictions)
- Claim the documents cannot answer the question when they contain trial-level evidence

ALWAYS end prognosis responses with a clarification:
"These are trial-level outcome estimates from selected study populations. The guideline does not provide individualized outcome predictions for specific patients."
""".strip()

NO_RESULTS_MESSAGE = "No relevant information was found in the available documentation for this query."


class VectorOutputAgent(LLMAgent):
    """Formats vector search chunks into user-facing responses with source attribution."""

    def __init__(self):
        super().__init__(name="vector_output_agent", skill_path=None)

    def _build_user_prompt(self, input_data: dict) -> str:
        """Build the user prompt from vector engine results."""
        user_query = input_data.get("user_query", "")
        data = input_data.get("data", {})
        chunks = data.get("chunks", [])
        device_context = data.get("device_context", {})

        if not chunks:
            return f"User Question: {user_query}\n\nNo document chunks were found. Respond with: \"{NO_RESULTS_MESSAGE}\""

        # Format chunks for the LLM
        chunk_texts = []
        for i, chunk in enumerate(chunks, 1):
            score = chunk.get("score", 0)
            attrs = chunk.get("attributes", {})
            file_id = chunk.get("file_id", "unknown")
            text = chunk.get("text", "")

            attr_str = ""
            if attrs:
                attr_parts = [f"{k}: {v}" for k, v in attrs.items() if v]
                if attr_parts:
                    attr_str = f" | Attributes: {', '.join(attr_parts)}"

            chunk_texts.append(
                f"[Chunk {i}] (score: {score:.2f}, file: {file_id}{attr_str})\n{text}"
            )

        chunks_formatted = "\n\n---\n\n".join(chunk_texts)

        device_str = ""
        if device_context:
            device_names = list(device_context.keys())
            device_str = f"\nDevices referenced: {', '.join(device_names)}"

        return f"""User Question: {user_query}
{device_str}

Document Data ({len(chunks)} chunks):

{chunks_formatted}

Answer the user's question using ONLY the document data above."""

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate the vector output response.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        data = input_data.get("data", {})
        chunks = data.get("chunks", [])

        # No-results fast path
        if not chunks:
            print(f"  [VectorOutputAgent] No chunks — returning no-results message")
            if broker:
                await broker.put({
                    "type": "final_chunk",
                    "data": {
                        "agent": self.name,
                        "content": NO_RESULTS_MESSAGE,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })
            return {
                "content": {"formatted_response": NO_RESULTS_MESSAGE},
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }

        system_message = VECTOR_SYSTEM_MESSAGE
        user_prompt = self._build_user_prompt(input_data)
        messages = [{"role": "user", "content": user_prompt}]

        print(f"  [VectorOutputAgent] Formatting {len(chunks)} chunks (top score: {data.get('top_score', 0):.2f})")

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            ):
                if isinstance(chunk, dict):
                    usage = chunk
                else:
                    final_text += chunk
                    await broker.put({
                        "type": "final_chunk",
                        "data": {
                            "agent": self.name,
                            "content": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

            return {
                "content": {"formatted_response": final_text},
                "usage": usage,
            }
        else:
            # Non-streaming fallback
            response = await self.llm_client.call(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
