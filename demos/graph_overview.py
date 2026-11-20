"""Whole-collection relationship map; no graph sampling or fixture substitution."""
import json
from pathlib import Path

import httpx
import streamlit as st
import streamlit.components.v1 as components


@st.cache_data(ttl=30, show_spinner=False)
def load_overview(backend):
    response = httpx.get(backend.rstrip('/') + '/v1/graph/overview', timeout=15)
    response.raise_for_status()
    graph = response.json()
    if (graph.get('complete') is not True or len(graph['nodes']) != graph['node_count']
            or len(graph['edges']) != graph['edge_count']):
        raise ValueError('Backend did not return a complete graph.')
    ids = {n['id'] for n in graph['nodes']}
    if any(e['source_id'] not in ids or e['target_id'] not in ids for e in graph['edges']):
        raise ValueError('Graph contains a relationship with a missing endpoint.')
    return graph


def overview_html(graph):
    # JSON is embedded in a script element; escape HTML delimiters from source data.
    payload = json.dumps(graph).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return Path(__file__).with_suffix('.html').read_text().replace('__GRAPH_DATA__', payload)


def render_overview(backend, key='overview'):
    st.subheader('The whole maritime graph')
    st.caption('All entities and directed relationships in the live demo collection, including corrections and proposals. This overview is not filtered by the investigation cutoff; source chunks are available on each relationship.')
    if st.button('Refresh graph', key=key + '_refresh'):
        load_overview.clear()
    try:
        graph = load_overview(backend)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        st.error(f'Full graph unavailable: {exc}. No sampled or fixture graph is substituted.')
        return
    if not graph['nodes']:
        st.info('This collection has no entities yet.')
        return
    st.caption(f"{graph['node_count']} entities · {graph['edge_count']} relationships · {graph['collection']}")
    components.html(overview_html(graph), height=790, scrolling=False)
    with st.expander('All relationships and source documents'):
        st.dataframe([{'From': e['source'], 'Relationship': e['relationship'].replace('_', ' '),
                       'To': e['target'], 'Sources': ', '.join(c.get('section_id') or c['chunk_id'] for c in e['chunks'])}
                      for e in graph['edges']], hide_index=True, use_container_width=True)
    st.download_button('Download complete graph JSON', json.dumps(graph, indent=2),
                       file_name='maritime-full-graph.json', mime='application/json', key=key + '_download')
