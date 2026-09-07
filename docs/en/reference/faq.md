# FAQ & troubleshooting

When something breaks, you don't know which module broke — you only know what you saw. So this
page is grouped by **what you observed**, not by subsystem.

Every entry has the same shape: **Symptom** (what you actually see) → **Cause** → **What to do**.

Five of them are **known defects**, not intended behavior. Those entries say outright that it's a
bug, link the issue, and give a workaround — they don't dress the bug up as a design decision.

## Won't install / won't run {#装不上}

The full install procedure is in [install.md](../getting-started/install.md#一句话安装). This
section only collects the "it installed, but the command won't run" cases.

### Python older than 3.10 {#python-版本}

**Symptom**: syntax errors during install, or pip flatly says no matching version was found.

**Cause**: flower requires Python ≥ 3.10. The only runtime dependency is `claude-agent-sdk`, whose
native binary ships inside its wheel — so a failed install is usually the interpreter version, not
the network.

**What to do**: first confirm which interpreter you're installing into.

```bash
python3 --version
```

Below 3.10, switch interpreters and install again. The system `python3` is often not the one your
shell's `python` points at; checking the version before installing is cheaper than debugging after
(see [install.md](../getting-started/install.md#装之前确认-python)).

### It installed, but `flower: command not found` {#command-not-found}

**Symptom**:

```text
zsh: command not found: flower
```

**Cause**: the package installed fine, but the directory holding the generated executable isn't on
`PATH`. That's a different thing from "it didn't install" — if `python3 -c "import flower"` doesn't
error, the package is fine.

**What to do**: the `flower` script's shebang is an absolute path, so symlinking it into a directory
already on `PATH` is enough; you don't need to source anything.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: I added the PATH line `install.sh` printed, still command not found {#macos-path}

!!! warning "Known issue ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    This advice happens to be wrong on exactly the machine that needs it.

**Symptom**: you run `install.sh` on macOS, follow its closing hint to add `~/.local/bin` to `PATH`,
reopen the terminal, and `flower` is still command not found.

**Cause**: when it falls through to the pip path, macOS's pip installs the executable into
`~/Library/Python/3.X/bin`, while `install.sh` tells you to add `~/.local/bin`. The two directories
don't match, so following the hint changes nothing.

??? note "The order `install.sh` picks install methods in, and the exact hint it prints"

    The priority chain has four steps, not two (`install.sh:35-56`):

    ```text
    1. 有 uv        → uv tool install --force
    2. 否则有 pipx  → pipx install --force
    3. 否则         → curl astral.sh/uv/install.sh 自举 uv,成功则用 uv 装
    4. 自举也失败   → "$PY" -m pip install --user --upgrade    ← 出问题的是这一条
    ```

    The exact PATH hint at the end (`install.sh:62-68`, printed only when `command -v flower` finds
    nothing):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` is hardcoded to `$HOME/.local/bin` (`install.sh:63`). That's correct for paths 1 and 3
    — uv installs there; **only path 4, the pip fallback, is wrong on macOS**. So this trap only
    shows up on machines where the first three paths all failed.

**What to do**: don't guess the directory, ask the interpreter.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Add the printed directory to `PATH`, or symlink out of it into `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip installed three different flowers {#三种装法}

**Symptom**: `flower` runs, but source edits have no effect; or it's still the old version after an
upgrade; or two terminals on the same machine behave differently.

**Cause**: the three install methods put the package and the executable in different places, and
whichever `PATH` hits first is what runs.

??? note "Where each install method lands"

    | Install method | Executable | When to use |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | You're editing source. Edits take effect immediately |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Use only, no edits, want an isolated env |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Directory as above |

**What to do**: first confirm which one is running, then decide which one to edit.

```bash
which -a flower                      # 列出 PATH 上所有同名的
head -1 "$(which flower)"            # shebang 指向哪个解释器,包就在那个环境里
```

If you're editing source, use venv + `-e .`, and don't let it coexist with a `uv` / `pipx` install —
debugging the coexistence costs far more than one clean reinstall
(see [install.md](../getting-started/install.md#从源码装)).

## Credentials and gateways {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptom**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Cause**: flower seals off host configuration with `setting_sources=[]`, so credentials must be
supplied explicitly. The full lookup order is in
[config.md](config.md#凭证查找优先级).

**What to do**: put them in `.env` at the repo root, or in the process environment.

```bash
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY
```

`.env` is already gitignored. For containers, see [deploy.md](deploy.md#凭证).

### It says "flower doesn't read `~/.claude/settings.json`" — that line is wrong {#settings-json}

**Symptom**: when credentials aren't configured, `env.py:192` prints:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Cause**: that line contradicts the code. `env.py:56-75` **does read** `~/.claude/settings.json`,
takes only the credential fields out of it, and uses them as the last-resort fallback — which is
exactly what `install.sh` advertises. The line only prints after that fallback has already come up
empty, so it never causes a failure; but it leads people to conclude "flower can't use my Claude
Code token", which is false. Tracked in
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**What to do**: if you have Claude Code installed locally, you don't need new credentials — the
fallback picks them up
(see [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
If you actually see this line, that file has no usable credential field either — write a `.env` as
described above.

### Not sure which credentials and endpoint are actually in effect {#生效值}

**Symptom**: you changed `.env`, but requests still hit the old gateway; or you can't say which
model is in use.

**Cause**: credentials and endpoints come from several sources (process environment, `.env`,
fallback). Who wins isn't decided by the config file, it's decided at runtime.

**What to do**: start once with `-v`. On startup it prints `describe()`: the effective `BASE_URL`
and model mapping, with the token masked.

```bash
flower -v
```

Full flag list in [cli.md](cli.md#全局开关); full variable list in
[config.md](config.md#环境变量).

### A bare `KEY=` in `.env` blocks every lower-priority source {#空值占位}

**Symptom**: you exported a token in the process environment, `.env` also has a line
`ANTHROPIC_AUTH_TOKEN=`, and it still reports missing credentials.

**Cause**: an empty value is still an assignment. A `KEY=` in a higher-priority source **occupies**
that key, and lower-priority sources won't fill it in; meanwhile `check_credentials()` (defined at
`env.py:184`) tests for "value non-empty", so it still reports it as missing. "Occupied" and
"missing" are two different things that look identical — that's what makes this class of problem so
hard to spot yourself.

**What to do**: delete the whole line; don't leave empty values behind.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # 列出所有空值行
```

After deleting, confirm the effective values once with `-v`. Parsing rules are in
[config.md](config.md#env-解析).

### Third-party gateway: connects, but fails on the first turn {#网关}

**Symptom**: 401 / 403; or it reports the model name doesn't exist; or it does a
[handoff](glossary.md#换代) right at the start and complains about the "startup floor".

**Cause**: three kinds of misconfiguration, each with a distinct symptom.

??? note "Three gateway misconfigurations and how to tell them apart"

    | Symptom | Usually | Where to fix |
    |---|---|---|
    | 401 / 403 | The credential is valid but wasn't issued by this gateway; or `BASE_URL` is missing a path or has a trailing slash | [config.md](config.md#凭证变量) |
    | Model name doesn't exist | The gateway only knows its own model names and the mapping isn't configured | [config.md](config.md#模型变量) |
    | Handoff right at the start, complains about "startup floor" | Window set too small: the threshold is below the role's startup floor (the [coordinator](glossary.md#协调者) measures around 34k) | `--window`, see [handoff.md](../guide/handoff.md#阈值怎么算) |

**What to do**: run `-v` to print the effective values before touching config. The window is
especially worth checking — the gateway on the development machine is configured as
`claude-opus-5[1m]`; computing against 200k would hand off every 150k, when it can actually run to
950k — **a factor of 5**, and [long-horizon](glossary.md#长程) work gets shredded.

---

## It runs but behaves wrong {#行为不对}

None of the symptoms in this group are errors: **the command completes, the exit code is 0, and the
wrong thing happened**. The first four are confirmed code defects with issues filed; what's given
here are workarounds, not fixes. The last one is intended behavior.

### `flower setup` starts an agent instead {#setup-跑成了-agent}

**Symptom**: you run `flower setup` expecting it to ask for an endpoint and a token; instead it asks
"what do you want done", then runs the whole go workflow treating the word `setup` as the task
description. When it finishes, not a single credential has been written.

**Cause**: `_CMDS` at `cli.py:758` lists only `"go"`, `"run"`, `"once"` — `"setup"` is missing. The
default-subcommand step therefore rewrites argv `["setup"]` into `["go", "setup"]` — `setup` is
demoted from a subcommand to `go`'s first positional argument, i.e. the request itself.
**No argv can reach the config wizard.** Filed as
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**What to do**: Ctrl-C out and write the config file directly. Writing to that file is all `setup`
ever did:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Full variable names and credential lookup order are in [config.md](config.md#凭证变量).
Once written, run `flower -v` from any directory; the effective endpoint printed at startup is your
verification.

### A full-width `？` doesn't trigger the oracle {#全角问号}

**Symptom**: following [oracle Q&A](cli.md#旁路问答), you type `？这个目录能删吗` at the input
prompt. It doesn't dispatch the [oracle](glossary.md#旁路顾问) — it treats the sentence as an answer
to the current question, or files it verbatim into the inbox.

**Cause**: `cli.py:733` performs two consecutive `startswith("?")` checks, **both against the same
ASCII character**. By the code's intent, the second should have tested the full-width `？`. Chinese
IMEs produce the full-width one by default — so the feature's primary users are exactly the ones who
can't use it. Filed as [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "This one contaminates the requirements"
    A `？` that misses doesn't error and doesn't get dropped. It's handled as ordinary input:
    during the clarify phase it counts as the answer to the current question, otherwise it goes into
    the inbox.
    **A sentence you only meant to ask on the side gets written into the brief.** If you notice the
    mistake, fix `.flower/notes/需求.md` on the spot — that file is what downstream goes by.

**What to do**: switch to half-width and type `?`, or type the half-width `?` first and then switch
back to Chinese for the body.

### `once` always shows `$0.00` spent and `0:00` elapsed {#once-计数为零}

**Symptom**: `flower once` runs start to finish, and the status line at the bottom keeps showing
`累计 $0.00` and a timer stuck at `0:00`, while the same model on the same work shows real numbers
under `go`.

**Cause**: `once`'s `render()` **constructs a new `Render` for every event received**, so the
accumulators are rebuilt with it and start from zero each time. The totals are being repeatedly
zeroed, not left uncounted. Filed as
[#14](https://github.com/ChenyuHeee/flower/issues/14).

**What to do**: if you need accurate numbers, use `go` — that path is unaffected. If you want
`once`'s single-turn shape and still want the accounting, check `runs/manifest.json` afterwards —
per-step cost is recorded there, and that record is correct. Details in
[config.md](config.md#run-dir).

### A skill dropped into `plugin/` is never loaded {#plugin-不加载}

**Symptom**: you write a skill per [deploy.md](deploy.md#写一个-skill完整例子), the directory
structure is right, but the agent behaves as if it doesn't exist — **no error, not one log line**.

**Cause**: `plugin/` isn't packaged into the wheel. In an installed package, `PLUGIN_DIR` points at
`<site-packages>/plugin`, that directory doesn't exist, and the existence check before loading
silently skips. **All three `install.sh` paths hit this**; only a source checkout can load skills.
Filed as [#15](https://github.com/ChenyuHeee/flower/issues/15).

**What to do**: first check where the path actually resolves.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

If it prints `False`, this is your issue. Right now there is exactly one way to use skills: **run
from a source checkout**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

An `-e` install points the package back at the checkout, `PLUGIN_DIR` lands on the real `plugin/`,
and rerunning that check prints `True`.

### `-T` has no visible effect on `go` {#trim-与-go}

**Symptom**: you add `-T` to `flower go`, compare with and without, and behavior is identical — as
if the flag were broken.

**Cause**: **this one is by design, not a defect.** The `go` path enables
[trimming](glossary.md#裁剪) by default, so `-T`'s intent is already satisfied and asking again
changes nothing. The meaningful switch on this path is the inverse `--no-trim` — you only need to be
explicit to turn trimming off. `-T` is a meaningful switch only on `run` and `once`.

**What to do**: to confirm trimming is on under `go`, read the startup print with `-v`; don't infer
it from the presence of `-T`. To turn it off, pass `--no-trim`. Full flag semantics are in
[cli.md](cli.md#全局开关).

## It says it's done but it isn't {#没做完}

The [goal guard](../guide/goal.md) exists precisely to catch this class — workers have a systematic
optimism bias; they know what they did, not what they missed. But the guard itself misjudges too,
and its misjudgments follow patterns. The five entries below are split into "it let through what it
shouldn't have" and "it never lets anything through".

### It says "can't be verified here", then passes {#无法达成不是未达成}

**Symptom**: the verdict reads "this item cannot be verified in the current environment, treated as
met", and the workflow moves on.

**Cause**: the [judge](glossary.md#判定者) collapsed «unachievable» and «not met» into one
conclusion. They are **different conclusions**, which is exactly the point of
[three conclusions, not two](../guide/goal.md#三个结论不是两个): «not met» means send it back and keep
working; «unachievable» means **stop and ask a human** — accept it, change the goal, or say the
judge got it wrong. With only "met/not met", a goal that genuinely can't be done makes the
coordinator spin round after round until the budget runs out.

**What to do**: **"can't verify here" can never count as met.** Spell out in the judge's
`instructions` what counts as unachievable in your setting, so it returns «unachievable» when it
should. If you truly don't want to be stopped for a question, pass `--timeout 0`: on unachievable it
stops outright, with the reason left on disk, instead of sliding through.

### It reads the source and declares it done {#判产出物}

**Symptom**: the verdict reasoning says "X is already implemented in the code", "the function
signature matches", while the build artifact, the command output, the running service — none of them
were touched.

**Cause**: the judge was pointed at source. [Judge the artifact, not the
source](../guide/goal.md#判的是产出物不是源码) — whether the source looks right and whether the
delivered thing works are two different things. The former is what the worker was already convinced
of; being convinced again produces no new information.

**What to do**: write verdict items as assertions about the **artifact**. "Export is implemented"
doesn't count; "running `./app export out.csv` produces `out.csv` with 3 header columns" does. Write
them that way when you set the goal, or the judge is left to fill in vague items on its own.

### The judge can't run commands, so it reads the Makefile and passes {#判定者不能跑命令}

**Symptom**: the goal is "build a binary that runs on Linux", and the verdict passes. You run `file`
yourself and the artifact is Mach-O, not ELF at all.

**Cause**: the judge defaults to `judge(can_run=False)`, and it has **only `Read` / `Glob` / `Grep`**.
Those three read files; they **cannot run `file`, and cannot run `./app --version`**. So it settles
for reading the Makefile, sees cross-compilation in the Darwin branch, and concludes the condition
is satisfied. It didn't lie — it **found the closest thing to evidence within its capabilities**.

??? note "When you must turn `can_run` on"
    The rule is simple: **if the goal mentions "the thing that got built", turn it on.**

    - Artifact goals: binaries, images, packages, generated data — on
    - Behavioral goals: the service starts, the command returns 0, output matches a pattern — on
    - Pure-text goals: is the doc written, was a field added to the schema — not needed

    On the command line it's `--judge-can-run`. When wiring it yourself, the entry points spell it
    differently but all end up at the same `judge()` parameter:

    | Entry point | How to pass | Source |
    |---|---|---|
    | `judge()` | `can_run=` is a real parameter | `roles.py:361` |
    | `with_goal()` | `can_run=` is a parameter, forwarded to `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **No `can_run` parameter**, but it falls into `**spec_kw`, and that line is exactly `judge(..., **spec_kw)` — so it arrives | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, turned into `with_goal(can_run=…)`; `--judge-can-run` goes through here | `starter.py:105` → `:196` |

    The cost is that the judge actually executes commands, making a verdict round slower and more
    expensive; what you get is that it verifies **the site**, not the site's documentation. See
    [Can the judge run commands](../guide/goal.md#判定者能不能跑命令).

**What to do**: if the goal is about an artifact, turn on `--judge-can-run`. When it's off, treat
"decidable by reading alone" as a hard constraint on writing verdict items — an item you can't phrase
that way is an item that needed a command in the first place.

### The verdict list has a dozen-plus items and never passes {#清单长度}

**Symptom**: every round comes back rejected with a long list of gaps, the list grows as you fix
things, and the work never finishes.

**Cause**: the list was written by "how rigorous do I want to be", not by "how many ways can this
fail". [The length of the list is set by how many ways it can
fail](../guide/goal.md#清单的长度由有多少种失败方式决定): for a
`git clone && make && ./app` task, **three to five items is enough** — it builds, it starts, it
works. In the real crash in [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了), a
"get the repo installed and running" task was written as **15 items**: only 5 verified whether
anything worked, 6 verified whether the process followed the rules, and 4 were **unverifiable in
principle**.

**What to do**: edit `.flower/notes/目标.md` — that file is what the verdict goes by. Go item by item
asking "which failure mode does this correspond to", and delete the ones you can't answer for. The
goal-setting step already flags unverifiable items; don't force them to stay.

### Boundaries written as verdict items {#边界不是判定项}

**Symptom**: the list contains items like "never ran `brew install`", "changed no files outside the
project directory", and the judge goes checking the mtime of `~/.zshrc` and whether `.flower/` was
touched, just to prove its own innocence.

**Cause**: boundaries and verdict items constrain different things; mixing them was the main cause of
the HT002 crash ([root cause one](../cases/ht002.md#根因一边界被当成了判定项)).

| | Constrains what | How it's honored |
|---|---|---|
| **Boundary** | **How you work** ("install only inside the project directory", "don't touch business code") | By **not crossing it**, not by proving it afterwards |
| **Verdict item** | **What you deliver** ("does it run", "is the result correct") | By verifying on the spot |

Boundaries are exactly the section the clarify phase encourages you to fill out. Copying them into
the list one by one means every extra boundary adds a check — and most of those checks can't be
verified, and unverifiable items drag the whole round of judgment down with them.

**What to do**: keep boundaries in the «boundaries» section of the brief, honored by not crossing
them, out of the verdict list. If you truly need an account of them, one sentence covers it —
**don't split it into six items**.

---

## Context and spend {#上下文与花费}

In long-horizon runs, context and money are the same problem: context grows until it hits the
ceiling and you either hand off or blow up the step; and everything you repeat in one round gets
paid for again in every round after it.

### Halfway through it opened a new session and said "handoff" {#换代打断}

**Symptom** A `handoff` shows up in the event stream, `payload["phase"]` goes `near` then `done`,
one extra round is spent writing the [handoff document](glossary.md#交接书), and then work continues
as normal.

**Cause** Context approached the threshold. flower **doesn't compact** — it writes the current
session's state as a five-section handoff document and starts a new session that reads it and
continues. [Compaction](glossary.md#压缩) erases the most expensive information along with everything
else — things like "paths that don't work" — whereas the handoff document is explicit, on disk, and
editable at any time: the successor session reads exactly that file.

**What to do** This is the normal path; ignore it. A handoff is not a retry — `attempts` doesn't
increase (it counts failures), the retired session_id is recorded in `StepResult.retired`, and the
externally visible `session_id` is always the live successor
(see [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
If you really want the SDK's auto-compact back, use `--no-handoff`.

??? note "Where the threshold comes from, and why the default is so aggressive"
    `at = window - headroom`. `window` **defaults to 1,000,000**, decided by model name: names
    containing `haiku` count as 200,000, everything else as 1,000,000. `headroom` defaults to 50k —
    auto-compact fires at −33k, the handoff has to get in front of it, and "writing the handoff"
    itself costs another round; 50k satisfies both.

    Guessing too high isn't a hard error: if the real window is smaller, the threshold is never
    reached, the request is rejected by the API as «prompt too long», flower recognizes that signal
    (`handoff.is_overflow()`) and hands off on the spot using a mechanically assembled degraded
    document, so the step doesn't fail
    (see [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    A measurement worth mentioning: the gateway on the development machine is configured as
    `claude-opus-5[1m]`. Computing against 200k would hand off every 150k, when it can actually run
    to 950k — **a factor of 5**, and long-horizon work gets shredded.

### It hands off right at the start, and won't stop {#一开局就换代}

**Symptom** The error mentions the "startup floor", or the same step hands off repeatedly until it
hits `max_generations=8`.

**Cause** `window` is set too small and the threshold is below this role's startup floor — measured
at about 34k for the coordinator, consumed by the system prompt plus the
[workbench](glossary.md#工作台) index alone. The new session crosses the line as soon as it opens its
mouth, so it writes a handoff, hands off, crosses again, forever (handoffs don't consume the retry
budget; that's deliberate).

**What to do** Set `--window` to the model's real window; `-v` prints the effective endpoint and
model mapping. A normal long run never reaches 8 generations, so hitting it is almost certainly this
cause, and the error message says so directly
(see [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
A related symptom is "handoffs are always degraded": the reason is in `errors` in
`runs/manifest.json`.

### It stops midway saying the budget is exhausted {#预算到顶}

**Symptom** A [step](glossary.md#步骤) stops before finishing, citing spend over the limit.

**Cause** `AgentSpec(max_budget_usd=...)` is a **hard ceiling**, not a soft warning;
`Runtime.total_cost()` is the total for this run.

**What to do** Before raising the ceiling, confirm it isn't spinning. Round after round rejected with
no progress usually means the judge should have returned «unachievable» and returned «not met»
instead — a goal that genuinely can't be done will burn until the budget is gone
(see [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirm real work is happening, then raise the ceiling.

### Why was this run so expensive {#为什么这么贵}

**Symptom** Spend far above expectation, and the output gives no clue where it went.

**Cause** The accounting isn't in the model's context. Each step's `session_id`, cost, retry count,
and failure reason are recorded only in `runs/manifest.json`, **appended across processes**. Retry
history and raw error text live only there — the model doesn't see them, and that's deliberate:
piling denied calls into context teaches the coordinator that "Bash gets blocked anyway", and it
stops even trying `git status` (`Runtime(keep_denials=1)` is already minimal; don't raise it).

**What to do** Open `runs/manifest.json` and attribute cost per step (disk layout in
[config.md#磁盘布局](config.md#磁盘布局)). Some measured reference values:

| | Cost |
|---|---|
| One subagent's startup floor (not amortizable) | ~4.3k tokens |
| The coordinator's startup floor | ~34k tokens |
| `tests/smoke.py` single-agent full chain | ~$0.21 |
| `tests/flow_demo.py` three ways to wire a workflow | ~$0.39 |
| `tests/delegation.py` delegation + measured context distribution | ~$0.71 |
| `tests/isolation.py` three issues, three worktrees | ~$0.9 |

### Context grows faster than the work gets done {#上下文涨得快}

**Symptom** Every round's [task brief](glossary.md#任务书) repeats the same discipline ("read the file
before editing", "don't touch business code", "run the tests after"), while the
[worker](glossary.md#执行者) was already doing exactly that.

**Cause** Every sentence the coordinator says goes into its own transcript, and the transcript only
grows. Restating the discipline costs money this round, **and costs it again in every round after**.
For something the other side already knows, the benefit of restating is zero and the cost is
permanent.

**What to do** Put discipline into mechanism, not into every round's speech: anything expressible via
`allowed_tools`, the brief's «boundaries» section, or the workbench index shouldn't go into the task
brief; the task brief should only carry what changed this round. Delegation itself is the layer that
saves the most
(see [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
On resume, large old tool results can be swapped for file pointers with `-T`.

## Interruption and continuity {#中断与接续}

### The process was killed, the machine rebooted {#进程被杀}

**Symptom** It died halfway, and after reopening the terminal you don't know how to pick it back up.

**Cause** There's nothing to pick up. [Lineage](glossary.md#血缘) (`runs/lineage.json`) records step
name → session_id and is written to disk at the end of every step, writing a `.tmp` first and then
atomically replacing — being killed midway can't leave half a file.

**What to do** Go back to **the same directory** and run `flower` again; each step resumes its
previous session: it won't interrogate you about the requirements again, won't re-set the goal, and
even remembers which dead ends the coordinator already tried. If you have nothing to say, just press
enter (see [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
The judge is the exception — it isn't a `Step`, it's dispatched directly from the gate and never goes
through lineage, so every round gets a fresh pair of eyes.

### It starts from scratch every time; nothing resumes {#接不上}

**Symptom** Rerunning in the same directory, it interrogates you about the requirements all over
again.

**Cause** Three kinds of mismatch, and flower **silently falls back to starting over without an
error** — [continuity](glossary.md#接续) is a bonus, and its failure shouldn't block work:

- `runs/lineage.json` is missing, or the `workspace` inside it doesn't match your current path (this
  happens when the directory was copied elsewhere)
- The session is no longer in `runs/sessions.db` (the store was deleted)
- The lineage file is corrupt

**What to do** First check whether `runs/lineage.json` exists and whether `workspace` matches
(the roles of the three files are in
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Not resuming after moving directories is **deliberate**: `project_key` is derived from the workspace
path, and old sessions aren't findable at the new location.

### I want to start over without losing history {#想重开}

**Symptom** The requirements have gone in a new direction, and you don't want it continuing from the
last pile.

**Cause** Continuing is the default. In a directory you've already used,
`flower "顺便支持代码块高亮"` isn't a new task, it's one more sentence in the same conversation.

**What to do** `--new`. It **archives, it doesn't delete**; the old material stays in
`notes/archive/`. On [wake](glossary.md#唤醒) it first reports one line of current context size; if
that looks too big, this is the path too.

### The network dropped; it neither errors nor moves {#断网}

**Symptom** No new events in the UI, the process is still alive, and it looks stuck.

**Cause** A network drop is treated as "wait a bit", not as a failure. flower hangs and waits: probes
DNS first, then TCP, and continues once it's through
(see [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
HT001 validated this against a real outage
(see [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**What to do** Wait it out; `-v` shows the probing. The errors accumulated during the wait **do not
enter the post-resume context** — they land only in `runs/manifest.json`, and the successor session
sees a clean site instead of being dragged off course by a string of timeouts.

### Two Ctrl-Cs in a row skip part of the shutdown {#双重-ctrl-c}

**Symptom** Killing with `kill` (SIGTERM) and hitting Ctrl-C twice leave different states behind.

**Cause** Known gap. A double Ctrl-C raises `KeyboardInterrupt`: in `cli.py`, `_drive`'s `finally`
calls `rt.close()` but **does not** call `rt.rescue()` — only the SIGHUP/SIGTERM handler calls
`rescue()`.

**What to do** Lineage survives on both paths (atomically written at the end of every step), so
rerunning still resumes; this gap won't lose you progress. For a complete shutdown, use `kill <pid>`
rather than mashing Ctrl-C.

## Parallelism and isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptom** Isolation won't start, reporting `not in a git repository`.

**Cause** `worker(..., isolate=True)` relies on git worktrees to give each agent a private copy; if
the workspace isn't a git repository, it can't create one.

**What to do** This one **does not degrade silently** — either run inside a real repository, or turn
`isolate` off. Isolation guarantees that several agents can edit simultaneously without seeing each
other's working tree; it does not guarantee that merges are conflict-free.

### An isolated agent can't write to the workbench {#隔离写不进工作台}

**Symptom** The subagent reports "write permission denied" and scripts and outputs never land; or
outputs land inside one worktree where the other agents can't see them.

**Cause** A worktree is each agent's **private copy**; the workbench is the **shared layer** across
agents. Put something shared inside a private fence and of course nobody else can reach it.

**What to do** With isolation on, point the workbench **outside the repository**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

When it sits outside the workspace, `Runtime` grants access automatically via `add_dirs`;
`Runtime(workbench=True)` already handles this, but a self-built `Workbench` needs the grant from
you.

!!! warning "The workbench has two defaults, and they differ"
    `Workbench(workspace)` — the path the CLI and `starter_flow()` take — puts the workbench at
    `<workspace>/.flower`; while `Runtime(workbench=True)` (i.e. `-W`) puts it at
    `<run_dir>/workbench`, that is, `runs/workbench`. So running `flower` once gives you `.flower/`,
    and calling `Runtime(workbench=True)` from Python **does not**.

### Running flower gives me `.flower/`, my own script doesn't {#两个工作台默认值}

**Symptom** The brief clearly got written to `.flower/notes/需求.md`, yet the coordinator acts as if
it never read it; **no error**.

**Cause** You have two workbench objects. The brief was written into directory A, while the index
injected into the system prompt scans directory B, and the promise "it knows where the requirements
file is from the start" **fails silently**. Both variants are silent: assembling a `brief_path`
yourself relative to the process cwd gives a different directory from the `<run_dir>/workbench` that
`-W` builds; and you can't fetch it back out of `Runtime` either — `cli.py` calls `main()` to build
the `Workflow` first and only then creates the `Runtime`, by which point `brief_path` is long since
fixed.

**What to do** Build one `Workbench` yourself and hand **the same object** to both `Workflow` and
`Runtime`; the location is then pinned:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` pins this down: assertion 5 checks that the brief appears in
`prompt_block()`. Also, the index is injected only into the **coordinator's** system prompt;
subagents don't inherit it (measured at $0.2461, `tests/prelude_live.py`) — the coordinator has to
relay the paths downward; no subagent knows them automatically
(see [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
