/* =============================================================================
   Node-wise Tract Explorer — application logic
   =============================================================================

   WHAT THIS FILE DOES
   -------------------
   Turns a long-format results CSV (one row per node) into an interactive
   explorer: a filterable table of every analysis, and a click-to-open detail
   panel per analysis with the node-wise profile plot, cluster stats, and (if
   the tracts are lateralized) a laterality bar + left/right overlap panel.

   Everything runs in the browser. Nothing is uploaded anywhere.

   HOW TO READ THIS FILE
   ---------------------
   It's in dependency order, section by section:

     1. STATE + HELPERS      the few globals, and tiny utilities
     2. CSV PARSING          text -> array of {column: value} row objects
     3. DATA MODEL           rows -> "analyses" (the core; derives clusters etc.)
     4. LATERALITY           pairing each analysis with its L/R sibling
     5. JSON INPUT           optional alternative input shape
     6. UI: FILTERS          dropdowns discovered from the data
     7. UI: RENDERING        the SVG node plots, the detail panel, the table
     8. BOOT + LOADING       drag/drop, file picker, ?data= URL, example button

   To adapt it: the DATA MODEL (section 3) is the contract — if you can turn
   your results into the `analysis` objects it produces, every UI section
   below just works. The UI never touches raw CSV.

   THE INPUT CONTRACT (see README for the full table)
   --------------------------------------------------
   One row per node. Required columns:  outcome, tract, metric, node, t, p
   Optional per-analysis columns:       hemisphere, N, covariates,
                                        extent_threshold, cluster_p, passed
   ANY OTHER column = a grouping dimension -> becomes a filter dropdown.
   Column names are case-insensitive; common aliases are accepted (see ALIAS).
   ============================================================================= */


/* =============================================================================
   1. STATE + HELPERS
   ============================================================================= */

// The whole app state. Deliberately tiny.
let DATA = [];        // array of "analysis" objects (see makeAnalysis below)
let META = {};        // optional page labels: title, sub, method, node0, node1, n_perms, scripts_note
let GROUPS = [];      // names of the user's extra grouping columns (family, condition, cohort ...)
let NN = 100;         // node count (derived from the data; 100 is only a placeholder)
let HAS_HEMI = false; // did the data include a hemisphere column with L/R?

// Column names that have a fixed meaning. Anything NOT in this list (and not
// an alias of one) is treated as a user grouping dimension.
const RESERVED = ['outcome', 'tract', 'metric', 'node', 't', 'p', 'hemisphere',
                  'n', 'covariates', 'extent_threshold', 'cluster_p', 'passed', 'dir', 'id'];

// tiny utilities
const norm   = s => String(s ?? '').trim();                       // safe string
const num    = v => { const x = parseFloat(v); return isNaN(x) ? null : x; }; // safe number or null
const truthy = v => ['1', 'true', 'yes', 'y', 't', 'pass', 'sig'].includes(norm(v).toLowerCase()); // "did it pass?"


/* =============================================================================
   2. CSV PARSING
   -----------------------------------------------------------------------------
   A small, dependency-free CSV parser. Handles quoted fields, embedded commas,
   escaped quotes (""), and \r\n line endings — enough for anything pandas / R
   writes. Returns an array of row objects keyed by the header names.
   ============================================================================= */
function parseCSV(text) {
  const rows = []; let row = [], cur = '', inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQuotes = false; }
      else cur += c;
    }
    else if (c === '"') inQuotes = true;
    else if (c === ',') { row.push(cur); cur = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;          // treat \r\n as one newline
      row.push(cur); rows.push(row); row = []; cur = '';
    }
    else cur += c;
  }
  if (cur !== '' || row.length) { row.push(cur); rows.push(row); } // last line without newline
  const nonempty = rows.filter(r => r.some(x => norm(x) !== ''));
  if (nonempty.length < 2) throw new Error('CSV has no data rows.');
  const header = nonempty[0].map(h => norm(h));
  return nonempty.slice(1).map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}


