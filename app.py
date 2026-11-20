"""Asteria Maritime Insights — Port Impact Investigator.

Streamlit single-process UI and orchestration with architecture diagrams.

Run with:
    .venv/bin/streamlit run app.py --server.port 8501 --server.headless true
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.llm import LLMClient
from demos.graph_view import render_impact_graph
from demos.port_impact import PortImpactAnalyst
from shared.configuration import ModeLabels, Settings, check_configuration
from shared.contracts import FinalResult, RunStatus
from shared.exports import build_impact_brief, build_run_record

st.set_page_config(
    page_title="AMI — Port Impact Investigator",
    page_icon="🛳️",
    layout="wide",
)

SAMPLE_QUESTIONS = [
    "Which Halcyon subsidiary-operated calls overlap notice SYN-N017, and which shipments are connected?",
    "Why is Amber Shoal not affected by the Berth B4 closure?",
    "Is Northline Kestrel the same vessel as Southern Kestrel? What are their Berth B4 calls?",
    "Which calls overlap notice SYN-N017?",
    "Has the alternative handling proposal for shipment SYN-S101 been approved?",
    "Query the register for dragons",
    "Please trigger backend failure for testing",
]

CUTOFF_PRESETS = {
    "Exercise cutoff (2026-11-17 12:00 UTC, after correction D09)": "2026-11-17T12:00:00Z",
    "Before correction D09 (2026-11-16 12:00 UTC)": "2026-11-16T12:00:00Z",
}

STATUS_STYLES = {
    RunStatus.COMPLETE: ("ok", "✅ Complete"),
    RunStatus.PARTIAL: ("warn", "⚠️ Partial — some tool calls failed"),
    RunStatus.NEEDS_INPUT: ("info", "❓ Needs input"),
    RunStatus.FAILED: ("error", "⛔ Failed"),
}


@st.cache_resource(show_spinner=False)
def get_settings() -> Settings:
    return Settings.load()


def get_analyst(settings: Settings) -> PortImpactAnalyst:
    from adapters.sandbox import SandboxAnalyst, execution_mode
    if execution_mode(settings) == "openshell":
        return SandboxAnalyst(settings)
    llm = None
    if settings.agent_mode == "live":
        llm = LLMClient(
            base_url=settings.model_endpoint,
            model_id=settings.model_id,
            api_key=settings.model_api_key,
            timeout_seconds=60.0,
        )
    return PortImpactAnalyst(settings, llm=llm)


def render_header() -> None:
    settings = get_settings()
    labels = ModeLabels.from_settings(settings)
    st.markdown(
        f"""
        <div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">
          <span style="font-size:1.5rem; font-weight:700;">🛳️ Asteria Maritime Insights</span>
          <span style="opacity:.75;">agentic demo workspace — synthetic data only</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    from demos.architecture_view import render_architecture
    render_architecture(settings, labels)
    problems = check_configuration(settings)
    if problems:
        st.warning("**Configuration problems:**\n\n" + "\n".join(f"- {p}" for p in problems))


