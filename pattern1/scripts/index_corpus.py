"""Index the AMI Demo 3 synthetic corpus into the local Neo4j (Pattern1).

Laptop-local equivalent of the Graph AutoRAG document-indexing pipeline:

1. Extracts the twelve section texts from the generated corpus PDF
   (``ami_maritime_graph_corpus.pdf``) with pypdf.
2. Embeds each section with the OpenAI-compatible endpoint configured in
   ``agent_config.json`` (Ollama bge-m3 locally, MaaS on the cluster).
3. Upserts the chunks via ai4rag's ``Neo4jGraphStore.add_documents`` WITH a
   foundation model, so entity/relation extraction runs (SimpleKGPipeline,
   constrained schema) and graph search can expand through the knowledge
   graph.

Run from the pattern1 directory with the kit venv:

    .venv/bin/python scripts/index_corpus.py --corpus ../assets/graph/ami_maritime_graph_corpus.pdf

Reads NEO4J_* / MAAS_* from the environment or ``.env``. Safe to re-run into
the same collection: chunks are deduplicated by deterministic IDs and MERGE
upserts. Never point this at a collection you did not create for this demo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]

SECTION_MARKER = re.compile(
    r"^SYNTHETIC DEMO ONLY \| Asteria Maritime Insights \| (?P<section_id>D\d\d) - (?P<title>[^|]+)\|",
    re.MULTILINE,
)


def load_agent_config() -> dict:
    return json.loads((KIT_ROOT / "agent_config.json").read_text(encoding="utf-8"))


def parse_sections(corpus_path: Path) -> list[dict]:
    """Return one chunk per corpus section, with section provenance metadata."""
    from pypdf import PdfReader

    reader = PdfReader(str(corpus_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    matches = list(SECTION_MARKER.finditer(text))
    if len(matches) != 12:
        raise SystemExit(
            f"ERROR: expected 12 section banners in {corpus_path.name}, found {len(matches)}"
        )
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Remove the banner's issue timestamp and the repeated page heading.
        body = re.sub(r"^Issued [^\n]+\n", "", body)
        body = re.sub(r"^" + re.escape(match.group("section_id")) + r"\s+" + re.escape(match.group("title").strip()) + r"\s*\n", "", body)
        # Strip the trailing issue-time footer line the PDF adds.
        body = re.sub(r"\nIssued [^\n]+\. Fictional exercise data\.\s*$", "", body).strip()
        body = " ".join(body.split())
        sections.append(
            {
                "section_id": match.group("section_id"),
                "title": match.group("title").strip(),
                "text": f"Section {match.group('section_id')} ({match.group('title').strip()}):\n{body}",
            }
        )
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=KIT_ROOT.parent / "assets" / "graph" / "ami_maritime_graph_corpus.pdf",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Embed and upsert chunks only; skip LLM entity/relation extraction.",
    )
    parser.add_argument(
        "--extraction-model",
        default="ami-demo3-qwen",
        help="Ollama model for KG extraction (8k-context variant of the chat model).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Extraction attempts per chunk before continuing.",
    )
    parser.add_argument("--section", choices=[f"D{i:02d}" for i in range(1, 13)], help="Extract one section first to validate the local model.")
    parser.add_argument("--request-timeout", type=float, default=90.0, help="Per model request timeout; no hidden 20-minute retry.")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(KIT_ROOT / ".env")

    config = load_agent_config()
    collection = config["vector_store"]["collection_name"]
    if collection == "ai4rag_ami_demo3_source":
        raise SystemExit("This is the source-parsed demo collection. Use build_source_graph.py; select a separate collection for model-extraction experiments.")
    model_id = config["generation"]["model_id"]
    embedding_model_id = config["embedding"]["model_id"]
    embedding_dimension = int(config["embedding"]["dimension"])

    sections = parse_sections(args.corpus)
    print(f"Corpus: {args.corpus.name} -> {len(sections)} sections")
    for section in sections:
        print(f"  {section['section_id']}: {len(section['text'])} chars")

    import os

    from openai import OpenAI
    from ai4rag.rag.chunking.chunk import AI4RAGChunk
    from ai4rag.rag.embedding.openai_model import OpenAIEmbeddingModel, OpenAIEmbeddingParams
    from agentic_rag.bounded_model import ExtractionFoundationModel
    from ai4rag.rag.vector_store import get_vector_store, get_vector_store_config

    base_url = os.getenv("MAAS_BASE_URL", "http://localhost:11434/v1").strip().rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    client = OpenAI(
        api_key=os.getenv("MAAS_API_KEY") or "ollama",
        base_url=base_url,
        timeout=args.request_timeout,
        max_retries=0,  # retries handled per chunk in the extraction loop
    )

    embedding_model = OpenAIEmbeddingModel(
        client=client,
        model_id=embedding_model_id,
        params=OpenAIEmbeddingParams(embedding_dimension=embedding_dimension, context_length=8192),
    )

    foundation_model = None
    if not args.skip_extraction:
        # KG extraction prompts (schema + examples + chunk) exceed the 4k chat
        # context; use the 8k-context variant created from qwen3:4b.
        foundation_model = ExtractionFoundationModel(
            client=client,
            model_id=args.extraction_model,
            params={"temperature": 0.0, "max_completion_tokens": 3072},
            system_message_text="/no_think",
        )

    store = get_vector_store(
        embedding_model=embedding_model,
        config=get_vector_store_config(config["vector_store"]["provider_type"]),
        collection_name=collection,
        foundation_model=None,  # embed first; extraction is explicit below
        kg_extraction_config={"mode": "constrained", "max_completion_tokens": 3072},
    )

    chunks = [
        AI4RAGChunk(
            text=section["text"],
            metadata={
                "document_id": args.corpus.name,
                "source": args.corpus.name,
                "section_id": section["section_id"],
                "section_title": section["title"],
                "sequence_number": position,
                "headings": [section["section_id"]],
                "synthetic": True,
            },
        )
        for position, section in enumerate(sections)
    ]

    if foundation_model is not None:
        # Embed first (fast, no LLM), then extract per chunk with retries so a
        # transient Ollama failure cannot discard the whole run.
        print(f"Embedding {len(chunks)} chunks...")
        store.add_documents(chunks)
        print(f"Extracting entities/relations with {args.extraction_model} (one chunk at a time)...")
        failures: list[str] = []
        for index, chunk in enumerate(chunks):
            if args.section and chunk.metadata.get("section_id") != args.section:
                continue
            section_id = chunk.metadata.get("section_id", f"chunk-{index}")
            ok = False
            for attempt in range(1, args.retries + 1):
                try:
                    store._run_kg_pipeline(
                        chunks=[chunk],
                        model=foundation_model,
                        max_concurrent=1,
                        on_error="RAISE",
                        perform_entity_resolution=True,
                    )
                    with store._driver.session(database=store._config.database) as session:
                        row = session.run(
                            "MATCH (e:__Entity__)-[:FROM_CHUNK]->(c:Chunk) "
                            "WHERE c.id=$cid AND c.collection=$col RETURN count(e) AS n",
                            cid=chunk.chunk_id, col=collection,
                        ).single()
                    if not row or not row['n']:
                        raise ValueError('Extraction wrote no source-linked entities')
                    ok = True
                    break
                except Exception as exc:  # noqa: BLE001 - retry transient failures
                    print(
                        f"  [{section_id}] extraction attempt {attempt}/{args.retries} failed: "
                        f"{type(exc).__name__}: {str(exc)[:120]}",
                        flush=True,
                    )
                    time.sleep(3.0)
            print(f"  [{section_id}] {'extracted' if ok else 'FAILED (continuing)'}", flush=True)
            if not ok:
                failures.append(section_id)
        if failures:
            print(f"WARNING: extraction failed for {len(failures)} chunk(s): {failures}", file=sys.stderr)
    else:
        print("Embedding chunks (extraction skipped)...")
        store.add_documents(chunks)
    if foundation_model is not None and failures:
        return 1
    print(f"Indexed {len(chunks)} chunks into collection '{collection}'")

    probe = "Which vessel call overlaps the Berth B4 closure notice SYN-N017?"
    results = store.search(probe, k=3, search_mode="graph", include_scores=True)
    print("\nSmoke search (top 3):")
    for chunk, score in results:
        print(f"  {score:.3f}  {chunk.metadata.get('section_id', '?')}")
    if not results:
        print("ERROR: search returned no results", file=sys.stderr)
        return 1
    print("\nOK: chunk indexing and retrieval verified (this does not prove entity-graph coverage).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