/* =============================================================================
   3. DATA MODEL  (the core)
   -----------------------------------------------------------------------------
   fromLong(rows) groups the node rows into analyses and DERIVES everything the
   UI needs. Users only supply per-node t and p; we compute:
     - the node-wise t/p arrays (indexed by node)
     - which nodes are significant (p < .05, uncorrected)
     - contiguous clusters of significant nodes, with size / direction / peak
     - the max cluster size
     - which clusters "pass" family-wise correction (see FWE rules below)
   ============================================================================= */

// Accepted names for each reserved column, so people's existing headers work
// as-is (e.g. an R script's `t_value` / `p_value` / `PassExtentThreshold`).
const ALIAS = {
  node:             ['node'],
  t:                ['t', 't_value', 'tvalue', 'tstat', 'statistic'],
  p:                ['p', 'p_value', 'pvalue', 'pval'],
  n:                ['n', 'n_subjects', 'nsubjects'],
  covariates:       ['covariates', 'covariate'],
  extent_threshold: ['extent_threshold', 'extentthresholdnodes', 'extent_thr'],
  cluster_p:        ['cluster_p', 'clusterpvalue', 'cluster_pvalue', 'fwe_p'],
  passed:           ['passed', 'passextentthreshold', 'fwe', 'significant', 'sig'],
  outcome:          ['outcome', 'outcome_label', 'dv'],
  tract:            ['tract', 'tract_label', 'bundle'],
  metric:           ['metric', 'measure'],
  hemisphere:       ['hemisphere', 'hemi', 'side'],
};

function fromLong(rows) {
  const cols = Object.keys(rows[0]);

  // Build a case-insensitive lookup: reserved key -> the actual column name in this file.
  const lc = {};
  cols.forEach(c => {
    const l = c.toLowerCase(); lc[l] = c;
    for (const k in ALIAS) if (ALIAS[k].includes(l)) lc[k] = c;
  });
  const aliasAll = new Set(Object.values(ALIAS).flat());

  // Validate the six required columns.
  const required = ['outcome', 'tract', 'metric', 'node', 't', 'p'];
  const missing = required.filter(k => !(k in lc));
  if (missing.length) throw new Error('Missing required column(s): ' + missing.join(', ') +
    '.\nRequired: outcome, tract, metric, node, t, p  (one row per node).');
  const C = k => lc[k];   // C('t') -> "t_value" (whatever the file called it)

  HAS_HEMI = ('hemisphere' in lc);

  // Everything not reserved / aliased = a user grouping dimension.
  // (estimate/df/clusterid are common per-node extras from R output; ignore them.)
  GROUPS = cols.filter(c => {
    const l = c.toLowerCase();
    return !aliasAll.has(l) && !RESERVED.includes(l) && !['estimate', 'df', 'clusterid'].includes(l);
  });

  // An "analysis" = one outcome x tract x metric (x hemisphere x every group value).
  // Group the node rows by that key.
  const keyOf = r => [r[C('outcome')], r[C('tract')], r[C('metric')],
                      HAS_HEMI ? r[C('hemisphere')] : '', ...GROUPS.map(g => r[g])].map(norm).join('||');
  const by = new Map();
  rows.forEach(r => { const k = keyOf(r); if (!by.has(k)) by.set(k, []); by.get(k).push(r); });

  const out = [];
  by.forEach((rs, key) => out.push(makeAnalysis(rs, key, C, lc)));

  NN = Math.max(...out.map(a => a.tvals.length));
  if (HAS_HEMI) attachLaterality(out);
  return out;
}

