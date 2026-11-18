import unittest
from pathlib import Path
from scripts.build_source_graph import build_rows
from scripts.index_corpus import parse_sections

class SourceGraph(unittest.TestCase):
    def test_graph_has_source_backed_identity_and_closure_links(self):
        source=Path(__file__).resolve().parents[2]/'assets/graph/ami_maritime_graph_corpus.pdf'
        nodes,edges=build_rows(parse_sections(source))
        triples={(e['source'],e['predicate'],e['target'],e['section']) for e in edges}
        self.assertIn(('SYN-C101','has_vessel','SYN-V001','D04'),triples)
        self.assertIn(('SYN-N017','closes','SYN-B04','D06'),triples)
        self.assertIn(('SYN-U09','corrects','SYN-C103','D09'),triples)
        self.assertFalse(any('delay' in e['predicate'] or 'approved' in e['predicate'] for e in edges))

    def test_ids_are_parsed_from_input_not_prebuilt_graph(self):
        source=Path(__file__).resolve().parents[2]/'assets/graph/ami_maritime_graph_corpus.pdf'
        sections=parse_sections(source)
        sections[3]['text']=sections[3]['text'].replace('SYN-C101','SYN-C999')
        _,edges=build_rows(sections)
        call_edges=[e for e in edges if e['section']=='D04']
        self.assertTrue(any(e['source']=='SYN-C999' for e in call_edges))
        self.assertFalse(any(e['source']=='SYN-C101' for e in call_edges))
