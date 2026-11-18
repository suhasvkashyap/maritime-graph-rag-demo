"""Evidence store for one agent run.

Collects every returned evidence item, assigns stable IDs (ev-001, ...),
keeps source content separate from instructions, and reconstructs typed
maritime records from retrieved passages deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .contracts import (
    CallAssertion,
    ClosureNotice,
    EvidenceItem,
    IdentityAssertion,
    ProposedAlternative,
    RelationshipAssertion,
    ScheduleCorrection,
    ShipmentLink,
)
from .validation import ParsedFacts, parse_passage


@dataclass
class EvidenceStore:
    as_of: datetime
    items: list[EvidenceItem] = field(default_factory=list)
    excluded_after_cutoff: list[tuple[EvidenceItem, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> bool:
        """Add one item; returns False and records an exclusion if published after the cutoff."""
        existing_pairs = {(existing.source_id, existing.excerpt) for existing in self.items}
        if (item.source_id, item.excerpt) in existing_pairs:
            return True  # already stored
        if item.published_at and item.published_at > self.as_of:
            self.excluded_after_cutoff.append(
                (
                    item,
                    f"{item.source_id} published {item.published_at.isoformat()}, after the requested "
                    f"cutoff {self.as_of.isoformat()}; not used in this as-of answer",
                )
            )
            return False
        if not item.evidence_id:
            item.evidence_id = self.next_id()
        if item.published_at is None:
            self.warnings.append(
                f"{item.source_id} has no recorded publication time; temporal coverage at the "
                f"cutoff cannot be verified."
            )
        self.items.append(item)
        return True

    def extend(self, items: list[EvidenceItem]) -> int:
        return sum(1 for item in items if self.add(item))

    def ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}

    def next_id(self) -> str:
        return f"ev-{len(self.items) + 1:03d}"

    # -- derived records (deterministic reconstruction) ---------------------

    def parsed_facts(self) -> list[ParsedFacts]:
        return [
            parse_passage(item.excerpt, item.source_id, [item.evidence_id], item.published_at)
            for item in self.items
        ]

    def calls(self) -> dict[str, CallAssertion]:
        calls: dict[str, CallAssertion] = {}
        for facts in self.parsed_facts():
            for call in facts.calls:
                existing = calls.get(call.call_id)
                if existing is None or existing.window is None:
                    calls[call.call_id] = call
        return calls

    def corrections(self) -> list[ScheduleCorrection]:
        seen: dict[tuple[str, str], ScheduleCorrection] = {}
        for facts in self.parsed_facts():
            for correction in facts.corrections:
                seen.setdefault((correction.correction_id, correction.call_id), correction)
        return list(seen.values())

    def notices(self) -> dict[str, ClosureNotice]:
        notices: dict[str, ClosureNotice] = {}
        for facts in self.parsed_facts():
            for notice in facts.notices:
                notices.setdefault(notice.notice_id, notice)
        return notices

    def shipments(self) -> list[ShipmentLink]:
        links: list[ShipmentLink] = []
        seen: set[tuple[str, str, str]] = set()
        for facts in self.parsed_facts():
            for link in facts.shipments:
                key = (link.call_id, link.shipment_id, link.facility or "")
                if key not in seen:
                    seen.add(key)
                    links.append(link)
        return self._merge_shipment_links(links)

    def _merge_shipment_links(self, links: list[ShipmentLink]) -> list[ShipmentLink]:
        """Merge per-call facts with per-shipment receiving facts."""
        merged: dict[str, ShipmentLink] = {}
        for link in links:
            current = merged.get(link.shipment_id)
            if current is None:
                merged[link.shipment_id] = link
                continue
            merged[link.shipment_id] = ShipmentLink(
                call_id=current.call_id or link.call_id,
                shipment_id=link.shipment_id,
                description=current.description or link.description,
                recipient=current.recipient or link.recipient,
                facility=current.facility or link.facility,
                receipt_deadline=current.receipt_deadline or link.receipt_deadline,
                status=current.status if current.status != "recorded" else link.status,
                source_id="+".join(sorted({current.source_id, link.source_id})),
                evidence_ids=sorted(set(current.evidence_ids) | set(link.evidence_ids)),
            )
        return list(merged.values())

    def proposals(self) -> list[ProposedAlternative]:
        seen: dict[str, ProposedAlternative] = {}
        for facts in self.parsed_facts():
            for proposal in facts.proposals:
                seen.setdefault(proposal.request_id, proposal)
        return list(seen.values())

    def relationships(self) -> list[RelationshipAssertion]:
        seen: dict[tuple[str, str, str], RelationshipAssertion] = {}
        for facts in self.parsed_facts():
            for relationship in facts.relationships:
                key = (relationship.source_entity, relationship.relationship, relationship.target_entity)
                existing = seen.get(key)
                if existing is None:
                    seen[key] = relationship
                else:
                    seen[key] = RelationshipAssertion(
                        source_entity=relationship.source_entity,
                        relationship=relationship.relationship,
                        target_entity=relationship.target_entity,
                        source_id="+".join(sorted({existing.source_id, relationship.source_id})),
                        evidence_ids=sorted(set(existing.evidence_ids) | set(relationship.evidence_ids)),
                    )
        return list(seen.values())

    def identities(self) -> list[IdentityAssertion]:
        seen: dict[tuple[str, str], IdentityAssertion] = {}
        for facts in self.parsed_facts():
            for identity in facts.identities:
                key = (identity.canonical_id, identity.name or "")
                existing = seen.get(key)
                if existing is None:
                    seen[key] = identity
                else:
                    seen[key] = IdentityAssertion(
                        canonical_id=identity.canonical_id,
                        name=identity.name,
                        alias_of=identity.alias_of or existing.alias_of,
                        distinct_from=sorted(set(existing.distinct_from) | set(identity.distinct_from)),
                        source_id="+".join(sorted({existing.source_id, identity.source_id})),
                        evidence_ids=sorted(set(existing.evidence_ids) | set(identity.evidence_ids)),
                    )
        return list(seen.values())

    def berth_ports(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for facts in self.parsed_facts():
            mapping.update(facts.berth_ports)
        return mapping

    def org_ids(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for facts in self.parsed_facts():
            mapping.update(facts.org_ids)
        return mapping
