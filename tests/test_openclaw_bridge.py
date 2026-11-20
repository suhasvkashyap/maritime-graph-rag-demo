from dataclasses import replace
from datetime import datetime
import pytest
from pydantic import ValidationError
from adapters.openclaw_bridge import InvestigationRequest, delegate
from shared.configuration import Settings
from demos.port_impact import PortImpactAnalyst

@pytest.mark.parametrize('payload', [
    {'question': 'investigate', 'as_of': '2026-11-17'},
    {'question': 'investigate', 'as_of': '2026-11-17T12:00:00'},
    {'question': 'investigate', 'as_of': 'invalid'},
    {'question': 'x', 'as_of': '2026-11-17T12:00:00Z'},
    {'question': 'investigate', 'as_of': '2026-11-17T12:00:00Z', 'command': 'anything'},
])
def test_invalid_request_rejected(payload):
    with pytest.raises(ValidationError):
        InvestigationRequest.model_validate(payload)

@pytest.mark.parametrize('cutoff,expected', [
    ('2026-11-17T12:00:00Z', [('SYN-C101', 8.0)]),
    ('2026-11-16T12:00:00Z', [('SYN-C101', 8.0), ('SYN-C103', 5.0)]),
])
def test_delegation_preserves_evidence_and_temporal_results(monkeypatch, tmp_path, cutoff, expected):
    settings = replace(Settings.load(), agent_mode='scripted', data_mode='fixture')
    fixture = PortImpactAnalyst(settings)
    result = fixture.run('Which Halcyon subsidiary-operated calls overlap SYN-N017, and which shipments are connected?', cutoff)
    captured = {}
    class FakeSandbox:
        def __init__(self, settings):
            assert settings.agent_mode == settings.data_mode == 'live'
        def run(self, question, analysis_cutoff):
            captured.update(question=question, cutoff=analysis_cutoff)
            return result
        def last_evidence(self):
            return fixture.last_evidence()
    monkeypatch.setattr('adapters.openclaw_bridge.ROOT', tmp_path)
    monkeypatch.setattr('adapters.openclaw_bridge.SandboxAnalyst', FakeSandbox)
    request = InvestigationRequest(question='Question; $(do not execute)', as_of=cutoff)
    output = delegate(request)
    assert captured['question'] == request.question
    assert datetime.fromisoformat(captured['cutoff']) == request.as_of
    assert sorted((o['call_id'], o['overlap_hours']) for o in output['overlaps']) == expected
    assert output['status'] == result.status.value
    assert output['claims'] == [c.model_dump(mode='json') for c in result.claims]
    assert output['sources']
    assert all(e['source_id'] for e in output['sources'])
    from pathlib import Path
    assert Path(output['artifact']).is_file()


def test_partial_result_is_not_promoted(monkeypatch, tmp_path):
    from shared.contracts import RunStatus
    settings = replace(Settings.load(), agent_mode='scripted', data_mode='fixture')
    fixture = PortImpactAnalyst(settings)
    result = fixture.run('Which calls overlap SYN-N017?', settings.analysis_cutoff)
    result.status = RunStatus.PARTIAL
    result.warnings = ['Supplement unavailable']
    class FakeSandbox:
        def __init__(self, settings): pass
        def run(self, *args): return result
        def last_evidence(self): return fixture.last_evidence()
    monkeypatch.setattr('adapters.openclaw_bridge.ROOT', tmp_path)
    monkeypatch.setattr('adapters.openclaw_bridge.SandboxAnalyst', FakeSandbox)
    output = delegate(InvestigationRequest(question='Investigate', as_of=settings.analysis_cutoff))
    assert output['status'] == 'partial'
    assert output['warnings'] == ['Supplement unavailable']


def test_sandbox_failure_has_no_fallback(monkeypatch, tmp_path):
    class BrokenSandbox:
        def __init__(self, settings): pass
        def run(self, *args): raise RuntimeError('sandbox unavailable')
    monkeypatch.setattr('adapters.openclaw_bridge.ROOT', tmp_path)
    monkeypatch.setattr('adapters.openclaw_bridge.SandboxAnalyst', BrokenSandbox)
    with pytest.raises(RuntimeError, match='sandbox unavailable'):
        delegate(InvestigationRequest(question='Investigate', as_of='2026-11-17T12:00:00Z'))
    assert not list(tmp_path.rglob('*.json'))
