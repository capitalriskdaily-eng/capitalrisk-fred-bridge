#!/usr/bin/env python3
"""Install the inspected Global Snapshot source repair; preserve live triggers/KV."""
from pathlib import Path
import base64, datetime, hashlib, json, os, re, shutil, subprocess, tempfile, time
import urllib.request, urllib.error

REPO='capitalriskdaily-eng/capitalrisk-fred-bridge'
ACCOUNT='40ce5e11730882562d1c5dcc42be0b27'
WORKER='capitalrisk-global-snapshot'
BASE=f'https://{WORKER}.capitalriskdaily.workers.dev'
VERSION='2026-10-06-source-repair-1'
REF=os.environ.get('CAPITALRISK_SNAPSHOT_REPAIR_REF','')
if not re.fullmatch(r'[a-f0-9]{40}',REF):raise SystemExit('Pinned repair commit is missing.')

def run(args,cwd=None,private=False):
    p=subprocess.run(args,cwd=cwd,text=True,capture_output=True)
    if p.returncode:
        raise SystemExit('Command failed: '+' '.join(args)+'\n'+('Authentication failed; credentials not printed.' if private else p.stderr.strip()))
    return p.stdout

def gh(path):return json.loads(run(['gh','api',path]))
def read_repo(path):
    d=gh(f'repos/{REPO}/contents/{path}?ref={REF}')
    return base64.b64decode(d['content'])

bundle=json.loads(read_repo('global-snapshot-repair/repair-bundle.json'))
root=Path.home()/'CapitalRisk-v1.5-GITHUB-BRIDGE/global-snapshot-worker'
if not root.is_dir():raise SystemExit('Inspected Global Snapshot project missing: '+str(root))
configs=[root/n for n in ('wrangler.jsonc','wrangler.json','wrangler.toml') if (root/n).is_file()]
configs=[p for p in configs if re.search(r'''(?:["']?name["']?\s*[:=]\s*["'])capitalrisk-global-snapshot["']''',p.read_text())]
if not configs:raise SystemExit('Global Snapshot Wrangler config missing; nothing changed.')
config=configs[0]

def jsonc(text):
    # Remove comments only outside quoted strings, preserving URL strings.
    out=[];i=0;quoted=False
    while i<len(text):
        c=text[i]
        if quoted:
            out.append(c)
            if c=='\\' and i+1<len(text):i+=1;out.append(text[i])
            elif c=='"':quoted=False
        elif c=='"':quoted=True;out.append(c)
        elif text[i:i+2]=='//':
            end=text.find('\n',i);i=len(text) if end<0 else end;continue
        elif text[i:i+2]=='/*':
            end=text.find('*/',i+2)
            if end<0:raise ValueError('Unclosed JSONC comment')
            i=end+2;continue
        else:out.append(c)
        i+=1
    return json.loads(re.sub(r',\s*([}\]])',r'\1',''.join(out)))
if config.suffix=='.toml':
    import tomllib
    cfg=tomllib.loads(config.read_text())
else:cfg=jsonc(config.read_text())
if cfg.get('name')!=WORKER:raise SystemExit('Wrong Worker config; nothing changed.')
if cfg.get('account_id') not in (None,ACCOUNT):raise SystemExit('Wrong Cloudflare account; nothing changed.')

print('Preflight: checking source, existing KV binding and live schedule.',flush=True)
cred=json.loads(run(['npx','wrangler','auth','token','--json','--config',config.name],cwd=root,private=True))
headers={'Content-Type':'application/json','User-Agent':'CapitalRisk-Verify'}
if cred.get('type')=='api_key':headers.update({'X-Auth-Key':cred['key'],'X-Auth-Email':cred['email']})
else:headers['Authorization']='Bearer '+cred['token']
def api(path):
    req=urllib.request.Request('https://api.cloudflare.com/client/v4/'+path,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=40) as response:d=json.load(response)
    except urllib.error.HTTPError as e:raise SystemExit('Cloudflare preflight HTTP '+str(e.code)+'; no deployment performed.')
    if not d.get('success'):raise SystemExit('Cloudflare preflight failed; no deployment performed.')
    return d['result']
script=f'accounts/{ACCOUNT}/workers/scripts/{WORKER}'
settings=api(script+'/settings')
livekv=next((b.get('namespace_id') for b in settings.get('bindings',[]) if b.get('name')=='SNAPSHOT_KV'),None)
localkv=next((b.get('id') for b in cfg.get('kv_namespaces',[]) if b.get('binding')=='SNAPSHOT_KV'),None)
if not livekv or localkv!=livekv:raise SystemExit('KV binding differs from live Worker; nothing changed.')
schedules=api(script+'/schedules')
if isinstance(schedules,dict):schedules=schedules.get('schedules',[])
crons=sorted(s['cron'] for s in schedules)
print('Existing schedule preserved:',crons,flush=True)
updates=[]
for item in bundle['files']:
    p=root/item['path']
    old=p.read_bytes()
    current=hashlib.sha256(old.decode().replace('\r\n','\n').strip().encode()).hexdigest()
    desired=item['content'].encode()
    desired_hash=hashlib.sha256(item['content'].strip().encode()).hexdigest()
    if current not in (item['before_sha256'],desired_hash):
        raise SystemExit('Source differs from inspected version: '+str(p)+'; nothing changed.')
    check=subprocess.run(['node','--input-type=module','--check'],input=item['content'],text=True,capture_output=True)
    if check.returncode:raise SystemExit('Syntax validation failed: '+item['path']+'\n'+check.stderr)
    updates.append((p,desired))
