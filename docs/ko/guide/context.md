# 컨텍스트 경제학

[주 스레드](../reference/glossary.md#主线程)의 컨텍스트는 한 번의 [long-horizon](../reference/glossary.md#长程) 실행에서
처음부터 끝까지 이어지는 유일한 것이다. 거기에 무엇을 담고 무엇을 담지 않느냐가 이번 실행이 얼마나 멀리 갈 수 있는지를 결정한다.
flower의 형태 —— [코디네이터](../reference/glossary.md#协调者)는 직접 손대지 않고, 긴 산출물은 디스크에 내리고,
hook이 그 자리에서 쳐낸다 —— 는 전부 이 한 줄에서 나온 것이다. 이 페이지는 그 이유를 설명한다.

## 무엇을 해결하는가

[compact](../reference/glossary.md#压缩)는 컨텍스트가 다 찬 뒤에 되돌아가 요약하는 것이라, 증상만 다룬다. 진짜 문제는 이것이다:
**자잘한 것들은 애초에 주 스레드에 들어오면 안 된다.**

차이는 타이밍이다. `pytest` 한 번의 출력은 흔히 수만 자에 달한다. 모델은 한 번 보고 결론 하나를 얻지만, 나머지 문자는 그 뒤로
매 턴마다 다시 전송된다. 창이 다 차면 compact가 그것을 옆에 있던 결정과 함께 한 문단으로 요약해 버린다 —— 아끼는 것은 부피이고,
잃는 것은 "당시에 왜 그렇게 정했는지"다. auto-compact의 트리거 임계값은 **윈도우 − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py))인데,
그 시점에는 버려야 할 것과 버리면 안 되는 것이 이미 나란히 누워 있다.

flower는 네 개 층으로 해결하며, 순서가 곧 우선순위다 —— 아끼는 양 순으로:

| 층 | 하는 일 | 위치 |
|---|---|---|
| 1. 분업 | 직접 손대는 일은 [subagent](../reference/glossary.md#subagent)에 맡기고, 시행착오는 그 자신의 transcript로 들어간다 | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. 워크벤치 | 스크립트 / 긴 산출물 / 결정을 디스크에 내리고, 인덱스는 system prompt에 주입 | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. 즉시 spill | `PostToolUse` hook이 임계값을 넘은 도구 결과를 디스크에 내리고, 컨텍스트에는 경로 한 줄만 남긴다 | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. trim과 prune | resume 전에 세션을 다시 쓴다: 만료된 결과, 거부된 호출, 끊긴 연결의 잔해를 다시 먹이지 않는다 | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

앞의 두 층은 **들어올지 말지**를 관리하고, 뒤의 두 층은 **이미 들어온 것을 남길지**를 관리한다. 순서를 뒤집을 수 없다:
네 번째 층이 아무리 독해도 첫 번째 층에서 새어 들어온 양은 따라잡지 못한다.

## 어떻게 쓰는가 (최소 코드)

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model 기본값 "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

이 몇 줄이 앞의 세 층을 장착한다. `coordinator()`는 항상 `delegate_only=True`를 설정하고(1층),
`workbench=True`는 [워크벤치](../reference/glossary.md#工作台)를 만들고 인덱스를 코디네이터의 system prompt에 주입하며(2층),
동시에 `Runtime`에 `spill_guard`를 장착한다(3층). 4층은 기본적으로 이미 켜져 있다 —— `Runtime`의
[세션 스토어](../reference/glossary.md#会话存储)는 `PruningSessionStore`로 고정되어 있고, 생성자 인자에 이를 바꿀 통로는 없다.

!!! warning "`workbench=True`는 선택 사항이 아니다"
    코디네이터가 직접 손대는 것을 막는 `delegate_guard`는 `workbench_hooks` 안에 걸려 있고, `workbench_hooks`는
    `Runtime`에 워크벤치가 있을 때만 장착된다. 게다가 `whitelist_guard`는 `delegate_only=True` 때문에 건너뛰어진다.
    결론: **`Runtime(workbench=False)`에 `coordinator()`를 쓰면, 주 스레드의 Bash / Write / Edit에는
    벽이 하나도 없다.**

## 실제로 무엇을 하는가

### 1층: 분업 (가장 많이 아낀다)

코디네이터는 "Claude Code를 쓸 줄 아는 사람" 역할을 한다: 분해하고, 일을 맡기고, 보고서를 읽고, 결정한다.
Bash / Write / Edit는 받지 못한다 —— 도구는 `Agent`, `TodoWrite`, `Read`뿐이다
(`glance=True`일 때 제한된 `Bash` 하나가 추가된다. 아래 참조). 직접 손대는 일은 전부
[워커](../reference/glossary.md#执行者)에게 맡긴다.

**언제 발동하는가**: 주 스레드가 `Bash|Write|Edit|NotebookEdit`를 호출할 때마다 `PreToolUse` hook
`delegate_guard`가 그 자리에서 deny하고 길을 알려준다 —— "Agent 도구로 subagent를 하나 보내라. 작업에 목표와
수용 기준을 명확히 쓰고, 긴 산출물은 `.flower/artifacts/`에 쓰고 응답에는 경로와 결론만 담으라고 요구하라."
subagent는 전부 통과시킨다. 판정 기준은 hook 데이터에 `agent_id`가 있는지다: **없으면 주 스레드다.**

**얼마나 아끼는가**: subagent의 도구 호출과 시행착오는 **그 자신의 transcript로 들어가고**(세션 스토어에서는 `subpath`로
구분한다), 주 스레드에는 그 한 번의 `Agent` 호출과 최종 보고서만 남는다. 시행착오 과정은 compact로 지워진 것이 아니라,
**애초에 주 스레드에 들어온 적이 없다.**

- 실측(도구 출력이 대량으로 발생하는 작업): transcript의 83%가 subagent 쪽에 떨어졌고,
  주 스레드는 13개 항목, 21K 문자, subagent는 105K 문자.
- 실측(실제 규모, 10.4시간짜리 실행 한 번, [HT001](../cases/ht001.md) 참조): subagent가
  **97.7%**의 턴, **94.8%**의 본문 문자를 담당했다. 직접 손대는 도구 호출은 1,893회 vs 주 스레드 32회(**59:1**).
  이른 시점의 compact는 더 이상 주된 문제가 아니다.

두 줄은 서로 다른 두 번의 측정이다. 위는 이전의 소규모 테스트, 아래는 실제 규모에서의 재측정이다. 같은 메커니즘이고,
규모가 클수록 더 많이 아낀다.

아끼는 것은 컨텍스트이지 모델 등급이 아니다: `worker()`의 기본값은 `model="inherit"` —— 워커는 다운그레이드되면 안 된다.

분업의 유일한 역방향 비용은 [태스크 브리프](../reference/glossary.md#任务书)다 —— 코디네이터가 일을 맡길 때 쓰는 그 문단은
주 스레드에 들어가고, 게다가 영구히 남는다. 실측 결과 8/8건의 태스크 브리프가 상대가 이미 아는 규율을 되풀이하고 있었고,
가장 짧은 것도 521자 중 작업 고유 내용은 약 120자뿐이어서, 한 턴에 약 4.8k의 영구 컨텍스트를 헛되이 차지했다. 그래서
`COORDINATOR_RULES`에는 한 줄이 고정되어 있다: **태스크 브리프에는 이번 작업 고유의 것만 쓴다.** 그럼에도 여전히 전달해야 하는
규칙은 "워크벤치가 어디 있는지 + 긴 산출물은 `artifacts/`에 + 응답에는 경로와 결론만"뿐이다 —— 워크벤치 인덱스는 subagent에
들어가지 못하므로, 태스크 브리프가 유일한 통로이기 때문이다.

### 2층: 워크벤치 ("매번 다시 쓰기"를 다룬다)

`.flower/` 아래 세 디렉터리가 워크스페이스를 따라다닌다:

| 디렉터리 | 무엇을 두는가 | 무엇을 해결하는가 |
|---|---|---|
| `scripts/` | 두 번째로 실행될 검증 / 재현 스크립트. 첫 줄에 `# desc: 한 줄 설명` | 한 번 쓰고 이후에는 그냥 실행. "compact 후 사라져서 매번 다시 작성"이 없어진다 |
| `artifacts/` | 2000자를 넘는 긴 산출물: 로그, 데이터, 보고서, diff | 대화에는 경로와 결론만 나타난다 |
| `notes/` | 핵심 결정과 이유. 결정 하나당 파일 하나 | compact되든, 재시작되든, 기계를 바꾸든 결론은 남아 있다 |

**언제 발동하는가**: `INDEX.md`는 자동 생성되며(기본 최대 40개 항목), `refresh()`는 `Write` / `Edit`가 워크벤치 안에 떨어질 때
`PostToolUse`의 `index_guard`가 호출하고, 각 스텝이 시작되기 전에도 한 번 갱신된다. 위의 세 규칙은
`prompt_block()`이 코디네이터의 system prompt에 주입한다 —— 코디네이터는 시작하자마자 어떤 기성 스크립트가 있는지 알고,
그것을 발견하기 위해 도구 호출을 한 번 쓸 필요가 없다.

**얼마나 아끼는가**: 10.4시간짜리 실행 한 번을 실측했을 때, **61개 스크립트가 95번 작성되고 331번 실행되었다. 92%가 한 번 이상
실행되었고, 쓰기만 하고 실행하지 않은 것은 0개였다.** 정성적으로는 `audit-fake-ai-server.py`가 7개 스크립트에서 재사용되었다.

이 층이 효과가 있는 것은 한 가지 차이 덕분이다: compact는 컨텍스트를 지울 수 있지만, **디스크는 지우지 못하고, system prompt
안의 인덱스도 지우지 못한다.**

!!! warning "인덱스는 subagent가 상속하지 못한다"
    인덱스는 세션 수준의 `system_prompt.append`를 탄다. subagent는 자기 자신의 system prompt를 가지므로
    **상속하지 못한다**(실측 $0.2461, `tests/prelude_live.py`). 그래서 "워크벤치가 어디 있는지 + 긴 산출물은
    `artifacts/`에"는 코디네이터가 태스크 브리프에서 반드시 옮겨 적어야 한다 —— 그것이 유일한 통로이지, 중복이 아니다.

### 3층: 즉시 spill

`spill_guard`는 `PostToolUse` hook으로, 도구 결과가 **모델에 들어가기 전에** 한 번 들여다본다. `threshold`
(기본 **4000**자)를 넘으면 워크벤치의 `spill/` 디렉터리로 [spill](../reference/glossary.md#落盘)하고,
컨텍스트에서는 포인터 한 줄 + **앞부분 400자**로 바꾼다. 내용은 사라지지 않고, 다만 상주하지 않을 뿐이다.

**언제 발동하는가**: matcher는 `Bash|Read|Grep|Glob|WebFetch|WebSearch`이고, 기본값이 `main_only=False`이므로
subagent의 결과도 spill된다. 도구 출력 구조 안에서 지나치게 긴 **문자열 필드**만 교체하고, list는 절대 건드리지 않는다
(안에 이미지 블록이 있을 수 있다). `updatedToolOutput`은 원래 도구의 출력 구조를 유지해야 하기 때문이다.

**spill된 파일 자체를 읽는 것은 통과시키고, 다시 spill하지 않는다.** 그러지 않으면 그 안내 줄에 있는 "전문이 필요하면 Read로
읽으라"는 말이 빈말이 된다: 읽어오면 또 임계값을 넘고, 또 spill되고, 또 포인터 한 줄을 주는 무한 루프다. 실측에서 부딪혔다
(`tests/handoff_live.py`를 처음 실제로 돌렸을 때). 모델은 다섯 가지 방식으로 우회를 시도하다가 스스로
"The spill read loops back on itself"라고 말했고, 결국 40줄씩 힘겹게 읽어내며 일고여덟 턴을 태웠다. spill의 의미는
"**자동으로** 큰 것을 컨텍스트에 밀어넣지 않는다"이다. 모델이 스스로 전문을 보겠다고 결정한다면 그건 그의 선택이다.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None 또는 0 = 이 hook을 장착하지 않음
```

**얼마나 아끼는가**: [HT001](../cases/ht001.md)의 그 실행에서 103번의 spill로 791.4K 문자가 경로 포인터로 바뀌었고,
컨텍스트에 상주하지 않았다.

### 4층: trim과 prune

이 층은 [세션 스토어](../reference/glossary.md#会话存储) 안에 있다. `Runtime`의 store는 언제나
`PruningSessionStore`이며(상속 체인 `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), `load()`에서 —— 즉 **resume 직전에** —— 다시 먹일 히스토리를 한 번 다시 쓴다.
SQLite 안의 원문은 한 글자도 건드리지 않는다. 네 가지를 한다:

**① 시효 만료**(`ephemeral`, 기본 켜짐). `git status`, `ls`, `cat` 같은
[일회성 명령](../reference/glossary.md#一次性命令)의 결과는 몇 턴이 지나면 본문이 설명 한 줄로 바뀌고,
최근 6개를 남긴다. 만료된 내용은 **spill하지 않는다** —— 옛날 `git status` 한 벌을 보관하는 것은 의미가 없고,
다시 한 번 실행하면 되기 때문이다:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

라이브 resume 실측에서 `expired: 2`였고, 실제 transcript에서 `keep_recent`를 2로 낮추자 5개가 만료되었다.

**② [trim](../reference/glossary.md#裁剪)**(`trim`, **기본 꺼짐**). `>= 2000`자인 tool_result 본문을
`<workspace>/.flower/spill/`로 spill하고 블록 내용을 파일 포인터로 바꾸며, 최근 20개의 원문을 남긴다. 이 디렉터리는
3층 `spill_guard`의 spill 디렉터리와 **같은 것이 아니다**: 후자는 워크벤치 루트 아래에 쓰지만, 여기 것은 반드시
워크스페이스 안에 떨어져야 한다. 그러지 않으면 agent의 `Read`가 닿지 못한다.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True도 가능
```

**③ 거부된 호출 [prune](../reference/glossary.md#剪除)**(`keep_denials`, 기본 1). 막아낸다는 행위 자체도 컨텍스트를
오염시킨다: 거부 메시지는 `tool_result` 하나이고, **한 번도 실행된 적 없는 그 명령**과 함께 영구히 남는다.
실측 한 번에 273자(거부 문구 93자 + 죽은 명령 180자)로, 죽은 명령이 거부 문구보다 비쌌다.

token보다 더 중요한 것은 그것이 **오도한다**는 점이다. 실측에서 코디네이터는 "Bash를 직접 쓰지 말라"는 문구를 몇 개 읽은 뒤,
통과되는 `git status`조차 시도하지 않고 곧장 "Bash가 제한되어 있으니 agent를 보내서 보게 하자"고 말했다 —— 학습된 무기력을
배운 것이고, 오히려 subagent 기동 비용을 한 번 더 쓴다. 기본값을 0이 아니라 1로 둔 이유: 가장 최근의 거부는 유효한 신호이며,
모델이 같은 턴에서 막힌 명령을 반복해서 재시도하는 것을 막아준다. 식별은 harness가 스스로 붙인 구조적 표식
`toolDenialKind: "permission-rule"`에 의존하며, 문구 매칭이 아니다 —— 문구는 언제든 바뀌지만 표식은 바뀌지 않는다.
라이브 실측: 2회 거부 → 1개 제거, 1개 유지. 체인은 끊기지 않았고 resume는 정상이었으며 모델은 여전히 무슨 일이 있었는지 알았다.

**④ 끊긴 연결의 잔해 prune.** 네트워크 단절 재시도 중에 생성된 합성 API 오류 메시지는 다시 먹이지 않는다. 중단으로 남겨진
`tool_result`는 중립적인 설명 한 줄(`[上一轮在此处被中断,该工具结果未产生]`)로 바꾸되, 항목 자체는 남긴다.

**제거할 때의 레드라인**: `tool_use`와 그에 대응하는 `tool_result`는 반드시 **함께** 제거해야 하고(하나라도 빠지면
`Missing Tool Result Block`), 같은 assistant 메시지 안의 다른 호출을 잘못 건드리면 안 되며, `parentUuid` 체인은
다시 이어 붙여야 한다.

`Runtime(trim=False)`(기본값)는 **아무것도 정리하지 않는다는 뜻이 아니다**: 큰 결과의 trim만 끄는 것이고, 만료, 거부된 호출,
끊긴 연결의 잔해는 그대로 처리한다.

### 반례: 한 번 보고 마는 일은 직접 한다

앞의 세 층은 모두 "밖으로 맡겨라"라고 말하지만, 반례가 하나 있다: `git status`, `ls`, `cat` 같은 명령은 결과가 수십 자인데,
**subagent 하나를 보내면 기동만으로 약 4.3k 컨텍스트가 든다**(실측, 분할 상각 불가). `ls` 하나를 위해 이 값을 치르는 것은
순손실이다.

그래서 코디네이터는 제한된 Bash를 되돌려 받는다(`coordinator(..., glance=True)`, 기본 켜짐). 판정 기준은 "명령이 짧은가"가
아니라 **결과가 만료될 것인가**이며, "통과"와 "만료"는 같은 함수 `is_ephemeral()`이 결정한다:

| | 직접 실행 통과 | 결과가 만료로 표시됨 |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ 위임 | — |

양쪽은 반드시 같은 표여야 한다. 그러지 않으면 어느 한쪽만 성립해도 해롭다: **통과시키고 trim하지 않으면** 만료된
`git status`가 영구히 컨텍스트를 차지하고, 현재 상태로 오인되어 결정을 오도한다. **trim하면서 통과시키지 않으면**
코디네이터는 `ls` 하나에 4.3k를 치러야 한다. `tests/glance.py`는 이 불변식을 assertion으로 못박았다 ——
실측 46개 명령에서 양쪽 판정이 완전히 일치했고, 여기에는 적대적 샘플 10개가 포함된다.

**함정(두 번 밟았다)**: 모델은 단일 명령을 쓰지 않는다. 모델이 쓰는 것은
`git status -s && echo "--- LOG ---" && git log --oneline -10`이다. 첫 버전은 `&&` / `|` / `2>&1`이 포함된
명령을 일괄 거부했고, 그 결과 **glance가 완전히 무력화되었다** —— 실측에서 코디네이터의 세 번의 시도가 모두 막혔고,
결국 다시 subagent를 보내야 했다. 지금은 구간별로 분해해 검사한다: 모든 구간이 화이트리스트에 있어야 통과하고,
`git status && rm -rf x`는 여전히 막힌다(뒷 구간이 표에 없다).

### append이지, 대체가 아니다

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

`build_options()`가 `AgentSpec`을 SDK 옵션으로 컴파일할 때 `instructions`는
[`append`](../reference/glossary.md#叠加)를 탄다 —— Claude Code 기본 시스템 프롬프트 **뒤에** 덧붙이는 것이지,
대체하는 것이 아니다. 그래서 위의 규율 텍스트들(`COORDINATOR_RULES`, `WORKER_RULES` 등)은 덧셈이다:
**전문화가 범용 능력의 손실을 대가로 하지 않는다.**

워크벤치 인덱스도 이 통로를 탄다. 매 턴 존재하지만 system prompt의 일부이므로 대화 히스토리를 차지하지 않고,
compact로도 지워지지 않는다 —— 대가는 위에 적은 그것이다: **코디네이터까지만.**

!!! warning "코디네이터가 손대지 못하게 하는 데 `disallowed_tools`를 쓰지 마라"
    `disallowed_tools`는 **세션 수준**이라, subagent까지 함께 금지한다. 실측 오류 원문:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    올바른 방법은 두 단계다: `allowed_tools`에 넣지 않고, 그다음 `PreToolUse` hook으로 `agent_id`에 따라 주 스레드만 막는다.
    `coordinator()`는 이미 그렇게 하고 있다 —— `delegate_only=True`를 설정하고, `delegate_guard`가 주 스레드를 막고
    subagent는 통과시킨다.

    `allowed_tools`만으로도 충분하지 않다: 그것은 **승인 면제 목록이지, 배타적 화이트리스트가 아니다.** 실측에서 모델은
    거기에 없는 도구를 호출할 수 있었다 —— $0.1짜리 프로브 하나에서 `allowed_tools=["Read"]`인 agent가 Write / Bash를
    멀쩡히 호출했다. 실제로 막는 것은 hook이다.

## 언제 쓰면 안 되는가

이 네 층이 아끼는 것은 전부 **현장**이다. 아래 문제들은 이 층들이 해결하지 못하며, 일부는 오히려 이 층들 때문에 더 보이지 않게 된다:

1. **목표를 잘못 이해한 경우 —— 이 네 층은 그것을 더 심각하게 만든다.** 현장이 버려진 뒤에 남는 것은 정확히 그 잘못된 전제 위에
   세워진 결정이고, 게다가 그것은 **올바른 결정과 똑같아 보인다.** long-horizon은 그것을 최악까지 증폭한다: 잘못된 전제로 몇 시간
   달리고, 십수 개의 subagent를 보내고, 디스크에 산출물을 잔뜩 남긴 뒤에야 드러난다. 그때 비싼 것은 token이 아니라, 모든 산출물이
   잘못된 요구에 맞춰 만들어졌다는 사실이다. 이것을 막는 것은 [사전 확인](clarify.md)이지, 이 페이지의 어떤 층도 아니다.
2. **주 스레드는 여전히 단조 증가한다.** 네 층이 누르는 것은 기울기이지 방향이 아니다. 실측: 주 스레드가 70턴 동안 28.7K에서
   185.9K로 늘었고, 기울기는 2.2K/턴, 전 구간 compact 없이 1M 윈도우의 18.6%를 썼으며, **외삽하면 약 440턴에서 벽에 부딪힌다.**
   그 벽을 넘는 것은 [핸드오프](handoff.md)다.
3. **전량 compact를 끈 뒤에는 안전망이 없다.** 핸드오프가 켜져 있으면 `Runtime`은 spec에
   `CompactPolicy(mode="no_summary")`를 강제로 설정하고, auto-compact는 그로써 꺼진다(spec이 직접 `compact`를 명시했다면
   그것을 존중한다). 상한에 부딪히면 하드 에러이므로, 이 네 층은 반드시 핸드오프와 짝지어 써야 하며, compact를 끄는 것만으로
   끝낼 수 없다.
4. **4층은 resume 때만 작동한다.** trim과 prune은 모두 `load()`에서 일어나므로, 계속 이어서 돌고 있는 세션은 이 때문에
   작아지지 않는다. 위의 분업을 따르고 나면 이 층은 대개 쓸 일도 없다 —— 주 스레드에는 애초에 도구 결과가 별로 들어가지 않는다.
5. **한 번 보고 마는 일을 밖으로 보내면 순손실이다.** subagent 기동에 약 4.3k. 위의 glance 절 참조.
6. **컨텍스트를 재배열하기 전에 캐시 계산을 먼저 하라.** 실측 한 번의 실행에서 입력 299.4M token 중 **96.1%가 캐시에
   적중했고**, $171이 성립한 것은 전적으로 그 덕이다. 히스토리를 다시 쓰는 어떤 최적화든 이 계산을 먼저 해야 한다.
7. **이미지, 문서류 도구 결과는 spill하지 않는다.** `spill_guard`는 출력 구조 안의 문자열 필드만 바꾸고, list는 절대 건드리지 않는다.

파라미터의 전체 기본값과 시그니처는 [Python API](../reference/api.md) 참조. 용어는 [용어집](../reference/glossary.md) 참조.
