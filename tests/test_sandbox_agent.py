import json
from dataclasses import replace
from types import SimpleNamespace
import urllib.error

import httpx
import pytest

from adapters.llm import AssistantMessage, LLMClient
from adapters.sandbox import SandboxAnalyst, execution_mode, require_inference_provider
from demos.document_tool import DOCUMENT_URLS, document_tool
from demos.maritime_policy import match_denials
from demos.port_impact import PortImpactAnalyst
from shared.agent_loop import BoundedToolLoop
from shared.configuration import Settings
from shared.contracts import ErrorCode


def test_provider_inference_uses_openai_format(monkeypatch):
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'done'}}]},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    history = [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'type': 'function',
                'function': {'name': 'fetch', 'arguments': '{"url":"x"}'}}]}]
    LLMClient('http://192.168.127.254:11434/v1', 'ami-demo3-qwen', 'unused').chat(history, tools=[])
    assert captured['url'] == 'http://192.168.127.254:11434/v1/chat/completions'
    assert captured['json']['messages'] == history
    assert captured['headers']['Authorization'] == 'Bearer unused'
    assert 'verify' not in captured  # no disabled TLS verification


def fail_opener(monkeypatch, reason):
    attempts = []
    class Opener:
        def open(self, url, timeout):
            attempts.append(url)
            raise urllib.error.URLError(reason)
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: Opener())
    return attempts


def test_model_selects_second_document_and_receives_actual_failure(monkeypatch):
    attempts = fail_opener(monkeypatch, PermissionError(13, 'Permission denied'))
    rows = []
    class Model:
        def chat(self, messages, tools=None):
            if messages[-1]['role'] == 'tool':
                assert DOCUMENT_URLS[1] in messages[-1]['content']
                assert 'permission_denied' in messages[-1]['content']
                return AssistantMessage('Supplement unavailable; continuing with existing evidence.')
            return AssistantMessage('', [{'id': 'chosen', 'name': 'fetch_synthetic_document',
                                          'arguments': {'url': DOCUMENT_URLS[1]}}])
    result = BoundedToolLoop(Model(), [document_tool(rows)]).run('Investigate', 'Check a supplement')
    assert attempts == [DOCUMENT_URLS[1]]
    assert rows[0]['selected_by'] == 'model'
    assert result.tool_events[0].error_code == 'permission_denied'
    assert result.final_text.startswith('Supplement unavailable')


def test_no_model_attempt_means_no_network_probe(monkeypatch):
    attempts = fail_opener(monkeypatch, PermissionError(13, 'Permission denied'))
    rows = []
    class Model:
        def chat(self, messages, tools=None):
            return AssistantMessage('No supplement is needed.')
    BoundedToolLoop(Model(), [document_tool(rows)]).run('Investigate', 'Check evidence')
    assert rows == attempts == []


@pytest.mark.parametrize('reason', [ConnectionRefusedError(61, 'refused'), TimeoutError('timeout')])
def test_network_failure_is_not_permission_denial(monkeypatch, reason):
    fail_opener(monkeypatch, reason)
    rows = []
    result = document_tool(rows).execute({'url': DOCUMENT_URLS[0]})
    assert result.error_code == ErrorCode.BACKEND_UNAVAILABLE
    assert not match_denials('[11.0] DENIED 192.168.127.254:8031', rows, 10, 12)


def test_non_catalog_url_is_validation_not_network_denial(monkeypatch):
    attempts = fail_opener(monkeypatch, PermissionError(13, 'denied'))
    rows = []
    result = document_tool(rows).execute({'url': 'http://example.com/'})
    assert result.error_code == ErrorCode.VALIDATION
    assert rows == attempts == []


def test_audit_rejects_stale_wrong_destination_and_missing_attempt():
    rows = [{'selected_by': 'model', 'errno': 13, 'destination': '192.168.127.254:8031'}]
    valid = '[11.0] DENIED 192.168.127.254:8031'
    assert match_denials(valid, rows, 10, 12) == valid
    assert not match_denials(valid, rows, 12, 15)
    assert not match_denials(valid, rows, 0, 10)
    assert not match_denials(valid.replace(':8031', ':80310'), rows, 10, 12)
    assert not match_denials(valid.replace('DENIED', 'ALLOWED'), rows, 10, 12)
    assert not match_denials(valid, [], 10, 12)
    assert not match_denials('unparseable DENIED 192.168.127.254:8031', rows, 10, 12)


def test_missing_provider_fails_without_local_fallback(monkeypatch):
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(returncode=2))
    with pytest.raises(RuntimeError, match='inference provider is not ready'):
        require_inference_provider('openshell')


