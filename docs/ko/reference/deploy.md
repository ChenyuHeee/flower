# 배포와 확장

flower를 다른 곳으로 옮기려면 세 가지를 처리해야 한다: 컨테이너(제한 없는 Bash를 가둬 두면서
"CLI 없이 돈다"는 말을 겸사겸사 검증한다),
[plugin](glossary.md#plugin)(도메인 능력이 저장소를 따라다니고, 호스트에 무엇이 깔려 있는지 보지 않는다),
문서 사이트(`main`에 push하면 자동 배포되고, `install.sh`는 Pages 도메인에 붙는다).
세 절은 서로 독립적이니 필요한 것만 읽으면 된다.

## 1. 컨테이너 {#一容器}

### 왜 컨테이너인가 {#为什么要容器}

**첫째, 가두기 위해서다.** 실제로 일하는 [실행자](glossary.md#执行者)는 **제한 없는 Bash**를 쓴다 ——
flower의 Bash 화이트리스트(`delegate_guard`)는 [메인 스레드](glossary.md#主线程)만 담당하고,
내보낸 쪽은 테스트를 돌릴 수 있어야 하므로 의도된 설계다.
컨테이너에는 네 프로젝트 디렉터리만 마운트되고, 프레임워크 소스는 이미지 안의 `/opt/flower`에 있으며,
호스트의 다른 곳은 보이지 않는다.

**둘째, 그 자체가 [이식성](glossary.md#可移植)이라는 제약에 대한 검증이다.** 이미지 안에는 Claude Code CLI도
Node도 없고 Python과 `claude-agent-sdk`만 있다 —— 요청은 wheel이 번들한 네이티브 바이너리가 내보낸다.
여기서 돌아간다면 "CLI 없이 돈다"는 말은 종이 위의 주장이 아니다.

실측 통과(2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| 검증 대상 | 결과 |
|---|---|
| 이미지에 CLI가 있는가 | `claude`, `node`, `npm`, `npx` **모두 없음** |
| 번들 바이너리 | `\177ELF`(207M) |
| 실제 요청 | `cloud.infini-ai.com/maas`를 거쳐 발신하고 응답 수신, `$0.1741 / 1턴`(Opus 5 + 1M 윈도의 1턴 바닥값이 이 가격이다) |
| 파일 소유권 | 컨테이너 안에서 `/work`에 쓴 파일이 호스트에서 `hechenyu:staff`, 매핑 정확 |
| 호스트 가시성 | 컨테이너 안에서 `ls /Users` → `No such file or directory` |

### 이미지에 무엇이 들어 있나 {#镜像里装了什么}

베이스 이미지는 `python:3.13-slim`, 그 위에 apt로 세 개 패키지만 깐다. 각각 이유가 있다:

| 설치물 | 이유 |
|---|---|
| `python:3.13-slim` | Python ≥ 3.10만 있으면 된다. Node도 claude CLI도 깔지 않는다 |
| `git` | `--isolate`가 [subagent](glossary.md#subagent)마다 worktree를 나눠 줘야 한다 |
| `ca-certificates` | HTTPS 게이트웨이를 탄다 |
| `libstdc++6` | SDK가 번들한 바이너리는 Bun으로 컴파일한 단일 파일이라 Linux에서 이게 필요하다. slim 이미지에는 없다 |

프레임워크 소스가 이미지로 들어가는 방식은 `COPY`이고, **bind mount가 아니다** ——
그래서 컨테이너 안의 agent는 호스트의 프레임워크 소스에 손댈 수 없다:

| 이미지 내 경로 | 내용 | 출처 |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, 여기서 `pip install .` | `COPY` |
| `/work` | 작업 디렉터리(`WORKDIR`), 실행 시 호스트의 `$PWD`를 마운트 | `docker run -v` |

엔트리포인트는 `ENTRYPOINT ["flower"]`이고 `CMD`는 비어 있다 —— 인자 없이 컨테이너를 돌리면
`--help`를 찍는 대신 대화형 입력으로 들어간다(무엇을 할지 물어본다).
그래서 shell에서 요구사항 한 줄에 따옴표를 씌울 필요가 없다.

### 호스트의 `.venv`를 마운트하면 안 되는 이유 {#为什么不能把宿主的-venv-挂进去}

SDK는 플랫폼별로 wheel을 배포하고, 번들된 바이너리는 플랫폼 전용이다:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

마운트해 봐야 돌지 않으므로 이미지는 스스로 `pip install`을 해야 한다. 뒤집어 보면 이것 역시 이식성의 증거다:
같은 `pyproject.toml`로 플랫폼이 바뀌면 네이티브 바이너리만 바뀌고, 프레임워크 코드는 한 줄도 고치지 않는다.

### 두 개의 스크립트 {#两个脚本}

| 스크립트 | 하는 일 |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | 이미지 빌드. 저장소 루트로 `cd`한 뒤 `docker build -f docker/Dockerfile -t flower-box .`. `FLOWER_MIRRORS=1`(기본값)이면 먼저 registry 미러에서 `python:3.13-slim`을 받아 retag하고, pip / apt의 `--build-arg`를 붙인다 |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | 한 번 실행. 자격 증명 파일 확인 → `$PWD`가 마운트되는지 확인 → TTY 유무 판단 → `docker run` |

`docker/build`의 스위치는 전부 환경 변수다:

| 변수 | 기본값 | 의미 |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | 이미지 tag |
| `FLOWER_MIRRORS` | `1` | `0` = 미러를 하나도 바꾸지 않고 전부 업스트림으로 |
| `FLOWER_REGISTRY` | `dockerproxy.net` | 여기서 베이스 이미지를 받아 `python:3.13-slim`으로 retag해서 `FROM`이 로컬을 맞히게 한다 |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | `--build-arg PIP_INDEX_URL`로 전달 |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | `--build-arg APT_MIRROR`로 전달 |

뒤의 셋은 `FLOWER_MIRRORS=1`일 때만 작동한다 —— `FLOWER_MIRRORS=0` 분기는 build-arg를 아예 설정하지 않는다.

`docker/flowerbox`가 보는 건 두 개다:

| 변수 | 기본값 | 의미 |
|---|---|---|
| `FLOWER_HOME` | 스크립트 자신의 위치에서 한 단계 위(즉 저장소 루트) | `.env`를 어디서 찾을지. `$FLOWER_HOME/.env`가 없으면 바로 1로 종료 |
| `FLOWER_IMAGE` | `flower-box` | 어떤 이미지를 돌릴지 |

`FLOWER_HOME`은 스크립트 자신의 위치에서 추론하고 경로를 하드코딩하지 않으므로, 저장소를 어디에 클론해도 쓸 수 있다.

### 이미지 빌드와 컨테이너 실행 {#跑起来}

```bash
docker/build                       # 한 번이면 충분
cd ~/프로젝트-디렉터리               # 반드시 $HOME 아래여야 한다. 아래 마운트 경계 참고
/path/to/flower/docker/flowerbox   # 인자 없이 → 무엇을 할지 물어본다, 따옴표 필요 없음
```

pypi.org / Docker Hub 네트워크가 정상이면 빌드는 이렇게 돌린다:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox`의 인자는 `flower`와 완전히 같다 —— `"$@"`를 그대로 `ENTRYPOINT` 뒤에 붙인다.
`--clarify-only`, `--asks N`, `--timeout 초`, `--isolate`, `-v` 모두 그대로 넘어가며, 전체 표는 [커맨드라인](cli.md)에 있다:

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "X를 만들어 줘"
```

실제로 실행되는 건 이 한 줄이다(`-t`는 TTY가 있을 때만 붙는다, 아래 참고):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### 마운트 경계와 영속화 {#挂载边界与持久化}

```text
宿主 $PWD  ──挂载──>  /work       ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

그래서 `flower/human-test/HT001` 같은 저장소 내부 하위 디렉터리에서 돌려도 안전하다:
마운트되는 건 `HT001`뿐이고, 프레임워크 소스는 마운트 범위 밖이다.

| 대상 | 종료 후에도 남는가 | 이유 |
|---|---|---|
| 호스트 `$PWD` 아래 전부, `runs/`와 [워크벤치](glossary.md#工作台) `.flower/` 포함 | 남는다 | 그게 바로 `/work`로 마운트된 디렉터리다 |
| 컨테이너 안 다른 경로에 쓴 것 | 안 남는다 | `--rm`, 컨테이너 종료 즉시 삭제 |
| 자격 증명 | 이미지 레이어에 들어가지 않는다 | `--env-file`로 전달. `.dockerignore`에서 `.env`를 제외했으므로 `COPY . .`을 해도 들어가지 않는다 |

!!! danger "프로젝트 디렉터리는 반드시 `$HOME` 아래여야 한다. 아니면 산출물이 조용히 사라진다"
    **colima는 기본적으로 `$HOME`만 VM에 마운트한다**(`mount | grep virtiofs` → `mount0 on /Users/<너>`).
    `/tmp` 같은 곳에서 돌리면 `-v`가 VM 안에 **빈 디렉터리**를 만들고, 거기에 쓴 것은 호스트에서 영원히 볼 수 없으며
    **에러도 나지 않는다** —— 산출물, [요구사항 확인서](glossary.md#需求确认书), `runs/`가 전부 사라진다. 한 번 밟았다:
    `once` 한 번을 다 돌려서 $0.17을 썼는데 `runs/`가 호스트에 아예 존재하지 않았다.

    `flowerbox`는 이제 이 상황을 막는다: `$PWD`가 `$HOME` 아래면 바로 통과. 아니면 `$PWD`에 프로브 파일을 하나 쓰고,
    컨테이너를 하나 띄워 `test -f /work/<프로브>`로 실측한다(추가 마운트를 설정했다면 통과한다). 통과하지 못하면 1로 종료하면서
    `colima start --mount '<경로>:w'`를 알려 준다. 프로브가 컨테이너를 띄우므로 먼저 `docker/build`를 해야 한다.

### 자격 증명은 어떻게 컨테이너로 들어가나 {#凭证}

`docker run --env-file`을 탄다. **이미지 레이어에 들어가지 않는다.** `flowerbox`가 읽는 건
`$FLOWER_HOME/.env`이고, 기본값은 저장소 루트의 `.env`다:

```bash
cp .env.example .env       # token 채우기. .env는 이미 gitignore 되어 있다
```

`flower setup`이 쓰는 곳은 `~/.config/flower/.env`이고, **그 경로를 `flowerbox`는 보지 않는다**.
이미 `setup`으로 설정해 두었고 한 벌 더 복사하기 싫다면 `FLOWER_HOME`을 그쪽으로 가리키면 된다:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

키 이름, 우선순위, 게이트웨이 작성법은 [설정](config.md)을 보라.

!!! warning "TTY가 없으면 질문이 `--timeout`까지 계속 멈춰 있는다"
    `flowerbox`는 `[ -t 0 ]`일 때만 `-t`를 붙인다 —— `docker run -t`는 파이프 / CI에서
    "the input device is not a TTY"를 바로 뱉는다. `-i`는 항상 필요하다. 아니면 stdin이 아예 들어가지 않는다.

    답변은 표준 입력으로 들어간다. TTY가 없으면 `input()`이 첫 호출에서 `EOFError`를 던지고 → 현재 질문은
    "입력이 닫혔다"로 간주되어 건너뛰어지며, **답변 스레드가 그대로 종료된다**. 그래서 두 번째 질문부터는 받아 줄 사람이 없고
    `--timeout`(기본 1800초)이 다 찰 때까지 그냥 기다리게 된다. 무인 운영이라면 명시적으로 `--timeout 0`을 줘야 한다.
    스크립트는 TTY가 없음을 감지하면 먼저 한 줄 경고를 찍는다.

### git submodule {#git-submodule}

`.gitmodules`에는 항목이 하나뿐이다:

| path | url | 무엇인가 |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | [HT001](../cases/ht001.md) 그 실행이 **산출한** 코드 저장소, 기록 보존용 |

평범한 `git clone`은 이것을 받아 오지 않고, `human-test/HT001`은 빈 디렉터리다(`git submodule status` 앞에
`-`가 붙으면 그 상태다). 신경 써야 하는지 여부:

| 하려는 일 | 초기화가 필요한가 |
|---|---|
| flower 실행, 이미지 빌드 | **필요 없다**. `.dockerignore`가 `human-test/`를 제외하고, `Dockerfile`도 원래 `pyproject.toml` / `flower` / `examples`만 `COPY`한다 |
| 로컬에서 HT001의 산출 코드를 들여다보기 | 필요하다: `git submodule update --init human-test/HT001`, 또는 처음부터 `git clone --recurse-submodules` |

### 중국 내 네트워크: 그 많은 미러 치환은 왜 있는가 {#国内网络为什么有那一堆镜像替换}

이 물건을 방화벽 안에서 설치할 때 느린 것은 대역폭이 아니라 국제 회선이다. 기본 `docker/build`는 바꿀 것을 이미 다 바꿔 뒀고,
`FLOWER_MIRRORS=0` 한 방으로 전부 끌 수 있다. 아래는 실측 데이터와 네 군데 치환의 경위다 ——
네트워크에 이 문제가 없다면 읽지 않아도 된다.

??? note "실측 속도 표와 네 군데 치환(2026-09-06, macOS/arm64)"

    | 소스 | 속도 |
    |---|---|
    | `pypi.org`(인덱스) | 32 KB/s |
    | `files.pythonhosted.org`(패키지 파일) | **284 B/s** |
    | `github.com`(release asset 직접 연결) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com`(VM 안) | 26 KB/s |
    | `download.docker.com` | **연결 불가**(HTTP 000). VM 안에서는 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **연결 불가** |
    | `mirrors.aliyun.com/pypi`(**패키지 파일**) | 1.4 MB/s(호스트) / 152 KB/s(VM 안) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports`(VM 안) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top`(GitHub 프록시) | **2.5 MB/s** |
    | `gh-proxy.com`(GitHub 프록시) | 1.5 MB/s |
    | `dockerproxy.net`(Docker Hub 프록시) | 사용 가능(manifest를 바로 반환) |

    측정할 때 **인덱스 페이지**를 패키지 파일로 착각하지 말 것: `mirrors.aliyun.com/pypi/simple/` 그 페이지는 7.4 MB/s가 나오지만,
    실제 95.9 MB짜리 wheel은 1.4 MB/s에 불과하다(VM 안에서는 152 KB/s —— colima의 유저스페이스 네트워크에는 손실이 있다).
    시간은 패키지 파일 수치로 추정하라.

    **치환 지점 1 —— colima의 VM 이미지.** colima가 쓰는 건 평범한 Ubuntu cloud image가 아니라
    **docker가 사전 설치된** 자체 커스텀 이미지(`abiosoft/colima-core`의 release asset)다. 그래서 VM을 띄울 때
    apt로 docker를 설치할 필요가 없고, 연결되지 않는 `download.docker.com`을 우회하게 된다. 직접 받아 두고 `--disk-image`로 먹이면 된다:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 검증: digest는 GitHub API에서 받는다. 건너뛰지 말 것 —— VM으로 돌릴 물건이다
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    프록시는 중간에 끊긴다(실측 curl 56). `-C -` 이어받기로 몇 번 다시 돌리면 된다.

    **치환 지점 2 —— VM 안의 apt.** docker가 사전 설치된 이미지를 써도 lima의 boot 스크립트
    `30-install-packages.sh`는 `rsync`를 설치하려고 `apt-get update`를 한 번 돌린다 ——
    `ports.ubuntu.com`(26 KB/s)과 `download.docker.com`(4 KB/s)을 때리므로 수십 분 동안 멈춘다.

    처리 방법(**먼저 `/mnt/lima-cidata/boot.sh`를 읽고 손대라**: 실패한 boot 스크립트에 대해 `WARNING` +
    `CODE=1`만 남기고 계속 진행하며, 마지막에 **반드시** `/run/lima-boot-done`을 쓴다. 그래서 그 단계를 실패시키는 건 안전하다):

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
      pkill -f "apt-get update"          # boot.sh는 끝까지 진행하고 완료 표식을 쓴다
    '
    # colima start가 곧 정상 종료된다. 이후 rsync를 마저 설치한다(이제 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    겸사겸사 `127.0.0.1 lima-colima`를 VM의 `/etc/hosts`에 넣어 `sudo: unable to resolve host` 경고 줄을 없애자.

    **치환 지점 3 —— 베이스 이미지.** `docker/build`는 먼저 `dockerproxy.net`에서 `python:3.13-slim`을 받아
    retag해서 Dockerfile의 `FROM`이 로컬을 맞히게 한다. 실측상 `dockerproxy.net`은 manifest를 바로 반환하고
    (HTTP 200), `docker.1ms.run` / `docker.m.daocloud.io`는 401, `hub.rat.dev`는 302,
    `docker.xuanyuan.me`는 403을 반환한다.

    **치환 지점 4 —— 컨테이너 안의 apt와 pip.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s),
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. 참고로 `PIP_INDEX_URL`은
    pip 자신이 인식하는 환경 변수이기도 해서, `ARG`를 선언하는 것만으로 RUN 안의 pip가 그것을 읽는다 ——
    `--index-url`을 명시하지 않아도 적용된다.

    일회성 준비 총 소요 시간은(위와 같은 네트워크 조건에서) 약 25분이고, 대부분은 364 MB의 VM 이미지와 95.9 MB의
    SDK wheel이다. 이후 `flowerbox` 기동은 초 단위다.

## 2. plugin {#plugin}

### plugin이란 무엇이고 SDK는 어떻게 로드하나 {#它是什么}

저장소를 따라다니는 **도메인 능력 패키지**다. 프레임워크 코드에는 도메인 지식이 전혀 없고, 도메인 지식은 전부
저장소 루트의 `plugin/` 디렉터리에 놓여 코드와 함께 clone되고, 함께 review되고, 함께 tag된다.

SDK 쪽 배선은
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)의
`build_options()` 안에 두 줄로 있다:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

`setting_sources=[]`(아래에서 따로 설명한다)와 함께, 이것이 flower가 "[이식성](glossary.md#可移植)"과
"네 도메인을 이해함"을 동시에 만족시킬 수 있는 이유다: 호스트에 무엇이 깔렸는지 묻지 않고, 저장소가 가져온 이 디렉터리 하나만 인정한다.

### 디렉터리 구조 {#目录布局}

| 경로 | 담는 것 | 언제 작동하나 | 누가 결정하나 |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | 패키지의 신원: `name`, `description`, `version`, `author` | 로드 시 한 번 읽음 | — |
| `plugin/skills/<name>/SKILL.md` | 도메인 지식, 필요 시 로드 | **확률적** —— 모델이 관련 있다고 판단해야 쓴다 | 모델 |
| `plugin/agents/<name>.md` | subagent, 독립 컨텍스트 윈도 | 모델이 위임하거나, [워크플로](glossary.md#流程)에서 명시 지정 | 모델 / 너 |
| `plugin/hooks/hooks.json` | 도구 호출 가로채기 | **결정적** —— 매치되면 실행 | 코드 |
| `plugin/.mcp.json` | 외부 도구 연결 | 도구로 등록되어 내장 도구와 동일하게 취급 | 모델 |

**확률적인 것과 결정적인 것의 차이는 표현의 차이가 아니라 선택의 핵심이다:**

- skill은 **거기 놓여 있는 지식**이다. 모델이 그 `description`을 보고 현재 작업과 관련 있다고 느껴야 읽으러 간다.
  관련성 판단을 모델이 하므로, 같은 문장을 두 번 돌리면 한 번은 쓰고 한 번은 안 쓸 수 있다.
- hook은 **코드**다. 이벤트에 매치되면 돌고, 모델이 원하는지 아는지와 무관하다. flower 자신의
  [스필](glossary.md#落盘)과 [격리](glossary.md#隔离)가 전부 hook인 이유가 바로 그것들이 "가끔만 작동"하면 안 되기 때문이다.

그래서 판단 기준은 하나뿐이다: **이 일은 매번 반드시 일어나야 하는가?** 그렇다면 —— hook을 쓴다. 그저 "알고 있으면 좋다" 정도면 ——
skill을 쓴다. 반드시 일어나야 하는 일을 skill로 쓰는 것은 규율을 모델의 한 번의 판단에 거는 것과 같다.

지금 저장소의 `plugin/`에는 두 가지밖에 없다: `.claude-plugin/plugin.json`과 `skills/example/SKILL.md`.
`agents/`, `hooks/`, `.mcp.json`은 **아직 존재하지 않는다** —— 쓰려면 직접 만들고, 디렉터리 이름은 위 표대로 고정이다.

### skill 하나 쓰기: 완전한 예제 {#写一个-skill完整例子}

"릴리스 노트 생성"을 예로, 0부터 작동 확인까지.

**1단계: 디렉터리 만들기.** 디렉터리 이름이 곧 skill 이름이고, frontmatter의 `name`과 일치시킨다.

```bash
mkdir -p plugin/skills/release-notes
```

**2단계: `plugin/skills/release-notes/SKILL.md` 작성.** 파일명은 반드시 `SKILL.md`, 대문자다.
형식은 YAML frontmatter + Markdown 본문이고, frontmatter에는 두 필드가 있다:

| 필드 | 역할 |
|---|---|
| `name` | skill의 식별자. 디렉터리 이름과 일치 |
| `description` | **모델이 이것을 고를지 여부는 이 한 줄만 본다**. "언제 써야 하는지"를 명확히 쓰고, "이게 무엇인지"를 쓰지 말 것 |

바로 쓸 수 있는 최소 파일:

````markdown
---
name: release-notes
description: 릴리스 노트를 정리할 때 사용. 사용자가 "release notes 써 줘", "이번 버전에서 뭐가 바뀌었나", "릴리스"라고 말할 때 쓴다.
---

# 릴리스 노트

## 소재 수집 방법

```bash
git describe --tags --abbrev=0        # 직전 tag
git log --oneline <직전 tag>..HEAD     # 이번 버전의 커밋
```

## 출력 형식

세 단락으로 나누고, 각 단락은 순서 없는 목록, 각 항목은 한 줄. 사용자가 체감할 수 있는 변화를 쓰고, 내부 리팩터링은 쓰지 않는다:

- **추가** —— 이번 버전에서 전에는 못 하던 무엇을 할 수 있는가
- **수정** —— 무엇을 고쳤는지, 증상을 한 문장으로
- **비호환** —— 업그레이드할 때 손대야 하는 것. 없으면 단락 자체를 쓰지 않는다

## 경계

- 버전 번호를 지어내지 말고 `pyproject.toml`의 `version`에서 읽는다.
- 어떤 커밋이 사용자에게 체감되는지 확신이 없으면 나열해서 물어보고, 사용자를 대신해 결정하지 않는다.
````

본문에 무엇을 쓸지는 강제 형식이 없다 —— 그저 컨텍스트로 읽혀 들어가는 텍스트 한 덩어리다.
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md)의
작성 방식을 참고하라: **언제 쓰는지**, **단계**, **결과물의 모양**, **경계가 어디인지**를 명확히 하는 편이
배경 지식을 쌓아 두는 것보다 유용하다.

**3단계: 로드되었는지 확인.** 확실한 것 하나만 확인한다 —— 디렉터리가 있는지 없는지:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

`/path/to/flower/plugin True`가 찍혀야 `build_options()`의 그 `if`로 들어간다는 뜻이다.
`False`가 찍히면 로드되지 않은 것이고, **런타임에 에러도 나지 않는다**. 아래 경고를 보라.

**"한 문장 돌려 보고 `example` skill이 호출되는지"를 검증으로 삼지 말 것.** skill은 확률적이다:
모델이 호출하지 않은 것은 설치되지 않았기 때문일 수도 있고, 그저 현재 작업에 필요하다고 느끼지 않았기 때문일 수도 있다 ——
이 신호는 두 경우를 구분하지 못한다. 게다가 `build_options()`는 SDK의 세션 수준 `skills=` 옵션을 전혀 설정하지 않으므로,
plugin 안의 skill이 코디네이터의 선택 목록에 실제로 나타나는지는 실측된 바 없다. 위의 `PLUGIN_DIR` `True`/`False`는 확실하다. 그것을 쓰라.

특정 [실행자](glossary.md#执行者)에게 어떤 skill을 열어 줄지 지정하려면 `worker(..., skills=[...])`를 쓴다
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)).
이름은 `SKILL.md`의 `name`을 쓰고, SDK는 `플러그인명:skill명` 같은 한정 표기도 받는다.

!!! warning "설치된 flower에는 `plugin/`이 없다 —— 세 가지 설치 방식 모두"
    `PLUGIN_DIR`은 `flower/core/agent.py`에서 세 단계 위로 올라간 뒤 `plugin/`으로 들어간다. 소스 checkout에서 돌릴 때는 저장소 루트의
    `plugin/`이지만, wheel은 `flower` 디렉터리 하나만 패키징하므로(`pyproject.toml`의
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`) site-packages에 설치되고 나면
    `site-packages/plugin`은 존재하지 않고 `PLUGIN_DIR.is_dir()`은 거짓이 된다 —— **조용히 건너뛰고, 에러도 경고도 없다**.

    **이건 컨테이너의 문제가 아니라 훨씬 범위가 넓다.** `install.sh`의 모든 경로 —— `uv tool install`,
    `pipx install`, uv를 부트스트랩한 뒤 다시 uv 사용, 그리고 `pip install --user` 폴백 —— 이 설치하는 것은 전부 wheel이다.
    즉 **한 줄로 설치한 flower에서는 도메인 능력 패키지가 예외 없이 조용히 무력화된다**. 컨테이너는 같은 문제의 한 사례일 뿐이다:
    `docker/Dockerfile`은 `pyproject.toml`, `flower/`, `examples/`만 `COPY`하고 `plugin/`은 이미지에 들어가지 않는다.

    [issue #15](https://github.com/ChenyuHeee/flower/issues/15)에 기록했다. 설치 후 먼저 위의
    `PLUGIN_DIR` 명령으로 자가 점검하라: `False`가 찍히면 이번 설치에는 도메인 능력 패키지가 없다는 뜻이다.
    도메인 능력 패키지를 쓰려면 지금은 소스 checkout에서 돌리는 수밖에 없다.

### `setting_sources=[]`가 도메인 능력을 plugin으로 몰아넣는 이유 {#setting_sources-为什么逼着领域能力走-plugin}

같은 함수 안에 이 줄도 있다:

```python
"setting_sources": [] if portable else ["project"],
```

SDK의 기본값은 `None` = 세 출처를 전부 읽는다: `~/.claude/settings.json`(사용자),
`.claude/settings.json`(프로젝트), `.claude/settings.local.json`(로컬). flower는 기본적으로 `[]`를 넘겨
이것들을 **전부 끈다**.

| | 읽는가 | 결과 |
|---|---|---|
| `~/.claude/`(호스트) | 안 읽음 | 기계를 바꿔도 동작이 일치하고, "내 이 기계는 설정해 둬서" 결과가 달라지는 일이 없다 |
| 프로젝트 `.claude/` | 안 읽음 | `.claude/skills/`, `.claude/agents/`에 넣은 것은 flower 아래에서 **하나도 작동하지 않는다** |
| `plugin/` | 읽음 | 경로가 코드에 하드코딩되어 있고, 저장소를 따라다닌다 |
| 자격 증명 | 이 경로를 타지 않음 | 반드시 `.env`를 직접 가져와야 한다. `~/.claude/settings.json`과 `settings.local.json`의 `env` 블록은 최후의 폴백일 뿐이고 **9개 자격 증명 키만 취한다**, [설정](config.md) 참고 |

`.claude/`가 작동하지 않는 것은 **설정을 빠뜨린 게 아니라 이 제약의 정의다**: 호스트에서 1바이트라도 읽는 순간
"기계를 바꿔도 동작이 일치한다"가 성립하지 않는다. 그래서 도메인 능력에는 통로가 하나뿐이다 ——
저장소를 따라다니는 `plugin/`.

스위치는 두 개(둘 다 `build_options()`에 있고, 기본값이 곧 이식 가능한 쪽이다):

| 파라미터 | 기본값 | 바꾸면 어떻게 되나 |
|---|---|---|
| `portable` | `True` | `False`를 넘기면 → `setting_sources`가 `["project"]`가 되어 프로젝트 `.claude/`를 읽기 시작한다(SDK 쪽: `CLAUDE.md`를 읽으려면 반드시 `"project"`가 있어야 한다). 이식성은 그와 함께 사라진다 |
| `use_plugin` | `True` | `False`를 넘기면 → `plugin/`을 전혀 붙이지 않고, 도메인 능력은 전부 `AgentSpec.instructions`에 의존한다 |

덧붙여: `instructions`는 [append](glossary.md#叠加)(`system_prompt`의 `append`)를 타고,
plugin과는 별개의 통로다 —— 전자는 매 턴 컨텍스트에 있고, 후자는 필요 시 로드된다. 짧고 반드시 지켜야 할 규율은 `instructions`에,
길고 가끔 쓸모 있는 지식은 skill에 쓴다.

## 3. 문서 사이트 {#三文档站}

지금 읽고 있는 이 사이트는 mkdocs-material로 만들었고, 소스 파일은 저장소의 `docs/` 아래에 있으며, `main`에 push하면 자동 배포된다.

| 단계 | 무엇인가 |
|---|---|
| 설정 | `mkdocs.yml`, `docs_dir: docs` |
| 다국어 | `mkdocs-static-i18n`, `docs_structure: folder` —— `docs/zh/`, `docs/en/`…… 기본 언어는 `zh` |
| 의존성 | `docs-requirements.txt`(버전 고정). `pyproject.toml`의 `docs` extra가 **아니다** —— CI가 설치하는 건 전자다 |
| 빌드 | `mkdocs build --strict`. 깨진 내부 링크, 존재하지 않는 페이지를 가리키는 nav는 바로 빌드를 실패시키고, 404를 조용히 배포하지 않는다 |
| 리다이렉트 | `hooks/redirects.py`, 빌드 **이후** 최종 URL 기준으로 meta-refresh 스텁 페이지를 써서 예전 평면 주소(`/start/`, `/workflow/`, `/case-ht001/`……)를 새 위치로 잇는다 |
| 배포 | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, GitHub Pages로 배포 |

로컬에서 문서 수정:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # 로컬 미리보기
mkdocs build --strict         # 커밋 전에 한 번 돌린다. CI와 같은 명령
```

CI의 트리거 조건은 `main`으로 push하고 **또한** 변경이 다음 경로에 맞을 때이며, 그 밖에 Actions 페이지에서 수동으로
`workflow_dispatch`할 수 있다:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### `install.sh`를 왜 Pages에서 배포하나 {#installsh-为什么从-pages-发}

빌드 단계 끝에 이 한 줄이 있다:

```yaml
- run: cp install.sh site/install.sh
```

설치 스크립트가 사이트 산출물에 끼워 넣어지고, 그래서 문서 사이트 도메인에 붙는다. 한 줄 설치는 이렇게 생겼다:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

이유는 아주 현실적이다: **`raw.githubusercontent.com`은 중국에서 안 되고, `*.github.io`는 된다**(실측).
스크립트 자체는 저장소 루트에 있고, 배포할 때 한 벌 더 복사할 뿐이다 —— 내용을 두 벌 유지할 필요도, 별도의 CDN도 필요 없다.

`install.sh`가 하는 일: Python 도구 설치기를 하나 고르고(`uv` > `pipx` > `uv` 설치 > `pip --user`),
GitHub에서 flower를 설치한 뒤 다음 단계를 안내한다. **자격 증명에는 손대지 않는다** —— 처음 `flower`를 돌릴 때 물어보고
`~/.config/flower/.env`에 저장한다.
