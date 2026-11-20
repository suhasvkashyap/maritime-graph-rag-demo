"""Typed contracts for the AMI demos (Demo 3 subset).

Implements the evidence envelope, evidence item, final-result contract, and
the maritime records used by the Port Impact Investigator. Every field the
backend does not provide stays null; failures are typed, never disguised as
empty successes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Evidence contract
# ---------------------------------------------------------------------------


class Locator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_page: int | None = None
    section: str | None = None
    start_seconds: int | None = None
    end_seconds: int | None = None


class EvidenceItem(BaseModel):
    """One source-backed evidence item returned by a tool."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_id: str
    source_title: str
    source_kind: str = "pdf"
    locator: Locator = Field(default_factory=Locator)
    excerpt: str
    published_at: datetime | None = None
    event_start: datetime | None = None
    event_end: datetime | None = None
    synthetic: bool = True
    origin: Literal["fixture", "live"] = "fixture"

    @field_validator("published_at", "event_start", "event_end", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def published_by(self, as_of: datetime) -> bool:
        """Whether this item was published at or before ``as_of``.

        Items without a publication time never count as published-by; the
        caller must surface an explicit temporal-coverage warning instead.
        """
        if self.published_at is None:
            return False
        return self.published_at <= as_of


class ToolError(Exception):
    """Typed tool failure carrying a machine-readable error code."""

    def __init__(self, message: str, error_code: "ErrorCode | str | None" = None):
        super().__init__(message)
        if isinstance(error_code, str):
            try:
                error_code = ErrorCode(error_code)
            except ValueError:
                error_code = ErrorCode.BACKEND_ERROR
        self.error_code = error_code


class ErrorCode(str, Enum):
    PERMISSION_DENIED = "permission_denied"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_ERROR = "backend_error"
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    NO_MATCH = "no_match"
    UNSUPPORTED = "unsupported"


class ToolEnvelope(BaseModel):
    """Every tool returns this envelope."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: ErrorCode | None = None

    @classmethod
    def failure(cls, error: str, code: ErrorCode, warnings: list[str] | None = None) -> "ToolEnvelope":
        return cls(ok=False, error=error, error_code=code, warnings=warnings or [])

    @classmethod
    def success(
        cls,
        data: dict[str, Any],
        evidence: list[EvidenceItem] | None = None,
        warnings: list[str] | None = None,
    ) -> "ToolEnvelope":
        return cls(ok=True, data=data, evidence=evidence or [], warnings=warnings or [])


# ---------------------------------------------------------------------------
# Final result contract
# ---------------------------------------------------------------------------


class ClaimStatus(str, Enum):
    SOURCE_STATEMENT = "source_statement"
    DETERMINISTIC_DERIVATION = "deterministic_derivation"
    MODEL_PREDICTION = "model_prediction"


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus


class ToolEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    duration_ms: int
    outcome: Literal["ok", "error"]
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str = ""
    error_code: str | None = None

    @property
    def is_hard_error(self) -> bool:
        """Backend/validation failures; typed not-found outcomes are soft."""
        return self.outcome == "error" and self.error_code not in {
            ErrorCode.NOT_FOUND.value,
            ErrorCode.NO_MATCH.value,
        }


class RunStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


class FinalResult(BaseModel):
    """Shared final result contract for every demo."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    demo_id: str
    generated_at: datetime
    analysis_cutoff: datetime
    agent_mode: Literal["live", "scripted"]
    data_mode: Literal["live", "fixture"]
    status: RunStatus
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    actions_for_review: list[str] = Field(default_factory=list)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    demo_specific_result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Maritime records (typed, deterministic)
# ---------------------------------------------------------------------------


def parse_utc(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp; naive values are treated as UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class TimeWindow(BaseModel):
    """A half-open [start, end) UTC interval."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: datetime, info):
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError(f"Window end {value.isoformat()} must be after start {start.isoformat()}")
        return value


class CallAssertion(BaseModel):
    """A planned vessel call asserted by a source section."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    vessel_id: str | None = None
    vessel_name: str | None = None
    berth_id: str | None = None
    berth_name: str | None = None
    port: str | None = None
    window: TimeWindow | None = None
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class ScheduleCorrection(BaseModel):
    """An explicit correction replacing named fields of one call."""

    model_config = ConfigDict(extra="forbid")

    correction_id: str
    call_id: str
    new_window: TimeWindow | None = None
    supersedes_source_id: str | None = None
    source_id: str
    published_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ClosureNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_id: str
    berth_id: str
    berth_name: str | None = None
    port: str | None = None
    window: TimeWindow
    source_id: str
    published_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ShipmentLink(BaseModel):
    """A call-to-shipment-to-recipient chain fact."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    shipment_id: str
    description: str | None = None
    recipient: str | None = None
    facility: str | None = None
    receipt_deadline: datetime | None = None
    status: Literal["recorded", "pending", "delivered"] = "recorded"
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class RelationshipAssertion(BaseModel):
    """A source-backed relationship between two named entities."""

    model_config = ConfigDict(extra="forbid")

    source_entity: str
    relationship: str
    target_entity: str
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class IdentityAssertion(BaseModel):
    """A vessel identity/alias fact."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str
    name: str | None = None
    alias_of: str | None = None  # former name that maps to canonical_id
    distinct_from: list[str] = Field(default_factory=list)  # IDs this vessel is NOT
    source_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProposedAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    shipment_id: str | None = None
    facility: str | None = None
    date: str | None = None
    pending_items: list[str] = Field(default_factory=list)
    approved: bool = False
    source_id: str
    published_at: datetime | None = None
    evidence_ids: list[str] = Field(default_factory=list)
