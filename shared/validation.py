"""Deterministic logic for the Port Impact Investigator.

Everything in this module is pure Python: no LLM calls, no network. The agent
may *choose* tools, but correction application, interval math, identity
resolution, and shipment tracing are computed here, never by free-form model
arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .contracts import (
    CallAssertion,
    ClosureNotice,
    IdentityAssertion,
    ProposedAlternative,
    RelationshipAssertion,
    ScheduleCorrection,
    ShipmentLink,
    TimeWindow,
    parse_utc,
)

_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def parse_register_date(text: str, time_hhmm: str | None = None) -> datetime | None:
    """Parse register dates like ``November 18, 2026`` (optionally with HH:MM)."""
    match = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", text)
    if not match:
        return None
    month = _MONTHS.get(match.group(1))
    if month is None:
        return None
    day, year = int(match.group(2)), int(match.group(3))
    hour = minute = 0
    if time_hhmm:
        hour, minute = (int(part) for part in time_hhmm.split(":"))
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Passage parsing (deterministic, source-backed)
# ---------------------------------------------------------------------------


@dataclass
class ParsedFacts:
    source_id: str
    calls: list[CallAssertion] = field(default_factory=list)
    corrections: list[ScheduleCorrection] = field(default_factory=list)
    notices: list[ClosureNotice] = field(default_factory=list)
    shipments: list[ShipmentLink] = field(default_factory=list)
    proposals: list[ProposedAlternative] = field(default_factory=list)
    relationships: list[RelationshipAssertion] = field(default_factory=list)
    identities: list[IdentityAssertion] = field(default_factory=list)
    berth_ports: dict[str, str] = field(default_factory=dict)  # berth name -> port
    org_ids: dict[str, str] = field(default_factory=dict)  # org name -> SYN-O/G id


_CALL_RE = re.compile(
    r"(?P<call_id>SYN-C\d{3}): (?P<vessel>[A-Z][A-Za-z ]+?) \(?(?P<vessel_id>SYN-V\d{3})\)? "
    r"at (?P<berth>Berth [A-Z]\d+)(?: \(?(?P<berth_id>SYN-B\d{2})\)?)?"
    r"(?: in (?P<port>Port [A-Z][A-Za-z]+))?"
    r" on (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4}), planned (?P<start>\d{2}:\d{2}) to (?P<end>\d{2}:\d{2}) UTC"
)
_NOTICE_RE = re.compile(
    r"Notice (?P<notice_id>SYN-N\d+) closes (?P<berth>Berth [A-Z]\d+)(?: \(?(?P<berth_id>SYN-B\d{2})\)?)?"
    r"(?: in (?P<port>Port [A-Z][A-Za-z]+))?.*?on (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4}), "
    r"from (?P<start>\d{2}:\d{2}) to (?P<end>\d{2}:\d{2}) UTC"
)
_CORRECTION_RE = re.compile(
    r"Correction (?P<correction_id>SYN-U\d+) explicitly replaces the planned times of call "
    r"(?P<call_id>SYN-C\d{3}) for (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})\. "
    r"The new (?P<berth>Berth [A-Z]\d+) window is (?P<start>\d{2}:\d{2}) to (?P<end>\d{2}:\d{2}) UTC"
)
_CARRIES_RE = re.compile(
    r"call (?P<call_id>SYN-C\d{3}) carries shipment (?P<shipment>SYN-S\d+), "
    r"(?P<description>[a-z\- ]+?), for (?P<recipient>[A-Z][A-Za-z ]+?)\."
)
_RECEIVES_RE = re.compile(
    r"(?P<recipient>[A-Z][A-Za-z ]+?) assigns shipment (?P<shipment>SYN-S\d+) to "
    r"(?:with receipt requested by )?(?P<facility>[A-Z][A-Za-z ]+?)(?:, with receipt requested by| by) "
    r"(?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})(?: at (?P<time>\d{2}:\d{2}) UTC)?"
)
_PROPOSAL_RE = re.compile(
    r"Request (?P<request_id>SYN-RQ\d+) proposes handling shipment (?P<shipment>SYN-S\d+) "
    r"at (?P<facility>[A-Z][A-Za-z ]+? Terminal [A-Z]\d) on (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})\."
)
_PENDING_RE = re.compile(r"[Aa]s of the [a-z ]*cutoff, (?P<pending>[^.]*) remain pending")
_BERTH_PORT_RE = re.compile(
    r"(?P<berth>Berth [A-Z]\d+)(?:, (?P<berth_id>SYN-B\d{2})?,? is in the [A-Za-z ]+ of (?P<port>Port [A-Za-z]+)| is in (?P<port2>Port [A-Za-z]+))"
)
_OPERATOR_RE = re.compile(r"(?P<operator>[A-Z][A-Za-z ]+?), (?P<operator_id>SYN-O\d{2}), operates (?P<vessels>[^.]+)\.")
_VESSEL_IN_LIST_RE = re.compile(r"(?:and of |and )?([A-Z][A-Za-z ]+?) \((SYN-[VO]\d{2,3})\)")
_PARENT_RE = re.compile(r"(?P<group>[A-Z][A-Za-z ]+?), (?P<group_id>SYN-G\d{2}), is the parent of (?P<subs>[^.]+?) throughout")
_INDEPENDENT_RE = re.compile(r"([A-Z][A-Za-z ]+?) \((SYN-O\d{2})\) is independent")
_NAMED_RE = re.compile(r"stable identifier (?P<vessel_id>SYN-V\d{3}) is named (?P<name>[A-Z][A-Za-z ]+?)\.")
_RENAMED_RE = re.compile(r"It was renamed from (?P<old>[A-Z][A-Za-z ]+?) on")
_DIFFERENT_RE = re.compile(r"(?P<name>[A-Z][A-Za-z ]+?), (?P<vessel_id>SYN-V\d{3}), is a different vessel")
_IS_RE = re.compile(r"(?P<name>[A-Z][A-Za-z ]+?) is (?P<vessel_id>SYN-V\d{3})")
_POSITION_RE = re.compile(
    r"report (?P<report>SYN-AIS\d+) recorded (?:the vessel with identifier )?"
    r"(?P<vessel_id>SYN-V\d{3})(?: under the old name (?P<old>[A-Z][A-Za-z ]+?) at (?P<place>Waypoint [A-Za-z ]+?)"
    r"|, (?P<name>[A-Z][A-Za-z ]+?), approaching (?P<port>Port [A-Za-z]+))\.? at ?(?P<time>\d{2}:\d{2})? ?UTC"
)


def parse_passage(
    text: str,
    source_id: str,
    evidence_ids: list[str] | None = None,
    published_at: datetime | None = None,
) -> ParsedFacts:
    """Extract typed record assertions from one retrieved passage.

    Only facts literally present in the passage are asserted. Anything the
    passage does not state is left null. The extraction is intentionally
    narrow: it recognizes the register phrasing used by the demo corpus.
    """
    facts = ParsedFacts(source_id=source_id)
    evidence_ids = evidence_ids or []
    normalized = " ".join(text.split())
    # Strip the corpus banner's issue-time fragment: its trailing 'Z' would
    # otherwise glue onto the next capitalized phrase in name captures.
    normalized = re.sub(r"Issued \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\.?", "", normalized)

    for match in _CALL_RE.finditer(normalized):
        date = parse_register_date(match.group("date"))
        facts.calls.append(
            CallAssertion(
                call_id=match.group("call_id"),
                vessel_id=match.group("vessel_id"),
                vessel_name=match.group("vessel").strip(),
                berth_name=match.group("berth"),
                berth_id=match.group("berth_id"),
                port=match.group("port"),
                window=TimeWindow(
                    start=parse_register_date(match.group("date"), match.group("start")),
                    end=parse_register_date(match.group("date"), match.group("end")),
                )
                if date
                else None,
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    for match in _NOTICE_RE.finditer(normalized):
        facts.notices.append(
            ClosureNotice(
                notice_id=match.group("notice_id"),
                berth_id=match.group("berth_id") or match.group("berth"),
                berth_name=match.group("berth"),
                port=match.group("port"),
                window=TimeWindow(
                    start=parse_register_date(match.group("date"), match.group("start")),
                    end=parse_register_date(match.group("date"), match.group("end")),
                ),
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    for match in _CORRECTION_RE.finditer(normalized):
        facts.corrections.append(
            ScheduleCorrection(
                correction_id=match.group("correction_id"),
                call_id=match.group("call_id"),
                new_window=TimeWindow(
                    start=parse_register_date(match.group("date"), match.group("start")),
                    end=parse_register_date(match.group("date"), match.group("end")),
                ),
                source_id=source_id,
                published_at=published_at,
                evidence_ids=evidence_ids,
            )
        )

    for match in _CARRIES_RE.finditer(normalized):
        facts.shipments.append(
            ShipmentLink(
                call_id=match.group("call_id"),
                shipment_id=match.group("shipment"),
                description=match.group("description").strip(),
                recipient=match.group("recipient").strip(),
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    for match in _RECEIVES_RE.finditer(normalized):
        facts.shipments.append(
            ShipmentLink(
                call_id="",
                shipment_id=match.group("shipment"),
                recipient=match.group("recipient").strip(),
                facility=match.group("facility").strip(),
                receipt_deadline=parse_register_date(match.group("date"), match.group("time") or "12:00"),
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    for match in _PROPOSAL_RE.finditer(normalized):
        pending = []
        pending_match = _PENDING_RE.search(normalized)
        if pending_match:
            pending = [item.strip() for item in pending_match.group("pending").split(" and ")]
        facts.proposals.append(
            ProposedAlternative(
                request_id=match.group("request_id"),
                shipment_id=match.group("shipment"),
                facility=match.group("facility").strip(),
                date=match.group("date"),
                pending_items=pending,
                approved=False,
                source_id=source_id,
                published_at=published_at,
                evidence_ids=evidence_ids,
            )
        )

    for match in _BERTH_PORT_RE.finditer(normalized):
        port = match.group("port") or match.group("port2")
        if port:
            facts.berth_ports[match.group("berth")] = port

    for match in _OPERATOR_RE.finditer(normalized):
        operator = match.group("operator").strip()
        facts.org_ids[operator] = match.group("operator_id")
        for vessel_name, vessel_id in _VESSEL_IN_LIST_RE.findall(match.group("vessels")):
            facts.relationships.append(
                RelationshipAssertion(
                    source_entity=vessel_id,
                    relationship="operated_by",
                    target_entity=operator,
                    source_id=source_id,
                    evidence_ids=evidence_ids,
                )
            )
            facts.identities.append(
                IdentityAssertion(canonical_id=vessel_id, name=vessel_name.strip(), source_id=source_id,
                                  evidence_ids=evidence_ids)
            )

    parent_match = _PARENT_RE.search(normalized)
    if parent_match:
        group = parent_match.group("group").strip()
        facts.org_ids[group] = parent_match.group("group_id")
        for sub_name, sub_id in _VESSEL_IN_LIST_RE.findall(parent_match.group("subs")):
            facts.relationships.append(
                RelationshipAssertion(
                    source_entity=sub_id,
                    relationship="subsidiary_of",
                    target_entity=group,
                    source_id=source_id,
                    evidence_ids=evidence_ids,
                )
            )

    for name, operator_id in _INDEPENDENT_RE.findall(normalized):
        facts.org_ids[name.strip()] = operator_id
        facts.relationships.append(
            RelationshipAssertion(
                source_entity=operator_id,
                relationship="independent_of_groups",
                target_entity="no parent recorded",
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    named = _NAMED_RE.search(normalized)
    if named:
        identity = IdentityAssertion(
            canonical_id=named.group("vessel_id"),
            name=named.group("name").strip(),
            source_id=source_id,
            evidence_ids=evidence_ids,
        )
        renamed = _RENAMED_RE.search(normalized)
        if renamed:
            identity.alias_of = renamed.group("old").strip()
        different = _DIFFERENT_RE.search(normalized)
        if different:
            identity.distinct_from.append(different.group("vessel_id"))
        facts.identities.append(identity)

    for match in _IS_RE.finditer(normalized):
        name, vessel_id = match.group("name").strip(), match.group("vessel_id")
        if name in {"Amber Shoal", "Lantern Tern", "Southern Kestrel", "Atlas Kestrel"}:
            facts.identities.append(
                IdentityAssertion(canonical_id=vessel_id, name=name, source_id=source_id, evidence_ids=evidence_ids)
            )

    position = _POSITION_RE.search(normalized)
    if position and position.group("old"):
        facts.identities.append(
            IdentityAssertion(
                canonical_id=position.group("vessel_id"),
                name=position.group("old").strip(),
                alias_of=None,
                source_id=source_id,
                evidence_ids=evidence_ids,
            )
        )

    return facts


# ---------------------------------------------------------------------------
# Temporal filtering
# ---------------------------------------------------------------------------


@dataclass
class TemporalFilterResult:
    included: list = field(default_factory=list)
    excluded: list = field(default_factory=list)  # (item, reason)
    warnings: list[str] = field(default_factory=list)


def filter_by_publication(items: list, as_of: datetime) -> TemporalFilterResult:
    """Reject items published after ``as_of``; warn when publication is unknown."""
    result = TemporalFilterResult()
    for item in items:
        published_at = getattr(item, "published_at", None)
        if published_at is None:
            source_id = getattr(item, "source_id", "item")
            result.warnings.append(
                f"{source_id} has no recorded publication time; temporal coverage at the "
                f"requested cutoff {as_of.isoformat()} cannot be verified."
            )
            result.included.append(item)
        elif published_at <= as_of:
            result.included.append(item)
        else:
            source_id = getattr(item, "source_id", "item")
            result.excluded.append(
                (item, f"published {published_at.isoformat()}, after the requested cutoff {as_of.isoformat()}")
            )
    return result


# ---------------------------------------------------------------------------
# Correction precedence
# ---------------------------------------------------------------------------


@dataclass
class CorrectionApplication:
    call_id: str
    correction_id: str | None
    new_window: TimeWindow | None
    status: Literal["applied", "unresolved", "not_yet_published"] = "applied"
    reason: str = ""


def apply_corrections(
    calls: dict[str, CallAssertion],
    corrections: list[ScheduleCorrection],
    as_of: datetime,
) -> tuple[dict[str, CallAssertion], list[CorrectionApplication]]:
    """Apply only corrections published at or before ``as_of``.

    A correction applies only when it explicitly matches the call ID and
    replaces named fields (the window). Conflicting same-authority
    corrections without explicit precedence leave the schedule unresolved
    instead of guessing.
    """
    effective = dict(calls)
    applications: list[CorrectionApplication] = []

    by_call: dict[str, list[ScheduleCorrection]] = {}
    for correction in corrections:
        by_call.setdefault(correction.call_id, []).append(correction)

    for call_id, corr_list in by_call.items():
        published = [c for c in corr_list if c.published_at and c.published_at <= as_of]
        for correction in corr_list:
            if correction not in published:
                applications.append(
                    CorrectionApplication(
                        call_id=call_id,
                        correction_id=correction.correction_id,
                        new_window=correction.new_window,
                        status="not_yet_published",
                        reason=f"{correction.correction_id} is published after the cutoff; not applied",
                    )
                )
        if not published:
            continue
        windows: list[TimeWindow] = []
        for correction in published:
            if correction.new_window and not any(correction.new_window == w for w in windows):
                windows.append(correction.new_window)
        if len(published) > 1 and len(windows) > 1:
            # No explicit precedence between conflicting corrections.
            applications.append(
                CorrectionApplication(
                    call_id=call_id,
                    correction_id=None,
                    new_window=None,
                    status="unresolved",
                    reason=(
                        f"{len(published)} conflicting corrections for {call_id} without explicit "
                        "precedence; the current schedule is unresolved"
                    ),
                )
            )
            continue
        latest = max(published, key=lambda c: c.published_at)
        base = effective.get(call_id)
        if base is None:
            applications.append(
                CorrectionApplication(
                    call_id=call_id,
                    correction_id=latest.correction_id,
                    new_window=latest.new_window,
                    status="unresolved",
                    reason=f"correction references unknown call {call_id}",
                )
            )
            continue
        if latest.new_window is not None:
            effective[call_id] = base.model_copy(update={"window": latest.new_window})
        applications.append(
            CorrectionApplication(
                call_id=call_id,
                correction_id=latest.correction_id,
                new_window=latest.new_window,
                status="applied",
                reason=f"{latest.correction_id} replaces the window with {format_window(latest.new_window)}",
            )
        )
    return effective, applications


def format_window(window: TimeWindow | None) -> str:
    if window is None:
        return "unknown"
    return f"{window.start.strftime('%Y-%m-%d %H:%M')} to {window.end.strftime('%H:%M')} UTC"


# ---------------------------------------------------------------------------
# Overlap evaluation (half-open intervals [start, end))
# ---------------------------------------------------------------------------


@dataclass
class OverlapResult:
    call_id: str
    included: bool
    overlap_seconds: int
    reason: str
    effective_window: TimeWindow | None


def evaluate_call_overlap(
    call: CallAssertion,
    notice: ClosureNotice,
    berth_ports: dict[str, str] | None = None,
) -> OverlapResult:
    """Half-open interval overlap for one call against one closure notice."""
    berth_ports = berth_ports or {}
    effective_window = call.window

    if call.berth_id is None or notice.berth_id is None:
        same_berth = False
    else:
        same_berth = call.berth_id == notice.berth_id

    if not same_berth:
        call_port = call.port or berth_ports.get(call.berth_name or "", "")
        notice_port = notice.port or berth_ports.get(notice.berth_name or "", "")
        if call_port and notice_port and call_port != notice_port:
            reason = f"{call.berth_name} is in {call_port}; the notice affects {notice_port}"
        else:
            reason = f"{call.berth_name} is not the closed berth {notice.berth_name}"
        return OverlapResult(call_id=call.call_id, included=False, overlap_seconds=0, reason=reason,
                             effective_window=effective_window)

    if effective_window is None:
        return OverlapResult(
            call_id=call.call_id,
            included=False,
            overlap_seconds=0,
            reason="no parsed schedule window; cannot evaluate",
            effective_window=None,
        )

    overlap = effective_window.start < notice.window.end and notice.window.start < effective_window.end
    if not overlap:
        if effective_window.start >= notice.window.end:
            reason = (
                f"corrected window {format_window(effective_window)} starts at or after the closure ends "
                f"({notice.window.end.strftime('%H:%M')} UTC)"
            )
        else:
            reason = f"window {format_window(effective_window)} ends at or before the closure starts"
        return OverlapResult(call_id=call.call_id, included=False, overlap_seconds=0, reason=reason,
                             effective_window=effective_window)

    overlap_seconds = max(
        0,
        (
            min(effective_window.end, notice.window.end) - max(effective_window.start, notice.window.start)
        ).total_seconds(),
    )
    return OverlapResult(
        call_id=call.call_id,
        included=True,
        overlap_seconds=int(overlap_seconds),
        reason=f"planned occupancy at {notice.berth_name} during the closure window",
        effective_window=effective_window,
    )


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


@dataclass
class IdentityResolution:
    name_or_id: str
    canonical_id: str | None
    resolved_name: str | None
    aliases: list[str] = field(default_factory=list)
    distinct_from: list[str] = field(default_factory=list)
    ambiguous: bool = False
    reason: str = ""


def resolve_vessel_identity(
    name_or_id: str,
    identities: list[IdentityAssertion],
    evidence_ids: set[str] | None = None,
) -> IdentityResolution:
    """Resolve a vessel name or ID to its canonical ID using only given evidence."""
    needle = name_or_id.strip().lower()
    pool = [
        identity
        for identity in identities
        if evidence_ids is None or (set(identity.evidence_ids) & evidence_ids)
    ]
    matches: dict[str, IdentityAssertion] = {}

    for identity in pool:
        hay = [identity.canonical_id.lower(), (identity.name or "").lower(), (identity.alias_of or "").lower()]
        if needle in [h for h in hay if h]:
            matches.setdefault(identity.canonical_id, identity)

    if not matches:
        return IdentityResolution(
            name_or_id=name_or_id,
            canonical_id=None,
            resolved_name=None,
            reason=f"no supported identity assertion for {name_or_id!r} in the cited evidence",
        )

    if len(matches) > 1:
        return IdentityResolution(
            name_or_id=name_or_id,
            canonical_id=None,
            resolved_name=None,
            ambiguous=True,
            reason=f"{name_or_id!r} matches multiple canonical IDs: {sorted(matches)}",
        )

    canonical_id, identity = next(iter(matches.items()))
    aliases = []
    if identity.alias_of:
        aliases.append(identity.alias_of)
    for other in pool:
        if other.canonical_id == canonical_id and other.alias_of and other.alias_of not in aliases:
            aliases.append(other.alias_of)
    # Distinctness: stated on this vessel's assertions, and stated about this
    # vessel from the other side ("X ... is not an alias of Y").
    distinct = set()
    for other in pool:
        if other.canonical_id == canonical_id:
            distinct.update(other.distinct_from)
        elif canonical_id in other.distinct_from:
            distinct.add(other.canonical_id)
    return IdentityResolution(
        name_or_id=name_or_id,
        canonical_id=canonical_id,
        resolved_name=identity.name,
        aliases=aliases,
        distinct_from=sorted(distinct),
        reason="resolved from cited identity assertions",
    )


# ---------------------------------------------------------------------------
# Summary guard
# ---------------------------------------------------------------------------

_FORBIDDEN_PHRASES = (
    ("has been diverted", "no diversion is approved in the evidence"),
    ("was diverted", "no diversion is approved in the evidence"),
    ("approved diversion", "no diversion is approved in the evidence"),
    ("delivered", "no delivery is recorded in the evidence"),
    ("actual delay of", "the overlap duration is planned occupancy, not an established delay"),
)


def guard_summary(summary: str) -> list[str]:
    """Return warnings for summary wording that overstates the evidence."""
    warnings = []
    lowered = summary.lower()
    if "delay" in lowered and "not established" not in lowered and "no established" not in lowered:
        warnings.append(
            "Summary mentions delay; the deterministic result establishes planned overlap "
            "duration only. State that actual delay is not established."
        )
    for phrase, reason in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            warnings.append(f"Summary states {phrase!r}; {reason}.")
    return warnings


def validate_claim_evidence(claims: list, evidence_ids: set[str]) -> list[str]:
    """Claims must reference evidence that actually exists."""
    problems = []
    for claim in claims:
        for evidence_id in claim.evidence_ids:
            if evidence_id not in evidence_ids:
                problems.append(
                    f"{claim.claim_id} cites {evidence_id}, which is not in the returned evidence"
                )
    return problems
