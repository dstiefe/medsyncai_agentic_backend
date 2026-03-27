"""
Knowledge Base Q&A API router for MedSync AI Sales Simulation Engine.

Provides a RAG-only chat endpoint where reps ask questions and get answers
grounded exclusively in the document chunk knowledge base (2,243 chunks).

Uses a two-stage hybrid retrieval:
  Stage 1: LLM extracts structured search intent (keywords, trial names, metadata)
  Stage 2: Python keyword/metadata search over all chunks, scored and ranked
  Fallback: vector similarity search supplements if keyword results are sparse
Clinical study answers are restricted to methods/results sections only.
"""

import json
import logging
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..rag.retrieval import VectorRetriever
from ..services.data_loader import DataManager, get_data_manager
from ..services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qa", tags=["knowledge_qa"])


# --- Request / Response Models ---

class QARequest(BaseModel):
    """Request model for a knowledge base question."""
    question: str = Field(..., description="The user's question")
    conversation_history: List[Dict] = Field(
        default_factory=list,
        description="Previous Q&A turns for multi-turn context",
    )
    filters: Optional[Dict] = Field(
        None,
        description="Optional filters: manufacturer, source_type, device_names",
    )
    rep_name: Optional[str] = Field(
        None,
        description="Rep name for personalized responses",
    )
    rep_company: Optional[str] = Field(
        None,
        description="Rep's company (e.g. Penumbra, Stryker) for portfolio-aware responses",
    )
    physician_id: Optional[str] = Field(
        None,
        description="Physician dossier ID for meeting prep context",
    )
    meeting_type: Optional[str] = Field(
        None,
        description="Meeting type: physician_call, sales, inservice, vac, product_review, product_showcase",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "What is the evidence for aspiration thrombectomy in large vessel occlusion?",
                "conversation_history": [],
                "filters": None,
            }
        }


class QASourceChunk(BaseModel):
    """A source chunk used to answer the question."""
    chunk_id: str
    source_type: str
    file_name: str
    manufacturer: str
    section_hint: str
    excerpt: str = Field(..., description="Short excerpt from the chunk")
    score: float


class QAResponse(BaseModel):
    """Response model for a knowledge base answer."""
    answer: str = Field(..., description="The grounded answer")
    sources: List[QASourceChunk] = Field(
        default_factory=list,
        description="Source chunks that informed the answer",
    )
    source_count: int = Field(0, description="Number of sources used")


# --- System prompt for grounded Q&A ---

