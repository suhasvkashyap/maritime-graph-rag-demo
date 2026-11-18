"""Deterministic interval math and correction precedence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.contracts import (
    CallAssertion,
    ClosureNotice,
    ScheduleCorrection,
    TimeWindow,
    parse_utc,
)
from shared.validation import apply_corrections, evaluate_call_overlap


def _ts(text: str) -> datetime:
    return parse_utc(text)


def call(call_id: str, start: str, end: str, berth_id: str = "SYN-B04", berth: str = "Berth B4", port: str = "Port Lumen"):
    return CallAssertion(
        call_id=call_id,
        vessel_id="SYN-V001",
        vessel_name="Atlas Kestrel",
        berth_id=berth_id,
        berth_name=berth,
        port=port,
        window=TimeWindow(start=_ts(start), end=_ts(end)),
        source_id="D04",
    )


def notice(start: str = "2026-11-18T08:00:00Z", end: str = "2026-11-18T20:00:00Z") -> ClosureNotice:
    return ClosureNotice(
        notice_id="SYN-N017",
        berth_id="SYN-B04",
        berth_name="Berth B4",
        port="Port Lumen",
        window=TimeWindow(start=_ts(start), end=_ts(end)),
        source_id="D06",
    )


class TestOverlap:
    def test_full_containment_eight_hours(self):
        result = evaluate_call_overlap(call("SYN-C101", "2026-11-18T09:00:00Z", "2026-11-18T17:00:00Z"), notice())
        assert result.included
        assert result.overlap_seconds == 8 * 3600

    def test_boundary_start_equals_end_is_excluded(self):
        # Half-open [start, end): touching at 20:00 is zero overlap.
        result = evaluate_call_overlap(call("X", "2026-11-18T20:00:00Z", "2026-11-18T23:00:00Z"), notice())
        assert not result.included
        assert result.overlap_seconds == 0

    def test_end_equals_start_is_excluded(self):
        result = evaluate_call_overlap(call("X", "2026-11-18T05:00:00Z", "2026-11-18T08:00:00Z"), notice())
        assert not result.included

    def test_partial_overlap_minutes(self):
        result = evaluate_call_overlap(call("X", "2026-11-18T19:30:00Z", "2026-11-18T21:00:00Z"), notice())
        assert result.included
        assert result.overlap_seconds == 30 * 60

    def test_different_berth_excluded_with_reason(self):
        result = evaluate_call_overlap(
            call("SYN-C102", "2026-11-18T13:00:00Z", "2026-11-18T19:00:00Z", berth_id="SYN-B02", berth="Berth B2"),
            notice(),
        )
        assert not result.included
        assert "Berth B2" in result.reason

    def test_different_port_reason(self):
        result = evaluate_call_overlap(
            call(
                "SYN-C104",
                "2026-11-18T10:00:00Z",
                "2026-11-18T15:00:00Z",
                berth_id="W1",
                berth="Berth W1",
                port="Port Westhaven",
            ),
            notice(),
            berth_ports={"Berth W1": "Port Westhaven", "Berth B4": "Port Lumen"},
        )
        assert not result.included
        assert "Port Westhaven" in result.reason and "Port Lumen" in result.reason

    def test_missing_window_is_unresolved_not_zero(self):
        call_no_window = call("X", "2026-11-18T09:00:00Z", "2026-11-18T10:00:00Z").model_copy(update={"window": None})
        result = evaluate_call_overlap(call_no_window, notice())
        assert not result.included
        assert "cannot evaluate" in result.reason


class TestCorrections:
    def test_published_correction_applied(self):
        calls = {"SYN-C103": call("SYN-C103", "2026-11-18T11:00:00Z", "2026-11-18T16:00:00Z")}
        corrections = [
            ScheduleCorrection(
                correction_id="SYN-U09",
                call_id="SYN-C103",
                new_window=TimeWindow(start=_ts("2026-11-18T21:00:00Z"), end=_ts("2026-11-18T23:00:00Z")),
                source_id="D09",
                published_at=_ts("2026-11-17T09:00:00Z"),
            )
        ]
        effective, applications = apply_corrections(calls, corrections, _ts("2026-11-17T12:00:00Z"))
        assert effective["SYN-C103"].window.start == _ts("2026-11-18T21:00:00Z")
        assert applications[0].status == "applied"

    def test_correction_after_cutoff_not_applied(self):
        calls = {"SYN-C103": call("SYN-C103", "2026-11-18T11:00:00Z", "2026-11-18T16:00:00Z")}
        corrections = [
            ScheduleCorrection(
                correction_id="SYN-U09",
                call_id="SYN-C103",
                new_window=TimeWindow(start=_ts("2026-11-18T21:00:00Z"), end=_ts("2026-11-18T23:00:00Z")),
                source_id="D09",
                published_at=_ts("2026-11-17T09:00:00Z"),
            )
        ]
        effective, applications = apply_corrections(calls, corrections, _ts("2026-11-16T12:00:00Z"))
        assert effective["SYN-C103"].window.start == _ts("2026-11-18T11:00:00Z")
        assert applications[0].status == "not_yet_published"

    def test_conflicting_corrections_without_precedence_unresolved(self):
        calls = {"SYN-C999": call("SYN-C999", "2026-11-18T09:00:00Z", "2026-11-18T10:00:00Z")}
        corrections = [
            ScheduleCorrection(
                correction_id="SYN-U01",
                call_id="SYN-C999",
                new_window=TimeWindow(start=_ts("2026-11-18T11:00:00Z"), end=_ts("2026-11-18T12:00:00Z")),
                source_id="X1",
                published_at=_ts("2026-11-16T09:00:00Z"),
            ),
            ScheduleCorrection(
                correction_id="SYN-U02",
                call_id="SYN-C999",
                new_window=TimeWindow(start=_ts("2026-11-18T13:00:00Z"), end=_ts("2026-11-18T14:00:00Z")),
                source_id="X2",
                published_at=_ts("2026-11-16T10:00:00Z"),
            ),
        ]
        effective, applications = apply_corrections(calls, corrections, _ts("2026-11-17T12:00:00Z"))
        assert effective["SYN-C999"].window.start == _ts("2026-11-18T09:00:00Z")
        assert applications[-1].status == "unresolved"

    def test_correction_for_unknown_call_flagged(self):
        corrections = [
            ScheduleCorrection(
                correction_id="SYN-U77",
                call_id="SYN-C777",
                new_window=TimeWindow(start=_ts("2026-11-18T11:00:00Z"), end=_ts("2026-11-18T12:00:00Z")),
                source_id="X9",
                published_at=_ts("2026-11-16T09:00:00Z"),
            )
        ]
        effective, applications = apply_corrections({}, corrections, _ts("2026-11-17T12:00:00Z"))
        assert "SYN-C777" not in effective
        assert applications[0].status == "unresolved"


class TestTimeWindows:
    def test_end_after_start_enforced(self):
        with pytest.raises(Exception):
            TimeWindow(start=_ts("2026-11-18T10:00:00Z"), end=_ts("2026-11-18T10:00:00Z"))

    def test_naive_timestamps_treated_as_utc(self):
        parsed = parse_utc("2026-11-18T09:00:00")
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0
