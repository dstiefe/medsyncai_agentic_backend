"""
Synthesis Output Agent

Combines multi-engine results (chain + vector, database + vector, etc.)
into a unified user-facing response. Streams tokens in real-time via broker.
"""

from datetime import datetime, timezone
from medsync_ai_v2.base_agent import LLMAgent


SYNTHESIS_SYSTEM_MESSAGE = """You are a medical device assistant synthesizing information from multiple data sources.

You have been given results from multiple analysis engines. Your job is to combine them into a single, coherent response.

Rules:
- Present information in the order that makes most clinical sense
- For compatibility results: lead with the compatibility analysis, then add documentation context
- For documentation/IFU results: present document content VERBATIM — use the exact wording from the source. Do NOT paraphrase or summarize the document text.
- Organize verbatim document content using bullet points where it improves readability.
- For documentation results: cite sources ("Per the IFU...", "The 510(k) states...")
- If compatibility data and IFU data conflict, note both and flag the discrepancy
- Use markdown formatting (tables for compatibility/device comparisons, bullet points for document content)
- Stay neutral and clinical — no marketing language
- AVOID words like: "popular", "best", "commonly used", "leading", "preferred", "top", "recommended"
- Do not favor any manufacturer over another
- Present all options objectively based on specifications

SCOPE CONTROL:
- Answer ONLY what the user asked. If the user asked about deployment, only include deployment information
- Do NOT include warnings, contraindications, indications, or other IFU sections unless the user specifically asked for them or they directly relate to the asked question
- The document chunks may contain more information than needed — extract only what's relevant to the question, but present that content verbatim (not summarized)
- Match the specificity of the question: a focused question gets a focused answer
- For clinical eligibility results: present the assessment with Class/Level notation, reference guideline sections and trials. Frame as "eligible/not eligible per guidelines" — never recommend treatment.
- If clinical assessment is incomplete due to missing data, note what's missing and present whatever device information is available. Pass through any clinical clarification questions exactly as provided.
""".strip()


class SynthesisOutputAgent(LLMAgent):
    """Combines multi-engine results into a unified response."""

    def __init__(self):
        super().__init__(name="synthesis_output_agent", skill_path=None)

    def _build_user_prompt(self, input_data: dict) -> str:
        """Build prompt from all step results."""
        user_query = input_data.get("user_query", "")
        step_results = input_data.get("step_results", {})
        plan = input_data.get("plan", {})

        sections = [f"User Question: {user_query}\n"]

        for step in plan.get("steps", []):
            store_as = step.get("store_as", step.get("step_id", ""))
            engine = step.get("engine", "")
            result = step_results.get(store_as, {})

            if engine == "chain":
                text_summary = result.get("data", {}).get("text_summary", "")
                if text_summary:
                    sections.append(f"## Compatibility Analysis\n\n{text_summary}")

            elif engine == "database":
                device_list = result.get("data", {}).get("device_list", [])
                if device_list:
                    names = [d.get("product_name", "?") for d in device_list[:20]]
                    sections.append(
                        f"## Database Results\n\n"
                        f"{len(device_list)} devices found: {', '.join(names)}"
                    )

            elif engine == "vector":
                chunks = result.get("data", {}).get("chunks", [])
                if chunks:
                    chunk_texts = []
                    for i, chunk in enumerate(chunks, 1):
                        score = chunk.get("score", 0)
                        attrs = chunk.get("attributes", {})
                        text = chunk.get("text", "")

                        attr_str = ""
                        if attrs:
                            attr_parts = [f"{k}: {v}" for k, v in attrs.items() if v]
                            if attr_parts:
                                attr_str = f" | {', '.join(attr_parts)}"

                        chunk_texts.append(
                            f"[Chunk {i}] (score: {score:.2f}{attr_str})\n{text}"
                        )
                    sections.append(
                        f"## Document Data ({len(chunks)} chunks)\n\n"
                        + "\n\n---\n\n".join(chunk_texts)
                    )

            elif engine == "clinical":
                # Clinical assessment — pass through verbatim when clarification,
                # otherwise format eligibility for the LLM to synthesize
                if result.get("status") == "needs_clarification":
                    clarification_text = result.get("_clarification_text", "")
                    if clarification_text:
                        sections.append(
                            f"## Clinical Assessment\n\n{clarification_text}"
                        )
                    else:
                        cdata = result.get("data", {})
                        missing = cdata.get("completeness", {}).get("missing_critical", [])
                        questions = [m.get("question", m.get("label", "")) for m in missing]
                        sections.append(
                            f"## Clinical Assessment\n\n"
                            "I need a few more details to complete the clinical assessment:\n\n"
                            + "\n".join(f"- {q}" for q in questions)
                        )
                else:
                    cdata = result.get("data", {})
                    patient = cdata.get("patient", {})
                    eligibility = cdata.get("eligibility", [])

                    patient_parts = []
                    if patient.get("age"):
                        patient_parts.append(f"Age: {patient['age']}")
                    if patient.get("nihss") is not None:
                        patient_parts.append(f"NIHSS: {patient['nihss']}")
                    if patient.get("aspects") is not None:
                        patient_parts.append(f"ASPECTS: {patient['aspects']}")
                    if patient.get("occlusion_segment"):
                        patient_parts.append(f"Occlusion: {patient['occlusion_segment']}")
                    if patient.get("mrs_pre") is not None:
                        patient_parts.append(f"Pre-stroke mRS: {patient['mrs_pre']}")
                    if patient.get("last_known_well_hours") is not None:
                        patient_parts.append(f"LKW: {patient['last_known_well_hours']}h")

                    elig_lines = []
                    for e in eligibility:
                        treatment = e.get("treatment", "")
                        status = e.get("eligibility", "")
                        cor = e.get("cor", "")
                        loe = e.get("loe", "")
                        reasoning = e.get("reasoning", "")
                        trials = ", ".join(e.get("relevant_trials", []))
                        section = e.get("guideline_section", "")
                        elig_lines.append(
                            f"- **{treatment}**: {status} "
                            f"(Class {cor}, Level {loe})"
                            f"\n  Reasoning: {reasoning}"
                            + (f"\n  Trials: {trials}" if trials else "")
                            + (f"\n  Guideline Section: {section}" if section else "")
                        )

                    sections.append(
                        f"## Clinical Assessment\n\n"
                        f"Patient: {', '.join(patient_parts)}\n\n"
                        f"### Eligibility\n\n" + "\n\n".join(elig_lines)
                    )

        sections.append(
            "\nSynthesize all the above into a single coherent response."
        )
        return "\n\n".join(sections)

    async def run(self, input_data: dict, session_state: dict, broker=None) -> dict:
        """
        Generate a synthesized response from multi-engine results.

        If broker is provided, streams tokens in real-time as final_chunk SSE events.
        """
        system_message = SYNTHESIS_SYSTEM_MESSAGE
        user_prompt = self._build_user_prompt(input_data)
        messages = [{"role": "user", "content": user_prompt}]

        print(f"  [SynthesisOutputAgent] Synthesizing multi-engine results")

        if broker:
            # Stream tokens in real-time via broker
            final_text = ""
            usage = {"input_tokens": 0, "output_tokens": 0}

            async for chunk in self.llm_client.call_stream(
                system_prompt=system_message,
                messages=messages,
                model=self.model,
                max_tokens=8192,
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
                max_tokens=8192,
            )
            return {
                "content": {"formatted_response": response.get("content", "")},
                "usage": response.get("usage", {}),
            }
