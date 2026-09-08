# FAQ and troubleshooting

When something breaks, you don't know which module broke — you only know what you saw. So this
page is grouped by **what you observe**, not by subsystem.

Every entry has the same shape: **symptom** (what you actually see) → **cause** → **what to do**.

Five of them are **known defects**, not design. Those entries say outright that it's a bug, give
the issue link and a workaround — they will not be dressed up as intentional.

## Won't install / won't run {#装不上}

The full install procedure is in [install.md](../getting-started/install.md#一句话安装). This
section only collects the "it installed, but the command won't run" cases.

### Python older than 3.10 {#python-版本}

**Symptom**: syntax errors during install, or pip flatly says it can't find a version that
satisfies the requirement.

**Cause**: flower requires Python ≥ 3.10. The only runtime dependency is `claude-agent-sdk`, and
the native binary ships inside its wheel — so a failed install is usually the interpreter
version, not the network.

**What to do**: first confirm which interpreter you're installing into.

```bash
python3 --version
```

Below 3.10, switch and install again. The system's `python3` is often not the one `python` points
at in your shell; checking the version before installing is cheaper than debugging afterwards
(see [install.md](../getting-started/install.md#装之前确认-python)).

### Installed, but `flower: command not found` {#command-not-found}

**Symptom**:

```text
zsh: command not found: flower
```

**Cause**: the package installed fine, but the directory holding the generated executable isn't
on `PATH`. That is a different thing from "it didn't install" — if `python3 -c "import flower"`
doesn't error, the package is fine.

**What to do**: the `flower` script's shebang is an absolute path, so symlinking it into a
directory already on `PATH` is enough; you don't need to source anything.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: added the PATH line `install.sh` told me to, still command not found {#macos-path}

!!! warning "Known issue ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    This piece of advice fails on exactly the machine that needs it.

**Symptom**: on macOS you run `install.sh`, follow its closing hint to add `~/.local/bin` to
`PATH`, reopen the terminal, and `flower` is still command not found.

**Cause**: when it falls through to the pip path, macOS's pip installs the executable into
`~/Library/Python/3.X/bin`, while `install.sh` tells you to add `~/.local/bin`. The two
directories don't match, so following the hint does nothing.

??? note "What order `install.sh` picks an installer in, and the exact text of that hint"

    The priority chain is four rungs, not two (`install.sh:35-56`):

    ```text
    1. uv present     → uv tool install --force
    2. else pipx      → pipx install --force
    3. else           → curl astral.sh/uv/install.sh to bootstrap uv, install with uv if it works
    4. bootstrap fails→ "$PY" -m pip install --user --upgrade    ← this is the broken one
    ```

    The exact text of that closing PATH hint (`install.sh:62-68`, printed only when
    `command -v flower` comes up empty):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` is hardcoded to `$HOME/.local/bin` (`install.sh:63`). For rungs 1 and 3 that's
    correct — uv installs right there; **only rung 4, the pip fallback, is wrong on macOS**. So
    this pit only opens on machines where the first three rungs all failed.

**What to do**: don't guess the directory, ask the interpreter.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Add the printed directory to `PATH`, or symlink out of it into `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip installed three different flowers {#三种装法}

**Symptom**: `flower` runs, but source edits have no effect; or an upgrade leaves you on the old
version; or two terminals on the same machine behave differently.

**Cause**: the three installers put the package and the executable in different places, and
whichever `PATH` hits first is the one that runs.

??? note "Where each installer lands"

    | Installer | Executable | When to use it |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | You're editing the source. Edits take effect immediately |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Use, don't edit; you want an isolated environment |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Directory as above |

**What to do**: first confirm which one is actually running, then decide which copy to edit.

```bash
which -a flower                      # list every match on PATH
head -1 "$(which flower)"            # the shebang names the interpreter; the package lives in that env
```

If you're editing the source, use a venv + `-e .`, and don't let it coexist with a `uv` / `pipx`
install — coexistence costs far more in debugging than one reinstall
(see [install.md](../getting-started/install.md#从源码装)).

## Credentials and gateways {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptom**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Cause**: flower isolates itself from host configuration with `setting_sources=[]`, so you must
supply credentials yourself. The full lookup order is in
[config.md](config.md#凭证查找优先级).

**What to do**: put them in `.env` at the repo root, or in the process environment.

```bash
cp .env.example .env        # fill in ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY
```

`.env` is already gitignored. For containers, see [deploy.md](deploy.md#凭证).

### It says "flower doesn't read `~/.claude/settings.json`" — that statement is wrong {#settings-json}

**Symptom**: when credentials aren't configured, `env.py:192` prints:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Cause**: that line doesn't match the code. `env.py:56-75` **does read**
`~/.claude/settings.json`, taking only the credential fields, as the last fallback rung — which
is exactly what `install.sh` advertises. The line is only printed after that fallback has already
come up empty, so it never causes a failure; but it leads people to conclude "flower can't use my
Claude Code token", which is false. Filed as
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**What to do**: if you have Claude Code installed locally, you don't need to get new credentials;
the fallback will pick them up
(see [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
If you really do see this line, that file has no usable credential field either — write a `.env`
as in the previous entry.

### Not sure which credentials and endpoint are actually in effect {#生效值}

**Symptom**: you changed `.env` but requests still hit the old gateway; or you can't say which
model is in use.

**Cause**: credentials and endpoints have several sources (process environment, `.env`,
fallback), and who wins isn't decided by a config file — it's decided at runtime.

**What to do**: start once with `-v`. On startup it prints `describe()`: the effective `BASE_URL`
and model mapping, with the token masked.

```bash
flower -v
```

Full flag table in [cli.md](cli.md#全局开关), full variable table in
[config.md](config.md#环境变量).

### A bare `KEY=` in `.env` means nothing downstream can ever fill it {#空值占位}

**Symptom**: the token is exported in the process environment, `.env` also has a line
`ANTHROPIC_AUTH_TOKEN=`, and you still get "missing credentials".

**Cause**: an empty value is still an assignment. A `KEY=` in a higher-priority source **claims**
that key, and lower-priority sources won't fill it in; meanwhile `check_credentials()` (defined at
`env.py:184`) tests for "value non-empty", so it reports missing anyway. "Claimed" and "missing"
are two different things with identical symptoms — which is what makes this class of problem
hardest to spot on your own.

**What to do**: delete the whole line; don't leave an empty value.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # list every empty-value line
```

After deleting, confirm the effective values once more with `-v`. Parsing rules in
[config.md](config.md#env-解析).

### Third-party gateway: connects, but fails on the first turn {#网关}

**Symptom**: 401 / 403; or an unknown model name; or a [handoff](glossary.md#换代) right at the
start, complaining about the "startup floor".

**Cause**: three kinds of misconfiguration, each with its own symptom.

??? note "Three gateway misconfigurations and how to tell them apart"

    | Symptom | Most likely | Where to change |
    |---|---|---|
    | 401 / 403 | The credential is valid but wasn't issued by this gateway; or `BASE_URL` is missing a path or has a trailing slash | [config.md](config.md#凭证变量) |
    | Unknown model name | The gateway only knows its own model names and the mapping isn't set | [config.md](config.md#模型变量) |
    | Handoff at the start, "startup floor" | The window is set too small: the threshold is below the role's startup floor ([coordinator](glossary.md#协调者) measures around 34k) | `--window`, see [handoff.md](../guide/handoff.md#阈值怎么算) |

**What to do**: print the effective values with `-v` before touching config. The window is
especially worth checking — the gateway on the development machine is configured as
`claude-opus-5[1m]`; assuming 200k would hand off every 150k, when it actually runs to 950k, a
**5× difference**, and [long-horizon](glossary.md#长程) work gets chopped to pieces.

---

## It runs, but does the wrong thing {#行为不对}

The symptoms in this group aren't errors: **the command completes, exit code 0, and it did the
wrong thing**. The first four are confirmed code defects with issues filed; what's given here is
a workaround, not a fix. The last one is by design.

### `flower setup` starts an agent {#setup-跑成了-agent}

**Symptom**: you run `flower setup` expecting it to ask for endpoint and token, and instead it
asks "what do you want done", then runs the whole go workflow, treating the word `setup` as the
task description. When it finishes, not one character of credentials has been written.

**Cause**: `_CMDS` at `cli.py:937` lists only `"go"`, `"run"`, `"once"` — `"setup"` is missing.
The default-subcommand step then rewrites argv `["setup"]` into `["go", "setup"]` — `setup` is
demoted from a subcommand to `go`'s first positional argument, i.e. the request itself.
**No argv reaches the config wizard.** Filed as
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**What to do**: Ctrl-C out and write the config file directly. All `setup` was ever going to do
is write into that file:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Full variable names and credential lookup order in [config.md](config.md#凭证变量).
Afterwards run `flower -v` from any directory; the effective endpoint printed at startup is your
check.

### A full-width `？` doesn't trigger oracle Q&A {#全角问号}

**Symptom**: following [oracle Q&A](cli.md#旁路问答), you type `？这个目录能删吗` at the input
prompt, and it doesn't spin up an [oracle](glossary.md#旁路顾问) — it treats the line as an answer
to the current question, or files it verbatim into the inbox.

**Cause**: `cli.py:907` does two consecutive `startswith("?")` checks, **both against the same
ASCII character**. By intent, the second one should test the full-width `？`. A Chinese IME
produces full-width by default — so the feature's main users are precisely the ones who can't use
it. Filed as [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "This one contaminates the requirement"
    A `？` that misses doesn't error and isn't discarded. It's handled as ordinary input: during
    the clarify phase as an answer to the current question, otherwise straight into the inbox.
    **A line you only meant to ask on the side gets written into the brief.** If you catch the
    mistake, edit `.flower/notes/需求.md` right then — that file is what downstream goes by.

**What to do**: switch to half-width and type `?`, or type the half-width `?` first and then
switch back to Chinese for the body.

### `once` always reports `$0.00` spent and `0:00` elapsed {#once-计数为零}

**Symptom**: `flower once` runs start to finish and the status line at the bottom shows
`累计 $0.00` the whole way, with the timer stuck at `0:00`, while the same model on the same work
does report numbers under `go`.

**Cause**: `once`'s `render()` **constructs a new `Render` for every event received**, so the
accumulators are rebuilt with it and start from zero each time. The totals are being repeatedly
zeroed, not left uncounted. Filed as [#14](https://github.com/ChenyuHeee/flower/issues/14).

**What to do**: if you need accurate numbers, use `go`; that path is unaffected. If you want
`once`'s single-turn shape and still want the bill, check `runs/manifest.json` afterwards — every
step's cost is recorded there, and that record is correct. See [config.md](config.md#run-dir).

### A skill dropped into `plugin/` is never loaded {#plugin-不加载}

**Symptom**: you wrote a skill following
[deploy.md](deploy.md#写一个-skill完整例子), the directory layout is right, but the agent behaves
as if it doesn't exist — **no error, not one log line**.

**Cause**: `plugin/` isn't packaged into the wheel. In an installed package, `PLUGIN_DIR` points
at `<site-packages>/plugin`, that directory doesn't exist, and the existence check before loading
silently skips. **All three `install.sh` paths are affected**; only a source checkout can load
skills. Filed as [#15](https://github.com/ChenyuHeee/flower/issues/15).

**What to do**: first check where the path actually resolves.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

If it prints `False`, this is your problem. To use skills there is currently exactly one way:
**run from a source checkout**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

An `-e` install points the package back at the checkout, `PLUGIN_DIR` lands on the real
`plugin/`, and rerunning that check prints `True`.

### `-T` seems to do nothing on `go` {#trim-与-go}

**Symptom**: you add `-T` to `flower go`, compare with and without, and the behaviour is
identical, as if the flag were broken.

**Cause**: **this one is by design, not a defect.** The `go` path already enables
[trim](glossary.md#裁剪) by default, so the intent `-T` expresses is already satisfied and
supplying it again changes nothing. The real switch on this path is the inverse `--no-trim` —
you only need to pass something explicitly if you want trimming off. `-T` is a meaningful switch
only on `run` and `once`.

**What to do**: to confirm trimming really is on under `go`, read the startup print with `-v`;
don't judge by the presence or absence of `-T`. To turn it off, pass `--no-trim`. Full flag
semantics in [cli.md](cli.md#全局开关).

## It says it's done and it isn't {#没做完}

The [goal guard](../guide/goal.md) exists to catch exactly this class — workers have a systematic
optimism bias; they know what they did, not what they missed. But the guard misjudges too, and
its misjudgements have a pattern. The five entries below split into "it passed something it
shouldn't have" and "it never passes".

### It says "can't be verified here", then passes {#无法达成不是未达成}

**Symptom**: the verdict reads "this can't be verified in the current environment, treating it as
met", and the workflow moves on.

**Cause**: the [judge](glossary.md#判定者) collapsed "unachievable" and "not met" into one
conclusion. Those are **different conclusions**, which is what
[three conclusions, not two](../guide/goal.md#三个结论不是两个) is about: "not met" means send it
back and keep working; "unachievable" means **stop and ask a human** — accept it, change the goal,
or say the judge got it wrong. With only "met/not met", a goal that genuinely cannot be done will
have the coordinator spinning round after round until the budget is gone.

**What to do**: **"can't verify here" can never count as met.** Spell out in the judge's
`instructions` what counts as undoable in your setting, so it returns "unachievable" when it
should. If you truly don't want to be stopped and asked, pass `--timeout 0`: on unachievable it
stops outright, with the reason left on disk instead of being papered over.

### It read the source and declared it done {#判产出物}

**Symptom**: the verdict reasons "X is implemented in the code", "the function signature matches
the requirement", while build artefacts, command output and running services were never touched.

**Cause**: the judge was pointed at the source.
[Judge the artefact, not the source](../guide/goal.md#判的是产出物不是源码) — whether the source
looks right and whether the delivered thing works are two different things. The former is
something the worker is already convinced of, and being convinced twice produces no new
information.

**What to do**: write criteria as assertions about the **artefact**. "Export is implemented"
doesn't count; "run `./app export out.csv`, `out.csv` has a 3-column header" does. That's how the
goal-setting step should write them in the first place, or the judge has to fill in vague items on
its own.

### The judge can't run commands, so it read the Makefile and passed it {#判定者不能跑命令}

**Symptom**: the goal is "produce a binary that runs on Linux", the verdict passes. You run
`file` yourself and the artefact is Mach-O, not ELF at all.

**Cause**: the judge is `judge(can_run=False)` by default, and it has **only `Read` / `Glob` /
`Grep`**. Those three read files; they **can't run `file` and can't run `./app --version`**. So it
settles for reading the Makefile, sees a cross-compile in the Darwin branch, and concludes the
condition is satisfied. It didn't lie — it **found the closest thing to evidence within its
capabilities**.

??? note "When you must turn `can_run` on"
    The test is simple: **if the goal mentions "the thing that gets built", turn it on.**

    - Artefacts: binaries, images, packages, generated data — on
    - Behaviour: the service starts, the command returns 0, the output matches a pattern — on
    - Pure text: whether a doc was written, whether a field was added to a schema — no need

    On the command line it's `--judge-can-run`. Wiring it yourself, the spelling differs per
    entry point, but they all end at the same parameter on `judge()`:

    | Entry point | How to pass it | Source |
    |---|---|---|
    | `judge()` | `can_run=` is a real parameter | `roles.py:361` |
    | `with_goal()` | `can_run=` is a parameter, forwarded to `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **no `can_run` parameter**, but it falls into `**spec_kw`, and that line is exactly `judge(..., **spec_kw)` — so it arrives | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, turned into `with_goal(can_run=…)`; this is the path `--judge-can-run` takes | `starter.py:105` → `:196` |

    The price is that the judge really executes commands, so a round of judging is slower and more
    expensive; what you buy is that it verifies **the site**, not the site's documentation. See
    [can the judge run commands](../guide/goal.md#判定者能不能跑命令).

**What to do**: if the goal is about an artefact, turn on `--judge-can-run`. When it's off, make
"decidable by reading alone" a hard constraint on how criteria are written — an item that can't
be written that way is one that needed a command to begin with.

### The checklist has a dozen-odd items and never passes {#清单长度}

**Symptom**: every round comes back rejected with a long list of gaps, the list grows as you fix
things, and the work never finishes.

**Cause**: the checklist was written for "how rigorous do I want to be", not for "how many ways
can this fail".
[The length of the checklist is set by how many ways the work can fail](../guide/goal.md#清单的长度由有多少种失败方式决定):
for a `git clone && make && ./app` task, **three to five items is enough** — it builds, it runs,
it works. In the real crash in [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了),
a "install the repo and run it" task got written as **15 items**: only 5 verified that something
worked, 6 verified that the process followed the rules, and 4 **could not be verified in
principle**.

**What to do**: edit `.flower/notes/目标.md`; that file is what judging goes by. Ask of each item
"which failure mode does this correspond to", and delete the ones you can't answer for. The
goal-setting step already flags unverifiable items — don't keep the ones it flagged.

### Boundaries written as criteria {#边界不是判定项}

**Symptom**: the checklist contains items like "never ran `brew install`", "no files outside the
project directory were modified", and the judge goes off checking the mtime of `~/.zshrc` and
whether `.flower/` was touched, to prove its own innocence.

**Cause**: boundaries and criteria constrain different things, and mixing them is the main cause
of the HT002 crash ([root cause one](../cases/ht002.md#根因一边界被当成了判定项)).

| | Constrains what | How it's honoured |
|---|---|---|
| **Boundary** | **How you work** ("install inside the project directory only", "don't touch business code") | By **not crossing it**, not by proving it afterwards |
| **Criterion** | **What you deliver** ("does it run", "is the result right") | By verifying on the spot |

Boundaries are exactly the section the clarify phase encourages you to fill out. Moving them item
by item into the checklist means every boundary adds another check, and most of those checks can't
be verified — an unverifiable item drags the whole round of judging down with it.

**What to do**: leave boundaries in the brief's "boundaries" section, honoured by not crossing
them, out of the checklist. If you really need to account for them, do it in one sentence —
**don't split it into six items**.

---

## Context and cost {#上下文与花费}

In a long-horizon run, context and money are the same problem: context grows to the ceiling and
either you hand off or that step blows up; and everything you repeat in one round is paid for
again in every round after it.

### Halfway through it started a new session and said "handoff" {#换代打断}

**Symptom** A `handoff` appears in the event stream, `payload["phase"]` goes `near` then `done`,
one extra round is spent writing the [handoff document](glossary.md#交接书), and then work carries
on as normal.

**Cause** Context approached the threshold. flower **does not compact** — it writes the current
session's state into a five-section handoff document and starts a new session that reads it and
continues. [Compaction](glossary.md#压缩) erases the most expensive information along with
everything else, such as which paths turned out to be dead ends; the handoff document is explicit,
on disk, and editable at any time: the session taking over reads exactly that file.

**What to do** This is the normal path; leave it alone. A handoff is not a retry — `attempts`
doesn't increase (it counts failures), the burned session_id is recorded in
`StepResult.retired`, and the externally visible `session_id` is always the successor that's still
alive
(see [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
If you really want the SDK's auto-compact back, use `--no-handoff`.

??? note "Where the threshold comes from, and why the default is so aggressive"
    `at = window - headroom`. `window` **defaults to 1,000,000**, decided by model name: names
    containing `haiku` count as 200k, everything else as 1,000,000. `headroom` defaults to 50k —
    auto-compact fires at −33k, the handoff has to get ahead of it, and writing the handoff itself
    takes another round; 50k satisfies both.

    Guessing high isn't a hard error: if the real window is smaller the threshold is never reached,
    the request comes back from the API as "prompt too long", flower recognises that signal
    (`handoff.is_overflow()`) and hands off on the spot with a mechanically assembled degraded
    document, so the step doesn't fail
    (see [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    One measured value worth mentioning: the gateway on the development machine is configured as
    `claude-opus-5[1m]`. Assuming 200k would hand off every 150k, when it actually runs to 950k —
    a **5× difference**, and long-horizon work gets chopped to pieces.

### It hands off right at the start, and won't stop {#一开局就换代}

**Symptom** The error mentions the "startup floor", or the same step hands off over and over
until it hits `max_generations=8`.

**Cause** `window` is set too small and the threshold is below this role's startup floor — the
coordinator measures around 34k, taken up by the system prompt plus the
[workbench](glossary.md#工作台) index alone. The new session is over the line as soon as it opens
its mouth, so it writes a handoff, hands off, crosses the line again, forever (handoffs don't
consume retry budget; that's deliberate).

**What to do** Set `--window` to the model's real window; `-v` prints the effective endpoint and
model mapping. A normal long run never needs 8 generations, so hitting the cap is almost always
this, and the error message says so directly
(see [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
A related symptom is "handoffs are always degraded": the reason is in `errors` in
`runs/manifest.json`.

### It stops halfway and says the budget is exhausted {#预算到顶}

**Symptom** A [step](glossary.md#步骤) stops before finishing, citing exceeded spend.

**Cause** `AgentSpec(max_budget_usd=...)` is a **hard ceiling**, not a soft warning;
`Runtime.total_cost()` is the total for this run.

**What to do** Before raising the ceiling, confirm it isn't spinning. Round after round rejected
with no progress in any of them usually means the judge should have returned "unachievable" and
returned "not met" instead — a goal that genuinely can't be done will burn until the budget is
gone
(see [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirm it's doing real work, then raise the ceiling.

### Why was this run so expensive {#为什么这么贵}

**Symptom** Spend far exceeds expectation, and the output doesn't show where the money went.

**Cause** The ledger isn't in the model's context. Each step's `session_id`, cost, retry count and
failure reason are recorded only in `runs/manifest.json`, **appended across processes**. Retry
history and raw errors live only there too — the model doesn't see them, and that's deliberate:
pile denied calls into the context and the coordinator learns "Bash gets blocked anyway" and stops
even trying `git status` (`Runtime(keep_denials=1)` already clears them by default; don't raise
it).

**What to do** Open `runs/manifest.json` and attribute cost per step (disk layout in
[config.md#磁盘布局](config.md#磁盘布局)). Some measured reference points:

| | Cost |
|---|---|
| One subagent's startup floor (can't be amortised) | ~4.3k tokens |
| The coordinator's startup floor | ~34k tokens |
| `tests/smoke.py`, single agent, full chain | ~$0.21 |
| `tests/flow_demo.py`, three ways of wiring a workflow | ~$0.39 |
| `tests/delegation.py`, division of labour + measuring context distribution | ~$0.71 |
| `tests/isolation.py`, three issues in three worktrees | ~$0.9 |

### Context grows faster than the work gets done {#上下文涨得快}

**Symptom** Every round's [task brief](glossary.md#任务书) repeats the same discipline ("read the
file before editing", "don't touch business code", "run the tests after"), and the
[worker](glossary.md#执行者) was doing that anyway.

**Cause** Everything the coordinator says goes into its own transcript, and a transcript only
grows. Restating the discipline costs money this round **and again in every round after it**.
Restating what the other side already knows has zero benefit and permanent cost.

**What to do** Put discipline into mechanism, not into every round's speech: anything expressible
through `allowed_tools`, the brief's "boundaries" section, or the workbench index does not belong
in the task brief; the task brief says only what changed this round. Division of labour is the
layer that saves the most
(see [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
On resume, large old tool results can be swapped for file pointers with `-T`.

## Interruption and continuity {#中断与接续}

### The process was killed, the machine rebooted {#进程被杀}

**Symptom** It died halfway; you reopen the terminal and don't know how to pick it up.

**Cause** There's nothing to pick up. [Lineage](glossary.md#血缘) (`runs/lineage.json`) records
step name → session_id, spilled to disk at the end of every step, written to `.tmp` first and then
atomically replaced — being killed midway leaves no half file.

**What to do** Go back to the **same directory** and run `flower` again; each step resumes its
previous session: it won't interrogate you about the requirement again, won't re-set the goals, and
still remembers which dead ends the coordinator tried. If you have nothing to say, just press
Enter
(see [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
The judge is the exception — it isn't a `Step`, it's dispatched directly from the gate and never
goes through lineage, so every round gets a fresh pair of eyes.

### It starts from scratch every time; continuity never kicks in {#接不上}

**Symptom** Running again in the same directory, it interrogates you about the requirement all
over again.

**Cause** Three kinds of mismatch, and in all of them flower **silently falls back to starting
over, without an error** — [continuity](glossary.md#接续) is a bonus, and its failure shouldn't
block you from working:

- `runs/lineage.json` is missing, or the `workspace` inside it doesn't match your current path
  (which happens if the directory was copied elsewhere)
- The session is no longer in `runs/sessions.db` (the store was deleted)
- The lineage file is corrupt

**What to do** First check whether `runs/lineage.json` exists and whether `workspace` is right
(the roles of the three files are in
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Not resuming after a directory move is **intentional**: `project_key` is derived from the
workspace path, and old sessions can't be found at the new location.

### I want a fresh start without losing the history {#想重开}

**Symptom** The requirement has turned in a different direction, and you don't want it continuing
from last time.

**Cause** Continuing is the default. In a directory you've used before,
`flower "顺便支持代码块高亮"` is not a new task, it's one more sentence in the same conversation.

**What to do** `--new`. It **archives rather than deletes**; the old material stays in
`notes/archive/`. On [wake](glossary.md#唤醒) it first prints one line with the current context
size — if that looks too big, this is the same path to take.

### The network dropped; it neither errors nor moves {#断网}

**Symptom** No new events on screen, the process is still alive, and it looks stuck.

**Cause** A network drop is treated as "wait a bit", not as a failure. flower hangs and waits: it
probes DNS, then TCP, and continues once it's through
(see [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
This was validated by a real failure in HT001
(see [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**What to do** Wait for it; `-v` shows the probes running. The errors accumulated during the wait
**do not enter the post-resume context** — they land only in `runs/manifest.json`, and the session
taking over sees a clean site rather than being pulled off course by a string of timeouts.

### Two rapid Ctrl-Cs skip part of the shutdown {#双重-ctrl-c}

**Symptom** Closing with `kill` (SIGTERM) and hammering Ctrl-C twice leave different state behind.

**Cause** Known gap. A double Ctrl-C raises `KeyboardInterrupt`: the `finally` in `_drive` in
`cli.py` calls `rt.close()`, but **not** `rt.rescue()` — only the SIGHUP/SIGTERM handler calls
`rescue()`.

**What to do** Lineage survives on both paths (spilled atomically at the end of every step), so
running again still resumes and this gap won't lose you progress. For a complete shutdown, use
`kill <pid>` rather than mashing Ctrl-C.

## Parallelism and isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptom** Turning on isolation won't start, reporting `not in a git repository`.

**Cause** `worker(..., isolate=True)` relies on a git worktree to give each agent a private copy;
if the workspace isn't a git repository, it can't create one.

**What to do** This one **does not silently degrade** — either run inside a real repository, or
turn `isolate` off. Isolation guarantees "several agents editing at once without seeing each
other's working tree"; it does not guarantee the merge is conflict-free.

### An isolated agent can't write to the workbench {#隔离写不进工作台}

**Symptom** The subagent reports "write permission denied" and scripts and outputs can't be
spilled; or the output lands inside one worktree and the other agents can't see it.

**Cause** A worktree is each agent's **private copy**; the workbench is a **shared layer** across
agents. Put something shared inside a private fence and of course nobody else can reach it.

**What to do** With isolation on, point the workbench **outside the repository**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

When it sits outside the workspace, `Runtime` grants access via `add_dirs` automatically;
`Runtime(workbench=True)` already handles this, but if you build your own `Workbench` you have to
grant it yourself.

!!! warning "The workbench has two default locations, and they differ"
    `Workbench(workspace)` — the path the CLI and `starter_flow()` take — puts the workbench at
    `<workspace>/.flower`; `Runtime(workbench=True)` (i.e. `-W`) puts it at `<run_dir>/workbench`,
    that is `runs/workbench`. So running `flower` once gives you `.flower/`, and calling
    `Runtime(workbench=True)` from Python **does not**.

### Running flower gives me `.flower/`, my own script doesn't {#两个工作台默认值}

**Symptom** The brief clearly went into `.flower/notes/需求.md`, and yet the coordinator acts as
if it never read it; **no error**.

**Cause** You have two workbench objects. The brief was written into directory A, while the index
injected into the system prompt scans directory B, and the promise "it knows where the requirement
file is from the start" **fails silently**. Both ways of getting this wrong are silent: assembling
your own `brief_path` relative to the process cwd gives a different directory from the
`<run_dir>/workbench` that `-W` creates; and you can't work backwards from `Runtime` either —
`cli.py` calls `main()` to build the `Workflow` first and only then constructs `Runtime`, by which
time `brief_path` is long since fixed.

**What to do** Build one `Workbench` yourself and hand **the same object** to both `Workflow` and
`Runtime`; then the location is pinned:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` pins this down: assertion 5 checks that the brief appears in
`prompt_block()`. Also, the index is injected only into the **coordinator's** system prompt;
subagents don't inherit it (measured at $0.2461, `tests/prelude_live.py`) — the coordinator has to
relay the paths downward, they aren't automatically known to every subagent
(see [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
