# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Claude Agent SDK 上に作られた、ポータブルなロングホライズン agent フレームワーク。</p>

<p class="fl-hero__sub">Claude Code の能力を犠牲にせず、持ち出せて、対話をカスタマイズでき、何日でも走り続けられる専用 agent にする。
メインスレッド上の agent は決定だけを行い、手を動かす作業はすべて subagent に投げる。要件は先に聞き切ってから着手し、できているかどうかは別の役割が判定する。
別のマシンに移しても挙動は同じ —— ホストマシンの設定を読まず、認証情報は自分で持ち歩く。</p>

[クイックスタート](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>1 回の実行のコスト</span></div>
<div class="fl-stat"><b>10.4 時間</b><span>連続実行。途中でネットワークが切れても自力で復帰</span></div>
<div class="fl-stat"><b>185.9K</b><span>メインスレッドのコンテキスト最大値。全期間で圧縮なし</span></div>
<div class="fl-stat"><b>94.8%</b><span>本文文字数が subagent 側に落ちた割合</span></div>
</div>

4 つの数字は [HT001](cases/ht001.md) から —— 1 つの agent が flower の上でゼロから端末 IDE を書き上げた、あの実行のものだ。

## コマンド 1 本で導入、Node 不要 {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

スクリプトが `uv` / `pipx` / `pip` を自動で探して `flower` コマンドを入れる。必要なのは Python ≥ 3.10 だけで、
Claude Code CLI も入れなくていい。入れ終わったら任意のプロジェクトディレクトリに `cd` して `flower` と打つ。初回は API key
かゲートウェイのアドレスを聞かれる。一度設定すれば `~/.config/flower/.env` に保存され、どこでも効く。ローカルにすでに Claude Code が入っていて設定済みなら、
その token をそのまま借りるので、何も聞かれない。手順の全体とトラブルシューティングは[インストール](getting-started/install.md)を参照。

## 4 種類の失敗を防ぐ {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [事前確認](guide/clarify.md) {#前置确认}

作ったものが欲しかったものと違う、という失敗 —— 着手する前に、質問だけして手を動かさない役割が、はっきりするまで聞き切る。要件は 1 通の文書に凍結され、
以降の各ステップはそれを読んで始まる。
</div>

<div class="fl-card" markdown>
### [ゴールガード](guide/goal.md) {#目标看守}

「できました」と言うが実際にはできていない、という失敗 —— 1 ラウンドの作業が終わるたびに別の役割が独立に一度判定する。達成なら次へ、未達成なら差し戻し、
この環境では検証できないなら止まって人に聞く。
</div>

<div class="fl-card" markdown>
### [継続](guide/continuity.md) {#接续}

数時間走ってからクラッシュして最初からやり直し、という失敗 —— 同じディレクトリでもう一度 `flower` と打てば前回の続きから再開する。プロセスが kill されても、
マシンが再起動しても同じで、id を覚えておく必要はない。
</div>

<div class="fl-card" markdown>
### [世代交代](guide/handoff.md) {#换代}

コンテキストが埋まって 1 段落の要約に圧縮される、という失敗 —— いまのセッションが自分で、人が読めて手も入れられる引き継ぎ書を書き、新しいセッションが引き継ぐ。
compact は使わない。
</div>

</div>

## なぜ「ロングホライズン」なのか {#长程}

メインスレッド上の[コーディネーター](reference/glossary.md#协调者)は決定だけを積み、`Write` と `Edit` は持たない ——
コードを書く、テストを走らせる、資料を調べるは全部 [subagent](reference/glossary.md#subagent) に投げる。
subagent の試行錯誤は**別の** transcript に入り、メインスレッドは 30 行を超えないレポートを 1 通受け取るだけだ。
HT001 の 10.4 時間の実行では、**本文文字数の 94.8% が subagent 側に落ち**、
手を動かすツール呼び出し 1,893 回のうちコーディネーターの視界に入ったのは 32 回だけだった。
だからメインスレッドは 70 ターンかけて 185.9K までしか伸びず、全期間で圧縮は一度も起きなかった —— この層をどう作ったか、残り 3 層が何かは、
[コンテキストの経済学](guide/context.md)を参照。

## 実際の長時間実行 2 回の生記録 {#真的跑过}

- **[HT001](cases/ht001.md)** —— ゼロから端末 IDE を書く。$171.62 / 10.4 時間 /
  メインスレッドのコンテキストは 185.9K まで伸び、12,212 行のプロダクトコードを出した。途中で一度ネットワークが切れたが、自力で最後まで走り切った。
- **[HT002](cases/ht002.md)** —— それを macOS に入れて動かす。$38.24 / 約 1 時間、初めてゴールガードを付けた回。
  プログラムは実際に動いたが、判定の結論は**達成不能**で、人に聞くために浮上した。

どちらのページにも、成立していない箇所を書いた。HT001 では agent が自分の受け入れ判定を 1 件間違えている。
HT002 は `git clone && make && ./cppide` に 1 時間かけている。どの数字も `runs/manifest.json`
と `sessions.db` から再計算できる —— 宣伝ではなく記録だ。

## どこから読むか {#从哪读起}

- **すぐ動かしたい** —— [クイックスタート](getting-started/quickstart.md):コマンド 3 本で動かし、
  そのあと画面を流れていくものの読み方を説明する。
- **先に概念を押さえたい** —— [コアコンセプト](getting-started/concepts.md):実行、ステップ、セッション、5 つの役割を、
  5 分で一通り。
- **自分のコードに組み込みたい** —— [Python API](reference/api.md):`Runtime`、`Step`、5 つの役割ファクトリ、
  62 個の公開シンボルのシグネチャとデフォルト値。
