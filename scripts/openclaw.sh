#!/bin/sh
# Dedicated runtime and state; does not change system Node or ~/.openclaw.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AMI_HOME="${AMI_OPENCLAW_HOME:-$HOME/.local/share/ami-openclaw}"
export PATH="$AMI_HOME/official-node/bin:$PATH"
export OPENCLAW_STATE_DIR="$AMI_HOME/state"
export OPENCLAW_CONFIG_PATH="$OPENCLAW_STATE_DIR/openclaw.json"
exec "$AMI_HOME/install/node_modules/.bin/openclaw" "$@"
