# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Claude Agent SDK 기반의 이식 가능한 long-horizon agent 프레임워크.</p>

<p class="fl-hero__sub">Claude Code의 능력을 희생하지 않으면서, 그것을 들고 다닐 수 있고 상호작용을 직접 정의할 수 있으며 며칠씩 돌릴 수 있는 전용 agent로 바꾼다.
메인 스레드 위의 agent는 결정만 하고, 실제로 손을 대는 일은 전부 subagent에게 맡긴다. 요구사항은 먼저 명확히 물어본 뒤에 착수하고, 다 됐는지 안 됐는지는 다른 역할이 판정한다.
다른 기기로 옮겨도 동작이 같다 — 호스트 머신의 설정을 읽지 않고, 자격 증명은 스스로 들고 다닌다.</p>

[빠른 시작](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>한 번의 run 비용</span></div>
<div class="fl-stat"><b>10.4 시간</b><span>연속 실행, 도중에 끊긴 네트워크를 스스로 이어붙임</span></div>
<div class="fl-stat"><b>185.9K</b><span>메인 스레드 컨텍스트 최고치, 전 구간 compact 없음</span></div>
<div class="fl-stat"><b>94.8%</b><span>본문 문자 중 subagent에 떨어진 비율</span></div>
</div>

네 개의 숫자는 [HT001](cases/ht001.md)에서 나왔다 — 한 agent가 flower 위에서 터미널 IDE를 맨바닥부터 작성한 그 run이다.

## 명령 하나로 설치, Node 불필요 {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

스크립트가 `uv` / `pipx` / `pip`를 알아서 찾아 `flower` 명령을 설치한다. Python ≥ 3.10만 있으면 되고,
Claude Code CLI도 설치할 필요 없다. 설치가 끝나면 아무 프로젝트 디렉터리로 `cd` 해서 `flower`라고 치면 된다. 처음에는 API key나
게이트웨이 주소를 물어보고, 한 번 설정하면 `~/.config/flower/.env`에 저장되어 어디서나 적용된다. 이미 Claude Code를 설치하고 설정해 둔 기기라면
그 token을 그대로 빌려 쓰고, 아무것도 묻지 않는다. 전체 절차와 문제 해결은 [설치](getting-started/install.md)를 보라.

## 네 가지 실패를 대신 막아준다 {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [사전 확인](guide/clarify.md) {#前置确认}

만들어 놓고 보니 원하던 게 아닐까 봐 — 착수하기 전에 질문만 하고 손은 대지 않는 역할이 명확해질 때까지 묻고,
요구사항을 문서 하나로 얼려 둔다. 이후 모든 단계는 그것을 읽고 시작한다.
</div>

<div class="fl-card" markdown>
### [목표 가드](guide/goal.md) {#目标看守}

다 했다고 말하지만 실은 안 됐을까 봐 — 매 라운드 작업이 끝날 때마다 다른 역할이 독립적으로 한 번 판정한다. 달성이면 다음으로 가고, 미달성이면 되돌리고,
이 환경에서 검증할 수 없으면 멈춰서 사람에게 묻는다.
</div>

<div class="fl-card" markdown>
### [연속성](guide/continuity.md) {#接续}

몇 시간 돌리다 죽어서 처음부터 다시 할까 봐 — 같은 디렉터리에서 `flower`를 한 번 더 치면 지난번 진행 지점으로 이어진다. 프로세스가 kill 되거나
머신이 재부팅돼도 마찬가지고, 어떤 id도 외울 필요 없다.
</div>

<div class="fl-card" markdown>
### [핸드오프](guide/handoff.md) {#换代}

컨텍스트가 가득 차서 요약 한 토막으로 압축될까 봐 — 현재 session이 사람이 읽고 고칠 수 있는 핸드오프 문서를 스스로 쓰고, 새 session이 이어받는다.
compact는 쓰지 않는다.
</div>

</div>

## 무엇이 "long-horizon"을 가능하게 하나 {#长程}

메인 스레드의 [코디네이터](reference/glossary.md#协调者)는 결정만 담고 `Write`와 `Edit`을 받지 못한다 —
코드 작성, 테스트 실행, 자료 조사는 전부 [subagent](reference/glossary.md#subagent)에게 넘긴다.
subagent의 시행착오는 **다른** transcript로 들어가고, 메인 스레드는 30줄을 넘지 않는 보고서 하나만 받는다.
HT001의 그 10.4시간 run에서 **본문 문자의 94.8%가 subagent에 떨어졌고**,
손을 댄 1,893번의 도구 호출 중 코디네이터의 시야에 들어온 것은 32번뿐이었다.
그래서 메인 스레드는 70 라운드가 지나서야 185.9K에 이르렀고 전 구간에서 compact가 한 번도 일어나지 않았다 — 이 층위를 어떻게 만들었는지, 나머지 세 층은 무엇인지는
[컨텍스트 경제학](guide/context.md)을 보라.

## 실제 장시간 run 두 번의 원본 기록 {#真的跑过}

- **[HT001](cases/ht001.md)** — 터미널 IDE를 맨바닥부터 작성. $171.62 / 10.4 시간 /
  메인 스레드 컨텍스트는 185.9K까지 올랐고, 12,212 줄의 제품 코드를 내놓았다. 도중에 한 번 네트워크가 끊겼지만 스스로 이어서 끝까지 갔다.
- **[HT002](cases/ht002.md)** — 그것을 macOS에 설치해서 돌리기. $38.24 / 약 1 시간, 목표 가드를 처음 붙인 run.
  프로그램은 실제로 돌아갔지만, 판정 결론은 **미달성**이었고 사람에게 물으러 올라왔다.

두 페이지 모두 설득력이 없는 부분을 적어 두었다. HT001에서는 agent가 스스로 내린 검수 판정 하나가 틀렸고,
HT002는 `git clone && make && ./cppide`를 한 시간짜리로 만들었다. 모든 숫자는 `runs/manifest.json`과
`sessions.db`에서 다시 계산할 수 있다 — 홍보가 아니라 기록이다.

## 어디부터 읽을까 {#从哪读起}

- **당장 돌려보고 싶다면** — [빠른 시작](getting-started/quickstart.md): 명령 세 개로 실행하고,
  그다음 화면에 흘러가는 것을 읽는 법을 알려준다.
- **개념부터 이해하고 싶다면** — [핵심 개념](getting-started/concepts.md): run, 스텝, session, 다섯 역할을
  5분에 한 번에 설명한다.
- **자기 코드에 붙이고 싶다면** — [Python API](reference/api.md): `Runtime`, `Step`, 다섯 역할 팩토리,
  공개 심볼 62개의 시그니처와 기본값.
