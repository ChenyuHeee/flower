# Deployment and extension

Moving flower somewhere else means dealing with three things: containers (fencing in the
unrestricted Bash, and incidentally testing the claim "no CLI needed"),
[plugins](glossary.md#plugin) (domain capability travels with the repo, independent of what the
host machine has installed), and the documentation site (push to `main` and it publishes itself;
`install.sh` is served from the Pages domain). The three sections are independent — read what you
need.

## 1. Containers {#一容器}

### Why a container {#为什么要容器}

**First, to fence things in.** The [worker](glossary.md#执行者) doing the actual work has
**unrestricted Bash** — flower's Bash allowlist (`delegate_guard`) only covers the
[main thread](glossary.md#主线程), and a delegate has to be able to run tests, so this is
deliberate. The container mounts only your project directory; the framework source lives at
`/opt/flower` inside the image, and nothing else on the host is visible.

**Second, the container is itself the test of the [portability](glossary.md#可移植) constraint.**
The image has no Claude Code CLI and no Node — only Python and `claude-agent-sdk`; requests go out
through the native binary bundled in the wheel. If it runs here, "no CLI needed" is not a claim on
paper.

Verified in practice (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| What was checked | Result |
|---|---|
| Is there a CLI in the image | `claude`, `node`, `npm`, `npx` **all absent** |
| Bundled binary | `\177ELF` (207M) |
| A real request | Sent via `cloud.infini-ai.com/maas` and answered, `$0.1741 / 1 turn` (that is simply the single-turn floor for Opus 5 + the 1M window) |
| File ownership | Files written to `/work` inside the container are `hechenyu:staff` on the host — the mapping is correct |
| Host visibility | `ls /Users` inside the container → `No such file or directory` |

### What is in the image {#镜像里装了什么}

Base image `python:3.13-slim`, plus exactly three apt packages on top. Each has a reason:

| Installed | Why |
|---|---|
| `python:3.13-slim` | All that is needed is Python ≥ 3.10. No Node, no claude CLI |
| `git` | `--isolate` gives each [subagent](glossary.md#subagent) its own worktree |
| `ca-certificates` | HTTPS to the gateway |
| `libstdc++6` | The binary bundled with the SDK is a Bun-compiled single file that needs it on Linux; the slim image does not ship it |

The framework source enters the image via `COPY`, **not a bind mount** — so the agent inside the
container cannot reach the framework source on the host:

| Path in image | Contents | Comes from |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, with `pip install .` run here | `COPY` |
| `/work` | Working directory (`WORKDIR`), the host's `$PWD` mounted at runtime | `docker run -v` |

The entrypoint is `ENTRYPOINT ["flower"]` and `CMD` is empty — running the container with no
arguments drops into interactive input (it asks what you want done) rather than printing `--help`.
That way you do not have to quote a Chinese request on the shell.

### Why you cannot mount the host's `.venv` {#为什么不能把宿主的-venv-挂进去}

The SDK ships per-platform wheels, and the bundled binary is platform-specific:

```text
host      claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
          → _bundled/claude is Mach-O 64-bit arm64, 191M
container claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Mounting it in does not work, so the image must run its own `pip install`. Turned around, this is
also evidence of portability: the same `pyproject.toml`, a different native binary per platform,
and not one line of framework code changes.

### Two scripts {#两个脚本}

| Script | What it does |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Builds the image. `cd` to the repo root, `docker build -f docker/Dockerfile -t flower-box .`; when `FLOWER_MIRRORS=1` (the default) it first pulls `python:3.13-slim` from a registry mirror and retags it, and passes pip / apt `--build-arg`s |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Runs once. Check the credentials file → check that `$PWD` can actually be mounted → decide whether there is a TTY → `docker run` |

All of `docker/build`'s switches are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Image tag |
| `FLOWER_MIRRORS` | `1` | `0` = substitute no mirrors at all, everything goes upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | Pull the base image from here and retag it as `python:3.13-slim` so the `FROM` hits the local copy |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Passed as `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Passed as `--build-arg APT_MIRROR` |

The last three only take effect when `FLOWER_MIRRORS=1` — the `FLOWER_MIRRORS=0` branch sets no
build-args at all.

`docker/flowerbox` recognizes two:

| Variable | Default | Meaning |
|---|---|---|
| `FLOWER_HOME` | One level above the script itself (i.e. the repo root) | Where to look for `.env`. If `$FLOWER_HOME/.env` is missing it exits 1 |
| `FLOWER_IMAGE` | `flower-box` | Which image to run |

`FLOWER_HOME` is derived from the script's own location rather than hard-coded, so the repo works
wherever it is cloned.

### Running it {#跑起来}

```bash
docker/build                       # once is enough
cd ~/your-project-dir              # must be under $HOME, see the mount boundary below
/path/to/flower/docker/flowerbox   # no arguments → it asks what you want done, no quoting needed
```

If your network reaches pypi.org / Docker Hub fine, build like this:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox`'s arguments are exactly `flower`'s — it appends `"$@"` verbatim after the
`ENTRYPOINT`. `--clarify-only`, `--asks N`, `--timeout SECONDS`, `--isolate`, `-v` all pass
through; the full table is in [command line](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

What actually runs is this one line (`-t` is added only when there is a TTY, see below):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Mount boundary and persistence {#挂载边界与持久化}

```text
host $PWD  ──mount──>  /work       ← the agent works here, output stays on the host
in image               /opt/flower ← framework source, **not mounted**, cannot reach the host
```

So running inside an in-repo subdirectory such as `flower/human-test/HT001` is also safe: only
`HT001` is mounted, and the framework source is outside the mount.

| Thing | Still there after exit? | Why |
|---|---|---|
| Everything under the host's `$PWD`, including `runs/` and the [workbench](glossary.md#工作台) `.flower/` | Yes | That directory *is* what is mounted as `/work` |
| Anything written to other paths inside the container | No | `--rm`, the container is deleted on exit |
| Credentials | Never enter an image layer | Passed via `--env-file`; `.dockerignore` excludes `.env`, so even `COPY . .` would not carry it in |

!!! danger "The project directory must be under `$HOME`, or output is silently lost"
    **colima by default only mounts `$HOME` into the VM** (`mount | grep virtiofs` →
    `mount0 on /Users/<you>`). Run somewhere like `/tmp` and `-v` creates an **empty directory**
    inside the VM; whatever gets written there is never visible on the host, **and nothing errors
    out** — output, the [brief](glossary.md#需求确认书), `runs/`, all gone. Hit this once: a
    `once` run finished, $0.17 spent, and `runs/` did not exist on the host at all.

    `flowerbox` now blocks this case: if `$PWD` is under `$HOME` it passes straight through;
    otherwise it writes a probe file into `$PWD` and starts a container to actually check
    `test -f /work/<probe>` (extra mounts pass too). If that fails it exits 1 and tells you
    `colima start --mount '<path>:w'`. The probe needs a container, so run `docker/build` first.

### Credentials {#凭证}

Passed via `docker run --env-file`; they **never enter an image layer**. `flowerbox` reads
`$FLOWER_HOME/.env`, which by default is the `.env` at the repo root:

```bash
cp .env.example .env       # fill in the token; .env is already gitignored
```

Note that `flower setup` writes `~/.config/flower/.env`, and **`flowerbox` does not look at that
path**. If you have already configured things with `setup` and do not want a second copy, point
`FLOWER_HOME` at it:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Key names, precedence, and how to fill in the gateway are in [configuration](config.md).

!!! warning "With no TTY, a question blocks until `--timeout`"
    `flowerbox` only adds `-t` when `[ -t 0 ]` — `docker run -t` in a pipe or in CI fails outright
    with "the input device is not a TTY"; `-i` is always needed, or stdin never gets in at all.

    Answers to questions come from standard input. With no TTY, the first `input()` raises
    `EOFError` → the current question is treated as "input closed" and skipped, **and the answering
    thread exits**, so from the second question onward nobody is listening and you just wait out
    the full `--timeout` (1800 seconds by default). Unattended runs need an explicit
    `--timeout 0`. The script prints a warning line when it detects there is no TTY.

### git submodule {#git-submodule}

`.gitmodules` has exactly one entry:

| path | url | What it is |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | The code repository **produced by** the [HT001](../cases/ht001.md) run, kept for the record |

An ordinary `git clone` does not fetch it, and `human-test/HT001` is just an empty directory (the
leading `-` in `git submodule status` means exactly this state). Whether you need to care:

| What you want to do | Do you need to init it? |
|---|---|
| Run flower, build the image | **No.** `.dockerignore` excludes `human-test/`, and the `Dockerfile` only `COPY`s `pyproject.toml` / `flower` / `examples` anyway |
| Read HT001's output code locally | Yes: `git submodule update --init human-test/HT001`, or `git clone --recurse-submodules` from the start |

### Networks inside China: why all those mirror substitutions {#国内网络为什么有那一堆镜像替换}

Installing this behind the GFW, the bottleneck is not bandwidth but the international route. The
default `docker/build` already substitutes everything that needs substituting, and
`FLOWER_MIRRORS=0` turns all of it off at once. Below are the measurements and the reasoning
behind the four substitution points — skip it if your network does not have this problem.

??? note "Measured speeds and the four substitution points (2026-09-06, macOS/arm64)"

    | Source | Speed |
    |---|---|
    | `pypi.org` (index) | 32 KB/s |
    | `files.pythonhosted.org` (package files) | **284 B/s** |
    | `github.com` (direct release asset) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (inside the VM) | 26 KB/s |
    | `download.docker.com` | **unreachable** (HTTP 000); 4 KB/s inside the VM |
    | `mirrors.tuna.tsinghua.edu.cn` | **unreachable** |
    | `mirrors.aliyun.com/pypi` (**package files**) | 1.4 MB/s (host) / 152 KB/s (inside the VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (inside the VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (GitHub proxy) | **2.5 MB/s** |
    | `gh-proxy.com` (GitHub proxy) | 1.5 MB/s |
    | `dockerproxy.net` (Docker Hub proxy) | Works (returns the manifest directly) |

    When measuring, do not mistake the **index page** for package files: that
    `mirrors.aliyun.com/pypi/simple/` page hits 7.4 MB/s, while the actual 95.9 MB wheel only does
    1.4 MB/s (152 KB/s inside the VM — colima's userspace networking costs something). Estimate
    time from the package-file numbers.

    **Substitution point 1 — colima's VM image.** colima does not use a plain Ubuntu cloud image
    but its own custom image with **docker pre-installed** (a release asset of
    `abiosoft/colima-core`), so bringing up the VM needs no apt install of docker, which sidesteps
    the unreachable `download.docker.com`. Download it yourself and feed it in with `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # Verify: get the digest from the GitHub API. Do not skip this — you are about to run it as a VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    The proxy drops the stream mid-transfer (curl 56 in practice); `-C -` resumes, just rerun it a
    few times.

    **Substitution point 2 — apt inside the VM.** Even with the pre-installed-docker image, lima's
    boot script `30-install-packages.sh` still runs one `apt-get update` in order to install
    `rsync` — hitting `ports.ubuntu.com` (26 KB/s) and `download.docker.com` (4 KB/s), which can
    hang for tens of minutes.

    The fix (**read `/mnt/lima-cidata/boot.sh` before doing anything**: a failed boot script only
    produces a `WARNING` + `CODE=1` and execution continues, and the end of the script **always**
    writes `/run/lima-boot-done`, so making that step fail is safe):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh runs to completion and writes the done marker
    '
    # colima start then exits normally; afterwards install rsync (1.95 MB/s now)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    While you are there, add `127.0.0.1 lima-colima` to the VM's `/etc/hosts` to silence the
    `sudo: unable to resolve host` warnings.

    **Substitution point 3 — the base image.** `docker/build` first pulls `python:3.13-slim` from
    `dockerproxy.net` and retags it so the Dockerfile's `FROM` hits the local copy. Measured:
    `dockerproxy.net` returns the manifest directly (HTTP 200); `docker.1ms.run` /
    `docker.m.daocloud.io` return 401, `hub.rat.dev` 302, `docker.xuanyuan.me` 403.

    **Substitution point 4 — apt and pip inside the container.**
    `--build-arg APT_MIRROR=mirrors.ustc.edu.cn` (`deb.debian.org` 32 KB/s → USTC 435 KB/s) and
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Note that `PIP_INDEX_URL`
    is also an environment variable pip itself honors, so once the `ARG` is declared, pip in the
    RUN step picks it up — it works without an explicit `--index-url`.

    Total one-time setup under those network conditions is about 25 minutes, dominated by the
    364 MB VM image and the 95.9 MB SDK wheel. After that, `flowerbox` starts in seconds.

## 2. plugin {#plugin}

### What it is {#它是什么}

A **domain capability package that travels with the repo**. The framework code contains no domain
knowledge at all; domain knowledge lives entirely in the `plugin/` directory at the repo root, and
gets cloned, reviewed and tagged along with the code.

The SDK-side wiring is two lines in `build_options()` in
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py):

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Together with `setting_sources=[]` (covered separately below), this is why flower can be both
"[portable](glossary.md#可移植)" and "aware of your domain" at the same time: it does not ask what
the host machine has installed, it only recognizes this one directory that came with the repo.

### Directory layout {#目录布局}

| Path | What goes there | When it takes effect | Who decides |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | The package's identity: `name`, `description`, `version`, `author` | Read once at load | — |
| `plugin/skills/<name>/SKILL.md` | Domain knowledge, loaded on demand | **Probabilistic** — used only if the model judges it relevant | Model |
| `plugin/agents/<name>.md` | A subagent with its own context window | Delegated by the model, or named explicitly in a [workflow](glossary.md#流程) | Model / you |
| `plugin/hooks/hooks.json` | Intercept tool calls | **Deterministic** — matches, runs | Code |
| `plugin/.mcp.json` | External tool integration | Registered as tools, same as the built-ins | Model |

**The difference between probabilistic and deterministic is the whole basis for choosing, not a
matter of phrasing:**

- A skill is **knowledge sitting there**. The model sees its `description` and reads it only if it
  thinks it is relevant to the current task. That relevance judgment is made by the model, so the
  same request run twice may use it once and not the other time.
- A hook is **code**. It runs when the event matches, regardless of whether the model wants it or
  even knows about it. flower's own [spill](glossary.md#落盘) and
  [isolation](glossary.md#隔离) are hooks precisely because they cannot be allowed to work "some
  of the time".

So there is exactly one criterion: **must this happen every time?** If yes — write a hook. If it
is merely "useful to know" — write a skill. Writing something mandatory as a skill means betting
your discipline on a single judgment by the model.

Right now `plugin/` in the repo contains only two things: `.claude-plugin/plugin.json` and
`skills/example/SKILL.md`. `agents/`, `hooks/` and `.mcp.json` **do not exist yet** — create them
yourself if you need them, with the directory names exactly as in the table above.

### Writing a skill: a complete example {#写一个-skill完整例子}

Take "generate release notes", from nothing to confirmed loaded.

**Step 1: create the directory.** The directory name is the skill name, and must match `name` in
the frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Step 2: write `plugin/skills/release-notes/SKILL.md`.** The filename must be `SKILL.md`,
uppercase. The format is YAML frontmatter plus a Markdown body, with two frontmatter fields:

| Field | Purpose |
|---|---|
| `name` | The skill's identifier. Matches the directory name |
| `description` | **This one line is all the model looks at when deciding whether to use it.** Say *when it should be used*, not *what it is* |

A minimal file you can use as-is:

````markdown
---
name: release-notes
description: Use when putting together release notes. Use it when the user says "write release notes", "what changed in this version", or "cut a release".
---

# Release notes

## How to gather material

```bash
git describe --tags --abbrev=0        # the previous tag
git log --oneline <previous tag>..HEAD # the commits in this version
```

## Output format

Three sections, each an unordered list, one line per item, describing changes the user can
perceive; no internal refactoring:

- **Added** — what this version can do that it could not before
- **Fixed** — what was fixed, with the symptom stated in one sentence
- **Breaking** — what has to be changed by hand when upgrading. Omit the whole section if there is none

## Boundaries

- Do not invent a version number; read `version` from `pyproject.toml`.
- If you are unsure whether a commit is user-perceptible, list it and ask; do not decide for the user.
````

There is no required format for the body — it is simply a piece of text that gets read into the
context. Follow the style of
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
stating **when to use it**, **the steps**, **what the output should look like**, and **where the
boundaries are** is more useful than piling up background knowledge.

**Step 3: confirm it was loaded.** Check exactly one certain thing — whether the directory is
there at all:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Only `/path/to/flower/plugin True` means that `if` in `build_options()` will be entered. `False`
means it was not loaded — **and nothing errors at runtime**, see the warning below.

**Do not use "run a request and see whether the `example` skill got invoked" as verification.**
Skills are probabilistic: if the model did not invoke it, that could mean it was not installed, or
just that the model did not think the current task needed it — the signal cannot distinguish the
two. Also, `build_options()` never sets the SDK's session-level `skills=` option, and whether
skills from a plugin actually appear in the coordinator's list of options has not been verified in
practice. The `True`/`False` from the `PLUGIN_DIR` command above is certain; use that.

To name specific skills for a given [worker](glossary.md#执行者), use `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
use the `name` from `SKILL.md`, and the SDK also accepts the qualified form
`plugin-name:skill-name`.

!!! warning "An installed flower has no `plugin/` — none of the three install paths do"
    `PLUGIN_DIR` goes three levels up from `flower/core/agent.py` and then into `plugin/`. Running
    from a source checkout, that is the repo root's `plugin/`; but the wheel packages only the
    `flower` directory (`[tool.hatch.build.targets.wheel] packages = ["flower"]` in
    `pyproject.toml`), so after installation into site-packages there is no `site-packages/plugin`,
    `PLUGIN_DIR.is_dir()` is false — **silently skipped, no error, no warning**.

    **This is not a container problem; the scope is much larger.** Every path in `install.sh` —
    `uv tool install`, `pipx install`, bootstrapping uv and then using uv, and the
    `pip install --user` fallback — installs the wheel. Which means **a one-line install of flower
    always has the domain capability package silently disabled**. The container is just one
    instance of the same problem: `docker/Dockerfile` only `COPY`s `pyproject.toml`, `flower/` and
    `examples/`, so `plugin/` never enters the image.

    Tracked in [issue #15](https://github.com/ChenyuHeee/flower/issues/15). After installing, run
    the `PLUGIN_DIR` command above to check: `False` means this installation has no domain
    capability package. To use one, you currently have to run from a source checkout.

### Why `setting_sources=[]` forces domain capability through plugins {#setting_sources-为什么逼着领域能力走-plugin}

The same function also has this line:

```python
"setting_sources": [] if portable else ["project"],
```

The SDK's default is `None` = read all three sources: `~/.claude/settings.json` (user),
`.claude/settings.json` (project), `.claude/settings.local.json` (local). flower passes `[]` by
default, turning **all of them off**.

| | Read? | Consequence |
|---|---|---|
| `~/.claude/` (host machine) | No | Behavior is identical on another machine; results do not differ because "I configured this box" |
| Project `.claude/` | No | Anything in `.claude/skills/` or `.claude/agents/` has **no effect whatsoever** under flower |
| `plugin/` | Yes | The path is hard-coded in the code and travels with the repo |
| Credentials | Not through this channel | You must bring your own `.env`; the `env` block in `~/.claude/settings.json` and `settings.local.json` is only a last-resort fallback, and **only 9 credential keys are taken** — see [configuration](config.md) |

`.claude/` having no effect **is not a missing feature, it is the definition of this constraint**:
as long as a single byte is read from the host machine, "identical behavior on another machine" is
false. That leaves exactly one channel for domain capability — `plugin/`, which travels with the
repo.

Two switches (both on `build_options()`, with the portable set as the defaults):

| Parameter | Default | What changing it does |
|---|---|---|
| `portable` | `True` | Pass `False` → `setting_sources` becomes `["project"]` and the project's `.claude/` starts being read (SDK side: reading `CLAUDE.md` requires `"project"`). Portability goes away with it |
| `use_plugin` | `True` | Pass `False` → `plugin/` is not attached at all, and domain capability rests entirely on `AgentSpec.instructions` |

Incidentally: `instructions` goes through [append](glossary.md#叠加) (the `append` of
`system_prompt`), a different channel from plugins — the former is in the context every turn, the
latter is loaded on demand. Put short, mandatory discipline in `instructions`; put long,
occasionally-useful knowledge in a skill.

## 3. Documentation site {#三文档站}

The site you are reading is built with mkdocs-material; the sources are under `docs/` in the repo,
and pushing to `main` publishes it automatically.

| Piece | What it is |
|---|---|
| Config | `mkdocs.yml`, `docs_dir: docs` |
| Multilingual | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`, … with `zh` as the default language |
| Dependencies | `docs-requirements.txt` (pinned). **Not** the `docs` extra in `pyproject.toml` — CI installs the former |
| Build | `mkdocs build --strict`. Broken internal links or nav entries pointing at non-existent pages fail the build outright, rather than silently shipping a 404 |
| Redirects | `hooks/redirects.py`, which **after** the build writes meta-refresh stub pages by final URL, connecting the old flat addresses (`/start/`, `/workflow/`, `/case-ht001/`, …) to their new locations |
| Deploy | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, published to GitHub Pages |

Editing the docs locally:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # local preview
mkdocs build --strict         # run before committing, the same command CI uses
```

CI triggers on a push to `main` **and** only when the changes touch these paths; you can also
trigger it manually from the Actions page via `workflow_dispatch`:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Why `install.sh` is served from Pages {#installsh-为什么从-pages-发}

The end of the build step has one line:

```yaml
- run: cp install.sh site/install.sh
```

The install script is dropped into the site artifact, so it is served from the docs domain, and
the one-line install looks like this:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

The reason is entirely practical: **`raw.githubusercontent.com` is unreachable from inside China,
while `*.github.io` works** (measured). The script itself lives at the repo root; publishing just
copies it once more — no second copy of the content to maintain, and no extra CDN.

What `install.sh` does on its own: pick a Python tool installer (`uv` > `pipx` > install `uv` >
`pip --user`), install flower from GitHub, then print the next step. It **does not touch
credentials** — the first `flower` run asks, and stores them in `~/.config/flower/.env`.
