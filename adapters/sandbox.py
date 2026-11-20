"""Host-side transport only: all investigation code executes in OpenShell."""
import json
import os
import shutil
import subprocess
import time
from shared.contracts import EvidenceItem, FinalResult

SANDBOX = "ami-maritime-agent"


def cli_path():
    cli = shutil.which("openshell")
    if not cli:
        raise RuntimeError("OpenShell is not installed; sandbox execution cannot start.")
    return cli


MODEL_ENDPOINT = "http://192.168.127.254:11434/v1"
INFERENCE_PROVIDER = "ami-maritime-inference"


def require_inference_provider(cli):
    check = subprocess.run([cli, "sandbox", "provider", "list", SANDBOX],
                           capture_output=True, text=True, timeout=15)
    if check.returncode or INFERENCE_PROVIDER not in check.stdout.split():
        raise RuntimeError("The maritime agent sandbox or inference provider is not ready. "
                           "Run ./scripts/setup_maritime_sandbox.sh, then retry.")


class SandboxAnalyst:
    def __init__(self, settings):
        self.settings = settings
        self.payload = {}

    def run(self, question, analysis_cutoff, *, challenge=False):
        if not challenge and (self.settings.agent_mode != "live" or self.settings.data_mode != "live"):
            raise ValueError("Sandbox investigations require live model and data modes; use local for rehearsal.")
        cli = cli_path()
        require_inference_provider(cli)
        self.started = time.time()
        request = {"question": question, "analysis_cutoff": analysis_cutoff, "challenge": challenge,
                   "model_id": self.settings.model_id,
                   "max_tool_calls": self.settings.max_tool_calls,
                   "request_timeout_seconds": self.settings.request_timeout_seconds}
        timeout = int(self.settings.request_timeout_seconds) + 30
        process = subprocess.run(
            [cli, "sandbox", "exec", SANDBOX, "--timeout", str(timeout), "--no-tty",
             "--no-login-shell", "--workdir", "/app", "--", "/usr/local/bin/python3.12",
             "-m", "demos.sandbox_agent", json.dumps(request)],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if process.returncode:
            raise RuntimeError("Sandbox agent failed. Check the sandbox image, gateway, attached inference provider and service health.")
        self.payload = json.loads(process.stdout)
        if self.payload.get("runtime") != "openshell" or self.payload.get("model_endpoint") != MODEL_ENDPOINT:
            raise RuntimeError("Unexpected sandbox runtime response")
        return FinalResult.model_validate(self.payload["result"])

    def last_evidence(self):
        return [EvidenceItem.model_validate(item) for item in self.payload.get("evidence", [])]


def execution_mode(settings):
    # Fixture rehearsals remain usable without OpenShell; live defaults to isolation.
    mode = os.getenv("AMI_EXECUTION_MODE", "local" if settings.agent_mode == "scripted" else "openshell")
    if mode not in {"local", "openshell"}:
        raise ValueError("AMI_EXECUTION_MODE must be local or openshell")
    return mode
