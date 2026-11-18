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
    agent, data, demo = st.columns(3)
    with agent:
        st.markdown('<section class="ami-card"><h3>Agent</h3>'
            f'<div class="ami-status">Current execution: {escape(labels.agent)} · local process</div>'
            + _flow(
                ('Port Impact Analyst', 'One coordinating agent plans the investigation and selects tools.', True),
                ('Evidence & graph tools', 'Retrieve source passages and inspect connected Neo4j records.'),
                ('Impact & shipment tools', 'Calculate schedule overlap, apply corrections and trace cargo recipients.'),
                ('Evidence-backed brief', 'Assemble validated findings, exclusions and the tool action log.'),
            )
            + '<div class="ami-boundary"><strong>Maritime OpenShell worker — active</strong>'
            '<p>Dedicated ami-maritime sandbox runs the access-test tool worker. Graph RAG and model inference remain host services.</p>'
            '<p>Maritime policy: endpoint/method allowlists; restricted filesystem writes; Landlock best-effort compatibility.</p>'
            '<p><b>The access-test worker is sandboxed. The dashboard and model-driven investigator run locally.</b></p></div></section>', unsafe_allow_html=True)
    with data:
        from demos.data_explorer import show_data
        with st.container(border=True):
            st.markdown('### Data')
            st.caption(f'{labels.data} · fictional maritime exercise')
            for title, detail, kind in [
                ('12 synthetic source documents', 'Browse D01–D12 and read each document.', 'documents'),
                ('Maritime records', 'Vessels, aliases, companies, ports and scheduled visits.', 'maritime'),
                ('Operational evidence', 'Closure, corrections, shipments, proposals and receiving assignments.', 'operations'),
                ('Source-parsed Neo4j graph', 'Explore connected entities and source-backed relationships.', 'graph'),
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
    from demos.maritime_policy import show_maritime_policy
    if st.button('Maritime OpenShell — live denial scenario', use_container_width=True):
        show_maritime_policy()
    with st.expander('Maritime OpenShell policy & execution boundary'):
        st.markdown('''**Verified boundary:** Local dashboard → **OpenShell [ami-maritime access-test worker]** → maritime Graph RAG on **8010** (allowed). An outside-policy document destination on **8031** is denied.

The model-driven Port Impact Analyst currently runs locally; full investigator sandbox deployment is not claimed.

One model-driven agent coordinates four tool responsibilities; these are not four separately deployed agents.

| Maritime worker policy | Applied from `deployment/sandbox-policy.yaml` |
|---|---|
| Graph RAG egress | Host gateway, port 8010: POST `/v1/retrieve`, `/v1/responses`; GET `/health`, `/v1/graph/status`, `/v1/graph/evidence` |
| Model egress | Host gateway, port 11434: POST `/v1/chat/completions`; GET `/v1/models` |
| Process scope | Network rules scoped to `/usr/local/bin/python3.12` |
| Filesystem | Work directory included; listed system paths read-only; `/tmp` and `/dev/null` writable |
| Enforcement settings | Network `enforce`; Landlock `best_effort`; endpoint TLS setting `skip` |
| Application controls | Bounded tool calls and deadlines; source citations; cutoff filtering; no booking or diversion actions |

**Runtime distinction:** This session runs locally, outside OpenShell. The cluster pipeline is the origin of the starter kit; the current UI is not calling the cluster. Endpoint allow/deny enforcement is verified for the ami-maritime worker. Document-path filtering and full investigator sandbox execution are not verified.''')
