# インタラクション層を差し替える

flower のコアは UI の存在を知らない。実行の中で起きるすべて——モデルが話す、ツールを呼ぶ、コンテキストがもうすぐ満杯、人に一言尋ねたい——は、同じ一つのデータ構造 [`Event`](../reference/glossary.md#事件) に平坦化される。
**[インタラクション層](../reference/glossary.md#交互层)は `Event` しか知らず、SDK の型を一切 import しない。**
これが、UI を替えてもコアに手を入れずに済む境界だ。ターミナル、Web、HTTP サービス、全自動の無人運転——差し替わるのは `Event` の消費者であって、それ以外は一行も変わらない。

## 解決する問題 {#解决什么问题}

SDK のメッセージストリームは**内部型**だ:`AssistantMessage`、`ToolUseBlock`、`ToolResultBlock`、`ResultMessage`、`SystemMessage`……。UI がこれらを直接消費すると結果は 2 つ。SDK が上がるたびにフロントエンドも直さなければならない。そしてメッセージごとに形が違うので、UI ごとに「これは本文かツール呼び出しか」の判定を毎回書き直すことになる。

`normalize(message)` は 1 本の SDK メッセージを 0 〜 N 個の `Event` に変換する([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py))。コストは一度の変換、引き換えに得られるのはインタラクション層と SDK のあいだに型依存が無いことだ。

この境界は、ついでに自明でないことを 4 つ片づけている。4 つとも `normalize()` の中にある:

1. **[subagent](../reference/glossary.md#subagent) の発言に印がつく**(`payload["subagent"]`)。
   そうしないと、仕事を振る[タスクブリーフ](../reference/glossary.md#任务书)や subagent の途中発言が[メインスレッド](../reference/glossary.md#主线程)の本文に混ざり、さらに[ワークフロー](../reference/glossary.md#流程)をたどって次のステップの prompt を汚染する。
2. **切断時の合成エラーメッセージが `kind="error"` に振り分けられる**。切断時、SDK 側は `API Error: …` を assistant メッセージとして transcript に書き込む。それはモデルの発言そっくりに見える(`model` が `"<synthetic>"`)。ここで止めなければ `StepResult.text` に入り、次の[ステップ](../reference/glossary.md#步骤)へ渡ってしまう。
3. **compact 境界が明示的に報告される**(`kind="reset"`)。境界の後にモデルが「覚えている」のは要約だけで、prompt キャッシュもここで切れる——[long-horizon](../reference/glossary.md#长程) な実行では、これが見えなければならない。
4. **コンテキスト水位が各メッセージに付いて出てくる**(`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`)。これが[ハンドオフ](../reference/glossary.md#换代)判定の唯一の情報源だ。

## 使い方(最小コード) {#怎么用最小代码}

インタラクション層がつなぐのは 3 つ:**イベント出口**(どこへ描くか)、**質問チャネル**(誰が答えるか)、**割り込み**(どう止めるか)。次のコードは全部つないである。そのまま動く:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event を自分の UI に描く —— 差し替えが必要なのはここだけ。"""
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
    # kind == "ask" で mail でないものは、下の answerer に任せる(プル式)


async def answerer(ch: HumanChannel) -> None:
    """プル式で質問を取る。Web / HTTP に替えるとき、このコルーチンがもう一箇所の変更点。"""
    while True:
        ask = await ch.next_ask()           # timeout を渡さなければずっと待つ
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # または ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime は workflow 自身が作ったワークベンチを使う —— 別に組み立てないこと
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # SQLite 接続を閉じる
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

見落としやすい後始末が 2 つ。`rt.close()` は必ず `finally` に置く。`ctx["_failed_at"]` に値があれば途中で止まったということ(`on_fail="stop"`)なので、成功扱いにしないこと。

!!! note "ワークベンチは一つ、別に組み立てないこと"
    `Runtime(workbench=True)` が作る[ワークベンチ](../reference/glossary.md#工作台)は
    `<run_dir>/workbench` にあり、`Workbench(ws)` のデフォルトは `<ws>/.flower` ——
    この 2 つは同じディレクトリではない。ドライバが自分でパスを組み立てて `需求.md` を探すと、
    「ブリーフは A ディレクトリに書かれ、注入されるインデックスは B ディレクトリを走査する」
    という状態になり、しかもエラーにならない。
    workflow が作ったものを `Runtime` に渡す(上の書き方)か、
    読み取り専用の探査 `wake_state()` で場所を聞くか、どちらかにすること。

### 3 つのイベント出口 {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. 単一の agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. ワークフロー全体、各ステップへ引き渡す
wf = Workflow(steps=[...], channel=ch)                  # 3. 質問チャネルも同じ出口へ
```

3 つ目のつなぎ方は `Workflow.run` の中にある。**`on_event` が `None` でなく、かつ `channel.on_event` がまだ `None` のときだけ自動でつなぐ**。自分でつないであれば上書きされない:

```python
ch = HumanChannel(on_event=my_own_sink)     # 自分でつなぐ。Workflow は触らない
```

`on_step(step, result)` はもう一つのコールバックで、各ステップが終わるたび(**失敗を含む**)に一度呼ばれ、完全な `StepResult` が渡される。プログレスバー、ディスクへの書き出し、アラートはここに掛ける。そのために `Event` ストリームから組み立てようとしないこと——本文はハンドオフとリトライで何段にも分断される。

### ターミナル:デフォルトのもの {#终端默认的那个}

コードを書かなくても一つある。`flower "帮我做一个 X"` が通るのは [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py) で、これはインタラクション層の**参照実装であって、フレームワークの一部ではない**。丸ごと差し替えられる。スイッチ類は [CLI リファレンス](../reference/cli.md) を参照。
規模は正直に書く。`cli.py` は全体で 1264 行、57KB —— だが**差し替えるのは全体ではない**。
本当の置換点はその中の `class Render`(`cli.py:489-687`、197 行)で、docstring にこう書いてある:「Event → ターミナル。UI を替えるとはこのクラスを替えることだ」。残りの千数百行は、割り込み、オラクル、インボックスの受領通知、シグナル救出といった**ターミナル固有**の付随物で、Web や HTTP に替えるならそもそも持ち込む必要がない。

だから「約 200 行を丸ごと差し替えられる」という言い方は成立する —— ただしそれが `Render` を指す場合であって、`cli.py` を指す場合ではない。

自分でターミナル UI を書くとき、要点は標準入力を読むスレッドだ:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """標準入力をずっと読む:未応答の質問があれば答え、なければインボックスへ。停止フラグを返す。"""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # ポーリングすることで停止フラグに反応できる
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # スレッド跨ぎで安全
            else:
                ch.send(raw)                    # インボックスへ。飛行中の仕事は止めない

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

3 点とも踏んで得たものだ:

- **daemon スレッドを使い、`asyncio.to_thread(input, ...)` は使わない。** `input()` はブロック中にキャンセルできず、`asyncio.run` は終了前にデフォルトエグゼキュータのスレッドを join する——結果、仕事が終わっているのにもう一度 Enter を押さないと終了できない。
- **`select` でポーリングし、ループ内で直接 `input()` しない。** 同じくキャンセル不能で、`input()` でブロックしたスレッドは `stop.set()` しても二度と起きない。
- **ずっと読む。質問があるときだけ読むのではない。** 質問があるときだけ読むと、作業中の数時間に打った文字がターミナルのバッファに残り、次の質問のときに答えとして食われる——人が問題を見る前に、問題が「回答」されてしまう。

### Web:キュー + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # 同期、イベントループのスレッド上、ブロック不可
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # フロントの障害で 3 時間の仕事を道連れにしない
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # リクエスト処理スレッド —— 別スレッド、これが常態
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` は生の SDK オブジェクト(`ask` イベントでは `Ask`)で、**JSON シリアライズできないし、フロントへ渡してもいけない** —— `raw` を使った時点でフロントエンドを SDK の型に縛り直すことになり、この層を作った意味が無くなる。`kind` / `text` / `tool` / `payload` の 4 フィールドで足りる。

### HTTP:シーケンス番号 + ポーリング {#http序号--轮询}

常時接続が無いときは、イベントに番号を振ってクライアントに取りに来させる:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # 直近だけ保持。メモリが実行時間に比例して増えない


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # 今、誰かの回答を待っているもの
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = この質問はもう待っていない
```

境界を 2 つ認識しておく。`maxlen` が埋まると最も古いものが落ちるので、かなり古い `after` を持ってきたクライアントは全部を取得できない。ポーリング間隔はこの長さに見合わせること。もう一つ、**`timeout_s` には必ず有限値を与える** —— 誰もポーリングしていないとき、質問は自分では終わらない。`timeout_s=None` は実行全体を永久に吊るす。デフォルトの `1800.0` 秒が妥当だ。

### 全自動・無人:人がいない {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # イベントは全部捨てる
```

コマンドラインでの等価な書き方は `flower "帮我做一个 X" --timeout 0`。

`timeout_s=0`(負数も同じ)は全自動モードだ。質問は**待機キューに入らず、`asked` イベントも出さず**、即座に `state="timeout"` で決着し、ツールは次の固定文言を返す——

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

——こうして実行はそのまま進む。質疑応答は `HumanChannel(log_path=...)` に追記され続ける(`starter_flow` のデフォルトは `<ワークベンチ>/notes/问答记录.md`)ので、あとから何を尋ね、どんな仮定を置いたかを見られる。

そもそも口を開かせたくなければ `max_asks=0`。質問は即座に拒否され(`state="over_budget"`)、これもブロックしない。
これは**「ツールを外す」ことではない**——`allowed_tools` は排他的ではなく、[コーディネーター](../reference/glossary.md#协调者)に `channel` を掛けた時点で `mcp__human__ask` と `mcp__human__inbox` の 2 つが一緒に渡される。列挙してもしなくても呼べる。質問を止められるのは回数上限とタイムアウトだけだ。

!!! warning "無人運転で質問を永久に待たせないこと"
    `timeout_s=None` は「永久に待つ」だ。誰も見ていないとき、質問 1 回で 10 時間の実行がその場で止まる。
    しかもエラーにならず、タイムアウトもせず、ログ上も違いが見えない。無人運転で正しい値は 2 つだけ:
    `0`(即座に空振り)か、有限の秒数か。

## 実際に何をしているか {#它实际做了什么}

### `Event` の形 {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 種類、下表を参照
    text: str = ""
    tool: str = ""                      # tool_call のときだけ値が入る
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # 生の SDK オブジェクト / Ask。触れば SDK に縛り直される
```

`str(ev)`:`tool_call` は `[ツール名] 要約`、それ以外は `text`。`text` が空なら `<kind>`。

### 15 個の `EventKind` {#15-个-eventkind}

| `kind` | 誰が出すか | いつ出るか | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | モデルの本文 | 本文 | `subagent`、`parent_tool_use_id?`、`context?` |
| `thinking` | `normalize()` | 思考ブロック | 思考内容 | 同上 |
| `prompt` | `normalize()` | **入力**:あなたの prompt、subagent へ渡すタスクブリーフ | 入力テキスト | 同上 |
| `tool_call` | `normalize()` | モデルがツール呼び出しを開始 | 要約(`file_path` / `command` / `pattern`、200 文字で切る) | `id`、`input` + 同上;`tool` はツール名 |
| `tool_result` | `normalize()` | ツールが返す | 先頭 500 文字(内容が文字列でなければ空) | `tool_use_id`、`is_error` + 同上 |
| `result` | `normalize()` | 1 回の SDK クエリの終了 | subtype | `session_id`、`cost_usd`、`num_turns`、`is_error` |
| `error` | `normalize()` | 切断時の合成メッセージ | エラーテキスト | `synthetic: True` |
| `reset` | `normalize()` | compact 境界またはセッションリセット | `压缩(trigger) 167000 → 42000 tokens`;セッションリセット時は `conversation reset` | `trigger`、`pre_tokens`、`post_tokens`、`micro`、`subtype`(セッションリセット時は空) |
| `system` | `normalize()` | それ以外の SDK システムメッセージ | subtype | `data` をそのまま透過 |
| `task` | `normalize()` | タスク進捗メッセージ | **空** | `kind` = SDK のメッセージクラス名 |
| `unknown` | `normalize()` | 認識できなかったメッセージ型 | クラス名 | — |

!!! note "`task` の本文は空。そのまま出力しないこと"
    `TaskProgressMessage` のようなものは SDK の内部メッセージ型だ。以前 `normalize()` はクラス名を本文として出していたが、
    画面に出ると純粋なノイズで、しかも agent の本文に混ざるとエラーのように見える(実測でそうだった)。今はこれを
    **本文なし**のイベントに分類し、クラス名は `payload["kind"]` に入れている —— 表示するかどうかはインタラクション層が決める
    (`events.py`)。
| `ask` | `HumanChannel` | 人の回答が要る、ある質問が決着した、または人が自発的に一言言った | 質問 / 人の発言 | 2 つの正体、下を参照 |
| `retry` | `Runtime` | リトライ中 / ネットワーク待ちで吊るされている | 一言の説明 | `step`、`attempt` |
| `step` | `Workflow.run` | ステップ境界 | ステップ名 | `index`、`total`、`resumed`、`woke` |
| `handoff` | `Runtime` | ハンドオフ:接近中 / 書いている最中 / 完了 | 水位を含む一言の説明 | `phase`、`step`、`context`、`window` + 下を参照 |

**4 つの kind は `normalize()` からは生まれない**:`ask` は `HumanChannel` から、`retry` と `handoff` は `Runtime` から、`step` は `Workflow.run` から来る。同じ `EventKind` に入れているのは意図的だ——
**UI は一種類の `Event` だけを知ればよく、「人の回答が要る」や「ステップ境界」のために別経路を用意しなくていい。**

UI を書くときは `else` 分岐を残しておくこと。`EventKind` には今後もメンバーが増える。古い UI がそれで壊れてはいけない。

### `handoff` の 3 つの phase {#handoff-的三个-phase}

| `phase` | いつ出るか | `payload` の追加分 |
|---|---|---|
| `near` | 水位が `warn_at` を越えた。**世代ごとに一度だけ**、画面を埋めない | `at`(ハンドオフの閾値) |
| `writing` | [ハンドオフ文書](../reference/glossary.md#交接书)を書き始めた。書くのに十数秒かかるので、これが無いと画面は固まったように見える | — |
| `done` | ハンドオフを書き終え、新しいセッションに切り替えた | `degraded`(縮退版かどうか)、`path`(どこに書いたか。ワークベンチが無ければ空文字列)、`sections` |

仕組み自体は[ハンドオフ](handoff.md)を参照。

### `ask` の 2 つの正体 {#ask-的两种身份}

`Event("ask")` は「質問」と「人が自発的に言ったこと」を同時に担う。**UI はまず `payload["kind"]` を見なければならない**:

| 正体 | 見分け方 | `payload` |
|---|---|---|
| 1 回の質問 | `kind` キーが無い | `id`、`options`、`state`、`answer`、`remaining`、`asked_at`;`raw` はその `Ask` |
| 人が自発的に言ったこと | `payload["kind"] == "mail"` | `kind`、`state`(`queued` 入った / `delivered` 取り出された)、`id`、`amended`(どのファイルに追記されたか。未設定なら空文字列)。**`options` と `remaining` は無い** |

1 回の質問は**2 回以上**イベントを出す。質問時に一度(`state="asked"`)、決着時にもう一度(`answered` / `timeout` / `declined` / `over_budget` / `invalid`)。UI は `payload["id"]` で同じ 1 件を更新すればよい。

### 人に尋ねる:`Ask` と `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1"、"q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # 上の 5 つの決着を参照
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # 何秒待ったか、小数第 1 位
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` はプロセス内 MCP server と、UI 用のメソッド群だ。モデル側からは 2 つのツールしか見えない:`mcp__human__ask`(質問。吊るして待つ)と `mcp__human__inbox`(インボックスの確認。**ブロックしない**。空ならすぐ説明を返す)。完全なコンストラクタ:

```python
HumanChannel(
    *,                                  # すべて keyword-only
    on_event=None,                      # プッシュ式の出口。Workflow は None のときだけ自動でつなぐ
    max_asks=None,                      # None = 無制限;0 = 質問禁止。超過は即拒否、ブロックしない
    timeout_s=1800.0,                   # None = 永久に待つ;<= 0 = 即座に空振り
    log_path=None,                      # 質疑応答をこのファイルに追記。コンテキストを消費しない
    amend_path=None,                    # 実行途中の人の発言をこのファイルに追記。通常はブリーフ
    over_budget_text=OVER_BUDGET,       # 3 つの固定応答。自前のものに差し替え可
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` は最も見落としやすく、しかも「人が途中で変えた要求がステップ境界を越えて生き残るか」を決める。各ステップは新しい[セッション](../reference/glossary.md#会话)で、読み取り専用の凍結物を読む。実行途中の発言はそのときの agent のコンテキストにしか入らず、次のステップ(たとえば[判定](../reference/glossary.md#判定))は完全に新しいセッションで `需求.md` と `目标.md` を読む。**あなたが言ったことは見えない**。結果として古い境界のまま判定し、直したものを逸脱と判定する。`amend_path` は各メッセージを[ブリーフ](../reference/glossary.md#需求确认书)に**追記**する——上書きではなく追記だ。元の要求は履歴であり、何が変わったか見えるほうが見えないよりよい。`starter_flow` のデフォルトは `<ワークベンチ>/notes/需求.md` だ。

実測($0.6767)では、これは予想以上に効いた。人が「ついでに総バイト数も報告して」と言い、コーディネーターがインボックスで見たあとこう報告した——「hand はすでに `.flower/notes/需求.md` の実行中補足から読み取って計算済みなので、もう一度振り直す必要はない」。
**subagent はファイルから読んだのであって、誰かの伝聞ではない。**

公開メンバー:

| メンバー | シグネチャ | 意味 |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | そのまま `AgentSpec.mcp_servers` に渡す。キー名は server 名と一致していなければならないので、まとめて出す |
| `ask` | `async (question, options=None) -> Ask` | 吊るして人を待つ。**`CancelledError` 以外の例外は決して投げない**——誰も答えないこともまた一つの答えで、`ask.state` で区別する |
| `pending` | `() -> list[Ask]` | 現在回答待ちの質問 |
| `next_ask` | `async (timeout=None) -> Ask \| None` | プル式 UI 用。タイムアウトで `None`、キャンセルされたら送出 |
| `answer` | `(ask_id, text) -> bool` | 回答する。`False` = この質問はもう待っていない(タイムアウト / 回答済み) |
| `decline` | `(ask_id, reason="") -> bool` | スキップし、モデル自身に判断させて仮定を「未知与假设」に書かせる |
| `send` | `(text) -> Mail \| None` | 人が自発的に一言、インボックスへ。agent を止めない。内部で自動的に `amend()` を呼ぶ |
| `amend` | `(text, *, label="运行中补充") -> bool` | `amend_path` へ追記。実際に書いたかを返す(パス未設定 / 空テキスト / `OSError` はすべて `False`) |
| `pending_mail` | `() -> list[Mail]` | まだ取り出されていない発言 |
| `remaining` | `-> int` | あと何回質問できるか。`max_asks=None` のときは **`-1`** を返す、0 ではない |
| `transcript` | `() -> str` | 質疑応答記録の markdown |
| `asks` / `mail` / `ui_errors` | `list` | 全質問 / 全ての人の発言 / UI コールバックが投げた例外 |

`answer`、`decline`、`send` は**任意のスレッドから呼べる**。Web バックエンドのリクエスト処理スレッドも、TUI の入力スレッドも別スレッドにある——これは常態であって例外ケースではない。内部では `loop.call_soon_threadsafe` を通す。`asyncio.Future.set_result` はスレッドセーフではないからだ。

プッシュとプル、2 つの取り方は**どちらか一方を選ぶ**:

| | 取り方 | 向いている先 |
|---|---|---|
| **プッシュ** | `HumanChannel(on_event=…)` で、`kind == "ask"` かつ `payload["state"] == "asked"` を受ける | イベント駆動の UI(Web プッシュ、TUI の再描画) |
| **プル** | `await channel.next_ask()` | 独立した入力タスク |

3 つの「0 / None」は意味がそれぞれ違う。取り違えると無人運転でハングするか、一言も尋ねなくなる:

| 書き方 | 意味 |
|---|---|
| `max_asks=None` | 回数無制限(デフォルト) |
| `max_asks=0` | 質問禁止、即拒否 |
| `timeout_s=None` | 永久に待つ |
| `timeout_s<=0` | 待たない、質問は即座に空振り |
| `remaining` が `-1` を返す | `max_asks=None` のときの値。0 ではない |

### 割り込み:どのスレッドからでも止められる {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`。空文字列なら止めるだけで何も言わない。性質は 3 つ:

- **同じセッションを続けて走らせる**(`resume`)。最初からやり直しではない——終わった仕事もコンテキストも残っている。切断リトライの既存経路をそのまま再利用し、「失敗理由」を「人が割り込んだ」に、`resume_prompt` を人の発言に差し替えているだけだ。
- **`max_attempts` を消費しない。** あれは障害のための枠であって、人のための枠ではない。
- **協調的**。メッセージ境界で切り、タスクを強制キャンセルしない。代償は次のメッセージまでの遅延(subagent が走行中なら戻るまで待つ)で、引き換えに途中で状態が引き裂かれない。

代償は正直に書く。割り込むと**飛行中の subagent が作りかけを失う**(HT001 の切断時に実測、[issue #2](https://github.com/ChenyuHeee/flower/issues/2) を参照)。ターミナル参照実装はこれをプロンプトに明記して、押す前に分かるようにしている。自分で UI を書くときも同じようにすべきだ。

割り込みたいのではなく、要求を足したいだけならインボックス(`ch.send(...)`)を使う——何も止めず、遅延は agent の次のチェックポイントまでだ。

### オラクル:実行を邪魔せずに一言尋ねる {#旁路顾问问一句而不打扰运行}

「今どこまで進んだか」を知りたいとき、割り込む必要はないし、コーディネーターに聞くべきでもない。その質疑応答は**メインスレッドのコンテキストを永久に占有する**(そこに入れるのは意思決定であって、質疑応答記録ではない)し、手元の仕事も止めさせる。10 時間の実行に対して軽く 3 回尋ねれば、その両方の代償を払うことになる。

[オラクル](../reference/glossary.md#旁路顾问)は読み取り専用のバイパスだ。ツールは `Read` / `Glob` / `Grep` だけ、ワークベンチは開いており、デフォルトで栓がある:`max_turns=12`、`max_budget_usd=0.5`。ターミナルでは `?` で始まる行が発火させ、答えるための材料は 2 つ:直近のイベントウィンドウ(固定 60 件)と、ワークベンチ内のブリーフ、目標、ノート、成果物。独立した `Runtime`(`<run_dir>/aside`)を使うので、コストとセッションの[リネージ](../reference/glossary.md#血缘)は**メインの manifest に混ざらない**——あのマニフェストが記録するのは「この実行がどんなステップを踏んだか」であり、ついでの一言はステップではない。

実測で 2 回の質問が合計 $0.5190、メイン実行の manifest は 1 バイトも増えなかった。

### 2 つの厳格なルール {#两条硬规矩}

!!! warning "on_event はブロックしてはならず、例外を外へ出してもならない"
    **一、`on_event` は同期関数で、イベントループのスレッド上で呼ばれる。** だから
    `asyncio.Queue.put_nowait()` は安全だが `await` は不可(コルーチンではない)。**これをブロックすることは実行全体をブロックすることだ。**
    遅い処理はキューに投げ、別のタスクにやらせること。

    **二、`on_event` の中で例外を投げると実行そのものを傷つける。** 本文系のイベントは `Runtime._attempt` の `try` ブロック内で
    発火し、例外は `result.error` に記録される —— そのステップは失敗判定になる。`retry` イベントはその外側で発火するので、例外は
    そのまま `Runtime.run` の外へ抜ける。フロントエンドが 3 時間の仕事を道連れにしてはいけない。**自分で try で包むこと。**

    例外:`HumanChannel` 自身が出す `ask` イベントはすでに包んであり、例外は `channel.ui_errors` に収まって実行は中断しない。

## 使うべきでない場面 {#什么时候不该用它}

### インタラクション層でやってはいけないこと {#交互层里不该做的事}

| やってはいけないこと | なぜ | どうするか |
|---|---|---|
| `from claude_agent_sdk import ...` | インタラクション層が SDK の型に依存した瞬間、SDK が上がるたびにフロントも直すことになり、この層が無意味になる | `Event` の `kind` / `text` / `tool` / `payload` だけを使う |
| `ev.raw` を読む | 同上。しかも JSON シリアライズできない | 足りない詳細は `normalize()` の `payload` に足す。境界を迂回しない |
| `on_event` の中で `await`、ネットワークリクエスト、遅いディスク書き込み | 同期関数でイベントループのスレッド上で呼ばれる。ブロックは実行全体のブロック | `put_nowait()` でキューに投げ、別タスクで消費 |
| `on_event` から例外を外へ出す | 本文イベントの例外は `result.error` になり、そのステップが失敗判定になる | コールバック本体を丸ごと `try` で包む |
| `disallowed_tools` で質問を止める | これは**セッション単位**で、subagent の同名ツールまで一緒に禁止する(実測のエラー原文:`"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` か `timeout_s=0` |
| `allowed_tools` から `mcp__human__ask` を外して質問禁止のつもりになる | `allowed_tools` は排他的ではなく、承認免除リストであってホワイトリストではない。`channel` を掛ければ 2 つのツールが一緒に渡される | 同上 |
| 自分でパスを組み立てて `需求.md` / `目标.md` を探す | ワークベンチの場所は 2 通りあり、間違えてもエラーにならず、静かに効かなくなるだけ | `wake_state()` か `wf.workbench` |
| `Event` ストリームから進捗や結果を組み立てる | 本文はハンドオフやリトライで何段にも分断される | `on_step(step, result)` で完全な `StepResult` を取る |
| 無人運転で `timeout_s=None` を使う | 誰も答えず、実行は永久に吊るされる。エラーにもならずタイムアウトもしない | `0`、または有限の秒数 |

### そもそも差し替える必要がない場面 {#什么时候根本不用换}

- **色を変えたい、一行増やしたい減らしたいだけ** —— レンダリング関数を直せばよい。ターミナル参照実装にある割り込み、オラクル、インボックスの受領通知、SIGHUP / SIGTERM の救出、終了前のバイパス後始末待ちを書き直す代償は小さくない。
- **1 ステップだけ走らせたい、対話は要らない** —— `flower once` を使う。対話駆動の経路を通らないので、そもそも Ctrl+C 割り込み、標準入力の応答スレッド、オラクル、シグナル救出は無い。
- **替えたいのが実は UI ではなくワークフロー** —— [ワークフローを設計する](workflow.md)を参照。インタラクション層が決めるのは誰が見て誰が答えるかだけで、何ステップ走らせるか、どう判定するか、いつ早期終了するかを決めるのは `Workflow` だ。
- **替えたいのがセッションストア、モデル、予算** —— その 3 つはこの境界の上に無い。[Python API リファレンス](../reference/api.md)を参照。
