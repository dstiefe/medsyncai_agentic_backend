# ─── v4 (Q&A v4 namespace) ─────────────────────────────────────────────
# Step 4: Present retrieved content to the clinician.
#
# Single LLM call. The LLM does two things:
#   1. Semantic filter: identify which recs actually answer the question
#      (Python term-matching casts a wide net; the LLM understands meaning)
#   2. Summary: write a concise clinical summary from the relevant recs
#
# Python builds the detail section from ONLY the LLM-selected recs.
#
# Rules enforced by prompt:
#   - The LLM selects recs by semantic relevance, not keyword match
#   - Summary: clear, concise, conversational clinical language
#   - The LLM does NOT interpret, editorialize, or paraphrase
#   - Detail: exact verbatim recs, RSS, KG (built by Python, not LLM)
# ───────────────────────────────────────────────────────────────────────
"""
Step 4: Response Presenter — one LLM call for filtering + summary.

    1. LLM reads retrieved content and the question, identifies which
       recs semantically answer the question (not just term matches),
       and writes a clinical summary
    2. Python builds the detail section from only the LLM-selected recs
       (verbatim recs with COR/LOE, RSS text, KG text)
    3. Combined: summary + filtered detail = full answer
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .content_retriever import RetrievedContent
from .knowledge_loader import (
    get_section as _kl_get_section,
    load_concept_section_catalogue as _kl_catalogue,
)
from .schemas import ParsedQAQuery
from . import atom_retriever

logger = logging.getLogger(__name__)


# ── Lazy-loaded knowledge store for full RSS expansion ──────────────
# Step 3's content retriever filters RSS rows by content-match score,
# dropping anything that doesn't contain the query's search terms.
# That's correct for the LLM context (precision), but wrong for the
# Details panel (recall). Once Step 4 has decided which sections
# answer the question, the clinician wants the COMPLETE body of
# supporting evidence for those sections — not a keyword-filtered
# subset. _build_detail uses this store to expand RSS back to full.
def _filter_rss_to_relevant(
    rss_rows: List[Dict[str, Any]],
    entry_ids: set,
    relevant_sections: set,
) -> List[Dict[str, Any]]:
    """Keep only RSS rows the LLM cited for the Summary.

    Details supports the Summary — nothing more. A row passes if:
      1. Its specific ID was listed in RELEVANT (entry_ids), OR
      2. It's a concept-dispatched row whose concept section's
         parentChapter is in the RELEVANT sections. This resolves
         the ID mismatch where the LLM cites "4.8(17)" (parent
         section) but the row's section is "antiplatelet_ivt_interaction"
         (concept section).

    Rows from unrelated sub-topics (cervical dissection, DAPT, AF
    anticoagulation) are dropped because their concept section's
    parentChapter won't be in relevant_sections unless the LLM
    explicitly cited a rec from those sub-topics.
    """
    catalogue = _kl_catalogue()
    kept: List[Dict[str, Any]] = []
    for r in rss_rows:
        # Path 1: specific entry ID cited
        if _rss_id(r) in entry_ids:
            kept.append(r)
            continue
        # Path 2: concept-dispatched row whose parent matches
        sec = r.get("section", "")
        if sec in relevant_sections:
            kept.append(r)
            continue
        # Resolve concept section → parentChapter
        concept = catalogue.get(sec)
        if concept:
            parent = concept.get("parentChapter", "")
            if parent and parent in relevant_sections:
                kept.append(r)
                continue
    return kept


def _load_sections_store() -> Dict[str, Any]:
    """Return the guideline sections dict via knowledge_loader.

    This is the single read path for section content. It routes
    through knowledge_loader.load_sections_store() which handles
    alias resolution and content_section_id dereferencing.
    """
    from .knowledge_loader import load_sections_store
    return load_sections_store()


def _full_rss_for_sections(
    section_ids: List[str],
    parsed_query: Optional[ParsedQAQuery] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return the full evidence row set for each requested section.

    Two paths:
      1. Atomized section (atoms[] present in guideline_knowledge.json):
         route through atom_retriever.select_atoms_for_section and
         convert the ranked atoms to RSS-shaped rows. This is the
         Stage 2 SWITCH path — rows are selected at the ROW level
         based on the query's anchors and intent, not dumped as a
         whole-table block.
      2. Legacy section (no atoms[] yet): return every RSS row for
         the section, as before. Bypasses the content-match filter
         in Step 3 so the Details panel shows the full body of
         supporting evidence under kept recs.

    Rows are normalized to the same shape Step 3 produces:
    (section, sectionTitle, recNumber, category, condition, text).
    Empty dict if the knowledge store is unavailable.
    """
    # Use knowledge_loader.get_section() so concept sections with
    # content_section_id + category_filter return only their
    # sub-topic rows, not the entire parent section.
    out: Dict[str, List[Dict[str, Any]]] = {}
    for sec_id in section_ids:
        sec = _kl_get_section(sec_id)
        if not sec:
            continue

        # ── Stage 2 SWITCH: atomized sections ───────────────────
        if parsed_query is not None and atom_retriever.section_has_atoms(sec_id):
            selected = atom_retriever.select_atoms_for_section(
                sec_id, parsed_query,
            )
            if selected:
                rows = atom_retriever.atoms_to_rss_rows(
                    selected,
                    section_title=sec.get("sectionTitle", ""),
                )
                if rows:
                    out[sec_id] = rows
                    continue
            # If atom selection came back empty, drop to legacy
            # rows rather than leaving the section invisible.

        # ── Legacy path: every RSS row for the section ──────────
        rows: List[Dict[str, Any]] = []
        for raw in sec.get("rss", []) or []:
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            rows.append({
                "section": sec_id,
                "sectionTitle": sec.get("sectionTitle", ""),
                "recNumber": raw.get("recNumber", ""),
                "category": raw.get("category", ""),
                "condition": raw.get("condition", ""),
                "text": text,
            })
        if rows:
            out[sec_id] = rows
    return out


# ── Soft caps on content passed to the LLM ──────────────────────────
# This is a clinical decision tool. Completeness beats token thrift.
# Caps are sized so the worst realistic Step 3 output (a broad
# multi-table contraindication query: ~30 recs + ~50 RSS rows + all
# synopses + KGs) fits comfortably inside a 200k-token context with
# room for the prompt and the model's own generation. No RSS or
# synopsis truncation — the LLM sees full verbatim text.
_MAX_RECS_FOR_LLM = 80
_MAX_RSS_FOR_LLM = 80
_MAX_KG_FOR_LLM = 40
_MAX_RSS_CHARS = 0       # 0 = no truncation; full verbatim text
_MAX_SYN_CHARS_DEFAULT = 0  # 0 = no truncation in _generate_summary

