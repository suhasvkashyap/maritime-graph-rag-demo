#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v openshell >/dev/null
command -v podman >/dev/null
# The checked-in policy uses the Podman Desktop/macOS host gateway.
# Check the effective host address on other platforms before provisioning.
podman build -f deployment/Containerfile.policy-worker -t localhost/ami-maritime-worker:latest .
if openshell sandbox get ami-maritime >/dev/null 2>&1; then
  echo 'ami-maritime already exists; leaving its policy and process unchanged.'
  exit 0
fi
openshell sandbox create --name ami-maritime --from localhost/ami-maritime-worker:latest \
  --policy deployment/sandbox-policy.yaml --detach --no-tty --no-auto-providers -- \
  /usr/local/bin/python3.12 -c 'import time; time.sleep(2147483647)'
