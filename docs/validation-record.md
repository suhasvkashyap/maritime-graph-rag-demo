# Demo 3 — verified local validation record

Date: 2026-11-18. Validation notes for the synthetic maritime demo. Runtime artifacts are generated locally and intentionally excluded from Git.

## Verified implementation

- Live Neo4j collection: `ai4rag_ami_demo3_source`.
- 12 PDF chunks, 31 source-parsed entities, 35 relationships; exact source-section links are stored on edges.
- Graph edges are parsed from the actual structured synthetic PDF, not loaded from the expected fixture graph. D08/D10 remain retrievable document evidence; graph edges cover the other ten sections.
- Live model: `ami-demo3-qwen`, based on installed Qwen2.5 7B weights. The real model selects tools through Ollama. Required successful evidence tools are enforced before accepting its final response.
- Graph AutoRAG starter-kit retriever is used with Neo4j graph search. A retrieval-only endpoint avoids nested model agents. All twelve sections are retrieved for this bounded exercise packet so schedule corrections cannot disappear below a top-k cutoff.
- Published summaries are constructed from validated tool values. Temporal correction, identity, interval and shipment logic is deterministic. This is not autonomous booking or operational decision making.

## Acceptance evidence

`python scripts/verify_live.py --agent` passed:

1. Live graph status and actual source-linked graph inspection.
2. Twelve distinct corpus sections returned through the HTTP retrieval endpoint.
3. Default cutoff: C101 alone, 8 hours planned occupancy; operator Meridian Shelf Shipping.
4. Earlier cutoff: C101 8h and C103 5h; later correction excluded.
5. Live agent complete, successful retrieval, overlap, shipment and graph tools; no fixture substitution. Final measured acceptance run: approximately **52.7 seconds**, six model calls. Timing is specific to this laptop/run, not a product benchmark.

The application suite has **74 passing tests** and the service/ingestion suite **7 passing tests**. Tests cover tool JSON serialization and native history, evidence surviving FastAPI serialization, required-tool completion, source parsing, graph IDs derived from changed input, graph query parameters, correction precedence and interval boundaries.

Actual artifacts: `verified-runs/current.json`, `before-correction.json`, `live-agent.json`, corresponding Markdown briefs, and `graph-evidence.json`. `source-graph-build.json` records ingestion counts.

Browser verification also completed investigation `run-55074cf777af`: the UI displayed Complete, C101's 8-hour overlap, exclusions, citations and the live graph. Screenshot: `verified-runs/browser-graph.jpg`. The browser automation timed out while checking the JSON download, so the download button is not recorded as verified; use the saved acceptance artifacts above if needed. Both service health endpoints remained healthy after that timeout.

## Important scope and limits

This is a working **local adaptation** of the Graph AutoRAG starter kit, not proof that generic automatic LLM graph extraction works. The generic model extraction path had inconsistent IDs/relationships; it is retained only for experiments in separate collections. The demo labels its live graph **source-parsed**. Its domain parser targets this register format, not arbitrary PDFs.

A dedicated `ami-maritime` OpenShell tool worker is now deployed with the maritime policy. The recorded live probe verifies allowed Graph RAG port 8010 (HTTP 200) and denied destination port 8031 (errno 13 plus a fresh DENIED audit event). See `verified-runs/maritime-denial.json`. The dashboard and model-driven investigation remain local; full investigator sandboxing and document-path filtering are not verified.

A stochastic model may choose a different tool order or fail; failed/partial runs stay visibly failed/partial. Unknown source questions and broader maritime corpora need additional evaluation. Warm-model latency varies with local load. Avoid simultaneous model investigations while presenting.

Neo4j's bundled APOC plugin was enabled during model-extraction diagnosis, following the [official installation procedure](https://neo4j.com/docs/apoc/current/installation/). The source-parser graph builder itself uses ordinary parameterized Cypher and does not depend on model extraction.

## Distribution validation

A clean checkout installed both locked environments and passed 74 application tests plus 7 backend tests. A freshly provisioned Neo4j 2026.10.2 container with newly generated credentials ingested the included corpus to 12 chunks, 31 nodes and 35 relationships. Both temporal acceptance cases passed against the clean service. Local-only logs, screenshots and environment files are excluded from the distribution.

The clean-checkout live agent acceptance also passed: 56.6 seconds, six model calls, all four required tools successful. Secret scanning with Gitleaks found no leaks in the staged distribution or initial Git history. This is a bounded local validation, not a guarantee for every platform.
