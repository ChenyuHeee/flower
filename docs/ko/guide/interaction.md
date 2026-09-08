# 교체 가능한 인터랙션 레이어

flower의 핵심은 UI의 존재를 모른다. 실행 중에 일어나는 모든 일 — 모델이 말하고, 도구를 호출하고, 컨텍스트가 거의 다 차고, 사람에게 한마디 물어봐야 하는 것 — 은 전부 동일한 데이터 구조 [`Event`](../reference/glossary.md#事件)로 평탄화된다.
**[인터랙션 레이어](../reference/glossary.md#交互层)는 `Event`만 알고, 어떤 SDK 타입도 import 하지 않는다.**
이것이 UI를 바꿔도 핵심을 건드리지 않아도 되는 경계다. 터미널, Web, HTTP 서비스, 완전 자동 무인 운영 — 바뀌는 것은 `Event`의 소비자뿐이고, 나머지는 한 줄도 고칠 필요가 없다.

## 무엇을 해결하는가 {#解决什么问题}

SDK의 메시지 스트림은 **내부 타입**이다. `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage`…… UI가 이것들을 직접 소비하면 두 가지 결과가 따라온다. SDK가 올라가면 프런트엔드도 따라 고쳐야 하고, 메시지마다 모양이 달라서 UI마다 "이게 본문인가 도구 호출인가"를 판단하는 코드를 다시 짜야 한다.

`normalize(message)`는 SDK 메시지 하나를 0개에서 N개의 `Event`로 변환한다
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
대가는 변환 한 번, 얻는 것은 인터랙션 레이어와 SDK 사이에 타입 의존이 없다는 사실이다.

이 경계는 덤으로 그리 자명하지 않은 네 가지도 해결한다. 넷 다 `normalize()` 안에 있다:

1. **[subagent](../reference/glossary.md#subagent)의 발언이 표시된다**(`payload["subagent"]`).
   그러지 않으면 작업을 넘기는 [태스크 브리프](../reference/glossary.md#任务书)와 subagent의 중간 발언이
   [메인 스레드](../reference/glossary.md#主线程) 본문에 섞여 들어가고, 그대로 [워크플로](../reference/glossary.md#流程)를 타고 다음 단계의 prompt를 오염시킨다.
2. **연결이 끊겼을 때의 합성 오류 메시지가 `kind="error"`로 분리된다**. 연결이 끊기면 SDK 쪽에서 `API Error: …`를
   assistant 메시지로 transcript에 써 넣는데, 생김새가 모델이 한 말과 똑같다(`model`이 `"<synthetic>"`).
   여기서 막지 않으면 그대로 `StepResult.text`에 들어가고, 다음 [스텝](../reference/glossary.md#步骤)으로 전달된다.
3. **compact 경계가 명시적으로 보고된다**(`kind="reset"`). 경계 이후 모델이 "기억"하는 것은 요약뿐이고, prompt 캐시도
   여기서 끊긴다 — [long-horizon](../reference/glossary.md#长程) 실행은 반드시 이걸 볼 수 있어야 한다.
4. **컨텍스트 수위가 메시지마다 함께 나온다**(`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). 이것이
   [핸드오프](../reference/glossary.md#换代) 판정 기준의 유일한 출처다.

## 어떻게 쓰는가(최소 코드) {#怎么用最小代码}

인터랙션 레이어는 세 가지를 연결해야 한다. **이벤트 출구**(어디에 렌더링할지), **질문 채널**(누가 답할지), **인터럽트**(어떻게 멈출지).
아래 코드는 셋 다 연결했고, 그대로 실행된다:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event를 당신의 UI로 렌더링한다 —— 바꿔야 하는 건 이것뿐이다."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask"이면서 mail이 아닌 것은 아래 answerer가 처리한다(풀 방식)


async def answerer(ch: HumanChannel) -> None:
    """풀 방식으로 질문을 가져온다. Web / HTTP로 바꿀 때 손대야 할 또 한 곳이 이 코루틴이다."""
    while True:
        ask = await ch.next_ask()           # timeout을 주지 않으면 계속 기다린다
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # 또는 ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime은 workflow가 이미 만들어 둔 워크벤치를 쓴다 —— 따로 하나 더 만들지 말 것
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # SQLite 연결을 닫는다
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

빠뜨리기 쉬운 마무리 두 가지: `rt.close()`는 반드시 `finally`에 두고, `ctx["_failed_at"]`에 값이 있으면 도중에 멈춘 것이니(`on_fail="stop"`) 성공으로 착각하지 말 것.

!!! note "워크벤치는 하나뿐, 따로 만들지 말 것"
    `Runtime(workbench=True)`가 만드는 [워크벤치](../reference/glossary.md#工作台)는
    `<run_dir>/workbench`에 있고, `Workbench(ws)`는 기본이 `<ws>/.flower`다 ——
    둘은 같은 디렉터리가 아니다. 드라이버가 직접 경로를 조립해 `需求.md`를 찾으면
    "브리프는 A 디렉터리에 쓰였는데 주입된 인덱스는 B 디렉터리를 스캔"하는 상황이 생기고, 게다가 오류도 안 난다.
    workflow가 만들어 둔 것을 `Runtime`에 넘기거나(위 코드처럼),
    읽기 전용 탐지 `wake_state()`로 어디 있는지 물어볼 것.

### 세 가지 이벤트 출구 {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. 단일 agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. 워크플로 전체, 각 스텝에 전달
wf = Workflow(steps=[...], channel=ch)                  # 3. 질문 채널을 같은 출구에 연결
```

세 번째 연결은 `Workflow.run` 안에 있다. **`on_event`가 `None`이 아니고, 동시에 `channel.on_event`가 아직
`None`일 때만 자동으로 연결된다.** 직접 연결해 두었다면 덮어쓰지 않는다:

```python
ch = HumanChannel(on_event=my_own_sink)     # 직접 연결하면 Workflow가 건드리지 않는다
```

`on_step(step, result)`는 또 다른 콜백으로, 스텝이 끝날 때마다(**실패 포함**) 한 번 호출되고 완전한
`StepResult`를 받는다. 진행률 표시, 디스크 기록, 알림은 여기에 걸고, 이걸 하려고 `Event` 스트림을 짜맞추지 말 것 — 본문은 핸드오프와 재시도로 여러 조각으로 끊긴다.

### 터미널: 기본으로 딸려 있는 것 {#终端默认的那个}

코드를 안 짜도 하나 있다. `flower "帮我做一个 X"`가 실행하는 것은
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py)이고,
이것은 인터랙션 레이어의 **참조 구현이지 프레임워크의 일부가 아니다**. 통째로 갈아치울 수 있다. 스위치는 [CLI 레퍼런스](../reference/cli.md) 참고.
규모를 있는 그대로 말하자면, `cli.py` 전체는 1264줄, 57KB다 —— 하지만 **바꿔야 하는 건 전체가 아니다**.
실제 교체 지점은 그 안의 `class Render`(`cli.py:489-687`, 197줄)이고, docstring에 이렇게 쓰여 있다.
"Event → 터미널. UI를 바꾼다는 건 이 클래스 하나를 바꾸는 것이다." 나머지 천여 줄은 인터럽트, oracle, 인박스 회신, 시그널 구조 같은 **터미널 고유** 부속이고, Web이나 HTTP로 바꿀 때는 애초에 그대로 옮길 필요가 없다.

그러니 "약 200줄이면 통째로 교체 가능"이라는 말은 성립한다 —— 단, 그게 `cli.py`가 아니라 `Render`를 가리킬 때 얘기다.

터미널 UI를 직접 짠다면, 요점은 표준 입력을 읽는 스레드다:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """계속 표준 입력을 읽는다: 대기 중인 질문이 있으면 답변, 없으면 인박스로. 정지 플래그를 반환한다."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # 폴링해야 정지 플래그에 반응할 수 있다
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # 스레드 간 안전
            else:
                ch.send(raw)                    # 인박스로. 진행 중인 작업을 끊지 않는다

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

세 가지 다 밟아 보고 얻은 것이다:

- **daemon 스레드를 쓰고, `asyncio.to_thread(input, ...)`은 쓰지 않는다.** `input()`은 블로킹 중에 취소가 안 되는데,
  `asyncio.run`은 종료 전에 기본 executor의 스레드를 join한다 — 결과는 일이 다 끝났는데도 엔터를 한 번 더 눌러야 종료되는 것이다.
- **`select`로 폴링하고, 루프 안에서 바로 `input()`을 부르지 않는다.** 마찬가지로 취소가 안 된다. `input()`에 블로킹된 스레드는
  `stop.set()`으로도 다시는 깨울 수 없다.
- **계속 읽지, 질문이 있을 때만 읽지 않는다.** 질문이 있을 때만 읽으면, 몇 시간 일하는 동안 사람이 친 내용이 터미널 버퍼에 남아 있다가
  다음 질문 때 답변으로 먹혀 버린다 — 사람은 질문을 보지도 못했는데 질문이 이미 "답변"된 것이다.

### Web: 큐 + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # 동기, 이벤트 루프가 있는 스레드에서, 블로킹 금지
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # 프런트엔드 오류가 세 시간짜리 작업을 날려선 안 된다
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # 요청 처리 스레드 —— 다른 스레드, 이게 정상 상황이다
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw`는 원본 SDK 객체다(`ask` 이벤트에서는 `Ask`). **JSON 직렬화가 불가능하고, 프런트엔드로 보내지도 말 것** ——
`raw`를 쓰는 순간 프런트엔드를 다시 SDK 타입에 묶는 것이고, 이 레이어는 헛수고가 된다. `kind` / `text` / `tool` / `payload`
네 필드면 충분하다.

### HTTP: 시퀀스 번호 + 폴링 {#http序号--轮询}

롱 커넥션이 없을 때는 이벤트에 번호를 매겨 클라이언트가 가져가게 한다:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # 최근 것만 남긴다. 메모리가 실행 시간을 따라 늘지 않게


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # 지금 누군가의 답을 기다리며 걸려 있는 것
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = 이 질문은 이미 기다리고 있지 않다
```

인지해야 할 경계가 둘 있다. `maxlen`이 차면 가장 오래된 것이 버려지므로, 클라이언트가 아주 오래된 `after`를 들고 오면 전부 조회할 수 없다. 폴링 간격을 이 길이에 맞춰야 한다. 그리고 **`timeout_s`에 반드시 유한한 값을 줘야 한다** —— 아무도 폴링하지 않으면 질문은 스스로 끝나지 않고,
`timeout_s=None`이면 실행 전체가 영원히 그 자리에 걸린다. 기본값 `1800.0`초면 적당하다.

### 완전 자동 무인 운영: 사람이 없다 {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # 이벤트를 전부 버린다
```

커맨드라인 등가 표현은 `flower "帮我做一个 X" --timeout 0`이다.

`timeout_s=0`(음수도 동일)은 완전 자동 모드다. 질문은 **대기 큐에 들어가지 않고 `asked` 이벤트도 발생하지 않으며**, 즉시
`state="timeout"`으로 정산되고, 도구는 다음 고정 문구를 반환한다 ——

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

—— 그래서 실행은 문제없이 계속된다. 질문과 답변은 여전히 `HumanChannel(log_path=...)`에 추가되고(`starter_flow`가 기본으로 연결하는 곳은
`<워크벤치>/notes/问答记录.md`), 사후에 무엇을 물었고 스스로 무엇을 가정했는지 볼 수 있다.

아예 입을 열지 않게 하려면 `max_asks=0`을 쓴다. 질문은 곧바로 거절되고(`state="over_budget"`), 마찬가지로 블로킹되지 않는다.
이것은 **"도구를 빼는 것"이 아니라는 점**에 주의할 것 —— `allowed_tools`는 배타적이지 않고,
[코디네이터](../reference/glossary.md#协调者)에 `channel`을 걸면 `mcp__human__ask`와
`mcp__human__inbox` 두 도구가 함께 주어진다. 목록에 넣든 안 넣든 호출은 된다. 질문을 막을 수 있는 것은 할당량과 타임아웃뿐이다.

!!! warning "무인 운영에서 질문을 영원히 기다리게 하지 말 것"
    `timeout_s=None`은 "영원히 기다림"이다. 보는 사람이 없을 때는 질문 하나로 열 시간짜리 실행이 그 자리에 멈춰 설 수 있고,
    게다가 오류도 안 나고 타임아웃도 안 나고 로그상으로도 구분되지 않는다. 무인 운영에서 올바른 값은 둘뿐이다. `0`(즉시 불발)
    또는 유한한 초 수.

## 실제로 무엇을 하는가 {#它实际做了什么}

### `Event`의 형태 {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15가지 값, 아래 표 참고
    text: str = ""
    tool: str = ""                      # tool_call일 때만 값이 있다
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # 원본 SDK 객체 / Ask. 건드리면 다시 SDK에 묶인다
```

`str(ev)`: `tool_call`은 `[도구명] 요약`, 나머지는 `text`. `text`가 비어 있으면 `<kind>`.

### 15가지 `EventKind` {#15-个-eventkind}

| `kind` | 누가 발생시키나 | 언제 나오나 | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | 모델 본문 | 본문 | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | thinking 블록 | 사고 내용 | 위와 동일 |
| `prompt` | `normalize()` | **입력**: 당신의 prompt, subagent에게 넘기는 태스크 브리프 | 입력 텍스트 | 위와 동일 |
| `tool_call` | `normalize()` | 모델이 도구 호출을 시작 | 요약(`file_path` / `command` / `pattern`, 200자에서 자름) | `id`, `input` + 위와 동일. `tool`은 도구명 |
| `tool_result` | `normalize()` | 도구 반환 | 앞 500자(내용이 문자열이 아니면 빈 값) | `tool_use_id`, `is_error` + 위와 동일 |
| `result` | `normalize()` | SDK 쿼리 한 번이 끝남 | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | 연결이 끊겼을 때의 합성 메시지 | 오류 텍스트 | `synthetic: True` |
| `reset` | `normalize()` | compact 경계 또는 세션 리셋 | `压缩(trigger) 167000 → 42000 tokens`. 세션 리셋일 때는 `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype`(세션 리셋일 때는 빈 값) |
| `system` | `normalize()` | 그 밖의 SDK 시스템 메시지 | subtype | `data` 그대로 전달 |
| `task` | `normalize()` | 태스크 진행 메시지 | **빈 값** | `kind` = SDK의 메시지 클래스명 |
| `unknown` | `normalize()` | 인식하지 못한 메시지 타입 | 클래스명 | — |

!!! note "`task`의 본문은 비어 있다, 그대로 출력하지 말 것"
    `TaskProgressMessage` 같은 것은 SDK의 내부 메시지 타입이다. 예전에는 `normalize()`가 클래스명을 본문으로 내보냈는데,
    화면에 찍히면 순수한 노이즈고, agent의 본문에 섞여서 오류가 난 것처럼 보였다(실측 그러함). 지금은
    **본문 없는** 이벤트로 분류하고 클래스명은 `payload["kind"]`에 넣는다 —— 표시 여부는 인터랙션 레이어가 알아서 정한다
    (`events.py`).
| `ask` | `HumanChannel` | 사람의 답이 필요할 때, 어떤 질문의 결말이 났을 때, 또는 사람이 먼저 한마디 했을 때 | 질문 / 사람이 한 말 | 두 가지 정체, 아래 참고 |
| `retry` | `Runtime` | 재시도 중 / 네트워크를 기다리며 걸려 있음 | 한 줄 설명 | `step`, `attempt` |
| `step` | `Workflow.run` | 스텝 경계 | 스텝 이름 | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | 핸드오프: 임박 / 작성 중 / 완료 | 수위가 포함된 한 줄 설명 | `phase`, `step`, `context`, `window` + 아래 참고 |

**네 가지 kind는 `normalize()`가 만들지 않는다.** `ask`는 `HumanChannel`에서, `retry`와 `handoff`는
`Runtime`에서, `step`은 `Workflow.run`에서 온다. 같은 `EventKind` 안에 둔 것은 의도적이다 ——
**UI는 한 벌의 `Event`만 알면 되고, "사람의 답이 필요함"이나 "스텝 경계"를 위해 별도 경로를 열 필요가 없다.**

UI를 짤 때는 `else` 분기를 하나 남겨 둘 것. `EventKind`에는 새 멤버가 더 추가될 것이고, 기존 UI가 그걸로 죽어선 안 된다.

### `handoff`의 세 가지 phase {#handoff-的三个-phase}

| `phase` | 언제 발생 | `payload`가 추가로 담는 것 |
|---|---|---|
| `near` | 수위가 `warn_at`을 넘음. **세대마다 한 번만** 발생, 화면을 도배하지 않음 | `at`(핸드오프 임계값) |
| `writing` | [핸드오프 문서](../reference/glossary.md#交接书) 작성 시작. 쓰는 데 십수 초 걸리므로, 이걸 안 보내면 화면이 멈춘 것처럼 보인다 | — |
| `done` | 핸드오프 문서 작성 완료, 새 세션으로 교체 | `degraded`(축소 버전인지 여부), `path`(어디에 썼는지, 워크벤치가 없으면 빈 문자열), `sections` |

메커니즘 자체는 [핸드오프](handoff.md) 참고.

### `ask`의 두 가지 정체 {#ask-的两种身份}

`Event("ask")`는 "질문"과 "사람이 먼저 한 말"을 동시에 실어 나른다. **UI는 반드시 `payload["kind"]`를 먼저 봐야 한다**:

| 정체 | 어떻게 구분 | `payload` |
|---|---|---|
| 질문 한 건 | `kind` 키가 없음 | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`. `raw`는 그 `Ask` |
| 사람이 먼저 한 말 | `payload["kind"] == "mail"` | `kind`, `state`(`queued` 들어감 / `delivered` 가져감), `id`, `amended`(어느 파일에 추가되었는지, 설정하지 않았으면 빈 문자열). **`options`와 `remaining`은 없다** |

질문 한 건은 **두 번 이상** 이벤트를 발생시킨다. 질문할 때 한 번(`state="asked"`), 결말이 났을 때 다시 한 번
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). UI는 `payload["id"]`로 같은 항목을
갱신하면 된다.

### 사람에게 묻기: `Ask`와 `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # 위의 다섯 가지 결말 참고
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # 몇 초 기다렸는지, 소수점 한 자리
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel`은 프로세스 내 MCP server 하나와 UI용 메서드 묶음이다. 모델 쪽에서는 도구가 둘만 보인다.
`mcp__human__ask`(질문, 걸려서 기다림)와 `mcp__human__inbox`(인박스 확인, **블로킹하지 않음**, 비어 있으면 즉시
설명 한 줄을 반환). 전체 생성자:

```python
HumanChannel(
    *,                                  # 전부 keyword-only
    on_event=None,                      # 푸시 출구. Workflow는 이것이 None일 때만 자동 연결한다
    max_asks=None,                      # None = 무제한. 0 = 질문 금지. 초과하면 즉시 거절, 블로킹 없음
    timeout_s=1800.0,                   # None = 영원히 기다림. <= 0 = 즉시 불발
    log_path=None,                      # 질문과 답변을 이 파일에 추가. 컨텍스트를 차지하지 않는다
    amend_path=None,                    # 사람이 실행 도중에 한 말을 이 파일에 추가. 보통은 브리프
    over_budget_text=OVER_BUDGET,       # 고정 응답 세 개, 직접 바꿀 수 있다
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path`는 가장 빠뜨리기 쉬운 항목이면서, "사람이 도중에 바꾼 요구가 스텝 경계를 살아서 넘어가는가"를 결정한다.
각 스텝은 새 [세션](../reference/glossary.md#会话)이고 읽기 전용 동결본이다. 실행 도중에 한 말은 그때 그 agent의 컨텍스트에만 들어가고, 다음 스텝(예를 들어 [판정](../reference/glossary.md#判定))은 완전히 새 세션이라
`需求.md`와 `目标.md`를 읽는다. **당신이 한 그 말은 보이지 않는다.** 그래서 여전히 옛 경계로 판정하고, 고쳐 놓은 것을 범위 이탈로 판정해 버린다.
`amend_path`는 각 메시지를 [브리프](../reference/glossary.md#需求确认书)에 **추가**한다 —— 덮어쓰지 않고 추가한다. 원래 요구는 이력이고, 무엇이 바뀌었는지 보이는 편이 안 보이는 편보다 낫다. `starter_flow`가 기본으로 연결하는 곳은
`<워크벤치>/notes/需求.md`다.

실측($0.6767)에서 이것은 예상보다 더 잘 들었다. 사람이 "겸사겸사 총 바이트 수도 보고해 달라"고 하자, 코디네이터가 인박스를 확인하고 이렇게 보고했다 ——
"hand가 이미 `.flower/notes/需求.md`의 실행 중 보충에서 읽어 계산했으니 다시 파견할 필요 없다."
**subagent는 파일에서 읽은 것이지, 누가 전달해 준 것에 기대지 않았다.**

공개 멤버:

| 멤버 | 시그니처 | 의미 |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | 그대로 `AgentSpec.mcp_servers`에 넣는다. 키 이름이 server 이름과 같아야 하므로 여기서 함께 내준다 |
| `ask` | `async (question, options=None) -> Ask` | 걸려서 사람을 기다린다. **`CancelledError` 외에는 절대 예외를 던지지 않는다** —— 아무도 답하지 않는 것도 답의 일종이며, `ask.state`로 구분한다 |
| `pending` | `() -> list[Ask]` | 현재 답을 기다리며 걸려 있는 질문들 |
| `next_ask` | `async (timeout=None) -> Ask \| None` | 풀 방식 UI용. 타임아웃이면 `None` 반환, 취소되면 예외 |
| `answer` | `(ask_id, text) -> bool` | 답변. `False` = 이 질문은 이미 기다리고 있지 않다(타임아웃 / 이미 답변됨) |
| `decline` | `(ask_id, reason="") -> bool` | 건너뛴다. 모델이 스스로 판단하고 가정을 「未知与假设」에 쓰게 한다 |
| `send` | `(text) -> Mail \| None` | 사람이 먼저 한마디 한다, 인박스로. agent를 끊지 않는다. 내부에서 자동으로 `amend()`를 호출한다 |
| `amend` | `(text, *, label="运行中补充") -> bool` | `amend_path`에 추가. 실제로 썼는지 반환(경로 미설정 / 빈 텍스트 / `OSError`는 전부 `False`) |
| `pending_mail` | `() -> list[Mail]` | 아직 가져가지 않은 말들 |
| `remaining` | `-> int` | 몇 번 더 물을 수 있는지. `max_asks=None`일 때는 **`-1`**을 반환하며, 0이 아니다 |
| `transcript` | `() -> str` | 질문·답변 기록의 markdown |
| `asks` / `mail` / `ui_errors` | `list` | 전체 질문 / 사람이 한 말 전체 / UI 콜백이 던진 예외 |

`answer`, `decline`, `send`는 **어느 스레드에서든 호출할 수 있다**. Web 백엔드의 요청 처리 스레드, TUI의 입력 스레드는 모두 다른 스레드에 있다 — 이건 정상 상황이지 예외적인 경우가 아니다. 내부적으로는 `loop.call_soon_threadsafe`를 쓰는데,
`asyncio.Future.set_result`가 스레드 안전하지 않기 때문이다.

푸시와 풀 두 가지 방식 중 **하나를 고른다**:

| | 어떻게 받나 | 적합한 곳 |
|---|---|---|
| **푸시** | `HumanChannel(on_event=…)`, `kind == "ask"`이고 `payload["state"] == "asked"`인 것을 받음 | 이벤트 구동 UI(Web 푸시, TUI 리드로우) |
| **풀** | `await channel.next_ask()` | 독립된 입력 태스크 하나 |

세 가지 "0 / None"의 의미는 각각 다르다. 헷갈리면 무인 운영에서 멈춰 서거나 한마디도 묻지 않게 된다:

| 표기 | 의미 |
|---|---|
| `max_asks=None` | 횟수 무제한(기본) |
| `max_asks=0` | 질문 금지, 즉시 거절 |
| `timeout_s=None` | 영원히 기다림 |
| `timeout_s<=0` | 기다리지 않음, 질문은 즉시 불발 |
| `remaining`이 `-1` 반환 | `max_asks=None`일 때의 값이며, 0이 아니다 |

### 인터럽트: 어느 스레드에서든 멈출 수 있다 {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`, 빈 문자열이면 말없이 끊기만 한다. 성질 세 가지:

- **같은 세션을 이어서 실행한다**(`resume`). 처음부터 다시가 아니다 — 이미 끝낸 작업과 컨텍스트가 그대로 있다. 재사용하는 것은 네트워크 끊김 재시도의 기존 경로이고, "실패 원인"을 "사람이 끊었음"으로, `resume_prompt`를 사람이 한 말로 바꿀 뿐이다.
- **`max_attempts`를 소모하지 않는다.** 그건 장애용 할당량이지 사람용이 아니다.
- **협조적이다.** 메시지 경계에서 끊고, 태스크를 강제 취소하지 않는다. 대가는 다음 메시지까지의 지연(subagent가 돌고 있으면 돌아올 때까지 기다려야 한다)이고, 얻는 것은 중간에 상태가 찢어지지 않는다는 점이다.

대가는 있는 그대로 말한다. 인터럽트는 **진행 중인 subagent의 반제품을 잃게 만든다**(HT001 네트워크 끊김 때 실측했다,
[issue #2](https://github.com/ChenyuHeee/flower/issues/2) 참고). 터미널 참조 구현은 안내문에 이 점을 명시해서
누르기 전에 알 수 있게 했다. 직접 UI를 짤 때도 그렇게 해야 한다.

끊고 싶지는 않고 요구만 하나 더하고 싶다면 인박스(`ch.send(...)`)를 쓴다 — 아무것도 끊지 않고, 지연은 agent의 다음 체크포인트까지다.

### Oracle: 실행을 방해하지 않고 한마디 묻기 {#旁路顾问问一句而不打扰运行}

"지금 어디까지 갔나"를 알고 싶다고 해서 끊을 필요는 없고, 코디네이터에게 물어서도 안 된다. 그 문답은 **메인 스레드 컨텍스트를 영구히 차지하고**
(거기 담기는 것은 결정이지 문답 기록이 아니다), 게다가 코디네이터는 하던 일을 멈춰야 한다. 열 시간짜리 실행에서 김에 세 마디 물으면 이 두 가지 대가를 다 치르게 된다.

[Oracle](../reference/glossary.md#旁路顾问)은 읽기 전용 우회로다. 도구는 `Read` / `Glob` /
`Grep`뿐이고, 워크벤치는 열려 있으며, 기본으로 차단기가 달려 있다. `max_turns=12`, `max_budget_usd=0.5`. 터미널에서는 `?`로 시작하는 한 줄로
트리거하고, 두 가지를 근거로 답한다. 최근 이벤트 윈도(고정 60건), 그리고 워크벤치 안의 브리프, 목표, 노트, 산출물.
독립된 `Runtime`(`<run_dir>/aside`)을 쓰므로 비용과 세션 [계보](../reference/glossary.md#血缘)는
**메인 manifest에 섞이지 않는다** — 그 매니페스트가 기록하는 것은 "이번 실행이 어떤 스텝을 밟았는가"이고, 지나가며 한마디 묻는 것은 스텝이 아니다.

실측으로 두 번 질문에 합계 $0.5190, 메인 실행의 manifest는 1바이트도 늘지 않았다.

### 두 가지 엄격한 규칙 {#两条硬规矩}

!!! warning "on_event은 블로킹해서도, 예외를 밖으로 내보내서도 안 된다"
    **첫째, `on_event`은 동기 함수이고, 이벤트 루프가 있는 스레드에서 호출된다.** 그래서
    `asyncio.Queue.put_nowait()`는 안전하지만 `await`는 안 된다(코루틴이 아니니까). **이걸 블로킹하면 실행 전체가 블로킹된다.**
    느린 일이 필요하면 큐에 던지고 다른 태스크가 처리하게 한다.

    **둘째, `on_event` 안에서 예외를 던지면 실행 자체가 상한다.** 본문 계열 이벤트는 `Runtime._attempt`의 `try` 블록 안에서
    발생하므로 예외가 `result.error`로 기록된다 —— 그 스텝은 실패로 판정된다. `retry` 이벤트는 그 바깥에서 발생하므로 예외가 그대로
    `Runtime.run` 밖으로 튀어 나간다. 프런트엔드가 세 시간짜리 작업을 날려선 안 되니, **직접 try로 감쌀 것.**

    예외: `HumanChannel`이 스스로 발생시키는 `ask` 이벤트는 이미 감싸져 있고, 예외는 `channel.ui_errors`에 수집되며
    실행을 중단시키지 않는다.

## 언제 쓰지 말아야 하는가 {#什么时候不该用它}

### 인터랙션 레이어에서 하면 안 되는 일 {#交互层里不该做的事}

| 하면 안 되는 것 | 왜 | 어떻게 해야 하나 |
|---|---|---|
| `from claude_agent_sdk import ...` | 인터랙션 레이어가 SDK 타입에 의존하는 순간, SDK가 올라가면 프런트엔드도 따라 고쳐야 하고 이 레이어는 헛수고가 된다 | `Event`의 `kind` / `text` / `tool` / `payload`만 쓴다 |
| `ev.raw`를 읽기 | 위와 같고, 게다가 JSON 직렬화가 불가능하다 | 부족한 세부 정보는 `normalize()`의 `payload`에 채워 넣고, 경계를 우회하지 않는다 |
| `on_event` 안에서 `await`, 네트워크 요청, 느린 디스크 쓰기 | 동기 함수이고 이벤트 루프 스레드에서 호출되므로, 블로킹하면 실행 전체가 블로킹된다 | `put_nowait()`로 큐에 던지고, 별도 태스크가 소비 |
| `on_event`이 예외를 밖으로 던지게 두기 | 본문 이벤트의 예외는 `result.error`가 되고, 그 스텝은 실패로 판정된다 | 콜백 본문 전체를 `try`로 감싼다 |
| `disallowed_tools`로 질문을 끄기 | 그것은 **세션 단위**라, subagent의 동명 도구까지 함께 금지한다(실측 오류 원문: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` 또는 `timeout_s=0` |
| `allowed_tools`에서 `mcp__human__ask`를 빼서 질문 금지로 삼기 | `allowed_tools`는 배타적이지 않다. 승인 면제 목록이지 화이트리스트가 아니다. `channel`을 걸면 두 도구가 함께 주어진다 | 위와 동일 |
| 직접 경로를 조립해 `需求.md` / `目标.md`를 찾기 | 워크벤치 위치가 두 가지라, 틀려도 오류가 안 나고 조용히 무효가 된다 | `wake_state()` 또는 `wf.workbench` |
| `Event` 스트림으로 진행률과 결과를 짜맞추기 | 본문은 핸드오프와 재시도로 여러 조각으로 끊긴다 | `on_step(step, result)`로 완전한 `StepResult`를 받는다 |
| 무인 운영에서 `timeout_s=None` 쓰기 | 답할 사람이 없어 실행이 영원히 걸리고, 오류도 타임아웃도 안 난다 | `0`, 또는 유한한 초 수 |

### 아예 바꿀 필요가 없는 경우 {#什么时候根本不用换}

- **색만 바꾸고 한 줄 더 찍거나 덜 찍고 싶을 뿐** —— 렌더링 함수만 고치면 된다. 터미널 참조 구현의 인터럽트, oracle,
  인박스 회신, SIGHUP / SIGTERM 구조, 종료 전 우회로 마무리 대기를 다시 짜는 비용은 작지 않다.
- **한 스텝만 돌리고 인터랙션은 필요 없을 뿐** —— `flower once`를 쓴다. 그것은 인터랙션 구동 경로를 타지 않으므로, 애초에 Ctrl+C 인터럽트,
  표준 입력 응답 스레드, oracle, 시그널 구조가 없다.
- **바꾸고 싶은 게 사실 워크플로지 UI가 아닌 경우** —— [워크플로 설계](workflow.md) 참고. 인터랙션 레이어는 누가 볼지, 누가 답할지만 정한다.
  몇 스텝을 돌릴지, 어떻게 판정할지, 언제 조기 종료할지를 정하는 것은 `Workflow`다.
- **바꾸고 싶은 게 세션 스토어, 모델, 또는 예산인 경우** —— 그 셋은 이 경계 위에 있지 않다.
  [Python API 레퍼런스](../reference/api.md) 참고.
