# Configuration

flower has no config file format, and no config subcommand that actually goes anywhere — all
configuration is **environment variables** plus **`.env` files**, plus a batch of policy objects
that can only be supplied from the Python side. This page gathers what's scattered across five
places into one: every variable, the order credentials are looked up in, what syntax `.env`
accepts, what `setting_sources=[]` actually isolates, what a single run leaves on disk, what each
of the three session store layers drops, and how it waits when the network is down. Terminology
follows the [glossary](glossary.md) throughout.

| Want to know | Go to |
|---|---|
| Which env vars flower reads | [Full environment variable table](#环境变量) |
| Where my token actually comes from | [Credential lookup priority](#凭证查找优先级) |
| Why that line in `.env` didn't take effect | [`.env` parsing rules](#env-解析) |
| What to carry when switching machines | [The cost of portability](#可移植性) |
| What's in `.flower/` and `runs/` | [Disk layout](#磁盘布局) |
| Which messages aren't fed back to the model | [The three session store layers](#会话存储) |
| What it's waiting for when the network's down | [Network resilience](#韧性) |

## Full environment variable table {#环境变量}

Five groups: credentials and endpoints flower reads directly, model selection, path lookup,
behavior switches, and what flower **writes to** the agent subprocess. You don't set the last
group — set it and it gets overwritten anyway.

### Credentials and endpoints {#凭证变量}

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic's official key. If present, requests go out with an `x-api-key` header | none | **exactly one of it and `ANTHROPIC_AUTH_TOKEN` is required** | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token issued by a gateway. Used with `authorization: Bearer` when there's no `ANTHROPIC_API_KEY` | none | same as above | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | The API endpoint root. A third-party gateway fills in its own address, **without `/v1`** — the probe assembles `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | no | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

If neither is set (or both are empty strings), `check_credentials()` returns that four-line error,
and `Runtime.__init__` also raises `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Model selection {#模型变量}

flower reads only three of these for its own decisions; the rest are loaded and passed straight
through to the SDK.

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | The main model name. Also decides the default [handoff](glossary.md#换代) window: `1m` in the name or no `haiku` → 1M, `haiku` present → 200K | none (decided on the server side) | no | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Model mapping for the opus tier. When `ANTHROPIC_MODEL` is empty, the window decision falls back to it | none | no | `agent.py:78`; `cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Model mapping for the sonnet tier. flower doesn't read it itself, only loads and lends it | none | no | `env.py:34`; `cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Model mapping for the haiku tier. **The credential probe prefers it** | probe falls back to `ANTHROPIC_MODEL`, then to `claude-3-5-haiku-20241022` | no | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Which model [subagents](glossary.md#subagent) use. flower doesn't interpret it; the SDK consumes it | none | no | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Thinking tier. Same as above, only loaded, not interpreted | none | no | `env.py:35` |

If `flower setup` filled in a model name, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, and
`ANTHROPIC_DEFAULT_SONNET_MODEL` **all three get written together** (`cli.py:1383-1385`).

### Paths and lookup {#路径变量}

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `FLOWER_ENV` | Points at a `.env` file path, placed **before** all others | none | no | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Determines the location of the global credential file `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | no | `env.py:41-42` |
| `HOME` | The source of `Path.home()`; both `~/.config` and `~/.claude` are derived from it | given by the system | no | `env.py:41`, `:67` |

### Behavior switches {#行为开关}

Both are escape hatches: not setting them is the norm, setting them makes flower do one thing
less. **Any non-empty value takes effect**; the value itself isn't parsed (`update.py:121`;
`cli.py:1413`).

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | Turns off [auto-update](../getting-started/install.md#自动更新). When unset, a flower installed via pip / pipx / uv spins up a background thread at startup to check for a new version, installs it if found, and it **takes effect on the next `flower` run**; checks at most once every 24 hours, timestamp recorded in `~/.config/flower/.update` | none (auto-update on) | no | `update.py:32-33`, `:121-124` |
| `FLOWER_NO_PROBE` | Skips the startup [credential probe](cli.md#第二道-凭证能不能用). Non-interactive runs (pipe / CI / redirected stdin) don't probe anyway; this variable is the escape hatch left for interactive terminals | none (probes under interactive) | no | `cli.py:1413` |

A flower run from git source isn't affected by auto-update; `FLOWER_NO_UPDATE` is a no-op for it —
the update command recognizes a `.git` in the repo at that step and returns `None` immediately
(`update.py:83-87`).

### What flower writes to the agent subprocess {#写出的变量}

These three are generated by `CompactPolicy.env()` and stuffed into `ClaudeAgentOptions.env`
(`agent.py:48-58`, `:241-245`), controlling the harness's built-in [compact](glossary.md#压缩).
**Setting them in your shell means nothing** — what actually takes effect is the copy flower
passes to the subprocess.

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` turns off auto-compact. **Force-written** when [handoff](glossary.md#换代) is on — with both mechanisms running at once you can't tell which one caused a context rollback | handoff is on by default, so in practice always `1` | no (flower writes) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` turns off `/compact` too. Only written by `CompactPolicy(mode="off")` | not written | no (flower writes) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | The auto-compact window (tokens). Only written by `CompactPolicy(window=N)` | not written | no (flower writes) | `agent.py:56-57` |

### What the container wrapper reads {#容器变量}

These two aren't read by flower proper; they're read by the `docker/flowerbox` shell wrapper. See
[Deployment](deploy.md) for full usage.

| Variable | Effect | Default | Required | Source |
|---|---|---|---|---|
| `FLOWER_HOME` | Where to find the `.env` for `--env-file` | the parent directory of the script's own location | no | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Which image to use | `flower-box` | no | `docker/flowerbox:13` |

**The keys in `.env` aren't limited to the above.** The parser loads **every** `k=v` line into
`os.environ`, with no allowlist (`env.py:30`, `:102-107`). The `KNOWN` set made up of the 9
credential keys above only does two things: acts as an allowlist when borrowing `~/.claude`
config (`env.py:72`), and bounds the fields printed by `describe()` when starting with `-v`
(`env.py:205`).

## Credential lookup priority {#凭证查找优先级}

When `load_dotenv()` is called with no path, it reads **every file that exists** in the following
order (`env.py:45-53`, `:78-112`):

1. **Process environment variables** — always highest. No `.env` can override an already-exported
   value. (`env.py:91`)
2. **The file `$FLOWER_ENV` points at** — only present if set. (`env.py:48-49`)
3. **`$PWD/.env`** — the current working directory. `cd` into a project and it reads the nearest
   one. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — the per-user global location, the one
   `flower setup` writes. (`env.py:51`, `:39-42`)
5. **The `.env` at the source repo root** — three levels up from `flower/core/env.py`. Only
   present when running from source; a flower installed via pip / pipx / uv lives in
   site-packages and has no such file. (`env.py:52`)
6. **The `env` block of `~/.claude/settings.json`, then `~/.claude/settings.local.json`** — the
   last fallback, **takes only the 9 credential keys**. (`env.py:56-75`, `:109-111`)

**Which file wins**: entry 3 (project `.env`) beats entry 4 (global `.env`), entry 4 beats entry 5
(repo-root `.env`), all three beat entry 6 (Claude Code's config), and none of them beat entry 1
(the process environment).

The mechanism is "**don't overwrite a key that already has a value**" (`env.py:90-93`): the ones
earlier in the order claim keys first, the later ones only fill gaps. So priority is **computed
per key, not per file** — if the project `.env` only writes `ANTHROPIC_BASE_URL`, the token can
still come from the global one. The first value that appears for a given key is settled for life.

Entry 6 is only enabled during **automatic lookup**. Give an explicit path
(`load_dotenv("/path/to/.env")`) and it reads only that one file, with no fallback whatsoever
(`env.py:86-87`, `:109`).

### Entry 6: borrowing Claude Code's token {#借用}

It reads `~/.claude/settings.json` then `~/.claude/settings.local.json` in order, takes the
`data["env"]` dict, and picks out these 9 keys (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

If the file doesn't exist, can't be read, or isn't valid JSON (`OSError` / `ValueError`), it
returns an empty dict and moves on — **a broken fallback shouldn't take the run down with it**
(`env.py:62-63`, `:66-69`).

The stance in the code: all it borrows is "where to find the token"; nothing else in
settings.json (permission rules, hooks, model settings) is taken over, so this doesn't violate the
portability promise of `setting_sources=[]` (`env.py:17-19`, `:59-61`). `install.sh:77` pitches it
as a feature: someone with Claude Code already configured on the machine won't even see the config
screen.

!!! warning "The in-product error text contradicts the actual behavior"
    When credentials can't be found at all, the last line of the error flower prints is:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, that line at `:192`; the same claim also appears in `.env.example:2`,
    `env.py:3-4`, `agent.py:10-12`.) **Trust the code: it does read it.** `env.py:56-75` plus
    `:109-111` explicitly reads those two files, and `install.sh:77` even sells this as a
    selling point. That text is currently misleading — on a machine that has Claude Code
    configured, your token very likely comes from exactly there.

## `.env` parsing rules {#env-解析}

The parsing rules are short enough to memorize (`env.py:95-107`, 13 lines): `strip` each line,
skip blank lines, lines starting with `#`, and lines with no `=`; split the rest at the **first**
`=` into key and value, `strip` each side, then run the value through `.strip("'\"")` once — any
leading or trailing single or double quotes are stripped, **without requiring them to be paired**.

**Accepted forms**:

| Form | Result |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — spaces around the equals sign are stripped |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — leading and trailing quotes stripped |
| `KEY=a=b` | value is `a=b` — split at the first `=`, later equals signs stay in the value verbatim |
| `# comment` | whole line skipped |
| blank line | skipped |

**Not accepted**. Writing these raises no error, you just silently get an unexpected value:

| Form | Actual result |
|---|---|
| `export KEY=VALUE` | key becomes `export KEY`, `KEY` itself still has no value |
| `KEY=value # note` | value is `value # note` — trailing comments aren't stripped |
| `KEY=$OTHER` | the literal `$OTHER`, no variable interpolation |
| multi-line value (quoted across lines) | processed line by line; the second line has no `=` and gets skipped wholesale |

**An empty value claims the key.** If `ANTHROPIC_AUTH_TOKEN=` appears in a higher-priority file,
`take()` runs `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, and then later files can't fill it in
because "the key already exists" (`env.py:90-93`); meanwhile `check_credentials()` tests for
truthiness, so an empty string still counts as unconfigured (`env.py:186`). **The result is
neither credentials nor a fallback.** If you don't want a key, delete the whole line — don't leave
an empty one.

## The cost of portability {#可移植性}

That one line in `build_options()` is the whole mechanism (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` is the default for `Runtime`, and **no command-line switch can turn it off** — to
turn it off you have to go through the Python API and write `Runtime(portable=False)`, which
becomes `["project"]`, i.e. reads the project's `.claude/`.

### What gets isolated {#被隔绝的东西}

| Isolated | Consequence |
|---|---|
| The host's `~/.claude/` settings | The permission rules, hooks, and model settings there take no effect. **Credentials are the sole exception**, see [borrowing](#借用) |
| The project's `.claude/` | Same as above; only read when `portable=False` |

Domain capability doesn't go through this path — it ships with the repo, loaded via
`plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`, `:210-212`), see
[Deployment](deploy.md). Domain instructions are **appended** after the native Claude Code system
prompt, not a replacement (`agent.py:198-202`), so specialization doesn't cost you general
capability.

### What to carry when switching machines {#换台机器要带什么}

- **Credentials: one file**. Copy `~/.config/flower/.env` over, or reconfigure once on the new
  machine. Don't bring it and nothing runs — nothing gets inherited automatically.
- **Continuity state: the whole directory**. `runs/` (session store, manifest, lineage) and
  `.flower/` (workbench).
- **But paths must match**. `lineage.json` stores the workspace's absolute path; if it doesn't
  match it's treated as absent, silently falling back to a new session, **with no error**
  (`lineage.py:65-66`). The reason is that the SDK's `project_key` is derived from the workspace
  path (`/`, `_`, `.` all replaced with `-`, `runtime.py:40-41`); move the directory and the old
  `session_id` can no longer be found.

## Disk layout {#磁盘布局}

A single flower run writes two trees: `<run_dir>/` holds the ledger and sessions, and
`<workspace>/.flower/` holds the [workbench](glossary.md#工作台). Both default to under the
current directory, but **their bases differ**.

!!! warning "`runs/` follows the current directory, not `-w`"
    `-r/--run-dir` defaults to `"runs"`, and what `Runtime` does with it is
    `Path(run_dir).resolve()` (`runtime.py:93-94`) — relative to the **current working
    directory**, not to the workspace given by `-w`. Run `flower -w /path/to/proj` from `~` and
    the session store lands in `~/runs/`, not in the project.

### `<run_dir>/` — default `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, full transcript (including each subagent's own)
  manifest.json      run manifest: each step's session_id / cost / retries / failure reason, accumulated across processes
  lineage.json       lineage: step name → session_id, reconnecting a re-run in the same directory relies on it
  aside/             the oracle's separate Runtime, its own sessions.db + manifest.json
  workbench/         only when going through the run / once path and given -W
```

| Path | Contents | Source |
|---|---|---|
| `runs/sessions.db` | Full transcript. Written by `PruningSessionStore`, the three-layer policy is described [below](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | A JSON array, the [run manifest](glossary.md#运行清单) **accumulated across processes**. Fields in the table below | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Writes to `.tmp` first then `replace`, atomic swap | `lineage.py:31`, `:87-97` |
| `runs/aside/` | The [oracle](glossary.md#旁路顾问)'s separate Runtime. **Its cost and lineage aren't mixed into the main manifest** | `cli.py:741-743` |
| `runs/workbench/` | The default workbench location for `Runtime(workbench=True)`, outside the workspace. The `go` path doesn't use it | `runtime.py:148-151` |

Each line of `manifest.json` is `asdict(StepResult)` plus two patches (`runtime.py:44-71`,
`:579-582`):

| Field | Type | Meaning |
|---|---|---|
| `step` | `str` | Step name. Four shapes: `<name>`, `<name>#round<N>` (sent back for redo), `<name>#retry<N>` (plain retry), `<name>·判定#<N>` ([judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | The last live [session](glossary.md#会话) of this step |
| `ok` | `bool` | Whether it succeeded |
| `cost_usd` | `float` | How much this step cost |
| `num_turns` | `int` | How many turns it ran |
| `text` | `str` | The final reply of this step |
| `error` | `str \| None` | Failure reason. When killed by SIGHUP / SIGTERM it's `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch seconds |
| `attempts` | `int` | Actual number of attempts. `>1` means it retried |
| `errors` | `list[str]` | The failure reasons over the attempts. **Only here — the model can't see them** |
| `resumed` | `bool` | Whether it reconnected from the interruption point via resume rather than running from scratch |
| `retired` | `list[str]` | The session_ids burned during this step's [handoff](glossary.md#换代), in order |
| `context` | `int` | The context size the [main thread](glossary.md#主线程) actually saw on the last turn |
| `duration_s` | `float` | Patched in by hand — it's a `@property`, `asdict()` can't collect it |
| `run` | `str` | This process's marker `YYYYmmdd-HHMMSS-<6-digit hex>`. **Must be unique per instance** |

The write policy is **append, don't overwrite**: each flush re-reads the file, replaces the lines
whose `run` equals its own with the latest, and leaves other lines untouched (`runtime.py:564-586`).
So running multiple flowers in parallel in the same directory won't have their ledgers clobber
each other.

The stuff in `runs/` is pure data, readable offline anytime with sqlite3 or
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — the workbench {#工作台目录}

```text
.flower/
  INDEX.md      auto-generated index, injected into the main agent's system prompt
  scripts/      scripts to be run a second time. The first line `# desc: 一句话` appears in the index
  artifacts/    long outputs over 2000 characters: reports, data, logs
  notes/        cross-step decision records
  spill/        spilled large tool results, filename = first 16 chars of the content sha256 + `.txt`
```

The three subdirectories plus the index are created by `Workbench` (`workbench.py:73-92`).
`INDEX.md` goes through the session-level `system_prompt.append`, which **subagents can't
inherit** — so the rule "write long outputs to `artifacts/`" must be relayed by the
[coordinator](glossary.md#协调者) in the [task brief](glossary.md#任务书), that being the only
channel.

The `go` path always generates these under `notes/`:

| File | Contents | Source |
|---|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goal / acceptance criteria / boundaries / unknowns and assumptions | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Two frozen sections: goal / verdict checklist | `workflow/goal.py:124` |
| `notes/问答记录.md` | An appended record of all the Q&A, including inbox entries from "the human speaking up unprompted". **Doesn't enter context, kept only for the record** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书). The previous generation gets filed into `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json` + `需求.md` + `目标.md` archived by `--new` / `/new` (**moved, not deleted**) | `lineage.py:100-117` |

**With `--isolate` the workbench moves outside the repo**: `<parent of workspace>/.flower-<workspace name>/`
(`starter.py:47-55`). A worktree is each agent's private copy, the workbench is a shared layer
across agents, and shared things can't go inside a private fence. In this case the path given to
the model is absolute (`workbench.py:69-71`, `:142-145`).

**`spill/` has two writers, with different landing algorithms**:

| Who writes | When | Where to | Threshold |
|---|---|---|---|
| `spill_guard` (`PostToolUse` hook) | **before** a tool result enters the model | `<workbench root>/spill/` (`guard.py:130`) | `spill_threshold`, default 4000 characters |
| `TrimPolicy` (at `load`) | when replaying history before resume | `<workspace>/.flower/spill/` — a fixed string relative to the workspace (`trim.py:49`, `:303`) | `min_chars`, default 2000 characters |

Under the default layout these are the same directory. But when the workbench is moved away
(`-W` lands it in `runs/workbench/`, or `--isolate` lands it outside the repo) the two split apart
— the `TrimPolicy` copy is always inside the workspace, because the agent's `Read` must be able to
reach it.

What `spill_guard` swaps in isn't one line, it's one line of pointer plus the **first 400
characters** (`guard.py:132-140`). Calls that read the spill file itself are let through,
otherwise "use Read to read the full text" is an empty phrase — read it back and it's over
threshold again, spilled again, an infinite loop (`guard.py:155-170`).

### The `sessions.db` schema {#sessions-db}

Three tables, the CREATE statements are in `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| Table | What a row is | Key point |
|---|---|---|
| `entries` | One entry in the transcript, `payload` is the raw JSON | `uid` is the entry's `uuid`, serving as an **idempotency key**: a failed batch gets retried 3 times, and the replay must not produce duplicate rows. Entries with no `uuid` (titles, tags, mode markers) aren't deduped, so the unique index carries `WHERE uid IS NOT NULL` |
| `meta` | A session's cursor | `next_seq` is the next sequence number, `mtime` is a millisecond timestamp and **strictly monotonic** (`sqlite.py:72-79`) — `list_sessions` and summaries share this clock, and non-monotonicity would send the SDK's new/old judgment down the wrong fast path |
| `summaries` | A main-thread summary sidecar | **Only the main transcript participates**, subagents' don't (`sqlite.py:122-123`) |

`store_key` is built (`sqlite.py:54-58`) as `<project_key>/<session_id>`, with subagents adding a
further `subpath`. `project_key` is derived by the SDK from the workspace path — `/`, `_`, `.` all
replaced with `-`.

Look at a real sample
([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

That one has 956 `entries`, 10 `meta`, and 4 `summaries` — of the 10 sessions 4 are main
transcripts, 6 are subagents', and `summaries` exactly equals the number of main transcripts.

## The three session store layers {#会话存储}

!!! note "The three layers are an inheritance chain, not an optional combination"
    `PruningSessionStore` inherits `TrimmingSessionStore` inherits `SqliteSessionStore`.
    `Runtime` **always** constructs the outermost one (`runtime.py:109-112`); there's no
    entry point in the constructor arguments to swap the backend. The way to "turn off a layer"
    is to set its policy object's `enabled` to `False`, not to swap the class.

`append` (write) is always a full spill to disk, not a word changed. The three layers only affect
`load` (the copy read back and fed to the model). The actual order of `load` is:

```text
SqliteSessionStore.load     read out all entries from the entries table by seq
  → TrimmingSessionStore.expire()   time-sensitive Bash results → swapped for "expired"
  → TrimmingSessionStore.trim()     old large tool_results → spilled + swapped for a pointer
    → PruningSessionStore.prune()   synthetic error messages / old denied calls → removed wholesale and the chain relinked
```

| Layer | Class | Drops what | Criterion |
|---|---|---|---|
| 1 | `SqliteSessionStore` | drops nothing | —— |
| 2 | `TrimmingSessionStore` | large tool result bodies, expired ephemeral command results | size + timeliness |
| 3 | `PruningSessionStore` | disconnection debris, old denied calls | whether it's an error |

Layer 2 is [trim](glossary.md#裁剪), layer 3 is [prune](glossary.md#剪除) — **trim drops by size
and value, prune drops by "is it an error"**, don't conflate them. Full signatures in the
[Python API](api.md).

### `SqliteSessionStore` — the foundation {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

A SQLite implementation with zero external dependencies. To swap in Postgres / S3 / Redis,
implement the same protocol; the SDK ships a conformance test suite
`claude_agent_sdk.testing.session_store_conformance` you can validate against directly
(`sqlite.py:1-8`).

Besides the protocol methods, there are three **synchronous** queries, for flower's own use:

| Method | Returns | Use |
|---|---|---|
| `projects()` | `list[str]` | The `project_key`s that actually exist in the store. The SDK derives it from cwd; confirm with this before querying rather than guessing |
| `has_session(project_key, session_id)` | `bool` | Queries only one `meta` row, doesn't read the payload. Query before starting [continuity](glossary.md#接续) — resuming a session that doesn't exist blows up only after the subprocess starts, by which point money and time are spent |
| `last_context(project_key, session_id, scan=60)` | `int` | How large a context the last turn of this session saw. Scans only the last 60 entries backward. `input_tokens` plus the two `cache_*` all count — looking at only the former, which is near 0 on a cache hit, would badly underestimate |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Two orthogonal rules. `TrimPolicy` handles **size**:

| Parameter | Type | Default | Semantics |
|---|---|---|---|
| `keep_recent` | `int` | `20` | The most recent N `tool_result`s keep their original text — the context in active use shouldn't be trimmed |
| `min_chars` | `int` | `2000` | Anything shorter isn't trimmed. Swapping in a pointer would cost more tokens instead |
| `spill_dirname` | `str` | `".flower/spill"` | The archive directory, **relative to workspace**. Must be inside the workspace, otherwise the agent's `Read` can't reach it |
| `enabled` | `bool` | `True` | `False` when `Runtime(trim=False)` (the default) |

The trimmed body is written as `<first 16 chars of sha256>.txt`, and the original position is
swapped for
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` handles **timeliness**: results from `git status`, `ls`, `ps` and the like are
short, and by size would never get their turn to be trimmed, but their correctness decays over
time — a `git status` from 20 turns ago isn't "useless", it's **misleading**.

| Parameter | Type | Default | Semantics |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converted from `Runtime(ephemeral=…)`, **on by default** |
| `keep_recent` | `int` | `6` | The most recent N keep their original text. Much smaller than `TrimPolicy`'s 20 — the "recent" window for this kind of thing is inherently short |
| `max_chars` | `int` | `2000` | Beyond this it's handed to `TrimPolicy` to spill and archive, not this path |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Replacement text |

Applies only to **Bash** tool results, and the command must match `EPHEMERAL_CMD`. `Read` isn't
included: file contents don't distort into being misleading merely because time passes, and it may
be exactly what the model's reasoning rests on (`trim.py:153-160`). Expired content is **not
spilled** — archiving an expired `git status` is pointless, rerun it once and you have it.

The judging function is `is_ephemeral(cmd)`, and it is **also the permission list handed back to
the coordinator**: `delegate_guard(allow_glance=True)` uses the same function (`trim.py:63-68`,
`:128-150`). The two sets must always be equal — allow it but don't trim it and an expired
`git status` occupies context forever; trim it but don't allow it and the coordinator dispatches a
subagent for a single `ls`, trading 4.3k of startup cost for a few dozen characters. Adding one
command to the allowlist says both of those things at once.

**When to use which**:

- Want only disconnection debris kept out of context → do nothing, `Runtime` defaults to
  `PruningSessionStore`. `trim=False` just doesn't trim large results; removal still happens.
- Long runs, large tool output → `trim=True`. The `go` path CLI has it on by default, use
  `--no-trim` to turn it off in reverse.
- The [coordinator](glossary.md#协调者) has `glance=True` on → `ephemeral` must stay on, reasons in
  the previous paragraph.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parameter | Type | Default | Semantics |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Removes synthetic messages with `isApiErrorMessage=true` or `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | For a `[Request interrupted …]` `tool_result`, **swap the body, don't remove the block** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Replacement text for the previous entry |
| `heal_orphans` | `bool` | `True` | **Adds** a synthetic result for orphaned calls that "have a `tool_use` but no `tool_result`" |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | The body of the `tool_result` added |
| `keep_denials` | `int` | `1` | Keep the most recent N tool calls denied by the permission hook, remove earlier ones **call and result together** |

`keep_denials` is the only `Runtime` constructor argument passed straight through to this layer
(`Runtime(keep_denials=N)`). The reason for defaulting to 1 rather than 0: the most recent denial
is a valid signal, preventing the model from repeatedly retrying the same blocked command within a
single turn. **Don't raise it** — a denied call was never executed, its result carries no
information, and in measurement one occupies 273 characters (a 93-character refusal plus 180
characters of the dead command's text), and it **misleads**: in measurement, after the coordinator
reads a few "don't use Bash directly" lines, it stops even trying an allowed `git status` and just
says "Bash is restricted, dispatch an agent to look" (`prune.py:135-148`).

`heal_orphans` cures **resume 400-ing every time after an interruption**: the interruption breaks
at a message boundary, the `tool_use` in flight at the time may have no `tool_result` following it
at all, while the API requires the two to be paired. This bad history left in the transcript won't
go away on its own, so every subsequent resume gets bounced by it. The fix is to insert a `user`
entry after the assistant entry containing the orphan, filling in the results for all orphans in
that entry at once, then reroute the `parentUuid` that originally pointed at that assistant to
point at this inserted one (`prune.py:95-147`). **Add, don't delete**: deleting an orphan requires
relinking the parent-child chain, and the same assistant entry may still hold valid blocks, text,
and thinking that would get caught in the crossfire (`prune.py:195-204`).

Three structural red lines, violating which makes the API error out directly:

1. **The `tool_result` block itself must be present**, only `content` can be swapped. Miss one and
   it's "Missing Tool Result Block" (`trim.py:20-22`; `prune.py:79-92`).
2. **`isCompactSummary` / `isMeta` entries can't be touched** — that's the only form in which the
   compacted history exists (`trim.py:179-181`).
3. **Remove an entry and you must reattach its children to its parent**. The transcript is a
   single `parentUuid` chain, the harness walks back from the leaf, and wherever the chain breaks
   all the history before it is lost (`prune.py:95-122`). So `relink()` must receive the full list
   **including** the entry to be removed, and does the filtering itself.

**Not one word of the original in SQLite is changed** — the three layers only affect "the copy fed
back to the model" (`trim.py:18`; `prune.py:8`).

## Network resilience {#韧性}

A long-horizon workflow runs for hours at a stretch, and the network will drop at least once. The
default behavior is bad: the moment it drops, the harness stuffs a synthetic assistant message
into the transcript (`model="<synthetic>"`, `isApiErrorMessage=true`), with the body
`API Error: Can't reach the API server …`; it becomes the session's leaf, so a later resume feeds
it back as "what the model said last", and the model thinks it's discussing a network failure; it
also mixes into `StepResult.text` and passes down the workflow to the next step's prompt
(`resilience.py:1-22`).

The [resilience](glossary.md#韧性) layer does three things, none optional: probe, resume instead of
restart, keep errors out of context.

### `Resilience` parameters {#resilience}

| Parameter | Type | Default | Semantics |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converted from `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | How many times a [step](glossary.md#步骤) can be attempted at most, **including the first** |
| `base_delay` | `float` | `4.0` | Exponential backoff starting point, seconds |
| `max_delay` | `float` | `120.0` | Backoff ceiling, seconds |
| `probe_timeout` | `float` | `5.0` | Single-probe timeout, seconds |
| `probe_interval` | `float` | `15.0` | How often to probe while offline, seconds |
| `max_offline_wait` | `float` | `3600.0` | Maximum wait while offline. Default 1 hour — longer than that is usually not jitter, it's something actually wrong |
| `retry_unknown` | `bool` | `True` | Retry errors that can't be classified too. Most unknown errors are transient, and fatal errors are already blocked separately |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | What to say to the model when resuming |

The backoff formula (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

That is `±25%` jitter, avoiding a bunch of processes rushing in together the instant the network
recovers. At defaults: the 1st backoff is 4 seconds (actually 3–5), the 2nd is 8 seconds (6–10),
and from the 5th it caps at 120 seconds (90–150).

### Probe strategy {#探针}

- **What it probes is the host:port of `ANTHROPIC_BASE_URL`**, not `api.anthropic.com`
  (`resilience.py:67-72`). With a self-hosted gateway, the latter being reachable says nothing
  about the former.
- **DNS plus a TCP handshake only**: `getaddrinfo` then `connect_tcp` then close immediately. No
  HTTP, no credentials, no cost (`resilience.py:75-85`). The probe must be free, otherwise
  "probing every 15 seconds while offline" itself becomes a failure.
- Any failure counts as unreachable — no distinction between DNS being down and TCP being refused.
- `wait_online()` hangs there waiting: returns `True` when reachable, returns `False` after a full
  `max_offline_wait`. On the first unreachability it notifies one line
  `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, and on recovery notifies one more line
  `<host>:<port> 恢复,继续`, **without flooding the screen in between** (`resilience.py:126-140`).

The credential probe before the run starts is a separate matter: it actually sends one
`POST <BASE_URL>/v1/messages`, `max_tokens=16`, with a default timeout of 20 seconds
(`env.py:126-181`). **Don't set `max_tokens` to 1** — in measurement a model with forced
chain-of-thought can't even fit its thinking, and the server struggles until 30 seconds before
returning; set it to 16 and it takes only 3.6 seconds (`env.py:120-123`).

### Error classification {#错误分类}

`classify(text)` returns one of three. **Judge fatal first**: a 401 and the like often carry words
like "connection" in their text too, and getting the order backwards causes a deadlock wait
(`resilience.py:53-64`).

| Class | What it matches (regex in `resilience.py:37-50`) | Behavior |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Stop immediately, no retry. However many times you retry the result is the same, and each one costs money |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Wait for the network to come back, then resume |
| `unknown` | matches none | Retried too when `retry_unknown=True` (the default) |

Distinguishing retryable from non-retryable is the core of this layer: **network jitter should
wait, a credential error should stop immediately** — deadlock-waiting while offline is right, but
deadlock-waiting on a mistyped key is just burning time.

### What gets held out of context {#错误不进上下文}

1. **Synthetic error messages**. `PruningSessionStore` removes them wholesale at `load` and
   relinks `parentUuid` (`prune.py:27-32`, `:191-195`). **Kept verbatim in SQLite**, just not fed
   back.
2. **In the event stream it's `kind="error"`, not `"text"`**, so it doesn't enter
   `StepResult.text`, and therefore doesn't pass down the workflow into the next step's prompt
   (`resilience.py:17-18`).
3. **`resume_prompt` deliberately contains no error detail**. The model needs to know "you were
   interrupted, keep going", not whether it was `ENOTFOUND` or `503`. **That belongs in the log,
   not the context** (`resilience.py:112-113`). For the log, look at the `errors` field of
   `manifest.json`.

Resume instead of restart: by the time the failure occurs the `session_id` is already in hand, use
resume to reconnect from the interruption point, and the earlier cost isn't wasted.

## Related {#相关}

- [Command line](cli.md) — how each switch maps to the configuration on this page.
- [Python API](api.md) — full signatures of `Runtime`, the three stores, and `Resilience`.
- [Deployment](deploy.md) — running in a container, distributing domain capability via a plugin.
- [Glossary](glossary.md) — the precise meaning of every term used on this page.