// Build one analysis object from its node rows.
function makeAnalysis(rs, key, C, lc) {
  rs.sort((a, b) => num(a[C('node')]) - num(b[C('node')]));
  const nn = Math.max(...rs.map(r => num(r[C('node')]))) + 1;   // node count = max index + 1

  // per-node arrays, indexed by node
  const tv = new Array(nn).fill(null), pv = new Array(nn).fill(null);
  rs.forEach(r => { const i = num(r[C('node')]); tv[i] = num(r[C('t')]); pv[i] = num(r[C('p')]); });

  const first = rs[0];   // per-analysis fields are the same on every row; read the first
  const a = {
    id: key,
    outcome_label: norm(first[C('outcome')]),
    tract_label:   norm(first[C('tract')]),
    metric:        norm(first[C('metric')]),
    hemisphere:    HAS_HEMI ? norm(first[C('hemisphere')]).toUpperCase() : '',
    tvals: tv, pvals: pv,
    N:                ('n' in lc)                ? num(first[C('n')])                : null,
    covariates:       ('covariates' in lc)       ? norm(first[C('covariates')])      : '',
    extent_threshold: ('extent_threshold' in lc) ? num(first[C('extent_threshold')]) : null,
    best_p:           ('cluster_p' in lc)        ? num(first[C('cluster_p')])        : null,
    passed:           ('passed' in lc)           ? truthy(first[C('passed')])        : null,
  };
  GROUPS.forEach(g => a[g] = norm(first[g]));

  // --- derive significance + clusters ---
  const sig = pv.map(x => x != null && x < 0.05);          // node-wise significant (uncorrected)
  a.n_sig_nodes   = sig.filter(Boolean).length;
  a.sig_node_list = sig.map((s, i) => s ? i : -1).filter(i => i >= 0);

  // Contiguous runs of significant nodes = clusters.
  a.clusters = []; let start = null;
  for (let i = 0; i <= nn; i++) {
    const on = i < nn && sig[i];
    if (on && start == null) start = i;
    else if (!on && start != null) {
      const end = i - 1;
      const ts = tv.slice(start, end + 1).map(x => x ?? 0);
      const meanT = ts.reduce((u, v) => u + v, 0) / ts.length;
      const peakIdx = ts.map(Math.abs).indexOf(Math.max(...ts.map(Math.abs)));
      a.clusters.push({
        start, end, size: end - start + 1,
        dir: meanT >= 0 ? 'Positive' : 'Negative',    // direction = sign of the mean t
        mean_t: +meanT.toFixed(2),
        max_abs_t: +ts[peakIdx].toFixed(2), max_abs_t_node: start + peakIdx,
        p: null, passes: false,
      });
      start = null;
    }
  }
  a.obs_max_cluster = a.clusters.length ? Math.max(...a.clusters.map(c => c.size)) : 0;

  // --- FWE rules (which clusters count as corrected-significant) ---
  // 1) If the file gives an extent_threshold: a cluster passes if size >= threshold.
  // 2) Else if the file says passed=1: flag the largest cluster as the survivor.
  // 3) Else: nothing passes (we never invent significance).
  if (a.extent_threshold != null) {
    a.clusters.forEach(c => c.passes = c.size >= a.extent_threshold);
    a.passed = a.clusters.some(c => c.passes);
  } else if (a.passed === true && a.clusters.length) {
    const big = a.clusters.reduce((x, y) => y.size > x.size ? y : x);
    big.passes = true; big.p = a.best_p;
  } else if (a.passed == null) a.passed = false;
  if (a.best_p != null) a.clusters.filter(c => c.passes).forEach(c => c.p = a.best_p);

  // fields the UI expects to exist (kept for the optional JSON input path)
  a.n_perms = META.n_perms || null; a.dropped = null;
  a.family = a.family || ''; a.condition = a.condition || ''; a.tract_type = a.tract_type || '';
  return a;
}


/* =============================================================================
   4. LATERALITY  (only when a hemisphere column exists)
   -----------------------------------------------------------------------------
   Each analysis is paired with its opposite-hemisphere "sibling": same outcome,
   metric, and group values, and a tract label that differs only by side
   (e.g. "left_uncinate" <-> "right_uncinate"). From the pair we compute how
   many significant nodes fall on each side, and which nodes are significant
   on BOTH sides (the overlap shown in green in the L/R panel).
   ============================================================================= */