def test_live_defaults_to_sandbox_and_rehearsal_to_local(monkeypatch):
    monkeypatch.delenv('AMI_EXECUTION_MODE', raising=False)
    settings = Settings.load()
    assert execution_mode(replace(settings, agent_mode='live')) == 'openshell'
    assert execution_mode(replace(settings, agent_mode='scripted')) == 'local'


def test_host_dispatches_full_agent_without_local_credentials(monkeypatch):
    settings = replace(Settings.load(), agent_mode='scripted', data_mode='fixture', model_api_key='secret-value')
    expected = PortImpactAnalyst(settings).run('Which calls overlap SYN-N017?', settings.analysis_cutoff)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ["sandbox", "provider", "list"]:
            return SimpleNamespace(returncode=0, stdout="ami-maritime-inference")
        return SimpleNamespace(returncode=0, stdout=json.dumps({'runtime': 'openshell',
            'model_endpoint': 'http://192.168.127.254:11434/v1', 'result': expected.model_dump(mode='json'),
            'evidence': []}))
    monkeypatch.setattr('adapters.sandbox.cli_path', lambda: 'openshell')
    monkeypatch.setattr('subprocess.run', run)
    analyst = SandboxAnalyst(replace(settings, agent_mode="live", data_mode="live"))
    assert analyst.run('question; $(echo nope)', settings.analysis_cutoff).run_id == expected.run_id
    command = calls[-1]
    assert command[-2] == 'demos.sandbox_agent'
    assert json.loads(command[-1])['question'] == 'question; $(echo nope)'
    assert 'secret-value' not in str(command)
    assert analyst.last_evidence() == []


def test_entrypoint_forces_live_provider_endpoint(monkeypatch):
    from demos.sandbox_agent import run_request
    settings = replace(Settings.load(), agent_mode='scripted', data_mode='fixture')
    expected = PortImpactAnalyst(settings).run('Which calls overlap SYN-N017?', settings.analysis_cutoff)
    captured = {}
    class Analyst:
        document_requests = []
        def __init__(self, settings, llm, policy_challenge):
            captured.update(settings=settings, challenge=policy_challenge)
        def run(self, question, cutoff, scripted):
            assert scripted is False
            return expected
        def last_evidence(self):
            return []
    monkeypatch.setattr('demos.sandbox_agent.PortImpactAnalyst', Analyst)
    result = run_request({'question': 'calls', 'analysis_cutoff': settings.analysis_cutoff,
                          'model_id': 'routed', 'challenge': True, 'max_tool_calls': 6,
                          'request_timeout_seconds': 180})
    actual = captured['settings']
    assert actual.agent_mode == actual.data_mode == 'live'
    assert actual.model_endpoint == 'http://192.168.127.254:11434/v1'
    assert actual.model_api_key == 'unused'
    assert captured['challenge'] is True
    assert result['runtime'] == 'openshell'


@pytest.mark.parametrize('retrieved,attempted,expected', [(True, True, True), (False, True, False), (True, False, False)])
def test_challenge_verification_requires_retrieval_and_model_attempt(monkeypatch, retrieved, attempted, expected):
    from demos.maritime_policy import probe
    from shared.contracts import ToolEvent
    settings = replace(Settings.load(), agent_mode='scripted', data_mode='fixture')
    result = PortImpactAnalyst(settings).run('Which calls overlap SYN-N017?', settings.analysis_cutoff)
    result.tool_events = [ToolEvent(tool_name='retrieve_maritime_relationships', duration_ms=1,
                                   outcome='ok' if retrieved else 'error')]
    class Analyst:
        started = 10
        payload = {'requests': [{'selected_by': 'model', 'errno': 13,
                                 'destination': '192.168.127.254:8031'}] if attempted else [],
                   'model_calls': 2, 'model_endpoint': 'http://192.168.127.254:11434/v1'}
        def __init__(self, settings):
            pass
        def run(self, *args, **kwargs):
            assert kwargs['challenge'] is True
            return result
    monkeypatch.setattr('demos.maritime_policy.SandboxAnalyst', Analyst)
    monkeypatch.setattr('demos.maritime_policy.cli_path', lambda: 'openshell')
    monkeypatch.setattr('demos.maritime_policy.time.time', lambda: 12)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(returncode=0,
                        stdout='[11.0] DENIED 192.168.127.254:8031', stderr=''))
    assert probe()['verified'] is expected


def test_provider_attached_allows_dispatch(monkeypatch):
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='NAME TYPE\nami-maritime-inference ami-maritime-inference\n'))
    require_inference_provider('openshell')


def test_other_provider_does_not_satisfy_preflight(monkeypatch):
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='NAME TYPE\nother-inference other-inference\n'))
    with pytest.raises(RuntimeError, match='inference provider is not ready'):
        require_inference_provider('openshell')
