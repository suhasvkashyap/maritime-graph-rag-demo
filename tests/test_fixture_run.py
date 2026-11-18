"""Fixture-mode scripted runs: acceptance behaviors from the build spec."""

from __future__ import annotations

from tests.conftest import EARLY_CUTOFF, MAIN_QUESTION


class TestDefaultCutoff:
    def test_exactly_c101_overlaps_eight_hours(self, default_result):
        overlaps = default_result.demo_specific_result["overlaps"]
        assert [(o["call_id"], o["overlap_hours"]) for o in overlaps] == [("SYN-C101", 8.0)]

    def test_c103_corrected_window_excludes_overlap(self, default_result):
        pipeline = default_result.demo_specific_result
        corrections = pipeline["corrections_applied"]
        assert any(c["call_id"] == "SYN-C103" and c["status"] == "applied" for c in corrections)
        excluded = {e["call_id"] for e in pipeline["exclusions"]}
        assert "SYN-C103" in excluded

    def test_c102_excluded_by_berth(self, default_result):
        reasons = {e["call_id"]: e["reason"] for e in default_result.demo_specific_result["exclusions"]}
        assert "Berth B2" in reasons["SYN-C102"]

    def test_c104_excluded_by_port_and_group(self, default_result):
        reasons = {e["call_id"]: e["reason"] for e in default_result.demo_specific_result["exclusions"]}
        assert "Port Westhaven" in reasons["SYN-C104"]

    def test_c105_excluded_by_window(self, default_result):
        excluded = {e["call_id"] for e in default_result.demo_specific_result["exclusions"]}
        assert "SYN-C105" in excluded

    def test_shipment_chain_complete(self, default_result):
        rows = {
            r["shipment_id"]: r
            for r in default_result.demo_specific_result["shipments"]
            if r.get("status") == "recorded"
        }
        s101 = rows["SYN-S101"]
        assert s101["call_id"] == "SYN-C101"
        assert s101["recipient"] == "Pelagic Clinic Supply"
        assert s101["facility"] == "Pearl Cold Store"
        assert s101["delivered"] is False

    def test_proposal_pending_not_approved(self, default_result):
        rows = [r for r in default_result.demo_specific_result["shipments"] if r.get("status") == "pending"]
        assert len(rows) == 1
        proposal = rows[0]["proposal"]
        assert proposal["request_id"] == "SYN-RQ11"
        assert proposal["approved"] is False
        assert "terminal-slot confirmation" in proposal["pending_items"][0]

    def test_proposed_alternatives_field(self, default_result):
        proposals = default_result.demo_specific_result["proposed_alternatives"]
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal["request_id"] == "SYN-RQ11"
        assert proposal["facility"] == "Aster Terminal A1"
        assert proposal["approved"] is False
        assert len(proposal["pending_items"]) == 2
        assert proposal["source_id"] == "D11"
        assert proposal["evidence_ids"]

    def test_halcyon_annotation(self, default_result):
        overlaps = default_result.demo_specific_result["overlaps"]
        assert overlaps[0]["operator"] == "Meridian Shelf Shipping"
        assert overlaps[0]["halcyon_subsidiary_operated"] is True

    def test_status_complete_with_claims_and_evidence(self, default_result):
        assert default_result.status.value == "complete"
        assert default_result.claims
        store_ids = {c for claim in default_result.claims for c in claim.evidence_ids}
        assert store_ids  # claims cite evidence
        for claim in default_result.claims:
            for evidence_id in claim.evidence_ids:
                assert evidence_id.startswith("ev-")

    def test_mode_labels(self, default_result):
        assert default_result.agent_mode == "scripted"
        assert default_result.data_mode == "fixture"

    def test_summary_never_claims_delay(self, default_result):
        lowered = default_result.summary.lower()
        assert "delay" not in lowered or "not established" in lowered


class TestEarlierCutoff:
    def test_d09_not_used_and_c103_initial_plan_overlaps(self, early_result):
        pipeline = early_result.demo_specific_result
        assert any("D09" in reason for reason in pipeline["excluded_evidence"])
        overlaps = [(o["call_id"], o["overlap_hours"]) for o in pipeline["overlaps"]]
        assert ("SYN-C101", 8.0) in overlaps
        assert ("SYN-C103", 5.0) in overlaps

    def test_correction_not_applied_at_early_cutoff(self, early_result):
        # D09 is published after this cutoff, so it is excluded from the store
        # entirely: no correction may be applied to SYN-C103.
        pipeline = early_result.demo_specific_result
        assert not any(
            c["call_id"] == "SYN-C103" and c["status"] == "applied"
            for c in pipeline["corrections_applied"]
        )
        assert any("D09" in reason for reason in pipeline["excluded_evidence"])


class TestFailureModes:
    def test_no_match_gives_needs_input(self, fixture_analyst):
        result = fixture_analyst.run("Query the register for dragons", "2026-11-17T12:00:00Z")
        assert result.status.value == "needs_input"
        assert not result.demo_specific_result["effective_calls"]

    def test_backend_failure_is_typed_not_empty_success(self, fixture_analyst):
        result = fixture_analyst.run("Please trigger backend failure for testing", "2026-11-17T12:00:00Z")
        assert result.status.value == "failed"
        retrieval_events = [e for e in result.tool_events if e.tool_name == "retrieve_maritime_relationships"]
        assert retrieval_events and retrieval_events[0].outcome == "error"
        assert any("503" in (event.detail or "") or "unavailable" in (event.detail or "") for event in retrieval_events)


class TestFocusedQuestions:
    def test_amber_shoal_question_shows_exclusion_reason(self, fixture_analyst):
        result = fixture_analyst.run("Why is Amber Shoal not affected?", "2026-11-17T12:00:00Z")
        exclusions = {e["call_id"]: e["reason"] for e in result.demo_specific_result["exclusions"]}
        assert "Berth B2" in exclusions.get("SYN-C102", "")

    def test_identity_question_resolves_without_merge(self, fixture_analyst):
        result = fixture_analyst.run(
            "Is Northline Kestrel the same vessel as Southern Kestrel?", "2026-11-17T12:00:00Z"
        )
        identity_events = [
            e for e in result.tool_events if e.tool_name == "resolve_vessel_identity"
        ]
        assert identity_events  # scripted plan includes identity resolution
        claims_text = " ".join(claim.text for claim in result.claims)
        assert "SYN-V004" in claims_text and "different vessel" in claims_text
