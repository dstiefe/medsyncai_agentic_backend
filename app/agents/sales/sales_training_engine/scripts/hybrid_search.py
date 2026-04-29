"""
Hybrid search for the Sales Training Engine knowledge QA.

Combines keyword matching with vector similarity for document retrieval.
Extracted from knowledge_qa.py — deterministic Python, no LLM calls.
"""

import re
from typing import Dict, List, Optional, Set


def extract_keywords(query: str) -> List[str]:
    """Extract meaningful keywords from a query string."""
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "but", "and",
        "or", "if", "while", "about", "what", "which", "who", "whom", "this",
        "that", "these", "those", "i", "me", "my", "we", "our", "you", "your",
        "it", "its", "they", "them", "their",
    }

    # Tokenize and filter
    words = re.findall(r'\b[a-zA-Z0-9]+\b', query.lower())
    return [w for w in words if w not in stop_words and len(w) > 1]


def keyword_match_chunks(
    keywords: List[str],
    chunks: List[dict],
    filters: Optional[Dict] = None,
    max_results: int = 20,
) -> List[dict]:
    """
    Score chunks by keyword overlap. Returns chunks sorted by match count.

    Args:
        keywords: List of search keywords
        chunks: List of document chunk dicts (must have 'text' field)
        filters: Optional filters (manufacturer, source_type, device_names)
        max_results: Maximum results to return

    Returns:
        Sorted list of (chunk, match_count) tuples
    """
    if not keywords:
        return []

    keyword_set = set(k.lower() for k in keywords)
    scored = []

    for chunk in chunks:
        # Apply filters
        if filters:
            if not _matches_filters(chunk, filters):
                continue

        text = chunk.get("text", "").lower()
        match_count = sum(1 for kw in keyword_set if kw in text)

        if match_count > 0:
            scored.append({"chunk": chunk, "keyword_matches": match_count})

    # Sort by match count descending
    scored.sort(key=lambda x: x["keyword_matches"], reverse=True)
    return scored[:max_results]


def merge_results(
    keyword_results: List[dict],
    vector_results: List[dict],
    keyword_weight: float = 0.3,
    vector_weight: float = 0.7,
    max_results: int = 10,
) -> List[dict]:
    """
    Merge keyword and vector search results with weighted scoring.

    Args:
        keyword_results: Results from keyword_match_chunks
        vector_results: Results from vector retrieval
        keyword_weight: Weight for keyword matches
        vector_weight: Weight for vector similarity
        max_results: Maximum merged results

    Returns:
        Merged and de-duplicated results sorted by combined score
    """
    seen_ids: Set[str] = set()
    merged = {}

    # Process keyword results (normalize to 0-1 by dividing by max)
    max_kw = max((r["keyword_matches"] for r in keyword_results), default=1)
    for r in keyword_results:
        chunk = r["chunk"]
        cid = chunk.get("chunk_id", id(chunk))
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        merged[cid] = {
            "chunk": chunk,
            "keyword_score": r["keyword_matches"] / max_kw * keyword_weight,
            "vector_score": 0.0,
        }

    # Process vector results
    for r in vector_results:
        cid = r.get("chunk_id", id(r))
        vector_score = r.get("score", 0.0) * vector_weight

        if cid in merged:
            merged[cid]["vector_score"] = vector_score
        else:
            merged[cid] = {
                "chunk": r,
                "keyword_score": 0.0,
                "vector_score": vector_score,
            }

    # Compute combined scores and sort
    results = []
    for cid, entry in merged.items():
        entry["combined_score"] = entry["keyword_score"] + entry["vector_score"]
        results.append(entry)

    results.sort(key=lambda x: x["combined_score"], reverse=True)
    return results[:max_results]


def _matches_filters(chunk: dict, filters: Dict) -> bool:
    """Check if a chunk matches the provided filters."""
    if "manufacturer" in filters and filters["manufacturer"]:
        if chunk.get("manufacturer", "").lower() != filters["manufacturer"].lower():
            return False

    if "source_type" in filters and filters["source_type"]:
        if chunk.get("source_type", "").lower() != filters["source_type"].lower():
            return False

    if "device_names" in filters and filters["device_names"]:
        chunk_devices = set(d.lower() for d in chunk.get("device_names", []))
        filter_devices = set(d.lower() for d in filters["device_names"])
        if not chunk_devices & filter_devices:
            return False

    return True
