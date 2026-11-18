"""Fixture replay for the Port Impact Investigator tools.

Fixture mode replays the inspected Pattern1 service contract: passages come
from ``fixtures/tool_responses.json`` and the deterministic evaluation runs on
the parsed fixture passages exactly as it does in live mode. Only the
extracted-graph tool returns curated data, clearly labeled ``Expected fixture
graph``. Failures replayed from fixtures stay visibly labeled as fixtures.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shared.contracts import EvidenceItem, Locator, ToolEnvelope, ToolError, parse_utc
from shared.configuration import fixture_path

SECTION_PUBLISHED_AT = {
    "D01": "2026-11-16T09:00:00Z",
    "D02": "2026-11-16T09:15:00Z",
    "D03": "2026-11-16T09:30:00Z",
    "D04": "2026-11-16T10:00:00Z",
    "D05": "2026-11-16T10:15:00Z",
    "D06": "2026-11-16T11:00:00Z",
    "D07": "2026-11-16T11:15:00Z",
    "D08": "2026-11-16T11:30:00Z",
    "D09": "2026-11-17T09:00:00Z",
    "D10": "2026-11-17T10:30:00Z",
    "D11": "2026-11-17T11:00:00Z",
    "D12": "2026-11-16T12:00:00Z",
}


@lru_cache(maxsize=1)
def load_fixtures(path: str | None = None) -> dict:
    file_path = Path(path) if path else fixture_path("tool_responses.json")
    if not file_path.is_file():
        raise ToolError(f"fixture file not found: {file_path}", "backend_unavailable")
    return json.loads(file_path.read_text(encoding="utf-8"))


def service_response_for_query(tool: str, query: str, path: str | None = None) -> dict:
    """Return the canned *service-level* response payload for one query.

    Passage selection models the graph retriever: the impact core (calls,
    closure, correction) is always in the neighborhood, and keyword matches
    add focused sections. All matches are unioned.
    """
    fixtures = load_fixtures(path)
    entry = fixtures[tool]
    responses = entry.get("responses", {})
    lowered = query.lower()
    if "trigger backend failure" in lowered:
        return responses["backend_failure"]
    if "no records exist" in lowered or "query the register for dragons" in lowered:
        return responses["no_match"]

    base = list(entry.get("base_sections", []))
    keyword_sections = entry.get("keyword_sections", {})
    matched: list[str] = []
    for keyword, section_ids in keyword_sections.items():
        if keyword in lowered:
            matched.extend(section_ids)
    if not matched:
        matched = list(entry.get("default_sections", []))
    section_ids = sorted(set(base) | set(matched))
    return _service_payload(section_ids)


def _service_payload(section_ids: list[str]) -> dict:
    from fixtures.corpus_sections import SECTIONS, section_full_text

    by_id = {s.section_id: s for s in SECTIONS}
    evidence = []
    for index, sid in enumerate(section_ids):
        section = by_id[sid]
        evidence.append(
            {
                "text": f"Section {sid} ({section.title}):\n{section_full_text(section)}",
                "metadata": {
                    "document_id": "ami_maritime_graph_corpus.pdf",
                    "section_id": sid,
                    "section_title": section.title,
                    "sequence_number": index,
                    "synthetic": True,
                },
            }
        )
    return {"output_text": "", "evidence": evidence}


def fixture_evidence_items(payload: dict) -> list[EvidenceItem]:
    """Normalize a fixture service payload exactly like the live adapter does."""
    items: list[EvidenceItem] = []
    for index, entry in enumerate(payload.get("evidence") or []):
        metadata = entry.get("metadata") or {}
        section_id = metadata.get("section_id")
        items.append(
            EvidenceItem(
                evidence_id="",
                source_id=section_id or f"doc-{index + 1:02d}",
                source_title=(
                    f"{section_id} {metadata.get('section_title', '')}".strip()
                    if section_id
                    else str(metadata.get("document_id") or "unknown source")
                ),
                locator=Locator(section=section_id),
                excerpt=str(entry.get("text") or ""),
                published_at=parse_utc(SECTION_PUBLISHED_AT.get(section_id or "")),
                synthetic=bool(metadata.get("synthetic", True)),
                origin="fixture",
            )
        )
    return items


def fixture_identity(name_or_id: str, path: str | None = None) -> dict | None:
    lowered = name_or_id.strip().lower()
    responses = load_fixtures(path)["resolve_vessel_identity"]["responses"]
    for key, value in responses.items():
        if key == lowered:
            return value
    return None


def fixture_graph(entity_names: list[str], path: str | None = None) -> dict:
    responses = load_fixtures(path)["get_graph_evidence"]["responses"]
    return responses.get("default") or responses["unavailable"]


__all__ = [
    "fixture_evidence_items",
    "fixture_graph",
    "fixture_identity",
    "load_fixtures",
    "service_response_for_query",
    "ToolEnvelope",
]
