# インストール

flower のインストールに必要なのは Python ≥ 3.10 だけ。ランタイム依存は `claude-agent-sdk` の 1 つだけで、リクエストを送るネイティブバイナリはその wheel の中に入っている。つまり **Node も Claude Code CLI もインストール不要**。このページではゼロから一通り: ワンライナーでのインストール、ソースからのインストール、最初の認証情報の設定、そして「本当に入った」ことを証明できるコマンド 1 本。通ったら [クイックスタート](quickstart.md)へ。

## 始める前に: Python の確認

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

`True 3.13.7` のような出力なら十分。`False` が出る、あるいは `python3` そのものが無い場合は、先に入れること(`brew install python` / `apt install python3`)。でないとインストールスクリプトはその場で終了する。

| 必要 | 不要 |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`;`install.sh:22-31` でも自己チェックする) | Node.js |
| API エンドポイントへのネットワーク | Claude Code CLI |
| API key またはゲートウェイ token 1 つ(インストール後に渡せばよい) | ホストの `~/.claude/` の設定(認証情報だけは例外、下記参照) |

パッケージ名は `flower`、バージョン `0.1.0`、唯一のランタイム依存は `claude-agent-sdk>=0.2.152`(`pyproject.toml:2-6`)。`mkdocs-material` は CI でドキュメントサイトを建てるときだけ使うもので、flower の実行には要らない。

## ワンライナーでインストール

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

終わるとターミナルはこうなる(色は省略):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

肝心なのは `== 装好了 <絶対パス>` の行 —— これはスクリプト自身が `command -v flower` を 1 回走らせた結果(`install.sh:60-61`)。パスが出るということは、`flower` が PATH 上にあるということ。

### インストーラが実際にやっていること

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) がやるのは 3 つだけ: Python のツールインストーラを 1 つ選ぶ、GitHub から入れる、次の一歩を伝える。**認証情報には一文字も触れない**(`install.sh:7-8`)。インストール元は `git+https://github.com/ChenyuHeee/flower.git` に固定(`install.sh:11`)。

インストーラは順に試し、最初に成功したところで止まる(`install.sh:33-57`):

| 順序 | 条件 | 実際のコマンド | 実行ファイルの置き場所 |
|---|---|---|---|
| 1 | `uv` が PATH 上にある | `uv tool install --force <REPO>` | uv の tool bin ディレクトリ、通常は `~/.local/bin/flower` |
| 2 | `uv` は無いが `pipx` がある | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | どちらも無い | まず `curl -LsSf https://astral.sh/uv/install.sh \| sh` で uv を入れ、入ったら 1 に戻る | 1 と同じ |
| 4 | 3 でも uv が入らなかった | `python3 -m pip install --user --upgrade <REPO>` | ユーザースクリプトディレクトリ —— **macOS では `~/.local/bin` ではない** |

4 通りとも入るのは同じ console script: `flower = "flower.cli:main"`(`pyproject.toml:12`)。インストール後は `python -m flower.cli` で呼んでも同じ(`cli.py:1263-1264`)。

!!! warning "インストールスクリプトの再実行は確認なしで強制上書きする"
    3 つのインストールコマンドはそれぞれ `--force`、`--force`、`--upgrade` を付けている(`install.sh:37`、`:40`、`:54`)。もう一度走らせれば既存のインストールをそのまま潰す —— アップグレードはまさにこうやるのだが、事前に一言聞いてくれるとは思わないこと。

### `flower` コマンドを PATH に載せる

