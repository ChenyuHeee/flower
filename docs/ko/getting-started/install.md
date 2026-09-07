# 설치

flower를 설치하는 데 필요한 것은 Python ≥ 3.10뿐이다. 런타임 의존성은 `claude-agent-sdk` 하나뿐이고,
요청을 보내는 네이티브 바이너리가 그 wheel 안에 들어 있다. 그래서 **Node도, Claude Code CLI도 설치할 필요가 없다**.
이 페이지는 처음부터 한 번 훑는다: 한 줄 설치, 소스에서 설치, 첫 자격 증명 설정, 그리고 "정말 제대로
설치됐다"를 증명하는 명령 하나. 다 돌려본 뒤에는 [빠른 시작](quickstart.md)으로.

## 설치 전: Python 확인

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

`True 3.13.7` 정도로 나오면 충분하다. `False`가 찍히거나 `python3` 자체가 없으면 먼저 설치하라
(`brew install python` / `apt install python3`). 그렇지 않으면 설치 스크립트가 바로 종료된다.

| 필요한 것 | 필요 없는 것 |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31`에서도 한 번 자체 확인) | Node.js |
| API 엔드포인트로 나가는 네트워크 | Claude Code CLI |
| API key 또는 게이트웨이 token 한 개(설치 후에 주면 된다) | 호스트의 `~/.claude/` 설정(자격 증명만 유일한 예외, 아래 참조) |

패키지명 `flower`, 버전 `0.1.0`, 유일한 런타임 의존성은 `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material`은 CI에서 문서 사이트를 빌드할 때만 쓰고, flower를 실행하는 데는 필요 없다.

## 한 줄 설치

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

설치가 끝나면 터미널은 이렇게 나온다(색상 생략):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

핵심은 `== 装好了 <절대 경로>` 그 한 줄이다 —— 스크립트가 직접 `command -v flower`를 한 번 실행한 결과다
(`install.sh:60-61`). 경로가 찍혔다면 `flower`가 이미 PATH에 올라와 있다는 뜻이다.

### 설치 스크립트가 실제로 하는 일

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh)는 세 가지만 한다: Python 도구
설치기를 하나 고르고, GitHub에서 설치하고, 다음 단계를 알려준다. **자격 증명은 한 글자도 건드리지 않는다**(`install.sh:7-8`).
설치 소스는 `git+https://github.com/ChenyuHeee/flower.git`로 고정되어 있다(`install.sh:11`).

설치 스크립트는 순서대로 시도하고, 처음 성공한 것에서 멈춘다(`install.sh:33-57`):

| 순서 | 조건 | 실제 명령 | 실행 파일이 놓이는 위치 |
|---|---|---|---|
| 1 | `uv`가 PATH에 있음 | `uv tool install --force <REPO>` | uv의 tool bin 디렉터리, 보통 `~/.local/bin/flower` |
| 2 | `uv`는 없고 `pipx`는 있음 | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | 둘 다 없음 | 먼저 `curl -LsSf https://astral.sh/uv/install.sh \| sh`로 uv를 설치하고, 성공하면 1번으로 돌아간다 | 1번과 동일 |
| 4 | 3번에서 uv 설치도 실패 | `python3 -m pip install --user --upgrade <REPO>` | 사용자 스크립트 디렉터리 —— **macOS에서는 `~/.local/bin`이 아니다** |

네 경우 모두 설치되는 것은 같은 console script다: `flower = "flower.cli:main"`(`pyproject.toml:12`). 설치 후
`python -m flower.cli`로 불러도 결과는 같다(`cli.py:1263-1264`).

!!! warning "설치 스크립트를 다시 돌리면 확인 없이 강제로 덮어쓴다"
    세 설치 명령에는 각각 `--force`, `--force`, `--upgrade`가 붙어 있다(`install.sh:37`, `:40`, `:54`).
    다시 돌리면 기존 설치를 그대로 덮어쓴다 —— 업그레이드가 바로 이 방식이지만, 먼저 한마디 물어봐 줄 거라고
    기대하지는 마라.

### `flower` 명령을 PATH에 올리는 방법

