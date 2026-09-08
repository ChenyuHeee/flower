# 용어집

이 페이지는 flower 문서의 용어 기준이다. 같은 대상은 문서 전체에서 하나의 이름만 갖고, 중·영 대응은 여기서 확정한다 —— 번역본도 이 표를 따른다.

각 항목은 세 가지를 준다: **이 단어가 무엇을 가리키는가**, **코드에서는 무엇인가**, **무엇이 아닌가**. 세 번째가 대개 가장 유용하다. 오해의 대부분은 한 단어를 다른 단어로 착각하는 데서 나오기 때문이다.

---

## 프레임워크와 run {#框架与运行}

### 장기 실행 {#长程}

**long-horizon**

한 번의 run이 수 시간에서 수 일에 걸치고, 여러 session에 걸치고, 프로세스 재시작을 넘어가는 것. 한 번 묻고 한 번 답하는 방식이 아니다. flower의 모든 메커니즘은 이런 run이 중도에 무너지지 않게 하려고 존재한다.

실측 참조: [HT001](../cases/ht001.md)은 연속 10.4시간을 돌았다.

### run {#运行}

**run**

`Runtime` 하나가 시작해서 끝날 때까지의 전체 과정. 한 run 안에는 여러 [step](#步骤)과 여러 [session](#会话)이 있을 수 있고, 중단 후 [continuity](#接续)로 이어갈 수 있다. run 기록은 `runs/manifest.json`과 `runs/sessions.db`에 남는다.

**아닌 것**: API 호출 한 번도 아니고, session 하나도 아니다.

### session {#会话}

**session**

모델 쪽의 컨텍스트 한 줄. 자기 `session_id`가 있고, resume할 수 있고, fork할 수 있다. 한 번의 [run](#运行)이 여러 session을 태울 수 있다 —— [handoff](#换代)할 때마다 새 session으로 바뀐다.

### step {#步骤}

**step** · `Step`

[workflow](#流程) 안의 실행 단위 하나. 컨텍스트 딕셔너리를 받아 agent 하나를 돌리고, 결과를 딕셔너리에 다시 쓴다. `Step`은 클래스다. [Python API](api.md#step) 참조.

### workflow {#流程}

**workflow** · `Workflow`

순서대로 이어붙인 [step](#步骤) 묶음, 그리고 step 사이에서 상태를 어떻게 넘기는지와 언제 조기 종료하는지.

!!! note "프레임워크는 완성된 workflow를 제공하지 않는다"
    flower는 메커니즘만 제공한다. **workflow는 당신이 쓰는 것이다.** [workflow 설계](../guide/workflow.md) 참조.

---

## 역할 {#角色}

역할은 flower가 agent에게 부여하는 분업이다. 각 역할 = 주입되는 규칙 텍스트 한 조각 + 도구 한 세트 + hook 한 세트. 다섯 역할 모두 팩토리 함수이며, [Python API](api.md#角色工厂) 참조.

### coordinator {#协调者}

**coordinator** · `coordinator()`

[main thread](#主线程)에 있는 agent. 작업을 쪼개고, 일을 배분하고, 보고를 읽고, 결정을 내리지만 **직접 손대지는 않는다** —— `Bash` / `Write` / `Edit`를 받지 못한다. 도구는 `Agent`, `TodoWrite`, `Read`뿐이다.

역할 설정은 "Claude Code를 쓸 줄 아는 사람"이지, worker가 아니다.

**아닌 것**: 더 똑똑한 agent. coordinator는 [worker](#执行者)와 기본적으로 같은 모델 등급을 쓴다. 아끼는 것은 컨텍스트이지 모델이 아니다.

### worker {#执行者}

**worker** · `worker()`

실제로 일하는 [subagent](#subagent): 코드를 쓰고, 테스트를 돌리고, 자료를 찾는다. 도구는 `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

응답 형식은 규칙 텍스트로 네 단락에 묶여 있다 —— **결론 / 근거 / 산출물 / 미검증**, 30줄을 넘지 않으며, 파일 내용·명령 출력·로그·diff 원문을 붙여넣는 것은 금지된다.

### clarifier {#确认者}

**clarifier** · `clarify()`

손대기 전에 요구사항을 명확히 물어보는 역할. 일은 하지 않고 질문만 하며, 명확해질 때까지 묻는다(**라운드 상한 없음**). 마지막에 [brief](#需求确认书) 한 부를 낸다. [clarify](../guide/clarify.md) 참조.

### judge {#判定者}

**judge** · `judge()`

"다 됐는지"를 판정하는 역할. 둘 중 하나를 한다: 시작 전에 **목표를 설정**(목표 + 판정 체크리스트 산출)하거나, 매 라운드가 끝난 뒤 **그 라운드를 판정**([verdict](#判定) 산출)한다. [goal guard](../guide/goal.md) 참조.

**핵심**: judge가 판정하는 것은 **산출물**이지 소스 코드가 아니다.

[HT001](../cases/ht001.md)에서 한 번 넘어졌다. 인수 기준에는 "macOS 터미널에서 직접 실행"이라고 적혀 있었는데, 인도된 산출물에 `file`을 돌려보니 `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`였고, 그런데도 판정은 통과였다.

두 가지를 분명히 해야 한다. 그러지 않으면 이 사례가 오독된다:

1. **그때 잘못 판정한 것은 goal guard가 아니다** —— HT001에는 아직 이 메커니즘이 없었고, 잘못 판정한 것은 coordinator가 자발적으로 파견한 감사자였다.
2. **기본 설정의 judge도 십중팔구 이걸 놓친다.** `judge()`의 기본값은 `can_run=False`이고 도구는 `Read/Glob/Grep`뿐이다 —— **`file`을 돌릴 수 없다.** `Makefile`을 읽고 Darwin 분기가 실제로 있다는 것만 확인한 뒤 달성으로 판정할 것이다.

정말로 통한 것은 [HT002](../cases/ht002.md)다. judge에 `judge_can_run`을 켜서 직접 `file`과 `lsof`를 돌려 현장을 확인했고, 이 함정을 명확히 피했다. **그러니 "산출물을 판정한다"는 말은 `can_run=True`가 있어야 땅에 발을 붙인다.**

### oracle {#旁路顾问}

**oracle** · `oracle()`

읽기 전용 우회 경로 하나. run이 아직 돌고 있는 동안 "지금 어디까지 왔나"를 물어볼 수 있고, oracle은 최근 event와 [workbench](#工作台)를 한번 보고 답한다. **oracle이 하는 말은 그 run의 컨텍스트에 들어가지 않는다** —— 물어봐도 run에 영향이 없고, 답하면 버려진다.

### subagent {#subagent}

Claude Agent SDK의 개념: 메인 agent가 `Agent` 도구로 파견하는 자식 agent. **자기 transcript를 따로** 가지며, 도구 호출과 시행착오는 모두 그쪽에 기록되고 main thread는 최종 보고만 받는다.

이것이 flower가 컨텍스트를 아끼는 첫 번째 층이자 가장 많이 아끼는 층이다. [컨텍스트 경제학](../guide/context.md) 참조.

---

## 네 가지 메커니즘 {#四个机制}

### clarify {#前置确认}

**clarify**

손대기 전에 요구사항을 명확히 물어 [brief](#需求确认书) 한 부로 동결한 뒤 실행을 시작한다. 막는 것은 "만들어 놓고 보니 원하던 게 아님"이다. [clarify](../guide/clarify.md) 참조.

### brief {#需求确认书}

**brief** · `Brief`

[clarifier](#确认者)가 다 묻고 나서 내놓는 문서, **정확히 네 단락**. 이후 step들은 이것을 읽고, 요구사항을 다시 추측하지 않는다.

[task brief](#任务书)와 **헷갈리지 말 것**. brief는 "사람이 무엇을 원하는가"이고, task brief는 "이 subagent가 이번에 무엇을 하는가"다.

### task brief {#任务书}

**task brief**

[coordinator](#协调者)가 일을 배분할 때 [worker](#执行者)에게 써 주는 그 문단. **이번 작업에만 해당하는 것만 쓴다** —— 상대가 이미 아는 규율은 되풀이하지 않는다.

실측: 8/8 부의 task brief가 상대가 이미 아는 규율을 되풀이했고, 가장 짧은 것은 521자 중 약 120자만이 작업 고유 내용이었다. 한 라운드에 약 4.8k의 영구 컨텍스트를 헛되이 차지했다.

### goal guard {#目标看守}

**goal guard**

[judge](#判定者)가 매 라운드가 끝난 뒤 목표 달성 여부를 독립적으로 판정하고, 달성하지 못했으면 되돌려 계속하게 한다. 막는 것은 "다 했다고 말했지만 사실은 안 됐음"이다. [goal guard](../guide/goal.md) 참조.

### verdict {#判定}

**verdict** · `Verdict`

[judge](#判定者)가 한 라운드를 판정한 결과, **정확히 세 단락**: 결론 / 이유 / 미통과.

결론은 세 가지다. `ACHIEVED`(달성), `NOT_YET`(아직), `UNREACHABLE`(이 환경에서는 검증 불가). **뒤의 둘은 서로 다른 결론이다** —— "여기서는 검증할 수 없다"는 절대로 통과로 판정하지 않는다.

### continuity {#接续}

**continuity**

같은 디렉터리에서 다시 돌리면 지난번 진행 상황에 자동으로 이어붙는다 —— 프로세스가 죽어도, 머신이 재시작해도 마찬가지다. 막는 것은 "몇 시간 돌다 죽어서 처음부터 다시"다. [continuity](../guide/continuity.md) 참조.

[handoff](#换代)와 **헷갈리지 말 것**: continuity는 **프로세스를 넘어** 지난 run에 이어붙는 것이고, handoff는 **같은 run 내부에서** 새 session으로 갈아타는 것이다.

### handoff {#换代}

**handoff**

컨텍스트가 거의 찼을 때, 현재 session이 사람이 읽고 고칠 수 있는 [handoff document](#交接书)를 쓰게 한 다음 새 session이 이어받는다. 막는 것은 "컨텍스트가 꽉 차서 요약 한 단락으로 뭉개짐"이다. [handoff](../guide/handoff.md) 참조.

compact가 **아니다**. [compact](#压缩) 참조.

### handoff document {#交接书}

**handoff document** · `Handoff`

handoff 때 쓰는 문서, 다섯 단락: `doing`(무엇을 하고 있는가), `decided`(무엇을 정했는가), `deadends`(막힌 길), `next`(다음 단계), `scene`(현장).

**필수는 `doing`과 `next`뿐이다** —— "막힌 길"을 비워 두지 못하게 강제하면 모델이 지어내게 된다.

### compact {#压缩}

**compact**

Claude Code의 기본 방식: 컨텍스트가 차면 앞의 대화를 요약 한 단락으로 정리한다.

flower는 **이것을 쓰지 않고** [handoff](#换代)로 대체한다. 차이는 이렇다. 요약은 모델이 생성한 것이라 읽을 수도 고칠 수도 없고 무엇이 버려졌는지 알 수 없다. handoff document는 구조화되어 있고 디스크에 남으며, 열어서 한 줄 고친 뒤 이어서 돌리게 할 수 있다.

---

## 컨텍스트 관리 {#上下文管理}

### main thread {#主线程}

**main thread**

[coordinator](#协调者)가 있는 그 session 컨텍스트. run 전체를 관통하는 유일한 컨텍스트이므로 가장 아껴야 한다.

코드에서 main thread를 판정하는 방식: hook 데이터에 `agent_id`가 **없다**. subagent의 hook에는 `agent_id`가 붙는다.

### workbench {#工作台}

**workbench** · `Workbench`

디스크에 남는 작업 디렉터리, 하위 디렉터리 셋:

| 디렉터리 | 무엇을 두나 |
|---|---|
| `scripts/` | 두 번째로 돌릴 스크립트, 첫 줄에 `# desc: 한 줄 설명` |
| `artifacts/` | 2000자를 넘는 긴 산출물 |
| `notes/` | 핵심 결정, 결정 하나당 파일 하나 |

`INDEX.md`는 이 세 디렉터리의 색인이고, **system prompt에 주입되므로** agent는 매 라운드 손에 무엇이 있는지 안다.

!!! warning "진입점 둘, 기본 위치 둘"
    workbench가 어디에 놓이는지는 어떻게 만들었느냐에 달려 있고, 여기서 자주 걸린다:

    | 생성 방식 | workbench 루트 디렉터리 |
    |---|---|
    | `Workbench(workspace)` —— `starter_flow()` / `wake_state()`가 가는 길이기도 하다 | `<워크스페이스>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench`(기본 `runs/workbench`) |

    커맨드라인은 전자를 쓰므로 `flower`로 돌리면 `.flower/`가 나온다. 하지만 Python에서 직접 `Runtime(workbench=True)`를 쓰면 `runs/workbench`를 받는다. 위치를 지정하려면 만들어 둔 `Workbench` 인스턴스를 넘기고, 기본값에 기대지 말 것.

!!! warning "색인은 subagent가 상속받지 못한다"
    색인은 session 수준의 `system_prompt.append`로 가므로 **subagent는 받지 못한다.** 그래서 "긴 산출물은 `artifacts/`에 쓴다"는 규칙은 반드시 [coordinator](#协调者)가 [task brief](#任务书)에 옮겨 적어야 한다 —— 그것이 유일한 통로다.

### spill {#落盘}

**spill**

도구 결과가 임계값(기본 4000자)을 넘으면 `PostToolUse` hook이 그것을 `<workbench 루트>/spill/`에 쓰고, 컨텍스트에는 경로 한 줄만 남긴다.

경로는 **[workbench](#工作台)를 따라간다.** 하드코딩된 것이 아니다 —— workbench가 기본 위치 `<워크스페이스>/.flower`에 있을 때만 정확히 `.flower/spill/`이 된다. [isolation](#隔离)을 켜서 workbench가 `home=`으로 리포지터리 밖을 가리키면, spill도 함께 밖으로 옮겨진다.

**그 자리에서 바로 잘라낸다.** 컨텍스트가 찬 뒤 되돌아가 [compact](#压缩)하는 게 아니다.

### ephemeral command {#一次性命令}

**ephemeral command**

결과가 곧 만료되고 보존 가치가 없는 명령 —— `ls`, `git status`, `ps` 같은 것들. 이런 결과는 영속화되는 session 기록에 들어가지 않는다. "main thread에서 한 번 돌려보게 허용할 것인가"와 "결과가 잘려 나갈 것인가"를 판단하는 데 같은 함수를 쓰므로, 두 집합은 항상 같다.

### trim {#裁剪}

**trim** · `TrimmingSessionStore`

**resume 직전에** 모델에게 다시 먹일 그 메시지들을 다시 쓴다([ephemeral command](#一次性命令)의 결과, 지나치게 긴 도구 출력).

`load()`만 덮어쓴다: **SQLite 안의 원문은 항상 그대로이고**, 잘리는 것은 이번 resume에서 컨텍스트로 들어가는 사본뿐이다. 그래서 trim은 되돌릴 수 있다 —— 전략을 바꿔 다시 resume하면 다시 완전한 기록을 받는다.

### prune {#剪除}

**prune** · `PruningSessionStore`

**에러 메시지**를 컨텍스트 밖에 막아 둔다. 네트워크 끊김 재시도 중에 쌓인 오류 더미가 resume 이후의 컨텍스트를 차지해서는 안 된다.

[trim](#裁剪)과 **헷갈리지 말 것**: trim은 크기와 가치로 버리고, prune은 "에러인가 아닌가"로 버린다.

---

## 런타임 {#运行时}

### isolation {#隔离}

**isolation**

표시된 역할은 자동으로 독립된 git worktree에 배정된다. hook이 강제하며 프롬프트에 기대지 않는다. 같은 리포지터리를 병렬로 고칠 때 충돌하지 않는다.

!!! warning "isolation을 켜면 workbench를 리포지터리 밖으로 옮겨야 한다"
    worktree isolation을 켤 때 [workbench](#工作台)는 반드시 `home=`으로 리포지터리 밖을 가리켜야 한다. 그러지 않으면 격리된 agent가 공유 checkout에 쓸 수 없다.

### resilience {#韧性}

**resilience** · `Resilience`

네트워크가 끊기면 실패로 종료하지 않고 매달려 기다린다: DNS + TCP 프로브가 지켜보다가, 네트워크가 복구되면 resume해서 이어 달린다. 대기 중에 생긴 에러 메시지는 [prune](#剪除)이 컨텍스트 밖으로 막는다.

### lineage {#血缘}

**lineage** · `Lineage`

"이번 run이 어느 session에서 fork되었는가"를 프로세스를 넘어 기록하며, `lineage.json`에 남는다. [continuity](#接续)는 이것으로 지난번에 어디까지 갔는지 찾는다.

[run manifest](#运行清单)와 **헷갈리지 말 것** —— 그쪽은 `runs/manifest.json`이고, 매 run의 장부를 기록한다.

### run manifest {#运行清单}

**run manifest** · `runs/manifest.json`

매 [run](#运行)의 장부 기록: 얼마를 썼는지, 얼마나 돌았는지, 컨텍스트가 얼마나 컸는지. 사례 페이지의 숫자는 모두 여기서 다시 계산할 수 있다.

### wake {#唤醒}

**wake** · `wake_state()`

출발 전의 **읽기 전용 탐지**: 이 워크스페이스에 이미 [brief](#需求确认书)와 목표가 있는지 보고, 이번이 완전히 새로 시작하는 것인지 [continuity](#接续)인지 결정한다. **1바이트도 쓰지 않는다.**

`wake_state()`는 workbench 위치의 유일한 정의처다 —— 드라이버 프로그램도 brief가 어디 있는지 알려면 이것을 거쳐야 한다. 직접 경로를 조립하다 틀려도 오류가 나지 않고, 조용히 무효가 될 뿐이다.

### event {#事件}

**event** · `Event`

SDK의 메시지 스트림을 평탄화한 안정적인 구조. **[interaction layer](#交互层)는 `Event`만 알고, 어떤 SDK 타입도 import하지 않는다** —— UI를 바꿔도 코어를 고치지 않게 하는 경계다.

### interaction layer {#交互层}

**interaction layer**

사람과 run 사이의 UI 층. 기본은 터미널이고, Web·TUI·HTTP로 바꾸거나 완전 자동 무인 운전으로 바꿀 수 있다. [interaction layer 교체](../guide/interaction.md) 참조.

### session store {#会话存储}

**session store** · `SessionStore`

session 메시지의 영속화 백엔드. 기본 `SqliteSessionStore`는 `runs/sessions.db`에 쓰고, [trim](#裁剪)과 [prune](#剪除) 두 층으로 감쌀 수 있다.

### budget {#预算}

**budget** · `max_budget_usd`

한 run의 지출 상한. 넘으면 멈춘다. 장기 실행에서 이게 없으면 매우 비싸진다 —— [HT001](../cases/ht001.md)은 $171.62를 썼다.

---

## 이식성 {#可移植性}

### portable {#可移植}

**portable**

머신을 바꿔도 동작이 같다. 방법은 `setting_sources=[]` —— 호스트 머신의 `~/.claude/`도 읽지 않고, 프로젝트의 `.claude/`도 읽지 않는다. 도메인 능력은 [plugin](#plugin)으로 리포지터리를 따라가고, 자격 증명은 `.env`로 직접 들고 간다.

대가: **자격 증명을 직접 들고 가야 하며**, 호스트 머신 설정을 자동으로 상속하지 않는다.

### append {#叠加}

**append**

도메인 지시는 Claude Code 기본 시스템 프롬프트 **뒤에** 덧붙이며, 그것을 대체하지 않는다:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

그래서 특화가 범용 능력의 손실을 대가로 하지 않는다.

### plugin {#plugin}

리포지터리를 따라다니는 도메인 능력 꾸러미. `plugins=[local]`로 로드하고, 디렉터리에는 `skills/`, `agents/`, `hooks/`, `.mcp.json`을 둘 수 있다. [배포](deploy.md#plugin) 참조.
