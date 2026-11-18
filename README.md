# Asteria Maritime Insights — Port Impact Investigator

An agentic Graph RAG demo that investigates a fictional berth closure: **which scheduled vessel visits overlap it, who operates those vessels, and which shipments are connected?**

The UI includes a document reader, a live Neo4j neighborhood explorer, time-aware evidence, an investigation tool log, and an optional real OpenShell network-denial demonstration. All maritime names, identifiers, schedules and cargo records are synthetic. No bookings, diversions or notifications are executed.

## Architecture and scope

```mermaid
flowchart LR
    PDF[12 synthetic documents] --> Parser[Domain-specific source parser]
    Parser --> Neo4j[Neo4j graph + embedded chunks]
    Ollama[Ollama: Qwen2.5 + bge-m3] --> Agent[Port Impact Analyst]
    UI[Streamlit dashboard] --> Agent
    Agent --> Tools[Evidence / graph / overlap / shipment tools]
    Tools --> API[Graph RAG service :8010]
    API --> Neo4j
    UI --> Worker[Optional OpenShell maritime worker]
    Worker -->|allowed| API
    Worker -->|denied| Outside[Outside-policy destination :8031]
```

The application adapts a Graph RAG starter kit originally generated on Red Hat OpenShift AI 3.6. **You do not need an OpenShift cluster, cloud account, S3 bucket or API subscription to run this repository.** Dependencies and model weights are downloaded separately.

- The live model chooses tools. Code applies schedule corrections, computes interval overlaps and assembles the factual brief from validated results.
- The graph is **source-parsed**, using this register's structure and stable IDs, not generic LLM extraction. The expected build has 12 chunks, 31 entities and 35 relationships.
- The main dashboard and investigator run locally. Only the optional access-test worker runs in OpenShell. It tests destination-level network denial, not document-path authorization or full investigator sandboxing.
- Fixture rehearsal is clearly labelled and never silently replaces the live backend.

## Prerequisites

