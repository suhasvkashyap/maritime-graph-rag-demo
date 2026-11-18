"""Demo 3: Port Impact Investigator.

One agent (``PortImpactAnalyst``) with a bounded tool loop, deterministic
interval/correction logic, and a reviewable impact brief. The agent chooses
tools; every schedule comparison, identity resolution, and shipment trace is
computed by deterministic Python from evidence the tools actually returned.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from adapters.fixture_replay import (
    fixture_evidence_items,
    fixture_graph,
    fixture_identity,
    service_response_for_query,
)
from adapters.graph_pattern import GraphPatternClient, passage_excerpts, SECTION_PUBLISHED_AT
from adapters.llm import LLMClient
from shared.agent_loop import AgentRunResult, BoundedToolLoop, ToolSpec, event_detail
from shared.configuration import ROOT, Settings
from shared.contracts import (
    Claim,
    ClaimStatus,
    ErrorCode,
    EvidenceItem,
    FinalResult,
    RunStatus,
    ToolEnvelope,
    ToolError,
    ToolEvent,
    parse_utc,
)
from shared.evidence import EvidenceStore
from shared.validation import (
    apply_corrections,
    evaluate_call_overlap,
    format_window,
    guard_summary,
    resolve_vessel_identity,
    validate_claim_evidence,
)

TRAILING_ISSUED_RE = re.compile(r"\s*Issued \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\.?\s*$")

CORE_ENTITIES = [
    "SYN-G01",
    "SYN-O01",
    "SYN-O02",
    "SYN-V001",
    "SYN-V003",
    "SYN-C101",
    "SYN-C103",
    "SYN-B04",
    "SYN-N017",
    "SYN-S101",
]


# ---------------------------------------------------------------------------
# Tool argument models (validated before execution)
# ---------------------------------------------------------------------------


class RetrieveArgs(BaseModel):
    query: str = Field(min_length=3)
    as_of: str | None = None
    entity_ids: list[str] = Field(default_factory=list, max_length=8)


class ResolveArgs(BaseModel):
    name_or_id: str = Field(min_length=2)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class OverlapArgs(BaseModel):
    call_ids: list[str] = Field(default_factory=list, max_length=12)
    notice_id: str | None = None
    as_of: str | None = None


class TraceArgs(BaseModel):
    call_ids: list[str] = Field(default_factory=list, max_length=12)
    as_of: str | None = None


class GraphArgs(BaseModel):
    entity_ids: list[str] = Field(default_factory=list, max_length=12)
    max_nodes: int = Field(default=15, ge=1, le=25)
    max_edges: int = Field(default=20, ge=1, le=35)


# ---------------------------------------------------------------------------
# Tool JSON schemas
# ---------------------------------------------------------------------------

RETRIEVE_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search question about calls, vessels, berths, notices or shipments."},
        "as_of": {"type": "string", "description": "Optional analysis cutoff (ISO-8601). Defaults to the run cutoff."},
        "entity_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional entity IDs to focus on."},
    },
    "required": ["query"],
}
RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "name_or_id": {"type": "string", "description": "Vessel name or SYN-V identifier."},
        "evidence_ids": {"type": "array", "items": {"type": "string"}, "description": "Restrict resolution to these evidence IDs."},
    },
    "required": ["name_or_id"],
}
OVERLAP_SCHEMA = {
    "type": "object",
    "properties": {
        "call_ids": {"type": "array", "items": {"type": "string"}, "description": "Call IDs to evaluate; empty means all retrieved calls."},
        "notice_id": {"type": "string", "description": "Closure notice ID, e.g. SYN-N017."},
        "as_of": {"type": "string", "description": "Optional cutoff override (ISO-8601)."},
    },
    "required": [],
}
TRACE_SCHEMA = {
    "type": "object",
    "properties": {
        "call_ids": {"type": "array", "items": {"type": "string"}, "description": "Call IDs to trace; empty means all."},
        "as_of": {"type": "string", "description": "Optional cutoff override (ISO-8601)."},
    },
    "required": [],
}
GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_ids": {"type": "array", "items": {"type": "string"}, "description": "Entity names or IDs to inspect."},
        "max_nodes": {"type": "integer", "minimum": 1, "maximum": 25},
        "max_edges": {"type": "integer", "minimum": 1, "maximum": 35},
    },
    "required": [],
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class _RunState:
    as_of: datetime
    store: EvidenceStore
    graph_views: list[dict[str, Any]]


class PortImpactAnalyst:
    """The Demo 3 agent plus its deterministic pipeline."""

    def __init__(self, settings: Settings, llm: LLMClient | None = None):
        self._settings = settings
        self._llm = llm
        self._pattern = GraphPatternClient(
            base_url=settings.graph_pattern_url,
            timeout_seconds=settings.graph_pattern_timeout,
        )
        self._last_summary_source = "deterministic"

    # -- public API ---------------------------------------------------------

    def last_evidence(self) -> list[EvidenceItem]:
        """Evidence items from the most recent run (for UI citation panels)."""
        store = getattr(self, "_last_store", None)
        return list(store.items) if store else []

    def run(self, question: str, analysis_cutoff: str, scripted: bool | None = None) -> FinalResult:
        as_of = parse_utc(analysis_cutoff) or parse_utc(self._settings.analysis_cutoff)
        assert as_of is not None
        use_scripted = scripted if scripted is not None else self._settings.agent_mode == "scripted"
        state = _RunState(as_of=as_of, store=EvidenceStore(as_of=as_of), graph_views=[])
        self._last_store = state.store

        if use_scripted:
            agent_result = self._scripted_run(state, question)
        elif self._llm is not None:
            agent_result = self._live_run(state, question)
        else:
            agent_result = self._scripted_run(
                state,
                question,
                previous=AgentRunResult(
                    final_text="",
                    status=RunStatus.FAILED,
                    error="no LLM client configured for live agent mode",
                ),
            )

        return self._assemble(state, question, agent_result, use_scripted)

    # -- agent execution ----------------------------------------------------

    def _tool_specs(self, state: _RunState) -> list[ToolSpec]:
        return [
            ToolSpec(
                "retrieve_maritime_relationships",
                "Search the graph-indexed maritime corpus for source passages and relationship assertions.",
                RETRIEVE_SCHEMA,
                self._make_retrieve(state),
                RetrieveArgs,
            ),
            ToolSpec(
                "resolve_vessel_identity",
                "Resolve a vessel name or ID to its canonical ID using only cited evidence.",
                RESOLVE_SCHEMA,
                self._make_resolve(state),
                ResolveArgs,
            ),
            ToolSpec(
                "evaluate_call_overlap",
                "Deterministically evaluate retrieved calls against a closure notice with corrections applied.",
                OVERLAP_SCHEMA,
                self._make_overlap(state),
                OverlapArgs,
            ),
            ToolSpec(
                "trace_shipments",
                "Trace call-to-shipment-to-recipient chains for the retrieved calls.",
                TRACE_SCHEMA,
                self._make_trace(state),
                TraceArgs,
            ),
            ToolSpec(
                "get_graph_evidence",
                "Inspect the extracted relationship graph around the given entities.",
                GRAPH_SCHEMA,
                self._make_graph(state),
                GraphArgs,
            ),
        ]

    def _live_run(self, state: _RunState, question: str) -> AgentRunResult:
        assert self._llm is not None
        system_prompt = self._system_prompt()
        context_notes = f"Analysis cutoff: {state.as_of.isoformat()}. Notice of interest: SYN-N017."
        required = ['retrieve_maritime_relationships', 'get_graph_evidence']
        if re.search(r'overlap|closure|call|impact', question, re.I):required.append('evaluate_call_overlap')
        if re.search(r'shipment|cargo|handling|recipient', question, re.I):required.append('trace_shipments')
        loop = BoundedToolLoop(llm=self._llm, tools=self._tool_specs(state),
            required_tools=tuple(required),
            max_tool_calls=self._settings.max_tool_calls,
            deadline_seconds=self._settings.request_timeout_seconds)
        self._last_summary_source = 'agent'
        return loop.run(system_prompt, question, context_notes)

    def _scripted_run(self, state: _RunState, question: str, previous: AgentRunResult | None = None) -> AgentRunResult:
        """Execute the rehearsal plan through the same tools, without model tool selection."""
        plan: list[tuple[str, dict[str, Any]]] = [
            ("retrieve_maritime_relationships", {"query": question}),
            ("evaluate_call_overlap", {"notice_id": "SYN-N017"}),
            ("trace_shipments", {}),
            ("resolve_vessel_identity", {"name_or_id": "Atlas Kestrel"}),
            ("get_graph_evidence", {"entity_ids": []}),
        ]
        tool_events = list(previous.tool_events) if previous else []
        specs = {spec.name: spec for spec in self._tool_specs(state)}
        for name, arguments in plan:
            if name not in specs:
                continue
            started = time.perf_counter()
            try:
                envelope = specs[name].execute(arguments)
            except ToolError as exc:
                envelope = ToolEnvelope.failure(str(exc), exc.error_code or ErrorCode.BACKEND_ERROR)
            except Exception as exc:  # noqa: BLE001
                envelope = ToolEnvelope.failure(f"tool failed: {type(exc).__name__}", ErrorCode.BACKEND_ERROR)
            tool_events.append(
                ToolEvent(
                    tool_name=name,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    outcome="ok" if envelope.ok else "error",
                    evidence_ids=[item.evidence_id for item in envelope.evidence],
                    detail=event_detail(envelope),
                    error_code=str(envelope.error_code.value) if envelope.error_code else None,
                )
            )
        self._last_summary_source = "deterministic"
        return AgentRunResult(final_text="", tool_events=tool_events, status=RunStatus.COMPLETE)

    def _system_prompt(self) -> str:
        prompt_path = ROOT / "prompts" / "port_impact_system.txt"
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        return f"{prompt}\n\n/no_think"

    # -- tool implementations -------------------------------------------------

    def _make_retrieve(self, state: _RunState):
        def retrieve(arguments: dict[str, Any]) -> ToolEnvelope:
            query = arguments["query"]
            if self._settings.data_mode == "live":
                evidence, pattern_answer = self._pattern.query(query)
                warnings = []
            else:
                payload = service_response_for_query("retrieve_maritime_relationships", query)
                if "status_code" in payload:  # fixture-replayed backend failure
                    return ToolEnvelope.failure(
                        "Graph AutoRAG endpoint returned 503 (fixture replay)",
                        ErrorCode.BACKEND_UNAVAILABLE,
                        warnings=["Fixture-replayed failure; no live call was made."],
                    )
                evidence = fixture_evidence_items(payload)
                pattern_answer = payload.get("output_text", "")
                warnings = ["Data source: fixture replay of the Pattern1 service contract."]

            added, excluded = [], []
            for item in evidence:
                accepted = state.store.add(item)
                (added if accepted else excluded).append(item)

            passages = []
            for item in added:
                passages.append(
                    {
                        "evidence_id": item.evidence_id,
                        "source_id": item.source_id,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                        "excerpt": _clean_excerpt(item.excerpt, limit=700),
                    }
                )
            for item, reason in state.store.excluded_after_cutoff[-len(excluded) if excluded else 0:]:
                passages.append(
                    {
                        "evidence_id": None,
                        "source_id": item.source_id,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                        "excerpt": _clean_excerpt(item.excerpt, limit=200),
                        "excluded": reason,
                    }
                )

            relationships = [
                {
                    "source_entity": r.source_entity,
                    "relationship": r.relationship,
                    "target_entity": r.target_entity,
                    "source_id": r.source_id,
                    "evidence_ids": r.evidence_ids,
                }
                for r in state.store.relationships()
            ]
            data = {
                "passages": passages,
                "relationships": relationships,
                "excluded_after_cutoff": [reason for _, reason in state.store.excluded_after_cutoff],
                "pattern_answer": pattern_answer[:400],
            }
            return ToolEnvelope.success(data, evidence=added, warnings=warnings)

        return retrieve

    def _make_resolve(self, state: _RunState):
        def resolve(arguments: dict[str, Any]) -> ToolEnvelope:
            name_or_id = arguments["name_or_id"]
            cited_ids = set(arguments.get("evidence_ids") or []) & state.store.ids()
            if self._settings.data_mode == "fixture" and not state.store.items:
                identity_fixture = fixture_identity(name_or_id)
                if identity_fixture is None:
                    return ToolEnvelope.failure(
                        f"no supported identity assertion for {name_or_id!r}",
                        ErrorCode.NOT_FOUND,
                    )
                return ToolEnvelope.success({"identity": {**identity_fixture, "graph": "fixture"}})

            resolution = resolve_vessel_identity(name_or_id, state.store.identities(), cited_ids or None)
            if resolution.canonical_id is None:
                return ToolEnvelope.failure(resolution.reason, ErrorCode.NOT_FOUND)
            return ToolEnvelope.success(
                {
                    "identity": {
                        "canonical_id": resolution.canonical_id,
                        "resolved_name": resolution.resolved_name,
                        "aliases": resolution.aliases,
                        "distinct_from": resolution.distinct_from,
                        "ambiguous": resolution.ambiguous,
                        "reason": resolution.reason,
                    }
                }
            )

        return resolve

    def _make_overlap(self, state: _RunState):
        def evaluate(arguments: dict[str, Any]) -> ToolEnvelope:
            as_of = parse_utc(arguments.get("as_of")) or state.as_of
            notices = state.store.notices()
            if not notices:
                return ToolEnvelope.failure(
                    "no closure notice found in the retrieved evidence; retrieve the notice first",
                    ErrorCode.NOT_FOUND,
                )
            notice_id = arguments.get("notice_id")
            if notice_id:
                notice = notices.get(notice_id)
                if notice is None:
                    return ToolEnvelope.failure(
                        f"notice {notice_id} not found in retrieved evidence (found: {sorted(notices)})",
                        ErrorCode.NOT_FOUND,
                    )
            elif len(notices) == 1:
                notice = next(iter(notices.values()))
            else:
                return ToolEnvelope.failure(
                    f"multiple notices retrieved ({sorted(notices)}); pass an explicit notice_id",
                    ErrorCode.VALIDATION,
                )

            calls = state.store.calls()
            if arguments.get("call_ids"):
                wanted = set(arguments["call_ids"])
                calls = {call_id: call for call_id, call in calls.items() if call_id in wanted}
                missing = wanted - set(calls)
                if missing:
                    return ToolEnvelope.failure(
                        f"call(s) {sorted(missing)} not found in retrieved evidence",
                        ErrorCode.NOT_FOUND,
                    )

            effective, applications = apply_corrections(calls, state.store.corrections(), as_of)
            berth_ports = state.store.berth_ports()
            effective_calls, overlaps, exclusions = [], [], []
            for call_id in sorted(effective):
                call = effective[call_id]
                result = evaluate_call_overlap(call, notice, berth_ports)
                effective_calls.append(
                    {
                        "call_id": call.call_id,
                        "vessel": call.vessel_name or call.vessel_id,
                        "vessel_id": call.vessel_id,
                        "berth": call.berth_name,
                        "berth_id": call.berth_id,
                        "port": call.port or berth_ports.get(call.berth_name or "", None),
                        "window": format_window(result.effective_window),
                        "source_id": call.source_id,
                    }
                )
                if result.included:
                    overlaps.append(
                        {
                            "call_id": call.call_id,
                            "overlap_seconds": result.overlap_seconds,
                            "overlap_hours": round(result.overlap_seconds / 3600, 2),
                            "reason": result.reason,
                            "kind": "planned_occupancy",
                        }
                    )
                else:
                    exclusions.append({"call_id": call.call_id, "reason": result.reason})

            corrections_view = [
                {
                    "call_id": application.call_id,
                    "correction_id": application.correction_id,
                    "status": application.status,
                    "reason": application.reason,
                }
                for application in applications
            ]
            return ToolEnvelope.success(
                {
                    "notice": {
                        "notice_id": notice.notice_id,
                        "berth": notice.berth_name,
                        "berth_id": notice.berth_id,
                        "window": format_window(notice.window),
                    },
                    "effective_calls": effective_calls,
                    "overlaps": overlaps,
                    "exclusions": exclusions,
                    "corrections_applied": corrections_view,
                    "as_of": as_of.isoformat(),
                }
            )

        return evaluate

    def _make_trace(self, state: _RunState):
        def trace(arguments: dict[str, Any]) -> ToolEnvelope:
            as_of = parse_utc(arguments.get("as_of")) or state.as_of
            wanted = set(arguments.get("call_ids") or [])
            shipments = []
            for link in state.store.shipments():
                if wanted and link.call_id and link.call_id not in wanted and link.shipment_id not in wanted:
                    continue
                if link.call_id and wanted and link.call_id not in wanted:
                    continue
                shipments.append(
                    {
                        "call_id": link.call_id or None,
                        "shipment_id": link.shipment_id,
                        "description": link.description,
                        "recipient": link.recipient,
                        "facility": link.facility,
                        "receipt_deadline": link.receipt_deadline.isoformat() if link.receipt_deadline else None,
                        "status": "recorded",
                        "delivered": False,
                        "source_id": link.source_id,
                    }
                )
            proposal = None
            for item in state.store.proposals():
                if item.published_at and item.published_at > as_of:
                    continue
                proposal = {
                    "request_id": item.request_id,
                    "shipment_id": item.shipment_id,
                    "facility": item.facility,
                    "date": item.date,
                    "pending_items": item.pending_items,
                    "approved": False,
                    "source_id": item.source_id,
                }
            return ToolEnvelope.success({"shipments": shipments, "proposal": proposal})

        return trace

    def _make_graph(self, state: _RunState):
        def graph(arguments: dict[str, Any]) -> ToolEnvelope:
            pipeline = self._pipeline(state)
            affected = [o['call_id'] for o in pipeline['overlaps']]
            focus = affected + ([pipeline['notice']['notice_id']] if pipeline.get('notice') else [])
            focus += [row['shipment_id'] for row in pipeline['shipments'] if row.get('call_id') in affected]
            focus += [o['operator_id'] for o in pipeline['overlaps'] if o.get('operator_id')]
            entity_names = list(dict.fromkeys(arguments.get("entity_ids") or focus or CORE_ENTITIES[:6]))[:8]
            max_nodes = int(arguments.get("max_nodes") or 15)
            max_edges = int(arguments.get("max_edges") or 20)

            if self._settings.data_mode == "fixture":
                payload = fixture_graph(entity_names)
                view = {
                    "graph_label": "expected_fixture",
                    "label_text": "Expected fixture graph: curated fixture data used only in rehearsal mode.",
                    "nodes": payload.get("nodes", []),
                    "edges": payload.get("edges", []),
                    "matched_seeds": payload.get("matched_seeds", []),
                    "unmatched": payload.get("unmatched", []),
                }
                state.graph_views.append(view)
                return ToolEnvelope.success(view, warnings=["Fixture graph; not produced by live extraction."])

            try:
                payload = self._pattern.graph_evidence(entity_names, max_nodes=max_nodes, max_edges=max_edges)
            except ToolError as exc:
                return ToolEnvelope.failure(
                    f"{exc}; extracted-graph inspection unavailable",
                    ErrorCode.BACKEND_UNAVAILABLE,
                    warnings=["Showing evidence relationships from retrieved passages instead."],
                )
            nodes, raw_edges = payload.get("nodes", []), payload.get("edges", [])
            # Never expose a later correction through the graph side channel.
            edges = []
            for edge in raw_edges:
                chunks = [c for c in edge.get("chunks", [])
                          if SECTION_PUBLISHED_AT.get(c.get("section_id")) is not None
                          and SECTION_PUBLISHED_AT[c['section_id']] <= state.as_of]
                if chunks:
                    edges.append(dict(edge, chunks=chunks))
            visible = {e['source'] for e in edges} | {e['target'] for e in edges}
            nodes = [node for node in nodes if node['name'] in visible]
            view = {
                "graph_label": "source_parsed",
                "label_text": "Live source-parsed Neo4j graph: built from the PDF register, with section citations and analysis-cutoff filtering.",
                "nodes": nodes,
                "edges": edges,
                "matched_seeds": payload.get("matched_seeds", []),
                "unmatched": payload.get("unmatched", []),
            }
            state.graph_views.append(view)
            warnings = []
            if not nodes:
                warnings.append(
                    "The extracted graph has no matching entities for the requested seeds; "
                    "use the evidence relationships reconstructed from retrieved passages."
                )
            return ToolEnvelope.success(view, warnings=warnings)

        return graph

    # -- deterministic pipeline assembly --------------------------------------

    def _pipeline(self, state: _RunState, notice_id: str | None = None) -> dict[str, Any]:
        """Deterministic evaluation over everything the store actually holds."""
        notices = state.store.notices()
        notice = None
        if notice_id and notice_id in notices:
            notice = notices[notice_id]
        elif notices:
            notice = next(iter(notices.values()))

        calls = state.store.calls()
        effective, applications = apply_corrections(calls, state.store.corrections(), state.as_of)
        berth_ports = state.store.berth_ports()
        overlaps, exclusions, effective_calls = [], [], []
        for call_id in sorted(effective):
            call = effective[call_id]
            if notice is None:
                exclusions.append({"call_id": call_id, "reason": "no closure notice in evidence"})
                continue
            result = evaluate_call_overlap(call, notice, berth_ports)
            effective_calls.append(
                {
                    "call_id": call.call_id,
                    "vessel": call.vessel_name or call.vessel_id,
                    "vessel_id": call.vessel_id,
                    "berth": call.berth_name,
                    "berth_id": call.berth_id,
                    "port": call.port or berth_ports.get(call.berth_name or "", None),
                    "window": format_window(result.effective_window),
                    "source_id": call.source_id,
                }
            )
            if result.included:
                overlaps.append(
                    {
                        "call_id": call.call_id,
                        "overlap_seconds": result.overlap_seconds,
                        "overlap_hours": round(result.overlap_seconds / 3600, 2),
                        "reason": result.reason,
                        "kind": "planned_occupancy",
                    }
                )
            else:
                exclusions.append({"call_id": call.call_id, "reason": result.reason})

        relationships = [
            {
                "source_entity": r.source_entity,
                "relationship": r.relationship,
                "target_entity": r.target_entity,
                "source_id": r.source_id,
                "evidence_ids": r.evidence_ids,
            }
            for r in state.store.relationships()
        ]
        operators_by_vessel = {
            r["source_entity"]: r["target_entity"]
            for r in relationships
            if r["relationship"] == "operated_by"
        }
        subsidiaries = {
            r["source_entity"] for r in relationships if r["relationship"] == "subsidiary_of"
        }
        vessel_ids_by_call = {call.call_id: call.vessel_id for call in effective.values()}
        org_id_by_name = state.store.org_ids()
        for entry in effective_calls:
            vessel_id = entry.get("vessel_id")
            operator = operators_by_vessel.get(vessel_id)
            if operator:
                entry["operator"] = operator
                org_id = org_id_by_name.get(operator)
                entry["operator_id"] = org_id
                entry["halcyon_subsidiary_operated"] = bool(org_id and org_id in subsidiaries)
        for entry in overlaps:
            vessel_id = vessel_ids_by_call.get(entry["call_id"])
            operator = operators_by_vessel.get(vessel_id)
            if operator:
                entry["operator"] = operator
                org_id = org_id_by_name.get(operator)
                entry["operator_id"] = org_id
                entry["halcyon_subsidiary_operated"] = bool(org_id and org_id in subsidiaries)
        return {
            "notice": (
                {
                    "notice_id": notice.notice_id,
                    "berth": notice.berth_name,
                    "berth_id": notice.berth_id,
                    "window": format_window(notice.window),
                }
                if notice
                else None
            ),
            "effective_calls": effective_calls,
            "overlaps": overlaps,
            "exclusions": exclusions,
            "corrections_applied": [
                {
                    "call_id": a.call_id,
                    "correction_id": a.correction_id,
                    "status": a.status,
                    "reason": a.reason,
                }
                for a in applications
            ],
            "relationships": relationships,
            "shipments": self._shipment_view(state),
            "proposed_alternatives": self._proposals_view(state),
            "graph_views": state.graph_views,
            "excluded_evidence": [reason for _, reason in state.store.excluded_after_cutoff],
        }

    def _proposals_view(self, state: _RunState) -> list[dict[str, Any]]:
        """Handling-proposal records: pending items only, never approvals."""
        rows = []
        for facts in state.store.parsed_facts():
            for proposal in facts.proposals:
                rows.append(
                    {
                        "request_id": proposal.request_id,
                        "shipment_id": proposal.shipment_id,
                        "facility": proposal.facility,
                        "approved": proposal.approved,
                        "pending_items": list(proposal.pending_items),
                        "source_id": proposal.source_id,
                        "evidence_ids": list(proposal.evidence_ids),
                    }
                )
        return rows

    def _shipment_view(self, state: _RunState) -> list[dict[str, Any]]:
        rows = []
        for link in state.store.shipments():
            rows.append(
                {
                    "call_id": link.call_id or None,
                    "shipment_id": link.shipment_id,
                    "description": link.description,
                    "recipient": link.recipient,
                    "facility": link.facility,
                    "receipt_deadline": link.receipt_deadline.isoformat() if link.receipt_deadline else None,
                    "status": "recorded",
                    "delivered": False,
                    "source_id": link.source_id,
                }
            )
        for item in state.store.proposals():
            if item.published_at and item.published_at > state.as_of:
                continue
            rows.append(
                {
                    "call_id": None,
                    "shipment_id": item.shipment_id,
                    "description": None,
                    "recipient": None,
                    "facility": item.facility,
                    "receipt_deadline": None,
                    "status": "pending",
                    "delivered": False,
                    "proposal": {
                        "request_id": item.request_id,
                        "pending_items": item.pending_items,
                        "approved": False,
                    },
                    "source_id": item.source_id,
                }
            )
        return rows

    def _assemble(self, state: _RunState, question: str, agent_result: AgentRunResult, use_scripted: bool) -> FinalResult:
        pipeline = self._pipeline(state)
        warnings = list(state.store.warnings)
        if agent_result.error:
            warnings.append(agent_result.error)
        unresolved_questions: list[str] = []
        claims: list[Claim] = []
        claim_counter = 0

        def add_claim(text: str, evidence_ids: list[str], status: ClaimStatus) -> None:
            nonlocal claim_counter
            claim_counter += 1
            claims.append(Claim(claim_id=f"claim-{claim_counter:03d}", text=text, evidence_ids=evidence_ids, status=status))

        evidence_by_source = {item.source_id: item for item in state.store.items}

        for overlap in pipeline["overlaps"]:
            call_ids = [item.evidence_id for item in state.store.items if item.source_id in _sources_for_call(overlap["call_id"], state)]
            notice_evidence = [item.evidence_id for item in state.store.items if item.source_id == "D06"]
            add_claim(
                f"{overlap['call_id']} overlaps the closure notice with {overlap['overlap_hours']} hours of "
                "planned occupancy. This is planned exposure; actual delay is not established.",
                sorted(set(call_ids + notice_evidence)),
                ClaimStatus.DETERMINISTIC_DERIVATION,
            )
        for exclusion in pipeline["exclusions"]:
            evidence_ids = [item.evidence_id for item in state.store.items if item.source_id in _sources_for_call(exclusion["call_id"], state)]
            add_claim(
                f"{exclusion['call_id']} is excluded: {exclusion['reason']}",
                evidence_ids,
                ClaimStatus.DETERMINISTIC_DERIVATION,
            )

        identity = state.store.identities()
        for candidate in identity:
            if candidate.canonical_id == "SYN-V001" and candidate.alias_of:
                add_claim(
                    f"{candidate.name} is SYN-V001, formerly named {candidate.alias_of}; Southern Kestrel "
                    "(SYN-V004) is a different vessel.",
                    candidate.evidence_ids,
                    ClaimStatus.SOURCE_STATEMENT,
                )
                break

        for relationship in pipeline["relationships"]:
            if relationship["relationship"] in {"operated_by", "subsidiary_of"}:
                add_claim(
                    f"{relationship['source_entity']} {relationship['relationship'].replace('_', ' ')} "
                    f"{relationship['target_entity']}.",
                    relationship["evidence_ids"],
                    ClaimStatus.SOURCE_STATEMENT,
                )

        for row in pipeline["shipments"]:
            if row.get("status") == "pending":
                pending = ", ".join(row.get("proposal", {}).get("pending_items") or [])
                add_claim(
                    f"Handling proposal for {row['shipment_id']} at {row['facility']} remains pending"
                    + (f" ({pending})" if pending else "")
                    + ". No diversion is approved.",
                    [item.evidence_id for item in state.store.items if item.source_id == row["source_id"]],
                    ClaimStatus.SOURCE_STATEMENT,
                )
            else:
                chain = " -> ".join(
                    str(part)
                    for part in (
                        row.get("call_id"),
                        row.get("shipment_id"),
                        row.get("recipient"),
                        row.get("facility"),
                    )
                    if part
                )
                deadline = f", receipt requested by {row['receipt_deadline']}" if row.get("receipt_deadline") else ""
                add_claim(
                    f"Shipment chain {chain}{deadline}. No delivery is recorded.",
                    [item.evidence_id for item in state.store.items if item.source_id in (row.get("source_id") or "").split("+")],
                    ClaimStatus.SOURCE_STATEMENT,
                )

        claim_problems = validate_claim_evidence(claims, state.store.ids())
        warnings.extend(claim_problems)

        # Status determination
        notice_present = pipeline.get("notice") is not None
        had_hard_errors = any(event.is_hard_error for event in agent_result.tool_events)
        if not state.store.items:
            status = RunStatus.FAILED if (agent_result.error or had_hard_errors) else RunStatus.NEEDS_INPUT
            if not agent_result.error and not had_hard_errors:
                unresolved_questions.append(
                    "No register passages were retrieved for this question. "
                    "Rephrase the question or ask about calls, berths, vessels, or shipments."
                )
        elif not notice_present:
            status = RunStatus.NEEDS_INPUT
            unresolved_questions.append(
                "No closure notice was found in the retrieved evidence. "
                "Name the notice ID (for example SYN-N017) to evaluate schedule overlap."
            )
        elif agent_result.status in {RunStatus.FAILED, RunStatus.PARTIAL} or had_hard_errors:
            status = RunStatus.PARTIAL if pipeline["overlaps"] or pipeline["effective_calls"] else RunStatus.FAILED
        elif claim_problems:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.COMPLETE

        # The published brief uses validated tool values, not unverified model prose.
        summary = self._deterministic_summary(pipeline, question)
        self._last_summary_source = "deterministic"
        warnings.extend(guard_summary(summary))

        unresolved_questions.extend(_unresolved_from_pipeline(pipeline))
        actions_for_review = []
        for row in pipeline["shipments"]:
            if row.get("status") == "pending":
                proposal = row.get("proposal", {})
                actions_for_review.append(
                    f"Proposal {proposal.get('request_id')}: confirm terminal slot and landside transport "
                    f"for {row['shipment_id']} at {row['facility']} (proposal only; no action executed)."
                )
        actions_for_review.append(
            "Review the impact brief and evidence before any operational decision; this tool takes no action."
        )

        tool_events = agent_result.tool_events
        if not any(event.tool_name == "evaluate_call_overlap" for event in tool_events):
            tool_events.append(
                ToolEvent(
                    tool_name="deterministic_pipeline_evaluation",
                    duration_ms=0,
                    outcome="ok",
                    evidence_ids=[item.evidence_id for item in state.store.items],
                    detail="executed by the demo pipeline (agent did not request it)",
                )
            )

        return FinalResult(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            demo_id="impact",
            generated_at=datetime.now(timezone.utc),
            analysis_cutoff=state.as_of,
            agent_mode="scripted" if use_scripted else "live",
            data_mode=self._settings.data_mode,
            status=status,
            summary=summary,
            claims=claims,
            unresolved_questions=unresolved_questions,
            actions_for_review=actions_for_review,
            tool_events=tool_events,
            demo_specific_result=pipeline,
            warnings=warnings,
        )

    def _deterministic_summary(self, pipeline: dict[str, Any], question: str) -> str:
        notice = pipeline.get("notice") or {}
        parts = []
        if notice:
            parts.append(
                f"Notice {notice.get('notice_id')} closes {notice.get('berth')} ({notice.get('berth_id')}) "
                f"{notice.get('window')}."
            )
        overlaps = pipeline.get("overlaps", [])
        if overlaps:
            described = "; ".join(
                f"{o['call_id']} ({o.get('operator') or o.get('vessel_id') or 'vessel'}, {o['overlap_hours']} h planned occupancy)"
                for o in overlaps
            )
            parts.append(f"Overlapping calls: {described}.")
        else:
            parts.append("No retrieved call overlaps the closure window." if notice else "No closure determination can be made: the required notice/evidence is unavailable.")
        exclusions = pipeline.get("exclusions", [])
        if exclusions:
            parts.append(
                "Excluded: " + "; ".join(f"{e['call_id']} ({e['reason']})" for e in exclusions[:4]) + "."
            )
        shipments = [s for s in pipeline.get("shipments", []) if s.get("status") == "recorded"]
        for shipment in shipments:
            parts.append(
                f"Shipment chain: {shipment.get('call_id')} -> {shipment.get('shipment_id')} -> "
                f"{shipment.get('recipient')} -> {shipment.get('facility')}. No delivery recorded."
            )
        pending = [s for s in pipeline.get("shipments", []) if s.get("status") == "pending"]
        for row in pending:
            parts.append(
                f"Pending proposal {row.get('proposal', {}).get('request_id')} for {row.get('shipment_id')}: "
                + ", ".join(row.get("proposal", {}).get("pending_items") or [])
                + ". No diversion approved."
            )
        parts.append("Actual delay is not established by these records; overlap is planned occupancy.")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_excerpt(text: str, limit: int = 700) -> str:
    cleaned = TRAILING_ISSUED_RE.sub("", " ".join(text.split()))
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _sources_for_call(call_id: str, state: _RunState) -> set[str]:
    sources = set()
    for facts in state.store.parsed_facts():
        for call in facts.calls:
            if call.call_id == call_id:
                sources.add(facts.source_id)
    return sources


def _unresolved_from_pipeline(pipeline: dict[str, Any]) -> list[str]:
    unresolved = []
    for row in pipeline.get("shipments", []):
        if row.get("status") == "pending":
            unresolved.append(
                "Terminal-slot confirmation and landside transport approval for the "
                f"{row.get('shipment_id')} handling proposal remain pending."
            )
    for correction in pipeline.get("corrections_applied", []):
        if correction["status"] == "unresolved":
            unresolved.append(f"Schedule for {correction['call_id']} is unresolved: {correction['reason']}")
    return unresolved