// strip side words so "left uncinate" and "right uncinate" compare equal
function tractBase(t) {
  return norm(t).replace(/\b(left|right|L|R|lh|rh)\b/ig, '').replace(/[_\-\s]+/g, ' ').trim().toLowerCase();
}
function sibOf(a, pool) {
  pool = pool || DATA;
  return pool.find(x => x !== a && x.outcome_label === a.outcome_label && x.metric === a.metric &&
    x.hemisphere && x.hemisphere !== a.hemisphere && tractBase(x.tract_label) === tractBase(a.tract_label) &&
    GROUPS.every(g => x[g] === a[g]));
}
function attachLaterality(analyses) {
  analyses.forEach(a => {
    const sib = sibOf(a, analyses);
    const L = a.hemisphere === 'L' ? a : sib, R = a.hemisphere === 'R' ? a : sib;
    const Ls = L ? L.n_sig_nodes : 0, Rs = R ? R.n_sig_nodes : 0, tot = Ls + Rs;
    const overlap = (L && R) ? L.sig_node_list.filter(i => R.sig_node_list.includes(i)) : [];
    a.laterality = { L_sig: Ls, R_sig: Rs,
      pct_left: tot ? +(100 * Ls / tot).toFixed(0) : 0, pct_right: tot ? +(100 * Rs / tot).toFixed(0) : 0,
      overlap_nodes: overlap };
  });
}


/* =============================================================================
   5. JSON INPUT  (optional)
   -----------------------------------------------------------------------------
   You can also feed the viewer already-built analysis objects as JSON — either
   an array, or {"meta": {...}, "results": [...]}. Same fields as section 3
   produces. Most people should just use the CSV.
   ============================================================================= */
function fromJSON(o) {
  const arr = Array.isArray(o) ? o : (o.results || []);
  if (!arr.length) throw new Error('No result records found. Expected an array of results, or {"meta":..,"results":[..]}.');
  META = Object.assign({}, META, Array.isArray(o) ? {} : (o.meta || {}));
  HAS_HEMI = arr.some(a => a.hemisphere === 'L' || a.hemisphere === 'R');
  const std = ['id', 'outcome', 'outcome_label', 'tract', 'tract_label', 'hemisphere', 'metric', 'N', 'dropped',
    'covariates', 'n_sig_nodes', 'obs_max_cluster', 'extent_threshold', 'n_passing', 'n_perms', 'passed', 'best_p',
    'clusters', 'sig_node_list', 'tvals', 'pvals', 'laterality'];
  GROUPS = Object.keys(arr[0]).filter(k => !std.includes(k) && typeof arr[0][k] !== 'object');
  NN = Math.max(...arr.map(a => (a.tvals || []).length));
  return arr;
}


/* =============================================================================
   6. UI: FILTERS
   -----------------------------------------------------------------------------
   Filter dropdowns are DISCOVERED from the data: tract, metric, hemisphere (if
   present), outcome, then every user grouping column. A dimension with only one
   value gets no dropdown (nothing to filter). Plus a "Show" selector and search.
   ============================================================================= */
function uniq(k) { return [...new Set(DATA.map(r => r[k]).filter(v => v != null && v !== ''))].sort(); }

function buildFilters() {
  const host = document.getElementById('filters'); host.innerHTML = '';
  const dims = [['tract_label', 'Tract'], ['metric', 'Metric'],
                ...(HAS_HEMI ? [['hemisphere', 'Hemisphere']] : []),
                ['outcome_label', 'Outcome'],
                ...GROUPS.map(g => [g, g])];                          // user columns, labeled by their own name
  dims.forEach(([k, label]) => {
    const vals = uniq(k); if (vals.length < 2) return;                 // single-valued -> no dropdown
    const s = document.createElement('span');
    s.innerHTML = `<label>${label}</label><select data-k="${k}"><option value="">All</option>${vals.map(v => `<option>${v}</option>`).join('')}</select>`;
    host.appendChild(s);
  });
  const sig = document.createElement('span');
  sig.innerHTML = `<label>Show</label><select id="f_sig"><option value="all">All</option><option value="sig">FWE-significant only</option><option value="trend">≥5 sig nodes</option></select>`;
  host.appendChild(sig);
  const q = document.createElement('input'); q.id = 'f_search'; q.placeholder = 'search…'; q.style.minWidth = '130px'; host.appendChild(q);
  const c = document.createElement('span'); c.className = 'count'; c.id = 'count'; host.appendChild(c);
  host.querySelectorAll('select,input').forEach(el => el.oninput = render);
}

