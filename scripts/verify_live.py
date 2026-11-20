"""Verify live retrieval, extracted graph, temporal results and optionally the model agent."""
import argparse,json,sys,time
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from adapters.llm import LLMClient
from adapters.sandbox import SandboxAnalyst, execution_mode
from demos.port_impact import PortImpactAnalyst
from shared.configuration import Settings
from shared.exports import build_impact_brief

QUESTION='Which Halcyon subsidiary-operated calls overlap notice SYN-N017, and which shipments are connected?'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent',action='store_true')
    args=parser.parse_args()
    settings=replace(Settings.load(),data_mode='live',agent_mode='scripted')
    url=settings.graph_pattern_url
    status=httpx.get(url+'/v1/graph/status',timeout=10).json()
    assert status['available'],status
    print('Graph:',status,flush=True)
    payload=httpx.post(url+'/v1/retrieve',json={'input':QUESTION},timeout=45).json()
    assert len({e['metadata']['section_id'] for e in payload['evidence']})==12
    graph=httpx.get(url+'/v1/graph/evidence',params={'entities':'SYN-C101,SYN-N017','max_nodes':25,'max_edges':35},timeout=15).json()
    assert {'SYN-C101','SYN-N017'} <= {n['name'] for n in graph['nodes']},graph
    assert any(e['chunks'] for e in graph['edges']),graph
    output=ROOT/'docs/verified-runs'
    output.mkdir(exist_ok=True)
    (output/'graph-evidence.json').write_text(json.dumps(graph,indent=2))
    for tag,cutoff,expected in [
        ('current','2026-11-17T12:00:00Z',{'SYN-C101':8.0}),
        ('before-correction','2026-11-16T12:00:00Z',{'SYN-C101':8.0,'SYN-C103':5.0}),
    ]:
        analyst=PortImpactAnalyst(settings)
        result=analyst.run(QUESTION,cutoff)
        overlaps={o['call_id']:o['overlap_hours'] for o in result.demo_specific_result['overlaps']}
        assert result.status.value=='complete',result.model_dump_json()
        assert overlaps==expected,overlaps
        assert all(event.outcome=='ok' for event in result.tool_events)
        assert all(claim.evidence_ids for claim in result.claims)
        assert result.demo_specific_result['overlaps'][0]['operator']=='Meridian Shelf Shipping'
        (output/(tag+'.json')).write_text(result.model_dump_json(indent=2))
        (output/(tag+'.md')).write_text(build_impact_brief(result))
        print('PASS',tag,overlaps,flush=True)
    if args.agent:
        live=replace(settings,agent_mode='live')
        llm=LLMClient(live.model_endpoint,live.model_id,live.model_api_key,timeout_seconds=60)
        analyst=SandboxAnalyst(live) if execution_mode(live)=="openshell" else PortImpactAnalyst(live,llm)
        start=time.monotonic()
        result=analyst.run(QUESTION,'2026-11-17T12:00:00Z')
        (output/'live-agent.json').write_text(result.model_dump_json(indent=2))
        (output/'live-agent.md').write_text(build_impact_brief(result))
        print('Live agent:',result.status.value,'elapsed',round(time.monotonic()-start,1),'runtime',execution_mode(live),flush=True)
        print('Tools:',[(event.tool_name,event.outcome) for event in result.tool_events],flush=True)
        assert result.status.value=='complete',result.model_dump_json()
        assert result.agent_mode=='live' and result.data_mode=='live'
        assert result.demo_specific_result['overlaps'][0]['call_id']=='SYN-C101'
        assert len(result.demo_specific_result['overlaps'])==1
        assert all(e.outcome=='ok' for e in result.tool_events)
        assert any(e.tool_name=='get_graph_evidence' for e in result.tool_events)
    print('PASS live acceptance; artifacts:',output)

if __name__=='__main__':main()
