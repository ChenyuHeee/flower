# Python API

このページは `flower` のトップレベル `__all__` にある **62 個の公開シンボル**を網羅する:シグネチャ、引数、デフォルト値、意味、
公開属性とメソッド。読み終えたら引数を探すためにソースを開く必要はない。

構成は**関心事**ごとに分けてあり、モジュールファイルごとではない ——「[協調者](glossary.md#协调者)が
自分で手を動かすのをどう止めるか」を知りたいなら [hook 層](#hook)へ;「前のステップの結果をどう次に渡すか」なら[フロー](#流程)へ。
用語はすべて[用語集](glossary.md)に従う。

バージョン `0.1.0`、依存は `claude-agent-sdk>=0.2.152`。すべてのシグネチャはソースと逐語対応する。

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## このページの内容 {#索引}

| 関心事 | シンボル |
|---|---|
| [agent を 1 つ走らせる](#运行时) | `Runtime` `StepResult` |
| [複数ステップをつなぐ](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [役割を作る](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [agent 定義を手書きする](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [構造化された文書](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [ツールを止め、結果を裁剪し、隔離を分ける](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [落盤用の作業ディレクトリ](#工作台) | `Workbench` |
| [session をどう保存し、何を保存するか](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [ネットが切れたらどうするか](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [UI を差し替える](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [プロセスをまたいで前回に接続する](#血缘) | `Lineage` |

## 噛みつく 6 つのデフォルト値 {#危险默认值}

この 6 条は些末な話ではなく、最も頻繁に起きる 6 種類の事故だ。各条は対応する節に完全な説明がある。

| デフォルト値 | 結果 | 詳細 |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | main thread の `Bash`/`Write`/`Edit` に **hook が 1 つもかからない** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | spec に強制的に `CompactPolicy(mode="no_summary")` を付ける。つまり `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | `resume_from=None` のステップでもプロセスをまたいで前回の session に接続してしまう | [Workflow](#workflow) |
| `build_options(fork=True)` に `resume` を渡さない | 黙って無効化される。エラーも出ない | [build_options](#build-options) |
| `clarify(max_turns=<小さい数>)` | 「質問回数は無制限」を空文句にする —— 質問 1 回がそのまま 1 ターン | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | session 単位。subagent もまとめて禁止される | [AgentSpec](#agentspec) |

---

## ランタイム {#运行时}

ソース:[`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` は実行の中核だ。ワークスペース、[session store](glossary.md#会话存储)、[workbench](glossary.md#工作台)、
[resilience](glossary.md#韧性) 方針、[handoff](glossary.md#换代) 方針を保持し、外向きの動詞は 1 つだけ:1 ステップを `run` する。
リトライ、中断後の再開、コンテキストが満杯になったときの handoff、すべてこの 1 呼び出しの中で完結する。

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

コンストラクタ引数は**すべて keyword-only**(`*` が先頭にある)で、`workspace` は必須。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `str \| Path` | 必須 | agent の `cwd`。構築時に resolve して `mkdir(parents=True, exist_ok=True)` する。SDK の `project_key` はここから導出される —— ディレクトリを別の場所へコピーすると、古い `session_id` は引けなくなる |
| `run_dir` | `str \| Path` | `"runs"` | `sessions.db`、`manifest.json`、`lineage.json` を置く場所。`workbench=True` のときのデフォルト workbench もここ。同じく resolve して mkdir する |
| `portable` | `bool` | `True` | `build_options(portable=)` にそのまま渡す。すなわち `setting_sources=[]`:ホストの `~/.claude/` も、プロジェクトの `.claude/` も読まない。[portable](glossary.md#可移植) を参照 |
| `trim` | `TrimPolicy \| bool` | `False` | インスタンスを渡せばそのまま使う;`bool` を渡すと `TrimPolicy(enabled=bool(trim))`。**切っても大きな結果を裁剪しなくなるだけで、剪除は行われる** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | 変換ルールは上と同じ。`coordinator(glance=True)` と対になる —— main thread に `git status` を走らせるなら、その結果が期限切れになることを保証しなければならない |
| `keep_denials` | `int` | `1` | `PrunePolicy(keep_denials=)` に渡す。直近 N 回の拒否されたツール呼び出しを残し、それ以前は呼び出しと結果ごと取り除く |
| `workbench` | `Workbench \| bool` | `False` | インスタンスを渡せばそのまま使う;`True` を渡すと `Workbench(workspace, home=run_dir / "workbench")` を作る(**デフォルトではワークスペースの外に置かれる**)。その直後に `refresh()` する |
| `spill_threshold` | `int \| None` | `4000` | ツール結果が何文字を超えたら[落盤](glossary.md#落盘)するか。`None` または `0` = `spill_guard` を付けない |
| `resilience` | `Resilience \| bool` | `True` | 変換ルールは同じ |
| `handoff` | `HandoffPolicy \| bool` | `True` | 変換ルールは同じ |

**session store はハードコードされている**:常に
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`。
コンストラクタ引数にバックエンドを差し替える口は**用意されていない** —— 差し替えるなら自分で `AgentSpec` + `build_options(session_store=...)` を組むか、
構築後に `rt.store` を上書きする。

構築の最後の 2 ステップは `load_dotenv()` と `check_credentials()` で、**後者はエラーがあれば `raise RuntimeError`**。
認証情報がない場合は構築段階で落ちる。`run()` まで待たない。

!!! warning "`workbench=False` + `coordinator()` = main thread に壁が 1 枚もない"
    `delegate_guard` は `workbench_hooks` の中でしか付かず、`workbench_hooks` は `self.workbench is not None`
    のときにしか呼ばれない;`whitelist_guard` のほうは `if not spec.delegate_only` でスキップされる。そして `coordinator()` は常に
    `delegate_only=True` を立て、デフォルトの `glance=True` が `Bash` を許す。

    **結論:協調者を `Runtime(workbench=False)` と組み合わせると、その `Bash`/`Write`/`Edit` を止める hook は一切ない。**
    `coordinator()` を使うなら `workbench` を有効にすること —— `Runtime(..., workbench=True)` か、
    `Workbench` インスタンスを渡す。

!!! warning "`handoff=True`(デフォルト)は auto-compact を強制的に切る"
    `_attempt` の中:`handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`、
    子プロセスに落ちると `DISABLE_AUTO_COMPACT=1` になる。理由は、2 つの仕組みを同時に動かすと、コンテキストが減ったのがどちらの仕業なのか説明できなくなるからだ。

    **代償:handoff document を書くステップには必ず縮退経路が要る**(`handoff.degraded`)。compact という受け皿がもうないからだ。
    auto-compact を残したいなら `AgentSpec.compact` を明示的に渡す(spec 側が指定していればそれを尊重し、上書きしない)。

#### 公開属性 {#runtime-属性}

| 属性 | 型 | 説明 |
|---|---|---|
| `workspace` | `Path` | resolve 済みのワークスペース |
| `run_dir` | `Path` | resolve 済みの run ディレクトリ |
| `portable` | `bool` | そのまま保持 |
| `store` | `PruningSessionStore` | session store。バックエンドを替えたければ構築後に上書きするしかない |
| `resilience` | `Resilience` | 正規化済みインスタンス |
| `handoff` | `HandoffPolicy` | 正規化済みインスタンス |
| `workbench` | `Workbench \| None` | `workbench=False` のときは `None` |
| `spill_threshold` | `int \| None` | そのまま保持し、`_attempt` の中で `workbench_hooks` に渡す |
| `results` | `list[StepResult]` | このプロセスで走ったすべてのステップを順に追加する |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`。**インスタンスごとに一意でなければならない** —— `manifest.json` は `run` フィールドで重複排除するので、2 つの id が衝突すると後から書いたほうが相手の行を自分の前回分と誤認して削除する |
| `on_session` | `Callable[[str], None] \| None` | 新しい `session_id` を得た**即座に**コールバックする。デフォルトは `None`。**`runtime.run` のその一文にだけ被せるべきだ** —— [判定者](glossary.md#判定者)が同じ `Runtime` を使う場合、gate の間も掛けたままだと判定者の session が作業ステップの[血縁](glossary.md#血缘)に書き込まれてしまう |

クラス定数:`INTERRUPTED = "interrupted-by-human"`、`HANDOFF_DUE = "context-full-handoff"`、
`INTERRUPT_NOTE`(中断からの再開時に人の発言の後ろに付ける一節。「当時飛んでいたツール呼び出しが interrupted を返すのは
中断の正常な副作用であって、環境障害ではない」と説明する)。

#### 公開メソッド {#runtime-方法}

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | 1 ステップ走らせる。下記参照 |
| `interrupt` | `(message: str = "") -> None` | 現在のターンの中断を要求する。**どのスレッドからでも呼べる**。協調的:**メッセージ境界**でクリーンに切り、強制キャンセルはしない。空文字列 = 中断だけして何も言わない |
| `rescue` | `() -> None` | 強制終了される前にできる限り帳簿を残す。`SIGHUP`/`SIGTERM` ハンドラから呼ぶ。飛行中のステップも manifest に書き、`error="killed-by-signal"` とする。同期的な小さい書き込みしかしない |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())` の中の `/`、`_`、`.` をすべて `-` に置換したもの。**SDK が cwd から導出するので、呼び出し側では指定できない** |
| `has_session` | `(session_id: str) -> bool` | この id は**このワークスペース**下でまだ引けるか。同期、payload は読まない |
| `context_of` | `(session_id: str) -> int` | ある session の最終ターンのコンテキスト規模。`store.last_context` に委譲する |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `spec` | `AgentSpec` | 必須、位置引数 | 走らせる agent の宣言 |
| `prompt` | `str` | 必須、位置引数 | このターンで話す内容 |
| `step_name` | `str \| None` | `None` | `StepResult.step`、manifest、血縁に載るキー。`None` → `spec.name` |
| `resume` | `str \| None` | `None` | この `session_id` を再開する |
| `fork` | `bool` | `False` | 新しい session に分岐し、元の session を汚さない。**`resume` が真のときにのみ効く** |
| `resume_at` | `str \| None` | `None` | あるメッセージ位置から再開する(巻き戻し)。同じく**`resume` が真のときにのみ効く** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | イベントの出口。[`Event`](#event) を参照 |

各ステップの冒頭でコンテキストの水位をゼロに戻す(`self._ctx, self._warned = 0, False`)。その後はループで、出口は 4 つ:

1. **成功** → 抜ける。
2. **人による中断**(`result.error == INTERRUPTED`)→ **`max_attempts` の制約を受けず**、ネットワークも待たない。
   人の発言を携えて同じ session を `resume` し、`attempt -= 1`(中断は失敗した試行に数えない)、prompt = 人の発言 + `INTERRUPT_NOTE`。
   **`session_id` を得られていなければ止まるしかない**。
3. **コンテキスト満杯**(`result.error == HANDOFF_DUE`、または `handoff.enabled` かつ `session_id` を取得済みかつ
   `is_overflow(...)` が成立)→ **これも `max_attempts` の制約を受けない**。まず `len(result.retired) >= handoff.max_generations` を確認し、
   超えていれば error を診断メッセージに差し替えて抜ける;そうでなければ[handoff document](glossary.md#交接书)を書く → `resume=None, fork=False`
   (**まったく新しい session**)→ prompt を `h.prompt_block()` に差し替え → 水位をゼロに戻す → `attempt -= 1`。
4. **リトライ可能な障害** → `not resilience.enabled or attempt >= max_attempts` なら抜ける;
   `classify(error)` がリトライすべきでないと判定しても抜ける;そうでなければ `Event("retry")` を送り、`wait_online()` でネットワークを待ち、
   `sleep(delay_for(attempt))`;**`session_id` を得ていれば `resume` で再開する**(prompt は
   `resilience.resume_prompt` に差し替え)、そして `result.resumed` を `True` にする。

締めくくり:`ended_at` を書き、`self.results` に追加し、`manifest.json` を書く。

`manifest.json` は**append** の意味論を持つ:書くたびにディスクを読み直し、`run` フィールドで重複排除する(自分の行は新しいものに差し替え、他人の行は残す)。
そのため同じ `run_dir` の下で flower を 2 つ並行に走らせても安全だ —— `run_id` が衝突しないことが前提。

**handoff の観測点は 3 つ**(いずれも `Event("handoff")` で、`payload["phase"]` で区別する):
`near`(`warn_at` に近づいた。世代ごとに 1 回だけ送る)、`writing`(handoff を書いている最中。十数秒かかる)、
`done`(payload に `degraded` / `path` / `sections` が付く)。handoff を書くターンは
`replace(spec, max_budget_usd=None)` で走らせる —— handoff は必ず書き切れなければならず、予算で詰まってはいけないからだ;
かつ `on_event=None` で、このターンは UI に流さない。

handoff は `<workbench.notes>/交接-<步骤名>.md` に落ちる;**workbench がなければ落盤しない**。文書はそれでも prompt を通じて
引き継ぎ手に渡されるが、後から見返すことはできない。古い handoff は `notes/archive/交接/<名>-<时间戳>.md` へ移される。

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

1 ステップ走り終えた全部の帳簿。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `step` | `str` | 必須 | ステップ名(`step_name` または `spec.name`) |
| `session_id` | `str \| None` | `None` | **常に最後に引き継いだ session** —— 途中の handoff で燃やしたものは `retired` にある |
| `ok` | `bool` | `False` | このステップが成功したか |
| `cost_usd` | `float` | `0.0` | ドル。リトライと handoff をまたいで**累加**される |
| `num_turns` | `int` | `0` | ターン数。同じく累加 |
| `text` | `str` | `""` | **main thread の本文のみを含む**。subagent の発言はそれ自身の transcript に残り、subagent に渡した task brief は `kind="prompt"` で、どちらも入らない |
| `error` | `str \| None` | `None` | 失敗理由。特殊値は `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` を参照 |
| `started_at` / `ended_at` | `float` | `0.0` | Unix タイムスタンプ |
| `attempts` | `int` | `1` | 実際の試行回数。中断と handoff は**数えない** |
| `errors` | `list[str]` | `[]` | 集めた合成 API エラーメッセージ。**`text` には入らない** |
| `resumed` | `bool` | `False` | 途中で resume による再開をしたか |
| `retired` | `list[str]` | `[]` | このステップの handoff で燃やした `session_id`、順序どおり |
| `context` | `int` | `0` | 最終ターンで main thread が実際に見たコンテキスト規模。すなわち handoff の判定材料 |

| 属性 | 型 | 説明 |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`。走り終えていなければ `0.0` |

---

## ワークフロー {#流程}

ソース:[`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[ワークフロー](glossary.md#流程)は順番に繋いだ一連の[ステップ](glossary.md#步骤)と、ステップ間で状態をどう渡すか、
いつ早期に抜けるかを加えたもの。**フレームワークは出来合いのワークフローを提供しない。ワークフローは自分で書くもの** ——
`starter_flow` は動くサンプルにすぎない。

型エイリアス `Ctx = dict[str, Any]`(`flower.workflow.base.Ctx`、`flower.workflow.__all__` にはあるが、
トップレベルの `__all__` にはない)。

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

ステップの**宣言**。`Step` 自体は関数ではない —— 実際に実行するのは `Runtime.run(step.spec, prompt, ...)`。
最初の3つのフィールドは位置引数なので、`Step("取词", terse, "读 seed.txt …")` は正しい書き方。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ステップ名。**プロセスをまたいで安定なキー** —— `ctx[name]`、`ctx["_results"]`、manifest、リネージに落ちる。改名 = リネージが切れる |
| `spec` | `AgentSpec` | 必須 | どの agent を走らせるか |
| `prompt` | `str \| Callable[[Ctx], str]` | 必須 | 何を言うか。クロージャにして `ctx` を受け取りその場で組み立ててもよい |
| `resume_from` | `str \| None` | `None` | どのステップのセッションを継続するか。指した先がセッションを生んでいなければ**`ValueError` を投げる**。黙ってスキップはしない |
| `fork` | `bool` | `False` | `resume_from` の上で分岐する。**`resume_from` がなければ無効** |
| `retries` | `int` | `0` | gate を通らなかったとき最大何回やり直すか。`retries=0` = 1ラウンドのみ |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | 今回を合格とみなすか判定する。**async でもよい**。`False` を返すと失敗扱い。**1回の試行につき1度だけ呼ばれる** —— 副作用(ブリーフをディスクに書くなど)を持ちうるので、重複して発火させてはならない |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`、下記参照 |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | `False` を返すと**ステップ全体をスキップ**:result を生まず、`ctx["_results"]` にも入らない。**async でもよい** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | gate を通らなかったとき**次ラウンドで何を言うか**。**async でもよい**。これを与えるとリトライの意味が変わる、下記参照 |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | 継続する(最初からやり直すのではない)ときに使う prompt |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | `ctx[name]` に何を置くかを決める。デフォルトは `result.text` の原文。**同期関数でなければならない** |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | `resuming` かつ `resume_prompt` があれば後者、なければ `prompt`;呼び出し可能オブジェクトなら `ctx` を渡して呼ぶ |

**セッションの3つの繋ぎ方**(同一 run 内):

| 書き方 | 効果 |
|---|---|
| `resume_from=None`(デフォルト) | 新しいセッション。prompt に渡した文脈だけが頼り。安く、隔離される。**ただし `Workflow(continuous=True)` の場合はプロセスをまたぐリネージから同名ステップのセッションを取ってくる** |
| `resume_from="上一步名"` | 同じセッションを継続、文脈は完全。高く、一貫する |
| `resume_from="上一步名", fork=True` | 分岐し、元のセッションを汚さない。レビューや複数案の並行に使う |

**`on_reject` はリトライの意味を変える**:

- 与えない → 次の試行は**最初からやり直す**(同じ prompt、同じ `resume_from`)。
- 与える → 次の試行は**却下されたそのセッションを継続**し、prompt はその戻り値に差し替わり、`fork` は強制的に `False`。
- 空文字列を返す → 差し戻さず、最初からやり直しに退化する。
- `result.session_id` が `None` → これも最初からやり直しに退化する。

**`on_fail` の3つの値**:

| 値 | 挙動 |
|---|---|
| `"stop"`(デフォルト) | `ctx["_failed_at"] = name` を書き、**ワークフロー全体を中断** |
| `"skip"` | 次のステップへ飛ぶ。**`ctx[name]` は書かれない** —— 下流の `lambda ctx: ctx["某步"]` は `KeyError` になる |
| `"continue"` | `ctx[name] = result.text`、欠けた結果を抱えたまま先へ進む |

通ったかどうかに関わらず `ctx["_results"][name] = result` は必ず書かれる;`result.session_id` が空でなければ
さらに `ctx["_sessions"]` に書かれ、`lineage.remember(...)` される。

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

一連の `Step` を順に走らせ、最終的な `ctx` を返す。`steps` は位置引数なので `Workflow([...])` は正しい。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `steps` | `list[Step]` | 必須 | 順番に実行する |
| `name` | `str` | `"workflow"` | ワークフロー名 |
| `context` | `Ctx` | `{}` | 初期コンテキスト辞書。**同じ `Workflow` を2度走らせると ctx は同じ dict** |
| `channel` | `HumanChannel \| None` | `None` | 止まって人に聞く必要があるときここに挿す。`run()` はその `on_event` を同じ出口へ自動で繋ぐ、**ただし `channel.on_event is None` のときだけ**;ドライバもこのフィールドで誰に答えればよいかを知る |
| `workbench` | `Workbench \| None` | `None` | ワークフローが指定するワークベンチ。ドライバが見つけられるようにするためのもの |
| `continuous` | `bool` | `True` | 同じパス = 同じ会話。実体は [`Lineage`](#lineage) |

| `run()` の引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `runtime` | `Runtime` | 必須・位置引数 | どのランタイムで走らせるか |
| `on_event` | `Callable[[Event], None] \| None` | `None` | イベント出口。各 `Runtime.run` にそのまま渡す |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | 1ステップ終わるごとに1回コールバック |

!!! warning "`continuous=True` がデフォルト、`resume_from=None` は新規セッションを意味しない"
    継続が有効なとき、`run()` はまず `Lineage.open(run_dir, workspace)` し、次に各レコードを1件ずつ
    `runtime.has_session(sid)` でまだストアに存在するか検証し、生きているものだけを `ctx["_sessions"]` に流し込む。したがって
    **`resume_from=None` のステップも前回のセッションの続きとして話す** —— プロセスが kill されても、マシンが再起動しても同じ。

    毎回新しいセッションにしたいなら、明示的に `Workflow(..., continuous=False)` と書く。
    さらに:**ステップ名はプロセスをまたいで安定なキーであり、ステップ名を変えるとリネージが切れる。**

`run()` が ctx に書き込む**プライベートキー**(すべて `_` 始まりで、ステップ名と衝突しない):

| キー | 内容 |
|---|---|
| `_runtime` | 渡された `Runtime`。**gate の中で agent を派遣するにはこれが要る** |
| `_on_event` | イベント出口。gate の中の agent も UI に出せなければ画面が真っ暗になる |
| `_sessions` | `dict[ステップ名, session_id]`、`setdefault` で取る |
| `_results` | `dict[ステップ名, StepResult]` |
| `_lineage` | `Lineage` オブジェクト。`continuous=True` かつ runtime に `run_dir` + `workspace` があるときだけ存在 |
| `_woke` | `lineage.bump()` の戻り値、何回目のウェイクか |
| `_aborted` | `StepAbort` のメッセージ |
| `_failed_at` | `on_fail="stop"` のときに失敗したステップ名 |

`Event("step")` の payload:`{"index": i, "total": len(steps), "resumed": bool, "woke": int}`。

**リトライのラベル**:0回目は `step.name`;以降は `on_reject` があれば `f"{name}#round{attempt+1}"`、
なければ `f"{name}#retry{attempt}"`。manifest を見ればこのステップがどう終わったか一目で分かる。
**サフィックス付きの名前はプロセスをまたぐリネージには入らない** —— `Lineage.remember` が使うのは元の名前。

`runtime.on_session` は `runtime.run` の1行だけを覆い、`try/finally` で gate の前に必ず外れることを保証する。
`prompt_cur` / `resume_cur` / `fork_cur` はローカル変数で、`step` には書き戻さない —— 同じ `Step` オブジェクトが2度走ることがあるため。

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

`gate` から投げる = **即座に止める、もうリトライしない**。「`False` を返す」との違い:`False` は「今回はダメ、もう1ラウンド」;
`StepAbort` は「もう1回やっても無駄」。

投げた後:`ctx["_aborted"] = str(exc)`、`passed = False`、**リトライループを抜ける(残りの `retries` を消費しない)**、
その後は通常の失敗として `on_fail`(デフォルト `"stop"`)に従う。

`with_goal` は2箇所でこれを投げる:`ctx["_runtime"]` が取れないとき、および判定結果が `unreachable` で誰も応答しないとき。

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

[事前確認](glossary.md#前置确认)を行う `Step` を生成する:要件を問い詰める → [`Brief`](#brief) にパース →
4節が揃えば凍結してディスクに書く。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必須・位置引数 | 質問チャネル |
| `brief_path` | `str \| Path` | 必須 | [ブリーフ](glossary.md#需求确认书)をどこに置くか。**実際にインデックスが注入されるワークベンチの中に置かなければならない** |
| `prompt` | `str \| Callable[[Ctx], str]` | 必須 | 人間の元の要望 |
| `name` | `str` | `"确认需求"` | ステップ名、同時に `ctx` のキー |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `clarify(name, channel, instructions=instructions, **spec_kw)` を使う |
| `instructions` | `str` | `""` | [クラリファイア](glossary.md#确认者)への追加指示 |
| `always_ask` | `bool` | `False` | `True` = ブリーフの有無に関わらず毎回聞き直す |
| `on_fail` | `str` | `"stop"` | `Step.on_fail` と同じ |
| `retries` | `int` | `0` | 4節が揃わなかったとき何回聞き直すか |
| `**spec_kw` | | | [`clarify()`](#clarify-role) にそのまま渡すので、`can_read=False`、`max_budget_usd=...` などが書ける |

生成される `Step` の各フィールドはこう埋まる:

- `resume_prompt = CLARIFY_RESUME`。
- `when`:`always_ask=True` → 常に `True`;そうでなければ `Brief.load(brief_path)` が揃っていればそれを ctx に流し込み
  **その上で `False` を返す(スキップ)** —— スキップするときも流し込む。さもないと下流が要件を受け取れない。
- `gate`:`Brief.parse(result.text)`、揃っていなければ `ctx[MISSING_KEY]` を書いて `False` を返す;
  揃っていれば `b.write(brief_path)` で凍結し、ctx に流し込み、`True` を返す。
- `reduce`:`ctx[BRIEF_KEY].prompt_block()` を返す。**モデルの原文ではない** —— 原文には余計に書いたものが混ざりうる。
- `resume_from` は**デフォルトの `None` のまま**:次のステップは新しいセッションで、ブリーフだけを受け取り、その一問一答は受け取らない。
  事前確認の一問一答は**そもそも一度も**コーディネーターのコンテキストに入っていない。入った後で刈られたのではない。

ctx への流し込みは3箇所:`ctx[BRIEF_KEY] = b`、`ctx[name] = b.prompt_block()`、`ctx.pop(MISSING_KEY, None)`。

| 定数 | 値 | 説明 |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` は `Brief` オブジェクト;`ctx[step.name]` はその `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | 確認に失敗したときどの節が欠けているか(中国語の節名)、UI 表示用 |
| `CLARIFY_RESUME` | 中国語のプロンプト文 | 「さっき途中で終わった要件確認の続き —— **やり直しではない**……」。この一文がないと、継続時に元の要望を新しいタスクとして再送してしまい、クラリファイアが聞いた質問をもう一度聞きかねない |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

**目標を設定する** `Step` を生成する:[ジャッジ](glossary.md#判定者)にブリーフを読ませ、目標 + 判定チェックリストを書かせ、
[`Goal`](#goal) にパースして凍結・書き出す。`clarify_step` と同じ形。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必須・位置引数 | 質問チャネル |
| `goal_path` | `str \| Path` | 必須 | 目標ファイルをどこに置くか |
| `brief_key` | `str` | `"确认需求"` | `ctx[brief_key]` からブリーフ原文を取り prompt に入れる。**取れなければ `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | ステップ名 |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `judge(name, channel, instructions=instructions, **spec_kw)` を使う |
| `instructions` | `str` | `""` | 追加指示 |
| `always_set` | `bool` | `False` | `True` = 目標ファイルの有無に関わらずチェックリストを引き直す |
| `on_fail` | `str` | `"stop"` | 同上 |
| `retries` | `int` | `0` | 同上 |
| `**spec_kw` | | | [`judge()`](#judge-role) にそのまま渡す |

**`can_run` という仮引数はない** —— 目標を設定するジャッジにコマンドを走らせたければ、`**spec_kw` 経由で `can_run=True` を渡すしかない。
渡さなければ `Bash` を持てず、`JUDGE_RULES` の「まず自分がどんな環境にいるかを見極めよ」という条項が実行できない。

`gate` はパースと凍結のほかに、もう一つやることがある:目標に `[此环境无法验证:…]` の項目があるとき、**その場で**
`ctx["_on_event"]` 経由で `Event("task", payload={"unverifiable", "total", "path"})` を送って警告する ——
これらの項目の運命は目標を設定するこの瞬間に決まっており、判定の時点ではすでに1ラウンド分の作業費を使い切っている。

**`resume_prompt` は設定していない** —— 目標設定はそもそもブリーフ全文を送り直すべきものだから。

| 定数 | 値 | 説明 |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` は `Goal` オブジェクト;`ctx[step.name]` は markdown |
| `VERDICT_KEY` | `"_verdict"` | 直近の [`Verdict`](#verdict)、UI 用 |
| `ROUND_KEY` | `"_goal_rounds"` | 判定を何ラウンド走らせたか |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

既存の `Step` に[ゴールガード](glossary.md#目标看守)を被せる:各ラウンドの終わりにジャッジが独立に判定し、
達成していなければ差し戻して続けさせる。

戻り値は `replace(step, retries=max(0, rounds - 1), gate=<新 gate>, on_reject=<新 on_reject>)` ——
フィールドを1つずつ組み直すのではなく `dataclasses.replace` を使う。一度組み直したときに `resume_prompt` を落とし、**しかもエラーにならず**、
ただ継続時にブリーフ全文をもう一度送っていた。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `step` | `Step` | 必須・位置引数 | ガードされるステップ |
| `channel` | `HumanChannel` | 必須・位置引数 | 判定しきれないとき人に助けを求めるチャネル |
| `goal_path` | `str \| Path` | 必須 | 目標ファイル。`ctx[GOAL_KEY]` が揃っていないときここから読む |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` を使う |
| `rounds` | `int` | `3` | **総ラウンド数であって追加ラウンド数ではない**:`rounds=3` → `retries=2` → 作業は最大3ラウンド。`rounds=1` = 1ラウンド走らせ、1回判定し、通らなければ失敗 |
| `instructions` | `str` | `""` | ジャッジへの追加指示 |
| `can_run` | `bool` | `False` | ジャッジが `Bash` を使えるか |
| `name` | `str \| None` | `None` | ジャッジの名前、デフォルトは `f"{step.name}·判定"` |
| `**spec_kw` | | | `judge()` にそのまま渡す |

`gate` は **async** で、流れはこう:

1. `ctx["_runtime"]` が無い → **`StepAbort` を投げる**(「拿不到 Runtime,无法判定目标」)。**通ったふりをしない。**
2. `ctx[ROUND_KEY] += 1`。
3. 目標を取る:まず `ctx[GOAL_KEY]` の揃った `Goal`、なければ `Goal.load(goal_path)`、それも無ければ空の `Goal()`。
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`。
   **ジャッジは独立した1回の `Runtime.run` で、`resume` は常に `None` —— つねに新しいセッション**;`step_name` にラウンド番号が付くので、
   プロセスをまたぐリネージには入らない。
5. `Verdict.parse(vr.text)` を `ctx[VERDICT_KEY]` に書く。
6. `v.achieved` → `True` を返す。
7. `unreachable` でない(`v.ok=False` の曖昧なケースを含む)→ 曖昧なときはデフォルトの reason を補い、`False` を返す。
   **曖昧なものは一律に未達成とみなす** —— 「いけそうに見える」の一言で作業を終わらせてはならない。
8. `unreachable` → `await channel.ask(...)` で人に聞く、選択肢は3つ:
   - 誰も応答しない(`a.state != "answered"`)→ **`StepAbort` を投げる**。空回りを続けるのが一番高くつく選択だから。
   - 「接受这个结果,就这样往下走」→ `True` を返す。
   - 「修改目标」→ もう一度新しい目標を聞き、`g.amend(...).write(goal_path)`、`ctx[GOAL_KEY]` を更新し、`False` を返す。
   - それ以外(人が自分で打った自由回答を含む)→「お前の判定が間違っている」として、人の言い分を `v.reason` に記録し、`False` を返す。

`on_reject` は**同期**:`ctx[VERDICT_KEY].feedback()` を返し、`Verdict` が無ければ `""` を返す
(最初からやり直しに退化する)。

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

そのまま動く3ステップのワークフローを組み立てる:**要件確認 → 目標設定 → 作業**(ゴールガード付き)。コマンドライン `flower` が使っているのもこれ。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `ask` | `str` | 必須・位置引数 | 一言の要望。**ウェイク時、これは新しいタスクではなく「また言われた一言」** |
| `workspace` | `str \| Path` | `"."` | ワークスペース |
| `run_dir` | `str \| Path` | `"runs"` | run ディレクトリ |
| `new` | `bool` | `False` | `True` = リネージ + ブリーフ + 目標をアーカイブし(3つまとめて片付ける)、最初からやり直す |
| `isolate` | `bool` | `False` | ワーカーに worktree [隔離](glossary.md#隔离)を与える。ワークベンチもそれに伴い `<ws>.parent/.flower-<ws.name>` へ移る |
| `clarify_only` | `bool` | `False` | 確認ステップだけを含む Workflow を返す |
| `goal` | `bool` | `True` | [ゴールガード](glossary.md#目标看守)を付けるかどうか。`False` = 作業ステップが終わればそれで完了 |
| `rounds` | `int` | `3` | `with_goal(rounds=)` にそのまま渡す、総ラウンド数 |
| `judge_can_run` | `bool` | `False` | `with_goal(can_run=)` にそのまま渡す |
| `max_asks` | `int \| None` | `None` | `HumanChannel` にそのまま渡す、`None` = 回数無制限 |
| `timeout_s` | `float \| None` | `1800.0` | `HumanChannel` にそのまま渡す。`0` = 完全自動、すべての質問は即座に空振り |
| `instructions` | `str` | `""` | クラリファイアへの追加指示 |
| `worker_prompt` | `str` | シグネチャ参照 | ワーカーの system prompt |
| `brief_name` | `str` | `"需求.md"` | ブリーフのファイル名、`<workbench.notes>/` に置かれる |
| `goal_name` | `str` | `"目标.md"` | 目標のファイル名、同上 |
| `log_name` | `str` | `"问答记录.md"` | 一問一答ログのファイル名、同上 |

固定の組み立て:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# コーディネーター = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

分岐する挙動:

- `isolate=True` かつ workspace が git リポジトリでない → **`ValueError` を投げる**。`Agent` ツールがエラーを出すまで待たない
  (その時点ではもう金を使っている)。
- **ウェイク判定**:`Brief.load(brief_path)` が存在し `complete()` ならウェイクとみなす。ウェイクでなく `ask` が空 →
  **`ValueError("要给一句诉求,例如 flower '帮我做一个 X'")` を投げる**。
- ウェイク時、その一言は同時に**3箇所**に落ちる。1つでも欠ければ黙って効かなくなる:ブリーフへの追記
  (`ch.amend(said, label="唤醒时追加")`、既にファイルにあれば重複して書かない)、
  `goal_step(always_set=True)` にチェックリストを引き直させる(引き直さないとジャッジが読むのは古い目標のまま)、
  コーディネーターの目の前に直接届ける(その文脈には**古い**目標が入っているので、渡さないと古い基準で作業して新しい基準で判定される)。

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**走り出す前の読み取り専用の探査で、1バイトも書かない。** 実際に走り出す前に「これは前回の続きか、最初からか」を人に伝えるためのもの。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | ワークスペース、位置引数 |
| `run_dir` | `str \| Path` | `"runs"` | run ディレクトリ |
| `isolate` | `bool` | `False` | ワークベンチの位置を決める。`starter_flow` に渡すのと同じ値でなければならない |
| `brief_name` | `str` | `"需求.md"` | ブリーフのファイル名 |
| `goal_name` | `str` | `"目标.md"` | 目標のファイル名 |

返る dict:

| キー | 型 | 説明 |
|---|---|---|
| `waking` | `bool` | ブリーフが存在し4節が揃っている |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | 目標チェックリストの項目数、目標が無ければ `0` |
| `woke` | `int` | `Lineage.woke`、これまで何回ウェイクしたか |
| `steps` | `dict` | `Lineage.steps` のコピー、ステップ名 → `session_id` |

ワークベンチの位置は**ここと `starter_flow` の中で一度だけ定義される**:`isolate=True` → `<ws>.parent/.flower-<ws.name>`
(リポジトリの外);そうでなければ `<ws>/.flower`。ドライバがブリーフの場所を知りたいときもこの関数を通す ——
自分でパスを組み立てて間違えてもエラーにはならず、ただ黙って効かなくなる。

---

## ロールファクトリ {#角色工厂}

ソース:[`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

5 つのロールはいずれもファクトリ関数である。各ロール = **注入される 1 段のルールテキスト + 1 組のツール + 1 組の hook**。
`worker()` が返すのは SDK の `AgentDefinition`(subagent に渡す用)、残る 4 つは [`AgentSpec`](#agentspec) を返す
(自分で session を 1 本立ち上げる)。

ロール自体は **hook を付けない** —— ツールを止める仕事は `Runtime._attempt` が `spec.delegate_only` に応じて自動で装着する。
[hook 層](#hook)を参照。

内部のツール組定数(エクスポートされていないが、デフォルト値を決めている):

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

[main thread](glossary.md#主线程) 上の [coordinator](glossary.md#协调者) を作る:タスクを分解し、割り振り、レポートを読み、判断する。
**ただし自分では手を動かさない**。最初の 3 つは位置引数。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名。デフォルトの step 名でもある |
| `instructions` | `str` | 必須 | ドメイン指示。最終的に `f"{COORDINATOR_RULES}\n{instructions}".strip()` になる |
| `workers` | `dict[str, AgentDefinition]` | 必須 | 配下にどのロールがいるか。`AgentSpec.agents` に入る |
| `channel` | `HumanChannel \| None` | `None` | 渡すと `inbox` **と** `ask` の 2 ツールが同時に追加され、`mcp_servers` も設定される |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`;`False` → `Read` を外す |
| `glance` | `bool` | `True` | `"Bash"` を追加し、`AgentSpec.glance` を設定する。**実際に何が走れるかは `delegate_guard` が判定する**。ここではない |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | [budget](glossary.md#预算) 上限 |
| `permission_mode` | `str` | **`"acceptEdits"`** | 権限モード。**このデフォルト値に注意** —— これを `clarify()`/`judge()` に渡すと、その 2 ロールの保護が外れる |
| `compact` | `CompactPolicy \| None` | `None` | 渡せば `Runtime` に `no_summary` へ強制変更されない |
| `hooks` | `dict[str, Any] \| None` | `None` | 追加 hook。`workbench_hooks` とマージされる |
| `env` | `dict[str, str] \| None` | `None` | 追加の環境変数 |

返される `AgentSpec` で固定される 3 項目:`delegate_only=True`、`agents=workers`、
`workbench` は `AgentSpec` のデフォルト `True` のまま。

ソースには **`disallowed_tools` で「調整だけして手を動かさない」を実現するな**と明記されている —— あれは session 単位なので、
subagent の `Bash`/`Write` まで一緒に禁止してしまう。[`AgentSpec`](#agentspec) の警告を参照。
正しいやり方はここでの `delegate_only=True` + `allowed_tools` を渡さないこと。
そのうえで [`delegate_guard`](#delegate-guard) が `agent_id` を見て main thread だけを止める。

`channel` を渡すと **2 つのツールが必ずセットで来る**。選べない:MCP server を挿した時点で両方入るし、
`allowed_tools` は排他ではないので、列挙してもしなくても呼び出せる。無人運用では `ask` のたびに `timeout_s` を丸ごと待つ ——
そういう場面では `HumanChannel(timeout_s=0)` を使う。

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

実際に手を動かす [subagent](glossary.md#subagent) の定義を作る。最初の 2 つは位置引数。
返るのは SDK の `AgentDefinition` で、そのまま `coordinator(workers={...})` に入れる。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `description` | `str` | 必須 | **coordinator が人選する根拠** —— 「どんな仕事を任せるか」を明確に書く |
| `prompt` | `str` | 必須 | この worker の system prompt。`discipline=True` のとき `f"{prompt}\n\n{WORKER_RULES}"` に連結される |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | worker を格下げすべきではない |
| `effort` | `str \| int \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | SDK の **`maxTurns`**(キャメルケース)に落ちる |
| `permission_mode` | `str \| None` | `None` | SDK の **`permissionMode`**(キャメルケース)に落ちる |
| `skills` | `list[str] \| None` | `None` | 使用を許可する skill |
| `discipline` | `bool` | `True` | `WORKER_RULES` の報告規律を連結するかどうか |
| `isolate` | `bool` | `False` | [isolation](glossary.md#隔离) マークを付け、`isolated()` を通す。**`AgentDefinition` のフィールドではない** |

`isolate=True` は workspace が git リポジトリであることを要求する。そうでなければ `Agent` ツールが直接 `"not in a git repository"` を返す。
**黙って劣化はしない**。しかもこのマークは Python の属性なので —— `AgentDefinition` に `dataclasses.replace()` を掛けると失われ、
isolation が黙って無効になる。

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

[clarifier](glossary.md#确认者) を作る:着手前に要件を問い詰める。作業はせず質問だけをし、最後にちょうど 4 セクションを出力する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名。位置引数 |
| `channel` | `HumanChannel` | 必須 | 質問チャネル。位置引数 |
| `instructions` | `str` | `""` | 追加指示。`CLARIFIER_RULES` の後ろに連結される |
| `can_read` | `bool` | `True` | `True` のとき `Read` `Glob` `Grep` `WebFetch` `WebSearch` を追加 |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | **ターン数無制限** |
| `max_budget_usd` | `float \| None` | `None` | budget 上限 |

返る `AgentSpec`:`allowed_tools = [channel.tool_name] + (読める場合はその 5 つ)`、
`mcp_servers = channel.mcp_servers()`、`workbench=False`(書き込みツールを持たないので索引に意味がない)、
`permission_mode` は `AgentSpec` のデフォルト `"default"` を継承。
**`Write` / `Edit` / `Bash` / `Agent` はなく、`inbox` もない**(coordinator とは異なる)。

!!! warning "`max_turns` を小さくすると「回数無制限の質問」が空文句になる"
    質問 1 回が 1 ターンである。`max_turns=16` は「せいぜい十数個まで」という意味であり、チャネル側の「ターン数上限なし」という一文はその場で無効になる。

    質問を開放したいなら**両方**を開放する必要がある:`HumanChannel.max_asks`(デフォルトで既に `None` = 無制限)
    と `max_turns`(デフォルトで既に `None`)。

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

[judge](glossary.md#判定者) を作る:走り出す前に目標を設定するか、各ラウンド終了後にそのラウンドを判定するかのどちらか。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名。位置引数 |
| `channel` | `HumanChannel` | 必須 | 質問チャネル。位置引数 |
| `instructions` | `str` | `""` | 追加指示。`JUDGE_RULES` の後ろに連結される |
| `can_run` | `bool` | `False` | `True` のときホワイトリストに `Bash` を追加。`whitelist_guard` も `Bash` を通し、`Write`/`Edit` は依然止める |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | budget 上限 |

返る `AgentSpec`:`allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` +(`can_run` のとき)`["Bash"]`、
`workbench=False`、その他は `clarify()` と同じ。**`Write` / `Edit` / `Agent` はなく、`inbox` もない。**

**トレードオフ**:`can_run=True` は判定が硬くなる(検収コマンドを実際に走らせられる)が、代償として judge が workspace を変更できてしまう ——
`Bash` はそれ自体でファイルを書ける。絶対に中立な判定が欲しければ開けないこと。

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

[oracle](glossary.md#旁路顾问) を作る:run がまだ走っている最中に「今どこまで進んだ?」と聞くと、直近のイベントと workbench を一目見てから答える。
**その発言はその run のコンテキストには入らない。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | ロール名。位置引数 |
| `instructions` | `str` | `""` | 追加指示。`ORACLE_RULES` の後ろに連結される |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | **`12`** | デフォルトで制動あり |
| `max_budget_usd` | `float \| None` | **`0.5`** | デフォルトで制動あり。「ついでに一言聞く」用途であり、暴走してはいけない |

返る `AgentSpec`:`allowed_tools = ["Read", "Glob", "Grep"]`(**channel なし** —— 質問はせず、答えるだけ)、
`workbench=True`(**5 ロールの中で唯一、coordinator ではないのに workbench を開く** —— まさに成果物とメモを読みに行くため)。

### 5 つのルールテキスト {#rules}

5 つの定数はいずれも `__all__` に入っており、そのまま `import` して読む・連結する・書き換えることができる。

| 定数 | 注入先 | 注入方法 | 要点 |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | あなたは「Claude Code を使える人」であって worker ではない;ファイルを書く/コードを直す/テストを走らせるのは禁止;`Bash` は「一目見る」程度で、結果は陳腐化する;**[task brief](glossary.md#任务书) には今回のタスク固有のことだけを書く**;唯一まだ伝える必要のある決まりは「workbench の場所 + 長い成果物は `artifacts/` へ + 返答はパスだけ」;段階的な動作を 1 つ終えるごとに `inbox` を 1 回確認する;`ask` はブロックするので、本当の分岐点でのみ使う |
| `WORKER_RULES` | `worker()` | subagent の `prompt` の**後ろ**に連結 | 返答形式は **結論 / 根拠 / 成果物 / 未検証**、30 行以内;ファイル内容・コマンド出力・ログ・diff 原文の貼り付けは禁止;試行錯誤の過程を復唱するのは禁止;着手前に `.flower/scripts/` を見る。**「長い成果物は `artifacts/` へ」は意図的に書いていない** —— 実際のパスは `Workbench` が生成するため、ハードコードすると間違う |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | 作業はせず、要件だけを問い詰める;**回数制限はなく、明確になるまで聞く**;人が不在の可能性があり、タイムアウトしたら自分で判断して「未知と前提」に書く;出力は**ちょうど 4 セクション**;コードを書かない、ファイル内容を貼らない |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | 2 つのうちどちらか一方。**目標設定**:各チェック項目はその場で検証可能でなければならない。リストの長さは失敗パターンの数で決まる。**境界は判定項目ではない**。検証できない項目は末尾に `[此环境无法验证:原因]` を付ける。**このラウンドの判定**:出力は**ちょうど 3 セクション**、判定対象は**成果物であってソースコードではない**、デフォルトで「やり終えた」を信じない、「できていない」と「ここでは検証できない」は別の結論であり、後者は**絶対に通過と判定してはならない** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | あなたはバイパスである;その run はまだ走っており、あなたは中断もせず参加もしない;**読み取り専用**;答えたら捨てられ、あなたの発言はその run のコンテキストには入らない;手元にあるのは「直近イベントのウィンドウ」と「workbench」だけ;まず見てから答える、答えられなければ答えられないと言う、短く |

---

## agent 定義 {#agent-定义}

ソース:[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` は専任 agent の完全な宣言であり、`build_options` がそれを SDK の `ClaudeAgentOptions` にコンパイルする。
[ロールファクトリ](#角色工厂)が返すのがこの `AgentSpec` である —— ファクトリ外の組み合わせが必要なら、直接構築すればよい。

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名。`Runtime.run` のデフォルト `step_name` でもあり、`whitelist_guard` の拒否文中の自称でもある |
| `instructions` | `str` | 必須 | ドメイン指示。**Claude Code ネイティブの system prompt の後ろに[append](glossary.md#叠加)される。置換ではない** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **承認不要リストであって排他ホワイトリストではない** —— モデルはここにないツールも呼べる。排他は [`whitelist_guard`](#whitelist-guard) が担う |
| `disallowed_tools` | `list[str]` | `[]` | **session 単位**。下の警告を参照 |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | [budget](glossary.md#预算) 上限 |
| `permission_mode` | `str` | `"default"` | 権限モード |
| `agents` | `dict[str, Any] \| None` | `None` | subagent 定義表。値は `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP server 表。`HumanChannel.mcp_servers()` をそのまま入れる |
| `hooks` | `dict[str, Any] \| None` | `None` | 追加 hook。`Runtime` が `merge_hooks` で自前のものとマージする |
| `compact` | `CompactPolicy \| None` | `None` | 渡せば `Runtime` に `no_summary` へ強制変更されない |
| `env` | `dict[str, str]` | `{}` | 子プロセスに注入する環境変数。`compact.env()` が update される |
| `glance` | `bool` | `False` | coordinator 自身が「一目見るだけ」の `Bash` を走らせることを許す。何を通すかは [`is_ephemeral`](#is-ephemeral) が決め、結果は `EphemeralPolicy` によって陳腐化マークが付く |
| `workbench` | `bool` | `True` | この agent の system prompt に workbench 索引を注入するかどうか。**書き込みツールを持たないロールでは切る**(`clarify()` / `judge()` はデフォルトで `False`) |
| `delegate_only` | `bool` | `False` | 調整のみで手を動かさない。`True` のとき `Runtime` は `delegate_guard` を装着し、`whitelist_guard` は**装着しない** |

!!! warning "`disallowed_tools` は session 単位で、subagent まで一緒に禁止される"
    実測のエラー原文:`"Bash is disabled for this session, in subagents as well as here"`。
    つまり coordinator に手を動かさせないつもりで `disallowed_tools=["Bash"]` を使うと、送り出した worker もコマンドを走らせられない ——
    run 全体が台無しになる。

    「調整のみで手を動かさない」を実現するには、`delegate_only=True` + `allowed_tools` を渡さない構成にし、
    [`delegate_guard`](#delegate-guard) が `agent_id` を見て main thread だけを止めるようにする。

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

`AgentSpec` を SDK の `ClaudeAgentOptions` にコンパイルする。`Runtime._attempt` が内部で呼んでいるのもこれ。
自分で SDK を駆動する(`Runtime` を使わない)場合もここから入る。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `spec` | `AgentSpec` | 必須、位置引数 | コンパイル対象の宣言 |
| `cwd` | `str \| Path \| None` | `None` | `None` でないときだけ `cwd` に書き込む |
| `session_store` | `SessionStore \| None` | `None` | `None` でないときだけ `session_store` と `session_store_flush` に書き込む |
| `resume` | `str \| None` | `None` | どの session を続行するか |
| `fork` | `bool` | `False` | `fork_session` に落ちる。**`if resume:` の中にネストしている** |
| `resume_at` | `str \| None` | `None` | `resume_session_at` に落ちる。**同じく `if resume:` の中にネストしている** |
| `use_plugin` | `bool` | `True` | `True` かつ `PLUGIN_DIR` が存在 → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`;`False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | 追加で許可するディレクトリ。**workbench が workspace の外にある場合は必須** |
| `flush` | `str` | `"eager"` | `session_store_flush` に落ちる |
| `prelude` | `str` | `""` | `instructions` の後ろに追加される一段(workbench 索引はここを通る) |

対応関係:

| 生成される option キー | 値 |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | `spec` からそのまま |
| `setting_sources` | `[]`(portable)または `["project"]` |
| `plugins` | リポジトリルートの `plugin/` ディレクトリが存在するときだけ |
| `cwd` / `add_dirs` | 非空のときだけ書き込む |
| `session_store` / `session_store_flush` | `session_store` が `None` でないときだけ書き込む |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | それぞれ非空のときだけ書き込む |
| `env` | `dict(spec.env)` に `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **`resume` が真のときだけ有効** |

`PLUGIN_DIR` はリポジトリルートの `plugin/`(`flower/core/agent.py` から 3 階層上)。pip でインストールした場合この
ディレクトリは存在するとは限らず、コードは `is_dir()` で判定している。

!!! warning "`fork=True` を `resume` なしで渡すと黙って無効になる"
    `fork_session` も `resume_session_at` も `if resume:` の中にネストしている —— `resume` を渡さなければまったく効かず、
    **エラーも出ない**。同様に `Runtime.run(resume_at=...)` は `resume` を渡したときにのみ効き、
    さらに **`Workflow` は `resume_at` を一度も渡さない**:メッセージ単位でロールバックしたければ `Runtime.run` を直接呼ぶしかない。

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

auto-[compact](glossary.md#压缩) のスイッチパネル。生成物は子プロセスに注入する環境変数の組である。
compact のアルゴリズム自体は harness バイナリの中にあり変更できない。変えられるのは「発動するかどうか」だけ。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = 何も設定しない。閾値 = ウィンドウ − 33k;`"no_summary"` → `DISABLE_AUTO_COMPACT=1`;`"off"` → `DISABLE_COMPACT=1`(`/compact` ごと無効化)。**それ以外の値は `ValueError` を投げる**。黙って無視はしない |
| `window` | `int \| None` | `None` | `None` でなければ → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`。CLI 側の制限は 100k–1M で、100k 未満を設定すると 100k に引き上げられる |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `env` | `() -> dict[str, str]` | 環境変数を生成する。**不正な `mode` はここで `ValueError` を投げる。構築時ではない** —— `build_options` から呼ばれるので、エラーは `Runtime.run` の中で露出する |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

コンテキストが埋まりかけたとき、compact ではなく「[handoff document](glossary.md#交接书)を書いて新しい session に切り替える」ためのポリシーオブジェクト。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 切ると auto-compact に戻る |
| `window` | `int` | `default_window()` | モデルのコンテキストウィンドウをどれだけと見なすか |
| `headroom` | `int` | `50_000` | どれだけ余裕を残すか。理由:auto-compact はウィンドウ −33k で発動するため、handoff はその前に間に合わせる必要があり、しかも「handoff を書く」こと自体に 1 ラウンドかかる |
| `max_generations` | `int` | `8` | 1 step で最大何世代まで交代するか。**暴走防止の制動であって、容量計画ではない** |

| プロパティ | 型 | 説明 |
|---|---|---|
| `at` | `@property -> int` | handoff 閾値 `max(10_000, window - headroom)`。**10k の下限がある** —— それ以下では handoff すら書けない |
| `warn_at` | `@property -> int` | 接近警告の位置 `max(1_000, at - 20_000)`。1 世代につき 1 回だけ発火する |

!!! warning "`window` を小さく設定すると無限に handoff してコストを焼く"
    `at` がそのロールの**起動フロア**(coordinator の実測で約 34k)を下回ると、新しい session は口を開いた瞬間に閾値を越える。しかも
    **handoff はリトライ枠を消費しない**(`attempt -= 1`)ので、無限に空回りする。唯一の制動は `max_generations=8` で、
    そこに当たると `error` が診断メッセージに差し替わり、`window` を大きくするか handoff を切るよう促す。

### `default_window()` {#default-window}

```python
def default_window() -> int
```

環境変数 `ANTHROPIC_MODEL` または `ANTHROPIC_DEFAULT_OPUS_MODEL` の**モデル名文字列**からコンテキストウィンドウを推測する:

| 条件 | 戻り値 |
|---|---|
| 名前の中に独立した `1m` の語がある(正規表現 `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| 名前に `haiku` を含む | `200_000` |
| その他(**両方の変数とも未設定の場合を含む**) | `1_000_000` |

**デフォルトは強気の値を取る**。大きく見積もっても致命的ではない:API が `prompt is too long` で弾き、`Runtime` はそのシグナルを認識して
(内部の `is_overflow`)その場で handoff する —— ただしその世代の handoff は劣化版になる。

---

## 文書 {#文书}

ソース:[`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

4 つの dataclass。いずれも「モデルの返答 1 段を決まった数のセクションに解析し、spill する」ものである。共通の形:
`parse()` で解析、`missing()` / `complete()` で揃っているか確認、`to_markdown()` で人向け、
`prompt_block()` で下流モデル向け、`write()` / `load()` で spill と読み戻し。

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

[brief](glossary.md#需求确认书)。**ちょうど 4 セクション**で、順序は
`goal` → `accept` → `bounds` → `unknowns` に固定。中国語のセクション名はそれぞれ「目标」「验收标准」「边界」「未知与假设」。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `goal` | `str` | `""` | 目標 |
| `accept` | `str` | `""` | 受け入れ基準 |
| `bounds` | `str` | `""` | 境界 |
| `unknowns` | `str` | `""` | 未知と前提 |
| `path` | `Path \| None` | `None` | spill 先。`compare=False` で等価判定には参加しない |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `missing` | `() -> list[str]` | 欠けているセクションの**中国語名**。そのまま表示できる |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | モデルの返答から 4 セクションを解析する。**先にフェンス付きコードブロックを剥がす**。解析できなかったものは空のまま |
| `to_markdown` | `() -> str` | ヘッダのメタ情報付きの完全な文書。空セクションは `"(未填)"` と書く |
| `prompt_block` | `() -> str` | 下流に食わせるコンパクト版。**非空セクションのみ**、メタ情報なし |
| `write` | `(path: str \| Path) -> Path` | 親ディレクトリを作り、書き込み、`self.path` を resolve 後のパスに設定して返す |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | ファイルが存在しない、または `OSError` なら `None`。**`"(未填)"` のプレースホルダは空文字列に戻す** |

解析ルール(間違いやすい点の集中箇所):

- フェンスを剥がす際、**閉じていない ``` や `~~~` に遭遇したらそこから丸ごと捨てる** —— 実測で clarifier がコード全文を返答に貼ってきた。
  モデルの出力が途中で切れると後続のセクションが一切解析できなくなり、`complete()` が `False` になって gate に差し戻される。
- 見出しの正規表現は `## 目标` / `**目标**` / `目标:` / `3. 边界` を許容し、見出しの直後に本文が続く形も許容する。
- 別名テーブルは長さの降順でコンパイルする。そうしないと「未知」が「未知与假设」を先に食ってしまう。
- 同名セクションが複数回現れた場合は**最初の内容のあるもの**を取る。
- brief を手で編集する際に `to_markdown()` の `"(未填)"` プレースホルダをそのまま写すと、そのセクションは依然として欠落扱いになる。

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

[handoff](glossary.md#换代) 時に書く [handoff document](glossary.md#交接书)。5 セクション。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `doing` | `str` | `""` | 何をしているか。**必須** |
| `decided` | `str` | `""` | 何が決まったか |
| `deadends` | `str` | `""` | 通らなかった道 |
| `next` | `str` | `""` | 次の一手。**必須** |
| `scene` | `str` | `""` | 現場 |
| `step` | `str` | `""` | 文書ヘッダ用のみ。**解析には関与しない** |
| `path` | `Path \| None` | `None` | spill 先 |

**必須は `doing` と `next` の 2 セクションだけ** —— 「通らなかった道」を非空必須にすると、モデルが作り話をする。

| メンバ | シグネチャ | 説明 |
|---|---|---|
| `missing` | `() -> list[str]` | **必須の 2 セクションだけを検査する** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | 本文に劣化マーク `[降级:交接没写成]` が付いているか |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | `Brief` のセクション分割器を再利用する |
| `to_markdown` | `() -> str` | 空セクションは `"(空)"` と書く |
| `prompt_block` | `() -> str` | **ヘッダで「あなたは引き継いでいる」と明示する**。背景を人に聞き返しに行くのを防ぐため |
| `write` | `(path) -> Path` | `Brief.write` と同じ |
| `load` | `@classmethod (path) -> Handoff \| None` | `Brief.load` と同じ |

同モジュール内の**エクスポートされていないが意味上重要な**3 つのメンバ:`is_overflow(*texts)` は `prompt is too long`、
`context length exceeded`、`maximum context length`、`too many total text bytes`、
`input length and max_tokens exceed` などにマッチし、「ハードエラー」を「その場で handoff」に変える;`HANDOFF_PROMPT` は
**現在の session 自身**に handoff を書かせるためのプロンプト(`{used}` `{window}` の 2 プレースホルダを含む。**新しいロールではない** ——
そのコンテキストを持っているのは自分だけだから);`degraded(step, prompt, *, why="")` は handoff が書けなかったときに機械的に 1 通でっち上げ、
`scene` に元タスクの先頭 **1200** 文字を詰める。

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

[goal guard](glossary.md#目标看守) における目標 + 判定チェックリスト。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `statement` | `str` | `""` | 目標の記述 |
| `checks` | `list[str]` | `[]` | 判定チェックリスト。1 行 1 項目 |
| `path` | `Path \| None` | `None` | spill 先 |

| メンバ | シグネチャ | 説明 |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | `checks` のうち `[此环境无法验证:…]` が付いた項目。**目標を設定したその瞬間に、通らないことが確定している** |
| `missing` | `() -> list[str]` | `statement` が非空**かつ** `checks` が非空であることを要求する |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` は 1 行 1 項目。`-` / `*` / `1.` の記号は自動で除去する |
| `to_markdown` | `() -> str` | チェックリストが空のときは `"(空)"` と書く |
| `prompt_block` | `() -> str` | 下流に食わせるコンパクト版 |
| `write` / `load` | `Brief` と同じ | spill と読み戻し |
| `amend` | `(extra: str) -> Goal` | **追記であって上書きではない**:`statement` の後ろに `"\n\n(已修改)" + extra` を連結し、`self` を返す |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

[judge](glossary.md#判定者) による 1 ラウンド分の判定結果。**ちょうど 3 セクション**:結論 / 理由 / 未通過。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`。解析できなければ `""` |
| `reason` | `str` | `""` | 理由 |
| `failed` | `list[str]` | `[]` | 通らなかったチェック項目 |

| メンバ | シグネチャ | 説明 |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | 結論が解析できたかどうか。**`ok=False` は必ず「未達成」として扱うこと。達成扱いにしてはならない** |
| `parse` | `@classmethod (text) -> Verdict` | 下記参照 |
| `feedback` | `() -> str` | worker に差し戻す文言:「どこが足りないか」だけを渡し、解決策は渡さない |

`parse` の認識順序:

1. まず見出しセクションで「结论」/「判定」を取る。
2. 見出しセクションがない場合、全体を strip して `fullmatch(r"1|true")` → 達成;`fullmatch(r"0|false")` → 未達。
3. それ以外は結論テキスト中を状態語テーブル(**長い語が先**)で探し、最初にヒットした語を採用する。
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」はすべて `unreachable` に寄せる** ——
   実測でやられた:ターゲットプラットフォームが macOS、実行環境が Linux コンテナで、judge がソースの分岐を見ただけで通過と判定した。
4. それでも決まらなければ → 孤立した `\b1\b` を探して達成、`\b0\b` を探して未達。
5. すべて外れ → `state=""`、`ok=False`。

`unreachable` と `not_yet` は**別の結論である**:前者は「立ち止まって人に聞く」経路に進み、「もう 1 ラウンド」ではない。

---

## hook 層 {#hook}

ソース:[`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

この層は flower の**実行境界**である:どのツールをメインスレッドに触らせないか、長すぎる結果をどう切り詰めるか、どのロールを独立 worktree に置くか —— すべて SDK hook が強制し、**プロンプトには頼らない**。理由は単純で、プロンプトは提案にすぎずモデルは従わなくてよいからだ:system prompt に「worktree を使うな」と明記していても `isolate_guard` の注入はそのまま効く、という実測がある(モデルが渡したのは `None`、実際に着地したのは `'worktree'`)。

エクスポートは 9 個:`HookMatcher` を返す guard ファクトリ 5 個(`whitelist_guard` は `None` を返しうる)、組み立て関数 1 個、マージ関数 1 個、隔離マーキング関数 2 個。
これらを手で取り付ける必要はない —— [`Runtime`](#runtime) が `AgentSpec` に従って自動で組み立てる。手で取り付けるのは、自分で SDK を駆動する(`Runtime` を経由しない)場合だけだ。

**メインスレッド判定はすべて 1 つの関数を通る**:`_is_main_thread(data) = not data.get("agent_id")` ——
subagent の tool-lifecycle hook データには `agent_id` が入り、[メインスレッド](glossary.md#主线程)には入らない。
「メインスレッドだけを止める」guard はすべてこの 1 行に依存している。

ツールグループ定数(モジュールレベル、非エクスポート。ただしデフォルト matcher を決めている):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### 早見表:どの guard がどの SDK イベントに載るか {#hook-速查表}

| 関数 | SDK hook イベント | matcher | 止める対象 | 何を返すか | 誰が取り付けるか |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` のうち **`allowed_tools` に入っていない**もの | **メインスレッドのみ**の禁止ツール呼び出し | `permissionDecision: "deny"` + 理由 | `Runtime._attempt`、**`spec.delegate_only is False` のときだけ** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit`(`tools=` で変更可) | **メインスレッドのみ**の直接作業。`allow_glance=True` のとき `is_ephemeral()` を通った `Bash` は通す | `deny` +「subagent に委譲せよ」 | `workbench_hooks(delegate_only=True)`、**`Runtime` にワークベンチがあるときだけ** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` に `cwd` も `isolation` もなく、かつ `subagent_type` が `isolated()` でマークされている | `permissionDecision: "allow"` + `updatedInput`(`isolation="worktree"` を注入) | `workbench_hooks`、**`agents` にマーク済みのロールがあるときだけ** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` が `workbench.root` 内に落ちる場合 | `{}`(副作用は `workbench.refresh()`) | `workbench_hooks`、常に取り付け |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | `tool_response` の中で `threshold` 文字以上の**文字列フィールド**。spill ディレクトリ自体を読む場合は通す | `updatedToolOutput`(spill + 1 行のポインタ + 冒頭 400 文字) | `workbench_hooks`、**`spill_threshold` が真のときだけ** |

**この表から読み取れる重要な帰結**:`Runtime(workbench=False)` のときは `workbench_hooks` が丸ごと取り付けられない。
そして `delegate_only=True` のコーディネーターでは `whitelist_guard` もスキップされる —— **メインスレッドには壁が 1 枚もない**。
詳しくは [Runtime](#runtime) の警告を参照。

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**`allowed_tools` を、直接作業する 4 つのツールに対して本当に排他的にする。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `allowed` | `list[str] \| None` | 必須、位置引数 | 通常は `spec.allowed_tools` をそのまま渡す |
| `role` | `str` | `"这个角色"` | 拒否文中の自称。`Runtime` は `spec.name` を渡す |

- **`PreToolUse` に載る**。matcher は `"|".join(banned)`、`banned` = `Bash` `Write` `Edit` `NotebookEdit` のうち `allowed` に入っていないもの。
- 該当すれば即 `permissionDecision: "deny"`。文面の趣旨:「XX に YY はない。**これは意図的であり、設定漏れではない。** 結論は返答の本文に書け、フレームワークはそこから取る —— 別の書き方で回避しようとするな。」
- **止めるのは当該セッションのメインスレッドだけ**で、subagent は通す —— subagent のツールは `AgentDefinition.tools` が決める。
- 止めるべきツールが 1 つもない場合は **`None`** を返す(たとえば `worker()` のようなフルセットのロール)。呼び出し側はこれを見て取り付けるかどうかを決める。

**なぜこれが必須か**:`allowed_tools` は**承認不要リストであって、排他的ホワイトリストではない**。実測での証拠は 2 つ ——
目標を設定したジャッジが `Bash` を 11 回実行した。$0.1 のプローブでは `allowed_tools=["Read"]` の agent が `Write`/`Bash` を普通に呼べた。
したがって `clarify()` / `judge()` の「書き込みツールを持たない」は**この hook が支えている**のであって、ホワイトリスト自体ではない。

利点は `allowed_tools` から派生していることだ。だから `judge(can_run=True)` は自動的に `Bash` を残しつつ `Write`/`Edit` は止め続ける —— 追加のスイッチは要らない。

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**メインスレッドが自分で手を動かす → 拒否し、進む道を示す。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher。リストではなく正規表現文字列 |
| `allow_glance` | `bool` | `False` | `True` のとき `tool_name == "Bash"` かつ [`is_ephemeral(command)`](#is-ephemeral) が真なら通す |

- **`PreToolUse` に載る**。matcher はそのまま `tools`。
- メインスレッドがこの 4 つのツールを呼ぶと deny。理由の中で**次に何をすべきか**を示す:`Agent` ツールで subagent を出し、タスクに目標と受け入れ基準を明記し、長い成果物は `.flower/artifacts/` に書き、返答にはパスと結論だけを載せるよう求めること。
- subagent は一律に通す。

`whitelist_guard` との違いは**言い回し**だ:止めるツール群は同じだが、こちらは「人を出せ」と言う。そのほうが筋が通る。
だから `delegate_only=True` のロールにはこの 1 本だけを載せる。重複して載せるとモデルは矛盾した 2 つの指示を受け取る。

`allow_glance=True` の通過判定と「結果が切り詰められるかどうか」は**同じ関数**([`is_ephemeral`](#is-ephemeral))である ——
通過集合は失効集合と一致していなければならず、片方を変えたらもう片方も変えなければならない。

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

しきい値を超えたツール結果を**その場で [spill](glossary.md#落盘) する**。コンテキストには 1 行のポインタだけを残す —— コンテキストが埋まってから振り返って compact するのではない。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | spill 先は `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | 何文字を超えたら spill するか |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False`(デフォルト)= subagent の結果も spill する |

- **`PostToolUse` に載る**。返すのは
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <切り詰め後>}}`。
- spill ファイル名は内容の `sha256` 先頭 16 桁 + `.txt`。コンテキストでは 1 行のポインタ + **冒頭 400 文字**に置き換わる。
- `updatedToolOutput` は**元ツールの出力構造を保たなければならない**。よって dict の中の長すぎる**文字列フィールド**だけを置換する。**list には一切触れない**(中身が画像ブロックの可能性がある)。構造が合わなければ拒否される(元のまま、エラーにはならない)。
- **spill ファイル自体を読むときは必ず通すこと** —— でなければ「`Read` で読め」が空手形になる:読み戻した全文がまた spill され、無限ループになる。実測でぶつかっており、モデルは 5 通りの書き方で回避を試みた。

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

[ワークベンチ](glossary.md#工作台)に何か書いたら `INDEX.md` を更新する。次の agent は開始時点でその存在を知る。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | 判定範囲であり、更新対象 |

**`PostToolUse` に載る**。matcher は `"Write|Edit"`。`tool_input["file_path"]` を resolve した結果が `workbench.root` 内に落ちれば `workbench.refresh()` を呼ぶ。**常に `{}` を返す** —— 何も書き換えず、副作用だけを持つ。

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

ロールごとに subagent へ独立した git worktree を割り当て、[隔離](glossary.md#隔离)を実現する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | 必須、位置引数 | ロール表。`subagent_type` がマークされているかを引くのに使う |
| `on_inject` | `Any` | `None` | 任意のコールバック。`on_inject(subagent_type, description)` の形で呼ばれる |

**`PreToolUse` に載る**。matcher は `"Agent"`。3 条件が同時に成り立ったときだけ注入する:`tool_name == "Agent"`、`tool_input` に **`cwd` も `isolation` もない**、`subagent_type` に対応するロールが `isolated()` でマークされている。成立すれば `permissionDecision: "allow"` + `updatedInput`(`isolation` を `"worktree"` に設定)を返す。

`isolation` と `cwd` は `Agent` ツールでは**排他**である —— モデルが自分で `cwd` を指定したならそれを尊重する。
「隔離するかどうか」は**ロールの属性**であって、グローバルスイッチでも、委譲のたびに判断するものでもない。隔離が不要なロールには 1 バイトも足されない。

**隔離を有効にするなら[ワークベンチ](glossary.md#工作台)をリポジトリの外へ出すこと。** 隔離された agent は共有 checkout に書けないので、ワークベンチは `home=` でリポジトリ外を指す必要がある。`starter_flow(isolate=True)` は `<ws>.parent/.flower-<ws.name>` を、`Runtime(workbench=True)` は `<run_dir>/workbench` を使う —— どちらもリポジトリ外だが、**同じディレクトリではない**。混ぜて使わないこと。

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

subagent 定義に「独立した作業領域が必要」というマークを付ける、およびそのマークを読み戻す。

| 関数 | 引数 | デフォルト | 説明 |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | 必須 | マークを付ける定義。**返るのは同じオブジェクト** |
| | `flag: bool` | `True` | 位置引数。`False` = マークを外す |
| `wants_isolation` | `agent: AgentDefinition \| None` | 必須 | `None` も受け付け、`False` を返す |

マークは `object.__setattr__` で付ける Python 側の属性 `_flower_isolate` であり、**dataclass のフィールドではない** ——
SDK は `asdict()` でシリアライズし、宣言済みフィールドしか見ないので、このマークが CLI 側へ漏れることはない(実測済み)。

**代償**:`AgentDefinition` に `dataclasses.replace()` をかけるとこのマークは失われ、隔離が黙って無効になる。

`worker(isolate=True)` は内部で `isolated()` を通っている。

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

ワークベンチに必要な hook を一度に取り付ける。`Runtime._attempt` が呼ぶのはこれ。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | `index_guard` と `spill_guard` に渡す |
| `delegate_only` | `bool` | `True` | `True` のときだけ `delegate_guard` を載せる |
| `spill_threshold` | `int \| None` | `4000` | 真のときだけ `spill_guard` を載せる |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | **1 つでも** `isolated()` でマークされていれば `isolate_guard` を追加 |
| `allow_glance` | `bool` | `False` | `delegate_guard(allow_glance=)` へそのまま渡す |

出力:

- `PreToolUse`:`delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`。
  マーク済みのロールがあれば `isolate_guard(agents)` を追加。
- `PostToolUse`:常に `[index_guard(workbench)]`。`spill_threshold` が真なら `spill_guard(workbench, threshold=spill_threshold)` を追加。
- **空リストになるイベントキーは削除される**。空の list は返さない。

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

複数の hook 設定をイベント名ごとに**連結**する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | 可変長引数 | 任意個。`None` のグループはスキップ |

`extend` を使い、**重複排除はしない** —— 同じ guard を 2 回渡せば 2 回取り付けられる。`Runtime` はこれで `spec.hooks`、`workbench_hooks(...)`、`whitelist_guard` を 1 つにまとめている。

---

## ワークベンチ {#工作台}

ソース:[`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

ディスクに書き出すための作業ディレクトリ。サブディレクトリ 3 つ + インデックス 1 つ。インデックスは **system prompt に注入される**ので、agent は毎ターン手元に何があるかを知っている。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `Path` | 必須、位置引数 | ワークスペース。`__post_init__` で resolve される |
| `dirname` | `str` | `".flower"` | ワークベンチのディレクトリ名。`workspace` からの相対 |
| `max_index_entries` | `int` | `40` | **`prompt_block()` にしか効かない**:system prompt に注入される部分で各カテゴリ最大何件まで列挙するか。超過分は「…他 N 個」の 1 行にまとめる。`INDEX.md` 自体は制限なしで全部載る |
| `home` | `Path \| None` | `None` | 指定すればそれを `root` に使い、**`dirname` は無視**。`None` でなければこちらも resolve される |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `root` | `@property -> Path` | `home` が指定されていればそれ、なければ `workspace / dirname` |
| `external` | `@property -> bool` | `root` が `workspace` の**外**にあるか。隔離モードでは `True` であるべき |
| `scripts` | `@property -> Path` | `root / "scripts"`。2 回目も走らせるスクリプト |
| `artifacts` | `@property -> Path` | `root / "artifacts"`。2000 文字を超える長い成果物 |
| `notes` | `@property -> Path` | `root / "notes"`。重要な決定。1 決定 1 ファイル |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | モデルに見せるパス:ワークスペース内なら相対パス、外なら絶対パス |
| `ensure` | `() -> Workbench` | 3 つのディレクトリを mkdir し、`self` を返す(チェーン可:`Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(表示パス, 説明, バイト数)`。`rglob("*")` で再帰し、`.` 始まりのファイルはスキップ |
| `refresh` | `() -> str` | `INDEX.md` を書き直し、その内容を返す |
| `prompt_block` | `() -> str` | **system prompt に注入される部分**。意図的に短くしてある —— 毎ターン常駐するので |

スクリプトの自己説明フォーマット:先頭 8 行以内の `# desc: 一行説明`(`//` と `--` のコメント記号も認識)。
なければ最初の空でないコメント行、または docstring の 1 行目にフォールバック(100 文字で切る)。

`prompt_block()` が注入する 3 つのルール:

1. 2 回目も走らせるスクリプトは `scripts/` に書き、1 行目に `# desc:` を付ける。
2. **2000 文字**を超える成果物は `artifacts/` に書き、会話にはパスと結論だけを載せる。
3. 重要な決定は `notes/` に書く。1 決定 1 ファイル。

`external=True` のとき、`prompt_block()` は「絶対パスでアクセスすること」の 1 文を追加で挿入する。

**インデックスは subagent に継承されない。** これはセッションレベルの `system_prompt.append` を通っており、subagent は自分の system prompt を持つからだ(実測 $0.2461)。したがって「長い成果物は `artifacts/` に書く」「ワークベンチはどこにあるか」の 2 点は、[コーディネーター](glossary.md#协调者)が[タスク指示書](glossary.md#任务书)の中で伝え直すしかない —— **それが唯一の経路**であり、冗長ではない。
`WORKER_RULES` に**わざと書いていない**:実際のパスは `Workbench` が生成するので、ハードコードすれば間違う。

---

## セッションストア {#会话存储}

ソース:[`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

3 層の継承:`SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`。
`Runtime` は**常に最外層を使う**。3 層それぞれの方針はコンストラクタ引数で制御する。

3 層の担当は 1 つずつ:ディスクへの永続化、サイズと価値による [trim](glossary.md#裁剪)、「エラーかどうか」による [prune](glossary.md#剪除)。
trim も prune も **`load()`**(つまり resume が履歴をモデルへ戻す)瞬間に起きる。SQLite の生レコードは 1 バイトも変わらない。

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

SDK の `SessionStore` プロトコルの実装。テーブルは `entries` / `meta` / `summaries` の 3 つ。
store key は `project_key/session_id[/subpath]` —— **サブ agent の transcript は subpath で区別する**。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `str \| Path` | 必須、位置引数 | DB ファイル。接続は `check_same_thread=False` |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `append` | `async (key, entries) -> None` | uuid で冪等に重複排除(まず既に格納済みのものを除き、次にバッチ内の重複を除く)。バッチ全体が再生されたときは **mtime を進めず、fold summary も重複させない**。summary に参加するのはメイン transcript(`subpath is None`)だけ |
| `projects` | `() -> list[str]` | DB に実在する `project_key`。**SDK は cwd から推測するので、クエリ前にこれで確認すること。当て推量しない** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **同期。payload は読まず**、meta の 1 行だけを引く。「同じパスでの継続」用 —— 存在しないセッションを resume すると子プロセスが立ち上がるまで失敗が分からない |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | 最後のターンでモデルが実際に見ていたコンテキストのサイズ。見つからなければ `0`。末尾 `scan` 件だけを逆順に走査する。`input + cache_read + cache_creation` の 3 項すべてを数える(`input_tokens` だけを見ると大幅に過小評価する) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | seq 順にソート。行がなければ `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | メイン transcript のみ |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | セッションのサマリを列挙 |
| `delete` | `async (key) -> None` | メイン transcript を削除するとき**サブ agent の分もカスケード削除**し、孤児を防ぐ |
| `list_subkeys` | `async (key) -> list[str]` | このセッション配下のサブ transcript を列挙 |
| `close` | `() -> None` | 接続を閉じる |

内部の `_next_mtime` は**厳密な単調性**を保証する —— `list_sessions` と summary の sidecar がこの時計を共有しており、そうでないと SDK の staleness 高速パスが誤判定する。

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `keep_recent` | `int` | `20` | 直近 N 個の `tool_result` は原文のまま残す |
| `min_chars` | `int` | `2000` | 短い結果は trim する価値がない |
| `spill_dirname` | `str` | `".flower/spill"` | **`workspace` からの相対で、ワークスペース内でなければならない** —— でないと agent の `Read` が届かない |
| `enabled` | `bool` | `True` | `Runtime(trim=False)` のときここが `False` |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | 本文を置き換えるポインタ行を生成 |

**2 つの spill ディレクトリは同じものではない。** `spill_guard` は `<workbench.root>/spill/` に書く(ワークスペース外でもよい)。
`TrimPolicy.spill_dirname` は `<workspace>/.flower/spill/` に書く(**ワークスペース内でなければならない**)。
それぞれ「その場で切る」と「resume 時に切る」に対応しており、ディレクトリが違うのは意図的だ。1 つにまとめないこと。

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

[エフェメラルコマンド](glossary.md#一次性命令)の結果に対する失効ポリシー。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 切ると失効マーキング自体を行わない |
| `keep_recent` | `int` | `6` | 直近 N 個は免除。**`TrimPolicy` の 20 よりずっと小さい** |
| `max_chars` | `int` | `2000` | 超えたらスキップし、`TrimPolicy` のアーカイブに任せる |
| `text` | `str` | シグネチャ参照 | 置換文面。`{cmd}` と `{age}` の 2 つのプレースホルダ |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | `text` に埋めて置換本文を生成 |

**作用するのは `Bash` ツールの結果だけ**で、しかもコマンドがエフェメラルコマンドのホワイトリストに一致する必要がある。**`Read` は対象外** ——
ファイル内容は時間の経過で誤解を招くほど劣化するわけではない。失効した内容は **spill せず**、そのまま捨てる。

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Bash コマンドが[エフェメラルコマンド](glossary.md#一次性命令)かどうかを判定する。
**`delegate_guard` の通過判定と trim の失効判定はこの 1 つの関数を共有する** —— コーディネーターが自分で実行できるコマンド集合は、結果が失効マークされる集合と一致していなければならない。通すのに trim しなければ、失効した `git status` が永久にコンテキストを占めたうえ誤解を招く。trim するのに通さなければ、コーディネーターは `ls` 1 本のために subagent を出し、4.3k の起動コストを数十文字と引き換えにする。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `cmd` | `str` | 必須、位置引数 | コマンドライン全体 |

判定順:

1. 空 / 全部空白 → `False`。
2. コマンド置換(`$(`、バッククォート、`<(`、`>(`)または「状態を変える」書き方に該当 → `False`。
3. 安全なリダイレクト(`2>&1`、`&> /dev/null` など)を外してもなお `>` または `<` を含む → `False`。
4. `&&` / `||` / `;` / `|` を外してもなお単独の `&` が残る(バックグラウンド実行)→ `False`。
5. `&&` / `||` / `;` / `|` で分割し、**各セグメントすべてがホワイトリストに該当**しなければならない。

ホワイトリストの動詞カテゴリ:読み取り専用の `git` サブコマンド(`status` `diff` `log` `show` `branch` `rev-parse` など)、ディレクトリとシステム情報(`ls` `pwd` `df` `du` `date` `whoami` `env` など)、プロセスとコンテナ(`ps` `top` `lsof` `docker ps` `kubectl get` など)、ファイル閲覧(`cat` `head` `tail` `wc` `stat` `find` `tree`)、パス探索(`which` `whereis` `command -v` `type`)、テキスト処理(`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` など)。

動詞がホワイトリストにあっても、次の書き方は止められる:`xargs`、`exec`、`eval`、`source`、`tee`、
`find -delete` / `-ok` / `-fprint`、`sed -i`、`sort -o`、`awk` の中の `system(` と `print >`、
`git branch -D/-d/-m`、`git * --force/--hard/--prune`。

初版は複合コマンドを一律に拒否していたが、**実測では glance が完全に機能しなくなった**(コーディネーターの 3 回の試行がすべてブロックされた)。そこでセグメント単位の判定に変えた。

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `str \| Path` | 必須 | DB ファイル |
| `workspace` | `str \| Path` | 必須 | spill ディレクトリの基準 |
| `policy` | `TrimPolicy \| None` | `None` | 未指定ならデフォルトの `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 未指定ならデフォルトの `EphemeralPolicy()` |

公開属性:`workspace`、`policy`、`ephemeral`、`last_report: dict[str, int]`。

`load()` の順序:`super().load()` → `last_report` をクリア → `ephemeral.enabled` なら `expire()` →
`policy.enabled` なら `trim()`。**`enabled=False` のときはそのステップを丸ごとスキップする。**

| メソッド | 説明 |
|---|---|
| `expire(entries)` | 失効した時間依存の `Bash` 結果を、**本文だけ差し替え、ブロックは残す**。コマンドは直前の assistant メッセージの `tool_use` から探す。`isCompactSummary` / `isMeta` はスキップ。`max_chars` を超えるものはスキップ(`trim` に任せる)。最後の `keep_recent` 個は免除。`last_report["expired"]` を書く |
| `trim(entries)` | `>= min_chars` の `tool_result` 本文を `<workspace>/<spill_dirname>/<sha256先頭16桁>.txt` へ spill し、ブロックの内容をポインタに置換。最後の `keep_recent` 個は免除。`last_report` の `cleared` / `kept` / `chars_saved` を書く |

**trim するのはプレーンテキストだけ**:`image` / `document` ブロックはそのまま残す。

**構造上のレッドラインが 2 つ**:`tool_result` **ブロック自体は必ず残す**こと。置き換えてよいのは content だけだ(1 つでも欠けると「Missing Tool Result Block」になる)。`isCompactSummary` のエントリには触れないこと。

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

`store.last_report` を 1 行の中国語にレンダリングする。UI のログ用。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | 必須、位置引数 | サブクラスの `PruningSessionStore` も受け付ける |

出力は 3 種類:何もしていない → `"未裁剪"`。失効のみ → `"N 个时效性结果标记为过期"`。
それ以外は `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`。ここで X = `chars_saved // 4`。

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | 合成された API エラーメッセージ(切断の残骸)を取り除く |
| `neutralize_interrupts` | `bool` | `True` | 中断で残った `tool_result` を中立的な説明に置き換える |
| `interrupt_text` | `str` | シグネチャ参照 | 中立的な説明の文面 |
| `keep_denials` | `int` | `1` | 直近 N 件の拒否されたツール呼び出しを残す |

`keep_denials` の理由:拒否された呼び出しは一度も実行されておらず、結果に情報はないが、場所は小さくない(実測で 1 件 273 文字 = 拒否文 93 文字 + **実行されなかったコマンドの原文** 180 文字)。さらに重要なのは**それが誤解を招く**ことだ —— 実測では、コーディネーターが「Bash を直接使うな」を数件読んだ後、通るはずの `git status` すら試さなくなり、学習性無力感を身につけた。
**デフォルトは 0 ではなく 1 件**:直近の拒否は、同じターン内でモデルが同じブロック済みコマンドを繰り返し再試行するのを防ぐ。

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**`Runtime` のデフォルト store。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `str \| Path` | 必須 | DB ファイル |
| `workspace` | `str \| Path` | 必須 | spill ディレクトリの基準 |
| `policy` | `TrimPolicy \| None` | `None` | trim ポリシー |
| `prune` | `PrunePolicy \| None` | `None` | prune ポリシー |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 失効ポリシー |

公開属性は親クラスに加えて 3 つ:`prune_policy`、`pruned`、`denials_dropped`。

`load()` = `super().load()`(先に `expire` + `trim`)→ `self.prune(entries)`。`prune` は 3 つのことをする:

1. **古すぎる拒否済み呼び出しを取り除く**:harness の構造的マーカー `toolDenialKind == "permission-rule"` で判定し(拒否文のテキストマッチより信頼できる)、最後の `keep_denials` 個を残し、それ以外は `tool_use` **と** `tool_result` ブロックをまとめて取り除く。同じ assistant メッセージに複数の `tool_use` がある場合は**該当したものだけ**を取り除く。でないと「Missing Tool Result Block」になる。テキストブロックと thinking ブロックは残す。
2. **合成された API エラーメッセージを取り除く。** SQLite にはそのまま残り、単に戻さないだけ。
3. **中断で残った `tool_result` を中立的な説明に置き換える** —— 本文を替えるだけで、エントリは取り除かない。

**構造上のレッドラインは 1 つだけ**:transcript は `parentUuid` の単一リンクなので、1 件取り除いたらその子を最も近い生存祖先へ繋ぎ直さなければならない。内部の `relink` に渡す `entries` は**取り除く対象を含んだ完全なリストでなければならない**。フィルタは `relink` 自身が行う ——
呼び出し側が先に除いてから渡すと鎖はそこで切れ、それより前の履歴が全部失われる(**踏み済み:取り除く対象が末尾にあるうちは表面化せず、途中にあると壊れる**)。

**引数の順序が親クラスと違う**:親は `(path, workspace, policy, ephemeral)`、子は `(path, workspace, policy, prune, ephemeral)` —— **4 番目の位置引数が `ephemeral` から `prune` に変わっている**。位置渡しすると黙ってずれる。必ずキーワードで渡すこと。

---

## レジリエンス {#韧性}

ソース:[`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

ネットワークが切れたら、失敗して終了するのではなくぶら下がって待つ。エクスポートは 4 つ:ポリシーの dataclass 1 個 + 単体でも使える探査関数 3 個。

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 切るとどんな障害でも再試行しない |
| `max_attempts` | `int` | `6` | **初回を含む** |
| `base_delay` | `float` | `4.0` | バックオフの基数、秒 |
| `max_delay` | `float` | `120.0` | バックオフの上限、秒 |
| `probe_timeout` | `float` | `5.0` | プローブ 1 回のタイムアウト |
| `probe_interval` | `float` | `15.0` | プローブ間の待機時間 |
| `max_offline_wait` | `float` | `3600.0` | 最大でどれだけぶら下がって待つか。デフォルト 1 時間 |
| `retry_unknown` | `bool` | `True` | 分類できないエラーを再試行するか |
| `resume_prompt` | `str` | シグネチャ参照 | 継続実行時に伝える言葉。**意図的にエラーの詳細を一切含まない** —— モデルが知る必要があるのは「中断された、続けろ」であって、`ENOTFOUND` か 503 かではない |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` にさらに `0.75 + random()*0.5` を掛ける(±25% のジッター) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`、または `kind == "unknown"` かつ `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | ネットワークが戻るまでぶら下がって待つ。戻れば `True`、`max_offline_wait` を超えたら `False`。`notify` は `(str) -> None` のコールバックで、**最初に到達不能になったとき**と**復旧したとき**に 1 回ずつ発火する |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

エラーテキストを `"transient"` / `"fatal"` / `"unknown"` の 3 種類に分類する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `text` | `str \| None` | 必須、位置引数 | エラーメッセージの原文。空なら `"unknown"` を返す |

**先に fatal を判定し、その後に transient** —— 401 などのテキストにはよく `connection` の語が混ざるので、順序を逆にすると永久に待ち続けることになる。

| 種類 | 何に該当するか |
|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`network error`、`Connection error`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`too many requests`、`timeout` / `timed out`、`temporarily unavailable`、`service unavailable`、`internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

探査すべきホストとポート。`ANTHROPIC_BASE_URL` に従い、デフォルトは `https://api.anthropic.com`。
ポートのデフォルトは `80`(http)または `443`。

**自前ゲートウェイを使うならそれを探査しなければならない** —— `api.anthropic.com` に通ることはゲートウェイに通ることを意味しない。

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `host` | `str` | 必須、位置引数 | ホスト名 |
| `port` | `int` | 必須、位置引数 | ポート |
| `timeout` | `float` | `5.0` | 秒 |

**DNS(`getaddrinfo`)+ TCP ハンドシェイクだけ**を行う。HTTP は送らず、認証情報も付けず、**課金もされない**。例外はすべて到達不能とみなす。

---

## イベントと対話 {#事件与交互}

ソース:[`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[イベント](glossary.md#事件)は SDK のメッセージストリームを平坦化した安定構造である。**[対話層](glossary.md#交互层)は
`Event` しか知らず、SDK の型を一切 import しない** —— これが UI を差し替えてもコアを触らずに済む境界だ。[対話層の差し替え](../guide/interaction.md)を参照。

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `kind` | `EventKind` | 必須 | 下表を参照 |
| `text` | `str` | `""` | 本文 |
| `tool` | `str` | `""` | ツール名。`tool_call` のときのみ |
| `payload` | `dict[str, Any]` | `{}` | 構造化された付加情報 |
| `raw` | `Any` | `None` | 生の SDK オブジェクト。深く掘りたいときに使う |

`__str__`:`tool_call` なら `f"[{tool}] {text}"`、それ以外は `text`、`text` が空なら `f"<{kind}>"`。
つまり `print(ev)` はそのまま読める。

`EventKind` は全部で **15** 個:

| kind | 発行元 | 説明 |
|---|---|---|
| `text` | `normalize` | assistant の本文 |
| `thinking` | `normalize` | 思考ブロック |
| `tool_call` | `normalize` | ツール呼び出し。`text` は `file_path` / `command` / `pattern` の要約で 200 文字に切る |
| `tool_result` | `normalize` | ツール結果。`text` は 500 文字に切り、payload に `tool_use_id` / `is_error` |
| `task` | `normalize` | 3 種類の Task メッセージ。`text` はメッセージのクラス名 |
| `system` | `normalize` | その他のシステムメッセージ。`text` は subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`。payload に `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | 合成 API エラーメッセージ。payload に `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`。**本文は入力であってモデルの産出ではない**ので `StepResult.text` には入らない |
| `unknown` | `normalize` | 判別できなかったもの |
| `retry` | `Runtime` | リトライ通知 |
| `step` | `Workflow.run` | payload:`{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | payload の `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | 質問。**「人が自発的に言ったこと」も載る** |

**最後の 4 つは `normalize()` からは生まれない。**

すべての assistant / user イベントの `payload` には次が入る:

| キー | 型 | 説明 |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | `subagent` が真のときのみ |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。**[世代交代](glossary.md#换代)の判定基準の唯一の出所**であり、long-horizon な run で最も見えているべき数字 |

**`ask` という kind は「質問」と「人が自発的に言ったこと」の両方を載せる。** 後者は `payload["kind"] == "mail"` で、
**`options` / `remaining` を持たない**。UI は必ず `payload.get("kind")` を先に判定してから描画を決めること。
さもないと、ただの一言を「回答待ちの質問」として吊り下げてしまう。

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

1 件の SDK メッセージを 0〜N 個の `Event` に平坦化する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `message` | `Any` | 必須、位置引数 | 任意の SDK メッセージオブジェクト |

主要な分岐:

- **合成 API エラーメッセージ**(`isApiErrorMessage=True` または `model == "<synthetic>"`)→ 単一の
  `Event("error", payload={"synthetic": True})`。**これは意図的だ** —— さもないと切断時の文言が本文として
  `StepResult.text` に入り、次の step に渡ってしまう。
- `AssistantMessage` → `kind="text"`;`UserMessage` → `kind="prompt"`。
- `ToolUseBlock` → `Event("tool_call", text=<要約>, tool=block.name, payload={"id", "input"})`。
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`。
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`。
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`。

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

人への 1 回の質問。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `id` | `str` | 必須 | 回答時にこれで特定する |
| `question` | `str` | 必須 | 質問本文 |
| `options` | `list[str]` | `[]` | 選択肢。人は選ばずに自分で書いてもよい |
| `asked_at` | `float` | `time.time()` | 質問した時刻 |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | 回答本文 |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `waited_s` | `@property -> float` | すでにどれだけ待ったか |
| `event` | `(remaining: int = 0) -> Event` | `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` を産出 |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

**プロセス内 MCP server**(ツール 2 つ)と、UI 用のメソッド群。モデル側には
`mcp__human__ask` と `mcp__human__inbox` しか見えない。コンストラクタ引数はすべて keyword-only。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | **プッシュ**方式の出口。これを渡すと `Workflow.run` は配線しない |
| `max_asks` | `int \| None` | `None` | **回数無制限**。数字を渡せばハードな枠になり、`0` = 質問禁止(全自動 / CI)。枠を超えるとツールは**そのまま拒否を返し、ブロックしない** |
| `timeout_s` | `float \| None` | `1800.0` | 30 分。`None` = 永久に待つ;**`<= 0` = 待たない、すべての質問は即座に空振り** |
| `log_path` | `str \| Path \| None` | `None` | 質疑応答をディスクに**追記**する。コンテキストは食わない |
| `amend_path` | `str \| Path \| None` | `None` | run の途中で人が言ったことをこのファイルに追記する(通常は brief そのもの)。**spill しなければ step 境界を越えられない** —— 次の step は新しい session で、読むのは凍結物だけだ |
| `over_budget_text` | `str` | モジュール定数 | 枠超過時にモデルへ返す文言 |
| `timeout_text` | `str` | モジュール定数 | タイムアウト時にモデルへ返す文言 |
| `declined_text` | `str` | モジュール定数 | スキップされたときにモデルへ返す文言 |

公開属性:コンストラクタ引数と同名の 8 つ、加えて `asks: list[Ask]`、`mail: list[Mail]`、
`ui_errors: list[str]`(**UI コールバックが投げた例外はここに溜まり、run は止まらない**)。

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | そのまま `AgentSpec.mcp_servers` に渡す。**キー名は server 名と一致していなければならない**ので、これがまとめて出す |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | 人を待って吊り下がる。**`CancelledError` を除いて例外を投げない** —— 誰も答えないこともひとつの答えであり、`ask.state` で区別する |
| `send` | `(text: str) -> Mail \| None` | 人が自発的に一言言う。**どのスレッドからでも呼べる**。agent を中断しない;内部で自動的に `amend()` を呼ぶ |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | `amend_path` に追記する。実際に書けたかを返す(パス未設定、空テキスト、`OSError` はいずれも `False`) |
| `pending_mail` | `() -> list[Mail]` | まだ取り出されていない mail |
| `remaining` | `@property -> int` | あと何回質問できるか。**`max_asks=None` のときは `-1` を返す**。0 でも無限でもない |
| `pending` | `() -> list[Ask]` | いま回答待ちで吊り下がっている質問 |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | **プル**方式で使う。タイムアウトで `None`、キャンセルされたら投げる |
| `answer` | `(ask_id: str, text: str) -> bool` | 回答する。`False` = その質問はもう待っていない(タイムアウト / 既回答) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | スキップして、モデルに自分で判断させる |
| `transcript` | `() -> str` | 質疑応答記録の markdown |

**取り方は 2 つのうち 1 つを選ぶ**:**プッシュ** —— `HumanChannel(on_event=...)` で構築;**プル** —— `await channel.next_ask()`。
`Workflow.run` は `channel.on_event is None` のときだけ自動で配線するので、自分で渡した場合は上書きされない。

**スレッド越え**:`answer` / `decline` / `send` は内部で `loop.call_soon_threadsafe` を通るので、
Web バックエンドや TUI の入力スレッドから直接呼ぶのが普通だ。

3 つの「0 / None」はそれぞれ意味が違うので混同しないこと:`max_asks=None` = 無制限、`max_asks=0` = 質問禁止;
`timeout_s=None` = 永久に待つ、`timeout_s<=0` = 即タイムアウト;`remaining` は `max_asks=None` のとき `-1`。

エクスポートされていないが戻り値に現れる `Mail` は dataclass で、フィールドは `id` / `text` / `sent_at` / `taken`。

---

## 血統 {#血缘}

ソース:[`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

「どの step がどの session を使ったか」をプロセス越しに記録する。[継続](glossary.md#接续)はこれで前回どこまで進んだかを見つける。
ファイルは `<run_dir>/lineage.json`。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `Path` | 必須 | 血統ファイルのパス |
| `workspace` | `Path` | 必須 | ワークスペース。`__post_init__` で resolve する |
| `steps` | `dict[str, str]` | `{}` | step 名 → `session_id` |
| `woke` | `int` | `0` | 何回 wake したか |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | `<run_dir>/lineage.json` を読む。**ファイルが無い、読めない、`workspace` フィールドが合わない場合は一律で空を返し、エラーにしない** |
| `remember` | `(step: str, session_id: str) -> None` | 対応を覚えて**即座に spill する**。step が空か sid が空なら何もせず戻る |
| `bump` | `() -> int` | wake カウントを +1 して spill し、新しい値を返す(初回の run は `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | 血統ファイル + `extra` を `<into>/<YYYYmmdd-HHMMSS>/` へ**移動**し、`steps` / `woke` をゼロに戻す。**移動であって削除ではない** |

spill は `tmp.replace(path)` の原子的置換で行う;`OSError` は黙って飲む —— spill の失敗でこの run を落とすべきではない。

**`workspace` はガードだ**:SDK の `project_key` はワークスペースのパスから導かれるので、ディレクトリをコピーして移すと古い `session_id` は引けなくなる。
だからパスが合わなければ無かったものとして扱う。

`Workflow.run` が血統をロードするとき、各レコードを `runtime.has_session(sid)` で 1 件ずつ検証し、生きているものだけを使う ——
血統ファイルは `sessions.db` より長生きすることがある。

---

## 最小の動く例 {#示例}

5 つとも、そのまま実行できる。前提:`claude-agent-sdk` がインストール済みで、`ANTHROPIC_API_KEY` または `ANTHROPIC_AUTH_TOKEN` が使えること
(でなければ `Runtime(...)` の構築時点で `RuntimeError` が飛ぶ)。

### agent 1 つで 1 step 走らせる {#示例-单-agent}

最小の骨格:`AgentSpec` を 1 つ宣言し、`Runtime` を 1 つ作り、`await rt.run(...)` して `StepResult` を読む。

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`Runtime` の引数は**すべて keyword-only**;`rt.run()` の `spec` と `prompt` は位置引数で、残りは keyword-only。
`AgentSpec` はデフォルトで `allowed_tools=["Read", "Glob", "Grep"]`、`delegate_only=False` なので、
`Runtime` が自動で [`whitelist_guard`](#whitelist-guard) を付け、`Bash`/`Write`/`Edit`/`NotebookEdit` を全部止める。

### コーディネーター + ワーカー {#示例-协调}

手を動かさない[コーディネーター](glossary.md#协调者)が、実作業をする[ワーカー](glossary.md#执行者)を 1 人連れる。
これが flower のコンテキスト節約の第一層だ。

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True は必須:delegate_guard は workbench_hooks に載っているので、
    # workbench を開かないとコーディネーターの Bash/Write を止める hook が 1 つも無い。
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

`worker()` の最初の 2 引数は位置引数:`description`(コーディネーターが人選に使う)、`prompt`(その system prompt。
後ろに `WORKER_RULES` が自動で連結される)。`coordinator()` の最初の 3 つは位置引数:`name`、`instructions`、`workers`。

### Workflow を自分で書く {#示例-workflow}

2 step。後の step が前の step の結果を自分の prompt に注入する —— 安価で isolate されており、session を共有しない。

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # 新しい session:prompt に入っているものしか食べない
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 新しい session + 前 step の結果を prompt に注入(安価で、汚染を防ぐ)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # 同じ session で続けて話したいなら resume_from="造句";分岐させたいなら fork=True も付ける
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text(reduce を渡していないとき)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # on_fail="stop" のとき、どの step で失敗したか


asyncio.run(main())
```

`Step` の最初の 3 フィールド(`name` / `spec` / `prompt`)は位置引数で、`Workflow` の `steps` も同様。
`Workflow.run(runtime, *, on_event=None, on_step=None)` —— `runtime` は位置引数、2 つのコールバックは keyword-only。
**`continuous=True` がデフォルトであることに注意**:同じ `run_dir` + 同じ `workspace` で 2 回目を走らせると、
`resume_from=None` の step も前回の session の続きを話す。

### ゴールガードを 1 枚足す {#示例-目标}

まず[ジャッジ](glossary.md#判定者)にゴールと判定チェックリストを確定させ、次に実作業の step に判定を受けさせる ——
通らなければフィードバックを持って再挑戦し、最大 3 ラウンド。

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = 全自動:すべての質問は即座に空振りし、人を待つふりをしない
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds は**総ラウンド数**:rounds=3 → retries=2 → 実作業は最大 3 ラウンド
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # goal_step の prompt は ctx["确认需求"](brief_key のデフォルト値)を読む。
        # clarify_step が無いときは自分で 1 部流し込む。でないと "(没有确认书)" しか見えない。
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY:Goal オブジェクト
    print(ctx["_verdict"])     # VERDICT_KEY:直近の Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY:何ラウンド走ったか
    print(ctx.get("_aborted")) # StepAbort の理由(達成不能かつ誰も応答しないとき)


asyncio.run(main())
```

`with_goal` は `gate` / `on_reject` / `retries` だけを差し替え、残りのフィールドは `dataclasses.replace` でそのまま持っていく。
ジャッジは**独立した session** だ:`gate` の内部で単独に `rt.run(judger, ..., step_name=f"{label}#{轮次}")` を呼び、
`resume` は常に `None`。

### 対話層を差し替える {#示例-交互层}

ターミナルを Web / TUI / HTTP に替えるとき、変えるものは 2 つだけ:`Event` を描画する関数と、質問を取ってくるコルーチン。

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event を自分の UI に描画する —— 差し替えが必要な唯一のもの。"""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" で mail ではないものは、下の answerer に任せる(プル方式)


async def answerer(ch: HumanChannel) -> None:
    """プル方式で質問を取る。Web バックエンド / HTTP サービスに替えるとき、変えるのはこのコルーチンだけ。"""
    while True:
        ask = await ch.next_ask()          # timeout なしならずっと待つ
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # または ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime は workflow 自身が作った workbench を使う —— もう 1 つ組み立てないこと
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

プッシュとプルは**どちらか一方を選ぶ**:プッシュは `HumanChannel(on_event=...)` で構築、プルは `await channel.next_ask()`。
`Workflow.run` は `channel.on_event is None` のときだけ自動で配線するので、自分で `on_event` を渡した場合は上書きされない。
`answer()` / `decline()` / `send()` / `interrupt()` は**いずれも別スレッドから呼べる**。

---

## 罠と間違いやすい点 {#陷阱}

踏む順に並べてあり、モジュール順ではない。どれも実測に出所がある。

### 組み立て {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = メインスレッドに壁が 1 枚も無い。**
   `delegate_guard` は workbench があるときだけ付き、`whitelist_guard` は `delegate_only=True` でスキップされる。
   コーディネーターを使うなら workbench を開くこと。詳しくは [Runtime](#runtime)。
2. **workbench の位置は 2 つある。組み間違えないこと。** `Runtime(workbench=True)` は `<run_dir>/workbench` に落ち、
   `Workbench(ws)` のデフォルトは `<ws>/.flower`。自分で `brief_path` を組むときは後者に合わせること。
   **brief は A ディレクトリに書かれ、注入されるインデックスが走査するのは B ディレクトリ、しかもエラーにならない。**
   正しいやり方:workflow 自身が `Workbench(...).ensure()` して `Workflow.workbench` に載せ、
   **同じオブジェクト**を `Runtime(workbench=wb)` に渡す。
3. **`allowed_tools` は排他的なホワイトリストではなく、承認不要リストだ。** モデルはそこに無いツールも呼べる。
   `clarify()` / `judge()` の「書き込みツールを持たない」は [`whitelist_guard`](#whitelist-guard) という hook で成り立っている。
   一方 `coordinator()` はデフォルトで `permission_mode="acceptEdits"` —— この値を
   `clarify()` / `judge()` に渡すと保護は消える。
4. **`disallowed_tools` は session レベル**なので、subagent の同名ツールもまとめて禁止する。
5. **workbench のインデックスは subagent に入らない。** 「長い産出は `artifacts/` に書く」はコーディネーターが task brief で言い換えて渡すしかない。
   それが唯一の経路だ。
6. **`Runtime(...)` は資格情報が無いと構築段階で `RuntimeError` を投げる**。`run()` まで待たない。
7. **`Runtime.run_id` はインスタンスごとに一意でなければならない。** `manifest.json` は `run` フィールドで重複排除するので、
   2 つの id が衝突すると、後から書いた側が相手の行を「自分が前回書いたもの」と見なして消す。

### workflow {#陷阱-流程}

8. **`Workflow.continuous=True` がデフォルト**であり、`resume_from=None` は「まったく新しい session」を意味しない。
   毎回新しく開きたいなら明示的に `continuous=False`。**step 名を変えれば血統は切れる。**
9. **`with_goal(rounds=N)` は総ラウンド数であり、追加ラウンド数ではない**:`retries = max(0, rounds - 1)`。
10. **`on_fail="skip"` は `ctx[step.name]` を書かない** —— 下流の `lambda ctx: ctx["某步"]` は `KeyError` になる。
    欠けた結果を持って先へ進みたいなら `on_fail="continue"`。
11. **`resume_from` が未実行 / 失敗済みの step を指すと `ValueError` を投げる**。黙ってスキップはしない。
12. **`Step.reduce` は同期関数でなければならない;`gate` / `when` / `on_reject` は async でよい。**
13. **`fork=True` は `resume` を渡さないと黙って無効になる。** `Workflow` は `resume_at` を一切渡さないので、
    メッセージ単位で巻き戻すには `Runtime.run` を直接呼ぶしかない。
14. **`Runtime` を自分で駆動するときは、`on_session` を gate の前に必ず外すこと**。さもないとジャッジの session が
    実作業 step の血統に書き込まれる。`Workflow` は `try/finally` でこれを保証している。
15. **`step_name` が manifest と血統のキーを決める。** `Workflow` は `#retryN` / `#roundN` の接尾辞を付け、
    ジャッジは `#轮次` を付ける —— **接尾辞付きの名前はプロセス越しの血統に入らない**。これが「ジャッジは常に新しい session」の実装のひとつだ。

### 役割 {#陷阱-角色}

16. **`clarify(max_turns=<小さい数>)` は「質問は回数無制限」を空文にする** —— 質問 1 回が 1 ターンだからだ。
17. **`goal_step()` に `can_run` の仮引数は無い**。`**spec_kw` 経由で `can_run=True` を渡すしかない。
    渡さないとゴールを立てるジャッジが `Bash` を得られず、`JUDGE_RULES` の「まず自分がどんな環境にいるかを見極めろ」が実行できない。
18. **`judge(can_run=True)` はジャッジにワークスペースを変更させうる** —— `whitelist_guard` は `allowed_tools` から導かれるので、
    `Bash` を渡せば `Bash` は通る(`Write`/`Edit` は依然止まるが、`Bash` 自体でファイルは書ける)。絶対に中立でいてほしいなら開けないこと。
19. **`worker(isolate=True)` は workspace が git リポジトリであることを要求する**。でなければ `Agent` ツールが
    `"not in a git repository"` をそのまま返し、黙って劣化はしない。しかも isolate フラグは Python の属性なので、
    **`AgentDefinition` に `dataclasses.replace()` をかけると失われる**。
20. **`AgentDefinition` を直接構築するときの引数はキャメルケース**:`maxTurns`、`permissionMode`。
    `worker()` はすでに変換してくれている。

### 世代交代とコンテキスト {#陷阱-换代}

21. **世代交代が有効なとき auto-compact は強制的に切られ、フォールバックが無い。** だから handoff document を書く step には劣化経路が必須だ。
    auto-compact を残したければ `AgentSpec.compact` を明示的に渡す。
22. **`HandoffPolicy.window` を小さくしすぎると世代交代が無限に回って金が燃える。** 唯一の閂は `max_generations=8`。
    もう一方、**`default_window()` は環境変数が両方とも未設定のときも `1_000_000` を返す** ——
    大きく見積もった分は `is_overflow()` が受け止める(劣化した世代交代 1 回になる)。ハードエラーではないが、その世代の handoff は劣化版だ。
23. **workbench が無いと handoff document は spill されない。** 文書は prompt 経由で引き継ぎ手に渡るが、人は後から見返せない。

### ストレージ {#陷阱-存储}

24. **`Runtime(trim=False)`(デフォルト)は「何も掃除しない」ではない。** store は常に `PruningSessionStore` であり、
    `trim=False` は大きな結果の trim だけを切る;**切断残骸の除去、拒否された呼び出しの除去、中断残留の中性化、時効切れの処理は変わらず行う。**
25. **2 つの spill ディレクトリは同じものではない**:`spill_guard` は `<workbench.root>/spill/` に落ち、
    `TrimPolicy.spill_dirname` は `<workspace>/.flower/spill/` に落ちる(ワークスペース内でなければならない)。
26. **`PruningSessionStore.__init__` の 4 番目の位置引数は `ephemeral` ではなく `prune`** であり、
    親クラスと異なる。位置で渡すと黙ってずれる。

### 文書と対話 {#陷阱-文书}

27. **`Verdict` が結論を解析できなかったときは `state=""`、`ok=False` であり、達成と見なしては絶対にいけない。**
    さらに「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」はすべて `unreachable` に寄せられ、
    「止まって人に聞く」経路に入る。「もう 1 ラウンド」ではない。
28. **`Brief.parse` は閉じていないコードフェンスに出会うとそれ以降の内容を全部捨てる** —— モデル出力が途中で切れると、
    後ろのセクションは一切解析されず、`complete()` は `False` になり、gate が差し戻す。
29. **`Brief.load` は `"(未填)"` を空として扱う。** brief を手で編集するときにプレースホルダの文字をそのまま写すと、そのセクションは欠落扱いのままだ。
30. **`HumanChannel` の 3 つの「0 / None」はそれぞれ意味が違う**:`max_asks=None` は無制限、`max_asks=0` は質問禁止;
    `timeout_s=None` は永久に待つ、`timeout_s<=0` は即タイムアウト;`remaining` は `max_asks=None` のとき **`-1`** を返す。
31. **`Event("ask")` は質問と人が自発的に言ったことの両方を載せ**、後者は `payload["kind"] == "mail"`。UI は先にこれを判定すること。
32. **`Workflow.run` は `channel.on_event is None` のときだけ自動で配線する** ——
    自分で `HumanChannel(on_event=...)` を構築した場合、質問イベントは workflow の `on_event` 出口には流れない。
