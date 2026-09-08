# インストール

flower のインストールに必要なのは Python ≥ 3.10 だけ。実行時依存は `claude-agent-sdk` 一つで、
リクエストを送るネイティブバイナリはその wheel の中に入っている。だから **Node も、Claude Code CLI も要らない**。
このページではゼロから一通り: 一行インストール、ソースからのインストール、初回の認証情報設定、
そして「本当に入った」ことを証明できるコマンドまで。通ったら
[クイックスタート](quickstart.md)へ。

## 始める前に: Python の確認 {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

`True 3.13.7` のように出れば十分。`False` が出るか、そもそも `python3` が無いなら先に入れること
(`brew install python` / `apt install python3`)。でないとインストールスクリプトはその場で終了する。

| 要るもの | 要らないもの |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`;`install.sh:22-31` でも自前チェックしている) | Node.js |
| API エンドポイントへのネットワーク | Claude Code CLI |
| API キーまたはゲートウェイ token(入れた後で渡せばいい) | ホスト側 `~/.claude/` の設定(認証情報だけが唯一の例外、後述) |

パッケージ名 `flower`、バージョン `0.1.0`、実行時依存は `claude-agent-sdk>=0.2.152` の一つだけ
(`pyproject.toml:2-6`)。`mkdocs-material` は CI がドキュメントサイトを建てるときにしか使わない。flower を動かすのに必要はない。

## 一行インストール {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

終わると端末はこうなる(色は省略):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

肝心なのは `== 装好了 <絶対パス>` の行 —— これはスクリプト自身が `command -v flower` を一度走らせた結果だ
(`install.sh:60-61`)。パスが出ているなら `flower` は PATH に乗っている。

### インストーラが実際にやること {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) がやるのは三つだけ:
Python 用のツールインストーラを一つ選ぶ、GitHub から入れる、次にやることを表示する。**認証情報には一文字も触れない**(`install.sh:7-8`)。
インストール元は `git+https://github.com/ChenyuHeee/flower.git` に固定(`install.sh:11`)。

インストーラは順に試し、最初に成功したところで止まる(`install.sh:33-57`):

| 順序 | 条件 | 実際のコマンド | 実行ファイルの置き場所 |
|---|---|---|---|
| 1 | `uv` が PATH にある | `uv tool install --force <REPO>` | uv の tool bin ディレクトリ、通常は `~/.local/bin/flower` |
| 2 | `uv` は無いが `pipx` がある | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | どちらも無い | まず `curl -LsSf https://astral.sh/uv/install.sh \| sh` で uv を入れ、入ったら 1 に戻る | 1 と同じ |
| 4 | 3 でも uv が入らなかった | `python3 -m pip install --user --upgrade <REPO>` | ユーザースクリプトディレクトリ —— **macOS では `~/.local/bin` ではない** |

四通りとも入るのは同じ console script:`flower = "flower.cli:main"`(`pyproject.toml:12`)。入れた後は
`python -m flower.cli` で呼んでも同じ(`cli.py:1451-1452`)。

!!! warning "インストールスクリプトを再実行すると確認なしで強制上書きされる"
    三つのインストールコマンドにはそれぞれ `--force`、`--force`、`--upgrade` が付いている(`install.sh:37`、`:40`、`:54`)。
    もう一度走らせれば既存のインストールはそのまま潰される —— アップグレードはまさにこうやるのだが、事前に一言聞いてくれるとは思わないこと。

### `flower` コマンドを PATH に乗せる {#flower-命令怎么上-path}

