# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Claude Agent SDK 上に構築した、ポータブルな long-horizon agent フレームワーク。</p>

<p class="fl-hero__sub">Claude Code の能力を犠牲にせず、持ち出せて、インタラクションをカスタマイズでき、何日でも走り続けられる専用 agent に変える。
main thread 上の agent は判断だけを行い、手を動かす作業はすべて subagent に委ねる。要件は先に問い詰めてから着手し、完了したかどうかは別の役割が判定する。
別のマシンに移しても挙動は同じ —— ホストマシンの設定は読まず、認証情報は自分で持ち歩く。</p>

[クイックスタート](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>1 回の run の費用</span></div>
<div class="fl-stat"><b>10.4 hours</b><span>連続稼働。途中でネットが切れても自力で復帰</span></div>
<div class="fl-stat"><b>185.9K</b><span>main thread のコンテキスト最大値。全行程で compact なし</span></div>
<div class="fl-stat"><b>94.8%</b><span>本文文字数が subagent 側に落ちた割合</span></div>
</div>

4 つの数字は [HT001](cases/ht001.md) —— ある agent が flower の下でゼロからターミナル IDE を書き上げた、あの run のもの。

## インストール

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

`uv` / `pipx` / `pip` を自動で探して `flower` コマンドを入れる。Python ≥ 3.10 さえあればよく、Node も
Claude Code CLI も要らない。インストール後は任意のプロジェクトディレクトリに `cd` して `flower` と一言叩く。初回は API key
かゲートウェイのアドレスを訊かれる。一度設定すれば `~/.config/flower/.env` に保存され、どこでも効く。すでに Claude Code をインストールして設定済みなら、
そのトークンをそのまま借りるので、何も訊かれない。詳しい手順とトラブルシューティングは[インストール](getting-started/install.md)を参照。

## 4 種類の失敗を肩代わりする

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [clarify](guide/clarify.md)

出来上がったものが望んだものと違うのが怖い —— 着手前に、質問だけして手を動かさない役割が、明確になるまで問い詰め、要件を 1 通の文書に凍結する。
以降のすべての step はそれを読んで開始する。
</div>

<div class="fl-card" markdown>
### [goal guard](guide/goal.md)

「完了しました」と言われても実は終わっていないのが怖い —— 各ラウンドの作業が終わるたびに別の役割が独立に 1 回判定する。達成なら先へ進み、未達成なら差し戻す。
その環境では検証できない場合は止まって人に訊く。
</div>

<div class="fl-card" markdown>
### [continuity](guide/continuity.md)

数時間走ったあとにクラッシュしてゼロからやり直しになるのが怖い —— 同じディレクトリでもう一度 `flower` と叩けば前回の進捗に接続する。プロセスが kill されても、
マシンが再起動しても同じ。id を覚えておく必要はない。
</div>

<div class="fl-card" markdown>
### [handoff](guide/handoff.md)

コンテキストが満杯になって要約 1 段落に潰されるのが怖い —— 現在の session が自分で、人が読めて編集もできる handoff document を書き、新しい session が引き継ぐ。
compact は使わない。
</div>

</div>

## なぜ "long-horizon" なのか

main thread 上の [coordinator](reference/glossary.md#协调者) には判断だけを載せ、`Write` と `Edit` は渡さない ——
コードを書く、テストを走らせる、資料を調べるはすべて [subagent](reference/glossary.md#subagent) に委ねる。
subagent の試行錯誤が入るのは**別の** transcript であり、main thread は 30 行を超えないレポートを 1 通受け取るだけだ。
HT001 の 10.4 hours の run では、**本文文字数の 94.8% が subagent 側に落ちた**。
手を動かす 1,893 回のツール呼び出しのうち、coordinator の視野に入ったのは 32 回だけ。
だから main thread は 70 ラウンドかけてようやく 185.9K に達し、全行程で compact は一度も起きなかった —— この層をどう作ったのか、残る 3 層は何かは、
[コンテキスト経済学](guide/context.md)を参照。

## 実際に走らせた

- **[HT001](cases/ht001.md)** —— ゼロからターミナル IDE を書く。$171.62 / 10.4 hours /
  main thread のコンテキストは 185.9K まで伸び、12,212 行のプロダクトコードを提出。途中で一度ネットが切れたが、自力で最後まで走り切った。
- **[HT002](cases/ht002.md)** —— それを macOS 上にインストールして動かす。$38.24 / 約 1 時間、初めて goal guard を有効化。
  プログラムは確かに起動したが、verdict は**達成不能**で、人に訊くために浮上した。

どちらのページにも、成立していない箇所を書いてある。HT001 では agent が自分の受け入れ判定を 1 件誤り、
HT002 では `git clone && make && ./cppide` に 1 時間かけた。すべての数字は `runs/manifest.json`
と `sessions.db` で再計算できる —— これは生の記録であって、宣伝ではない。

## どこから読むか

- **すぐ動かしたい** —— [クイックスタート](getting-started/quickstart.md):まず 0.2 元ぶんだけ使って認証情報を一発検証し、
  次にコードを書かずに 3 step の workflow を最後まで走らせる。
- **先に概念を掴みたい** —— [コアコンセプト](getting-started/concepts.md):run、step、session、5 つの役割を、
  5 分で一度に説明する。
- **自分のコードに組み込みたい** —— [Python API](reference/api.md):`Runtime`、`Step`、5 つの役割ファクトリ、
  公開シンボル 62 個のシグネチャとデフォルト値。
