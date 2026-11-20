"""Start only the demo's OpenClaw Gateway; leave existing demo services alone."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / '.run'
PID = RUN / 'openclaw-gateway.json'


def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18790/health', timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    if '--stop' in sys.argv:
        if PID.exists():
            pid = json.loads(PID.read_text())['pid']
            command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
            # OpenClaw can rename its process; verify the process owns our port too.
            listener = subprocess.run(['lsof', '-nP', '-a', '-p', str(pid), '-iTCP:18790', '-sTCP:LISTEN'], capture_output=True, text=True)
            if 'openclaw' in command and listener.returncode == 0:
                os.kill(pid, signal.SIGTERM)
                print('Stopped demo OpenClaw Gateway.')
            else:
                print('Recorded process is absent or cannot be verified; no process stopped.')
        return
    if healthy():
        print('Port 18790 is already serving HTTP; verify with scripts/openclaw.sh health.')
        return
    RUN.mkdir(exist_ok=True)
    with (RUN / 'openclaw-gateway.log').open('ab') as log:
        process = subprocess.Popen([str(ROOT / 'scripts/openclaw.sh'), 'gateway', 'run'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    PID.write_text(json.dumps({'pid': process.pid}))
    for _ in range(90):
        if process.poll() is not None:
            raise SystemExit('Gateway exited. See .run/openclaw-gateway.log')
        if healthy():
            print('OpenClaw ready: http://127.0.0.1:18790')
            print('Open authenticated chat with: ./scripts/openclaw.sh dashboard')
            return
        time.sleep(0.5)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    raise SystemExit('Gateway startup timed out and was stopped. Inspect .run/openclaw-gateway.log')

if __name__ == '__main__':
    main()
