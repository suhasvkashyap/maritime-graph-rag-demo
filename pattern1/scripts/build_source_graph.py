"""Build a source-parsed Neo4j graph from the actual structured PDF, not fixtures.

This demo-specific ingestion adapter uses the same typed passage parser as
its evidence evaluator. No model extraction or precomputed answer is used.
"""
import sys,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"pattern1"))
from scripts.index_corpus import parse_sections,load_agent_config,KIT_ROOT
from dotenv import load_dotenv
load_dotenv(KIT_ROOT/'.env')
from shared.validation import parse_passage
from adapters.graph_pattern import SECTION_PUBLISHED_AT
from agentic_rag.agent import create_rag
from ai4rag.rag.chunking.chunk import AI4RAGChunk


def build_rows(sections):
    facts=[parse_passage(s['text'],s['section_id'],[s['section_id']],SECTION_PUBLISHED_AT[s['section_id']]) for s in sections]
    names={};berths={}
    for f in facts:
        names.update(f.org_ids)
        for c in f.calls:
            if c.berth_id:berths[c.berth_name]=c.berth_id
    edges=[];nodes={}
    def node(value,label='Entity',display=None):
        value=names.get(value,berths.get(value,value))
        if value not in nodes:nodes[value]={'name':value,'display_name':display or value,'kind':label,'sections':[]}
        elif display:nodes[value]['display_name']=display
        return value
    def edge(a,predicate,b,section):
        a=node(a);b=node(b)
        for value in [a,b]:
            if section not in nodes[value]['sections']:nodes[value]['sections'].append(section)
        edges.append({'source':a,'target':b,'predicate':predicate,'section':section})
    for f in facts:
        sid=f.source_id
        for name,id_ in f.org_ids.items():node(id_,'Organization',name)
        for i in f.identities:
            node(i.canonical_id,'Vessel',i.name)
            if i.alias_of:edge(i.canonical_id,'formerly_named',i.alias_of,sid)
            for other in i.distinct_from:edge(i.canonical_id,'distinct_from',other,sid)
        for r in f.relationships:
            if r.relationship!='independent_of_groups':edge(r.source_entity,r.relationship,r.target_entity,sid)
        for c in f.calls:
            node(c.call_id,'PlannedCall');node(c.vessel_id,'Vessel',c.vessel_name)
            edge(c.call_id,'has_vessel',c.vessel_id,sid)
            edge(c.call_id,'planned_at_berth',c.berth_id or c.berth_name,sid)
        for berth,port in f.berth_ports.items():edge(berth,'located_in',port,sid)
        for n in f.notices:node(n.notice_id,'Notice');edge(n.notice_id,'closes',n.berth_id or n.berth_name,sid)
        for s in f.shipments:
            node(s.shipment_id,'Shipment')
            if s.call_id:edge(s.call_id,'carries',s.shipment_id,sid)
            if s.recipient:edge(s.shipment_id,'for_recipient',s.recipient,sid)
            if s.facility:edge(s.shipment_id,'requested_receipt_at',s.facility,sid)
        for c in f.corrections:node(c.correction_id,'Correction');edge(c.correction_id,'corrects',c.call_id,sid)
        for p in f.proposals:
            node(p.request_id,'Proposal');edge(p.request_id,'concerns',p.shipment_id,sid)
            edge(p.request_id,'proposed_alternative',p.facility,sid)
    return list(nodes.values()),edges


def main():
    corpus=ROOT/'assets/graph/ami_maritime_graph_corpus.pdf'
    sections=parse_sections(corpus)
    nodes,edges=build_rows(sections)
    rag=create_rag();store=rag.retriever._vector_store
    col=store._collection_name
    if col!='ai4rag_ami_demo3_source':raise SystemExit('Set collection to ai4rag_ami_demo3_source before building this adapter')
    chunks=[AI4RAGChunk(text=s['text'],metadata={'document_id':corpus.name,'source':corpus.name,'section_id':s['section_id'],'section_title':s['title'],'sequence_number':i,'synthetic':True,'extraction_method':'source_parsed'}) for i,s in enumerate(sections)]
    store.add_documents(chunks)
    chunk_ids={s['section_id']:c.chunk_id for s,c in zip(sections,chunks)}
    for n in nodes:n['key']=col+'|'+n['name']
    for e in edges:e.update(source_key=col+'|'+e['source'],target_key=col+'|'+e['target'],chunk_id=chunk_ids[e['section']])
    with store._driver.session(database=store._config.database) as session:
        session.run('UNWIND $nodes AS row MERGE (n:__Entity__ {demo_key:row.key}) SET n.name=row.name,n.display_name=row.display_name,n.kind=row.kind,n.ai4rag_kg_collections=[$col],n.extraction_method="source_parsed"',nodes=nodes,col=col).consume()
        session.run('UNWIND $edges AS row MATCH (a:__Entity__ {demo_key:row.source_key}),(b:__Entity__ {demo_key:row.target_key}),(c:Chunk {id:row.chunk_id,collection:$col}) MERGE (a)-[r:RELATED_TO {predicate:row.predicate,section_id:row.section}]->(b) SET r.ai4rag_kg_collections=[$col],r.source_chunk_id=row.chunk_id,r.extraction_method="source_parsed" MERGE (a)-[:FROM_CHUNK]->(c) MERGE (b)-[:FROM_CHUNK]->(c)',edges=edges,col=col).consume()
    report={'collection':col,'construction':'source_parsed','chunks':len(chunks),'nodes':len(nodes),'edges':len(edges),'mapped_sections':sorted({e['section'] for e in edges})}
    (ROOT/'docs/source-graph-build.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    store._driver.close()

if __name__=='__main__':main()
