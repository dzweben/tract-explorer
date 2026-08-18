#!/usr/bin/env python3
"""
Build index.html — a reusable, fully data-agnostic viewer for
node-wise (along-tract) statistical results.

Design (deliberately general):
  * Input = a LONG-format CSV, one row per node:  outcome, tract, metric, node, t, p  (required)
    + optional per-analysis columns: hemisphere, N, covariates, extent_threshold, cluster_p, passed, dir
    + ANY OTHER column = a grouping dimension (family, condition, cohort, site ...) that becomes a filter.
    (JSON in the results_data.json shape is also accepted.)
  * Everything else is DERIVED in the browser from the node rows: n_sig_nodes, clusters (contiguous
    p<.05 runs), max cluster, laterality + hemispheric-overlap panel (only if a hemisphere column with
    L/R exists), node count. Users never compute cluster stats themselves.
  * Filters are discovered from the data; a filter is hidden if its column has one value.
  * Hemisphere is OPTIONAL: laterality/overlap only render when present.
  * Node axis-end labels, title, method are optional meta (?title= etc. or a meta row).
Nothing is uploaded — files are parsed locally in the browser.
"""
from pathlib import Path
import re

OUT = Path(__file__).resolve().parent
css = r"""<style>
:root{--bg:#0f1117;--card:#1a1d27;--card2:#232733;--ink:#e6e9ef;--mut:#9aa3b2;--line:#2c3140;
--pos:#f4664a;--neg:#3b82f6;--sig:#22c55e;--accent:#a78bfa;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{padding:22px 26px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#171a24,#0f1117)}
h1{margin:0 0 4px;font-size:22px}
.sub{color:var(--mut);font-size:13px}
.wrap{padding:20px 26px;max-width:1400px;margin:0 auto}
.pill{display:inline-block;background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:3px 11px;margin:2px;font-size:12px;color:var(--mut)}
.section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}
.section h2{margin:0 0 12px;font-size:16px;color:var(--accent)}
.grid{display:grid;gap:10px}
.demo-grid{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.stat{background:var(--card2);border:1px solid var(--line);border-radius:9px;padding:11px 13px}
.stat .k{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.stat .v{font-size:19px;font-weight:600;margin-top:3px}
.stat .d{color:var(--mut);font-size:12px;margin-top:2px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.controls select,.controls input{background:var(--card2);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px}
.controls label{color:var(--mut);font-size:12px;margin-right:3px}
.count{color:var(--mut);font-size:13px;margin-left:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--ink)}
td{padding:8px 10px;border-bottom:1px solid #20242f}
tr.row{cursor:pointer}
tr.row:hover{background:var(--card2)}
tr.sig td{background:rgba(34,197,94,.06)}
.badge{display:inline-block;border-radius:6px;padding:2px 7px;font-size:11px;font-weight:600}
.b-sig{background:rgba(34,197,94,.16);color:#4ade80}
.b-ns{background:#242835;color:var(--mut)}
.b-pos{background:rgba(244,102,74,.16);color:#fb7a5e}
.b-neg{background:rgba(59,130,246,.16);color:#60a5fa}
.hemi{font-weight:600}
.detail{background:var(--card2);border-top:2px solid var(--accent)}
.detail td{padding:0}
.dbox{padding:18px 22px}
.dgrid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.dcol h4{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--accent)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
.kv .k{color:var(--mut)}
.nodeviz{margin-top:10px;background:#12141c;border:1px solid var(--line);border-radius:8px;padding:10px}
.script{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:#c9d1e0;background:#12141c;border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:4px;white-space:pre-wrap;line-height:1.45}
.latbar{display:flex;height:26px;border-radius:6px;overflow:hidden;border:1px solid var(--line);margin-top:6px}
.latbar .L{background:#3b82f6;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff}
.latbar .R{background:#f4664a;display:flex;align-items:center;justify-center;justify-content:center;font-size:11px;color:#fff}
a.back{color:var(--accent);text-decoration:none;font-size:13px}
.legend{font-size:12px;color:var(--mut);margin-top:8px}
.tag{font-size:11px;color:var(--mut)}
.clbl{font-size:11px;color:var(--mut)}

.drop{border:2px dashed var(--line);border-radius:10px;padding:26px 20px;text-align:center;color:var(--mut);font-size:14px;background:var(--card2);transition:border-color .12s,color .12s}
.drop.over{border-color:var(--accent);color:var(--ink)}
.flink{color:var(--accent);cursor:pointer;text-decoration:underline}
.loaderr{color:#fb7a5e;font-size:13px;margin-top:8px;white-space:pre-wrap}
.ok{color:#4ade80;font-size:13px;margin-top:8px}
.doc{font-size:13px;line-height:1.6;color:var(--ink);margin-top:8px}
.doc code{background:#12141c;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12px;color:#c9d1e0}
.doc b{color:var(--accent)}
.doc table{width:auto;margin:6px 0}
.doc td,.doc th{padding:4px 10px;font-size:12.5px}
</style>"""


