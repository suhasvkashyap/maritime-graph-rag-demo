"""Identity resolution: aliases with evidence, no cross-vessel merges."""

from __future__ import annotations

from shared.contracts import IdentityAssertion
from shared.validation import resolve_vessel_identity


def identities():
    return [
        IdentityAssertion(
            canonical_id="SYN-V001",
            name="Atlas Kestrel",
            alias_of="Northline Kestrel",
            distinct_from=["SYN-V004"],
            source_id="D01",
            evidence_ids=["ev-001"],
        ),
        IdentityAssertion(
            canonical_id="SYN-V004",
            name="Southern Kestrel",
            source_id="D01",
            evidence_ids=["ev-001"],
        ),
        IdentityAssertion(
            canonical_id="SYN-V001",
            name="Northline Kestrel",  # position report used the former name
            source_id="D10",
            evidence_ids=["ev-002"],
        ),
    ]


class TestResolveIdentity:
    def test_alias_resolves_to_canonical(self):
        resolution = resolve_vessel_identity("Northline Kestrel", identities())
        assert resolution.canonical_id == "SYN-V001"
        assert "Northline Kestrel" in resolution.aliases

    def test_old_name_does_not_create_new_vessel(self):
        resolution = resolve_vessel_identity("Northline Kestrel", identities())
        # Same vessel: exactly one canonical ID.
        assert resolution.canonical_id == "SYN-V001"

    def test_similar_name_does_not_merge(self):
        resolution = resolve_vessel_identity("Southern Kestrel", identities())
        assert resolution.canonical_id == "SYN-V004"
        assert "SYN-V001" in resolution.distinct_from

    def test_id_lookup(self):
        resolution = resolve_vessel_identity("SYN-V001", identities())
        assert resolution.resolved_name == "Atlas Kestrel"

    def test_unknown_name_unresolved(self):
        resolution = resolve_vessel_identity("Flying Dutchman", identities())
        assert resolution.canonical_id is None
        assert "no supported identity assertion" in resolution.reason

    def test_resolution_respects_cited_evidence(self):
        # Only D10 evidence cited: the alias fact from D01 is not available.
        resolution = resolve_vessel_identity("Northline Kestrel", identities(), {"ev-002"})
        assert resolution.canonical_id == "SYN-V001"  # D10 records the name on SYN-V001
        assert "Northline Kestrel" not in resolution.aliases  # but the alias fact is not cited
