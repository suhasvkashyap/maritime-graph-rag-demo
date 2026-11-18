"""Exports: the impact brief and the run record."""

from __future__ import annotations

import json

from shared.contracts import FinalResult
from shared.exports import build_impact_brief, build_run_record


class TestImpactBrief:
    def test_contains_call_table_and_verdicts(self, default_result):
        brief = build_impact_brief(default_result)
        assert "SYN-C101" in brief
        assert "OVERLAP" in brief
        assert "8.0 h planned occupancy" in brief
        assert "SYN-C102" in brief and "Berth B2" in brief
        assert "Pearl Cold Store" in brief
        assert "No operational" in brief or "no operational" in brief.lower() or "advisory only" in brief

    def test_contains_evidence_and_citations(self, default_result):
        brief = build_impact_brief(default_result)
        assert "## Claims" in brief
        assert "deterministic_derivation" in brief
        assert "ev-0" in brief

    def test_contains_warnings_section_when_warnings_exist(self, default_result):
        brief = build_impact_brief(default_result)
        assert "## Warnings" in brief or default_result.warnings == []

    def test_labels_mode(self, default_result):
        brief = build_impact_brief(default_result)
        assert "scripted" in brief and "fixture" in brief


class TestRunRecord:
    def test_round_trip(self, default_result):
        payload = build_run_record(default_result)
        data = json.loads(payload)
        restored = FinalResult.model_validate(data)
        assert restored.run_id == default_result.run_id
        assert len(restored.claims) == len(default_result.claims)
        assert restored.demo_specific_result["overlaps"] == default_result.demo_specific_result["overlaps"]
