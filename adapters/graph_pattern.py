"""Graph AutoRAG (Pattern1) adapter.

Normalizes the deployed pattern's Responses-style API into the demo's tool
contracts. The pattern runs the actual Graph AutoRAG template (graph search
over the demo Neo4j collection); this adapter only reshapes its response and
extracts relationship assertions deterministically from the returned
passages. It never fabricates metadata the service does not return.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from shared.contracts import ErrorCode, EvidenceItem, Locator, ToolEnvelope, ToolError, parse_utc
from shared.validation import parse_passage


class GraphPatternClient:
    """Client for the local Pattern1 Graph AutoRAG service."""

    def __init__(self, base_url: str, timeout_seconds: float = 45.0):
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        response = httpx.get(f"{self._base_url}/health", timeout=5.0)
        response.raise_for_status()
        return response.json()

    def query(self, question: str) -> tuple[list[EvidenceItem], str]:
        """Run one Graph AutoRAG request; return (evidence, pattern answer)."""
        try:
            response = httpx.post(
                f"{self._base_url}/v1/retrieve",
                json={"input": question},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Graph AutoRAG endpoint error: {type(exc).__name__}",
                ErrorCode.BACKEND_UNAVAILABLE,
            ) from exc

        try:
            payload = response.json()
            answer = str(payload.get("output_text") or "")
            raw_evidence = payload.get("evidence") or []
        except ValueError as exc:
            raise ToolError("Graph AutoRAG returned malformed JSON", ErrorCode.BACKEND_ERROR) from exc

        evidence: list[EvidenceItem] = []
        seen_texts: set[str] = set()
        for index, item in enumerate(raw_evidence):
            text = str(item.get("text") or "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            metadata = item.get("metadata") or {}
            section_id = metadata.get("section_id")
            source_title = (
                f"{section_id} {metadata.get('section_title', '')}".strip()
                if section_id
                else str(metadata.get("document_id") or "unknown source")
            )
            evidence.append(
                EvidenceItem(
                    evidence_id="",  # assigned by the store
                    source_id=section_id or f"doc-{index + 1:02d}",
                    source_title=source_title,
                    source_kind="pdf",
                    locator=Locator(section=section_id),
                    excerpt=text,
                    published_at=SECTION_PUBLISHED_AT.get(section_id or ""),
                    synthetic=True,
                    origin="live",
                )
            )
        return evidence, answer

    def graph_status(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self._base_url}/v1/graph/status", timeout=10.0)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Graph inspection endpoint error: {type(exc).__name__}",
                ErrorCode.BACKEND_UNAVAILABLE,
            ) from exc

    def graph_evidence(self, entity_names: list[str], max_nodes: int = 15, max_edges: int = 20) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self._base_url}/v1/graph/evidence",
                params={"entities": ",".join(entity_names), "max_nodes": max_nodes, "max_edges": max_edges},
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Graph inspection endpoint error: {type(exc).__name__}",
                ErrorCode.BACKEND_UNAVAILABLE,
            ) from exc


# Publication times are fixed properties of the synthetic corpus sections.
# They let the adapter stamp retrieved passages with the issue time the corpus
# itself states; unknown sections stay null and surface a temporal warning.
SECTION_PUBLISHED_AT: dict[str, Any] = {
    "D01": parse_utc("2026-11-16T09:00:00Z"),
    "D02": parse_utc("2026-11-16T09:15:00Z"),
    "D03": parse_utc("2026-11-16T09:30:00Z"),
    "D04": parse_utc("2026-11-16T10:00:00Z"),
    "D05": parse_utc("2026-11-16T10:15:00Z"),
    "D06": parse_utc("2026-11-16T11:00:00Z"),
    "D07": parse_utc("2026-11-16T11:15:00Z"),
    "D08": parse_utc("2026-11-16T11:30:00Z"),
    "D09": parse_utc("2026-11-17T09:00:00Z"),
    "D10": parse_utc("2026-11-17T10:30:00Z"),
    "D11": parse_utc("2026-11-17T11:00:00Z"),
    "D12": parse_utc("2026-11-16T12:00:00Z"),
}

_TRAILING_ISSUED_RE = re.compile(r"\s*Issued \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\.?\s*$")


def passage_excerpts(evidence: list[EvidenceItem]) -> list[tuple[EvidenceItem, str]]:
    """Pair each evidence item with its cleaned, single-line excerpt."""
    pairs = []
    for item in evidence:
        cleaned = _TRAILING_ISSUED_RE.sub("", " ".join(item.excerpt.split()))
        pairs.append((item, cleaned))
    return pairs


__all__ = ["GraphPatternClient", "passage_excerpts", "parse_passage", "SECTION_PUBLISHED_AT"]