JS = r"""
<script>
// ===================== data model =====================
let DATA=[], META={}, GROUPS=[], NN=100, HAS_HEMI=false;
const RESERVED=['outcome','tract','metric','node','t','p','hemisphere','n','covariates','extent_threshold','cluster_p','passed','dir','id'];
const norm=s=>String(s??'').trim();
const num=v=>{const x=parseFloat(v);return isNaN(x)?null:x;};
const truthy=v=>{const s=norm(v).toLowerCase();return ['1','true','yes','y','t','pass','sig'].includes(s);};

// ---- CSV parsing (quoted fields, commas, newlines) ----
function parseCSV(text){
  const rows=[];let row=[],cur='',q=false;
  for(let i=0;i<text.length;i++){const c=text[i];
    if(q){if(c=='"'){if(text[i+1]=='"'){cur+='"';i++;}else q=false;}else cur+=c;}
    else if(c=='"')q=true;
    else if(c==','){row.push(cur);cur='';}
    else if(c=='\n'||c=='\r'){if(c=='\r'&&text[i+1]=='\n')i++;row.push(cur);rows.push(row);row=[];cur='';}
    else cur+=c;}
  if(cur!==''||row.length){row.push(cur);rows.push(row);}
  const nonempty=rows.filter(r=>r.some(x=>norm(x)!==''));
  if(nonempty.length<2)throw new Error('CSV has no data rows.');
  const hdr=nonempty[0].map(h=>norm(h));
  return nonempty.slice(1).map(r=>Object.fromEntries(hdr.map((h,i)=>[h,r[i]??''])));
}

// ---- long CSV -> analyses (derive everything) ----
function fromLong(rows){
  const cols=Object.keys(rows[0]);
  // case-insensitive lookup + common aliases (Node, t_value, p_value, ...) work as-is
  const ALIAS={node:['node'],t:['t','t_value','tvalue','tstat','statistic'],p:['p','p_value','pvalue','pval'],
    n:['n','n_subjects','nsubjects'],covariates:['covariates','covariate'],extent_threshold:['extent_threshold','extentthresholdnodes','extent_thr'],
    cluster_p:['cluster_p','clusterpvalue','cluster_pvalue','fwe_p'],passed:['passed','passextentthreshold','fwe','significant','sig'],
    outcome:['outcome','outcome_label','dv'],tract:['tract','tract_label','bundle'],metric:['metric','measure'],hemisphere:['hemisphere','hemi','side']};
  const lc={};cols.forEach(c=>{const l=c.toLowerCase();lc[l]=c;for(const k in ALIAS)if(ALIAS[k].includes(l))lc[k]=c;});
  const aliasAll=new Set(Object.values(ALIAS).flat());
  const req=['outcome','tract','metric','node','t','p'];
  const missing=req.filter(k=>!(k in lc));
  if(missing.length)throw new Error('Missing required column(s): '+missing.join(', ')+'.\nRequired: outcome, tract, metric, node, t, p  (one row per node).');
  const C=k=>lc[k];  // actual column name for a reserved key
  HAS_HEMI=('hemisphere' in lc);
  GROUPS=cols.filter(c=>{const l=c.toLowerCase();return !aliasAll.has(l)&&!RESERVED.includes(l)&&!['estimate','df','clusterid'].includes(l);});      // extra columns = filter dimensions
  const keyOf=r=>[r[C('outcome')],r[C('tract')],r[C('metric')],HAS_HEMI?r[C('hemisphere')]:'',...GROUPS.map(g=>r[g])].map(norm).join('||');
  const by=new Map();
  rows.forEach(r=>{const k=keyOf(r);if(!by.has(k))by.set(k,[]);by.get(k).push(r);});
  const out=[];
  by.forEach((rs,k)=>{
    rs.sort((a,b)=>num(a[C('node')])-num(b[C('node')]));
    const nodes=rs.map(r=>num(r[C('node')]));
    const nn=Math.max(...nodes)+1;
    const tv=new Array(nn).fill(null),pv=new Array(nn).fill(null);
    rs.forEach(r=>{const i=num(r[C('node')]);tv[i]=num(r[C('t')]);pv[i]=num(r[C('p')]);});
    const first=rs[0];
    const a={id:k,outcome_label:norm(first[C('outcome')]),tract_label:norm(first[C('tract')]),metric:norm(first[C('metric')]),
      hemisphere:HAS_HEMI?norm(first[C('hemisphere')]).toUpperCase():'', tvals:tv,pvals:pv,
      N:('n' in lc)?num(first[C('n')]):null, covariates:('covariates' in lc)?norm(first[C('covariates')]):'',
      extent_threshold:('extent_threshold' in lc)?num(first[C('extent_threshold')]):null,
      best_p:('cluster_p' in lc)?num(first[C('cluster_p')]):null,
      passed:('passed' in lc)?truthy(first[C('passed')]):null};
    GROUPS.forEach(g=>a[g]=norm(first[g]));
    // derive clusters from p<.05 runs
    const sig=pv.map(x=>x!=null&&x<0.05); a.n_sig_nodes=sig.filter(Boolean).length;
    a.sig_node_list=sig.map((s,i)=>s?i:-1).filter(i=>i>=0);
    a.clusters=[];let s=null;
    for(let i=0;i<=nn;i++){const on=i<nn&&sig[i];
      if(on&&s==null)s=i; else if(!on&&s!=null){const e=i-1;const ts=tv.slice(s,e+1).map(x=>x??0);
        const mt=ts.reduce((u,v)=>u+v,0)/ts.length;const mi=ts.map(Math.abs).indexOf(Math.max(...ts.map(Math.abs)));
        const size=e-s+1;const passes=(a.extent_threshold!=null)?size>=a.extent_threshold:(a.passed===true&&size===Math.max(size,0));
        a.clusters.push({start:s,end:e,size,dir:mt>=0?'Positive':'Negative',mean_t:+mt.toFixed(2),max_abs_t:+ts[mi].toFixed(2),max_abs_t_node:s+mi,p:null,passes:false});s=null;}}
    a.obs_max_cluster=a.clusters.length?Math.max(...a.clusters.map(c=>c.size)):0;
    // FWE: if extent_threshold given -> size rule; else if passed given -> flag the largest cluster
    if(a.extent_threshold!=null){a.clusters.forEach(c=>c.passes=c.size>=a.extent_threshold);a.passed=a.clusters.some(c=>c.passes);}
    else if(a.passed===true&&a.clusters.length){const big=a.clusters.reduce((x,y)=>y.size>x.size?y:x);big.passes=true;big.p=a.best_p;}
    else if(a.passed==null)a.passed=false;
    if(a.best_p!=null)a.clusters.filter(c=>c.passes).forEach(c=>c.p=a.best_p);
    a.n_perms=META.n_perms||null; a.dropped=null; a.family=a.family||''; a.condition=a.condition||''; a.tract_type=a.tract_type||'';
    out.push(a);
  });
  NN=Math.max(...out.map(a=>a.tvals.length));
  // laterality: pair each analysis with its opposite-hemisphere sibling (same outcome/metric/groups, tract label differing only by side)
  if(HAS_HEMI){out.forEach(a=>{const sib=sibOf(a,out);const L=a.hemisphere==='L'?a:sib,R=a.hemisphere==='R'?a:sib;
    const Ls=L?L.n_sig_nodes:0,Rs=R?R.n_sig_nodes:0,tot=Ls+Rs;
    const ov=(L&&R)?L.sig_node_list.filter(i=>R.sig_node_list.includes(i)):[];
    a.laterality={L_sig:Ls,R_sig:Rs,pct_left:tot?+(100*Ls/tot).toFixed(0):0,pct_right:tot?+(100*Rs/tot).toFixed(0):0,overlap_nodes:ov};});}
  return out;
}
function tractBase(t){return norm(t).replace(/\b(left|right|L|R|lh|rh)\b/ig,'').replace(/[_\-\s]+/g,' ').trim().toLowerCase();}
function sibOf(a,pool){pool=pool||DATA;return pool.find(x=>x!==a&&x.outcome_label===a.outcome_label&&x.metric===a.metric&&x.hemisphere&&x.hemisphere!==a.hemisphere&&tractBase(x.tract_label)===tractBase(a.tract_label)&&GROUPS.every(g=>x[g]===a[g]));}

// ---- JSON (results_data.json shape) ----
function fromJSON(o){
  const arr=Array.isArray(o)?o:(o.results||[]);
  if(!arr.length)throw new Error('No result records found. Expected an array of results, or {"meta":..,"results":[..]}.');
  META=Object.assign({},META,Array.isArray(o)?{}:(o.meta||{}));
  HAS_HEMI=arr.some(a=>a.hemisphere==='L'||a.hemisphere==='R');
  const std=['id','outcome','outcome_label','tract','tract_label','hemisphere','metric','N','dropped','covariates','n_sig_nodes','obs_max_cluster','extent_threshold','n_passing','n_perms','passed','best_p','clusters','sig_node_list','tvals','pvals','laterality'];
  GROUPS=Object.keys(arr[0]).filter(k=>!std.includes(k)&&typeof arr[0][k]!=='object');
  NN=Math.max(...arr.map(a=>(a.tvals||[]).length));
  return arr;
}

// ===================== UI =====================
function uniq(k){return [...new Set(DATA.map(r=>r[k]).filter(v=>v!=null&&v!==''))].sort();}
function buildFilters(){
  const host=document.getElementById('filters');host.innerHTML='';
  const dims=[['tract_label','Tract'],['metric','Metric'],...(HAS_HEMI?[['hemisphere','Hemisphere']]:[]),['outcome_label','Outcome'],...GROUPS.map(g=>[g,g])];
  dims.forEach(([k,lab])=>{const vals=uniq(k);if(vals.length<2)return;
    const s=document.createElement('span');s.innerHTML=`<label>${lab}</label><select data-k="${k}"><option value="">All</option>${vals.map(v=>`<option>${v}</option>`).join('')}</select>`;host.appendChild(s);});
  const sig=document.createElement('span');sig.innerHTML=`<label>Show</label><select id="f_sig"><option value="all">All</option><option value="sig">FWE-significant only</option><option value="trend">≥5 sig nodes</option></select>`;host.appendChild(sig);
  const q=document.createElement('input');q.id='f_search';q.placeholder='search…';q.style.minWidth='130px';host.appendChild(q);
  const c=document.createElement('span');c.className='count';c.id='count';host.appendChild(c);
  host.querySelectorAll('select,input').forEach(el=>el.oninput=render);
}
function passFilters(r){
  for(const s of document.querySelectorAll('#filters select[data-k]')){if(s.value&&norm(r[s.dataset.k])!==s.value)return false;}
  const sg=document.getElementById('f_sig').value,q=document.getElementById('f_search').value.toLowerCase();
  if(sg==='sig'&&!r.passed)return false; if(sg==='trend'&&r.n_sig_nodes<5)return false;
  if(q&&!Object.values(r).filter(v=>typeof v==='string').join(' ').toLowerCase().includes(q))return false;
  return true;
}
let sortK='best_p',sortDir=1;
function dirBadge(d){return d==='Positive'?'<span class="badge b-pos">Positive</span>':'<span class="badge b-neg">Negative</span>'}
function fmtP(p){if(p==null)return '—';return p===0?'<1/n_perm':p}
function nodeViz(r,H=90){
  const W=560,pad=18,n=r.tvals.length;const ts=r.tvals.map(x=>x==null?0:x);const mx=Math.max(3,...ts.map(Math.abs));const bw=(W-2*pad)/n;
  let bars='';for(let i=0;i<n;i++){const t=ts[i];const sig=r.pvals[i]!=null&&r.pvals[i]<0.05;const h=Math.abs(t)/mx*(H/2-8);const y=t>=0?(H/2-h):(H/2);const col=sig?(t>=0?'#f4664a':'#3b82f6'):'#39404f';
    bars+=`<rect x="${pad+i*bw}" y="${y}" width="${Math.max(bw-0.4,0.6)}" height="${h}" fill="${col}"><title>node ${i}: t=${t}</title></rect>`;}
  let shade='';r.clusters.forEach(c=>{if(c.passes)shade+=`<rect x="${pad+c.start*bw}" y="4" width="${(c.end-c.start+1)*bw}" height="${H-8}" fill="rgba(34,197,94,.10)" stroke="rgba(34,197,94,.4)"/>`;});
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">${shade}<line x1="${pad}" y1="${H/2}" x2="${W-pad}" y2="${H/2}" stroke="#4a5163"/>${bars}
   <text x="${pad}" y="${H-2}" fill="#6b7280" font-size="9">${META.node0||'node 0'}</text><text x="${W-pad}" y="${H-2}" fill="#6b7280" font-size="9" text-anchor="end">${META.node1||('node '+(n-1))}</text></svg>`;
}
function miniProfile(r,label,overlap){
  const W=560,H=64,pad=18,n=r?r.tvals.length:NN;const ts=r?r.tvals.map(x=>x==null?0:x):new Array(n).fill(0);const mx=Math.max(3,...ts.map(Math.abs));const bw=(W-2*pad)/n;let bars='';
  for(let i=0;i<n;i++){const t=ts[i];const sig=r&&r.pvals[i]!=null&&r.pvals[i]<0.05;const ov=overlap.includes(i);const h=Math.abs(t)/mx*(H/2-6);const y=t>=0?(H/2-h):(H/2);
    const col=ov&&sig?'#22c55e':(sig?(t>=0?'#f4664a':'#3b82f6'):'#39404f');bars+=`<rect x="${pad+i*bw}" y="${y}" width="${Math.max(bw-0.4,0.6)}" height="${h}" fill="${col}"><title>node ${i}: t=${t}</title></rect>`;}
  let shade='';if(r)r.clusters.forEach(c=>{if(c.passes)shade+=`<rect x="${pad+c.start*bw}" y="3" width="${(c.end-c.start+1)*bw}" height="${H-6}" fill="rgba(34,197,94,.08)" stroke="rgba(34,197,94,.35)"/>`;});
  return `<div style="display:flex;align-items:center;gap:8px"><div style="width:34px;font-size:11px;color:var(--mut);text-align:right">${label}</div><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">${shade}<line x1="${pad}" y1="${H/2}" x2="${W-pad}" y2="${H/2}" stroke="#4a5163"/>${bars}</svg></div>`;
}
function detail(r){
  const lat=r.laterality;const sib=HAS_HEMI?sibOf(r):null;
  const clusters=r.clusters.length?('<table style="width:auto"><thead><tr><th>Nodes</th><th>Size</th><th>Dir</th><th>mean t</th><th>max|t|</th><th>@node</th><th>cluster p</th><th>FWE</th></tr></thead><tbody>'+
    r.clusters.map(c=>`<tr><td>${c.start}–${c.end}</td><td>${c.size}</td><td>${dirBadge(c.dir)}</td><td>${c.mean_t}</td><td>${c.max_abs_t}</td><td>${c.max_abs_t_node}</td><td>${fmtP(c.p)}</td><td>${c.passes?'<span class="badge b-sig">PASS</span>':'<span class="badge b-ns">no</span>'}</td></tr>`).join('')+'</tbody></table>'):'<span class="tag">No contiguous clusters formed.</span>';
  const groupsKV=GROUPS.map(g=>`<div class="k">${g}</div><div>${r[g]||'—'}</div>`).join('');
  let latHTML='';
  if(HAS_HEMI&&lat){const Lp=lat.pct_left||0,Rp=lat.pct_right||0;const L=r.hemisphere==='L'?r:sib,R=r.hemisphere==='R'?r:sib;
    latHTML=`<h4 style="margin-top:16px">Laterality <span class="tag">(node-wise-sig nodes, L vs R)</span></h4>
     <div class="latbar"><div class="L" style="width:${Lp}%">L ${lat.L_sig} (${Lp}%)</div><div class="R" style="width:${Rp}%">R ${lat.R_sig} (${Rp}%)</div></div>
     <h4 style="margin-top:14px">Hemispheric node overlap <span class="tag">(same outcome + metric, L and R aligned by node)</span></h4>
     <div class="nodeviz">${miniProfile(L,'L',lat.overlap_nodes||[])}${miniProfile(R,'R',lat.overlap_nodes||[])}<div style="font-size:10px;color:var(--mut);text-align:right;padding-right:2px">${META.node0||'node 0'} ————— ${META.node1||'last node'}</div></div>
     <div class="tag" style="margin-top:6px">Overlapping significant nodes (sig on <b>both</b> sides): ${(lat.overlap_nodes&&lat.overlap_nodes.length)?'<span style="color:#4ade80">'+lat.overlap_nodes.join(', ')+'</span>':'none'}${sib?'':' <i>(no opposite-hemisphere match found)</i>'}</div>`;}
  const cov=r.covariates?`<h4 style="margin-top:16px">Controlled for (covariates)</h4><div class="tag">${r.covariates}</div>`:'';
  const prov=META.scripts_note?`<h4 style="margin-top:18px">Provenance</h4><div class="script">${META.scripts_note}</div>`:'';
  return `<td colspan="99" class="detail"><div class="dbox"><div class="dgrid"><div class="dcol">
    <h4>${r.outcome_label} &nbsp;·&nbsp; ${r.tract_label}${r.hemisphere?' ('+r.hemisphere+')':''} &nbsp;·&nbsp; ${r.metric}</h4>
    <div class="kv">${groupsKV}<div class="k">Metric</div><div>${r.metric}</div>
     ${r.N!=null?`<div class="k">N</div><div>${r.N}</div>`:''}
     ${r.n_perms?`<div class="k">Permutations</div><div>${r.n_perms}${META.method?' ('+META.method+')':''}</div>`:''}
     <div class="k">Node-wise-significant nodes</div><div>${r.n_sig_nodes} / ${r.tvals.length}</div>
     <div class="k">Observed max cluster</div><div>${r.obs_max_cluster} nodes</div>
     ${r.extent_threshold!=null?`<div class="k">Extent threshold</div><div>${r.extent_threshold} nodes</div>`:''}
     <div class="k">FWE verdict</div><div>${r.passed?'<span class="badge b-sig">SIGNIFICANT</span>'+(r.best_p!=null?' (cluster p='+fmtP(r.best_p)+')':''):'<span class="badge b-ns">n.s.</span>'}</div>
    </div>${cov}${latHTML}</div>
    <div class="dcol"><h4>Node-wise values <span class="tag">(each bar = a separate regression across subjects at that node; a profile along the tract, not its shape; green = FWE cluster; colored bars = p&lt;0.05)</span></h4><div class="nodeviz">${nodeViz(r)}</div>
     <h4 style="margin-top:14px">Clusters</h4>${clusters}
     <h4 style="margin-top:14px">Significant nodes (p&lt;0.05, uncorrected)</h4><div class="tag" style="line-height:1.6">${r.sig_node_list.length?r.sig_node_list.join(', '):'none'}</div></div></div>${prov}</div></td>`;
}
function buildHeader(){
  const cols=[['outcome_label','Outcome'],...GROUPS.map(g=>[g,g]),['tract_label','Tract'],...(HAS_HEMI?[['hemisphere','Hemi']]:[]),['metric','Metric'],['N','N'],['n_sig_nodes','Sig nodes'],['obs_max_cluster','Max cluster'],['extent_threshold','Thresh'],['best_p','Cluster p'],['passed','FWE']];
  const showN=DATA.some(r=>r.N!=null),showT=DATA.some(r=>r.extent_threshold!=null);
  const use=cols.filter(([k])=>!(k==='N'&&!showN)&&!(k==='extent_threshold'&&!showT));
  document.getElementById('thead').innerHTML='<tr>'+use.map(([k,l])=>`<th data-k="${k}">${l}</th>`).join('')+'</tr>';
  document.querySelectorAll('#thead th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(sortK===k)sortDir*=-1;else{sortK=k;sortDir=1}render()});
  return use;
}
let COLS=[];
function render(){
  let rows=DATA.filter(passFilters);
  rows.sort((a,b)=>{let x=a[sortK],y=b[sortK];if(sortK==='best_p'){x=x==null?9:x;y=y==null?9:y}if(typeof x==='string')return sortDir*x.localeCompare(y);return sortDir*((x>y)-(x<y));});
  const tb=document.getElementById('tbody');tb.innerHTML='';
  rows.forEach(r=>{const tr=document.createElement('tr');tr.className='row'+(r.passed?' sig':'');const dir=r.clusters.find(c=>c.passes);
    tr.innerHTML=COLS.map(([k])=>{let v=r[k];
      if(k==='outcome_label')return `<td><b>${v}</b></td>`;
      if(k==='best_p')return `<td>${v!=null?fmtP(v)+' '+(dir?dirBadge(dir.dir):''):(dir?dirBadge(dir.dir):'<span class="tag">—</span>')}</td>`;
      if(k==='passed')return `<td>${r.passed?'<span class="badge b-sig">✓</span>':'<span class="badge b-ns">·</span>'}</td>`;
      return `<td>${v==null||v===''?'—':v}</td>`;}).join('');
    tr.onclick=()=>{const nx=tr.nextSibling;if(nx&&nx.classList&&nx.classList.contains('detail-row')){nx.remove();return}
      document.querySelectorAll('.detail-row').forEach(e=>e.remove());const dr=document.createElement('tr');dr.className='detail-row';dr.innerHTML=detail(r);tr.after(dr);};
    tb.appendChild(tr);});
  document.getElementById('count').textContent=`${rows.length} of ${DATA.length} analyses · ${rows.filter(r=>r.passed).length} FWE-significant`;
}
function boot(){
  buildFilters();COLS=buildHeader();
  document.getElementById('exptitle').textContent=META.title||'Results';
  const dims=[`${DATA.length} analyses`,`${uniq('outcome_label').length} outcomes`,`${uniq('tract_label').length} tracts`,`${uniq('metric').length} metrics`,`${NN} nodes`,...(HAS_HEMI?['hemispheres detected']:[]),...GROUPS.map(g=>`${uniq(g).length} ${g}`)];
  document.getElementById('expsub').textContent=META.sub||dims.join(' · ');
  document.getElementById('explorer').style.display='';render();
  document.getElementById('explorer').scrollIntoView({behavior:'smooth',block:'start'});
}
function showMsg(m,ok){const e=document.getElementById('loaderr');e.className=ok?'ok':'loaderr';e.textContent=m;e.style.display=m?'':'none';}
function loadText(text,name){
  try{META=Object.assign({},urlMeta());
    if(/^\s*[\[{]/.test(text)){DATA=fromJSON(JSON.parse(text));}
    else{DATA=fromLong(parseCSV(text));}
    showMsg(`Loaded ${name||'data'}: ${DATA.length} analyses${GROUPS.length?' · grouping columns: '+GROUPS.join(', '):''}${HAS_HEMI?' · hemisphere detected':' · no hemisphere column (laterality hidden)'}`,true);boot();
  }catch(x){showMsg('Could not load: '+x.message,false);}
}
function urlMeta(){const u=new URLSearchParams(location.search);const m={};['title','sub','method','node0','node1','n_perms','scripts_note'].forEach(k=>{if(u.get(k))m[k]=u.get(k)});return m;}
function readFile(f){const rd=new FileReader();rd.onload=()=>loadText(rd.result,f.name);rd.readAsText(f);}
document.getElementById('file').onchange=e=>{if(e.target.files[0])readFile(e.target.files[0]);};
const dz=document.getElementById('drop');
['dragover','dragenter'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('over');}));
['dragleave','dragend'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('over');}));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('over');if(e.dataTransfer.files[0])readFile(e.dataTransfer.files[0]);});
document.getElementById('loadex').onclick=e=>{e.preventDefault();fetch('example_results_long.csv').then(r=>r.text()).then(t=>loadText(t,'example dataset')).catch(()=>showMsg('Could not load the example.',false));};
const _durl=new URLSearchParams(location.search).get('data');
if(_durl)fetch(_durl).then(r=>r.text()).then(t=>loadText(t,_durl)).catch(()=>showMsg('Could not load '+_durl,false));
</script>"""

