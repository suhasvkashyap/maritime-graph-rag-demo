#!/bin/sh
# Launch the OpenClaw gateway with the container state layout.
# Bind-mounted at runtime (see scripts/openclaw_container.sh start):
#   /state                                  gateway state + generated config
#   /state/workspace                        shared demo agent workspace
#   /opt/plugins/maritime-plugin            repo plugin (read-only)
#   /opt/ami-runtime/adapters, /shared      repo bridge code (read-only)
#   /opt/ami-runtime/.run/openclaw-investigations  bridge artifacts (rw)
set -eu
: "${OPENCLAW_STATE_DIR:=/state}"
: "${OPENCLAW_CONFIG_PATH:=${OPENCLAW_STATE_DIR}/openclaw.json}"
export OPENCLAW_STATE_DIR OPENCLAW_CONFIG_PATH
if [ "$#" -gt 0 ]; then
    # One-off commands (e.g. `gateway recover-lock`) run against the same state.
    exec openclaw "$@"
fi
exec openclaw gateway run