# Verify existing workflow and access before modifying local files.
gh(f'repos/{REPO}/contents/.github/workflows/global-snapshot-friday.yml?ref={REF}')
backup=root/('backup-source-repair-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
for p,data in updates:
    dest=backup/p.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
shutil.copy2(config,backup/config.name)
# Use the server's actual triggers, never add another cron.
cfg['account_id']=ACCOUNT;cfg.setdefault('triggers',{})['crons']=crons
repair_config=root/'wrangler.snapshot-repair.jsonc'
if repair_config.exists():shutil.copy2(repair_config,backup/repair_config.name)
repair_config.write_text(json.dumps(cfg,indent=2)+'\n')
for p,data in updates:p.write_bytes(data)
print('Validated source repair installed. Backup:',backup,flush=True)
p=subprocess.run(['npx','wrangler','deploy','--config',repair_config.name],cwd=root)
if p.returncode:raise SystemExit('Deployment failed. Backup retained; no healthy verdict issued.')
def public(path):
    req=urllib.request.Request(BASE+path,headers={'User-Agent':'CapitalRisk-Verify','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=40) as response:return json.load(response)
seen=False
for attempt in range(6):
    try:
        if public('/health').get('repairVersion')==VERSION:seen=True;break
    except Exception:pass
    if attempt<5:time.sleep(5)
if not seen:raise SystemExit('Deployment version not visible yet. Backup retained; no healthy verdict issued.')
after=api(script+'/schedules')
if isinstance(after,dict):after=after.get('schedules',[])
if sorted(s['cron'] for s in after)!=crons:raise SystemExit('Schedule verification failed; inspect before proceeding.')
deployed_at=datetime.datetime.now(datetime.timezone.utc)
print('DEPLOYED VERSION VERIFIED. Live schedule unchanged.',flush=True)
# Reuse an active full refresh. Submit only one new refresh if none is active.
active=gh(f'repos/{REPO}/actions/workflows/global-snapshot-friday.yml/runs?per_page=10')['workflow_runs']
r=next((x for x in active if x['status'] in ('queued','in_progress','waiting','pending')),None)
started=datetime.datetime.now(datetime.timezone.utc)
if not r:
    run(['gh','workflow','run','global-snapshot-friday.yml','--repo',REPO,'--ref','main'])
    for attempt in range(10):
        rs=gh(f'repos/{REPO}/actions/workflows/global-snapshot-friday.yml/runs?per_page=5')['workflow_runs']
        r=next((x for x in rs if datetime.datetime.fromisoformat(x['created_at'].replace('Z','+00:00'))>=started-datetime.timedelta(seconds=10) and x['event']=='workflow_dispatch'),None)
        if r:break
        time.sleep(3)
if not r:raise SystemExit('Refresh submitted but run ID not visible yet. Do not submit duplicates.')
print('REFRESH:',r['html_url'],flush=True)
print('Watching the one refresh; closing this terminal does not stop GitHub.',flush=True)
for attempt in range(65):
    job=gh(f'repos/{REPO}/actions/runs/{r["id"]}')
    print(datetime.datetime.now().strftime('%H:%M:%S'),job['status'],job.get('conclusion') or '',flush=True)
    if job['status']=='completed':
        if job['conclusion']!='success':
            # Print only relevant failure log; never dump auth/environment lines.
            p=subprocess.run(['gh','run','view',str(r['id']),'--repo',REPO,'--log-failed'],text=True,capture_output=True)
            lines=[x for x in p.stdout.splitlines() if re.search(r'Error:|failed HTTP|exceeded|unexpected|invalid|outside safety',x,re.I)]
            for x in lines[-12:]:print(x)
            raise SystemExit('Refresh failed. '+r['html_url'])
        break
    time.sleep(30)
else:raise SystemExit('Refresh still active; keep its existing run, do not submit another: '+r['html_url'])
health=public('/health')
print('\nPUBLISHED HEALTH:',json.dumps(health,indent=2),flush=True)
checked=health.get('lastCheckedAt')
if not checked or datetime.datetime.fromisoformat(checked.replace('Z','+00:00'))<deployed_at:
    raise SystemExit('The completed run did not prove a refresh after deployment. Keep this output for inspection.')
print('\nPaste this final health output. Partial means remaining failures are still visible; it is not a complete-health verdict.',flush=True)
