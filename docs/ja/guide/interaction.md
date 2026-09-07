# インタラクション層を差し替える

flower のコアは UI の存在を知らない。runの中で起きるすべてのこと——モデルが話す、ツールを呼ぶ、コンテキストがそろそろ満杯になる、人に一言聞きたい——は、同じ一つのデータ構造 [`Event`](../reference/glossary.md#事件) に平坦化される。
**[インタラクション層](../reference/glossary.md#交互层)は `Event` しか知らず、SDK の型を一切 import しない。**
これが、UI を差し替えてもコアに手を入れずに済む境界だ。ターミナル、Web、HTTP サービス、完全無人運転——差し替わるのは `Event` の消費者だけで、他は一行も変えなくていい。

## 何を解決するのか

SDK のメッセージストリームは**内部型**だ:`AssistantMessage`、`ToolUseBlock`、`ToolResultBlock`、`ResultMessage`、`SystemMessage`……UI がこれらを直接消費すると、結果は二つ。SDK がアップグレードするたびにフロントエンドも追随して直す羽目になる。そしてメッセージごとに形が違うので、「これは本文かツール呼び出しか」の判定をどの UI でも書き直すことになる。

`normalize(message)` は SDK メッセージ 1 件を 0〜N 個の `Event` に変換する([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py))。
代価は一度の変換、得られるのはインタラクション層と SDK のあいだに型依存がないことだ。

この境界は、ついでにそれほど自明でない四つのことも解決している。四つとも `normalize()` の中にある:

1. **[subagent](../reference/glossary.md#subagent) の発言に印が付く**(`payload["subagent"]`)。
   そうしないと、割り当てた[タスク書](../reference/glossary.md#任务书)や subagent の中間発言が[メインスレッド](../reference/glossary.md#主线程)の本文に混入し、さらに[ワークフロー](../reference/glossary.md#流程)をたどって次のステップの prompt を汚染する。
2. **切断時の合成エラーメッセージが `kind="error"` に振り分けられる**。切断時、SDK 側は `API Error: …` を assistant メッセージとして transcript に書き込む。それはモデルの発言そっくりに見える(`model` は `"<synthetic>"`)。
   ここで止めなければ、それは `StepResult.text` に入り、次の[ステップ](../reference/glossary.md#步骤)へ渡される。
3. **compact 境界が明示的に報告される**(`kind="reset"`)。境界の後にモデルが「覚えている」のは要約だけで、prompt キャッシュもここで切れる——[long-horizon](../reference/glossary.md#长程) な run はこれを見えるようにしておかなければならない。
4. **コンテキスト水位がメッセージごとに出てくる**(`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`)。これは[ハンドオフ](../reference/glossary.md#换代)判定基準の唯一の情報源だ。

## 使い方(最小コード)

インタラクション層がつなぐものは三つ:**イベント出口**(どこへ描画するか)、**質問チャネル**(誰が答えるか)、**割り込み**(どう止めるか)。
以下は全部つないである。そのまま動く:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event を自分の UI に描画する —— 差し替えが必要なのはここだけ。"""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 換代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ リトライ: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人からの申し出:{ev.text}")
    # kind == "ask" かつ mail でないものは、下の answerer が処理する(プル式)


async def answerer(ch: HumanChannel) -> None:
    """プル式で質問を取る。Web / HTTP に替えるとき、この coroutine がもう一つの変更点。"""
    while True:
        ask = await ch.next_ask()           # timeout を渡さなければずっと待つ
        if ask is None:
            continue
        print(f"\n?? {ask.question} 選択肢={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # または ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime は workflow が自分で作ったワークベンチを使う —— 別に組み立てないこと
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

見落としやすい後始末が二つ。`rt.close()` は必ず `finally` に置く。`ctx["_failed_at"]` に値があれば途中で止まったということ(`on_fail="stop"`)なので、成功と見なさないこと。

!!! note "ワークベンチは一つだけ。別に組み立てないこと"
    `Runtime(workbench=True)` が作る[ワークベンチ](../reference/glossary.md#工作台)は `<run_dir>/workbench` にあり、`Workbench(ws)` はデフォルトで `<ws>/.flower` にある —— この二つは同じディレクトリではない。ドライバ側で自前でパスを組み立てて `需求.md` を探すと、「確認書は A ディレクトリに書かれ、注入されるインデックスは B ディレクトリを走査する」という状態になり、しかもエラーは出ない。
    workflow が作ったものを `Runtime` に渡す(上のやり方)か、読み取り専用の探索 `wake_state()` で場所を尋ねるかのどちらかにすること。

### 三つのイベント出口

```python
await rt.run(spec, "…", on_event=sink)                  # 1. 単一の agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. ワークフロー全体、各ステップに引き渡す
wf = Workflow(steps=[...], channel=ch)                  # 3. 質問チャネルを同じ出口につなぐ
```

三つめの接続は `Workflow.run` の中にある:**`on_event` が `None` でなく、かつ `channel.on_event` がまだ `None` のときだけ自動でつなぐ**。自分でつないであれば上書きされない:

```python
ch = HumanChannel(on_event=my_own_sink)     # 自分でつなぐ。Workflow は触らない
```

`on_step(step, result)` はもう一つのコールバックで、各ステップが終わるたび(**失敗も含む**)に一度呼ばれ、完全な `StepResult` を受け取る。プログレスバー、ディスク書き込み、アラートはここに掛けること。これを `Event` ストリームから組み立てようとしないこと——本文はハンドオフとリトライで何段にも分断される。

### ターミナル:デフォルトのやつ

コードを書かなくても一つある。`flower "帮我做一个 X"` が通るのは [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py) で、これはインタラクション層の**参考実装であって、フレームワークの一部ではない**。丸ごと差し替えてよい。スイッチは [CLI リファレンス](../reference/cli.md) を参照。
規模は正直に書く。`cli.py` 全体は 1264 行、57KB —— だが**差し替えるのは全体ではない**。
本当の差し替え地点はその中の `class Render`(`cli.py:382-578`、197 行)で、その docstring にこう書いてある:「Event → ターミナル。UI を差し替えるとはこのクラス一つを差し替えることだ」。残りの千数百行は、割り込み、oracle、受信箱の受領通知、シグナル救済といった**ターミナル固有**の付随物であり、Web や HTTP に替えるならそもそもそのまま持ち込む必要はない。

だから「約 200 行を丸ごと差し替え可能」という言い方は成り立つ —— それが `Render` を指し、`cli.py` を指していないという前提であれば。

自分でターミナル UI を書くときの要点は、標準入力を読むスレッドだ:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """標準入力をずっと読む:未回答の質問があればそれが答え、なければ受信箱へ。停止フラグを返す。"""
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
                ch.send(raw)                    # 受信箱へ。飛行中の作業は中断しない

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

三つとも踏んで学んだことだ:

- **daemon スレッドを使い、`asyncio.to_thread(input, ...)` は使わない。** `input()` はブロック中にキャンセルできず、`asyncio.run` は終了前にデフォルトエグゼキュータのスレッドを join する——結果として、作業が終わっているのにもう一度 Enter を押さないと終了できない。
- **`select` でポーリングし、ループの中で直接 `input()` を呼ばない。** 同じくキャンセルできない:`input()` でブロックしたスレッドは、`stop.set()` しても二度と起きない。
- **常に読む。質問があるときだけ読むのではない。** 質問があるときだけ読む方式だと、作業している数時間のあいだに打った文字がターミナルバッファに残り、次の質問のときに答えとして食われる——人が質問を見る前に、質問が「回答」されてしまう。

### Web:キュー + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # 同期、イベントループのスレッド上、ブロック禁止
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # フロントのエラーで三時間の作業を道連れにしない
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # リクエスト処理スレッド —— 別スレッド、これが常態
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` は生の SDK オブジェクト(`ask` イベントでは `Ask`)で、**JSON シリアライズできないし、フロントに渡してもいけない** —— `raw` を使った時点でフロントを SDK の型に縛り直したことになり、この層の意味がなくなる。`kind` / `text` / `tool` / `payload` の四つで足りる。

### HTTP:連番 + ポーリング

常時接続がない場合は、イベントに番号を振ってクライアントに取りに来させる:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # 直近だけ保持。メモリが run の長さに比例して増えない


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # 今誰かの回答を待っているもの
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = この質問はもう待っていない
```

認識すべき境界が二つ。`maxlen` が満杯になると最も古いものが落ちるので、かなり古い `after` を持ってきたクライアントは全部を取得できない。ポーリング間隔はこの長さに見合ったものにすること。もう一つ、**`timeout_s` には必ず有限値を与えること** —— 誰もポーリングしていないとき、質問は自然に終わらない。`timeout_s=None` は run 全体を永遠に吊るす。デフォルトの `1800.0` 秒が妥当だ。

### 完全無人運転:人がいない

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # イベントは全部捨てる
```

コマンドラインでの等価な書き方は `flower "帮我做一个 X" --timeout 0`。

`timeout_s=0`(負数も同様)は完全自動モードだ:質問は**待ち行列に入らず、`asked` イベントも出さず**、即座に `state="timeout"` として決着し、ツールは次の固定文言を返す——

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

——こうして run は止まらずに進む。問答は依然として `HumanChannel(log_path=...)` に追記される(`starter_flow` のデフォルト接続先は `<ワークベンチ>/notes/问答记录.md`)ので、事後に何を尋ね、自分でどう仮定したかを見られる。

そもそも口を開かせたくなければ `max_asks=0` を使う:質問は即座に拒否され(`state="over_budget"`)、同じくブロックしない。
これは**「ツールを外す」ことではない**点に注意——`allowed_tools` は排他的ではなく、[コーディネーター](../reference/glossary.md#协调者)に `channel` を付けた時点で `mcp__human__ask` と `mcp__human__inbox` の二つが一緒に渡される。リストに挙げようが挙げまいが呼べる。質問を止められるのは上限回数とタイムアウトだけだ。

!!! warning "無人運転時に質問を永遠に待たせないこと"
    `timeout_s=None` は「永遠に待つ」だ。誰も見ていないとき、たった一度の質問で十時間の run がその場で止まる。しかもエラーは出ず、タイムアウトもせず、ログ上では区別がつかない。無人運転で正しい値は二つだけ:`0`(即座に空振り)か、有限の秒数か。

## 実際に何をしているのか

### `Event` の形

```python
@dataclass
class Event:
    kind: EventKind                     # 15 種類。下表を参照
    text: str = ""
    tool: str = ""                      # tool_call のときだけ値が入る
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # 生の SDK オブジェクト / Ask。触れば SDK に縛り直される
```

`str(ev)`:`tool_call` は `[ツール名] 要約`、それ以外は `text`。`text` が空なら `<kind>`。

### 15 個の `EventKind`

| `kind` | 誰が出すか | いつ出るか | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | モデルの本文 | 本文 | `subagent`、`parent_tool_use_id?`、`context?` |
| `thinking` | `normalize()` | thinking ブロック | 思考内容 | 同上 |
| `prompt` | `normalize()` | **入力**:あなたの prompt、subagent へ渡すタスク書 | 入力テキスト | 同上 |
| `tool_call` | `normalize()` | モデルがツール呼び出しを開始 | 要約(`file_path` / `command` / `pattern`、200 文字で切る) | `id`、`input` + 同上;`tool` はツール名 |
| `tool_result` | `normalize()` | ツールが返る | 先頭 500 文字(内容が文字列でない場合は空) | `tool_use_id`、`is_error` + 同上 |
| `result` | `normalize()` | 一回の SDK クエリが終了 | subtype | `session_id`、`cost_usd`、`num_turns`、`is_error` |
| `error` | `normalize()` | 切断時の合成メッセージ | エラーテキスト | `synthetic: True` |
| `reset` | `normalize()` | compact 境界またはセッションリセット | `压缩(trigger) 167000 → 42000 tokens`;セッションリセット時は `conversation reset` | `trigger`、`pre_tokens`、`post_tokens`、`micro`、`subtype`(セッションリセット時は空) |
| `system` | `normalize()` | その他の SDK システムメッセージ | subtype | `data` をそのまま透過 |
| `task` | `normalize()` | タスク進捗メッセージ | メッセージのクラス名 | — |
| `unknown` | `normalize()` | 認識できないメッセージ型 | クラス名 | — |
| `ask` | `HumanChannel` | 人の回答が必要、ある質問に決着がついた、または人が自発的に一言言った | 質問 / 人の発言 | 二つの身元。下記参照 |
| `retry` | `Runtime` | リトライ中 / ネットワーク待ちで吊るされている | 説明一行 | `step`、`attempt` |
| `step` | `Workflow.run` | ステップ境界 | ステップ名 | `index`、`total`、`resumed`、`woke` |
| `handoff` | `Runtime` | ハンドオフ:接近 / 書き込み中 / 完了 | 水位付きの説明一行 | `phase`、`step`、`context`、`window` + 下記参照 |

**四つの kind は `normalize()` から生まれない**:`ask` は `HumanChannel` から、`retry` と `handoff` は `Runtime` から、`step` は `Workflow.run` から来る。同じ `EventKind` に入れてあるのは意図的だ——
**UI は一組の `Event` だけを知っていればよく、「人の回答が要る」や「ステップ境界」のために別経路を作らなくていい。**

UI を書くときは `else` 分岐を残しておくこと。`EventKind` にはさらに新しいメンバーが追加される。古い UI がそれで壊れてはいけない。

### `handoff` の三つの phase

| `phase` | いつ出るか | `payload` の追加分 |
|---|---|---|
| `near` | 水位が `warn_at` を超えた。**一世代につき一度だけ**出し、画面を埋めない | `at`(ハンドオフ閾値) |
| `writing` | [引き継ぎ書](../reference/glossary.md#交接书)を書き始めた。書くのに十数秒かかるので、これを出さないと画面が固まったように見える | — |
| `done` | 引き継ぎを書き終え、新しいセッションに切り替えた | `degraded`(縮退版かどうか)、`path`(どこに書いたか。ワークベンチがない場合は空文字列)、`sections` |

仕組み自体は[ハンドオフ](handoff.md)を参照。

### `ask` の二つの身元

`Event("ask")` は「質問」と「人が自発的に言ったこと」の両方を運ぶ。**UI はまず `payload["kind"]` を見なければならない**:

| 身元 | 見分け方 | `payload` |
|---|---|---|
| 一件の質問 | `kind` キーがない | `id`、`options`、`state`、`answer`、`remaining`、`asked_at`;`raw` はその `Ask` |
| 人が自発的に言ったこと | `payload["kind"] == "mail"` | `kind`、`state`(`queued` 投入 / `delivered` 取り出し済み)、`id`、`amended`(どのファイルに追記したか。未設定なら空文字列)。**`options` と `remaining` はない** |

一件の質問は**二回以上**イベントを出す:質問時に一度(`state="asked"`)、決着時にもう一度(`answered` / `timeout` / `declined` / `over_budget` / `invalid`)。UI は `payload["id"]` で同じ一件を更新すればよい。

### 人に聞く:`Ask` と `HumanChannel`

```python
@dataclass
class Ask:
    id: str                                             # "q1"、"q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # 上記五つの決着を参照
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # 何秒待ったか、小数一桁
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` はプロセス内 MCP server 一つと、UI 向けのメソッド群だ。モデル側から見えるツールは二つだけ:`mcp__human__ask`(質問する。吊るされて待つ)と `mcp__human__inbox`(受信箱を見る。**ブロックしない**。空なら即座に説明を一言返す)。完全なコンストラクタ:

```python
HumanChannel(
    *,                                  # すべて keyword-only
    on_event=None,                      # プッシュ式の出口。Workflow は None のときだけ自動接続する
    max_asks=None,                      # None = 無制限;0 = 質問禁止。超過分は即拒否、ブロックしない
    timeout_s=1800.0,                   # None = 永遠に待つ;<= 0 = 即座に空振り
    log_path=None,                      # 問答をこのファイルに追記する。コンテキストは消費しない
    amend_path=None,                    # run の途中で人が言ったことをこのファイルに追記。通常は需求确认书
    over_budget_text=OVER_BUDGET,       # 固定の返答三種。自前のものに差し替え可
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` は最も見落としやすく、しかも「人が途中で変えた要求がステップ境界を生き延びるか」を決めている。
各ステップは新しい[セッション](../reference/glossary.md#会话)で、読み取り専用の凍結物だ:run の途中で言ったことはその時点の agent のコンテキストにしか入らない。次のステップ(たとえば[判定](../reference/glossary.md#判定))は完全に新しいセッションで、読むのは `需求.md` と `目标.md` であり、**あなたが言ったその一言は見えない**。だから古い境界のまま判定し、直したものを逸脱と判定してしまう。
`amend_path` は各メッセージを[需求確認書](../reference/glossary.md#需求确认书)に**追記**する——上書きではなく追記だ。元の要求は履歴であり、何が変わったか見えるほうが見えないより良い。`starter_flow` のデフォルト接続先は `<ワークベンチ>/notes/需求.md`。

実測($0.6767)では、これは想定以上に効いた:人が「ついでに総バイト数も報告して」と言い、コーディネーターが受信箱でそれを見て、こう報告した——「hand は `.flower/notes/需求.md` の run 中の追記からすでに読んで計算済みなので、もう一度割り当てる必要はない」。
**subagent はファイルから読んだのであって、誰かの伝言に頼っていない。**

公開メンバー:

| メンバー | シグネチャ | 意味 |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | そのまま `AgentSpec.mcp_servers` に渡す。キー名は server 名と一致していなければならないので、これがまとめて出す |
| `ask` | `async (question, options=None) -> Ask` | 吊るされて人を待つ。**`CancelledError` 以外の例外は決して投げない**——誰も応答しないこともまた一つの答えであり、`ask.state` で区別する |
| `pending` | `() -> list[Ask]` | 現在回答を待っている質問 |
| `next_ask` | `async (timeout=None) -> Ask \| None` | プル式 UI 用。タイムアウトで `None` を返し、キャンセルされたら投げる |
| `answer` | `(ask_id, text) -> bool` | 回答する。`False` = この質問はもう待っていない(タイムアウト / 回答済み) |
| `decline` | `(ask_id, reason="") -> bool` | スキップし、モデル自身に判断させて仮定を「未知と仮定」の節に書かせる |
| `send` | `(text) -> Mail \| None` | 人が自発的に一言言い、受信箱に入る。agent を中断しない;内部で自動的に `amend()` を呼ぶ |
| `amend` | `(text, *, label="运行中补充") -> bool` | `amend_path` に追記する。実際に書いたかどうかを返す(パス未設定 / テキストが空 / `OSError` はいずれも `False`) |
| `pending_mail` | `() -> list[Mail]` | まだ取り出されていない発言 |
| `remaining` | `-> int` | あと何回聞けるか。`max_asks=None` のときは **`-1`** を返す。0 ではない |
| `transcript` | `() -> str` | 問答記録の markdown |
| `asks` / `mail` / `ui_errors` | `list` | 全質問 / 人の全発言 / UI コールバックが投げた例外 |

`answer`、`decline`、`send` は**任意のスレッドから呼べる**。Web バックエンドのリクエスト処理スレッドも、TUI の入力スレッドも別スレッドにいる——これは常態であって、エッジケースではない。内部は `loop.call_soon_threadsafe` を通す。`asyncio.Future.set_result` はスレッドセーフではないからだ。

プッシュとプルの二つの取り方は**どちらか一つを選ぶ**:

| | 取り方 | 向いている先 |
|---|---|---|
| **プッシュ** | `HumanChannel(on_event=…)` で、`kind == "ask"` かつ `payload["state"] == "asked"` を受け取る | イベント駆動の UI(Web プッシュ、TUI 再描画) |
| **プル** | `await channel.next_ask()` | 独立した入力タスク |

三つの「0 / None」は意味がそれぞれ違う。取り違えると、無人運転時にハングするか、一言も聞かなくなる:

| 書き方 | 意味 |
|---|---|
| `max_asks=None` | 回数無制限(デフォルト) |
| `max_asks=0` | 質問禁止、即拒否 |
| `timeout_s=None` | 永遠に待つ |
| `timeout_s<=0` | 待たない。質問は即座に空振り |
| `remaining` が `-1` を返す | `max_asks=None` のときの値。0 ではない |

### 割り込み:どのスレッドからでも止められる

`rt.interrupt("别改 Makefile,那两行直接改")`、空文字列なら割り込むだけで何も言わない。性質は三つ:

- **同じセッションを継続する**(`resume`)。最初からではない——すでに終わった作業もコンテキストも残っている。再利用しているのは切断リトライの既存の経路で、「失敗理由」を「人が割り込んだ」に、`resume_prompt` を人の発言に差し替えているだけだ。
- **`max_attempts` を消費しない**。あれは障害のための枠であって、人のための枠ではない。
- **協調的**:メッセージ境界で切り、タスクを強制キャンセルしない。代価は次のメッセージまでの遅延(subagent が走っていればそれが戻るまで待つ)、得られるのは途中で状態を裂かないことだ。

代価は正直に書く。割り込みは**飛行中の subagent の作りかけを捨てさせる**(HT001 の切断の回に実測済み。[issue #2](https://github.com/ChenyuHeee/flower/issues/2) 参照)。ターミナル参考実装はこれをプロンプトに明記し、押す前に人が知れるようにしてある。自分で UI を書くときもそうすべきだ。

割り込みたいのではなく、単に要求を足したいだけなら受信箱を使う(`ch.send(...)`)——何も中断せず、遅延は agent の次のチェックポイントまでだ。

### oracle:run を邪魔せずに一言聞く

「今どこまで進んだか」を知りたいだけなら、割り込む必要はないし、コーディネーターに聞くべきでもない:その問答は**メインスレッドのコンテキストを永久に占有する**(そこに入っているのは決断であって、問答記録ではない)し、コーディネーターは手を止めることになる。十時間の run に対して、軽い気持ちで三度尋ねればこの二つの代価を払うことになる。

[oracle](../reference/glossary.md#旁路顾问) は読み取り専用のバイパスだ。ツールは `Read` / `Glob` / `Grep` のみ、ワークベンチは開いており、デフォルトでブレーキ付き:`max_turns=12`、`max_budget_usd=0.5`。ターミナルでは `?` で始まる行が引き金になり、二つの材料から答える:直近のイベントウィンドウ(固定 60 件)と、ワークベンチ内の確認書、目標、ノート、成果物。独立した `Runtime`(`<run_dir>/aside`)を使うので、コストとセッションの[血統](../reference/glossary.md#血缘)は**メインの manifest に混ざらない**——あの一覧に記録されるのは「この run がどのステップを実行したか」であり、ついでの一言はステップではない。

実測では二問で合計 $0.5190、メイン run の manifest は 1 バイトも増えなかった。

### 二つの厳格な規則

!!! warning "on_event はブロックしてもいけないし、例外を外に出してもいけない"
    **一、`on_event` は同期関数で、イベントループのスレッド上で呼ばれる。** だから `asyncio.Queue.put_nowait()` は安全だが、`await` はできない(コルーチンではない)。**これをブロックすることは run 全体をブロックすることだ。**
    遅い処理をしたいならキューに投げ、別のタスクにやらせること。

    **二、`on_event` の中で例外を投げると run 自体を傷つける。** 本文系のイベントは `Runtime._attempt` の `try` ブロック内で出されるので、例外は `result.error` に記録され —— そのステップは失敗と判定される。`retry` イベントはその外で出されるので、例外はそのまま `Runtime.run` の外へ抜ける。フロントエンドが三時間の作業を道連れにしてはいけない。**自分で try で包むこと。**

    例外:`HumanChannel` が自分で出す `ask` イベントはすでに包んであり、例外は `channel.ui_errors` に収まって run を中断しない。

## いつ使うべきでないか

### インタラクション層でやってはいけないこと

| やってはいけないこと | なぜ | どうすべきか |
|---|---|---|
| `from claude_agent_sdk import ...` | インタラクション層が SDK の型に依存した時点で、SDK のアップグレードにフロントエンドが追随することになり、この層の意味がなくなる | `Event` の `kind` / `text` / `tool` / `payload` だけを使う |
| `ev.raw` を読む | 同上、しかも JSON シリアライズできない | 足りない詳細は `normalize()` の `payload` に足す。境界を迂回しないこと |
| `on_event` の中で `await`、ネットワークリクエスト、遅いディスク書き込み | 同期であり、イベントループのスレッドで呼ばれる。ブロックすることは run 全体をブロックすることだ | `put_nowait()` でキューに投げ、別タスクで消費する |
| `on_event` から例外を外に出す | 本文イベントの例外は `result.error` になり、そのステップが失敗と判定される | コールバックの本体を丸ごと `try` で包む |
| `disallowed_tools` で質問を止める | あれは**セッション単位**で、subagent の同名ツールもまとめて禁止する(実測のエラー原文:`"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` または `timeout_s=0` |
| `allowed_tools` から `mcp__human__ask` を外して質問禁止のつもりになる | `allowed_tools` は排他的ではなく、承認免除リストであってホワイトリストではない;`channel` を付けた時点で二つのツールが一緒に渡される | 同上 |
| 自前でパスを組み立てて `需求.md` / `目标.md` を探す | ワークベンチの場所は二通りあり、間違えてもエラーは出ず、静かに効かなくなるだけ | `wake_state()` か `wf.workbench` |
| `Event` ストリームから進捗と結果を組み立てる | 本文はハンドオフとリトライで何段にも分断される | `on_step(step, result)` で完全な `StepResult` を取る |
| 無人運転で `timeout_s=None` を使う | 誰も答えず、run は永遠に吊るされ、エラーも出ずタイムアウトもしない | `0`、または有限の秒数 |

### そもそも差し替える必要がない場合

- **色を変えたい、一行増やしたい減らしたいだけ** —— 描画関数を直せばいい。ターミナル参考実装の割り込み、oracle、受信箱の受領通知、SIGHUP / SIGTERM の救済、終了前のバイパス完了待ちを書き直す代価は小さくない。
- **一ステップだけ走らせたい、対話は不要** —— `flower once` を使う。対話ドライバの経路を通らないので、Ctrl+C 割り込み、標準入力の応答スレッド、oracle、シグナル救済は最初から存在しない。
- **差し替えたいのは実はワークフローで、UI ではない** —— [ワークフローを設計する](workflow.md)を参照。インタラクション層が決めるのは誰が見て誰が答えるかだけだ。何ステップ走るか、どう判定するか、いつ早期終了するかを決めるのは `Workflow` だ。
- **差し替えたいのはセッションストア、モデル、または予算** —— その三つはこの境界の上にない。[Python API リファレンス](../reference/api.md)を参照。
