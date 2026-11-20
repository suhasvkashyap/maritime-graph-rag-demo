"""Generate the containerized OpenClaw gateway's state from the host setup.

Outputs, under <ami-home>/container-state/:

* openclaw.json          — the gateway config, derived from the host config:
                           same token and model, container paths, bind "lan".
* openshell-config/      — an OpenShell CLI registration for the container:
                           the host's active (or chosen) registration's mTLS
                           credentials, re-pointed at the podman host-gateway
                           address (host.containers.internal) so the bridge
                           reaches the loopback-only OpenShell gateway.

Nothing on the host is modified. Run via scripts/openclaw_container.sh prepare.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from pathlib import Path

HOME = Path.home()
DEFAULT_AMI_HOME = Path(os.environ.get("AMI_OPENCLAW_HOME", HOME / ".local/share/ami-openclaw"))
CONTAINER_VM_ADDRESS = "192.168.127.254"  # Podman Desktop/macOS host address, as used by the demo


def endpoint_port(metadata: dict) -> int:
    endpoint = str(metadata.get("gateway_endpoint", ""))
    _, _, port = endpoint.rpartition(":")
    try:
        return int(port)
    except ValueError:
        raise SystemExit(f"Cannot parse a port from gateway_endpoint {endpoint!r}") from None


def container_config(host_config: dict, vm_address: str) -> dict:
    config = json.loads(json.dumps(host_config))
    config["gateway"]["bind"] = "lan"  # reachable from the published host port, still loopback-published on macOS
    agents = config.setdefault("agents", {}).setdefault("defaults", {})
    agents["workspace"] = "/state/workspace"
    providers = config.get("models", {}).get("providers", {})
    for provider in providers.values():
        base = str(provider.get("baseUrl", ""))
        provider["baseUrl"] = base.replace("127.0.0.1", vm_address).replace("localhost", vm_address)
    plugins = config.get("plugins", {})
    load = plugins.setdefault("load", {})
    load["paths"] = ["/opt/plugins/maritime-plugin"]
    entries = plugins.setdefault("entries", {})
    for entry in entries.values():
        entry_config = entry.setdefault("config", {})
        if "repoRoot" in entry_config:
            entry_config["repoRoot"] = "/opt/ami-runtime"
    return config


def export_openshell_registration(source_dir: Path, output_dir: Path, openshell_address: str, port: int) -> None:
    mtls = source_dir / "mtls"
    for name in ("ca.crt", "tls.crt", "tls.key"):
        if not (mtls / name).is_file():
            raise SystemExit(f"Missing {name} in {mtls}; cannot export the OpenShell registration.")
    metadata_path = source_dir / "metadata.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text())
    else:
        # A creds-only registration (no metadata.json): synthesize the fields
        # the CLI needs. The gateway port must come from --gateway-port.
        if port is None:
            raise SystemExit(f"Registration {source_dir.parent.name!r} has no metadata.json; "
                             "pass --gateway-port for the OpenShell gateway port.")
        metadata = {"name": source_dir.name, "gateway_endpoint": f"https://127.0.0.1:{port}",
                    "is_remote": False, "gateway_port": 0, "auth_mode": "mtls"}
    target = output_dir / "gateways" / str(metadata.get("name", source_dir.parent.name))
    (target / "mtls").mkdir(parents=True, exist_ok=True)
    metadata["gateway_endpoint"] = f"https://{openshell_address}:{port}"
    metadata["is_remote"] = True  # the container reaches the gateway over the VM network
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    for name in ("ca.crt", "tls.crt", "tls.key"):
        shutil.copyfile(mtls / name, target / "mtls" / name)
        mode = stat.S_IRUSR | stat.S_IWUSR if name == "tls.key" else stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        (target / "mtls" / name).chmod(mode)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ami-home", type=Path, default=DEFAULT_AMI_HOME, help="demo OpenClaw home")
    parser.add_argument("--vm-address", default=CONTAINER_VM_ADDRESS, help="podman-internal macOS address for model/graph endpoints")
    parser.add_argument("--openshell-address", default="host.containers.internal",
                        help="address the container CLI uses for the OpenShell gateway; must appear in the "
                             "gateway TLS certificate's SAN list (host.containers.internal is minted by default)")
    parser.add_argument("--registration", default=None,
                        help="OpenShell gateway registration to export (default: the active one)")
    parser.add_argument("--gateway-port", type=int, default=None,
                        help="OpenShell gateway port (default: the port in that registration's endpoint)")
    arguments = parser.parse_args()

    host_state = arguments.ami_home / "state"
    host_config_path = host_state / "openclaw.json"
    if not host_config_path.is_file():
        raise SystemExit(f"No host gateway config at {host_config_path}; run scripts/install_openclaw.sh first.")
    host_config = json.loads(host_config_path.read_text())

    openshell_config = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "openshell"
    name = arguments.registration
    if name is None:
        active = openshell_config / "active_gateway"
        if not active.is_file():
            raise SystemExit(f"No OpenShell registration found under {openshell_config}; "
                             "is OpenShell installed and set up?")
        name = active.read_text().strip()
    source_dir = openshell_config / "gateways" / name
    metadata_path = source_dir / "metadata.json"
    if not source_dir.is_dir():
        raise SystemExit(f"OpenShell registration {name!r} not found at {source_dir}.")
    if arguments.gateway_port:
        port = arguments.gateway_port
    elif metadata_path.is_file():
        port = endpoint_port(json.loads(metadata_path.read_text()))
    else:
        port = None  # creds-only registration; export_openshell_registration will require --gateway-port

    state = arguments.ami_home / "container-state"
    openshell_out = state / "openshell-config" / "openshell"
    (state / "workspace").mkdir(parents=True, exist_ok=True)
    (state / "logs").mkdir(parents=True, exist_ok=True)
    openshell_out.mkdir(parents=True, exist_ok=True)

    (state / "openclaw.json").write_text(json.dumps(container_config(host_config, arguments.vm_address), indent=2) + "\n")
    (openshell_out / "active_gateway").write_text(name)
    export_openshell_registration(source_dir, openshell_out, arguments.openshell_address, port)

    print(f"Container state:        {state}")
    print(f"Gateway config:         {state / 'openclaw.json'} (token preserved from the host config)")
    print(f"OpenShell registration: {name!r} -> https://{arguments.openshell_address}:{port} (mTLS credentials copied)")
    print(f"Relay target:           {state / 'forward-target'}")


if __name__ == "__main__":
    main()
