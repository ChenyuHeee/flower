# 設定

flower には設定ファイル形式がなく、実際に動く設定サブコマンドもない —— すべての設定は**環境変数**と
**`.env` ファイル**、それに Python 側からしか渡せない一群のポリシーオブジェクトで構成される。このページは五箇所に散っているものを一つにまとめる:
各変数、認証情報を探す順序、`.env` が認識する文法、`setting_sources=[]` が何を遮断するのか、
1 回 run するとディスクに何が残るのか、session store の三層がそれぞれ何を捨てるのか、ネットワークが切れたときどう待つのか。用語はすべて[用語集](glossary.md)に従う。

| 知りたいこと | 行き先 |
|---|---|
| flower が認識する環境変数 | [環境変数の完全表](#环境变量) |
| 自分の token が結局どこから来ているのか | [認証情報の探索優先順位](#凭证查找优先级) |
| `.env` のあの行がなぜ効かないのか | [`.env` の解析ルール](#env-解析) |
| 別のマシンに移すとき何を持っていくか | [portable であることの代償](#可移植性) |
| `.flower/` と `runs/` の中身 | [ディスクレイアウト](#磁盘布局) |
| モデルに戻されないメッセージはどれか | [session store の三層](#会话存储) |
| ネットワークが切れたとき何を待っているのか | [ネットワーク断への resilience](#韧性) |

## 環境変数の完全表 {#环境变量}

四つのグループに分かれる: flower が直接読む認証情報とエンドポイント、モデル選択、パス探索、そして flower が agent の子プロセスに**書き出す**もの。
最後のグループは自分で設定する必要はない —— 設定しても上書きされる。

### 認証情報とエンドポイント {#凭证变量}

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic 公式 key。あれば `x-api-key` ヘッダでリクエストする | なし | `ANTHROPIC_AUTH_TOKEN` と**どちらか一方が必須** | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | ゲートウェイが発行した token。`ANTHROPIC_API_KEY` がないときは `authorization: Bearer` を使う | なし | 同上 | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | API エンドポイントのルートアドレス。サードパーティのゲートウェイは自分のアドレスを入れる。**`/v1` は付けない** —— プローブが組み立てるのは `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | 否 | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

両方とも未設定(あるいは両方とも空文字列)なら、`check_credentials()` はあの 4 行のエラーを返し、`Runtime.__init__`
も `RuntimeError` を投げる(`env.py:184-194`;`runtime.py:156-158`)。

### モデル選択 {#模型变量}

flower が自分の判断に使うのはそのうち三つだけで、残りはロードして SDK にそのまま渡すだけだ。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | メインモデル名。同時に[handoff](glossary.md#换代)ウィンドウのデフォルト値も決める: 名前に `1m` を含むか `haiku` を含まない → 100 万、`haiku` を含む → 20 万 | なし(端側が決める) | 否 | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | opus 段のモデルマッピング。`ANTHROPIC_MODEL` が空のとき、ウィンドウ判定はこれにフォールバックする | なし | 否 | `agent.py:78`;`cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | sonnet 段のモデルマッピング。flower 自身は読まず、ロードと借用だけを行う | なし | 否 | `env.py:34`;`cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | haiku 段のモデルマッピング。**認証情報プローブはこれを優先して使う** | プローブは `ANTHROPIC_MODEL`、さらに `claude-3-5-haiku-20241022` にフォールバック | 否 | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | [subagent](glossary.md#subagent) が使うモデル。flower は解釈せず、SDK が消費する | なし | 否 | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | 思考の段位。同上、ロードするだけで解釈しない | なし | 否 | `env.py:35` |

`flower setup` でモデル名を入力した場合、`ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、
`ANTHROPIC_DEFAULT_SONNET_MODEL` の**三つが一緒に書かれる**(`cli.py:1204-1206`)。

### パスと探索 {#路径变量}

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `FLOWER_ENV` | `.env` ファイルのパスを一つ指定する。他のすべてのファイル**より前**に来る | なし | 否 | `env.py:48-49` |
| `XDG_CONFIG_HOME` | グローバル認証情報ファイルの位置 `$XDG_CONFIG_HOME/flower/.env` を決める | `~/.config` | 否 | `env.py:41-42` |
| `HOME` | `Path.home()` の出どころ。`~/.config` と `~/.claude` の両方のパスがここから導かれる | システム依存 | 否 | `env.py:41`、`:67` |

### flower が agent の子プロセスに書き出すもの {#写出的变量}

この三つは `CompactPolicy.env()` が生成して `ClaudeAgentOptions.env` に入れるもので(`agent.py:48-58`、`:241-245`)、
harness 内蔵の[compact](glossary.md#压缩) を制御する。**shell で設定しても意味はない** ——
実際に効くのは flower が子プロセスに渡す方だ。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` で自動 compact を切る。[handoff](glossary.md#换代) が有効なときは**強制的に書き込まれる** —— 二つの仕組みが同時に走ると、コンテキストの落ち込みがどちらの仕業か分からなくなる | handoff はデフォルトで有効なので、実質常に `1` | 否(flower が書く) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` で `/compact` も含めて切る。`CompactPolicy(mode="off")` のときだけ書かれる | 書かない | 否(flower が書く) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 自動 compact のウィンドウ(tokens)。`CompactPolicy(window=N)` のときだけ書かれる | 書かない | 否(flower が書く) | `agent.py:56-57` |

### コンテナラッパーが読むもの {#容器变量}

この二つは flower 本体が読むのではなく、`docker/flowerbox` という shell ラッパーが読む。完全な使い方は[デプロイ](deploy.md)を参照。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `FLOWER_HOME` | `--env-file` に使う `.env` をどこに探しに行くか | スクリプト自身の位置の一つ上のディレクトリ | 否 | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | どのイメージを使うか | `flower-box` | 否 | `docker/flowerbox:13` |

**`.env` のキーは上記に限られない。** パーサは**すべての** `k=v` 行を `os.environ` にロードし、ホワイトリストは適用しない
(`env.py:30`、`:102-107`)。上の 9 個の認証情報キーからなる `KNOWN` が効くのは二箇所だけだ: `~/.claude`
の設定を借用するときのホワイトリスト(`env.py:72`)と、`-v` 起動時に `describe()` が出力するフィールドの範囲(`env.py:205`)。

## 認証情報の探索優先順位 {#凭证查找优先级}

`load_dotenv()` にパスを渡さない場合、以下の順序で**存在するすべての**ファイルを順に読み込む
(`env.py:45-53`、`:78-112`):

1. **プロセス環境変数** —— 常に最優先。どんな `.env` も、すでに export された値を上書きできない。(`env.py:91`)
2. **`$FLOWER_ENV` が指すファイル** —— 設定したときだけこの項目がある。(`env.py:48-49`)
3. **`$PWD/.env`** —— カレントワーキングディレクトリ。`cd` したプロジェクトのものを近い順に読む。(`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** —— ユーザごとに一つのグローバルな場所。`flower setup` が書くのはこれ。(`env.py:51`、`:39-42`)
5. **ソースリポジトリのルートの `.env`** —— `flower/core/env.py` から三階層上。ソースから走らせたときだけ存在する。pip / pipx / uv でインストールした flower は site-packages の中にあるので、この項目はない。(`env.py:52`)
6. **`~/.claude/settings.json`、次に `~/.claude/settings.local.json` の `env` ブロック** —— 最後のフォールバック。**9 個の認証情報キーだけを取る**。(`env.py:56-75`、`:109-111`)

**どのファイルが勝つか**: 3(プロジェクトの `.env`)が 4(グローバルの `.env`)に勝ち、4 が 5(リポジトリルートの `.env`)に勝ち、
その三つすべてが 6(Claude Code の設定)に勝つ。そしてすべてが 1(プロセス環境)には勝てない。

実装は「**すでに値があるキーは上書きしない**」(`env.py:90-93`): 先に来たものがキーを押さえ、後のものは空きを埋めるだけだ。
つまり優先順位は**キー単位であって、ファイル単位ではない** —— プロジェクトの `.env` に `ANTHROPIC_BASE_URL` だけ書いてあれば、
token はグローバルの方から来て構わない。同名キーは最初に現れた値で確定する。

6 番目は**自動探索のとき**だけ有効になる。明示的にパスを渡した場合(`load_dotenv("/path/to/.env")`)はそのファイル一つだけを読み、
いかなるフォールバックも通らない(`env.py:86-87`、`:109`)。

### 6 番目: Claude Code の token を借りる {#借用}

`~/.claude/settings.json` と `~/.claude/settings.local.json` を順に読み、`data["env"]` という dict を取り出し、
その中から次の 9 個のキーを拾う(`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

ファイルが存在しない、読めない、あるいは正しい JSON でない(`OSError` / `ValueError`)場合は、空の dict を返して先へ進む ——
**フォールバックの失敗がこの run を巻き込んではならない**(`env.py:62-63`、`:66-69`)。

コード上の立場はこうだ: 借りるのは「token をどこに探しに行くか」だけであり、settings.json の中の他の何か(権限ルール、hook、
モデル設定)は一切引き継がない。だからこれは `setting_sources=[]` の portable であるという約束に反しない(`env.py:17-19`、`:59-61`)。
`install.sh:77` はこれを機能として宣伝している: ローカルで Claude Code を設定済みの人は、設定画面すら見ずに済む。

!!! warning "プロダクト内のエラー文言は実際の挙動と逆になっている"
    認証情報がまったく見つからないとき、flower が出力するエラーの最終行はこうだ:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`、その一文は `:192`;同じ主張は `.env.example:2`、`env.py:3-4`、
    `agent.py:10-12` にも出てくる。)**コードが正しい: 読んでいる。** `env.py:56-75` と `:109-111` は明確にその二つのファイルを読みに行くし、
    `install.sh:77` はこれをセールスポイントにしている。この文言は現状ミスリーディングだ ——
    Claude Code を設定済みのマシンでは、あなたの token はおそらくそこから来ている。

## `.env` の解析ルール {#env-解析}

解析ルールは暗記できるほど短い(`env.py:95-107`、13 行): 各行を `strip` し、空行、`#` で始まる行、
`=` を含まない行をスキップする。残りは**最初の** `=` で key と value に切り、両側をそれぞれ `strip` し、value にはさらに
`.strip("'\"")` をかける —— 先頭と末尾のシングル/ダブルクォートは一律に剥がされ、**対になっている必要はない**。

**認識される書き方**:

| 書き方 | 結果 |
|---|---|
| `KEY=VALUE` | 正常 |
| `KEY = VALUE` | 正常 —— 等号の両側の空白は strip される |
| `KEY="VALUE"` / `KEY='VALUE'` | 正常 —— 先頭末尾のクォートが剥がされる |
| `KEY=a=b` | value は `a=b` —— 最初の `=` で切るので、以降の等号は値の中にそのまま残る |
| `# コメント` | 行ごとスキップ |
| 空行 | スキップ |

**認識されない書き方**。書いてもエラーにはならず、黙って予期しない値になるだけだ:

| 書き方 | 実際の結果 |
|---|---|
| `export KEY=VALUE` | key が `export KEY` になり、`KEY` 自体には依然として値がない |
| `KEY=value # 説明` | value は `value # 説明` —— 行末コメントは剥がされない |
| `KEY=$OTHER` | リテラル `$OTHER`。変数展開はしない |
| 複数行の値(クォートで行をまたぐ) | 行ごとに処理され、2 行目は `=` を含まないので行ごとスキップされる |

**空の値はキーを押さえてしまう**。優先順位の高いファイルに `ANTHROPIC_AUTH_TOKEN=` があると、`take()` は
`os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` を実行し、後続のファイルは「キーがすでに存在する」ため埋められなくなる
(`env.py:90-93`)。一方 `check_credentials()` は真偽値で判定するので、空文字列は未設定と同じ扱いになる(`env.py:186`)。
**結果として認証情報もなく、フォールバックも取れなくなる。** あるキーが不要なら行ごと消すこと。空のまま残さない。

## portable であることの代償 {#可移植性}

`build_options()` の中のあの 1 行がすべての仕掛けだ(`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` は `Runtime` のデフォルト値で、**コマンドラインにこれを切るスイッチはない** —— 切るには Python API で
`Runtime(portable=False)` と書くしかなく、そうすると `["project"]` になり、プロジェクトの `.claude/` を読むようになる。

### 遮断されるもの

| 遮断されるもの | 帰結 |
|---|---|
| ホストの `~/.claude/` の設定 | そこにある権限ルール、hook、モデル設定は一切効かない。**認証情報だけが唯一の例外**、[借用](#借用)を参照 |
| プロジェクトの `.claude/` | 同上。`portable=False` のときだけ読む |

ドメイン能力はこの経路を通らない —— リポジトリとともに配布され、`plugins=[{"type": "local", "path": PLUGIN_DIR}]` でロードされる
(`agent.py:26`、`:210-212`)。[デプロイ](deploy.md)を参照。ドメイン指示は Claude Code のネイティブなシステム
プロンプトの後ろに**append** されるものであり、置き換えではない(`agent.py:198-202`)。だから専門化は汎用能力を犠牲にしない。

### 別のマシンに移すとき何を持っていくか

- **認証情報: ファイル一つ**。`~/.config/flower/.env` をコピーするか、新しいマシンで設定し直すだけでいい。
  持っていかなければ何も動かない —— 自動的に継承されるものは一切ない。
- **continuity の状態: ディレクトリまるごと**。`runs/`(session の DB、manifest、lineage)と `.flower/`(workbench)。
- **ただしパスは一致させること**。`lineage.json` にはワークスペースの絶対パスが入っており、合わなければ無いものとして扱われ、黙って新しい session に戻る。
  **エラーは出ない**(`lineage.py:65-66`)。理由は SDK の `project_key` がワークスペースのパスから導出されるからだ
  (`/`、`_`、`.` はすべて `-` に置換される、`runtime.py:40-41`)。ディレクトリの位置が変われば、古い `session_id` は引けなくなる。

## ディスクレイアウト {#磁盘布局}

flower を 1 回走らせると 2 本のツリーが書かれる: `<run_dir>/` に帳簿と session、`<workspace>/.flower/` に[workbench](glossary.md#工作台)。
どちらもデフォルトではカレントディレクトリの下だが、**基準が違う**。

!!! warning "`runs/` はカレントディレクトリに追随し、`-w` には追随しない"
    `-r/--run-dir` のデフォルトは `"runs"` で、`Runtime` はこれに `Path(run_dir).resolve()` をかける
    (`runtime.py:93-94`)—— つまり**カレントワーキングディレクトリ**基準であって、`-w` で指定したワークスペース基準ではない。
    `~` で `flower -w /path/to/proj` を走らせると、session の DB は `~/runs/` に落ち、プロジェクトの中には入らない。

### `<run_dir>/` —— デフォルトは `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite,全量 transcript(含每个 subagent 自己那条)
  manifest.json      运行清单:每一步的 session_id / 花费 / 重试 / 失败原因,跨进程累积
  lineage.json       血缘:步骤名 → session_id,同一个目录再跑一次靠它接上
  aside/             旁路问答的独立 Runtime,自己的 sessions.db + manifest.json
  workbench/         仅当走 run / once 路径且给了 -W
```

| パス | 内容 | 出典 |
|---|---|---|
| `runs/sessions.db` | 全量の transcript。書くのは `PruningSessionStore` で、三層の戦略は[後述](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | JSON 配列。**プロセスをまたいで積み上がる**[run manifest](glossary.md#运行清单)。フィールドは下表 | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`。先に `.tmp` を書いてから `replace` する、アトミックな置換 | `lineage.py:31`、`:87-97` |
| `runs/aside/` | [oracle](glossary.md#旁路顾问)の独立した Runtime。**コストと lineage はメインの manifest に混ざらない** | `cli.py:632-634` |
| `runs/workbench/` | `Runtime(workbench=True)` のデフォルトの workbench 位置。ワークスペースの外にある。`go` の経路では使わない | `runtime.py:148-151` |

`manifest.json` の各行は `asdict(StepResult)` に 2 つのパッチを当てたものだ(`runtime.py:44-71`、`:579-582`):

| フィールド | 型 | 意味 |
|---|---|---|
| `step` | `str` | step 名。4 つの形態: `<名>`、`<名>#round<N>`(差し戻しでやり直し)、`<名>#retry<N>`(通常のリトライ)、`<名>·判定#<N>`([judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | この step で最後に生きていた[session](glossary.md#会话) |
| `ok` | `bool` | 成功したかどうか |
| `cost_usd` | `float` | この step でいくらかかったか |
| `num_turns` | `int` | 何ターン回ったか |
| `text` | `str` | この step の最終的な返答 |
| `error` | `str \| None` | 失敗理由。SIGHUP / SIGTERM で殺されたときは `killed-by-signal`(`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch 秒 |
| `attempts` | `int` | 実際の試行回数。`>1` ならリトライしている |
| `errors` | `list[str]` | 過去の失敗理由。**ここにしかなく、モデルからは見えない** |
| `resumed` | `bool` | resume で中断地点から継いだのか、最初からやり直したのか |
| `retired` | `list[str]` | この step の[handoff](glossary.md#换代)で焼いた session_id、順番通り |
| `context` | `int` | 最終ターンで[main thread](glossary.md#主线程)が実際に見たコンテキスト規模 |
| `duration_s` | `float` | 手で補ったもの —— これは `@property` なので `asdict()` では拾えない |
| `run` | `str` | 本プロセスのマーカー `YYYYmmdd-HHMMSS-<6 位 hex>`。**インスタンスごとに必ず一意** |

書き込み方針は**追記であって上書きではない**: 毎回の書き出し前にファイルを読み直し、`run` が自分と一致する行を最新に差し替え、
他人の行はそのまま残す(`runtime.py:564-586`)。だから同じディレクトリで複数の flower を並行に走らせても、帳簿が互いを潰すことはない。

`runs/` の中身は純粋なデータであり、いつでも sqlite3 や
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)
でオフラインで調べられる。

### `<workspace>/.flower/` —— workbench {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

3 つのサブディレクトリとインデックスは `Workbench` が作る(`workbench.py:73-92`)。`INDEX.md` は session レベルの
`system_prompt.append` を通るので、**subagent には継承されない** —— したがって「長い成果物は `artifacts/` に書く」というルールは
[coordinator](glossary.md#协调者)が[task brief](glossary.md#任务书)の中で伝え直すしかない。それが唯一の経路だ。

`go` の経路では `notes/` の下に必ず次のものが生成される:

| ファイル | 内容 | 出典 |
|---|---|---|
| `notes/需求.md` | 凍結された[brief](glossary.md#需求确认书)。4 節: 目標 / 受け入れ基準 / 境界 / 未知と仮定 | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | 凍結された 2 節: 目標 / 判定チェックリスト | `workflow/goal.py:124` |
| `notes/问答记录.md` | すべての問答の追記記録。「人が自発的に言った」インボックスの項目も含む。**コンテキストには入らず、記録として残すだけ** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | [handoff document](glossary.md#交接书)。前の世代は `notes/archive/交接/<步骤名>-<时间戳>.md` に収める | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `--new` / `/new` でアーカイブされた `lineage.json` + `需求.md` + `目标.md`(**移動であって削除ではない**) | `lineage.py:100-117` |

**`--isolate` のとき workbench はリポジトリの外に移る**: `<workspace の親ディレクトリ>/.flower-<workspace 名>/`
(`starter.py:47-55`)。worktree は agent ごとのプライベートなコピーで、workbench は agent をまたぐ共有層だ。
共有されるものをプライベートな囲いの中に置くことはできない。このときモデルに渡すパスは絶対パスになる(`workbench.py:69-71`、`:142-145`)。

**`spill/` には書き込み者が 2 つあり、書き込み先の算出方法が異なる**:

| 誰が書くか | いつ | どこへ書くか | 閾値 |
|---|---|---|---|
| `spill_guard`(`PostToolUse` hook) | ツール結果がモデルに入る**前** | `<workbench の root>/spill/`(`guard.py:130`) | `spill_threshold`、デフォルト 4000 文字 |
| `TrimPolicy`(`load` 時) | resume 前に履歴をリプレイするとき | `<workspace>/.flower/spill/` —— ワークスペース基準の固定文字列(`trim.py:49`、`:303`) | `min_chars`、デフォルト 2000 文字 |

デフォルトのレイアウトではこれは同じディレクトリだ。しかし workbench が移された場合(`-W` で `runs/workbench/` に落ちる、あるいは `--isolate`
でリポジトリの外に落ちる)、両者は分かれる —— `TrimPolicy` の方は常にワークスペースの中にある。agent の `Read` が
届かなければならないからだ。

`spill_guard` が差し替えるのは 1 行ではなく、1 行のポインタと**冒頭 400 文字**だ(`guard.py:132-140`)。
spill ファイル自体を読む呼び出しは通される。そうでなければ「全文が必要なら Read で読め」が空文句になる —— 読み戻すとまた閾値を超え、また spill され、
無限ループになる(`guard.py:155-170`)。

### `sessions.db` のテーブル構造 {#sessions-db}

3 つのテーブル。CREATE 文は `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| テーブル | 1 行が何か | 要点 |
|---|---|---|
| `entries` | transcript の 1 件。`payload` は生の JSON | `uid` は項目の `uuid` で、**冪等キー**として働く: 失敗したバッチは 3 回までリトライされるので、リプレイが重複行を生んではならない。`uuid` を持たない項目(タイトル、タグ、モードマーカー)は重複排除しないので、UNIQUE インデックスに `WHERE uid IS NOT NULL` が付いている |
| `meta` | 1 つの session のカーソル | `next_seq` は次の連番、`mtime` はミリ秒のタイムスタンプで**厳密に単調**(`sqlite.py:72-79`)—— `list_sessions` と summary がこの時計を共有しており、単調でないと SDK の新旧判定が誤った高速パスに入る |
| `summaries` | 1 つの main thread のサマリ sidecar | **メインの transcript のみが対象**で、subagent のものは数えない(`sqlite.py:122-123`) |

`store_key` の構成(`sqlite.py:54-58`): `<project_key>/<session_id>`、subagent はさらに
`subpath` が付く。`project_key` は SDK がワークスペースのパスから導出する —— `/`、`_`、`.` はすべて `-` に置換される。

実際のサンプルを見てみる([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

このサンプルは `entries` が 956 件、`meta` が 10 件、`summaries` が 4 件 —— 10 件の session のうち 4 件がメインの transcript、
6 件が subagent のもので、`summaries` はちょうどメインの transcript の数と等しい。

## session store の三層 {#会话存储}

!!! note "三層は継承チェーンであって、選択可能な組み合わせではない"
    `PruningSessionStore` は `TrimmingSessionStore` を継承し、それは `SqliteSessionStore` を継承する。
    `Runtime` は**常に**最も外側のものを構築し(`runtime.py:109-112`)、構築パラメータにバックエンドを差し替える入口はない。
    「ある層を切る」方法は、その層のポリシーオブジェクトの `enabled` を `False` にすることであって、クラスを差し替えることではない。

`append`(書き込み)は常に全量をディスクに落とし、一字も変えない。三層が影響するのは `load`(モデルに戻して食わせる方)だけだ。
`load` の実際の順序はこうなる:

```text
SqliteSessionStore.load     从 entries 表按 seq 读出全部
  → TrimmingSessionStore.expire()   时效性 Bash 结果 → 换成"已过期"
  → TrimmingSessionStore.trim()     旧的大 tool_result → 落盘 + 换成指针
    → PruningSessionStore.prune()   合成错误消息 / 旧的被拒调用 → 整条摘掉并重接链
```

| 層 | クラス | 何を捨てるか | 判断基準 |
|---|---|---|---|
| 1 | `SqliteSessionStore` | 何も捨てない | —— |
| 2 | `TrimmingSessionStore` | 大きなツール結果の本文、期限切れの ephemeral command の結果 | サイズ + 鮮度 |
| 3 | `PruningSessionStore` | 切断の残骸、古い拒否された呼び出し | エラーかどうか |

第 2 層が[trim](glossary.md#裁剪)、第 3 層が[prune](glossary.md#剪除) ——
**trim はサイズと価値で捨て、prune は「エラーかどうか」で捨てる**。混同しないこと。完全なシグネチャは [Python API](api.md) を参照。

### `SqliteSessionStore` —— 土台 {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

外部依存ゼロの SQLite 実装。Postgres / S3 / Redis に差し替えたければ、同じプロトコルを実装すればよい。SDK には整合性テスト
スイート `claude_agent_sdk.testing.session_store_conformance` が付属しており、そのまま検証できる(`sqlite.py:1-8`)。

プロトコルのメソッド以外に、flower 自身が使う 3 つの**同期**クエリがある:

| メソッド | 戻り値 | 用途 |
|---|---|---|
| `projects()` | `list[str]` | DB に実際に存在する `project_key`。SDK は cwd から導出するが、クエリ前にこれで確認すること。推測しない |
| `has_session(project_key, session_id)` | `bool` | `meta` の 1 行を引くだけで、payload は読まない。[continuity](glossary.md#接续) を始める前にまず引く —— 存在しない session を resume すると、子プロセスが起動した後になって初めて落ちる。そのときにはもう金も時間も使っている |
| `last_context(project_key, session_id, scan=60)` | `int` | この session の最終ターンが見たコンテキストの大きさ。末尾 60 件だけを逆向きに走査する。`input_tokens` と 2 つの `cache_*` をすべて数える —— 前者だけを見るとキャッシュヒット時にほぼ 0 になり、大幅に過小評価してしまう |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

直交する 2 つのルール。`TrimPolicy` は**サイズ**を担当する:

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 直近 N 件の `tool_result` は原文を保持する —— 今使っているコンテキストは trim すべきでない |
| `min_chars` | `int` | `2000` | これより短ければ trim しない。ポインタに置き換える方がかえって token を食う |
| `spill_dirname` | `str` | `".flower/spill"` | アーカイブ先ディレクトリ。**workspace 基準**。ワークスペース内でなければならない。さもないと agent の `Read` が届かない |
| `enabled` | `bool` | `True` | `Runtime(trim=False)`(デフォルト)のときは `False` |

trim された本文は `<sha256 前 16 位>.txt` として書かれ、元の位置は
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` に置き換わる(`trim.py:54-57`、`:308-317`)。

`EphemeralPolicy` は**鮮度**を担当する: `git status`、`ls`、`ps` のような結果は短く、サイズ基準では永遠に trim の順番が回ってこない。
しかしその正しさは時間とともに劣化する —— 20 ターン前の `git status` は「役に立たない」のではなく、**誤解を招く**。

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(ephemeral=…)` から変換される。**デフォルトで有効** |
| `keep_recent` | `int` | `6` | 直近 N 件は原文を保持する。`TrimPolicy` の 20 よりずっと小さい —— この種のものは「直近」のウィンドウがそもそも短い |
| `max_chars` | `int` | `2000` | これを超えたら `TrimPolicy` に渡して spill でアーカイブし、この経路は通らない |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | 置き換えの文言 |

**Bash** ツールの結果にのみ作用し、しかもコマンドが `EPHEMERAL_CMD` にマッチする必要がある。`Read` は対象外だ: ファイルの内容は
時間の経過によって誤解を招くほど歪むことはないし、それがモデルの推論の根拠そのものであり得る(`trim.py:153-160`)。期限切れの内容は
**spill しない** —— 期限切れの `git status` をアーカイブしても意味はなく、もう一度実行すれば手に入る。

判定関数は `is_ephemeral(cmd)` で、これは**同時に coordinator に返す権限リストでもある**: `delegate_guard(allow_glance=True)`
が使うのは同じ関数だ(`trim.py:63-68`、`:128-150`)。二つの集合は常に一致していなければならない ——
通したのに trim しなければ、期限切れの `git status` が永久にコンテキストを占める。trim したのに通さなければ、coordinator は `ls` 一つのために
subagent を派遣し、4.3k の起動コストで数十文字を得ることになる。ホワイトリストにコマンドを 1 つ足すことは、この 2 つを同時に言うことに等しい。

**どんなときにどれを使うか**:

- 切断の残骸をコンテキストに入れたくないだけ → 何もしなくてよい。`Runtime` はデフォルトで `PruningSessionStore` だ。
  `trim=False` は大きな結果を trim しないだけで、prune は行われる。
- 長時間走る、ツール出力が大きい → `trim=True`。`go` 経路の CLI はデフォルトで有効になっており、`--no-trim` で逆に切る。
- [coordinator](glossary.md#协调者) が `glance=True` にしている → `ephemeral` は有効なままにしなければならない。理由は前段の通り。

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | `isApiErrorMessage=true` または `message.model == "<synthetic>"` の合成メッセージを取り除く |
| `neutralize_interrupts` | `bool` | `True` | `[Request interrupted …]` の `tool_result` は**本文を差し替えるだけで、ブロックは取り除かない** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | 前項の置き換え文言 |
| `keep_denials` | `int` | `1` | permission hook に拒否されたツール呼び出しを直近 N 件だけ残し、それより古いものは**呼び出しと結果をまとめて**取り除く |

`keep_denials` はこの層に透過的に渡される唯一の `Runtime` 構築パラメータだ(`Runtime(keep_denials=N)`)。
デフォルトが 0 ではなく 1 である理由: 最新の拒否は有効なシグナルであり、モデルが同じターン内で同じ遮断済みコマンドを繰り返し再試行するのを防げる。
**大きくするな** —— 拒否された呼び出しは一度も実行されておらず、結果には何の情報もない。実測で 1 件あたり 273 文字を占め
(93 文字の拒否文言と 180 文字の死んだコマンドの原文)、しかも**誤解を招く**: 実測では coordinator が「Bash を直接使うな」を数件読んだ後、
通されるはずの `git status` すら試さなくなり、「Bash は制限されているので、agent を派遣して見てもらう」と言い出した(`prune.py:135-148`)。

構造上のレッドラインが 3 本ある。破ると API が直接エラーを返す:

1. **`tool_result` ブロックそのものは残さなければならない**。差し替えていいのは `content` だけだ。1 つでも欠ければ "Missing Tool Result Block" になる
   (`trim.py:20-22`;`prune.py:79-92`)。
2. **`isCompactSummary` / `isMeta` の項目に触れてはならない** —— それは compact で圧縮された履歴の唯一の存在形式だ
   (`trim.py:179-181`)。
3. **1 件取り除いたら、その子をその親につなぎ直さなければならない**。transcript は `parentUuid` の単方向チェーンで、harness は葉から
   遡っていく。チェーンが切れた地点より前の履歴は全部失われる(`prune.py:95-122`)。だから `relink()` には取り除く対象を**含む**
   完全なリストを渡す必要があり、フィルタリングはそれ自身が行う。

**SQLite の中の原文は一字も変わらない** —— 三層が影響するのは「モデルに戻して食わせる方」だけだ(`trim.py:18`;`prune.py:8`)。

## ネットワーク断への resilience {#韧性}

long-horizon な workflow は一度走れば数時間になり、ネットワークは必ず一度は切れる。デフォルトの挙動はひどい: 切断した瞬間、harness は transcript
に合成の assistant メッセージ(`model="<synthetic>"`、`isApiErrorMessage=true`)を差し込み、本文は
`API Error: Can't reach the API server …` になる。それが session の葉になり、以後 resume すると「モデルが直前に言ったこと」として
食わされ、モデルは自分がネットワーク障害について議論していると思い込む。さらにそれは `StepResult.text` にも混ざり、workflow を伝って次の step の
prompt に渡る(`resilience.py:1-22`)。

[resilience](glossary.md#韧性)の層は 3 つのことをする。どれも欠かせない: プローブ、やり直しではなく続行、エラーをコンテキストに入れない。

### `Resilience` のパラメータ {#resilience}

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(resilience=…)` から変換される |
| `max_attempts` | `int` | `6` | 1 つの[step](glossary.md#步骤)を最大何回試すか。**初回を含む** |
| `base_delay` | `float` | `4.0` | 指数バックオフの起点、秒 |
| `max_delay` | `float` | `120.0` | バックオフの上限、秒 |
| `probe_timeout` | `float` | `5.0` | プローブ 1 回のタイムアウト、秒 |
| `probe_interval` | `float` | `15.0` | ネットワーク断のとき何秒ごとに探るか、秒 |
| `max_offline_wait` | `float` | `3600.0` | ネットワーク断で最大どれだけ待つか。デフォルト 1 時間 —— これより長いなら普通は揺らぎではなく、本当に何かが起きている |
| `retry_unknown` | `bool` | `True` | 分類できないエラーもリトライする。未知のエラーの多くは一過性であり、致命的なものはすでに個別に弾かれている |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | 続行時にモデルに言う言葉 |

バックオフの式(`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

つまり `±25%` のジッタで、ネットワーク復旧の瞬間に大量のプロセスが一斉に殺到するのを避ける。デフォルト値では: 1 回目のバックオフは 4 秒(実際は 3~5)、
2 回目は 8 秒(6~10)、5 回目以降は 120 秒で頭打ち(90~150)。

### プローブの方針 {#探针}

- **探るのは `ANTHROPIC_BASE_URL` の host:port** であって、`api.anthropic.com` ではない(`resilience.py:67-72`)。
  自前のゲートウェイを使っている場合、後者が通っても前者が通る証明にはならない。
- **DNS と TCP ハンドシェイクだけを行う**: `getaddrinfo` してから `connect_tcp` し、すぐ閉じる。HTTP は送らず、
  認証情報も付けず、金もかからない(`resilience.py:75-85`)。プローブは無料でなければならない。さもなければ「ネットワーク断のとき 15 秒ごとに探る」こと
  自体が障害になる。
- 失敗はすべて到達不能とみなす —— DNS が落ちたのか TCP が拒否されたのかは区別しない。
- `wait_online()` はそこでぶら下がって待つ: 通れば `True` を返し、`max_offline_wait` を待ち切れば `False` を返す。
  最初に到達不能になったときに `<host>:<port> 不可达,等待恢复(最多 60 分钟)` を 1 行通知し、復旧したらもう 1 行
  `<host>:<port> 恢复,继续` を通知する。**その間は画面を流さない**(`resilience.py:126-140`)。

走り出す前の認証情報プローブは別物だ: こちらは実際に `POST <BASE_URL>/v1/messages` を 1 回叩き、`max_tokens=16`、
タイムアウトはデフォルト 20 秒(`env.py:126-181`)。`max_tokens` を **1 にしてはいけない** —— 実測では思考の連鎖を強制するモデルは思考すら
収まらず、サーバ側が 30 秒までもがいてようやく返した。16 にすればわずか 3.6 秒だ(`env.py:120-123`)。

### エラー分類 {#错误分类}

`classify(text)` は 3 種類のいずれかを返す。**まず致命的かを判定する**: 401 のようなテキストにはしばしば "connection" のような語も含まれており、
順序を逆にすると永遠に待つことになる(`resilience.py:53-64`)。

| 分類 | 何にマッチするか(正規表現は `resilience.py:37-50`) | 挙動 |
|---|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` | 即座に停止、リトライしない。何回リトライしても結果は同じで、しかも毎回金がかかる |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`timeout`、`service unavailable` | ネットワークの復旧を待ち、その後 resume で続行する |
| `unknown` | どれにもマッチしない | `retry_unknown=True`(デフォルト)ならリトライする |

リトライ可能かどうかを区別することがこの層の核心だ: **ネットワークの揺らぎは待つべきで、認証情報の誤りは即座に止めるべきだ** ——
ネットワーク断のときに待ち続けるのは正しいが、key を書き間違えたときに待ち続けるのは時間を燃やすだけだ。

### 何がコンテキストの外に締め出されるか {#错误不进上下文}

1. **合成エラーメッセージ**。`PruningSessionStore` が `load` 時にまるごと取り除き、`parentUuid` をつなぎ直す
   (`prune.py:27-32`、`:191-195`)。**SQLite にはそのまま残る**。ただ食わせ直さないだけだ。
2. **イベントストリームでは `kind="text"` ではなく `kind="error"` になる**ので、`StepResult.text` に入らず、
   したがって workflow を伝って次の step の prompt に渡ることもない(`resilience.py:17-18`)。
3. **`resume_prompt` は意図的にエラーの詳細を一切含まない**。モデルが知る必要があるのは「中断された、続けろ」であって、
   `ENOTFOUND` なのか `503` なのかではない。**それはログに属するものであって、コンテキストに属さない**(`resilience.py:112-113`)。
   ログは `manifest.json` の `errors` フィールドを見ること。

やり直しではなく続行: 失敗が起きた時点で `session_id` はすでに取れているので、resume で中断地点から継ぎ、それまでのコストを無駄にしない。

## 関連 {#相关}

- [コマンドライン](cli.md) —— 各スイッチがこのページの設定にどう対応するか。
- [Python API](api.md) —— `Runtime`、3 つの store、`Resilience` の完全なシグネチャ。
- [デプロイ](deploy.md) —— コンテナで走らせる、plugin でドメイン能力を配布する。
- [用語集](glossary.md) —— このページで使ったすべての語の正確な意味。
