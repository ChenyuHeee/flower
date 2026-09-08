# 컨텍스트 경제학

[메인 스레드](../reference/glossary.md#主线程)의 컨텍스트는 한 번의 [롱호라이즌](../reference/glossary.md#长程) 실행에서
처음부터 끝까지 이어지는 유일한 것이다. 거기에 무엇을 담고 무엇을 담지 않느냐가 그 실행이 얼마나 멀리 갈 수 있는지를 결정한다.
flower의 형태 — [코디네이터](../reference/glossary.md#协调者)는 직접 손대지 않고, 긴 산출물은 디스크에 spill하고,
hook이 그 자리에서 잘라낸다 — 는 전부 이 한 줄에서 도출된 것이다. 이 페이지는 그 이유를 다룬다.

## 무엇을 해결하나 {#解决什么问题}

[compact](../reference/glossary.md#压缩)는 컨텍스트가 다 찬 뒤에 되돌아가 요약하는 것이라, 증상만 다룬다. 진짜 문제는 이것이다:
**자잘한 것은 애초에 메인 스레드에 들어와서는 안 된다.**

차이는 타이밍에 있다. `pytest` 한 번의 출력은 예사로 수만 자에 달하는데, 모델은 한 번 보고 결론 하나를 얻을 뿐이고
나머지 문자는 그때부터 매 턴마다 다시 전송된다. 윈도가 가득 차면 compact가 그것을 옆에 있던 결정과 함께 한 단락 요약으로 뭉뚱그린다 —
아끼는 것은 부피고, 잃는 것은 "애초에 왜 그렇게 정했는가"다. auto-compact의 트리거 임계값은 **윈도 − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py))이며,
그 시점이 되면 버려도 되는 것과 버리면 안 되는 것이 이미 나란히 누워 있다.

flower는 네 개의 층으로 해결한다. 순서가 곧 우선순위다 — 아끼는 양이 많은 순이다:

| 층 | 하는 일 | 위치 |
|---|---|---|
| 1. 분업 | 직접 손대는 일은 [subagent](../reference/glossary.md#subagent)에게 위임하고, 시행착오는 그 자신의 transcript로 들어간다 | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. 워크벤치 | 스크립트 / 긴 산출물 / 결정을 디스크에 남기고, 인덱스를 system prompt에 주입 | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. 즉시 spill | `PostToolUse` hook이 임계값을 넘는 도구 결과를 spill하고, 컨텍스트에는 경로 한 줄만 남긴다 | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. 트림과 프루닝 | resume 직전에 세션을 다시 쓴다: 만료된 결과, 거부된 호출, 연결 끊김의 잔여물은 다시 먹이지 않는다 | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

앞의 두 층은 **들어오느냐 마느냐**를 관리하고, 뒤의 두 층은 **이미 들어온 것을 남기느냐 마느냐**를 관리한다. 순서를 뒤집을 수 없다:
네 번째 층이 아무리 독해도 첫 번째 층에서 새어 들어온 양은 되찾지 못한다.

## 어떻게 쓰나(최소 코드) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model 기본값 "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

이 몇 줄이 앞의 세 층을 설치한다. `coordinator()`는 언제나 `delegate_only=True`를 설정한다(1층). `workbench=True`는
[워크벤치](../reference/glossary.md#工作台)를 만들고 인덱스를 코디네이터의 system prompt에 주입하며(2층),
동시에 `Runtime`이 `spill_guard`를 설치하게 한다(3층). 4층은 기본으로 이미 있다 — `Runtime`의
[세션 스토어](../reference/glossary.md#会话存储)는 `PruningSessionStore`로 못 박혀 있고, 생성자 인자에는 그것을 바꿀 입구가 없다.

!!! warning "`workbench=True`는 선택 사항이 아니다"
    코디네이터가 직접 손대는 것을 막는 `delegate_guard`는 `workbench_hooks` 안에 걸려 있고, `workbench_hooks`는
    `Runtime`에 워크벤치가 있을 때만 설치된다. 그리고 `whitelist_guard`는 `delegate_only=True` 때문에 건너뛴다.
    결론: **`Runtime(workbench=False)`에 `coordinator()`를 조합하면, 메인 스레드의 Bash / Write / Edit에는
    벽이 하나도 없다.**

## 실제로 하는 일 {#它实际做了什么}

### 1층: 분업(가장 많이 아낀다) {#第一层分工省得最多}

코디네이터는 "Claude Code를 쓸 줄 아는 사람" 역할을 한다: 분해하고, 일을 나눠 주고, 리포트를 읽고, 결정한다. 그것은
Bash / Write / Edit를 받지 못한다 — 도구는 `Agent`, `TodoWrite`, `Read`뿐이다
(`glance=True`일 때는 제한된 `Bash` 하나가 추가된다, 아래 참조). 직접 손대는 일은 전부
[워커](../reference/glossary.md#执行者)에게 위임한다.

**언제 발동하나**: 메인 스레드가 `Bash|Write|Edit|NotebookEdit`를 호출할 때마다 `PreToolUse` hook
`delegate_guard`가 그 자리에서 deny하고, 길을 알려준다 — "Agent 도구로 subagent를 하나 보내라. 태스크에 목표와
인수 기준을 명확히 쓰고, 긴 산출물은 `.flower/artifacts/`에 쓰며 회신에는 경로와 결론만 담으라고 요구하라." subagent는 전부 통과다.
판단 근거는 hook 데이터에 `agent_id`가 있는지 여부다: **없으면 메인 스레드다.**

**얼마나 아끼나**: subagent의 도구 호출과 시행착오는 **그 자신의 transcript로 들어간다**(세션 스토어에서는 `subpath`로
구분한다). 메인 스레드에는 그 한 번의 `Agent` 호출과 최종 리포트만 남는다. 시행착오 과정은 compact로 지워진 것이 아니라
**애초에 메인 스레드에 들어온 적이 없다.**

- 실측(도구 출력을 대량으로 만들어내는 작업 하나): transcript의 83%가 subagent 안에 떨어졌다.
  메인 스레드는 13건 21K 문자, subagent는 105K 문자.
- 실측(실제 규모, 10.4시간짜리 실행 한 번, [HT001](../cases/ht001.md) 참조): subagent가
  턴의 **97.7%**, 본문 문자의 **94.8%**를 담당했다. 직접 손대는 도구 호출 1,893회 대 메인 스레드 32회(**59:1**).
  초반에 compact가 걸리는 일은 더 이상 주된 경로가 아니다.

두 줄은 서로 다른 두 번의 측정이다. 위는 초기의 소규모 테스트, 아래는 실제 규모에서의 재측정이다. 같은 메커니즘이고,
규모가 클수록 더 많이 아낀다.

아끼는 것은 컨텍스트지 모델 등급이 아니다. `worker()`의 기본값은 `model="inherit"`이다 — 워커를 강등해서는 안 된다.

분업의 유일한 역방향 비용은 [태스크 브리프](../reference/glossary.md#任务书)다 — 코디네이터가 일을 맡길 때 쓰는 그 문단은
메인 스레드로 들어가고, 게다가 영구히 남는다. 실측에서 8/8개의 태스크 브리프가 상대가 이미 아는 규율을 되풀이하고 있었고,
가장 짧은 것도 521자 중 태스크 고유의 내용은 약 120자뿐이었으며, 한 턴에 약 4.8k의 영구 컨텍스트를 헛되이 차지했다. 그래서
`COORDINATOR_RULES`에는 한 줄이 못 박혀 있다: **태스크 브리프에는 이번 태스크 고유의 것만 쓴다.** 그래도 반드시 전달해야 할
규칙은 "워크벤치가 어디 있는지 + 긴 산출물은 `artifacts/`에 + 회신은 경로와 결론만"뿐이다 — 워크벤치 인덱스가 subagent로
들어가지 못하기 때문에, 태스크 브리프가 유일한 통로다.

### 2층: 워크벤치("매번 다시 쓰기"를 치료한다) {#第二层工作台治每次重写}

`.flower/` 아래 세 디렉터리가 워크스페이스를 따라다닌다:

| 디렉터리 | 무엇을 담나 | 무엇을 해결하나 |
|---|---|---|
| `scripts/` | 두 번째로도 실행될 검증 / 재현 스크립트. 첫 줄에 `# desc: 한 줄 설명` | 한 번 쓰면 이후로는 그냥 실행한다. 더 이상 "compact 후 사라져서 매번 다시 작성"하지 않는다 |
| `artifacts/` | 2000자를 넘는 긴 산출물: 로그, 데이터, 리포트, diff | 대화에는 경로와 결론만 나타난다 |
| `notes/` | 핵심 결정과 그 이유. 결정 하나에 파일 하나 | compact되든, 재시작되든, 기계를 바꾸든 결론은 그대로 남는다 |

**언제 발동하나**: `INDEX.md`는 자동 생성된다(기본 최대 40건). `refresh()`는 `PostToolUse`의
`index_guard`가 `Write` / `Edit`가 워크벤치 안에 떨어질 때 호출하며, 매 스텝을 시작하기 전에도 한 번 갱신한다. 위의 세 규칙은
`prompt_block()`이 코디네이터의 system prompt에 주입한다 — 시작 시점부터 이미 어떤 기성 스크립트가 있는지 알고 있으므로,
그것을 발견하려고 도구 호출을 한 번 쓸 필요가 없다.

**얼마나 아끼나**: 실측으로 10.4시간짜리 실행 한 번에서 **스크립트 61개가 95번 쓰이고 331번 실행됐다. 92%가 한 번보다 많이
실행됐고, 쓰고 나서 한 번도 안 돌린 것은 0개다.** 정성적으로는 `audit-fake-ai-server.py`가 7개 스크립트에 재사용됐다.

이 층이 유효한 이유는 하나의 차이에 있다: compact는 컨텍스트를 지울 수 있지만, **디스크는 지우지 못하고 system prompt 안의
인덱스도 지우지 못한다.**

!!! warning "인덱스는 subagent가 상속받지 못한다"
    인덱스는 세션 수준의 `system_prompt.append`를 타는데, subagent는 자기 자신의 system prompt를 가지므로
    **상속받지 못한다**(실측 $0.2461, `tests/prelude_live.py`). 그래서 "워크벤치가 어디 있는지 + 긴 산출물은
    `artifacts/`에"는 반드시 코디네이터가 태스크 브리프에서 다시 전달해야 한다 — 그것이 유일한 통로지 중복이 아니다.

### 3층: 즉시 spill {#第三层当场落盘}

`spill_guard`는 `PostToolUse` hook 하나로, 도구 결과가 **모델에 들어가기 전에** 한 번 들여다본다. `threshold`
(기본 **4000**자)를 넘으면 워크벤치의 `spill/` 디렉터리로 [spill](../reference/glossary.md#落盘)하고,
컨텍스트에서는 포인터 한 줄 + **앞부분 400자**로 바꾼다. 내용은 사라지지 않고, 다만 상주하지 않을 뿐이다.

**언제 발동하나**: matcher는 `Bash|Read|Grep|Glob|WebFetch|WebSearch`다. 기본값이 `main_only=False`이므로
subagent의 결과도 spill된다. 도구 출력 구조 안에서 지나치게 긴 **문자열 필드**만 교체하고, list는 일절 건드리지 않는다
(그 안에 이미지 블록이 있을 수 있다). `updatedToolOutput`은 원래 도구의 출력 구조를 유지해야 하기 때문이다.

**spill된 파일을 읽는 것 자체는 통과시키고, 다시 spill하지 않는다.** 그러지 않으면 그 안내 한 줄에 적힌 "전문이 필요하면 Read로 읽어라"가
빈말이 된다: 읽어 오면 또 임계값을 넘어 또 spill되고 또 포인터 한 줄이 주어지는 무한 루프다. 실측에서 부딪혔다(`tests/handoff_live.py`를
처음 실제로 돌렸을 때). 모델은 다섯 가지 방식으로 우회를 시도했고, 스스로 "The spill read loops back on itself"라고 말했으며,
결국 40줄씩 끊어 억지로 읽어 내면서 예닐곱 턴을 헛되이 태웠다. spill의 의미는 "큰 것을 **자동으로는** 컨텍스트에 밀어 넣지 않는다"이다.
모델 스스로 전문을 보겠다고 정한다면, 그것은 모델의 선택이다.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None 또는 0 = 이 hook을 설치하지 않음
```

**얼마나 아끼나**: [HT001](../cases/ht001.md) 그 실행에서 103번의 spill로 791.4K 문자가 경로 포인터로 바뀌었고,
컨텍스트에 상주하지 않았다.

### 4층: 트림과 프루닝 {#第四层裁剪与剪除}

이 층은 [세션 스토어](../reference/glossary.md#会话存储) 안에 있다. `Runtime`의 store는 언제나
`PruningSessionStore`다(상속 사슬 `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`). 그것은 `load()`에서 — 즉 **resume 직전에** — 다시 먹일 히스토리를 한 번 다시 쓴다.
SQLite 안의 원문은 한 글자도 건드리지 않는다. 네 가지를 한다:

**① 시효 만료**(`ephemeral`, 기본 켜짐). `git status`, `ls`, `cat` 같은
[일회성 명령](../reference/glossary.md#一次性命令)의 결과는 몇 턴 뒤에 본문이 설명 한 줄로 바뀌고,
최근 6개만 남는다. 만료된 내용은 **spill하지 않는다** — 낡은 `git status` 한 부를 보관해 봐야 의미가 없고, 다시 돌리면 나온다:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

라이브 resume 실측은 `expired: 2`였다. 실제 transcript에서 `keep_recent`를 2로 낮추니 5건이 만료됐다.

**② [트림](../reference/glossary.md#裁剪)**(`trim`, **기본 꺼짐**). `>= 2000`자인 tool_result의
본문을 `<workspace>/.flower/spill/`로 spill하고, 블록 내용을 파일 포인터로 바꾸며, 최근 20개의 원문은 남긴다. 이 디렉터리는
3층 `spill_guard`의 spill 디렉터리와 **같지 않다**는 점에 주의하라. 후자는 워크벤치 루트 아래에 쓰지만, 여기 것은 반드시
워크스페이스 안에 떨어져야 한다. 그러지 않으면 agent의 `Read`가 닿지 못한다.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True도 가능
```

**③ 거부된 호출 [프루닝](../reference/glossary.md#剪除)**(`keep_denials`, 기본 1). 막아 세우는 그 동작 자체도
컨텍스트를 오염시킨다: 거부 메시지는 하나의 `tool_result`이고, **한 번도 실행되지 않은 그 명령**과 함께 영구히 남는다.
실측 한 번에 273자(거부 문구 93자 + 죽은 명령 180자)로, 죽은 명령이 거부 문구보다 비싸다.

token보다 더 중요한 것은 그것이 **오도한다**는 점이다. 실측에서 코디네이터는 "Bash를 직접 쓰지 말라"는 문구를 몇 번 읽고 나자
통과되는 `git status`조차 더 이상 시도하지 않고, 곧장 "Bash가 제한돼 있으니 agent를 보내서 보게 하겠다"고 말했다 —
학습된 무력감을 익힌 셈이고, 도리어 subagent 기동 비용을 한 번 더 썼다. 기본값을 0이 아니라 1로 둔 이유는, 가장 최근의 거부는
유효한 신호이며 모델이 같은 턴 안에서 막힌 같은 명령을 반복해 재시도하는 것을 막아 주기 때문이다. 식별은 harness가 스스로 붙이는
구조적 표식 `toolDenialKind: "permission-rule"`에 의존하지, 문구 매칭이 아니다 — 문구는 언제든 바뀌지만 표식은 바뀌지 않는다.
라이브 실측: 2번의 거부 → 1개 제거 1개 유지, 사슬은 끊기지 않았고 resume은 정상이었으며 모델은 여전히 무슨 일이 있었는지 알고 있었다.

**④ 연결 끊김 잔여물 프루닝**. 네트워크가 끊겨 재시도하는 동안 생긴 합성 API 에러 메시지는 다시 먹이지 않는다. 중단으로 남겨진
`tool_result`는 중립적인 설명 한 줄(`[上一轮在此处被中断,该工具结果未产生]`)로 바꾸되, 항목 자체는 남긴다.

**제거할 때의 레드라인**: `tool_use`와 그에 대응하는 `tool_result`는 반드시 **함께** 제거해야 하고(하나만 빠지면
`Missing Tool Result Block`이다), 같은 assistant 메시지 안의 다른 호출을 오폭해서는 안 되며, `parentUuid` 사슬은 반드시
다시 이어 붙여야 한다.

`Runtime(trim=False)`(기본값)은 **아무것도 지우지 않는다는 뜻이 아니다.** 큰 결과의 트림만 끄는 것이고, 만료, 거부된 호출,
연결 끊김 잔여물 처리는 그대로 한다.

### 반례: 흘긋 보는 일은 직접 한다 {#反例看一眼的活自己干}

앞의 세 층은 모두 "밖으로 위임하라"고 말하지만, 반례가 하나 있다. `git status`, `ls`, `cat` 같은 명령은 결과가 수십 자인데,
**subagent를 하나 보내면 기동만으로 약 4.3k의 컨텍스트가 든다**(실측, 분할 상각 불가). `ls` 한 줄에 이 값을 치르는 것은 순손실이다.

그래서 코디네이터는 제한된 Bash를 하나 돌려받는다(`coordinator(..., glance=True)`, 기본 켜짐). 판단 근거는 "명령이 짧다"가
아니라 **결과가 만료되느냐**이고, "통과"와 "만료"는 같은 함수 `is_ephemeral()`이 결정한다:

| | 직접 실행 통과 | 결과가 만료로 표시됨 |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ 위임 | — |

양쪽은 반드시 같은 표여야 한다. 그러지 않으면 어느 한쪽만 성립해도 해롭다. **통과시키고 트림하지 않으면** 만료된 `git status`가
영구히 컨텍스트를 차지하고, 게다가 현재 상태로 오인되어 결정을 오도한다. **트림하면서 통과시키지 않으면** 코디네이터는 `ls` 한 줄에
4.3k를 치러야 한다. `tests/glance.py`는 이 불변식을 assertion으로 못 박았다 — 실측으로 46개 명령에 대해 양쪽 판정이
완전히 일치했고, 그중 10개는 적대적 샘플이다.

**함정(두 번 밟았다)**: 모델은 단일 명령을 쓰지 않는다. 모델이 쓰는 것은
`git status -s && echo "--- LOG ---" && git log --oneline -10`이다. 첫 버전은 `&&` / `|` / `2>&1`이
포함된 명령을 일률적으로 거부했고, 결과적으로 **glance가 완전히 무력화됐다** — 실측에서 코디네이터의 세 번 시도가 모두 막혀,
결국 subagent를 보내는 쪽으로 돌아갔다. 지금은 구간별로 쪼개서 검사한다. 모든 구간이 화이트리스트에 있어야 통과시키고,
`git status && rm -rf x`는 여전히 막는다(뒷 구간이 표에 없다).

### append하되 대체하지 않는다 {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

`build_options()`가 `AgentSpec`을 SDK 옵션으로 컴파일할 때, `instructions`는
[`append`](../reference/glossary.md#叠加)를 탄다 — Claude Code 네이티브 시스템 프롬프트 **뒤에** 덧붙이는 것이지
대체가 아니다. 그래서 위의 규율 텍스트들(`COORDINATOR_RULES`, `WORKER_RULES` 등)은 덧셈이다:
**전문화가 범용 능력의 손실을 대가로 하지 않는다.**

워크벤치 인덱스도 이 통로를 탄다. 그것은 매 턴 존재하지만 system prompt의 일부이므로 대화 히스토리를 차지하지 않고,
compact도 그것을 지우지 못한다 — 대가는 앞에서 말한 그것이다: **코디네이터까지만이다.**

!!! warning "코디네이터가 직접 손대지 못하게 하려고 `disallowed_tools`를 쓰지 마라"
    `disallowed_tools`는 **세션 수준**이라서 subagent까지 함께 금지시킨다. 실측 에러 원문:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    올바른 방법은 두 단계다: `allowed_tools`에 넣지 않고, 그다음 `PreToolUse` hook으로 `agent_id`에 따라 메인 스레드만 막는다.
    `coordinator()`는 이미 그렇게 하고 있다 — `delegate_only=True`를 설정하고, `delegate_guard`가 메인 스레드를 막고
    subagent는 통과시킨다.

    `allowed_tools`만으로도 충분하지 않다. 그것은 **승인 면제 목록이지 배타적 화이트리스트가 아니다.** 실측에서 모델은 거기 없는
    도구도 호출할 수 있었다 — $0.1짜리 프로브 하나에서, `allowed_tools=["Read"]`인 agent가 Write / Bash를 멀쩡히 호출했다.
    진짜로 막는 것은 hook이다.

    **`allowed_tools`도 세션 수준이다. 같은 수업을 두 번 들었다.** 이 목록에 없는 도구는 **subagent**가 호출할 때도
    똑같이 권한 승인을 거쳐야 한다. 무인 상태에서는 승인할 사람이 없으니, 에러도 나지 않고 멈추지도 않은 채 모델이 같은 호출을 반복 재시도한다
    (`toolDenialKind=user-rejected`). 실측: 워커에게 `WebFetch`/`WebSearch`를 추가하면서 `AgentDefinition.tools`에만
    적었더니, 그 실행은 스무 번 넘게 user-rejected가 나고 한 글자도 산출하지 못했다(`roles.py:513-518`).
    증상은 `disallowed_tools`보다 찾기 어렵다 — 후자는 그 자리에서 에러를 내지만, 전자는 화면상 아무것도 에러처럼 보이지 않는다.
    그래서 `coordinator()`는 이제 휘하 워커의 읽기 전용 web 도구를 자신의 `allowed_tools`에 합친다
    (`roles.py:523-526`). 반면 `Write`/`Edit`/`Bash`는 **의도적으로 합치지 않는다** — 합치면 위의 그 hook을
    해체하는 것과 같다.

## 언제 쓰면 안 되나 {#什么时候不该用它}

이 네 층이 아끼는 것은 모두 **현장**이다. 아래 문제들은 해결하지 못하고, 어떤 것은 이 층들 때문에 더 보이지 않게 된다:

1. **목표를 잘못 이해한 경우 — 이 네 층은 그것을 악화시킨다.** 현장이 버려지고 나면 남는 것이 하필 잘못된 전제 위에 세워진
   그 결정이고, 게다가 그것은 **올바른 결정과 똑같이 생겼다.** 롱호라이즌은 그것을 최악까지 증폭시킨다. 잘못된 전제로 먼저 몇 시간을 달리고,
   subagent를 십수 개 보내고, 디스크에 산출물을 잔뜩 남긴 뒤에야 드러난다. 그때 비싼 것은 token이 아니라, 산출물 하나하나가
   잘못된 요구에 맞춰 지어졌다는 사실이다. 이것을 막는 것은 [사전 확인](clarify.md)이지, 이 페이지의 어떤 층도 아니다.
2. **메인 스레드는 여전히 단조 증가한다.** 네 층이 누르는 것은 기울기지 방향이 아니다. 실측: 메인 스레드가 70턴 동안 28.7K에서
   185.9K로 늘었고, 기울기는 2.2K/턴, 전 구간 compact 없이 1M 윈도의 18.6%를 썼으며, **외삽하면 약 440턴에서 벽에 부딪힌다.**
   그 벽을 넘는 것은 [핸드오프](handoff.md)다.
3. **전량 compact를 끈 뒤에는 안전망이 없다.** 핸드오프가 켜져 있으면 `Runtime`은 spec에 강제로
   `CompactPolicy(mode="no_summary")`를 설정하고, auto-compact는 그것으로 꺼진다(spec이 스스로 `compact`를 명시했을 때만
   그것을 존중한다). 상한에 부딪히면 하드 에러이므로, 이 네 층은 반드시 핸드오프와 세트로 써야 하며, 그냥 compact만 꺼 놓고 끝낼 수 없다.
4. **4층은 resume 때만 작동한다.** 트림과 프루닝은 모두 `load()`에서 일어나므로, 연속으로 돌고 있는 세션은 그것 때문에
   작아지지 않는다. 위의 분업대로 하고 나면 이 층은 대개 쓸 일도 없다 — 메인 스레드는 애초에 도구 결과를 그리 많이 담지 못한다.
5. **흘긋 보는 일을 밖으로 위임하면 순손실이다.** subagent 기동은 약 4.3k다. 위 glance 절 참조.
6. **컨텍스트를 재배열하기 전에 캐시 계산부터 하라.** 실측으로 한 번의 실행 입력이 299.4M token이었고, **96.1%가 캐시에 적중**했다.
   $171로 성립한 것은 전적으로 그 덕이다. 히스토리를 다시 쓰는 어떤 최적화든 이 계산을 먼저 해야 한다.
7. **이미지, 문서류 도구 결과는 spill하지 않는다.** `spill_guard`는 출력 구조 안의 문자열 필드만 바꾸고, list는 일절 건드리지 않는다.

파라미터의 전체 기본값과 시그니처는 [Python API](../reference/api.md)를, 용어는 [용어집](../reference/glossary.md)을 보라.