DOC = """<div class="doc">
<b>Fit your data to the sample CSV.</b> One row per node. Six required columns — <code>outcome, tract, metric, node, t, p</code> — everything else optional. Your permutation output already has the node-wise <code>t</code> and <code>p</code>; you just stack your analyses into one file and label each row with its outcome, tract, and metric. Column names are case-insensitive (<code>Node</code>, <code>t_value</code>, <code>p_value</code> etc. are fine as-is).
<br><br><b>Columns:</b>
<table><thead><tr><th>Column</th><th>Required?</th><th>Meaning</th></tr></thead><tbody>
<tr><td><code>outcome</code></td><td>yes</td><td>what was predicted (e.g. SOCIAL_dprime)</td></tr>
<tr><td><code>tract</code></td><td>yes</td><td>tract label — any number of tracts</td></tr>
<tr><td><code>metric</code></td><td>yes</td><td>the along-tract measure (FA, NDI, MD …)</td></tr>
<tr><td><code>node</code></td><td>yes</td><td>0-based node index — any node count</td></tr>
<tr><td><code>t</code> / <code>t_value</code>, <code>p</code> / <code>p_value</code></td><td>yes</td><td>that node's statistic and uncorrected p, straight from <code>_nodewise.csv</code></td></tr>
<tr><td><code>hemisphere</code></td><td>no</td><td>L / R — if present, the laterality bar and the L-vs-R overlap panel appear; if absent they are hidden</td></tr>
<tr><td><code>N</code>, <code>covariates</code></td><td>no</td><td>sample size and the controls in the model (any text) — shown per analysis</td></tr>
<tr><td><code>extent_threshold</code></td><td>no</td><td>the permutation cluster-size threshold (<code>ExtentThresholdNodes</code>); clusters at least this long are marked FWE-significant</td></tr>
<tr><td><code>cluster_p</code>, <code>passed</code></td><td>no</td><td>your FWE cluster p and verdict (1/0, TRUE/FALSE)</td></tr>
<tr><td><b>any other column</b></td><td>—</td><td><b>becomes a filter</b> (family, condition, cohort, site, task …). Single-valued columns are auto-hidden. <code>Estimate</code> and <code>df</code> are ignored.</td></tr>
</tbody></table>
Everything else is derived here in the browser from your node rows: sig-node counts, clusters (contiguous p&lt;.05 runs), max cluster, laterality and the hemispheric-overlap panel. You never compute cluster stats yourself. Nothing is uploaded.
<br>Optional page labels via URL: <code>?title=…&amp;method=Freedman–Lane&amp;node0=start&amp;node1=end&amp;n_perms=5000</code>, or <code>?data=URL</code> to auto-load a hosted CSV.
</div>"""

