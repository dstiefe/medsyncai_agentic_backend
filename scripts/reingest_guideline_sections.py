"""
Section-aware re-ingestion of the 2026 AHA/ASA AIS Guideline PDF.

Re-parses each prose section directly from the source PDF, extracting
each sub-unit (synopsis, numbered RSS items, knowledge gaps) one at a
time by section-boundary markers. No page-range chunking — content
cannot be truncated at page transitions because boundaries are driven
by section/item markers in the text, not by page numbers.

Usage:
    python scripts/reingest_guideline_sections.py 2.1 2.2 2.3 ...

Arguments are section IDs. Each ID is looked up against the PDF text,
its content span extracted, sub-structure parsed, and the result
written to guideline_knowledge.json.sections[id].

Pass --dry-run to print the parsed output without writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import PyPDF2


PDF_PATH = "/Users/MFS/Desktop/2026 AIS Guidelines.pdf"
REPO_ROOT = Path(__file__).resolve().parent.parent
GK_PATH = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/data/guideline_knowledge.json"


# ──────────────────────────────────────────────────────────────────
# PDF text loading
# ──────────────────────────────────────────────────────────────────

_pdf_cache: str | None = None


def load_pdf_text() -> str:
    """Load the entire PDF as one concatenated text blob, cached."""
    global _pdf_cache
    if _pdf_cache is None:
        pdf = PyPDF2.PdfReader(PDF_PATH)
        parts = []
        for page in pdf.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        _pdf_cache = "\n\n".join(parts)
    return _pdf_cache


# ──────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────

_PAGE_HEADER_PATTERNS = [
    r"CLINICAL STATEMENTS\s*\n\s*AND\s*GUIDELINES?\w*",
    r"TBD 2026\s*Stroke\.\s*2026;57:e00[^\n]*",
    r"DOI:\s*10\.1161/STR[^\n]*",
    # No trailing \w* — that was eating the first word of the next line
    r"Prabhakaran et al 2026 Acute Ischemic Stroke Guideline",
    r"Downloaded from http://ahajournals\.org[^\n]*",
    r"e\d+\s*\u2003?\s*\u2002?\s*TBD 2026",
    r"\x08",
]

# Residual journal citation stubs that survive the first header pass
# ("Stroke. 2026;57:e00-e00." appearing mid-text as a page-break leak)
_CITATION_STUB = re.compile(r"\s*\.\s*2026;57:e00[–-]e00\.\s*")
_STROKE_CITATION_STUB = re.compile(r"\s*Stroke\.\s*2026;57:e00[–-]e00\.\s*")

# Known compound over-merges from PyPDF2 soft-hyphen line-wraps
_COMPOUND_FIXES = [
    ("PlateletOriented", "Platelet-Oriented"),
    ("shortterm", "short-term"),
    ("longterm", "long-term"),
    ("highrisk", "high-risk"),
    ("metaanalysis", "meta-analysis"),
    ("openlabel", "open-label"),
    ("noninferiority", "noninferiority"),  # legitimate
    ("lowrisk", "low-risk"),
    ("followup", "follow-up"),
    ("evidencebased", "evidence-based"),
    ("doseresponse", "dose-response"),
    ("doubleblind", "double-blind"),
    ("singleblind", "single-blind"),
    ("longacting", "long-acting"),
    ("shortacting", "short-acting"),
    ("timesensitive", "time-sensitive"),
    ("healthcare", "health care"),
    ("realworld", "real-world"),
    ("preexisting", "pre-existing"),
    ("postprocessing", "post-processing"),
    ("posttreatment", "post-treatment"),
    ("intraarterial", "intra-arterial"),
    ("intraaxial", "intra-axial"),
    ("intracardiac", "intracardiac"),  # legitimate
    ("smallvessel", "small-vessel"),
    ("largevessel", "large-vessel"),
    ("rtPA", "rt-PA"),
    ("tPA", "tPA"),
]


# Generic pattern for an embedded Figure/Table caption block with its
# abbreviation legend. These get page-inlined into adjacent prose
# sections' synopsis content and need to be stripped post-parse.
#
# The guideline's figure/table captions always follow the pattern:
#   "Figure N. Title. ACR indicates word; ABC, y; ...; and XYZ, word."
# The legend starts with "indicates" and ends with a final
# "and XYZ, word word word." pattern. Using .*? with DOTALL keeps the
# match non-greedy so we don't over-reach into the next section.
_FIGURE_CAPTION_RE = re.compile(
    r"(?:Figure|Table)\s+\d+\.\s.*?indicates\s.*?\band\s+[A-Z][A-Za-z0-9]*(?:\s+\d)?,[^.]+\.",
    re.DOTALL,
)


def _strip_figure_captions(text: str) -> str:
    """Remove embedded Figure/Table caption + abbreviation legend blocks."""
    if not text:
        return text
    # Run iteratively to catch multiple captions in one block
    prev = None
    while prev != text:
        prev = text
        text = _FIGURE_CAPTION_RE.sub(" ", text)
    # Collapse whitespace the substitution left behind
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def clean_page_artifacts(blob: str) -> str:
    """Strip PDF page headers, footers, and line-continuation hyphens."""
    # Step 1: line-continuation hyphens while newlines still present
    # Pattern A: "word-\nword" (no spaces) → join, drop hyphen
    blob = re.sub(r"([a-zA-Z])-\s*\n\s*([a-zA-Z])", r"\1\2", blob)
    # Pattern B: "word - \nword" (space-hyphen-space-newline) → join
    blob = re.sub(r"([a-zA-Z])\s+-\s*\n\s*([a-zA-Z])", r"\1\2", blob)

    # Step 2: strip page headers
    for pat in _PAGE_HEADER_PATTERNS:
        blob = re.sub(pat, " ", blob)

    # Step 3: collapse newlines to spaces
    blob = re.sub(r"\n(?!\n)", " ", blob)
    blob = re.sub(r"\s+", " ", blob).strip()

    # Step 4: residual "word - word" artifacts (PyPDF2 hyphen gap with spaces)
    blob = re.sub(r"([a-z])\s+-\s+([a-z])", r"\1\2", blob)

    # Step 5: strip residual journal citation stubs
    blob = _STROKE_CITATION_STUB.sub(" ", blob)
    blob = _CITATION_STUB.sub(" ", blob)

    # Step 6: apply known-compound fixes
    for bad, good in _COMPOUND_FIXES:
        if bad != good:
            blob = blob.replace(bad, good)

    # Step 7: normalize section-header rendering quirks.
    # PyPDF2 sometimes renders "2.7 . Title" with a space between
    # the section number and its trailing period. Match "N.M" or
    # "N.M.K" followed by " . " and collapse to "N.M. ".
    blob = re.sub(r"(\b\d+\.\d+(?:\.\d+)?)\s+\.\s", r"\1. ", blob)

    # Collapse whitespace after all substitutions
    blob = re.sub(r"\s{2,}", " ", blob).strip()
    return blob


# ──────────────────────────────────────────────────────────────────
# Section boundary detection
# ──────────────────────────────────────────────────────────────────

# A section header in the PDF looks like: "N.M.K  Title" or "N.M  Title"
# or "N.M.K. Title" depending on the version. PyPDF2 output sometimes
# collapses the number and title together or adds a space.

# PDF titles for sections whose ais_guideline_section_map.json title
# does not exactly match the printed PDF heading. Authoritative.
_PDF_TITLE_OVERRIDES: dict[str, str] = {
    "3.2":   "Initial, Vascular, and Multimodal Imaging Approaches",
    "4.7.1": "Concomitant With IVT",
    "4.7.2": "Endovascular Thrombectomy for Adult Patients",
    "4.7.5": "Endovascular Thrombectomy in Pediatric Patients",
    "4.10":  "Volume Expansion/Hemodilution, Vasodilators, and Hemodynamic Augmentation",
}


def _all_header_positions(blob: str, section_id: str, title: str) -> list[int]:
    """Return every position where '{id}. {title}' (or a close variant)
    appears in the blob. Each section header typically appears 3-4
    times: TOC, executive summary, body, and references section.

    Matches on the section id + a title prefix so sections whose
    PDF title has a parenthetical suffix ('Emergency Evaluation of
    Patients With Suspected Stroke (Including ED...)') still match
    against a shorter title in the section map.
    """
    # Prefer the authoritative PDF title if we have an override
    if section_id in _PDF_TITLE_OVERRIDES:
        title = _PDF_TITLE_OVERRIDES[section_id]
    positions: list[int] = []

    # First try the exact combos
    for c in (f"{section_id}. {title}", f"{section_id} {title}"):
        start = 0
        while True:
            idx = blob.find(c, start)
            if idx < 0:
                break
            if idx not in positions:
                positions.append(idx)
            start = idx + 1

    # Title-prefix fallback: match the section id followed by the
    # first few words of the title. Use the first 25 chars of the
    # title (or all of it if shorter) so truncated section-map
    # titles still hit the full PDF heading.
    if not positions:
        title_prefix = title[:25].strip()
        if title_prefix:
            id_esc = re.escape(section_id)
            pref_esc = re.escape(title_prefix)
            pat = rf"\b{id_esc}\.?\s+{pref_esc}"
            for m in re.finditer(pat, blob):
                if m.start() not in positions:
                    positions.append(m.start())

    positions.sort()
    return positions


def find_section_start(blob: str, section_id: str, title: str) -> int:
    """Find the BODY occurrence of a section in the cleaned blob.

    Each section header appears 3-4 times in the PDF: table of
    contents (followed by dot leaders), executive summary (followed
    by a condensed COR/LOE table), the actual section body (followed
    by 'Recommendations for {title}' and/or 'Synopsis'), and the
    references section (followed by a numbered citation list).

    This picks the body occurrence by scoring each candidate on how
    close it is to a 'Synopsis' or 'Recommendations for {title}' or
    'Recommendation-Specific Supportive Text' marker. The closest
    match wins.
    """
    positions = _all_header_positions(blob, section_id, title)
    if not positions:
        return -1

    # Use the PDF-authoritative title for body-marker search
    pdf_title = _PDF_TITLE_OVERRIDES.get(section_id, title)

    # For each position, check whether the body markers appear close by.
    # The body occurrence will have "Recommendations for {title}" OR
    # "Synopsis" OR "Recommendation-Specific Supportive Text" within
    # a small window — typically the header is immediately followed by
    # "Recommendations for {title}".
    body_markers = [
        (f"Recommendations for {pdf_title}", 500),
        (f"Recommendations For {pdf_title}", 500),
        (f"Recommendation for {pdf_title}", 500),  # some sections singular
        ("Synopsis ", 6000),
        ("Recommendation-Specific Supportive Text", 20000),
    ]

    best_pos = -1
    best_score = float("inf")
    for pos in positions:
        for marker, window in body_markers:
            marker_idx = blob.find(marker, pos, pos + window)
            if marker_idx >= 0:
                distance = marker_idx - pos
                if distance < best_score:
                    best_score = distance
                    best_pos = pos
                break  # first matching marker for this position wins

    if best_pos >= 0:
        return best_pos

    # Fallback: skip the first position (TOC) and return the next one.
    # Rarely needed — sections with no synopsis/RST do exist (chapter 1
    # introductory subsections), but those are usually skipped anyway.
    if len(positions) >= 2:
        return positions[1]
    return positions[0]


def find_next_section_start(blob: str, current_id: str, all_sections: list[tuple[str, str]]) -> int:
    """Find the start of the next section after current_id in the blob.

    all_sections is the ordered list of (id, title). Returns the position
    of the nearest subsequent section that can be located, or len(blob)
    if nothing comes after.
    """
    current_start = find_section_start(blob, current_id, dict(all_sections)[current_id])
    if current_start < 0:
        return len(blob)

    # Look for any subsequent section id that appears AFTER current_start
    best = len(blob)
    current_index = next((i for i, (sid, _) in enumerate(all_sections) if sid == current_id), -1)
    if current_index < 0:
        return best
    for sid, title in all_sections[current_index + 1:]:
        pos = find_section_start(blob, sid, title)
        if pos > current_start and pos < best:
            best = pos
    return best


# ──────────────────────────────────────────────────────────────────
# Sub-structure parsing
# ──────────────────────────────────────────────────────────────────

def extract_synopsis(span: str) -> str:
    """Extract the synopsis block from a section span."""
    syn_start = span.find("Synopsis ")
    if syn_start < 0:
        syn_start = span.find("Synopsis\n")
        if syn_start < 0:
            return ""
    # Synopsis ends at "Recommendation-Specific Supportive Text" or
    # "Knowledge Gaps" or the end of the span.
    ends = []
    for marker in ["Recommendation-Specific Supportive Text",
                   "Recommendation Specific Supportive Text",
                   "Knowledge Gaps and Future Research",
                   "Knowledge Gaps"]:
        pos = span.find(marker, syn_start + 1)
        if pos > 0:
            ends.append(pos)
    end = min(ends) if ends else len(span)
    return span[syn_start + len("Synopsis "):end].strip()


def extract_rst_block(span: str) -> str:
    """Extract the Recommendation-Specific Supportive Text block."""
    for marker in ["Recommendation-Specific Supportive Text",
                   "Recommendation Specific Supportive Text"]:
        rst_start = span.find(marker)
        if rst_start >= 0:
            break
    else:
        return ""
    # RST ends at Knowledge Gaps or end of span
    ends = []
    for marker in ["Knowledge Gaps and Future Research", "Knowledge Gaps"]:
        pos = span.find(marker, rst_start + 1)
        if pos > 0:
            ends.append(pos)
    end = min(ends) if ends else len(span)
    return span[rst_start + len("Recommendation-Specific Supportive Text"):end].strip()


_REFERENCES_MARKERS = [
    "References 1.",
    "ARTICLE INFORMATION",
    "Acknowledgments",
]


def extract_kg_block(span: str) -> str:
    """Extract the Knowledge Gaps block.

    Bounded at the end of §6.5 (the last clinical section) by the
    References / Acknowledgments section, so §6.5 doesn't swallow
    the entire rest of the document.
    """
    for marker in ["Knowledge Gaps and Future Research", "Knowledge Gaps"]:
        kg_start = span.find(marker)
        if kg_start >= 0:
            kg_text = span[kg_start + len(marker):]
            # Bound at References / Acknowledgments if present
            min_end = len(kg_text)
            for ref_marker in _REFERENCES_MARKERS:
                idx = kg_text.find(ref_marker)
                if idx >= 0 and idx < min_end:
                    min_end = idx
            return kg_text[:min_end].strip()
    return ""


_ITEM_RE = re.compile(r"(?:(?<=\s)|(?<=\.))(\d{1,2})\s*\.\s+(?=[A-Z])")


def split_rss_items(rst_block: str) -> list[tuple[int, str]]:
    """Split an RST block into numbered supportive-text items.

    Returns [(item_number, item_text), ...] with contiguous monotonic
    numbering. Items are separated by " N. " markers where N is 1..20
    followed by a capital letter.
    """
    if not rst_block:
        return []

    # Prepend a space so item 1 (at start) is reachable by the lookbehind
    working = " " + rst_block

    matches = list(_ITEM_RE.finditer(working))

    # Strict monotonic filter: accept only when num == expected.
    # This rejects false positives like "median values of 6 and 7" that
    # would otherwise be mistaken for item markers, because they'll
    # fail the exact-match check. If a legitimate later match arrives
    # for the currently-expected number, it's still accepted.
    valid = []
    expected = 1
    for m in matches:
        num = int(m.group(1))
        if num == expected:
            valid.append(m)
            expected += 1

    items = []
    for i, m in enumerate(valid):
        num = int(m.group(1))
        start = m.end()
        end = valid[i + 1].start() if i + 1 < len(valid) else len(working)
        text = working[start:end].strip()
        items.append((num, text))
    return items


# ──────────────────────────────────────────────────────────────────
# Main per-section extraction
# ──────────────────────────────────────────────────────────────────

def extract_section(section_id: str, title: str, all_sections: list[tuple[str, str]]) -> dict:
    """Extract the content for a single section from the PDF.

    Returns a dict with synopsis, rss, knowledgeGaps, sectionTitle.
    """
    raw_blob = load_pdf_text()
    cleaned = clean_page_artifacts(raw_blob)

    start = find_section_start(cleaned, section_id, title)
    if start < 0:
        return {
            "sectionTitle": title,
            "synopsis": "",
            "rss": [],
            "knowledgeGaps": "",
            "_error": f"section start not found for id={section_id!r} title={title!r}",
        }

    end = find_next_section_start(cleaned, section_id, all_sections)
    span = cleaned[start:end]

    synopsis = extract_synopsis(span)
    rst_block = extract_rst_block(span)
    kg_block = extract_kg_block(span)

    # Build rss rows
    items = split_rss_items(rst_block)
    rss = [
        {"recNumber": str(num), "category": "", "condition": "", "text": text}
        for num, text in items
    ]

    # Post-process: strip any embedded Figure/Table caption blocks.
    # These get page-inlined from adjacent structural units.
    synopsis = _strip_figure_captions(synopsis)
    kg_block = _strip_figure_captions(kg_block)
    for row in rss:
        row["text"] = _strip_figure_captions(row["text"])

    return {
        "sectionTitle": title,
        "synopsis": synopsis,
        "rss": rss,
        "knowledgeGaps": kg_block,
    }


# ──────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────

def validate(section_id: str, parsed: dict) -> list[str]:
    """Return a list of validation warnings for a parsed section."""
    warnings = []
    if parsed.get("_error"):
        warnings.append(f"EXTRACTION ERROR: {parsed['_error']}")
        return warnings

    # Residual page-header / citation artifacts
    all_text = parsed["synopsis"] + " ".join(r["text"] for r in parsed["rss"]) + parsed["knowledgeGaps"]
    for pat, label in [
        (r"2026;57", "journal citation stub"),
        (r"CLINICAL STATEMENTS", "page header"),
        (r"DOI: 10\.1161", "DOI header"),
        (r"TBD 2026", "TBD 2026 page marker"),
        (r"Downloaded from http://ahajournals", "page footer"),
    ]:
        if re.search(pat, all_text):
            warnings.append(f"residual {label} in {section_id}")

    # Sanity: synopsis should not be implausibly short or long
    syn_len = len(parsed["synopsis"])
    if 0 < syn_len < 50:
        warnings.append(f"{section_id}: synopsis suspiciously short ({syn_len} chars)")
    if syn_len > 20000:
        warnings.append(f"{section_id}: synopsis suspiciously long ({syn_len} chars) — possible section boundary miss")

    # Item numbering should be contiguous 1..N
    if parsed["rss"]:
        nums = [int(r["recNumber"]) for r in parsed["rss"]]
        if nums != list(range(1, max(nums) + 1)):
            warnings.append(f"{section_id}: non-contiguous rss numbering {nums}")

    return warnings


# ──────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────

def load_section_map() -> list[tuple[str, str]]:
    """Load the flat ordered list of (id, title) from the section map."""
    sm_path = REPO_ROOT / "app/agents/clinical/ais_clinical_engine/agents/qa_v4/references/ais_guideline_section_map.json"
    with open(sm_path) as f:
        sm = json.load(f)

    def walk(entries):
        result = []
        for e in entries:
            sid = e.get("id", "")
            title = e.get("title", "")
            if sid and title:
                result.append((sid, title))
            for sub in e.get("subsections", []) or []:
                result.extend(walk([sub]))
        return result

    return walk(sm.get("sections", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("section_ids", nargs="+", help="Section IDs to re-ingest (e.g. 2.1 2.2 2.3)")
    ap.add_argument("--dry-run", action="store_true", help="Print parsed output, do not write")
    args = ap.parse_args()

    all_sections = load_section_map()
    id_to_title = dict(all_sections)

    with open(GK_PATH) as f:
        gk = json.load(f)

    warnings_all = []
    for sid in args.section_ids:
        title = id_to_title.get(sid)
        if not title:
            print(f"[{sid}] NOT IN SECTION MAP — skipping")
            continue
        parsed = extract_section(sid, title, all_sections)
        warns = validate(sid, parsed)
        warnings_all.extend(warns)

        syn_len = len(parsed["synopsis"])
        rss_count = len(parsed["rss"])
        kg_len = len(parsed["knowledgeGaps"])
        flag = "OK" if not warns else "WARN"
        print(f"[{sid}] {flag}  synopsis={syn_len:>5} rss={rss_count:>2} kg={kg_len:>5}  {title[:50]}")
        for w in warns:
            print(f"    ! {w}")

        if not args.dry_run and not parsed.get("_error"):
            gk["sections"][sid] = {
                "sectionTitle": parsed["sectionTitle"],
                "synopsis": parsed["synopsis"],
                "rss": parsed["rss"],
                "knowledgeGaps": parsed["knowledgeGaps"],
            }

    if not args.dry_run:
        with open(GK_PATH, "w") as f:
            json.dump(gk, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {GK_PATH}")

    print(f"\nTotal warnings across all sections: {len(warnings_all)}")


if __name__ == "__main__":
    main()