QA_SYSTEM_PROMPT = """You are MedSync AI Knowledge Assistant — a medical device knowledge base for neurovascular sales representatives.

CRITICAL RULES:
1. Answer ONLY using the provided document context below. Never use outside knowledge.
2. If the context does not contain enough information to answer, say: "I don't have sufficient information in the knowledge base to answer that question. Try rephrasing or ask about a specific device or topic."
3. For clinical study questions: Only cite findings from METHODS and RESULTS sections. Do NOT reference abstracts, discussion sections, or conclusions. Present data as reported (sample sizes, percentages, p-values, outcomes).
4. Always cite your sources by file name so the rep can look them up.
5. Be specific — include device names, specifications, numbers, and data points from the sources.
6. Go A MILE DEEP — provide exhaustive, thorough analysis. Include ALL relevant specs, ALL relevant IFU language, ALL head-to-head comparisons between devices. When comparing devices, create a full spec-by-spec comparison table. Never skim the surface — the rep needs every data point to win.
7. If multiple sources provide conflicting data, present both and note the discrepancy.
8. Format answers using markdown: use **bold** for emphasis, ## for section headers, - for bullet lists, and numbered lists where appropriate. Make responses well-structured and scannable.

FOLLOW-UP DEEP DIVE TOPICS (MANDATORY):
At the END of every response, include a section called "## Dive Deeper" with 3-5 clickable follow-up topics formatted as a numbered list. Each topic should be a specific, actionable question the rep can ask next to go deeper on a related area. Format each as a complete question the rep would ask. For example:
1. What are the exact IFU contraindications for the Raptor Aspiration Catheter?
2. How does the Revere compare to Penumbra Neuron MAX on trackability specs?
3. Are there any MAUDE adverse events reported for the Stellar Guide Catheter?
These MUST be grounded in topics you have data for in the knowledge base. Never suggest topics you cannot answer.

VERBATIM SOURCE DATA RULES (MANDATORY):
9. IFU data and device specifications must be quoted VERBATIM — word for word, exactly as written in the source. IFUs are legal documents. NEVER paraphrase, reword, or summarize IFU text. Present the exact text from the source.
10. NEVER round numbers. All values must appear exactly as stated in the source document. For example, "0.017 inches" must remain "0.017 inches" — never "~0.02 inches" or "approximately 0.02 inches." This applies to all specifications, dimensions, pressures, flow rates, and any numerical data.
11. 510(k) data, Recall notices, MAUDE adverse event reports, and clinical article methods/results must also be presented VERBATIM — quote the exact text from the source. You may add a brief summary ONLY in a clearly labeled "Summary:" section AFTER the verbatim text, never as a replacement for it.
12. Marketing materials and webpage content are the ONLY source types that may be freely summarized or paraphrased in your response.
13. When presenting verbatim content, label it clearly with the source file name so the rep knows it is an exact quote from the original document.

DEVICE-TO-MANUFACTURER REFERENCE (use this to correctly identify which company makes which device):
- **Penumbra**: JET 7, JET 7 MAX, ENGINE, RED 62, RED 72, Neuron MAX, Velocity, ACE 60, ACE 64, ACE 68, BENCHMARK, 3D Separator, Lightning series
- **Stryker**: Trevo XP ProVue, Trevo NXT ProVue, AXS Vecta 71, AXS Vecta 74, AXS Catalyst 6, AXS Catalyst 7, AXS Universal, FlowGate2, Excelsior SL-10, Synchro-2, Synchro SELECT, Target series, Dash Hydrophilic Sheath, Catalyst 7, Lift, Infinity Plus, Surpass Evolve, Surpass Elite, Neuroform Atlas
- **Medtronic**: Solitaire X, Solitaire 2, React 68, React 71, Rebar 18/27, Phenom 21/27, Rist, Navigate catheter system, Marksman, Echelon
- **MicroVention (Terumo)**: SOFIA, SOFIA Plus, SOFIA Flow Plus, Embotrap II/III, Neuronet, Luna AES, FRED, AZUR
- **Cerenovus (J&J)**: EmboTrap, Bravo, Revive SE
- **Balt**: Raptor Aspiration Catheter, Revere Hybrid Access Catheter, Stellar Guide Catheter, MEGA Ballast Access Sheath, Eclipse 2L Dual Lumen Balloon Catheter, MAGIC Flow-Dependent Microcatheter, Rist Selective Catheter, Carrier Delivery Catheter, Carrier XL Delivery Catheter
- **Wallaby / phenox**: Esperance Aspiration Catheter, Tigertriever, Catch+, pREset, pEGASUS
- **Q'apel Medical**: WALRUS Balloon Guide Catheter
- **Route 92 Medical**: Tenzing 7, Tenzing 8
When the user mentions ANY device above, you MUST correctly attribute it to the right manufacturer. NEVER confuse Stryker products with Penumbra products or vice versa. In particular, Vecta and Trevo are STRYKER products, NOT Penumbra.

You are grounded in a knowledge base of:
- Device IFU documents (indications, contraindications, warnings, specifications) — VERBATIM ONLY
- 510(k) submissions — VERBATIM ONLY
- Recall notices — VERBATIM ONLY
- MAUDE adverse event reports — VERBATIM ONLY
- Clinical trial data (methods and results sections) — VERBATIM ONLY
- Competitive intelligence and marketing claims — may be summarized
- Press releases and product announcements — may be summarized
"""


# --- Intent extraction prompt ---

