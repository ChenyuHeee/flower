# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Claude Agent SDK 기반의 이식 가능한 long-horizon agent 프레임워크.</p>

<p class="fl-hero__sub">Claude Code의 능력을 희생하지 않은 채, 그것을 들고 다닐 수 있고 상호작용을 커스터마이즈할 수 있으며 며칠씩 돌릴 수 있는 전용 agent로 바꾼다.
main thread 위의 agent는 결정만 내리고, 손을 쓰는 일은 전부 subagent에 넘긴다. 요구사항은 먼저 물어서 분명히 한 뒤에 착수하고, 다 됐는지 안 됐는지는 다른 역할이 판정한다.
다른 기계로 옮겨도 동작이 같다 — 호스트 머신의 설정을 읽지 않고, 자격 증명은 스스로 들고 다닌다.</p>

[빠른 시작](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>한 번의 run에 든 비용</span></div>
<div class="fl-stat"><b>10.4 hours</b><span>연속 실행, 중간에 끊긴 네트워크를 스스로 이어붙임</span></div>
<div class="fl-stat"><b>185.9K</b><span>main thread 컨텍스트 최고치, 전 구간 compact 없음</span></div>
<div class="fl-stat"><b>94.8%</b><span>본문 문자가 subagent에 떨어진 비율</span></div>
</div>

네 개의 숫자는 [HT001](cases/ht001.md)에서 나왔다 — 한 agent가 flower 위에서 터미널 IDE를 맨바닥부터 써낸 그 run이다.

## 설치 {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

`uv` / `pipx` / `pip`를 자동으로 찾아 `flower` 명령을 설치한다. Python ≥ 3.10만 있으면 되고, Node도 Claude Code CLI도 필요 없다.
설치가 끝나면 아무 프로젝트 디렉터리로 `cd`해서 `flower` 한 줄만 치면 된다. 처음에는 API key나 게이트웨이 주소를 물어보고, 한 번 설정하면 `~/.config/flower/.env`에 저장되어 어디서나 유효하다. 이미 이 머신에 Claude Code가 설치되어 설정까지 되어 있다면 그 token을 그대로 빌려 쓰고, 묻지도 않는다. 전체 절차와 트러블슈팅은 [설치](getting-started/install.md)를 보라.

## 네 종류의 실패를 대신 막아준다 {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [전치 확인](guide/clarify.md) {#前置确认}

만들어놨더니 원하던 게 아닐까 봐 — 착수 전에 질문만 하고 손은 대지 않는 역할이 분명해질 때까지 캐묻고, 요구사항을 하나의 문서로 얼려둔다. 이후 모든 단계는 그것을 읽으며 시작한다.
</div>

<div class="fl-card" markdown>
### [목표 감시](guide/goal.md) {#目标看守}

다 됐다고 말해놓고 실은 안 됐을까 봐 — 매 라운드가 끝날 때마다 다른 역할이 독립적으로 한 번 판정한다. 달성했으면 앞으로 가고, 못 했으면 되돌려 보내고, 이 환경에서 검증이 불가능하면 멈춰서 사람에게 묻는다.
</div>

<div class="fl-card" markdown>
### [접속 지속](guide/continuity.md) {#接续}

몇 시간 돌다 죽어서 처음부터 다시 할까 봐 — 같은 디렉터리에서 `flower`를 한 번 더 치면 지난번 진행 상황에 이어붙는다. 프로세스가 kill되든 머신이 재부팅되든 마찬가지고, 어떤 id도 기억할 필요가 없다.
</div>

<div class="fl-card" markdown>
### [세대 교체](guide/handoff.md) {#换代}

컨텍스트가 꽉 차서 요약 한 토막으로 압축될까 봐 — 현재 session이 사람이 읽고 고칠 수 있는 인계 문서를 직접 쓰고, 새 session이 이어받는다. compact는 쓰지 않는다.
</div>

</div>

## 무엇으로 "long-horizon"인가 {#长程}

main thread 위의 [coordinator](reference/glossary.md#协调者)에는 결정만 들어 있고 `Write`와 `Edit`는 주어지지 않는다 — 코드 작성, 테스트 실행, 자료 조사는 전부 [subagent](reference/glossary.md#subagent)에 넘긴다. subagent의 시행착오는 **또 다른** transcript로 들어가고, main thread는 30줄을 넘지 않는 보고서 하나만 받는다.
HT001의 그 10.4시간짜리 run에서 **본문 문자의 94.8%가 subagent에 떨어졌고**, 손을 쓰는 도구 호출 1,893회 중 32회만이 coordinator의 시야에 들어왔다.
그래서 main thread는 70라운드 만에야 185.9K까지 올라갔고 전 구간에서 compact가 한 번도 일어나지 않았다 — 이 층을 어떻게 만들었는지, 나머지 세 층은 무엇인지는 [컨텍스트 경제학](guide/context.md)에 있다.

## 실제로 돌려봤다 {#真的跑过}

- **[HT001](cases/ht001.md)** — 터미널 IDE를 맨바닥부터 작성. $171.62 / 10.4시간 / main thread 컨텍스트는 185.9K까지 올라갔고, 제품 코드 12,212줄을 내놓았다. 중간에 네트워크가 한 번 끊겼지만 스스로 이어서 끝까지 돌았다.
- **[HT002](cases/ht002.md)** — 이것을 macOS에 설치해 돌리기. $38.24 / 약 1시간, goal guard를 처음 붙인 run이다. 프로그램은 실제로 돌아갔지만, 판정 결론은 **달성 불가**였고 사람에게 물으러 떠올랐다.

두 페이지 모두 버티지 못하는 지점을 적어두었다. HT001에서는 agent가 스스로 내린 인수 판정 중 한 항목을 틀리게 판단했고, HT002는 `git clone && make && ./cppide`를 한 시간짜리로 만들어버렸다. 모든 숫자는 `runs/manifest.json`과 `sessions.db`에서 재계산할 수 있다 — 이건 원시 기록이지 홍보물이 아니다.

## 어디부터 읽을까 {#从哪读起}

- **당장 돌려보고 싶다** — [빠른 시작](getting-started/quickstart.md): 먼저 몇 십 원어치로 자격 증명을 한 번 검증하고, 그다음 코드 없이 3단계 workflow를 한 번 끝까지 돌린다.
- **개념부터 이해하고 싶다** — [핵심 개념](getting-started/concepts.md): run, step, session, 다섯 역할을 5분 안에 한 번에 설명한다.
- **자기 코드에 붙이고 싶다** — [Python API](reference/api.md): `Runtime`, `Step`, 다섯 개의 역할 팩토리, 공개 심볼 62개의 시그니처와 기본값.
