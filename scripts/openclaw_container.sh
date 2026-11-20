#!/bin/sh
# Containerized OpenClaw Gateway control (see docs/openclaw.md
# for why the gateway runs in a container on this Mac: AppleSystemPolicy kills
# every process under the OpenClaw package tree, across reboot and reinstall).
#
# The container is published on host loopback only (127.0.0.1:18790). The
# OpenShell bridge keeps its end-to-end mTLS transport; inside the container
# the openshell CLI reaches the loopback-only OpenShell gateway through the
# podman host-gateway address (host.containers.internal), which gvproxy
# forwards to macOS loopback and which the gateway TLS certificate names.
#
# Usage: scripts/openclaw_container.sh build|prepare|start|stop|restart|
#        status|health|logs|dashboard|verify
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AMI_HOME="${AMI_OPENCLAW_HOME:-$HOME/.local/share/ami-openclaw}"
STATE="$AMI_HOME/container-state"
RUN="$ROOT/.run"
NAME="ami-openclaw-gateway"
OPENCLAW_VERSION=$(.venv/bin/python -c 'import json;print(json.load(open("'$AMI_HOME'/install/node_modules/openclaw/package.json"))["version"])' 2>/dev/null || echo "2026.11.6")
IMAGE="localhost/ami-openclaw-gateway:$OPENCLAW_VERSION"

require_podman() {
    if ! podman info >/dev/null 2>&1; then
        echo "Podman is not reachable. Run: podman machine start" >&2
        exit 1
    fi
}

case "${1:-help}" in
build)
    podman build -t "$IMAGE" "$ROOT/deployment/openclaw-gateway"
    ;;
prepare)
    shift
    exec "$ROOT/.venv/bin/python" "$ROOT/scripts/prepare_openclaw_container.py" "$@"
    ;;
start)
    require_podman
    mkdir -p "$RUN/openclaw-investigations"
    need_run=1
    if podman container exists "$NAME" 2>/dev/null; then
        state=$(podman ps -a --filter "name=$NAME" --format '{{.State}}')
        if [ "$state" = "running" ]; then
            need_run=0
            echo "Container $NAME is already running."
        else
            podman rm "$NAME" >/dev/null
        fi
    fi
    if [ "$need_run" = "1" ]; then
        podman run -d --name "$NAME" \
            -p 127.0.0.1:18790:18790 \
            -v "$STATE:/state" \
            -v "$AMI_HOME/state/workspace:/state/workspace" \
            -v "$ROOT/openclaw/maritime-plugin:/opt/plugins/maritime-plugin:ro" \
            -v "$ROOT/adapters:/opt/ami-runtime/adapters:ro" \
            -v "$ROOT/shared:/opt/ami-runtime/shared:ro" \
            -v "$RUN/openclaw-investigations:/opt/ami-runtime/.run/openclaw-investigations" \
            "$IMAGE"
    fi
    printf "Waiting for the gateway"
    i=0
    until curl -fsS -m 2 http://127.0.0.1:18790/health >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -gt 120 ]; then
            echo
            echo "Gateway did not become healthy; see: scripts/openclaw_container.sh logs" >&2
            exit 1
        fi
        printf "."
        sleep 1
    done
    echo
    echo "OpenClaw ready (container): http://127.0.0.1:18790"
    ;;
stop)
    if podman container exists "$NAME" 2>/dev/null; then
        podman stop -t 30 "$NAME" >/dev/null
        podman rm "$NAME" >/dev/null
        echo "Container $NAME stopped and removed."
    else
        echo "Container $NAME is not present."
    fi
    ;;
recover-lock)
    # Clear a gateway lock left by a container that did not exit cleanly.
    require_podman
    podman run --rm -v "$STATE:/state" -v "$AMI_HOME/state/workspace:/state/workspace" \
        "$IMAGE" gateway recover-lock
    ;;
restart)
    "$0" stop || true
    "$0" start
    ;;
status)
    if podman container exists "$NAME" 2>/dev/null; then
        podman ps -a --filter "name=$NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    else
        echo "Container $NAME is not present. Start with: scripts/openclaw_container.sh start"
    fi
    ;;
health)
    curl -fsS -m 3 http://127.0.0.1:18790/health && echo
    ;;
logs)
    podman logs ${2:---tail 100} "$NAME" 2>&1 | grep -vE '^\[openclaw\] $' || true
    ;;
dashboard)
    if ! podman container exists "$NAME" 2>/dev/null; then
        echo "Container $NAME is not running. Start with: scripts/openclaw_container.sh start" >&2
        exit 1
    fi
    url=$(podman exec "$NAME" openclaw dashboard 2>&1 | grep -oE 'https?://[^ "'"'"']+' | head -1 || true)
    if [ -n "$url" ]; then
        echo "Open in a browser: $url"
    else
        echo "The dashboard command printed no URL; check: podman logs $NAME" >&2
        exit 1
    fi
    ;;
verify)
    echo "== gateway health =="
    "$0" health
    echo "== OpenShell leg from inside the container =="
    podman exec "$NAME" openshell status
    echo "== maritime sandbox (optional, for live investigations) =="
    podman exec "$NAME" openshell sandbox provider list ami-maritime-agent 2>&1 | head -2 || true
    ;;
*)
    echo "Usage: scripts/openclaw_container.sh build|prepare|start|stop|restart|status|health|logs|dashboard|verify"
    ;;
esac
