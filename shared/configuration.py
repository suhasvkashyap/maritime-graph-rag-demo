"""Configuration and mode handling for the AMI demos.

Precedence: environment variables (``AMI_*``) → ``.env`` → defaults. Secrets
are only ever read from the environment and are never logged, rendered, or
echoed in errors. The two mode labels are independent:

* ``agent_mode`` — live model or scripted rehearsal (tool selection source).
* ``data_mode``  — live backend or fixture replay (data source).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from os import getenv

ROOT = Path(__file__).resolve().parents[1]

EXERCISE_CUTOFF = "2026-11-17T12:00:00Z"


@dataclass(frozen=True)
class Settings:
    demo: str
    agent_mode: str  # live | scripted
    data_mode: str  # live | fixture
    asset_root: Path
    model_endpoint: str
    model_id: str
    model_api_key: str
    graph_pattern_url: str
    graph_pattern_timeout: float
    max_tool_calls: int
    tool_timeout_seconds: float
    request_timeout_seconds: float
    analysis_cutoff: str

    @classmethod
    def load(cls, demo: str = "impact") -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            demo=demo,
            agent_mode=getenv("AMI_AGENT_MODE", "live").strip().lower(),
            data_mode=getenv("AMI_DATA_MODE", "live").strip().lower(),
            asset_root=Path(getenv("AMI_ASSET_ROOT", str(ROOT / "assets"))),
            model_endpoint=getenv("AMI_MODEL_ENDPOINT", "http://localhost:11434/v1").strip().rstrip("/"),
            model_id=getenv("AMI_MODEL_ID", "ami-demo3-qwen"),
            model_api_key=getenv("AMI_MODEL_API_KEY", "ollama"),
            graph_pattern_url=getenv("AMI_GRAPH_PATTERN_CONFIG", "http://localhost:8010").strip().rstrip("/"),
            graph_pattern_timeout=float(getenv("AMI_TOOL_TIMEOUT_SECONDS", "45")),
            max_tool_calls=int(getenv("AMI_MAX_TOOL_CALLS", "6")),
            tool_timeout_seconds=float(getenv("AMI_TOOL_TIMEOUT_SECONDS", "45")),
            request_timeout_seconds=float(getenv("AMI_REQUEST_TIMEOUT_SECONDS", "180")),
            analysis_cutoff=getenv("AMI_ANALYSIS_CUTOFF", EXERCISE_CUTOFF),
        )


@dataclass(frozen=True)
class ModeLabels:
    """The two independent UI labels required by the specification."""

    agent: str
    data: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModeLabels":
        return cls(
            agent="live model" if settings.agent_mode == "live" else "scripted rehearsal",
            data="live backend" if settings.data_mode == "live" else "fixture",
        )


def fixture_path(name: str) -> Path:
    return ROOT / "fixtures" / name


def check_configuration(settings: Settings) -> list[str]:
    """Return human-readable problems; empty list means configured.

    Live modes require their endpoints; fixture modes must not silently call
    live services. ``live`` without a reachable endpoint is a hard error at
    run time, never a fallback to fixtures.
    """
    problems: list[str] = []
    if settings.agent_mode not in {"live", "scripted"}:
        problems.append(f"AMI_AGENT_MODE must be 'live' or 'scripted', got {settings.agent_mode!r}")
    if settings.data_mode not in {"live", "fixture"}:
        problems.append(f"AMI_DATA_MODE must be 'live' or 'fixture', got {settings.data_mode!r}")
    if settings.data_mode == "live" and not settings.graph_pattern_url:
        problems.append("AMI_GRAPH_PATTERN_CONFIG is required in live data mode")
    if settings.data_mode == "fixture" and not (ROOT / "fixtures" / "tool_responses.json").is_file():
        problems.append("fixtures/tool_responses.json is required in fixture data mode")
    return problems
