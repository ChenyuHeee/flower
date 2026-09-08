# 用語集

このページは flower ドキュメントの用語基準です。同じものは全サイトで一つの呼び方しかせず、中英対照はここで固定します —— 翻訳版もこの表に従います。

各項目で三つのことを示します:**その語が何を指すか**、**コード上では何か**、**何ではないか**。三つ目が一番役に立つことが多い。誤解のほとんどは、ある語を別の語と取り違えることから生まれるからです。

---

## フレームワークと run {#框架与运行}

### long-horizon {#长程}

**long-horizon**

一回の run が数時間から数日にわたり、複数の session をまたぎ、プロセス再起動をまたぐ —— 一問一答ではない。flower のすべての機構は、この種の run が途中で崩れないためにあります。

実測の参照:[HT001](../cases/ht001.md) は連続で 10.4 時間走りました。

### run {#运行}

**run**

一つの `Runtime` が開始から終了までたどる全過程。一回の run の内部には複数の[step](#步骤)、複数の[session](#会话)がありえて、中断してから[continuity](#接续)で続けられます。run の記録は `runs/manifest.json` と `runs/sessions.db` に残ります。

**そうではないもの**:1 回の API 呼び出しでも、1 本の session でもありません。

### session {#会话}

**session**

モデル側のコンテキスト 1 本。自分の `session_id` を持ち、resume でき、fork できます。一回の[run](#运行)は session を何本も焼き潰すことがあります —— [handoff](#换代) のたびに新しい 1 本に切り替わります。

### step {#步骤}

**step** · `Step`

[workflow](#流程) の中の実行単位。コンテキスト辞書を受け取り、agent を 1 回走らせ、結果を辞書に書き戻します。`Step` はクラスです。[Python API](api.md#step) を参照。

### workflow {#流程}

**workflow** · `Workflow`

順番に連ねた[step](#步骤)の集合と、step 間で状態をどう渡すか、いつ早期終了するかの取り決め。

!!! note "フレームワークは既製の workflow を提供しない"
    flower が提供するのは機構だけです。**workflow はあなたが書くもの**です。[workflow を設計する](../guide/workflow.md)を参照。

---

## 役割 {#角色}

役割は flower における agent の分業です。各役割 = 注入されるルールテキスト 1 本 + ツール一式 + hook 一式。5 つの役割はすべてファクトリ関数です。[Python API](api.md#角色工厂) を参照。

### coordinator {#协调者}

**coordinator** · `coordinator()`

[main thread](#主线程) 上にいる agent。タスクを分解し、仕事を割り振り、報告を読み、判断を下す。**しかし自分では手を動かさない** —— `Write` / `Edit` を持ちません。基本ツールは `Agent`、`TodoWrite`、`Read`(`roles.py:27`)ですが、それが最終的な一覧ではなく、引数に応じて 3 種類が追加されます:`glance=True`(デフォルト)は制限付きの `Bash` を足し(`git status` / `ls` のような一目見て終わるコマンドだけ、`delegate_guard` が門番)、質問チャネルを渡すと `inbox` と `ask` が足され、配下の[worker](#执行者)が `WebFetch` / `WebSearch` を持つならこの 2 つも合流します —— `allowed_tools` は**session 単位**なので、合流させないと subagent が自分で呼んだときに誰も応答しない権限承認で固まります(`roles.py:513-526`)。

役割設定は「Claude Code を使える人」であって、実行者ではありません。

**そうではないもの**:より賢い agent ではありません。[worker](#执行者) とデフォルトで同じモデル階層を使い、節約しているのはコンテキストであってモデルではありません。

### worker {#执行者}

**worker** · `worker()`

実際に手を動かす [subagent](#subagent):コードを書き、テストを走らせ、資料を調べる。ツールは `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`。

返答フォーマットはルールテキストで 4 段に固定されます —— **結論 / 根拠 / 成果物 / 未検証**、30 行以内、ファイル内容・コマンド出力・ログ・diff 原文の貼り付けは禁止。

### clarifier {#确认者}

**clarifier** · `clarify()`

手を動かす前に要求を問い詰める役割。仕事はせず、質問だけをし、明確になるまで問う(**ラウンド数の上限なし**)。最後に[brief](#需求确认书)を 1 部出力します。[clarify](../guide/clarify.md) を参照。

### judge {#判定者}

**judge** · `judge()`

「終わったかどうか」を判定する役割。次の 2 つのうち 1 つを行います:走り出す前に**目標を設定**する(目標 + 判定チェックリストを産出)、または各ラウンド終了後に**そのラウンドを判定**する([verdict](#判定) を産出)。[goal guard](../guide/goal.md) を参照。

**要点**:judge が判定するのは**成果物**であって、ソースコードではありません。

[HT001](../cases/ht001.md) で一度転んでいます:受け入れ基準は「macOS ターミナルで直接実行できること」だったのに、納品された成果物に `file` をかけると `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`、それでも判定は合格でした。

2 点はっきりさせておかないと、この例は誤読されます:

1. **あのとき誤判したのは goal guard ではない** —— HT001 にはまだこの機構がなく、誤判したのは coordinator が自発的に派遣した監査役でした。
2. **デフォルト設定の judge でも、おそらく同じく見逃します。** `judge()` はデフォルトで `can_run=False`、ツールは `Read/Glob/Grep` のみ —— **`file` を走らせられません**。`Makefile` を読んで確かに Darwin ブランチがあると確認し、達成と判定するだけです。

本当に効いたのは [HT002](../cases/ht002.md) です:judge が `judge_can_run` を有効にし、自分で `file` と `lsof` を走らせて現場を見に行き、この落とし穴を明確に回避しました。**つまり「成果物を判定する」という一文は、`can_run=True` があって初めて地に足がつきます。**

### oracle {#旁路顾问}

**oracle** · `oracle()`

読み取り専用のバイパス 1 本。run が走っている最中に「今どこまで進んだ?」と聞くと、直近の event と[workbench](#工作台)を一目見てから答えます。**その発言はその run のコンテキストには入りません** —— 聞いても run に影響せず、答えたら捨てられます。

### subagent {#subagent}

Claude Agent SDK の概念:主 agent が `Agent` ツールで派遣する子 agent。**自分自身の transcript を 1 本持ち**、ツール呼び出しも試行錯誤もそちらに記録され、main thread は最終報告だけを受け取ります。

これは flower がコンテキストを節約する第一層であり、最も節約量の大きい層でもあります。[コンテキスト経済学](../guide/context.md) を参照。

---

## 4 つの機構 {#四个机制}

### clarify {#前置确认}

**clarify**

手を動かす前に要求を問い詰め、[brief](#需求确认书) 1 部に凍結してから実行を始める。防いでいるのは「作ったものが望んだものではない」です。[clarify](../guide/clarify.md) を参照。

### brief {#需求确认书}

**brief** · `Brief`

[clarifier](#确认者) が問い終えた後に産出する文書。**ちょうど 4 段**。後続の step はこれを読み、要求を推測し直しません。

[task brief](#任务书) と**混同しないこと**。brief は「人が何を望むか」、task brief は「この subagent が今回何をするか」です。

### task brief {#任务书}

**task brief**

[coordinator](#协调者) が仕事を割り振るとき、[worker](#执行者) に書いて渡す文章。**今回のタスク固有のことだけを書く** —— 相手がすでに知っている規律を繰り返さない。

実測:8/8 部の task brief が相手の既知の規律を繰り返しており、最短の 1 部は 521 文字のうち約 120 文字だけがタスク固有、1 ラウンドで約 4.8k の永久コンテキストを無駄に占めていました。

### goal guard {#目标看守}

**goal guard**

[judge](#判定者) が各ラウンド終了後に独立して目標達成を判定し、未達なら差し戻して続行させる。防いでいるのは「終わったと言うが実は終わっていない」です。[goal guard](../guide/goal.md) を参照。

### verdict {#判定}

**verdict** · `Verdict`

[judge](#判定者) の 1 ラウンドの判定結果。**ちょうど 3 段**:結論 / 理由 / 未通過。

結論は 3 種類、`ACHIEVED`(達成)、`NOT_YET`(未到達)、`UNREACHABLE`(この環境では検証できない)。**後の 2 つは別の結論です** —— 「ここでは検証できない」は絶対に合格と判定しません。

### continuity {#接续}

**continuity**

同じディレクトリでもう一度走らせると、前回の進捗に自動で接続する —— プロセスが kill されても、マシンが再起動しても同じ。防いでいるのは「数時間走って落ちたら最初からやり直し」です。[continuity](../guide/continuity.md) を参照。

[handoff](#换代) と**混同しないこと**:continuity は**プロセスをまたいで**前回の run に接続すること、handoff は**同じ run の内部で**新しい session に切り替えることです。

### handoff {#换代}

**handoff**

コンテキストが満杯に近づいたら、今の session に人が読めて直せる[handoff document](#交接书)を書かせ、新しい session を立てて引き継がせる。防いでいるのは「コンテキストが満杯になって要約一段に潰される」ことです。[handoff](../guide/handoff.md) を参照。

**compact ではありません。** [compact](#压缩) を参照。

### handoff document {#交接书}

**handoff document** · `Handoff`

handoff のときに書く文書。5 段:`doing`(何をしているか)、`decided`(何を決めたか)、`deadends`(通らなかった道)、`next`(次の一手)、`scene`(現場)。

**必須は `doing` と `next` だけ** —— 「通らなかった道」を必ず非空にしろと強制すると、モデルが捏造します。

### compact {#压缩}

**compact**

Claude Code のネイティブなやり方:コンテキストが満杯になったら、それまでの会話を要約 1 段にまとめる。

flower は**これを使わず**、[handoff](#换代) で代替します。違いは:要約はモデルが生成したもので、読めず直せず、何を捨てたかわからない。handoff document は構造化され、ディスクに落ち、開いて 1 行直してから続きを走らせられます。

---

## コンテキスト管理 {#上下文管理}

### main thread {#主线程}

**main thread**

[coordinator](#协调者) がいる session コンテキスト。run 全体を貫く唯一のコンテキストなので、最も節約が必要です。

コード上で main thread を判定する方法:hook データに `agent_id` が**ない**こと。subagent の hook には `agent_id` が付きます。

### workbench {#工作台}

**workbench** · `Workbench`

ディスクに落ちた作業ディレクトリ。サブディレクトリは 3 つ:

| ディレクトリ | 何を置くか |
|---|---|
| `scripts/` | 二度目も走らせるスクリプト。先頭行に `# desc: 一句话` |
| `artifacts/` | 2000 文字を超える長い産出物 |
| `notes/` | 重要な決定。1 決定 1 ファイル |

`INDEX.md` はこの 3 ディレクトリのインデックスで、**system prompt に注入される**ため、agent は毎ラウンド手元に何があるかを把握します。

!!! warning "入口が 2 つ、デフォルト位置も 2 つ"
    workbench がどこに置かれるかは作り方に依存します。ここは踏みやすい:

    | 作り方 | workbench のルートディレクトリ |
    |---|---|
    | `Workbench(workspace)` —— `starter_flow()` / `wake_state()` が通る道でもある | `<ワークスペース>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench`(デフォルトは `runs/workbench`) |

    コマンドラインは前者を通るので、`flower` で走らせると `.flower/` ができます。しかし Python から直接 `Runtime(workbench=True)` とすると `runs/workbench` になります。位置を指定したいなら、作成済みの `Workbench` インスタンスを渡すこと。デフォルト値に頼らないでください。

!!! warning "インデックスは subagent に継承されない"
    インデックスは session 単位の `system_prompt.append` を通るので、**subagent には届きません**。したがって「長い産出物は `artifacts/` に書く」という規律は、[coordinator](#协调者) が[task brief](#任务书)の中で伝え直す必要があります —— それが唯一の経路です。

### spill {#落盘}

**spill**

ツール結果がしきい値(デフォルト 4000 文字)を超えると、`PostToolUse` hook がそれを `<workbench ルート>/spill/` に書き出し、コンテキストにはパス 1 行だけを残します。

パスは**[workbench](#工作台) に追従**し、固定ではありません —— workbench がデフォルト位置 `<ワークスペース>/.flower` にあるときだけ、ちょうど `.flower/spill/` になります。[isolation](#隔离) を有効にして workbench を `home=` でリポジトリ外に指したときは、spill も一緒に外へ移ります。

**その場で剪る**のであって、コンテキストが満杯になってから振り返って[compact](#压缩) するのではありません。

### ephemeral command {#一次性命令}

**ephemeral command**

結果が期限切れになり保存価値のないコマンド —— `ls`、`git status`、`ps` の類。その結果は永続化される session 記録に入りません。「main thread に一目見に行かせてよいか」と「結果が trim されるか」の判断には同じ関数を使うので、2 つの集合は常に等しくなります。

### trim {#裁剪}

**trim** · `TrimmingSessionStore`

**resume の前に**、モデルへ戻すメッセージ一式を書き換えます([ephemeral command](#一次性命令)の結果、超長のツール出力)。

これは `load()` だけをオーバーライドします:**SQLite 内の原文は一切動かさず**、trim されるのは今回の resume でコンテキストへ送る分だけです。つまり trim は可逆です —— 方針を変えてもう一度 resume すれば、また完全な記録が得られます。

### prune {#剪除}

**prune** · `PruningSessionStore`

**エラーメッセージ**をコンテキストの外に締め出します。ネットワーク断のリトライ中に生じた大量のエラーが、resume 後のコンテキストを占めるべきではありません。

[trim](#裁剪) と**混同しないこと**:trim は体積と価値で捨て、prune は「エラーかどうか」で捨てます。

---

## ランタイム {#运行时}

### isolation {#隔离}

**isolation**

印を付けた役割は自動で独立した git worktree に割り当てられます。hook が強制し、プロンプトには頼りません。同じリポジトリを並行で変更してもぶつかりません。

!!! warning "isolation を有効にしたら workbench はリポジトリ外へ"
    worktree isolation を有効にするときは、[workbench](#工作台) を `home=` でリポジトリ外に指す必要があります。さもないと隔離された agent が共有 checkout に書き込めません。

### resilience {#韧性}

**resilience** · `Resilience`

ネットワークが切れたら失敗終了せずにぶら下がって待ちます:DNS + TCP プローブが見張り、回線が戻ったら resume して続行します。待機中に生じたエラーメッセージは[prune](#剪除) がコンテキストの外に締め出します。

### lineage {#血缘}

**lineage** · `Lineage`

「この run はどの session から fork したか」をプロセスをまたいで記録し、`lineage.json` に落とします。[continuity](#接续) はこれを頼りに前回どこまで走ったかを見つけます。

[run manifest](#运行清单) と**混同しないこと** —— あちらは `runs/manifest.json` で、各 run の帳簿を記録します。

### run manifest {#运行清单}

**run manifest** · `runs/manifest.json`

各[run](#运行)の帳簿記録:いくら使ったか、どれだけ走ったか、コンテキストがどれだけ大きかったか。ケースページの数字はすべてここで再計算できます。

### wake {#唤醒}

**wake** · `wake_state()`

走り出す前の**読み取り専用の探査**:このワークスペースにすでに[brief](#需求确认书)と目標があるかを見て、今回が新規開始か[continuity](#接续)かを決めます。**1 バイトも書きません。**

`wake_state()` は workbench の位置の唯一の定義箇所です —— ドライバが brief の在り処を知りたいときも、ここを通す必要があります。自分でパスを組み立てて間違えてもエラーにはならず、静かに機能しなくなるだけです。

### event {#事件}

**event** · `Event`

SDK のメッセージストリームを平坦化した安定構造。**[interaction layer](#交互层) は `Event` しか知らず、SDK の型を一切 import しません** —— これが UI を差し替えてもコアを直さずに済む境界です。

### interaction layer {#交互层}

**interaction layer**

人と run の間にある UI の層。デフォルトはターミナル、Web、TUI、HTTP に差し替えられ、完全自動の無人運転にもできます。[interaction layer を差し替える](../guide/interaction.md) を参照。

### session store {#会话存储}

**session store** · `SessionStore`

session メッセージの永続化バックエンド。デフォルトの `SqliteSessionStore` は `runs/sessions.db` に書き、[trim](#裁剪) と[prune](#剪除) の 2 層でラップできます。

### budget {#预算}

**budget** · `max_budget_usd`

1 回の run の費用上限。超えたら停止します。long-horizon な run はこれがないと非常に高くつきます —— [HT001](../cases/ht001.md) は $171.62 かかりました。

---

## 可搬性 {#可移植性}

### portable {#可移植}

**portable**

別のマシンに移しても挙動が同じ。やり方は `setting_sources=[]` —— ホストマシンの `~/.claude/` を読まず、プロジェクトの `.claude/` も読みません。ドメイン能力は [plugin](#plugin) がリポジトリと一緒に移動し、資格情報は `.env` で自前で持ちます。

代償:**資格情報は自前で用意する必要があり**、ホストマシンの設定を自動継承しません。

### append {#叠加}

**append**

ドメイン指示は Claude Code ネイティブの system prompt の**後ろに**追記され、置き換えません:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

だから専門化は汎用能力の喪失を代償にしません。

### plugin {#plugin}

リポジトリと一緒に移動するドメイン能力パッケージ。`plugins=[local]` で読み込み、ディレクトリには `skills/`、`agents/`、`hooks/`、`.mcp.json` を置けます。[デプロイ](deploy.md#plugin) を参照。
