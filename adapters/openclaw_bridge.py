"""Validated stdin/stdout bridge to the existing OpenShell investigator.

No HTTP listener, arbitrary commands, fixture fallback, or model credentials.
"""
from __future__ import annotations
import fcntl
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from adapters.sandbox import SandboxAnalyst
from shared.configuration import ROOT, Settings

class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=2000)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(timezone.utc)


def delegate(request: InvestigationRequest):
    settings = replace(Settings.load(), agent_mode="live", data_mode="live")
    run_dir = ROOT / ".run" / "openclaw-investigations"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Serialize this bridge's requests; the Streamlit challenge must also be idle.
    with (run_dir / "investigator.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "status": "busy", "error": "Another delegated investigation is running; retry after it finishes."}
        analyst = SandboxAnalyst(settings)
        result = analyst.run(request.question, request.as_of.isoformat())
        evidence = analyst.last_evidence()
        # Use our own generated filename; never trust a backend-provided path.
        from uuid import uuid4
        artifact = run_dir / (uuid4().hex + ".json")
        full = {"request": request.model_dump(mode="json"), "runtime": "openshell",
                "result": result.model_dump(mode="json"),
                "evidence": [e.model_dump(mode="json") for e in evidence]}
        artifact.write_text(json.dumps(full, indent=2) + "\n")
        detail = result.demo_specific_result
        return {
            "ok": result.status.value in {"complete", "partial"},
            "status": result.status.value, "runtime": "openshell",
            "run_id": result.run_id, "as_of": result.analysis_cutoff.isoformat(),
            "summary": result.summary,
            "claims": [c.model_dump(mode="json") for c in result.claims],
            "warnings": result.warnings, "unresolved_questions": result.unresolved_questions,
            "actions_for_review": result.actions_for_review,
            "overlaps": detail.get("overlaps", []),
            "corrections_applied": detail.get("corrections_applied", []),
            "exclusions": detail.get("exclusions", []),
            "shipments": detail.get("shipments", []),
            "sources": [{"evidence_id": e.evidence_id, "source_id": e.source_id,
                         "source_title": e.source_title, "excerpt": e.excerpt,
                         "published_at": e.published_at.isoformat() if e.published_at else None}
                        for e in evidence],
            "tool_events": [e.model_dump(mode="json") for e in result.tool_events],
            "artifact": str(artifact),
            "limitations": ["Synthetic maritime exercise; planned overlap is not proven delay.",
                            "No booking, diversion, delivery, or notification was executed.",
                            "This tool does not run or verify the network-denial challenge."],
        }


def main():
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError("request exceeds 8192 characters")
        request = InvestigationRequest.model_validate_json(raw)
        payload = delegate(request)
    except Exception as exc:
        # No stderr, environment, credentials, or raw subprocess output in model context.
        payload = {"ok": False, "status": "failed", "error": type(exc).__name__,
                   "message": "Investigation failed. Check request timezone, local services, sandbox and attached provider. No fallback was used."}
    print(json.dumps(payload))
    return 0 if payload.get("ok") else 1

if __name__ == "__main__":
    raise SystemExit(main())