INTENT_EXTRACTION_PROMPT = """You are a search query analyzer for a medical device knowledge base containing document chunks about neurovascular thrombectomy devices.

Given the user's question, extract structured search parameters to find relevant chunks. Output ONLY a JSON object — no explanation, no markdown fences.

The knowledge base contains chunks with these fields:
- text: the chunk content
- file_name: source file name (e.g., "DAWN_Trial_6_to_24_hour_Methods_Results.txt", "ACE_68_IFU_Contraindications.txt")
- source_type: one of "clinical_trial", "ifu", "competitive_intel", "adverse_event", "press_release"
- manufacturer: e.g., "Penumbra", "Medtronic", "Stryker", "MicroVention"
- section_hint: e.g., "methods_results", "contraindications", "indications", "warnings", "specifications"
- device_names: list of device names in the chunk

Output this JSON:
{
  "search_terms": ["keyword1", "keyword2"],
  "trial_names": ["DAWN", "DEFUSE-3"],
  "device_names": ["ACE 68", "Solitaire X"],
  "manufacturers": ["Penumbra"],
  "source_types": ["clinical_trial", "ifu"],
  "section_hints": ["methods_results"],
  "file_name_keywords": ["DAWN", "6_to_24"]
}

Rules:
- search_terms: important medical/technical terms from the question
- trial_names: any specific trial or study names mentioned or implied (e.g., "EVT 6-24 hours" implies DAWN and DEFUSE-3)
- device_names: specific devices mentioned or implied
- manufacturers: companies mentioned or implied
- source_types: which document types are most relevant
- section_hints: which sections to prioritize
- file_name_keywords: terms likely to appear in file names
- Include empty arrays [] for fields with no matches
- Be generous with trial_names — if the question implies a well-known trial, include it"""


async def _extract_search_intent(question: str, llm_service: LLMService) -> dict:
    """Use LLM to extract structured search parameters from a question."""
    try:
        response = await llm_service.generate(
            system_prompt=INTENT_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": question}],
            temperature=0,
            max_tokens=500,
        )

        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        intent = json.loads(text)
        logger.info(f"Extracted search intent: {json.dumps(intent, indent=2)}")
        return intent

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Intent extraction failed: {e}. Falling back to basic keywords.")
        # Fallback: extract simple keywords from question
        words = question.lower().split()
        stop_words = {"what", "is", "the", "a", "an", "to", "for", "of", "in", "and", "or", "how", "does", "do", "can", "with", "about", "are", "from", "this", "that", "it", "be", "was", "were"}
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return {
            "search_terms": keywords,
            "trial_names": [],
            "device_names": [],
            "manufacturers": [],
            "source_types": [],
            "section_hints": [],
            "file_name_keywords": keywords[:3],
        }


def _hybrid_search(intent: dict, chunks: list, max_results: int = 15) -> list:
    """
    Search chunks using keyword matching, file name matching, and metadata filters.

    Scoring:
      +3 for file_name_keywords match in chunk's file_name
      +2 for trial_name found in chunk text
      +1 for search_term found in chunk text
      +1 for source_type match
      +1 for manufacturer match
      +1 for section_hint match
      +1 for device_name match

    Returns list of (chunk, score) tuples sorted by score descending.
    """
    search_terms = [t.lower() for t in intent.get("search_terms", [])]
    trial_names = [t.lower() for t in intent.get("trial_names", [])]
    device_names = [d.lower() for d in intent.get("device_names", [])]
    manufacturers = [m.lower() for m in intent.get("manufacturers", [])]
    source_types = [s.lower() for s in intent.get("source_types", [])]
    section_hints = [s.lower() for s in intent.get("section_hints", [])]
    file_name_keywords = [k.lower() for k in intent.get("file_name_keywords", [])]

    scored_chunks = []

    for chunk in chunks:
        score = 0
        chunk_text = (chunk.get("text", "") or "").lower()
        chunk_file = (chunk.get("file_name", "") or "").lower()
        chunk_source = (chunk.get("source_type", "") or "").lower()
        chunk_mfr = (chunk.get("manufacturer", "") or "").lower()
        chunk_section = (chunk.get("section_hint", "") or "").lower()
        chunk_devices = [d.lower() for d in (chunk.get("device_names", []) or [])]

        # File name keyword match (+3 each)
        for kw in file_name_keywords:
            if kw in chunk_file:
                score += 3

        # Trial name in text (+2 each)
        for trial in trial_names:
            if trial in chunk_text:
                score += 2

        # Search term in text (+1 each)
        for term in search_terms:
            if term in chunk_text:
                score += 1

        # Source type match (+1)
        if source_types and chunk_source in source_types:
            score += 1

        # Manufacturer match (+1)
        if manufacturers and chunk_mfr in manufacturers:
            score += 1

        # Section hint match (+1)
        if section_hints and chunk_section in section_hints:
            score += 1

        # Device name match (+1 each)
        for dev in device_names:
            if dev in chunk_devices or any(dev in cd for cd in chunk_devices):
                score += 1
            # Also check in text
            elif dev in chunk_text:
                score += 1

        if score > 0:
            scored_chunks.append((chunk, score))

    # Sort by score descending
    scored_chunks.sort(key=lambda x: x[1], reverse=True)

    return scored_chunks[:max_results]


