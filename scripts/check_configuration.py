"""Pre-run configuration checks: fail loudly on missing or contradictory setup.

Run before the demo. Checks environment variables, file presence, and (in live
mode) endpoint reachability. Exits 0 when the configuration is usable, 1
otherwise. Never mutates anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from shared.configuration import ModeLabels, Settings, check_configuration, fixture_path  # noqa: E402


def probe_endpoints(settings: Settings) -> list[str]:
    """Return a list of endpoint problems (empty when reachable)."""
    problems: list[str] = []
    if settings.data_mode == "live":
        try:
            response = httpx.get(f"{settings.graph_pattern_url}/health", timeout=5.0)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            problems.append(
                f"Pattern1 service unreachable at {settings.graph_pattern_url}: "
                f"{type(exc).__name__}. Start it with: "
                "cd pattern1 && .venv/bin/uvicorn main:app --port 8010"
            )
    if settings.agent_mode == "live":
        try:
            response = httpx.get(
                f"{settings.model_endpoint.rstrip('/')}/models", timeout=5.0
            )
            response.raise_for_status()
            models = {m.get("id") for m in response.json().get("data", [])}
            if settings.model_id not in models:
                problems.append(
                    f"Model '{settings.model_id}' not served by Ollama "
                    f"(available: {sorted(m for m in models if m)})."
                )
        except Exception as exc:  # noqa: BLE001
            problems.append(
                f"Ollama unreachable at {settings.model_endpoint}: {type(exc).__name__}."
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-probes", action="store_true", help="Only check files and settings.")
    args = parser.parse_args()

    settings = Settings.load()
    problems = check_configuration(settings)
    if not args.skip_probes:
        problems.extend(probe_endpoints(settings))

    labels = ModeLabels.from_settings(settings)
    print(f"Agent mode : {labels.agent}")
    print(f"Data mode  : {labels.data}")
    print(f"Service    : {settings.graph_pattern_url}")
    print(f"Model      : {settings.model_endpoint} ({settings.model_id})")
    if settings.data_mode == "fixture":
        print(f"Fixtures   : {fixture_path('tool_responses.json')}")
    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: configuration is usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
