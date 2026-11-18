"""Maritime source document and graph explorer."""
import json
from pathlib import Path
import httpx
import streamlit as st
from demos.graph_view import _render_graph_view

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return json.loads((ROOT / 'assets/graph/documents/catalog.json').read_text())


@st.dialog('Explore the maritime evidence', width='large')
def show_data(kind, backend):
    docs = catalog()
    if kind == 'graph':
        st.subheader('Source-parsed Neo4j graph')
        st.caption('Live graph neighborhoods. Select an entity to explore its connected records; this view is not filtered by an investigation cutoff.')
        focus = st.selectbox('Start from an entity', ['SYN-C101', 'SYN-V001', 'SYN-O01', 'SYN-G01', 'SYN-N017', 'SYN-B04', 'SYN-S101', 'SYN-C103', 'SYN-U09'])
        try:
            response = httpx.get(backend + '/v1/graph/evidence', params={'entities': focus, 'max_nodes':25, 'max_edges':35}, timeout=15)
            response.raise_for_status()
            graph = response.json()
            st.markdown(_render_graph_view(graph), unsafe_allow_html=True)
            st.caption(f"{len(graph['nodes'])} nodes · {len(graph['edges'])} relationships in this neighborhood")
            st.dataframe([{'From':e['source'], 'Relationship':e['relationship'], 'To':e['target'], 'Source':', '.join(c.get('section_id','') for c in e['chunks'])} for e in graph['edges']], hide_index=True, use_container_width=True)
            ids = {c['section_id'] for e in graph['edges'] for c in e['chunks'] if c.get('section_id')}
            docs = [d for d in docs if d['section_id'] in ids]
        except (httpx.HTTPError, KeyError) as exc:
            st.error(f'Live graph unavailable: {type(exc).__name__}. No fixture graph substituted.')
            return
    elif kind == 'maritime':
        st.subheader('Maritime records')
        docs = docs[:5]
    elif kind == 'operations':
        st.subheader('Operational evidence')
        docs = docs[5:]
    else:
        st.subheader('12 synthetic source documents')
    st.caption('Select a document below to read its complete source text.')
    if not docs:
        st.info('No source documents returned for this neighborhood.')
        return
    chosen = st.radio('Documents', [f"{d['section_id']} · {d['title']}" for d in docs], key=f'doc_{kind}')
    doc = docs[[f"{d['section_id']} · {d['title']}" for d in docs].index(chosen)]
    with st.container(border=True):
        st.markdown(f"### {doc['section_id']} — {doc['title']}")
        st.caption('SYNTHETIC EXERCISE · Asteria Maritime Insights')
        body = doc['text'].split('\n',1)[-1]
        st.write(body)
    st.download_button('Download this document as text', doc['text'], file_name=f"{doc['section_id']}.txt", mime='text/plain')
