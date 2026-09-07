# ワークフローを設計する

フレームワークが面倒を見るのはメカニズムだけだ:1 ステップをどう走らせるか、セッションをどう繋ぐか、失敗したらどうするか、コンテキストをどう節約するか。
**[ワークフロー](../reference/glossary.md#流程)はあなたが書く** —— フレームワークはあなたがどんなプロジェクトで何の言語を使っているかを知らないし、
知るべきでもない。このページではワークフローの設計方法を扱う。`Step` と `Workflow` の全フィールド表は
[Python API](../reference/api.md) にある。

## 何を解決するか

1 回の[long-horizon](../reference/glossary.md#长程)な run は、prompt 一言で言い尽くせるものではない:まず要件を問い詰め、
次に調査し、実装し、レビューする。各段には固有のロール、固有のコンテキスト、固有の受け入れ条件がある。
全部を 1 つのプロンプトに書き込めば、モデルはどの段を飛ばすか自分で決めてしまう。ワークフローとして書けば、
**順序・終了条件・状態の受け渡しがそのまま Python コードになる** —— 読めるし、テストできるし、壊れたステップだけを再実行できる。

`Workflow` がやるのは 3 つだけだ:

- 一連の[ステップ](../reference/glossary.md#步骤)を順番に走らせる
- 各ステップが前の何を見られるかを決める(3 種類のセッションの繋ぎ方 + 1 つの `ctx` 辞書)
- いつリトライし、いつ早期終了するかを決める

そこにドメインの仮定は一切ない。どこで切るか、各ステップで何を検収するか、通らなかったらどうするか —— この 4 つが「ワークフローを設計する」ということだ。

## 使い方(最小コード)

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # 新しいセッション:prompt で渡したものしか食べない
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # これも新しいセッション。前ステップの成果を prompt に注入する(安い、汚染を防ぐ)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

`flower run` の引数は `モジュール:属性` または `ファイルパス:属性` だ。取得したオブジェクトが呼び出し可能ならまず一度呼び、
`Workflow` を得てから走らせる。走り終わるとターミナルに合計コストと run manifest のパスが出る。

自前のドライバを書いてもいい。`Workflow.run` の第一引数は `Runtime` だ:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## 実際に何をしているか

### Step は何を受け取り、何を返さなければならないか

`Step` は関数ではなく、**宣言**だ。実際に実行されるのは `Runtime.run(step.spec, レンダリング済みの prompt, ...)` ——
**1 ステップ = 1 回の `Runtime.run` = 1 本の[セッション](../reference/glossary.md#会话)**。

最初の 3 つのフィールドは位置引数、`Step(name, spec, prompt)`:

- `name` —— ステップ名。これは同時に `ctx` のキー名であり、`runs/manifest.json` の行名であり、
  プロセスをまたぐ [lineage](../reference/glossary.md#血缘) のキーでもある。
- `spec` —— どの `AgentSpec` で走らせるか。このステップのツールのホワイトリスト、モデル、予算を決める。
- `prompt` —— `str`、または `(ctx) -> str`。呼び出し可能なら現在の `ctx` を受け取る。
  **前ステップの成果を流し込む最も安い方法がこれだ**(もう一つはセッションを繋ぐ方法、後述)。

このステップが「返す」のは `StepResult` だが、ワークフローの中で手に入るのは 2 つだ:

- `ctx[step.name]` —— デフォルトは `result.text`。`reduce` を与えれば `reduce` の戻り値に変わる。
- `ctx["_results"][step.name]` —— 完全な `StepResult`(コスト、ターン数、試行回数、`session_id`)。

`result.text` は**メインスレッドの本文だけを拾う**:subagent の発言はそれ自身の transcript の中にあり、subagent に渡した
[タスク指示書](../reference/glossary.md#任务书)は `kind="prompt"`、切断時の合成エラーは `kind="error"`
—— この 3 つはどれも入らない。

### reduce:シンタックスシュガーではない

デフォルトで下流に渡るのはモデルが言った生のテキストだ。ステップによっては、その生のテキストを**そのまま下流に渡すべきではない**:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

実測では、要件確認のステップが 4 つのセクションのほかに**コード全体を貼り付けてくる**。下流に渡すのはパース済みの 4 セクションでなければならず、
さもないとそのコードの塊が次ステップの prompt に入る。`clarify_step` はこのフィールドで受け止めている。

`reduce` は**同期関数でなければならない**。`gate` / `when` / `on_reject` は async でよい。

### 状態は ctx をどう流れるか

`ctx` は `dict[str, Any]` で、`Workflow.context` そのものだ。各ステップが走り終わるたびにこの表のとおり書かれる:

| 状況 | `ctx[ステップ名]` | その他 |
|---|---|---|
| `when(ctx)` が False を返す | **書かない**、ステップ全体をスキップ | result も生まれず、`_results` にも入らない |
| 通過 | `reduce(result, ctx)`、与えていなければ `result.text` | |
| 失敗 + `on_fail="stop"`(デフォルト) | **書かない** | `ctx["_failed_at"]` を書き、ワークフロー全体がこのステップで止まる |
| 失敗 + `on_fail="skip"` | **書かない** | そのまま先へ進む |
| 失敗 + `on_fail="continue"` | `result.text`(欠けたもの、**`reduce` は通さない**) | そのまま先へ進む |

通ったかどうかに関係なく `ctx["_results"][ステップ名]` は必ず書かれる。`result.session_id` が空でなければ
`ctx["_sessions"]` にも書かれ、lineage にも記録される。

**この run が成功したかどうかは `ctx.get("_failed_at")` を見て判断する**。最後のステップに出力があるかどうかではない。

アンダースコアで始まるキーはすべて `Workflow.run` が自分で入れるものだ:`_runtime`、`_on_event`、`_sessions`、`_results`、
`_lineage`、`_woke`、`_aborted`、`_failed_at`。これらを自分のステップ名にしないこと。各メカニズムも自前のキーを入れる
(`_brief` / `_goal` / `_verdict` など)。完全な一覧は [Python API](../reference/api.md) にある。

うち `_runtime` と `_on_event` は `gate` のためにある:gate は自分で agent を 1 つ派遣して判定させることができ、
その判定の過程もちゃんと UI に出る —— そうしないと十数秒のあいだ画面が真っ暗で、固まったように見える。
[ゴールガード](goal.md)はこうやって実装されている。

`ctx` は同じ dict だ:**同じ `Workflow` オブジェクトを 2 回走らせると、前回のキーがまだ残っている**。
きれいにやり直したいなら新しく作るか、明示的に `context={}` を渡す。

!!! warning "on_fail に skip を選ぶと `ctx[ステップ名]` は書かれない"
    下流で `lambda ctx: ctx["あるステップ"]` と書くとそのまま `KeyError` になる。欠けた結果を持って先へ進みたいなら
    `on_fail="continue"` を使う。本当にスキップしたいなら、下流で自分で `ctx.get(...)` を使って自衛すること。

### 判定と差し戻し:gate、on_reject、StepAbort

`gate(result, ctx) -> bool` が判定するのは「走り終わった、で、合格か」だ。知っておくべき点が 2 つある:

- **`result.ok` が偽のとき `gate` はそもそも呼ばれない**(短絡)。
- **1 回の試行につき 1 回しか呼ばれない**。結論は取っておいて後で使う —— 副作用があり得るからだ。`clarify_step` の gate は
  [要件確認書](../reference/glossary.md#需求确认书)をディスクに書き出すので、繰り返し発火すれば繰り返し書き込む。

gate が通らなかったあとどう再実行するかは、`on_reject` を与えたかどうかで決まる:

| | 次のラウンドの走り方 | manifest 上の名前 |
|---|---|---|
| `retries` だけ | 最初からやり直し。元の prompt、元の `resume_from` | `X#retry1` |
| `on_reject` も付ける | **いま否決されたそのセッションを続けて走らせる**。prompt は `on_reject` の戻り値に差し替わり、`fork` は強制的に False | `X#round2` |

2 つ目は「差し戻して、どこが足りないかを伝えて、続きを埋めさせる」だ —— すでに終わった作業もコンテキストもそのまま残っている。
`on_reject` が空文字列を返した場合、あるいはその試行がそもそも `session_id` を取れなかった場合は、最初からやり直しに縮退する。

`gate` は `StepAbort` を投げることもできる。意味は**もう試しても無駄だ、残りのラウンドを消費するな**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

投げたあと:理由は `ctx["_aborted"]` に記録され、このステップは失敗として扱われて `on_fail`(デフォルト `"stop"`)に従う。
**リトライループはその場で break** し、残りの `retries` は 1 回も消費されない。

違いを覚えておくこと:**False を返すのは「今回はダメ、もう 1 ラウンド」。`StepAbort` は「もう 1 回やっても無駄」だ。**
典型的な場面は、目標がこの環境では達成不能だと判定され、しかも誰にも聞けないとき —— そのまま空回りを続けるのがいちばん高くつく選択肢だ。

### 2 層のリトライを混同しない

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| 何を扱うか | 業務的な失敗:`gate` が通らない、`result.ok` が偽 | インフラ:ネットワークの揺らぎ、切断、5xx |
| どう再実行するか | **ステップ全体をやり直す**。同じ prompt と `resume_from` | **中断地点から resume して続ける**。それまでのコストは無駄にならない |
| その前に何をするか | 何もしない | DNS + TCP プローブを張ってネットワークの復帰を待つ(HTTP は投げない、資格情報も載せない。プローブは無料でなければならない) |
| リトライしないもの | —— | 資格情報エラー、パラメータエラーは即座に停止し、待ち続けない |

resume に使う prompt は**意図的にエラーの詳細を一切含まない** —— モデルが知る必要があるのは「中断された、続けろ」であって、
ENOTFOUND なのか 503 なのかを知る必要はない。

### ステップをつなぐ

ステップ間で状態を渡す繋ぎ方は 3 つあり、どれを選ぶかで次のステップに何が見えるかが決まる:

| 書き方 | 次のステップに見えるもの | どこで使うか |
|---|---|---|
| `resume_from=None`(デフォルト)+ prompt に注入 | 注入した文字だけ | 各ステップが独立。安い、汚染を防ぐ |
| `resume_from="前のステップ名"` | セッション履歴すべて | 一貫した記憶が要るとき |
| `resume_from="前のステップ名"` + `fork=True` | 履歴すべて、ただし別のブランチを開く | レビュー / 複数案の並行 / リトライで元の線を汚さない |

`resume_from` が指すそのステップは**実際に session を生んでいなければならない**。`when` でスキップされた、あるいはそもそも走っていない場合、
`Workflow.run` はそのまま `ValueError` を投げる —— 黙って新しいセッションに縮退させたりはしない。それをやると「一貫した記憶」という仮定が
こっそり崩れるからだ。

何度も痛い目を見て得た設計上の経験をいくつか:

1. **1 ステップに検収可能な目標を 1 つ。** ステップ境界はそのままコンテキスト境界だ:`resume_from=None` のところでは、
   それ以前のツール結果はもう常駐しなくなる。[コンテキストの経済学](context.md)を見よ。
2. **迷ったらまず `clarify_step`。** long-horizon では「目標を取り違えた」がいちばん高くつく誤りで、
   しかもそれはコンテキストを節約するあの数層がどうしても消せない類のものだ。[事前確認](clarify.md)を見よ。
3. **派遣するタスクは自己完結させる。** subagent はクリーンなコンテキストで、[コーディネーター](../reference/glossary.md#协调者)が
   知っていることを知らない。必要な背景はタスク指示書に書くか、どの artifact を読めばいいか伝える。
4. **長い成果物はディスクを通す、会話に戻さない。** これはすでに `WORKER_RULES` に書いてある。あなたの `instructions` で
   それを打ち消さないこと(「完全なログを貼り戻して見せて」など)。
5. **`gate` はまず硬い条件で止める。** ファイルがあるか、終了コードが 0 か —— Python 1 行で判定できるものにモデルを派遣しない。
   モデルに判定させたいなら既製の `with_goal` を使う —— gate を、独立した
   [判定者](../reference/glossary.md#判定者)を走らせる実装に差し替えてくれる。自分で gate の中に手作りしないこと。
6. **同じリポジトリを並行で書き換えるなら `worker(isolate=True)`。** 後始末(マージ、worktree の掃除、PR を開く)は今のところ
   あなたのワークフロー自身の仕事で、harness が保証するのは変更がそれぞれの worktree に落ちることだけだ。

### ワークベンチは Workflow に付ける

ワークフローが[ワークベンチ](../reference/glossary.md#工作台)にファイルを書く場面 —— 典型的には
`clarify_step(brief_path=...)` —— では必ず自分で `Workbench` を 1 つ作り、**同時に** `Workflow.workbench` に付け、
かつ `Runtime` にも渡すこと:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

`channel` を workflow に付ける理由は 2 つある:`run()` がその `on_event` を同じイベント出口につなぐ
(`channel.on_event` がまだ `None` のときに限る)ため、そしてドライバがこのフィールドを見て誰に答えればいいかを知るためだ。

!!! warning "ワークベンチのパスを自分で組み立てると黙って壊れる"
    `Runtime(workbench=True)` のデフォルト位置は `<run_dir>/workbench`、`Workbench(ws)` のデフォルトは
    `<ws>/.flower` —— **この 2 つは同じディレクトリではない**。ワークフローが CLI から呼ばれるときは `run_dir` が見えないので、
    自分でパスを組み立てても別の場所を指すだけになる。結果として確認書は A ディレクトリに書かれ、注入されるインデックスは
    B ディレクトリを走査する。**しかもエラーにならない**。
    オブジェクトを 1 つ作って両方で共有すればこの問題は起きない。`Workflow.workbench` があるときはコマンドラインの `-W` は無視され、
    そちらが優先される。

### `continuous=True`:同じパスでもう一度走らせる

上の 3 つの繋ぎ方は**1 回の run の中**でのステップ間の話だ。プロセスをまたぐのは別の軸になる:

```python
Workflow([...], continuous=True)     # デフォルト値
```

同じワークスペースでもう一度走らせると、各ステップは前回のそのセッションの続きから話す —— `<run_dir>/lineage.json` の中の
「ステップ名 → session_id」による。ロード時には各レコードを `runtime.has_session()` に通して session がまだストアにあるか検証し、
生きているものだけを使う:lineage ファイルは `sessions.db` より長生きすることがあり、存在しない session を resume すると
子プロセスが起動するまで落ちない。

結果は 3 つ:

- **`resume_from=None` は「まっさらな新セッション」を意味しない。** 初回はそうだが、2 回目はそうではない。毎回新しいセッションにしたいなら、
  明示的に `Workflow(..., continuous=False)` と書く。
- **[継続](../reference/glossary.md#接续)ではコンテキストが増え続ける。** 継続時に別のことを言いたいなら
  `Step.resume_prompt` を与える —— 相手のコンテキストにすでにあるものを再送すべきではない。
- 明示的に `resume_from` を書いたステップは影響を受けない。そちらが優先される。

!!! warning "ステップ名はプロセスをまたぐキーだ"
    ステップ名を 1 つ変えれば、そのステップの lineage は切れる:次回から継続しなくなり、しかも**エラーにならない**。`#retry1` /
    `#round2` のサフィックスが付いたリトライ名は**lineage に入らない**(記録されるのは常に元の名前だ)。これは「判定者は常に新しいセッション」を
    実現している方法の 1 つでもある。

完全な設計と `--new` は[継続](continuity.md)を見よ。

## 使うべきでないとき

- **agent を 1 つ走らせるだけで、判定も要らない** —— `Workflow` を被せない。素直に `await rt.run(spec, "…")`、
  あるいはコマンドラインで `flower once "读一眼这个仓库"`。
- **形がまさに「要件を問い詰める → 目標を決める → 作業する」** —— 既製の
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) を使えばよく、
  自分で書く必要はない:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    これは**3 ステップ**だ:`确认需求` → `设定目标` → `干活`(判定ループ付き、判定ステップの名前は `干活·判定#N`)。
    `goal=False` のときは 2 つ目のステップと判定ループがなく、`clarify_only=True` のときは最初のステップだけが残る。
    `HumanChannel` と `Workbench` を自前で持って workflow に付けているので、
    `Runtime(workbench=wf.workbench)` をそのまま使えばいい。別に組み立てないこと。

    コードを書かなくてもいい。プロジェクトディレクトリで `flower "帮我做一个 X"` を実行すれば走るのがこれだ。
    **これは「推奨されるワークフロー設計」ではない**。ゼロ設定で走り出せるようにするためだけのものだ。

- **ステップを「1 つの検収可能な目標」より細かく切る** —— 純粋な損だ。ステップごとに新しいセッションを起こす必要があり、
  新しいセッションには起動フロア(コーディネーターの実測で約 34k コンテキスト)があって、薄められない。
- **あとから特定のメッセージまでロールバックしたい** —— `Workflow` ではこの道は通れない。`resume_at` を渡すことが決してないからだ。
  直接 `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` を呼ぶ。

ロールの選び方(`coordinator` / `worker` / `clarify` / `judge` / `oracle`)、`Step` と `Workflow` の
フィールドごとの意味は [Python API](../reference/api.md) を、用語は[用語集](../reference/glossary.md)を見よ。