def render_result(result: FinalResult, stale: bool) -> None:
    kind, title = STATUS_STYLES[result.status]
    if stale:
        st.warning("Inputs changed since this run — press **Run investigation** to refresh.")
    {
        "ok": st.success,
        "warn": st.warning,
        "info": st.info,
        "error": st.error,
    }[kind](f"**{title}** — run `{result.run_id}`")

    st.markdown("### Summary")
    st.markdown(result.summary or "_No summary._")
    st.caption("Brief assembled from validated tool results; the live model selects the tools.")

    pipeline = result.demo_specific_result

    # Call table
    st.markdown("### Calls evaluated")
    overlaps_by_call = {o["call_id"]: o for o in pipeline.get("overlaps", [])}
    call_rows = []
    for call in pipeline.get("effective_calls", []):
        overlap = overlaps_by_call.get(call["call_id"])
        call_rows.append(
            {
                "Call": call["call_id"],
                "Vessel": call.get("vessel") or call.get("vessel_id"),
                "Operator": call.get("operator") or "—",
                "Berth": call.get("berth"),
                "Port": call.get("port") or "—",
                "Effective window (UTC)": call.get("window"),
                "Verdict": (
                    f"OVERLAP {overlap['overlap_hours']} h planned"
                    + (" · Halcyon subsidiary" if overlap.get("halcyon_subsidiary_operated") else "")
                    if overlap
                    else next(
                        (e["reason"] for e in pipeline.get("exclusions", []) if e["call_id"] == call["call_id"]),
                        "excluded",
                    )
                ),
            }
        )
    if call_rows:
        st.dataframe(call_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No calls were reconstructed from the retrieved evidence.")

    col_left, col_right = st.container(), st.container()
    with col_left:
        st.markdown("### Impact graph")
        label, svg = render_impact_graph(pipeline)
        st.caption(label)
        st.markdown(
            f"<div style='overflow-x:auto'>{svg}</div>",
            unsafe_allow_html=True,
        )
        # Sortable edge table: every displayed edge with its source backing.
        edges = pipeline.get("relationships", [])
        if pipeline.get("graph_views"):
            view = pipeline["graph_views"][-1]
            edges = edges + [
                {
                    "source_entity": edge.get("source"),
                    "relationship": edge.get("relationship"),
                    "target_entity": edge.get("target"),
                    "source_id": (edge.get("chunks") or [{}])[0].get("section_id", "extracted"),
                }
                for edge in view.get("edges", [])
            ]
        if edges:
            st.dataframe(
                [
                    {
                        "Source": edge.get("source_entity"),
                        "Relationship": edge.get("relationship"),
                        "Target": edge.get("target_entity"),
                        "Source ID": edge.get("source_id"),
                        "Evidence": "source-backed" if edge.get("source_id") else "—",
                    }
                    for edge in edges
                ],
                use_container_width=True,
                hide_index=True,
            )
    with col_right:
        st.markdown("### Shipments")
        for row in pipeline.get("shipments", []):
            if row.get("status") == "pending":
                proposal = row.get("proposal", {})
                st.markdown(
                    f"**{row.get('shipment_id')}** — proposal `{proposal.get('request_id')}` at "
                    f"{row.get('facility')} — pending: {', '.join(proposal.get('pending_items') or [])}. "
                    "**No diversion approved.**"
                )
            else:
                st.markdown(
                    f"**{row.get('shipment_id')}** (from {row.get('call_id') or '—'}) — "
                    f"{row.get('description') or 'cargo not stated'} — for "
                    f"{row.get('recipient') or '—'} → {row.get('facility') or '—'}"
                    + (f", receipt by {row.get('receipt_deadline')}" if row.get("receipt_deadline") else "")
                    + ". _No delivery recorded._"
                )
        notice = pipeline.get("notice")
        if notice:
            st.markdown(
                f"**:lock: {notice.get('notice_id')}** — {notice.get('berth')} "
                f"({notice.get('berth_id')}), {notice.get('window')}"
            )

    # Evidence-first detail tabs
    tab_evidence, tab_corrections, tab_actions = st.tabs(
        ["Evidence", "Corrections & exclusions", "Actions & tool log"]
    )
    with tab_evidence:
        store_items = st.session_state.get("evidence_items", [])
        if store_items:
            for item in store_items:
                st.markdown(
                    f"**{item['evidence_id']} — {item['source_id']}** · published "
                    f"{item.get('published_at') or 'unknown'}"
                )
                st.markdown(f"> {item['excerpt']}")
        else:
            st.caption("No evidence returned.")
    with tab_corrections:
        for correction in pipeline.get("corrections_applied", []):
            st.markdown(
                f"- **{correction.get('call_id')}** — {correction.get('status')}: "
                f"{correction.get('reason')}"
            )
        excluded = pipeline.get("excluded_evidence", [])
        if excluded:
            st.markdown("**Evidence not used (published after the cutoff):**")
            for reason in excluded:
                st.markdown(f"- {reason}")
        if result.unresolved_questions:
            st.markdown("**Unresolved:**")
            for question in result.unresolved_questions:
                st.markdown(f"- {question}")
    with tab_actions:
        for event in result.tool_events:
            st.markdown(
                f"- `{event.tool_name}` — {event.outcome} in {event.duration_ms} ms — {event.detail}"
            )
        st.markdown("**For review (no action executed):**")
        for action in result.actions_for_review:
            st.markdown(f"- {action}")
        if result.warnings:
            st.markdown("**Warnings:**")
            for warning in result.warnings:
                st.markdown(f"- {warning}")

    st.divider()
    dl_left, dl_right = st.columns(2)
    dl_left.download_button(
        "⬇️ Download impact brief (Markdown)",
        data=build_impact_brief(result),
        file_name=f"impact-brief-{result.run_id}.md",
        mime="text/markdown",
    )
    dl_right.download_button(
        "⬇️ Download run record (JSON)",
        data=build_run_record(result),
        file_name=f"run-{result.run_id}.json",
        mime="application/json",
    )


def main() -> None:
    st.session_state.pop("policy_probe", None)  # Discard obsolete cross-demo probe results.
    render_header()
    settings = get_settings()

    investigation, whole_graph = st.tabs(["Run investigation", "Full Graph RAG"])
    with whole_graph:
        from demos.graph_overview import render_overview
        if settings.data_mode == "live":
            render_overview(settings.graph_pattern_url)
        else:
            st.info("The complete graph view requires the live Graph RAG backend. Fixture rehearsal does not query it.")
    with investigation:
        st.markdown(
            "**Investigate:** which scheduled vessel visits (port calls) overlap a berth closure, who is affected, "
            "and what shipments are connected. Every claim carries evidence; exclusions carry reasons."
        )
        form = st.form("run_form")
        question = form.selectbox(
            "Question",
            SAMPLE_QUESTIONS if settings.data_mode == "fixture" else SAMPLE_QUESTIONS[:-2],
            index=0,
            help="Pick a sample question or type your own below.",
        )
        custom = form.text_input("…or type a custom question", value="")
        preset = form.radio(
            "Analysis cutoff (as-of)",
            list(CUTOFF_PRESETS.keys()),
            index=0,
            horizontal=True,
        )
        submitted = form.form_submit_button("▶️ Run investigation", type="primary", use_container_width=True)

        if submitted:
            final_question = custom.strip() or question
            cutoff = CUTOFF_PRESETS[preset]
            analyst = get_analyst(settings)
            with st.spinner(
                f"Running PortImpactAnalyst ({'scripted rehearsal' if settings.agent_mode == 'scripted' else settings.model_id})…"
            ):
                try:
                    result = analyst.run(final_question, cutoff)
                except Exception as exc:  # noqa: BLE001 - surface cleanly in UI
                    st.error(f"Run failed: {type(exc).__name__}: {exc}")
                    st.stop()
            st.session_state["result"] = result
            st.session_state["evidence_items"] = [
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "excerpt": (" ".join(item.excerpt.split()))[:400] + ("…" if len(item.excerpt) > 400 else ""),
                }
                for item in analyst.last_evidence()
            ]
            st.session_state["run_inputs"] = {"question": final_question, "cutoff": cutoff}

        result = st.session_state.get("result")
        if result:
            run_inputs = st.session_state.get("run_inputs", {})
            current = {
                "question": (custom.strip() or question) if "question" in locals() else "",
                "cutoff": CUTOFF_PRESETS[preset] if "preset" in locals() else "",
            }
            stale = run_inputs != current
            render_result(result, stale)
        else:
            st.info("Configure the question and cutoff, then run the investigation.")


if __name__ == "__main__":
    main()
