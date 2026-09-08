# 워크플로 설계

프레임워크는 메커니즘만 담당한다. 한 스텝이 어떻게 도는지, 세션이 어떻게 이어지는지, 실패하면 어떻게 되는지, 컨텍스트를 어떻게 아끼는지.
**[워크플로](../reference/glossary.md#流程)는 당신이 쓴다** — 프레임워크는 당신이 무슨 프로젝트를 어떤 언어로 하는지 모르고,
알아서도 안 된다. 이 페이지는 워크플로를 어떻게 설계하는지를 다룬다. `Step`과 `Workflow`의 전체 필드 표는
[Python API](../reference/api.md)에 있다.

## 무엇을 해결하는가 {#解决什么问题}

한 번의 [long-horizon](../reference/glossary.md#长程) 실행은 프롬프트 한 줄로 끝나는 일이 아니다. 먼저 요구사항을 명확히 하고,
조사하고, 구현하고, 검토한다. 각 구간마다 자기 역할, 자기 컨텍스트, 자기 인수 조건이 있다.
전부 프롬프트 한 줄에 밀어 넣으면 모델이 어느 구간을 건너뛸지 스스로 정한다. 워크플로로 쓰면 **순서, 종료 조건, 상태 전달이
Python 코드가 된다** — 읽을 수 있고, 테스트할 수 있고, 망가진 스텝만 다시 돌릴 수 있다.

`Workflow`가 하는 일은 세 가지뿐이다.

- [스텝](../reference/glossary.md#步骤) 여러 개를 순서대로 실행한다
- 각 스텝이 앞의 무엇을 볼 수 있는지 결정한다(세 가지 세션 연결 방식 + `ctx` 딕셔너리 하나)
- 언제 재시도하고 언제 조기 종료할지 결정한다

도메인 가정은 하나도 들어 있지 않다. 어디서 자를지, 각 스텝이 무엇을 인수 조건으로 삼을지, 통과하지 못하면 어떻게 할지 — 이 네 가지가 바로 "워크플로 설계"다.

## 어떻게 쓰나(최소 코드) {#怎么用最小代码}

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # 새 세션: prompt로 넘겨준 것만 먹는다
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 역시 새 세션, 앞 스텝의 산출물을 prompt에 주입한다(싸고, 오염을 막는다)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

`flower run`의 인자는 `모듈:속성` 또는 `파일경로:속성`이다. 얻어낸 객체가 호출 가능하면 먼저 한 번 호출하고,
`Workflow`를 받아 실행한다. 다 돌고 나면 터미널에 총비용과 실행 매니페스트의 경로가 찍힌다.

드라이버를 직접 써도 된다. `Workflow.run`의 첫 번째 인자는 `Runtime`이다.

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## 실제로 하는 일 {#它实际做了什么}

### Step이 무엇을 받고 무엇을 반드시 돌려주는가 {#一个-step-收到什么必须返回什么}

`Step`은 함수가 아니라 **선언**이다. 실제로 실행되는 것은 `Runtime.run(step.spec, 렌더링된 prompt, ...)`이다 —
**한 스텝 = `Runtime.run` 한 번 = [세션](../reference/glossary.md#会话) 하나**.

앞의 세 필드는 위치 인자다. `Step(name, spec, prompt)`:

- `name` — 스텝 이름. 동시에 `ctx`의 키 이름이고, `runs/manifest.json`의 행 이름이며,
  프로세스를 건너뛰는 [리니지](../reference/glossary.md#血缘)의 키다.
- `spec` — 어떤 `AgentSpec`으로 돌릴지. 이 스텝의 도구 화이트리스트, 모델, 예산을 결정한다.
- `prompt` — `str`, 또는 `(ctx) -> str`. 호출 가능하면 현재 `ctx`를 받는다.
  **앞 스텝의 산출물을 먹이는 가장 싼 방법이다**(다른 하나는 세션을 잇는 것, 아래 참조).

이 스텝이 "돌려주는" 것은 `StepResult`지만, 워크플로 안에서 당신이 받는 것은 두 가지다.

- `ctx[step.name]` — 기본은 `result.text`, `reduce`를 주면 `reduce`의 반환값으로 바뀐다.
- `ctx["_results"][step.name]` — 완전한 `StepResult`(비용, 턴 수, 시도 횟수, `session_id`).

`result.text`는 **메인 스레드의 본문만 받는다**. subagent의 발언은 자기 transcript 안에 있고, 그에게 넘긴
[태스크 브리프](../reference/glossary.md#任务书)는 `kind="prompt"`, 연결 끊김으로 합성된 에러는 `kind="error"`다
— 셋 다 들어오지 않는다.

### reduce: 설탕이 아니다 {#reduce不是糖}

기본적으로 아래로 전달되는 것은 모델이 한 말 그대로다. 어떤 스텝의 원문은 그대로 내려보내면 **안 된다**.

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

실측해 보면 요구사항을 확인하는 그 스텝은 네 개 섹션 외에 **코드 전체를 붙여 넣는다**. 하류로 전달해야 하는 것은 파싱된 네 개 섹션이어야 하고,
그렇지 않으면 그 코드 뭉치가 다음 스텝의 prompt로 들어간다. `clarify_step`이 바로 이 필드로 막아낸다.

`reduce`는 **반드시 동기 함수여야 한다**. `gate` / `when` / `on_reject`는 async여도 된다.

### 상태는 ctx 안에서 어떻게 흐르나 {#状态怎么在-ctx-里流动}

`ctx`는 `dict[str, Any]`이고, `Workflow.context` 그 자체다. 매 스텝이 끝날 때마다 이 표대로 쓴다.

| 상황 | `ctx[步骤名]` | 그 밖에 |
|---|---|---|
| `when(ctx)`가 False 반환 | **쓰지 않음**, 스텝 전체 건너뜀 | result가 생기지 않고 `_results`에도 안 들어감 |
| 통과 | `reduce(result, ctx)`, 안 주면 `result.text` | |
| 실패 + `on_fail="stop"`(기본값) | **쓰지 않음** | `ctx["_failed_at"]`을 쓰고, 워크플로 전체가 이 스텝에서 멈춤 |
| 실패 + `on_fail="skip"` | **쓰지 않음** | 계속 아래로 진행 |
| 실패 + `on_fail="continue"` | `result.text`(불완전한 것, **`reduce`를 거치지 않음**) | 계속 아래로 진행 |

통과 여부와 관계없이 `ctx["_results"][步骤名]`은 항상 쓰인다. `result.session_id`가 비어 있지 않으면
`ctx["_sessions"]`에도 쓰고 리니지에 기록한다.

**이번 워크플로가 성공했는지는 `ctx.get("_failed_at")`으로 판단한다.** 마지막 스텝에 출력이 있는지로 보는 게 아니다.

밑줄로 시작하는 키는 전부 `Workflow.run`이 직접 넣은 것이다. `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — 이것들을 자기 스텝 이름으로 쓰지 마라. 각 메커니즘도 자기 것을 넣는다
(`_brief` / `_goal` / `_verdict` 등). 전체 목록은 [Python API](../reference/api.md)에 있다.

그중 `_runtime`과 `_on_event`는 `gate`용이다. gate는 스스로 agent를 하나 파견해 판정할 수 있고,
그 판정 과정도 그대로 UI에 찍힌다 — 안 그러면 십수 초 동안 화면이 깜깜해서 멈춘 것처럼 보인다.
[목표 가드](goal.md)가 바로 이렇게 구현돼 있다.

`ctx`는 같은 dict다. **같은 `Workflow` 객체를 두 번째로 돌리면 지난번 키가 그대로 남아 있다.**
깨끗하게 다시 시작하려면 새로 만들거나 `context={}`를 명시적으로 넘겨라.

!!! warning "on_fail을 skip으로 하면 `ctx[步骤名]`을 쓰지 않는다"
    하류에서 `lambda ctx: ctx["某步"]`라고 쓰면 바로 `KeyError`다. 불완전한 결과를 들고 계속 가려면
    `on_fail="continue"`를 쓰고, 정말 건너뛰려면 하류가 직접 `ctx.get(...)`으로 받아내야 한다.

### 판정과 반려: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool`이 판단하는 것은 "다 돌긴 했는데, 합격인가"다. 반드시 알아야 할 두 가지가 있다.

- **`result.ok`가 거짓이면 `gate`는 아예 호출되지 않는다**(단락 평가).
- **시도당 한 번만 호출되고**, 결론은 뒤에서 재사용한다 — 부작용이 있을 수 있기 때문이다. `clarify_step`의 gate는
  [브리프](../reference/glossary.md#需求确认书)를 디스크에 쓰므로, 중복 호출은 중복 기록이 된다.

gate를 통과하지 못한 뒤 어떻게 다시 도는지는 `on_reject`를 줬는지에 달려 있다.

| | 다음 라운드가 도는 방식 | manifest에서의 이름 |
|---|---|---|
| `retries`만 있음 | 처음부터 다시, 원래 prompt와 원래 `resume_from` | `X#retry1` |
| `on_reject`까지 있음 | **방금 반려된 그 세션을 이어서 실행**, prompt는 `on_reject`의 반환값으로 교체, `fork`는 강제로 False | `X#round2` |

두 번째는 "돌려보내고, 어디가 모자란지 알려주고, 이어서 채우게 한다"이다 — 이미 해놓은 작업과 컨텍스트가 그대로 남아 있다.
`on_reject`가 빈 문자열을 반환하거나, 그 시도가 애초에 `session_id`를 못 받았으면 처음부터 다시 도는 쪽으로 퇴화한다.

`gate`는 `StepAbort`를 던질 수도 있다. 뜻은 **더 시도해도 소용없으니 남은 턴을 쓰지 말라**는 것이다.

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

던진 뒤에는 사유가 `ctx["_aborted"]`에 기록되고, 이 스텝은 실패로 처리되어 `on_fail`을 따르며(기본값 `"stop"`),
**재시도 루프는 그 자리에서 break**, 남은 `retries`는 한 번도 소모하지 않는다.

구분을 확실히 해두자. **False를 반환하는 것은 "이번엔 안 됐으니 한 라운드 더", `StepAbort`는 "더 해도 소용없다"이다.**
전형적인 경우는 목표가 이 환경에서는 불가능하다고 판정됐고, 물어볼 사람도 없을 때다 — 계속 헛도는 게 가장 비싼 선택이다.

### 두 층의 재시도를 섞지 마라 {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| 무엇을 담당 | 업무 실패: `gate` 불통과, `result.ok`가 거짓 | 인프라: 네트워크 흔들림, 연결 끊김, 5xx |
| 어떻게 다시 | **스텝 전체 재실행**, 같은 prompt와 같은 `resume_from` | **중단된 지점에서 resume해 이어감**, 이전 비용이 헛되지 않음 |
| 그 전에 무엇을 | 아무것도 안 함 | DNS + TCP 프로브를 걸어두고 네트워크가 돌아오길 기다림(HTTP를 보내지 않고 자격 증명도 싣지 않음, 프로브는 반드시 무료여야 함) |
| 재시도 불가 | —— | 자격 증명 오류, 파라미터 오류는 즉시 중단, 무한정 기다리지 않음 |

이어서 실행할 때 쓰는 prompt에는 **의도적으로 어떤 에러 세부 정보도 넣지 않는다** — 모델은 "중단됐으니 이어서 하라"만 알면 되고,
ENOTFOUND인지 503인지 알 필요는 없다.

### 스텝을 엮기 {#把步骤串起来}

스텝 사이에 상태를 전달하는 방식은 세 가지이고, 어느 것을 고르느냐가 다음 스텝이 무엇을 볼 수 있는지를 결정한다.

| 작성법 | 다음 스텝이 보는 것 | 어디에 쓰나 |
|---|---|---|
| `resume_from=None`(기본값) + prompt에 주입 | 당신이 주입한 그 글자들만 | 각 스텝 독립. 싸고 오염 방지 |
| `resume_from="앞 스텝 이름"` | 완전한 세션 이력 | 일관된 기억이 필요할 때 |
| `resume_from="앞 스텝 이름"` + `fork=True` | 완전한 이력, 단 별도 분기 | 검토 / 다중 방안 병렬 / 재시도로 원래 라인을 더럽히지 않기 |

`resume_from`이 가리키는 그 스텝은 **실제로 session을 만들어냈어야 한다**. `when`으로 건너뛰었거나 아예 돌지 않았으면
`Workflow.run`은 곧바로 `ValueError`를 던진다 — 조용히 새 세션으로 격하하지 않는다. 그렇게 하면 "일관된 기억"이라는 가정이
슬그머니 무너지기 때문이다.

반복해서 손해 보며 얻은 설계 경험 몇 가지.

1. **한 스텝에 인수 가능한 목표 하나.** 스텝 경계가 곧 컨텍스트 경계다. `resume_from=None`인 지점에서는
   앞의 도구 결과들이 완전히 상주에서 빠진다. [컨텍스트 경제학](context.md) 참조.
2. **확신이 없으면 먼저 `clarify_step`.** long-horizon에서 "목표를 잘못 이해했다"는 가장 비싼 오류이고,
   하필 컨텍스트를 아끼는 그 몇 개 층으로는 지워지지 않는 종류다. [사전 확인](clarify.md) 참조.
3. **파견할 일감은 자족적이어야 한다.** subagent는 깨끗한 컨텍스트라서 [코디네이터](../reference/glossary.md#协调者)가
   아는 것을 모른다. 필요한 배경은 태스크 브리프에 쓰거나, 어느 artifact를 읽으라고 알려줘라.
4. **긴 산출물은 디스크로, 대화로 돌려보내지 말 것.** 이 조항은 이미 `WORKER_RULES`에 들어 있다. 당신의 `instructions`가
   그걸 무효화하지 않게 하라("전체 로그를 붙여서 보여줘").
5. **`gate`는 하드 조건을 먼저 걸어라.** 파일이 있는지, 종료 코드가 0인지처럼 Python 한 줄로 판단되는 걸 모델에 맡기지 마라.
   모델이 판단해야 한다면 기성품인 `with_goal`을 써라 — gate를 독립된
   [판정자](../reference/glossary.md#判定者)를 돌리는 구현으로 바꿔준다. gate 안에서 직접 손으로 짜지 마라.
6. **같은 저장소를 병렬로 고친다면 `worker(isolate=True)`.** 마무리(병합, worktree 정리, PR 생성)는 현재
   당신의 워크플로가 직접 해야 한다. harness는 변경이 각자의 worktree 안에 떨어지는 것만 보장한다.

### 워크벤치는 Workflow에 달아야 한다 {#工作台要挂在-workflow-上}

워크플로가 [워크벤치](../reference/glossary.md#工作台)에 파일을 써야 하는 모든 경우 — 전형적으로는
`clarify_step(brief_path=...)` — `Workbench`를 직접 하나 만들어서 **동시에** `Workflow.workbench`에 달고
`Runtime`에도 넘겨야 한다.

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

`channel`을 workflow에 다는 이유는 둘이다. `run()`이 그 `on_event`를 같은 이벤트 출구에 연결하고
(`channel.on_event`가 아직 `None`일 때만), 드라이버도 이 필드를 통해 누구에게 답해야 하는지 안다.

!!! warning "워크벤치 경로를 직접 조립하면 조용히 어긋난다"
    `Runtime(workbench=True)`의 기본 위치는 `<run_dir>/workbench`이고, `Workbench(ws)`의 기본값은
    `<ws>/.flower`다 — **둘은 같은 디렉터리가 아니다**. 워크플로가 CLI로 호출될 때는 `run_dir`이 보이지 않으므로,
    직접 경로를 조립하면 엉뚱한 곳을 가리키게 되고, 그 결과 브리프는 A 디렉터리에 쓰이는데 주입되는 인덱스는 B 디렉터리를 훑는다.
    **게다가 에러도 나지 않는다.** 객체 하나를 만들어 양쪽이 공유하면 이 문제가 없다. `Workflow.workbench`가 있으면
    커맨드라인의 `-W`는 무시되고, 이쪽이 기준이 된다.

### `continuous=True`: 같은 경로에서 한 번 더 실행 {#continuoustrue同一个路径再跑一次}

위의 세 가지 연결 방식은 **한 번의 실행 안에서** 스텝과 스텝 사이 이야기다. 프로세스를 넘나드는 것은 다른 축이다.

```python
Workflow([...], continuous=True)     # 默认值
```

같은 작업 공간에서 한 번 더 실행하면 각 스텝이 지난번 그 세션에 이어서 말한다 — `<run_dir>/lineage.json` 안의
「스텝 이름 → session_id」에 의존한다. 로드할 때 각 레코드는 `runtime.has_session()`으로 세션이 아직 저장소에 있는지 검증하고,
살아 있을 때만 쓴다. 리니지 파일이 `sessions.db`보다 오래 살아남을 수 있고, 존재하지 않는 세션을 resume하면 자식 프로세스가 뜬 뒤에야 터지기 때문이다.

결과는 세 가지다.

- **`resume_from=None`이 "완전히 새 세션"과 같지 않다.** 첫 실행은 그렇지만 두 번째 실행은 아니다. 매번 새 세션이어야 한다면
  `Workflow(..., continuous=False)`를 명시적으로 써라.
- **[연속성](../reference/glossary.md#接续) 상황에서 컨텍스트는 계속 늘어난다.** 이어서 실행할 때 다른 말을 하고 싶으면
  `Step.resume_prompt`를 줘라 — 상대의 컨텍스트에 이미 있는 것을 다시 보낼 이유는 없다.
- `resume_from`을 명시적으로 쓴 스텝은 영향을 받지 않는다. 그쪽이 우선한다.

!!! warning "스텝 이름은 프로세스를 건너뛰는 키다"
    스텝 이름 하나를 바꾸면 그 스텝의 리니지가 끊어진다. 다음 실행에서 더 이상 이어지지 않고, **에러도 나지 않는다**. `#retry1` /
    `#round2` 접미사가 붙은 재시도 이름은 **리니지에 들어가지 않는다**(기록되는 것은 언제나 원래 이름). 이것이 "판정자는 언제나 새 세션"을 구현하는
    방식 중 하나이기도 하다.

전체 설계와 `--new`는 [연속성](continuity.md) 참조.

## 언제 쓰지 말아야 하나 {#什么时候不该用它}

- **agent 하나만 돌리고 판정도 필요 없다면** — `Workflow`를 씌우지 마라. 바로 `await rt.run(spec, "…")`,
  아니면 커맨드라인으로 `flower once "读一眼这个仓库"`.
- **형태가 그냥 "요구사항 확인 → 목표 설정 → 작업"이라면** — 기성품인
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py)를 쓰고,
  직접 쓰지 마라.

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    이것은 **세 스텝**이다. `确认需求` → `设定目标` → `干活`(판정 루프 포함, 판정 스텝의 이름은 `干活·判定#N`).
    `goal=False`면 두 번째 스텝과 판정 루프가 없고, `clarify_only=True`면 첫 스텝만 남는다.
    `HumanChannel`과 `Workbench`를 자체적으로 갖고 있으며 workflow에 달아두므로,
    `Runtime(workbench=wf.workbench)`로 그대로 가져다 쓰고 따로 하나 더 조립하지 마라.

    코드를 안 써도 된다. 프로젝트 디렉터리에서 `flower "帮我做一个 X"`를 돌리면 이것이 실행된다.
    **이건 "권장하는 워크플로 설계"가 아니다.** 설정 없이 바로 돌려볼 수 있게 해줄 뿐이다.

- **스텝을 "인수 가능한 목표 하나"보다 더 잘게 쪼갠 경우** — 순손실이다. 스텝마다 새 세션을 띄워야 하는데,
  새 세션에는 시작 바닥값이 있고(코디네이터 실측 약 34k 컨텍스트) 그걸 희석할 수가 없다.
- **사후에 특정 메시지로 롤백하고 싶은 경우** — `Workflow`로는 안 된다. 이쪽은 `resume_at`을 절대 넘기지 않는다.
  `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`를 직접 호출하라.

역할을 어떻게 고르는지(`coordinator` / `worker` / `clarify` / `judge` / `oracle`), `Step`과 `Workflow`의
필드별 의미는 [Python API](../reference/api.md)를, 용어는 [용어집](../reference/glossary.md)을 보라.
