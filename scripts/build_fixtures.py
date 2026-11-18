"""Build fixtures/tool_responses.json from the corpus source of truth.

Fixtures replay the *inspected service contract* (the Pattern1 Responses
payload shape), so the adapter normalization path is exercised in fixture
mode too. Fixture passages carry the same synthetic banner and section
structure the live service returns. Run after changing the corpus:

    .venv/bin/python scripts/build_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fixtures.corpus_sections import SECTIONS, section_full_text  # noqa: E402

OUT = ROOT / "fixtures" / "tool_responses.json"


def service_evidence(section_ids: list[str]) -> list[dict]:
    by_id = {s.section_id: s for s in SECTIONS}
    return [
        {
            "text": f"Section {sid} ({by_id[sid].title}):\n{section_full_text(by_id[sid])}",
            "metadata": {
                "document_id": "ami_maritime_graph_corpus.pdf",
                "section_id": sid,
                "section_title": by_id[sid].title,
                "sequence_number": index,
                "synthetic": True,
            },
        }
        for index, sid in enumerate(section_ids)
    ]


def retrieval(answer: str, section_ids: list[str]) -> dict:
    return {
        "output_text": answer,
        "evidence": service_evidence(section_ids),
    }


DEFAULT_SECTIONS = ["D04", "D06", "D09", "D02", "D07", "D12", "D11", "D01"]

FIXTURES: dict = {
    "_meta": {
        "classification": "synthetic",
        "description": (
            "Fixture replay of the Pattern1 Graph AutoRAG service contract for the AMI "
            "Port Impact Investigator. All data is fictional exercise data."
        ),
        "corpus": "fixtures/corpus_sections.py",
    },
    "retrieve_maritime_relationships": {
        "base_sections": ["D04", "D06", "D09"],
        "keyword_sections": {
            "amber shoal": ["D02", "D05"],
            "southern kestrel": ["D01", "D10", "D03"],
            "northline": ["D01", "D10"],
            "approved": ["D11", "D08"],
            "proposal": ["D11", "D08"],
            "shipment": ["D07", "D12", "D11"],
            "identity": ["D01", "D10"],
            "operator": ["D02", "D03"],
            "group": ["D02", "D03"],
            "halcyon": ["D02", "D03"],
        },
        "default_sections": ["D02", "D07", "D12", "D11", "D01"],
        "responses": {
            "default": retrieval(
                "The register lists five planned calls and the SYN-N017 closure of Berth B4. "
                "Call SYN-C101 is at Berth B4 on November 18 from 09:00 to 17:00 UTC, which "
                "falls inside the closure window.",
                DEFAULT_SECTIONS,
            ),
            "no_match": {
                "output_text": "I cannot answer from the provided context documents.",
                "evidence": [],
            },
            "backend_failure": {
                "status_code": 503,
                "body": {"error": "upstream retrieval service unavailable"},
            },
        },
    },
    "resolve_vessel_identity": {
        "responses": {
            "atlas kestrel": {
                "canonical_id": "SYN-V001",
                "resolved_name": "Atlas Kestrel",
                "aliases": ["Northline Kestrel"],
                "distinct_from": ["SYN-V004"],
            },
            "syn-v001": {
                "canonical_id": "SYN-V001",
                "resolved_name": "Atlas Kestrel",
                "aliases": ["Northline Kestrel"],
                "distinct_from": ["SYN-V004"],
            },
            "southern kestrel": {
                "canonical_id": "SYN-V004",
                "resolved_name": "Southern Kestrel",
                "aliases": [],
                "distinct_from": ["SYN-V001"],
            },
        }
    },
    "get_graph_evidence": {
        "graph_label": "expected_fixture",
        "responses": {
            "default": {
                "collection": "fixture://ami-demo3",
                "nodes": [
                    {"name": "Halcyon Maritime Group", "type_labels": ["Organization"]},
                    {"name": "Meridian Shelf Shipping", "type_labels": ["Organization"]},
                    {"name": "Bluewater Reach Logistics", "type_labels": ["Organization"]},
                    {"name": "SYN-V001", "type_labels": ["Product"]},
                    {"name": "SYN-V003", "type_labels": ["Product"]},
                    {"name": "SYN-C101", "type_labels": ["Event"]},
                    {"name": "SYN-C103", "type_labels": ["Event"]},
                    {"name": "SYN-B04", "type_labels": ["Place"]},
                    {"name": "SYN-N017", "type_labels": ["Event"]},
                    {"name": "SYN-S101", "type_labels": ["Product"]},
                    {"name": "Pelagic Clinic Supply", "type_labels": ["Organization"]},
                    {"name": "Pearl Cold Store", "type_labels": ["Place"]},
                ],
                "edges": [
                    {"source": "Meridian Shelf Shipping", "relationship": "PART_OF", "target": "Halcyon Maritime Group", "chunks": []},
                    {"source": "Bluewater Reach Logistics", "relationship": "PART_OF", "target": "Halcyon Maritime Group", "chunks": []},
                    {"source": "SYN-V001", "relationship": "RELATED_TO", "target": "Meridian Shelf Shipping", "chunks": []},
                    {"source": "SYN-V003", "relationship": "RELATED_TO", "target": "Bluewater Reach Logistics", "chunks": []},
                    {"source": "SYN-C101", "relationship": "LOCATED_IN", "target": "SYN-B04", "chunks": []},
                    {"source": "SYN-C103", "relationship": "LOCATED_IN", "target": "SYN-B04", "chunks": []},
                    {"source": "SYN-N017", "relationship": "RELATED_TO", "target": "SYN-B04", "chunks": []},
                    {"source": "SYN-C101", "relationship": "MENTIONS", "target": "SYN-S101", "chunks": []},
                    {"source": "SYN-S101", "relationship": "RELATED_TO", "target": "Pelagic Clinic Supply", "chunks": []},
                    {"source": "SYN-S101", "relationship": "RELATED_TO", "target": "Pearl Cold Store", "chunks": []},
                ],
                "matched_seeds": ["syn-g01", "syn-v001", "syn-c101", "syn-b04", "syn-n017", "syn-s101"],
                "unmatched": [],
            },
            "unavailable": {
                "collection": "fixture://ami-demo3",
                "nodes": [],
                "edges": [],
                "matched_seeds": [],
                "unmatched": [],
            },
        },
    },
}


def main() -> int:
    OUT.write_text(json.dumps(FIXTURES, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
