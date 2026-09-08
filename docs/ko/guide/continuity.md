# 이어붙이기

같은 디렉터리에서 `flower`를 한 번 더 돌리면, 지난번 그 대화를 이어서 말한다 — 프로세스가 kill 되든,
터미널이 죽든, 머신이 재부팅되든 똑같다. session이라는 단어를 알 필요도, id를 기억할 필요도 없다.
이 페이지는 그게 무엇으로 성립하는지, 언제 조용히 실패하는지, 그리고 일부러 이어붙이지 않는 방법을 다룬다.

!!! note "이어붙이기는 handoff가 아니다"
    [이어붙이기](../reference/glossary.md#接续)는 **프로세스를 가로지른다**: 다음 프로세스가 지난 [실행](../reference/glossary.md#运行)을 이어받는다.
    [handoff](../reference/glossary.md#换代)는 **한 번의 실행 내부**의 일이다: 컨텍스트가 거의 차면 현재 [세션](../reference/glossary.md#会话)이
    [handoff 문서](../reference/glossary.md#交接书)를 한 부 쓰고, 새 세션이 이어받는다 — [handoff](handoff.md)를 보라.

    둘은 자동으로 맞물리며 별도 배선이 필요 없다: [lineage](../reference/glossary.md#血缘)가 기록하는 것은 언제나 그 스텝에서
    **마지막으로** 이어받은 세션이므로, 다음 wake는 곧 그 후임자를 이어받는다.

## 어떤 문제를 푸는가 {#解决什么问题}

디스크에는 사실 전부 다 있다. `runs/sessions.db`에는 모든 과거 세션의 **완전한** transcript가 있고,
`需求.md` / `目标.md`는 동결본이며, 코드는 워크스페이스에 있다.

**잃어버리는 건 매핑 한 줄뿐이다** — "어떤 스텝이 어떤 session을 썼는가". 예전에는 그게 메모리의 `ctx["_sessions"]`
안에만 살아 있어서, 프로세스가 끝나면 사라졌다. 그래서 새 프로세스가 뜨면 [코디네이터](../reference/glossary.md#协调者)는
기억을 잃은 신입이다: 누구를 파견했는지, 어떤 막다른 길을 시도했는지, 왜 어떤 방안을 기각했는지 전부 처음부터 다시 한다.

[HT002](../cases/ht002.md)에서는 컴파일 flag를 시험하느라 한 시간을 돌았다. 프로세스가 바뀌면 그 한 시간이 헛걸음이 된다.

## 어떻게 쓰나(최소 코드) {#怎么用最小代码}

커맨드라인에서는 아무 설정도 필요 없다. `flower` 경로는 이어붙이기가 기본으로 켜져 있다:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # 처음
# …다 돌았거나, Ctrl-C로 나갔거나, 머신이 재부팅됐거나

cd ~/proj && flower "顺便支持代码块高亮"          # 지난번 그 대화를 이어서
cd ~/proj && flower                              # 아무 말 안 함 = 계속 하기
cd ~/proj && flower --new "另一件事"              # 이번엔 이어붙이지 말 것
```

직접 [워크플로](../reference/glossary.md#流程)를 쓸 때도 이어붙이기는 기본으로 켜져 있다 — `Workflow.continuous`의
기본값이 `True`다:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous 기본값 True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # 몇 번째 wake인지, 첫 실행은 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

같은 디렉터리에서 이 코드를 두 번째로 실행하면 `ctx["_woke"]`는 `2`이고, `ctx["_sessions"]["取词"]`는 첫 번째와
**같은 id**다 — `取词` 스텝은 지난번 그 세션을 이어서 돌린 것이지 새로 연 것이 아니다.

!!! tip "이 디렉터리가 이어붙는지만 알고 싶다면"
    `wake_state()`는 읽기 전용 탐침이며 **1바이트도 쓰지 않는다**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    `{"waking", "brief", "goal", "checks", "woke", "steps"}`를 돌려준다. `waking` = brief가 존재하고 네 절이 다 갖춰짐;
    `checks` = 판정 목록 몇 개; `woke` = 지금까지 몇 번 wake 했는지; `steps` = 스텝 이름에서 session_id로의 매핑.
    커맨드라인은 이걸로 프롬프트에서 "무엇을 할까"를 물을지 "계속 할까"를 물을지 결정한다.

## 실제로 무엇을 하는가 {#它实际做了什么}

### 디스크에 남는 세 개의 파일 {#落在磁盘上的三个文件}

`run_dir`의 기본값은 `./runs`이고, **현재 작업 디렉터리 기준이지 workspace 기준이 아니다**.

| 경로 | 무엇이 들어가나 |
|---|---|
| `runs/lineage.json` | lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. 이어붙이기는 전적으로 이것에 달려 있다 |
| `runs/sessions.db` | SQLite, transcript 전량. 테이블은 `entries` / `meta` / `summaries`, key는 `project_key/session_id[/subpath]` — subagent의 transcript는 subpath로 분리 저장 |
| `runs/manifest.json` | JSON 배열, **프로세스를 가로질러 누적**되는 run manifest. 스텝마다 한 줄이며, 사후에 session_id를 찾을 유일한 곳 |

lineage 파일은 이렇게 생겼다:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

`manifest.json`의 각 줄은 `StepResult`의 전체 필드다 — `step`、`session_id`、`ok`、`cost_usd`、
`num_turns`、`text`、`error`、`started_at`、`ended_at`、`attempts`、`errors[]`、`resumed`、
`retired[]`、`context` — 여기에 손으로 채워 넣은 `duration_s`(`@property`라서 `asdict()`가 못 잡는다)와
`run`(프로세스 표식, `YYYYmmdd-HHMMSS-<6자리 hex>`)이 더해진다.

스텝 이름은 그 안에서 네 가지 형태를 가지며, 그 스텝이 어떻게 끝났는지 한눈에 보인다: `<步骤名>`(첫 시도)、
`<步骤名>#retry<N>`(일반 재시도)、`<步骤名>#round<N>`(판정 통과 실패, 되돌려보내 계속 진행)、
`<步骤名>·判定#<N>`([판정자](../reference/glossary.md#判定者) 라운드).

디스크 쓰기는 **덮어쓰지 않고 덧붙인다**: 기록할 때마다 파일을 다시 읽어 `run` 필드로 중복 제거한다 —
이 프로세스에 속한 줄은 최신으로 바꾸고, 남의 줄은 그대로 둔다. 그래서 같은 디렉터리에서 여러 flower를 병렬로 돌려도 안전하다.

### `continuous=True`는 `resume_from`의 의미를 바꾼다 {#continuoustrue-改变了-resume_from-的语义}

가장 놓치기 쉬운 항목이다: `Workflow.continuous`의 기본값이 `True`이므로, `resume_from=None`은
**"완전히 새 세션"을 뜻하지 않는다**.

| 표기 | 같은 실행 내부 | 프로세스를 가로질러(`continuous=True`) |
|---|---|---|
| `resume_from=None`(기본) | 새 세션, prompt로 넘긴 컨텍스트에만 의존 | **lineage에서 같은 이름의 스텝이 쓴 session을 이어서 실행** |
| `resume_from="上一步名"` | 같은 세션을 이어서, 컨텍스트 전부 유지 | 왼쪽과 같음 |
| `resume_from=…, fork=True` | 분기, 원래 세션을 오염시키지 않음 | 왼쪽과 같음 |

매 프로세스마다 깨끗한 새 세션을 원한다면 명시적으로 `Workflow(..., continuous=False)`라고 써야 한다.

lineage를 적재할 때 검증이 하나 더 있다: 읽어 온 각 `(스텝 이름, session_id)`는 먼저 `runtime.has_session(sid)`로
아직 `sessions.db` 안에 있는지 확인하고, 살아 있을 때만 쓴다. 이유는 lineage 파일이 `sessions.db`보다 오래 살아남을 수 있는데,
존재하지 않는 session을 resume하면 서브프로세스가 뜬 다음에야 터지기 때문이다.

!!! warning "스텝 이름은 프로세스를 가로질러 안정적인 키다"
    lineage는 `Step.name`으로 색인된다. **스텝 이름을 바꾸면 lineage가 끊긴 것과 같다** — 에러는 나지 않고, 다음 실행이 그냥 새 세션이 된다.
    접미사가 붙은 이름(`#retry`、`#round`、`·判定#`)은 lineage에 들어가지 않으며, `Lineage.remember`는 언제나 원래 이름을 쓴다.

### 두 가지 불변식 {#两条不变式}

**하나, session_id를 얻는 즉시 디스크에 쓴다. 스텝이 끝나기를 기다리지 않는다.**

프로세스가 강제로 죽는 상황이 바로 막아야 할 시나리오다. 실제로 당한 적이 있다: 2026-09-07 Terminal.app이 두 번 죽었고,
커널이 SIGHUP을 보냈는데 SIGHUP의 기본 동작은 즉시 종료라서 `finally`가 한 줄도 돌지 않았다. 당시 lineage는 **스텝 경계**에서
쓰고 있었기 때문에, 첫 스텝 안에서 죽은 그 실행은 `steps`가 비어 있었고, 사람은 이미 답한 질문을 다시 답해야 했다(issue #6 참조).

지금은 `Runtime.on_session`이 id를 얻는 그 순간 디스크에 쓴다 — 실제로 가장 이른 시점은 첫 assistant 메시지이며,
init 시스템 메시지는 Python SDK에서 `session_id`를 달고 오지 않는다. 쓸 때는 먼저 `.tmp`에 쓰고 원자적으로 교체하므로
도중에 죽어도 반쪽짜리 파일이 남지 않는다. 기록 실패(`OSError`)는 조용히 삼키고, 이번 실행을 같이 죽이지 않는다.

이 훅은 **`runtime.run` 이 한 줄만 덮는다**. gate 앞에서는 `try/finally`로 떼어 낸다. 판정자는 같은 `Runtime`을 쓰므로,
훅이 그대로 걸려 있으면 판정자의 session이 작업 스텝의 lineage에 기록되어 버린다.

**둘, 맞지 않으면 없는 셈 치고, 에러를 내지 않는다.**

맞지 않는 경우는 세 가지다: 워크스페이스 경로가 바뀜(디렉터리를 복사해 옮김 — [HT001](../cases/ht001.md)이 바로 컨테이너에서 꺼내 온 경우)、
session이 이미 DB에 없음(`sessions.db`를 지운 적 있음)、lineage 파일이 깨짐. 어느 쪽이든 조용히 "처음부터 시작"으로 물러난다.

`workspace` 필드는 가드다: SDK의 `project_key`는 워크스페이스 경로에서 유도되는데(`/`、`_`、`.`를 전부 `-`로 치환),
디렉터리를 복사해 옮기고 나면 옛 session_id는 새 위치에서 아예 조회되지 않는다. 그래서 경로가 맞지 않으면 없는 셈 친다.

**이어붙이기는 있으면 좋은 것이고, 그게 실패한다고 사람이 일하는 걸 막아서는 안 된다.**

### 프로세스가 죽는 것, 그리고 머신 재부팅 {#进程被杀和机器重启}

두 경우의 결과는 같다 — 둘 다 이어붙는다 — 그러나 과정은 다르다:

| 상황 | 무슨 일이 일어나나 | 다음 실행 |
|---|---|---|
| `Ctrl-C` 한 번 | 협조적 중단, **메시지 경계**에서 깨끗하게 끊긴다. 한마디 덧붙일 수도 있고, 같은 프로세스 안에서 같은 세션을 resume해 이어서 돈다. 중단은 실패한 시도로 치지 않고 재시도 한도를 먹지 않는다 | 이어붙이기와 무관 |
| `Ctrl-C` 두 번 | `KeyboardInterrupt`를 바로 던지고 종료. 마무리는 스토리지를 닫는 데까지만 하고, **비행 중이던 스텝은 `manifest.json`에 들어가지 않는다** | lineage는 이미 기록되어 있으므로 이어붙는다 |
| `SIGTERM` / `SIGHUP` | 핸들러가 먼저 `rescue()`를 호출해 비행 중이던 스텝도 `manifest.json`에 기록하고(`error="killed-by-signal"` 표시), 그 다음 기본 동작으로 복원해 실제로 종료 | 위와 같고, 이어붙는다 |
| `SIGKILL`、정전、머신 재부팅 | 마무리가 전혀 없음 | 그래도 이어붙는다 — 세 파일 모두 디스크에 있고, lineage는 id를 얻는 그 순간 쓰였다 |

전제는 하나뿐이다: **같은 `workspace`와 같은 `run_dir`**. `run_dir`은 현재 작업 디렉터리 기준이므로,
다른 디렉터리에서 `flower`를 치면 다른 `runs/`를 찾게 되고, 이어붙지 않는다.

### 판정자는 언제나 새 세션이다 {#判定者永远是新会话}

이건 **구조적으로 보장**되는 것이지, 기억해서 지키는 게 아니다.

판정자는 `Step`이 아니다 — `with_goal`의 gate 안에서 `rt.run()`으로 직접 파견된다
([목표 가드](goal.md) 참조). lineage 경로를 절대 거치지 않는다. 그래서 매 라운드, 매 wake마다 완전히 새로운 한 쌍의 눈이다.

그게 판정자의 가치 전부다: **워커가 몇 번 시도했는지, 얼마나 고생했는지 모르므로, 대신 변명을 찾아 주지 않는다.**
판정자까지 이어붙이면 목표 가드는 자기 감사로 퇴화한다.

`tests/lineage_offline.py` 4절이 이 항목을 못 박아 두었다.

### wake 때 한 말은 세 군데에 떨어져야 한다 {#唤醒时说的那句话要落到三个地方}

이미 써 본 디렉터리에서의 `flower "顺便支持代码块高亮"`는 **새 작업이 아니라, 한마디 더 한 것**이다.
동시에 세 가지 일을 한다 — 하나만 빠져도 조용히 실패한다:

| 어디로 가나 | 빠지면 어떻게 되나 |
|---|---|
| `需求.md`에 덧붙임(`## 唤醒时追加`) | 스텝 경계를 넘기지 못한다. 다음 스텝은 새 session이고 동결본만 읽는다 |
| 작업 스텝의 prompt로 사용 | 코디네이터가 아예 받지 못한다 |
| **`目标.md` 재유도를 트리거** | 판정자가 읽는 건 여전히 옛 목록이고, **새로 추가된 일은 했든 안 했든 판정에 아예 들어가지 않는다** |

세 번째가 가장 놓치기 쉽다. 판정자는 동결된 `目标.md`만 읽으므로 도중에 추가한 것은 보이지 않는다 — 재유도하지 않으면
옛 목록대로 "달성"으로 판정하고, 정작 원했던 그 일은 검증조차 되지 않는다. 대가는 덧붙일 때마다 목표 설정을 한 번 더 도는 것이다
([HT002](../cases/ht002.md) 실측 $0.41 / 3분).

**아무 말 없이 wake**(그냥 엔터)하면 덧붙이지도, 재유도하지도 않으므로 한 푼도 더 들지 않는다.

### 첫 스텝(`确认需求`) 안에서 죽어도 이어붙는다 {#崩在第一步确认需求之内也能接上}

`clarify_step`에는 `resume_prompt`(상수 `CLARIFY_RESUME`)가 붙어 있다: 확인 도중에 죽고 다시 시작하면
[확인자](../reference/glossary.md#确认者)에게 "방금 끝내지 못한 요구 확인을 이어서 계속하라 — 처음부터 다시 하는 게 아니다"라고 말하지,
원래 요청을 새 작업처럼 다시 보내지 않는다. 위의 "session_id를 얻는 즉시 디스크에 쓴다"와 맞물려,
첫 스텝에서 죽어 `需求.md`가 아직 동결되지 않은 경우도 이제 이어붙으며 다시 답할 필요가 없다.

반대로, 이미 동결된 선행 스텝은 **스텝 통째로 건너뛴다**: `需求.md`의 네 절이 다 갖춰져 있으면 `确认需求`를 건너뛰고
(내용은 여전히 ctx로 주입된다), `目标.md`가 갖춰져 있으면 `设定目标`를 건너뛴다.

### 이어붙일 때 보내는 말은 같은 말이 아니다 {#接续时发的不是同一句话}

`Step.resume_prompt`가 이걸 담당한다. 상대의 컨텍스트에는 brief、목표、지난번 어디까지 했는지가 **이미 있다**.
"이 요구대로 하라: <brief 전문>"을 그대로 다시 보내는 건 순수한 잡음이고, 더 나쁘게는
"요구가 바뀌었으니 다시 보라"로 읽힌다.

`resume_prompt`를 주지 않으면 `prompt`를 그대로 쓴다 — 어떤 스텝은 원래 전문을 다시 보내야 한다
(`设定目标`가 목록을 재유도할 때 필요한 게 바로 그 brief 전문이다).

### wake 때 한 줄 먼저 보고한다 {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

보고하지 않으면 "이게 대체 기억하고 있는가"를 전혀 감지할 수 없는데, 그게 바로 이 층의 가치 전부다. 배너에서
`需求已确认`은 항상 나오고, `目标 N 条`는 판정 목록이 비어 있지 않을 때만, `干活上下文 X`는 `sessions.db`에서
그 세션의 마지막 라운드 컨텍스트 규모를 조회할 수 있어야 나온다.

**컨텍스트 숫자는 일부러 내놓은 것이다** — 이유는 아래 "대가" 절에 있다.

### 회복력: 네트워크가 끊기면 매달려 기다리고, 에러는 이어붙인 뒤의 컨텍스트에 들어가지 않는다 {#韧性断网时挂着等而且错误不进接续后的上下文}

[회복력](../reference/glossary.md#韧性)과 이어붙이기는 한 세트다: 한 번에 몇 시간을 도는데 네트워크는 반드시 한 번 끊기고,
기본 동작이 아주 나쁘다 — 끊기는 그 순간 harness가 transcript에 **합성 assistant 메시지**를 밀어 넣는다
(`isApiErrorMessage=true`、`model="<synthetic>"`), 본문은 "API Error: Can't reach the API server …"다.
이 메시지가 세션의 잎이 되고, 이후 resume하면 "모델이 직전에 한 말"로 다시 먹여져서, 모델은 자기가 네트워크 장애를 논의 중이라고 여긴다.

`Resilience`는 세 가지를 한다:

**하나, 탐침은 DNS + TCP만 한다.** `reachable(host, port, timeout=5.0)`은 `getaddrinfo`와 TCP 핸드셰이크 한 번만 돌린다.
**HTTP를 보내지 않고, 자격 증명을 싣지 않으며, 돈이 들지 않는다.** 어떤 예외든 도달 불가로 친다. 어느 주소를 탐침할지는
`endpoint()`가 정하고, 그건 `ANTHROPIC_BASE_URL`을 따라간다. 기본은 `https://api.anthropic.com`, 포트 기본은 `443`(http는 `80`).
**자체 게이트웨이를 쓴다면 반드시 게이트웨이를 탐침해야 한다** — `api.anthropic.com`이 통한다고 게이트웨이가 통한다는 뜻은 아니다.

**둘, 기다려야 할 것과 멈춰야 할 것을 구분한다.** `classify(text)`는 `"transient"` / `"fatal"` / `"unknown"`을 돌려주며,
**fatal을 먼저 판정하고 그다음 transient를 본다** — 401 같은 텍스트에는 "connection"이라는 단어가 자주 섞이므로, 순서를 뒤집으면 하염없이 기다리게 된다.
기본값: `max_attempts=6`(첫 시도 포함)、`base_delay=4.0`、`max_delay=120.0`、`probe_timeout=5.0`、
`probe_interval=15.0`、`max_offline_wait=3600.0`(1시간)、`retry_unknown=True`.
백오프는 `min(base_delay * 2**(attempt-1), max_delay)`에 ±25% 지터를 곱한다.

session_id를 이미 받았다면 **처음부터 다시 하지 않고 resume해서 이어 돈다**. 앞서 쓴 비용이 헛되지 않는다. 이어 돌 때 보내는 건
`Resilience.resume_prompt`다: "직전 라운드가 도중에 중단되어 끝나지 않았다. 워크벤치에 이미 기록된 것을 확인하고,
중단된 지점부터 이어서 하라. 처음부터 다시 하지 말 것." 이 프롬프트는 **의도적으로 어떤 에러 상세도 담지 않는다** —
모델은 "중단됐다, 이어서 하라"만 알면 되고, ENOTFOUND인지 503인지는 알 필요가 없다.

**셋, 재시도 폭풍이 만들어 낸 에러는 resume 이후의 컨텍스트에 들어가지 않는다.** 이건 [prune](../reference/glossary.md#剪除)이 하는 일이다.
`Runtime`의 세션 스토어는 `PruningSessionStore`로 고정되어 있고, `load()` 시점에 세 가지를 한다:

- 합성 API 에러 메시지를 걷어낸다. **SQLite에는 그대로 남는다**, 다시 먹이지 않을 뿐이다
- 오래된 거부된 호출을 걷어내고, 최근 `keep_denials=1`개만 남긴다
- 중단으로 남은 `tool_result`를 중립적 설명 "[직전 라운드가 여기서 중단되어 이 도구 결과는 생성되지 않았다]"로 바꾼다. 본문만 바꾸고 항목은 걷어내지 않는다

0개가 아니라 1개를 남기는 데는 이유가 있다: 거부된 호출은 실행된 적이 없으므로 결과에 정보가 없는데도 자리를 적지 않게 차지하고
(실측 한 건이 273자 = 거부 문구 93자 + **거부된 명령 원문 180자**), 게다가 **오도한다** —
실측에서 코디네이터는 "Bash를 직접 쓰지 말 것" 몇 건을 읽고 나자, 허용된 `git status`조차 시도하지 않게 되어 학습된 무기력을 익혔다.
그러나 가장 최근 한 건은 남겨 두면 쓸모가 있다: 모델이 같은 라운드에서 차단된 같은 명령을 반복 재시도하는 걸 막는다.

걷어내기에는 구조적 레드라인이 하나 있다: transcript는 `parentUuid` 단일 체인이므로, 한 건을 걷어내면 그 자식을 가장 가까운 살아 있는 조상에 이어 붙여야 한다.
그러지 않으면 체인이 거기서 끊기고 앞의 이력이 전부 사라진다.

[HT001](../cases/ht001.md)에서 실제로 한 번 부딪혔다: 단선 타임라인 01:52:40 → 01:55:41, `manifest.json`의 그 스텝은
`attempts=2` / `resumed=True` / `ok=True`이고, 이어 돈 뒤 8시간 넘게 더 돌아 완료했다.

마지막 한 가지는 오해하기 쉽다: **`Runtime(trim=False)`는 "아무것도 치우지 않는다"는 뜻이 아니다.** `trim`의 기본값은 원래 `False`지만,
그건 **큰 도구 결과 [trim](../reference/glossary.md#裁剪)** 층만 끄는 것이다. 단선 잔해 걷어내기, 거부된 호출 걷어내기,
중단 잔여물 중립화, [일회성 명령](../reference/glossary.md#一次性命令) 결과 만료 표시 — 이 네 가지는 그대로 한다
(`ephemeral` 기본 `True`, `keep_denials` 기본 `1`).

### 대가: 컨텍스트는 계속 자라고, 끝이 없다 {#代价上下文会一直涨而且没有尽头}

이건 이어붙이기의 고유한 대가이지 버그가 아니다.

[HT001](../cases/ht001.md)의 `干活` 스텝은 10.44시간을 연속으로 돌았고, [메인 스레드](../reference/glossary.md#主线程) 컨텍스트는
1라운드 **28.7K**、20라운드 **35.2K**、35라운드 **108.6K**、50라운드 **158.2K**、70라운드 **185.9K**로
단조 증가했으며 기울기는 약 **2.2K/라운드**였다. 전 구간 compact 없이, 1M 윈도의 **18.6%**를 썼다. 이 기울기로 외삽하면
약 **440라운드**에서 벽에 부딪힌다 — 현재 형태에서 "long-horizon"의 상한은 그 실행의 약 **6배**다. 영구적 이어붙이기는 언젠가 윈도에 부딪힌다는 뜻이다.

두 층의 메커니즘이 이걸 관리한다:

1. **trim**(`flower --no-trim`으로 끌 수 있고, `flower` 경로는 기본으로 켬) — resume 때 오래된 큰 도구 결과를
   파일 포인터로 바꾼다. 내용은 사라지지 않고, 상주하지 않을 뿐이다
2. **[handoff](handoff.md)** — 임계값에 닿으면 handoff 문서를 한 부 쓰고 새 세션으로 교체한다. **[compact](../reference/glossary.md#压缩)가 아니다**:
   문서는 읽을 수 있고 고칠 수 있으며, 무엇을 잃었는지 눈에 보인다. 그래서 컨텍스트는 벽까지 계속 오르는 대신 주기적으로 내려간다

**그래서 wake 라인은 반드시 컨텍스트 숫자를 보고해야 한다**: 사람이 볼 수 있어야, 벽에 부딪히기 전에 스스로 다시 시작할 기회가 생긴다.

덧붙여: `--rounds`(작업 총 라운드 수)는 **wake마다 리셋된다**. 의도적이다 — 새 wake는 새 의도이므로,
지난번에 쓴 라운드 수를 물려받아서는 안 된다.

### 하나를 다시 시작하기 {#重开一件事}

```bash
flower --new "另一件事"
```

또는 wake 프롬프트에서 바로 `/new`를 친다:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**아카이브하지, 지우지 않는다.** `lineage.json`、`需求.md`、`目标.md`를 함께 `notes/archive/<YYYYmmdd-HHMMSS>/`로 **옮기고**,
lineage의 `steps`와 `woke`를 동시에 0으로 만든다. 세 가지는 같은 이력의 세 면이므로, 일부만 거두면 "목표는 남았는데 대화는 사라진"
어중간한 상태가 남는다.

`sessions.db`는 건드리지 않는다 — 그건 아카이브이고, 그 안의 transcript는 전부 여전히 조회할 수 있다.

코드로는 `Lineage.archive(into, extra=[...])`에 해당한다.

## 언제 쓰면 안 되나 {#什么时候不该用它}

- **매번 깨끗한 출발점이 필요한 경우.** 같은 워크플로를 배치로 돌리기, 대조 평가하기, 남에게 버그를 재현해 주기 —
  이런 건 지난번 컨텍스트를 들고 가면 안 된다. `Workflow(..., continuous=False)`를 쓰거나, 매번 다른 `run_dir`을 쓰라.
- **디렉터리가 옮겨지거나 복사되거나, `run_dir`이 영속적이지 않은 경우.** 컨테이너 안에서 돌리는데 `runs/`가 컨테이너 내부 파일시스템에 떨어지거나,
  워크스페이스를 다른 머신으로 rsync 하는 경우 — 이어붙이기는 **조용히 실패한다**(경로 가드가 맞지 않는 lineage를 거부한다).
  이걸 보장으로 여기지 말라.
- **이번이 새 의도인데 컨텍스트가 이미 큰 경우.** 이어붙이면 무관한 이력까지 짊어지고, 매 라운드 그것에 대해 토큰을 낸다.
  참느니 `--new`로 아카이브하고 다시 시작하는 편이 낫다.
- **일회성 단일 agent.** `flower once`는 `Workflow`를 타지 않으므로 lineage가 없다. 이어 돌리려면 직접 `--resume <session_id>`를 줘야 한다.
- **이어붙이기를 백업으로 여기는 것.** 그것은 "어떤 스텝이 어떤 session을 썼는가"만 기억한다. 코드、산출물、결정은 워크스페이스와
  [워크벤치](../reference/glossary.md#工作台)에 떨어져야 하고, transcript에서 파내기를 기대해서는 안 된다.

## 다음에 읽을 것 {#相关}

- [handoff](handoff.md) — 한 번의 실행 내부에서 컨텍스트가 찼을 때 어떻게 하나. 이 페이지와 같은 일의 두 방향이다
- [목표 가드](goal.md) — 판정자가 왜 이어붙이지 않는가
- [컨텍스트 경제학](context.md) — trim、prune、spill이 각각 무엇을 담당하나
- [Python API](../reference/api.md) — `Lineage`、`Workflow.continuous`、`Step.resume_prompt`、`wake_state`
- [커맨드라인](../reference/cli.md) — `--new`、`--no-trim`、`--rounds`、`-r/--run-dir`
- 소스: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