// Does analysis r survive the current filter settings?
function passFilters(r) {
  for (const s of document.querySelectorAll('#filters select[data-k]')) {
    if (s.value && norm(r[s.dataset.k]) !== s.value) return false;
  }
  const sg = document.getElementById('f_sig').value, q = document.getElementById('f_search').value.toLowerCase();
  if (sg === 'sig' && !r.passed) return false;
  if (sg === 'trend' && r.n_sig_nodes < 5) return false;
  if (q && !Object.values(r).filter(v => typeof v === 'string').join(' ').toLowerCase().includes(q)) return false;
  return true;
}


/* =============================================================================
   7. UI: RENDERING
   ============================================================================= */
let sortK = 'best_p', sortDir = 1;   // table sort state
const dirBadge = d => d === 'Positive' ? '<span class="badge b-pos">Positive</span>' : '<span class="badge b-neg">Negative</span>';
const fmtP = p => p == null ? '—' : (p === 0 ? '<1/n_perm' : p);   // a permutation p of 0 means "< 1/n_perms"

// The node-wise profile: one bar per node = that node's statistic (t by default).
// Colored bar = p<.05 at that node; green shading = a cluster that passed FWE.
// NOTE: this is a profile of "how much does the metric HERE predict the outcome",
// across subjects, node by node — it is not a picture of the tract's shape.
function nodeViz(r, H = 90) {
  const W = 560, pad = 18, n = r.tvals.length;
  const ts = r.tvals.map(x => x == null ? 0 : x);
  const mx = Math.max(3, ...ts.map(Math.abs));       // y-scale: at least ±3
  const bw = (W - 2 * pad) / n;
  let bars = '';
  for (let i = 0; i < n; i++) {
    const t = ts[i], sig = r.pvals[i] != null && r.pvals[i] < 0.05;
    const h = Math.abs(t) / mx * (H / 2 - 8), y = t >= 0 ? (H / 2 - h) : (H / 2);
    const col = sig ? (t >= 0 ? '#f4664a' : '#3b82f6') : '#39404f';   // sig: orange(+)/blue(−); else grey
    bars += `<rect x="${pad + i * bw}" y="${y}" width="${Math.max(bw - 0.4, 0.6)}" height="${h}" fill="${col}"><title>node ${i}: t=${t}</title></rect>`;
  }
  let shade = '';
  r.clusters.forEach(c => { if (c.passes) shade += `<rect x="${pad + c.start * bw}" y="4" width="${(c.end - c.start + 1) * bw}" height="${H - 8}" fill="rgba(34,197,94,.10)" stroke="rgba(34,197,94,.4)"/>`; });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">${shade}<line x1="${pad}" y1="${H / 2}" x2="${W - pad}" y2="${H / 2}" stroke="#4a5163"/>${bars}
   <text x="${pad}" y="${H - 2}" fill="#6b7280" font-size="9">${META.node0 || 'node 0'}</text><text x="${W - pad}" y="${H - 2}" fill="#6b7280" font-size="9" text-anchor="end">${META.node1 || ('node ' + (n - 1))}</text></svg>`;
}

// A smaller profile used in the L/R overlap panel; nodes significant on BOTH sides are green.
function miniProfile(r, label, overlap) {
  const W = 560, H = 64, pad = 18, n = r ? r.tvals.length : NN;
  const ts = r ? r.tvals.map(x => x == null ? 0 : x) : new Array(n).fill(0);
  const mx = Math.max(3, ...ts.map(Math.abs)), bw = (W - 2 * pad) / n;
  let bars = '';
  for (let i = 0; i < n; i++) {
    const t = ts[i], sig = r && r.pvals[i] != null && r.pvals[i] < 0.05, ov = overlap.includes(i);
    const h = Math.abs(t) / mx * (H / 2 - 6), y = t >= 0 ? (H / 2 - h) : (H / 2);
    const col = ov && sig ? '#22c55e' : (sig ? (t >= 0 ? '#f4664a' : '#3b82f6') : '#39404f');
    bars += `<rect x="${pad + i * bw}" y="${y}" width="${Math.max(bw - 0.4, 0.6)}" height="${h}" fill="${col}"><title>node ${i}: t=${t}</title></rect>`;
  }
  let shade = '';
  if (r) r.clusters.forEach(c => { if (c.passes) shade += `<rect x="${pad + c.start * bw}" y="3" width="${(c.end - c.start + 1) * bw}" height="${H - 6}" fill="rgba(34,197,94,.08)" stroke="rgba(34,197,94,.35)"/>`; });
  return `<div style="display:flex;align-items:center;gap:8px"><div style="width:34px;font-size:11px;color:var(--mut);text-align:right">${label}</div><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">${shade}<line x1="${pad}" y1="${H / 2}" x2="${W - pad}" y2="${H / 2}" stroke="#4a5163"/>${bars}</svg></div>`;
}

