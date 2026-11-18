import unittest
from pathlib import Path
from scripts.index_corpus import parse_sections

class CorpusParsing(unittest.TestCase):
    def test_page_headers_do_not_pollute_entity_names(self):
        sections=parse_sections(Path(__file__).resolve().parents[2] / 'assets/graph/ami_maritime_graph_corpus.pdf')
        self.assertEqual(len(sections),12)
        body=sections[1]['text'].split('\n',1)[1]
        self.assertTrue(body.startswith('Meridian Shelf Shipping, SYN-O01'),body)
        self.assertNotIn('Fictional exercise data.',body)
