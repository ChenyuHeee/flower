# Configuration

flower has no configuration file format, and no configuration subcommand that actually goes anywhere — all configuration is **environment variables** plus a **`.env` file**, plus a set of policy objects that can only be supplied from the Python side. This page collects what is scattered across five places into one: every variable, the order credentials are looked up in, what syntax `.env` accepts, what `setting_sources=[]` actually isolates, what a run leaves on disk, what each of the three session-store layers drops, and how it waits when the network is down. Terminology follows the [glossary](glossary.md) throughout.

| What you want to know | Where |
|---|---|
| Which environment variables flower reads | [Full environment variable table](#环境变量) |
| Where my token actually came from | [Credential lookup priority](#凭证查找优先级) |
| Why that line in `.env` had no effect | [`.env` parsing rules](#env-解析) |
| What to carry to another machine | [The price of portability](#可移植性) |
| What is inside `.flower/` and `runs/` | [Disk layout](#磁盘布局) |
| Which messages never get fed back to the model | [The three session-store layers](#会话存储) |
| What it is waiting for when the network is down | [Offline resilience](#韧性) |

## Full environment variable table {#环境变量}

Four groups: credentials and endpoint that flower reads directly, model selection, path lookup, and what flower **writes to** the agent subprocess. You do not set the last group — if you do, it gets overwritten.

### Credentials and endpoint {#凭证变量}

| Variable | Purpose | Default | Required | Source |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Official Anthropic key. If present, requests go out with the `x-api-key` header | none | **one of** this or `ANTHROPIC_AUTH_TOKEN` is required | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token issued by a gateway. Used as `authorization: Bearer` when `ANTHROPIC_API_KEY` is absent | none | same as above | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | API endpoint root. A third-party gateway puts its own address here, **without `/v1`** — the probe assembles `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | no | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

If neither is set (or both are empty strings), `check_credentials()` returns that four-line error and `Runtime.__init__` raises `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Model selection {#模型变量}

flower reads only three of these for its own decisions; the rest are loaded and passed through to the SDK.

| Variable | Purpose | Default | Required | Source |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Main model name. Also determines the default [handoff](glossary.md#换代) window: name contains `1m`, or does not contain `haiku` → 1,000,000; contains `haiku` → 200,000 | none (endpoint decides) | no | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Model mapping for the opus tier. When `ANTHROPIC_MODEL` is empty, the window decision falls back to this | none | no | `agent.py:78`; `cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Model mapping for the sonnet tier. flower does not read it, only loads and borrows it | none | no | `env.py:34`; `cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Model mapping for the haiku tier. **The credential probe prefers it** | probe falls back to `ANTHROPIC_MODEL`, then to `claude-3-5-haiku-20241022` | no | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Which model [subagents](glossary.md#subagent) use. flower does not interpret it; the SDK consumes it | none | no | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Thinking level. Same as above, loaded but not interpreted | none | no | `env.py:35` |

If you gave `flower setup` a model name, it writes `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` and `ANTHROPIC_DEFAULT_SONNET_MODEL` **all three together** (`cli.py:1204-1206`).

### Paths and lookup {#路径变量}

| Variable | Purpose | Default | Required | Source |
|---|---|---|---|---|
| `FLOWER_ENV` | Points at one `.env` file, placed **before** all other files | none | no | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Determines where the global credential file lives: `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | no | `env.py:41-42` |
| `HOME` | Source of `Path.home()`; both `~/.config` and `~/.claude` are derived from it | given by the system | no | `env.py:41`, `:67` |

### What flower writes to the agent subprocess {#写出的变量}

These three are produced by `CompactPolicy.env()` and injected into `ClaudeAgentOptions.env` (`agent.py:48-58`, `:241-245`), controlling the harness's built-in [compaction](glossary.md#压缩). **Setting them in your shell means nothing** — what takes effect is the copy flower passes to the subprocess.

| Variable | Purpose | Default | Required | Source |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` turns off auto-compaction. **Forced on** whenever [handoff](glossary.md#换代) is enabled — with both mechanisms running you cannot tell which one caused a context drop | handoff is on by default, so this is effectively always `1` | no (flower writes it) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` disables `/compact` as well. Only written for `CompactPolicy(mode="off")` | not written | no (flower writes it) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Auto-compaction window (tokens). Only written for `CompactPolicy(window=N)` | not written | no (flower writes it) | `agent.py:56-57` |

### What the container wrapper reads {#容器变量}

These two are not read by flower itself but by the `docker/flowerbox` shell wrapper. Full usage in [Deployment](deploy.md).

| Variable | Purpose | Default | Required | Source |
|---|---|---|---|---|
| `FLOWER_HOME` | Where to find the `.env` used for `--env-file` | the parent directory of the script's own location | no | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Which image to use | `flower-box` | no | `docker/flowerbox:13` |

**The keys in `.env` are not limited to the ones above.** The parser loads **every** `k=v` line into `os.environ` with no allowlist (`env.py:30`, `:102-107`). The `KNOWN` set of those 9 credential keys matters in only two places: as the allowlist when borrowing `~/.claude` configuration (`env.py:72`), and as the field range printed by `describe()` under `-v` (`env.py:205`).

## Credential lookup priority {#凭证查找优先级}

When `load_dotenv()` is called without a path, it reads **every file that exists** in this order (`env.py:45-53`, `:78-112`):

1. **Process environment variables** — always highest. No `.env` can override an already-exported value. (`env.py:91`)
2. **The file pointed at by `$FLOWER_ENV`** — only if it is set. (`env.py:48-49`)
3. **`$PWD/.env`** — the current working directory. Whichever project you `cd` into, that one is read. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — the per-user global location; this is what `flower setup` writes. (`env.py:51`, `:39-42`)
5. **`.env` at the source repository root** — three levels up from `flower/core/env.py`. Exists only when running from source; a flower installed with pip / pipx / uv lives in site-packages and has no such file. (`env.py:52`)
6. **The `env` block of `~/.claude/settings.json`, then `~/.claude/settings.local.json`** — the last fallback, **only the 9 credential keys**. (`env.py:56-75`, `:109-111`)

**Which file wins**: item 3 (project `.env`) beats item 4 (global `.env`), item 4 beats item 5 (repo-root `.env`), all three beat item 6 (Claude Code's configuration), and none of them beats item 1 (the process environment).

The mechanism is "**a key that already has a value is never overwritten**" (`env.py:90-93`): earlier entries claim keys first, later ones only fill gaps. So priority is **computed per key, not per file** — if the project `.env` only sets `ANTHROPIC_BASE_URL`, the token can still come from the global one. The first value seen for a given key is final.

Item 6 is enabled only during **automatic lookup**. Given an explicit path (`load_dotenv("/path/to/.env")`), only that one file is read, with no fallback at all (`env.py:86-87`, `:109`).

### Item 6: borrowing Claude Code's token {#借用}

`~/.claude/settings.json` and then `~/.claude/settings.local.json` are read in order, `data["env"]` is taken as a dict, and these 9 keys are picked out of it (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

If the file does not exist, cannot be read, or is not valid JSON (`OSError` / `ValueError`), an empty dict is returned and execution continues — **a broken fallback must not take the run down with it** (`env.py:62-63`, `:66-69`).

The position taken in the code is: what is borrowed is only "where to find the token". Nothing else in settings.json (permission rules, hooks, model settings) is taken over, so this does not violate the portability promise of `setting_sources=[]` (`env.py:17-19`, `:59-61`). `install.sh:77` advertises it as a feature: someone with Claude Code already configured on the machine never even sees a configuration screen.

!!! warning "The in-product error text says the opposite of the actual behavior"
    When no credentials can be found at all, the last line of the error flower prints is:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, the line itself at `:192`; the same claim also appears in `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **The code is authoritative: it does read them.** `env.py:56-75` plus `:109-111` explicitly read those two files, and `install.sh:77` sells it as a feature. That message is currently misleading — on a machine that has Claude Code configured, your token very likely came from exactly there.

## `.env` parsing rules {#env-解析}

The parsing rules are short enough to memorize (`env.py:95-107`, 13 lines): `strip` each line, skip empty lines, lines starting with `#`, and lines without `=`; split what remains at the **first** `=` into key and value, `strip` both sides, then run the value through `.strip("'\"")` — leading and trailing single or double quotes are removed unconditionally, **they do not have to be paired**.

**These forms are accepted**:

| Form | Result |
|---|---|
| `KEY=VALUE` | fine |
| `KEY = VALUE` | fine — spaces around the equals sign are stripped |
| `KEY="VALUE"` / `KEY='VALUE'` | fine — surrounding quotes are removed |
| `KEY=a=b` | the value is `a=b` — split at the first `=`, later equals signs stay in the value |
| `# comment` | whole line skipped |
| blank line | skipped |

**These are not**. Writing them raises no error; you silently get an unexpected value:

| Form | Actual result |
|---|---|
| `export KEY=VALUE` | the key becomes `export KEY`; `KEY` itself still has no value |
| `KEY=value # note` | the value is `value # note` — trailing comments are not stripped |
| `KEY=$OTHER` | the literal `$OTHER`; no variable interpolation |
| multi-line value (quoted across lines) | processed line by line; the second line has no `=` and is skipped entirely |

**An empty value claims the key.** If `ANTHROPIC_AUTH_TOKEN=` appears in a higher-priority file, `take()` executes `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, so later files cannot fill it in because "the key already exists" (`env.py:90-93`); meanwhile `check_credentials()` tests truthiness, and an empty string still counts as unconfigured (`env.py:186`). **The result is no credential and no fallback.** If you do not want a key, delete the whole line; do not leave an empty one.

## The price of portability {#可移植性}

That one line in `build_options()` is the entire mechanism (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` is `Runtime`'s default, and **no command-line flag can turn it off** — turning it off requires the Python API, `Runtime(portable=False)`, which makes it `["project"]`, i.e. the project's `.claude/` is read.

### What gets isolated

| Isolated | Consequence |
|---|---|
| The host's `~/.claude/` settings | Permission rules, hooks and model settings there have no effect. **Credentials are the one exception**, see [borrowing](#借用) |
| The project's `.claude/` | Same; only read when `portable=False` |

Domain capability does not travel this path — it ships with the repository and is loaded via `plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`, `:210-212`), see [Deployment](deploy.md). Domain instructions are **appended** after Claude Code's native system prompt rather than replacing it (`agent.py:198-202`), so specialization does not cost general capability.

### What to carry to another machine

- **Credentials: one file.** Copy `~/.config/flower/.env` over, or configure it again on the new machine. Without it nothing runs — nothing is inherited automatically.
- **Continuity state: whole directories.** `runs/` (session store, manifest, lineage) and `.flower/` (workbench).
- **But the paths must match.** `lineage.json` stores the absolute path of the workspace; if it does not match, it is treated as absent and silently falls back to a new session, **with no error** (`lineage.py:65-66`). The reason is that the SDK derives `project_key` from the workspace path (`/`, `_`, `.` all become `-`, `runtime.py:40-41`), so once the directory moves, old `session_id`s can no longer be found.

## Disk layout {#磁盘布局}

One flower run writes two trees: `<run_dir>/` holds the accounting and the sessions, `<workspace>/.flower/` holds the [workbench](glossary.md#工作台). Both default to the current directory, but **their base points differ**.

!!! warning "`runs/` follows the current directory, not `-w`"
    `-r/--run-dir` defaults to `"runs"`, and what `Runtime` does with it is `Path(run_dir).resolve()` (`runtime.py:93-94`) — relative to the **current working directory**, not to the workspace given by `-w`. Running `flower -w /path/to/proj` from `~` puts the session store in `~/runs/`, not in the project.

### `<run_dir>/` — default `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, the full transcript (including each subagent's own)
  manifest.json      Run manifest: session_id / cost / retries / failure reason per step, accumulated across processes
  lineage.json       Lineage: step name → session_id; how a second run in the same directory picks up
  aside/             A separate Runtime for oracle Q&A, with its own sessions.db + manifest.json
  workbench/         Only on the run / once path when -W was given
```

| Path | Content | Source |
|---|---|---|
| `runs/sessions.db` | The full transcript. Written by `PruningSessionStore`; the three-layer policy is [below](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | A JSON array, the [run manifest](glossary.md#运行清单), **accumulated across processes**. Fields in the table below | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Written to `.tmp` first, then `replace`d — atomic | `lineage.py:31`, `:87-97` |
| `runs/aside/` | The separate Runtime for the [oracle](glossary.md#旁路顾问). **Its cost and lineage do not mix into the main manifest** | `cli.py:632-634` |
| `runs/workbench/` | The default workbench location for `Runtime(workbench=True)`, outside the workspace. The `go` path does not use it | `runtime.py:148-151` |

Each row of `manifest.json` is `asdict(StepResult)` plus two patches (`runtime.py:44-71`, `:579-582`):

| Field | Type | Meaning |
|---|---|---|
| `step` | `str` | Step name. Four forms: `<name>`, `<name>#round<N>` (sent back for rework), `<name>#retry<N>` (plain retry), `<name>·判定#<N>` ([judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | The [session](glossary.md#会话) still alive at the end of this step |
| `ok` | `bool` | Whether it succeeded |
| `cost_usd` | `float` | What this step cost |
| `num_turns` | `int` | How many turns it took |
| `text` | `str` | The final reply of this step |
| `error` | `str \| None` | Failure reason. `killed-by-signal` when killed by SIGHUP / SIGTERM (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Epoch seconds |
| `attempts` | `int` | Actual number of attempts. `>1` means it retried |
| `errors` | `list[str]` | Failure reasons across attempts. **Only here; the model never sees them** |
| `resumed` | `bool` | Whether it resumed from the interruption point rather than starting over |
| `retired` | `list[str]` | The session_ids burned during [handoff](glossary.md#换代) in this step, in order |
| `context` | `int` | The context size the [main thread](glossary.md#主线程) actually saw on the last turn |
| `duration_s` | `float` | Patched in by hand — it is a `@property`, so `asdict()` misses it |
| `run` | `str` | Marker for this process, `YYYYmmdd-HHMMSS-<6 hex digits>`. **Must be unique per instance** |

The write strategy is **append, never overwrite**: before each flush the file is re-read, rows whose `run` equals this process's are replaced with the latest version, and everyone else's rows are left untouched (`runtime.py:564-586`). So several flowers running in parallel in the same directory do not clobber each other's books.

Everything under `runs/` is plain data; you can browse it offline at any time with sqlite3 or [`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — the workbench {#工作台目录}

```text
.flower/
  INDEX.md      Auto-generated index, injected into the main agent's system prompt
  scripts/      Scripts meant to be run a second time. The first line `# desc: one sentence` shows up in the index
  artifacts/    Long outputs over 2000 characters: reports, data, logs
  notes/        Decision records that cross steps
  spill/        Spilled large tool results; filename = first 16 chars of the content's sha256 + `.txt`
```

The three subdirectories and the index are created by `Workbench` (`workbench.py:73-92`). `INDEX.md` goes through the session-level `system_prompt.append`, so **subagents do not inherit it** — which means the rule "write long output to `artifacts/`" must be restated by the [coordinator](glossary.md#协调者) in the [task brief](glossary.md#任务书); that is the only channel.

The `go` path always generates these under `notes/`:

| File | Content | Source |
|---|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goal / acceptance criteria / boundaries / unknowns and assumptions | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Two frozen sections: goal / verdict checklist | `workflow/goal.py:124` |
| `notes/问答记录.md` | An appended record of every Q&A, including inbox entries the human volunteered. **Never enters context; archival only** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书). The previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `lineage.json` + `需求.md` + `目标.md` archived by `--new` / `/new` (**moved, not deleted**) | `lineage.py:100-117` |

**With `--isolate` the workbench moves outside the repository**: `<parent of workspace>/.flower-<workspace name>/` (`starter.py:47-55`). A worktree is each agent's private copy; the workbench is the layer shared across agents, and shared things cannot live inside a private fence. In that case the paths handed to the model are absolute (`workbench.py:69-71`, `:142-145`).

**`spill/` has two writers with different placement rules**:

| Who writes | When | Where | Threshold |
|---|---|---|---|
| `spill_guard` (`PostToolUse` hook) | **before** the tool result reaches the model | `<workbench root>/spill/` (`guard.py:130`) | `spill_threshold`, default 4000 characters |
| `TrimPolicy` (at `load`) | when replaying history before a resume | `<workspace>/.flower/spill/` — a fixed string relative to the workspace (`trim.py:49`, `:303`) | `min_chars`, default 2000 characters |

Under the default layout these are the same directory. But once the workbench moves (with `-W` putting it in `runs/workbench/`, or `--isolate` putting it outside the repository) they split — `TrimPolicy`'s copy always stays inside the workspace, because the agent's `Read` has to be able to reach it.

What `spill_guard` substitutes is not one line but a pointer line plus the **first 400 characters** (`guard.py:132-140`). Calls that read the spill file itself are let through, otherwise "use Read for the full text when you need it" would be empty words — the read comes back over threshold, gets spilled again, forever (`guard.py:155-170`).

### The schema of `sessions.db` {#sessions-db}

Three tables; the DDL is at `stores/sqlite.py:27-51`:

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

| Table | What one row is | Notes |
|---|---|---|
| `entries` | One transcript entry; `payload` is the raw JSON | `uid` is the entry's `uuid`, used as an **idempotency key**: failed batches are retried 3 times and the replay must not produce duplicate rows. Entries without a `uuid` (titles, labels, mode markers) are not deduplicated, hence the unique index carries `WHERE uid IS NOT NULL` |
| `meta` | The cursor for one session | `next_seq` is the next sequence number; `mtime` is a millisecond timestamp and is **strictly monotonic** (`sqlite.py:72-79`) — `list_sessions` and the summaries share this clock, and non-monotonicity makes the SDK's newer/older check take the wrong fast path |
| `summaries` | The summary sidecar for one main thread | **Only main transcripts participate**; subagents' do not (`sqlite.py:122-123`) |

How `store_key` is built (`sqlite.py:54-58`): `<project_key>/<session_id>`, with a further `subpath` segment for subagents. `project_key` is derived by the SDK from the workspace path — `/`, `_`, `.` all become `-`.

A look at a real sample ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

That one has 956 `entries`, 10 `meta`, 4 `summaries` — of the 10 sessions, 4 are main transcripts and 6 belong to subagents, and `summaries` is exactly the number of main transcripts.

## The three session-store layers {#会话存储}

!!! note "The three layers are an inheritance chain, not an optional combination"
    `PruningSessionStore` extends `TrimmingSessionStore` extends `SqliteSessionStore`. `Runtime` **always** constructs the outermost one (`runtime.py:109-112`), and its constructor has no entry point for swapping the backend. The way to "turn off a layer" is to set its policy object's `enabled` to `False`, not to swap the class.

`append` (the write path) always persists everything, unchanged. The three layers only affect `load` (the copy fed back to the model). The actual order of `load` is:

```text
SqliteSessionStore.load     read everything from the entries table, ordered by seq
  → TrimmingSessionStore.expire()   time-sensitive Bash results → replaced with "expired"
  → TrimmingSessionStore.trim()     old large tool_results → spilled + replaced with a pointer
    → PruningSessionStore.prune()   synthetic error messages / old denied calls → dropped whole and the chain relinked
```

| Layer | Class | What it drops | Criterion |
|---|---|---|---|
| 1 | `SqliteSessionStore` | nothing | — |
| 2 | `TrimmingSessionStore` | the bodies of large tool results, expired ephemeral command results | size + freshness |
| 3 | `PruningSessionStore` | disconnect residue, old denied calls | whether it is an error |

Layer 2 is [trimming](glossary.md#裁剪), layer 3 is [pruning](glossary.md#剪除) — **trim drops by size and value, prune drops by whether something is an error**; do not conflate them. Full signatures in [Python API](api.md).

### `SqliteSessionStore` — the foundation {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

A SQLite implementation with zero external dependencies. To switch to Postgres / S3 / Redis, implement the same protocol; the SDK ships a conformance suite, `claude_agent_sdk.testing.session_store_conformance`, that verifies it directly (`sqlite.py:1-8`).

Besides the protocol methods there are three **synchronous** queries for flower's own use:

| Method | Returns | Purpose |
|---|---|---|
| `projects()` | `list[str]` | The `project_key`s that actually exist in the database. The SDK derives it from cwd; confirm with this before querying instead of guessing |
| `has_session(project_key, session_id)` | `bool` | Reads one row of `meta` only, no payload. Check before [continuity](glossary.md#接续) starts — resuming a nonexistent session only blows up after the subprocess is already up, by which point money and time are spent |
| `last_context(project_key, session_id, scan=60)` | `int` | How large a context this session saw on its last turn. Scans backwards over the last 60 entries only. `input_tokens` plus both `cache_*` counts — looking at the first alone is near 0 on a cache hit and badly underestimates |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Two orthogonal rules. `TrimPolicy` governs **size**:

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `keep_recent` | `int` | `20` | The most recent N `tool_result`s keep their original text — context in active use should not be trimmed |
| `min_chars` | `int` | `2000` | Anything shorter is not trimmed. Replacing it with a pointer would cost more tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Archive directory, **relative to workspace**. Must be inside the workspace or the agent's `Read` cannot reach it |
| `enabled` | `bool` | `True` | `False` under `Runtime(trim=False)` (the default) |

The trimmed body is written as `<first 16 chars of sha256>.txt`, and the original position is replaced with `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` governs **freshness**: results from `git status`, `ls`, `ps` and the like are short and would never be trimmed on size grounds, but their correctness decays with time — a `git status` from 20 turns ago is not "useless", it is **misleading**.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converted from `Runtime(ephemeral=…)`; **on by default** |
| `keep_recent` | `int` | `6` | The most recent N keep their original text. Much smaller than `TrimPolicy`'s 20 — for this kind of thing the "recent" window is inherently short |
| `max_chars` | `int` | `2000` | Above this it is handed to `TrimPolicy` to spill and archive, and does not go down this path |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Replacement text |

Applies only to results of the **Bash** tool, and only when the command matches `EPHEMERAL_CMD`. `Read` is not included: file content does not decay with time to the point of being misleading, and it may be exactly what the model's reasoning rests on (`trim.py:153-160`). Expired content is **not spilled** — archiving a stale `git status` is pointless; rerunning it gives you a fresh one.

The predicate is `is_ephemeral(cmd)`, and it **is simultaneously the permission list handed back to the coordinator**: `delegate_guard(allow_glance=True)` uses the same function (`trim.py:63-68`, `:128-150`). The two sets must stay identical — allowed but not trimmed, and a stale `git status` occupies context forever; trimmed but not allowed, and the coordinator dispatches a subagent for a single `ls`, paying 4.3k of startup cost for a few dozen characters. Adding a command to the allowlist says both of these things at once.

**Which to use when**:

- You only want disconnect residue kept out of context → do nothing; `Runtime` already defaults to `PruningSessionStore`. `trim=False` only stops large results from being trimmed; pruning still happens.
- Long runs with large tool output → `trim=True`. The CLI on the `go` path has it on by default; use `--no-trim` to turn it off.
- The [coordinator](glossary.md#协调者) has `glance=True` → `ephemeral` must stay on, for the reason in the previous paragraph.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Drop synthetic messages with `isApiErrorMessage=true` or `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | For `[Request interrupted …]` `tool_result`s, **replace the body, do not drop the block** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Replacement text for the row above |
| `keep_denials` | `int` | `1` | Keep the most recent N tool calls denied by the permission hook; earlier ones are dropped **call and result together** |

`keep_denials` is the only `Runtime` constructor parameter passed straight through to this layer (`Runtime(keep_denials=N)`). Why the default is 1 and not 0: the most recent denial is a useful signal that stops the model from retrying the same blocked command over and over within a turn. **Do not raise it** — a denied call was never executed, so its result carries no information; measured, one costs 273 characters (93 characters of refusal text plus 180 characters of the dead command verbatim), and it **misleads**: in practice, after reading a few "do not use Bash directly" messages, the coordinator stops even trying an allowed `git status` and just says "Bash is restricted, dispatch an agent to look" (`prune.py:135-148`).

Three structural red lines; violating them makes the API error out immediately:

1. **The `tool_result` block itself must remain**, only `content` may be replaced. One missing block is a "Missing Tool Result Block" (`trim.py:20-22`; `prune.py:79-92`).
2. **`isCompactSummary` / `isMeta` entries must not be touched** — they are the only surviving form of the history that was compacted away (`trim.py:179-181`).
3. **Dropping an entry means reattaching its children to its parent.** The transcript is a single `parentUuid` chain; the harness walks back from the leaf, and wherever the chain breaks, all earlier history is lost (`prune.py:95-122`). This is why `relink()` must receive the complete list **including** the entries to be dropped, and does the filtering itself.

**Not one character of the original in SQLite is changed** — the three layers only affect "the copy fed back to the model" (`trim.py:18`; `prune.py:8`).

## Offline resilience {#韧性}

A long-horizon workflow runs for hours, so the network will drop at least once. The default behavior is bad: the moment it drops, the harness stuffs a synthetic assistant message into the transcript (`model="<synthetic>"`, `isApiErrorMessage=true`) with the body `API Error: Can't reach the API server …`; it becomes the leaf of the session, so a later resume feeds it back as "what the model just said" and the model thinks it is discussing a network failure; it also leaks into `StepResult.text` and rides the workflow into the next step's prompt (`resilience.py:1-22`).

The [resilience](glossary.md#韧性) layer does three things, all of them required: probe, resume instead of restart, and keep errors out of context.

### `Resilience` parameters {#resilience}

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converted from `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Maximum attempts for one [step](glossary.md#步骤), **including the first** |
| `base_delay` | `float` | `4.0` | Exponential backoff base, seconds |
| `max_delay` | `float` | `120.0` | Backoff ceiling, seconds |
| `probe_timeout` | `float` | `5.0` | Timeout for a single probe, seconds |
| `probe_interval` | `float` | `15.0` | How often to probe while offline, seconds |
| `max_offline_wait` | `float` | `3600.0` | Maximum time to wait while offline. Default 1 hour — longer than that is usually not jitter, something is genuinely broken |
| `retry_unknown` | `bool` | `True` | Retry errors that cannot be classified. Most unknown errors are transient, and fatal ones are already blocked separately |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | What is said to the model when resuming |

The backoff formula (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

That is `±25%` jitter, so a crowd of processes does not charge in the instant the network recovers. With the defaults: the 1st backoff is 4 seconds (3~5 in practice), the 2nd is 8 seconds (6~10), and from the 5th on it caps at 120 seconds (90~150).

### Probe strategy {#探针}

- **It probes the host:port of `ANTHROPIC_BASE_URL`**, not `api.anthropic.com` (`resilience.py:67-72`). With a self-hosted gateway, the latter being reachable says nothing about the former.
- **DNS plus a TCP handshake only**: `getaddrinfo`, then `connect_tcp`, then close immediately. No HTTP, no credentials, no cost (`resilience.py:75-85`). The probe must be free, otherwise "probe every 15 seconds while offline" becomes the failure itself.
- Any failure counts as unreachable — no distinction between DNS being down and TCP being refused.
- `wait_online()` blocks there: returns `True` when it comes back, returns `False` after `max_offline_wait` elapses. On the first unreachable result it prints one notification line, `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, and on recovery one more, `<host>:<port> 恢复,继续`, with **nothing in between** (`resilience.py:126-140`).

The credential probe before a run starts is a different thing: it really does send one `POST <BASE_URL>/v1/messages` with `max_tokens=16` and a default timeout of 20 seconds (`env.py:126-181`). **Do not set `max_tokens` to 1** — measured, a model with forced chain-of-thought cannot even fit its thinking in, and the server struggles for 30 seconds before returning; 16 takes only 3.6 seconds (`env.py:120-123`).

### Error classification {#错误分类}

`classify(text)` returns one of three. **Fatal is checked first**: text for things like a 401 often also contains a word like "connection", and the reverse order would wait forever (`resilience.py:53-64`).

| Class | What it matches (regexes at `resilience.py:37-50`) | Behavior |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Stop immediately, no retry. The result is the same however many times you retry, and each one costs money |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Wait for the network, then resume |
| `unknown` | matches nothing | Retried as well when `retry_unknown=True` (the default) |

Separating retryable from non-retryable is the core of this layer: **network jitter deserves waiting, a bad credential deserves an immediate stop** — waiting forever is right when the network is down, and pure wasted time when the key is wrong.

### What is kept out of context {#错误不进上下文}

1. **Synthetic error messages.** `PruningSessionStore` drops them whole at `load` time and relinks `parentUuid` (`prune.py:27-32`, `:191-195`). **They stay in SQLite untouched**; they are simply not fed back.
2. **In the event stream they carry `kind="error"` rather than `"text"`**, so they never reach `StepResult.text` and thus never ride the workflow into the next step's prompt (`resilience.py:17-18`).
3. **`resume_prompt` deliberately contains no error detail.** The model needs to know "you were interrupted, keep going"; it does not need to know whether it was `ENOTFOUND` or a `503`. **That belongs in the log, not in context** (`resilience.py:112-113`). For the log, look at the `errors` field in `manifest.json`.

Resume instead of restart: by the time a failure happens the `session_id` is already in hand, so resume picks up from the interruption point and the cost already spent is not wasted.

## Related {#相关}

- [Command line](cli.md) — how each flag maps onto the configuration on this page.
- [Python API](api.md) — the full signatures of `Runtime`, the three stores, and `Resilience`.
- [Deployment](deploy.md) — running in a container, distributing domain capability as a plugin.
- [Glossary](glossary.md) — the precise meaning of every term used on this page.