// The expandable detail panel for one analysis (opens under its table row).
function detail(r) {
  const lat = r.laterality, sib = HAS_HEMI ? sibOf(r) : null;

  const clusters = r.clusters.length
    ? ('<table style="width:auto"><thead><tr><th>Nodes</th><th>Size</th><th>Dir</th><th>mean t</th><th>max|t|</th><th>@node</th><th>cluster p</th><th>FWE</th></tr></thead><tbody>' +
       r.clusters.map(c => `<tr><td>${c.start}–${c.end}</td><td>${c.size}</td><td>${dirBadge(c.dir)}</td><td>${c.mean_t}</td><td>${c.max_abs_t}</td><td>${c.max_abs_t_node}</td><td>${fmtP(c.p)}</td><td>${c.passes ? '<span class="badge b-sig">PASS</span>' : '<span class="badge b-ns">no</span>'}</td></tr>`).join('') +
       '</tbody></table>')
    : '<span class="tag">No contiguous clusters formed.</span>';

  const groupsKV = GROUPS.map(g => `<div class="k">${g}</div><div>${r[g] || '—'}</div>`).join('');

  let latHTML = '';
  if (HAS_HEMI && lat) {
    const Lp = lat.pct_left || 0, Rp = lat.pct_right || 0;
    const L = r.hemisphere === 'L' ? r : sib, R = r.hemisphere === 'R' ? r : sib;
    latHTML = `<h4 style="margin-top:16px">Laterality <span class="tag">(node-wise-sig nodes, L vs R)</span></h4>
     <div class="latbar"><div class="L" style="width:${Lp}%">L ${lat.L_sig} (${Lp}%)</div><div class="R" style="width:${Rp}%">R ${lat.R_sig} (${Rp}%)</div></div>
     <h4 style="margin-top:14px">Hemispheric node overlap <span class="tag">(same outcome + metric, L and R aligned by node)</span></h4>
     <div class="nodeviz">${miniProfile(L, 'L', lat.overlap_nodes || [])}${miniProfile(R, 'R', lat.overlap_nodes || [])}<div style="font-size:10px;color:var(--mut);text-align:right;padding-right:2px">${META.node0 || 'node 0'} ————— ${META.node1 || 'last node'}</div></div>
     <div class="tag" style="margin-top:6px">Overlapping significant nodes (sig on <b>both</b> sides): ${(lat.overlap_nodes && lat.overlap_nodes.length) ? '<span style="color:#4ade80">' + lat.overlap_nodes.join(', ') + '</span>' : 'none'}${sib ? '' : ' <i>(no opposite-hemisphere match found)</i>'}</div>`;
  }
  const cov  = r.covariates ? `<h4 style="margin-top:16px">Controlled for (covariates)</h4><div class="tag">${r.covariates}</div>` : '';
  const prov = META.scripts_note ? `<h4 style="margin-top:18px">Provenance</h4><div class="script">${META.scripts_note}</div>` : '';

  return `<td colspan="99" class="detail"><div class="dbox"><div class="dgrid"><div class="dcol">
    <h4>${r.outcome_label} &nbsp;·&nbsp; ${r.tract_label}${r.hemisphere ? ' (' + r.hemisphere + ')' : ''} &nbsp;·&nbsp; ${r.metric}</h4>
    <div class="kv">${groupsKV}<div class="k">Metric</div><div>${r.metric}</div>
     ${r.N != null ? `<div class="k">N</div><div>${r.N}</div>` : ''}
     ${r.n_perms ? `<div class="k">Permutations</div><div>${r.n_perms}${META.method ? ' (' + META.method + ')' : ''}</div>` : ''}
     <div class="k">Node-wise-significant nodes</div><div>${r.n_sig_nodes} / ${r.tvals.length}</div>
     <div class="k">Observed max cluster</div><div>${r.obs_max_cluster} nodes</div>
     ${r.extent_threshold != null ? `<div class="k">Extent threshold</div><div>${r.extent_threshold} nodes</div>` : ''}
     <div class="k">FWE verdict</div><div>${r.passed ? '<span class="badge b-sig">SIGNIFICANT</span>' + (r.best_p != null ? ' (cluster p=' + fmtP(r.best_p) + ')' : '') : '<span class="badge b-ns">n.s.</span>'}</div>
    </div>${cov}${latHTML}</div>
    <div class="dcol"><h4>Node-wise values <span class="tag">(each bar = a separate regression across subjects at that node; a profile along the tract, not its shape; green = FWE cluster; colored bars = p&lt;0.05)</span></h4><div class="nodeviz">${nodeViz(r)}</div>
     <h4 style="margin-top:14px">Clusters</h4>${clusters}
     <h4 style="margin-top:14px">Significant nodes (p&lt;0.05, uncorrected)</h4><div class="tag" style="line-height:1.6">${r.sig_node_list.length ? r.sig_node_list.join(', ') : 'none'}</div></div></div>${prov}</div></td>`;
}

