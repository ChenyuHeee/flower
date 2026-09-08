# デプロイと拡張

flower を別の場所に持っていくとき、扱うことは三つある。コンテナ(制限のない Bash を囲い込む、
ついでに「CLI から独立している」という主張を検証する)、
[plugin](glossary.md#plugin)(ドメイン能力がリポジトリに付いて回る。ホストマシンに何が入っているかは見ない)、
ドキュメントサイト(`main` に push すれば自動で公開、`install.sh` は Pages のドメインにぶら下げる)。
三節は互いに独立しているので、必要なものだけ読めばいい。

## 一、コンテナ {#一容器}

### なぜコンテナか {#为什么要容器}

**一つ目は囲い込み。** 実作業をする[ワーカー](glossary.md#执行者)は**制限のない Bash** を持つ ——
flower の Bash ホワイトリスト(`delegate_guard`)は[メインスレッド](glossary.md#主线程)だけを見ており、
送り出した相手にはテストを走らせられる必要がある。これは意図的だ。
コンテナにはあなたのプロジェクトディレクトリだけをマウントし、フレームワークのソースはイメージ内の `/opt/flower` に置く。
ホストの他の場所は見えない。

**二つ目は、これ自体が[ポータブル](glossary.md#可移植)という制約の検証になっていること。** イメージには Claude Code CLI もなければ
Node もない。あるのは Python と `claude-agent-sdk` だけ —— リクエストは wheel に同梱されたネイティブバイナリが送る。
ここで動くなら、「CLI から独立している」は紙の上の話ではなくなる。

実測で通過(2026-09-06、macOS 15 / arm64 / colima + docker 28.4.0):

| 検証対象 | 結果 |
|---|---|
| イメージに CLI があるか | `claude`、`node`、`npm`、`npx` は**いずれも存在しない** |
| 同梱バイナリ | `\177ELF`(207M) |
| 実リクエスト | `cloud.infini-ai.com/maas` 経由で送信し応答を取得、`$0.1741 / 1 ターン`(Opus 5 + 1M ウィンドウのシングルターンの下限価格がこれ) |
| ファイルの所有者 | コンテナ内で `/work` に書いたファイルはホストでは `hechenyu:staff`、マッピングは正しい |
| ホストの可視性 | コンテナ内で `ls /Users` → `No such file or directory` |

### イメージに何が入っているか {#镜像里装了什么}

ベースイメージは `python:3.13-slim`、その上に apt で三つのパッケージだけを入れる。どれにも理由がある:

| 入れるもの | 理由 |
|---|---|
| `python:3.13-slim` | 必要なのは Python ≥ 3.10 だけ。Node も claude CLI も入れない |
| `git` | `--isolate` は [subagent](glossary.md#subagent) ごとに worktree を割り当てる |
| `ca-certificates` | HTTPS ゲートウェイを通る |
| `libstdc++6` | SDK 同梱のバイナリは Bun でコンパイルされた単一ファイルで、Linux ではこれが要る。slim イメージには入っていない |

フレームワークのソースは `COPY` でイメージに入る。**bind mount ではない** —— だからコンテナ内の agent は
ホストのフレームワークソースに触れられない:

| イメージ内パス | 内容 | 由来 |
|---|---|---|
| `/opt/flower` | `pyproject.toml`、`flower/`、`examples/`。ここで `pip install .` する | `COPY` |
| `/work` | 作業ディレクトリ(`WORKDIR`)、実行時にホストの `$PWD` をマウント | `docker run -v` |

エントリポイントは `ENTRYPOINT ["flower"]`、`CMD` は空 —— 引数なしでコンテナを起動すると対話入力に入る
(何をしたいかを聞いてくる)。`--help` は出さない。こうすれば、日本語の要求を shell でクォートする必要がなくなる。

### なぜホストの `.venv` をマウントできないのか {#为什么不能把宿主的-venv-挂进去}

SDK はプラットフォーム別に wheel を配布しており、同梱バイナリはプラットフォーム専用だ:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

マウントしても動かないので、イメージ側で自前に `pip install` するしかない。裏を返せばこれはポータビリティの証拠でもある:
同じ `pyproject.toml` で、プラットフォームを変えればネイティブバイナリが差し替わり、フレームワークのコードは一行も変えなくていい。

### 二つのスクリプト {#两个脚本}

| スクリプト | 何をするか |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | イメージをビルドする。リポジトリルートに `cd` して `docker build -f docker/Dockerfile -t flower-box .`。`FLOWER_MIRRORS=1`(デフォルト)のときは先に registry ミラーから `python:3.13-slim` を pull して retag し、pip / apt の `--build-arg` を付ける |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | 一回実行する。認証情報ファイルを確認 → `$PWD` がマウントできるか確認 → TTY の有無を判定 → `docker run` |

`docker/build` のスイッチはすべて環境変数:

| 変数 | デフォルト | 意味 |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | イメージ tag |
| `FLOWER_MIRRORS` | `1` | `0` = ミラーを一つも使わず、すべて上流に行く |
| `FLOWER_REGISTRY` | `dockerproxy.net` | ここからベースイメージを pull して `python:3.13-slim` に retag し、`FROM` をローカルにヒットさせる |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | `--build-arg PIP_INDEX_URL` に渡す |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | `--build-arg APT_MIRROR` に渡す |

後ろの三つは `FLOWER_MIRRORS=1` のときだけ効く —— `FLOWER_MIRRORS=0` の分岐では build-arg をそもそも設定しない。

`docker/flowerbox` が見るのは二つ:

| 変数 | デフォルト | 意味 |
|---|---|---|
| `FLOWER_HOME` | スクリプト自身の位置の一つ上(つまりリポジトリルート) | `.env` をどこに探すか。`$FLOWER_HOME/.env` が見つからなければ即座に 1 で終了 |
| `FLOWER_IMAGE` | `flower-box` | どのイメージを動かすか |

`FLOWER_HOME` はスクリプト自身の位置から導出しており、パスをハードコードしていない。だからリポジトリをどこに clone しても使える。

### イメージをビルドしてコンテナを起動する {#跑起来}

```bash
docker/build                       # 一度だけでいい
cd ~/任意のプロジェクトディレクトリ    # 必ず $HOME 配下に。下のマウント境界を参照
/path/to/flower/docker/flowerbox   # 引数なし → 何をしたいか聞いてくる。クォート不要
```

pypi.org / Docker Hub へのネットワークが正常なら、ビルドはこう:

```bash
FLOWER_MIRRORS=0 docker/build
```

`flowerbox` の引数は `flower` と完全に同じ —— `"$@"` をそのまま `ENTRYPOINT` の後ろに繋ぐだけだ。
`--clarify-only`、`--asks N`、`--timeout 秒数`、`--isolate`、`-v` もそのまま渡せる。全表は[コマンドライン](cli.md)に:

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "Xを作ってほしい"
```

実際に実行されるのはこの一行(`-t` は TTY がある場合のみ付く。下記参照):

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

だから `flower/human-test/HT001` のようなリポジトリ内のサブディレクトリで動かしても安全だ:
マウントされるのは `HT001` だけで、フレームワークのソースはマウント範囲に入らない。

| 対象 | 終了後も残るか | 理由 |
|---|---|---|
| ホスト `$PWD` 配下のすべて(`runs/`、[ワークベンチ](glossary.md#工作台) `.flower/` を含む) | 残る | それが `/work` としてマウントされているディレクトリそのものだから |
| コンテナ内の他のパスに書いたもの | 残らない | `--rm`、コンテナ終了と同時に消える |
| 認証情報 | イメージレイヤーに入らない | `--env-file` 経由。`.dockerignore` で `.env` を除外しているので、`COPY . .` でも入らない |

!!! danger "プロジェクトディレクトリは必ず `$HOME` 配下に。そうでないと成果物が黙って失われる"
    **colima はデフォルトで `$HOME` だけを VM にマウントする**(`mount | grep virtiofs` → `mount0 on /Users/<ユーザー名>`)。
    `/tmp` のような場所で動かすと、`-v` は VM 内に**空のディレクトリ**を作り、そこに書いたものはホストからは永遠に見えない。
    **しかもエラーも出ない** —— 成果物、[ブリーフ](glossary.md#需求确认书)、`runs/` がすべて失われる。一度踏んだ:
    `once` を一回走らせて $0.17 を使い切ったのに、`runs/` はホスト上にそもそも存在しなかった。

    `flowerbox` は現在このケースを止める:`$PWD` が `$HOME` 配下ならそのまま通す。そうでなければ `$PWD` に
    プローブファイルを書き、もう一つコンテナを起こして `test -f /work/<プローブ>` で実測する(追加マウントを設定していれば通る)。
    通らなければ 1 で終了し、`colima start --mount '<パス>:w'` を案内する。プローブはコンテナを起こすので、先に `docker/build` が必要。

### 認証情報はどうやってコンテナに入るか {#凭证}

`docker run --env-file` 経由で、**イメージレイヤーには入らない**。`flowerbox` が読むのは `$FLOWER_HOME/.env`、
デフォルトではリポジトリルートの `.env` だ:

```bash
cp .env.example .env       # 填 token;.env 已被 gitignore
```

注意:`flower setup` が書くのは `~/.config/flower/.env` で、**そのパスを `flowerbox` は見ない**。
すでに `setup` で設定済みで、もう一部コピーしたくないなら `FLOWER_HOME` をそちらに向ける:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

キー名、優先順位、ゲートウェイの書き方は[設定](config.md)を参照。

!!! warning "TTY がないと、質問は `--timeout` まで固まり続ける"
    `flowerbox` は `[ -t 0 ]` のときだけ `-t` を付ける —— パイプや CI の中で `docker run -t` すると
    「the input device is not a TTY」で即エラーになる。`-i` は常に必要で、これがないと stdin がそもそも入らない。

    質問への回答は標準入力を通る。TTY がないと `input()` が最初の一回で `EOFError` を投げ → その質問は
    「入力が閉じた」として飛ばされ、しかも**回答スレッドがそのまま終了する**。だから二つ目以降の質問は誰も受けず、
    `--timeout`(デフォルト 1800 秒)いっぱいまで待つしかない。無人運用では明示的に `--timeout 0` を指定すること。
    スクリプトは TTY がないことを検出すると、先に一行注意を出す。

### git submodule {#git-submodule}

`.gitmodules` には一行しかない:

| path | url | 何か |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | [HT001](../cases/ht001.md) の run が**生み出した**コードリポジトリ。記録用 |

通常の `git clone` ではこれを取ってこないので、`human-test/HT001` は空のディレクトリのままだ
(`git submodule status` の先頭に `-` が付くのがこの状態)。扱うべきかどうか:

| やりたいこと | 初期化が必要か |
|---|---|
| flower を動かす、イメージをビルドする | **不要**。`.dockerignore` が `human-test/` を除外しているし、`Dockerfile` はそもそも `pyproject.toml` / `flower` / `examples` しか `COPY` しない |
| ローカルで HT001 の成果コードを読む | 必要:`git submodule update --init human-test/HT001`、または最初から `git clone --recurse-submodules` |

### 中国国内のネットワーク:なぜあれだけミラー差し替えがあるのか {#国内网络为什么有那一堆镜像替换}

この一式を Great Firewall の内側で入れるとき、遅いのは帯域ではなく国際回線だ。デフォルトの `docker/build` は
差し替えるべきものをすでに全部差し替えてあり、`FLOWER_MIRRORS=0` で一括オフにできる。以下は実測データと
四箇所の差し替えの経緯 —— ネットワークにこの問題がないなら読まなくていい。

??? note "実測速度表と四箇所の差し替え(2026-09-06、macOS/arm64)"

    | ソース | 速度 |
    |---|---|
    | `pypi.org`(インデックス) | 32 KB/s |
    | `files.pythonhosted.org`(パッケージファイル) | **284 B/s** |
    | `github.com`(release asset に直接) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com`(VM 内) | 26 KB/s |
    | `download.docker.com` | **接続不可**(HTTP 000);VM 内では 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **接続不可** |
    | `mirrors.aliyun.com/pypi`(**パッケージファイル**) | 1.4 MB/s(ホスト)/ 152 KB/s(VM 内) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports`(VM 内) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top`(GitHub プロキシ) | **2.5 MB/s** |
    | `gh-proxy.com`(GitHub プロキシ) | 1.5 MB/s |
    | `dockerproxy.net`(Docker Hub プロキシ) | 利用可(manifest をそのまま返す) |

    計測するときは**インデックスページ**をパッケージファイルと取り違えないこと:`mirrors.aliyun.com/pypi/simple/` の
    あのページは 7.4 MB/s 出るが、本体である 95.9 MB の wheel は 1.4 MB/s しかない(VM 内では 152 KB/s —— colima の
    ユーザー空間ネットワークにロスがある)。時間はパッケージファイルの数字で見積もること。

    **差し替え 1 —— colima の VM イメージ。** colima が使うのは普通の Ubuntu cloud image ではなく、
    **docker をプリインストールした**独自イメージ(`abiosoft/colima-core` の release asset)だ。だから VM 起動時に
    apt で docker を入れる必要がなく、接続できない `download.docker.com` を回避できる。自分でダウンロードしてから
    `--disk-image` で食わせる:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 検証: digest は GitHub API から取る。飛ばさないこと —— VM として動かすものだ
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    プロキシは途中で切れることがある(実測 curl 56)。`-C -` のレジューム付きで何度かやり直せばいい。

    **差し替え 2 —— VM 内の apt。** docker プリインストール済みイメージを使っても、lima の boot スクリプト
    `30-install-packages.sh` は `rsync` を入れるために `apt-get update` を一度走らせる ——
    `ports.ubuntu.com`(26 KB/s)と `download.docker.com`(4 KB/s)を叩き、数十分固まる。

    対処(**先に `/mnt/lima-cidata/boot.sh` を読んでから手を動かすこと**:失敗した boot スクリプトに対しては
    `WARNING` + `CODE=1` を出して続行するだけで、しかも末尾で**必ず** `/run/lima-boot-done` を書く。だからその
    ステップを失敗させても安全だ):

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
      pkill -f "apt-get update"          # boot.sh はそのまま走り切って完了マーカーを書く
    '
    # colima start はこの後正常に終了する。あとで rsync を補う(今なら 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    ついでに `127.0.0.1 lima-colima` を VM の `/etc/hosts` に足しておくと、`sudo: unable to resolve host` の
    警告の列が消える。

    **差し替え 3 —— ベースイメージ。** `docker/build` はまず `dockerproxy.net` から `python:3.13-slim` を pull し、
    retag して Dockerfile の `FROM` をローカルにヒットさせる。実測では `dockerproxy.net` は manifest を直接返す
    (HTTP 200)。`docker.1ms.run` / `docker.m.daocloud.io` は 401、`hub.rat.dev` は 302、
    `docker.xuanyuan.me` は 403 だった。

    **差し替え 4 —— コンテナ内の apt と pip。** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s)、
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。注意:`PIP_INDEX_URL` は
    pip 自身が認識する環境変数でもあるので、`ARG` を宣言した時点で RUN 内の pip がそれを読む ——
    `--index-url` を明示しなくても効く。

    一度きりの準備にかかる合計時間(上記のネットワーク条件下)はおよそ 25 分、大半は 364 MB の VM イメージと
    95.9 MB の SDK wheel だ。その後の `flowerbox` の起動は秒単位になる。

## 二、plugin {#plugin}

### plugin とは何か、SDK はどう読み込むか {#它是什么}

リポジトリに付いて回る**ドメイン能力パッケージ**だ。フレームワークのコードはドメイン知識を一切含まず、
ドメイン知識はすべてリポジトリルートの `plugin/` ディレクトリに置く。コードと一緒に clone され、
一緒に review され、一緒に tag が打たれる。

SDK 側の配線は
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)
の `build_options()` の中の二行:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

`setting_sources=[]`(後述)と合わせて、これが flower が「[ポータブル](glossary.md#可移植)」と
「あなたのドメインを理解する」を同時に満たせる理由だ:ホストマシンに何が入っているかは問わず、
リポジトリが持ってきたこの一つのディレクトリだけを見る。

### ディレクトリ構成 {#目录布局}

| パス | 何を置くか | いつ効くか | 誰が決めるか |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | パッケージの素性:`name`、`description`、`version`、`author` | 読み込み時に一度読む | — |
| `plugin/skills/<name>/SKILL.md` | ドメイン知識、必要に応じて読み込む | **確率的** —— モデルが関連すると判断したときだけ使う | モデル |
| `plugin/agents/<name>.md` | subagent、独立したコンテキストウィンドウ | モデルが委譲するか、[ワークフロー](glossary.md#流程)で明示指定 | モデル / あなた |
| `plugin/hooks/hooks.json` | ツール呼び出しを横取りする | **決定的** —— マッチすれば実行 | コード |
| `plugin/.mcp.json` | 外部ツールの接続 | ツールとして登録され、組み込みツールと同じに扱われる | モデル |

**確率的と決定的の違いは選定の要であって、言い回しの違いではない:**

- skill は**そこに置いてある知識**だ。モデルはその `description` を見て、現在のタスクと関連すると思ったときに読みに行く。
  関連性の判断はモデルがやるので、同じ一言で二回走らせると、一度は使い、一度は使わない、ということが起こりうる。
- hook は**コード**だ。イベントにマッチすれば走る。モデルがそうしたいか、知っているかは無関係。flower 自身の
  [スピル](glossary.md#落盘)や[隔離](glossary.md#隔离)が hook なのは、まさにそれらが「ときどき効く」では困るからだ。

だから判断基準は一つだけ:**これは毎回必ず起きなければならないか?** 必ず起きるべきなら hook を書く。
「知っていると得をする」程度なら skill を書く。必須のことを skill にするのは、規律をモデルの一回の判断に賭けることに等しい。

いま リポジトリの `plugin/` にあるのは二つだけ:`.claude-plugin/plugin.json` と `skills/example/SKILL.md`。
`agents/`、`hooks/`、`.mcp.json` は**まだ存在しない** —— 使うなら自分で作る。ディレクトリ名は上表のとおり固定だ。

### skill を一つ書く:完全な例 {#写一个-skill完整例子}

「リリースノートを生成する」を例に、ゼロから有効化の確認まで。

**第一歩:ディレクトリを作る。** ディレクトリ名がそのまま skill 名で、frontmatter の `name` と揃える。

```bash
mkdir -p plugin/skills/release-notes
```

**第二歩:`plugin/skills/release-notes/SKILL.md` を書く。** ファイル名は必ず `SKILL.md`、大文字。
形式は YAML frontmatter + Markdown 本文、frontmatter のフィールドは二つ:

| フィールド | 役割 |
|---|---|
| `name` | skill の識別子。ディレクトリ名と一致させる |
| `description` | **モデルがこれを選ぶかどうかは、この一行だけで決まる**。「どういうときに使うべきか」を書く。「これは何か」を書かない |

そのまま使える最小のファイル:

````markdown
---
name: release-notes
description: リリースノートをまとめるときに使う。ユーザーが「release notes を書いて」「このバージョンで何が変わった」「リリース」と言ったら使う。
---

# リリースノート

## 素材の取り方

```bash
git describe --tags --abbrev=0        # 前のタグ
git log --oneline <前のタグ>..HEAD     # このバージョンのコミット
```

## 出力フォーマット

三つのセクションに分け、各セクションは箇条書き、一項目一行。ユーザーが体感できる変化を書き、内部のリファクタリングは書かない:

- **追加** —— このバージョンでできるようになったこと
- **修正** —— 何を直したか、症状を一文で
- **非互換** —— アップグレード時に手を入れる必要があるもの。なければセクションごと書かない

## 境界

- バージョン番号を自分で作らない。`pyproject.toml` の `version` から読む。
- あるコミットがユーザーに体感されるかどうか判断がつかないときは、列挙して質問する。ユーザーの代わりに決めない。
````

本文の書き方に強制はない —— コンテキストに読み込まれる一片のテキストにすぎない。
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md)
の書き方を参照:**いつ使うか**、**手順**、**出力はどんな形か**、**境界はどこか**をはっきり書くほうが、
背景知識を積み上げるより役に立つ。

**第三歩:読み込まれたことを確認する。** 確実に分かることを一つだけ調べる —— ディレクトリが実際にあるかどうか:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

`/path/to/flower/plugin True` と出て初めて、`build_options()` のあの `if` に入ると分かる。
`False` なら読み込まれていない。しかも**実行時にエラーは出ない**。下の警告を参照。

**「一言走らせて `example` skill が呼ばれたか見る」を検証にしないこと。** skill は確率的だ:モデルが呼ばなかったのは、
インストールされていないせいかもしれないし、単に今回のタスクに必要と思わなかっただけかもしれない —— この信号では二つを区別できない。
さらに `build_options()` は SDK のセッションレベルの `skills=` オプションを一度も設定していないので、plugin 内の skill が
コーディネーターの選択肢リストに現れるかどうかは実測されていない。上の `PLUGIN_DIR` の `True`/`False` は確実なので、そちらを使う。

特定の[ワーカー](glossary.md#执行者)にどの skill を開くか名指しするには `worker(..., skills=[...])` を使う
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py))。
名前は `SKILL.md` の `name`。SDK は `プラグイン名:skill名` という限定表記も受け付ける。

!!! warning "インストールされた flower には `plugin/` がない —— 三つのインストール方法すべてで"
    `PLUGIN_DIR` は `flower/core/agent.py` から三階層上って `plugin/` に入る。ソースの checkout から動かすときは
    それがリポジトリルートの `plugin/` になる。しかし wheel は `flower` ディレクトリしかパッケージしない
    (`pyproject.toml` の `[tool.hatch.build.targets.wheel] packages = ["flower"]`)。site-packages に入った後は
    `site-packages/plugin` が存在せず、`PLUGIN_DIR.is_dir()` は偽 —— **黙ってスキップされ、エラーも警告も出ない**。

    **これはコンテナの問題ではなく、範囲はずっと広い。** `install.sh` のどの経路も —— `uv tool install`、
    `pipx install`、uv をブートストラップしてから uv を使う経路、そして `pip install --user` のフォールバック ——
    インストールするのは wheel だ。つまり**一行でインストールした flower では、ドメイン能力パッケージは一律に黙って無効化される**。
    コンテナは同じ問題の一インスタンスにすぎない:`docker/Dockerfile` は `pyproject.toml`、`flower/`、`examples/` しか
    `COPY` しておらず、`plugin/` はイメージに入っていない。

    [issue #15](https://github.com/ChenyuHeee/flower/issues/15) に記録した。インストール後はまず上の
    `PLUGIN_DIR` コマンドで自己診断すること:`False` が出たら、今回のインストールにはドメイン能力パッケージが入っていない。
    ドメイン能力パッケージを使うなら、いまのところソースの checkout から動かすしかない。

### `setting_sources=[]` がなぜドメイン能力を plugin に追い込むのか {#setting_sources-为什么逼着领域能力走-plugin}

同じ関数の中にこの一行もある:

```python
"setting_sources": [] if portable else ["project"],
```

SDK のデフォルトは `None` = 三つのソースをすべて読む:`~/.claude/settings.json`(ユーザー)、
`.claude/settings.json`(プロジェクト)、`.claude/settings.local.json`(ローカル)。flower はデフォルトで `[]` を渡し、
これらを**すべて切る**。

| | 読むか | 帰結 |
|---|---|---|
| `~/.claude/`(ホストマシン) | 読まない | マシンを変えても挙動が同じ。「自分のマシンでは設定してある」で結果が変わることがない |
| プロジェクトの `.claude/` | 読まない | `.claude/skills/`、`.claude/agents/` に置いたものは flower の下では**一つも効かない** |
| `plugin/` | 読む | パスがコードに固定されており、リポジトリに付いて回る |
| 認証情報 | この経路を通らない | 必ず自前の `.env` を用意する。`~/.claude/settings.json` と `settings.local.json` の `env` ブロックは最後のフォールバックにすぎず、**9 個の認証情報キーしか取らない**。[設定](config.md)を参照 |

`.claude/` が効かないのは**設定漏れではなく、この制約の定義そのもの**だ:ホストマシンから 1 バイトでも読む限り、
「マシンを変えても挙動が同じ」は成り立たない。したがってドメイン能力の通り道は一つしかない ——
リポジトリに付いて回る `plugin/` だ。

スイッチは二つ(どちらも `build_options()` にあり、デフォルト値がポータブルな側):

| 引数 | デフォルト | 変えるとどうなるか |
|---|---|---|
| `portable` | `True` | `False` を渡すと `setting_sources` が `["project"]` になり、プロジェクトの `.claude/` を読み始める(SDK 側:`CLAUDE.md` を読むには `"project"` を含める必要がある)。ポータビリティはそれと引き換えに失われる |
| `use_plugin` | `True` | `False` を渡すと `plugin/` を一切マウントせず、ドメイン能力は `AgentSpec.instructions` 頼みになる |

ついでに:`instructions` は[追記](glossary.md#叠加)(`system_prompt` の `append`)を通り、
plugin とは別の通り道だ —— 前者は毎ターンコンテキストに載り、後者は必要に応じて読み込まれる。
短くて必須の規律は `instructions` に、長くてたまに役立つ知識は skill に書く。

## 三、ドキュメントサイト {#三文档站}

いま読んでいるこのサイトは mkdocs-material で作られており、ソースはリポジトリの `docs/` 配下にある。
`main` に push すれば自動で公開される。

| 要素 | 何か |
|---|---|
| 設定 | `mkdocs.yml`、`docs_dir: docs` |
| 多言語 | `mkdocs-static-i18n`、`docs_structure: folder` —— `docs/zh/`、`docs/en/`……デフォルト言語は `zh` |
| 依存 | `docs-requirements.txt`(バージョン固定)。`pyproject.toml` の `docs` extra **ではない** —— CI が入れるのは前者 |
| ビルド | `mkdocs build --strict`。壊れた内部リンクや、存在しないページを指す nav はビルドを失敗させる。404 を黙って公開したりしない |
| リダイレクト | `hooks/redirects.py`。ビルド**の後**に最終 URL に従って meta-refresh のスタブページを書き、古いフラットなアドレス(`/start/`、`/workflow/`、`/case-ht001/`……)を新しい位置に繋ぐ |
| デプロイ | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`、GitHub Pages に公開 |

ローカルでドキュメントを直すとき:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # 本地预览
mkdocs build --strict         # 提交前跑一遍,和 CI 同一条命令
```

CI のトリガー条件は `main` への push **かつ**変更が以下のパスにヒットすること。加えて Actions ページから手動で
`workflow_dispatch` もできる:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### `install.sh` はなぜ Pages から配るのか {#installsh-为什么从-pages-发}

ビルドステップの末尾にこの一行がある:

```yaml
- run: cp install.sh site/install.sh
```

インストールスクリプトがサイト成果物に押し込まれる。結果としてドキュメントサイトのドメインにぶら下がり、
一行インストールはこうなる:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

理由は極めて実際的だ:**`raw.githubusercontent.com` は中国国内から通らないが、`*.github.io` は通る**(実測)。
スクリプト自体はリポジトリルートに置いてあり、公開時に一部コピーするだけ ——
二つの内容を保守する必要も、追加の CDN も要らない。

`install.sh` 自身がやること:Python のツールインストーラを一つ選び(`uv` > `pipx` > `uv` を入れる > `pip --user`)、
GitHub から flower をインストールし、次の一手を案内する。**認証情報には触れない** —— 初回に `flower` を走らせると聞かれ、
`~/.config/flower/.env` に保存される。
