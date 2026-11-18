"""Regenerate the document catalog and Markdown from the included PDF."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pattern1/scripts'))
from index_corpus import parse_sections
out=ROOT/'assets/graph/documents';out.mkdir(parents=True,exist_ok=True)
rows=parse_sections(ROOT/'assets/graph/ami_maritime_graph_corpus.pdf')
(out/'catalog.json').write_text(json.dumps(rows,indent=2))
for row in rows:
    (out/(row['section_id']+'.md')).write_text('# '+row['title']+'\n\nSynthetic exercise — Asteria Maritime Insights.\n\n'+row['text']+'\n')
print(f'Exported {len(rows)} synthetic documents.')
