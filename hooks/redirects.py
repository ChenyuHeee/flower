"""Emit meta-refresh stubs for the old flat documentation URLs.

The previous site served /start/, /workflow/, /case-ht001/ … at the site root.
The restructured site serves them under /getting-started/, /guide/, /cases/,
and mkdocs-static-i18n strips the default-language folder from the output path.

mkdocs-redirects cannot be used here: it resolves its targets from the source
tree (docs/zh/guide/workflow.md -> /zh/guide/workflow/) before the i18n plugin
rewrites dest paths, so every stub it writes points at a /zh/ prefix that is
never built. This hook runs after the build and writes the stubs against the
final URLs instead.
"""

from __future__ import annotations

import os
from pathlib import Path

# old flat path (one segment) -> new path, both relative to the site root
REDIRECTS = {
    "start": "getting-started/quickstart",
    "workflow": "guide/workflow",
    "clarify": "guide/clarify",
    "goal": "guide/goal",
    "continuity": "guide/continuity",
    "handoff": "guide/handoff",
    "interaction": "guide/interaction",
    "case-ht001": "cases/ht001",
    "case-ht002": "cases/ht002",
}

_TEMPLATE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Redirecting…</title>
<link rel="canonical" href="{canonical}">
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url={target}">
<script>window.location.replace({target_js} + window.location.hash);</script>
</head>
<body>
Redirecting to <a href="{target}">{target}</a>…
</body>
</html>
"""


# mkdocs-static-i18n triggers one full build per locale, so this hook fires
# once per language. The stubs it writes are identical every time; log once.
_LOGGED = False


def on_post_build(config, **kwargs) -> None:
    global _LOGGED
    site_dir = Path(config["site_dir"])
    site_url = (config.get("site_url") or "").rstrip("/")
    written, skipped = 0, []

    for old, new in REDIRECTS.items():
        destination = site_dir / new / "index.html"
        if not destination.exists():
            skipped.append(f"{old} -> {new}")
            continue

        stub = site_dir / old / "index.html"
        stub.parent.mkdir(parents=True, exist_ok=True)
        # relative, so the stubs also work when the site is served from a
        # subdirectory or opened straight off the filesystem
        target = os.path.relpath(destination.parent, stub.parent).replace(os.sep, "/") + "/"
        stub.write_text(
            _TEMPLATE.format(
                target=target,
                target_js=f'"{target}"',
                canonical=f"{site_url}/{new}/" if site_url else target,
            ),
            encoding="utf-8",
        )
        written += 1

    if not _LOGGED:
        _LOGGED = True
        print(f"INFO    -  redirects hook: wrote {written} legacy URL stub(s)")
        for entry in skipped:
            print(f"WARNING -  redirects hook: target missing, skipped {entry}")
