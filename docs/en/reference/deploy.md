# Deployment and extension

Moving flower elsewhere means dealing with three things: containers (fencing in unrestricted Bash, and incidentally testing the claim of "no CLI needed"), [plugin](glossary.md#plugin) (domain capabilities travel with the repo, regardless of what the host machine has installed), and the docs site (push to `main` and it publishes itself; `install.sh` is served from the Pages domain). The three sections are independent; read what you need.

## 1. Containers {#一容器}

### Why a container {#为什么要容器}

**First, to fence things in.** The [worker](glossary.md#执行者) doing the work has **unrestricted Bash** — flower's Bash allowlist (`delegate_guard`) only covers the [main thread](glossary.md#主线程), and anyone sent out has to be able to run tests, so this is deliberate. Inside the container only your project directory is mounted; the framework source sits at `/opt/flower` inside the image, and nothing else on the host is visible.

**Second, the container is itself the test of the [portable](glossary.md#可移植) constraint.** There is no Claude Code CLI in the image and no Node, only Python and `claude-agent-sdk` — requests go out through the native binary bundled with the wheel. If it runs here, "no CLI needed" is not a claim on paper.

Verified (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| What was checked | Result |
|---|---|
| Is there a CLI in the image | `claude`, `node`, `npm`, `npx` **none of them exist** |
| Bundled binary | `\177ELF` (207M) |
| Real request | sent through `cloud.infini-ai.com/maas` and got an answer, `$0.1741 / 1 turn` (that is the single-turn floor for Opus 5 + 1M window) |
| File ownership | a file written to `/work` inside the container shows as `hechenyu:staff` on the host — mapping is correct |
| Host visibility | inside the container `ls /Users` → `No such file or directory` |

### What is in the image {#镜像里装了什么}

Base image `python:3.13-slim`, plus three apt packages on top. Each one has a reason:

| Installed | Why |
|---|---|
| `python:3.13-slim` | Only Python ≥ 3.10 is needed. No Node, no claude CLI |
| `git` | `--isolate` has to hand each [subagent](glossary.md#subagent) its own worktree |
| `ca-certificates` | HTTPS gateway |
| `libstdc++6` | The binary bundled with the SDK is a Bun-compiled single file that needs it on Linux; the slim image doesn't ship it |

The framework source enters the image via `COPY`, **not a bind mount** — which is why the agent inside the container cannot reach the framework source on the host:

| Path in image | Contents | From |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, with `pip install .` run here | `COPY` |
| `/work` | working directory (`WORKDIR`), the host's `$PWD` mounted here at run time | `docker run -v` |

The entrypoint is `ENTRYPOINT ["flower"]` and `CMD` is empty — running the container with no arguments drops into interactive input (it asks what you want done) instead of printing `--help`. That way you don't have to quote a Chinese request in the shell.

### Why you can't mount the host's `.venv` {#为什么不能把宿主的-venv-挂进去}

The SDK ships per-platform wheels, and the bundled binary is platform-specific:

```text
host       claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
           → _bundled/claude is Mach-O 64-bit arm64, 191M
container  claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Mounting it in doesn't run, so the image has to `pip install` for itself. Turned around, that is also the evidence for portability: the same `pyproject.toml`, a different native binary per platform, and not one line of framework code changes.

### Two scripts {#两个脚本}

| Script | What it does |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Builds the image. `cd` to the repo root, `docker build -f docker/Dockerfile -t flower-box .`; when `FLOWER_MIRRORS=1` (the default) it first pulls `python:3.13-slim` from a registry mirror and retags it, and passes the pip / apt `--build-arg`s |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Runs once. Check the credentials file → check whether `$PWD` can actually be mounted in → decide whether there is a TTY → `docker run` |

The switches for `docker/build` are all environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | image tag |
| `FLOWER_MIRRORS` | `1` | `0` = swap no mirror at all, everything goes upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | pull the base image from here and retag it to `python:3.13-slim`, so `FROM` hits the local copy |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | passed as `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | passed as `--build-arg APT_MIRROR` |

The last three only take effect when `FLOWER_MIRRORS=1` — the `FLOWER_MIRRORS=0` branch sets no build-args at all.

`docker/flowerbox` reads two:

| Variable | Default | Meaning |
|---|---|---|
| `FLOWER_HOME` | one level above the script's own location (i.e. the repo root) | where to look for `.env`. If `$FLOWER_HOME/.env` isn't there it exits 1 |
| `FLOWER_IMAGE` | `flower-box` | which image to run |

`FLOWER_HOME` is derived from the script's own location rather than hard-coded, so the repo works wherever you clone it.

### Build the image and start a container {#跑起来}

```bash
docker/build                       # once is enough
cd ~/any-project-dir               # must be under $HOME, see the mount boundary below
/path/to/flower/docker/flowerbox   # no arguments → it asks what you want, no quoting needed
```

If your network reaches pypi.org / Docker Hub fine, build like this:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox` takes exactly the same arguments as `flower` — it appends `"$@"` to the `ENTRYPOINT` verbatim. `--clarify-only`, `--asks N`, `--timeout SECONDS`, `--isolate`, `-v` all work; full table in [command line](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "build me an X"
```

What actually runs is this line (`-t` is added only when there is a TTY, see below):

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
in image               /opt/flower ← framework source, **not mounted**, can't be modified on the host
```

So running inside a repo subdirectory like `flower/human-test/HT001` is also safe: only `HT001` is mounted in, and the framework source is outside the mount.

| Thing | Still there after exit? | Why |
|---|---|---|
| everything under the host's `$PWD`, including `runs/` and the [workbench](glossary.md#工作台) `.flower/` | yes | it is the directory mounted as `/work` |
| anything written to other paths inside the container | no | `--rm`, deleted the moment the container exits |
| credentials | never enter an image layer | via `--env-file`; `.dockerignore` excludes `.env`, so even `COPY . .` can't drag it in |

!!! danger "The project directory must be under `$HOME`, or output is silently lost"
    **colima only mounts `$HOME` into the VM by default** (`mount | grep virtiofs` → `mount0 on /Users/<you>`).
    Run somewhere like `/tmp` and `-v` will create an **empty directory** inside the VM; whatever is written
    there is never visible on the host, **and there is no error** — output, the [brief](glossary.md#需求确认书),
    `runs/`, all gone. Hit this once: a `once` run finished, $0.17 spent, and `runs/` simply did not exist on the host.

    `flowerbox` now blocks this case: if `$PWD` is under `$HOME` it goes straight through; if not, it writes a
    probe file into `$PWD` and starts a container to actually check `test -f /work/<probe>` (extra mounts pass
    too). If the check fails it exits 1 and tells you `colima start --mount '<path>:w'`. The probe needs a
    container, so `docker/build` has to have run first.

### How credentials get into the container {#凭证}

Through `docker run --env-file`, **never into an image layer**. `flowerbox` reads `$FLOWER_HOME/.env`, which defaults to the `.env` at the repo root:

```bash
cp .env.example .env       # fill in the token; .env is already gitignored
```

Note that `flower setup` writes `~/.config/flower/.env`, and **`flowerbox` does not look at that path**. If you already configured it with `setup` and don't want a second copy, point `FLOWER_HOME` at it:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Key names, precedence, and how to fill in the gateway: see [configuration](config.md).

!!! warning "With no TTY, a question hangs until `--timeout`"
    `flowerbox` adds `-t` only when `[ -t 0 ]` — `docker run -t` in a pipe or in CI fails outright with
    "the input device is not a TTY"; `-i` is always needed, otherwise stdin never gets in.

    Answers arrive on standard input. With no TTY the first `input()` raises `EOFError` → the current question
    is treated as "input closed" and skipped, and **the answering thread exits**, so from the second question on
    nobody is listening and you just wait out the full `--timeout` (1800 seconds by default). Unattended runs
    need an explicit `--timeout 0`. The script prints a reminder line when it detects there is no TTY.

### git submodule {#git-submodule}

`.gitmodules` has exactly one entry:

| path | url | what it is |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | the code repository **produced by** the [HT001](../cases/ht001.md) run, kept for the record |

A plain `git clone` doesn't fetch it, and `human-test/HT001` is just an empty directory (a leading `-` in `git submodule status` means exactly that). Whether you need to care:

| What you want to do | Initialize it? |
|---|---|
| Run flower, build the image | **No.** `.dockerignore` excludes `human-test/`, and `Dockerfile` only `COPY`s `pyproject.toml` / `flower` / `examples` anyway |
| Read HT001's produced code locally | Yes: `git submodule update --init human-test/HT001`, or `git clone --recurse-submodules` from the start |

### Networks in mainland China: why all those mirror swaps {#国内网络为什么有那一堆镜像替换}

Installing this behind the firewall, the bottleneck isn't bandwidth, it's the international routes. The default `docker/build` already swaps everything that needs swapping, and `FLOWER_MIRRORS=0` turns all of it off in one go. Below are the measurements and the reasoning behind the four swaps — skip it if your network doesn't have this problem.

??? note "Measured speeds and the four swaps (2026-09-06, macOS/arm64)"

    | Source | Speed |
    |---|---|
    | `pypi.org` (index) | 32 KB/s |
    | `files.pythonhosted.org` (package files) | **284 B/s** |
    | `github.com` (release asset, direct) | 22 KB/s |
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
    | `dockerproxy.net` (Docker Hub proxy) | works (returns the manifest directly) |

    When measuring, don't mistake the **index page** for package files: `mirrors.aliyun.com/pypi/simple/` serves
    that page at 7.4 MB/s, while the actual 95.9 MB wheel only comes at 1.4 MB/s (152 KB/s inside the VM —
    colima's user-mode networking costs you). Estimate time from the package-file numbers.

    **Swap 1 — colima's VM image.** colima doesn't use a plain Ubuntu cloud image, it uses its own custom image
    with **docker preinstalled** (a release asset of `abiosoft/colima-core`), so starting the VM doesn't need apt
    to install docker, which sidesteps the unreachable `download.docker.com`. Download it yourself and feed it in
    with `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # verify: get the digest from the GitHub API. Don't skip this — you're going to run it as a VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    The proxy drops the stream partway through (curl 56 in practice); `-C -` resumes, just rerun a few times.

    **Swap 2 — apt inside the VM.** Even with the preinstalled-docker image, lima's boot script
    `30-install-packages.sh` still runs an `apt-get update` in order to install `rsync` — hitting
    `ports.ubuntu.com` (26 KB/s) and `download.docker.com` (4 KB/s), which can hang for tens of minutes.

    What to do (**read `/mnt/lima-cidata/boot.sh` before you touch anything**: for a failed boot script it only
    emits `WARNING` + `CODE=1` and continues, and at the end it **always** writes `/run/lima-boot-done`, so
    letting that step fail is safe):

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
      pkill -f "apt-get update"          # boot.sh runs to the end and writes the done marker
    '
    # colima start then exits normally; install rsync afterwards (1.95 MB/s now)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    While you're there, add `127.0.0.1 lima-colima` to the VM's `/etc/hosts` to silence the
    `sudo: unable to resolve host` warnings.

    **Swap 3 — the base image.** `docker/build` first pulls `python:3.13-slim` from `dockerproxy.net` and
    retags it, so the Dockerfile's `FROM` hits the local copy. Measured: `dockerproxy.net` returns the manifest
    directly (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` return 401, `hub.rat.dev` 302,
    `docker.xuanyuan.me` 403.

    **Swap 4 — apt and pip inside the container.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) and
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Note that `PIP_INDEX_URL` is also an
    environment variable pip itself honours, so declaring the `ARG` is enough for pip in the RUN step to pick it
    up — it works without writing `--index-url` explicitly.

    Total one-off setup time (on the network described above) is about 25 minutes, most of it the 364 MB VM image
    and the 95.9 MB SDK wheel. After that `flowerbox` starts in seconds.

## 2. plugin {#plugin}

### What a plugin is, and how the SDK loads it {#它是什么}

A **domain capability package** that travels with the repo. The framework code contains no domain knowledge; all of it lives in the `plugin/` directory at the repo root, cloned with the code, reviewed with the code, tagged with the code.

The SDK-side wiring is two lines in `build_options()` in
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py):

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Together with `setting_sources=[]` (covered separately below), this is why flower can be both "[portable](glossary.md#可移植)" and "aware of your domain": it doesn't ask what the host machine has installed, it only knows this one directory that came with the repo.

### Directory layout {#目录布局}

| Path | Contents | When it takes effect | Who decides |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | the package's identity: `name`, `description`, `version`, `author` | read once at load | — |
| `plugin/skills/<name>/SKILL.md` | domain knowledge, loaded on demand | **probabilistic** — used only if the model judges it relevant | the model |
| `plugin/agents/<name>.md` | subagent with its own context window | delegated by the model, or named explicitly in a [workflow](glossary.md#流程) | model / you |
| `plugin/hooks/hooks.json` | intercept tool calls | **deterministic** — runs on match | code |
| `plugin/.mcp.json` | external tool integration | registered as tools, same as the built-in ones | the model |

**The difference between probabilistic and deterministic is the basis for choosing, not a difference in wording:**

- A skill is **knowledge sitting there**. The model sees its `description` and only reads it if it thinks it is relevant to the current task. The relevance judgement belongs to the model, so the same request run twice may use it once and not the other time.
- A hook is **code**. It runs when the event matches, regardless of whether the model wants it or knows about it. flower's own [spill](glossary.md#落盘) and [isolation](glossary.md#隔离) are hooks, precisely because they cannot be allowed to work "sometimes".

So there is exactly one criterion: **does this have to happen every time?** It must — write a hook. It's merely "useful to know" — write a skill. Writing a must-happen thing as a skill stakes discipline on a single judgement by the model.

Right now `plugin/` in the repo holds only two things: `.claude-plugin/plugin.json` and `skills/example/SKILL.md`. `agents/`, `hooks/`, `.mcp.json` **do not exist yet** — create them yourself if you need them, with the directory names exactly as in the table above.

### Writing a skill: a complete example {#写一个-skill完整例子}

Take "generate release notes", from nothing to confirmed working.

**Step 1: create the directory.** The directory name is the skill name, and must match `name` in the frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Step 2: write `plugin/skills/release-notes/SKILL.md`.** The filename must be `SKILL.md`, uppercase. The format is YAML frontmatter plus a Markdown body, with two frontmatter fields:

| Field | Purpose |
|---|---|
| `name` | the skill's identifier. Matches the directory name |
| `description` | **this one line is all the model looks at when deciding whether to use it**. Say clearly *when to use it*, not *what it is* |

A minimal file you can use as-is:

````markdown
---
name: release-notes
description: Use when putting together release notes. Use it when the user says "write release notes", "what changed in this version", "cut a release".
---

# Release notes

## Where to get the material

```bash
git describe --tags --abbrev=0        # the previous tag
git log --oneline <previous tag>..HEAD   # commits in this release
```

## Output format

Three sections, each an unordered list, one line per item, describing changes the user can perceive; no internal refactors:

- **Added** — what this version can do that it couldn't before
- **Fixed** — what was fixed, one sentence on the symptom
- **Breaking** — what has to be changed to upgrade. If there is none, drop the whole section

## Boundaries

- Don't invent the version number; read `version` from `pyproject.toml`.
- If you're unsure whether a commit is perceptible to the user, list it and ask; don't decide for them.
````

There is no required format for the body — it is just a piece of text read into the context. Follow the style of
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
stating **when to use it**, **the steps**, **what the output should look like** and **where the boundaries are** is more useful than piling up background knowledge.

**Step 3: confirm it was loaded.** Check exactly one certain thing — whether the directory is there at all:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Printing `/path/to/flower/plugin True` means the `if` in `build_options()` will be entered. Printing `False` means it wasn't loaded, and **there is no error at run time**; see the warning below.

**Don't use "run something and see whether the `example` skill got invoked" as verification.** Skills are probabilistic: if the model didn't call it, that could mean it isn't installed, or just that it didn't think the current task needed it — that signal can't tell the two apart. Also, `build_options()` never sets the SDK's session-level `skills=` option, and whether skills from the plugin actually appear in the coordinator's list of options has not been measured. The `True`/`False` from `PLUGIN_DIR` above is certain; use that.

To name which skills a given [worker](glossary.md#执行者) gets, use `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
use the `name` from `SKILL.md`, and the SDK also accepts the qualified form `plugin-name:skill-name`.

!!! warning "An installed flower has no `plugin/` — none of the three install methods do"
    `PLUGIN_DIR` goes three levels up from `flower/core/agent.py` and then into `plugin/`. Running from a source
    checkout that is the repo root's `plugin/`; but the wheel packages only the `flower` directory
    (`[tool.hatch.build.targets.wheel] packages = ["flower"]` in `pyproject.toml`), so after installing into
    site-packages there is no `site-packages/plugin`, `PLUGIN_DIR.is_dir()` is false — **silently skipped, no
    error, no warning**.

    **This is not a container problem, the scope is far wider.** Every path in `install.sh` — `uv tool install`,
    `pipx install`, bootstrapping uv and then using uv, and the `pip install --user` fallback — installs a wheel.
    Which means **a flower installed with the one-liner has its domain capability package silently disabled,
    every time**. The container is just one instance of the same problem: `docker/Dockerfile` only `COPY`s
    `pyproject.toml`, `flower/`, `examples/`; `plugin/` never enters the image.

    Tracked in [issue #15](https://github.com/ChenyuHeee/flower/issues/15). After installing, run the
    `PLUGIN_DIR` command above to check yourself: `False` means this install has no domain capability package.
    To use one, right now you have to run from a source checkout.

### Why `setting_sources=[]` forces domain capabilities through the plugin {#setting_sources-为什么逼着领域能力走-plugin}

The same function also has this line:

```python
"setting_sources": [] if portable else ["project"],
```

The SDK default is `None` = read all three sources: `~/.claude/settings.json` (user),
`.claude/settings.json` (project), `.claude/settings.local.json` (local). flower passes `[]` by default, turning **all of them** off.

| | Read? | Consequence |
|---|---|---|
| `~/.claude/` (host machine) | no | behaviour is identical on another machine; results don't differ because "I configured this box" |
| project `.claude/` | no | anything placed in `.claude/skills/` or `.claude/agents/` has **no effect whatsoever** under flower |
| `plugin/` | yes | the path is hard-coded in the code and travels with the repo |
| credentials | not through this channel | you must bring your own `.env`; the `env` block in `~/.claude/settings.json` and `settings.local.json` is only a last-resort fallback, and **only 9 credential keys are taken**, see [configuration](config.md) |

`.claude/` having no effect **is not a missing config, it is the definition of the constraint**: read a single byte from the host machine and "identical behaviour on another machine" no longer holds. So domain capabilities have exactly one channel — `plugin/`, which travels with the repo.

Two switches (both on `build_options()`, with the portable set as the defaults):

| Parameter | Default | What changes |
|---|---|---|
| `portable` | `True` | pass `False` → `setting_sources` becomes `["project"]` and the project `.claude/` starts being read (SDK side: reading `CLAUDE.md` requires `"project"`). Portability goes with it |
| `use_plugin` | `True` | pass `False` → `plugin/` is not attached at all, and domain capability rests entirely on `AgentSpec.instructions` |

Incidentally: `instructions` goes through [append](glossary.md#叠加) (`system_prompt`'s `append`), a different channel from the plugin — the former is in the context every turn, the latter is loaded on demand. Short, mandatory discipline goes in `instructions`; long knowledge that is only occasionally useful goes in a skill.

## 3. The docs site {#三文档站}

The site you are reading is built with mkdocs-material; the source files are under `docs/` in the repo, and pushing to `main` publishes it.

| Piece | What it is |
|---|---|
| Config | `mkdocs.yml`, `docs_dir: docs` |
| Multi-language | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`… default language is `zh` |
| Dependencies | `docs-requirements.txt` (versions pinned). **Not** the `docs` extra in `pyproject.toml` — CI installs the former |
| Build | `mkdocs build --strict`. A broken internal link, or nav pointing at a page that doesn't exist, fails the build outright instead of silently shipping a 404 |
| Redirects | `hooks/redirects.py`, which **after** the build writes meta-refresh stub pages against the final URLs, wiring the old flat addresses (`/start/`, `/workflow/`, `/case-ht001/`…) to their new locations |
| Deploy | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, published to GitHub Pages |

Editing docs locally:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # local preview
mkdocs build --strict         # run before committing; the same command CI uses
```

CI triggers on a push to `main` **and** changes hitting these paths; you can also trigger `workflow_dispatch` manually from the Actions page:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Why `install.sh` is served from Pages {#installsh-为什么从-pages-发}

The last line of the build step:

```yaml
- run: cp install.sh site/install.sh
```

The install script is dropped into the site artifact, so it lives on the docs site's domain, and the one-line install looks like this:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

The reason is practical: **`raw.githubusercontent.com` is unreachable from inside China while `*.github.io` works** (measured). The script itself lives at the repo root; publishing just copies it once more — no second copy of the content to maintain, and no extra CDN.

What `install.sh` does on its own: pick a Python tool installer (`uv` > `pipx` > install `uv` > `pip --user`), install flower from GitHub, then tell you the next step. It **does not touch credentials** — the first `flower` run asks, and stores them in `~/.config/flower/.env`.
