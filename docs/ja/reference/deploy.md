# デプロイと拡張

flower を別の場所へ持っていくときに片づけることは 3 つある。コンテナ(制限のない Bash を囲い込み、
ついでに「CLI から独立している」という主張を検証する)、[plugin](glossary.md#plugin)(ドメイン能力が
リポジトリに付いて回り、ホストに何が入っているかを見ない)、ドキュメントサイト(`main` に push すれば
自動で公開され、`install.sh` は Pages のドメインにぶら下がる)。3 節は互いに独立しているので、必要なところだけ読めばいい。

## 一、コンテナ {#一容器}

### なぜコンテナが要るのか {#为什么要容器}

**一つは囲い込むため。** 実作業をする[ワーカー](glossary.md#执行者)は **制限のない Bash** を持つ ——
flower の Bash ホワイトリスト(`delegate_guard`)は[メインスレッド](glossary.md#主线程)だけを見ており、
送り出した側はテストを走らせられる必要があるので、これは意図的だ。
コンテナにはあなたのプロジェクトディレクトリだけをマウントし、フレームワークのソースはイメージ内の
`/opt/flower` にある。ホストの他の場所は見えない。

**二つめは、これ自体が[ポータブル](glossary.md#可移植)という制約の検証になっているから。** イメージには
Claude Code CLI も Node も入っておらず、あるのは Python と `claude-agent-sdk` だけ ——
リクエストは wheel に同梱されたネイティブバイナリが発行する。
ここで動くなら、「CLI から独立している」は紙の上の話ではない。

実測で確認済み(2026-09-06、macOS 15 / arm64 / colima + docker 28.4.0):

| 検証項目 | 結果 |
|---|---|
| イメージ内に CLI があるか | `claude`、`node`、`npm`、`npx` は **いずれも存在しない** |
| 同梱バイナリ | `\177ELF`(207M) |
| 実リクエスト | `cloud.infini-ai.com/maas` 経由で発行し応答を取得、`$0.1741 / 1 ラウンド`(Opus 5 + 1M ウィンドウの 1 ラウンドの下限がこの値) |
| ファイルの所有者 | コンテナ内から `/work` に書いたファイルはホスト側で `hechenyu:staff`、マッピングは正しい |
| ホストの可視性 | コンテナ内で `ls /Users` → `No such file or directory` |

### イメージに何が入っているか {#镜像里装了什么}

ベースイメージは `python:3.13-slim`、その上に apt で 3 パッケージだけ。どれにも理由がある:

| 入れたもの | なぜ |
|---|---|
| `python:3.13-slim` | 必要なのは Python ≥ 3.10 だけ。Node も claude CLI も入れない |
| `git` | `--isolate` が [subagent](glossary.md#subagent) ごとに worktree を切るため |
| `ca-certificates` | HTTPS ゲートウェイを通るため |
| `libstdc++6` | SDK 同梱のバイナリは Bun でコンパイルされた単一ファイルで、Linux ではこれが要る。slim イメージには入っていない |

フレームワークのソースは `COPY` でイメージに入る。**bind mount ではない** —— したがってコンテナ内の
agent はホストのフレームワークソースに触れない:

| イメージ内パス | 中身 | 由来 |
|---|---|---|
| `/opt/flower` | `pyproject.toml`、`flower/`、`examples/`。ここで `pip install .` を実行 | `COPY` |
| `/work` | 作業ディレクトリ(`WORKDIR`)。実行時にホストの `$PWD` をマウント | `docker run -v` |

エントリポイントは `ENTRYPOINT ["flower"]` で、`CMD` は空 —— 引数なしでコンテナを走らせると対話入力に入る
(何をしたいか聞かれる)。`--help` を出すのではない。こうしておけば、日本語の要望を shell 上でクォートで
くくる必要がなくなる。

### ホストの `.venv` をマウントできない理由 {#为什么不能把宿主的-venv-挂进去}

SDK はプラットフォームごとに wheel を配っており、同梱バイナリはプラットフォーム専用だ:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

マウントしても動かないので、イメージ側で自分で `pip install` するしかない。逆に言えばこれはポータビリティの
証拠でもある:同じ `pyproject.toml` で、プラットフォームが変わればネイティブバイナリが差し替わるだけ、
フレームワークのコードは 1 行も変えない。

### 2 つのスクリプト {#两个脚本}

| スクリプト | 何をするか |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | イメージをビルドする。リポジトリルートに `cd` して `docker build -f docker/Dockerfile -t flower-box .`。`FLOWER_MIRRORS=1`(既定)のときはまず registry ミラーから `python:3.13-slim` を pull して retag し、pip / apt の `--build-arg` を付ける |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | 1 回実行する。認証情報ファイルを確認 → `$PWD` がマウントできるか確認 → TTY の有無を判定 → `docker run` |

`docker/build` のスイッチはすべて環境変数:

| 変数 | 既定値 | 意味 |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | イメージ tag |
| `FLOWER_MIRRORS` | `1` | `0` = ミラーを一切使わず、すべて上流へ |
| `FLOWER_REGISTRY` | `dockerproxy.net` | ここからベースイメージを pull して `python:3.13-slim` に retag し、`FROM` をローカルにヒットさせる |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | `--build-arg PIP_INDEX_URL` に渡す |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | `--build-arg APT_MIRROR` に渡す |

後ろの 3 つは `FLOWER_MIRRORS=1` のときだけ効く —— `FLOWER_MIRRORS=0` の分岐では build-arg をそもそも設定しない。

`docker/flowerbox` が見るのは 2 つ:

| 変数 | 既定値 | 意味 |
|---|---|---|
| `FLOWER_HOME` | スクリプト自身の位置の 1 つ上(= リポジトリルート) | `.env` をどこに探すか。`$FLOWER_HOME/.env` が見つからなければ即 exit 1 |
| `FLOWER_IMAGE` | `flower-box` | どのイメージを走らせるか |

`FLOWER_HOME` はスクリプト自身の位置から導出しており、パスをハードコードしていないので、
リポジトリをどこにクローンしても動く。

### 動かす {#跑起来}

```bash
docker/build                       # 一度やれば十分
cd ~/任意项目目录                   # $HOME 配下である必要がある。下のマウント境界を参照
/path/to/flower/docker/flowerbox   # 引数なし → 何をしたいか聞いてくる。クォート不要
```

pypi.org / Docker Hub へのネットワークが正常なら、ビルドはこう走らせる:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox` の引数は `flower` とまったく同じ —— `"$@"` をそのまま `ENTRYPOINT` の後ろに渡している。
`--clarify-only`、`--asks N`、`--timeout 秒`、`--isolate`、`-v` もそのまま通る。全一覧は[コマンドライン](cli.md)を参照:

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

実際に実行されるのはこの 1 行(`-t` は TTY があるときだけ付く。下記参照):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### マウント境界と永続化 {#挂载边界与持久化}

```text
宿主 $PWD  ──挂载──>  /work       ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

だから `flower/human-test/HT001` のようなリポジトリ内のサブディレクトリで走らせても安全だ:
マウントされるのは `HT001` だけで、フレームワークのソースはマウント範囲に入らない。

| 対象 | 終了後も残るか | なぜ |
|---|---|---|
| ホスト `$PWD` 配下のすべて(`runs/`、[ワークベンチ](glossary.md#工作台) `.flower/` を含む) | 残る | それが `/work` としてマウントされたディレクトリそのものだから |
| コンテナ内の他のパスに書いたもの | 残らない | `--rm`、コンテナ終了と同時に消える |
| 認証情報 | イメージレイヤーに入らない | `--env-file` 経由。`.dockerignore` で `.env` を除外しているので、`COPY . .` でも入らない |

!!! danger "プロジェクトディレクトリは `$HOME` 配下でなければならない。さもないと成果物が黙って失われる"
    **colima は既定で `$HOME` しか VM にマウントしない**(`mount | grep virtiofs` → `mount0 on /Users/<あなた>`)。
    `/tmp` のような場所で走らせると、`-v` は VM 内に**空のディレクトリ**を作り、そこに書いたものはホストからは永久に見えない。
    **しかもエラーにならない** —— 成果物、[ブリーフ](glossary.md#需求确认书)、`runs/` がすべて失われる。一度踏んだ:
    `once` を走らせ切って $0.17 を使ったのに、`runs/` はホスト上にそもそも存在しなかった。

    `flowerbox` は現在この状況をブロックする:`$PWD` が `$HOME` 配下ならそのまま通す。そうでない場合は `$PWD` に
    プローブファイルを書き、もう 1 つコンテナを起こして `test -f /work/<プローブ>` で実測する(追加マウントを設定していれば通る)。
    通らなければ exit 1 し、`colima start --mount '<パス>:w'` を教える。プローブはコンテナを起こすので、先に `docker/build` が必要。

### 認証情報 {#凭证}

`docker run --env-file` 経由で渡し、**イメージレイヤーには入らない**。`flowerbox` が読むのは
`$FLOWER_HOME/.env`、既定ではリポジトリルートの `.env`:

```bash
cp .env.example .env       # token を書く。.env は gitignore 済み
```

注意:`flower setup` が書くのは `~/.config/flower/.env` で、**そのパスを `flowerbox` は見ない**。
すでに `setup` で設定済みで、もう 1 部コピーしたくないなら、`FLOWER_HOME` をそちらへ向ければいい:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

キー名、優先順位、ゲートウェイの書き方は[設定](config.md)を参照。

!!! warning "TTY がないと、質問は `--timeout` まで固まり続ける"
    `flowerbox` は `[ -t 0 ]` のときだけ `-t` を付ける —— `docker run -t` はパイプや CI では
    "the input device is not a TTY" を直接吐く。`-i` は常に必要で、ないと stdin がそもそも入らない。

    質問への回答は標準入力を通る。TTY がないと `input()` は 1 回目で `EOFError` を投げ → 現在の質問は
    「入力が閉じた」として飛ばされ、しかも**回答スレッドがそのまま終了する**。だから 2 問目以降は誰も受け取らず、
    `--timeout`(既定 1800 秒)を丸ごと待つしかない。無人運転では明示的に `--timeout 0` を指定すること。
    スクリプトは TTY がないことを検出すると、先に注意を 1 行出す。

### git submodule {#git-submodule}

`.gitmodules` にあるのは 1 件だけ:

| path | url | 何か |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | [HT001](../cases/ht001.md) のあのランが**生成した**コードリポジトリ。記録用 |

普通の `git clone` ではこれを取ってこないので、`human-test/HT001` は空ディレクトリのままだ
(`git submodule status` の先頭に `-` が付くのがこの状態)。扱うべきかどうか:

| やりたいこと | 初期化が要るか |
|---|---|
| flower を走らせる、イメージをビルドする | **不要**。`.dockerignore` が `human-test/` を除外しており、`Dockerfile` もそもそも `pyproject.toml` / `flower` / `examples` しか `COPY` しない |
| ローカルで HT001 の成果コードを読む | 必要:`git submodule update --init human-test/HT001`、または最初から `git clone --recurse-submodules` |

### 中国国内ネットワーク:あのミラー置換の山は何なのか {#国内网络为什么有那一堆镜像替换}

この一式を中国国内でインストールするとき、遅いのは帯域ではなく国際回線だ。既定の `docker/build` は
置換すべきところをすべて置換済みで、`FLOWER_MIRRORS=0` で一括オフにできる。以下は実測データと 4 箇所の置換の経緯 ——
ネットワークにこの問題がなければ読まなくていい。

??? note "実測速度表と 4 箇所の置換(2026-09-06、macOS/arm64)"

    | ソース | 速度 |
    |---|---|
    | `pypi.org`(インデックス) | 32 KB/s |
    | `files.pythonhosted.org`(パッケージ本体) | **284 B/s** |
    | `github.com`(release asset 直結) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com`(VM 内) | 26 KB/s |
    | `download.docker.com` | **接続不可**(HTTP 000);VM 内で 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **接続不可** |
    | `mirrors.aliyun.com/pypi`(**パッケージ本体**) | 1.4 MB/s(ホスト)/ 152 KB/s(VM 内) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports`(VM 内) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top`(GitHub プロキシ) | **2.5 MB/s** |
    | `gh-proxy.com`(GitHub プロキシ) | 1.5 MB/s |
    | `dockerproxy.net`(Docker Hub プロキシ) | 利用可(manifest を直接返す) |

    計測するときに**インデックスページ**をパッケージ本体と取り違えないこと:`mirrors.aliyun.com/pypi/simple/` の
    あのページは 7.4 MB/s 出るが、実際の 95.9 MB の wheel は 1.4 MB/s しか出ない(VM 内では 152 KB/s —— colima の
    ユーザーランドネットワークで目減りする)。時間の見積もりはパッケージ本体の数字でやること。

    **置換ポイント 1 —— colima の VM イメージ。** colima が使うのは普通の Ubuntu cloud image ではなく、
    **docker をプリインストールした**独自イメージ(`abiosoft/colima-core` の release asset)だ。だから VM 起動時に
    apt で docker を入れる必要がなく、接続できない `download.docker.com` を回避できる。自分でダウンロードしておいて
    `--disk-image` で食わせる:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 検証:digest は GitHub API から取る。飛ばさないこと —— これは VM として走らせるものだ
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    プロキシは途中でストリームが切れる(実測 curl 56)。`-C -` のレジューム付きで何度かやり直せばいい。

    **置換ポイント 2 —— VM 内の apt。** docker プリインストール済みイメージを使っても、lima の boot スクリプト
    `30-install-packages.sh` は `rsync` を入れるために `apt-get update` を 1 回走らせる ——
    `ports.ubuntu.com`(26 KB/s)と `download.docker.com`(4 KB/s)を叩き、数十分固まる。

    対処(**先に `/mnt/lima-cidata/boot.sh` を読んでから手を出すこと**:失敗した boot スクリプトに対しては `WARNING` +
    `CODE=1` を出して続行するだけで、しかも末尾で**必ず** `/run/lima-boot-done` を書く。だからそのステップを失敗させても安全だ):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh は最後まで走り切り、完了マーカーを書く
    '
    # colima start はその後正常に終了する。あとで rsync を入れ直す(いまは 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    ついでに `127.0.0.1 lima-colima` を VM の `/etc/hosts` に足して、`sudo: unable to resolve host` の警告の列を消しておく。

    **置換ポイント 3 —— ベースイメージ。** `docker/build` はまず `dockerproxy.net` から `python:3.13-slim` を pull して
    retag し、Dockerfile の `FROM` をローカルにヒットさせる。実測で `dockerproxy.net` は manifest を直接返した
    (HTTP 200)。`docker.1ms.run` / `docker.m.daocloud.io` は 401、`hub.rat.dev` は 302、
    `docker.xuanyuan.me` は 403 を返した。

    **置換ポイント 4 —— コンテナ内の apt と pip。** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s)、
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。なお `PIP_INDEX_URL` は
    pip 自身が認識する環境変数でもあるので、`ARG` を宣言した時点で RUN 内の pip がそれを読む ——
    `--index-url` を明示しなくても効く。

    一度きりの準備の総所要時間(上記のネットワーク条件で)は約 25 分。大半は 364 MB の VM イメージと 95.9 MB の
    SDK wheel だ。以後の `flowerbox` の起動は秒単位。

## 二、plugin {#plugin}

### それは何か {#它是什么}

リポジトリに付いて回る**ドメイン能力パッケージ**。フレームワークのコードはドメイン知識を一切含まず、
ドメイン知識はすべてリポジトリルートの `plugin/` ディレクトリに置かれ、コードと一緒に clone され、
一緒に review され、一緒に tag が打たれる。

SDK 側の結線は
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)
の `build_options()` にある 2 行:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

`setting_sources=[]`(後述)と合わせて、これが flower が「[ポータブル](glossary.md#可移植)」と
「あなたのドメインを理解している」を同時に成立させられる理由だ:ホストに何が入っているかを問わず、
リポジトリが持ち込んだこの 1 ディレクトリだけを見る。

### ディレクトリ構成 {#目录布局}

| パス | 何を置くか | いつ効くか | 誰が決めるか |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | パッケージの素性:`name`、`description`、`version`、`author` | ロード時に 1 回読む | — |
| `plugin/skills/<name>/SKILL.md` | ドメイン知識、必要に応じてロード | **確率的** —— モデルが関連ありと判断したときだけ使う | モデル |
| `plugin/agents/<name>.md` | subagent、独立したコンテキストウィンドウ | モデルが委譲するか、[ワークフロー](glossary.md#流程)で明示指定 | モデル / あなた |
| `plugin/hooks/hooks.json` | ツール呼び出しの割り込み | **決定的** —— マッチすれば実行 | コード |
| `plugin/.mcp.json` | 外部ツールの接続 | ツールとして登録され、組み込みツールと同じ扱い | モデル |

**確率的と決定的の違いは選定の要であり、言い回しの違いではない:**

- skill は**そこに置いてある知識**だ。モデルはその `description` を見て、いまのタスクに関連すると
  思ったときだけ読みに行く。関連性の判断はモデルがするので、同じ 1 文を 2 回走らせると、一度は使い、
  一度は使わない、ということが起こりうる。
- hook は**コード**だ。イベントにマッチすれば走る。モデルがそうしたいかどうか、知っているかどうかとは無関係。
  flower 自身の[スピル](glossary.md#落盘)、[隔離](glossary.md#隔离)はすべて hook だ。まさにそれらが
  「ときどき効く」であってはならないからだ。

だから判断基準は 1 つだけ:**これは毎回必ず起きなければならないことか?** 必須なら —— hook を書く。
「知っていれば得をする」程度なら —— skill を書く。必須のことを skill に書くのは、規律をモデルの
一度の判断に賭けることに等しい。

いま、リポジトリの `plugin/` には 2 つしかない:`.claude-plugin/plugin.json` と `skills/example/SKILL.md`。
`agents/`、`hooks/`、`.mcp.json` は**まだ存在しない** —— 使うなら自分で作る。ディレクトリ名は上の表のとおりに固定。

### skill を書く:完全な例 {#写一个-skill完整例子}

「リリースノートを生成する」を例に、ゼロから有効化の確認まで。

**第 1 ステップ:ディレクトリを作る。** ディレクトリ名がそのまま skill 名で、frontmatter の `name` と一致させる。

```bash
mkdir -p plugin/skills/release-notes
```

**第 2 ステップ:`plugin/skills/release-notes/SKILL.md` を書く。** ファイル名は `SKILL.md`、大文字でなければならない。
形式は YAML frontmatter + Markdown 本文で、frontmatter のフィールドは 2 つ:

| フィールド | 役割 |
|---|---|
| `name` | skill の識別子。ディレクトリ名と一致させる |
| `description` | **モデルがこれを選ぶかどうかは、この 1 行だけで決まる**。「これは何か」ではなく「いつ使うべきか」を明確に書く |

そのまま使える最小のファイル:

````markdown
---
name: release-notes
description: リリースノートをまとめるときに使う。ユーザーが「release notes を書いて」「このバージョンで何が変わった」「リリースする」と言ったときに使う。
---

# リリースノート

## 素材の取り方

```bash
git describe --tags --abbrev=0        # 直前の tag
git log --oneline <直前の tag>..HEAD   # このバージョンのコミット
```

## 出力フォーマット

3 セクションに分け、各セクションは順不同リスト、1 項目 1 行。ユーザーが体感できる変化を書き、内部リファクタリングは書かない:

- **追加** —— このバージョンでできるようになった、以前はできなかったこと
- **修正** —— 何を直したか。症状を一言で説明する
- **非互換** —— アップグレード時に手を入れる必要があるもの。なければセクションごと書かない

## 境界

- バージョン番号を勝手に作らない。`pyproject.toml` の `version` から読む。
- あるコミットがユーザーに体感されるか判断がつかないときは、挙げて質問する。ユーザーの代わりに決めない。
````

本文の書き方に強制フォーマットはない —— コンテキストに読み込まれる単なるテキストだ。
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md)
の書き方を参照:**いつ使うか**、**手順**、**出力をどうするか**、**境界はどこか**を明確にするほうが、
背景知識を積み上げるより役に立つ。

**第 3 ステップ:ロードされたことを確認する。** 確実に分かることを 1 つだけ調べる —— ディレクトリが実際にあるかどうか:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

`/path/to/flower/plugin True` と出て初めて、`build_options()` のあの `if` に入ると言える。
`False` が出たらロードされていない。しかも**実行時にはエラーにならない**。下の警告を参照。

**「1 文走らせて `example` skill が呼び出されたかどうかを見る」を検証にしてはいけない。** skill は確率的だ:
モデルがそれを呼ばなかったのは、インストールされていないからかもしれないし、単にいまのタスクに必要だと
思わなかっただけかもしれない —— このシグナルではこの 2 つを区別できない。さらに
`build_options()` は SDK のセッション単位の `skills=` オプションを一切設定していないので、plugin 内の skill が
コーディネーターの選択肢リストに現れるかどうかは、実測されていない。上の `PLUGIN_DIR` の `True`/`False` は確定的だ。そちらを使え。

ある[ワーカー](glossary.md#执行者)に対してどの skill を有効にするかを名指しするには、`worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py))を使う。
名前は `SKILL.md` の `name` を使う。SDK は `プラグイン名:skill 名` という限定表記も受け付ける。

!!! warning "インストールされた flower には `plugin/` がない —— 3 通りのインストール方法すべてで"
    `PLUGIN_DIR` は `flower/core/agent.py` から 3 階層上がって `plugin/` に入る。ソースの checkout から走らせる場合、
    それはリポジトリルートの `plugin/` だ。しかし wheel は `flower` ディレクトリ 1 つしかパッケージしない
    (`pyproject.toml` の `[tool.hatch.build.targets.wheel] packages = ["flower"]`)。site-packages に入った後は
    `site-packages/plugin` が存在せず、`PLUGIN_DIR.is_dir()` は偽になる —— **黙ってスキップされ、エラーも警告も出ない**。

    **これはコンテナの問題ではなく、範囲はもっと広い。** `install.sh` のすべての経路 —— `uv tool install`、
    `pipx install`、uv をブートストラップしてから uv を使う経路、そしてフォールバックの `pip install --user` ——
    どれも入れるのは wheel だ。つまり**ワンライナーでインストールした flower では、ドメイン能力パッケージは一律に黙って無効になる**。
    コンテナは同じ問題の一事例にすぎない:`docker/Dockerfile` は `pyproject.toml`、`flower/`、`examples/` しか
    `COPY` しておらず、`plugin/` はイメージに入っていない。

    [issue #15](https://github.com/ChenyuHeee/flower/issues/15) に記録した。インストール後にまず上の
    `PLUGIN_DIR` コマンドを走らせて自己確認すること:`False` が出れば、そのインストールにはドメイン能力パッケージがない。
    ドメイン能力パッケージを使うなら、いまのところソースの checkout から走らせるしかない。

### `setting_sources=[]` がドメイン能力を plugin に追い込む理由 {#setting_sources-为什么逼着领域能力走-plugin}

同じ関数にはこの 1 行もある:

```python
"setting_sources": [] if portable else ["project"],
```

SDK の既定は `None` = 3 つのソースをすべて読む:`~/.claude/settings.json`(ユーザー)、
`.claude/settings.json`(プロジェクト)、`.claude/settings.local.json`(ローカル)。flower は既定で `[]` を渡し、
それらを**すべてオフにする**。

| | 読むか | 帰結 |
|---|---|---|
| `~/.claude/`(ホスト) | 読まない | マシンを変えても挙動が一致する。「自分のマシンでは設定してある」ことで結果が変わらない |
| プロジェクトの `.claude/` | 読まない | `.claude/skills/`、`.claude/agents/` に置いたものは flower 下では**1 つも効かない** |
| `plugin/` | 読む | パスがコードにハードコードされており、リポジトリに付いて回る |
| 認証情報 | この経路を通らない | `.env` を自分で持つ必要がある。`~/.claude/settings.json` と `settings.local.json` の `env` ブロックは最後のフォールバックにしか使わず、**9 個の認証キーしか取らない**。[設定](config.md)を参照 |

`.claude/` が効かないのは**設定漏れではなく、この制約の定義そのもの**だ:ホストから 1 バイトでも読む限り、
「マシンを変えても挙動が一致する」は成り立たない。だからドメイン能力の通り道は 1 本しかない ——
リポジトリに付いて回る `plugin/` だ。

スイッチは 2 つ(どちらも `build_options()` にあり、既定値がポータブル側):

| 引数 | 既定値 | 変えるとどうなるか |
|---|---|---|
| `portable` | `True` | `False` を渡す → `setting_sources` が `["project"]` になり、プロジェクトの `.claude/` を読み始める(SDK 側:`CLAUDE.md` を読むには `"project"` が必要)。ポータビリティはそこで失われる |
| `use_plugin` | `True` | `False` を渡す → `plugin/` を一切マウントせず、ドメイン能力はすべて `AgentSpec.instructions` 頼みになる |

ついでに:`instructions` は[アペンド](glossary.md#叠加)(`system_prompt` の `append`)を通り、
plugin とは別の通り道だ —— 前者は毎ラウンドコンテキストに載り、後者は必要に応じてロードされる。
短くて必須の規律は `instructions` に、長くてたまに役立つ知識は skill に書く。

## 三、ドキュメントサイト {#三文档站}

いま読んでいるこのサイトは mkdocs-material で作っている。ソースはリポジトリの `docs/` 配下にあり、
`main` に push すれば自動で公開される。

| 工程 | 何か |
|---|---|
| 設定 | `mkdocs.yml`、`docs_dir: docs` |
| 多言語 | `mkdocs-static-i18n`、`docs_structure: folder` —— `docs/zh/`、`docs/en/`…… 既定言語は `zh` |
| 依存 | `docs-requirements.txt`(バージョン固定)。`pyproject.toml` の `docs` extra **ではない** —— CI が入れるのは前者 |
| ビルド | `mkdocs build --strict`。内部リンク切れや nav が存在しないページを指す場合はビルドを失敗させ、404 を黙って公開しない |
| リダイレクト | `hooks/redirects.py`。ビルド**後**に最終 URL に従って meta-refresh のスタブページを書き、旧来のフラットなアドレス(`/start/`、`/workflow/`、`/case-ht001/`……)を新しい位置につなぐ |
| デプロイ | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`、GitHub Pages へ公開 |

ローカルでドキュメントを直す:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # ローカルプレビュー
mkdocs build --strict         # コミット前に一度走らせる。CI と同じコマンド
```

CI のトリガー条件は `main` への push、**かつ**変更が以下のパスにヒットすること。加えて Actions ページから手動で
`workflow_dispatch` もできる:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### `install.sh` を Pages から配る理由 {#installsh-为什么从-pages-发}

ビルドステップの末尾にこの 1 行がある:

```yaml
- run: cp install.sh site/install.sh
```

インストールスクリプトがサイトの成果物に押し込まれ、ドキュメントサイトのドメインにぶら下がる。
ワンライナーインストールはこうなる:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

理由はきわめて実際的だ:**`raw.githubusercontent.com` は中国国内から繋がらないが、`*.github.io` は繋がる**(実測)。
スクリプト本体はリポジトリルートに置いたままで、公開時に 1 部コピーするだけ —— 二重管理も、追加の CDN も要らない。

`install.sh` 自身がやること:Python のツールインストーラを 1 つ選び(`uv` > `pipx` > `uv` を入れる > `pip --user`)、
GitHub から flower をインストールし、次の手順を案内する。**認証情報には触らない** —— 初回に `flower` を走らせると聞かれ、
`~/.config/flower/.env` に保存される。
