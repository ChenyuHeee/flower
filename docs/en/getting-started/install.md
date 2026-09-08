# Installation

Installing flower needs only Python ≥ 3.10. There is exactly one runtime dependency,
`claude-agent-sdk` — the native binary that sends the requests ships inside its wheel, so
**you do not need Node, and you do not need the Claude Code CLI**. This page walks the whole
thing from zero: one-line install, install from source, first-time credential setup, and one
command that proves it really works. Once that runs, go to
[Quickstart](quickstart.md).

## Before installing: check Python {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Output like `True 3.13.7` is enough. If it prints `False`, or there is no `python3` at all,
install one first (`brew install python` / `apt install python3`), otherwise the install script
exits immediately.

| Needed | Not needed |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` checks again itself) | Node.js |
| Network access to the API endpoint | Claude Code CLI |
| An API key or gateway token (supply it after installing) | Settings in the host's `~/.claude/` (credentials are the one exception, see below) |

Package name `flower`, version `0.1.0`, sole runtime dependency `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material` is only used when CI builds the docs site; running
flower does not need it.

## One-line install {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

When it finishes the terminal should look like this (colors omitted):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

The line that matters is `== 装好了 <absolute path>` — it is the result of the script running
`command -v flower` itself (`install.sh:60-61`). If it prints a path, `flower` is on PATH.

### What the installer actually does {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) does three things only:
pick a Python tool installer, install from GitHub, tell you the next step. **It does not touch a
single byte of your credentials** (`install.sh:7-8`). The install source is fixed at
`git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

The installer tries in order and stops at the first one that works (`install.sh:33-57`):

| Order | Trigger | Actual command | Where the executable lands |
|---|---|---|---|
| 1 | `uv` on PATH | `uv tool install --force <REPO>` | uv's tool bin directory, usually `~/.local/bin/flower` |
| 2 | No `uv`, but `pipx` present | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Neither | first `curl -LsSf https://astral.sh/uv/install.sh \| sh` to install uv, then back to case 1 | same as case 1 |
| 4 | uv failed to install in case 3 | `python3 -m pip install --user --upgrade <REPO>` | user scripts directory — **not `~/.local/bin` on macOS** |

All four cases install the same console script: `flower = "flower.cli:main"` (`pyproject.toml:12`).
After installing you can also invoke it as `python -m flower.cli`, same effect
(`cli.py:1451-1452`).

!!! warning "Re-running the install script force-overwrites, with no confirmation prompt"
    The three install commands carry `--force`, `--force`, `--upgrade` respectively
    (`install.sh:37`, `:40`, `:54`). Re-running it simply overwrites the existing installation —
    that is exactly how you upgrade, but do not expect it to ask first.

### How the `flower` command gets on PATH {#flower-命令怎么上-path}

