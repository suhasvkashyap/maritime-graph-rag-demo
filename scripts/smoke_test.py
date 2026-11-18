"""End-to-end smoke test for Demo 3.

Runs, in order:
  1. Configuration check (same rules as check_configuration.py).
  2. Fixture-mode scripted run with the primary demo question; asserts the
     spec's acceptance results.
  3. Live-mode checks when the Pattern1 service and Ollama are reachable:
     health, retrieval, graph inspection endpoints.

Exit code 0 = demo is ready to run. Never mutates data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from demos.port_impact import PortImpactAnalyst  # noqa: E402
from shared.configuration import Settings, check_configuration  # noqa: E402

MAIN_QUESTION = (
    "Which Halcyon subsidiary-operated calls overlap notice SYN-N017, "
    "and which shipments are connected?"
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    line = f"[{marker}] {name}" + (f" — {detail}" if detail and not condition else "")
    print(line, flush=True)
    (PASSED if condition else FAILED).append(name)


def run_fixture_checks(settings: Settings) -> None:
    analyst = PortImpactAnalyst(settings, llm=None)
    result = analyst.run(MAIN_QUESTION, "2026-11-17T12:00:00Z")
    pipeline = result.demo_specific_result
    overlaps = [(o["call_id"], o["overlap_hours"]) for o in pipeline["overlaps"]]
    check("fixture scripted run completes", result.status.value == "complete", result.status.value)
    check("exactly SYN-C101 overlaps 8h at default cutoff", overlaps == [("SYN-C101", 8.0)], str(overlaps))
    check(
        "C103 corrected and excluded",
        any(c["call_id"] == "SYN-C103" and c["status"] == "applied" for c in pipeline["corrections_applied"])
        and any(e["call_id"] == "SYN-C103" for e in pipeline["exclusions"]),
    )
    excluded = {e["call_id"]: e["reason"] for e in pipeline["exclusions"]}
    check("C102 excluded by berth", "Berth B2" in excluded.get("SYN-C102", ""))
    check("C104 excluded by port", "Port Westhaven" in excluded.get("SYN-C104", ""))
    check("C105 excluded by window", "SYN-C105" in excluded)
    check(
        "Halcyon subsidiary annotation",
        pipeline["overlaps"][0].get("halcyon_subsidiary_operated") is True,
    )
    check("claims carry evidence ids", all(c.evidence_ids for c in result.claims))
    check("no delay/diversion claims", not any("delay" in c.text.lower() and "not established" not in c.text.lower() for c in result.claims))

    early = analyst.run("Which calls overlap notice SYN-N017?", "2026-11-16T12:00:00Z")
    early_overlaps = [(o["call_id"], o["overlap_hours"]) for o in early.demo_specific_result["overlaps"]]
    check(
        "earlier cutoff: C101+C103 overlap, D09 excluded",
        ("SYN-C101", 8.0) in early_overlaps
        and ("SYN-C103", 5.0) in early_overlaps
        and any("D09" in r for r in early.demo_specific_result["excluded_evidence"]),
        str(early_overlaps),
    )


def run_live_checks(settings: Settings) -> None:
    try:
        response = httpx.get(f"{settings.graph_pattern_url}/health", timeout=5.0)
        response.raise_for_status()
        check("pattern1 /health", True)
    except Exception as exc:  # noqa: BLE001
        check("pattern1 /health", False, f"{type(exc).__name__}: {exc}")
        return

    try:
        response = httpx.post(
            f"{settings.graph_pattern_url}/v1/retrieve",
            json={"input": "Which call overlaps notice SYN-N017?"},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        sections = [e.get("metadata", {}).get("section_id") for e in payload.get("evidence", [])]
        check("live retrieval returns corpus sections", bool(sections), str(sections))
        check("live retrieval includes the calls section", "D04" in sections, str(sections))
    except Exception as exc:  # noqa: BLE001
        check("live retrieval", False, f"{type(exc).__name__}: {exc}")

    try:
        response = httpx.get(
            f"{settings.graph_pattern_url}/v1/graph/status",
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        check(
            "graph status reports entities",
            payload.get("available") is True and (payload.get("entities") or 0) > 0,
            str(payload)[:120],
        )
    except Exception as exc:  # noqa: BLE001
        check("graph status", False, f"{type(exc).__name__}: {exc}")

    try:
        response = httpx.get(
            f"{settings.graph_pattern_url}/v1/graph/evidence",
            params={"entities": "SYN-C101,SYN-N017", "max_nodes": 15},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        node_names = {n.get("name") for n in payload.get("nodes", [])}
        check(
            "graph evidence has the call and notice",
            {"SYN-C101", "SYN-N017"} <= node_names,
            str(sorted(node_names))[:120],
        )
    except Exception as exc:  # noqa: BLE001
        check("graph evidence", False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-live", action="store_true", help="Fixture checks only.")
    args = parser.parse_args()

    settings = Settings.load()
    problems = check_configuration(settings)
    check("configuration valid", not problems, "; ".join(problems))

    # The fixture checks always run against fixture/scripted settings,
    # regardless of the ambient .env, so the demo contract is verified even
    # when the service is down.
    from dataclasses import replace

    fixture_settings = replace(settings, agent_mode="scripted", data_mode="fixture")
    run_fixture_checks(fixture_settings)

    if not args.skip_live and settings.data_mode == "live":
        run_live_checks(settings)
    elif not args.skip_live:
        print("\n(live checks skipped: AMI_DATA_MODE != live)")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
