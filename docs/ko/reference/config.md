# 설정

flower에는 설정 파일 형식이 없고, 실제로 동작하는 설정 서브커맨드도 없다 —— 모든 설정은 **환경 변수**와
**`.env` 파일**, 그리고 Python 쪽에서만 넘길 수 있는 정책 객체 몇 개가 전부다. 이 페이지는 다섯 군데에 흩어진 것들을 한 장으로 모은다:
변수 하나하나, 인증 정보를 어떤 순서로 찾는지, `.env`가 어떤 문법을 인정하는지, `setting_sources=[]`가 정확히 무엇을 격리하는지,
한 번 실행하면 디스크에 무엇이 남는지, session store 세 층이 각각 무엇을 버리는지, 네트워크가 끊겼을 때 어떻게 기다리는지. 용어는 전부 [용어집](glossary.md)을 따른다.

| 알고 싶은 것 | 갈 곳 |
|---|---|
| flower가 인정하는 환경 변수 | [환경 변수 전체 표](#环境变量) |
| 내 token이 대체 어디서 오는지 | [인증 정보 탐색 우선순위](#凭证查找优先级) |
| `.env`의 그 줄이 왜 안 먹는지 | [`.env` 파싱 규칙](#env-解析) |
| 다른 머신으로 옮길 때 챙길 것 | [portable의 대가](#可移植性) |
| `.flower/`와 `runs/`에 뭐가 들어 있는지 | [디스크 레이아웃](#磁盘布局) |
| 어떤 메시지가 모델에 다시 먹여지지 않는지 | [session store 세 층](#会话存储) |
| 네트워크가 끊겼을 때 무엇을 기다리는지 | [네트워크 단절 resilience](#韧性) |

## 환경 변수 전체 표 {#环境变量}

다섯 그룹이다: flower가 직접 읽는 인증 정보와 엔드포인트, 모델 선택, 경로 탐색, 동작 스위치, 그리고 flower가 agent 하위 프로세스에 **써 주는** 것.
마지막 그룹은 네가 설정할 필요가 없다 —— 설정해도 덮어써진다.

### 인증 정보와 엔드포인트 {#凭证变量}

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic 공식 key. 있으면 `x-api-key` 헤더로 요청 | 없음 | `ANTHROPIC_AUTH_TOKEN`과 **둘 중 하나 필수** | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | 게이트웨이가 발급한 token. `ANTHROPIC_API_KEY`가 없을 때 `authorization: Bearer`로 사용 | 없음 | 위와 같음 | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | API 엔드포인트 루트 주소. 서드파티 게이트웨이는 자기 주소를 넣되 **`/v1`은 붙이지 않는다** —— 프로브가 `<BASE_URL>/v1/messages`로 조립한다 | `https://api.anthropic.com` | 아니오 | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

둘 다 설정하지 않으면(또는 둘 다 빈 문자열이면) `check_credentials()`가 그 네 줄짜리 에러를 반환하고, `Runtime.__init__`도
`RuntimeError`를 던진다(`env.py:184-194`;`runtime.py:156-158`).

### 모델 선택 {#模型变量}

flower는 이 중 세 개만 자기 판단에 쓰고, 나머지는 로드해서 SDK로 그대로 넘긴다.

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | 주 모델 이름. 동시에 [handoff](glossary.md#换代) 윈도의 기본값을 결정한다: 이름에 `1m`이 있거나 `haiku`가 없으면 → 100만, `haiku`가 있으면 → 20만 | 없음(엔드 쪽에서 결정) | 아니오 | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | opus 등급의 모델 매핑. `ANTHROPIC_MODEL`이 비어 있으면 윈도 판단이 이쪽으로 물러난다 | 없음 | 아니오 | `agent.py:78`;`cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | sonnet 등급의 모델 매핑. flower 자신은 읽지 않고, 로드와 차용만 담당 | 없음 | 아니오 | `env.py:34`;`cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | haiku 등급의 모델 매핑. **인증 프로브가 이걸 우선 사용한다** | 프로브는 `ANTHROPIC_MODEL`로, 다시 `claude-3-5-haiku-20241022`로 물러난다 | 아니오 | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | [subagent](glossary.md#subagent)가 어떤 모델을 쓸지. flower는 해석하지 않고 SDK가 소비한다 | 없음 | 아니오 | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | 사고 등급. 위와 같이 로드만 하고 해석하지 않는다 | 없음 | 아니오 | `env.py:35` |

`flower setup`에서 모델 이름을 채우면 `ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、
`ANTHROPIC_DEFAULT_SONNET_MODEL` **세 개를 함께 쓴다**(`cli.py:1383-1385`).

### 경로와 탐색 {#路径变量}

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `FLOWER_ENV` | `.env` 파일 경로 하나를 지정한다. 다른 모든 파일**보다 앞**에 놓인다 | 없음 | 아니오 | `env.py:48-49` |
| `XDG_CONFIG_HOME` | 전역 인증 파일의 위치 `$XDG_CONFIG_HOME/flower/.env`를 결정 | `~/.config` | 아니오 | `env.py:41-42` |
| `HOME` | `Path.home()`의 출처. `~/.config`와 `~/.claude` 두 경로 모두 여기서 유도된다 | 시스템이 제공 | 아니오 | `env.py:41`、`:67` |

### 동작 스위치 {#行为开关}

둘 다 비상구다: 설정하지 않는 게 정상이고, 설정하는 건 flower가 뭔가 하나를 덜 하게 하려는 것이다. **비어 있지 않은 아무 값이나 넣으면 발효되며**,
값 자체는 파싱하지 않는다(`update.py:121`;`cli.py:1413`).

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | [자동 업데이트](../getting-started/install.md#自动更新)를 끈다. 설정하지 않으면 pip / pipx / uv로 설치한 flower가 시작할 때 백그라운드 스레드를 하나 띄워 새 버전이 있는지 확인하고, 있으면 설치한다. **다음 번 `flower` 실행부터 적용**되며, 24시간에 최대 한 번만 확인하고 타임스탬프는 `~/.config/flower/.update`에 기록된다 | 없음(자동 업데이트 켜짐) | 아니오 | `update.py:32-33`、`:121-124` |
| `FLOWER_NO_PROBE` | 시작 시의 [인증 프로브](cli.md#第二道-凭证能不能用)를 건너뛴다. 비대화형(파이프 / CI / 리다이렉트된 stdin)에서는 원래 프로브하지 않으므로, 이 변수는 대화형 터미널을 위해 남겨둔 구멍이다 | 없음(대화형에서는 프로브함) | 아니오 | `cli.py:1413` |

git 소스에서 실행한 flower는 자동 업데이트의 영향을 받지 않으며, `FLOWER_NO_UPDATE`는 이 경우 no-op이다 —— 업데이트 명령 단계에서
저장소에 `.git`이 있음을 알아채면 바로 `None`을 반환한다(`update.py:83-87`).

### flower가 agent 하위 프로세스에 써 주는 것 {#写出的变量}

이 셋은 `CompactPolicy.env()`가 생성해서 `ClaudeAgentOptions.env`에 넣는 것이며(`agent.py:48-58`、`:241-245`),
harness 내장 [compact](glossary.md#压缩)를 제어한다. **shell에서 직접 설정해도 의미가 없다** ——
실제로 발효되는 것은 flower가 하위 프로세스에 전달하는 쪽이다.

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1`이면 자동 compact를 끈다. [handoff](glossary.md#换代)가 켜져 있으면 **강제로 기록** —— 두 메커니즘이 동시에 돌면 컨텍스트가 줄어든 게 누구 짓인지 구분할 수 없다 | handoff가 기본 켜짐이므로 실제로는 항상 `1` | 아니오(flower가 씀) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1`이면 `/compact`까지 함께 끈다. `CompactPolicy(mode="off")`일 때만 쓴다 | 쓰지 않음 | 아니오(flower가 씀) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 자동 compact의 윈도(tokens). `CompactPolicy(window=N)`일 때만 쓴다 | 쓰지 않음 | 아니오(flower가 씀) | `agent.py:56-57` |

### 컨테이너 래퍼가 읽는 것 {#容器变量}

이 둘은 flower 본체가 읽는 게 아니라 `docker/flowerbox`라는 shell 래퍼가 읽는다. 전체 사용법은 [배포](deploy.md)를 보라.

| 변수 | 역할 | 기본값 | 필수 | 출처 |
|---|---|---|---|---|
| `FLOWER_HOME` | `--env-file`에 쓸 `.env`를 어디서 찾을지 | 스크립트 자신 위치의 상위 디렉터리 | 아니오 | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | 어떤 이미지를 쓸지 | `flower-box` | 아니오 | `docker/flowerbox:13` |

**`.env`의 키는 위의 것들로 제한되지 않는다.** 파서는 **모든** `k=v` 줄을 `os.environ`에 로드하며 화이트리스트를 두지 않는다
(`env.py:30`、`:102-107`). 위 9개 인증 키로 이루어진 `KNOWN`은 두 군데에서만 작용한다: `~/.claude`
설정을 차용할 때의 화이트리스트(`env.py:72`), 그리고 `-v`로 시작할 때 `describe()`가 출력하는 필드 범위(`env.py:205`).

## 인증 정보 탐색 우선순위 {#凭证查找优先级}

`load_dotenv()`에 경로를 넘기지 않으면 아래 순서로 **존재하는 모든** 파일을 차례로 읽어 들인다
(`env.py:45-53`、`:78-112`):

1. **프로세스 환경 변수** —— 언제나 최우선. 어떤 `.env`도 이미 export된 값을 덮지 못한다.(`env.py:91`)
2. **`$FLOWER_ENV`가 가리키는 파일** —— 설정했을 때만 존재하는 항목.(`env.py:48-49`)
3. **`$PWD/.env`** —— 현재 작업 디렉터리. 어느 프로젝트로 `cd`하든 가까운 것을 읽는다.(`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** —— 사용자당 하나인 전역 위치. `flower setup`이 쓰는 곳이 여기다.(`env.py:51`、`:39-42`)
5. **소스 저장소 루트의 `.env`** —— `flower/core/env.py`에서 세 단계 위. 소스에서 실행할 때만 존재한다. pip / pipx / uv로 설치한 flower는 site-packages 안에 있으므로 이 항목이 없다.(`env.py:52`)
6. **`~/.claude/settings.json`, 그다음 `~/.claude/settings.local.json`의 `env` 블록** —— 마지막 폴백이며, **9개 인증 키만 가져온다**.(`env.py:56-75`、`:109-111`)

**어느 파일이 이기는가**: 3번(프로젝트 `.env`)이 4번(전역 `.env`)을 이기고, 4번이 5번(저장소 루트 `.env`)을 이기며,
셋 다 6번(Claude Code 설정)을 이기고, 전부 1번(프로세스 환경)은 이기지 못한다.

구현 방식은 "**이미 값이 있는 키는 덮지 않는다**"이다(`env.py:90-93`): 앞에 놓인 것이 먼저 키를 차지하고, 뒤의 것은 빈 자리만 채운다.
그래서 우선순위는 **파일 단위가 아니라 키 단위로 계산된다** —— 프로젝트 `.env`에 `ANTHROPIC_BASE_URL`만 써 두었다면,
token은 전역 쪽에서 와도 된다. 같은 이름의 키는 처음 나타난 값이 끝까지 간다.

6번은 **자동 탐색**일 때만 활성화된다. 경로를 명시적으로 주면(`load_dotenv("/path/to/.env")`) 그 파일 하나만 읽고
어떤 폴백도 타지 않는다(`env.py:86-87`、`:109`).

### 6번: Claude Code의 token 빌려 쓰기 {#借用}

`~/.claude/settings.json`과 `~/.claude/settings.local.json`을 차례로 읽어 `data["env"]` dict를 가져오고,
거기서 이 9개 키만 골라낸다(`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

파일이 없거나, 읽지 못하거나, 올바른 JSON이 아니면(`OSError` / `ValueError`) 빈 dict를 반환하고 계속 진행한다 ——
**폴백이 실패했다고 이번 run까지 데려가서는 안 된다**(`env.py:62-63`、`:66-69`).

코드가 취하는 입장은 이렇다: 빌리는 것은 "token을 어디서 찾을지"뿐이고, settings.json 안의 다른 어떤 것도(권한 규칙, hook,
모델 설정) 일절 넘겨받지 않는다. 그래서 이것은 `setting_sources=[]`의 portable 약속을 위반하지 않는다(`env.py:17-19`、`:59-61`).
`install.sh:77`은 이를 하나의 기능으로 홍보한다: 로컬에 Claude Code를 설정해 둔 사람은 설정 화면조차 보지 않는다.

!!! warning "제품 내 에러 문구가 실제 동작과 반대다"
    인증 정보를 전혀 찾지 못했을 때 flower가 출력하는 에러의 마지막 줄은 이렇다:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, 그 문장은 `:192`에 있다. 같은 표현이 `.env.example:2`、`env.py:3-4`、
    `agent.py:10-12`에도 나온다.) **코드를 기준으로 하라: 읽는다.** `env.py:56-75`와 `:109-111`은 명확히 그 두 파일을 읽으며,
    `install.sh:77`은 이걸 셀링 포인트로 삼는다. 저 문구는 현재 오해를 부른다 ——
    Claude Code를 설정해 둔 머신이라면, 네 token은 십중팔구 거기서 온 것이다.

## `.env` 파싱 규칙 {#env-解析}

파싱 규칙은 외울 수 있을 만큼 짧다(`env.py:95-107`, 13줄): 줄마다 `strip`하고, 빈 줄과 `#`로 시작하는 줄,
`=`가 없는 줄은 건너뛴다. 나머지는 **첫 번째** `=`를 기준으로 key와 value로 자르고, 양쪽을 각각 `strip`한 뒤 value에 다시
`.strip("'\"")`를 한 번 더 건다 —— 앞뒤의 작은따옴표/큰따옴표는 무조건 벗겨내며, **짝이 맞을 필요도 없다**.

**인정하는 표기**:

| 표기 | 결과 |
|---|---|
| `KEY=VALUE` | 정상 |
| `KEY = VALUE` | 정상 —— 등호 양쪽 공백은 strip된다 |
| `KEY="VALUE"` / `KEY='VALUE'` | 정상 —— 앞뒤 따옴표가 벗겨진다 |
| `KEY=a=b` | value는 `a=b` —— 첫 번째 `=`로 자르고, 뒤의 등호는 값에 그대로 남는다 |
| `# 주석` | 줄 전체를 건너뜀 |
| 빈 줄 | 건너뜀 |

**인정하지 않는 표기**. 써도 에러는 나지 않고, 조용히 예상 밖의 값이 될 뿐이다:

| 표기 | 실제 결과 |
|---|---|
| `export KEY=VALUE` | key가 `export KEY`가 되고, `KEY` 자체는 여전히 값이 없다 |
| `KEY=value # 설명` | value는 `value # 설명` —— 줄 끝 주석은 벗겨내지 않는다 |
| `KEY=$OTHER` | 리터럴 `$OTHER`. 변수 치환은 하지 않는다 |
| 여러 줄 값(따옴표로 줄을 넘김) | 줄 단위로 처리하며, 둘째 줄은 `=`가 없으므로 줄 전체가 건너뛰어진다 |

**빈 값도 키를 차지한다.** 우선순위가 높은 파일에 `ANTHROPIC_AUTH_TOKEN=`가 나오면 `take()`가
`os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`를 실행하고, 이후 파일들은 "키가 이미 존재함" 때문에 채워 넣지 못한다
(`env.py:90-93`). 반면 `check_credentials()`는 참 값으로 판정하므로 빈 문자열은 여전히 미설정으로 친다(`env.py:186`).
**결과적으로 인증 정보도 없고 폴백도 못 받는다.** 어떤 키를 원하지 않으면 줄 전체를 지워라. 빈 값으로 남기지 마라.

## portable의 대가 {#可移植性}

`build_options()` 안의 그 한 줄이 전부다(`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True`는 `Runtime`의 기본값이고, **커맨드라인에는 이걸 끌 스위치가 없다** —— 끄려면 Python API로
`Runtime(portable=False)`를 쓰는 수밖에 없으며, 그러면 `["project"]`가 되어 프로젝트의 `.claude/`를 읽는다.

### 격리되는 것들 {#被隔绝的东西}

| 격리되는 것 | 결과 |
|---|---|
| 호스트 머신 `~/.claude/`의 설정 | 거기 있는 권한 규칙, hook, 모델 설정이 일절 발효되지 않는다. **인증 정보만 유일한 예외**이며, [차용](#借用) 참고 |
| 프로젝트의 `.claude/` | 위와 같음. `portable=False`일 때만 읽는다 |

도메인 능력은 이 경로를 타지 않는다 —— 저장소와 함께 배포되며, `plugins=[{"type": "local", "path": PLUGIN_DIR}]`로 로드된다
(`agent.py:26`、`:210-212`). [배포](deploy.md)를 보라. 도메인 지시는 Claude Code 기본 시스템
프롬프트 뒤에 **append**되는 것이지 교체가 아니다(`agent.py:198-202`). 그래서 전문화가 범용 능력의 손실을 대가로 하지 않는다.

### 다른 머신으로 옮길 때 챙길 것 {#换台机器要带什么}

- **인증 정보: 파일 하나**. `~/.config/flower/.env`를 복사해 가거나, 새 머신에서 다시 한 번 설정하면 된다.
  가져가지 않으면 아무것도 돌지 않는다 —— 자동으로 상속되는 것은 없다.
- **continuity 상태: 디렉터리 전체**. `runs/`(session 저장소, manifest, lineage)와 `.flower/`(workbench).
- **단, 경로가 일치해야 한다**. `lineage.json`에는 워크스페이스의 절대 경로가 저장되어 있고, 맞지 않으면 없는 것으로 치고 조용히 새 session으로 물러난다.
  **에러를 내지 않는다**(`lineage.py:65-66`). 이유는 SDK의 `project_key`가 워크스페이스 경로에서 유도되기 때문이다
  (`/`、`_`、`.`를 전부 `-`로 치환, `runtime.py:40-41`). 디렉터리 위치가 바뀌면 예전 `session_id`를 찾을 수 없다.

## 디스크 레이아웃 {#磁盘布局}

flower를 한 번 실행하면 두 개의 트리를 쓴다: `<run_dir>/`에는 장부와 session이, `<workspace>/.flower/`에는 [workbench](glossary.md#工作台)가 놓인다.
둘 다 기본적으로 현재 디렉터리 아래지만, **기준점이 다르다**.

!!! warning "`runs/`는 현재 디렉터리를 따르지, `-w`를 따르지 않는다"
    `-r/--run-dir`의 기본값은 `"runs"`이고, `Runtime`은 여기에 `Path(run_dir).resolve()`를 적용한다
    (`runtime.py:93-94`) —— **현재 작업 디렉터리** 기준이지, `-w`로 지정한 워크스페이스 기준이 아니다.
    `~`에서 `flower -w /path/to/proj`를 실행하면 session 저장소는 `~/runs/`에 떨어지고, 프로젝트 안에는 생기지 않는다.

### `<run_dir>/` —— 기본값 `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite,全量 transcript(含每个 subagent 自己那条)
  manifest.json      运行清单:每一步的 session_id / 花费 / 重试 / 失败原因,跨进程累积
  lineage.json       血缘:步骤名 → session_id,同一个目录再跑一次靠它接上
  aside/             旁路问答的独立 Runtime,自己的 sessions.db + manifest.json
  workbench/         仅当走 run / once 路径且给了 -W
```

| 경로 | 내용 | 출처 |
|---|---|---|
| `runs/sessions.db` | 전체 transcript. 쓰는 주체는 `PruningSessionStore`이며, 세 층 정책은 [아래](#会话存储) 참고 | `runtime.py:109-112` |
| `runs/manifest.json` | JSON 배열이며, **프로세스를 넘어 누적되는** [run manifest](glossary.md#运行清单). 필드는 아래 표 참고 | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. 먼저 `.tmp`에 쓰고 `replace`하는 원자적 교체 | `lineage.py:31`、`:87-97` |
| `runs/aside/` | [oracle](glossary.md#旁路顾问)의 독립 Runtime. **비용과 lineage가 메인 manifest에 섞이지 않는다** | `cli.py:741-743` |
| `runs/workbench/` | `Runtime(workbench=True)`의 기본 workbench 위치로, 워크스페이스 바깥에 있다. `go` 경로는 쓰지 않는다 | `runtime.py:148-151` |

`manifest.json`의 각 행은 `asdict(StepResult)`에 두 개의 패치를 더한 것이다(`runtime.py:44-71`、`:579-582`):

| 필드 | 타입 | 의미 |
|---|---|---|
| `step` | `str` | step 이름. 네 가지 형태: `<이름>`、`<이름>#round<N>`(반려되어 재작업)、`<이름>#retry<N>`(일반 재시도)、`<이름>·判定#<N>`([judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | 이 step에서 마지막까지 살아 있던 [session](glossary.md#会话) |
| `ok` | `bool` | 성공 여부 |
| `cost_usd` | `float` | 이 step에 든 비용 |
| `num_turns` | `int` | 몇 턴 돌았는지 |
| `text` | `str` | 이 step의 최종 응답 |
| `error` | `str \| None` | 실패 원인. SIGHUP / SIGTERM으로 죽었을 때는 `killed-by-signal`(`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch 초 |
| `attempts` | `int` | 실제 시도 횟수. `>1`이면 재시도했다는 뜻 |
| `errors` | `list[str]` | 역대 실패 원인. **여기에만 있고, 모델은 볼 수 없다** |
| `resumed` | `bool` | 처음부터 다시 돌린 게 아니라 resume으로 중단 지점에서 이어붙였는지 |
| `retired` | `list[str]` | 이 step의 [handoff](glossary.md#换代) 때 태워버린 session_id들, 순서대로 |
| `context` | `int` | 마지막 턴에 [main thread](glossary.md#主线程)가 실제로 본 컨텍스트 규모 |
| `duration_s` | `float` | 수동으로 채운 값 —— `@property`라서 `asdict()`가 잡지 못한다 |
| `run` | `str` | 이 프로세스의 표식 `YYYYmmdd-HHMMSS-<6 위 hex>`. **인스턴스마다 유일해야 한다** |

디스크 기록 전략은 **덮어쓰지 않고 이어 쓰기**다: 매번 기록 전에 파일을 다시 읽어, `run`이 자기 것과 같은 행만 최신으로 바꾸고
남의 행은 그대로 둔다(`runtime.py:564-586`). 그래서 같은 디렉터리에서 flower를 여러 개 병렬로 돌려도 장부가 서로를 지우지 않는다.

`runs/` 안의 것은 순수 데이터이며, 언제든 sqlite3나
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)로
오프라인에서 들춰볼 수 있다.

### `<workspace>/.flower/` —— workbench {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

세 개의 하위 디렉터리와 인덱스는 `Workbench`가 만든다(`workbench.py:73-92`). `INDEX.md`는 session 레벨의
`system_prompt.append`를 타므로 **subagent는 상속받지 못한다** —— 따라서 "긴 산출물은 `artifacts/`에 쓴다"는 규칙은
[coordinator](glossary.md#协调者)가 [task brief](glossary.md#任务书)에서 다시 전달해야 하며, 그것이 유일한 통로다.

`go` 경로는 `notes/` 아래에 다음을 고정적으로 생성한다:

| 파일 | 내용 | 출처 |
|---|---|---|
| `notes/需求.md` | 동결된 [brief](glossary.md#需求确认书). 네 단락: 목표 / 수용 기준 / 경계 / 미지와 가정 | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | 동결된 두 단락: 목표 / 판정 체크리스트 | `workflow/goal.py:124` |
| `notes/问答记录.md` | 모든 문답의 추가 기록. "사람이 먼저 말한" 인박스 항목도 포함한다. **컨텍스트에 들어가지 않으며, 기록 보존용일 뿐이다** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | [handoff document](glossary.md#交接书). 이전 세대는 `notes/archive/交接/<步骤名>-<时间戳>.md`로 들어간다 | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `--new` / `/new`로 아카이브한 `lineage.json` + `需求.md` + `目标.md`(**이동이지 삭제가 아니다**) | `lineage.py:100-117` |

**`--isolate`일 때 workbench는 저장소 바깥으로 옮겨진다**: `<workspace 的父目录>/.flower-<workspace 名>/`
(`starter.py:47-55`). worktree는 각 agent의 사설 사본이고 workbench는 agent를 가로지르는 공유 층이다.
공유되는 것을 사설 울타리 안에 넣을 수는 없다. 이때 모델에게 주는 경로는 절대 경로다(`workbench.py:69-71`、`:142-145`).

**`spill/`에는 쓰는 주체가 둘이고, 낙점 알고리즘이 다르다**:

| 누가 쓰나 | 언제 | 어디에 | 임계값 |
|---|---|---|---|
| `spill_guard`(`PostToolUse` hook) | 도구 결과가 모델에 들어가기 **전** | `<工作台 root>/spill/`(`guard.py:130`) | `spill_threshold`, 기본 4000자 |
| `TrimPolicy`(`load` 시) | resume 전에 히스토리를 재생할 때 | `<workspace>/.flower/spill/` —— 워크스페이스 기준의 고정 문자열(`trim.py:49`、`:303`) | `min_chars`, 기본 2000자 |

기본 레이아웃에서는 같은 디렉터리다. 하지만 workbench가 옮겨지면(`-W`로 `runs/workbench/`에 떨어지거나, `--isolate`로
저장소 밖에 떨어질 때) 둘이 갈라진다 —— `TrimPolicy` 쪽은 항상 워크스페이스 안에 있는데, agent의 `Read`가
반드시 닿을 수 있어야 하기 때문이다.

`spill_guard`가 바꿔 넣는 것은 한 줄이 아니라, 한 줄짜리 포인터에 **앞부분 400자**를 더한 것이다(`guard.py:132-140`).
spill 파일 자체를 읽는 호출은 통과시킨다. 그러지 않으면 "전문이 필요하면 Read로 읽어라"가 빈말이 된다 —— 읽어 오면 또 임계값을 넘고, 또 spill되어
무한 루프가 된다(`guard.py:155-170`).

### `sessions.db`의 테이블 구조 {#sessions-db}

테이블 세 개이며, 생성문은 `stores/sqlite.py:27-51`에 있다:

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

| 테이블 | 한 행이 무엇인가 | 요점 |
|---|---|---|
| `entries` | transcript 안의 한 항목. `payload`는 원본 JSON | `uid`는 항목의 `uuid`이며 **멱등 키** 역할을 한다: 실패한 배치는 3번 재시도되므로, 재생이 중복 행을 만들면 안 된다. `uuid`가 없는 항목(제목, 태그, 모드 표식)은 중복 제거하지 않으므로 유니크 인덱스에 `WHERE uid IS NOT NULL`이 붙는다 |
| `meta` | 한 session의 커서 | `next_seq`는 다음 시퀀스 번호, `mtime`은 밀리초 타임스탬프이며 **엄격히 단조 증가**한다(`sqlite.py:72-79`) —— `list_sessions`와 summary가 이 시계를 공유하므로, 단조가 아니면 SDK의 신구 판정이 잘못된 fast path를 타게 된다 |
| `summaries` | 한 main thread의 요약 사이드카 | **메인 transcript만 참여**하며, subagent의 것은 계산에 들어가지 않는다(`sqlite.py:122-123`) |

`store_key`의 구성(`sqlite.py:54-58`): `<project_key>/<session_id>`이며, subagent는 뒤에 `subpath` 한 토막이 더 붙는다.
`project_key`는 SDK가 워크스페이스 경로에서 유도한다 —— `/`、`_`、`.`를 전부 `-`로 바꾼다.

실제 샘플을 하나 보자([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

이 샘플은 `entries` 956건, `meta` 10건, `summaries` 4건이다 —— session 10건 중 4건이 메인 transcript,
6건이 subagent의 것이고, `summaries`는 정확히 메인 transcript 수와 같다.

## session store 세 층 {#会话存储}

!!! note "세 층은 상속 체인이지, 선택 가능한 조합이 아니다"
    `PruningSessionStore`는 `TrimmingSessionStore`를 상속하고, 그것은 `SqliteSessionStore`를 상속한다.
    `Runtime`은 **언제나** 가장 바깥쪽 것을 구성하며(`runtime.py:109-112`), 구성 파라미터에 백엔드를 갈아 끼울 입구는 없다.
    "어느 한 층을 끄는" 방법은 그 층의 정책 객체 `enabled`를 `False`로 두는 것이지, 클래스를 바꾸는 게 아니다.

`append`(쓰기)는 언제나 전량을 디스크에 기록하며 한 글자도 고치지 않는다. 세 층은 `load`(모델에 다시 먹일 쪽)에만 영향을 준다.
`load`의 실제 순서는 이렇다:

```text
SqliteSessionStore.load     从 entries 表按 seq 读出全部
  → TrimmingSessionStore.expire()   时效性 Bash 结果 → 换成"已过期"
  → TrimmingSessionStore.trim()     旧的大 tool_result → 落盘 + 换成指针
    → PruningSessionStore.prune()   合成错误消息 / 旧的被拒调用 → 整条摘掉并重接链
```

| 층 | 클래스 | 무엇을 버리나 | 기준 |
|---|---|---|---|
| 1 | `SqliteSessionStore` | 아무것도 버리지 않음 | —— |
| 2 | `TrimmingSessionStore` | 큰 도구 결과 본문, 만료된 ephemeral command 결과 | 크기 + 시효 |
| 3 | `PruningSessionStore` | 단절 잔해, 오래된 거부된 호출 | 에러인지 여부 |

2층은 [trim](glossary.md#裁剪)이고 3층은 [prune](glossary.md#剪除)이다 ——
**trim은 크기와 가치로 버리고, prune은 "에러인지 여부"로 버린다**. 헷갈리지 마라. 전체 시그니처는 [Python API](api.md)를 보라.

### `SqliteSessionStore` —— 기반 {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

외부 의존성 없는 SQLite 구현. Postgres / S3 / Redis로 바꾸려면 같은 프로토콜을 구현하면 되고, SDK에 딸린 일관성 테스트
스위트 `claude_agent_sdk.testing.session_store_conformance`로 바로 검증할 수 있다(`sqlite.py:1-8`).

프로토콜 메서드 외에, flower 자신이 쓰는 **동기** 조회가 세 개 있다:

| 메서드 | 반환 | 용도 |
|---|---|---|
| `projects()` | `list[str]` | 저장소에 실제로 존재하는 `project_key`. SDK는 cwd로부터 이를 유도하므로, 조회 전에 이걸로 확인하라. 추측하지 마라 |
| `has_session(project_key, session_id)` | `bool` | `meta` 한 행만 조회하고 payload는 읽지 않는다. [continuity](glossary.md#接续)를 시작하기 전에 먼저 확인하라 —— 존재하지 않는 session을 resume하면 하위 프로세스가 뜬 다음에야 터지고, 그때는 이미 돈과 시간을 쓴 뒤다 |
| `last_context(project_key, session_id, scan=60)` | `int` | 이 session이 마지막 턴에 본 컨텍스트 규모. 뒤에서부터 60건만 훑는다. `input_tokens`에 두 개의 `cache_*`를 모두 합산한다 —— 앞의 것만 보면 캐시 히트 시 0에 가까워져서 심각하게 과소평가하게 된다 |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

직교하는 두 규칙이다. `TrimPolicy`는 **크기**를 담당한다:

| 파라미터 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 최근 N개 `tool_result`는 원문을 유지 —— 지금 쓰고 있는 컨텍스트를 잘라내서는 안 된다 |
| `min_chars` | `int` | `2000` | 이보다 짧으면 자르지 않는다. 포인터로 바꾸면 오히려 token이 더 든다 |
| `spill_dirname` | `str` | `".flower/spill"` | 아카이브 디렉터리이며 **workspace 기준 상대 경로**다. 반드시 워크스페이스 안이어야 하고, 아니면 agent의 `Read`가 닿지 못한다 |
| `enabled` | `bool` | `True` | `Runtime(trim=False)`(기본)일 때는 `False` |

잘린 본문은 `<sha256 前 16 位>.txt`로 기록되고, 원래 자리는
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]`로 대체된다(`trim.py:54-57`、`:308-317`).

`EphemeralPolicy`는 **시효**를 담당한다: `git status`、`ls`、`ps` 같은 결과는 아주 짧아서 크기 기준으로는 영원히 잘릴 차례가 오지 않지만,
그 정확성은 시간이 지나면서 감쇠한다 —— 20턴 전의 `git status`는 "쓸모없는" 게 아니라 **오도한다**.

| 파라미터 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(ephemeral=…)`에서 변환되며, **기본 켜짐** |
| `keep_recent` | `int` | `6` | 최근 N건은 원문을 유지. `TrimPolicy`의 20보다 훨씬 작다 —— 이런 것들은 "최근"의 창 자체가 원래 짧다 |
| `max_chars` | `int` | `2000` | 이를 넘으면 `TrimPolicy`에 넘겨 spill·아카이브하며, 이 경로를 타지 않는다 |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | 대체 문구 |

**Bash** 도구의 결과에만 작용하며, 명령이 `EPHEMERAL_CMD`에 매치해야 한다. `Read`는 여기 포함되지 않는다: 파일 내용은
시간이 흐른다고 오도할 정도로 왜곡되지 않고, 오히려 모델 추론의 근거일 수 있다(`trim.py:153-160`). 만료된 내용은
**spill하지 않는다** —— 만료된 `git status`를 아카이브해 봐야 의미가 없고, 다시 실행하면 얻어진다.

판단 함수는 `is_ephemeral(cmd)`이며, 이것은 **동시에 coordinator에게 돌려주는 권한 목록**이기도 하다: `delegate_guard(allow_glance=True)`가
같은 함수를 쓴다(`trim.py:63-68`、`:128-150`). 두 집합은 언제나 같아야 한다 ——
통과시키되 자르지 않으면 만료된 `git status`가 컨텍스트를 영구히 점유하고, 자르되 통과시키지 않으면 coordinator가 `ls` 하나 때문에
subagent를 파견해 4.3k의 기동 비용으로 수십 자를 바꾸게 된다. 화이트리스트에 명령을 하나 추가하는 것은 이 두 문장을 동시에 말하는 것과 같다.

**언제 무엇을 쓰나**:

- 단절 잔해만 컨텍스트에 안 들어가게 하고 싶다면 → 아무것도 할 필요 없다. `Runtime`의 기본값이 이미 `PruningSessionStore`다.
  `trim=False`는 큰 결과를 자르지 않을 뿐, prune은 그대로 한다.
- 장시간 실행이고 도구 출력이 크다면 → `trim=True`. `go` 경로의 CLI는 기본으로 켜져 있고, `--no-trim`으로 반대로 끈다.
- [coordinator](glossary.md#协调者)에 `glance=True`를 켰다면 → `ephemeral`은 반드시 켜 두어야 한다. 이유는 앞 문단 참고.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| 파라미터 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | `isApiErrorMessage=true`이거나 `message.model == "<synthetic>"`인 합성 메시지를 제거 |
| `neutralize_interrupts` | `bool` | `True` | `[Request interrupted …]`인 `tool_result`는 **본문만 바꾸고 블록은 제거하지 않는다** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | 위 항목의 대체 문구 |
| `heal_orphans` | `bool` | `True` | "`tool_use`는 있는데 `tool_result`가 없는" 고아 호출에 합성 결과를 **보충**한다 |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | 보충된 `tool_result`의 본문 |
| `keep_denials` | `int` | `1` | permission hook에 거부당한 도구 호출 중 최근 N건만 남기고, 그보다 오래된 것은 **호출과 결과를 함께** 제거 |

`keep_denials`는 이 층까지 전달되는 유일한 `Runtime` 구성 파라미터다(`Runtime(keep_denials=N)`).
기본이 0이 아니라 1인 이유: 가장 최근의 거부는 유효한 신호이며, 모델이 같은 턴 안에서 차단된 명령을 반복 재시도하는 것을 막아준다.
**키우지 마라** —— 거부된 호출은 애초에 실행된 적이 없어서 결과에 아무 정보도 없고, 실측상 한 건이 273자를 차지한다
(93자의 거부 문구 + 180자의 죽은 명령 원문). 게다가 **오도한다**: 실측에서 coordinator가 "Bash를 직접 쓰지 말라"를 몇 건 읽고 나면
허용된 `git status`조차 시도하지 않고 곧장 "Bash가 제한되어 있으니 agent를 파견해 보겠다"고 말한다(`prune.py:135-148`).

`heal_orphans`가 고치는 것은 **중단 후 resume이 매번 400을 내는** 문제다: 중단은 메시지 경계에서 끊기므로 당시 비행 중이던 `tool_use`
뒤에 `tool_result`가 아예 없을 수 있는데, API는 둘이 짝을 이루기를 요구한다. 이 망가진 히스토리는 transcript에 남아서 저절로 사라지지 않으며,
그래서 이후 모든 resume이 그것 때문에 되돌려진다. 고치는 방법은 고아를 포함한 그 assistant 항목 뒤에 `user` 항목을 하나 끼워 넣어
그 안의 모든 고아 결과를 한 번에 채우고, 원래 그 assistant를 가리키던 `parentUuid`를 새로 끼워 넣은 항목으로 돌리는 것이다
(`prune.py:95-147`). **보충하되 삭제하지 않는다**: 고아를 삭제하면 부모-자식 체인을 다시 이어야 하고, 같은 assistant 항목 안에 정상 블록이나
텍스트, thinking이 함께 있을 수 있어 말려들기 쉽다(`prune.py:195-204`).

구조적 레드라인 세 가지. 어기면 API가 바로 에러를 낸다:

1. **`tool_result` 블록 자체는 반드시 있어야 하며**, `content`만 교체할 수 있다. 하나라도 빠지면 "Missing Tool Result Block"이다
   (`trim.py:20-22`;`prune.py:79-92`).
2. **`isCompactSummary` / `isMeta` 항목은 건드리면 안 된다** —— compact로 눌린 그 구간 히스토리의 유일한 존재 형태다
   (`trim.py:179-181`).
3. **한 항목을 제거하면 그 자식을 그 부모에 반드시 다시 이어야 한다.** transcript는 `parentUuid` 단일 체인이며, harness는 리프에서
   거슬러 올라가므로 체인이 끊긴 지점 앞의 히스토리는 전부 사라진다(`prune.py:95-122`). 그래서 `relink()`는 제거 대상을 **포함한**
   전체 리스트를 받아야 하고, 필터링은 자기가 한다.

**SQLite 안의 원문은 한 글자도 고치지 않는다** —— 세 층은 "모델에 다시 먹이는 쪽"에만 영향을 준다(`trim.py:18`;`prune.py:8`).

## 네트워크 단절 resilience {#韧性}

long-horizon workflow는 한 번 돌면 몇 시간이고, 네트워크는 반드시 한 번은 끊긴다. 기본 동작은 아주 나쁘다: 끊기는 순간 harness가 transcript에
합성 assistant 메시지 하나를 밀어 넣는데(`model="<synthetic>"`、`isApiErrorMessage=true`), 본문은
`API Error: Can't reach the API server …`이다. 그것이 session의 리프가 되고, 이후 resume하면 "모델이 직전에 한 말"로 간주되어
다시 먹여져 모델은 자기가 네트워크 장애를 논하고 있다고 생각한다. 게다가 `StepResult.text`에 섞여 들어가 workflow를 따라 다음 step의
prompt로 전달된다(`resilience.py:1-22`).

[resilience](glossary.md#韧性) 층은 세 가지를 하며, 하나도 빠뜨릴 수 없다: 프로브, 처음부터가 아니라 이어 달리기, 에러를 컨텍스트에 넣지 않기.

### `Resilience` 파라미터 {#resilience}

| 파라미터 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(resilience=…)`에서 변환됨 |
| `max_attempts` | `int` | `6` | 한 [step](glossary.md#步骤)당 최대 시도 횟수. **첫 시도 포함** |
| `base_delay` | `float` | `4.0` | 지수 백오프 시작점, 초 |
| `max_delay` | `float` | `120.0` | 백오프 상한, 초 |
| `probe_timeout` | `float` | `5.0` | 프로브 1회 타임아웃, 초 |
| `probe_interval` | `float` | `15.0` | 단절 시 얼마마다 프로브할지, 초 |
| `max_offline_wait` | `float` | `3600.0` | 단절 시 최대 대기 시간. 기본 1시간 —— 이보다 길면 대개 흔들림이 아니라 진짜 사고다 |
| `retry_unknown` | `bool` | `True` | 분류되지 않는 에러도 재시도한다. 대부분의 미지 에러는 일시적이고, 치명적 에러는 이미 따로 막혀 있다 |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | 이어 달릴 때 모델에게 하는 말 |

백오프 공식(`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

즉 `±25%` 지터로, 네트워크가 복구되는 순간 여러 프로세스가 한꺼번에 몰려드는 것을 피한다. 기본값 기준: 1회차 백오프 4초(실제 3~5),
2회차 8초(6~10), 5회차부터는 120초로 상한(90~150).

### 프로브 전략 {#探针}

- **프로브 대상은 `ANTHROPIC_BASE_URL`의 host:port**이지 `api.anthropic.com`이 아니다(`resilience.py:67-72`).
  자체 게이트웨이를 쓸 때, 후자가 통한다고 전자가 통한다는 뜻은 아니다.
- **DNS와 TCP 핸드셰이크만 한다**: `getaddrinfo` 다음 `connect_tcp`, 그리고 곧바로 닫는다. HTTP를 보내지 않고,
  인증 정보를 싣지 않고, 돈이 들지 않는다(`resilience.py:75-85`). 프로브는 반드시 공짜여야 한다. 그렇지 않으면 "단절 시 15초마다 프로브"
  자체가 장애가 된다.
- 어떤 실패든 도달 불가로 친다 —— DNS가 죽었는지 TCP가 거부했는지 구분하지 않는다.
- `wait_online()`은 그 자리에서 기다린다: 통하면 `True`를 반환하고, `max_offline_wait`을 다 채우면 `False`를 반환한다.
  처음 도달 불가일 때 `<host>:<port> 不可达,等待恢复(最多 60 分钟)` 한 줄을 알리고, 복구되면 다시 한 줄
  `<host>:<port> 恢复,继续`를 알린다. **중간에는 화면을 도배하지 않는다**(`resilience.py:126-140`).

시작 전의 그 인증 프로브는 별개다: 실제로 `POST <BASE_URL>/v1/messages`를 한 번 때리며, `max_tokens=16`,
기본 타임아웃 20초다(`env.py:126-181`). `max_tokens`를 **1로 두지 마라** —— 실측상 사고 사슬을 강제하는 모델은 사고조차
담지 못해 서버가 30초까지 버둥거린 끝에 응답한다. 16으로 두면 3.6초면 된다(`env.py:120-123`).

### 에러 분류 {#错误分类}

`classify(text)`는 셋 중 하나를 반환한다. **치명적인 것부터 판정한다**: 401 같은 텍스트에도 "connection" 같은 단어가 섞여 있는 경우가 흔해서,
순서가 뒤바뀌면 하염없이 기다리게 된다(`resilience.py:53-64`).

| 분류 | 무엇에 걸리나(정규식은 `resilience.py:37-50`) | 동작 |
|---|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` | 즉시 중단, 재시도하지 않음. 몇 번을 재시도해도 결과는 같고, 매번 돈이 든다 |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`timeout`、`service unavailable` | 네트워크가 돌아올 때까지 기다린 뒤 resume으로 이어 달림 |
| `unknown` | 어디에도 매치되지 않음 | `retry_unknown=True`(기본)일 때 역시 재시도 |

재시도 가능한 것과 불가능한 것을 구분하는 게 이 층의 핵심이다: **네트워크 흔들림은 기다려야 하고, 인증 오류는 즉시 멈춰야 한다** ——
단절 시 하염없이 기다리는 건 맞지만, key를 잘못 썼는데 하염없이 기다리는 건 시간을 태우는 짓이다.

### 무엇이 컨텍스트 밖에 막히는가 {#错误不进上下文}

1. **합성 에러 메시지**. `PruningSessionStore`가 `load` 시 통째로 제거하고 `parentUuid`를 다시 잇는다
   (`prune.py:27-32`、`:191-195`). **SQLite 안에는 그대로 남아 있고**, 다시 먹이지 않을 뿐이다.
2. **이벤트 스트림에서 그것은 `kind="text"`가 아니라 `kind="error"`다.** 그래서 `StepResult.text`에 들어가지 않고,
   workflow를 따라 다음 step의 prompt로 전달되지도 않는다(`resilience.py:17-18`).
3. **`resume_prompt`는 의도적으로 어떤 에러 세부 정보도 담지 않는다.** 모델은 "중단됐으니 이어서 하라"만 알면 되고,
   `ENOTFOUND`인지 `503`인지는 알 필요가 없다. **그건 로그의 몫이지 컨텍스트의 몫이 아니다**(`resilience.py:112-113`).
   로그는 `manifest.json`의 `errors` 필드에서 보라.

처음부터가 아니라 이어 달리기: 실패 시점에 `session_id`는 이미 확보되어 있으므로 resume으로 중단 지점에서 이어붙이며, 이전에 쓴 비용이 헛되지 않는다.

## 관련 {#相关}

- [커맨드라인](cli.md) —— 각 스위치가 이 페이지의 설정에 어떻게 대응되는지.
- [Python API](api.md) —— `Runtime`, 세 개의 store, `Resilience`의 전체 시그니처.
- [배포](deploy.md) —— 컨테이너에서 실행하기, plugin으로 도메인 능력 배포하기.
- [용어집](glossary.md) —— 이 페이지에서 쓴 모든 단어의 정확한 의미.
