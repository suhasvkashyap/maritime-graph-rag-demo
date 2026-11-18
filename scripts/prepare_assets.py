"""Prepare Demo 3 assets: the synthetic twelve-section corpus PDF.

Generates ``assets/graph/ami_maritime_graph_corpus.pdf`` from the source of
truth in ``fixtures/corpus_sections.py`` and writes a manifest describing the
synthetic data. The PDF is the artifact that gets indexed into the local Neo4j
Graph AutoRAG collection.

Usage:
    python scripts/prepare_assets.py [--demo impact] [--mode fixture|live]

``--mode`` selects which checks run; both modes require the corpus PDF, so it
is always generated (idempotent).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fixtures.corpus_sections import SECTIONS, section_full_text  # noqa: E402

PDF_PATH = ROOT / "assets" / "graph" / "ami_maritime_graph_corpus.pdf"
MANIFEST_PATH = ROOT / "fixtures" / "corpus_manifest.json"


def build_pdf(out_path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.set_title("AMI synthetic maritime graph corpus (Demo 3)")

    for section in SECTIONS:
        pdf.add_page()
        # Banner line
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, 4.5, section_banner_text(section))
        pdf.ln(2)
        # Section id + title
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, f"{section.section_id}  {section.title}")
        pdf.ln(4)
        pdf.set_draw_color(180, 180, 180)
        pdf.line(20, pdf.get_y(), 190, pdf.get_y())
        pdf.ln(4)
        # Body
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, section.text)
        # Issue time footer
        pdf.ln(4)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.multi_cell(0, 5, f"Issued {section.published_at}. Fictional exercise data.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


def section_banner_text(section) -> str:
    from fixtures.corpus_sections import section_banner

    return section_banner(section)


def build_manifest() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo_id": "impact",
        "classification": "synthetic",
        "notice": (
            "All names, identifiers, vessels, organizations, times and events are "
            "fictional exercise data for Asteria Maritime Insights (AMI)."
        ),
        "analysis_cutoff": "2026-11-17T12:00:00Z",
        "pdf": str(PDF_PATH.relative_to(ROOT)),
        "sections": [
            {
                "section_id": s.section_id,
                "title": s.title,
                "published_at": s.published_at,
                "characters": len(s.text),
            }
            for s in SECTIONS
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", choices=["impact"], default="impact")
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    args = parser.parse_args()

    build_pdf(PDF_PATH)
    print(f"Wrote {PDF_PATH.relative_to(ROOT)} ({len(SECTIONS)} sections)")

    MANIFEST_PATH.write_text(json.dumps(build_manifest(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH.relative_to(ROOT)}")

    # Verify the PDF is selectable text and round-trips through pypdf.
    from pypdf import PdfReader

    reader = PdfReader(str(PDF_PATH))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    missing = [s.section_id for s in SECTIONS if f"{s.section_id}" not in extracted]
    if missing:
        print(f"ERROR: sections missing from extracted PDF text: {missing}", file=sys.stderr)
        return 1
    print(f"Verified {len(reader.pages)} pages; all {len(SECTIONS)} section IDs present in extracted text")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
