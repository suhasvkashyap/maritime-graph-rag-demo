# Demo 3 — presenter instructions

## Start

From the cloned repository root, after completing the README setup, run:

```bash
.venv/bin/python scripts/start_demo.py
```

Open http://127.0.0.1:8501. Confirm **Agent: live model** and **Data: live backend**. Allow roughly one to two minutes for a live model investigation on this laptop; inference latency varies. Do not start simultaneous investigations.

## Explain the scope accurately

“This fictional maritime register contains vessels, operators, port calls, a closure notice, shipments and a later correction. We build a source-parsed graph with stable IDs and section citations. A live agent chooses evidence tools, Neo4j returns relationships, and deterministic code checks the times. This local adaptation demonstrates the Graph AutoRAG retrieval pattern and agent workflow; the graph ingestion here is a domain parser, not a claim of reliable generic LLM extraction.”

## Main investigation

1. Keep the first question: **Which Halcyon subsidiary-operated calls overlap notice SYN-N017, and which shipments are connected?**
2. Keep the cutoff after correction D09. Click **Run investigation**.
3. Confirm **Complete**. Show C101's **8 hours planned occupancy**, its operator and shipment chain. Explain that planned exposure is not an observed delay.
4. Show exclusions: different berth (C102), corrected late call (C103), different port (C104), following day (C105).
5. Show the live source-parsed Neo4j graph and edge/source table. Open evidence D04, D06 and D09. The exact source chunk is attached to each parsed edge.
6. Show the tool action log: the real model selected retrieval, calculation, shipment and graph tools. The log contains executed tool events, not invented reasoning.
7. Download the Markdown impact brief and JSON run record.

## Temporal follow-up

Select **Before correction D09**, then run again. The expected overlap set is C101 (8h) plus C103 (5h). D09 is now future evidence, so its correction and graph evidence must not be used. This demonstrates why retrieval alone is insufficient without temporal logic.

## Other questions

- Why is Amber Shoal not affected by the Berth B4 closure?
- Is Northline Kestrel the same vessel as Southern Kestrel?
- Has the alternative handling proposal for shipment SYN-S101 been approved?

The identity and proposal facts are tested in the deterministic suite; the recorded live acceptance focuses on the main investigation and temporal cases. Model phrasing and chosen tool order can vary.

## If a run fails

Do not present a partial or failed run as complete. Check `.run/backend.log`, `.run/ui.log`, `/health`, and `/v1/graph/status`. Use `scripts/verify_live.py --agent` to capture a diagnosis. Do not launch another indexer or silently switch to fixtures. Fixture rehearsal may run separately on 8502 with explicit labels.

## Boundaries

This is synthetic advisory data, not an operational intelligence assessment. No booking, diversion, delivery, notification or approval is executed. The dedicated maritime worker verifies endpoint-level OpenShell denial. The main investigator remains local; full investigator sandboxing and document-path filtering are not verified.

## Clickable data walkthrough

- Click **12 synthetic source documents** for the D01–D12 catalog. Select any document to render its full extracted text.
- **Maritime records** filters D01–D05; **Operational evidence** filters D06–D12.
- **Source-parsed Neo4j graph** opens a live neighborhood browser. Select an entity, inspect edges and read their supporting documents. This exploratory view is not cutoff-filtered.

Open **Maritime OpenShell — live denial scenario**, then **Run maritime denial test**. The dedicated `ami-maritime` worker uses `deployment/sandbox-policy.yaml`: Graph RAG port **8010** is allowed, and synthetic document-service destination **8031** is denied. The UI requires an allowed HTTP 200 control, errno 13 on the denied request, and a fresh matching OpenShell DENIED audit event before reporting verification.

This is a fixed tool-execution probe in the maritime sandbox, not a model-selected action. The main investigator and dashboard remain local. It proves destination enforcement, not document-path authorization. Start a stopped worker with `openshell sandbox start ami-maritime`; the worker image is built from `deployment/Containerfile.policy-worker`. No other demo sandbox is involved.