# --- Meeting type prompt overlays ---

MEETING_TYPE_PROMPTS = {
    "physician_call": (
        "This is preparation for a physician sales call. Focus on:\n"
        "- The physician's current device preferences and potential switching triggers\n"
        "- Specific objections this physician is likely to raise and evidence-based rebuttals\n"
        "- Talking points that align with the physician's clinical priorities and decision style\n"
        "- Competitive positioning against devices currently in the physician's stack"
    ),
    "sales": (
        "This is preparation for a general sales meeting. Focus on:\n"
        "- Value propositions and competitive differentiators\n"
        "- Clinical evidence that supports product superiority\n"
        "- Pricing and cost-effectiveness arguments\n"
        "- Closing strategies and next steps"
    ),
    "inservice": (
        "This is preparation for a device inservice/training session. Focus on:\n"
        "- Step-by-step device setup and procedure workflow\n"
        "- Key IFU requirements, indications, and contraindications\n"
        "- Common technical questions staff will ask\n"
        "- Tips for smooth device adoption and troubleshooting"
    ),
    "vac": (
        "This is preparation for a Value Analysis Committee (VAC) presentation. Focus on:\n"
        "- Cost-effectiveness data and total procedure cost comparisons\n"
        "- Clinical outcomes and safety data from trials\n"
        "- Formulary and contract considerations\n"
        "- ROI arguments and institutional benefit analysis"
    ),
    "product_review": (
        "This is preparation for a new product review meeting. Focus on:\n"
        "- Detailed device specifications and comparative advantages\n"
        "- Regulatory status (510(k), FDA clearance details)\n"
        "- Clinical trial data supporting the product\n"
        "- How the product addresses unmet clinical needs"
    ),
    "product_showcase": (
        "This is preparation for a new product showcase/demo. Focus on:\n"
        "- Key differentiators that make this product stand out\n"
        "- Demonstration talking points and visual selling points\n"
        "- Head-to-head competitive positioning\n"
        "- Early adopter feedback and clinical case highlights"
    ),
}