When `command -v flower` finds nothing, the script suggests adding `$HOME/.local/bin` to
`~/.zshrc` or `~/.bashrc` (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Both `uv tool install` and `pipx install` put things there, so that suggestion is accurate for
them. **But case 4 (`pip install --user`) is not guaranteed** — the directory in that message is
hard-coded, while pip's user scripts directory is platform-dependent. On macOS it is
`~/Library/Python/3.13/bin`. Check yours:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Output like `/Users/you/Library/Python/3.13/bin` — add that directory to PATH instead of
`~/.local/bin`, then reopen the terminal or `source` your rc file.

## Install from source {#从源码装}

If you want to read the code, modify the framework, or run the offline checks in `tests/`,
install from source:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

After that, `.venv/bin/flower --help` should print the usage lines.

The shebang of that executable inside the venv is an **absolute path**, so you do not need to
activate anything; symlink it and it works from any directory:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

With `~/.local/bin` on PATH, typing `flower` in any project directory runs this venv's
interpreter and this copy of the source.

A source install also gets one extra credential location: **`.env` at the repo root** (5th in the
lookup order, see
[Configuration · Credential lookup order](../reference/config.md#凭证查找优先级)). While developing:

```bash
cp .env.example .env        # fill in ANTHROPIC_AUTH_TOKEN
```

`.env` is already in `.gitignore` and will not enter version control. A flower installed via
pip / pipx / uv **does not** have this location available — it lives in site-packages, there is no
"repo root" — so that kind of install uses the global credential file below.

## Automatic updates {#自动更新}

flower is still iterating fast, so **an install via pip / pipx / uv updates itself by default**:
a bug reported by someone running a three-day-old version may already be fixed, wasting both
sides' time. There is no toggle-style "do you want this on" question — it is on by default, and
you turn it off with an environment variable.

What it does (`update.py:116-129`):

1. On every `flower` start, it checks the latest commit on `main` on GitHub in a **background
   thread** (`update.py:70-80`). The main flow does not wait a single second — that is the first
   invariant.
2. If it differs from the locally installed commit, it runs an update command matching how you
   installed: `uv tool install --force` if `uv` is present, `pipx install --force` if `pipx` is,
   otherwise `pip install --user --upgrade` (`update.py:83-93`).
3. **Even after installing, it does not swap out the currently running process** — the new version
   is used on the next `flower` run (`update.py:113`). Being swapped mid-run is the hardest class
   of failure to diagnose.
4. Throttling: at most one check per 24 hours, timestamp recorded in `~/.config/flower/.update`
   (`update.py:32`, `:36-37`, `:124`).
5. **Failures are always silent.** No network, GitHub down, install failed — none of it interrupts
   your work (`update.py:79`, `:108-110`).

**Running from source (git) is unaffected.** The update-command step first checks whether the repo
has a `.git`; if so it returns `None` immediately and does nothing (`update.py:83-87`) — your
working tree belongs to `git`, not to it. Non-interactive use (stdin is not a terminal, e.g. a
pipe / CI) is skipped entirely as well (`update.py:121`).

To turn it off:

```bash
export FLOWER_NO_UPDATE=1
```

Any non-empty value counts (`update.py:33`, `:121`). Use it in CI, offline environments, or when
reproducing the behavior of an older version.

## First run: set up credentials {#第一次跑配凭证}

All three work entry points — `go`, `run`, `once` — call `ensure_credentials()` at the top
(`cli.py:1192`, `:1160`, `:1225`), two gates:

1. **Present or not** — search the priority order once; if nothing is found, ask you on the spot.
2. **Usable or not** — actually hit the API. A minimal request with `max_tokens=16`
   (`env.py:120-123`), costing almost nothing. An expired token or a mistyped gateway address
   cannot be detected by looking at environment variables; without the probe you only blow up
   minutes later.

With no credentials, the first `flower` run stops at this screen (`cli.py:1358-1388`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

Question 1 is required; leaving it blank prints the red line `没给 token,取消。` and exits.
Questions 2 and 3 accept a bare Enter. Leave question 2 blank for the official endpoint; for a
third-party gateway enter its root address, **without `/v1`** — flower's probe hits
`<BASE_URL>/v1/messages` (`env.py:162`).

The keys written after you answer (`cli.py:1378-1386`):

| What you entered | Key written to `.env` |
|---|---|
| token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| any other token | `ANTHROPIC_AUTH_TOKEN` |
| non-empty gateway address | `ANTHROPIC_BASE_URL` |
| non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **all three at once** |

The file lives at `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), is written as a
**full overwrite**, and is `chmod 0o600` afterwards (`cli.py:1336-1347`). This is the "set up once,
works everywhere" file — switching project directories needs no reconfiguration; for the meaning
of each variable see [Configuration](../reference/config.md#环境变量).

### If Claude Code is already installed here, you may not be asked anything {#本机装过-claude-code-的话可能一个问题都不问}

Credential lookup has one **final fallback**: read `~/.claude/settings.json`, then
`~/.claude/settings.local.json`, and take 9 credential keys out of their `env` blocks
(`env.py:56-75`, `:109-111`). If you already have Claude Code configured here, just run `flower`
and go — the setup screen never appears. That is exactly what `install.sh:77` advertises.

!!! warning "The in-product line “flower 不读 ~/.claude/settings.json” is wrong"
    When no credentials are found at all, the last line of the error flower prints is
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, that sentence is at `:192`). **The code is authoritative: it does read them.**
    `env.py:56-75` explicitly reads the `env` blocks of those two files; it just takes only the 9
    credential keys and takes over no other settings. When you read that line, do not conclude that
    your local Claude Code configuration is being ignored. For the full chain see
    [Configuration · Credential lookup order](../reference/config.md#凭证查找优先级).

### When you want to reconfigure {#想重新配的时候}

The `flower setup` subcommand is registered (`cli.py:1326-1328`), but `_CMDS` omits it
(`cli.py:937`), so `flower setup` gets rewritten into `flower go setup` — treating "setup" as a
request and running the full workflow on it. **There is currently no command-line spelling that
reaches that subcommand**, even though several error messages still tell you to run it. To change
credentials:

```bash
$EDITOR ~/.config/flower/.env
```

Or delete the token from that file and run `flower` again — the missing-credential gate will ask
again (provided no other location has one either, e.g. `~/.claude/settings.json`). When credentials
are rejected (HTTP 401 / 403), the same screen pops up on the spot to let you reconfigure, with one
retry at most (`cli.py:1416-1428`).

## Verify the install {#验证装好了没有}

Two levels, cheap to expensive.

**Level one — is the command there (free)**:

```bash
flower --help
```

Seeing these lines means the console script is installed and on PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Level two — credentials, endpoint and native binary all work (a few cents)**: the cheapest real
run is `once` — a single agent, by default only the three read-only tools `Read` / `Glob` / `Grep`,
no [goal guard](../reference/glossary.md#目标看守), no [workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` prints the configuration currently in effect **before** the run starts, keeping only the
first 4 characters of the token (`cli.py:1445-1447`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Those lines confirm you are not pointed at the wrong gateway. Then comes the credential probe and
the actual run:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**No step header.** `once` goes through `_run_once` → `rt.run()`, bypassing `_drive` /
`Workflow.run`, and `Event("step", …)` is only emitted at `workflow/base.py:220` — so separator
lines like `== 步骤名 ===== 1/1` never appear under `once`; only `go` / `run` have them.

**The run passes as soon as the `+ 完成` line appears**, and it proves three things at once:
the credentials work, the endpoint is reachable, and the native binary inside the
`claude-agent-sdk` wheel runs on this machine. If `- 验一下凭证…` is followed by
`! 凭证被拒` or `! 网关地址或模型名不对`, go to the troubleshooting table below.

!!! note "`once` shows elapsed time and cumulative cost as 0"
    `once` creates a new renderer for every event (`cli.py:1239`, `:579-581`), so `用时` is always
    `0:00` and the `累计 $` in the status line never accumulates — **the per-step cost is real, the
    time is not**.

    The `1 轮 · $0.1741` above is a **sourced, measured figure**: on 2026-09-06, in a Linux/arm64
    container, one real request sent through `cloud.infini-ai.com/maas` (`docker/README.md:24-25`),
    i.e. the **single-turn floor price** for Opus 5 + 1M window. Running the command above yourself
    involves reading a repo, so there will be more turns and the cost will be somewhat above that
    floor. The full accounting is in `runs/manifest.json`, see
    [Configuration · Disk layout](../reference/config.md#磁盘布局).

## When it will not install {#装不上的时候}

| Symptom | Cause | What to do |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Neither `python3` nor `python` satisfies 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, then run the script again |
| Script says it installed, but `flower: command not found` | Installed into a directory that is not on PATH | See "How the `flower` command gets on PATH" above. On the `pip --user` path, macOS uses `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Every path failed, usually no network to GitHub or PyPI | Run the suggested command manually and read the real error |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 lines) | No credentials in a non-interactive environment (pipe, CI, `nohup`) — the setup screen does not appear there, it just exits | Run `flower` once in a real terminal to configure, or write `~/.config/flower/.env` directly |
| `! 凭证被拒:HTTP 401 …` | Token expired or mistyped | In an interactive terminal it lets you reconfigure on the spot; non-interactive exits |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` or the model name is wrong | Point BASE_URL at the gateway root, without `/v1`; use the gateway's own model names |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Not a credential problem**; flower deliberately does not make you reconfigure, it starts the run anyway and leaves it to the [resilience](../reference/glossary.md#韧性) layer |
| `! 标准输入不是终端,没人能回答提问` | Running in a pipe or CI | Pass `--timeout 0` so it decides on its own instead of waiting for a human |
| `flower setup` starts and asks "what should I do" | `_CMDS` omits `setup` (`cli.py:937`) | Edit `~/.config/flower/.env` directly, see "When you want to reconfigure" above |

## Next steps {#下一步}

- [Quickstart](quickstart.md) — enter a project directory and get the first real job done.
- [Configuration](../reference/config.md) — every environment variable, credential priority, `.env` syntax, what is left on disk.
- [CLI](../reference/cli.md) — every subcommand and flag.
- [Deployment](../reference/deploy.md) — running in a container, distributing domain capability as a plugin.
- [Glossary](../reference/glossary.md) — the exact meaning of every term in the docs.
