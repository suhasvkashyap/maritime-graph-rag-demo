"""Export helpers: the downloadable impact brief (Markdown) and run record."""

from __future__ import annotations

import json
from typing import Any

from shared.contracts import FinalResult


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|")


def build_impact_brief(result: FinalResult) -> str:
    """Render the reviewable impact brief as Markdown."""
    pipeline = result.demo_specific_result
    lines: list[str] = []
    lines.append("# Port impact brief (synthetic demo)")
    lines.append("")
    lines.append(
        f"Run `{result.run_id}` | generated {result.generated_at.isoformat()} | "
        f"analysis cutoff {result.analysis_cutoff.isoformat()}"
    )
    lines.append("")
    lines.append(
        f"**Agent:** {result.agent_mode} tool selection | **Data:** {result.data_mode} backend | "
        f"**Status:** {result.status.value}"
    )
    lines.append("")
    lines.append("> All names, identifiers, times and events are fictional exercise data for")
    lines.append("> Asteria Maritime Insights. This brief is advisory only; no operational")
    lines.append("> action was executed or authorized.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(result.summary or "_No summary produced._")
    lines.append("")

    notice = pipeline.get("notice")
    if notice:
        lines.append("## Closure notice")
        lines.append("")
        lines.append(
            f"- **{_esc(notice.get('notice_id'))}** closes {_esc(notice.get('berth'))} "
            f"({_esc(notice.get('berth_id'))}), window {_esc(notice.get('window'))}"
        )
        lines.append("")

    lines.append("## Calls evaluated")
    lines.append("")
    lines.append("| Call | Vessel | Operator | Berth | Effective window (UTC) | Result |")
    lines.append("|---|---|---|---|---|---|")
    overlaps_by_call = {o["call_id"]: o for o in pipeline.get("overlaps", [])}
    for call in pipeline.get("effective_calls", []):
        overlap = overlaps_by_call.get(call["call_id"])
        if overlap:
            verdict = (
                f"**OVERLAP** — {overlap['overlap_hours']} h planned occupancy"
                + (" (Halcyon subsidiary-operated)" if overlap.get("halcyon_subsidiary_operated") else "")
            )
        else:
            reason = next(
                (e["reason"] for e in pipeline.get("exclusions", []) if e["call_id"] == call["call_id"]),
                "excluded",
            )
            verdict = f"excluded — {_esc(reason)}"
        lines.append(
            f"| {_esc(call['call_id'])} | {_esc(call.get('vessel'))} | {_esc(call.get('operator') or '—')} "
            f"| {_esc(call.get('berth'))} | {_esc(call.get('window'))} | {verdict} |"
        )
    lines.append("")

    lines.append("## Connected shipments")
    lines.append("")
    lines.append("| Call | Shipment | Cargo | Recipient | Facility | Receipt requested | Status |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in pipeline.get("shipments", []):
        status = "pending (proposal)" if row.get("status") == "pending" else "recorded; no delivery"
        lines.append(
            f"| {_esc(row.get('call_id') or '—')} | {_esc(row.get('shipment_id'))} "
            f"| {_esc(row.get('description') or '—')} | {_esc(row.get('recipient') or '—')} "
            f"| {_esc(row.get('facility') or '—')} | {_esc(row.get('receipt_deadline') or '—')} | {status} |"
        )
    lines.append("")

    corrections = pipeline.get("corrections_applied", [])
    if corrections:
        lines.append("## Corrections applied")
        lines.append("")
        for correction in corrections:
            lines.append(
                f"- {correction.get('call_id')}: {correction.get('status')} — {_esc(correction.get('reason'))}"
            )
        lines.append("")

    excluded_evidence = pipeline.get("excluded_evidence", [])
    if excluded_evidence:
        lines.append("## Evidence excluded by the cutoff")
        lines.append("")
        for reason in excluded_evidence:
            lines.append(f"- {_esc(reason)}")
        lines.append("")

    if pipeline.get("graph_views"):
        view = pipeline["graph_views"][-1]
        lines.append(f"## Graph view — {view.get('label_text', '')}")
        lines.append("")
        for edge in view.get("edges", [])[:12]:
            chunks = edge.get("chunks") or []
            chunk_note = f" (section {chunks[0].get('section_id')})" if chunks else ""
            lines.append(
                f"- {_esc(edge.get('source'))} —{_esc(edge.get('relationship'))}→ {_esc(edge.get('target'))}{chunk_note}"
            )
        lines.append("")

    lines.append("## Claims")
    lines.append("")
    for claim in result.claims:
        evidence = ", ".join(claim.evidence_ids) if claim.evidence_ids else "—"
        lines.append(
            f"- **{claim.claim_id}** ({claim.status.value}; evidence: {evidence}): {_esc(claim.text)}"
        )
    lines.append("")

    if result.unresolved_questions:
        lines.append("## Unresolved")
        lines.append("")
        for question in result.unresolved_questions:
            lines.append(f"- {_esc(question)}")
        lines.append("")

    lines.append("## For review (no action executed)")
    lines.append("")
    for action in result.actions_for_review:
        lines.append(f"- {_esc(action)}")
    lines.append("")

    if result.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in result.warnings:
            lines.append(f"- {_esc(warning)}")
        lines.append("")

    lines.append("## Tool actions")
    lines.append("")
    for event in result.tool_events:
        lines.append(
            f"- `{event.tool_name}` — {event.outcome} in {event.duration_ms} ms — {_esc(event.detail)}"
        )
    lines.append("")
    return "\n".join(lines)


def build_run_record(result: FinalResult) -> str:
    """Serialize the full run result as pretty JSON."""
    return json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False)