# ── Caps on the detail section ───────────────────────────────────────
# Detail renders every filtered rec/RSS verbatim. Same principle —
# never silently drop clinically relevant content.
_MAX_RECS_FOR_DETAIL = 80
_MAX_RSS_FOR_DETAIL = 80


class ResponsePresenter:
    """Formats Step 3 retrieved content into summary + detail."""

    def __init__(self, nlp_client=None):
        self._client = nlp_client
        self.is_available = nlp_client is not None

    async def present(
        self,
        question: str,
        retrieved: RetrievedContent,
        parsed: ParsedQAQuery,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate summary (LLM) + detail (Python) from retrieved content.

        The LLM does two things in one call:
        1. Semantic filter: identify which recs answer the question
        2. Summary: write a concise clinical summary

        Python then builds the detail section from only the selected recs.

        Returns:
            {
                "summary": str,           # LLM-written clinical summary
                "answer": str,            # Python-built verbatim content
                "citations": [str],
                "related_sections": [str],
            }
        """
        # ── Score-based pre-filter ──────────────────────────────────
        # Content search scored each entry by how many anchor concepts
        # matched. When discriminating terms exist (headache + IVT),
        # entries matching only the global term (IVT) score much lower.
        # Cut entries below 50% of the max score to remove noise.
        retrieved = _apply_score_threshold(retrieved)

        # ── Stage 2 SWITCH: atom-level row filtering ────────────────
        # For every atomized section reached via retrieved.rss,
        # replace the section's legacy rows with the ranked atoms
        # for this query BEFORE the LLM sees them. This prevents
        # the Step 4 summary from being polluted by unrelated row
        # dumps (e.g., a severe-headache query no longer sees the
        # tenecteplase dosing band as "relevant evidence").
        retrieved = _apply_atom_filter(retrieved)

        has_content = bool(
            retrieved.recommendations
            or retrieved.rss
            or retrieved.knowledge_gaps
            or retrieved.synopsis
            or retrieved.semantic_units
        )

        # ── LLM: semantic filter + summary ───────────────────────────
        if self._client and has_content:
            summary, relevant_rec_ids = await self._generate_summary(
                question, retrieved, parsed,
            )
            # Filter all content to only what the LLM identified
            if relevant_rec_ids:
                relevant_sections = {
                    rid.split("(")[0] for rid in relevant_rec_ids
                }
                # IDs with parens are entry-level (recs or individual
                # RSS entries). Bare section IDs are section-level.
                entry_ids = {
                    rid for rid in relevant_rec_ids if "(" in rid
                }
                filtered = RetrievedContent(
                    raw_query=retrieved.raw_query,
                    parsed_query=retrieved.parsed_query,
                    source_types=retrieved.source_types,
                    sections=retrieved.sections,
                    recommendations=[
                        r for r in retrieved.recommendations
                        if _rec_id(r) in entry_ids
                    ],
                    synopsis={
                        sec: text
                        for sec, text in retrieved.synopsis.items()
                        if sec in relevant_sections
                    },
                    # RSS: keep ONLY the rows the LLM used for
                    # the Summary. Details supports the Summary —
                    # nothing more. The LLM decides what's relevant;
                    # Python shows exactly that, verbatim.
                    #
                    # Concept-dispatched rows have section IDs like
                    # "antiplatelet_ivt_interaction" but the LLM
                    # cites parent sections like "4.8". Resolve via
                    # the concept catalogue's parentChapter field.
                    rss=_filter_rss_to_relevant(
                        retrieved.rss, entry_ids, relevant_sections,
                    ),
                    knowledge_gaps={
                        sec: text
                        for sec, text in retrieved.knowledge_gaps.items()
                        if sec in relevant_sections
                    },
                    tables=retrieved.tables,
                    figures=retrieved.figures,
                    semantic_units=retrieved.semantic_units,
                )
                logger.info(
                    "Step 4: LLM filtered %d→%d recs, %d→%d rss "
                    "(relevant: %s)",
                    len(retrieved.recommendations),
                    len(filtered.recommendations),
                    len(retrieved.rss),
                    len(filtered.rss),
                    relevant_rec_ids,
                )
            else:
                # LLM didn't return rec IDs — use all
                filtered = retrieved
        else:
            summary = _fallback_summary(retrieved)
            filtered = retrieved

        # ── Detail section (Python, verbatim, filtered recs) ─────────
        detail = _build_detail(filtered)
        citations = _extract_citations(filtered)

        # Related sections: from filtered recs, or from synopsis if no recs
        seen_sections: list = []
        for rec in filtered.recommendations:
            sec = rec.get("section", "")
            if sec and sec not in seen_sections:
                seen_sections.append(sec)
        if not seen_sections and filtered.synopsis:
            for sec_id in filtered.synopsis:
                if sec_id not in seen_sections:
                    seen_sections.append(sec_id)

        # ── Output ────────────────────────────────────────────────────
        return {
            "summary": summary,
            "answer": detail,
            "citations": citations,
            "related_sections": seen_sections,
        }

    async def _generate_summary(
        self,
        question: str,
        retrieved: RetrievedContent,
        parsed: ParsedQAQuery,
    ) -> tuple:
        """Single LLM call: filter recs by relevance + write summary.

        Returns:
            (summary_text, relevant_rec_ids)
            relevant_rec_ids is a set of "section(recNumber)" strings,
            e.g. {"4.3(5)", "4.3(8)"}.
        """

        # ── Build content blocks for the LLM ─────────────────────────
        content_parts: List[str] = []

        # Concept units (hand-labeled semantic index hits).
        # Each unit is ONE clinical decision point with a terse meaning
        # sentence and a unit_id (rec.4.3.5, rss.4.6.1, syn.4.7, etc.).
        # Surfaced first so the LLM anchors on precise hits before wading
        # through the wider full-text rec/RSS pool.
        semantic = retrieved.semantic_units[:_MAX_RECS_FOR_LLM]
        if semantic:
            content_parts.append("CONCEPT UNITS:")
            for unit in semantic:
                unit_id = unit.get("id", "")
                section = unit.get("section_key", "")
                concept = unit.get("concept") or unit.get("concepts") or ""
                meaning = unit.get("meaning", "")
                content_parts.append(
                    f"  [{unit_id} @ {section}] {concept}: {meaning}"
                )
            content_parts.append("")

        # Recommendations (top N, with metadata)
        recs = retrieved.recommendations[:_MAX_RECS_FOR_LLM]
        if recs:
            content_parts.append("RECOMMENDATIONS:")
            for rec in recs:
                sec = rec.get("section", "")
                rec_num = rec.get("recNumber", "")
                cor = rec.get("cor", "")
                loe = rec.get("loe", "")
                text = rec.get("text", "")
                content_parts.append(
                    f"  [{sec}({rec_num})] "
                    f"(COR {cor}, LOE {loe}): {text}"
                )

        # RSS / supporting evidence (top N, truncated)
        # Label each entry with [section(recNumber)] so the LLM can
        # reference individual entries on the RELEVANT line.
        #
        # Exhaustive rows (from the structured-list retrieval path)
        # must never be dropped by the flat top-N cut: they are the
        # literal answer to a list question and dropping one breaks
        # the completeness guarantee. Keep them all, then fill the
        # remaining budget from the ranked results.
        exhaustive_rss = [
            r for r in retrieved.rss if r.get("_exhaustive")
        ]
        ranked_rss = [
            r for r in retrieved.rss if not r.get("_exhaustive")
        ]
        remaining_slots = max(
            0, _MAX_RSS_FOR_LLM - len(exhaustive_rss),
        )
        rss = exhaustive_rss + ranked_rss[:remaining_slots]
        if rss:
            content_parts.append("\nSUPPORTING EVIDENCE:")
            for entry in rss:
                sec = entry.get("section", "")
                rec_num = entry.get("recNumber", "")
                text = entry.get("text", "")
                # No truncation: clinical accuracy requires the full
                # verbatim text reach the LLM. Truncation here once
                # caused "…" to chop off the dosing bands in
                # tenecteplase weight-band rows.
                if _MAX_RSS_CHARS and len(text) > _MAX_RSS_CHARS:
                    text = text[:_MAX_RSS_CHARS] + "..."
                entry_id = f"{sec}({rec_num})" if rec_num else sec
                # Surface the row's category (Table 8 band) so the LLM
                # can state the strength in the summary — e.g., a row
                # tagged absolute_contraindication must be summarized as
                # an absolute contraindication, not "a contraindication".
                cat_label = _format_category(entry.get("category", ""))
                if cat_label:
                    content_parts.append(
                        f"  [{entry_id} | {cat_label}]: {text}"
                    )
                else:
                    content_parts.append(f"  [{entry_id}]: {text}")

        # Synopsis / narrative content (for table-based answers).
        # No truncation — a clinician asking about pregnancy IVT
        # should not have the relevant paragraph cut at 6k because
        # some other section's synopsis was longer.
        if retrieved.synopsis:
            content_parts.append("\nGUIDELINE TEXT:")
            for sec_id, text in retrieved.synopsis.items():
                if _MAX_SYN_CHARS_DEFAULT and \
                        len(text) > _MAX_SYN_CHARS_DEFAULT:
                    text = text[:_MAX_SYN_CHARS_DEFAULT] + "..."
                content_parts.append(f"  [{sec_id}]: {text}")

        # Knowledge gaps (top N, truncated)
        kg_items = list(retrieved.knowledge_gaps.items())[:_MAX_KG_FOR_LLM]
        if kg_items:
            content_parts.append("\nKNOWLEDGE GAPS:")
            for sec_id, text in kg_items:
                if len(text) > 500:
                    text = text[:500] + "..."
                content_parts.append(f"  [{sec_id}]: {text}")

        content_block = "\n".join(content_parts)

        # ── Prompt ───────────────────────────────────────────────────
        # The rendering rules branch by intent family: evidentiary
        # questions want evidence-narrative prose that names trials
        # and weaves numerical outcomes, while prescriptive questions
        # want a short bulleted consult answer. Everything else
        # (rules against fusion, inversion, hallucinated citations,
        # softening contraindications) is shared.
        render_rules = _render_rules_for_intent(parsed.intent)

        # LIST MODE override.
        #
        # When Step 3's exhaustive list path has delivered a
        # categorized set of rows (e.g. "benefit greater than risk"
        # band), the clinician has literally asked for a list and
        # the retriever has provided the complete, authoritative
        # set. The answer must be a bullet list of every row, not
        # a narrative synthesis — regardless of how the intent
        # classifier tagged the question.
        #
        # This override is prepended so it beats any conflicting
        # instruction in the intent-family render rule.
        list_mode_categories = getattr(
            retrieved, "list_mode_categories", None,
        ) or []
        if list_mode_categories:
            pretty_cats = ", ".join(
                c.title() for c in list_mode_categories
            )
            list_mode_block = (
                "LIST MODE — OVERRIDES ANY CONFLICTING INSTRUCTION "
                "BELOW:\n"
                f"- The clinician asked for the items in: {pretty_cats}. "
                "The SUPPORTING EVIDENCE block contains EVERY row of "
                "that category from the guideline, already filtered "
                "to the correct band.\n"
                "- Render EACH row as its own bullet. Do not "
                "summarize the table. Do not merge rows. Do not "
                "paraphrase two rows into one sentence. Do not add "
                "rows from outside the retrieved content. Do not "
                "invoke knowledge from outside the retrieved "
                "content.\n"
                "- If the retrieved content contains N rows in the "
                "asked category, your output contains N bullets. "
                "Not N-1. Not N+1.\n"
                "- Bullet format:\n"
                "    - {Condition from the row} — {one short "
                "sentence drawn verbatim from the row's text, "
                "preserving any thresholds or numeric criteria}.\n"
                "- If multiple categories were requested, group "
                "bullets under a one-line header per category "
                "(plain text, no markdown). Absolute first, then "
                "relative, then benefit > risk, then any others.\n"
                "- Cite each bullet inline as (Table N) using the "
                "section id from the row header.\n"
                "- Do not include introductory prose ('The "
                "guidelines identify...'). Go straight to the "
                "bullets.\n"
                "- Do not include any row whose category tag in "
                "the SUPPORTING EVIDENCE header is not in the "
                "requested list.\n\n"
            )
            render_rules = list_mode_block + render_rules

        system_prompt = (
            "You are a stroke specialist colleague answering a question "
            "about the 2026 AHA/ASA AIS guidelines.\n\n"
            "You have two jobs:\n"
            "1. FILTER: From the content below, identify ONLY the "
            "sections and recommendations that semantically answer "
            "the question. Content is relevant if it directly "
            "addresses the clinical scenario — not just because it "
            "mentions a related term. A rec about EVT BP targets is "
            "NOT relevant to an IVT BP question. "
            "CONCEPT UNITS (if present) are hand-labeled to one "
            "clinical decision point each — prefer them as the anchor "
            "for filtering, and use the other blocks to back them up.\n"
            "2. SUMMARIZE: Write a clinical summary using only "
            "the relevant content.\n\n"
            "OUTPUT FORMAT (follow exactly):\n"
            "Line 1: RELEVANT: followed by comma-separated IDs from "
            "the content. For recommendations use the full ID, e.g. "
            "4.3(5). For supporting evidence or guideline text use "
            "the section ID, e.g. Table 8 or 4.6.1\n"
            "Line 2 onwards: Your clinical summary.\n\n"
            f"{render_rules}\n"
            "SHARED RULES (always apply):\n"
            "- Plain text only. No markdown, no asterisks, no bold, "
            "no headers, no special formatting.\n"
            "- Parenthetical COR/LOE references inline, "
            "e.g. '...to reduce hemorrhagic complications "
            "(Rec 5, COR 1, LOE B-NR).'\n"
            "- Answer ONLY what was asked — nothing more. Do not add "
            "related information the user did not ask about. "
            "The user can ask a follow-up if needed.\n"
            "- Do NOT use filler words like 'importantly', 'notably', "
            "'it should be noted', 'according to the guidelines'.\n"
            "- State what the guideline says. Do NOT answer yes/no or "
            "draw conclusions the guideline does not explicitly state.\n"
            "- When a supporting-evidence entry carries a category label "
            "(after the | in its header, e.g. 'Conditions That Are "
            "Considered Absolute Contraindications'), you MUST state "
            "that strength explicitly in the summary. Do not soften "
            "'absolute contraindication' to 'a contraindication', and "
            "do not soften 'relative contraindication' to 'caution'.\n"
            "- ONE SOURCE PER CLAUSE. Each sentence or bullet may "
            "reference at most ONE retrieved item (one rec, one RSS "
            "row, one synopsis paragraph, one table row). NEVER merge "
            "content from two different sources into a single "
            "sentence or clause. If two sources cover different "
            "aspects of the same topic, put them in SEPARATE bullets "
            "with their own citations.\n"
            "- NO CROSS-SOURCE PARAPHRASE. If you cannot point to "
            "exactly ONE retrieved item that supports a statement "
            "verbatim, drop the statement. Do not synthesize a new "
            "claim by combining fragments from different items.\n"
            "- NEVER INVERT GUIDANCE. If one source says 'do X' and "
            "another says 'delay X', they are NOT the same clinical "
            "point — keep them separate, cite each, and let the "
            "clinician reconcile. Do not merge them into a single "
            "statement that inverts either.\n"
            "- CITATION INTEGRITY. When you cite a recommendation "
            "number like 4.3(5), it MUST appear verbatim in the "
            "RECOMMENDATIONS block above. Do not invent section "
            "numbers, do not round or shift digits, do not infer a "
            "number from a section title. If no rec number is "
            "available for a statement, cite by section id (e.g. "
            "'Table 7') instead.\n"
            "- Do NOT interpret or add clinical opinions beyond what the "
            "guideline states.\n"
            "- Do NOT fabricate — if the content does not answer the "
            "question, say so plainly.\n"
            "- If knowledge gaps exist, note them briefly.\n"
        )

        question_summary = parsed.question_summary or question

        user_message = (
            f"QUESTION: {question}\n"
            f"CLINICAL CONTEXT: {question_summary}\n\n"
            f"GUIDELINE CONTENT:\n{content_block}\n\n"
            "First line: RELEVANT: followed by the IDs of content that "
            "answers the question.\n"
            "Then: concise clinical summary in plain text."
        )

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            for block in response.content:
                if hasattr(block, "text"):
                    raw = block.text.strip()
                    relevant_ids, summary = _parse_relevant_and_summary(raw)
                    # Strip any hallucinated section/rec numbers that
                    # don't appear in the retrieved set. This is the
                    # last line of defense against the LLM free-typing
                    # a section number like 6.3(3) when the retrieved
                    # recs were 5.3(3).
                    summary = _strip_hallucinated_citations(
                        summary, retrieved,
                    )
                    return summary, relevant_ids
        except Exception as e:
            logger.error("Summary generation failed: %s", e)

        return _fallback_summary(retrieved), set()


# ── Score-based pre-filtering ────────────────────────────────────────
#
# Historically Step 4 cut entries below 50 % of the top score before
# passing content to the LLM. This was written as a noise filter but
# it was silently deleting relevant content — e.g. a dysphagia
# question would retrieve Rec 5.3(3) at score 30 alongside a
# peripheral mention at score 80, and the rec would get cut because
# 30 < 0.5·80. The LLM never saw the actually-relevant rec.
#
# Clinical decision tool: completeness beats token thrift. This
# function is now a passthrough. We keep the shape so callers are
# unchanged, and preserve the hook if a future metric-based filter
# is added (it would need explicit justification per clinical review).
def _apply_score_threshold(retrieved: RetrievedContent) -> RetrievedContent:
    """Passthrough — historically pruned entries below 50% of max score.

    Removed because clinical decision tools cannot silently drop
    retrieved content. Step 4's LLM semantic filter + hand-curated
    prompt rules do the relevance filtering instead, with every
    candidate visible to the model.
    """
    return retrieved


def _apply_atom_filter(retrieved: RetrievedContent) -> RetrievedContent:
    """Replace legacy RSS rows for atomized sections with ranked atoms.

    Stage 2 SWITCH. For every section that has been migrated to
    the atom schema (Table 7 today, more tables/sections to follow),
    run atom_retriever.select_atoms_for_section with the current
    parsed query and replace that section's RSS rows with the atom
    selection — converted to the RSS row shape the rest of the
    presenter consumes. Sections that have NOT been atomized pass
    through unchanged.

    This must happen before the LLM summary call so the Step 4
    model sees only the relevant row(s), not the whole table.

    Zero-match guarantee: if a section is atomized but no atom
    clears the score threshold, select_atoms_for_section returns
    every atom in PDF order — so the clinician never loses recall
    relative to legacy behavior.
    """
    parsed = getattr(retrieved, "parsed_query", None)
    if parsed is None or not retrieved.rss:
        return retrieved

    # Group incoming rows by section so we can decide per-section
    # whether to substitute atoms.
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for row in retrieved.rss:
        sec = row.get("section", "")
        if sec not in by_section:
            by_section[sec] = []
            order.append(sec)
        by_section[sec].append(row)

    replaced_any = False
    new_rss: List[Dict[str, Any]] = []
    for sec in order:
        if atom_retriever.section_has_atoms(sec):
            selected = atom_retriever.select_atoms_for_section(sec, parsed)
            if selected:
                sec_data = _kl_get_section(sec)
                sec_title = (sec_data or {}).get("sectionTitle", "")
                atom_rows = atom_retriever.atoms_to_rss_rows(
                    selected, section_title=sec_title,
                )
                if atom_rows:
                    new_rss.extend(atom_rows)
                    replaced_any = True
                    logger.info(
                        "Stage 2 SWITCH: section %s atom-filtered "
                        "%d legacy rows -> %d atoms",
                        sec, len(by_section[sec]), len(atom_rows),
                    )
                    continue
        # Passthrough: section not atomized, or atom path returned nothing
        new_rss.extend(by_section[sec])

    if not replaced_any:
        return retrieved

    # Return a new RetrievedContent with the atom-filtered RSS list.
    # Every other field is copied by reference — the atom filter
    # only reshapes RSS rows.
    return RetrievedContent(
        raw_query=retrieved.raw_query,
        parsed_query=retrieved.parsed_query,
        source_types=retrieved.source_types,
        sections=retrieved.sections,
        recommendations=retrieved.recommendations,
        synopsis=retrieved.synopsis,
        rss=new_rss,
        knowledge_gaps=retrieved.knowledge_gaps,
        tables=retrieved.tables,
        figures=retrieved.figures,
        semantic_units=retrieved.semantic_units,
        list_mode_categories=retrieved.list_mode_categories,
    )


# ── Detail section (pure Python, verbatim) ────────────────────────────


_CATEGORY_LABELS = {
    "absolute_contraindication": "Conditions that are Considered Absolute Contraindications",
    "relative_contraindication": "Conditions That are Relative Contraindications",
    "benefit_greater_than_risk": "Conditions in Which Benefits of Intravenous Thrombolysis Generally are Greater Than Risks of Bleeding",
}


def _format_category(category: str) -> str:
    """Map RSS category slugs to clinician-facing labels."""
    return _CATEGORY_LABELS.get(category, "")


def _section_title(sec_id: str, retrieved: RetrievedContent) -> str:
    """Get section title from RSS or rec metadata."""
    for entry in retrieved.rss:
        if entry.get("section") == sec_id:
            title = entry.get("sectionTitle", "")
            if title:
                return title
    for rec in retrieved.recommendations:
        if rec.get("section") == sec_id:
            title = rec.get("sectionTitle", "")
            if title:
                return title
    return ""


def _build_detail(retrieved: RetrievedContent) -> str:
    """Build the verbatim detail section from retrieved content.

    Deterministic. No LLM. Every word comes directly from the
    guideline JSON — recs, RSS, KG — unmodified.

    Format matches frontend DETAILS & CITATIONS rendering:
        Recommendation {section} ({rec_num}) — {sectionTitle}
        Class of Recommendation: {COR} | Level of Evidence: {LOE}

        {verbatim text}

        Supporting Evidence: {verbatim RSS text}
    """
    parts: List[str] = []

    # ── Recommendations (ordered by Step 3 relevance score) ──────
    recs = retrieved.recommendations[:_MAX_RECS_FOR_DETAIL]
    for rec in recs:
        sec = rec.get("section", "")
        rec_num = rec.get("recNumber", "")
        sec_title = rec.get("sectionTitle", "")
        cor = rec.get("cor", "")
        loe = rec.get("loe", "")
        text = rec.get("text", "")

        parts.append(
            f"Recommendation {sec} ({rec_num}) — {sec_title} "
            f"Class of Recommendation: {cor} | Level of Evidence: {loe}"
        )
        parts.append("")
        parts.append(text)
        parts.append("")

    # ── Full supporting-evidence expansion for every kept section ─
    # Step 3 filters RSS rows by content-match score, which is
    # right for the LLM context (precision) but wrong for the
    # Details panel (recall). Once Step 4 has decided which
    # sections answer the question, expand RSS back to the full
    # body of evidence for those sections by reloading straight
    # from the knowledge store. The retrieved.rss list is kept as
    # a fallback for sections the knowledge store can't resolve
    # (e.g. Table 8 bands, which live outside the sections tree).
    rec_sections: List[str] = []
    for rec in recs:
        sec = rec.get("section", "")
        if sec and sec not in rec_sections:
            rec_sections.append(sec)
    # ── Stage 2 SWITCH: pass parsed_query through so atomized
    # sections (e.g. Table 7) return row-level atom selections
    # instead of whole-table dumps.
    parsed_query = getattr(retrieved, "parsed_query", None)
    full_by_section = _full_rss_for_sections(rec_sections, parsed_query)

    # ── Also atom-filter any section pulled into rss_by_section
    # via the retrieved.rss list (synopsis / orphan path). Table 7
    # is the canary here: it has no recs, so it never flows through
    # rec_sections — only through retrieved.rss — and we must not
    # let the synopsis branch dump every row unfiltered.
    def _atom_filter_section(sec_id: str) -> Optional[List[Dict[str, Any]]]:
        if parsed_query is None:
            return None
        if not atom_retriever.section_has_atoms(sec_id):
            return None
        selected = atom_retriever.select_atoms_for_section(
            sec_id, parsed_query,
        )
        if not selected:
            return None
        sec_data = _kl_get_section(sec_id)
        sec_title = (sec_data or {}).get("sectionTitle", "")
        return atom_retriever.atoms_to_rss_rows(
            selected, section_title=sec_title,
        )

    # Build the RSS-by-section map for the Details panel.
    #
    # When the retriever returned concept-dispatched rows (rows with
    # _concept_dispatched=True), those are already filtered by the
    # concept section's category_filter — they ARE the authoritative
    # content. Do NOT re-expand them via _full_rss_for_sections,
    # which would fetch the entire parent section and undo the
    # sub-topic filtering. Use retrieved.rss directly.
    #
    # The old full-expansion path only fires when there are NO
    # concept-dispatched rows (legacy fallback queries).
    rss_from_retrieved = retrieved.rss[:_MAX_RSS_FOR_DETAIL]
    has_concept_rows = any(
        r.get("_concept_dispatched") for r in rss_from_retrieved
    )

    # DIAGNOSTIC: log exactly what _build_detail sees
    logger.info(
        "_build_detail DIAGNOSTIC: rss_from_retrieved=%d rows, "
        "has_concept_rows=%s, rec_sections=%s, "
        "full_by_section_keys=%s, "
        "rss_sections=%s",
        len(rss_from_retrieved),
        has_concept_rows,
        rec_sections,
        list(full_by_section.keys()),
        sorted(set(r.get("section", "") for r in rss_from_retrieved)),
    )

    rss_by_section: Dict[str, List[Dict[str, Any]]] = {}
    if has_concept_rows:
        # Concept-dispatched: use retrieved rows as-is, grouped by section
        for entry in rss_from_retrieved:
            sec = entry.get("section", "")
            rss_by_section.setdefault(sec, []).append(entry)
    else:
        # Legacy fallback: expand kept sections to full RSS
        for entry in rss_from_retrieved:
            sec = entry.get("section", "")
            if sec in full_by_section:
                continue
            rss_by_section.setdefault(sec, []).append(entry)
        for sec, rows in full_by_section.items():
            rss_by_section[sec] = rows

    # ── Stage 2 SWITCH: override any atomized section that reached
    # rss_by_section via the retrieved.rss path. This covers the
    # synopsis/orphan branch where full_by_section is empty (e.g.
    # Table 7 has no recs). Replace the unfiltered legacy rows
    # with ranked atoms for the current query.
    for sec in list(rss_by_section.keys()):
        atom_rows = _atom_filter_section(sec)
        if atom_rows is not None:
            rss_by_section[sec] = atom_rows

    if retrieved.synopsis and not recs:
        for sec_id, text in retrieved.synopsis.items():
            sec_rss = rss_by_section.pop(sec_id, [])
            if sec_rss:
                # Header the RSS block with the section number only,
                # then group rows by category so each sub-heading
                # prints exactly once with all its rows nested
                # beneath. We deliberately do NOT print Table 8's
                # verbatim sectionTitle ("Other Situations Wherein
                # Thrombolysis is Deemed to Be Considered") — it is
                # clinically misleading for readers looking at an
                # absolute-contraindication row. The band sub-heading
                # below carries the true strength.
                parts.append(sec_id)
                parts.append("")

                grouped: Dict[str, List[Dict[str, Any]]] = {}
                order: List[str] = []
                for entry in sec_rss:
                    if not entry.get("text"):
                        continue
                    cat = entry.get("category", "")
                    if cat not in grouped:
                        grouped[cat] = []
                        order.append(cat)
                    grouped[cat].append(entry)

                for cat in order:
                    cat_label = _format_category(cat)
                    if cat_label:
                        parts.append(cat_label)
                        parts.append("")
                    # Each bullet gets its own blank line after it
                    # so the frontend markdown renderer treats them
                    # as separate bullets, not one paragraph joined
                    # by spaces. Previously the blank line sat
                    # outside this inner loop, so 10 consecutive
                    # bullets collapsed into a wall of text.
                    for entry in grouped[cat]:
                        condition = entry.get("condition", "")
                        entry_text = entry.get("text", "")
                        if condition:
                            parts.append(
                                f"\u2022 {condition} — {entry_text}"
                            )
                        else:
                            parts.append(f"\u2022 {entry_text}")
                        parts.append("")
            else:
                # No RSS for this section. Only show synopsis for
                # table sections (Table 7, Table 8) where the synopsis
                # IS the structured content. For narrative sections
                # (4.6.1, 5.3), the synopsis is a massive narrative
                # dump that overwhelms the detail — the summary
                # already covers it.
                if sec_id.startswith("Table"):
                    parts.append(f"Guideline Text — {sec_id}")
                    parts.append("")
                    parts.append(text)
                    parts.append("")

    # ── Remaining RSS not paired with a synopsis section ────────
    # Group by section so each block gets a clear header. Render
    # kept-rec sections first (in rec order) so the evidence
    # appears right under the recommendations it supports, then
    # any orphan sections after.
    render_order: List[str] = []
    for sec in rec_sections:
        if sec in rss_by_section and sec not in render_order:
            render_order.append(sec)
    for sec in rss_by_section.keys():
        if sec not in render_order:
            render_order.append(sec)

    any_rss = any(rss_by_section.get(sec) for sec in render_order)
    if any_rss:
        parts.append("Supporting Evidence:")
        parts.append("")
        for sec in render_order:
            sec_entries = rss_by_section.get(sec, [])
            if not sec_entries:
                continue
            # Section header shows the guideline section number +
            # title so the clinician can anchor each evidence
            # block back to its recommendation above.
            sec_title = _section_title(sec, retrieved)
            if sec_title:
                parts.append(f"{sec} — {sec_title}")
            else:
                parts.append(sec)
            parts.append("")
            for entry in sec_entries:
                entry_text = entry.get("text", "")
                if not entry_text:
                    continue
                category = entry.get("category", "")
                cat_label = _format_category(category)
                if cat_label:
                    parts.append(f"{cat_label}:")
                    parts.append("")
                condition = entry.get("condition", "")
                if condition:
                    parts.append(
                        f"\u2022 {condition} — {entry_text}"
                    )
                else:
                    parts.append(f"\u2022 {entry_text}")
                parts.append("")

    # ── Knowledge gaps ───────────────────────────────────────────
    if retrieved.knowledge_gaps:
        for _sec_id, text in retrieved.knowledge_gaps.items():
            parts.append(f"\u2022 Knowledge Gap: {text}")
        parts.append("")

    return "\n".join(parts)


def _extract_citations(retrieved: RetrievedContent) -> List[str]:
    """Extract citation strings matching the frontend GUIDELINE REFERENCES format.

    Format:
        Section {section} -- {sectionTitle} (COR {COR}, LOE {LOE})
        Section {section} -- {sectionTitle} (Recommendation-Specific Supportive Text)
    """
    citations: List[str] = []
    seen: set = set()

    # Recommendation citations
    for rec in retrieved.recommendations:
        sec = rec.get("section", "")
        sec_title = rec.get("sectionTitle", "")
        cor = rec.get("cor", "")
        loe = rec.get("loe", "")
        if sec:
            citation = f"Section {sec} -- {sec_title} (COR {cor}, LOE {loe})"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)

    # RSS citations. When the entry has a category (Table 8 band),
    # the citation is "<section> — <band> (Supporting Evidence)" —
    # the band IS the meaningful label, and Table 8's verbatim
    # sectionTitle ("Other Situations Wherein Thrombolysis is Deemed
    # to Be Considered") is deliberately excluded because it misreads
    # as "maybe consider these" even for absolute-contraindication
    # rows. For entries without a category, fall back to the section
    # title.
    for rss in retrieved.rss:
        sec = rss.get("section", "")
        sec_title = rss.get("sectionTitle", "")
        if sec:
            cat_label = _format_category(rss.get("category", ""))
            if cat_label:
                citation = f"{sec} — {cat_label} (Supporting Evidence)"
            else:
                label = sec_title if sec_title else sec
                citation = f"{label} (Supporting Evidence)"
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)

    return citations


def _rec_id(rec: Dict[str, Any]) -> str:
    """Build a rec ID string like '4.3(5)' from a rec dict."""
    sec = rec.get("section", "")
    num = rec.get("recNumber", "")
    return f"{sec}({num})"


def _rss_id(entry: Dict[str, Any]) -> str:
    """Build an RSS entry ID like 'Table 8(severe-coagulopathy-or-thrombocytopenia)'."""
    sec = entry.get("section", "")
    num = entry.get("recNumber", "")
    return f"{sec}({num})" if num else sec


def _parse_relevant_and_summary(raw: str) -> tuple:
    """Parse LLM output into (relevant_rec_ids, summary_text).

    Expected format:
        RELEVANT: 4.3(5), 4.3(8)
        Summary text here...

    Two sources of relevant IDs:
    1. The explicit RELEVANT line (primary)
    2. Rec IDs cited in the summary text (fallback)
       e.g. "Rec 4.3(7)" or "4.3(7), COR 1" in summary text

    The LLM sometimes cites recs in the summary but omits them
    from the RELEVANT line. Parsing the summary catches these.

    Returns:
        (set of rec ID strings, summary text)
    """
    import re

    lines = raw.strip().split("\n")
    relevant_ids: set = set()
    summary_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("RELEVANT:"):
            # Parse the comma-separated IDs after "RELEVANT:"
            id_part = stripped[len("RELEVANT:"):].strip()
            if id_part and id_part.upper() != "NONE":
                for token in id_part.split(","):
                    token = token.strip()
                    if token:
                        relevant_ids.add(token)
            summary_start = i + 1
            break

    # Everything after the RELEVANT line is the summary
    summary = "\n".join(lines[summary_start:]).strip()
    if not summary:
        summary = raw.strip()  # fallback: entire response is summary

    # Extract rec IDs cited in summary text that aren't on the
    # RELEVANT line. Pattern: "Rec 4.3(7)" or bare "4.3(7)"
    # followed by comma, close-paren, or COR/LOE reference.
    cited_in_summary = re.findall(
        r"(?:Rec\s+)?(\d+\.\d+(?:\.\d+)?\(\d+\))", summary,
    )
    for cited_id in cited_in_summary:
        if cited_id not in relevant_ids:
            relevant_ids.add(cited_id)
            logger.info(
                "Step 4: added %s from summary text to RELEVANT",
                cited_id,
            )

    return relevant_ids, summary


# ── Intent family → rendering rules ─────────────────────────────────
# The summary voice has to match what the clinician asked for.
# An evidence question wants evidence-narrative prose (named trials,
# subgroup data, numerical outcomes). A prescriptive question wants
# a short bulleted consult answer. A safety question wants strength-
# first contraindication phrasing. Families mirror the rubric in
# references/qa_query_parsing_schema.md ("Semantic Decision Rubric")
# so Step 1 and Step 4 stay aligned.

_INTENT_FAMILY: Dict[str, str] = {
    # Evidentiary — the user wants the evidence behind a rec
    "evidence_for_recommendation": "evidentiary",
    "trial_specific_data": "evidentiary",
    "evidence_with_recommendation": "evidentiary",
    "evidence_with_confidence": "evidentiary",
    "evidence_vs_gaps": "evidentiary",
    # Explanatory — the user wants to understand why / what it means
    "narrative_context": "explanatory",
    "rationale_explanation": "explanatory",
    "definition_lookup": "explanatory",
    "rationale_with_uncertainty": "explanatory",
    "risk_factor_inquiry": "explanatory",
    # Safety — contraindications and harms
    "contraindications": "safety",
    "harm_query": "safety",
    "no_benefit_query": "safety",
    "complication_management": "safety",
    "reversal_protocol": "safety",
    # Comparative
    "comparison_query": "comparative",
    "drug_choice": "comparative",
    "treatment_modality_choice": "comparative",
    # Uncertainty
    "knowledge_gap": "uncertainty",
    "recommendation_with_confidence": "uncertainty",
    "current_understanding_and_gaps": "uncertainty",
    # Comprehensive
    "clinical_overview": "comprehensive",
    "full_topic_deep_dive": "comprehensive",
    "pediatric_specific": "comprehensive",
    # Everything else is prescriptive by default
}


def _intent_family(intent: Optional[str]) -> str:
    """Map an intent id to its rendering family. Default: prescriptive."""
    if not intent:
        return "prescriptive"
    return _INTENT_FAMILY.get(intent, "prescriptive")


_RENDER_RULES: Dict[str, str] = {
    "evidentiary": (
        "RENDERING — EVIDENTIARY QUESTION:\n"
        "- The clinician asked 'what data / what evidence / what "
        "trials / what studies / what supports' — they want BOTH "
        "the supporting evidence (from RSS / trials / synopses) "
        "AND the recommendations that evidence supports. An "
        "evidence summary without the evidence is a failure. "
        "A recommendation list without the trials behind it is "
        "a failure. You MUST include both when both are present "
        "in the retrieved content.\n"
        "- Use a READABLE BULLETED STRUCTURE. A busy stroke "
        "specialist should be able to scan the answer in seconds. "
        "No wall-of-text paragraphs, no markdown headers.\n"
        "- Open with a single short lead-in line (one sentence, "
        "no bullet) naming the body of evidence — e.g. 'The "
        "evidence supporting EVT in large-core stroke comes from "
        "SELECT2, ANGEL-ASPECT, RESCUE-Japan LIMIT, TENSION, "
        "TESLA, and LASTE.'\n"
        "- Then a 'Key trials:' block with one bullet per named "
        "trial. Each bullet names the trial and gives its key "
        "numerical finding from the retrieved content (effect "
        "size, 90-day mRS, NNT, absolute risk reduction, CI, "
        "p-value, subgroup result). If the retrieved content "
        "does not give a number for a trial, describe the "
        "finding qualitatively — do not invent numbers.\n"
        "- Then a 'What the guideline recommends:' block with "
        "one bullet per recommendation the evidence supports. "
        "Each bullet states the recommendation in plain clinical "
        "language and cites it inline as (section(recNumber), "
        "COR X, LOE Y). Cite RSS entries inline using the "
        "unit_id from the CONCEPT UNITS block when available "
        "(e.g. rss.4.7.2.3), otherwise by section.\n"
        "- If numerical synthesis data exist in the retrieved "
        "content (pooled NNT, functional independence rates, "
        "mortality, mRS shift across trials), add a final "
        "'Pooled effect:' block with one bullet per synthesis "
        "datum so the clinician sees the effect size clearly.\n"
        "- Use plain dash bullets (-). Keep each bullet to one "
        "or two sentences.\n"
    ),
    "explanatory": (
        "RENDERING — EXPLANATORY QUESTION:\n"
        "- Use a READABLE BULLETED STRUCTURE. No wall-of-text "
        "paragraphs, no markdown headers.\n"
        "- Open with a single short lead-in line (one sentence, "
        "no bullet) stating the concept, mechanism, or "
        "background the user asked to understand.\n"
        "- Then bullets (plain dash -) for each mechanism, "
        "rationale, or supporting point. Draw from SYN and RSS "
        "to explain the 'why'. Cite each bullet inline by "
        "section.\n"
        "- If recs are relevant, add a final 'Relevant "
        "recommendations:' block with one bullet per rec, cited "
        "as (section(recNumber), COR, LOE).\n"
        "- Keep each bullet to one or two sentences.\n"
    ),
    "safety": (
        "RENDERING — SAFETY QUESTION:\n"
        "- Lead with STRENGTH. If an item is an absolute "
        "contraindication, say 'absolute contraindication' in "
        "the opening clause. If relative, say 'relative "
        "contraindication'. Never soften these to 'caution' or "
        "'a contraindication'.\n"
        "- Group by strength: absolute first, then relative, "
        "then benefit-greater-than-risk. Within each strength, "
        "use short bullet points (plain dash -) for distinct "
        "conditions.\n"
        "- COMPLETENESS: when the SUPPORTING EVIDENCE block "
        "contains RSS rows tagged with a category label in the "
        "[section | Category] header, render EVERY such row as "
        "its own bullet under the correct band. Do not summarize, "
        "merge, or drop rows. If you were given 10 rows tagged "
        "'Absolute Contraindication', output 10 bullets. The "
        "clinician asked for the list — give them the list.\n"
        "- Each bullet: bold the condition name from the row, "
        "then a dash, then one short sentence drawn from the "
        "row's text explaining the restriction.\n"
        "- Cite each condition's source inline.\n"
    ),
    "comparative": (
        "RENDERING — COMPARATIVE QUESTION:\n"
        "- Lay out each option, one per paragraph or one per "
        "bullet, with its recommendation strength and the "
        "evidence that distinguishes it.\n"
        "- Do not pick a winner unless the guideline picks one. "
        "If the guideline is silent on preference, say so.\n"
    ),
    "uncertainty": (
        "RENDERING — UNCERTAINTY QUESTION:\n"
        "- Use a READABLE BULLETED STRUCTURE. No wall-of-text.\n"
        "- Open with a one-sentence lead-in stating what IS "
        "known (the recommendation or current thinking).\n"
        "- Then a 'What is known:' block with bullets drawn "
        "from REC/SYN, cited inline.\n"
        "- Then a 'What remains uncertain:' block with one "
        "bullet per knowledge gap. Use KG content directly. "
        "Do not hedge beyond what the KG block says.\n"
    ),
    "comprehensive": (
        "RENDERING — COMPREHENSIVE QUESTION:\n"
        "- Use a READABLE BULLETED STRUCTURE with short labeled "
        "blocks: 'What is recommended:', 'Why (evidence):', "
        "'What remains uncertain:'. No markdown headers.\n"
        "- Each block is a short list of plain dash bullets (-). "
        "Cite each bullet inline.\n"
    ),
    "prescriptive": (
        "RENDERING — PRESCRIPTIVE QUESTION:\n"
        "- Lead with the direct answer.\n"
        "- Use bullet points (plain dash -) to separate distinct "
        "recommendations or decision points.\n"
        "- Conversational but precise — like a brief consult "
        "answer.\n"
        "- Keep it concise. A busy clinician should grasp the "
        "answer in under 30 seconds of reading.\n"
    ),
}


def _render_rules_for_intent(intent: Optional[str]) -> str:
    """Return the rendering rule block for the intent's family."""
    family = _intent_family(intent)
    return _RENDER_RULES.get(family, _RENDER_RULES["prescriptive"])


_REC_ID_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\((\d+)\)")
_REC_PAREN_RE = re.compile(
    r"\s*\((?:Rec\s+)?(\d+\.\d+(?:\.\d+)?)\((\d+)\)"
    r"[^)]*\)",
)
_REC_INLINE_RE = re.compile(
    r"\bRec\s+(\d+\.\d+(?:\.\d+)?)\((\d+)\)",
)


def _strip_hallucinated_citations(
    summary: str, retrieved: RetrievedContent,
) -> str:
    """Remove any rec ID in the summary that isn't in the retrieved set.

    The LLM sometimes free-types a section number that looks
    plausible but was never in its context — e.g. citing 6.3(3)
    when the retrieved recs were 5.3(3). Post-validate and strip.

    Strategy:
        1. Build the set of valid rec IDs from retrieved.recommendations
           (and semantic_units when they carry a rec id).
        2. Scan the summary for rec-id tokens (X.Y(Z) or X.Y.Z(W)).
        3. For each token whose ID is NOT in the valid set:
             - If wrapped in a parenthetical "(Rec X.Y(Z), COR ...)",
               drop the entire parenthetical.
             - Otherwise drop the bare "Rec X.Y(Z)" prefix, leaving
               surrounding prose untouched.
        4. Log every strip so the test harness can surface the bug.

    Valid rec IDs come only from retrieved content — never invented
    or inferred from section titles.
    """
    valid_ids = set()
    for rec in retrieved.recommendations:
        sec = str(rec.get("section", "")).strip()
        num = str(rec.get("recNumber", "")).strip()
        if sec and num:
            valid_ids.add(f"{sec}({num})")
    for unit in retrieved.semantic_units:
        uid = str(unit.get("id", ""))
        # unit.id looks like "rec.4.3.5" — normalize to "4.3(5)"
        if uid.startswith("rec."):
            bits = uid[len("rec."):].split(".")
            if len(bits) >= 2:
                rec_num = bits[-1]
                sec = ".".join(bits[:-1])
                valid_ids.add(f"{sec}({rec_num})")

    found_tokens = set(
        f"{sec}({num})" for sec, num in _REC_ID_RE.findall(summary)
    )
    bogus = found_tokens - valid_ids
    if not bogus:
        return summary

    logger.warning(
        "Step 4: stripping hallucinated citations %s "
        "(valid set had %d ids)",
        sorted(bogus), len(valid_ids),
    )

    cleaned = summary

    # Pass 1: drop entire parentheticals that contain a bogus id.
    def _paren_sub(match: "re.Match") -> str:
        sec, num = match.group(1), match.group(2)
        if f"{sec}({num})" in bogus:
            return ""
        return match.group(0)

    cleaned = _REC_PAREN_RE.sub(_paren_sub, cleaned)

    # Pass 2: drop bare "Rec X.Y(Z)" prefixes where only the bogus
    # id survives (prior pass already handled parenthetical forms).
    def _inline_sub(match: "re.Match") -> str:
        sec, num = match.group(1), match.group(2)
        if f"{sec}({num})" in bogus:
            return ""
        return match.group(0)

    cleaned = _REC_INLINE_RE.sub(_inline_sub, cleaned)

    # Pass 3: any remaining bare "X.Y(Z)" tokens for bogus ids
    # (no "Rec" prefix, no parenthetical) — strip the token itself.
    def _bare_sub(match: "re.Match") -> str:
        sec, num = match.group(1), match.group(2)
        if f"{sec}({num})" in bogus:
            return ""
        return match.group(0)

    cleaned = _REC_ID_RE.sub(_bare_sub, cleaned)

    # Tidy up double spaces and empty parens left behind.
    cleaned = re.sub(r"\(\s*[,;]?\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)

    return cleaned.strip()


def _fallback_summary(retrieved: RetrievedContent) -> str:
    """Simple summary when LLM is unavailable."""
    parts = []
    if retrieved.recommendations:
        parts.append(
            f"Found {len(retrieved.recommendations)} relevant "
            f"recommendation(s) from {len(retrieved.sections)} section(s)."
        )
    if retrieved.rss:
        parts.append(
            f"Supporting evidence from {len(retrieved.rss)} source(s)."
        )
    if retrieved.knowledge_gaps:
        parts.append("Knowledge gaps noted.")
    if retrieved.semantic_units and not parts:
        parts.append(
            f"Found {len(retrieved.semantic_units)} concept-level "
            f"match(es) in the guideline index."
        )
    return " ".join(parts) if parts else "No relevant content found."
