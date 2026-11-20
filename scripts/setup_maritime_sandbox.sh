#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v openshell >/dev/null
command -v podman >/dev/null
# Never silently reuse an agent image or replace another demo's sandbox.
if openshell sandbox get ami-maritime-agent >/dev/null 2>&1; then
  echo 'ami-maritime-agent already exists. Refusing stale image reuse; see docs/openshell-agent.md.' >&2
  exit 1
fi
if ! openshell profile describe ami-maritime-inference >/dev/null 2>&1; then
  openshell profile lint -f deployment/inference-provider.yaml
  openshell profile import -f deployment/inference-provider.yaml
fi
if ! openshell provider get ami-maritime-inference >/dev/null 2>&1; then
  openshell provider create --name ami-maritime-inference --type ami-maritime-inference
fi
podman build -f deployment/Containerfile.policy-worker -t localhost/ami-maritime-agent:latest .
openshell sandbox create --name ami-maritime-agent --from localhost/ami-maritime-agent:latest \
  --policy deployment/sandbox-policy.yaml --provider ami-maritime-inference \
  --detach --no-tty --no-auto-providers -- \
  /usr/local/bin/python3.12 -c 'import time; time.sleep(2147483647)'
