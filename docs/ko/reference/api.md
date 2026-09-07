# Python API

이 페이지는 `flower` 최상위 `__all__`의 **공개 심볼 62개**를 남김없이 다룬다: 시그니처, 파라미터, 기본값,
의미, 공개 속성과 메서드. 다 읽고 나면 파라미터를 찾으러 소스를 열 일은 없다.

구성은 **관심사** 기준이며 모듈 파일 기준이 아니다 —— "[코디네이터](glossary.md#协调者)가 직접
손대는 걸 어떻게 막나"가 궁금하면 [hook 레이어](#hook)로, "이전 스텝의 결과를 다음 스텝에 어떻게
넘기나"가 궁금하면 [워크플로](#流程)로 가면 된다. 용어는 전부 [용어집](glossary.md)을 따른다.

버전 `0.1.0`, 의존성 `claude-agent-sdk>=0.2.152`. 모든 시그니처는 소스 코드와 글자 단위로 일치한다.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 최상위에서 한 번에 import
```

## 이 페이지에 있는 것 {#索引}

| 관심사 | 심볼 |
|---|---|
| [agent 하나 돌리기](#运行时) | `Runtime` `StepResult` |
| [여러 스텝 엮기](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [역할 만들기](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [agent 정의 직접 작성](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [구조화된 문서](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [툴 차단, 결과 트림, 격리 분리](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [스필이 놓이는 작업 디렉터리](#工作台) | `Workbench` |
| [세션을 어떻게, 무엇을 저장하나](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [네트워크가 끊기면](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [UI 교체](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [프로세스를 넘어 이어 붙이기](#血缘) | `Lineage` |

## 물어뜯는 기본값 여섯 개 {#危险默认值}

이 여섯 개는 자잘한 예외가 아니라, 가장 흔한 사고 여섯 가지다. 각 항목은 해당 절에 완전한 설명이 있다.

| 기본값 | 결과 | 상세 |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | 메인 스레드의 `Bash`/`Write`/`Edit`에 **hook이 하나도 걸리지 않는다** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | spec에 `CompactPolicy(mode="no_summary")`를 강제로 씌운다. 즉 `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | `resume_from=None`인 스텝도 프로세스를 넘어 지난번 그 세션에 이어 붙는다 | [Workflow](#workflow) |
| `build_options(fork=True)`에 `resume`을 주지 않음 | 조용히 무효화되고, 에러도 없다 | [build_options](#build-options) |
| `clarify(max_turns=<작은 수>)` | "질문 횟수 제한 없음"을 빈말로 만든다 —— 질문 한 번이 곧 한 턴이다 | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | 세션 단위라서 subagent까지 함께 금지된다 | [AgentSpec](#agentspec) |

---

## 런타임 {#运行时}

소스: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime`은 실행의 핵심이다. 워크스페이스, [세션 스토어](glossary.md#会话存储),
[워크벤치](glossary.md#工作台), [리질리언스](glossary.md#韧性) 정책, [핸드오프](glossary.md#换代) 정책을
쥐고 있고, 밖으로 내놓는 동사는 하나뿐이다: 스텝 하나를 `run`. 재시도, 중단된 뒤 이어 실행,
컨텍스트가 꽉 차서 핸드오프하기까지 전부 이 호출 하나 안에서 끝난다.

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

생성자 파라미터는 **전부 keyword-only**(`*`가 맨 앞)이며, `workspace`는 필수다.

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workspace` | `str \| Path` | 필수 | agent의 `cwd`. 생성 시 resolve하고 `mkdir(parents=True, exist_ok=True)`. SDK의 `project_key`는 여기서 유도된다 —— 디렉터리를 다른 곳으로 옮기면 예전 `session_id`는 조회할 수 없게 된다 |
| `run_dir` | `str \| Path` | `"runs"` | `sessions.db`, `manifest.json`, `lineage.json`을 두는 곳이고, `workbench=True`일 때의 기본 워크벤치 위치이기도 하다. 역시 resolve 후 mkdir |
| `portable` | `bool` | `True` | `build_options(portable=)`로 그대로 전달, 즉 `setting_sources=[]`: 호스트의 `~/.claude/`도, 프로젝트의 `.claude/`도 읽지 않는다. [포터블](glossary.md#可移植) 참고 |
| `trim` | `TrimPolicy \| bool` | `False` | 인스턴스를 주면 그대로 쓰고, `bool`을 주면 `TrimPolicy(enabled=bool(trim))`. **꺼도 큰 결과를 트림하지 않을 뿐, 프룬은 그대로 한다** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | 위와 같은 변환 규칙. `coordinator(glance=True)`와 한 쌍이다 —— 메인 스레드가 `git status`를 돌리도록 허용한다면, 그 결과가 만료된다는 보장이 있어야 한다 |
| `keep_denials` | `int` | `1` | `PrunePolicy(keep_denials=)`로 전달. 최근 N번의 거부된 툴 호출만 남기고, 그보다 이전 것은 호출과 결과를 함께 떼어낸다 |
| `workbench` | `Workbench \| bool` | `False` | 인스턴스를 주면 그대로 쓰고, `True`를 주면 `Workbench(workspace, home=run_dir / "workbench")`를 만든다(**기본 위치는 워크스페이스 밖이다**). 그 직후 곧바로 `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | 툴 결과가 몇 글자를 넘으면 [스필](glossary.md#落盘)할지. `None` 또는 `0` = `spill_guard`를 달지 않음 |
| `resilience` | `Resilience \| bool` | `True` | 같은 변환 규칙 |
| `handoff` | `HandoffPolicy \| bool` | `True` | 같은 변환 규칙 |

**세션 스토어는 하드코딩되어 있다**: 항상
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`이다.
생성자 파라미터에는 백엔드를 갈아 끼울 입구가 **없다** —— 바꾸려면 직접 `AgentSpec` +
`build_options(session_store=...)`를 구성하거나, 생성 후에 `rt.store`를 덮어써야 한다.

생성의 마지막 두 단계는 `load_dotenv()`와 `check_credentials()`이고, **후자는 문제가 있으면 `raise RuntimeError`**.
크레덴셜이 없으면 `run()`까지 가지 않고 생성 단계에서 터진다.

!!! warning "`workbench=False` + `coordinator()` = 메인 스레드에 벽이 하나도 없다"
    `delegate_guard`는 `workbench_hooks` 안에서만 설치되고, `workbench_hooks`는 `self.workbench is not None`
    일 때만 호출된다. 게다가 `whitelist_guard`는 `if not spec.delegate_only`에 걸려 건너뛰어진다. 그런데
    `coordinator()`는 항상 `delegate_only=True`로 설정하고, 기본값 `glance=True`가 `Bash`를 허용한다.

    **결론: 코디네이터를 `Runtime(workbench=False)`와 함께 쓰면, 그 `Bash`/`Write`/`Edit`을 막는 hook이 하나도 없다.**
    `coordinator()`를 쓴다면 `workbench`를 켜라 —— `Runtime(..., workbench=True)`이나
    `Workbench` 인스턴스를 넘길 것.

!!! warning "`handoff=True`(기본값)는 auto-compact를 강제로 끈다"
    `_attempt` 안에서: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    자식 프로세스로 내려가면 `DISABLE_AUTO_COMPACT=1`이다. 이유는 두 메커니즘을 동시에 켜두면 컨텍스트가
    줄어든 게 누구 짓인지 분간할 수 없기 때문이다.

    **대가: 핸드오프 문서를 쓰는 스텝에는 반드시 폴백 경로(`handoff.degraded`)가 있어야 한다.** compact가
    뒤를 받쳐주지 않기 때문이다.
    auto-compact를 남기려면 `AgentSpec.compact`를 명시적으로 주면 된다(spec이 직접 준 값은 존중하고 덮어쓰지 않는다).

#### 공개 속성 {#runtime-属性}

| 속성 | 타입 | 설명 |
|---|---|---|
| `workspace` | `Path` | resolve된 워크스페이스 |
| `run_dir` | `Path` | resolve된 런 디렉터리 |
| `portable` | `bool` | 그대로 보관 |
| `store` | `PruningSessionStore` | 세션 스토어. 백엔드를 바꾸려면 생성 후 덮어쓰는 방법밖에 없다 |
| `resilience` | `Resilience` | 정규화된 인스턴스 |
| `handoff` | `HandoffPolicy` | 정규화된 인스턴스 |
| `workbench` | `Workbench \| None` | `workbench=False`일 때는 `None` |
| `spill_threshold` | `int \| None` | 그대로 보관하고, `_attempt`에서 `workbench_hooks`로 전달 |
| `results` | `list[StepResult]` | 이 프로세스에서 실행한 모든 스텝, 순서대로 추가 |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **인스턴스마다 반드시 유일해야 한다** —— `manifest.json`은 `run` 필드로 중복을 제거하므로, 두 id가 충돌하면 나중에 쓰는 쪽이 상대의 행을 자기가 지난번에 쓴 것으로 착각해 지워버린다 |
| `on_session` | `Callable[[str], None] \| None` | 새 `session_id`를 받는 **즉시** 콜백, 기본값 `None`. **`runtime.run` 이 한 줄에만 씌워야 한다** —— [판정자](glossary.md#判定者)가 같은 `Runtime`을 쓰는데 gate 구간에도 걸려 있으면 판정자의 세션이 실제 작업 스텝의 [리니지](glossary.md#血缘)에 기록된다 |

클래스 상수: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE`(중단 후 이어 실행할 때 사람의 말 뒤에 덧붙는 문단으로, "당시 실행 중이던 툴 호출이
interrupted를 반환하는 것은 중단의 정상적인 부작용이며 환경 장애가 아니다"라고 설명한다).

#### 공개 메서드 {#runtime-方法}

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | 스텝 하나를 실행. 아래 참고 |
| `interrupt` | `(message: str = "") -> None` | 현재 턴의 중단을 요청. **어느 스레드에서든 호출 가능**. 협조적 방식: **메시지 경계**에서 깔끔하게 끊고, 강제 취소하지 않는다. 빈 문자열 = 중단만 하고 말은 하지 않음 |
| `rescue` | `() -> None` | 강제 종료되기 전에 최대한 장부를 남긴다. `SIGHUP`/`SIGTERM` 핸들러가 호출한다. 실행 중이던 스텝도 manifest에 `error="killed-by-signal"`로 기록한다. 동기 방식의 작은 디스크 쓰기만 수행 |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())`에서 `/`, `_`, `.`를 모두 `-`로 치환. **SDK가 cwd에서 유도하므로 호출자가 지정할 수 없다** |
| `has_session` | `(session_id: str) -> bool` | 이 id를 **이 워크스페이스** 아래에서 아직 조회할 수 있는지. 동기, payload는 읽지 않음 |
| `context_of` | `(session_id: str) -> int` | 어떤 세션의 마지막 턴 컨텍스트 규모. `store.last_context`에 위임 |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `spec` | `AgentSpec` | 필수, 위치 인자 | 실행할 agent 선언 |
| `prompt` | `str` | 필수, 위치 인자 | 이번 턴에 하는 말 |
| `step_name` | `str \| None` | `None` | `StepResult.step`, manifest, 리니지에 들어가는 키. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | 이 `session_id`를 이어 실행 |
| `fork` | `bool` | `False` | 원래 세션을 오염시키지 않고 새 세션으로 분기. **`resume`이 truthy일 때만 유효** |
| `resume_at` | `str \| None` | `None` | 특정 메시지 지점에서 이어 실행(롤백). 역시 **`resume`이 truthy일 때만 유효** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | 이벤트 출구, [`Event`](#event) 참고 |

각 스텝의 시작에서 컨텍스트 수위를 0으로 되돌린다(`self._ctx, self._warned = 0, False`). 그다음은 루프이고,
출구는 네 개다.

1. **성공** → 루프 이탈.
2. **사람의 중단**(`result.error == INTERRUPTED`) → **`max_attempts`의 제약을 받지 않고**, 네트워크도
   기다리지 않는다. 사람의 말을 들고 같은 세션을 `resume`, `attempt -= 1`(중단은 실패한 시도로 세지 않는다),
   prompt = 사람의 말 + `INTERRUPT_NOTE`. **`session_id`를 못 받았으면 멈추는 수밖에 없다.**
3. **컨텍스트 초과**(`result.error == HANDOFF_DUE`, 또는 `handoff.enabled`이고 `session_id`를 받았고
   `is_overflow(...)`가 걸린 경우) → **역시 `max_attempts`의 제약을 받지 않는다**. 먼저
   `len(result.retired) >= handoff.max_generations`를 확인해 초과했으면 error를 진단 문구로 바꾸고 이탈하고,
   아니면 [핸드오프 문서](glossary.md#交接书)를 쓰고 → `resume=None, fork=False`(**완전히 새 세션**)
   → prompt를 `h.prompt_block()`으로 교체 → 수위 0으로 → `attempt -= 1`.
4. **재시도 가능한 장애** → `not resilience.enabled or attempt >= max_attempts`면 이탈.
   `classify(error)`가 재시도 대상이 아니라고 판정하면 이탈. 아니면 `Event("retry")`를 발행하고
   `wait_online()`으로 네트워크가 돌아오길 기다린 뒤 `sleep(delay_for(attempt))`.
   **`session_id`를 받은 적이 있으면 `resume`으로 이어 실행**(prompt는 `resilience.resume_prompt`로 교체)하고,
   `result.resumed`를 `True`로 설정한다.

마무리: `ended_at` 기록, `self.results`에 추가, `manifest.json` 기록.

`manifest.json`은 **추가** 의미다. 쓸 때마다 디스크를 다시 읽고 `run` 필드로 중복을 제거한다(자기 행은
갱신하고, 다른 쪽 행은 그대로 남긴다). 그래서 같은 `run_dir` 아래에서 flower 두 개를 병렬로 돌려도 안전하다
—— `run_id`가 충돌하지 않는다는 전제에서.

**핸드오프의 관측점 세 개**(모두 `Event("handoff")`이고 `payload["phase"]`로 구분):
`near`(`warn_at`에 근접, 세대당 한 번만 발행), `writing`(핸드오프 문서를 쓰는 중, 십수 초 걸린다),
`done`(payload에 `degraded` / `path` / `sections`). 핸드오프 문서를 쓰는 턴은
`replace(spec, max_budget_usd=None)`으로 돌린다 —— 핸드오프는 반드시 써낼 수 있어야 하고, 예산에 걸려
막혀서는 안 된다. 그리고 `on_event=None`이라 이 턴은 UI로 흘려보내지 않는다.

핸드오프 문서는 `<workbench.notes>/交接-<步骤名>.md`에 기록된다. **워크벤치가 없으면 디스크에 남지 않는다.**
문서 자체는 여전히 prompt를 통해 인수자에게 전달되지만, 나중에 되돌아볼 수 없을 뿐이다. 오래된 핸드오프 문서는
`notes/archive/交接/<名>-<时间戳>.md`로 옮겨진다.

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

스텝 하나가 끝난 뒤의 장부 전체.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `step` | `str` | 필수 | 스텝 이름(`step_name` 또는 `spec.name`) |
| `session_id` | `str \| None` | `None` | **항상 마지막으로 인수한 그 세션** —— 중간에 핸드오프로 태워버린 것들은 `retired`에 있다 |
| `ok` | `bool` | `False` | 이 스텝이 성공했는지 |
| `cost_usd` | `float` | `0.0` | 달러. 재시도와 핸드오프를 거치는 동안 **누적**된다 |
| `num_turns` | `int` | `0` | 턴 수, 역시 누적 |
| `text` | `str` | `""` | **메인 스레드의 본문만 담는다.** subagent의 발언은 자기 transcript에 남고, 그에게 넘긴 태스크 브리프는 `kind="prompt"`라서 둘 다 들어오지 않는다 |
| `error` | `str \| None` | `None` | 실패 원인. 특수값은 `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` 참고 |
| `started_at` / `ended_at` | `float` | `0.0` | Unix 타임스탬프 |
| `attempts` | `int` | `1` | 실제 시도 횟수. 중단과 핸드오프는 **세지 않는다** |
| `errors` | `list[str]` | `[]` | 수집된 합성 API 에러 메시지, **`text`에는 들어가지 않는다** |
| `resumed` | `bool` | `False` | 중간에 resume으로 이어 실행한 적이 있는지 |
| `retired` | `list[str]` | `[]` | 이 스텝의 핸드오프에서 태워버린 `session_id`들, 순서대로 |
| `context` | `int` | `0` | 마지막 턴에 메인 스레드가 실제로 본 컨텍스트 규모. 즉 핸드오프 판단 기준 |

| 속성 | 타입 | 설명 |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, 아직 끝나지 않았으면 `0.0` |

---

## 워크플로 {#流程}

소스: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[워크플로](glossary.md#流程)는 순서대로 엮인 [스텝](glossary.md#步骤)들의 묶음이고, 여기에 스텝 사이에서 상태를 어떻게 넘길지,
언제 앞당겨 빠져나올지가 더해진 것이다. **프레임워크는 기성 워크플로를 제공하지 않는다. 워크플로는 네가 쓰는 것이다** —— `starter_flow`는 그저 돌아가는 견본일 뿐이다.

타입 별칭 `Ctx = dict[str, Any]`(`flower.workflow.base.Ctx`, `flower.workflow.__all__`에 들어 있고
최상위 `__all__`에는 없다).

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

한 스텝의 **선언**이다. `Step` 자체는 함수가 아니다 —— 실제로 실행하는 것은 `Runtime.run(step.spec, prompt, ...)`이다.
앞의 세 필드는 위치 인자라서 `Step("취어", terse, "seed.txt를 읽고 …")` 같은 표기가 유효하다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | 필수 | 스텝 이름. **프로세스를 넘어 안정적인 키** —— `ctx[name]`, `ctx["_results"]`, 매니페스트, 계보에 그대로 남는다. 이름 변경 = 계보 단절 |
| `spec` | `AgentSpec` | 필수 | 어떤 agent를 돌릴지 |
| `prompt` | `str \| Callable[[Ctx], str]` | 필수 | 무엇을 말할지. 클로저로 두면 `ctx`를 받아 그 자리에서 계산한다 |
| `resume_from` | `str \| None` | `None` | 어느 스텝의 세션을 이어서 돌릴지. 가리킨 스텝이 세션을 만들지 않았다면 **`ValueError`를 던진다**. 조용히 건너뛰지 않는다 |
| `fork` | `bool` | `False` | `resume_from` 위에서 분기한다. **`resume_from`이 없으면 무효** |
| `retries` | `int` | `0` | gate를 통과하지 못했을 때 최대 몇 번 더 시도할지. `retries=0` = 한 라운드만 |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | 이번 시도를 통과로 볼지 판단한다. **async여도 된다**. `False`를 반환하면 실패로 본다. **시도 한 번당 한 번만 호출된다** —— 부작용(예: 확인서를 디스크에 기록)이 있을 수 있어 반복 호출되면 안 되기 때문이다 |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, 아래 참조 |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | `False`를 반환하면 **스텝 전체를 건너뛴다**: result가 생기지 않고 `ctx["_results"]`에도 들어가지 않는다. **async여도 된다** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | gate를 통과하지 못했을 때 **다음 라운드에 무슨 말을 할지**. **async여도 된다**. 이걸 주면 재시도 의미 자체가 바뀐다, 아래 참조 |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | 처음부터 다시 시작하는 대신 이어갈 때 쓰는 prompt |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | `ctx[name]`에 무엇을 넣을지 결정한다. 기본은 `result.text` 원문. **반드시 동기 함수여야 한다** |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | `resuming`이고 `resume_prompt`가 있으면 후자를, 아니면 `prompt`를 쓴다. 호출 가능한 객체면 `ctx`를 넘겨 호출한다 |

**세 가지 세션 연결 방식**(같은 런 안에서):

| 표기 | 효과 |
|---|---|
| `resume_from=None`(기본) | 새 세션. prompt로 넘긴 컨텍스트만 갖는다. 싸고, 격리된다. **단 `Workflow(continuous=True)`이면 프로세스를 넘는 계보에서 같은 이름의 스텝 세션을 가져온다** |
| `resume_from="이전 스텝 이름"` | 같은 세션을 이어서 돌린다. 컨텍스트가 온전하다. 비싸고, 연속적이다 |
| `resume_from="이전 스텝 이름", fork=True` | 분기해서 원래 세션을 오염시키지 않는다. 재검토 / 다중 안 병렬에 쓴다 |

**`on_reject`는 재시도 의미를 바꾼다**:

- 주지 않으면 → 다음 시도는 **처음부터 다시 돈다**(같은 prompt, 같은 `resume_from`).
- 주면 → 다음 시도는 **방금 거절당한 그 세션을 이어서 돌리고**, prompt는 반환값으로 바뀌며, `fork`는 강제로 `False`가 된다.
- 빈 문자열을 반환하면 → 되돌리지 않고, 처음부터 다시 도는 쪽으로 퇴화한다.
- `result.session_id`가 `None`이면 → 이 역시 처음부터 다시 도는 쪽으로 퇴화한다.

**`on_fail`의 세 가지 값**:

| 값 | 동작 |
|---|---|
| `"stop"`(기본) | `ctx["_failed_at"] = name`을 쓰고 **워크플로 전체를 중단한다** |
| `"skip"` | 다음 스텝으로 건너뛴다. **`ctx[name]`은 쓰지 않는다** —— 하류의 `lambda ctx: ctx["某步"]`는 `KeyError`가 난다 |
| `"continue"` | `ctx[name] = result.text`. 불완전한 결과를 들고 계속 간다 |

통과 여부와 무관하게 `ctx["_results"][name] = result`는 항상 쓰인다. `result.session_id`가 비어 있지 않으면
`ctx["_sessions"]`에도 쓰고 `lineage.remember(...)`까지 한다.

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

`Step` 여러 개를 순서대로 돌리고 최종 `ctx`를 반환한다. `steps`는 위치 인자라 `Workflow([...])`가 유효하다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `steps` | `list[Step]` | 필수 | 순서대로 실행한다 |
| `name` | `str` | `"workflow"` | 워크플로 이름 |
| `context` | `Ctx` | `{}` | 초기 컨텍스트 딕셔너리. **같은 `Workflow`를 두 번째로 돌리면 ctx는 동일한 dict다** |
| `channel` | `HumanChannel \| None` | `None` | 멈춰서 사람에게 물어야 할 때 여기에 단다. `run()`은 이것의 `on_event`를 같은 출구에 자동으로 연결하는데, **`channel.on_event is None`일 때만** 그렇게 한다. 드라이버도 이 필드를 보고 누구에게 답해야 할지 안다 |
| `workbench` | `Workbench \| None` | `None` | 워크플로가 지정하는 워크벤치. 드라이버가 찾을 수 있게 하기 위한 것 |
| `continuous` | `bool` | `True` | 같은 경로 = 같은 대화. 구현은 [`Lineage`](#lineage) |

| `run()`의 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `runtime` | `Runtime` | 필수, 위치 인자 | 어떤 런타임으로 돌릴지 |
| `on_event` | `Callable[[Event], None] \| None` | `None` | 이벤트 출구. 매 `Runtime.run`에 그대로 전달된다 |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | 스텝이 끝날 때마다 한 번 콜백한다 |

!!! warning "`continuous=True`가 기본값이고, `resume_from=None`은 새 세션을 뜻하지 않는다"
    이어가기가 켜져 있으면 `run()`은 먼저 `Lineage.open(run_dir, workspace)`를 하고, 각 기록에 대해
    `runtime.has_session(sid)`로 아직 스토어에 살아 있는지 검증한 뒤, 살아 있는 것만 `ctx["_sessions"]`에 채운다. 그래서
    **`resume_from=None`인 스텝도 지난번 그 세션을 이어서 말한다** —— 프로세스가 죽었든 머신이 재부팅됐든 마찬가지다.

    매번 새 세션이어야 한다면 `Workflow(..., continuous=False)`를 명시하라.
    또 하나: **스텝 이름은 프로세스를 넘어 안정적인 키이고, 이름을 바꾸면 계보가 끊긴다.**

`run()`이 ctx에 쓰는 **비공개 키**(전부 `_`로 시작하므로 스텝 이름과 충돌하지 않는다):

| 키 | 내용 |
|---|---|
| `_runtime` | 넘겨받은 `Runtime`. **gate 안에서 agent를 파견하려면 이게 필요하다** |
| `_on_event` | 이벤트 출구. gate 안의 agent도 UI까지 신호를 보낼 수 있어야 한다. 아니면 화면이 깜깜해진다 |
| `_sessions` | `dict[스텝 이름, session_id]`. `setdefault`로 꺼낸다 |
| `_results` | `dict[스텝 이름, StepResult]` |
| `_lineage` | `Lineage` 객체. `continuous=True`이고 runtime에 `run_dir` + `workspace`가 있을 때만 존재한다 |
| `_woke` | `lineage.bump()`의 반환값. 몇 번째 웨이크인지 |
| `_aborted` | `StepAbort`의 메시지 |
| `_failed_at` | `on_fail="stop"`일 때 실패한 스텝 이름 |

`Event("step")`의 payload: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**재시도 라벨**: 0번째는 `step.name`을 쓴다. 그 이후에는 `on_reject`가 있으면 `f"{name}#round{attempt+1}"`,
없으면 `f"{name}#retry{attempt}"`. 매니페스트만 봐도 이 스텝이 어떻게 끝까지 갔는지 한눈에 보인다.
**접미사가 붙은 이름은 프로세스를 넘는 계보에 들어가지 않는다** —— `Lineage.remember`는 원래 이름을 쓴다.

`runtime.on_session`은 `runtime.run` 이 한 줄만 감싸고, `try/finally`로 gate 이전에 반드시 벗겨지도록 보장한다.
`prompt_cur` / `resume_cur` / `fork_cur`는 지역 변수라 `step`에 되쓰지 않는다 —— 같은 `Step` 객체가 두 번째로 돌 수 있기 때문이다.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

`gate`가 던지면 = **즉시 멈추고, 더 재시도하지 마라**. "`False` 반환"과의 차이: `False`는 "이번엔 안 됐으니 한 번 더";
`StepAbort`는 "더 해봐야 소용없다".

던져진 뒤: `ctx["_aborted"] = str(exc)`, `passed = False`, **재시도 루프를 빠져나온다(남은 `retries`를 소비하지 않는다)**.
그다음에는 보통 실패와 똑같이 `on_fail`(기본 `"stop"`)을 따른다.

`with_goal`은 두 곳에서 이걸 던진다: `ctx["_runtime"]`을 얻지 못할 때, 그리고 판정 결과가 `unreachable`인데 아무도 응답하지 않을 때.

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

[사전 확인](glossary.md#前置确认)을 하는 `Step`을 만든다: 요구를 캐물어 명확히 하고 → [`Brief`](#brief)로 파싱하고 →
네 단락이 다 갖춰지면 동결해 디스크에 기록한다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `channel` | `HumanChannel` | 필수, 위치 인자 | 질문 채널 |
| `brief_path` | `str \| Path` | 필수 | [확인서](glossary.md#需求确认书)를 어디에 둘지. **실제로 인덱스에 주입되는 바로 그 워크벤치 안이어야 한다** |
| `prompt` | `str \| Callable[[Ctx], str]` | 필수 | 사람의 원래 요구 |
| `name` | `str` | `"确认需求"` | 스텝 이름이자 `ctx`의 키 |
| `spec` | `AgentSpec \| None` | `None` | 주지 않으면 `clarify(name, channel, instructions=instructions, **spec_kw)`를 쓴다 |
| `instructions` | `str` | `""` | [클래리파이어](glossary.md#确认者)에게 덧붙이는 보충 지시 |
| `always_ask` | `bool` | `False` | `True` = 확인서가 있든 없든 매번 다시 묻는다 |
| `on_fail` | `str` | `"stop"` | `Step.on_fail`과 동일 |
| `retries` | `int` | `0` | 네 단락이 안 갖춰졌을 때 몇 번 더 물을지 |
| `**spec_kw` | | | [`clarify()`](#clarify-role)에 그대로 전달된다. 그래서 `can_read=False`, `max_budget_usd=...` 같은 걸 쓸 수 있다 |

만들어진 `Step`의 각 필드는 이렇게 채워진다:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: `always_ask=True` → 항상 `True`. 아니면 `Brief.load(brief_path)`가 완전하면 그걸 ctx에 채워 넣고
  **그다음 `False`를 반환한다(건너뛴다)** —— 건너뛰더라도 채워 넣어야 한다. 안 그러면 하류가 요구를 못 받는다.
- `gate`: `Brief.parse(result.text)`. 불완전하면 → `ctx[MISSING_KEY]`를 쓰고 `False` 반환.
  완전하면 → `b.write(brief_path)`로 동결하고 ctx에 채워 넣은 뒤 `True` 반환.
- `reduce`: `ctx[BRIEF_KEY].prompt_block()`을 반환한다. **모델 원문이 아니다** —— 원문에는 모델이 더 쓴 것들이 섞여 있을 수 있다.
- `resume_from`은 **기본값 `None` 그대로**: 다음 스텝은 새 세션이라 확인서만 받고 그 문답은 받지 못한다.
  사전 확인의 문답은 **애초에 코디네이터의 컨텍스트에 들어간 적이 없다**. 들어갔다가 잘려나간 게 아니다.

ctx에 채워 넣는 세 곳: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| 상수 | 값 | 설명 |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]`는 `Brief` 객체. `ctx[step.name]`은 그것의 `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | 확인 실패 시 어느 단락이 빠졌는지(중국어 단락명). UI 표시용 |
| `CLARIFY_RESUME` | 중국어 프롬프트 한 단락 | "방금 끝내지 못한 요구 확인을 이어서 계속하라 —— **다시 시작하는 게 아니다**……". 이 문장이 없으면 이어갈 때 원래 요구를 새 작업으로 다시 보내게 되고, 클래리파이어가 이미 물었던 걸 또 물을 수 있다 |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

**목표를 설정하는** `Step`을 만든다: [판정자](glossary.md#判定者)가 확인서를 읽고 목표 + 판정 체크리스트를 쓰게 한 뒤,
[`Goal`](#goal)로 파싱해 동결하고 디스크에 기록한다. `clarify_step`과 같은 모양이다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `channel` | `HumanChannel` | 필수, 위치 인자 | 질문 채널 |
| `goal_path` | `str \| Path` | 필수 | 목표 파일을 어디에 둘지 |
| `brief_key` | `str` | `"确认需求"` | `ctx[brief_key]`에서 확인서 원문을 꺼내 prompt에 넣는다. **못 꺼내면 `"(没有确认书)"`가 된다** |
| `name` | `str` | `"设定目标"` | 스텝 이름 |
| `spec` | `AgentSpec \| None` | `None` | 주지 않으면 `judge(name, channel, instructions=instructions, **spec_kw)`를 쓴다 |
| `instructions` | `str` | `""` | 추가 지시 |
| `always_set` | `bool` | `False` | `True` = 목표 파일이 있든 없든 체크리스트를 다시 도출한다 |
| `on_fail` | `str` | `"stop"` | 위와 동일 |
| `retries` | `int` | `0` | 위와 동일 |
| `**spec_kw` | | | [`judge()`](#judge-role)에 전달 |

**`can_run` 형식 인자는 없다** —— 목표를 세우는 판정자가 명령을 돌릴 수 있게 하려면 `**spec_kw`로 `can_run=True`를 넘기는 수밖에 없다.
넘기지 않으면 `Bash`를 못 받고, `JUDGE_RULES`의 "먼저 네가 어떤 환경에 있는지 똑똑히 봐라"는 항목을 실행할 수 없다.

`gate`는 파싱과 동결 말고 한 가지를 더 한다: 목표에 `[此环境无法验证:…]` 항목이 있으면 **그 자리에서**
`ctx["_on_event"]`를 통해 `Event("task", payload={"unverifiable", "total", "path"})`를 보내 경고한다 ——
이런 항목들의 운명은 목표를 세우는 바로 이 순간에 정해지고, 판정 시점까지 가면 이미 한 라운드치 작업 비용을 다 써버린 뒤다.

**`resume_prompt`는 설정하지 않는다** —— 목표 설정은 원래 확인서 전문을 다시 보내는 게 맞다.

| 상수 | 값 | 설명 |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]`는 `Goal` 객체. `ctx[step.name]`은 markdown |
| `VERDICT_KEY` | `"_verdict"` | 가장 최근의 [`Verdict`](#verdict). UI용 |
| `ROUND_KEY` | `"_goal_rounds"` | 판정을 몇 라운드 돌렸는지 |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

기존 `Step`에 [목표 가드](glossary.md#目标看守)를 씌운다: 매 라운드가 끝날 때마다 판정자가 독립적으로 판정하고,
달성하지 못했으면 되돌려 보내 계속하게 한다.

결과물은 `replace(step, retries=max(0, rounds - 1), gate=<새 gate>, on_reject=<새 on_reject>)`다 ——
필드를 하나씩 다시 조립하지 않고 `dataclasses.replace`를 쓴다. 한 번 다시 조립했다가 `resume_prompt`를 빠뜨렸고,
**게다가 에러도 나지 않았다**. 그저 이어갈 때 확인서 전문을 한 번 더 보냈을 뿐이다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `step` | `Step` | 필수, 위치 인자 | 가드를 씌울 스텝 |
| `channel` | `HumanChannel` | 필수, 위치 인자 | 판정이 막혔을 때 사람에게 도움을 청하는 채널 |
| `goal_path` | `str \| Path` | 필수 | 목표 파일. `ctx[GOAL_KEY]`가 불완전할 때 여기서 읽는다 |
| `spec` | `AgentSpec \| None` | `None` | 주지 않으면 `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)`를 쓴다 |
| `rounds` | `int` | `3` | **추가 라운드가 아니라 총 라운드 수**: `rounds=3` → `retries=2` → 최대 세 라운드 작업. `rounds=1` = 한 라운드 돌리고 한 번 판정, 통과 못 하면 실패 |
| `instructions` | `str` | `""` | 판정자에게 덧붙이는 지시 |
| `can_run` | `bool` | `False` | 판정자가 `Bash`를 돌릴 수 있는지 |
| `name` | `str \| None` | `None` | 판정자의 이름. 기본은 `f"{step.name}·判定"` |
| `**spec_kw` | | | `judge()`에 전달 |

`gate`는 **async**이고, 흐름은 이렇다:

1. `ctx["_runtime"]`이 없으면 → **`StepAbort`를 던진다**("Runtime을 얻을 수 없어 목표를 판정할 수 없다"). **통과한 척하지 마라.**
2. `ctx[ROUND_KEY] += 1`.
3. 목표를 가져온다: `ctx[GOAL_KEY]`에 완전한 `Goal`이 있으면 그걸, 없으면 `Goal.load(goal_path)`, 그것도 없으면 빈 `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **판정자는 독립된 한 번의 `Runtime.run`이고, `resume`는 항상 `None` —— 언제나 새 세션이다**. `step_name`에 라운드 번호가 붙으므로
   프로세스를 넘는 계보에는 들어가지 않는다.
5. `Verdict.parse(vr.text)`를 `ctx[VERDICT_KEY]`에 쓴다.
6. `v.achieved` → `True` 반환.
7. `unreachable`이 아니면(`v.ok=False`인 애매한 경우 포함) → 애매할 때는 기본 reason 한 줄을 채우고 `False` 반환.
   **애매하면 무조건 미달성으로 본다** —— "될 것 같다" 한마디로 작업을 끝내게 둘 수는 없다.
8. `unreachable` → `await channel.ask(...)`로 사람에게 묻는다. 선택지는 셋:
   - 아무도 응답하지 않으면(`a.state != "answered"`) → **`StepAbort`를 던진다**. 계속 헛도는 게 가장 비싼 선택이다.
   - 「이 결과를 받아들이고 이대로 진행」 → `True` 반환.
   - 「목표를 수정」 → 새 목표를 한 번 더 묻고, `g.amend(...).write(goal_path)`로 쓰고 `ctx[GOAL_KEY]`를 갱신한 뒤 `False` 반환.
   - 그 외(사람이 직접 쓴 자유 답변 포함) → "네 판단이 틀렸다"로 보고, 사람의 말을 `v.reason`에 기록한 뒤 `False` 반환.

`on_reject`는 **동기**다: `ctx[VERDICT_KEY].feedback()`을 반환하고, `Verdict`가 없으면 `""`를 반환한다
(처음부터 다시 도는 쪽으로 퇴화한다).

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

바로 돌릴 수 있는 세 스텝 워크플로를 조립한다: **요구 확인 → 목표 설정 → 작업**(목표 가드 포함). 커맨드라인 `flower`가 쓰는 게 바로 이것이다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `ask` | `str` | 필수, 위치 인자 | 요구 한마디. **웨이크 시에는 새 작업이 아니라 "또 한마디 한 것"이다** |
| `workspace` | `str \| Path` | `"."` | 작업 공간 |
| `run_dir` | `str \| Path` | `"runs"` | 런 디렉터리 |
| `new` | `bool` | `False` | `True` = 계보 + 확인서 + 목표를 아카이브(셋을 함께 거둔다)하고 처음부터 시작 |
| `isolate` | `bool` | `False` | 워커에게 worktree [격리](glossary.md#隔离)를 연다. 워크벤치도 따라서 `<ws>.parent/.flower-<ws.name>`로 옮겨간다 |
| `clarify_only` | `bool` | `False` | 확인 스텝만 담은 Workflow를 반환 |
| `goal` | `bool` | `True` | [목표 가드](glossary.md#目标看守)를 다는지 여부. `False` = 작업 스텝이 끝나면 그걸로 끝 |
| `rounds` | `int` | `3` | `with_goal(rounds=)`로 전달. 총 라운드 수 |
| `judge_can_run` | `bool` | `False` | `with_goal(can_run=)`로 전달 |
| `max_asks` | `int \| None` | `None` | `HumanChannel`로 전달. `None` = 횟수 제한 없음 |
| `timeout_s` | `float \| None` | `1800.0` | `HumanChannel`로 전달. `0` = 완전 자동, 모든 질문이 즉시 허공으로 |
| `instructions` | `str` | `""` | 클래리파이어에게 덧붙이는 지시 |
| `worker_prompt` | `str` | 시그니처 참조 | 워커의 system prompt |
| `brief_name` | `str` | `"需求.md"` | 확인서 파일명. `<workbench.notes>/`에 놓인다 |
| `goal_name` | `str` | `"目标.md"` | 목표 파일명. 위와 동일 |
| `log_name` | `str` | `"问答记录.md"` | 문답 기록 파일명. 위와 동일 |

고정 조립:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

동작 분기:

- `isolate=True`인데 workspace가 git 저장소가 아니면 → **`ValueError`를 던진다**. `Agent` 도구가 에러를 낼 때까지 기다렸다 알게 되지 않는다
  (그때는 이미 돈을 썼다).
- **웨이크 판정**: `Brief.load(brief_path)`가 존재하고 `complete()`면 웨이크로 본다. 웨이크가 아니고 `ask`가 비어 있으면 →
  **`ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`를 던진다**.
- 웨이크 시 그 한마디는 동시에 **세 곳**에 들어간다. 하나라도 빠지면 조용히 무효가 된다: 확인서에 덧붙이고
  (`ch.amend(said, label="唤醒时追加")`, 이미 파일에 있으면 중복해서 쓰지 않는다),
  `goal_step(always_set=True)`으로 체크리스트를 다시 도출하게 하고(다시 도출하지 않으면 판정자가 읽는 건 여전히 옛 목표다),
  코디네이터 앞에 곧바로 전달한다(코디네이터의 컨텍스트에는 **옛** 목표가 있으므로, 주지 않으면 옛 기준으로 일하고 새 기준으로 판정받는다).

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**출발 전의 읽기 전용 탐지로, 단 1바이트도 쓰지 않는다.** 실제로 돌기 전에 사람에게 "이번 건 지난번을 이어가는 건지, 처음부터 시작하는 건지"를 알려주는 용도다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | 작업 공간, 위치 인자 |
| `run_dir` | `str \| Path` | `"runs"` | 런 디렉터리 |
| `isolate` | `bool` | `False` | 워크벤치 위치를 결정한다. `starter_flow`에 넘긴 값과 반드시 같아야 한다 |
| `brief_name` | `str` | `"需求.md"` | 확인서 파일명 |
| `goal_name` | `str` | `"目标.md"` | 목표 파일명 |

반환되는 dict:

| 키 | 타입 | 설명 |
|---|---|---|
| `waking` | `bool` | 확인서가 존재하고 네 단락이 다 갖춰졌는지 |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | 목표 체크리스트 항목 수. 목표가 없으면 `0` |
| `woke` | `int` | `Lineage.woke`. 지금까지 몇 번 웨이크했는지 |
| `steps` | `dict` | `Lineage.steps`의 복사본. 스텝 이름 → `session_id` |

워크벤치 위치는 **여기와 `starter_flow` 안에서 딱 한 번씩만 정의된다**: `isolate=True` → `<ws>.parent/.flower-<ws.name>`
(저장소 밖). 아니면 `<ws>/.flower`. 드라이버가 확인서 위치를 알고 싶을 때도 이 함수를 거친다 —— 직접 경로를 조립하다 틀려도 에러가 나지 않고,
그저 조용히 무효가 된다.

---

## 역할 팩토리 {#角色工厂}

소스: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

다섯 역할은 모두 팩토리 함수다. 각 역할 = **주입되는 규칙 텍스트 한 덩어리 + 도구 한 묶음 + hook 한 묶음**.
`worker()`가 내놓는 것은 SDK의 `AgentDefinition`(subagent에 배정용)이고, 나머지 넷은 [`AgentSpec`](#agentspec)
(자기 session을 하나 띄운다)을 내놓는다.

역할 자체는 **hook을 달지 않는다** —— 도구를 가로채는 일은 `Runtime._attempt`가 `spec.delegate_only`에 따라 자동으로 붙인다.
[hook 층](#hook) 참조.

내부 도구 묶음 상수(export되지 않지만 기본값을 결정한다):

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

[main thread](glossary.md#主线程) 위의 그 [coordinator](glossary.md#协调者)를 만든다: 작업을 쪼개고, 배정하고, 보고를 읽고, 결정한다.
**단 직접 손대지는 않는다.** 앞의 세 인자는 위치 인자다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | 필수 | 역할 이름, 동시에 기본 step 이름 |
| `instructions` | `str` | 필수 | 도메인 지시. 최종적으로 `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | 필수 | 휘하에 어떤 역할이 있는지. `AgentSpec.agents`로 들어간다 |
| `channel` | `HumanChannel \| None` | `None` | 주면 `inbox` **와** `ask` 두 도구를 동시에 추가하고 `mcp_servers`를 설정한다 |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → `Read` 제거 |
| `glance` | `bool` | `True` | `"Bash"`를 추가하고 `AgentSpec.glance`를 설정한다. **실제로 무엇을 실행할 수 있는지는 `delegate_guard`가 통제**하지, 여기서 정해지지 않는다 |
| `model` | `str \| None` | `None` | 모델 |
| `effort` | `str \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | `None` | 턴 수 상한 |
| `max_budget_usd` | `float \| None` | `None` | [budget](glossary.md#预算) 상한 |
| `permission_mode` | `str` | **`"acceptEdits"`** | 권한 모드. **이 기본값에 주의** —— 이걸 `clarify()`/`judge()`에 넘기면 그 두 역할의 보호가 벗겨진다 |
| `compact` | `CompactPolicy \| None` | `None` | 주면 `Runtime`이 `no_summary`로 강제 변경하지 않는다 |
| `hooks` | `dict[str, Any] \| None` | `None` | 추가 hook. `workbench_hooks`와 병합된다 |
| `env` | `dict[str, str] \| None` | `None` | 추가 환경 변수 |

만들어진 `AgentSpec`에서 고정된 세 항목: `delegate_only=True`, `agents=workers`,
`workbench`는 `AgentSpec`의 기본값 `True` 유지.

소스에는 **`disallowed_tools`로 "조율만 하고 손대지 않기"를 구현하지 말라**고 명시돼 있다 —— 그건 session 단위라
subagent의 `Bash`/`Write`까지 함께 막아버린다. [`AgentSpec`](#agentspec)의 경고 참조.
올바른 방법은 여기처럼 `delegate_only=True` + `allowed_tools`를 주지 않는 것이고,
그다음 [`delegate_guard`](#delegate-guard)가 `agent_id`로 main thread만 가로막게 하는 것이다.

`channel`을 주면 **두 도구가 함께 온다**. 선택이 아니다: MCP server를 붙이는 순간 둘 다 존재하고,
`allowed_tools`는 배타적이지 않으므로 목록에 넣든 말든 호출된다. 무인 운용 시 `ask`는 매번 `timeout_s`를 꽉 채우고 멈춘다 ——
그런 상황에는 `HumanChannel(timeout_s=0)`을 쓴다.

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

실제로 일하는 [subagent](glossary.md#subagent) 정의를 만든다. 앞의 두 인자는 위치 인자다.
반환값은 SDK의 `AgentDefinition`이며, 그대로 `coordinator(workers={...})`에 넣으면 된다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `description` | `str` | 필수 | **coordinator가 사람을 고르는 근거** —— "어떤 일을 이 역할에 준다"를 분명히 쓴다 |
| `prompt` | `str` | 필수 | 이 역할의 system prompt. `discipline=True`면 `f"{prompt}\n\n{WORKER_RULES}"`로 이어붙인다 |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | worker는 다운그레이드되면 안 된다 |
| `effort` | `str \| int \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | `None` | SDK의 **`maxTurns`**(카멜케이스)로 들어간다 |
| `permission_mode` | `str \| None` | `None` | SDK의 **`permissionMode`**(카멜케이스)로 들어간다 |
| `skills` | `list[str] \| None` | `None` | 사용 허용할 skill 목록 |
| `discipline` | `bool` | `True` | `WORKER_RULES`의 보고 규율을 붙일지 여부 |
| `isolate` | `bool` | `False` | [isolation](glossary.md#隔离) 표식을 달아 `isolated()`를 태운다. **`AgentDefinition`의 필드가 아니다** |

`isolate=True`는 workspace가 git 저장소일 것을 요구한다. 아니면 `Agent` 도구가 곧바로 `"not in a git repository"`를 낸다.
**조용히 퇴화하지 않는다.** 게다가 이 표식은 Python 속성이라 —— `AgentDefinition`에 `dataclasses.replace()`를 하면
사라져 isolation이 조용히 무효가 된다.

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

[clarifier](glossary.md#确认者)를 만든다: 손대기 전에 요구를 분명히 묻고, 일은 하지 않고 질문만 하며, 마지막에 정확히 네 절을 출력한다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | 필수 | 역할 이름, 위치 인자 |
| `channel` | `HumanChannel` | 필수 | 질문 채널, 위치 인자 |
| `instructions` | `str` | `""` | 보충 지시. `CLARIFIER_RULES` 뒤에 붙는다 |
| `can_read` | `bool` | `True` | `True`면 `Read` `Glob` `Grep` `WebFetch` `WebSearch`를 추가 |
| `model` | `str \| None` | `None` | 모델 |
| `effort` | `str \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | `None` | **턴 수 무제한** |
| `max_budget_usd` | `float \| None` | `None` | budget 상한 |

만들어진 `AgentSpec`: `allowed_tools = [channel.tool_name] + (읽기 가능할 때 그 다섯 개)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False`(쓰기 도구가 없으니 인덱스가 의미 없다),
`permission_mode`는 `AgentSpec`의 기본값 `"default"`를 그대로 물려받는다.
**`Write` / `Edit` / `Bash` / `Agent`도 없고, `inbox`도 없다**(coordinator와 다르다).

!!! warning "`max_turns`를 작게 잡으면 무제한 질문이 빈말이 된다"
    질문 한 번이 한 턴이다. `max_turns=16`은 "많아야 열몇 개까지 물어봐"라는 뜻이고, 채널에 적힌 "턴 수 상한 없음"은 즉시 무효가 된다.

    질문을 풀어주려면 **두 곳을 동시에** 풀어야 한다: `HumanChannel.max_asks`(기본값이 이미 `None` = 무제한)와
    `max_turns`(기본값이 이미 `None`).

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

[judge](glossary.md#判定者)를 만든다: 출발 전에 목표를 설정하거나, 매 라운드가 끝난 뒤 그 라운드를 판정하거나 둘 중 하나다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | 필수 | 역할 이름, 위치 인자 |
| `channel` | `HumanChannel` | 필수 | 질문 채널, 위치 인자 |
| `instructions` | `str` | `""` | 보충 지시. `JUDGE_RULES` 뒤에 붙는다 |
| `can_run` | `bool` | `False` | `True`면 화이트리스트에 `Bash`를 추가하고, `whitelist_guard`도 `Bash`를 통과시키되 `Write`/`Edit`는 계속 막는다 |
| `model` | `str \| None` | `None` | 모델 |
| `effort` | `str \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | `None` | 턴 수 상한 |
| `max_budget_usd` | `float \| None` | `None` | budget 상한 |

만들어진 `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (`can_run`일 때) `["Bash"]`,
`workbench=False`, 나머지는 `clarify()`와 같다. **`Write` / `Edit` / `Agent`도 없고, `inbox`도 없다.**

**트레이드오프**: `can_run=True`면 판정이 더 단단해지지만(검수 명령을 실제로 돌릴 수 있다), 그 대가로 judge가 작업 공간을 변경할 수 있게 된다 ——
`Bash` 자체가 파일을 쓸 수 있기 때문이다. 절대적으로 중립인 판정을 원하면 켜지 마라.

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

[oracle](glossary.md#旁路顾问)을 만든다: run이 아직 돌고 있을 때 "지금 어디까지 왔냐"고 물으면, 최근 이벤트와 workbench를
한 번 보고 답한다. **그가 한 말은 그 run의 컨텍스트로 들어가지 않는다.**

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | 역할 이름, 위치 인자 |
| `instructions` | `str` | `""` | 보충 지시. `ORACLE_RULES` 뒤에 붙는다 |
| `model` | `str \| None` | `None` | 모델 |
| `effort` | `str \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | **`12`** | 기본적으로 브레이크가 걸려 있다 |
| `max_budget_usd` | `float \| None` | **`0.5`** | 기본적으로 브레이크가 걸려 있다. 이건 "지나가며 한마디 묻는 것"이지 통제 불능이 되면 안 된다 |

만들어진 `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]`(**channel 없음** —— 묻지 않고 답하기만 한다),
`workbench=True`(**다섯 역할 중 coordinator가 아니면서 workbench를 켜는 유일한 역할** —— 산출물과 노트를 읽으러 가야 하기 때문이다).

### 다섯 벌의 규칙 텍스트 {#rules}

다섯 상수 모두 `__all__`에 있으므로, 바로 `import`해서 읽고 이어붙이고 고칠 수 있다.

| 상수 | 누구에게 주입되나 | 주입 방식 | 요점 |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | 너는 "Claude Code를 쓸 줄 아는 사람"이지 worker가 아니다; 파일을 쓰거나 코드를 고치거나 테스트를 돌릴 수 없다; `Bash`는 "한 번 훑어보는" 정도이고 결과는 곧 낡는다; **[task brief](glossary.md#任务书)에는 이번 작업에만 해당하는 것만 쓴다**; 아직 전달해야 할 유일한 규칙은 "workbench 위치 + 긴 산출물은 `artifacts/`에 + 답변에는 경로만"; 단계적 동작을 하나 끝낼 때마다 `inbox`를 한 번 확인한다; `ask`는 블로킹이므로 진짜 갈림길에서만 쓴다 |
| `WORKER_RULES` | `worker()` | subagent의 `prompt` **뒤에** 이어붙임 | 답변 형식은 **결론 / 근거 / 산출물 / 미검증**, 30줄을 넘기지 않는다; 파일 내용·명령 출력·로그·diff 원문 붙여넣기 금지; 시행착오 과정 재서술 금지; 손대기 전에 `.flower/scripts/`를 먼저 본다. **"긴 산출물은 `artifacts/`에"는 일부러 쓰지 않았다** —— 실제 경로는 `Workbench`가 만들기 때문에 하드코딩하면 틀린다 |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | 일은 하지 않고 요구만 분명히 묻는다; **횟수 제한 없음, 분명해질 때까지 묻는다**; 사람이 없을 수 있으니 타임아웃되면 스스로 판단해 「未知与假设」에 적는다; **정확히 네 절**을 출력한다; 코드를 쓰지 말고 파일 내용을 붙이지 마라 |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | 두 가지 중 하나만 한다. **목표 설정**: 각 항목은 그 자리에서 검증 가능해야 하고, 목록 길이는 실패 방식의 개수가 정한다, **경계는 판정 항목이 아니다**, 검증 불가능한 항목은 끝에 `[此环境无法验证:原因]`을 붙인다. **이번 라운드 판정**: **정확히 세 절**을 출력하고, 판정 대상은 **소스가 아니라 산출물**이며, "다 했다"는 말은 기본적으로 믿지 않는다. "못 했다"와 "여기서는 검증할 수 없다"는 서로 다른 결론이며, 후자는 **절대로 통과 판정을 내릴 수 없다** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | 너는 우회로다; 그 run은 아직 돌고 있고, 너는 끊지도 참여하지도 않는다; **읽기 전용**; 답하면 곧 버려지고, 네 말은 그 run의 컨텍스트로 들어가지 않는다; 손에 있는 것은 "최근 이벤트 창"과 "workbench"뿐이다; 먼저 보고 답하고, 못 답하겠으면 못 답하겠다고 말하고, 짧게 |

---

## agent 정의 {#agent-定义}

소스: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec`은 특정 agent의 완전한 선언이고, `build_options`는 그것을 SDK의 `ClaudeAgentOptions`로 컴파일한다.
[역할 팩토리](#角色工厂)가 내놓는 것이 바로 `AgentSpec`이다 —— 팩토리 밖의 조합이 필요하면 직접 구성하면 된다.

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `name` | `str` | 필수 | 역할 이름. `Runtime.run`의 기본 `step_name`이자, `whitelist_guard`의 거부 문구에서 자칭으로 쓰인다 |
| `instructions` | `str` | 필수 | 도메인 지시. **Claude Code 기본 system prompt 뒤에 [append](glossary.md#叠加)되며, 대체가 아니다** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **승인 면제 목록이지 배타적 화이트리스트가 아니다** —— 모델은 여기 없는 도구도 호출할 수 있다. 배타성은 [`whitelist_guard`](#whitelist-guard)가 담당한다 |
| `disallowed_tools` | `list[str]` | `[]` | **session 단위.** 아래 경고 참조 |
| `model` | `str \| None` | `None` | 모델 |
| `effort` | `str \| None` | `None` | 사고 강도 |
| `max_turns` | `int \| None` | `None` | 턴 수 상한 |
| `max_budget_usd` | `float \| None` | `None` | [budget](glossary.md#预算) 상한 |
| `permission_mode` | `str` | `"default"` | 권한 모드 |
| `agents` | `dict[str, Any] \| None` | `None` | subagent 정의 표, 값은 `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP server 표. `HumanChannel.mcp_servers()`를 그대로 넣는다 |
| `hooks` | `dict[str, Any] \| None` | `None` | 추가 hook. `Runtime`이 `merge_hooks`로 자기 것과 병합한다 |
| `compact` | `CompactPolicy \| None` | `None` | 주면 `Runtime`이 `no_summary`로 강제 변경하지 않는다 |
| `env` | `dict[str, str]` | `{}` | 자식 프로세스에 주입할 환경 변수. `compact.env()`가 여기에 update된다 |
| `glance` | `bool` | `False` | coordinator가 "한 번 훑어보는" `Bash`를 직접 돌리도록 허용. 무엇을 통과시킬지는 [`is_ephemeral`](#is-ephemeral)이 정하고, 결과는 `EphemeralPolicy`가 만료로 표시한다 |
| `workbench` | `bool` | `True` | workbench 인덱스를 이 agent의 system prompt에 주입할지 여부. **쓰기 도구가 없는 역할은 꺼야 한다**(`clarify()` / `judge()`는 기본값이 `False`) |
| `delegate_only` | `bool` | `False` | 조율만 하고 손대지 않음. `True`면 `Runtime`이 `delegate_guard`를 달고, `whitelist_guard`는 **달지 않는다** |

!!! warning "`disallowed_tools`는 session 단위라 subagent까지 함께 막힌다"
    실측 에러 원문: `"Bash is disabled for this session, in subagents as well as here"`.
    즉 coordinator가 손대지 못하게 하려고 `disallowed_tools=["Bash"]`를 썼다면, 배정한 worker도 명령을 못 돌린다 ——
    run 전체가 못 쓰게 된다.

    "조율만 하고 손대지 않기"는 `delegate_only=True` + `allowed_tools`를 주지 않는 방식으로 하고,
    [`delegate_guard`](#delegate-guard)가 `agent_id`로 main thread만 가로막게 하라.

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

`AgentSpec`을 SDK의 `ClaudeAgentOptions`로 컴파일한다. `Runtime._attempt`가 내부에서 호출하는 것이 바로 이것이고,
직접 SDK를 구동할 때(`Runtime`을 쓰지 않을 때)도 여기로 들어온다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `spec` | `AgentSpec` | 필수, 위치 인자 | 컴파일할 선언 |
| `cwd` | `str \| Path \| None` | `None` | `None`이 아닐 때만 `cwd`에 기록 |
| `session_store` | `SessionStore \| None` | `None` | `None`이 아닐 때만 `session_store`와 `session_store_flush`에 기록 |
| `resume` | `str \| None` | `None` | 어느 session을 이어서 돌릴지 |
| `fork` | `bool` | `False` | `fork_session`으로 들어간다. **`if resume:` 안에 중첩돼 있다** |
| `resume_at` | `str \| None` | `None` | `resume_session_at`으로 들어간다. **역시 `if resume:` 안에 중첩돼 있다** |
| `use_plugin` | `bool` | `True` | `True`이고 `PLUGIN_DIR`이 존재하면 → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | 추가로 권한을 주는 디렉터리. **workbench가 작업 공간 밖에 있으면 반드시 줘야 한다** |
| `flush` | `str` | `"eager"` | `session_store_flush`로 들어간다 |
| `prelude` | `str` | `""` | `instructions` 뒤에 덧붙는 한 덩어리(workbench 인덱스가 여기로 간다) |

매핑 관계:

| 만들어지는 option 키 | 값 |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | `spec`에서 그대로 |
| `setting_sources` | `[]`(portable) 또는 `["project"]` |
| `plugins` | 저장소 루트의 `plugin/` 디렉터리가 존재할 때만 |
| `cwd` / `add_dirs` | 비어 있지 않을 때만 기록 |
| `session_store` / `session_store_flush` | `session_store`가 `None`이 아닐 때만 기록 |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | 각각 비어 있지 않을 때만 기록 |
| `env` | `dict(spec.env)`에 이어 `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **`resume`이 참일 때만 유효** |

`PLUGIN_DIR`은 저장소 루트의 `plugin/`이다(`flower/core/agent.py` 기준 세 단계 위). pip으로 설치하면 이 디렉터리가 없을 수도 있어서
코드가 `is_dir()`로 확인한다.

!!! warning "`fork=True`인데 `resume`을 주지 않으면 조용히 무효가 된다"
    `fork_session`과 `resume_session_at`은 모두 `if resume:` 안에 중첩돼 있다 —— `resume`을 주지 않으면 전혀 적용되지 않고,
    **에러도 나지 않는다.** 마찬가지로 `Runtime.run(resume_at=...)`은 `resume`을 줬을 때만 작동하는데,
    **`Workflow`는 `resume_at`을 절대 넘기지 않는다**: 메시지 단위 롤백을 하려면 `Runtime.run`을 직접 호출하는 수밖에 없다.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

auto-[compact](glossary.md#压缩)의 스위치 패널이고, 산출물은 자식 프로세스에 주입할 환경 변수 묶음이다.
compact 알고리즘 자체는 harness 바이너리 안에 있어 바꿀 수 없고, 바꿀 수 있는 건 "발동 여부"뿐이다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = 아무것도 설정하지 않음, 임계값 = 윈도 − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1`(`/compact`까지 함께 끔). **그 밖의 값은 `ValueError`를 던진다.** 조용히 무시하지 않는다 |
| `window` | `int \| None` | `None` | `None`이 아니면 → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. CLI 쪽 제한은 100k–1M이며, 100k 미만으로 설정하면 100k로 올라간다 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `env` | `() -> dict[str, str]` | 환경 변수를 만든다. **잘못된 `mode`는 생성 시점이 아니라 여기서 `ValueError`를 던진다** —— 이 메서드는 `build_options`가 호출하므로, 에러는 `Runtime.run`에서 드러난다 |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

컨텍스트가 거의 찼을 때 compact 대신 "[handoff document](glossary.md#交接书)를 쓰고 새 session으로 갈아타는" 정책 객체.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 끄면 auto-compact로 되돌아간다 |
| `window` | `int` | `default_window()` | 모델의 컨텍스트 윈도를 얼마로 볼지 |
| `headroom` | `int` | `50_000` | 여유를 얼마나 남길지. 이유: auto-compact는 윈도 −33k에서 발동하므로 handoff는 그 전에 끝나야 하고, "handoff를 쓰는 것" 자체도 한 턴이 더 필요하다 |
| `max_generations` | `int` | `8` | 한 step에서 최대 몇 세대까지 갈아탈지. **폭주 방지 브레이크지 용량 계획이 아니다** |

| 속성 | 타입 | 설명 |
|---|---|---|
| `at` | `@property -> int` | handoff 임계값 `max(10_000, window - headroom)`. **10k 하한이 있다** —— 더 낮으면 handoff조차 쓸 수 없다 |
| `warn_at` | `@property -> int` | 임박 알림 지점 `max(1_000, at - 20_000)`, 세대마다 한 번만 보낸다 |

!!! warning "`window`를 작게 잡으면 무한 handoff로 돈을 태운다"
    `at`이 해당 역할의 **시작 바닥**(coordinator 실측 약 34k)보다 낮으면, 새 session이 입을 떼자마자 선을 넘는다. 그런데
    **handoff는 재시도 횟수를 소모하지 않으므로**(`attempt -= 1`) 무한 공회전이 된다. 유일한 브레이크가 `max_generations=8`이고,
    거기에 걸리면 `error`가 진단 문구로 바뀌어 `window`를 키우거나 handoff를 끄라고 알려준다.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

환경 변수 `ANTHROPIC_MODEL` 또는 `ANTHROPIC_DEFAULT_OPUS_MODEL`의 **모델명 문자열**로 컨텍스트 윈도를 추측한다:

| 조건 | 반환 |
|---|---|
| 이름에 독립된 `1m` 토큰이 있음(정규식 `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| 이름에 `haiku`가 포함됨 | `200_000` |
| 그 외(**두 변수 모두 설정되지 않은 경우 포함**) | `1_000_000` |

**기본값은 공격적인 쪽을 택한다.** 크게 잡는 것은 치명적 오류가 아니다: API가 `prompt is too long`으로 되돌려주고,
`Runtime`이 이 신호를 인식해(내부의 `is_overflow`) 그 자리에서 handoff한다 —— 다만 그 세대의 handoff는 강등된 버전이다.

---

## 문서 {#文书}

소스: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

네 개의 dataclass. 모두 "모델의 답변 한 덩어리를 고정된 몇 절로 파싱하고 디스크에 쓰는" 일을 한다. 공통 형태:
`parse()`로 파싱, `missing()` / `complete()`로 빠짐 확인, `to_markdown()`은 사람용,
`prompt_block()`은 하류 모델용, `write()` / `load()`는 spill과 되읽기.

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

[brief](glossary.md#需求确认书). **정확히 네 절**이고 순서는 고정이다.
`goal` → `accept` → `bounds` → `unknowns`, 중국어 절 이름은 각각 「目标」「验收标准」「边界」「未知与假设」.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `goal` | `str` | `""` | 목표 |
| `accept` | `str` | `""` | 검수 기준 |
| `bounds` | `str` | `""` | 경계 |
| `unknowns` | `str` | `""` | 미지와 가정 |
| `path` | `Path \| None` | `None` | spill 위치. `compare=False`라 동등 비교에 참여하지 않는다 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `missing` | `() -> list[str]` | 빠진 절의 **중국어 이름**. 그대로 표시할 수 있다 |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | 모델 답변에서 네 절을 파싱한다. **먼저 펜스 코드 블록을 벗겨내고**, 파싱되지 않는 절은 비워 둔다 |
| `to_markdown` | `() -> str` | 머리말 메타 정보가 붙은 완전한 문서. 빈 절은 `"(未填)"`로 쓴다 |
| `prompt_block` | `() -> str` | 하류에 먹이는 압축판. **비어 있지 않은 절만** 포함하고 메타 정보는 없다 |
| `write` | `(path: str \| Path) -> Path` | 부모 디렉터리를 만들고, 디스크에 쓰고, `self.path`를 resolve된 경로로 설정한 뒤 반환 |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | 파일이 없거나 `OSError`면 `None`. **`"(未填)"` 자리표시자를 빈 문자열로 되돌린다** |

파싱 규칙(실수하기 쉬운 지점 모음):

- 펜스를 벗길 때 **닫히지 않은 ``` 또는 `~~~`를 만나면 거기서부터 통째로 버린다** —— 실측상 clarifier가 코드 전체를 답변에 붙여 넣는다.
  모델 출력이 잘리면 뒤쪽 절이 전부 파싱되지 않아 `complete()`가 `False`가 되고, gate가 되돌려 다시 시킨다.
- 제목 정규식은 `## 目标` / `**目标**` / `目标:` / `3. 边界`를 허용하고, 제목 뒤에 본문이 바로 붙는 것도 허용한다.
- 별칭 표는 길이 내림차순으로 컴파일한다. 그러지 않으면 "未知"가 "未知与假设"를 먼저 먹어버린다.
- 같은 이름의 절이 여러 번 나오면 **내용이 있는 첫 번째를 취한다**.
- brief를 손으로 편집할 때 `to_markdown()`의 `"(未填)"` 자리표시자 문구를 그대로 베껴 두면 그 절은 여전히 누락으로 취급된다.

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

[handoff](glossary.md#换代) 시 쓰는 [handoff document](glossary.md#交接书), 다섯 절.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `doing` | `str` | `""` | 무엇을 하고 있는지. **필수** |
| `decided` | `str` | `""` | 무엇이 정해졌는지 |
| `deadends` | `str` | `""` | 막힌 길 |
| `next` | `str` | `""` | 다음 단계. **필수** |
| `scene` | `str` | `""` | 현장 |
| `step` | `str` | `""` | 문서 머리말에만 쓰이고 **파싱에는 관여하지 않는다** |
| `path` | `Path \| None` | `None` | spill 위치 |

**필수는 `doing`과 `next` 두 절뿐이다** —— "막힌 길"을 비워둘 수 없게 강제하면 모델이 지어내게 된다.

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `missing` | `() -> list[str]` | **필수인 두 절만 확인한다** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | 본문에 강등 표식 `[降级:交接没写成]`이 붙어 있는지 |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | `Brief`의 절 분할기를 재사용 |
| `to_markdown` | `() -> str` | 빈 절은 `"(空)"`로 쓴다 |
| `prompt_block` | `() -> str` | **머리말에서 인계받는 쪽에 "너는 인계받는 중"이라고 명시**해, 배경을 다시 사람에게 물으러 가지 않게 한다 |
| `write` | `(path) -> Path` | `Brief.write`와 동일 |
| `load` | `@classmethod (path) -> Handoff \| None` | `Brief.load`와 동일 |

같은 모듈 안에 **export되지 않지만 의미상 핵심인** 멤버 셋: `is_overflow(*texts)`는 `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` 등을 매칭해 "치명적 오류"를 "즉시 handoff"로 바꾼다; `HANDOFF_PROMPT`는
**현재 session이 스스로** handoff를 쓰게 하는 프롬프트다(`{used}` `{window}` 두 자리표시자를 포함하며, **새 역할이 아니다** ——
그 컨텍스트를 가진 건 자기 자신뿐이다); `degraded(step, prompt, *, why="")`는 handoff를 쓰지 못했을 때 기계적으로 한 벌 조립하며,
`scene`에는 원래 작업의 앞 **1200**자를 채운다.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

[goal guard](glossary.md#目标看守)의 목표 + 판정 목록.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `statement` | `str` | `""` | 목표 진술 |
| `checks` | `list[str]` | `[]` | 판정 목록, 한 줄에 한 항목 |
| `path` | `Path \| None` | `None` | spill 위치 |

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | `checks` 중 `[此环境无法验证:…]`가 표시된 항목. **목표를 세우는 그 순간 이미 통과할 수 없도록 정해진 것들** |
| `missing` | `() -> list[str]` | `statement`가 비어 있지 않고 **동시에** `checks`도 비어 있지 않아야 한다 |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks`는 한 줄에 한 항목이고, `-` / `*` / `1.` 기호는 자동으로 제거된다 |
| `to_markdown` | `() -> str` | 목록이 비면 `"(空)"`로 쓴다 |
| `prompt_block` | `() -> str` | 하류에 먹이는 압축판 |
| `write` / `load` | `Brief`와 동일 | spill과 되읽기 |
| `amend` | `(extra: str) -> Goal` | **덮어쓰지 않고 덧붙인다**: `statement` 뒤에 `"\n\n(已修改)" + extra`를 이어붙이고 `self`를 반환 |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

[judge](glossary.md#判定者)가 한 라운드를 판정한 결과. **정확히 세 절**: 결론 / 이유 / 미통과.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, 파싱되지 않으면 `""` |
| `reason` | `str` | `""` | 이유 |
| `failed` | `list[str]` | `[]` | 통과하지 못한 목록 항목 |

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | 결론이 파싱되었는지 여부. **`ok=False`는 반드시 "미달성"으로 처리해야 하며, 달성으로 봐서는 안 된다** |
| `parse` | `@classmethod (text) -> Verdict` | 아래 참조 |
| `feedback` | `() -> str` | worker에게 되돌려 보내는 말: "무엇이 모자란지"만 주고 해법은 주지 않는다 |

`parse`의 인식 순서:

1. 먼저 제목 절에서 「结论」/「判定」을 취한다.
2. 제목 절이 없으면, 전체를 strip한 뒤 `fullmatch(r"1|true")` → 달성; `fullmatch(r"0|false")` → 미달성.
3. 아니면 결론 텍스트에서 상태어 표(**긴 단어가 앞**)를 따라 처음 걸리는 단어를 찾는다.
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」은 전부 `unreachable`로 귀속된다** ——
   실제로 당한 적이 있다: 목표 플랫폼은 macOS인데 Linux 컨테이너에서 돌고 있었고, judge가 소스의 분기만 보고 통과로 판정했다.
4. 여전히 없으면 → 고립된 `\b1\b`를 찾아 달성, `\b0\b`를 찾아 미달성.
5. 전부 걸리지 않으면 → `state=""`, `ok=False`.

`unreachable`과 `not_yet`은 **서로 다른 결론이다**: 전자는 "멈추고 사람에게 묻는" 경로로 가지, "한 라운드 더"가 아니다.

---

## hook 계층 {#hook}

소스: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

이 계층은 flower의 **실행 경계**다. 어떤 도구를 메인 스레드가 만지면 안 되는지, 지나치게 긴 결과를 어떻게 자를지, 어떤 역할을 독립 worktree로 보낼지가
전부 SDK hook으로 강제되며, **프롬프트에 의존하지 않는다**. 이유는 단순하다 — 프롬프트는 권고일 뿐이고 모델은 안 들을 수 있다. 시스템 프롬프트에
"worktree를 쓰지 마라"라고 명시해도 `isolate_guard`의 주입은 그대로 먹히는 것을 실측했다(모델이 넘긴 값은 `None`, 실제로 반영된 값은 `'worktree'`).

익스포트는 아홉 개: `HookMatcher`를 반환하는 guard 팩토리 다섯 개(`whitelist_guard`는 `None`을 반환할 수 있다), 조립기 하나, 병합기 하나, 격리 표시 함수 둘.
직접 붙일 필요는 없다 — [`Runtime`](#runtime)이 `AgentSpec`에 따라 자동으로 장착한다. 수동으로 붙이는 것은 SDK를 직접 구동할 때
(`Runtime`을 거치지 않을 때)만 필요하다.

**메인 스레드 판정은 하나의 함수로 통일한다**: `_is_main_thread(data) = not data.get("agent_id")` ——
subagent의 tool-lifecycle hook 데이터에는 `agent_id`가 들어 있고, [메인 스레드](glossary.md#主线程)에는 없다.
"메인 스레드만 막는" 모든 guard가 이 한 줄에 의존한다.

도구 그룹 상수(모듈 레벨, 익스포트되지 않지만 기본 matcher를 결정한다):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### 조견표: 어떤 guard가 어떤 SDK 이벤트에 붙는가 {#hook-速查表}

| 함수 | SDK hook 이벤트 | matcher | 차단 대상 | 반환값 | 누가 장착하나 |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` 중 **`allowed_tools`에 없는** 것들 | **메인 스레드만** 금지 도구를 호출할 때 | `permissionDecision: "deny"` + 사유 | `Runtime._attempt`, **`spec.delegate_only is False`일 때만** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit`(`tools=`로 변경 가능) | **메인 스레드만** 직접 손대는 경우. `allow_glance=True`이면 `is_ephemeral()`을 통과한 `Bash`는 허용 | `deny` + "subagent를 파견하라" | `workbench_hooks(delegate_only=True)`, **`Runtime`에 워크벤치가 있을 때만** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input`에 `cwd`도 `isolation`도 없고, `subagent_type`이 `isolated()`로 표시되어 있을 때 | `permissionDecision: "allow"` + `updatedInput`(`isolation="worktree"` 주입) | `workbench_hooks`, **`agents`에 표시된 역할이 있을 때만** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path`가 `workbench.root` 안에 있을 때 | `{}`(부수효과로 `workbench.refresh()`) | `workbench_hooks`, 항상 장착 |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | `tool_response` 안의 ≥ `threshold` 문자인 **문자열 필드**. spill 디렉터리 자체를 읽는 것은 허용 | `updatedToolOutput`(스필 + 한 줄 포인터 + 앞부분 400자) | `workbench_hooks`, **`spill_threshold`가 참일 때만** |

**이 표에서 읽어낼 수 있는 핵심 추론**: `Runtime(workbench=False)`이면 `workbench_hooks` 전체가 장착되지 않는다.
그리고 `delegate_only=True`인 코디네이터에서는 `whitelist_guard`도 건너뛴다 — **메인 스레드에 벽이 하나도 없다**.
자세한 내용은 [Runtime](#runtime)의 경고를 보라.

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**`allowed_tools`가 직접 손대는 그 네 개 도구에 대해 진짜 배타적으로 작동하게 만든다.**

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `allowed` | `list[str] \| None` | 필수, 위치 인자 | 보통 `spec.allowed_tools`를 그대로 넘긴다 |
| `role` | `str` | `"这个角色"` | 거부 문구에서의 자칭. `Runtime`은 `spec.name`을 넘긴다 |

- **`PreToolUse`에 붙는다.** matcher는 `"|".join(banned)`이고, `banned` = `Bash` `Write` `Edit` `NotebookEdit`
  중 `allowed`에 없는 것들이다.
- 걸리면 `permissionDecision: "deny"`. 문구의 요지: "XX에는 YY가 없다. **이건 의도된 것이지 설정 누락이 아니다.**
  결론을 네 응답 본문에 써라. 프레임워크는 거기서 가져간다 — 다른 표현으로 우회하려 하지 마라."
- **이번 세션의 메인 스레드만 막고** subagent는 통과시킨다 — subagent의 도구는 `AgentDefinition.tools`가 정한다.
- 막을 도구가 없으면 **`None`**을 반환한다(예: `worker()`처럼 도구를 전부 갖는 역할). 호출 측이 이를 보고 장착 여부를 정한다.

**이것이 반드시 있어야 하는 이유**: `allowed_tools`는 **승인 면제 목록이지 배타적 화이트리스트가 아니다.** 실측 증거 두 가지 —
목표를 정하는 판정자가 `Bash`를 11번 실행했고, $0.1짜리 프로브에서
`allowed_tools=["Read"]`인 agent가 `Write`/`Bash`를 멀쩡히 호출했다.
그래서 `clarify()` / `judge()`가 "쓰기 도구가 없다"는 것은 **이 hook 덕분이지** 화이트리스트 자체 때문이 아니다.

장점은 `allowed_tools`에서 파생된다는 점이다. 그래서 `judge(can_run=True)`는 자동으로 `Bash`를 남기면서 여전히
`Write`/`Edit`을 막는다 — 별도 스위치가 필요 없다.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**메인 스레드가 직접 손대면 → 거부하고 길을 알려준다.**

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. 리스트가 아니라 정규식 문자열이다 |
| `allow_glance` | `bool` | `False` | `True`이면 `tool_name == "Bash"`이고 [`is_ephemeral(command)`](#is-ephemeral)가 참일 때 통과시킨다 |

- **`PreToolUse`에 붙고**, matcher는 그대로 `tools`다.
- 메인 스레드가 이 네 도구를 호출하면 → deny. 사유에는 **다음에 무엇을 해야 하는지**를 적어준다: `Agent` 도구로 subagent를 파견하고,
  과제에 목표와 인수 기준을 명확히 쓰고, 긴 산출물은 `.flower/artifacts/`에 쓰고 응답에는 경로와 결론만 담으라고 요구하라.
- subagent는 전부 통과.

`whitelist_guard`와의 차이는 **표현**이다. 둘 다 같은 도구들을 막지만 이쪽은 "사람을 파견하라"고 말하므로 더 맞는다.
그래서 `delegate_only=True`인 역할에는 이 하나만 장착한다. 중복으로 붙이면 모델이 모순되는 지침 두 개를 받게 된다.

`allow_glance=True`의 통과 판정과 "결과가 잘려나갈지 여부"는 **같은 함수**([`is_ephemeral`](#is-ephemeral))다 —
통과 집합은 만료 집합과 반드시 같아야 하며, 한쪽을 고치면 다른 쪽도 고쳐야 한다.

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

임계값을 넘는 도구 결과를 **그 자리에서 [스필](glossary.md#落盘)**하고 컨텍스트에는 한 줄 포인터만 남긴다 — 컨텍스트가 꽉 찬 뒤에
돌아가서 압축하는 방식이 아니다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workbench` | `Workbench` | 필수, 위치 인자 | 스필 디렉터리는 `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | 몇 문자를 넘어야 스필하는가 |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False`(기본) = subagent의 결과도 스필한다 |

- **`PostToolUse`에 붙고**,
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <잘린 것>}}`을 반환한다.
- 스필 파일명은 내용의 `sha256` 앞 16자리 + `.txt`이고, 컨텍스트에는 한 줄 포인터 + **앞부분 400자**로 대체된다.
- `updatedToolOutput`은 **원래 도구의 출력 구조를 유지해야 한다.** 그래서 dict 안의 너무 긴 **문자열 필드**만 교체하고,
  **list는 절대 건드리지 않는다**(안에 이미지 블록이 있을 수 있다). 구조가 맞지 않으면 거부된다(원문 그대로, 오류는 나지 않는다).
- **스필 파일 자체를 읽을 때는 반드시 통과시켜야 한다** — 안 그러면 "`Read`로 그것을 읽어라"는 빈말이 된다. 읽어온 전문이 다시 스필되어 무한 루프가 된다.
  실제로 부딪혔고, 모델이 다섯 가지 표현으로 우회를 시도했다.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

[워크벤치](glossary.md#工作台)에 뭔가를 쓰면 `INDEX.md`를 갱신해서, 다음 agent가 시작하자마자 그게 있다는 걸 알게 한다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workbench` | `Workbench` | 필수, 위치 인자 | 판정 범위이자 갱신 대상 |

**`PostToolUse`에 붙고** matcher는 `"Write|Edit"`이다. `tool_input["file_path"]`를 resolve했을 때
`workbench.root` 안이면 `workbench.refresh()`를 호출한다. **항상 `{}`를 반환한다** — 아무것도 바꾸지 않고 부수효과만 있다.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

역할에 따라 subagent에게 독립 git worktree를 배정해 [격리](glossary.md#隔离)를 구현한다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | 필수, 위치 인자 | 역할 표. `subagent_type`이 표시되어 있는지 조회하는 데 쓴다 |
| `on_inject` | `Any` | `None` | 선택 콜백. `on_inject(subagent_type, description)` 형태로 호출된다 |

**`PreToolUse`에 붙고** matcher는 `"Agent"`다. 세 조건이 동시에 성립할 때만 주입한다: `tool_name == "Agent"`,
`tool_input`에 **`cwd`도 `isolation`도 없음**, `subagent_type`에 해당하는 역할이 `isolated()`로 표시됨.
성립하면 `permissionDecision: "allow"` + `updatedInput`(`isolation`을 `"worktree"`로 설정)을 반환한다.

`isolation`과 `cwd`는 `Agent` 도구에서 **상호 배타적**이다 — 모델이 스스로 `cwd`를 지정했다면 그것을 존중한다.
"격리할지 말지"는 **역할의 속성**이지 전역 스위치가 아니며, 파견할 때마다 판단하는 것도 아니다. 격리가 필요 없는 역할에는 단 한 바이트도 붙지 않는다.

**격리를 켜면 [워크벤치](glossary.md#工作台)를 저장소 밖으로 옮겨야 한다.** 격리된 agent는 공유 checkout에 쓸 수 없으므로,
워크벤치는 `home=`으로 저장소 바깥을 가리켜야 한다. `starter_flow(isolate=True)`는
`<ws>.parent/.flower-<ws.name>`을, `Runtime(workbench=True)`은 `<run_dir>/workbench`를 쓴다 —
둘 다 저장소 밖이지만 **같은 디렉터리는 아니다.** 섞어 쓰지 마라.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

subagent 정의에 "독립 작업 공간이 필요하다"는 표시를 달고, 그 표시를 다시 읽는다.

| 함수 | 인자 | 기본값 | 설명 |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | 필수 | 표시할 정의. **반환되는 것은 동일한 객체다** |
| | `flag: bool` | `True` | 위치 인자. `False` = 표시 제거 |
| `wants_isolation` | `agent: AgentDefinition \| None` | 필수 | `None`도 받으며, 그때는 `False`를 반환한다 |

표시는 `object.__setattr__`로 붙인 Python 쪽 속성 `_flower_isolate`이며, **dataclass 필드가 아니다** —
SDK는 `asdict()`로 직렬화하면서 선언된 필드만 인식하므로 이 표시가 CLI 쪽으로 새지 않는다(실측 완료).

**대가**: `AgentDefinition`에 `dataclasses.replace()`를 하면 이 표시가 사라지고 격리가 조용히 무력화된다.

`worker(isolate=True)`는 내부적으로 `isolated()`를 쓴다.

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

워크벤치에 필요한 hook들을 한 번에 장착한다. `Runtime._attempt`가 호출하는 것이 바로 이것이다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workbench` | `Workbench` | 필수, 위치 인자 | `index_guard`와 `spill_guard`에 전달된다 |
| `delegate_only` | `bool` | `True` | `True`일 때만 `delegate_guard`를 장착 |
| `spill_threshold` | `int \| None` | `4000` | 참일 때만 `spill_guard`를 장착 |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | 그중 **하나라도** `isolated()`로 표시되어 있으면 `isolate_guard`를 추가 |
| `allow_glance` | `bool` | `False` | `delegate_guard(allow_glance=)`로 그대로 전달 |

산출:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`,
  표시된 역할이 있으면 → `isolate_guard(agents)` 추가.
- `PostToolUse`: 항상 `[index_guard(workbench)]`, `spill_threshold`가 참이면 →
  `spill_guard(workbench, threshold=spill_threshold)` 추가.
- **빈 리스트인 이벤트 키는 제거된다.** 빈 list를 반환하지 않는다.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

이벤트 이름별로 여러 hook 설정을 **이어 붙인다**.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | 가변 인자 | 몇 그룹이든. `None` 그룹은 건너뛴다 |

`extend`를 쓰고 **중복 제거는 하지 않는다** — 같은 guard를 두 번 넘기면 두 번 장착된다. `Runtime`은 이것으로 `spec.hooks`,
`workbench_hooks(...)`, `whitelist_guard`를 하나로 합친다.

---

## 워크벤치 {#工作台}

소스: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

디스크에 쓰는 작업 디렉터리. 하위 디렉터리 세 개 + 인덱스 하나. 인덱스는 **system prompt에 주입되므로**
agent는 매 턴 자기 손에 무엇이 있는지 안다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `workspace` | `Path` | 필수, 위치 인자 | 작업 공간. `__post_init__`에서 resolve한다 |
| `dirname` | `str` | `".flower"` | 워크벤치 디렉터리 이름, `workspace` 기준 상대 경로 |
| `max_index_entries` | `int` | `40` | **`prompt_block()`에만 적용된다**: system prompt에 주입되는 그 단락에서 종류별로 최대 몇 개까지 나열할지. 초과분은 "…외 N개" 한 줄로 접는다. `INDEX.md` 자체는 제한 없이 전부 나열한다 |
| `home` | `Path \| None` | `None` | 주면 그것을 `root`로 쓰고 **`dirname`은 무시한다.** `None`이 아니면 역시 resolve한다 |

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `root` | `@property -> Path` | `home`이 있으면 그것, 없으면 `workspace / dirname` |
| `external` | `@property -> bool` | `root`가 `workspace` **바깥**인지. 격리 모드에서는 `True`여야 한다 |
| `scripts` | `@property -> Path` | `root / "scripts"`. 두 번 실행할 스크립트 |
| `artifacts` | `@property -> Path` | `root / "artifacts"`. 2000자를 넘는 긴 산출물 |
| `notes` | `@property -> Path` | `root / "notes"`. 핵심 결정, 결정 하나당 파일 하나 |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | 모델에게 보여줄 경로: 작업 공간 안이면 상대 경로, 밖이면 절대 경로 |
| `ensure` | `() -> Workbench` | 디렉터리 세 개를 mkdir하고 `self`를 반환(체이닝 가능: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(표시 경로, 설명, 바이트 수)`. `rglob("*")`로 재귀하며 `.`으로 시작하는 파일은 건너뛴다 |
| `refresh` | `() -> str` | `INDEX.md`를 다시 쓰고 그 내용을 반환 |
| `prompt_block` | `() -> str` | **system prompt에 주입되는 단락.** 의도적으로 짧게 만들었다 — 매 턴 들어가기 때문이다 |

스크립트 자기소개 형식: 앞 8행 안의 `# desc: 한 줄 설명`(`//`와 `--` 주석 기호도 인식),
없으면 첫 번째 비어 있지 않은 주석이나 docstring 첫 줄로 대체(100자에서 자름).

`prompt_block()`이 주입하는 세 가지 규칙:

1. 두 번 실행할 스크립트는 `scripts/`에 쓰고 첫 줄에 `# desc:`를 단다.
2. **2000자**를 넘는 산출물은 `artifacts/`에 쓰고, 대화에는 경로와 결론만 준다.
3. 핵심 결정은 `notes/`에 쓴다. 결정 하나당 파일 하나.

`external=True`이면 `prompt_block()`은 "절대 경로로 접근하라"는 문장을 한 줄 더 넣는다.

**인덱스는 subagent가 상속받지 못한다.** 이것은 세션 레벨의 `system_prompt.append`를 타는데, subagent는 자기만의
system prompt를 갖는다(실측 $0.2461). 그래서 "긴 산출물은 `artifacts/`에 쓰라, 워크벤치는 어디에 있다"는 이 두 가지는
[코디네이터](glossary.md#协调者)가 [작업 지시서](glossary.md#任务书)에서 전달해야 한다 — **그것이 유일한 통로이지** 중복이 아니다.
`WORKER_RULES`에는 **일부러 이 항목을 넣지 않았다**: 실제 경로는 `Workbench`가 생성하므로 하드코딩하면 틀린다.

---

## 세션 스토어 {#会话存储}

소스: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

3단 상속: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime`은 **항상 가장 바깥 층을 쓰고**, 세 층의 정책은 생성자 인자로 제어한다.

각 층이 한 가지씩 맡는다: 디스크 저장, 크기와 가치에 따른 [트림](glossary.md#裁剪), "오류인가 아닌가"에 따른 [프룬](glossary.md#剪除).
트림과 프룬 모두 **`load()`** 시점(즉, resume가 히스토리를 모델에 다시 먹이는 순간)에 일어나며, SQLite의 원본 기록은 단 한 바이트도 건드리지 않는다.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

SDK의 `SessionStore` 프로토콜을 구현한다. 테이블 세 개 `entries` / `meta` / `summaries`.
store key는 `project_key/session_id[/subpath]` — **하위 agent의 transcript는 subpath로 구분한다.**

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `path` | `str \| Path` | 필수, 위치 인자 | 데이터베이스 파일. 연결은 `check_same_thread=False`로 한다 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `append` | `async (key, entries) -> None` | uuid 기준 멱등 중복 제거(먼저 이미 저장된 것을 걸러내고, 다음에 배치 내 중복을 걸러낸다). 배치 전체를 재생할 때는 **mtime을 진행시키지 않고 fold summary도 중복 실행하지 않는다.** 메인 transcript(`subpath is None`)만 summary에 참여한다 |
| `projects` | `() -> list[str]` | DB에 실제로 존재하는 `project_key`. **SDK는 cwd에서 이것을 유추하므로, 조회 전에 이것으로 확인하라. 추측하지 마라** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **동기이고 payload를 읽지 않는다.** meta 한 행만 조회한다. "같은 경로에서 이어가기"용 — 존재하지 않는 세션을 resume하면 자식 프로세스가 뜰 때까지 기다려야 터진다 |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | 마지막 턴에 모델이 실제로 본 컨텍스트 크기. 못 찾으면 `0`. 마지막 `scan`개만 역순으로 훑는다. `input + cache_read + cache_creation` 세 항목을 모두 센다(`input_tokens`만 보면 심각하게 과소평가된다) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | seq 순 정렬. 행이 없으면 `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | 메인 transcript만 |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | 세션 요약 목록 |
| `delete` | `async (key) -> None` | 메인 transcript를 지울 때 **하위 agent의 것도 연쇄 삭제**해 고아를 막는다 |
| `list_subkeys` | `async (key) -> list[str]` | 이 세션에 딸린 하위 transcript 목록 |
| `close` | `() -> None` | 연결을 닫는다 |

내부의 `_next_mtime`이 **엄격한 단조성**을 보장한다 — `list_sessions`와 summary sidecar가 이 시계를 공유하기 때문에,
그렇지 않으면 SDK의 staleness 빠른 경로가 오판한다.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 최근 N개의 `tool_result`는 원문 유지 |
| `min_chars` | `int` | `2000` | 짧은 결과는 자를 가치가 없다 |
| `spill_dirname` | `str` | `".flower/spill"` | **`workspace` 기준 상대 경로이며 작업 공간 안이어야 한다** — 아니면 agent의 `Read`가 닿지 못한다 |
| `enabled` | `bool` | `True` | `Runtime(trim=False)`이면 여기가 `False`가 된다 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | 본문을 대체하는 포인터 한 줄을 생성 |

**두 개의 spill 디렉터리는 같은 것이 아니다.** `spill_guard`는 `<workbench.root>/spill/`에 떨어뜨리고(작업 공간 밖일 수 있다),
`TrimPolicy.spill_dirname`은 `<workspace>/.flower/spill/`에 떨어뜨린다(**반드시 작업 공간 안**).
각각 "그 자리에서 자르기"와 "resume 때 자르기"에 대응하며, 디렉터리가 다른 것은 의도된 것이다. 하나로 합치지 마라.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

[일회성 명령](glossary.md#一次性命令)의 결과 만료 정책.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 끄면 만료 표시를 아예 하지 않는다 |
| `keep_recent` | `int` | `6` | 최근 N개는 면제. **`TrimPolicy`의 20보다 훨씬 작다** |
| `max_chars` | `int` | `2000` | 넘으면 건너뛰고 `TrimPolicy`의 보관에 맡긴다 |
| `text` | `str` | 시그니처 참조 | 대체 문구. `{cmd}`와 `{age}` 두 개의 자리표시자 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | `text`에 끼워 대체 본문을 생성 |

**`Bash` 도구의 결과에만 작용하며**, 명령이 일회성 명령 화이트리스트에 맞아야 한다. **`Read`는 여기 해당하지 않는다** —
파일 내용은 시간이 흐른다고 오도할 정도로 왜곡되지 않는다. 만료된 내용은 **스필하지 않고** 그냥 버린다.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Bash 명령 하나가 [일회성 명령](glossary.md#一次性命令)인지 판정한다.
**`delegate_guard`의 통과 판정과 트림의 만료 판정이 이 함수 하나를 공유한다** — 코디네이터가 직접 실행할 수 있는 명령 집합은
결과가 만료로 표시되는 집합과 같아야 한다. 통과시키되 트림하지 않으면 만료된 `git status`가 컨텍스트를 영구히 차지하면서 오도하고,
트림하되 통과시키지 않으면 코디네이터가 `ls` 하나 때문에 subagent를 파견해 4.3k의 시작 비용으로 수십 자를 얻는다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `cmd` | `str` | 필수, 위치 인자 | 전체 명령행 |

판정 순서:

1. 비었거나 전부 공백 → `False`.
2. 명령 치환(`$(`, 백틱, `<(`, `>(`)이나 "상태를 바꾸는" 표현에 걸리면 → `False`.
3. 안전한 리다이렉션(`2>&1`, `&> /dev/null` 같은 것)을 제거한 뒤에도 `>`나 `<`가 남으면 → `False`.
4. `&&` / `||` / `;` / `|`를 제거한 뒤에도 단독 `&`가 남으면(백그라운드 실행) → `False`.
5. `&&` / `||` / `;` / `|`로 쪼갠 뒤 **각 구간이 모두 화이트리스트에 걸려야 한다.**

화이트리스트 동사 대분류: 읽기 전용 `git` 하위 명령(`status` `diff` `log` `show` `branch` `rev-parse` 등), 
디렉터리와 시스템 정보(`ls` `pwd` `df` `du` `date` `whoami` `env` 등), 프로세스와 컨테이너
(`ps` `top` `lsof` `docker ps` `kubectl get` 등), 파일 보기(`cat` `head` `tail` `wc` `stat` `find` `tree`),
경로 조회(`which` `whereis` `command -v` `type`), 텍스트 처리(`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` 등).

동사가 화이트리스트에 있어도 다음 표현들은 차단된다: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `awk` 안의 `system(`과 `print >`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

첫 버전은 복합 명령을 일괄 거부했는데, **실측 결과 glance가 완전히 무력화됐다**(코디네이터의 시도 세 번이 전부 차단됨).
그래서 구간별 판정으로 바꿨다.

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `path` | `str \| Path` | 필수 | 데이터베이스 파일 |
| `workspace` | `str \| Path` | 필수 | 스필 디렉터리의 기준 |
| `policy` | `TrimPolicy \| None` | `None` | 주지 않으면 기본 `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 주지 않으면 기본 `EphemeralPolicy()` |

공개 속성: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

`load()`의 순서: `super().load()` → `last_report` 비우기 → `ephemeral.enabled`이면 `expire()` →
`policy.enabled`이면 `trim()`. **`enabled=False`이면 해당 단계 전체를 건너뛴다.**

| 메서드 | 설명 |
|---|---|
| `expire(entries)` | 만료된 시효성 `Bash` 결과의 **본문만 바꾸고 블록은 남긴다.** 명령은 직전 assistant 메시지의 `tool_use`에서 찾는다. `isCompactSummary` / `isMeta`는 건너뛴다. `max_chars`를 넘으면 건너뛴다(`trim`에 맡긴다). 마지막 `keep_recent`개는 면제. `last_report["expired"]`를 기록한다 |
| `trim(entries)` | `>= min_chars`인 `tool_result` 본문을 `<workspace>/<spill_dirname>/<sha256 앞 16자리>.txt`로 스필하고, 블록 내용을 포인터로 교체한다. 마지막 `keep_recent`개는 면제. `last_report`의 `cleared` / `kept` / `chars_saved`를 기록한다 |

**순수 텍스트만 자른다**: `image` / `document` 블록은 그대로 남긴다.

**구조적 레드라인 두 가지**: `tool_result` **블록 자체는 반드시 있어야 하고** content만 바꿀 수 있다(하나라도 빠지면
"Missing Tool Result Block"). `isCompactSummary` 항목은 건드리면 안 된다.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

`store.last_report`를 한 줄의 중국어로 렌더링한다. UI 로그용.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | 필수, 위치 인자 | 서브클래스 `PruningSessionStore`도 받는다 |

출력은 세 가지: 아무 동작 없음 → `"未裁剪"`, 만료만 있음 → `"N 个时效性结果标记为过期"`,
그 외에는 `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`이고 여기서 X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | 합성된 API 오류 메시지(연결 끊김의 잔해)를 제거 |
| `neutralize_interrupts` | `bool` | `True` | 중단으로 남은 `tool_result`를 중립적 설명으로 교체 |
| `interrupt_text` | `str` | 시그니처 참조 | 중립적 설명의 문구 |
| `keep_denials` | `int` | `1` | 최근 N번의 거부된 도구 호출을 유지 |

`keep_denials`의 이유: 거부된 호출은 아예 실행된 적이 없어 결과에 정보가 없지만 자리는 적지 않게 차지한다(실측 한 번에 273자 =
거부 문구 93자 + **죽은 명령 원문 180자**). 더 중요한 건 **그것이 오도한다는 점이다** — 실측에서 코디네이터가
"Bash를 직접 쓰지 마라"를 몇 건 읽은 뒤에는 허용되는 `git status`조차 시도하지 않게 되어, 학습된 무기력을 익혔다.
**기본값이 0이 아니라 1인 이유**: 가장 최근의 거부 하나는 모델이 같은 턴에서 차단된 같은 명령을 반복 재시도하는 것을 막아준다.

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**`Runtime`의 기본 store.**

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `path` | `str \| Path` | 필수 | 데이터베이스 파일 |
| `workspace` | `str \| Path` | 필수 | 스필 디렉터리의 기준 |
| `policy` | `TrimPolicy \| None` | `None` | 트림 정책 |
| `prune` | `PrunePolicy \| None` | `None` | 프룬 정책 |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 만료 정책 |

공개 속성은 부모 클래스의 것 외에 세 개가 더 있다: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()`(먼저 `expire` + `trim`) → `self.prune(entries)`. `prune`은 세 가지를 한다:

1. **너무 오래된 거부된 호출을 제거한다**: harness의 구조적 표식 `toolDenialKind == "permission-rule"`로 판정하며
   (거부 문구를 매칭하는 것보다 신뢰할 수 있다), 마지막 `keep_denials`개는 남기고 나머지는 `tool_use` **와** `tool_result`
   블록을 함께 제거한다. 같은 assistant 메시지에 `tool_use`가 여러 개 있으면 **해당되는 것만 제거한다.** 아니면
   "Missing Tool Result Block"이 된다. 텍스트와 thinking 블록은 남긴다.
2. **합성된 API 오류 메시지를 제거한다.** SQLite에는 그대로 남고, 다시 먹이지 않을 뿐이다.
3. **중단으로 남은 `tool_result`를 중립적 설명으로 교체한다** — 본문만 바꾸고 항목은 제거하지 않는다.

**유일한 구조적 레드라인**: transcript는 `parentUuid` 단일 체인이므로, 하나를 제거하면 그 자식을 가장 가까운 살아 있는 조상에 이어 붙여야 한다.
내부의 `relink`에 넘기는 `entries`는 **반드시 완전한 목록(제거할 것들 포함)이어야 하고** 필터링은 relink가 스스로 한다 —
호출 측이 먼저 걸러내고 넘기면 체인이 거기서 끊겨 앞선 히스토리가 전부 사라진다(**이미 밟았다: 제거 대상이 끝에 있을 때는 드러나지 않지만
중간에 있으면 터진다**).

**인자 순서가 부모 클래스와 다르다**: 부모는 `(path, workspace, policy, ephemeral)`, 자식은
`(path, workspace, policy, prune, ephemeral)` — **네 번째 위치 인자가 `ephemeral`에서 `prune`으로 바뀌었으므로**
위치로 넘기면 조용히 어긋난다. 무조건 키워드로 넘겨라.

---

## 복원력 {#韧性}

소스: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

네트워크가 끊기면 실패로 종료하지 않고 매달려 기다린다. 익스포트 네 개: 정책 dataclass 하나 + 단독으로 쓸 수 있는 탐지 함수 세 개.

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 끄면 어떤 장애도 재시도하지 않는다 |
| `max_attempts` | `int` | `6` | **첫 시도 포함** |
| `base_delay` | `float` | `4.0` | 백오프 기준값, 초 |
| `max_delay` | `float` | `120.0` | 백오프 상한, 초 |
| `probe_timeout` | `float` | `5.0` | 프로브 1회 타임아웃 |
| `probe_interval` | `float` | `15.0` | 프로브 사이의 대기 시간 |
| `max_offline_wait` | `float` | `3600.0` | 최대 대기 시간, 기본 1시간 |
| `retry_unknown` | `bool` | `True` | 분류되지 않는 오류를 재시도할지 |
| `resume_prompt` | `str` | 시그니처 참조 | 이어서 실행할 때 하는 말. **의도적으로 오류 세부를 담지 않는다** — 모델은 "중단됐다, 이어서 하라"만 알면 되지 `ENOTFOUND`인지 503인지 알 필요가 없다 |

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)`에 `0.75 + random()*0.5`를 곱한다(±25% 지터) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`이거나, `kind == "unknown"`이면서 `retry_unknown`일 때 |
| `wait_online` | `async (notify=None) -> bool` | 네트워크가 돌아올 때까지 매달려 기다린다. 돌아오면 `True`, `max_offline_wait`를 넘기면 `False`. `notify`는 `(str) -> None` 콜백이며 **처음 도달 불가일 때**와 **복구됐을 때** 각각 한 번씩 보낸다 |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

오류 텍스트를 `"transient"` / `"fatal"` / `"unknown"` 세 가지로 분류한다.

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `text` | `str \| None` | 필수, 위치 인자 | 오류 메시지 원문. 비어 있으면 `"unknown"` 반환 |

**fatal을 먼저 판정하고 transient를 나중에 판정한다** — 401 같은 텍스트에는 `connection`이라는 단어가 자주 섞여 있어서, 순서를 뒤집으면 영원히 기다리게 된다.

| 분류 | 무엇에 걸리나 |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

탐지할 호스트와 포트. `ANTHROPIC_BASE_URL`을 따르며 기본값은 `https://api.anthropic.com`,
포트 기본값은 `80`(http) 또는 `443`.

**자체 게이트웨이를 쓸 때는 반드시 그것을 탐지해야 한다** — `api.anthropic.com`이 된다고 게이트웨이가 된다는 뜻은 아니다.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| 인자 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `host` | `str` | 필수, 위치 인자 | 호스트명 |
| `port` | `int` | 필수, 위치 인자 | 포트 |
| `timeout` | `float` | `5.0` | 초 |

**DNS(`getaddrinfo`) + TCP 핸드셰이크만 한다.** HTTP를 보내지 않고, 자격증명도 싣지 않으며, **비용이 들지 않는다.** 어떤 예외든 도달 불가로 친다.

---

## 이벤트와 인터랙션 {#事件与交互}

소스: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[이벤트](glossary.md#事件)는 SDK 메시지 스트림을 평탄화한 안정적인 구조다. **[인터랙션 레이어](glossary.md#交互层)는
`Event`만 알고, SDK 타입은 하나도 import 하지 않는다** —— UI를 바꿔도 코어를 건드리지 않게 하는 경계다. [인터랙션 레이어 교체](../guide/interaction.md)를 보라.

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `kind` | `EventKind` | 필수 | 아래 표 참고 |
| `text` | `str` | `""` | 본문 |
| `tool` | `str` | `""` | 도구 이름. `tool_call`에만 있음 |
| `payload` | `dict[str, Any]` | `{}` | 구조화된 부가 정보 |
| `raw` | `Any` | `None` | 원본 SDK 객체. 더 깊이 파고들 때 사용 |

`__str__`: `tool_call`이면 `f"[{tool}] {text}"`, 아니면 `text`, `text`가 비었으면 `f"<{kind}>"`.
그래서 `print(ev)`만으로 바로 읽힌다.

`EventKind`는 총 **15** 개다:

| kind | 발신 주체 | 설명 |
|---|---|---|
| `text` | `normalize` | assistant 본문 |
| `thinking` | `normalize` | 사고 블록 |
| `tool_call` | `normalize` | 도구 호출. `text`는 `file_path` / `command` / `pattern` 요약, 200자에서 자름 |
| `tool_result` | `normalize` | 도구 결과. `text`는 500자에서 자름, payload에 `tool_use_id` / `is_error` |
| `task` | `normalize` | 세 종류의 Task 메시지. `text`는 메시지 클래스 이름 |
| `system` | `normalize` | 나머지 시스템 메시지. `text`는 subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`. payload에 `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | 합성 API 오류 메시지. payload에 `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **본문은 입력이지 모델 산출물이 아니다**. 그래서 `StepResult.text`에 들어가지 않는다 |
| `unknown` | `normalize` | 식별하지 못한 것 |
| `retry` | `Runtime` | 재시도 통지 |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | payload의 `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | 질문. **사람이 먼저 한 말도 여기에 실린다** |

**마지막 네 개는 `normalize()`가 만들지 않는다.**

모든 assistant / user 이벤트의 `payload`에는 다음이 함께 실린다:

| 키 | 타입 | 설명 |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | `subagent`가 참일 때만 존재 |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **[핸드오프](glossary.md#换代) 판정의 유일한 출처**이자, 롱호라이즌 런에서 가장 보여야 할 숫자 |

**`ask`라는 kind는 "질문"과 "사람이 먼저 한 말"을 동시에 실어 나른다.** 후자는 `payload["kind"] == "mail"`이고,
**`options` / `remaining`이 없다**. UI는 반드시 `payload.get("kind")`를 먼저 판별한 뒤 렌더링 방식을 정해야 한다.
그러지 않으면 한마디 말을 답변 대기 중인 질문으로 착각해 매달아 둔다.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

SDK 메시지 하나를 0개에서 N개의 `Event`로 평탄화한다.

| 매개변수 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `message` | `Any` | 필수, 위치 인자 | 임의의 SDK 메시지 객체 |

핵심 분기:

- **합성 API 오류 메시지**(`isApiErrorMessage=True` 또는 `model == "<synthetic>"`) → 단일
  `Event("error", payload={"synthetic": True})`. **이건 의도된 것이다** —— 그러지 않으면 연결 끊김 문구가 본문 취급을 받아
  `StepResult.text`에 들어가고, 다음 스텝으로 전달된다.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<요약>, tool=block.name, payload={"id", "input"})`.
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`.
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`.
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`.

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

사람에게 던지는 질문 하나.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `id` | `str` | 필수 | 답변할 때 이걸로 특정한다 |
| `question` | `str` | 필수 | 질문 본문 |
| `options` | `list[str]` | `[]` | 선택지. 사람은 고르지 않고 직접 입력해도 된다 |
| `asked_at` | `float` | `time.time()` | 질문 시각 |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | 답변 본문 |

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `waited_s` | `@property -> float` | 얼마나 기다렸는지 |
| `event` | `(remaining: int = 0) -> Event` | `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)`를 만든다 |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

**프로세스 내 MCP server**(도구 두 개) + UI가 쓰는 메서드 묶음. 모델 쪽에서는
`mcp__human__ask`와 `mcp__human__inbox`만 보인다. 생성자 인자는 전부 keyword-only.

| 매개변수 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | **푸시** 모드의 출구. 이걸 주면 `Workflow.run`이 다시 배선하지 않는다 |
| `max_asks` | `int \| None` | `None` | **횟수 무제한**. 숫자를 주면 하드 쿼터, `0` = 질문 금지(완전 자동 / CI). 초과 시 도구가 **곧바로 거절하고, 블로킹하지 않는다** |
| `timeout_s` | `float \| None` | `1800.0` | 30분. `None` = 무한 대기; **`<= 0` = 기다리지 않음, 모든 질문이 즉시 불발** |
| `log_path` | `str \| Path \| None` | `None` | 질의응답을 디스크에 **추가**한다. 컨텍스트를 먹지 않는다 |
| `amend_path` | `str \| Path \| None` | `None` | 사람이 런 도중에 한 말을 이 파일에 추가한다(보통은 요구사항 확인서). **디스크에 쓰지 않으면 스텝 경계를 넘지 못한다** —— 다음 스텝은 새 세션이고, 얼어붙은 파일만 읽는다 |
| `over_budget_text` | `str` | 모듈 상수 | 쿼터 초과 시 모델에게 돌려주는 말 |
| `timeout_text` | `str` | 모듈 상수 | 타임아웃 시 모델에게 돌려주는 말 |
| `declined_text` | `str` | 모듈 상수 | 건너뛰었을 때 모델에게 돌려주는 말 |

공개 속성: 생성자 인자와 같은 이름의 여덟 개, 그리고 `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]`(**UI 콜백이 던진 예외가 여기 모인다. 런을 끊지 않는다**).

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | 그대로 `AgentSpec.mcp_servers`에 넣으면 된다. **키 이름이 server 이름과 반드시 일치해야 하므로** 여기서 함께 내준다 |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | 매달려 사람을 기다린다. **`CancelledError` 외에는 절대 예외를 던지지 않는다** —— 아무도 답하지 않는 것도 하나의 답이고, `ask.state`로 구분한다 |
| `send` | `(text: str) -> Mail \| None` | 사람이 먼저 한마디 한다. **어느 스레드에서든 호출 가능**. agent를 끊지 않으며, 내부에서 자동으로 `amend()`를 호출한다 |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | `amend_path`에 추가한다. 실제로 썼는지를 반환한다(경로 미설정, 빈 텍스트, `OSError`는 전부 `False`) |
| `pending_mail` | `() -> list[Mail]` | 아직 수거되지 않은 mail |
| `remaining` | `@property -> int` | 몇 번 더 물을 수 있는지. **`max_asks=None`일 때 `-1`을 반환한다**. 0도 무한대도 아니다 |
| `pending` | `() -> list[Ask]` | 지금 답을 기다리며 매달린 질문들 |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | **풀** 모드용. 타임아웃이면 `None`, 취소되면 예외 |
| `answer` | `(ask_id: str, text: str) -> bool` | 답변. `False` = 그 질문은 이미 대기 중이 아니다(타임아웃 / 이미 답함) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | 건너뛰고, 모델이 스스로 판단하게 한다 |
| `transcript` | `() -> str` | 질의응답 기록의 markdown |

**두 가지 수신 방식 중 하나를 고른다**: **푸시** —— `HumanChannel(on_event=...)`로 생성; **풀** —— `await channel.next_ask()`.
`Workflow.run`은 `channel.on_event is None`일 때만 자동으로 배선하므로, 직접 넘겼다면 덮어쓰이지 않는다.

**스레드 간 호출**: `answer` / `decline` / `send`는 내부적으로 `loop.call_soon_threadsafe`를 거친다.
웹 백엔드 / TUI 입력 스레드에서 바로 호출하는 게 일반적이다.

세 가지 "0 / None"의 의미가 각각 다르니 헷갈리지 마라: `max_asks=None` = 무제한, `max_asks=0` = 질문 금지;
`timeout_s=None` = 무한 대기, `timeout_s<=0` = 즉시 타임아웃; `remaining`은 `max_asks=None`일 때 `-1`.

익스포트되지 않지만 반환값에 등장하는 `Mail`은 dataclass이며, 필드는 `id` / `text` / `sent_at` / `taken`이다.

---

## 계보 {#血缘}

소스: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

"어떤 스텝이 어떤 세션을 썼는지"를 프로세스 간에 기록한다. [연속성](glossary.md#接续)은 이걸로 지난번에 어디까지 갔는지 찾는다.
파일은 `<run_dir>/lineage.json`.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `path` | `Path` | 필수 | 계보 파일 경로 |
| `workspace` | `Path` | 필수 | 워크스페이스. `__post_init__`에서 resolve 한다 |
| `steps` | `dict[str, str]` | `{}` | 스텝 이름 → `session_id` |
| `woke` | `int` | `0` | 웨이크 횟수 |

| 멤버 | 시그니처 | 설명 |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | `<run_dir>/lineage.json`을 읽는다. **파일이 없거나, 읽을 수 없거나, `workspace` 필드가 맞지 않으면 전부 빈 것을 반환하고 오류를 내지 않는다** |
| `remember` | `(step: str, session_id: str) -> None` | 매핑을 기억하고 **즉시 디스크에 쓴다**. step이 비었거나 sid가 비면 그냥 반환 |
| `bump` | `() -> int` | 웨이크 카운트 +1, 디스크 기록, 새 값 반환(처음 실행이면 `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | 계보 파일 + `extra`를 `<into>/<YYYYmmdd-HHMMSS>/`로 **이동**하고, `steps` / `woke`를 0으로 만든다. **이동이지 삭제가 아니다** |

디스크 기록은 `tmp.replace(path)`로 원자적 치환한다. `OSError`는 조용히 삼킨다 —— 기록 실패가 이번 런을 데려가서는 안 된다.

**`workspace`는 가드다**: SDK의 `project_key`는 워크스페이스 경로에서 유도되므로, 디렉터리를 복사해 옮기면 예전 `session_id`를 찾을 수 없다.
그래서 경로가 맞지 않으면 없는 것으로 친다.

`Workflow.run`은 계보를 적재할 때 각 레코드마다 `runtime.has_session(sid)`로 아직 저장소에 있는지 검증하고, 살아 있을 때만 쓴다 ——
계보 파일이 `sessions.db`보다 오래 살아남을 수 있기 때문이다.

---

## 최소 동작 예제 {#示例}

다섯 개 전부 그대로 실행된다. 전제: `claude-agent-sdk`가 설치되어 있고 `ANTHROPIC_API_KEY` 또는 `ANTHROPIC_AUTH_TOKEN`이 사용 가능할 것
(아니면 `Runtime(...)` 생성 시점에 `RuntimeError`를 던진다).

### agent 하나로 한 스텝 {#示例-单-agent}

최소 골격: `AgentSpec` 하나를 선언하고, `Runtime` 하나를 만들고, `await rt.run(...)`, `StepResult`를 읽는다.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`Runtime`의 인자는 **전부 keyword-only**다. `rt.run()`의 `spec`과 `prompt`는 위치 인자이고 나머지는 keyword-only.
`AgentSpec`은 기본값이 `allowed_tools=["Read", "Glob", "Grep"]`, `delegate_only=False`이므로
`Runtime`이 자동으로 [`whitelist_guard`](#whitelist-guard)를 달아 `Bash`/`Write`/`Edit`/`NotebookEdit`를 전부 막는다.

### 코디네이터 + 워커 {#示例-协调}

손을 쓰지 않는 [코디네이터](glossary.md#协调者)가 실제로 일하는 [워커](glossary.md#执行者) 하나를 데리고 있다.
이것이 flower가 컨텍스트를 아끼는 첫 번째 층이다.

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True 는 반드시 줘야 한다: delegate_guard 는 workbench_hooks 안에 달리므로,
    # 워크벤치를 켜지 않으면 코디네이터의 Bash/Write 를 막는 hook 이 하나도 없다.
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`worker()`의 앞 두 인자는 위치 인자다: `description`(코디네이터가 사람을 고를 때 쓴다), `prompt`(그 워커의 system prompt,
뒤에 `WORKER_RULES`가 자동으로 붙는다). `coordinator()`의 앞 세 개도 위치 인자다: `name`, `instructions`, `workers`.

### Workflow 직접 작성 {#示例-workflow}

두 스텝. 뒤 스텝이 앞 스텝의 결과를 자기 prompt에 주입한다 —— 싸고, 격리되며, 세션을 공유하지 않는다.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # 새 세션: prompt 안에 있는 것만 먹는다
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 새 세션 + 이전 스텝 결과를 prompt 에 주입(싸고, 오염 방지)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # 같은 세션으로 이어서 말하고 싶으면 resume_from="造句"; 분기하려면 fork=True 를 추가
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text(reduce 를 주지 않았을 때)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # on_fail="stop" 일 때 어느 스텝에서 실패했는지


asyncio.run(main())
```

`Step`의 앞 세 필드(`name` / `spec` / `prompt`)는 위치 인자이고, `Workflow`의 `steps`도 그렇다.
`Workflow.run(runtime, *, on_event=None, on_step=None)` —— `runtime`은 위치 인자, 두 콜백은 keyword-only.
**`continuous=True`가 기본값임에 주의하라**: 같은 `run_dir` + 같은 `workspace`로 두 번째 실행하면
`resume_from=None`인 스텝도 지난번 그 세션을 이어서 말한다.

### 목표 가드 한 겹 붙이기 {#示例-目标}

먼저 [판정자](glossary.md#判定者)에게 목표와 판정 체크리스트를 확정하게 하고, 그다음 일하는 스텝이 판정을 받게 한다 ——
통과하지 못하면 피드백을 들고 다시, 최대 세 라운드.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = 완전 자동: 모든 질문이 즉시 불발되고, 사람을 기다리는 척하지 않는다
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds 는 **총 라운드 수**다: rounds=3 → retries=2 → 최대 세 라운드까지 일한다
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # goal_step 의 prompt 는 ctx["确认需求"](brief_key 기본값)를 읽는다.
        # clarify_step 이 없으면 직접 한 부 넣어줘야 한다. 아니면 "(没有确认书)" 만 보게 된다.
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: Goal 객체
    print(ctx["_verdict"])     # VERDICT_KEY: 가장 최근 Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: 몇 라운드 돌았는지
    print(ctx.get("_aborted")) # StepAbort 의 사유(달성 불가이고 응답할 사람도 없을 때)


asyncio.run(main())
```

`with_goal`은 `gate` / `on_reject` / `retries`만 갈아 끼우고, 나머지 필드는 `dataclasses.replace`로 그대로 가져간다.
판정자는 **독립 세션**이다: `gate` 내부에서 따로 `rt.run(judger, ..., step_name=f"{label}#{轮次}")`를 호출하며,
`resume`은 항상 `None`이다.

### 인터랙션 레이어 교체 {#示例-交互层}

터미널을 웹 / TUI / HTTP로 바꾸려면 두 가지만 고치면 된다: `Event`를 렌더링하는 함수, 그리고 질문을 가져오는 코루틴.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """把 Event 渲染成你自己的 UI —— 这是唯一需要换的东西。"""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" 이면서 mail 이 아닌 것은 아래 answerer 가 처리한다(풀 방식)


async def answerer(ch: HumanChannel) -> None:
    """拉式取提问。换成 Web 后端 / HTTP 服务时,这个协程是唯一要改的地方。"""
    while True:
        ask = await ch.next_ask()          # timeout 이 없으면 계속 기다린다
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # 또는 ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime 은 workflow 가 만들어 둔 워크벤치를 쓴다 —— 따로 하나 더 만들지 마라
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

푸시와 풀은 **둘 중 하나만** 고른다: 푸시는 `HumanChannel(on_event=...)`로 생성하는 것, 풀은 `await channel.next_ask()`.
`Workflow.run`은 `channel.on_event is None`일 때만 자동으로 배선하므로, 직접 `on_event`를 넘겼다면 덮어쓰이지 않는다.
`answer()` / `decline()` / `send()` / `interrupt()`는 **모두 다른 스레드에서 호출할 수 있다**.

---

## 함정과 실수하기 쉬운 지점 {#陷阱}

밟게 되는 순서대로 나열했고, 모듈 순서가 아니다. 각 항목은 실측에 근거한다.

### 조립 {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = 메인 스레드에 벽이 하나도 없다.**
   `delegate_guard`는 워크벤치가 있을 때만 달리고, `whitelist_guard`는 `delegate_only=True` 때문에 건너뛴다.
   코디네이터를 쓰면 워크벤치를 켜라. 자세한 건 [Runtime](#runtime).
2. **워크벤치 위치는 두 군데다. 잘못 조합하지 마라.** `Runtime(workbench=True)`는 `<run_dir>/workbench`에 놓이고,
   `Workbench(ws)`의 기본값은 `<ws>/.flower`다. 직접 `brief_path`를 조합할 때는 후자를 따라 써야 한다.
   **확인서는 A 디렉터리에 쓰이고 주입되는 인덱스는 B 디렉터리를 훑는데, 오류도 나지 않는다.**
   올바른 방법: workflow가 스스로 `Workbench(...).ensure()`를 해서 `Workflow.workbench`에 걸고,
   **같은 객체**를 `Runtime(workbench=wb)`에 넘긴다.
3. **`allowed_tools`는 배타적 화이트리스트가 아니라 승인 면제 목록이다.** 모델은 목록에 없는 도구도 그대로 호출할 수 있다.
   `clarify()` / `judge()`의 "쓰기 도구 없음"은 [`whitelist_guard`](#whitelist-guard)라는 hook에 의존한다.
   그리고 `coordinator()`의 기본값은 `permission_mode="acceptEdits"`다 —— 이 값을
   `clarify()` / `judge()`에 넘기는 순간 보호가 사라진다.
4. **`disallowed_tools`는 세션 단위다.** subagent의 동명 도구까지 함께 금지시킨다.
5. **워크벤치 인덱스는 subagent로 들어가지 않는다.** "긴 산출물은 `artifacts/`에 쓴다"는 코디네이터가 태스크 브리프에서 다시 말해줘야 하고,
   그게 유일한 통로다.
6. **`Runtime(...)`은 자격 증명이 없으면 생성 단계에서 `RuntimeError`를 던진다.** `run()`까지 기다리지 않는다.
7. **`Runtime.run_id`는 인스턴스마다 유일해야 한다.** `manifest.json`은 `run` 필드로 중복을 제거하므로, 두 id가 겹치면
   나중에 쓰는 쪽이 상대의 줄을 "자기가 지난번에 쓴 것"으로 여겨 지워버린다.

### 워크플로 {#陷阱-流程}

8. **`Workflow.continuous=True`가 기본값이다.** `resume_from=None`은 "완전히 새 세션"을 뜻하지 않는다.
   매번 새로 열려면 명시적으로 `continuous=False`. **스텝 이름을 바꾸면 곧 계보가 끊긴다.**
9. **`with_goal(rounds=N)`은 총 라운드 수이지 추가 라운드 수가 아니다**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"`은 `ctx[step.name]`을 쓰지 않는다** —— 하류의 `lambda ctx: ctx["某步"]`가 `KeyError`를 낸다.
    불완전한 결과라도 들고 계속 가려면 `on_fail="continue"`를 쓴다.
11. **`resume_from`이 실행되지 않았거나 실패한 스텝을 가리키면 `ValueError`를 던진다.** 조용히 건너뛰지 않는다.
12. **`Step.reduce`는 반드시 동기 함수여야 한다. `gate` / `when` / `on_reject`는 async여도 된다.**
13. **`fork=True`는 `resume`을 주지 않으면 조용히 무효가 된다.** `Workflow`는 `resume_at`을 절대 넘기지 않으므로,
    메시지 단위로 되감으려면 `Runtime.run`을 직접 호출할 수밖에 없다.
14. **`Runtime`을 직접 구동할 때는 gate 이전에 `on_session`을 반드시 떼어내야 한다.** 그러지 않으면 판정자의 세션이
    일하는 스텝의 계보에 기록된다. `Workflow`는 `try/finally`로 이를 보장한다.
15. **`step_name`이 manifest와 계보의 키를 결정한다.** `Workflow`는 `#retryN` / `#roundN` 접미사를 붙이고,
    판정자는 `#轮次`를 붙인다 —— **접미사가 붙은 이름은 프로세스 간 계보에 들어가지 않는다.** 이것이 "판정자는 언제나 새 세션"을 구현하는 방식 중 하나다.

### 역할 {#陷阱-角色}

16. **`clarify(max_turns=<작은 수>)`는 "질문 횟수 무제한"을 빈말로 만든다** —— 질문 한 번이 곧 한 턴이다.
17. **`goal_step()`에는 `can_run` 형식 인자가 없다.** `**spec_kw`로 `can_run=True`를 넘기는 수밖에 없다.
    넘기지 않으면 목표를 세우는 판정자가 `Bash`를 얻지 못하고, `JUDGE_RULES`의 "먼저 네가 어떤 환경에 있는지 똑똑히 보라"는 항목을 수행할 수 없다.
18. **`judge(can_run=True)`는 판정자가 워크스페이스를 바꿀 수 있게 만든다** —— `whitelist_guard`는 `allowed_tools`에서 유도되므로,
    `Bash`를 주면 `Bash`를 통과시킨다(`Write`/`Edit`는 여전히 막지만, `Bash` 자체로 파일을 쓸 수 있다). 절대 중립을 원하면 켜지 마라.
19. **`worker(isolate=True)`는 workspace가 git 저장소일 것을 요구한다.** 아니면 `Agent` 도구가 곧바로
    `"not in a git repository"`를 뱉고, 조용히 성능을 낮추지 않는다. 게다가 격리 표시는 Python 속성이라
    **`AgentDefinition`에 `dataclasses.replace()`를 하면 사라진다**.
20. **`AgentDefinition`을 직접 생성할 때 인자는 카멜케이스다**: `maxTurns`, `permissionMode`.
    `worker()`는 이미 대신 변환해 준다.

### 핸드오프와 컨텍스트 {#陷阱-换代}

21. **핸드오프가 켜져 있으면 auto-compact는 강제로 꺼지고, 대체 안전망이 없다.** 그래서 핸드오프 문서를 쓰는 그 스텝에는 반드시 강등 경로가 있어야 한다.
    auto-compact를 유지하려면 `AgentSpec.compact`를 명시적으로 주라.
22. **`HandoffPolicy.window`를 너무 작게 잡으면 무한 핸드오프로 돈을 태운다.** 유일한 브레이크는 `max_generations=8`이다.
    반대편에서는, **`default_window()`가 두 환경 변수 모두 설정되지 않았을 때도 `1_000_000`을 반환한다** ——
    크게 잡은 건 `is_overflow()`가 받아준다(한 번의 강등 핸드오프가 된다). 치명적 오류는 아니지만, 그 세대의 인계는 강등된 것이다.
23. **워크벤치가 없으면 핸드오프 문서가 디스크에 남지 않는다.** 문서는 여전히 prompt를 통해 후임에게 전달되지만, 사람은 나중에 찾아볼 수 없다.

### 스토리지 {#陷阱-存储}

24. **`Runtime(trim=False)`(기본값)은 "아무것도 정리하지 않는다"는 뜻이 아니다.** store는 항상 `PruningSessionStore`이고,
    `trim=False`는 대용량 결과 트림만 끈다. **연결 끊김 잔해 제거, 거부된 호출 제거, 중단 잔여물 중립화, 시효 만료는 그대로 수행한다.**
25. **두 spill 디렉터리는 같은 것이 아니다**: `spill_guard`는 `<workbench.root>/spill/`에 놓이고,
    `TrimPolicy.spill_dirname`은 `<workspace>/.flower/spill/`에 놓인다(반드시 워크스페이스 안이어야 한다).
26. **`PruningSessionStore.__init__`의 네 번째 위치 인자는 `ephemeral`이 아니라 `prune`이다.**
    부모 클래스와 다르다. 위치로 넘기면 조용히 어긋난다.

### 문서와 인터랙션 {#陷阱-文书}

27. **`Verdict`가 결론을 파싱하지 못하면 `state=""`, `ok=False`다. 절대 달성으로 취급해서는 안 된다.**
    또한 "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable"은 전부 `unreachable`로 분류되며,
    "멈추고 사람에게 묻는다" 경로를 발동시킨다. "한 라운드 더"가 아니다.
28. **`Brief.parse`는 닫히지 않은 코드 펜스를 만나면 그 뒤의 모든 내용을 버린다** —— 모델 출력이 잘렸을 때
    뒤 섹션이 전부 파싱되지 않고, `complete()`는 `False`가 되며, gate가 되돌려 보낸다.
29. **`Brief.load`는 `"(未填)"`를 빈 값으로 취급한다.** 확인서를 손으로 편집하면서 자리표시 문구를 그대로 베껴 넣었다면, 그 섹션은 여전히 누락으로 친다.
30. **`HumanChannel`의 세 가지 "0 / None"은 의미가 각각 다르다**: `max_asks=None`은 무제한, `max_asks=0`은 질문 금지;
    `timeout_s=None`은 무한 대기, `timeout_s<=0`은 즉시 타임아웃; `remaining`은 `max_asks=None`일 때 **`-1`**을 반환한다.
31. **`Event("ask")`는 질문과 사람이 먼저 한 말을 동시에 실어 나른다.** 후자는 `payload["kind"] == "mail"`이다. UI는 이걸 먼저 판별해야 한다.
32. **`Workflow.run`은 `channel.on_event is None`일 때만 자동으로 배선한다** ——
    직접 `HumanChannel(on_event=...)`을 만들었다면, 질문 이벤트는 workflow의 `on_event` 출구로 함께 들어가지 않는다.