`command -v flower` で見つからないとき、スクリプトは `$HOME/.local/bin` を `~/.zshrc` か `~/.bashrc` に足すよう促す
(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` も `pipx install` もここに置くので、この案内はそれらには正しい。**ただし 4 番目の経路
(`pip install --user`)では違うことがある** —— あの案内のディレクトリはハードコードだが、pip のユーザースクリプトディレクトリはプラットフォーム依存だ。
macOS では `~/Library/Python/3.13/bin` になる。自分で確かめること:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

出力が例えば `/Users/you/Library/Python/3.13/bin` なら、`~/.local/bin` ではなくそのディレクトリを PATH に足し、
端末を開き直すか `source` する。

## ソースからのインストール {#从源码装}

コードを読みたい、フレームワークを直したい、`tests/` のオフライン検証を回したい —— なら、ソースから入れる:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

終わったら `.venv/bin/flower --help` で usage の数行が出るはず。

venv の実行ファイルの shebang は**絶対パス**なので、activate しなくてよい。シンボリックリンクを張ればどのディレクトリからでも使える:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

`~/.local/bin` が PATH にあれば、どのプロジェクトディレクトリに `cd` して `flower` と打っても、この venv のインタプリタと
このソースが走る。

ソースからのインストールには認証情報の置き場所がもう一つ増える: **リポジトリルートの `.env`**(探索順では 5 番目、
[設定 · 認証情報の探索優先順位](../reference/config.md#凭证查找优先级)参照)。開発中は:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN を記入
```

`.env` は既に `.gitignore` されているのでバージョン管理には入らない。pip / pipx / uv で入れた flower ではこの場所は**使えない** ——
site-packages の中にあり、「リポジトリルート」が無いからだ —— なので、そちらのインストール方法では下記のグローバル認証情報ファイルを使う。

## 自動更新 {#自动更新}

flower はまだ速いペースで動いているので、**pip / pipx / uv で入れたものはデフォルトで自分を更新する**: 三日前の版を入れた人が
報告してくるバグは、とうに直っているかもしれない。双方の時間の無駄だ。これについて「有効にしますか」というスイッチ的な問いは無い ——
デフォルトで有効、切りたければ環境変数を立てる。

やっていること(`update.py:116-129`):

1. `flower` 起動のたびに、**バックグラウンドスレッド**で GitHub の `main` の最新 commit を一度だけ問い合わせる
   (`update.py:70-80`)。メインの流れは一秒も待たない —— これが第一の不変条件。
2. ローカルに入っている commit と違えば、当初のインストール方法に従って更新コマンドを一度走らせる: `uv` があれば
   `uv tool install --force`、`pipx` があれば `pipx install --force`、どちらも無ければ
   `pip install --user --upgrade`(`update.py:83-93`)。
3. **入れ終わっても、今走っているプロセスは差し替えない** —— 新版が使われるのは次に `flower` を走らせたとき
   (`update.py:113`)。走行中に差し替わるのは最も追いにくい類の故障だ。
4. スロットリング: 24 時間に最大 1 回だけ問い合わせ、タイムスタンプは `~/.config/flower/.update` に記録する
   (`update.py:32`、`:36-37`、`:124`)。
5. **失敗は一律で沈黙**。ネットワークが無い、GitHub が落ちている、インストールできない —— どれも作業を中断させない(`update.py:79`、`:108-110`)。

**ソース(git)から動かしている場合は影響を受けない。** 更新コマンドの手前でリポジトリに `.git` があるか見て、あれば即座に
`None` を返して何もしない(`update.py:83-87`)—— あなたのワークツリーは `git` の管轄であって、これの管轄ではない。
非対話(stdin が端末でない、たとえばパイプ / CI)でも丸ごとスキップする(`update.py:121`)。

切るには:

```bash
export FLOWER_NO_UPDATE=1
```

空でない値なら何でもよい(`update.py:33`、`:121`)。CI、オフライン環境、旧版の挙動を再現したいときに使う。

## 初回実行: 認証情報の設定 {#第一次跑配凭证}

`go`、`run`、`once` の三つの実行入口はいずれも冒頭で `ensure_credentials()` を呼ぶ(`cli.py:1192`、`:1160`、`:1225`)。関門は二つ:

1. **有るか** —— 優先順位に沿って一巡探し、無ければその場で尋ねる。
2. **使えるか** —— 実際に API を一度叩く。`max_tokens=16` の最小リクエスト(`env.py:120-123`)で、ほとんど費用はかからない。
   期限切れの token や書き間違えたゲートウェイアドレスは環境変数を眺めても分からない。探らなければ数分後に落ちる。

認証情報が無いとき、初めて `flower` を走らせるとこの画面で止まる(`cli.py:1358-1388`):

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

1 問目は必須で、空のままだと赤字で `没给 token,取消。` と出て終了する。2 問目と 3 問目はそのまま Enter でよい。
公式エンドポイントを使うなら 2 問目は空に。サードパーティのゲートウェイならそのルートアドレスを入れる。**`/v1` は付けないこと** ——
flower のプローブが叩くのは `<BASE_URL>/v1/messages` だ(`env.py:162`)。

答え終わって書き出されるキー(`cli.py:1378-1386`):

| 入力したもの | `.env` に書かれるキー |
|---|---|
| token が `sk-ant-` で始まる | `ANTHROPIC_API_KEY` |
| それ以外の token | `ANTHROPIC_AUTH_TOKEN` |
| ゲートウェイアドレスが非空 | `ANTHROPIC_BASE_URL` |
| モデル名が非空 | `ANTHROPIC_MODEL`、`ANTHROPIC_DEFAULT_OPUS_MODEL`、`ANTHROPIC_DEFAULT_SONNET_MODEL` の **三つまとめて** |

ファイルの位置は `${XDG_CONFIG_HOME:-~/.config}/flower/.env`(`env.py:39-42`)、**丸ごと上書き**で書き、
書き終わったら `chmod 0o600`(`cli.py:1336-1347`)。これが「一度入れればどこでも効く」ファイルだ ——
プロジェクトディレクトリを変えても設定し直す必要はない。各変数の意味は[設定](../reference/config.md#环境变量)を参照。

### Claude Code が入っているマシンでは何も聞かれないことがある {#本机装过-claude-code-的话可能一个问题都不问}

認証情報の探索には**最後のフォールバック**がある: `~/.claude/settings.json` を読み、次に `~/.claude/settings.local.json` を読み、
その `env` ブロックから 9 個の認証情報キーを取る(`env.py:56-75`、`:109-111`)。Claude Code を設定済みのマシンなら、
`flower` を走らせるだけで仕事が始まり、設定画面はそもそも出ない —— `install.sh:77` が謳っているのはこれだ。

!!! warning "製品内の「flower は ~/.claude/settings.json を読まない」は誤り"
    認証情報が全く見つからないとき、flower が出力するエラーの最後の行は
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`、その一文は `:192`)。**コードが正しい: 読んでいる。**
    `env.py:56-75` はその二つのファイルの `env` ブロックを明示的に読む。ただし取るのは 9 個の認証情報キーだけで、他の設定は一切引き継がない。
    この文言を見ても、マシンの Claude Code 設定が無視されていると判断しないこと。完全な連鎖は
    [設定 · 認証情報の探索優先順位](../reference/config.md#凭证查找优先级)を見よ。

### 設定をやり直したいとき {#想重新配的时候}

`flower setup` というサブコマンドは登録されている(`cli.py:1326-1328`)が、`_CMDS` から漏れている(`cli.py:937`)。
そのため `flower setup` は `flower go setup` に書き換えられ —— "setup" を一つの要求とみなしてワークフローを丸ごと走らせてしまう。
**現時点でそのサブコマンドに到達できるコマンドラインの書き方は存在しない**。にもかかわらず、いくつかのエラーメッセージはまだそれを走らせろと言う。認証情報を変えるには:

```bash
$EDITOR ~/.config/flower/.env
```

あるいはそのファイルの token を消してもう一度 `flower` を走らせる —— 認証情報が欠けている関門が改めて尋ねてくる(他の場所、たとえば
`~/.claude/settings.json` にも無いことが前提)。認証情報が拒否された(HTTP 401 / 403)ときも、その場で同じ画面が出て設定し直せる。
チャンスは一度だけ(`cli.py:1416-1428`)。

## 入ったことの確認 {#验证装好了没有}

二段階、安いほうから。

**第一段 —— コマンドがあるか(無料)**:

```bash
flower --help
```

この数行が出れば console script が入っていて PATH にも乗っている:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**第二段 —— 認証情報、エンドポイント、ネイティブバイナリまで通っているか(数セント)**: 最も安い実走は `once` ——
単一 agent、デフォルトで `Read` / `Glob` / `Grep` の読み取り専用ツール三つだけ、[ゴールガード](../reference/glossary.md#目标看守)なし、
[ワークベンチ](../reference/glossary.md#工作台)なし:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` は走り出す**前に**現在有効な設定を表示する。token は先頭 4 桁だけ残す(`cli.py:1445-1447`;`env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

この数行でゲートウェイを間違えていないことを確認する。続いて認証情報のプローブと実際の run:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**ステップ見出しは出ない。** `once` は `_run_once` → `rt.run()` を通り、`_drive` / `Workflow.run` を経由しない。
そして `Event("step", …)` は `workflow/base.py:220` でしか発行されない —— なので `== 步骤名 ===== 1/1`
のような区切り行は `once` では現れない。あるのは `go` / `run` だけだ。

**`+ 完成` の行が出れば合格**。それは同時に三つを証明している: 認証情報が使える、エンドポイントに繋がる、
`claude-agent-sdk` の wheel に入っているネイティブバイナリがこのマシンで動く。
`- 验一下凭证…` の下に `! 凭证被拒` や `! 网关地址或模型名不对` が続いたら、下のトラブルシューティング表へ。

!!! note "`once` の所要時間と累計費用は 0 と表示される"
    `once` はイベントごとにレンダラを新規作成する(`cli.py:1239`、`:579-581`)ので、`用时` は常に `0:00`、
    ステータス行の `累计 $` も決して積み上がらない —— **単ステップのその費用は本物、時間は違う**。

    上の行の `1 轮 · $0.1741` は**出所のある実測値**: 2026-09-06 に Linux/arm64 のコンテナ内で、
    `cloud.infini-ai.com/maas` 経由で送った実リクエスト(`docker/README.md:24-25`)、
    つまり Opus 5 + 1M ウィンドウの**1 ラウンドの下限価格**だ。自分で上のコマンドを走らせるとリポジトリを一通り読むので、
    ラウンド数は増え、費用もこの下限より少し高くなる。
    完全な会計は `runs/manifest.json` にある。[設定 · ディスクレイアウト](../reference/config.md#磁盘布局)を参照。

## 入らないとき {#装不上的时候}

| 症状 | 原因 | 対処 |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | `python3` も `python` も 3.10+ を満たさない(`install.sh:31`) | `brew install python` / `apt install python3` の後、スクリプトをもう一度 |
| スクリプトは入ったと言うのに `flower: command not found` | PATH に無いディレクトリに入った | 上の「`flower` コマンドを PATH に乗せる」を参照。`pip --user` の経路に落ちた場合、macOS では `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | 全経路が失敗。たいていは GitHub か PyPI へのネットワークが通っていない | 案内どおり手で一度走らせ、実際のエラーを見る |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。`(4 行) | 非対話環境(パイプ、CI、`nohup`)で認証情報が無い —— そこでは設定画面は出ず、そのまま終了する | 先に本物の端末で一度 `flower` を走らせて設定するか、`~/.config/flower/.env` を直接書く |
| `! 凭证被拒:HTTP 401 …` | token が期限切れか書き間違い | 対話端末ならその場で設定し直させる。非対話なら終了 |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` かモデル名が違う | BASE_URL はゲートウェイのルートまで、`/v1` は付けない。モデル名はゲートウェイ独自のものを使う |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / タイムアウト / 5xx | **認証情報の問題ではない**。flower は意図的に設定し直させず、そのまま走り出して[レジリエンス](../reference/glossary.md#韧性)の層に任せる |
| `! 标准输入不是终端,没人能回答提问` | パイプや CI の中で走らせている | `--timeout 0` を付けて自分で判断させる。人を待たせない |
| `flower setup` を走らせると「何をしますか」と聞かれる | `_CMDS` から `setup` が漏れている(`cli.py:937`) | `~/.config/flower/.env` を直接編集する。上の「設定をやり直したいとき」参照 |

## 次に {#下一步}

- [クイックスタート](quickstart.md) —— プロジェクトディレクトリに入って、最初の実務を一つ通す。
- [設定](../reference/config.md) —— 全環境変数、認証情報の優先順位、`.env` の文法、ディスクに何が残るか。
- [コマンドライン](../reference/cli.md) —— 全サブコマンドとフラグ。
- [デプロイ](../reference/deploy.md) —— コンテナで動かす、plugin でドメイン能力を配る。
- [用語集](../reference/glossary.md) —— ドキュメント中の各語の正確な意味。
