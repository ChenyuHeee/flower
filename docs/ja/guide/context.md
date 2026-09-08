# コンテキストの経済学

[メインスレッド](../reference/glossary.md#主线程)のコンテキストは、1 回の [long-horizon](../reference/glossary.md#长程) 実行を通じて最初から最後まで貫かれている唯一のものだ。そこに何を載せ、何を載せないかが、この実行がどこまで走れるかを決める。flower の形 —— [コーディネーター](../reference/glossary.md#协调者)は手を動かさない、長い成果物は spill する、hook がその場で刈り取る —— は、すべてこの一点から導かれている。このページはその理由を書く。

## 何を解決するのか {#解决什么问题}

[compact](../reference/glossary.md#压缩) はコンテキストが埋まるのを待ってから振り返って要約するもので、治しているのは対症的な部分だ。本当の問題はこうだ:**些末なものは最初からメインスレッドに入るべきではない。**

差はタイミングにある。1 回の `pytest` の出力は平気で数万文字になる。モデルはそれを一目見て結論を 1 つ取るだけで、残りの文字はそれ以降、毎ターン送り直される。ウィンドウが埋まる頃には、compact がそれを隣の意思決定ごと 1 段落の要約にまとめてしまう —— 節約できるのは体積で、失われるのは「当初なぜそう決めたのか」だ。auto-compact の発動閾値は**ウィンドウ − 33k**([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py))。その時点では、捨ててよいものと捨ててはいけないものが既に並んで横たわっている。

flower は 4 つの層で解決する。順序がそのまま優先度 —— 節約できる量の順だ:

| 層 | 何をするか | どこ |
|---|---|---|
| 一、分業 | 手を動かす作業は [subagent](../reference/glossary.md#subagent) に渡し、試行錯誤はその subagent 自身の transcript に入る | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 二、ワークベンチ | スクリプト / 長い成果物 / 意思決定を spill し、インデックスを system prompt に注入する | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 三、その場で spill | `PostToolUse` hook が閾値を超えたツール結果を spill し、コンテキストにはパス 1 行だけを残す | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 四、trim と prune | resume の前にセッションを書き換える:期限切れの結果、拒否された呼び出し、切断の残骸を再投入しない | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py)、[`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

前の 2 層は**入れるか入れないか**を、後ろの 2 層は**既に入ったものを残すか残さないか**を管理する。順序は逆にできない:第四層がどれだけ強力でも、第一層から漏れ込んだ量は取り戻せない。

## 使い方(最小コード) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model のデフォルトは "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

この数行で前の 3 層が入る:`coordinator()` は常に `delegate_only=True` を設定する(第一層)。`workbench=True` は[ワークベンチ](../reference/glossary.md#工作台)を作り、インデックスをコーディネーターの system prompt に注入する(第二層)と同時に、`Runtime` に `spill_guard` を装着する(第三層)。第四層はデフォルトで既に入っている —— `Runtime` の[セッションストア](../reference/glossary.md#会话存储)は `PruningSessionStore` にハードコードされていて、コンストラクタ引数に差し替え口はない。

!!! warning "`workbench=True` はオプションではない"
    コーディネーターが手を動かすのを止める `delegate_guard` は `workbench_hooks` にぶら下がっており、`workbench_hooks` は `Runtime` にワークベンチがあるときにしか装着されない。`whitelist_guard` のほうは `delegate_only=True` のためにスキップされる。結論:**`Runtime(workbench=False)` と `coordinator()` を組み合わせた場合、メインスレッドの Bash / Write / Edit には壁が 1 枚もない。**

## 実際に何をしているのか {#它实际做了什么}

### 第一層:分業(最も節約できる) {#第一层分工省得最多}

コーディネーターは「Claude Code を使える人間」を演じる:分解し、作業を振り、レポートを読み、意思決定する。Bash / Write / Edit は手に入らない —— ツールは `Agent`、`TodoWrite`、`Read` だけだ(`glance=True` のときは制限付きの `Bash` が 1 つ加わる。下を参照)。手を動かす作業はすべて[ワーカー](../reference/glossary.md#执行者)に渡す。

**いつ発動するか**:メインスレッドが `Bash|Write|Edit|NotebookEdit` を呼ぶたびに、`PreToolUse` hook の `delegate_guard` がその場で deny し、同時に道を示す ——「Agent ツールで subagent を派遣し、タスクに目標と受け入れ基準を明記し、長い成果物は `.flower/artifacts/` に書き、返答はパスと結論だけにするよう要求せよ」。subagent は一律で通す。判定基準は hook データに `agent_id` があるかどうか:**無いものがメインスレッドだ**。

**どれだけ節約できるか**:subagent のツール呼び出しと試行錯誤は**その subagent 自身の transcript に入る**(セッションストアでは `subpath` で区別する)。メインスレッドに残るのはその 1 回の `Agent` 呼び出しと最終レポートだけだ。試行錯誤の過程は compact で消されたのではなく、**そもそもメインスレッドに入ったことがない**。

- 実測(大量のツール出力を生むタスク):transcript の 83% が subagent 側に落ちた。メインスレッドは 13 件・21K 文字、subagent は 105K 文字。
- 実測(実規模、10.4 時間の実行 1 回。[HT001](../cases/ht001.md) を参照):subagent が**97.7%** のターン、**94.8%** の本文文字を担った。手を動かすツール呼び出しは 1,893 回 vs メインスレッド 32 回(**59:1**)。早期の compact はもはや主戦場ではない。

この 2 行は別々の 2 回の測定だ:上は初期の小規模テスト、下は実規模での再測定。同じ機構で、規模が大きいほど節約も大きい。

節約されるのはコンテキストであって、モデルのグレードではない:`worker()` はデフォルトで `model="inherit"` —— ワーカーが格下げされるべきではない。

分業の唯一の逆コストは[タスクブリーフ](../reference/glossary.md#任务书) —— コーディネーターが作業を振るときに書くあの文章だ。これはメインスレッドに入り、しかも永続的に残る。実測では 8/8 のタスクブリーフが、相手が既に知っている規律を復唱していた。最短の 1 通 521 文字のうち、そのタスク固有なのは約 120 文字だけで、1 ターンあたり約 4.8k の永続コンテキストを無駄に占める。だから `COORDINATOR_RULES` には次の 1 条がハードコードされている:**タスクブリーフにはそのタスク固有のことだけを書く**。唯一なお伝えるべき規約は「ワークベンチの場所 + 長い成果物は `artifacts/` に書く + 返答はパスと結論だけ」だ —— ワークベンチのインデックスは subagent には入らないので、タスクブリーフが唯一の経路になる。

### 第二層:ワークベンチ(「毎回書き直す」を治す) {#第二层工作台治每次重写}

`.flower/` 配下の 3 つのディレクトリがワークスペースに付いて回る:

| ディレクトリ | 何を置くか | 何を解決するか |
|---|---|---|
| `scripts/` | 2 回目も走る検証 / 再現スクリプト。1 行目に `# desc: 一句话` | 一度書けば以降はそのまま実行できる。「compact 後に失われ、毎回書き直す」がなくなる |
| `artifacts/` | 2000 文字を超える長い成果物:ログ、データ、レポート、diff | 会話に出るのはパスと結論だけ |
| `notes/` | 重要な意思決定とその理由。1 決定 1 ファイル | compact されても、再起動しても、マシンを替えても結論は残る |

**いつ発動するか**:`INDEX.md` は自動生成される(デフォルト最大 40 件)。`refresh()` は `PostToolUse` の `index_guard` が `Write` / `Edit` をワークベンチ内で検出したときに呼ぶほか、各ステップの開始前にも 1 回リフレッシュされる。上の 3 つの規約は `prompt_block()` によってコーディネーターの system prompt に注入される —— 開始時点でどんな既製スクリプトがあるかを知っており、発見のためにツール呼び出しを 1 回使う必要がない。

**どれだけ節約できるか**:10.4 時間の実行 1 回の実測で、**61 本のスクリプトが 95 回書かれ、331 回実行された。92% が 2 回以上実行され、書いたが走らせなかったものは 0 本**。定性的には `audit-fake-ai-server.py` が 7 本のスクリプトから再利用された。

この層が効くのは 1 つの差のおかげだ:compact はコンテキストを消せるが、**ディスクは消せないし、system prompt の中のインデックスも消せない**。

!!! warning "インデックスは subagent に継承されない"
    インデックスはセッション単位の `system_prompt.append` を通る。subagent は自分の system prompt を持つので、**継承されない**(実測 $0.2461、`tests/prelude_live.py`)。だから「ワークベンチの場所 + 長い成果物は `artifacts/` に書く」はコーディネーターがタスクブリーフの中で伝え直さなければならない —— それが唯一の経路であって、冗長ではない。

### 第三層:その場で spill {#第三层当场落盘}

`spill_guard` は `PostToolUse` hook で、ツール結果が**モデルに入る前**に一目見る:`threshold`(デフォルト **4000** 文字)を超えたものはワークベンチの `spill/` ディレクトリに [spill](../reference/glossary.md#落盘) し、コンテキスト側はポインタ 1 行 + **先頭 400 文字**に置き換える。内容は失われず、常駐しないだけだ。

**いつ発動するか**:matcher は `Bash|Read|Grep|Glob|WebFetch|WebSearch`。デフォルトは `main_only=False` なので、subagent の結果も spill される。置き換えるのはツール出力構造の中の長すぎる**文字列フィールド**だけで、list には一切触れない(中に画像ブロックが入っている可能性があるため)。`updatedToolOutput` は元のツールの出力構造を保たなければならないからだ。

**spill ファイル自体の読み取りは通し、再度 spill しない。** そうしないと、あの 1 行のヒントにある「全文が必要なら Read で読め」が空文句になる:読み戻すとまた閾値を超え、また spill され、またポインタ 1 行が返ってくる、という無限ループだ。実測で衝突した(`tests/handoff_live.py` の初回の実走)。モデルは 5 通りの書き方で回避を試み、自分で "The spill read loops back on itself" と言い、最後は 40 行ずつ力技で読み進め、7〜8 ターンを無駄に燃やした。spill の意味は「**自動的には**大きいものをコンテキストに詰め込まない」ことだ。モデル自身が全文を見ると決めるなら、それは彼の選択だ。

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None または 0 = この hook を装着しない
```

**どれだけ節約できるか**:[HT001](../cases/ht001.md) の実行では、103 回の spill、791.4K 文字がパスのポインタに置き換わり、コンテキストに常駐しなかった。

### 第四層:trim と prune {#第四层裁剪与剪除}

この層は[セッションストア](../reference/glossary.md#会话存储)の中にある。`Runtime` の store は常に `PruningSessionStore`(継承チェーンは `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`)で、`load()` —— つまり **resume の前** —— に、投入し直す履歴を書き換える。SQLite の原文は 1 文字も変えない。やることは 4 つ:

**① 時効切れ**(`ephemeral`、デフォルト有効)。`git status`、`ls`、`cat` のような[一時的コマンド](../reference/glossary.md#一次性命令)の結果は、数ターン後に本文が説明文 1 行に置き換わり、直近 6 件を残す。期限切れの内容は **spill しない** —— 古い `git status` を 1 部保管しても意味がなく、走らせ直せば得られるからだ:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

ライブ resume の実測で `expired: 2`。実 transcript 上で `keep_recent` を 2 に下げると 5 件が期限切れになった。

**② [trim](../reference/glossary.md#裁剪)**(`trim`、**デフォルト無効**)。`>= 2000` 文字の tool_result 本文を `<workspace>/.flower/spill/` に spill し、ブロックの内容をファイルポインタに置き換え、直近 20 件は原文のまま残す。このディレクトリは第三層 `spill_guard` の spill 先とは**同じではない**ことに注意:後者はワークベンチのルート直下に書くが、こちらはワークスペース内でなければならない。そうでないと agent の `Read` が届かない。

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True でも可
```

**③ 拒否された呼び出しを [prune](../reference/glossary.md#剪除) する**(`keep_denials`、デフォルト 1)。止めるというその行為自体もコンテキストを汚す:拒否メッセージは 1 件の `tool_result` であり、**一度も実行されなかったコマンド**と一緒に永続的に残る。実測で 1 回 273 文字(拒否文 93 文字 + 死んだコマンド 180 文字)、死んだコマンドのほうが拒否文より高くつく。

token より厄介なのは、それが**誤誘導すること**だ:実測では、コーディネーターは「Bash を直接使わない」という記述を数件読んだ後、通るはずの `git status` すら試さなくなり、「Bash は制限されているので agent を派遣して見てもらう」と言い出した —— 学習性無力感を学習してしまい、かえって subagent の起動コストを 1 回余計に払う。デフォルトを 0 ではなく 1 にしているのは、最新の拒否は有効なシグナルであり、モデルが同じターンで同じ拒否済みコマンドを繰り返し再試行するのを防げるからだ。識別は harness 自身が付ける構造的マーカー `toolDenialKind: "permission-rule"` に頼り、文面のマッチはしない —— 文面はいつでも変わるが、マーカーは変わらない。ライブ実測:2 件の拒否 → 1 件除去して 1 件を残す。チェーンは切れず、resume は正常で、モデルは何が起きたかを依然として把握していた。

**④ 切断の残骸を prune する**。ネットワーク切断のリトライ中に生じた合成 API エラーメッセージは投入し直さない。中断によって残された `tool_result` は中立的な説明文 1 行(`[上一轮在此处被中断,该工具结果未产生]`)に置き換え、エントリ自体は保持する。

**除去時のレッドライン**:`tool_use` とその `tool_result` は**一緒に**除去しなければならない(片方欠けると `Missing Tool Result Block`)。同じ assistant メッセージ内の他の呼び出しを巻き添えにしてはならず、`parentUuid` チェーンは繋ぎ直さなければならない。

`Runtime(trim=False)`(デフォルト)は**何も掃除しないという意味ではない**:大きい結果の trim をオフにするだけで、期限切れ・拒否された呼び出し・切断の残骸の処理はそのまま行う。

### 反例:ちょっと見るだけの作業は自分でやる {#反例看一眼的活自己干}

前の 3 層はどれも「外に出せ」と言っているが、反例がある:`git status`、`ls`、`cat` のようなコマンドは結果が数十文字なのに、**subagent を 1 つ派遣すると起動だけで約 4.3k のコンテキストを要する**(実測、償却できない)。`ls` 1 本のためにこの値段を払うのは純損だ。

そこでコーディネーターは制限付きの Bash を取り戻す(`coordinator(..., glance=True)`、デフォルト有効)。判定基準は「コマンドが短いか」ではなく、**結果が期限切れになるかどうか**であり、しかも「通す」と「期限切れ」は同じ関数 `is_ephemeral()` が決める:

| | 自分で実行するのを通す | 結果が期限切れとして印を付けられる |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ 派遣する | — |

両側は同じ 1 枚の表でなければならない。どちらか一方だけが成り立つと有害だ:**通すが trim しない**なら、期限切れの `git status` が永続的にコンテキストを占め、しかも現状と誤認されて意思決定を誤らせる。**trim するが通さない**なら、コーディネーターは `ls` 1 本のために 4.3k を払うことになる。`tests/glance.py` はこの不変条件をアサーションとして固定している —— 実測で 46 本のコマンドについて両側の判定が完全に一致した(敵対的サンプル 10 本を含む)。

**落とし穴(2 回踏んだ)**:モデルは単一コマンドを書かない。書くのは `git status -s && echo "--- LOG ---" && git log --oneline -10` だ。初版は `&&` / `|` / `2>&1` を含むコマンドを一律で拒否したところ、**glance が完全に機能しなくなった** —— 実測でコーディネーターの 3 回の試行がすべて阻止され、結局 subagent の派遣に戻った。現在はセグメントごとに分解して検査する:各セグメントがすべてホワイトリストにあるときだけ通し、`git status && rm -rf x` はきちんと止まる(後半のセグメントが表にないため)。

### append であって置換ではない {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

`build_options()` が `AgentSpec` を SDK オプションにコンパイルするとき、`instructions` は [`append`](../reference/glossary.md#叠加) を通る —— Claude Code のネイティブ system prompt の**後ろ**に追加されるのであって、置換ではない。したがって上に挙げた規律テキスト(`COORDINATOR_RULES`、`WORKER_RULES` など)は加算だ:**専門化は汎用能力を犠牲にしない。**

ワークベンチのインデックスもこの経路を通る。毎ターン存在するが、system prompt の一部なので会話履歴を占めず、compact でも消えない —— 代償は上に書いたとおり:**コーディネーターにしか届かない**。

!!! warning "コーディネーターに手を動かさせないために `disallowed_tools` を使ってはいけない"
    `disallowed_tools` は**セッション単位**で、subagent まで一緒に禁止する。実測のエラー原文:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    正しいやり方は 2 段階だ:`allowed_tools` に入れず、その上で `PreToolUse` hook が `agent_id` を見てメインスレッドだけを止める。`coordinator()` は既にこうしている —— `delegate_only=True` を設定し、`delegate_guard` がメインスレッドを止めて subagent を通す。

    `allowed_tools` だけでも足りない:それは**承認不要リストであって、排他的なホワイトリストではない**。実測ではモデルはそこにないツールを呼び出せた —— $0.1 のプローブ 1 回で、`allowed_tools=["Read"]` の agent が Write / Bash を平然と呼び出した。実際に止めているのは hook だ。

## いつ使うべきでないか {#什么时候不该用它}

この 4 層が節約するのはすべて**現場**だ。以下の問題は解決しないし、いくつかはこれらのせいでかえって見えにくくなる:

1. **目標の理解が間違っている場合 —— この 4 層はそれを悪化させる。** 現場が捨てられた後に残るのは、まさに誤った前提の上に建てられたその意思決定であり、しかもそれは**正しい意思決定と見た目がまったく同じ**だ。long-horizon はそれを最悪の形に増幅する:誤った前提でまず数時間走り、十数体の subagent を派遣し、ディスクに成果物を積み上げ、その後で露見する。そのときに高くつくのは token ではなく、成果物のすべてが間違った要求に沿って作られていることだ。これを防ぐのは[事前確認](clarify.md)であって、このページのどの層でもない。
2. **メインスレッドは依然として単調増加する。** 4 層が抑えるのは傾きであって、向きではない。実測:メインスレッドは 70 ターンで 28.7K から 185.9K に増え、傾きは 2.2K/ターン、全期間 compact なしで 1M ウィンドウの 18.6% を使った。**外挿すると約 440 ターンで壁にぶつかる**。その壁を越えるのは[ハンドオフ](handoff.md)だ。
3. **全量 compact を切った後のフォールバックがない。** ハンドオフが有効なとき、`Runtime` は spec に `CompactPolicy(mode="no_summary")` を強制し、auto-compact はそこで無効になる(spec 自身が明示的に `compact` を与えている場合はそれを尊重する)。上限への衝突はハードエラーなので、この 4 層はハンドオフとセットで使わなければならず、compact を切っただけで済ませてはいけない。
4. **第四層は resume のときにしか効かない。** trim も prune も `load()` で起きるので、連続して走り続けているセッションがそれで小さくなることはない。上の分業をやった後なら、この層はおそらく出番がない —— メインスレッドにはそもそもツール結果がさほど入らない。
5. **ちょっと見るだけの作業を外に出すのは純損。** subagent の起動は約 4.3k。上の glance の節を参照。
6. **コンテキストを並べ替える前にキャッシュの勘定をせよ。** 実測で 1 回の実行の入力は 299.4M token、**96.1% がキャッシュにヒット**した。$171 が成立するのはこれのおかげだ。履歴を書き換えるあらゆる最適化は、まずこの勘定をすること。
7. **画像やドキュメント系のツール結果は spill しない。** `spill_guard` は出力構造の中の文字列フィールドしか変更せず、list には一切触れない。

パラメータの完全なデフォルト値とシグネチャは [Python API](../reference/api.md) を、用語は[用語集](../reference/glossary.md)を参照。
