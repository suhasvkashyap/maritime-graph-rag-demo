#!/bin/sh
# Install verified official Node + pinned OpenClaw for this user.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AMI_HOME="${AMI_OPENCLAW_HOME:-$HOME/.local/share/ami-openclaw}"
"$ROOT/.venv/bin/python" "$ROOT/scripts/install_openclaw_node.py"
export PATH="$AMI_HOME/official-node/bin:$PATH"
"$AMI_HOME/official-node/bin/node" "$AMI_HOME/official-node/lib/node_modules/npm/bin/npm-cli.js" \
  install --prefix "$AMI_HOME/install" openclaw@2026.11.6 --no-audit --no-fund
"$ROOT/.venv/bin/python" "$ROOT/scripts/configure_openclaw.py"
"$ROOT/scripts/openclaw.sh" --version