TEMPLATE = """outcome,tract,metric,node,t,p,hemisphere,N,covariates,extent_threshold,cluster_p,passed
memory_score,uncinate,FA,0,2.040,0.0472,L,52,"age, sex, motion",26,0.0032,1
memory_score,uncinate,FA,1,2.057,0.0455,L,52,"age, sex, motion",26,0.0032,1
...   one row per node, then the next tract / metric / outcome"""

BODY = f"""<header>
<h1>Node-wise Tract Explorer</h1>
<div class="sub">A reusable, in-browser viewer for along-tract (node-wise) statistical results. Drop in a results file and browse it: filter by any dimension in your data, click a row for the node profile, clusters, laterality, and stats. Nothing is uploaded — files are parsed locally in your browser.</div>
</header>
<div class="wrap">
<div class="section" id="loader"><h2>Load results</h2>
<div id="drop" class="drop">Drop your results <b>.csv</b> here — or <label class="flink">choose a file<input type="file" id="file" accept=".csv,text/csv,.json" hidden></label></div>
<div style="margin-top:10px;font-size:13px;color:var(--mut)">New here? <a href="sample_results.csv" download class="flink" style="font-weight:600">Download the sample CSV</a> to see exactly how to structure yours (a small real example: 2 outcomes × 2 tracts × 2 metrics, 100 nodes) &nbsp;·&nbsp; or <a href="#" id="loadex" class="flink">load a full example dataset</a> to see the explorer populated.</div>
<div id="loaderr" class="loaderr" style="display:none"></div>
<details style="margin-top:14px" open><summary style="cursor:pointer;color:var(--accent);font-weight:600;font-size:13px">Data format</summary>
{DOC}
<div class="script" style="margin-top:10px">{TEMPLATE}</div>
<div class="tag" style="margin-top:6px"><a href="sample_results.csv" download style="color:var(--accent)">sample_results.csv</a> (small, copy this structure) · <a href="example_results_long.csv" style="color:var(--accent)">example_results_long.csv</a> (a full example dataset)</div>
</details>
</div>

<div class="section" id="explorer" style="display:none"><h2 id="exptitle">Results</h2>
<div id="expsub" class="sub" style="margin-bottom:12px"></div>
<div class="controls" id="filters"></div>
<table id="tbl"><thead id="thead"></thead><tbody id="tbody"></tbody></table>
<div class="legend">FWE = cluster passes the permutation extent threshold (from your <code>extent_threshold</code> / <code>passed</code> columns). Direction: <span class="badge b-pos">Positive</span> higher metric → higher outcome · <span class="badge b-neg">Negative</span> higher metric → lower outcome. Node values are whatever statistic you supplied in <code>t</code> (partial-regression t recommended). Where hemispheres exist, the detail view stacks L and R aligned by node; nodes significant on <span style="color:#4ade80">both</span> sides are green.</div>
</div>
</div>"""

html = f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Node-wise Tract Explorer</title>
{css}</head><body>
{BODY}
{JS}</body></html>'''
(OUT / "index.html").write_text(html)
print(f"wrote index.html ({len(html)} bytes)")
