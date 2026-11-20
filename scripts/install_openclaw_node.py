"""Install a checksum-verified official Node runtime without changing system Node."""
from pathlib import Path
import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '24.22.1'


def verify_node(root):
    node = root / 'bin/node'
    if not node.is_file():
        return False
    if platform.system() == 'Darwin':
        check = subprocess.run(['codesign', '--verify', '--verbose', str(node)], capture_output=True)
        if check.returncode:
            return False
    check = subprocess.run([str(node), '--version'], capture_output=True, text=True)
    return check.returncode == 0 and check.stdout.strip() == 'v' + VERSION


def main():
    system = {'Darwin': 'darwin', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64'}.get(platform.machine())
    if not system or not arch:
        raise SystemExit('This installer supports macOS/Linux arm64/x64.')
    home = Path(os.environ.get('AMI_OPENCLAW_HOME', str(Path.home() / '.local/share/ami-openclaw')))
    home.mkdir(parents=True, exist_ok=True)
    target = home / 'official-node'
    if verify_node(target):
        print(f'Official Node {VERSION} already verified: {target}')
        return
    filename = f'node-v{VERSION}-{system}-{arch}.tar.gz'
    base = f'https://nodejs.org/dist/v{VERSION}/'
    with tempfile.TemporaryDirectory(prefix='node-install-', dir=home) as tmp:
        temporary = Path(tmp)
        with urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60) as response:
            checksums = response.read().decode()
        expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == filename)
        archive = temporary / filename
        with urllib.request.urlopen(base + filename, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise SystemExit('Node archive checksum mismatch; installation stopped.')
        with tarfile.open(archive) as bundle:
            bundle.extractall(temporary, filter='data')
        extracted = temporary / filename.removesuffix('.tar.gz')
        if not verify_node(extracted):
            raise SystemExit('Official Node version/signature verification failed; installation stopped.')
        if target.exists():
            # Preserve a failed installation for diagnosis. Never overwrite running binaries.
            from time import time_ns
            target.rename(home / f'node-invalid-backup-{time_ns()}')
        extracted.rename(target)
    print(f'Installed checksum-verified official Node {VERSION}: {target}')

if __name__ == '__main__':
    main()