// Table header: base columns + the user's grouping columns; N / threshold only if present.
let COLS = [];
function buildHeader() {
  const cols = [['outcome_label', 'Outcome'], ...GROUPS.map(g => [g, g]), ['tract_label', 'Tract'],
    ...(HAS_HEMI ? [['hemisphere', 'Hemi']] : []), ['metric', 'Metric'], ['N', 'N'], ['n_sig_nodes', 'Sig nodes'],
    ['obs_max_cluster', 'Max cluster'], ['extent_threshold', 'Thresh'], ['best_p', 'Cluster p'], ['passed', 'FWE']];
  const showN = DATA.some(r => r.N != null), showT = DATA.some(r => r.extent_threshold != null);
  const use = cols.filter(([k]) => !(k === 'N' && !showN) && !(k === 'extent_threshold' && !showT));
  document.getElementById('thead').innerHTML = '<tr>' + use.map(([k, l]) => `<th data-k="${k}">${l}</th>`).join('') + '</tr>';
  document.querySelectorAll('#thead th').forEach(th => th.onclick = () => { const k = th.dataset.k; if (sortK === k) sortDir *= -1; else { sortK = k; sortDir = 1; } render(); });
  return use;
}

// (Re)draw the table from DATA + current filters + sort. Click a row -> detail panel.
function render() {
  let rows = DATA.filter(passFilters);
  rows.sort((a, b) => { let x = a[sortK], y = b[sortK]; if (sortK === 'best_p') { x = x == null ? 9 : x; y = y == null ? 9 : y; } if (typeof x === 'string') return sortDir * x.localeCompare(y); return sortDir * ((x > y) - (x < y)); });
  const tb = document.getElementById('tbody'); tb.innerHTML = '';
  rows.forEach(r => {
    const tr = document.createElement('tr'); tr.className = 'row' + (r.passed ? ' sig' : '');
    const dir = r.clusters.find(c => c.passes);
    tr.innerHTML = COLS.map(([k]) => {
      let v = r[k];
      if (k === 'outcome_label') return `<td><b>${v}</b></td>`;
      if (k === 'best_p') return `<td>${v != null ? fmtP(v) + ' ' + (dir ? dirBadge(dir.dir) : '') : (dir ? dirBadge(dir.dir) : '<span class="tag">—</span>')}</td>`;
      if (k === 'passed') return `<td>${r.passed ? '<span class="badge b-sig">✓</span>' : '<span class="badge b-ns">·</span>'}</td>`;
      return `<td>${v == null || v === '' ? '—' : v}</td>`;
    }).join('');
    tr.onclick = () => {                                       // toggle the detail row under this row
      const nx = tr.nextSibling;
      if (nx && nx.classList && nx.classList.contains('detail-row')) { nx.remove(); return; }
      document.querySelectorAll('.detail-row').forEach(e => e.remove());
      const dr = document.createElement('tr'); dr.className = 'detail-row'; dr.innerHTML = detail(r); tr.after(dr);
    };
    tb.appendChild(tr);
  });
  document.getElementById('count').textContent = `${rows.length} of ${DATA.length} analyses · ${rows.filter(r => r.passed).length} FWE-significant`;
}


