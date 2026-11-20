"""Maritime source document and graph explorer."""
import json
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return json.loads((ROOT / 'assets/graph/documents/catalog.json').read_text())


@st.dialog('Explore the maritime evidence', width='large')
def show_data(kind, backend):
    docs = catalog()
    if kind == 'graph':
        from demos.graph_overview import render_overview
        render_overview(backend, key='dialog_overview')
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