@router.post("/ask")
async def ask_question(
    request: QARequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> QAResponse:
    """
    Answer a question using only the document knowledge base.

    Two-stage hybrid retrieval:
      1. LLM extracts search intent (keywords, trial names, metadata)
      2. Python keyword/metadata search over all chunks
      3. Fallback: vector search supplements if results are sparse
    Then generates a grounded answer using the LLM.
    """
    try:
        config = get_settings()
        llm_service = LLMService(config)

        question = request.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question cannot be empty")

        # --- Stage 1: LLM Intent Extraction ---
        intent = await _extract_search_intent(question, llm_service)

        # --- Stage 2: Hybrid Keyword/Metadata Search ---
        all_chunks = data_mgr.document_chunks
        hybrid_results = _hybrid_search(intent, all_chunks, max_results=15)

        logger.info(
            f"Hybrid search returned {len(hybrid_results)} results for: {question[:80]}"
        )

        # --- Fallback: Vector search if hybrid results are sparse ---
        if len(hybrid_results) < 5:
            logger.info("Hybrid results sparse, supplementing with vector search")
            retriever = VectorRetriever(data_mgr, model_name=config.embedding_model)
            vector_results = retriever.retrieve(
                question,
                k=10,
                filters=request.filters or None,
            )

            # Merge: add vector results not already in hybrid results
            hybrid_chunk_texts = {
                (c.get("file_name", ""), c.get("text", "")[:100])
                for c, _ in hybrid_results
            }
            for vr in vector_results:
                key = (vr.file_name, vr.text[:100])
                if key not in hybrid_chunk_texts:
                    # Convert VectorRetriever result to chunk dict format
                    hybrid_results.append((
                        {
                            "chunk_id": vr.chunk_id,
                            "text": vr.text,
                            "file_name": vr.file_name,
                            "source_type": vr.source_type,
                            "manufacturer": vr.manufacturer,
                            "section_hint": vr.section_hint,
                            "device_names": [],
                        },
                        0.5,  # Lower score for vector-only results
                    ))
                    hybrid_chunk_texts.add(key)

            # Re-sort and limit
            hybrid_results.sort(key=lambda x: x[1], reverse=True)
            hybrid_results = hybrid_results[:15]

        if not hybrid_results:
            return QAResponse(
                answer="I couldn't find any relevant information in the knowledge base for your question. Try asking about a specific device, manufacturer, clinical trial, or IFU topic.",
                sources=[],
                source_count=0,
            )

        # --- Build context for LLM ---
        # Source types that MUST be quoted verbatim (regulatory/clinical)
        VERBATIM_SOURCE_TYPES = {"ifu", "510k", "recall", "adverse_event", "clinical_trial"}

        context_parts = []
        for i, (chunk, score) in enumerate(hybrid_results):
            source_type_raw = (chunk.get("source_type", "") or "unknown").lower()
            source_type = source_type_raw.upper()
            section = chunk.get("section_hint", "")
            section_str = f" | Section: {section}" if section else ""
            mfr = chunk.get("manufacturer", "")
            mfr_str = f" | Manufacturer: {mfr}" if mfr else ""
            file_name = chunk.get("file_name", "unknown")
            text = chunk.get("text", "")

            # Tag verbatim-required sources so the LLM knows the rule applies
            if source_type_raw in VERBATIM_SOURCE_TYPES:
                handling = "VERBATIM REQUIRED — quote this text exactly, do not paraphrase or round any numbers"
            else:
                handling = "May be summarized or paraphrased"

            context_parts.append(
                f"[SOURCE {i+1}: {source_type}{section_str}{mfr_str} | Relevance: {score}]\n"
                f"File: {file_name}\n"
                f"Handling: {handling}\n"
                f"{text[:1200]}"
            )

        context_block = "\n\n---\n\n".join(context_parts)

        # --- Build messages ---
        messages = []

        # Add conversation history
        for turn in request.conversation_history[-6:]:
            messages.append({"role": turn.get("role", "user"), "content": turn.get("content", "")})

        # Add current question
        messages.append({"role": "user", "content": question})

        # --- Build system prompt with optional personalization ---
        system_prompt = QA_SYSTEM_PROMPT
        if request.rep_name or request.rep_company:
            name_part = request.rep_name or "a rep"
            company_part = f" from {request.rep_company}" if request.rep_company else ""
            portfolio_note = ""
            if request.rep_company:
                portfolio_note = f"""

CRITICAL PORTFOLIO & COMPETITIVE RESPONSE RULES:
{name_part} works for {request.rep_company}. When they say "our devices", "my catheters", "our portfolio", or "my products", they ALWAYS mean {request.rep_company} devices. Never ask which company they represent — you already know.

When the user asks about their products or asks for comparisons, you MUST:

1. **IDENTIFY ALL RELEVANT PRODUCTS** — Search the knowledge base for ALL {request.rep_company} devices that relate to the clinical scenario or comparison. List them by name with key specs. Do not ask the user which products to include — include all relevant ones from the knowledge base.

2. **LEAD WITH {request.rep_company} STRENGTHS** — Start the response by highlighting where {request.rep_company} products excel. Use specific data: dimensions, specs, clinical evidence, IFU indications, compatibility advantages. Be enthusiastic but factual.

3. **HONESTLY ADDRESS WEAKNESSES** — After presenting strengths, gently and honestly note any areas where the competitor product may have an advantage. Use phrases like "One area where [competitor] has an edge is..." Be transparent — reps need to know this before the physician brings it up.

4. **PROVIDE REBUTTALS AND SOLUTIONS** — For EVERY weakness identified, immediately follow with:
   - A rebuttal or counter-argument if one exists in the data
   - A talking point that reframes the weakness
   - A clinical workflow solution that mitigates the concern
   - Evidence from the knowledge base that supports {request.rep_company}'s position

5. **END WITH COMPETITIVE POSITIONING** — Conclude with a concise summary of the strongest 2-3 talking points for the meeting. Frame these as ready-to-use statements the rep can deliver to the physician.

6. **DO NOT UPSELL WITHIN THE REP'S OWN PORTFOLIO** — Never suggest the physician switch from one {request.rep_company} product to another {request.rep_company} product. If the physician already uses {request.rep_company} devices, your job is to DEFEND that choice against competitor alternatives — not to pitch upgrades within the same company. Reinforce why the physician's current {request.rep_company} device is strong. Only discuss other {request.rep_company} products if the rep explicitly asks about them or if the question is specifically about portfolio breadth.

7. **COMPETITIVE FOCUS** — The primary purpose is always to position {request.rep_company} products favorably AGAINST competitor companies (Stryker, Medtronic, MicroVention, etc.). Comparisons should be {request.rep_company} vs. competitors, not {request.rep_company} vs. {request.rep_company}.

NEVER ask clarifying questions about which {request.rep_company} products to include — always search the knowledge base and include all relevant ones. The rep expects you to know their full portfolio."""
            system_prompt = f"You are helping {name_part}{company_part}, a neurovascular sales representative. Address them by name occasionally.{portfolio_note}\n\n{system_prompt}"

        # --- Inject physician dossier context for meeting prep ---
        if request.physician_id:
            try:
                from ..services.dossier_service import get_dossier_service
                dossier_svc = get_dossier_service()
                dossier_summary = dossier_svc.get_prompt_summary(request.physician_id)
                if dossier_summary:
                    system_prompt += f"""

=== PHYSICIAN DOSSIER (Meeting Prep Context) ===
The sales rep is preparing for a meeting with this physician. Use this dossier to ground your answers
in the physician's specific profile, device preferences, clinical priorities, and known objection patterns.
When relevant, connect knowledge base evidence to this physician's specific situation.

{dossier_summary}

=== END PHYSICIAN DOSSIER ==="""
            except Exception as e:
                logger.warning(f"Failed to load dossier for {request.physician_id}: {e}")

        # --- Inject meeting type focus ---
        if request.meeting_type:
            meeting_focus = MEETING_TYPE_PROMPTS.get(request.meeting_type, "")
            if meeting_focus:
                system_prompt += f"\n\n=== MEETING TYPE FOCUS ===\n{meeting_focus}\n=== END MEETING TYPE FOCUS ==="

        # --- Generate answer ---
        full_system = f"{system_prompt}\n\n=== DOCUMENT CONTEXT ===\n\n{context_block}"

        answer = await llm_service.generate(
            system_prompt=full_system,
            messages=messages,
            temperature=0.3,
            max_tokens=4000,
        )

        # --- Build source list ---
        sources = []
        for chunk, score in hybrid_results:
            chunk_id = chunk.get("chunk_id", chunk.get("file_name", "unknown"))
            sources.append(QASourceChunk(
                chunk_id=chunk_id,
                source_type=chunk.get("source_type", ""),
                file_name=chunk.get("file_name", ""),
                manufacturer=chunk.get("manufacturer", ""),
                section_hint=chunk.get("section_hint", ""),
                excerpt=(chunk.get("text", "")[:150].strip() + "..."),
                score=round(float(score), 4),
            ))

        return QAResponse(
            answer=answer,
            sources=sources,
            source_count=len(sources),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing Q&A question")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing question: {str(e)}",
        )


@router.get("/stats")
async def get_knowledge_base_stats(
    data_mgr: DataManager = Depends(get_data_manager),
) -> Dict:
    """
    Get knowledge base statistics for the Q&A interface.

    Returns chunk counts by source type, manufacturers covered, etc.
    """
    try:
        chunks = data_mgr.document_chunks

        # Count by source_type
        source_counts = {}
        manufacturer_set = set()
        section_counts = {}

        for chunk in chunks:
            st = chunk.get("source_type", "unknown")
            source_counts[st] = source_counts.get(st, 0) + 1

            mfr = chunk.get("manufacturer", "")
            if mfr:
                manufacturer_set.add(mfr)

            sh = chunk.get("section_hint", "")
            if sh:
                section_counts[sh] = section_counts.get(sh, 0) + 1

        return {
            "total_chunks": len(chunks),
            "source_types": source_counts,
            "manufacturers": sorted(manufacturer_set),
            "section_types": section_counts,
            "total_devices": len(data_mgr.devices),
        }

    except Exception as e:
        logger.exception("Error getting KB stats")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting stats: {str(e)}",
        )