Recommended: macOS or Linux, Python **3.12**, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com/), and [Podman](https://podman.io/) or Docker for Neo4j. A practical starting point is 16 GB RAM (24 GB recommended) and 15 GB free disk; model speed depends on your hardware. Internet is required for initial package, image and model downloads.

For optional sandbox denial: install [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell), start its local gateway, and use Podman. The verified configuration used OpenShell 0.1.9 and the Podman macOS host gateway `192.168.127.254`. Other platforms require checking host reachability and editing the gateway address consistently in `deployment/sandbox-policy.yaml` and `demos/maritime_policy.py`.

Required free local ports: **8501** UI, **8010** Graph RAG, **11434** Ollama, **17474/17687** Neo4j. Port **8031** is a deliberately non-allowlisted destination; no server or document needs to exist there.

## Quick rehearsal — no database or model required

```bash
git clone https://github.com/suhasvkashyap/maritime-graph-rag-demo.git
cd maritime-graph-rag-demo
uv sync --python 3.12 --all-extras --locked
AMI_DATA_MODE=fixture AMI_AGENT_MODE=scripted .venv/bin/streamlit run app.py --server.port 8502
```

Open http://localhost:8502. This verifies the UI and deterministic scenario using checked-in fixtures. Live graph browsing and OpenShell need the corresponding services below.

## Full live setup

Run commands from the repository root unless explicitly changing directories.

### 1. Install both locked Python environments

```bash
uv sync --python 3.12 --all-extras --locked
uv sync --project pattern1 --python 3.12 --extra dev --locked
```

There are two environments: `.venv` for the UI and `pattern1/.venv` for the generated Graph RAG service. Both lockfiles are included. `ai4rag`, Neo4j driver and PDF reader are explicit backend dependencies.

### 2. Configure and start Neo4j

Start your container engine first. For Podman on macOS, initialize/start a Podman machine if you do not already have one.

```bash
.venv/bin/python scripts/setup_local.py --start-neo4j --engine podman
# Docker alternative: --engine docker
```

This generates local `.env` files with a random database password and starts the dedicated `ami-maritime-neo4j` container using Neo4j **2026.10.2**, with persistent volume `ami-maritime-neo4j-data`. It binds database ports only to localhost. No authentication is disabled. Wait for database startup; inspect `podman logs ami-maritime-neo4j` if needed.

Existing `.env` files are preserved. To use your own Neo4j instead, run `scripts/setup_local.py` without `--start-neo4j`, then edit `pattern1/.env`. Do not commit that file. Templates document required variables. The supported source-parser build does not need APOC.

### 3. Download and prepare models

Start Ollama (`ollama serve` in a separate terminal, or its desktop app), then:

```bash
ollama pull qwen2.5:7b
ollama pull bge-m3
ollama create ami-demo3-qwen -f pattern1/scripts/Modelfile.ami-demo3
```

The `ollama` API-key value in the examples is a local compatibility placeholder, not a secret. Model weights are not stored in Git.

### 4. Ingest the synthetic corpus

```bash
(cd pattern1 && .venv/bin/python scripts/build_source_graph.py)
```

Expected counts: **12 chunks / 31 nodes / 35 edges**. The builder reads the included PDF and embeds sections with bge-m3. It is safe to repeat for the same corpus. If changing document content, use a new collection and update the explicit collection guard to avoid stale graph data.

Do not run the experimental `index_corpus.py` model-extraction path for the supported demo.

### 5. Launch and verify

```bash
.venv/bin/python scripts/start_demo.py
.venv/bin/python scripts/verify_live.py --agent
```

Open **http://127.0.0.1:8501**. Choose the first question and click **Run investigation**. Expect roughly one to two minutes on a suitable laptop; this is not a latency guarantee. Avoid concurrent investigations.

The launcher preserves background processes and writes logs/PIDs under `.run/`. Use `scripts/start_demo.py --restart` after configuration changes. It does not start Ollama, Neo4j or OpenShell for you.

## Presenter walkthrough and expected results

1. Ask: **Which Halcyon subsidiary-operated calls overlap notice SYN-N017, and which shipments are connected?**
2. At the default cutoff (17 November 2026, 12:00 UTC), C101 alone overlaps the berth closure for **8 hours**. Its operator is Meridian Shelf Shipping; its shipment is S101.
3. Show C103's correction and exclusions for other berths, ports and dates.
4. Select the earlier cutoff (16 November, 12:00 UTC). C103 now also overlaps for **5 hours**, because the later correction was not yet available.
5. Browse the documents and graph relationships, then show the evidence and executed-tool log.

A port call is a scheduled vessel visit, not a phone call. Overlap means planned berth occupancy, not proven delay. The cargo handling proposal remains pending; delivery and diversion are not established.

See [presenter instructions](docs/demo-03.md). Questions beyond this bounded synthetic exercise need further evaluation.

## Optional: dedicated maritime OpenShell denial demo

The local OpenShell gateway must already be running. Then:

```bash
./scripts/setup_maritime_sandbox.sh
```

This builds a minimal Python worker and creates **ami-maritime** with **this repository's policy**. It does not delete, modify or use another demo sandbox. An existing sandbox is left unchanged; if it is stopped, run `openshell sandbox start ami-maritime`.

In the UI, select **Maritime OpenShell — live denial scenario**, then **Run maritime denial test**. The fixed Python tool request executes inside the maritime sandbox:

| Request | Expected result |
|---|---|
| Maritime Graph RAG on host port **8010**, `/health` | HTTP 200 |
| Synthetic restricted document destination on **8031** | Permission denied plus a fresh OpenShell `DENIED` event |

The UI reports success only when both controls and the audit event match. The restricted connection is blocked before a document can be retrieved. This is a controlled tool probe, not a model-selected destination. The investigator itself stays local.

If the allowed control fails, check that the host Graph RAG service is healthy and reachable from the Podman VM. Do not broaden the allowlist to make the denied destination succeed. The filesystem and HTTP method/path entries are configuration; this test verifies network destination enforcement only.

## Synthetic data and reproducibility

Everything needed for this maritime scenario is included:

- `assets/graph/documents/D01.md`–`D12.md`: readable individual documents.
- `assets/graph/documents/catalog.json`: UI document catalog.
- `assets/graph/ami_maritime_graph_corpus.pdf`: ingestion artifact.
- `fixtures/corpus_sections.py`: synthetic source generator inputs; `scripts/prepare_assets.py` regenerates the PDF.
- `fixtures/`: canned service responses, evidence and graph expectations for offline tests.
- `pattern1/`: service source, configuration, lockfile, ingestion scripts and tests.
- `deployment/`: maritime policy and worker image definition.

After editing/regenerating source data, regenerate the catalog/Markdown with `scripts/export_documents.py`, rebuild into a fresh collection and rerun acceptance checks. Do not substitute data while retaining old expected results.

## Tests

```bash
.venv/bin/python -m pytest tests -q
(cd pattern1 && .venv/bin/python -m unittest discover -s tests -q)
.venv/bin/python scripts/verify_live.py --agent
```

The first two suites do not require live models or a database. Live verification writes ignored JSON/Markdown artifacts under `docs/verified-runs/`.

## Troubleshooting

- **Database authentication/connection:** check `pattern1/.env`, container logs and ports. A pre-existing volume retains its original password.
- **No graph evidence:** run the source graph builder and check `/v1/graph/status` on port 8010.
- **Model unavailable:** check `ollama list`; both `ami-demo3-qwen` and `bge-m3` must exist.
- **Slow/partial investigation:** inspect `.run/backend.log` and `.run/ui.log`; reduce other local workloads. Partial results remain visibly partial.
- **Sandbox test unavailable:** verify `openshell sandbox get ami-maritime` and gateway readiness. No simulated denial is substituted.
- **Ports occupied:** stop conflicting processes or update the relevant config and launcher consistently. Never point this demo at another demo's sandbox.

## Secrets and sharing

`.env`, credentials, virtual environments, logs, caches, runtime outputs and local screenshots are ignored. Setup generates a new database password on each fresh clone, not a shared checked-in password. Run `gitleaks git --redact` before publishing changes. Example configs contain placeholders only. Do not add real customer records or cluster credentials.

This repository is a demonstration, not an official supported Red Hat or NVIDIA product distribution. Dependencies and models retain their respective licenses. No license for upstream code is overridden by this repository.
