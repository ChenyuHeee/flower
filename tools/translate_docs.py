#!/usr/bin/env python3
"""Translate the Chinese documentation set into the other site locales.

One request per page, run concurrently against the gateway configured in
~/.claude/settings.json. Resumable: a page whose output already exists is
skipped unless --force, so a partial run can just be re-run.

The invariant that keeps nine locales linkable: anchors and link targets are
never translated. Only prose is. A heading keeps `{#协调者}` in every language,
and every link keeps `#协调者` too, so cross-page links resolve identically in
all locales without any per-locale anchor bookkeeping.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MODEL = "claude-opus-5"

LANGS = {
    "en": "English",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "es": "Spanish (Español)",
    "ru": "Russian (Русский)",
    "pt-BR": "Brazilian Portuguese (Português do Brasil)",
}

RULES = """You are translating the documentation of `flower`, a portable long-horizon agent
framework built on the Claude Agent SDK. The source is Chinese; it is precise, technical, and
deliberately unmarketed. Your translation must read as if it had been written natively in the
target language by the same engineer — not as a translation.

## Absolute rules — breaking any of these breaks the site build

1. **Never translate an anchor.** A heading written `## 目标看守 {#目标看守}` keeps `{#目标看守}`
   character for character; only the visible heading text is translated. Same for every
   `{#...}` in the document.
2. **Never translate a link target.** `[目标看守](../guide/goal.md#目标看守)` becomes
   `[Goal guard](../guide/goal.md#目标看守)` — the path and the `#fragment` are untouched, only
   the bracketed label changes. This is what keeps all locales cross-linkable.
3. **Never change a number.** Costs, durations, context sizes, percentages, line numbers,
   version numbers, byte counts — every digit stays exactly as written. `$171.62` stays
   `$171.62`; `10.4 小时` becomes `10.4 hours`, never `10 hours`.
4. **Never change code.** Inside fenced blocks, do not touch identifiers, string literals,
   file names, paths, commands, flags, or terminal output. You MAY translate a comment
   (`# ...`, `// ...`) — but a Chinese string literal such as `brief_name="需求.md"` is a real
   filename and must stay exactly as it is. When unsure, leave it.
5. **Keep the Markdown structure identical**: the same headings in the same order, the same
   table columns, the same fence languages, the same admonition types. `!!! warning "标题"`
   keeps `warning` and translates only the quoted title.
6. **Output only the translated Markdown.** No preamble, no explanation, no code fence around
   the whole document.

## Terminology

Use exactly one term per concept across the whole document, following this Chinese→English
table. For a target language other than English, pick the natural technical term in that
language for the English concept, then use that same word everywhere — never vary it.
Established English technical words (`subagent`, `hook`, `prompt`, `token`, `session`, `compact`,
`plugin`, `worktree`) normally stay in English in every locale; that is what practitioners
actually write.

{TERMS}

## Before you output, check these three counts against the source

These are the failures that actually happen, so verify them explicitly:

- **Markdown links**: the output must contain exactly as many `](...)` links as the input, in the
  same order, each with a byte-identical target. If the source links a term four times, so does
  the translation — do not merge, drop, or add links, and do not "tidy up" a link the target
  language would phrase differently.
- **Figures**: every `$1.23`, every `185.9K`, every `12,212` must appear in the output exactly as
  written. Count them. A dropped measurement is the worst failure mode here, because these pages
  exist to be checked against a raw record.
