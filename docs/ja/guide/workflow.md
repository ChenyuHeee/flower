# ワークフローを設計する

フレームワークが面倒を見るのはメカニズムだけだ:1 ステップをどう走らせるか、セッションをどうつなぐか、失敗したらどうするか、コンテキストをどう節約するか。
**[ワークフロー](../reference/glossary.md#流程)を書くのはあなただ** —— フレームワークはあなたがどんなプロジェクトを、どの言語でやっているかを知らないし、知るべきでもない。このページはワークフローの設計方法を扱う。`Step` と `Workflow` の全フィールド表は [Python API](../reference/api.md) にある。

## 何を解決するか {#解决什么问题}

1 回の[ロングホライズン](../reference/glossary.md#长程)実行は、プロンプト 1 文で言い切れる代物ではない:まず要件を詰め、次に調査し、実装し、レビューする。各区間にそれぞれの役割、それぞれのコンテキスト、それぞれの受け入れ条件がある。
これを全部 1 文のプロンプトに書き込むと、モデルはどの区間を飛ばすかを自分で決めてしまう。ワークフローとして書けば、**順序・終了条件・状態の受け渡しが Python コードになる** —— 読めるし、テストできるし、壊れたステップだけ再実行できる。

`Workflow` がやるのは 3 つだけだ:

- 一連の[ステップ](../reference/glossary.md#步骤)を順番に走らせる
- 各ステップが前の何を見えるかを決める(3 種類のセッション接続 + `ctx` という辞書 1 つ)
- いつリトライし、いつ早期終了するかを決める

ドメインの仮定は一切含まない。どこで切るか、各ステップで何を受け入れ条件にするか、通らなかったらどうするか —— この 4 つが「ワークフローを設計する」ということだ。

## 使い方(最小コード) {#怎么用最小代码}

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
        # 新規セッション:prompt に渡したものしか食わない
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # これも新規セッション。前ステップの出力を prompt に注入する(安い・汚染しない)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

`flower run` の引数は `モジュール:属性` あるいは `ファイルパス:属性`。取得したオブジェクトが呼び出し可能ならまず 1 回呼び、`Workflow` を得てから走らせる。走り終わるとターミナルに総コストと実行マニフェストのパスが出る。

ドライバを自分で書いてもいい。`Workflow.run` の第 1 引数は `Runtime` だ:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## 実際に何をしているか {#它实际做了什么}

### Step は何を受け取り、何を返さなければならないか {#一个-step-收到什么必须返回什么}

`Step` は関数ではなく**宣言**だ。実際に走るのは `Runtime.run(step.spec, レンダリングされた prompt, ...)` —— **1 ステップ = 1 回の `Runtime.run` = 1 本の[セッション](../reference/glossary.md#会话)**。

先頭 3 フィールドは位置引数、`Step(name, spec, prompt)`:

- `name` —— ステップ名。これは同時に `ctx` のキー名であり、`runs/manifest.json` の行名であり、プロセスをまたぐ[リネージ](../reference/glossary.md#血缘)のキーでもある。
- `spec` —— どの `AgentSpec` で走らせるか。このステップのツールホワイトリスト、モデル、予算を決める。
- `prompt` —— `str`、または `(ctx) -> str`。呼び出し可能なら現在の `ctx` を受け取る。**前ステップの出力を食わせる一番安い方法がこれだ**(もう 1 つはセッションを接ぐ方法。下記参照)。

このステップが「返す」のは `StepResult` だが、ワークフローの中で手に入るのは 2 つだ:

- `ctx[step.name]` —— 既定では `result.text`。`reduce` を与えた場合は `reduce` の返り値に差し替わる。
- `ctx["_results"][step.name]` —— 完全な `StepResult`(コスト、ターン数、試行回数、`session_id`)。

`result.text` は**メインスレッドの本文しか拾わない**:subagent の発言はそれ自身の transcript にあり、subagent に渡した[タスク指示書](../reference/glossary.md#任务书)は `kind="prompt"`、切断時の合成エラーは `kind="error"` —— この 3 つはいずれも入らない。

### reduce:糖衣ではない {#reduce不是糖}

既定で下流に渡るのはモデルの生の発言だ。ステップによっては、生の発言をそのまま下流に流す**べきではない**:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

実測では、要件確認のステップは 4 セクションのほかに**コード全文を貼り付けてくる**。下流に渡すべきはパース済みの 4 セクションでなければならない。さもないとそのコードの塊が次のステップの prompt に入る。`clarify_step` はこのフィールドで受け止めている。

`reduce` は**同期関数でなければならない**。`gate` / `when` / `on_reject` は async でよい。

### 状態は ctx をどう流れるか {#状态怎么在-ctx-里流动}

`ctx` は `dict[str, Any]` で、`Workflow.context` そのものだ。各ステップが走り終わるとこの表のとおりに書かれる:

| 状況 | `ctx[ステップ名]` | その他 |
|---|---|---|
| `when(ctx)` が False | **書かない**、ステップ丸ごとスキップ | result を生まず、`_results` にも入らない |
| 通過 | `reduce(result, ctx)`、未指定なら `result.text` | |
| 失敗 + `on_fail="stop"`(既定) | **書かない** | `ctx["_failed_at"]` を書き、ワークフロー全体がこのステップで停止 |
| 失敗 + `on_fail="skip"` | **書かない** | そのまま先へ進む |
| 失敗 + `on_fail="continue"` | `result.text`(欠損したまま、**`reduce` は通らない**) | そのまま先へ進む |

通過したかどうかに関わらず `ctx["_results"][ステップ名]` は書かれる。`result.session_id` が空でなければ `ctx["_sessions"]` にも書かれ、リネージにも記録される。

**今回のワークフローが成功したかどうかは `ctx.get("_failed_at")` を見る**。最後のステップに出力があるかどうかではない。

アンダースコアで始まるキーはすべて `Workflow.run` が自分で置くものだ:`_runtime`、`_on_event`、`_sessions`、`_results`、`_lineage`、`_woke`、`_aborted`、`_failed_at`。これらを自分のステップ名に使わないこと。各メカニズムも自前のキーを置く(`_brief` / `_goal` / `_verdict` など)。完全な一覧は [Python API](../reference/api.md) にある。

このうち `_runtime` と `_on_event` は `gate` のためにある:gate は自分で agent を派遣して判定させることができ、その判定過程もそのまま UI に流れる —— そうしないと十数秒のあいだ画面が真っ暗になり、固まったように見える。
[ゴールガード](goal.md)はこうやって実装されている。

`ctx` は同じ dict だ:**同じ `Workflow` オブジェクトを 2 回目に走らせると、前回のキーがまだ残っている**。
きれいにやり直したければ新しく作るか、明示的に `context={}` を渡すこと。

!!! warning "on_fail が skip のとき `ctx[ステップ名]` は書かれない"
    下流で `lambda ctx: ctx["某步"]` と書くとそのまま `KeyError` になる。欠損した結果を持って先へ進みたいなら `on_fail="continue"` を使う。本当にスキップしたいなら、下流が自分で `ctx.get(...)` でフォールバックすること。

### 判定と差し戻し:gate、on_reject、StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` が判断するのは「走り切ったが、合格か」だ。必ず知っておくべき細部が 2 つある:

- **`result.ok` が偽なら `gate` はそもそも呼ばれない**(短絡)。
- **1 回の試行につき 1 回しか呼ばれない**。結論は後で使い回す —— 副作用を持ちうるからだ。`clarify_step` の gate は[要件確認書](../reference/glossary.md#需求确认书)をディスクに書き出すので、重複して発火すれば重複して書き込む。

gate が通らなかったあとどうやり直すかは、`on_reject` を与えたかどうかで決まる:

| | 次のラウンドの走らせ方 | manifest 上の名前 |
|---|---|---|
| `retries` だけ | 最初からやり直し、元の prompt、元の `resume_from` | `X#retry1` |
| `on_reject` も指定 | **今 reject されたそのセッションを続行**、prompt は `on_reject` の返り値に差し替え、`fork` は強制的に False | `X#round2` |

2 つ目は「差し戻して、どこが足りないかを伝えて、続きをやらせる」だ —— すでに済んだ作業もコンテキストもそのまま残る。
`on_reject` が空文字列を返した場合、あるいはその試行がそもそも `session_id` を得ていない場合は、最初からやり直しに退化する。

`gate` は `StepAbort` を投げることもできる。意味は**もう試しても無駄だから残りのラウンドを消費するな**だ:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

投げられたあと:理由が `ctx["_aborted"]` に記録され、このステップは失敗扱いになって `on_fail`(既定は `"stop"`)に従い、**リトライループはその場で break** し、残りの `retries` は 1 回も消費されない。

区別をしっかり覚えること:**False を返すのは「今回はダメ、もう 1 ラウンド」。`StepAbort` は「もう 1 回やっても無駄」。**
典型的な場面は、目標がこの環境では達成不能と判定され、しかも聞ける相手もいないときだ —— 空回りを続けるのが一番高くつく。

### 2 層のリトライを混同しない {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| 何を扱うか | 業務上の失敗:`gate` が通らない、`result.ok` が偽 | インフラ:ネットワークの揺らぎ、切断、5xx |
| どうやり直すか | **ステップ丸ごとやり直し**、同じ prompt と `resume_from` | **中断地点から resume で続行**、それまでのコストは無駄にならない |
| その前に何をするか | 何もしない | DNS + TCP プローブを張ってネットワーク復帰を待つ(HTTP は送らない、資格情報も載せない。プローブは無料でなければならない) |
| リトライ不可なもの | —— | 資格情報エラー、パラメータエラーは即停止、待ち続けない |

続行に使うプロンプトには**意図的にエラーの詳細を一切含めていない** —— モデルが知る必要があるのは「中断された、続きをやれ」であって、ENOTFOUND なのか 503 なのかではない。

### ステップをつなぐ {#把步骤串起来}

ステップ間の状態の受け渡しには 3 種類の接ぎ方があり、どれを選ぶかで次のステップに何が見えるかが決まる:

| 書き方 | 次のステップに見えるもの | 用途 |
|---|---|---|
| `resume_from=None`(既定)+ prompt に注入 | あなたが注入した文字だけ | 各ステップが独立。安い、汚染しない |
| `resume_from="前ステップ名"` | 完全なセッション履歴 | 連続した記憶が必要なとき |
| `resume_from="前ステップ名"` + `fork=True` | 完全な履歴、ただし別ブランチを切る | レビュー / 複数案の並行 / リトライで元の線を汚さない |

`resume_from` が指すステップは**実際に session を生んでいなければならない**。`when` でスキップされた、あるいはそもそも走っていない場合、`Workflow.run` はそのまま `ValueError` を投げる —— 黙って新規セッションに降格したりはしない。それをやると「連続した記憶」という前提が静かに崩れるからだ。

何度も痛い目を見て得た設計上の経験をいくつか:

1. **1 ステップに 1 つの受け入れ可能な目標。** ステップ境界はコンテキスト境界だ:`resume_from=None` の場所では、それ以前のツール結果は完全に常駐しなくなる。[コンテキスト経済学](context.md)を参照。
2. **迷ったらまず `clarify_step`。** ロングホライズンでは「目標を取り違えた」が一番高くつく誤りであり、しかもそれはコンテキストを節約するどの層でも消せない類のものだ。[事前確認](clarify.md)を参照。
3. **派遣するタスクは自己完結させる。** subagent はクリーンなコンテキストで、[コーディネーター](../reference/glossary.md#协调者)が知っていることを知らない。必要な背景はタスク指示書に書くか、どの artifact を読めばいいかを伝えること。
4. **長い出力はディスク経由で、会話経由にしない。** これは既に `WORKER_RULES` に書き込まれている。あなたの `instructions` でそれを打ち消さないこと(「完全なログを貼り戻して見せてくれ」など)。
5. **`gate` はまず硬い条件で止める。** ファイルがあるか、終了コードが 0 か —— 1 行の Python で判定できることにモデルを派遣しない。モデルに判定させたいなら既製の `with_goal` を使う —— これは gate を、独立した[判定者](../reference/glossary.md#判定者)を走らせる実装に置き換えるものだ。gate の中で自作しないこと。
6. **同じリポジトリを並行して変更するなら `worker(isolate=True)`。** 後始末(マージ、worktree の掃除、PR を開く)は今のところあなたのワークフロー側の仕事だ。harness が保証するのは、変更がそれぞれの worktree に落ちることだけ。

### ワークベンチは Workflow に付ける {#工作台要挂在-workflow-上}

ワークフローが[ワークベンチ](../reference/glossary.md#工作台)にファイルを書く場面 —— 典型は `clarify_step(brief_path=...)` —— では、必ず自分で `Workbench` を作り、**同時に** `Workflow.workbench` に付け、かつ `Runtime` にも渡すこと:

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

`channel` を workflow に付ける理由は 2 つある:`run()` がその `on_event` を同じイベント出口につなぐこと(`channel.on_event` がまだ `None` の場合に限る)、そしてドライバがこのフィールドで「誰に答えればいいか」を知ること。

!!! warning "ワークベンチのパスを自分で組み立てると静かに壊れる"
    `Runtime(workbench=True)` の既定位置は `<run_dir>/workbench` だが、`Workbench(ws)` の既定は `<ws>/.flower` —— **この 2 つは同じディレクトリではない**。ワークフローが CLI から呼ばれるとき `run_dir` は見えないので、自分でパスを組み立てても別の場所を指すだけになり、確認書は A ディレクトリに書かれ、注入されるインデックスは B ディレクトリを走査する。**しかもエラーは出ない**。オブジェクトを 1 つ作って両方で共有すればこの問題は起きない。`Workflow.workbench` が存在する場合、コマンドラインの `-W` は無視され、こちらが優先される。

### `continuous=True`:同じパスでもう一度走らせる {#continuoustrue同一个路径再跑一次}

上の 3 種類の接ぎ方は**1 回の実行の内側**でのステップ間の話だ。プロセスをまたぐのは別の軸になる:

```python
Workflow([...], continuous=True)     # 既定値
```

同じワークスペースでもう一度走らせると、各ステップは前回のそのセッションの続きから話す —— `<run_dir>/lineage.json` の「ステップ名 → session_id」に依っている。ロード時には各レコードを `runtime.has_session()` で検証し、session がまだストアにあるかを確かめ、生きているものだけを使う:リネージファイルは `sessions.db` より長生きしうるし、存在しない session を resume すると子プロセスが起動するまで落ちないからだ。

帰結が 3 つある:

- **`resume_from=None` は「まっさらな新規セッション」を意味しない。** 1 回目はそうだが、2 回目はそうではない。毎回新規セッションにしたければ、明示的に `Workflow(..., continuous=False)` と書くこと。
- **[継続](../reference/glossary.md#接续)ではコンテキストが伸び続ける。** 継続時に別のことを言いたいなら `Step.resume_prompt` を与える —— 相手のコンテキストに既にあるものを再送すべきではない。
- 明示的に `resume_from` を書いたステップは影響を受けない。そちらが優先される。

!!! warning "ステップ名はプロセスをまたぐキーだ"
    ステップ名を 1 つ変えれば、そのステップのリネージを切ることになる:次回から継続しなくなり、しかも**エラーは出ない**。`#retry1` / `#round2` の接尾辞が付いたリトライ名は**リネージに入らない**(記録されるのは常に元の名前)。これは「判定者は常に新規セッション」を実現している方法の 1 つでもある。

完全な設計と `--new` については[継続](continuity.md)を参照。

## 使うべきでないとき {#什么时候不该用它}

- **agent を 1 つ走らせるだけで、判定も要らない** —— `Workflow` を被せない。素直に `await rt.run(spec, "…")`、あるいはコマンドラインで `flower once "读一眼这个仓库"`。
- **形が「要件を詰める → 目標を決める → 作業する」そのもの** —— 既製の [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) を使えばいい。自分で書く必要はない:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    これは**3 ステップ**だ:`确认需求` → `设定目标` → `干活`(判定ループ付き、判定ステップの名前は `干活·判定#N`)。
    `goal=False` なら第 2 ステップと判定ループがなくなり、`clarify_only=True` なら第 1 ステップだけが残る。
    `HumanChannel` と `Workbench` を自前で持ち、workflow に付けてあるので、`Runtime(workbench=wf.workbench)` をそのまま使えばいい。別に組み立てないこと。

    コードを書かなくてもいい。プロジェクトディレクトリで `flower "帮我做一个 X"` を走らせれば、これが動く。
    **これは「推奨するワークフロー設計」ではない**。設定ゼロで走り出せるようにしてあるだけだ。

- **ステップを「1 つの受け入れ可能な目標」より細かく切る** —— 純損だ。各ステップは新しいセッションを 1 本立てる必要があり、新しいセッションには起動フロア(コーディネーターの実測で約 34k コンテキスト)があるので、薄まらない。
- **事後に特定のメッセージまで巻き戻したい** —— `Workflow` ではこの道は通れない。`resume_at` を渡すことが一切ないからだ。直接 `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` を呼ぶこと。

役割の選び方(`coordinator` / `worker` / `clarify` / `judge` / `oracle`)、および `Step` と `Workflow` のフィールドごとの意味は [Python API](../reference/api.md) を、用語は[用語集](../reference/glossary.md)を参照。
