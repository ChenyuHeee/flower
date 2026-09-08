# 設定

flower には設定ファイル形式がなく、実際に動く設定サブコマンドもない —— 設定はすべて**環境変数**と
**`.env` ファイル**、それに Python 側からしか渡せないポリシーオブジェクト群だけだ。このページは 5 箇所に散っているものを 1 枚にまとめる:
変数の一覧、認証情報を探す順序、`.env` が受け付ける構文、`setting_sources=[]` が実際に何を遮断するのか、
1 回ラン すると何がディスクに残るのか、セッションストアの 3 層がそれぞれ何を捨てるのか、ネットワークが切れたときにどう待つのか。用語はすべて[用語集](glossary.md)に従う。

| 知りたいこと | 行き先 |
|---|---|
| flower が認識する環境変数 | [環境変数の完全な一覧](#环境变量) |
| 自分の token が結局どこから来ているのか | [認証情報の探索優先順位](#凭证查找优先级) |
| `.env` のあの行がなぜ効かないのか | [`.env` のパース規則](#env-解析) |
| 別のマシンに移すとき何を持っていくか | [ポータビリティの代価](#可移植性) |
| `.flower/` と `runs/` の中身 | [ディスクレイアウト](#磁盘布局) |
| どのメッセージがモデルに戻されないのか | [セッションストアの 3 層](#会话存储) |
| ネットワークが切れたとき何を待っているのか | [ネットワーク断のレジリエンス](#韧性) |

## 環境変数の完全な一覧 {#环境变量}

5 グループ:flower が直接読む認証情報とエンドポイント、モデル選択、パス探索、挙動スイッチ、そして flower が agent 子プロセスに**書き出す**もの。
最後のグループは設定する必要がない —— 設定しても上書きされる。

### 認証情報とエンドポイント {#凭证变量}

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic 公式の key。あれば `x-api-key` ヘッダでリクエストする | なし | `ANTHROPIC_AUTH_TOKEN` と**どちらか一方が必須** | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | ゲートウェイが発行する token。`ANTHROPIC_API_KEY` がないとき `authorization: Bearer` を使う | なし | 同上 | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | API エンドポイントのルート。サードパーティのゲートウェイは自分のアドレスを書く。**`/v1` は付けない** —— プローブが組み立てるのは `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | いいえ | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

両方とも未設定(あるいは両方とも空文字列)なら、`check_credentials()` はあの 4 行のエラーを返し、`Runtime.__init__`
も `RuntimeError` を投げる(`env.py:184-194`;`runtime.py:156-158`)。

### モデル選択 {#模型变量}

flower が自分の判断に使うのはこのうち 3 つだけで、残りはロードして SDK にそのまま渡すだけだ。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | メインモデル名。同時に[ハンドオフ](glossary.md#换代)ウィンドウのデフォルト値も決める:名前に `1m` を含むか `haiku` を含まない → 100 万、`haiku` を含む → 20 万 | なし(端側が決める) | いいえ | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | opus 段のモデルマッピング。`ANTHROPIC_MODEL` が空のとき、ウィンドウ判定はこれにフォールバックする | なし | いいえ | `agent.py:78`;`cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | sonnet 段のモデルマッピング。flower 自身は読まず、ロードと借用だけを担当する | なし | いいえ | `env.py:34`;`cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | haiku 段のモデルマッピング。**認証情報プローブはこれを優先して使う** | プローブは `ANTHROPIC_MODEL`、さらに `claude-3-5-haiku-20241022` にフォールバック | いいえ | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | [subagent](glossary.md#subagent) が使うモデル。flower は解釈せず、SDK が消費する | なし | いいえ | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | 思考の段位。同上、ロードするだけで解釈しない | なし | いいえ | `env.py:35` |

`flower setup` でモデル名を入力した場合、`ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、
`ANTHROPIC_DEFAULT_SONNET_MODEL` の**3 つがまとめて書かれる**(`cli.py:1383-1385`)。

### パスと探索 {#路径变量}

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `FLOWER_ENV` | `.env` ファイルのパスを 1 つ指定する。他のすべてのファイル**より前**に並ぶ | なし | いいえ | `env.py:48-49` |
| `XDG_CONFIG_HOME` | グローバル認証情報ファイルの位置 `$XDG_CONFIG_HOME/flower/.env` を決める | `~/.config` | いいえ | `env.py:41-42` |
| `HOME` | `Path.home()` の出どころ。`~/.config` と `~/.claude` の 2 本のパスはどちらもここから導かれる | システムが与える | いいえ | `env.py:41`、`:67` |

### 挙動スイッチ {#行为开关}

この 2 つはどちらも脱出口だ:設定しないのが通常で、設定するのは flower に何か 1 つをやらせないためだ。**任意の非空値を設定すれば有効**で、
値そのものはパースされない(`update.py:121`;`cli.py:1413`)。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | [自動アップデート](../getting-started/install.md#自动更新)を切る。未設定なら、pip / pipx / uv で入れた flower は起動時にバックグラウンドスレッドを 1 本立てて新バージョンの有無を調べ、あればインストールする。**次に `flower` を走らせたときに初めて有効になる**。確認は 24 時間に最大 1 回、タイムスタンプは `~/.config/flower/.update` に記録される | なし(自動アップデートは有効) | いいえ | `update.py:32-33`、`:121-124` |
| `FLOWER_NO_PROBE` | 起動時のあの[認証情報プローブ](cli.md#第二道-凭证能不能用)をスキップする。非対話(パイプ / CI / リダイレクトされた stdin)ではもともとプローブしないので、この変数は対話的ターミナル向けの逃げ道だ | なし(対話時はプローブする) | いいえ | `cli.py:1413` |

git ソースから走らせる flower は自動アップデートの影響を受けず、`FLOWER_NO_UPDATE` はそれに対して no-op だ ——
アップデートコマンドのその段階で、リポジトリに `.git` があると認識したら直接 `None` を返す(`update.py:83-87`)。

### flower が agent 子プロセスに書き出すもの {#写出的变量}

この 3 つは `CompactPolicy.env()` が生成して `ClaudeAgentOptions.env` に詰め込むもので(`agent.py:48-58`、`:241-245`)、
harness 内蔵の [compact](glossary.md#压缩) を制御する。**shell で設定しても意味がない** ——
実際に効くのは flower が子プロセスに渡すほうだ。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` で自動 compact を切る。[ハンドオフ](glossary.md#换代)が有効なとき**強制的に書き込まれる** —— 2 つの仕組みが同時に走ると、コンテキストの落ち込みがどちらの仕業か区別できなくなる | ハンドオフはデフォルト有効なので、実質つねに `1` | いいえ(flower が書く) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` で `/compact` まで含めて切る。`CompactPolicy(mode="off")` のときだけ書かれる | 書かない | いいえ(flower が書く) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 自動 compact のウィンドウ(tokens)。`CompactPolicy(window=N)` のときだけ書かれる | 書かない | いいえ(flower が書く) | `agent.py:56-57` |

### コンテナラッパーが読むもの {#容器变量}

この 2 つは flower 本体が読むものではなく、`docker/flowerbox` という shell ラッパーが読む。詳しい使い方は[デプロイ](deploy.md)を参照。

| 変数 | 役割 | デフォルト | 必須 | 出典 |
|---|---|---|---|---|
| `FLOWER_HOME` | `--env-file` に渡す `.env` をどこから探すか | スクリプト自身の位置の 1 つ上のディレクトリ | いいえ | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | どのイメージを使うか | `flower-box` | いいえ | `docker/flowerbox:13` |

**`.env` のキーは上記に限られない。** パーサは**すべての** `k=v` 行を `os.environ` にロードし、ホワイトリストは適用しない
(`env.py:30`、`:102-107`)。上記 9 つの認証情報キーからなる `KNOWN` が効くのは 2 箇所だけ:`~/.claude`
の設定を借用するときのホワイトリスト(`env.py:72`)と、`-v` 起動時に `describe()` が表示するフィールドの範囲(`env.py:205`)だ。

## 認証情報の探索優先順位 {#凭证查找优先级}

`load_dotenv()` にパスを渡さない場合、以下の順序で**存在するすべての**ファイルを順に読み込む
(`env.py:45-53`、`:78-112`):

1. **プロセス環境変数** —— つねに最優先。どの `.env` も export 済みの値を上書きできない。(`env.py:91`)
2. **`$FLOWER_ENV` が指すファイル** —— 設定したときだけこの項がある。(`env.py:48-49`)
3. **`$PWD/.env`** —— カレントワーキングディレクトリ。`cd` したプロジェクトのものを近い順に読む。(`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** —— 1 人 1 つのグローバルな位置。`flower setup` が書くのはこれだ。(`env.py:51`、`:39-42`)
5. **ソースリポジトリのルートの `.env`** —— `flower/core/env.py` から 3 階層上。ソースから走らせたときだけ存在する。pip / pipx / uv で入れた flower は site-packages の中にあるので、この項はない。(`env.py:52`)
6. **`~/.claude/settings.json`、続いて `~/.claude/settings.local.json` の `env` ブロック** —— 最後のフォールバックで、**9 つの認証情報キーだけを取る**。(`env.py:56-75`、`:109-111`)

**どのファイルが勝つか**:3(プロジェクトの `.env`)が 4(グローバルの `.env`)に勝ち、4 が 5(リポジトリルートの `.env`)に勝ち、
この 3 つはいずれも 6(Claude Code の設定)に勝つ。そしてすべてが 1(プロセス環境)には勝てない。

実装は「**すでに値のあるキーは上書きしない**」だ(`env.py:90-93`):前に並ぶものが先にキーを占め、後ろのものは空きを埋めるだけ。
したがって優先順位は**キー単位であってファイル単位ではない** —— プロジェクトの `.env` に `ANTHROPIC_BASE_URL` しか書かなくても、
token はグローバルのほうから来てよい。同名キーは最初に現れた値で決まる。

6 は**自動探索のときだけ**有効になる。パスを明示した場合(`load_dotenv("/path/to/.env")`)はそのファイル 1 つだけを読み、
どのフォールバックも通らない(`env.py:86-87`、`:109`)。

### 6:Claude Code の token を借りる {#借用}

`~/.claude/settings.json` と `~/.claude/settings.local.json` を順に読み、`data["env"]` という dict を取り、
その中から次の 9 つのキーを拾う(`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

ファイルが存在しない、読めない、あるいは正当な JSON でない(`OSError` / `ValueError`)場合は、空の dict を返して先へ進む ——
**フォールバックの失敗がこのランを道連れにしてはならない**(`env.py:62-63`、`:66-69`)。

コード上の立場はこうだ:借りるのは「token をどこから探すか」だけで、settings.json の他の一切(権限ルール、hook、
モデル設定)は引き継がない。だから `setting_sources=[]` のポータビリティの約束に反しない(`env.py:17-19`、`:59-61`)。
`install.sh:77` はこれを機能として宣伝している:ローカルで Claude Code を設定済みの人は、設定画面すら見ないで済む。

!!! warning "プロダクト内のエラー文言は実際の挙動と逆になっている"
    認証情報がまったく見つからないとき、flower が表示するエラーの最終行はこうだ:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`、当該の一文は `:192`;同じ言い回しは `.env.example:2`、`env.py:3-4`、
    `agent.py:10-12` にも出てくる。)**コードが正だ:読んでいる。** `env.py:56-75` と `:109-111` は明確にその 2 ファイルを読みに行くし、
    `install.sh:77` はこれをセールスポイントにしている。あの文言は現状ミスリーディングだ ——
    Claude Code を設定済みのマシンでは、あなたの token はおそらくそこから来ている。

## `.env` のパース規則 {#env-解析}

パース規則は暗記できるほど短い(`env.py:95-107`、13 行):行ごとに `strip` し、空行、`#` で始まる行、
`=` を含まない行をスキップ。残りは**最初の** `=` で key と value に切り、両側をそれぞれ `strip` し、value にはさらに
`.strip("'\"")` をかける —— 先頭と末尾のシングル/ダブルクォートは一律で剥がされ、**対になっている必要はない**。

**受け付ける書き方**:

| 書き方 | 結果 |
|---|---|
| `KEY=VALUE` | 正常 |
| `KEY = VALUE` | 正常 —— 等号の両側の空白は strip される |
| `KEY="VALUE"` / `KEY='VALUE'` | 正常 —— 先頭末尾のクォートが剥がされる |
| `KEY=a=b` | value は `a=b` —— 最初の `=` で切るので、以降の等号は値の中にそのまま残る |
| `# コメント` | 行ごとスキップ |
| 空行 | スキップ |

**受け付けない書き方**。書いてもエラーにはならず、黙って想定外の値になるだけだ:

| 書き方 | 実際の結果 |
|---|---|
| `export KEY=VALUE` | key が `export KEY` になり、`KEY` 自体には値が入らない |
| `KEY=value # 説明` | value は `value # 説明` —— 行末コメントは剥がされない |
| `KEY=$OTHER` | リテラルの `$OTHER`。変数展開はしない |
| 複数行の値(クォートで行をまたぐ) | 行単位で処理され、2 行目は `=` を含まないので行ごとスキップされる |

**空値はキーを占有する**。優先度の高いファイルに `ANTHROPIC_AUTH_TOKEN=` があると、`take()` は
`os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` を実行し、後続のファイルは「キーがすでに存在する」ため埋められない
(`env.py:90-93`)。そして `check_credentials()` が見るのは真偽値なので、空文字列は未設定と同じ扱いになる(`env.py:186`)。
**結果として、認証情報もなければフォールバックも得られない。** あるキーが不要なら行ごと削除すること。空のまま残さない。

## ポータビリティの代価 {#可移植性}

`build_options()` の中のあの 1 行がすべての仕掛けだ(`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` は `Runtime` のデフォルト値で、**コマンドラインにこれを切るスイッチはない** —— 切るには Python API で
`Runtime(portable=False)` と書くしかなく、そうすると `["project"]` になり、プロジェクトの `.claude/` を読むようになる。

### 遮断されるもの {#被隔绝的东西}

| 遮断されるもの | 帰結 |
|---|---|
| ホストマシンの `~/.claude/` の設定 | そこにある権限ルール、hook、モデル設定は一切効かない。**認証情報だけが例外**で、[借用](#借用)を参照 |
| プロジェクトの `.claude/` | 同上。`portable=False` のときだけ読む |

ドメイン能力はこの経路を通らない —— リポジトリとともに配布され、`plugins=[{"type": "local", "path": PLUGIN_DIR}]` でロードされる
(`agent.py:26`、`:210-212`)。[デプロイ](deploy.md)を参照。ドメイン指示のほうは Claude Code のネイティブなシステム
プロンプトの後ろに**アペンド**されるもので、置き換えではない(`agent.py:198-202`)。だから専門化は汎用能力を失うことと引き換えにならない。

### 別のマシンに移すとき何を持っていくか {#换台机器要带什么}

- **認証情報:ファイル 1 つ**。`~/.config/flower/.env` をコピーするか、新しいマシンで設定し直す。
  持っていかなければ何も動かない —— 自動的に継承されるものは何もない。
- **継続の状態:ディレクトリまるごと**。`runs/`(セッション DB、マニフェスト、リネージ)と `.flower/`(ワークベンチ)。
- **ただしパスは一致していること**。`lineage.json` にはワークスペースの絶対パスが保存されていて、一致しなければ無いものとして扱われ、黙って新しいセッションに戻る。
  **エラーにはならない**(`lineage.py:65-66`)。理由は、SDK の `project_key` がワークスペースのパスから導かれるからだ
  (`/`、`_`、`.` をすべて `-` に置換、`runtime.py:40-41`)。ディレクトリの位置が変われば、古い `session_id` は引けなくなる。

## ディスクレイアウト {#磁盘布局}

flower を 1 回ランすると 2 本のツリーが書かれる:`<run_dir>/` に会計とセッション、`<workspace>/.flower/` に[ワークベンチ](glossary.md#工作台)。
どちらもデフォルトではカレントディレクトリの下だが、**基準が違う**。

!!! warning "`runs/` はカレントディレクトリに従い、`-w` には従わない"
    `-r/--run-dir` のデフォルトは `"runs"` で、`Runtime` がそれに対して行うのは `Path(run_dir).resolve()`
    (`runtime.py:93-94`)—— つまり**カレントワーキングディレクトリ**からの相対であって、`-w` で指定したワークスペースからの相対ではない。
    `~` で `flower -w /path/to/proj` を走らせると、セッション DB は `~/runs/` に落ち、プロジェクトの中には入らない。

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
| `runs/sessions.db` | 全量の transcript。書くのは `PruningSessionStore` で、3 層のポリシーは[後述](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | JSON 配列で、**プロセスをまたいで累積する**[ランマニフェスト](glossary.md#运行清单)。フィールドは下表 | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`。まず `.tmp` に書いてから `replace`、アトミックに置き換える | `lineage.py:31`、`:87-97` |
| `runs/aside/` | [オラクル](glossary.md#旁路顾问)用の独立した Runtime。**コストとリネージはメインのマニフェストに混ざらない** | `cli.py:741-743` |
| `runs/workbench/` | `Runtime(workbench=True)` のときのデフォルトのワークベンチ位置で、ワークスペースの外にある。`go` 経路では使わない | `runtime.py:148-151` |

`manifest.json` の各行は `asdict(StepResult)` に 2 つのパッチを足したものだ(`runtime.py:44-71`、`:579-582`):

| フィールド | 型 | 意味 |
|---|---|---|
| `step` | `str` | ステップ名。4 つの形態:`<名>`、`<名>#round<N>`(差し戻しでやり直し)、`<名>#retry<N>`(通常のリトライ)、`<名>·判定#<N>`([ジャッジ](glossary.md#判定者)) |
| `session_id` | `str \| None` | このステップで最後に生きていた[セッション](glossary.md#会话) |
| `ok` | `bool` | 成功したかどうか |
| `cost_usd` | `float` | このステップでいくらかかったか |
| `num_turns` | `int` | 何ターン回ったか |
| `text` | `str` | このステップの最終的な返答 |
| `error` | `str \| None` | 失敗理由。SIGHUP / SIGTERM で殺された場合は `killed-by-signal`(`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch 秒 |
| `attempts` | `int` | 実際の試行回数。`>1` ならリトライしている |
| `errors` | `list[str]` | これまでの失敗理由。**ここにしかなく、モデルからは見えない** |
| `resumed` | `bool` | resume で中断地点から継いだのか、最初からやり直したのか |
| `retired` | `list[str]` | このステップの[ハンドオフ](glossary.md#换代)で焼き捨てた session_id を順番に |
| `context` | `int` | 最後のターンで[メインスレッド](glossary.md#主线程)が実際に見たコンテキストの規模 |
| `duration_s` | `float` | 手で補ったもの —— `@property` なので `asdict()` では拾えない |
| `run` | `str` | このプロセスのマーク `YYYYmmdd-HHMMSS-<6 位 hex>`。**インスタンスごとに必ず一意** |

書き込み方針は**追記であって上書きではない**:落とす前にファイルを読み直し、`run` が自分と等しい行を最新のものに差し替え、
他人の行はそのまま残す(`runtime.py:564-586`)。だから同じディレクトリで複数の flower を並行に走らせても、会計が潰し合うことはない。

`runs/` の中身は純粋なデータで、いつでも sqlite3 や
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)
でオフラインに掘り返せる。

### `<workspace>/.flower/` —— ワークベンチ {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

3 つのサブディレクトリとインデックスは `Workbench` が作る(`workbench.py:73-92`)。`INDEX.md` はセッション単位の
`system_prompt.append` に載るので、**subagent には継承されない** —— だから「長い成果物は `artifacts/` に書く」という決まりは
[コーディネーター](glossary.md#协调者)が[タスクブリーフ](glossary.md#任务书)の中で伝え直すしかない。それが唯一の経路だ。

`go` 経路では `notes/` の下に次のものが必ず生成される:

| ファイル | 内容 | 出典 |
|---|---|---|
| `notes/需求.md` | 凍結された[ブリーフ](glossary.md#需求确认书)。4 セクション:目標 / 受け入れ基準 / 境界 / 未知と仮定 | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | 凍結された 2 セクション:目標 / 判定リスト | `workflow/goal.py:124` |
| `notes/问答记录.md` | すべての問答の追記記録。「人が自発的に言った」インボックスの項目も含む。**コンテキストには入らず、記録として残すだけ** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | [ハンドオフ文書](glossary.md#交接书)。前の世代は `notes/archive/交接/<步骤名>-<时间戳>.md` に収める | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `--new` / `/new` でアーカイブされる `lineage.json` + `需求.md` + `目标.md`(**移動であって削除ではない**) | `lineage.py:100-117` |

**`--isolate` のときワークベンチはリポジトリの外へ移る**:`<workspace の親ディレクトリ>/.flower-<workspace 名>/`
(`starter.py:47-55`)。worktree は agent ごとのプライベートなコピーで、ワークベンチは agent をまたぐ共有層だ。
共有するものをプライベートな囲いの中に置くわけにはいかない。このときモデルに渡すパスは絶対パスになる(`workbench.py:69-71`、`:142-145`)。

**`spill/` には書き手が 2 人いて、落とし先のアルゴリズムが違う**:

| 誰が書くか | いつ | どこへ書くか | 閾値 |
|---|---|---|---|
| `spill_guard`(`PostToolUse` hook) | ツール結果がモデルに入る**前** | `<ワークベンチ root>/spill/`(`guard.py:130`) | `spill_threshold`、デフォルト 4000 文字 |
| `TrimPolicy`(`load` 時) | resume 前に履歴を再生するとき | `<workspace>/.flower/spill/` —— ワークスペースからの相対の固定文字列(`trim.py:49`、`:303`) | `min_chars`、デフォルト 2000 文字 |

デフォルトのレイアウトではこれは同じディレクトリだ。しかしワークベンチが移動させられたとき(`-W` で `runs/workbench/` に落ちる、あるいは `--isolate`
でリポジトリの外に落ちる)には両者は分かれる —— `TrimPolicy` のほうはつねにワークスペースの中にある。agent の `Read`
が届かなければならないからだ。

`spill_guard` が差し替えるのは 1 行ではなく、1 行のポインタと**先頭 400 文字**だ(`guard.py:132-140`)。
スピルしたファイル自体を読む呼び出しは通される。そうでなければ「全文が要るなら Read で読め」が空文句になる —— 読み戻したものがまた閾値を超え、またスピルされ、
無限ループになる(`guard.py:155-170`)。

### `sessions.db` のテーブル構造 {#sessions-db}

テーブルは 3 つ、CREATE 文は `stores/sqlite.py:27-51`:

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
| `entries` | transcript の 1 エントリ。`payload` は生の JSON | `uid` はエントリの `uuid` そのもので、**冪等キー**として使う:失敗したバッチは 3 回までリトライされ、再生で重複行が出てはいけない。`uuid` を持たないエントリ(タイトル、タグ、モードマーカー)は重複排除しないので、ユニークインデックスに `WHERE uid IS NOT NULL` が付いている |
| `meta` | 1 セッションのカーソル | `next_seq` は次の連番、`mtime` はミリ秒のタイムスタンプで**厳密に単調**(`sqlite.py:72-79`)—— `list_sessions` と summary はこの時計を共有していて、単調でないと SDK の新旧判定が誤った高速パスに入る |
| `summaries` | 1 メインスレッド分のサマリ sidecar | **メインの transcript だけが対象**で、subagent のものは数えない(`sqlite.py:122-123`) |

`store_key` の構成(`sqlite.py:54-58`):`<project_key>/<session_id>`、subagent はさらに
`subpath` が続く。`project_key` は SDK がワークスペースのパスから導く —— `/`、`_`、`.` をすべて `-` に置換する。

実サンプルを 1 つ見てみる([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

このサンプルは `entries` が 956 件、`meta` が 10 件、`summaries` が 4 件 —— 10 件のセッションのうち 4 件がメインの transcript、
6 件が subagent のもので、`summaries` はちょうどメインの transcript の数と一致する。

## セッションストアの 3 層 {#会话存储}

!!! note "3 層は継承チェーンであって、選べる組み合わせではない"
    `PruningSessionStore` は `TrimmingSessionStore` を継承し、それは `SqliteSessionStore` を継承する。
    `Runtime` は**つねに**最も外側のものを構築し(`runtime.py:109-112`)、構築パラメータにバックエンドを差し替える入口はない。
    「ある層を切る」方法は、その層のポリシーオブジェクトの `enabled` を `False` にすることであって、クラスを差し替えることではない。

`append`(書き)はつねに全量をそのまま落とし、一文字も変えない。3 層が影響するのは `load`(モデルに読み戻して食わせるほう)だけだ。
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
| 2 | `TrimmingSessionStore` | 大きいツール結果の本文、期限切れのエフェメラルコマンドの結果 | サイズ + 鮮度 |
| 3 | `PruningSessionStore` | 切断の残骸、古い拒否された呼び出し | エラーかどうか |

第 2 層が[トリム](glossary.md#裁剪)、第 3 層が[プルーン](glossary.md#剪除)だ ——
**トリムはサイズと価値で捨て、プルーンは「エラーかどうか」で捨てる**。混同しないこと。完全なシグネチャは [Python API](api.md) を参照。

### `SqliteSessionStore` —— 土台 {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

外部依存ゼロの SQLite 実装。Postgres / S3 / Redis に差し替えたければ、同じプロトコルを実装すればよい。SDK には整合性テスト
スイート `claude_agent_sdk.testing.session_store_conformance` が付属していて、そのまま検証できる(`sqlite.py:1-8`)。

プロトコルのメソッド以外に、flower 自身が使う**同期**クエリが 3 つある:

| メソッド | 戻り値 | 用途 |
|---|---|---|
| `projects()` | `list[str]` | DB に実在する `project_key`。SDK はこれを cwd から導くので、クエリの前にこれで確認する。推測しない |
| `has_session(project_key, session_id)` | `bool` | `meta` の 1 行を見るだけで、payload は読まない。[継続](glossary.md#接续)を始める前にまず確認する —— 存在しないセッションを resume すると、子プロセスが立ち上がってから初めて落ちる。そのときにはもう金も時間も使っている |
| `last_context(project_key, session_id, scan=60)` | `int` | このセッションの最後のターンがどれだけのコンテキストを見ていたか。末尾から 60 件だけ逆順にスキャンする。`input_tokens` と 2 つの `cache_*` をすべて数える —— 前者だけ見ると、キャッシュヒット時にほぼ 0 になり、大幅に過小評価する |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

直交する 2 つのルール。`TrimPolicy` は**サイズ**を見る:

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 直近 N 件の `tool_result` は原文を残す —— 今まさに使っているコンテキストは切ってはいけない |
| `min_chars` | `int` | `2000` | これより短ければ切らない。ポインタに置き換えるほうがかえって token を食う |
| `spill_dirname` | `str` | `".flower/spill"` | アーカイブ先ディレクトリで、**workspace からの相対**。ワークスペース内でなければならない。さもないと agent の `Read` が届かない |
| `enabled` | `bool` | `True` | `Runtime(trim=False)`(デフォルト)のときは `False` |

切られた本文は `<sha256 前 16 位>.txt` として書かれ、元の位置は
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` に置き換わる(`trim.py:54-57`、`:308-317`)。

`EphemeralPolicy` は**鮮度**を見る:`git status`、`ls`、`ps` の類の結果は短く、サイズで見ればいつまでも切られる番が来ない。
だがその正しさは時間とともに劣化する —— 20 ターン前の `git status` は「役に立たない」のではなく、**誤誘導する**。

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(ephemeral=…)` から変換される。**デフォルト有効** |
| `keep_recent` | `int` | `6` | 直近 N 件は原文を残す。`TrimPolicy` の 20 よりずっと小さい —— この種のものの「直近」の窓はもともと短い |
| `max_chars` | `int` | `2000` | これを超えたら `TrimPolicy` に渡してスピル・アーカイブさせ、この経路は通らない |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | 置換文言 |

作用するのは **Bash** ツールの結果だけで、しかもコマンドが `EPHEMERAL_CMD` にマッチする必要がある。`Read` は対象外だ:ファイルの内容は
時間の経過で誤誘導するほど歪まないし、それはモデルの推論の根拠そのものかもしれない(`trim.py:153-160`)。期限切れの内容は
**スピルしない** —— 期限切れの `git status` をアーカイブしても意味がない。もう一度走らせれば手に入る。

判定関数は `is_ephemeral(cmd)` で、それは**同時にコーディネーターに返す権限リストでもある**:`delegate_guard(allow_glance=True)`
が使っているのは同じ関数だ(`trim.py:63-68`、`:128-150`)。この 2 つの集合はつねに等しくなければならない ——
通したのに切らなければ、期限切れの `git status` が永久にコンテキストを占める。切ったのに通さなければ、コーディネーターは `ls` 1 本のために
subagent を出し、4.3k の起動コストを数十文字と交換する。ホワイトリストにコマンドを 1 つ足すことは、この 2 つを同時に言うことに等しい。

**どれをいつ使うか**:

- 切断の残骸をコンテキストに入れたくないだけ → 何もしなくていい。`Runtime` はデフォルトで `PruningSessionStore` だ。
  `trim=False` は大きい結果を切らないだけで、プルーンは行われる。
- 長時間走り、ツール出力が大きい → `trim=True`。`go` 経路の CLI ではデフォルトで有効になっていて、`--no-trim` で逆に切る。
- [コーディネーター](glossary.md#协调者)で `glance=True` にした → `ephemeral` は有効のままにしておくこと。理由は前の段落のとおり。

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
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | 前項の置換文言 |
| `heal_orphans` | `bool` | `True` | 「`tool_use` はあるが `tool_result` がない」孤児の呼び出しに、合成した結果を**補う** |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | 補われる `tool_result` の本文 |
| `keep_denials` | `int` | `1` | permission hook に拒否された直近 N 回のツール呼び出しを残し、それより古いものは**呼び出しと結果をまとめて**取り除く |

`keep_denials` はこの層に透過的に渡される唯一の `Runtime` 構築パラメータだ(`Runtime(keep_denials=N)`)。
デフォルトが 0 ではなく 1 である理由:最新の拒否は有効なシグナルで、モデルが同じターンの中で遮断された同じコマンドを繰り返し試すのを防げる。
**大きくするな** —— 拒否された呼び出しは一度も実行されておらず、結果には何の情報もない。実測で 1 件あたり 273 文字を占め
(93 文字の拒否文言と 180 文字の死んだコマンド原文)、しかも**誤誘導する**:実測では、コーディネーターが「Bash を直接使うな」を数件読んだ後、
通されるはずの `git status` すら試さなくなり、「Bash が制限されているので、agent を出して見に行かせる」と言い出した(`prune.py:135-148`)。

`heal_orphans` が治すのは**中断のあと resume が毎回 400 になる**問題だ:中断はメッセージ境界で切れるので、そのとき飛んでいた `tool_use`
の後ろに `tool_result` がまったく無いことがある。だが API は両者が対であることを要求する。この壊れた履歴は transcript に残ったまま勝手には消えないので、
以降のあらゆる resume がそれに弾かれる。補い方は、孤児を含む assistant の直後に `user` エントリを 1 件挿入し、
その中でそのエントリのすべての孤児の結果を一度に揃え、もともとその assistant を指していた `parentUuid` を挿入したエントリに向け直す
(`prune.py:95-147`)。**補うが消さない**:孤児を消すと親子チェーンを繋ぎ直す必要があり、同じ assistant の中に正常なブロック、
テキスト、thinking が残っている可能性があって、巻き添えにしやすい(`prune.py:195-204`)。

構造上のレッドラインが 3 つある。破ると API が即エラーを返す:

1. **`tool_result` ブロック自体は残さなければならない**。変えてよいのは `content` だけ。1 つ欠ければ "Missing Tool Result Block" だ
   (`trim.py:20-22`;`prune.py:79-92`)。
2. **`isCompactSummary` / `isMeta` のエントリには触ってはいけない** —— それは compact で潰された履歴の唯一の存在形式だ
   (`trim.py:179-181`)。
3. **1 件取り除いたら、その子を親に繋ぎ直さなければならない**。transcript は `parentUuid` の単方向チェーンで、harness は葉から
   遡って辿る。どこかでチェーンが切れれば、そこから先の履歴はすべて失われる(`prune.py:95-122`)。だから `relink()` には取り除く対象を**含む**
   完全なリストを渡し、フィルタはその中で行わせる。

**SQLite の中の原文は一文字も変えない** —— 3 層が影響するのは「モデルに戻すほう」だけだ(`trim.py:18`;`prune.py:8`)。

## ネットワーク断のレジリエンス {#韧性}

long-horizon な workflow は一度走れば数時間で、ネットワークは必ず一度は切れる。デフォルトの挙動はかなりひどい:切れた瞬間に harness は transcript
に合成の assistant メッセージ(`model="<synthetic>"`、`isApiErrorMessage=true`)を差し込む。本文は
`API Error: Can't reach the API server …` だ。それがセッションの葉になり、以降の resume では「モデルが直前に言ったこと」として
食わされ、モデルは自分がネットワーク障害について議論していると思い込む。さらに `StepResult.text` にも混ざり、workflow を伝って次のステップの
prompt に渡る(`resilience.py:1-22`)。

[レジリエンス](glossary.md#韧性)のこの層は 3 つのことをする。どれも欠かせない:プローブ、やり直しではなく続きから走る、エラーをコンテキストに入れない。

### `Resilience` のパラメータ {#resilience}

| パラメータ | 型 | デフォルト | 意味 |
|---|---|---|---|
| `enabled` | `bool` | `True` | `Runtime(resilience=…)` から変換される |
| `max_attempts` | `int` | `6` | 1 つの[ステップ](glossary.md#步骤)で最大何回試すか。**初回を含む** |
| `base_delay` | `float` | `4.0` | 指数バックオフの起点、秒 |
| `max_delay` | `float` | `120.0` | バックオフの上限、秒 |
| `probe_timeout` | `float` | `5.0` | プローブ 1 回のタイムアウト、秒 |
| `probe_interval` | `float` | `15.0` | ネットワーク断のとき何秒ごとにプローブするか |
| `max_offline_wait` | `float` | `3600.0` | ネットワーク断で最大どれだけ待つか。デフォルト 1 時間 —— これより長いのはたいてい揺らぎではなく、本当に何かが起きている |
| `retry_unknown` | `bool` | `True` | 分類できないエラーもリトライする。未知のエラーの多くは一過性で、致命的なものはすでに個別に弾いてある |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | 続きから走るときモデルに言う言葉 |

バックオフの式(`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

つまり `±25%` のジッタで、ネットワークが復旧した瞬間に大量のプロセスが一斉に殺到するのを避ける。デフォルト値では:1 回目のバックオフは 4 秒(実際は 3~5)、
2 回目は 8 秒(6~10)、5 回目からは 120 秒で頭打ち(90~150)。

### プローブの方針 {#探针}

- **プローブするのは `ANTHROPIC_BASE_URL` の host:port** であって、`api.anthropic.com` ではない(`resilience.py:67-72`)。
  自前のゲートウェイを使っているとき、後者が通ることは前者が通ることを何も示さない。
- **やるのは DNS と TCP ハンドシェイクだけ**:`getaddrinfo` してから `connect_tcp` して即座に閉じる。HTTP は送らず、
  認証情報も付けず、金もかからない(`resilience.py:75-85`)。プローブは無料でなければならない。そうでなければ「断のとき 15 秒ごとにプローブする」
  こと自体が障害になる。
- どんな失敗も到達不能とみなす —— DNS が死んだのか TCP が拒否されたのかは区別しない。
- `wait_online()` はそこでぶら下がって待つ:通れば `True` を返し、`max_offline_wait` を待ち切ったら `False` を返す。
  最初に到達不能になったとき `<host>:<port> 不可达,等待恢复(最多 60 分钟)` と 1 行通知し、復旧したらもう 1 行
  `<host>:<port> 恢复,继续` と通知する。**その間は画面を流さない**(`resilience.py:126-140`)。

走り始める前の認証情報プローブは別物だ:こちらは実際に `POST <BASE_URL>/v1/messages` を 1 回叩き、`max_tokens=16`、
デフォルトのタイムアウトは 20 秒(`env.py:126-181`)。`max_tokens` を **1 にするな** —— 実測では思考連鎖を強制されるモデルは思考すら
入りきらず、サーバ側が 30 秒もがいてから返ってきた。16 にすれば 3.6 秒で済む(`env.py:120-123`)。

### エラーの分類 {#错误分类}

`classify(text)` は 3 種類のいずれかを返す。**先に致命かどうかを判定する**:401 のようなテキストにはしばしば "connection" のような語も含まれていて、
順序を逆にすると永久に待つことになる(`resilience.py:53-64`)。

| 分類 | 何にマッチするか(正規表現は `resilience.py:37-50`) | 挙動 |
|---|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` | 即座に停止し、リトライしない。何回リトライしても結果は同じで、しかも毎回金がかかる |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`timeout`、`service unavailable` | ネットワークが戻るのを待ってから resume で続きを走る |
| `unknown` | どれにもマッチしない | `retry_unknown=True`(デフォルト)ならリトライする |

リトライ可能かどうかを区別することがこの層の核心だ:**ネットワークの揺らぎは待つべきで、認証情報の誤りは即座に止まるべきだ** ——
断のとき待ち続けるのは正しいが、key を書き間違えて待ち続けるのはただ時間を燃やしているだけだ。

### 何がコンテキストの外に締め出されるか {#错误不进上下文}

1. **合成エラーメッセージ**。`PruningSessionStore` が `load` のときに 1 件まるごと取り除き、`parentUuid` を繋ぎ直す
   (`prune.py:27-32`、`:191-195`)。**SQLite にはそのまま残る**。ただ戻さないだけだ。
2. **イベントストリームではそれは `kind="error"` であって `"text"` ではない**。だから `StepResult.text` に入らず、
   workflow を伝って次のステップの prompt に渡ることもない(`resilience.py:17-18`)。
3. **`resume_prompt` は意図的にエラーの詳細を一切含まない**。モデルが知る必要があるのは「中断された、続きをやれ」であって、
   `ENOTFOUND` なのか `503` なのかではない。**それはログに属し、コンテキストには属さない**(`resilience.py:112-113`)。
   ログは `manifest.json` の `errors` フィールドを見ればいい。

やり直しではなく続きから走る:失敗が起きた時点で `session_id` はすでに得られているので、resume で中断地点から継ぎ、それまでのコストを無駄にしない。

## 関連 {#相关}

- [コマンドライン](cli.md) —— 各スイッチがこのページの設定にどう対応するか。
- [Python API](api.md) —— `Runtime`、3 つの store、`Resilience` の完全なシグネチャ。
- [デプロイ](deploy.md) —— コンテナで走らせる、plugin でドメイン能力を配布する。
- [用語集](glossary.md) —— このページで使ったすべての語の正確な意味。
