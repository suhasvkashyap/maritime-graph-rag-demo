"""Fixed, bounded live probes in the dedicated maritime OpenShell sandbox."""
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
import streamlit as st

SANDBOX = 'ami-maritime'


def probe():
    cli = shutil.which('openshell') or '/opt/homebrew/bin/openshell'
    script = """import urllib.request,urllib.error,json
rows=[]
for name,url in [('Maritime Graph RAG (allowed)','http://192.168.127.254:8010/health'),('Outside-policy document service','http://192.168.127.254:8031/documents/restricted-maritime-brief.txt')]:
 try:
  r=urllib.request.urlopen(url,timeout=5); rows.append({'request':name,'status':r.status})
 except urllib.error.HTTPError as e: rows.append({'request':name,'status':e.code})
 except urllib.error.URLError as e: rows.append({'request':name,'errno':getattr(e.reason,'errno',None),'error':str(e.reason)})
print(json.dumps(rows))
"""
    started=time.time()
    result=subprocess.run([cli,'sandbox','exec',SANDBOX,'--timeout','20','--no-tty','--no-login-shell','--','/usr/local/bin/python3.12','-c',script],capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('Maritime sandbox unavailable. Start ami-maritime and retry.')
    rows=json.loads(result.stdout.strip())
    evidence=''
    for _ in range(5):
        logs=subprocess.run([cli,'logs',SANDBOX,'--since','30s','-n','100'],capture_output=True,text=True,timeout=10)
        evidence='\n'.join(line for line in (logs.stdout+logs.stderr).splitlines() if '192.168.127.254:8031' in line and 'DENIED' in line and (m:=re.match(r'\[(\d+\.\d+)\]',line)) and float(m.group(1))>=started)
        if evidence: break
        time.sleep(1)
    return {'sandbox':SANDBOX,'observed_at':datetime.now(timezone.utc).isoformat(),'verified':rows[0].get('status')==200 and rows[1].get('errno')==13 and bool(evidence),'requests':rows,'audit_event':evidence}


@st.dialog('Maritime OpenShell — live access-control test', width='large')
def show_maritime_policy():
    st.write('The maritime tool worker runs inside **ami-maritime**, using this demo’s OpenShell policy. The dashboard launches a fixed access test in that sandbox; model-directed investigation remains local.')
    st.markdown('**Allowed:** maritime Graph RAG on **8010**. **Outside policy:** synthetic document-service destination on **8031**.')
    st.markdown('''<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
    <div style="border:1px solid #aaa;border-radius:8px;padding:15px">Maritime tool worker<br><b>ami-maritime sandbox</b></div> →
    <div style="border:1px solid #aaa;border-radius:8px;padding:15px">OpenShell<br><b>Destination allowlist</b></div> →
    <div style="border:2px solid #c00;border-radius:8px;padding:15px">Restricted briefing on 8031<br><b>Expected: DENY</b></div></div>''',unsafe_allow_html=True)
    if st.button('Run maritime denial test',type='primary'):
        st.session_state.pop('maritime_probe',None)
        with st.spinner('Running the maritime sandbox control and denial checks…'):
            try: st.session_state['maritime_probe']=probe()
            except Exception as exc: st.error(f'Test could not complete: {type(exc).__name__}. No simulated result is substituted.')
    result=st.session_state.get('maritime_probe')
    if result:
        if result['verified']: st.success('Verified: Graph RAG on 8010 allowed; outside-policy destination on 8031 denied by OpenShell.')
        else: st.warning('Not verified. Review the control result and audit event before presenting this run.')
        st.caption(f"Sandbox: {result['sandbox']} · {result['observed_at']}")
        st.json(result['requests'])
        st.code(result['audit_event'] or 'No matching fresh denial event found.',language='text')
    st.caption('Endpoint-level enforcement: the restricted connection is blocked before any document can be retrieved. This does not test document-path filtering. The restricted URL is a synthetic probe; no confidential document is accessed.')
