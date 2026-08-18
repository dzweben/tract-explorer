# Node-wise Tract Explorer

An interactive, in-browser viewer for **node-wise (along-tract) statistical results** — the kind produced by along-tract profiling (AFQ / pyAFQ / dipy-style tract profiles) followed by a per-node regression and cluster-based correction.

Drop in a results CSV and get: a filterable table of every analysis, a node-wise profile plot for each one (per-node statistic with significant nodes and clusters highlighted), cluster stats, and — if your tracts are lateralized — a laterality bar and a left/right hemispheric-overlap panel.

**Nothing is uploaded.** The file is parsed locally in your browser. It's a single static HTML page.

**Live:** https://dzweben.github.io/tract-explorer/

## Use it

1. Open the page.
2. Drop your `results.csv` on it (or *choose a file*, or load via URL: `?data=https://…/results.csv`).
3. Browse. Filters build themselves from your data.

## Data format — fit your data to the sample CSV

**One row per node.** Six required columns; everything else optional.

| column | required | meaning |
|---|---|---|
| `outcome` | ✓ | the dependent variable (label) |
| `tract` | ✓ | the tract / bundle (label) |
| `metric` | ✓ | the microstructure measure (FA, NDI, MD, …) |
| `node` | ✓ | node index along the tract (0-based; any count) |
| `t` | ✓ | the per-node statistic (t by default; any statistic works) |
| `p` | ✓ | the per-node p-value |
| `hemisphere` | | `L` / `R` — enables laterality + hemispheric overlap |
| `N` | | subjects in that analysis |
| `covariates` | | comma-separated string, shown in the detail panel |
| `extent_threshold` | | cluster-size threshold (nodes) — clusters ≥ this pass FWE |
| `cluster_p` | | the surviving cluster's corrected p |
| `passed` | | 1/0 — did an FWE cluster survive |
| *anything else* | | **becomes a filter** (family, condition, cohort, site, …) |

Column names are case-insensitive, and common aliases work as-is (`Node`, `t_value`, `p_value`, `N_subjects`, `PassExtentThreshold`, …).

You compute your own per-node statistics however you like; the viewer **derives** everything else from the node rows — significant nodes, contiguous clusters, max cluster, laterality, node count.

Files in this repo:
- [`sample_results.csv`](sample_results.csv) — a small real example (2 outcomes × 2 tracts × 2 metrics, 100 nodes). Copy this structure.
- [`example_results_long.csv`](example_results_long.csv) — a full example dataset (128 analyses).

## Optional page labels

Via URL: `?title=My%20study&method=Freedman–Lane&node0=start&node1=end&n_perms=5000`.

## Extra grouping columns

Any column that isn't one of the reserved ones above is treated as a grouping dimension: it becomes a filter dropdown, a table column, and a field in the detail panel. Add as many as you want (`family`, `condition`, `cohort`, `site`, `task`, …); a column with only one value shows in the table but is hidden as a filter.

## How it's built (and how to adapt it)

The source is split into three readable, heavily-commented files in [`src/`](src/); `index.html` is just the three inlined into one self-contained page.

| file | what it is |
|---|---|
| [`src/explorer.js`](src/explorer.js) | **the whole app**, in 8 numbered sections: CSV parsing → data model (derives clusters, laterality) → filters → rendering (SVG node plots, detail panel, table) → loading. Read top-to-bottom. |
| [`src/explorer.css`](src/explorer.css) | the styles; theme is a handful of CSS variables in `:root` |
| [`src/index.template.html`](src/index.template.html) | the page skeleton with `{{CSS}}` / `{{JS}}` markers; the element ids the JS relies on are listed at the top |
| [`build.py`](build.py) | assembles the three into `index.html`. Standard library only: `python build.py` |

**To incorporate it into your own site**, the contract is the data model in `src/explorer.js` §3 (`fromLong` → `analysis` objects). If you can produce those objects, every UI section below it just works — the rendering never touches raw CSV. Re-theme by editing the `:root` variables. Rename or restyle the page freely, just keep the element ids the JS looks up (listed at the top of the template).

## License

MIT
