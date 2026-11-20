import json
import re
import httpx
import pytest
from demos.graph_overview import load_overview, overview_html


def test_html_embeds_source_text_without_script_injection():
    graph = {'nodes': [{'name': '</script><script>alert(1)</script>&'}], 'edges': []}
    page = overview_html(graph)
    payload = re.search(r'id="graph-data">(.*?)</script>', page).group(1)
    assert '<script>' not in payload
    assert json.loads(payload) == graph


@pytest.mark.parametrize('data', [
    {'complete': False, 'nodes': [], 'edges': [], 'node_count': 0, 'edge_count': 0},
    {'complete': True, 'nodes': [], 'edges': [], 'node_count': 31, 'edge_count': 0},
    {'complete': True, 'nodes': [], 'edges': [{'source_id': 'missing', 'target_id': 'missing'}], 'node_count': 0, 'edge_count': 1},
])
def test_rejects_incomplete_or_disconnected_payload(monkeypatch, data):
    load_overview.clear()
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: httpx.Response(
        200, json=data, request=httpx.Request('GET', url)))
    with pytest.raises(ValueError):
        load_overview('http://localhost:8010')
