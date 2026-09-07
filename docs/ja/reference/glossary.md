# 用語集

このページは flower ドキュメントの用語基準です。同じものは全サイトで一つの呼び方しか持たず、
中英対応はここで確定します —— 翻訳版もこの表に従います。

各項目には三つのことを記します:**この語が何を指すか**、**コード上では何なのか**、**何ではないか**。
三つ目がしばしば最も役に立ちます。多くの誤解は、ある語を別の語だと取り違えることから生まれるからです。

---

## フレームワークと実行

### long-horizon {#长程}

**long-horizon**

一問一答ではなく、一回の run が数時間から数日にわたり、複数の session をまたぎ、プロセスの再起動を
またいで続くこと。flower のすべての仕組みは、この種の run が途中で崩れないためにあります。

実測の参照:[HT001](../cases/ht001.md) は連続で 10.4 時間走りました。

### run {#运行}

**run**

一つの `Runtime` の開始から終了までの完全な過程。一回の run の内部には複数の[step](#步骤)、
複数の[session](#会话)があり得て、中断後に[continuity](#接续)することもできます。run の記録は
`runs/manifest.json` と `runs/sessions.db` に落ちます。

**ではない**:一回の API 呼び出しでもなければ、一つの session でもありません。

### session {#会话}

**session**

モデル側の一本のコンテキスト。固有の `session_id` を持ち、resume でき、fork できます。一回の
[run](#运行)は session を何本も焼き尽くすことがあります —— [handoff](#换代)のたびに新しい一本に
切り替わります。

### step {#步骤}

**step** · `Step`

[workflow](#流程)の中の一つの実行可能な単位。一つのコンテキスト辞書を受け取り、agent を一つ走らせ、
結果を辞書に書き戻します。`Step` はクラスです。[Python API](api.md#step) を参照。

### workflow {#流程}

**workflow** · `Workflow`

順に連ねた一組の[step](#步骤)、それに step 間でどう状態を渡すか、いつ早期に抜けるかを加えたもの。

!!! note "フレームワークは既製の workflow を提供しない"
    flower は仕組みだけを提供します。**workflow はあなたが書くものです**。[workflow を設計する](../guide/workflow.md)を参照。

---

## 役割

役割は flower による agent の分業です。各役割 = 注入される規則テキスト一段 + 一組のツール +
一組の hook。五つの役割はすべてファクトリ関数です。[Python API](api.md#角色工厂) を参照。

### coordinator {#协调者}

**coordinator** · `coordinator()`

[main thread](#主线程)上のあの agent。タスクを分解し、仕事を割り振り、報告を読み、意思決定をします。
**しかし自分では手を動かしません** —— `Bash` / `Write` / `Edit` を持ちません。ツールは `Agent`、
`TodoWrite`、`Read` だけ。

役割設定は「Claude Code を使える人」であって、worker ではありません。

**ではない**:より賢い agent ではありません。[worker](#执行者)とデフォルトで同じモデル水準を使い、
節約するのはコンテキストであってモデルではありません。

### worker {#执行者}

**worker** · `worker()`

実際に仕事をする [subagent](#subagent):コードを書き、テストを走らせ、資料を調べます。ツールは
`Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`。

返答形式は規則テキストによって四段に制約されます —— **結論 / 根拠 / 産出 / 未検証**、30 行を超えず、
ファイルの中身・コマンド出力・ログ・diff の原文を貼ることは禁止です。

### clarifier {#确认者}

**clarifier** · `clarify()`

手を動かす前に要件を問い明かす役割。仕事はせず、問うだけで、明確になるまで問い続け(**ラウンド数の上限なし**)、
最後に一份の[brief](#需求确认书)を出力します。[clarify](../guide/clarify.md)を参照。

### judge {#判定者}

**judge** · `judge()`

「終わったかどうか」を判定する役割。二つのうち一つをします:走り出す前に**目標を設定する**
(目標 + 判定リストを産出)か、あるいは各ラウンド終了後に**そのラウンドを判定する**([verdict](#判定)を産出)。
[goal guard](../guide/goal.md)を参照。

**要点**:judge が判定するのは**産出物**であって、ソースコードではありません。

[HT001](../cases/ht001.md) では一度ここでつまずきました:受け入れ基準には「macOS ターミナルで直接実行」
と書いてあったのに、納品された産出物を `file` にかけると `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`
だったのに、判定は通過でした。

二点をはっきりさせておかないと、この例は誤読されます:

1. **あの誤判をしたのは goal guard ではありません** —— HT001 にはまだこの仕組みがなく、誤判したのは
   coordinator が自発的に派遣した監査員でした。
2. **デフォルト設定の judge もおそらくこれを見逃します。** `judge()` はデフォルトで `can_run=False`、
   ツールは `Read/Glob/Grep` だけ —— **`file` を走らせられません**、`Makefile` を読んで確かに Darwin
   分岐があると見て、達成と判定するだけです。

本当に効いたのは [HT002](../cases/ht002.md) です:judge が `judge_can_run` を有効にし、自分で
`file` と `lsof` を走らせて現場を見て、はっきりこの落とし穴を避けました。**だから「産出物を判定する」
という言葉は、`can_run=True` があって初めて地に足がつくのです。**

### oracle {#旁路顾问}

**oracle** · `oracle()`

読み取り専用の側路(バイパス)を一本。run がまだ走っている間に「今どこまで来たか」を尋ねられ、
oracle は直近の event と[workbench](#工作台)を一目見てから答えます。**その発言はその run の
コンテキストには入りません** —— 尋ねても run に影響せず、答え終われば捨てられます。

### subagent {#subagent}

Claude Agent SDK の概念:主 agent が `Agent` ツールを通じて派遣する子 agent。**自分専用の
transcript を一本**持ち、ツール呼び出しや試行錯誤はそちらに記録され、main thread は最終報告だけを
受け取ります。

これは flower がコンテキストを節約する第一の層であり、最も節約する層でもあります。
[コンテキスト経済学](../guide/context.md)を参照。

---

## 四つの仕組み

### clarify {#前置确认}

**clarify**

手を動かす前にまず要件を問い明かし、一份の[brief](#需求确认书)に凍結してから、実行を始めること。
防ぐのは「作ったものが望んだものではない」です。[clarify](../guide/clarify.md)を参照。

### brief {#需求确认书}

**brief** · `Brief`

[clarifier](#确认者)が問い終えた後に産出する文書、**ちょうど四段**。後続の step がこれを読み、
要件を推測し直すことはもうしません。

[task brief](#任务书)と**混同しない**でください。brief は「人が何を望むか」、task brief は
「この subagent が今回何をするか」です。

### task brief {#任务书}

**task brief**

[coordinator](#协调者)が仕事を割り振るときに[worker](#执行者)に書き渡すあの一段。**今回のタスク
固有のものだけを書きます** —— 相手が既に知っている規律は繰り返さない。

実測:8/8 份の task brief がすべて相手の既知の規律を繰り返しており、最も短い一份は 521 文字のうち
タスク固有なのは約 120 文字だけで、一ラウンドで約 4.8k の永久コンテキストを無駄に占めました。

### goal guard {#目标看守}

**goal guard**

[judge](#判定者)が各ラウンド終了後に独立して目標達成の有無を判定し、達成していなければ差し戻して
続けさせること。防ぐのは「終わったと言うが実は終わっていない」です。[goal guard](../guide/goal.md)を参照。

### verdict {#判定}

**verdict** · `Verdict`

[judge](#判定者)による一ラウンドの判定結果、**ちょうど三段**:結論 / 理由 / 未通過。

結論は三種類、`ACHIEVED`(達成)、`NOT_YET`(未達)、`UNREACHABLE`(この環境では検証できない)。
**後の二つは異なる結論です** —— 「ここでは検証できない」を通過とは絶対に判定しません。

### continuity {#接续}

**continuity**

同じディレクトリでもう一度走らせると、自動で前回の進捗に接続します —— プロセスが kill されても、
マシンが再起動しても同じ。防ぐのは「数時間走って落ちたら最初からやり直し」です。
[continuity](../guide/continuity.md)を参照。

[handoff](#换代)と**混同しない**でください:continuity は**プロセスをまたいで**前回の run に接続します。
handoff は**同一の run 内部で**新しい session に切り替えます。

### handoff {#换代}

**handoff**

コンテキストがもうすぐ満杯になるとき、現在の session に人が読めて改められる一份の[handoff document](#交接书)を
書かせ、それから新しい session を開いて引き継がせること。防ぐのは「コンテキストが満杯になって一段の
摘要に圧縮される」です。[handoff](../guide/handoff.md)を参照。

**compact ではありません。** [compact](#压缩)を参照。

### handoff document {#交接书}

**handoff document** · `Handoff`

handoff のときに書く文書、五段:`doing`(何をしているか)、`decided`(何を決めたか)、
`deadends`(通じなかった道)、`next`(次の一手)、`scene`(現場)。

**必須なのは `doing` と `next` だけです** —— 「通じなかった道」を非空にする硬い要求は、
モデルにでっち上げを強います。

### compact {#压缩}

**compact**

Claude Code のネイティブなやり方:コンテキストが満杯になると、前の対話を一段の摘要にまとめます。

flower は**これを使いません**、[handoff](#换代)で代替します。違いはこうです:摘要はモデルが生成し、
読めず改められず、何を捨てたか分かりません。handoff document は構造化され、落盤され、あなたが開いて
一行改めてから続けて走らせられます。

---

## コンテキスト管理

### main thread {#主线程}

**main thread**

[coordinator](#协调者)がいるあの session コンテキスト。run 全体を貫く唯一のコンテキストなので、
最も節約が必要です。

コード上で main thread を判定する方法:hook データに `agent_id` が**ない**こと。subagent の hook には
`agent_id` が付きます。

### workbench {#工作台}

**workbench** · `Workbench`

落盤される作業ディレクトリ、三つのサブディレクトリ:

| ディレクトリ | 何を置くか |
|---|---|
| `scripts/` | 二度目に走らせるスクリプト、先頭行に `# desc: 一言` を書く |
| `artifacts/` | 2000 文字を超える長い産出 |
| `notes/` | 重要な決定、一つの決定に一つのファイル |

`INDEX.md` はこの三つのディレクトリのインデックスで、**system prompt に注入される**ので、
agent は毎ラウンド手元に何があるかを知っています。

!!! warning "二つの入口、二つのデフォルト位置"
    workbench をどこに置くかは、どう作るかに依存し、これは踏みやすい点です:

    | 作成方法 | workbench のルートディレクトリ |
    |---|---|
    | `Workbench(workspace)` —— `starter_flow()` / `wake_state()` が通る道でもある | `<ワークスペース>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench`(デフォルト `runs/workbench`) |

    コマンドラインは前者を通るので、`flower` を走らせると出てくるのは `.flower/` です。しかし Python で
    直接 `Runtime(workbench=True)` を使うと得られるのは `runs/workbench` です。位置を指定したければ
    作成済みの `Workbench` インスタンスを渡し、デフォルト値に依存しないでください。

!!! warning "インデックスは subagent が継承できない"
    インデックスは session レベルの `system_prompt.append` を通るので、**subagent は受け取れません**。
    だから「長い産出は `artifacts/` に書く」という規律は、[coordinator](#协调者)が[task brief](#任务书)の中で
    伝え直すしかありません —— それが唯一の通り道です。

### spill {#落盘}

**spill**

ツール結果が閾値(デフォルト 4000 文字)を超えると、`PostToolUse` hook がそれを
`<workbench ルートディレクトリ>/spill/` に書き出し、コンテキストにはパス一行だけを残します。

パスは**[workbench](#工作台)に付いて動き**、決め打ちではありません —— workbench がデフォルト位置
`<ワークスペース>/.flower` にあるときだけ、それはちょうど `.flower/spill/` になります。
[isolation](#隔离)を有効にし、workbench が `home=` でリポジトリ外に指されたときは、spill もそれに
付いて外へ移ります。

**その場ですぐ剪除し**、コンテキストが満杯になってから振り返って[compact](#压缩)するのではありません。

### ephemeral command {#一次性命令}

**ephemeral command**

結果が期限切れになり、留存する価値のないコマンド —— `ls`、`git status`、`ps` の類。これらの結果は
永続化される session 記録に入りません。「main thread に一目走らせてよいか」と「結果が trim されるか」を
判断するのに、同じ関数を使うので、二つの集合は常に等しくなります。

### trim {#裁剪}

**trim** · `TrimmingSessionStore`

**resume の前に**、モデルに送り返すあのメッセージ群([ephemeral command](#一次性命令)の結果、
長すぎるツール出力)を書き換えます。

これは `load()` だけを上書きします:**SQLite 内の原文は常に動きません**、trim されるのは今回の resume で
コンテキストに送り込む一份だけです。だから trim は可逆です —— 別の戦略でもう一度 resume すれば、
また完全な記録が得られます。

### prune {#剪除}

**prune** · `PruningSessionStore`

**エラーメッセージ**をコンテキストの外に締め出します。ネットワーク断からの再試行の間に生まれた大量の
エラーは、resume 後のコンテキストを占めるべきではありません。

[trim](#裁剪)と**混同しない**でください:trim は体積と価値で捨て、prune は「エラーかどうか」で捨てます。

---

## ランタイム

### isolation {#隔离}

**isolation**

マークされた役割は自動で独立した git worktree に分けられ、プロンプトではなく hook によって強制されます。
同じリポジトリを並行して改めるとき、ぶつかりません。

!!! warning "isolation を有効にしたら workbench をリポジトリ外へ移す"
    worktree isolation を有効にするとき、[workbench](#工作台)は `home=` でリポジトリ外に指す必要があります。
    さもないと isolation された agent は共有 checkout に書き込めません。

### resilience {#韧性}

**resilience** · `Resilience`

ネットワーク断のときに失敗して抜けるのではなく、掛けたまま待ちます:DNS + TCP プローブが見張り、
ネットワーク回復後に resume で続けます。待機の間に生まれるエラーメッセージは[prune](#剪除)が
コンテキストの外に締め出します。

### lineage {#血缘}

**lineage** · `Lineage`

プロセスをまたいで「この run がどの session から fork されたか」を記録し、`lineage.json` に落ちます。
[continuity](#接续)はこれによって前回どこまで走ったかを見つけます。

[run manifest](#运行清单)と**混同しない**でください —— あれは `runs/manifest.json` で、各 run の
帳簿を記録します。

### run manifest {#运行清单}

**run manifest** · `runs/manifest.json`

各[run](#运行)の帳簿記録:いくら使ったか、どれだけ走ったか、コンテキストがどれだけ大きいか。
ケースページの数字はすべてここで検算できます。

### wake {#唤醒}

**wake** · `wake_state()`

走り出す前の**読み取り専用の探査**:このワークスペースに既に[brief](#需求确认书)と目標があるかを見て、
今回が全く新規の開始か[continuity](#接续)かを決めます。**一バイトも書きません。**

`wake_state()` は workbench の位置を定義する唯一の場所です —— ドライバプログラムが brief の在り処を
知りたいときもこれを通らねばなりません。自分でパスを組んで間違えてもエラーは出ず、静かに失効するだけです。

### event {#事件}

**event** · `Event`

SDK のメッセージストリームを平坦化した安定した構造。**[interaction layer](#交互层)は `Event` しか
認識せず、いかなる SDK 型も import しません** —— これが UI を換えても核を改めなくてよい境界です。

### interaction layer {#交互层}

**interaction layer**

人と run の間のあの UI 層。デフォルトはターミナルで、Web、TUI、HTTP、あるいは全自動の無人運用に
換えられます。[interaction layer を換える](../guide/interaction.md)を参照。

### session store {#会话存储}

**session store** · `SessionStore`

session メッセージの永続化バックエンド。デフォルトの `SqliteSessionStore` は `runs/sessions.db` に
書き、[trim](#裁剪)と[prune](#剪除)の二層のラッパーを被せられます。

### budget {#预算}

**budget** · `max_budget_usd`

一回の run の費用上限、超えると止まります。long-horizon な run にこれがないととても高くつきます ——
[HT001](../cases/ht001.md) は $171.62 使いました。

---

## 可搬性

### portable {#可移植}

**portable**

マシンを換えても、挙動が一致すること。やり方は `setting_sources=[]` —— ホストマシンの `~/.claude/` を
読まず、プロジェクトの `.claude/` も読みません。ドメイン能力は [plugin](#plugin) がリポジトリに付いて動き、
認証情報は `.env` が自ら携えます。

代償:**認証情報は自ら携えねばならず**、ホストマシンの設定を自動継承しません。

### append {#叠加}

**append**

ドメイン指令を Claude Code のネイティブなシステムプロンプトの**後ろに**追加し、置き換えません:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

だから専門化は汎用能力を失う代償を払いません。

### plugin {#plugin}

リポジトリに付いて動くドメイン能力パッケージ。`plugins=[local]` を通じて読み込まれ、ディレクトリには
`skills/`、`agents/`、`hooks/`、`.mcp.json` を置けます。[デプロイ](deploy.md#plugin)を参照。
