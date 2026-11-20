"""Presenter-facing architecture diagrams; runtime and deployment intent stay distinct."""
from html import escape

import streamlit as st


def _box(title, detail, accent=False):
    return f'<div class="ami-node {"ami-accent" if accent else ""}"><strong>{escape(title)}</strong><span>{escape(detail)}</span></div>'


def _flow(*nodes):
    return '<div class="ami-arrow" aria-hidden="true">↓</div>'.join(_box(*node) for node in nodes)


def render_architecture(settings, labels):
    st.markdown('''<style>
    .ami-card {border:1px solid #d2d2d2;border-top:4px solid #ee0000;border-radius:10px;padding:20px;height:100%;background:var(--secondary-background-color);}
    .ami-card h3 {margin:0 0 8px;font-size:1.25rem;}
    .ami-status {font-size:.8rem;color:#646464;margin-bottom:16px;line-height:1.5;}
    .ami-node {border:1px solid #b8c5cc;border-radius:7px;padding:12px;background:var(--background-color);}
    .ami-node strong {display:block;font-size:.95rem;}
    .ami-node span {display:block;font-size:.83rem;line-height:1.5;margin-top:5px;}
    .ami-accent {border-left:4px solid #ee0000;}
    .ami-arrow {text-align:center;color:#737373;font-size:23px;line-height:30px;}
    .ami-boundary {border:2px dashed #89949e;border-radius:8px;padding:12px;margin-top:14px;}
    .ami-boundary strong {font-size:.88rem;}
    .ami-boundary p {font-size:.81rem;line-height:1.5;margin:7px 0 0;}
    </style>''', unsafe_allow_html=True)
    from adapters.sandbox import execution_mode
    runtime = execution_mode(settings)
    agent, data, demo = st.columns(3)
    with agent:
        st.markdown('<section class="ami-card"><h3>Agent</h3>'
            f'<div class="ami-status">Current execution: {escape(labels.agent)} · {escape(runtime)}</div>'
            + _flow(
                ('Port Impact Analyst', 'One coordinating agent plans the investigation and selects tools.', True),
                ('Evidence & graph tools', 'Retrieve source passages and inspect connected Neo4j records.'),
                ('Impact & shipment tools', 'Calculate schedule overlap, apply corrections and trace cargo recipients.'),
                ('Evidence-backed brief', 'Assemble validated findings, exclusions and the tool action log.'),
            )
            + '<div class="ami-boundary"><strong>Maritime OpenShell agent — configured</strong>'
            '<p>Live mode dispatches the complete investigator to ami-maritime-agent. Graph RAG stays external; model access uses an attached OpenShell provider.</p>'
            '<p>Maritime policy: endpoint/method allowlists; restricted filesystem writes; Landlock best-effort compatibility.</p>'
            '<p><b>The dashboard stays local. Sandbox execution requires the OpenShell inference provider; the challenge displays observed verification.</b></p></div></section>', unsafe_allow_html=True)
    with data:
        from demos.data_explorer import show_data
        with st.container(border=True):
            st.markdown('### Data')
            st.caption(f'{labels.data} · fictional maritime exercise')
            for title, detail, kind in [
                ('12 synthetic source documents', 'Browse D01–D12 and read each document.', 'documents'),
                ('Maritime records', 'Vessels, aliases, companies, ports and scheduled visits.', 'maritime'),
                ('Operational evidence', 'Closure, corrections, shipments, proposals and receiving assignments.', 'operations'),
                ('View full Graph RAG', 'All entities and relationships in one interactive map.', 'graph'),
            ]:
                if st.button(title, key='explore_' + kind, use_container_width=True):
                    show_data(kind, settings.graph_pattern_url)
                st.caption(detail)
                st.markdown('<div class="ami-arrow">↓</div>', unsafe_allow_html=True)
            st.markdown('**Time-aware evidence**')
            st.caption('Investigation results respect the selected analysis cutoff.')
    with demo:
        st.markdown('<section class="ami-card"><h3>Demo</h3>'
            '<div class="ami-status">Port Impact Investigator</div>'
            + _flow(
                ('Red Hat OpenShift AI 3.6', 'Graph RAG pipeline created on the cluster; starter kit used for this demo.', True),
                ('Local Graph RAG adaptation', 'Source-parsed PDF ingestion → Neo4j graph retrieval. Current requests use the local backend.'),
                ('Analyst question + cutoff', 'Which scheduled vessel visits overlap the berth closure, and which shipments are connected?'),
                ('Agent + connected evidence', 'Join notice → berth → vessel visit → vessel/operator and shipment/recipient.'),
                ('Decision-support output', 'Impact graph, planned overlap hours, source citations and reasons for exclusions.'),
            ) + '</section>', unsafe_allow_html=True)
    with st.expander('OpenClaw conversational investigation'):
        st.markdown("""OpenClaw adds follow-up questions, historical comparisons, and draft handoffs using the **same sandboxed investigator**.

**Flow:** OpenClaw browser chat → maritime delegation tool → **OpenShell investigator** → Graph RAG → source-backed findings → OpenClaw briefing.

The local assistant runs outside OpenShell. Graph RAG comes from an OpenShift AI-generated starter kit; current model and knowledge requests run locally. Cluster hosting is a separate deployment option.

Start with `./scripts/install_openclaw.sh`, then `.venv/bin/python scripts/start_openclaw.py`. Open authenticated chat with `./scripts/openclaw.sh dashboard`.

Try: “Investigate SYN-N017 as of 2026-11-17T12:00:00Z.” Then: “Compare with 2026-11-16T12:00:00Z and explain C103.”

Run investigations sequentially. The original denial challenge below remains the place to verify network enforcement.""")
    from demos.maritime_policy import show_maritime_policy
    if st.button('Maritime OpenShell — live denial scenario', use_container_width=True):
        show_maritime_policy()
    with st.expander('Maritime OpenShell policy & execution boundary'):
        st.markdown("""**Configured boundary:** Local dashboard → **OpenShell [ami-maritime-agent: full investigator]** → Graph RAG on **8010**. Model access comes from the attached **ami-maritime-inference** provider profile, separate from the base sandbox policy.

The model selects an optional synthetic document URL on port **8031**. Verification requires a model-selected permission error, fresh matching audit evidence and successful graph retrieval. No attempt is reported as unverified.

The bounded model loop, tools, evidence validation and brief assembly execute inside the sandbox. The dashboard and data explorer remain local. Explicit local/rehearsal mode does not claim isolation.

Filesystem: `/app` and system paths read-only, `/tmp` writable; Landlock best-effort. This challenge verifies destination enforcement, not document-path or filesystem enforcement.

**OpenShell 0.1.9:** Uses provider profiles and sandbox attachments. The retired `inference.local` route is not used. The agent never falls back to host execution.""")
