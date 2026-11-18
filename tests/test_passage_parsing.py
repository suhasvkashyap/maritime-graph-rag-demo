"""Passage parsing across the whole corpus and the evidence store."""

from __future__ import annotations

import pytest

from fixtures.corpus_sections import SECTIONS, section_full_text
from shared.contracts import EvidenceItem, Locator, parse_utc
from shared.evidence import EvidenceStore
from shared.validation import parse_passage


def all_facts():
    return [
        parse_passage(
            f"Section {s.section_id} ({s.title}):\n{section_full_text(s)}",
            s.section_id,
            [f"ev-{i + 1:03d}"],
            parse_utc(s.published_at),
        )
        for i, s in enumerate(SECTIONS)
    ]


class TestCorpusParsing:
    def test_five_calls_parsed(self):
        calls = {}
        for facts in all_facts():
            for call in facts.calls:
                calls[call.call_id] = call
        assert set(calls) == {"SYN-C101", "SYN-C102", "SYN-C103", "SYN-C104", "SYN-C105"}

    def test_c101_window(self):
        facts = next(f for f in all_facts() if f.source_id == "D04")
        c101 = next(c for c in facts.calls if c.call_id == "SYN-C101")
        assert c101.window.start.isoformat() == "2026-11-18T09:00:00+00:00"
        assert c101.window.end.isoformat() == "2026-11-18T17:00:00+00:00"
        assert c101.berth_id == "SYN-B04"
        assert c101.vessel_id == "SYN-V001"

    def test_c104_has_port_not_berth_id(self):
        facts = next(f for f in all_facts() if f.source_id == "D04")
        c104 = next(c for c in facts.calls if c.call_id == "SYN-C104")
        assert c104.port == "Port Westhaven"
        assert c104.berth_id is None

    def test_notice_window(self):
        facts = next(f for f in all_facts() if f.source_id == "D06")
        notice = facts.notices[0]
        assert notice.notice_id == "SYN-N017"
        assert notice.berth_id == "SYN-B04"
        assert notice.window.start.hour == 8 and notice.window.end.hour == 20

    def test_correction_window(self):
        facts = next(f for f in all_facts() if f.source_id == "D09")
        correction = facts.corrections[0]
        assert correction.call_id == "SYN-C103"
        assert correction.new_window.start.hour == 21
        assert correction.published_at is not None

    def test_operator_relationships(self):
        relationships = []
        for facts in all_facts():
            relationships.extend(facts.relationships)
        operated = {(r.source_entity, r.target_entity) for r in relationships if r.relationship == "operated_by"}
        assert ("SYN-V001", "Meridian Shelf Shipping") in operated
        assert ("SYN-V004", "Copper Bay Carriers") in operated

    def test_subsidiary_relationships(self):
        relationships = []
        for facts in all_facts():
            relationships.extend(facts.relationships)
        subsidiaries = {(r.source_entity, r.target_entity) for r in relationships if r.relationship == "subsidiary_of"}
        assert ("SYN-O01", "Halcyon Maritime Group") in subsidiaries
        assert ("SYN-O02", "Halcyon Maritime Group") in subsidiaries

    def test_berth_port_map(self):
        mapping = {}
        for facts in all_facts():
            mapping.update(facts.berth_ports)
        assert mapping["Berth B4"] == "Port Lumen"
        assert mapping["Berth B2"] == "Port Lumen"
        assert mapping["Berth W1"] == "Port Westhaven"

    def test_shipment_chains(self):
        links = []
        for facts in all_facts():
            links.extend(facts.shipments)
        by_shipment = {}
        for link in links:
            by_shipment.setdefault(link.shipment_id, link)
        assert by_shipment["SYN-S101"].call_id == "SYN-C101"
        assert by_shipment["SYN-S101"].recipient == "Pelagic Clinic Supply"


class TestEvidenceStore:
    def _item(self, section_id: str, published: str, store: EvidenceStore) -> EvidenceItem:
        section = next(s for s in SECTIONS if s.section_id == section_id)
        return EvidenceItem(
            evidence_id="",
            source_id=section_id,
            source_title=f"{section_id} {section.title}",
            locator=Locator(section=section_id),
            excerpt=f"Section {section_id} ({section.title}):\n{section_full_text(section)}",
            published_at=parse_utc(published),
            origin="fixture",
        )

    def test_ids_assigned_in_order(self):
        store = EvidenceStore(as_of=parse_utc("2026-11-17T12:00:00Z"))
        store.add(self._item("D04", "2026-11-16T10:00:00Z", store))
        store.add(self._item("D06", "2026-11-16T11:00:00Z", store))
        assert [item.evidence_id for item in store.items] == ["ev-001", "ev-002"]

    def test_future_evidence_excluded_with_reason(self):
        store = EvidenceStore(as_of=parse_utc("2026-11-16T12:00:00Z"))
        accepted = store.add(self._item("D09", "2026-11-17T09:00:00Z", store))
        assert not accepted
        assert store.excluded_after_cutoff
        reason = store.excluded_after_cutoff[0][1]
        assert "D09" in reason and "cutoff" in reason

    def test_dedup_same_source_and_excerpt(self):
        store = EvidenceStore(as_of=parse_utc("2026-11-17T12:00:00Z"))
        store.add(self._item("D04", "2026-11-16T10:00:00Z", store))
        store.add(self._item("D04", "2026-11-16T10:00:00Z", store))
        assert len(store.items) == 1

    def test_unknown_publication_time_warns(self):
        store = EvidenceStore(as_of=parse_utc("2026-11-17T12:00:00Z"))
        item = self._item("D04", "2026-11-16T10:00:00Z", store)
        item.published_at = None
        store.add(item)
        assert any("temporal coverage" in warning for warning in store.warnings)

    def test_calls_and_corrections_derived(self):
        store = EvidenceStore(as_of=parse_utc("2026-11-17T12:00:00Z"))
        store.add(self._item("D04", "2026-11-16T10:00:00Z", store))
        store.add(self._item("D09", "2026-11-17T09:00:00Z", store))
        calls = store.calls()
        assert set(calls) == {"SYN-C101", "SYN-C102", "SYN-C103", "SYN-C104", "SYN-C105"}
        corrections = store.corrections()
        assert len(corrections) == 1
        assert corrections[0].call_id == "SYN-C103"