# --- Feedback Models ---

class FeedbackRequest(BaseModel):
    """Request model for rating a Q&A answer."""
    question: str
    answer: str
    rating: str = Field(..., description="'up' or 'down'")
    sources: List[Dict] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    """Response model for feedback submission."""
    status: str = Field(..., description="'received' or 'validated'")
    validation: Optional[Dict] = None


def _validate_answer(answer: str, data_mgr: DataManager) -> Dict:
    """
    Validate an answer against the device knowledge base.

    Checks:
    1. Device-to-manufacturer attribution
    2. Specifications (OD, ID, lengths) accuracy
    3. Indication language against IFU chunks
    """
    answer_lower = answer.lower()

    devices_checked = []
    specs_checked = []
    issues_found = []

    # Build a lookup of device names -> Device objects
    device_lookup = {}  # lowercase name -> Device
    for dev in data_mgr.devices.values():
        # Index by product_name, device_name, and aliases
        device_lookup[dev.product_name.lower()] = dev
        device_lookup[dev.device_name.lower()] = dev
        for alias in dev.aliases:
            device_lookup[alias.lower()] = dev

    # Sort by name length descending to match longer names first
    sorted_names = sorted(device_lookup.keys(), key=len, reverse=True)

    # Track which devices we've already checked to avoid duplicates
    checked_device_ids = set()

    for name in sorted_names:
        if name in answer_lower and device_lookup[name].id not in checked_device_ids:
            dev = device_lookup[name]
            checked_device_ids.add(dev.id)

            # --- Check manufacturer attribution ---
            # Look for manufacturer claims near the device mention
            actual_mfr = dev.manufacturer
            # Check if any manufacturer name is associated with this device in the answer
            known_manufacturers = {
                "penumbra", "stryker", "medtronic", "microvention", "terumo",
                "cerenovus", "j&j", "balt", "wallaby", "phenox", "q'apel",
                "route 92", "route 92 medical",
            }
            claimed_mfr = None
            # Search for manufacturer mentions within ~200 chars of the device name
            for mfr_name in known_manufacturers:
                # Find all occurrences of the device name
                idx = answer_lower.find(name)
                while idx != -1:
                    context_start = max(0, idx - 200)
                    context_end = min(len(answer_lower), idx + len(name) + 200)
                    context = answer_lower[context_start:context_end]
                    if mfr_name in context:
                        claimed_mfr = mfr_name.title()
                        break
                    idx = answer_lower.find(name, idx + 1)
                if claimed_mfr:
                    break

            if claimed_mfr:
                # Normalize for comparison
                actual_norm = actual_mfr.lower()
                claimed_norm = claimed_mfr.lower()
                # Handle "MicroVention (Terumo)" style
                is_correct = (
                    claimed_norm == actual_norm
                    or claimed_norm in actual_norm.lower()
                    or actual_norm in claimed_norm.lower()
                )
                devices_checked.append({
                    "device_name": dev.product_name,
                    "manufacturer_claimed": claimed_mfr,
                    "manufacturer_actual": actual_mfr,
                    "correct": is_correct,
                })
                if not is_correct:
                    issues_found.append(
                        f"{dev.product_name} attributed to {claimed_mfr} but actual manufacturer is {actual_mfr}"
                    )

            # --- Check specifications ---
            specs = dev.specifications

            # Check inner diameter (ID)
            if specs.inner_diameter:
                for unit_name, unit_label in [("inches", '"'), ("mm", "mm"), ("french", "Fr")]:
                    val = getattr(specs.inner_diameter, unit_name, None)
                    if val is not None:
                        val_str = str(val)
                        # Search for spec mentions in the answer
                        # Look for patterns like "0.071"" or "ID of 0.071"
                        if val_str in answer:
                            specs_checked.append({
                                "device_name": dev.product_name,
                                "spec": f"ID ({unit_label})",
                                "value_claimed": f"{val_str}{unit_label}",
                                "value_actual": f"{val_str}{unit_label}",
                                "correct": True,
                            })

            # Check outer diameter distal (OD)
            if specs.outer_diameter_distal:
                for unit_name, unit_label in [("inches", '"'), ("mm", "mm"), ("french", "Fr")]:
                    val = getattr(specs.outer_diameter_distal, unit_name, None)
                    if val is not None:
                        val_str = str(val)
                        if val_str in answer:
                            specs_checked.append({
                                "device_name": dev.product_name,
                                "spec": f"OD distal ({unit_label})",
                                "value_claimed": f"{val_str}{unit_label}",
                                "value_actual": f"{val_str}{unit_label}",
                                "correct": True,
                            })

            # Check length
            if specs.length:
                for unit_name, unit_label in [("cm", "cm"), ("mm", "mm")]:
                    val = getattr(specs.length, unit_name, None)
                    if val is not None:
                        val_str = str(val)
                        if val_str in answer:
                            specs_checked.append({
                                "device_name": dev.product_name,
                                "spec": f"Length ({unit_label})",
                                "value_claimed": f"{val_str}{unit_label}",
                                "value_actual": f"{val_str}{unit_label}",
                                "correct": True,
                            })

    # --- Check indication language against IFU chunks ---
    # Look for IFU indication chunks for devices mentioned in the answer
    for dev_id in checked_device_ids:
        dev = data_mgr.devices[dev_id]
        dev_name_lower = dev.product_name.lower()

        # Find IFU indication/contraindication chunks for this device
        ifu_chunks = [
            c for c in data_mgr.document_chunks
            if (c.get("source_type", "") or "").lower() == "ifu"
            and dev_name_lower in (c.get("text", "") or "").lower()
            and (c.get("section_hint", "") or "").lower() in ("indications", "contraindications", "intended_use")
        ]

        if ifu_chunks:
            # Check if the answer contains indication-like language for this device
            indication_phrases = [
                "indicated for", "designed for", "intended for", "cleared for",
                "approved for", "used for the treatment of", "intended use",
            ]
            for phrase in indication_phrases:
                idx = answer_lower.find(phrase)
                if idx != -1:
                    # Check if this device is mentioned nearby
                    context_start = max(0, idx - 150)
                    context_end = min(len(answer_lower), idx + len(phrase) + 200)
                    context = answer_lower[context_start:context_end]

                    if dev_name_lower in context:
                        # Extract the claimed indication text from the answer
                        claim_start = idx
                        claim_end = min(len(answer), idx + 200)
                        # Cut at sentence boundary
                        for end_char in [".", "\n", ";"]:
                            boundary = answer.find(end_char, idx)
                            if boundary != -1 and boundary < claim_end:
                                claim_end = boundary + 1
                                break
                        claimed_text = answer[claim_start:claim_end].strip()

                        # Check if the claimed text matches IFU language
                        claimed_lower = claimed_text.lower()
                        match_found = False
                        for chunk in ifu_chunks:
                            chunk_text = (chunk.get("text", "") or "").lower()
                            # Check if key terms from the claim appear in the IFU
                            claim_terms = [
                                w for w in claimed_lower.split()
                                if len(w) > 3 and w not in {"that", "with", "from", "this", "have", "been", "were", "will", "they", "their", "which", "about"}
                            ]
                            matched_terms = sum(1 for t in claim_terms if t in chunk_text)
                            if claim_terms and matched_terms / len(claim_terms) > 0.5:
                                match_found = True
                                break

                        if not match_found and ifu_chunks:
                            # Report the discrepancy
                            ifu_excerpt = (ifu_chunks[0].get("text", "") or "")[:150].strip()
                            issues_found.append(
                                f"{dev.product_name}: answer claims '{claimed_text[:100]}' but IFU language says: '{ifu_excerpt}...'"
                            )

    return {
        "devices_checked": devices_checked,
        "specs_checked": specs_checked,
        "issues_found": issues_found,
    }


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    data_mgr: DataManager = Depends(get_data_manager),
) -> FeedbackResponse:
    """
    Submit feedback (thumbs-up/down) for a Q&A answer.

    On thumbs-down, automatically validates the answer against the device
    knowledge base checking manufacturer attribution, specs, and IFU language.
    """
    try:
        if request.rating not in ("up", "down"):
            raise HTTPException(status_code=400, detail="Rating must be 'up' or 'down'")

        logger.info(
            f"Feedback received: rating={request.rating}, "
            f"question={request.question[:80]}..."
        )

        if request.rating == "up":
            return FeedbackResponse(status="received")

        # Thumbs-down: run validation pipeline
        validation = _validate_answer(request.answer, data_mgr)

        logger.info(
            f"Validation complete: {len(validation['devices_checked'])} devices, "
            f"{len(validation['specs_checked'])} specs, "
            f"{len(validation['issues_found'])} issues"
        )

        return FeedbackResponse(status="validated", validation=validation)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing feedback")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing feedback: {str(e)}",
        )
