import fs from 'node:fs';
import path from 'node:path';

const BASE=(process.env.SNAPSHOT_WORKER_URL||'').replace(/\/$/,'');
const TOKEN=process.env.SNAPSHOT_ADMIN_TOKEN||'';
if(!BASE) throw new Error('SNAPSHOT_WORKER_URL is missing');
if(!TOKEN) throw new Error('GLOBAL_SNAPSHOT_ADMIN_TOKEN repository secret is missing');

const METRICS=['rate','inflation','gdp','unemployment','debt'];
const RANGES={rate:[-10,150],inflation:[-30,1000],gdp:[-60,60],unemployment:[0,80],debt:[0,1500]};

function normalizePeriod(raw){
  if(!raw) return null;
  const s=String(raw).trim(); let m;
  if((m=s.match(/^(\d{4})-(\d{2})$/))) return {type:'month',key:+m[1]*100 + +m[2]};
  if((m=s.match(/^(\d{4})-?Q([1-4])$/i))) return {type:'quarter',key:+m[1]*100 + +m[2]*3};
  if((m=s.match(/^(\d{4})\s+([A-Za-z]{3})-([A-Za-z]{3})$/))){
    const mo={Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12}[m[3].slice(0,3)];
    if(mo) return {type:'rolling-quarter',key:+m[1]*100+mo};
  }
  if((m=s.match(/^(\d{4})\s+WEO\s+estimate$/i))) return {type:'weo',key:+m[1]*100+12};
  if((m=s.match(/^(\d{4})$/))) return {type:'year',key:+m[1]*100+12};
  return null;
}

function validateSnapshot(snapshot){
  if(!snapshot || snapshot.status!=='ok') throw new Error('Snapshot payload missing/invalid');
  if(snapshot.dataset!=='CapitalRisk Global Snapshot') throw new Error(`Unexpected dataset: ${snapshot.dataset}`);
  if(!Array.isArray(snapshot.countries) || snapshot.countries.length!==47) throw new Error(`Expected 47 economies, got ${snapshot.countries?.length}`);
  const names=new Set(); let fields=0;
  for(const c of snapshot.countries){
    if(!c?.name || names.has(c.name)) throw new Error(`Missing/duplicate country: ${c?.name}`);
    names.add(c.name);
    for(const m of METRICS){
      fields++;
      if(!Object.hasOwn(c,m)) throw new Error(`${c.name}/${m}: field missing`);
      const meta=c.meta?.[m];
      if(!meta) throw new Error(`${c.name}/${m}: metadata missing`);
      const value=c[m];
      if(value===null){
        if(!(c.name==='Argentina' && m==='rate' && /^NOT APPLICABLE/.test(meta.status||''))){
          throw new Error(`${c.name}/${m}: unexpected null`);
        }
        continue;
      }
      const n=Number(value);
      if(!Number.isFinite(n)) throw new Error(`${c.name}/${m}: non-numeric value`);
      const [lo,hi]=RANGES[m];
      if(n<lo || n>hi) throw new Error(`${c.name}/${m}: value ${n} outside safety range`);
      if(!normalizePeriod(meta.period)) throw new Error(`${c.name}/${m}: invalid period ${meta.period}`);
      if(!meta.institution) throw new Error(`${c.name}/${m}: institution missing`);
      if(!/^https:\/\//.test(meta.sourceUrl||'')) throw new Error(`${c.name}/${m}: official source URL missing`);
      if(!/^OFFICIAL/.test(meta.status||'')) throw new Error(`${c.name}/${m}: unexpected status ${meta.status}`);
    }
  }
  if(fields!==235) throw new Error(`Expected 235 fields, got ${fields}`);
}

const controller=new AbortController();
const timer=setTimeout(()=>controller.abort(), 20*60*1000);
let response;
try{
  response=await fetch(`${BASE}/admin/refresh-export?custom=1`,{
    method:'POST',
    headers:{authorization:`Bearer ${TOKEN}`,accept:'application/json'},
    signal:controller.signal
  });
} finally {
  clearTimeout(timer);
}
if(!response.ok){
  const text=await response.text().catch(()=> '');
  throw new Error(`Worker refresh-export failed HTTP ${response.status}: ${text.slice(0,500)}`);
}
const payload=await response.json();
if(payload.status!=='done') throw new Error(`Unexpected Worker response status: ${payload.status}`);
validateSnapshot(payload.snapshot);

const diag=payload.diagnostics||{};
const publishedAt=new Date().toISOString();
const warnings={
  sourceErrors:Array.isArray(diag.sourceErrors)?diag.sourceErrors:[],
  verificationFailures:Array.isArray(diag.verificationFailures)?diag.verificationFailures:[],
  rejected:Array.isArray(diag.rejected)?diag.rejected:[]
};
const partial=warnings.sourceErrors.length>0 || warnings.verificationFailures.length>0 || warnings.rejected.length>0;

const canonical={
  ...payload.snapshot,
  publishedAt,
  refreshStatus:partial?'PARTIAL — last verified values retained where a source failed':'COMPLETE',
  refreshFinished:diag.finished||null
};
const publicDiag={
  publishedAt,
  refreshFinished:diag.finished||null,
  refreshStatus:canonical.refreshStatus,
  updated:diag.updated||[],
  revisions:diag.revisions||[],
  unchangedCount:Array.isArray(diag.unchanged)?diag.unchanged.length:0,
  sourceErrors:warnings.sourceErrors,
  verificationFailures:warnings.verificationFailures,
  rejected:warnings.rejected,
  sources:diag.sources||[]
};

fs.mkdirSync('data',{recursive:true});
fs.writeFileSync(path.join('data','global-snapshot.json'),JSON.stringify(canonical,null,2)+'\n');
fs.writeFileSync(path.join('data','global-snapshot-diagnostics.json'),JSON.stringify(publicDiag,null,2)+'\n');

console.log(`SNAPSHOT VALIDATION PASS: 47 economies / 235 fields`);
console.log(`REFRESH STATUS: ${canonical.refreshStatus}`);
console.log(`UPDATED: ${(diag.updated||[]).length}; REVISIONS: ${(diag.revisions||[]).length}; SOURCE ERRORS: ${warnings.sourceErrors.length}`);
if(partial) console.log('Publishing is safe: failed/rejected candidates did not replace last verified values.');
