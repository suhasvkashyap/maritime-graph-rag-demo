"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from demos.port_impact import PortImpactAnalyst
from shared.configuration import Settings

DEFAULT_CUTOFF = "2026-11-17T12:00:00Z"
EARLY_CUTOFF = "2026-11-16T12:00:00Z"
MAIN_QUESTION = (
    "Which Halcyon subsidiary-operated calls overlap notice SYN-N017, "
    "and which shipments are connected?"
)


def make_settings(**overrides) -> Settings:
    base = Settings.load().__dict__.copy()
    base.update({"data_mode": "fixture", "agent_mode": "scripted"})
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def fixture_analyst() -> PortImpactAnalyst:
    return PortImpactAnalyst(make_settings(), llm=None)


@pytest.fixture()
def default_result(fixture_analyst: PortImpactAnalyst):
    return fixture_analyst.run(MAIN_QUESTION, DEFAULT_CUTOFF)


@pytest.fixture()
def early_result(fixture_analyst: PortImpactAnalyst):
    return fixture_analyst.run("Which calls overlap notice SYN-N017?", EARLY_CUTOFF)
