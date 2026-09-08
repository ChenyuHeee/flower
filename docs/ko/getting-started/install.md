# 설치

flower를 설치하는 데 필요한 건 Python ≥ 3.10뿐이다. 런타임 의존성은 `claude-agent-sdk` 하나이고, 요청을 보내는 네이티브
바이너리는 그 wheel 안에 들어 있다. 그래서 **Node도 필요 없고, Claude Code CLI도 필요 없다**. 이 페이지는 처음부터
끝까지 한 번 훑는다: 한 줄 설치, 소스에서 설치, 첫 인증 설정, 그리고 "정말 제대로 깔렸다"를 증명하는 명령 하나.
여기까지 되면 [빠른 시작](quickstart.md)으로 간다.

## 설치 전: Python 확인 {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

`True 3.13.7` 정도가 나오면 충분하다. `False`가 나오거나 `python3` 자체가 없으면 먼저 설치하고
(`brew install python` / `apt install python3`), 아니면 설치 스크립트가 바로 종료된다.

| 필요 | 불필요 |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31`도 한 번 자체 확인한다) | Node.js |
| API 엔드포인트로 나가는 네트워크 | Claude Code CLI |
| API key 또는 게이트웨이 token 한 벌(설치 후에 넣어도 된다) | 호스트의 `~/.claude/` 설정(인증만 유일한 예외, 아래 참고) |

패키지 이름은 `flower`, 버전은 `0.1.0`, 유일한 런타임 의존성은 `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material`은 CI에서 문서 사이트를 빌드할 때만 쓰고, flower 실행에는 필요 없다.

## 한 줄 설치 {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

설치가 끝나면 터미널은 이렇게 나온다(색은 생략):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

핵심은 `== 装好了 <절대경로>` 그 한 줄이다 — 스크립트가 직접 `command -v flower`를 한 번 실행한 결과다
(`install.sh:60-61`). 경로가 찍혔다면 `flower`가 이미 PATH에 있다는 뜻이다.

### 설치 스크립트가 실제로 하는 일 {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh)는 세 가지만 한다: Python 도구
설치기를 하나 고르고, GitHub에서 설치하고, 다음 단계를 알려준다. **당신의 인증 정보는 한 글자도 건드리지 않는다**
(`install.sh:7-8`). 설치 소스는 `git+https://github.com/ChenyuHeee/flower.git`로 고정되어 있다(`install.sh:11`).

설치기는 순서대로 시도하고, 처음 성공한 데서 멈춘다(`install.sh:33-57`):

| 순서 | 조건 | 실제 명령 | 실행 파일이 놓이는 곳 |
|---|---|---|---|
| 1 | `uv`가 PATH에 있음 | `uv tool install --force <REPO>` | uv의 tool bin 디렉터리, 보통 `~/.local/bin/flower` |
| 2 | `uv`는 없고 `pipx`는 있음 | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | 둘 다 없음 | 먼저 `curl -LsSf https://astral.sh/uv/install.sh \| sh`로 uv를 설치하고, 되면 1번으로 돌아감 | 1번과 같음 |
| 4 | 3번에서 uv도 설치 실패 | `python3 -m pip install --user --upgrade <REPO>` | 사용자 스크립트 디렉터리 — **macOS에서는 `~/.local/bin`이 아니다** |

네 경우 모두 같은 console script를 설치한다: `flower = "flower.cli:main"`(`pyproject.toml:12`). 설치 후
`python -m flower.cli`로 호출해도 결과는 같다(`cli.py:1451-1452`).

!!! warning "설치 스크립트를 다시 돌리면 확인 없이 강제로 덮어쓴다"
    세 설치 명령에 각각 `--force`, `--force`, `--upgrade`가 붙어 있다(`install.sh:37`, `:40`, `:54`).
    다시 돌린다는 건 기존 설치를 그냥 덮는다는 뜻이다 — 업그레이드가 바로 이 방식이지만, 미리 한마디
    물어봐 주리라 기대하지는 마라.