/* =============================================================================
   8. BOOT + LOADING
   -----------------------------------------------------------------------------
   Four ways in: drag-drop, the file picker, the example button, or ?data=URL.
   All of them end up in loadText(text) -> parse -> build the analyses -> boot().
   ============================================================================= */
function boot() {
  buildFilters(); COLS = buildHeader();
  document.getElementById('exptitle').textContent = META.title || 'Results';
  const dims = [`${DATA.length} analyses`, `${uniq('outcome_label').length} outcomes`, `${uniq('tract_label').length} tracts`,
    `${uniq('metric').length} metrics`, `${NN} nodes`, ...(HAS_HEMI ? ['hemispheres detected'] : []), ...GROUPS.map(g => `${uniq(g).length} ${g}`)];
  document.getElementById('expsub').textContent = META.sub || dims.join(' · ');
  document.getElementById('explorer').style.display = ''; render();
  document.getElementById('explorer').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function showMsg(m, ok) { const e = document.getElementById('loaderr'); e.className = ok ? 'ok' : 'loaderr'; e.textContent = m; e.style.display = m ? '' : 'none'; }

// Central entry point: raw text -> DATA. Accepts CSV, or JSON (detected by a leading [ or {).
function loadText(text, name) {
  try {
    META = Object.assign({}, urlMeta());
    if (/^\s*[\[{]/.test(text)) DATA = fromJSON(JSON.parse(text));
    else                        DATA = fromLong(parseCSV(text));
    showMsg(`Loaded ${name || 'data'}: ${DATA.length} analyses${GROUPS.length ? ' · grouping columns: ' + GROUPS.join(', ') : ''}${HAS_HEMI ? ' · hemisphere detected' : ' · no hemisphere column (laterality hidden)'}`, true);
    boot();
  } catch (x) { showMsg('Could not load: ' + x.message, false); }
}
// Optional page labels can be passed as URL query params (title, sub, method, node0, node1, n_perms, scripts_note).
function urlMeta() { const u = new URLSearchParams(location.search); const m = {}; ['title', 'sub', 'method', 'node0', 'node1', 'n_perms', 'scripts_note'].forEach(k => { if (u.get(k)) m[k] = u.get(k); }); return m; }
function readFile(f) { const rd = new FileReader(); rd.onload = () => loadText(rd.result, f.name); rd.readAsText(f); }

document.getElementById('file').onchange = e => { if (e.target.files[0]) readFile(e.target.files[0]); };
const dz = document.getElementById('drop');
['dragover', 'dragenter'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
['dragleave', 'dragend'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('over'); if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]); });
document.getElementById('loadex').onclick = e => { e.preventDefault(); fetch('example_results_long.csv').then(r => r.text()).then(t => loadText(t, 'example dataset')).catch(() => showMsg('Could not load the example.', false)); };
const _durl = new URLSearchParams(location.search).get('data');
if (_durl) fetch(_durl).then(r => r.text()).then(t => loadText(t, _durl)).catch(() => showMsg('Could not load ' + _durl, false));
