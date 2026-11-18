"""Generate local-only configuration and optionally start an isolated Neo4j container."""
import argparse, os, secrets, shutil, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start-neo4j', action='store_true')
    p.add_argument('--engine', choices=['podman','docker'], default='podman')
    a=p.parse_args()
    app=ROOT/'.env'
    if not app.exists(): shutil.copyfile(ROOT/'.env.example', app); app.chmod(0o600)
    env=ROOT/'pattern1/.env'
    if not env.exists():
        env.write_text('MAAS_BASE_URL=http://localhost:11434/v1\nMAAS_API_KEY=ollama\nNEO4J_URI=bolt://localhost:17687\nNEO4J_USERNAME=neo4j\nNEO4J_DATABASE=neo4j\nNEO4J_PASSWORD='+secrets.token_hex(24)+'\n')
        env.chmod(0o600)
    if a.start_neo4j:
        values=dict(line.split('=',1) for line in env.read_text().splitlines() if '=' in line and not line.startswith('#'))
        if values.get('NEO4J_URI') != 'bolt://localhost:17687':
            raise SystemExit('Existing config targets another database; refusing to start a new container for it.')
        existing=subprocess.run([a.engine,'container','exists','ami-maritime-neo4j'],capture_output=True) if a.engine=='podman' else subprocess.run([a.engine,'inspect','ami-maritime-neo4j'],capture_output=True)
        if existing.returncode==0:
            subprocess.run([a.engine,'start','ami-maritime-neo4j'],check=True)
        else:
            child=os.environ.copy();child['NEO4J_AUTH']='neo4j/'+values['NEO4J_PASSWORD']
            subprocess.run([a.engine,'run','-d','--name','ami-maritime-neo4j','-p','127.0.0.1:17474:7474','-p','127.0.0.1:17687:7687','-e','NEO4J_AUTH','-v','ami-maritime-neo4j-data:/data','docker.io/library/neo4j:2026.10.2'],env=child,check=True)
    print('Local configuration ready. No credentials printed; .env files must remain untracked.')
if __name__=='__main__': main()