### `flower` 명령을 PATH에 올리는 법 {#flower-命令怎么上-path}

`command -v flower`로 찾이지 않으면 스크립트가 `$HOME/.local/bin`을 `~/.zshrc`나 `~/.bashrc`에 추가하라고 안내한다
(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install`과 `pipx install`은 모두 여기에 넣으므로 이 안내는 그 둘에 대해서는 정확하다. **하지만 4번 경로
(`pip install --user`)는 아닐 수 있다** — 안내문의 디렉터리는 하드코딩되어 있는데, pip의 사용자 스크립트 디렉터리는
플랫폼을 따라간다. macOS에서는 `~/Library/Python/3.13/bin`이다. 직접 확인해 보라:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

출력이 예를 들어 `/Users/you/Library/Python/3.13/bin`이라면 — `~/.local/bin`이 아니라 그 디렉터리를 PATH에 넣고,
터미널을 새로 열거나 `source`를 한 번 해라.

## 소스에서 설치 {#从源码装}

코드를 읽고, 프레임워크를 고치고, `tests/`에 있는 오프라인 검증을 돌리려면 소스에서 설치한다:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

끝나고 `.venv/bin/flower --help`를 하면 usage 몇 줄이 나와야 한다.

venv 안 실행 파일의 shebang은 **절대 경로**라서 activate할 필요가 없다. 심볼릭 링크만 걸면 어느 디렉터리에서든 쓸 수 있다:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`~/.local/bin`이 PATH에 있으면, 어떤 프로젝트 디렉터리로 `cd`해서 `flower`를 쳐도 이 venv의 인터프리터와
이 소스가 돌아간다.

소스 설치에는 인증 파일을 놓을 자리가 하나 더 있다: **저장소 루트의 `.env`**(탐색 순서에서 5번째,
[설정 · 인증 탐색 우선순위](../reference/config.md#凭证查找优先级) 참고). 개발할 때는:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN 채우기
```

`.env`는 이미 `.gitignore`에 들어 있어서 버전 관리에 올라가지 않는다. pip / pipx / uv로 설치한 flower에는 이 자리가
**없다** — site-packages 안에 있으니 "저장소 루트"라는 게 없다 — 그러니 그런 설치 방식에서는 아래의 전역 인증 파일을 쓴다.

## 자동 업데이트 {#自动更新}

flower는 아직 빠르게 바뀌는 중이라, **pip / pipx / uv로 설치한 쪽은 기본적으로 스스로 업데이트한다**: 사흘 전 버전을 쓰는
사람이 보고한 버그가 이미 고쳐져 있으면 양쪽 모두 시간을 낭비한다. 이건 "켤까 말까"를 묻는 스위치식 질문이 아니다 —
기본은 켜짐이고, 끄려면 환경 변수를 설정한다.

하는 일(`update.py:116-129`):

1. `flower`가 시작될 때마다 **백그라운드 스레드**에서 GitHub `main`의 최신 commit을 한 번 조회한다
   (`update.py:70-80`). 메인 흐름은 1초도 기다리지 않는다 — 이게 첫 번째 불변식이다.
2. 로컬에 설치된 commit과 다르면, 원래 설치 방식대로 업데이트 명령을 한 번 돌린다: `uv`가 있으면
   `uv tool install --force`, `pipx`가 있으면 `pipx install --force`, 둘 다 없으면
   `pip install --user --upgrade`(`update.py:83-93`).
3. **설치가 끝나도 지금 돌고 있는 이 프로세스를 갈아치우지는 않는다** — 다음번 `flower` 실행부터 새 버전이다
   (`update.py:113`). 실행 도중에 교체되는 건 가장 추적하기 어려운 종류의 장애다.
4. 스로틀링: 24시간에 최대 한 번만 조회하고, 타임스탬프는 `~/.config/flower/.update`에 기록한다
   (`update.py:32`, `:36-37`, `:124`).
5. **실패는 전부 조용히 넘어간다**. 네트워크가 없든, GitHub가 죽었든, 설치가 안 되든 — 당신 작업을 끊지 않는다
   (`update.py:79`, `:108-110`).

**소스(git)에서 돌리는 경우는 영향을 받지 않는다.** 업데이트 명령 단계에서 저장소에 `.git`이 있는지 먼저 보고,
있으면 곧바로 `None`을 반환하고 아무것도 하지 않는다(`update.py:83-87`) — 당신의 작업 트리는 `git` 관할이지
이것의 관할이 아니다. 비대화형(stdin이 터미널이 아닌 경우, 예: 파이프 / CI)에서도 통째로 건너뛴다(`update.py:121`).

끄려면:

```bash
export FLOWER_NO_UPDATE=1
```

비어 있지 않은 값이면 무엇이든 인정된다(`update.py:33`, `:121`). CI, 오프라인 환경, 옛 버전 동작을 재현해야 할 때 쓴다.

## 첫 실행: 인증 설정 {#第一次跑配凭证}

`go`, `run`, `once` 세 실행 진입점은 모두 시작 부분에서 `ensure_credentials()`를 호출한다(`cli.py:1192`, `:1160`, `:1225`).
관문은 두 개다:

1. **있는가** — 우선순위대로 한 번 찾고, 없으면 그 자리에서 묻는다.
2. **쓸 수 있는가** — 실제로 API를 한 번 때려 본다. `max_tokens=16`짜리 최소 요청(`env.py:120-123`)이라 비용은 거의 없다.
   만료된 token, 잘못 쓴 게이트웨이 주소는 환경 변수만 봐서는 알 수 없고, 찔러보지 않으면 몇 분 뒤에야 터진다.

인증이 없으면 첫 `flower` 실행은 이 화면에서 멈춘다(`cli.py:1358-1388`):

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

1번은 필수다. 비워 두면 빨간 글씨로 `没给 token,取消。`를 찍고 종료한다. 2번, 3번은 그냥 엔터를 쳐도 된다.
공식 엔드포인트를 쓴다면 2번은 비워 두고, 서드파티 게이트웨이라면 그 루트 주소를 넣되 **`/v1`은 붙이지 마라** —
flower의 프로브는 `<BASE_URL>/v1/messages`로 때린다(`env.py:162`).

답을 다 하면 기록되는 키(`cli.py:1378-1386`):

| 당신이 넣은 것 | `.env`에 기록되는 키 |
|---|---|
| token이 `sk-ant-`로 시작 | `ANTHROPIC_API_KEY` |
| 그 외 token | `ANTHROPIC_AUTH_TOKEN` |
| 게이트웨이 주소가 비어 있지 않음 | `ANTHROPIC_BASE_URL` |
| 모델명이 비어 있지 않음 | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` **세 개를 한꺼번에** |

파일 위치는 `${XDG_CONFIG_HOME:-~/.config}/flower/.env`(`env.py:39-42`)이고, **파일 전체를 덮어쓴 뒤**
`chmod 0o600`을 건다(`cli.py:1336-1347`). 이게 "한 번 설치하면 어디서나 적용"의 그 파일이다 —
프로젝트 디렉터리를 옮겨도 다시 설정할 필요가 없고, 각 변수의 의미는 [설정](../reference/config.md#环境变量)에 있다.

### 이 머신에 Claude Code가 설치돼 있으면 아무것도 안 물어볼 수도 있다 {#本机装过-claude-code-的话可能一个问题都不问}

인증 탐색에는 **마지막 폴백**이 하나 있다: `~/.claude/settings.json`을 읽고, 이어서 `~/.claude/settings.local.json`을
읽어서, 그 `env` 블록에서 인증 키 9개를 가져온다(`env.py:56-75`, `:109-111`). 이 머신에 Claude Code를 이미 설정해 둔
사람은 `flower`만 실행하면 바로 일할 수 있고, 설정 화면은 아예 뜨지 않는다 — `install.sh:77`이 홍보하는 게 바로 이거다.

!!! warning "제품 안에 나오는 “flower는 ~/.claude/settings.json을 읽지 않는다”는 문구는 틀렸다"
    인증을 전혀 찾지 못했을 때 flower가 찍는 에러의 마지막 줄은
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    이다(`env.py:184-194`, 그 문장은 `:192`). **코드가 기준이다: 읽는다.**
    `env.py:56-75`는 그 두 파일의 `env` 블록을 명시적으로 읽는다. 다만 인증 키 9개만 가져올 뿐,
    다른 어떤 설정도 넘겨받지 않는다. 저 문장을 읽고 이 머신의 Claude Code 설정이 무시된다고 단정하지 마라.
    전체 사슬은 [설정 · 인증 탐색 우선순위](../reference/config.md#凭证查找优先级)에 있다.

### 다시 설정하고 싶을 때 {#想重新配的时候}

`flower setup`이라는 서브커맨드는 등록되어 있지만(`cli.py:1326-1328`), `_CMDS`가 그걸 빠뜨렸다(`cli.py:937`).
그래서 `flower setup`은 `flower go setup`으로 다시 쓰인다 — "setup"을 하나의 요구로 보고 전체 workflow를 한 번 돌린다.
**현재 그 서브커맨드에 도달할 수 있는 커맨드라인 표기는 하나도 없다**. 여러 에러 문구는 여전히 그걸 실행하라고 하지만.
인증을 바꾸려면:

```bash
$EDITOR ~/.config/flower/.env
```

또는 그 파일의 token을 지우고 `flower`를 다시 실행하면 된다 — 인증 누락 관문이 다시 물어본다(단, 다른 위치,
예를 들어 `~/.claude/settings.json`에도 없어야 한다). 인증이 거부되면(HTTP 401 / 403) 그 자리에서 같은 화면이
떠서 다시 설정하게 하고, 기회는 최대 한 번이다(`cli.py:1416-1428`).

## 제대로 깔렸는지 확인 {#验证装好了没有}

두 단계, 싼 것부터 비싼 것 순으로.

**1단계 — 명령이 있는가(무료)**:

```bash
flower --help
```

이 몇 줄이 보이면 console script가 설치됐고 PATH에도 있다는 뜻이다:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**2단계 — 인증, 엔드포인트, 네이티브 바이너리가 모두 통하는가(몇 센트)**: 가장 싼 실제 실행은 `once`다 —
단일 agent, 기본으로 `Read` / `Glob` / `Grep` 읽기 전용 도구 세 개만 주고,
[goal guard](../reference/glossary.md#目标看守)도 [workbench](../reference/glossary.md#工作台)도 켜지 않는다:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v`는 실행 **직전에** 현재 적용된 설정을 먼저 찍고, token은 앞 4자리만 남긴다(`cli.py:1445-1447`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

이 몇 줄로 게이트웨이를 잘못 연결하지 않았음을 확인한다. 이어서 인증 프로브와 실제 run:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**step 헤더는 없다.** `once`는 `_run_once` → `rt.run()`으로 가고 `_drive` / `Workflow.run`을 거치지 않는데,
`Event("step", …)`는 `workflow/base.py:220`에서만 발생한다 — 그래서 `== 步骤名 ===== 1/1` 같은 구분선은
`once`에서는 나오지 않고, `go` / `run`에서만 나온다.

**`+ 完成` 줄이 뜨면 통과**이고, 그 한 줄이 동시에 세 가지를 증명한다: 인증이 유효하다, 엔드포인트에 연결된다,
`claude-agent-sdk` wheel 안의 네이티브 바이너리가 이 머신에서 실행된다. `- 验一下凭证…` 아래에
`! 凭证被拒`나 `! 网关地址或模型名不对`가 따라 나오면 아래 트러블슈팅 표로 가라.

!!! note "`once`의 소요 시간과 누적 비용은 0으로 표시된다"
    `once`는 이벤트마다 렌더러를 새로 만들기 때문에(`cli.py:1239`, `:579-581`) `用时`은 항상 `0:00`이고,
    상태 줄의 `累计 $`도 절대 누적되지 않는다 — **단일 step의 그 비용은 진짜고, 시간은 아니다.**

    위 줄의 `1 轮 · $0.1741`은 **출처가 있는 실측**이다: 2026-09-06, Linux/arm64 컨테이너에서
    `cloud.infini-ai.com/maas`를 거쳐 나간 실제 요청(`docker/README.md:24-25`),
    즉 Opus 5 + 1M 윈도의 **한 라운드 바닥값**이다. 당신이 위 명령을 직접 돌리면 저장소를 한 번 읽어야 하니
    라운드 수가 더 많고, 비용도 이 바닥값보다 조금 높아진다.
    전체 정산은 `runs/manifest.json`에 있다. [설정 · 디스크 레이아웃](../reference/config.md#磁盘布局) 참고.

## 설치가 안 될 때 {#装不上的时候}

| 증상 | 원인 | 어떻게 할까 |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | `python3`과 `python` 둘 다 3.10+를 만족하지 않음(`install.sh:31`) | `brew install python` / `apt install python3` 후 스크립트를 다시 실행 |
| 스크립트는 설치됐다는데 `flower: command not found` | PATH에 없는 디렉터리에 설치됨 | 위의 "`flower` 명령을 PATH에 올리는 법" 참고. `pip --user` 경로를 탔다면 macOS에서는 `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | 모든 경로 실패, 보통 GitHub나 PyPI로 가는 네트워크 문제 | 안내대로 수동으로 한 번 실행해서 진짜 에러를 확인 |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。`(4줄) | 비대화형 환경(파이프, CI, `nohup`)에 인증이 없음 — 거기서는 설정 화면이 뜨지 않고 바로 종료 | 진짜 터미널에서 `flower`를 한 번 실행해 설정하거나, `~/.config/flower/.env`를 직접 작성 |
| `! 凭证被拒:HTTP 401 …` | token 만료 또는 오타 | 대화형 터미널이면 그 자리에서 다시 설정하게 한다. 비대화형이면 종료 |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` 또는 모델명이 틀림 | BASE_URL은 게이트웨이 루트까지만 쓰고 `/v1`은 붙이지 않는다. 모델명은 게이트웨이 자체의 이름을 쓴다 |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / 타임아웃 / 5xx | **인증 문제가 아니다.** flower는 일부러 재설정을 시키지 않고 그대로 실행하며, [resilience](../reference/glossary.md#韧性) 계층에 맡긴다 |
| `! 标准输入不是终端,没人能回答提问` | 파이프나 CI에서 실행 중 | `--timeout 0`을 붙여 스스로 판단하게 하고, 사람을 기다리지 않게 한다 |
| `flower setup`을 실행했더니 "무엇을 할까"를 묻는다 | `_CMDS`가 `setup`을 빠뜨렸다(`cli.py:937`) | `~/.config/flower/.env`를 직접 수정. 위의 "다시 설정하고 싶을 때" 참고 |

## 다음 단계 {#下一步}

- [빠른 시작](quickstart.md) — 프로젝트 디렉터리에 들어가서 첫 실제 작업을 끝까지 돌려 본다.
- [설정](../reference/config.md) — 전체 환경 변수, 인증 우선순위, `.env` 문법, 디스크에 남는 것들.
- [커맨드라인](../reference/cli.md) — 전체 서브커맨드와 옵션.
- [배포](../reference/deploy.md) — 컨테이너에서 실행하기, plugin으로 도메인 능력 배포하기.
- [용어집](../reference/glossary.md) — 문서에 나오는 모든 단어의 정확한 의미.
