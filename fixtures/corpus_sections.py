"""AMI Demo 3 synthetic corpus — source of truth for the twelve sections.

Every string here is fictional exercise data for Asteria Maritime Insights
(AMI). The PDF in ``assets/graph/`` is generated from this module and is the
artifact that gets indexed; this module is never itself exposed to retrieval.
Evaluation answers and agent instructions are deliberately NOT included here.

Times are UTC. The exercise analysis cutoff is 2026-11-17T12:00:00Z.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusSection:
    section_id: str
    title: str
    published_at: str  # ISO-8601 UTC
    text: str


BANNER_PREFIX = "SYNTHETIC DEMO ONLY | Asteria Maritime Insights"

SECTIONS: tuple[CorpusSection, ...] = (
    CorpusSection(
        "D01",
        "Vessel register and aliases",
        "2026-11-16T09:00:00Z",
        (
            "In this exercise register, the vessel with stable identifier SYN-V001 is named "
            "Atlas Kestrel. It was renamed from Northline Kestrel on October 15, 2026; the "
            "stable identifier SYN-V001 did not change. Southern Kestrel, SYN-V004, is a "
            "different vessel and is not an alias of SYN-V001. Amber Shoal is SYN-V002 and "
            "Lantern Tern is SYN-V003. All identifiers are fictional exercise identifiers, "
            "not IMO numbers or MMSI numbers."
        ),
    ),
    CorpusSection(
        "D02",
        "Vessel operators",
        "2026-11-16T09:15:00Z",
        (
            "Meridian Shelf Shipping, SYN-O01, operates Atlas Kestrel (SYN-V001) and Amber "
            "Shoal (SYN-V002). Bluewater Reach Logistics, SYN-O02, operates Lantern Tern "
            "(SYN-V003). Copper Bay Carriers, SYN-O03, operates Southern Kestrel (SYN-V004). "
            "These operator assignments apply throughout November 2026. They record operation "
            "of the vessels, not ownership of them."
        ),
    ),
    CorpusSection(
        "D03",
        "Corporate group",
        "2026-11-16T09:30:00Z",
        (
            "Halcyon Maritime Group, SYN-G01, is the parent of Meridian Shelf Shipping "
            "(SYN-O01) and of Bluewater Reach Logistics (SYN-O02) throughout 2026. Copper Bay "
            "Carriers (SYN-O03) is independent in this fictional register and has no parent "
            "company recorded. A corporate parent relationship does not make the parent the "
            "operator or the owner of the vessels its subsidiaries operate."
        ),
    ),
    CorpusSection(
        "D04",
        "Planned vessel calls",
        "2026-11-16T10:00:00Z",
        (
            "The exercise register lists five planned vessel calls. "
            "SYN-C101: Atlas Kestrel (SYN-V001) at Berth B4 (SYN-B04) on November 18, 2026, "
            "planned 09:00 to 17:00 UTC. "
            "SYN-C102: Amber Shoal (SYN-V002) at Berth B2 (SYN-B02) on November 18, 2026, "
            "planned 13:00 to 19:00 UTC. "
            "SYN-C103: Lantern Tern (SYN-V003) at Berth B4 (SYN-B04) on November 18, 2026, "
            "planned 11:00 to 16:00 UTC. "
            "SYN-C104: Southern Kestrel (SYN-V004) at Berth W1 in Port Westhaven on "
            "November 18, 2026, planned 10:00 to 15:00 UTC. "
            "SYN-C105: Atlas Kestrel (SYN-V001) at Berth B4 (SYN-B04) on November 19, 2026, "
            "planned 09:00 to 12:00 UTC. "
            "All five are planned occupancies. Later explicit corrections supersede the named "
            "fields of a call only. No completed arrivals are recorded in this register."
        ),
    ),
    CorpusSection(
        "D05",
        "Locations",
        "2026-11-16T10:15:00Z",
        (
            "Berth B4, SYN-B04, is in the East Basin of Port Lumen. Berth B2, SYN-B02, is in "
            "the West Basin of Port Lumen. Berth W1 is in Port Westhaven. Aster Terminal A1 is "
            "in Port Aster. Waypoint Cedar is an approach waypoint recorded for exercise "
            "navigation references; it is not a berth."
        ),
    ),
    CorpusSection(
        "D06",
        "Berth B4 closure notice",
        "2026-11-16T11:00:00Z",
        (
            "Notice SYN-N017 closes Berth B4 (SYN-B04) in Port Lumen for fender maintenance on "
            "November 18, 2026, from 08:00 to 20:00 UTC. The closure end time is exclusive. "
            "Berth B2 (SYN-B02) is unaffected. The notice closes the berth, not the whole "
            "port. No extension of this closure is recorded in this exercise register as of "
            "the cutoff."
        ),
    ),
    CorpusSection(
        "D07",
        "Shipment assignments per call",
        "2026-11-16T11:15:00Z",
        (
            "Planned call SYN-C101 carries shipment SYN-S101, twelve refrigeration-module "
            "crates, for Pelagic Clinic Supply. Planned call SYN-C102 carries shipment "
            "SYN-S102, thirty packaging-material pallets, for Lumen Packaging Services. "
            "Planned call SYN-C103 carries shipment SYN-S103, eight water-treatment pump kits, "
            "for Island Utilities Cooperative. Shipment identifiers carry the full SYN- prefix "
            "throughout this register. No proof of delivery is recorded for any of these "
            "shipments."
        ),
    ),
    CorpusSection(
        "D08",
        "Terminal capability",
        "2026-11-16T11:30:00Z",
        (
            "Aster Terminal A1 in Port Aster can handle up to twenty refrigeration-module "
            "crates per booking and offers covered storage. Recorded capability is not a "
            "reservation, not an available slot, not a transit-time estimate, and not an "
            "authorization to handle cargo."
        ),
    ),
    CorpusSection(
        "D09",
        "Schedule correction for SYN-C103",
        "2026-11-17T09:00:00Z",
        (
            "Correction SYN-U09 explicitly replaces the planned times of call SYN-C103 for "
            "November 18, 2026. The new Berth B4 window is 21:00 to 23:00 UTC, replacing the "
            "previously planned 11:00 to 16:00 UTC. The vessel, the berth, and all other calls "
            "remain unchanged. The corrected window is still a planned occupancy, not an "
            "arrival."
        ),
    ),
    CorpusSection(
        "D10",
        "Position reports",
        "2026-11-17T10:30:00Z",
        (
            "At November 17, 10:00 UTC, report SYN-AIS01 recorded the vessel with identifier "
            "SYN-V001 under the old name Northline Kestrel at Waypoint Cedar. At 10:05 UTC the "
            "same day, report SYN-AIS02 recorded SYN-V004, Southern Kestrel, approaching Port "
            "Westhaven. No real coordinates and no berth arrivals are recorded in these "
            "exercise reports. A position report that uses a former vessel name does not "
            "describe a different vessel."
        ),
    ),
    CorpusSection(
        "D11",
        "Handling proposal",
        "2026-11-17T11:00:00Z",
        (
            "Request SYN-RQ11 proposes handling shipment SYN-S101 at Aster Terminal A1 on "
            "November 18, 2026. As of the exercise cutoff, terminal-slot confirmation and "
            "landside transport approval for this request remain pending. No diversion of any "
            "vessel has been approved and no completed cargo transfer is recorded."
        ),
    ),
    CorpusSection(
        "D12",
        "Receiving assignments",
        "2026-11-16T12:00:00Z",
        (
            "Pelagic Clinic Supply assigns shipment SYN-S101 to Pearl Cold Store, with receipt "
            "requested by November 19, 2026 at 12:00 UTC. Island Utilities Cooperative assigns "
            "shipment SYN-S103 to Juniper Water Works by November 20, 2026 at 12:00 UTC. No "
            "actual delivery, transit-time estimate, or missed deadline is established by "
            "these receiving assignments."
        ),
    ),
)


def section_banner(section: CorpusSection) -> str:
    """Return the per-section synthetic banner line used in the PDF.

    Uses plain ASCII separators so the generated PDF stays renderable with the
    standard PDF core fonts.
    """
    return f"{BANNER_PREFIX} | {section.section_id} - {section.title} | Issued {section.published_at}"


def section_full_text(section: CorpusSection) -> str:
    """Return the full indexed text of one section (banner + body)."""
    return f"{section_banner(section)}\n\n{section.text}"