`command -v flower`로 찾지 못하면 스크립트가 `$HOME/.local/bin`을 `~/.zshrc` 또는 `~/.bashrc`에
추가하라고 안내한다(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install`과 `pipx install`은 모두 여기에 놓으므로, 이 안내는 그 둘에는 맞다. **하지만 4번 경로
(`pip install --user`)는 다를 수 있다** —— 그 안내에 적힌 디렉터리는 하드코딩된 값이고, pip의 사용자
스크립트 디렉터리는 플랫폼에 따라 달라진다. macOS에서는 `~/Library/Python/3.13/bin`이다. 직접 확인해 보라:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

출력이 예컨대 `/Users/you/Library/Python/3.13/bin`이라면, `~/.local/bin`이 아니라 그 디렉터리를 PATH에
추가하고 터미널을 다시 열거나 `source`하라.

## 소스에서 설치

코드를 읽거나, 프레임워크를 고치거나, `tests/`에 있는 오프라인 검증을 돌리려면 소스에서 설치한다:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

실행이 끝난 뒤 `.venv/bin/flower --help`를 하면 usage 몇 줄이 찍혀야 한다.

venv 안 실행 파일의 shebang은 **절대 경로**라서 activate할 필요가 없다. 심볼릭 링크만 걸어 두면 어느
디렉터리에서든 쓸 수 있다:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`~/.local/bin`이 PATH에 있으면, 아무 프로젝트 디렉터리로 `cd`해서 `flower`를 쳐도 이 venv의 인터프리터와
이 소스가 실행된다.

소스 설치에는 자격 증명 위치가 하나 더 생긴다: **리포지터리 루트의 `.env`**(탐색 순서에서 5번째,
[설정 · 자격 증명 탐색 우선순위](../reference/config.md#凭证查找优先级) 참조). 개발할 때는:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN 채우기
```

`.env`는 이미 `.gitignore`에 들어 있어 버전 관리에 올라가지 않는다. pip / pipx / uv로 설치한 flower에는
이 위치가 **없다** —— site-packages 안에 있으니 "리포지터리 루트"가 없다 —— 그래서 그런 설치 방식에서는
아래의 전역 자격 증명 파일을 써야 한다.

## 첫 실행: 자격 증명 설정

`go`, `run`, `once` 세 실행 진입점은 모두 시작할 때 `ensure_credentials()`를 호출한다(`cli.py:1013`, `:981`, `:1046`).
관문은 둘이다:

1. **있는지** —— 우선순위대로 한 번 찾고, 못 찾으면 그 자리에서 물어본다.
2. **쓸 수 있는지** —— 실제로 API를 한 번 호출한다. `max_tokens=16`인 최소 요청(`env.py:120-123`)이라 비용은
   거의 없다. 만료된 token이나 잘못 적은 게이트웨이 주소는 환경 변수만 봐서는 알 수 없고, 찔러보지 않으면
   몇 분 뒤에야 터진다.

자격 증명이 없으면 `flower`의 첫 실행은 이 화면에서 멈춘다(`cli.py:1179-1209`):

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

1번 질문은 필수다. 비워 두면 빨간 글씨로 `没给 token,取消。`를 찍고 종료한다. 2번, 3번은 그냥 엔터를
쳐도 된다. 공식 엔드포인트를 쓰면 2번은 비워 두고, 서드파티 게이트웨이라면 그 루트 주소를 적는다.
**`/v1`은 붙이지 마라** —— flower의 프로브가 호출하는 것이 `<BASE_URL>/v1/messages`다(`env.py:162`).

답을 마치면 기록되는 키(`cli.py:1199-1207`):

| 입력한 값 | `.env`에 기록되는 키 |
|---|---|
| token이 `sk-ant-`로 시작 | `ANTHROPIC_API_KEY` |
| 그 외 token | `ANTHROPIC_AUTH_TOKEN` |
| 게이트웨이 주소가 비어 있지 않음 | `ANTHROPIC_BASE_URL` |
| 모델명이 비어 있지 않음 | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` **세 개를 함께 기록** |

파일 위치는 `${XDG_CONFIG_HOME:-~/.config}/flower/.env`(`env.py:39-42`)이며, **전체를 덮어쓴 뒤**
`chmod 0o600`을 한다(`cli.py:1157-1168`). 이것이 "한 번 설치하면 어디서나 적용"되는 그 파일이다 ——
프로젝트 디렉터리를 바꿔도 다시 설정할 필요가 없다. 각 변수의 의미는 [설정](../reference/config.md#环境变量) 참조.

### 이 기기에 Claude Code를 설치한 적이 있으면 아무것도 묻지 않을 수 있다

자격 증명 탐색에는 **마지막 폴백**이 하나 있다: `~/.claude/settings.json`을 읽고, 이어서
`~/.claude/settings.local.json`을 읽어 그 `env` 블록에서 자격 증명 키 9개를 가져온다(`env.py:56-75`, `:109-111`).
이 기기에 Claude Code를 이미 설정해 둔 사람은 그냥 `flower`를 실행하면 바로 작업에 들어갈 수 있고, 설정
화면은 아예 나오지 않는다 —— `install.sh:77`이 홍보하는 것이 바로 이 경로다.

!!! warning "제품 안의 'flower 不读 ~/.claude/settings.json'이라는 문장은 틀렸다"
    자격 증명을 전혀 찾지 못했을 때 flower가 출력하는 오류의 마지막 줄은
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    이다(`env.py:184-194`, 그 문장은 `:192`). **코드가 기준이다: 읽는다.**
    `env.py:56-75`는 그 두 파일의 `env` 블록을 명시적으로 읽는다. 다만 자격 증명 키 9개만 가져오고,
    나머지 어떤 설정도 인수하지 않는다. 그 문장을 봤다고 해서 이 기기의 Claude Code 설정이 무시된다고
    단정하지 마라. 전체 연결 고리는
    [설정 · 자격 증명 탐색 우선순위](../reference/config.md#凭证查找优先级) 참조.

### 다시 설정하고 싶을 때

`flower setup` 서브커맨드는 등록되어 있지만(`cli.py:1147-1149`) `_CMDS`에서 빠져 있어서(`cli.py:758`),
`flower setup`은 `flower go setup`으로 재작성된다 —— "setup"을 하나의 요청으로 보고 전체 워크플로를 한 번
돌리는 것이다. **현재 어떤 명령줄 표기로도 그 서브커맨드에 도달할 수 없다.** 여러 오류 문구가 여전히 그것을
실행하라고 안내하고 있지만 그렇다. 자격 증명을 바꾸려면:

```bash
$EDITOR ~/.config/flower/.env
```

또는 그 파일의 token을 지우고 `flower`를 다시 실행하라 —— 자격 증명 누락 관문이 다시 물어본다(다른 위치,
예컨대 `~/.claude/settings.json`에도 없어야 한다). 자격 증명이 거부되면(HTTP 401 / 403) 그 자리에서 같은
화면이 떠서 다시 설정하게 해 주는데, 기회는 최대 한 번이다(`cli.py:1229-1244`).

## 제대로 설치됐는지 확인

두 단계, 싼 것부터 비싼 것 순으로.

**1단계 —— 명령이 있는지(비용 없음)**:

```bash
flower --help
```

다음 몇 줄이 보이면 console script가 설치됐고 PATH에도 올라와 있다는 뜻이다:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**2단계 —— 자격 증명, 엔드포인트, 네이티브 바이너리까지 다 통하는지(몇 센트)**: 가장 싼 실제 실행은
`once`다 —— agent 하나, 기본으로 `Read` / `Glob` / `Grep` 세 개의 읽기 전용 도구만 주고,
[목표 가드](../reference/glossary.md#目标看守)도 [워크벤치](../reference/glossary.md#工作台)도 켜지 않는다:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v`는 실행 **전에** 현재 적용된 설정을 먼저 출력하고, token은 앞 4자리만 남긴다
(`cli.py:1257-1259`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

이 몇 줄로 게이트웨이를 잘못 붙지 않았음을 확인한다. 이어서 자격 증명 프로브와 실제 실행이 온다:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**스텝 헤더가 없다.** `once`는 `_run_once` → `rt.run()`으로 가고 `_drive` / `Workflow.run`을 거치지 않으며,
`Event("step", …)`은 `workflow/base.py:220`에서만 발행된다 —— 그래서 `== 步骤名 ===== 1/1` 같은 구분선은
`once`에서는 나타나지 않고 `go` / `run`에서만 나온다.

**`+ 完成` 그 줄이 나오면 통과다.** 이 줄은 동시에 세 가지를 증명한다: 자격 증명이 쓸 수 있고, 엔드포인트에
연결되며, `claude-agent-sdk` wheel 안의 네이티브 바이너리가 이 기기에서 실행된다는 것.
`- 验一下凭证…` 아래에 `! 凭证被拒`나 `! 网关地址或模型名不对`가 따라 나오면 아래 문제 해결 표로 가라.

!!! note "`once`의 소요 시간과 누적 비용은 0으로 표시된다"
    `once`는 이벤트마다 렌더러를 새로 만들기 때문에(`cli.py:1060`, `:579-581`) `用时`은 항상 `0:00`이고,
    상태 줄의 `累计 $`도 절대 누적되지 않는다 —— **단일 스텝의 그 비용은 진짜이고, 시간은 아니다.**

    위 줄의 `1 轮 · $0.1741`은 **출처가 있는 실측치**다: 2026-09-06에 Linux/arm64 컨테이너에서
    `cloud.infini-ai.com/maas`를 경유해 보낸 실제 요청(`docker/README.md:24-25`),
    즉 Opus 5 + 1M 윈도의 **단일 라운드 최저 비용**이다. 위 명령을 직접 돌리면 리포지터리를 한 번 읽어야
    하므로 라운드 수가 더 많고 비용도 이 최저치보다 조금 높아진다.
    전체 계산은 `runs/manifest.json`에 있다. [설정 · 디스크 레이아웃](../reference/config.md#磁盘布局) 참조.

## 설치가 안 될 때

| 증상 | 원인 | 대처 |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | `python3`과 `python` 모두 3.10+를 만족하지 않음(`install.sh:31`) | `brew install python` / `apt install python3` 후 스크립트를 다시 실행 |
| 스크립트는 설치됐다고 하는데 `flower: command not found` | PATH에 없는 디렉터리에 설치됨 | 위의 "`flower` 명령을 PATH에 올리는 방법" 참조. `pip --user` 경로를 탔다면 macOS에서는 `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | 모든 경로가 실패, 보통 GitHub나 PyPI로 나가는 네트워크가 막힌 경우 | 안내대로 수동으로 한 번 실행해 실제 오류를 확인 |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。`(4줄) | 비대화식 환경(파이프, CI, `nohup`)에 자격 증명이 없음 —— 그런 환경에서는 설정 화면이 뜨지 않고 바로 종료된다 | 먼저 실제 터미널에서 `flower`를 한 번 실행해 설정하거나, `~/.config/flower/.env`를 직접 작성 |
| `! 凭证被拒:HTTP 401 …` | token이 만료됐거나 잘못 적혔음 | 대화식 터미널이면 그 자리에서 다시 설정하게 해 준다. 비대화식이면 종료 |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL`이나 모델명이 틀림 | BASE_URL은 게이트웨이 루트까지만 쓰고 `/v1`은 붙이지 않는다. 모델명은 게이트웨이 자체 체계를 쓴다 |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / 타임아웃 / 5xx | **자격 증명 문제가 아니다.** flower는 의도적으로 다시 설정하게 하지 않고 그대로 실행을 시작하며, [복원력](../reference/glossary.md#韧性) 계층에 넘긴다 |
| `! 标准输入不是终端,没人能回答提问` | 파이프나 CI에서 실행 | `--timeout 0`을 붙여 스스로 판단하게 하고, 사람을 기다리지 않게 한다 |
| `flower setup`을 실행했는데 "무엇을 할 것인가"를 묻는다 | `_CMDS`에 `setup`이 빠져 있음(`cli.py:758`) | `~/.config/flower/.env`를 직접 수정. 위의 "다시 설정하고 싶을 때" 참조 |

## 다음 단계

- [빠른 시작](quickstart.md) —— 프로젝트 디렉터리에 들어가 첫 실제 작업을 끝까지 돌려 본다.
- [설정](../reference/config.md) —— 모든 환경 변수, 자격 증명 우선순위, `.env` 문법, 디스크에 무엇이 남는지.
- [명령줄](../reference/cli.md) —— 모든 서브커맨드와 옵션.
- [배포](../reference/deploy.md) —— 컨테이너에서 실행하기, plugin으로 도메인 능력 배포하기.
- [용어집](../reference/glossary.md) —— 문서에 나오는 모든 용어의 정확한 의미.
