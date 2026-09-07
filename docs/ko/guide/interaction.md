# 인터랙션 레이어 교체

flower의 코어는 UI의 존재를 모른다. 실행 중에 일어나는 모든 일 — 모델이 말하고, 도구를 호출하고,
컨텍스트가 거의 차고, 사람에게 한마디 물어야 하고 — 은 전부 같은 데이터 구조
[`Event`](../reference/glossary.md#事件)로 평탄화된다.
**[인터랙션 레이어](../reference/glossary.md#交互层)는 `Event`만 알고, 어떤 SDK 타입도 import하지 않는다.**
UI를 바꿔도 코어를 건드리지 않게 해주는 경계가 이것이다. 터미널, 웹, HTTP 서비스, 완전 자동 무인 실행 —
바뀌는 것은 `Event`의 소비자뿐이고, 나머지는 한 줄도 고칠 필요가 없다.

## 무엇을 해결하는가

SDK의 메시지 스트림은 **내부 타입**이다. `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`,
`ResultMessage`, `SystemMessage`…… UI가 이것들을 직접 소비하면 결과는 두 가지다. SDK가 올라가면
프런트엔드도 따라 고쳐야 하고, 메시지마다 모양이 달라서 "이건 본문인가 도구 호출인가"를 판별하는
코드를 UI마다 다시 써야 한다.

`normalize(message)`는 SDK 메시지 한 건을 0개에서 N개의 `Event`로 바꾼다
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
비용은 변환 한 번이고, 대가로 인터랙션 레이어와 SDK 사이에 타입 의존이 사라진다.

이 경계는 덤으로 그다지 자명하지 않은 네 가지도 처리한다. 넷 다 `normalize()` 안에 있다.

1. **[subagent](../reference/glossary.md#subagent)의 발언에 표시가 붙는다**(`payload["subagent"]`).
   그러지 않으면 일을 넘기는 [태스크 브리프](../reference/glossary.md#任务书)와 subagent의 중간 발언이
   [메인 스레드](../reference/glossary.md#主线程) 본문에 섞이고, 그대로
   [워크플로](../reference/glossary.md#流程)를 타고 다음 스텝의 prompt를 오염시킨다.
2. **연결이 끊겼을 때의 합성 에러 메시지가 `kind="error"`로 갈라져 나온다.** 끊겼을 때 SDK 쪽은
   `API Error: …`를 assistant 메시지 한 건으로 transcript에 적는다. 그것은 모델이 한 말처럼 생겼다
   (`model`이 `"<synthetic>"`이다). 여기서 막지 않으면 `StepResult.text`로 들어가고 다음
   [스텝](../reference/glossary.md#步骤)으로 전달된다.
3. **compact 경계가 명시적으로 보고된다**(`kind="reset"`). 경계 이후에 모델이 "기억하는" 것은 요약뿐이고,
   prompt 캐시도 여기서 끊긴다 — [long-horizon](../reference/glossary.md#长程) 실행은 이것을 반드시
   볼 수 있어야 한다.
4. **컨텍스트 수위가 메시지마다 함께 나온다**(`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). 이것이
   [핸드오프](../reference/glossary.md#换代) 판정의 유일한 근거다.

## 어떻게 쓰는가(최소 코드)

인터랙션 레이어는 세 가지를 연결해야 한다. **이벤트 출구**(어디에 렌더링할지), **질문 채널**(누가 답할지),
**인터럽트**(어떻게 멈추라고 외칠지). 아래 코드는 셋 다 연결되어 있고 그대로 실행된다.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event를 네 UI로 렌더링한다 —— 바꿔야 하는 건 이것 하나뿐이다."""
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
    """질문을 풀 방식으로 가져온다. Web / HTTP로 바꿀 때 고쳐야 할 또 한 곳이 이 코루틴이다."""
    while True:
        ask = await ch.next_ask()           # timeout을 주지 않으면 계속 기다린다
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # 또는 ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime은 workflow가 직접 만든 워크벤치를 쓴다 —— 따로 하나 더 조립하지 마라
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

빠뜨리기 쉬운 마무리 두 가지. `rt.close()`는 반드시 `finally`에 둔다. `ctx["_failed_at"]`에 값이 있으면
도중에 멈춘 것이니(`on_fail="stop"`) 성공으로 취급하지 마라.

!!! note "워크벤치는 하나뿐이다, 따로 조립하지 마라"
    `Runtime(workbench=True)`가 만드는 [워크벤치](../reference/glossary.md#工作台)는
    `<run_dir>/workbench`에 있고, `Workbench(ws)`의 기본값은 `<ws>/.flower`다 ——
    둘은 같은 디렉터리가 아니다. 드라이버가 직접 경로를 조립해서 `需求.md`를 찾으면
    "브리프는 A 디렉터리에 쓰였는데 주입된 인덱스는 B 디렉터리를 스캔"하는 상황이 되고, 에러도 나지 않는다.
    workflow가 만든 그것을 `Runtime`에 넘기거나(위의 방식),
    읽기 전용 탐색 `wake_state()`로 어디에 있는지 물어라.

### 세 개의 이벤트 출구

```python
await rt.run(spec, "…", on_event=sink)                  # 1. 에이전트 하나
await wf.run(rt, on_event=sink, on_step=progress)       # 2. 워크플로 전체, 각 스텝으로 전달된다
wf = Workflow(steps=[...], channel=ch)                  # 3. 질문 채널, 같은 출구로 연결된다
```

세 번째의 연결은 `Workflow.run` 안에 있다. **`on_event`가 `None`이 아니고, `channel.on_event`가 아직
`None`일 때만 자동으로 연결된다.** 직접 연결해 두었다면 덮어쓰지 않는다.

```python
ch = HumanChannel(on_event=my_own_sink)     # 직접 연결하면 Workflow는 건드리지 않는다
```

`on_step(step, result)`는 또 하나의 콜백으로, 스텝이 끝날 때마다(**실패 포함**) 한 번 호출되며 완전한
`StepResult`를 받는다. 진행 표시, 디스크 기록, 알림은 여기에 걸어라. 이걸 하겠다고 `Event` 스트림에서
짜맞추지 마라 — 본문은 핸드오프와 재시도에 의해 여러 토막으로 끊긴다.

### 터미널: 기본으로 딸려 있는 것

코드를 쓰지 않아도 하나 있다. `flower "帮我做一个 X"`가 타는 경로는
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py)이고,
이것은 인터랙션 레이어의 **참조 구현이지 프레임워크의 일부가 아니다**. 통째로 갈아치울 수 있다.
스위치는 [CLI 레퍼런스](../reference/cli.md)를 보라.
규모는 있는 그대로 말한다. `cli.py` 전체는 1264줄, 57KB다 — 하지만 **바꿔야 하는 건 전체가 아니다**.
실제 교체 지점은 그 안의 `class Render`(`cli.py:382-578`, 197줄)이고, 그 docstring에도
"Event → 터미널. UI를 바꾼다는 건 이 클래스 하나를 바꾸는 것이다"라고 적혀 있다. 나머지 천여 줄은
인터럽트, 오라클, 인박스 수신 확인, 시그널 구조 같은 **터미널 고유의** 부속이며, 웹이나 HTTP로 바꿀 때는
애초에 그대로 옮길 필요가 없다.

그래서 "약 200줄이면 통째로 교체 가능"이라는 말은 성립한다 — 그것이 `cli.py`가 아니라 `Render`를
가리킨다는 전제에서.

터미널 UI를 직접 쓴다면 핵심은 표준 입력을 읽는 그 스레드다.

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """계속 표준 입력을 읽는다: 대기 중인 질문이 있으면 답이고, 없으면 인박스로 간다. 정지 플래그를 반환한다."""
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
                ch.send(raw)                    # 인박스로 들어가고, 진행 중인 작업을 끊지 않는다

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

세 가지 모두 밟아보고 얻은 것이다.

- **daemon 스레드를 쓰고 `asyncio.to_thread(input, ...)`는 쓰지 않는다.** `input()`은 블로킹 중에 취소가
  안 되고, `asyncio.run`은 종료 전에 기본 executor의 스레드를 join한다 — 결과적으로 일이 다 끝났는데도
  엔터를 한 번 더 눌러야 빠져나온다.
- **`select`로 폴링하고, 루프 안에서 곧장 `input()`을 부르지 않는다.** 마찬가지로 취소가 안 된다.
  `input()`에서 블로킹된 스레드는 `stop.set()`으로도 다시 깨울 수 없다.
- **질문이 있을 때만 읽는 게 아니라 계속 읽는다.** 질문이 있을 때만 읽으면, 일하는 그 몇 시간 동안 친 것이
  터미널 버퍼에 남아 있다가 다음 질문 때 답으로 먹힌다 — 사람이 질문을 보기도 전에 질문이 "답해진다".

### 웹: 큐 + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # 동기, 이벤트 루프가 있는 스레드에서, 블로킹 금지
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # 프런트엔드 에러가 세 시간짜리 작업을 데려가면 안 된다
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # 요청 처리 스레드 —— 다른 스레드다, 이게 일상이다
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw`는 원본 SDK 객체다(`ask` 이벤트에서는 `Ask`). **JSON 직렬화가 안 되고, 프런트엔드로 보내서도 안 된다** ——
`raw`를 쓰는 순간 프런트엔드를 다시 SDK 타입에 묶는 것이고, 이 레이어는 헛일이 된다.
`kind` / `text` / `tool` / `payload` 네 필드면 충분하다.

### HTTP: 시퀀스 번호 + 폴링

롱 커넥션이 없을 때는 이벤트에 번호를 매겨 클라이언트가 당겨가게 한다.

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # 최근 것만 남긴다. 메모리가 실행 시간에 따라 늘지 않게


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
    return {"ok": ch.answer(ask_id, text)}      # False = 이 질문은 더 이상 기다리지 않는다
```

인정해야 할 경계가 둘이다. `maxlen`이 차면 가장 오래된 것이 버려지므로, 아주 오래된 `after`를 들고 돌아온
클라이언트는 전부를 받지 못한다. 폴링 간격을 이 길이에 맞춰야 한다. 그리고 **`timeout_s`에 반드시 유한한
값을 줘야 한다** —— 아무도 폴링하지 않을 때 질문은 스스로 끝나지 않고, `timeout_s=None`이면 실행 전체가
거기 영원히 매달린다. 기본값 `1800.0`초면 적당하다.

### 완전 자동 무인 실행: 사람이 없다

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # 이벤트를 전부 버린다
```

커맨드라인 등가 표현은 `flower "帮我做一个 X" --timeout 0`이다.

`timeout_s=0`(음수도 마찬가지)은 완전 자동 모드다. 질문은 **대기 큐에 들어가지 않고 `asked` 이벤트도
발생하지 않으며**, 즉시 `state="timeout"`으로 정산되고 도구는 이 고정 문구를 돌려준다 ——

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

—— 그래서 실행은 그대로 굴러간다. 질문과 답은 여전히 `HumanChannel(log_path=...)`에 덧붙여지고
(`starter_flow`가 기본으로 연결하는 곳은 `<工作台>/notes/问答记录.md`), 나중에 무엇을 물었고 스스로 무엇을
가정했는지 볼 수 있다.

아예 입을 열지 않게 하려면 `max_asks=0`을 쓴다. 질문은 곧바로 거절되고(`state="over_budget"`) 마찬가지로
막히지 않는다. 이것은 **"도구를 빼는 것"이 아니라는 점**에 주의하라 —— `allowed_tools`는 배타적이지 않고,
[코디네이터](../reference/glossary.md#协调者)에 `channel`을 걸면 `mcp__human__ask`와
`mcp__human__inbox` 두 도구가 함께 주어진다. 목록에 적든 안 적든 호출된다. 질문을 막을 수 있는 것은
횟수 한도와 타임아웃뿐이다.

!!! warning "무인 실행에서 질문을 영원히 기다리게 하지 마라"
    `timeout_s=None`은 "영원히 기다림"이다. 지켜보는 사람이 없을 때 질문 한 번이면 열 시간짜리 실행이
    제자리에 멈춰 선다. 게다가 에러도 없고 타임아웃도 없으며 로그상으로도 구분되지 않는다.
    무인 실행에서 올바른 값은 둘뿐이다. `0`(즉시 불발) 또는 유한한 초.

## 실제로 무엇을 하는가

### `Event`의 모양

```python
@dataclass
class Event:
    kind: EventKind                     # 15가지 값, 아래 표 참조
    text: str = ""
    tool: str = ""                      # tool_call에만 값이 있다
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # 원본 SDK 객체 / Ask, 건드리면 다시 SDK에 묶인다
```

`str(ev)`: `tool_call`은 `[도구명] 요약`, 나머지는 `text`. `text`가 비어 있으면 `<kind>`다.

### 15가지 `EventKind`

| `kind` | 누가 보내는가 | 언제 나오는가 | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | 모델 본문 | 본문 | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | 사고 블록 | 사고 내용 | 위와 같음 |
| `prompt` | `normalize()` | **입력**: 네 prompt, subagent에게 넘기는 태스크 브리프 | 입력 텍스트 | 위와 같음 |
| `tool_call` | `normalize()` | 모델이 도구 호출을 시작 | 요약(`file_path` / `command` / `pattern`, 200자에서 자름) | `id`, `input` + 위와 같음. `tool`은 도구명 |
| `tool_result` | `normalize()` | 도구가 반환 | 앞 500자(내용이 문자열이 아니면 빈 문자열) | `tool_use_id`, `is_error` + 위와 같음 |
| `result` | `normalize()` | SDK 쿼리 한 번이 끝남 | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | 연결이 끊겼을 때의 합성 메시지 | 에러 텍스트 | `synthetic: True` |
| `reset` | `normalize()` | compact 경계 또는 세션 리셋 | `压缩(trigger) 167000 → 42000 tokens`. 세션 리셋일 때는 `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype`(세션 리셋일 때는 빈 값) |
| `system` | `normalize()` | 그 외 SDK 시스템 메시지 | subtype | `data`를 그대로 통과시킴 |
| `task` | `normalize()` | 태스크 진행 메시지 | 메시지 클래스명 | — |
| `unknown` | `normalize()` | 알아보지 못한 메시지 타입 | 클래스명 | — |
| `ask` | `HumanChannel` | 사람의 답이 필요하거나, 어떤 질문에 결말이 났거나, 사람이 먼저 한마디 했을 때 | 질문 / 사람이 한 말 | 두 가지 신분, 아래 참조 |
| `retry` | `Runtime` | 재시도 중 / 네트워크를 기다리며 걸려 있음 | 한 줄 설명 | `step`, `attempt` |
| `step` | `Workflow.run` | 스텝 경계 | 스텝 이름 | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | 핸드오프: 임박 / 작성 중 / 완료 | 수위가 포함된 한 줄 설명 | `phase`, `step`, `context`, `window` + 아래 참조 |

**네 가지 kind는 `normalize()`가 만들지 않는다.** `ask`는 `HumanChannel`에서, `retry`와 `handoff`는
`Runtime`에서, `step`은 `Workflow.run`에서 온다. 같은 `EventKind` 안에 둔 것은 의도적이다 ——
**UI는 한 벌의 `Event`만 알면 되고, "사람의 답이 필요하다"거나 "스텝 경계다"를 위해 별도의 경로를 낼 필요가 없다.**

UI를 쓸 때는 `else` 분기를 하나 남겨라. `EventKind`에는 앞으로도 멤버가 추가되고, 그것 때문에 옛 UI가
죽어서는 안 된다.

### `handoff`의 세 가지 phase

| `phase` | 언제 보내는가 | `payload`가 추가로 싣는 것 |
|---|---|---|
| `near` | 수위가 `warn_at`을 넘음. **한 세대에 한 번만** 보내며 화면을 도배하지 않는다 | `at`(핸드오프 임계값) |
| `writing` | [핸드오프 문서](../reference/glossary.md#交接书) 작성 시작. 쓰는 데 십수 초가 걸리므로, 이걸 보내지 않으면 화면이 멈춘 것처럼 보인다 | — |
| `done` | 인계 작성 완료, 새 세션으로 교체 | `degraded`(강등 버전인지), `path`(어디에 썼는지, 워크벤치가 없으면 빈 문자열), `sections` |

메커니즘 자체는 [핸드오프](handoff.md)를 보라.

### `ask`의 두 가지 신분

`Event("ask")`는 "질문"과 "사람이 먼저 한 말"을 동시에 실어 나른다. **UI는 반드시 `payload["kind"]`를 먼저 봐야 한다.**

| 신분 | 어떻게 알아보는가 | `payload` |
|---|---|---|
| 질문 한 번 | `kind` 키가 없음 | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`. `raw`는 그 `Ask` |
| 사람이 먼저 한 말 | `payload["kind"] == "mail"` | `kind`, `state`(`queued` 넣음 / `delivered` 가져감), `id`, `amended`(어느 파일에 덧붙였는지, 설정이 없으면 빈 문자열). **`options`와 `remaining`은 없다** |

질문 한 번은 이벤트를 **두 번 이상** 발생시킨다. 물을 때 한 번(`state="asked"`), 결말이 났을 때 다시 한 번
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). UI는 `payload["id"]`로 같은 항목을
갱신하면 된다.

### 사람에게 묻기: `Ask`와 `HumanChannel`

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # 위의 다섯 가지 결말 참조
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # 몇 초 기다렸는지, 소수점 한 자리
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel`은 프로세스 내 MCP server 하나에 UI용 메서드 한 묶음이다. 모델 쪽에는 두 개의 도구만 보인다.
`mcp__human__ask`(질문, 걸려서 기다린다)와 `mcp__human__inbox`(인박스 확인, **블로킹하지 않으며** 비어 있으면
즉시 설명 한 줄을 돌려준다). 전체 생성자는 이렇다.

```python
HumanChannel(
    *,                                  # 전부 keyword-only
    on_event=None,                      # 푸시 출구. Workflow는 이것이 None일 때만 자동 연결한다
    max_asks=None,                      # None = 무제한. 0 = 질문 금지. 초과하면 곧바로 거절, 막히지 않는다
    timeout_s=1800.0,                   # None = 영원히 기다림. <= 0 = 즉시 불발
    log_path=None,                      # 질문과 답을 이 파일에 덧붙인다, 컨텍스트를 차지하지 않는다
    amend_path=None,                    # 사람이 실행 도중 한 말을 이 파일에 덧붙인다, 보통은 브리프
    over_budget_text=OVER_BUDGET,       # 고정 응답 세 줄, 직접 바꿔도 된다
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path`는 가장 빠뜨리기 쉬운 항목이면서, "사람이 도중에 바꾼 요구가 스텝 경계를 넘어 살아남는가"를 결정한다.
매 스텝은 새 [세션](../reference/glossary.md#会话)이고 읽기 전용 동결본이다. 실행 도중 한 말은 그때 그
에이전트의 컨텍스트에만 들어갔고, 다음 스텝(예컨대 [판정](../reference/glossary.md#判定))은 완전히 새 세션이라
`需求.md`와 `目标.md`를 읽는다. **네가 한 그 말은 보이지 않는다.** 그래서 여전히 옛 경계로 판단하고,
고쳐놓은 것을 범위 이탈로 판정한다. `amend_path`는 메시지 하나하나를
[브리프](../reference/glossary.md#需求确认书)에 **덧붙인다** —— 덮어쓰지 않고 덧붙이므로 원래 요구는 이력으로
남고, 무엇이 바뀌었는지 보이는 편이 안 보이는 편보다 낫다. `starter_flow`가 기본으로 연결하는 곳은
`<工作台>/notes/需求.md`다.

실측($0.6767)으로 이것은 예상보다 더 잘 들었다. 사람이 "겸사겸사 총 바이트 수도 보고해줘"라고 했고,
코디네이터가 인박스를 확인한 뒤 보고하기를 —— "hand가 이미 `.flower/notes/需求.md`의 실행 중 보충에서 읽고
계산했으니, 다시 파견할 필요 없다". **subagent는 파일에서 읽었지, 누가 전달해준 게 아니다.**

공개 멤버:

| 멤버 | 시그니처 | 의미 |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | `AgentSpec.mcp_servers`에 그대로 넣는다. 키 이름이 server 이름과 같아야 하므로 여기서 함께 내준다 |
| `ask` | `async (question, options=None) -> Ask` | 걸려서 사람을 기다린다. **`CancelledError` 외에는 절대 예외를 던지지 않는다** —— 아무도 답하지 않는 것도 하나의 답이며, `ask.state`로 구분한다 |
| `pending` | `() -> list[Ask]` | 현재 답을 기다리며 걸려 있는 질문들 |
| `next_ask` | `async (timeout=None) -> Ask \| None` | 풀 방식 UI용. 타임아웃이면 `None`을 반환하고, 취소되면 던진다 |
| `answer` | `(ask_id, text) -> bool` | 답한다. `False` = 이 질문은 더 이상 기다리지 않는다(타임아웃 / 이미 답함) |
| `decline` | `(ask_id, reason="") -> bool` | 건너뛰고, 모델이 스스로 판단해 가정을 「未知与假设」에 적게 한다 |
| `send` | `(text) -> Mail \| None` | 사람이 먼저 한마디 한다, 인박스로 들어간다. 에이전트를 끊지 않는다. 내부적으로 `amend()`를 자동 호출한다 |
| `amend` | `(text, *, label="运行中补充") -> bool` | `amend_path`에 덧붙인다. 실제로 썼는지를 반환한다(경로 미설정 / 빈 텍스트 / `OSError`는 모두 `False`) |
| `pending_mail` | `() -> list[Mail]` | 아직 가져가지 않은 말 |
| `remaining` | `-> int` | 몇 번 더 물을 수 있는지. `max_asks=None`이면 **`-1`**을 반환한다, 0이 아니다 |
| `transcript` | `() -> str` | 질문·답 기록의 markdown |
| `asks` / `mail` / `ui_errors` | `list` | 모든 질문 / 사람이 한 모든 말 / UI 콜백이 던진 예외 |

`answer`, `decline`, `send`는 **어느 스레드에서 호출해도 된다.** 웹 백엔드의 요청 처리 스레드, TUI의 입력
스레드는 모두 다른 스레드에 있다 —— 이것이 일상이지 예외 상황이 아니다. 내부는
`loop.call_soon_threadsafe`를 거치는데, `asyncio.Future.set_result`가 스레드 안전하지 않기 때문이다.

푸시와 풀 두 방식 중 **하나를 고른다.**

| | 어떻게 받는가 | 어울리는 곳 |
|---|---|---|
| **푸시** | `HumanChannel(on_event=…)`, `kind == "ask"`이고 `payload["state"] == "asked"`인 것을 받음 | 이벤트 구동 UI(웹 푸시, TUI 재그리기) |
| **풀** | `await channel.next_ask()` | 독립된 입력 태스크 하나 |

세 가지 "0 / None"의 의미가 각각 다르다. 헷갈리면 무인 실행에서 멈춰 서거나, 한마디도 묻지 않게 된다.

| 표기 | 의미 |
|---|---|
| `max_asks=None` | 횟수 무제한(기본) |
| `max_asks=0` | 질문 금지, 곧바로 거절 |
| `timeout_s=None` | 영원히 기다림 |
| `timeout_s<=0` | 기다리지 않음, 질문은 즉시 불발 |
| `remaining`이 `-1` 반환 | `max_asks=None`일 때의 값이지 0이 아니다 |

### 인터럽트: 어느 스레드에서든 멈추라고 외칠 수 있다

`rt.interrupt("别改 Makefile,那两行直接改")`, 빈 문자열이면 말 없이 끊기만 한다. 성질은 셋이다.

- **같은 세션을 이어서 달린다**(`resume`). 처음부터 다시가 아니다 —— 이미 끝낸 일과 컨텍스트는 그대로 있다.
  네트워크 끊김 재시도의 기존 경로를 재사용하며, "실패 원인"을 "사람이 끊었다"로, `resume_prompt`를 사람이
  한 말로 바꿀 뿐이다.
- **`max_attempts`를 소모하지 않는다.** 그것은 장애에 준 한도지 사람에게 준 한도가 아니다.
- **협조적이다.** 메시지 경계에서 끊고, 태스크를 강제 취소하지 않는다. 대가는 다음 메시지까지의 지연이고
  (subagent가 돌고 있으면 그것이 돌아올 때까지 기다린다), 얻는 것은 중간에 상태가 찢어지지 않는 것이다.

대가는 있는 그대로 말한다. 인터럽트는 **진행 중인 subagent의 반제품을 잃게 만든다**(HT001 네트워크 끊김
때 실측했다, [issue #2](https://github.com/ChenyuHeee/flower/issues/2) 참조). 터미널 참조 구현은 프롬프트에
이 점을 명시해서, 누르기 전에 알 수 있게 한다. 직접 UI를 쓴다면 똑같이 해야 한다.

끊고 싶지는 않고 요구만 하나 더 얹고 싶다면 인박스를 쓴다(`ch.send(...)`) —— 아무것도 끊지 않고, 지연은
에이전트의 다음 체크포인트까지다.

### 오라클: 실행을 방해하지 않고 한마디 묻기

"지금 어디까지 왔나"를 알고 싶다고 해서 끊을 필요는 없고, 코디네이터에게 물어서도 안 된다. 그 문답은
**메인 스레드의 컨텍스트를 영구히 차지하며**(거기 담기는 것은 결정이지 문답 기록이 아니다), 게다가
코디네이터는 하던 일을 멈춰야 한다. 열 시간짜리 실행에서 지나가는 김에 세 마디 물으면 이 두 가지 대가를
다 치른다.

[오라클](../reference/glossary.md#旁路顾问)은 읽기 전용 우회로다. 도구는 `Read` / `Glob` / `Grep`뿐이고,
워크벤치를 열어두며, 기본으로 빗장이 걸려 있다. `max_turns=12`, `max_budget_usd=0.5`. 터미널에서는 `?`로
시작하는 한 줄로 촉발하고, 두 가지를 근거로 답한다. 최근 이벤트 윈도(고정 60건)와 워크벤치 안의 브리프,
목표, 노트, 산출물이다. 독립된 `Runtime`(`<run_dir>/aside`)을 쓰므로 비용과 세션
[계보](../reference/glossary.md#血缘)가 **메인 manifest에 섞이지 않는다** —— 그 명세는 "이번 실행이 어떤
스텝을 했는가"를 기록하는 것이고, 지나가는 김에 한마디 묻는 것은 스텝이 아니다.

실측으로 두 번 물어 합계 $0.5190, 메인 실행의 manifest는 1바이트도 늘지 않았다.

### 두 가지 철칙

!!! warning "on_event는 블로킹해서도 안 되고, 예외를 밖으로 내보내서도 안 된다"
    **하나, `on_event`는 동기 함수이며 이벤트 루프가 있는 스레드에서 호출된다.** 그래서
    `asyncio.Queue.put_nowait()`는 안전하지만 `await`는 안 된다(코루틴이 아니다). **여기를 막는 것은
    실행 전체를 막는 것이다.** 느린 일을 해야 하면 큐에 던지고 다른 태스크가 처리하게 하라.

    **둘, `on_event` 안에서 예외를 던지면 실행 자체가 다친다.** 본문류 이벤트는 `Runtime._attempt`의
    `try` 블록 안에서 발생하므로 예외는 `result.error`로 기록된다 — 그 스텝은 실패로 판정된다.
    `retry` 이벤트는 그 바깥에서 발생하므로 예외는 곧장 `Runtime.run` 밖으로 튀어나온다.
    프런트엔드가 세 시간짜리 작업을 데려가서는 안 된다. **직접 try로 감싸라.**

    예외: `HumanChannel`이 스스로 보내는 `ask` 이벤트는 이미 감싸져 있고, 예외는 `channel.ui_errors`에
    모이며 실행을 중단시키지 않는다.

## 언제 쓰면 안 되는가

### 인터랙션 레이어에서 하면 안 되는 것

| 하면 안 되는 것 | 왜 | 어떻게 해야 하나 |
|---|---|---|
| `from claude_agent_sdk import ...` | 인터랙션 레이어가 SDK 타입에 의존하는 순간, SDK가 올라가면 프런트엔드도 따라 고쳐야 하고 이 레이어는 헛일이 된다 | `Event`의 `kind` / `text` / `tool` / `payload`만 쓴다 |
| `ev.raw`를 읽는 것 | 위와 같고, 게다가 JSON 직렬화가 안 된다 | 부족한 세부는 `normalize()`의 `payload`에 채워 넣는다. 경계를 우회하지 마라 |
| `on_event` 안에서 `await`, 네트워크 요청, 느린 디스크 쓰기 | 동기 함수이고 이벤트 루프 스레드에서 호출된다. 여기를 막는 것은 실행 전체를 막는 것이다 | `put_nowait()`로 큐에 던지고, 별도 태스크가 소비한다 |
| `on_event`가 예외를 밖으로 던지게 두는 것 | 본문 이벤트의 예외는 `result.error`가 되고, 그 스텝은 실패로 판정된다 | 콜백 본문 전체를 `try`로 감싼다 |
| `disallowed_tools`로 질문을 끄는 것 | 그것은 **세션 단위**여서 subagent의 동명 도구까지 함께 금지한다(실측 에러 원문: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` 또는 `timeout_s=0` |
| `allowed_tools`에서 `mcp__human__ask`를 빼고 질문 금지로 여기는 것 | `allowed_tools`는 배타적이지 않고, 승인 면제 목록이지 화이트리스트가 아니다. `channel`을 걸면 두 도구가 함께 주어진다 | 위와 같음 |
| 직접 경로를 조립해 `需求.md` / `目标.md`를 찾는 것 | 워크벤치 위치는 두 가지이고, 잘못 조립해도 에러가 나지 않고 조용히 무효가 된다 | `wake_state()` 또는 `wf.workbench` |
| `Event` 스트림으로 진행 상황과 결과를 짜맞추는 것 | 본문은 핸드오프와 재시도에 의해 여러 토막으로 끊긴다 | `on_step(step, result)`로 완전한 `StepResult`를 받는다 |
| 무인 실행에서 `timeout_s=None`을 쓰는 것 | 아무도 답하지 않으면 실행이 영원히 걸려 있고, 에러도 타임아웃도 나지 않는다 | `0`, 또는 유한한 초 |

### 애초에 바꿀 필요가 없을 때

- **색만 바꾸거나 한 줄 더/덜 찍고 싶을 때** —— 렌더링 함수만 고치면 된다. 터미널 참조 구현의 인터럽트,
  오라클, 인박스 수신 확인, SIGHUP / SIGTERM 구조, 종료 전 우회로 마무리 대기를 다시 쓰는 비용은 작지 않다.
- **한 스텝만 돌리고 인터랙션은 필요 없을 때** —— `flower once`를 쓴다. 인터랙션 구동 경로를 타지 않으므로
  애초에 Ctrl+C 인터럽트도, 표준 입력 응답 스레드도, 오라클도, 시그널 구조도 없다.
- **바꾸고 싶은 게 사실 UI가 아니라 워크플로일 때** —— [워크플로 설계](workflow.md)를 보라. 인터랙션 레이어는
  누가 보고 누가 답하는지만 결정한다. 몇 스텝을 돌지, 어떻게 판정할지, 언제 조기 종료할지는 `Workflow`가 정한다.
- **바꾸고 싶은 게 세션 스토어, 모델, 예산일 때** —— 그 셋은 이 경계에 있지 않다.
  [Python API 레퍼런스](../reference/api.md)를 보라.