- **Fences**: the number of ``` lines must match exactly.

## Voice

Declarative, active, concrete. No marketing adjectives. The source is candid about the
framework's failures and limits — keep that candor at full strength; do not soften it. Where the
source names a bug, the translation names a bug."""


def build_term_table() -> str:
    """Derive the zh->en term table from the two hand-written glossaries.

    They are the terminology contract for the whole site, so the table a
    translation is held to is generated from them rather than kept in a second
    place that can drift.
    """
    # These two are hand-written and gatekept, not generated — en/glossary.md is
    # excluded from translation below. Deleting it to force a retranslation takes
    # the term table with it, so say so plainly instead of dying on a traceback.
    missing = [p for p in (DOCS / "zh/reference/glossary.md", DOCS / "en/reference/glossary.md")
               if not p.exists()]
    if missing:
        raise SystemExit(
            "missing hand-written glossary: " + ", ".join(str(p) for p in missing)
            + "\nThese are the terminology contract, not generated output."
            + " Restore with: git checkout HEAD -- " + " ".join(str(p) for p in missing))
    zh = (DOCS / "zh/reference/glossary.md").read_text(encoding="utf-8")
    en = (DOCS / "en/reference/glossary.md").read_text(encoding="utf-8")
    zh_terms = re.findall(r"^### (.+?) \{#(.+?)\}\n\n\*\*(.+?)\*\*", zh, re.M)
    en_pairs = dict(
        (c.strip(), n.strip())
        for n, c in re.findall(r"^### (.+?) \{#.+?\}\n\n\*Chinese: (.+?)\*", en, re.M)
    )
    rows = []
    for name, _anchor, gloss in zh_terms:
        en_name = en_pairs.get(name) or re.sub(r"\s*·.*", "", gloss).strip().strip("*`")
        rows.append(f"| {name} | {en_name} |")
    return "| \u4e2d\u6587 | English |\n|---|---|\n" + "\n".join(rows)


def load_env() -> tuple[str, str]:
    cfg = json.loads((pathlib.Path.home() / ".claude" / "settings.json").read_text())["env"]
    return cfg["ANTHROPIC_BASE_URL"].rstrip("/"), cfg["ANTHROPIC_AUTH_TOKEN"]


_lock = threading.Lock()
_usage = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}


def call(base: str, tok: str, system: list[dict], text: str, *, tries: int = 6) -> tuple[str, dict]:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 32000,
        "system": system,
        "messages": [{"role": "user", "content": text}],
    }).encode()
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(
            f"{base}/v1/messages", data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": tok,
                     "anthropic-version": "2023-06-01",
                     "anthropic-beta": "prompt-caching-2024-07-31"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=900).read())
            out = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            u = r.get("usage", {})
            with _lock:
                _usage["in"] += u.get("input_tokens", 0)
                _usage["out"] += u.get("output_tokens", 0)
                _usage["cache_read"] += u.get("cache_read_input_tokens", 0)
                _usage["cache_write"] += u.get("cache_creation_input_tokens", 0)
            if not out.strip():
                raise RuntimeError(f"empty response (stop_reason={r.get('stop_reason')})")
            return out, u
        except urllib.error.HTTPError as ex:
            last = ex
            if ex.code in (429, 529, 503) and attempt < tries - 1:
                # 限流/过载:退避要够长,否则一堆并发同时重试等于没退
                time.sleep(min(90, 2 ** attempt * 10) + random.uniform(0, 5))
            elif attempt < tries - 1:
                time.sleep(2 ** attempt * 3)
        except Exception as ex:                      # noqa: BLE001 - retry everything
            last = ex
            if attempt < tries - 1:
                time.sleep(2 ** attempt * 3)
    raise RuntimeError(f"failed after {tries} tries: {type(last).__name__}: {last}")


def _headings(text: str) -> list[tuple[int, int, str, str]]:
    """(offset, length, hashes, title) for every heading outside a fenced block."""
    out, fence, pos = [], False, 0
    for line in text.split("\n"):
        if line.startswith("```"):
            fence = not fence
        elif not fence:
            m = re.match(r"^(#{2,4})\s+(.+?)\s*$", line)
            if m:
                out.append((pos, len(line), m.group(1), m.group(2)))
        pos += len(line) + 1
    return out


