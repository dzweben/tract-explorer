#!/usr/bin/env python3
"""
build.py — assemble the single-file index.html from the three source files.

    src/index.template.html   the page skeleton   (has {{CSS}} and {{JS}} markers)
    src/explorer.css          the styles
    src/explorer.js           the application logic

Why a build step at all?  So the DEPLOYED page is one self-contained file
(works from GitHub Pages, a file:// double-click, or any static host with no
external requests), while the SOURCE stays split into readable, commented
files you can actually edit.

Usage:
    python build.py            # writes ./index.html

No dependencies beyond the Python standard library. To change the app, edit
the files in src/ and re-run this. If you'd rather not build at all, you can
also just open src/index.template.html-style markup with <link>/<script src=>
tags pointing at the css/js — the build is a convenience, not a requirement.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

template = (SRC / "index.template.html").read_text()
css = (SRC / "explorer.css").read_text()
js = (SRC / "explorer.js").read_text()

# The markers sit on their own lines inside <style>…</style> and <script>…</script>.
html = template.replace("{{CSS}}", css.strip()).replace("{{JS}}", js.strip())

# Guard: a marker left behind means the template changed and the build would ship broken.
for marker in ("{{CSS}}", "{{JS}}"):
    assert marker not in html, f"unreplaced marker {marker} in template"

out = ROOT / "index.html"
out.write_text(html)
print(f"wrote {out.name} ({len(html):,} bytes)")