`command -v flower` で見つからないとき、スクリプトは `$HOME/.local/bin` を `~/.zshrc` か `~/.bashrc` に足すよう促す(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` も `pipx install` もここに置くので、この案内はそれらには正しい。**ただし 4 番目の経路(`pip install --user`)ではそうとは限らない** —— この案内のディレクトリはハードコードされており、pip のユーザースクリプトディレクトリはプラットフォーム依存だからだ。macOS では `~/Library/Python/3.13/bin` になる。自分で調べること:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

たとえば `/Users/you/Library/Python/3.13/bin` と出たら、`~/.local/bin` ではなくそのディレクトリを PATH に足し、ターミナルを開き直すか `source` する。

## ソースからインストール

コードを読みたい、フレームワークを改造したい、`tests/` のオフライン検証を走らせたい —— そういうときはソースから:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

終わったら `.venv/bin/flower --help` で usage の数行が出るはず。

venv 内の実行ファイルの shebang は**絶対パス**なので、activate しなくてよい。シンボリックリンクを張ればどのディレクトリからでも使える:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`~/.local/bin` が PATH 上にあれば、どのプロジェクトディレクトリで `flower` と打っても、この venv のインタプリタとこのソースが動く。

ソースからのインストールには認証情報の置き場所がもう 1 つ増える: **リポジトリルートの `.env`**(探索順では 5 番目、[設定 · 認証情報の探索優先順位](../reference/config.md#凭证查找优先级)参照)。開発時は:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN を書く
```

`.env` は既に `.gitignore` 済みで、バージョン管理には入らない。pip / pipx / uv で入れた flower ではこの場所は**使えない** —— site-packages の中にあり、「リポジトリルート」が無いからだ —— なのでその入れ方では下記のグローバル認証情報ファイルを使う。

## 初回実行: 認証情報の設定

`go`、`run`、`once` の 3 つの実行エントリはいずれも冒頭で `ensure_credentials()` を呼ぶ(`cli.py:1013`、`:981`、`:1046`)。関門は 2 つ:

1. **あるかどうか** —— 優先順位に沿って探し、見つからなければその場で聞く。
2. **使えるかどうか** —— 実際に API を 1 回叩く。`max_tokens=16` の最小リクエスト(`env.py:120-123`)で、ほぼ費用はかからない。期限切れの token や書き間違えたゲートウェイアドレスは環境変数を眺めても分からず、探らなければ数分後に爆発することになる。

認証情報が無い場合、初回の `flower` はこの画面で止まる(`cli.py:1179-1209`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

1 問目は必須で、空のままだと赤字で `没给 token,取消。` と出て終了する。2、3 問目はそのまま Enter でよい。公式エンドポイントを使うなら 2 問目は空に。サードパーティゲートウェイならそのルートアドレスを入れる。**`/v1` は付けないこと** —— flower のプローブが叩くのは `<BASE_URL>/v1/messages` だ(`env.py:162`)。

回答後に書き出されるキー(`cli.py:1199-1207`):

| 入力内容 | `.env` に書かれるキー |
|---|---|
| token が `sk-ant-` で始まる | `ANTHROPIC_API_KEY` |
| それ以外の token | `ANTHROPIC_AUTH_TOKEN` |
| ゲートウェイアドレスが空でない | `ANTHROPIC_BASE_URL` |
| モデル名が空でない | `ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL` の **3 つまとめて** |

ファイルの場所は `${XDG_CONFIG_HOME:-~/.config}/flower/.env`(`env.py:39-42`)、**ファイル全体を上書き**し、書き終えたら `chmod 0o600`(`cli.py:1157-1168`)。これが「一度入れればどこでも効く」ファイルで、プロジェクトディレクトリを変えても設定し直す必要はない。各変数の意味は[設定](../reference/config.md#环境变量)を参照。

### このマシンに Claude Code が入っているなら、一問も聞かれないかもしれない

認証情報の探索には**最後のフォールバック**がある: `~/.claude/settings.json` を読み、続いて `~/.claude/settings.local.json` を読み、その `env` ブロックから 9 個の認証情報キーを取る(`env.py:56-75`、`:109-111`)。Claude Code を設定済みの人はそのまま `flower` を走らせれば動き出し、設定画面はそもそも出ない —— `install.sh:77` が宣伝しているのはこの経路だ。

!!! warning "製品内の「flower は ~/.claude/settings.json を読まない」という文言は誤り"
    認証情報がまったく見つからないとき、flower が出すエラーの最終行は
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`、当該行は `:192`)。**コードが正しい: 読んでいる。**
    `env.py:56-75` はその 2 ファイルの `env` ブロックを明示的に読みに行く。ただし取るのは 9 個の認証情報キーだけで、他の設定は一切引き継がない。この文言を見ても、このマシンの Claude Code 設定が無視されていると判断しないこと。完全な連鎖は[設定 · 認証情報の探索優先順位](../reference/config.md#凭证查找优先级)を参照。

### 設定し直したいとき

`flower setup` というサブコマンドは登録されている(`cli.py:1147-1149`)が、`_CMDS` から漏れている(`cli.py:758`)。そのため `flower setup` は `flower go setup` に書き換えられ、"setup" を 1 つの要望として完全なフローで走らせてしまう。**現状、そのサブコマンドに到達できるコマンドラインの書き方は存在しない** —— いくつかのエラーメッセージはいまだにそれを走らせろと言ってくるが。認証情報を変えるには:

```bash
$EDITOR ~/.config/flower/.env
```

あるいはそのファイルの token を消してもう一度 `flower` を走らせる —— 認証情報欠如の関門が改めて聞いてくる(他の場所、たとえば `~/.claude/settings.json` にも無いことが前提)。認証情報が拒否された(HTTP 401 / 403)ときも、その場で同じ画面が出て設定し直せる。チャンスは 1 回だけ(`cli.py:1229-1244`)。

## インストールできたか確認する

2 段階、安い順に。

**第 1 段階 —— コマンドがあるか(無料)**:

```bash
flower --help
```

この数行が出れば console script が入っていて PATH 上にもあるということ:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**第 2 段階 —— 認証情報・エンドポイント・ネイティブバイナリが全部通るか(数セント)**: 一番安い実走は `once` —— 単一 agent、デフォルトでは `Read` / `Glob` / `Grep` の読み取り専用ツール 3 つだけ、[目標看守](../reference/glossary.md#目标看守)なし、[ワークベンチ](../reference/glossary.md#工作台)なし:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` を付けると走り出す**前**に、現在有効な設定を表示する。token は先頭 4 文字だけ(`cli.py:1257-1259`;`env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

この数行でゲートウェイを間違えていないことを確認する。続いて認証情報プローブと実際の実行:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**ステップのヘッダは出ない。** `once` は `_run_once` → `rt.run()` を通り、`_drive` / `Workflow.run` を経由しない。そして `Event("step", …)` は `workflow/base.py:220` でしか発行されない —— だから `== 步骤名 ===== 1/1` のような区切り行は `once` では出ず、`go` / `run` にしか出ない。

**`+ 完成` の行が出れば合格**。これは同時に 3 つを証明する: 認証情報が使えること、エンドポイントに到達できること、`claude-agent-sdk` の wheel に入っているネイティブバイナリがこのマシンで動くこと。`- 验一下凭证…` の下に `! 凭证被拒` や `! 网关地址或模型名不对` が続いたら、下のトラブルシュート表へ。

!!! note "`once` の所要時間と累計コストは 0 と表示される"
    `once` はイベントごとに新しいレンダラを作る(`cli.py:1060`、`:579-581`)ので、`用时` は常に `0:00`、ステータス行の `累计 $` も決して積み上がらない —— **単発のそのコストは本物、時間はそうではない**。

    上の行の `1 轮 · $0.1741` は**出典のある実測値**: 2026-09-06、Linux/arm64 コンテナ内で `cloud.infini-ai.com/maas` 経由に出した実リクエスト(`docker/README.md:24-25`)、つまり Opus 5 + 1M ウィンドウの**1 ラウンドの底値**。自分で上のコマンドを走らせるとリポジトリを一通り読むぶんラウンド数が増え、コストもこの底値より少し高くなる。完全な会計は `runs/manifest.json` にある。[設定 · ディスクレイアウト](../reference/config.md#磁盘布局)参照。

## インストールできないとき

| 症状 | 原因 | どうするか |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | `python3` も `python` も 3.10+ を満たさない(`install.sh:31`) | `brew install python` / `apt install python3` して、スクリプトをもう一度走らせる |
| スクリプトは成功と言うのに `flower: command not found` | PATH 上にないディレクトリに入った | 上の「`flower` コマンドを PATH に載せる」を参照。`pip --user` の経路になった場合、macOS では `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | すべての経路が失敗、たいていは GitHub か PyPI へのネットワーク不通 | 案内どおり手で 1 回走らせて、本当のエラーを見る |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。`(4 行) | 非対話環境(パイプ、CI、`nohup`)で認証情報が無い —— そこでは設定画面は出ずそのまま終了する | 先に本物のターミナルで `flower` を 1 回走らせて設定するか、`~/.config/flower/.env` を直接書く |
| `! 凭证被拒:HTTP 401 …` | token の期限切れか書き間違い | 対話ターミナルならその場で再設定させてくれる。非対話なら終了 |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` かモデル名が違う | BASE_URL はゲートウェイのルートまで、`/v1` は付けない。モデル名はゲートウェイ独自のものを使う |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / タイムアウト / 5xx | **認証情報の問題ではない**。flower は意図的に再設定させず、そのまま走り出して[韌性](../reference/glossary.md#韧性)の層に任せる |
| `! 标准输入不是终端,没人能回答提问` | パイプや CI の中で走っている | `--timeout 0` を付けて自分で判断させ、人を待たせない |
| `flower setup` が「何をしますか」と聞いてくる | `_CMDS` から `setup` が漏れている(`cli.py:758`) | `~/.config/flower/.env` を直接編集する。上の「設定し直したいとき」参照 |

## 次の一歩

- [クイックスタート](quickstart.md) —— プロジェクトディレクトリに入って、最初の実務を通す。
- [設定](../reference/config.md) —— 全環境変数、認証情報の優先順位、`.env` の文法、ディスクに何が残るか。
- [コマンドライン](../reference/cli.md) —— 全サブコマンドとフラグ。
- [デプロイ](../reference/deploy.md) —— コンテナで走らせる、plugin でドメイン能力を配る。
- [用語集](../reference/glossary.md) —— ドキュメント中の各語の正確な意味。