def sync_anchors(rel: str, lang: str) -> bool:
    """Copy the source's `{#anchor}` onto the translated headings, positionally.

    Nine locales share one set of anchors, so a link written once resolves in all
    of them. A translation will happily re-derive an anchor from its own heading
    text — usually a near-miss, like keeping a comma the slug drops — and that
    silently breaks every inbound link to that section in that language. The
    structure is preserved, so heading N matches heading N; just overwrite.
    """
    src = DOCS / "zh" / rel
    dst = DOCS / lang / rel
    if not src.exists() or not dst.exists():
        return False
    want = [re.search(r"\{#([^}]+)\}$", t) for _, _, _, t in _headings(src.read_text(encoding="utf-8"))]
    text = dst.read_text(encoding="utf-8")
    got = _headings(text)
    if len(want) != len(got):
        log.warning(f"{lang}/{rel}: {len(got)} headings vs {len(want)} in source, anchors not synced")
        return False
    for (start, length, hashes, title), m in zip(reversed(got), reversed(want)):
        if not m:
            continue
        clean = re.sub(r"\s*\{#[^}]+\}$", "", title).strip()
        text = text[:start] + f"{hashes} {clean} {{#{m.group(1)}}}" + text[start + length:]
    dst.write_text(text, encoding="utf-8")
    return True


def split_page(text: str, budget: int = 14000) -> list[str]:
    """Split an oversized page on `##` boundaries.

    A long page does not fit in one generation — the model silently stops
    mid-sentence and the result fails the anchor/fence checks. Chunking on
    top-level sections keeps every chunk self-contained: headings, fences and
    tables never straddle a boundary.

    The budget is in SOURCE characters and is deliberately well under what one
    generation can emit. Chinese is dense: 22.9k characters of it became far more
    than that in German and truncated mid-table at a 24000 budget, which looked
    like a page that simply did not need chunking.
    """
    if len(text) <= budget:
        return [text]
    # keep the preamble (everything before the first `##`) with chunk 1
    parts = re.split(r"^(?=## )", text, flags=re.M)
    chunks, cur = [], ""
    for part in parts:
        if cur and len(cur) + len(part) > budget:
            chunks.append(cur)
            cur = part
        else:
            cur += part
    if cur:
        chunks.append(cur)
    return chunks


def strip_fence(s: str) -> str:
    """Undo a model that wrapped the whole document in one fence anyway."""
    s = s.strip()
    if s.startswith("```"):
        first = s.find("\n")
        if first != -1 and s.rstrip().endswith("```"):
            inner = s[first + 1:s.rstrip().rfind("```")].rstrip()
            # only unwrap if it really was the whole doc, not a doc starting with code
            if inner.lstrip().startswith("#"):
                return inner
    return s


