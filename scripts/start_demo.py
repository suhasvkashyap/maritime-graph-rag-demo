"""Start the local Demo 3 backend and UI; keep logs and managed PIDs in .run."""
from pathlib import Path
import argparse,json,os,signal,subprocess,time,urllib.request

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.run'


def health(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart',action='store_true',help='Restart only processes previously started by this script')
    args=parser.parse_args()
    RUN.mkdir(exist_ok=True)
    specs=[
        ('backend', ROOT/'pattern1', [str(ROOT/'pattern1/.venv/bin/python'),'-m','uvicorn','main:app','--host','127.0.0.1','--port','8010'], 'http://127.0.0.1:8010/health'),
        ('ui', ROOT, [str(ROOT/'.venv/bin/python'),'-m','streamlit','run','app.py','--server.address','127.0.0.1','--server.port','8501','--server.headless','true','--browser.gatherUsageStats','false'], 'http://127.0.0.1:8501/_stcore/health'),
    ]
    for name,cwd,cmd,url in specs:
        pidfile=RUN/(name+'.json')
        if args.restart and pidfile.exists():
            record=json.loads(pidfile.read_text())
            process=subprocess.run(['ps','-p',str(record['pid']),'-o','command='],capture_output=True,text=True)
            if str(ROOT) in process.stdout and ('uvicorn' if name=='backend' else 'streamlit') in process.stdout:
                os.kill(record['pid'],signal.SIGTERM)
                for _ in range(30):
                    if not health(url):break
                    time.sleep(.2)
        if health(url):
            print(name,'already healthy:',url,flush=True)
            continue
        env=os.environ.copy()
        env.setdefault('AMI_AGENT_MODE','live')
        env.setdefault('AMI_DATA_MODE','live')
        env.setdefault('AMI_MODEL_ID','ami-demo3-qwen')
        with (RUN/(name+'.log')).open('ab') as log:
            proc=subprocess.Popen(cmd,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        pidfile.write_text(json.dumps({'pid':proc.pid,'command':cmd}))
        for _ in range(60):
            if proc.poll() is not None:raise SystemExit(f'{name} exited; see {RUN/name}.log')
            if health(url):break
            time.sleep(.5)
        else:raise SystemExit(f'{name} did not become ready; see {RUN/name}.log')
        print(name,'ready:',url,flush=True)
    print('Open http://127.0.0.1:8501')

if __name__=='__main__':main()