def check(src: str, out: str) -> list[str]:
    """Structural comparison against the source. Cheap, catches the failures that matter."""
    problems = []
    a = set(re.findall(r"\{#([^}]+)\}", src))
    b = set(re.findall(r"\{#([^}]+)\}", out))
    if a - b:
        problems.append(f"锚点丢失 {sorted(a - b)[:4]}")
    sa = len(re.findall(r"^```", src, re.M))
    sb = len(re.findall(r"^```", out, re.M))
    if sa != sb:
        problems.append(f"代码围栏 {sa} -> {sb}")
    ha = len(re.findall(r"^#{1,4} ", src, re.M))
    hb = len(re.findall(r"^#{1,4} ", out, re.M))
    if abs(ha - hb) > 1:
        problems.append(f"标题数 {ha} -> {hb}")
    # every link path in the source must survive untouched
    pa = set(re.findall(r"\]\((\.{0,2}[^)\s]*\.md[^)\s]*)\)", src))
    pb = set(re.findall(r"\]\((\.{0,2}[^)\s]*\.md[^)\s]*)\)", out))
    if pa - pb:
        problems.append(f"链接目标被改 {sorted(pa - pb)[:3]}")
    # A translation that stops mid-sentence still passes every structural check
    # above if it happens to break between fences. Length is the reliable tell:
    # no locale renders this content in under half the source.
    if len(out) < len(src) * 0.5:
        problems.append(f"疑似截断 {len(src)} -> {len(out)} 字符")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("langs", nargs="+", help="locale codes, or 'all'")
    ap.add_argument("--force", action="store_true", help="retranslate pages that already exist")
    ap.add_argument("--jobs", type=int, default=32)
    ap.add_argument("--only", help="substring filter on the page path")
    args = ap.parse_args()

    base, tok = load_env()
    terms = build_term_table()

    langs = list(LANGS) if args.langs == ["all"] else args.langs
    for l in langs:
        if l not in LANGS:
            print(f"unknown locale: {l}", file=sys.stderr)
            return 2

    pages = sorted(p for p in (DOCS / "zh").rglob("*.md"))
    if args.only:
        pages = [p for p in pages if args.only in str(p)]

    jobs = []
    for lang in langs:
        for src in pages:
            rel = src.relative_to(DOCS / "zh")
            dst = DOCS / lang / rel
            # the glossary is hand-written and gatekept for zh and en
            if lang == "en" and rel.as_posix() == "reference/glossary.md":
                continue
            if dst.exists() and dst.stat().st_size > 200 and not args.force:
                continue
            jobs.append((lang, src, dst, rel))

    if not jobs:
        print("nothing to do (everything exists; use --force to redo)")
        return 0

    print(f"{len(jobs)} page(s) across {len(langs)} locale(s), model={MODEL}, jobs={args.jobs}\n")
    t0 = time.time()
    failures = []

    def work(job):
        lang, src, dst, rel = job
        text = src.read_text(encoding="utf-8")
        system = [
            {"type": "text",
             "text": RULES.replace("{TERMS}", terms),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"Target language: {LANGS[lang]}."},
        ]
        chunks = split_page(text)
        if len(chunks) == 1:
            out = strip_fence(call(base, tok, system, text)[0])
        else:
            # translated piecewise; each chunk starts at a `##` so nothing straddles
            pieces = []
            for i, ch in enumerate(chunks, 1):
                sysx = system + [{"type": "text", "text":
                    f"This is part {i} of {len(chunks)} of one page. Translate this part only. "
                    f"Do not add a title, an introduction, or a summary — the parts are "
                    f"concatenated verbatim."}]
                pieces.append(strip_fence(call(base, tok, sysx, ch)[0]))
            out = "\n\n".join(p.strip() for p in pieces)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out.rstrip() + "\n", encoding="utf-8")
        sync_anchors(rel.as_posix(), lang)
        out = dst.read_text(encoding="utf-8")
        return lang, rel, len(out.splitlines()), check(text, out)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(work, j): j for j in jobs}
        done = 0
        for f in as_completed(futs):
            done += 1
            lang, src, dst, rel = futs[f]
            try:
                lang, rel, n, probs = f.result()
                flag = "!" if probs else " "
                print(f"[{done:3}/{len(jobs)}]{flag} {lang:5} {rel.as_posix():36} {n:4}行"
                      + (f"  <- {'; '.join(probs)}" if probs else ""), flush=True)
                if probs:
                    failures.append((lang, rel.as_posix(), probs))
            except Exception as ex:                  # noqa: BLE001
                print(f"[{done:3}/{len(jobs)}]X {lang:5} {rel.as_posix():36} {ex}", flush=True)
                failures.append((lang, rel.as_posix(), [str(ex)]))

    dt = time.time() - t0
    print(f"\n耗时 {dt/60:.1f} 分钟")
    print(f"token: 输入 {_usage['in']:,} / 输出 {_usage['out']:,} / "
          f"缓存命中 {_usage['cache_read']:,} / 缓存写入 {_usage['cache_write']:,}")
    if failures:
        print(f"\n{len(failures)} 页需要复查:")
        for lang, rel, probs in failures:
            print(f"  {lang:5} {rel:36} {'; '.join(probs)}")
        return 1
    print("全部通过结构校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
