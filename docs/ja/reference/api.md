# Python API

このページでは `flower` のトップレベル `__all__` にある **62 個の公開シンボル**を網羅する:シグネチャ、引数、デフォルト値、意味、
公開属性とメソッド。読み終えたら引数を探すためにソースを開く必要はない。

構成は**関心事**ごとであって、モジュールファイルごとではない ——「[coordinator](glossary.md#协调者) が
自分で手を動かすのをどう止めるか」を知りたいなら [hook 層](#hook)へ;「前のステップの結果を次にどう渡すか」なら[workflow](#流程)へ。
用語はすべて[用語集](glossary.md)に従う。

バージョン `0.1.0`、依存は `claude-agent-sdk>=0.2.152`。すべてのシグネチャはソースと逐語対応。

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## このページの内容 {#索引}

| 関心事 | シンボル |
|---|---|
| [agent を 1 つ走らせる](#运行时) | `Runtime` `StepResult` |
| [複数ステップをつなぐ](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [ロールを作る](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [agent 定義を手書きする](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [構造化された文書](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [ツールを止める・結果を切る・隔離を分ける](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [spill 先の作業ディレクトリ](#工作台) | `Workbench` |
| [session をどう保存し、何を保存するか](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [ネットが落ちたとき](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [UI を差し替える](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [プロセスをまたいで前回に接続する](#血缘) | `Lineage` |

## 噛みつく 6 つのデフォルト値 {#危险默认值}

この 6 条は些末事ではなく、最も頻出する 6 種類の事故だ。各条は対応する節に完全な説明がある。

| デフォルト値 | 結果 | 詳細 |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | main thread の `Bash`/`Write`/`Edit` に **hook が 1 つも掛からない** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | spec に強制的に `CompactPolicy(mode="no_summary")` を装着、つまり `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | `resume_from=None` のステップでもプロセスをまたいで前回の session に接続してしまう | [Workflow](#workflow) |
| `build_options(fork=True)` に `resume` を渡さない | 黙って無効化され、エラーも出ない | [build_options](#build-options) |
| `clarify(max_turns=<小さい数>)` | 「質問回数は無制限」を空文句にする —— 質問 1 回がそのまま 1 ターン | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | session 単位なので、subagent もろとも禁止される | [AgentSpec](#agentspec) |

---

## ランタイム {#运行时}

ソース:[`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` は実行の中核だ。ワークスペース、[session store](glossary.md#会话存储)、[workbench](glossary.md#工作台)、
[resilience](glossary.md#韧性) 方針、[handoff](glossary.md#换代) 方針を保持し、外向きには動詞が 1 つしかない:1 ステップを `run` する。
リトライ、中断後の再開、コンテキスト満杯時の handoff は、すべてこの 1 回の呼び出しの中で完結する。

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

コンストラクタ引数は**すべて keyword-only**(`*` が先頭)、`workspace` は必須。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `str \| Path` | 必須 | agent の `cwd`。構築時に resolve して `mkdir(parents=True, exist_ok=True)`。SDK の `project_key` はここから導出される —— ディレクトリをコピーして移すと、古い `session_id` は引けなくなる |
| `run_dir` | `str \| Path` | `"runs"` | `sessions.db`、`manifest.json`、`lineage.json`、および `workbench=True` のときのデフォルト workbench を置く。同じく resolve して mkdir |
| `portable` | `bool` | `True` | `build_options(portable=)` にそのまま渡す、つまり `setting_sources=[]`:ホストの `~/.claude/` も、プロジェクトの `.claude/` も読まない。[portable](glossary.md#可移植) を参照 |
| `trim` | `TrimPolicy \| bool` | `False` | インスタンスを渡せばそのまま使う;`bool` を渡すと `TrimPolicy(enabled=bool(trim))`。**切っても大きな結果を trim しなくなるだけで、prune は行われる** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | 変換規則は上と同じ。`coordinator(glance=True)` と対になる —— main thread に `git status` を走らせることを許すなら、その結果が期限切れになることを保証しなければならない |
| `keep_denials` | `int` | `1` | `PrunePolicy(keep_denials=)` に渡す。直近 N 回の拒否されたツール呼び出しを残し、それより前は呼び出しごと結果ごと取り除く |
| `workbench` | `Workbench \| bool` | `False` | インスタンスを渡せばそのまま使う;`True` を渡すと `Workbench(workspace, home=run_dir / "workbench")` を作る(**デフォルトはワークスペースの外に置かれる**)。その直後に `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | ツール結果が何文字を超えたら [spill](glossary.md#落盘) するか。`None` または `0` = `spill_guard` を装着しない |
| `resilience` | `Resilience \| bool` | `True` | 変換規則は同じ |
| `handoff` | `HandoffPolicy \| bool` | `True` | 変換規則は同じ |

**session store はハードコードされている**:常に
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`。
コンストラクタ引数にバックエンドを差し替える入口は**ない** —— 差し替えたいなら自分で `AgentSpec` + `build_options(session_store=...)` を組むか、
構築後に `rt.store` を上書きする。

構築の最後の 2 ステップは `load_dotenv()` と `check_credentials()` で、**後者はエラーがあれば `raise RuntimeError`**。
資格情報がない場合は構築段階で落ちるのであって、`run()` を待たない。

!!! warning "`workbench=False` + `coordinator()` = main thread に壁が 1 枚もない"
    `delegate_guard` は `workbench_hooks` の中でしか装着されず、`workbench_hooks` は `self.workbench is not None`
    のときしか呼ばれない;`whitelist_guard` は `if not spec.delegate_only` でスキップされる。そして `coordinator()` は常に
    `delegate_only=True` を設定し、デフォルトの `glance=True` が `Bash` を通す。

    **結論:coordinator を `Runtime(workbench=False)` と組み合わせると、その `Bash`/`Write`/`Edit` を止める hook は何もない。**
    `coordinator()` を使うなら `workbench` を有効にすること —— `Runtime(..., workbench=True)` か、
    `Workbench` インスタンスを渡す。

!!! warning "`handoff=True`(デフォルト)は auto-compact を強制的に切る"
    `_attempt` の中で:`handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`、
    子プロセスに落ちると `DISABLE_AUTO_COMPACT=1` になる。理由は、2 つの仕組みを同時に動かすと、コンテキストが落ちたのが誰の仕業か説明できなくなるからだ。

    **代償:handoff を書くそのステップには必ず縮退経路が必要**(`handoff.degraded`)。compact という受け皿がもうないからだ。
    auto-compact を残したいなら、`AgentSpec.compact` を明示的に指定する(spec 側が指定していればそれを尊重し、上書きしない)。

#### 公開属性 {#runtime-属性}

| 属性 | 型 | 説明 |
|---|---|---|
| `workspace` | `Path` | resolve 後のワークスペース |
| `run_dir` | `Path` | resolve 後の run ディレクトリ |
| `portable` | `bool` | そのまま保持 |
| `store` | `PruningSessionStore` | session store。バックエンドを差し替えるには構築後に上書きするしかない |
| `resilience` | `Resilience` | 正規化後のインスタンス |
| `handoff` | `HandoffPolicy` | 正規化後のインスタンス |
| `workbench` | `Workbench \| None` | `workbench=False` のときは `None` |
| `spill_threshold` | `int \| None` | そのまま保持し、`_attempt` の中で `workbench_hooks` に渡す |
| `results` | `list[StepResult]` | このプロセスで走らせた各ステップを、順に追記 |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`。**インスタンスごとに必ず一意でなければならない** —— `manifest.json` は `run` フィールドで重複排除するので、2 つの id が衝突すると後から書いた側が相手の行を自分の前回分と誤認して消す |
| `on_session` | `Callable[[str], None] \| None` | 新しい `session_id` を得た**その瞬間**にコールバック、デフォルトは `None`。**`runtime.run` のその 1 行だけに被せるべき** —— [judge](glossary.md#判定者) が同じ `Runtime` を使うため、gate の間も掛けたままだと judge の session が作業ステップの[lineage](glossary.md#血缘)に書き込まれてしまう |

クラス定数:`INTERRUPTED = "interrupted-by-human"`、`HANDOFF_DUE = "context-full-handoff"`、
`INTERRUPT_NOTE`(中断後の再開時に人の発言の後ろに付ける一節で、「そのとき飛んでいたツール呼び出しが interrupted を
返すのは中断の正常な副作用であって、環境障害ではない」と説明するもの)。

#### 公開メソッド {#runtime-方法}

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | 1 ステップ走らせる。下記参照 |
| `interrupt` | `(message: str = "") -> None` | 現在のターンの中断を要求する。**どのスレッドからでも呼べる**。協調的:**メッセージ境界**でクリーンに切り、強制キャンセルはしない。空文字列 = 中断するだけで何も言わない |
| `rescue` | `() -> None` | 強制終了される前に可能な限り帳簿を書き切る。`SIGHUP`/`SIGTERM` ハンドラから呼ばれる。飛行中のステップも manifest に書き、`error="killed-by-signal"` とする。同期の小さな書き込みしかしない |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())` の中の `/`、`_`、`.` をすべて `-` に置換したもの。**SDK が cwd から導出するので、呼び出し側からは指定できない** |
| `has_session` | `(session_id: str) -> bool` | この id が**このワークスペース**下でまだ引けるか。同期、payload は読まない |
| `context_of` | `(session_id: str) -> int` | ある session の最終ターンのコンテキスト規模、`store.last_context` に委譲 |
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
| `prompt` | `str` | 必須、位置引数 | このターンで言うこと |
| `step_name` | `str \| None` | `None` | `StepResult.step`、manifest、lineage に載るキー。`None` → `spec.name` |
| `resume` | `str \| None` | `None` | この `session_id` を継続する |
| `fork` | `bool` | `False` | 新しい session に分岐し、元の session を汚さない。**`resume` が真のときだけ有効** |
| `resume_at` | `str \| None` | `None` | あるメッセージ位置から継続する(巻き戻し)。同じく**`resume` が真のときだけ有効** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | イベントの出口、[`Event`](#event) 参照 |

各ステップの冒頭でコンテキスト水位をゼロに戻す(`self._ctx, self._warned = 0, False`)。その後はループで、出口は 4 つ:

1. **成功** → 抜ける。
2. **人による中断**(`result.error == INTERRUPTED`)→ **`max_attempts` の制約を受けず**、ネットワークも待たない。
   人の発言を携えて同じ session を `resume`、`attempt -= 1`(中断は失敗試行に数えない)、prompt = 人の発言 + `INTERRUPT_NOTE`。
   **`session_id` を得ていなければ止まるしかない**。
3. **コンテキスト満杯**(`result.error == HANDOFF_DUE`、または `handoff.enabled` かつ `session_id` を得ていて
   `is_overflow(...)` が成立)→ **これも `max_attempts` の制約を受けない**。まず `len(result.retired) >= handoff.max_generations` を確認し、
   超えていれば error を診断メッセージに差し替えて抜ける;そうでなければ[handoff document](glossary.md#交接书) を書き → `resume=None, fork=False`
   (**完全に新しい session**)→ prompt を `h.prompt_block()` に差し替え → 水位をゼロに戻し → `attempt -= 1`。
4. **リトライ可能な障害** → `not resilience.enabled or attempt >= max_attempts` なら抜ける;
   `classify(error)` がリトライすべきでないと判定すれば抜ける;そうでなければ `Event("retry")` を発火し、`wait_online()` でネットワークを待ち、
   `sleep(delay_for(attempt))`;**`session_id` を得ていれば `resume` で継続する**(prompt は
   `resilience.resume_prompt` に差し替え)、そして `result.resumed` を `True` にする。

締めくくり:`ended_at` を書き、`self.results` に追記し、`manifest.json` を書く。

`manifest.json` は**append** セマンティクス:書くたびにディスクを読み直し、`run` フィールドで重複排除する(自分の行は差し替え、他人の行は残す)。
だから同じ `run_dir` の下で flower を 2 つ並行して走らせても安全だ —— `run_id` が衝突しないことが前提。

**handoff の 3 つの観測点**(いずれも `Event("handoff")`、`payload["phase"]` で区別):
`near`(`warn_at` に接近、世代ごとに 1 回だけ発火)、`writing`(handoff を書いている最中、十数秒かかる)、
`done`(payload に `degraded` / `path` / `sections` を含む)。handoff を書くそのターンは
`replace(spec, max_budget_usd=None)` で走らせる —— handoff は必ず書き切れなければならず、予算で詰まってはいけないからだ;
さらに `on_event=None` で、このターンは UI に流さない。

handoff は `<workbench.notes>/交接-<步骤名>.md` に spill される;**workbench がなければ spill されない**。文書は変わらず prompt で
引き継ぎ手に渡されるが、事後に読み返せなくなるだけだ。古い handoff は `notes/archive/交接/<名>-<时间戳>.md` に移される。

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

1 ステップ走り終えた後の全帳簿。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `step` | `str` | 必須 | ステップ名(`step_name` または `spec.name`) |
| `session_id` | `str \| None` | `None` | **常に最後に引き継いだ session** —— 途中の handoff で焼き捨てたものは `retired` に入る |
| `ok` | `bool` | `False` | このステップが成功したか |
| `cost_usd` | `float` | `0.0` | ドル。リトライと handoff をまたいで**累積**する |
| `num_turns` | `int` | `0` | ターン数、同じく累積 |
| `text` | `str` | `""` | **main thread の本文のみを含む**。subagent の発言はそれ自身の transcript に残り、そこへ渡した task brief は `kind="prompt"` で、どちらも入らない |
| `error` | `str \| None` | `None` | 失敗理由。特殊値は `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` を参照 |
| `started_at` / `ended_at` | `float` | `0.0` | Unix タイムスタンプ |
| `attempts` | `int` | `1` | 実際の試行回数。中断と handoff は**数えない** |
| `errors` | `list[str]` | `[]` | 集めた合成 API エラーメッセージ、**`text` には入らない** |
| `resumed` | `bool` | `False` | 途中で resume による継続をしたか |
| `retired` | `list[str]` | `[]` | このステップの handoff で焼き捨てた `session_id`、順序どおり |
| `context` | `int` | `0` | 最終ターンで main thread が実際に見たコンテキスト規模、すなわち handoff の判定基準 |

| 属性 | 型 | 説明 |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`、走り終えていなければ `0.0` |

---

## ワークフロー {#流程}

ソース:[`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[ワークフロー](glossary.md#流程)は順番につないだ[ステップ](glossary.md#步骤)の集まりであり、
加えてステップ間で状態をどう渡すか、いつ早期終了するかを決めるものだ。**フレームワークは既製のワークフローを提供しない。ワークフローはあなたが書く** ——
`starter_flow` は動くサンプルにすぎない。

型エイリアス `Ctx = dict[str, Any]`(`flower.workflow.base.Ctx`。`flower.workflow.__all__` にはあるが、
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

ステップの**宣言**だ。`Step` そのものは関数ではない —— 実際に実行するのは `Runtime.run(step.spec, prompt, ...)`。
先頭3つのフィールドは位置引数なので、`Step("取词", terse, "读 seed.txt …")` と書ける。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ステップ名。**プロセスをまたいで安定するキー** —— `ctx[name]`、`ctx["_results"]`、マニフェスト、リネージに残る。改名 = リネージの切断 |
| `spec` | `AgentSpec` | 必須 | どの agent を走らせるか |
| `prompt` | `str \| Callable[[Ctx], str]` | 必須 | 何を言うか。クロージャにして `ctx` を受け取り、その場で組み立ててもよい |
| `resume_from` | `str \| None` | `None` | どのステップのセッションを継続するか。指したステップがセッションを生んでいない場合は**`ValueError` を投げる**。黙って読み飛ばしはしない |
| `fork` | `bool` | `False` | `resume_from` を基点に分岐する。**`resume_from` がなければ無効** |
| `retries` | `int` | `0` | gate を通らなかったとき、あと何回試すか。`retries=0` = 1ラウンドだけ |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | 今回を合格とみなすかどうかの判定。**async でもよい**。`False` を返せば失敗。**1回の試行につき1度だけ呼ばれる** —— 副作用(ブリーフのディスク書き出しなど)を持ちうるので、重ねて発火させてはならない |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`。下記参照 |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | `False` を返すと**ステップ丸ごとスキップ**:result を生まず、`ctx["_results"]` にも入らない。**async でもよい** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | gate を通らなかったとき、**次のラウンドで何を言うか**。**async でもよい**。これを与えるとリトライの意味が変わる。下記参照 |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | 最初からではなく継続するときに使う prompt |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | `ctx[name]` に何を入れるかを決める。デフォルトは `result.text` の原文。**同期関数でなければならない** |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | `resuming` かつ `resume_prompt` があるなら後者、なければ `prompt`。呼び出し可能オブジェクトなら `ctx` を渡して呼ぶ |

**セッションのつなぎ方は3通り**(同一ラン内):

| 書き方 | 効果 |
|---|---|
| `resume_from=None`(デフォルト) | 新しいセッション。prompt に渡した文脈だけが頼り。安く、隔離される。**ただし `Workflow(continuous=True)` のときは、プロセスをまたいだリネージから同名ステップのセッションを拾う** |
| `resume_from="上一步名"` | 同じセッションを継続。文脈は完全。高く、連続する |
| `resume_from="上一步名", fork=True` | 分岐。元のセッションを汚さない。レビューや複数案の並行に使う |

**`on_reject` はリトライの意味を変える**:

- 与えない → 次の試行は**最初から**(同じ prompt、同じ `resume_from`)。
- 与える → 次の試行は**さっき否決されたセッションを継続**し、prompt はその戻り値に差し替わる。`fork` は強制的に `False`。
- 空文字列を返す → 差し戻さず、最初から走る動きに退化する。
- `result.session_id` が `None` → これも最初から走る動きに退化する。

**`on_fail` の3つの値**:

| 値 | 挙動 |
|---|---|
| `"stop"`(デフォルト) | `ctx["_failed_at"] = name` を書き、**workflow 全体を中断** |
| `"skip"` | 次のステップへ飛ぶ。**`ctx[name]` は書かれない** —— 下流の `lambda ctx: ctx["某步"]` は `KeyError` になる |
| `"continue"` | `ctx[name] = result.text`。欠けた結果を抱えたまま先へ進む |

合格・不合格にかかわらず `ctx["_results"][name] = result` は必ず書かれる。`result.session_id` が非空なら
`ctx["_sessions"]` にも書き、`lineage.remember(...)` する。

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

`Step` の列を順に走らせ、最終的な `ctx` を返す。`steps` は位置引数なので `Workflow([...])` と書ける。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `steps` | `list[Step]` | 必須 | 順番に実行する |
| `name` | `str` | `"workflow"` | ワークフロー名 |
| `context` | `Ctx` | `{}` | 初期コンテキスト辞書。**同じ `Workflow` を2回走らせると ctx は同一の dict** |
| `channel` | `HumanChannel \| None` | `None` | 止まって人に尋ねる必要があるときはここに挿す。`run()` はその `on_event` を同じ出口に自動でつなぐ。**ただし `channel.on_event is None` のときだけ**。ドライバもこのフィールドを見て誰に答えればよいかを知る |
| `workbench` | `Workbench \| None` | `None` | workflow が指定するワークベンチ。ドライバが見つけられるようにするため |
| `continuous` | `bool` | `True` | 同じパス = 同じ会話。実体は [`Lineage`](#lineage) |

| `run()` の引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `runtime` | `Runtime` | 必須・位置引数 | どのランタイムで走らせるか |
| `on_event` | `Callable[[Event], None] \| None` | `None` | イベント出口。各 `Runtime.run` にそのまま渡される |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | ステップが終わるたびに1回呼ばれる |

!!! warning "`continuous=True` はデフォルト値。`resume_from=None` は新規セッションを意味しない"
    継続が有効なとき、`run()` はまず `Lineage.open(run_dir, workspace)` を呼び、次に各レコードを
    `runtime.has_session(sid)` でまだストアに残っているか検証し、生きているものだけを `ctx["_sessions"]` に流し込む。つまり
    **`resume_from=None` のステップも、前回のあのセッションの続きとして話す** —— プロセスが kill されても、マシンが再起動しても同じだ。

    毎回まっさらなセッションにしたいなら、明示的に `Workflow(..., continuous=False)` と書くこと。
    もう一点:**ステップ名はプロセスをまたいで安定するキーであり、ステップ名を変えることはリネージを切ることに等しい。**

`run()` が ctx に書き込む**プライベートキー**(すべて `_` 始まりで、ステップ名と衝突しない):

| キー | 内容 |
|---|---|
| `_runtime` | 渡された `Runtime`。**gate の中から agent を派遣するにはこれが要る** |
| `_on_event` | イベント出口。gate 内の agent も UI に届かなければ、画面は真っ暗になる |
| `_sessions` | `dict[ステップ名, session_id]`。`setdefault` で取る |
| `_results` | `dict[ステップ名, StepResult]` |
| `_lineage` | `Lineage` オブジェクト。`continuous=True` かつ runtime に `run_dir` + `workspace` があるときだけ存在する |
| `_woke` | `lineage.bump()` の戻り値。これが何回目のウェイクか |
| `_aborted` | `StepAbort` のメッセージ |
| `_failed_at` | `on_fail="stop"` のときに失敗したステップ名 |

`Event("step")` の payload:`{"index": i, "total": len(steps), "resumed": bool, "woke": int}`。

**リトライのラベル**:0回目は `step.name`。以降は `on_reject` があれば `f"{name}#round{attempt+1}"`、
なければ `f"{name}#retry{attempt}"`。マニフェストを見れば、そのステップがどう終わったか一目でわかる。
**サフィックス付きの名前はプロセスをまたぐリネージには入らない** —— `Lineage.remember` が使うのは元の名前だ。

`runtime.on_session` は `runtime.run` の一文だけを覆い、`try/finally` で gate の前に必ず外れることを保証する。
`prompt_cur` / `resume_cur` / `fork_cur` はローカル変数で、`step` に書き戻さない —— 同じ `Step` オブジェクトが2度走る可能性があるからだ。

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

`gate` から投げる = **即座に停止し、もうリトライしない**。「`False` を返す」との違いはこうだ:`False` は「今回はダメ、もう1ラウンド」。
`StepAbort` は「もう1回やっても無駄」。

投げたあと:`ctx["_aborted"] = str(exc)`、`passed = False`、**リトライループを抜ける(残りの `retries` は消費しない)**。
そのあとは通常の失敗として `on_fail`(デフォルト `"stop"`)に従う。

`with_goal` は2か所でこれを投げる:`ctx["_runtime"]` が取れないとき、そして判定結果が `unreachable` で誰も応答しないときだ。

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

[事前確認](glossary.md#前置确认)を行う `Step` を生成する:要件を聞き切る → [`Brief`](#brief) にパース →
4節すべて揃っていれば凍結してディスクに書き出す。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必須・位置引数 | 質問チャネル |
| `brief_path` | `str \| Path` | 必須 | [ブリーフ](glossary.md#需求确认书)をどこに置くか。**実際にインデックスとして注入されるワークベンチの中に置かなければならない** |
| `prompt` | `str \| Callable[[Ctx], str]` | 必須 | 人が最初に述べた要求 |
| `name` | `str` | `"确认需求"` | ステップ名。同時に `ctx` のキーでもある |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `clarify(name, channel, instructions=instructions, **spec_kw)` を使う |
| `instructions` | `str` | `""` | [クラリファイア](glossary.md#确认者)への追加指示 |
| `always_ask` | `bool` | `False` | `True` = ブリーフの有無にかかわらず毎回聞き直す |
| `on_fail` | `str` | `"stop"` | `Step.on_fail` と同じ |
| `retries` | `int` | `0` | 4節が揃わなかったとき、あと何回聞くか |
| `**spec_kw` | | | [`clarify()`](#clarify-role) にそのまま渡される。よって `can_read=False`、`max_budget_usd=...` などが書ける |

生成される `Step` の各フィールドはこう埋まる:

- `resume_prompt = CLARIFY_RESUME`。
- `when`:`always_ask=True` → 常に `True`。そうでなければ `Brief.load(brief_path)` が揃っていれば ctx に流し込み、
  **そのうえで `False` を返す(スキップ)** —— スキップするときも流し込まないと、下流が要件を受け取れない。
- `gate`:`Brief.parse(result.text)`。欠けていれば `ctx[MISSING_KEY]` を書いて `False` を返す。
  揃っていれば `b.write(brief_path)` で凍結し、ctx に流し込んで `True` を返す。
- `reduce`:`ctx[BRIEF_KEY].prompt_block()` を返す。**モデルの原文ではない** —— 原文にはモデルが余計に書いたものが混ざりうる。
- `resume_from` は**デフォルトの `None` のまま**:次のステップは新しいセッションで、ブリーフだけを受け取り、あの一問一答は受け取らない。
  事前確認の問答はコーディネーターの文脈に**一度も入っていない**。入ってから刈り取られたのではない。

ctx に流し込む3か所:`ctx[BRIEF_KEY] = b`、`ctx[name] = b.prompt_block()`、`ctx.pop(MISSING_KEY, None)`。

| 定数 | 値 | 説明 |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` は `Brief` オブジェクト。`ctx[step.name]` はその `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | 確認に失敗したとき、どの節が欠けているか(中国語の節名)。UI 表示用 |
| `CLARIFY_RESUME` | 中国語のプロンプト文 | 「さっき途中で終わった要件確認の続きだ —— **やり直しではない**……」。この一文がないと、継続時に元の要求を新しいタスクとして再送してしまい、クラリファイアが聞いた質問をもう一度聞きかねない |

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

**目標を設定する** `Step` を生成する:[ジャッジ](glossary.md#判定者)にブリーフを読ませ、目標と判定チェックリストを書かせ、
[`Goal`](#goal) にパースしてから凍結してディスクに書き出す。`clarify_step` と同じ形をしている。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `channel` | `HumanChannel` | 必須・位置引数 | 質問チャネル |
| `goal_path` | `str \| Path` | 必須 | 目標ファイルをどこに置くか |
| `brief_key` | `str` | `"确认需求"` | `ctx[brief_key]` からブリーフ原文を取って prompt に入れる。**取れなければ `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | ステップ名 |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `judge(name, channel, instructions=instructions, **spec_kw)` を使う |
| `instructions` | `str` | `""` | 追加指示 |
| `always_set` | `bool` | `False` | `True` = 目標ファイルの有無にかかわらずチェックリストを引き直す |
| `on_fail` | `str` | `"stop"` | 同上 |
| `retries` | `int` | `0` | 同上 |
| `**spec_kw` | | | [`judge()`](#judge-role) にそのまま渡される |

**`can_run` の仮引数はない** —— 目標設定のジャッジにコマンドを走らせたいなら、`**spec_kw` 経由で `can_run=True` を渡すしかない。
渡さなければ `Bash` は手に入らず、`JUDGE_RULES` の「まず自分がどんな環境にいるかを見極めろ」という一条が実行できない。

`gate` はパースと凍結のほかに、もう1つやることがある:目標に `[此环境无法验证:…]` の項目があるとき、**その場で**
`ctx["_on_event"]` 経由で `Event("task", payload={"unverifiable", "total", "path"})` を発して警告する ——
これらの項目の運命は目標を設定するこの瞬間に決まっており、判定の時点ではもう1ラウンド分の作業費を使い切っているからだ。

**`resume_prompt` は設定していない** —— 目標設定はそもそもブリーフ全文を再送すべきだ。

| 定数 | 値 | 説明 |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` は `Goal` オブジェクト。`ctx[step.name]` は markdown |
| `VERDICT_KEY` | `"_verdict"` | 直近の [`Verdict`](#verdict)。UI 用 |
| `ROUND_KEY` | `"_goal_rounds"` | 判定が何ラウンド走ったか |

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

既存の `Step` に[ゴールガード](glossary.md#目标看守)を被せる:各ラウンドの終わりにジャッジが独立して判定し、
達成していなければ差し戻して作業を続けさせる。

戻り値は `replace(step, retries=max(0, rounds - 1), gate=<新しい gate>, on_reject=<新しい on_reject>)` ——
フィールドを1つずつ組み直すのではなく `dataclasses.replace` を使う。一度組み直したときに `resume_prompt` が漏れ、**しかもエラーにならず**、
継続時にブリーフ全文をもう一度送ってしまっただけだった。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `step` | `Step` | 必須・位置引数 | 見張られる側のステップ |
| `channel` | `HumanChannel` | 必須・位置引数 | 判定しきれないときに人へ助けを求めるチャネル |
| `goal_path` | `str \| Path` | 必須 | 目標ファイル。`ctx[GOAL_KEY]` が揃っていないときここから読む |
| `spec` | `AgentSpec \| None` | `None` | 与えなければ `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` を使う |
| `rounds` | `int` | `3` | **追加ラウンド数ではなく総ラウンド数**:`rounds=3` → `retries=2` → 作業は最大3ラウンド。`rounds=1` = 1ラウンド走って1回判定し、通らなければ失敗 |
| `instructions` | `str` | `""` | ジャッジへの追加指示 |
| `can_run` | `bool` | `False` | ジャッジが `Bash` を走らせられるか |
| `name` | `str \| None` | `None` | ジャッジの名前。デフォルトは `f"{step.name}·判定"` |
| `**spec_kw` | | | `judge()` にそのまま渡される |

`gate` は **async** で、流れはこうだ:

1. `ctx["_runtime"]` がない → **`StepAbort` を投げる**(「Runtime が取れず、目標を判定できない」)。**通ったふりをするな。**
2. `ctx[ROUND_KEY] += 1`。
3. 目標を取る:まず `ctx[GOAL_KEY]` の揃った `Goal`、なければ `Goal.load(goal_path)`、それもなければ空の `Goal()`。
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`。
   **ジャッジは独立した1回の `Runtime.run` であり、`resume` は常に `None` —— つねに新しいセッションだ**。`step_name` にはラウンド番号が付くので、
   プロセスをまたぐリネージには入らない。
5. `Verdict.parse(vr.text)` を `ctx[VERDICT_KEY]` に書く。
6. `v.achieved` → `True` を返す。
7. `unreachable` ではない(`v.ok=False` の曖昧なケースを含む)→ 曖昧なときはデフォルトの reason を1行補い、`False` を返す。
   **曖昧なものは一律で未達成とみなす** —— 「いけそうに見える」の一言で作業を打ち切らせてはならない。
8. `unreachable` → `await channel.ask(...)` で人に尋ねる。選択肢は3つ:
   - 誰も応答しない(`a.state != "answered"`)→ **`StepAbort` を投げる**。空回りを続けるのが最も高くつく選択だ。
   - 「この結果を受け入れて、このまま先へ進む」→ `True` を返す。
   - 「目標を修正する」→ もう一度新しい目標を尋ね、`g.amend(...).write(goal_path)` して `ctx[GOAL_KEY]` を更新し、`False` を返す。
   - それ以外(人が自分で書いた自由回答を含む)→ 「お前の判定が間違っている」とみなし、人の言い分を `v.reason` に記録して `False` を返す。

`on_reject` は**同期**だ:`ctx[VERDICT_KEY].feedback()` を返し、`Verdict` がなければ `""` を返す
(最初から走る動きに退化する)。

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

そのまま動く3ステップのワークフローを組み立てる:**要件確認 → 目標設定 → 作業**(ゴールガード付き)。コマンドラインの `flower` が使っているのもこれだ。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `ask` | `str` | 必須・位置引数 | 一言の要求。**ウェイク時、これは新しいタスクではなく「また一言言われたこと」だ** |
| `workspace` | `str \| Path` | `"."` | ワークスペース |
| `run_dir` | `str \| Path` | `"runs"` | ランディレクトリ |
| `new` | `bool` | `False` | `True` = リネージ + ブリーフ + 目標をアーカイブ(3つまとめて片付ける)し、最初からやり直す |
| `isolate` | `bool` | `False` | ワーカーに worktree [隔離](glossary.md#隔离)を与える。ワークベンチもそれに伴い `<ws>.parent/.flower-<ws.name>` へ移る |
| `clarify_only` | `bool` | `False` | 確認ステップだけを含む Workflow を返す |
| `goal` | `bool` | `True` | [ゴールガード](glossary.md#目标看守)を付けるかどうか。`False` = 作業ステップが終わった時点で完了 |
| `rounds` | `int` | `3` | `with_goal(rounds=)` にそのまま渡す総ラウンド数 |
| `judge_can_run` | `bool` | `False` | `with_goal(can_run=)` にそのまま渡す |
| `max_asks` | `int \| None` | `None` | `HumanChannel` にそのまま渡す。`None` = 回数無制限 |
| `timeout_s` | `float \| None` | `1800.0` | `HumanChannel` にそのまま渡す。`0` = 全自動、すべての質問は即座に空振りする |
| `instructions` | `str` | `""` | クラリファイアへの追加指示 |
| `worker_prompt` | `str` | シグネチャ参照 | ワーカーの system prompt |
| `brief_name` | `str` | `"需求.md"` | ブリーフのファイル名。`<workbench.notes>/` に置かれる |
| `goal_name` | `str` | `"目标.md"` | 目標のファイル名。同上 |
| `log_name` | `str` | `"问答记录.md"` | 問答記録のファイル名。同上 |

固定の組み立て:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# コーディネーター = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

分岐する挙動:

- `isolate=True` かつ workspace が git リポジトリでない → **`ValueError` を投げる**。`Agent` ツールがエラーを出すまで待たない
  (そのときには既に金を使っている)。
- **ウェイク判定**:`Brief.load(brief_path)` が存在し `complete()` ならウェイクとみなす。ウェイクでなく `ask` が空 →
  **`ValueError("要给一句诉求,例如 flower '帮我做一个 X'")` を投げる**。
- ウェイク時、その一言は**3か所**に同時に落ちる。1つでも欠ければ黙って効かなくなる:ブリーフへの追記
  (`ch.amend(said, label="唤醒时追加")`。既にファイルにあれば重複して書かない)、
  `goal_step(always_set=True)` によるチェックリストの引き直し(引き直さないとジャッジが読むのは古い目標のまま)、
  そしてコーディネーターへ直接届けること(その文脈にあるのは**古い**目標なので、渡さなければ古い基準で作業して新しい基準で判定されることになる)。

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

**走り出す前の読み取り専用の探査で、1バイトも書かない。** 実際に走らせる前に「これは前回の続きなのか、最初からなのか」を人に伝えるためのものだ。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | ワークスペース。位置引数 |
| `run_dir` | `str \| Path` | `"runs"` | ランディレクトリ |
| `isolate` | `bool` | `False` | ワークベンチの位置を決める。`starter_flow` に渡すのと同じ値でなければならない |
| `brief_name` | `str` | `"需求.md"` | ブリーフのファイル名 |
| `goal_name` | `str` | `"目标.md"` | 目標のファイル名 |

返る dict:

| キー | 型 | 説明 |
|---|---|---|
| `waking` | `bool` | ブリーフが存在し、4節すべて揃っている |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | 目標チェックリストの項目数。目標がなければ `0` |
| `woke` | `int` | `Lineage.woke`。これまで何回ウェイクしたか |
| `steps` | `dict` | `Lineage.steps` のコピー。ステップ名 → `session_id` |

ワークベンチの位置は**ここと `starter_flow` の2か所でだけ定義される**:`isolate=True` → `<ws>.parent/.flower-<ws.name>`
(リポジトリの外)。そうでなければ `<ws>/.flower`。ドライバがブリーフの場所を知りたいときもこの関数を通す ——
自分でパスを組み立てて間違えてもエラーにはならず、黙って効かなくなるだけだ。

---

## ロールファクトリ {#角色工厂}

ソース:[`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

5 つのロールはすべてファクトリ関数だ。各ロール = **注入される 1 段のルールテキスト + 1 組のツール + 1 組の hook**。
`worker()` が返すのは SDK の `AgentDefinition`(subagent に割り当てる用)で、残り 4 つは [`AgentSpec`](#agentspec)
(自分でセッションを 1 本立てる)を返す。

ロール自体は **hook を持たない** —— ツールを止める仕事は `Runtime._attempt` が `spec.delegate_only` に応じて自動で装着する。
[hook 層](#hook)を参照。

内部のツール群定数(エクスポートされていないが、デフォルト値を決めている):

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

[メインスレッド](glossary.md#主线程)上の[コーディネーター](glossary.md#协调者)を作る:タスクを分解し、割り当て、レポートを読み、決定を下す。
**ただし自分では手を動かさない**。最初の 3 つは位置引数。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名。デフォルトのステップ名でもある |
| `instructions` | `str` | 必須 | ドメイン指示。最終的には `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | 必須 | 配下にどのロールがいるか。`AgentSpec.agents` に入る。**それらの読み取り専用 web ツールはコーディネーター自身の `allowed_tools` にもマージされる**。下記参照 |
| `channel` | `HumanChannel \| None` | `None` | 渡すと `inbox` **と** `ask` の 2 つのツールが同時に追加され、`mcp_servers` も設定される |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`;`False` → `Read` を外す |
| `glance` | `bool` | `True` | `"Bash"` を追加し、`AgentSpec.glance` を設定する。**実際に何を実行できるかは `delegate_guard` が判断する**。ここではない |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | [予算](glossary.md#预算)上限 |
| `permission_mode` | `str` | **`"acceptEdits"`** | パーミッションモード。**このデフォルト値に注意** —— これを `clarify()`/`judge()` に渡すと、その 2 つのロールの保護が外れる |
| `compact` | `CompactPolicy \| None` | `None` | 渡せば `Runtime` に `no_summary` へ強制変更されない |
| `hooks` | `dict[str, Any] \| None` | `None` | 追加の hook。`workbench_hooks` とマージされる |
| `env` | `dict[str, str] \| None` | `None` | 追加の環境変数 |

返される `AgentSpec` で固定される 3 項目:`delegate_only=True`、`agents=workers`、
`workbench` は `AgentSpec` のデフォルト `True` のまま。

#### `workers` の web ツールがマージされる {#coordinator-web-merge}

リストを組み立てた後、`coordinator()` は各 `AgentDefinition.tools` を走査し、
`WEB_TOOLS`(`WebFetch`、`WebSearch`、`roles.py:33`)に含まれるものをコーディネーター自身の
`allowed_tools` にも 1 つ追加する(`roles.py:523-526`)。

**理由:`allowed_tools` は `disallowed_tools` と同じくセッション単位だからだ。** この点についてはこの文書中で最も硬い証拠であり
—— 影響はメインスレッドだけに留まらない。このセッション単位のリストにないツールは、**subagent** が呼ぶときにもパーミッション承認を通る。
無人運転では承認する人がいないので、harness は
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`)を返し、モデルは同じ呼び出しを何度もリトライする。実測で踏んだ:ワーカーに
`WebFetch`/`WebSearch` を追加したのに `AgentDefinition.tools` にしか書かず、その novel の実行は 20 回以上
user-rejected を出し、1 文字も書けなかった(`roles.py:513-518`)。

2 つのフィールドのセッション単位という性質は同じだが、**症状が違う**:`disallowed_tools` はその場でエラー、
`allowed_tools` は静かに死ぬまでリトライ。後者のほうが追いにくい。画面上は何もエラーらしく見えないからだ。

**マージするのは読み取り専用で副作用のないものだけ。** `Write`/`Edit`/`Bash` は **意図的にマージしない**:メインスレッドがそれらを無承認で使えるようになった時点で、
`delegate_guard` の「コーディネーターは手を動かさない」という壁が無意味になる。しかも subagent の `Bash`/`Write`
はもともと通る(実測 462 回の許可、`roles.py:520-522`)。

ソースには **`disallowed_tools` で「調整だけして手を動かさない」を実装するな** と明記されている —— あれはセッション単位で、
subagent の `Bash`/`Write` まで一緒に禁止してしまう。[`AgentSpec`](#agentspec) の警告を参照。
正しいやり方はここにある `delegate_only=True` + `allowed_tools` に入れない、であり、
そのうえで [`delegate_guard`](#delegate-guard) が `agent_id` を見てメインスレッドだけを止める。

`channel` を渡すと **2 つのツールが一緒に来る**。選べない:MCP server を付けた時点で両方が存在し、
`allowed_tools` は排他ではないので、書いても書かなくても呼べる。無人運転では `ask` のたびに `timeout_s` を丸ごと待つ ——
その場面では `HumanChannel(timeout_s=0)` を使う。

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

実際に作業する [subagent](glossary.md#subagent) の定義を作る。最初の 2 つは位置引数。
返るのは SDK の `AgentDefinition` で、そのまま `coordinator(workers={...})` に入れられる。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `description` | `str` | 必須 | **コーディネーターが人選に使う根拠** —— 「どんな仕事を任せるか」をはっきり書く |
| `prompt` | `str` | 必須 | その system prompt。`discipline=True` のとき `f"{prompt}\n\n{WORKER_RULES}"` に連結される |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | ワーカーを格下げすべきではない |
| `effort` | `str \| int \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | SDK の **`maxTurns`**(キャメルケース)に入る |
| `permission_mode` | `str \| None` | `None` | SDK の **`permissionMode`**(キャメルケース)に入る |
| `skills` | `list[str] \| None` | `None` | 使用を許す skill |
| `discipline` | `bool` | `True` | `WORKER_RULES` の報告規律を連結するかどうか |
| `isolate` | `bool` | `False` | [隔離](glossary.md#隔离)マークを付け、`isolated()` を通す。**`AgentDefinition` のフィールドではない** |

`isolate=True` は workspace が git リポジトリであることを要求する。そうでなければ `Agent` ツールが直接 `"not in a git repository"` を返し、
**静かに劣化はしない**。しかもマークは Python の属性なので —— `AgentDefinition` に `dataclasses.replace()` をかけると
失われ、隔離が静かに無効化される。

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

[クラリファイア](glossary.md#确认者)を作る:手を動かす前に要件を明確にする。作業はせず、質問だけをして、最後にちょうど 4 セクションを出力する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名、位置引数 |
| `channel` | `HumanChannel` | 必須 | 質問チャネル、位置引数 |
| `instructions` | `str` | `""` | 追加指示。`CLARIFIER_RULES` の後に連結される |
| `can_read` | `bool` | `True` | `True` のとき `Read` `Glob` `Grep` `WebFetch` `WebSearch` を追加 |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | **ターン数無制限** |
| `max_budget_usd` | `float \| None` | `None` | 予算上限 |

返される `AgentSpec`:`allowed_tools = [channel.tool_name] + (読める場合はその 5 つ)`、
`mcp_servers = channel.mcp_servers()`、`workbench=False`(書き込みツールを持たないのでインデックスは無意味)、
`permission_mode` は `AgentSpec` のデフォルト `"default"` を継承。
**`Write` / `Edit` / `Bash` / `Agent` はなく、`inbox` もない**(コーディネーターとは違う)。

!!! warning "`max_turns` を小さくすると「回数無制限の質問」が空文句になる"
    質問 1 回が 1 ターンだ。`max_turns=16` は「せいぜい十数個まで」を意味し、チャネル側の「ターン数上限なし」はその場で無効になる。

    質問を開放したいなら **2 箇所を同時に** 開ける必要がある:`HumanChannel.max_asks`(デフォルトは既に `None` = 無制限)
    と `max_turns`(デフォルトは既に `None`)。

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

[ジャッジ](glossary.md#判定者)を作る:走り出す前に目標を設定するか、各ラウンドの終わりにそのラウンドを判定するか、どちらかをする。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | 必須 | ロール名、位置引数 |
| `channel` | `HumanChannel` | 必須 | 質問チャネル、位置引数 |
| `instructions` | `str` | `""` | 追加指示。`JUDGE_RULES` の後に連結される |
| `can_run` | `bool` | `False` | `True` のときホワイトリストに `Bash` を追加。`whitelist_guard` もそれに応じて `Bash` を通し、`Write`/`Edit` は止め続ける |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | 予算上限 |

返される `AgentSpec`:`allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (`can_run` のとき)`["Bash"]`、
`workbench=False`、それ以外は `clarify()` と同じ。**`Write` / `Edit` / `Agent` はなく、`inbox` もない。**

**トレードオフ**:`can_run=True` は判定が硬くなる(受け入れコマンドを実際に走らせられる)が、代償としてジャッジがワークスペースを変更できるようになる ——
`Bash` 自体がファイルを書けるからだ。絶対に中立な判定が欲しいなら開けない。

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

[オラクル](glossary.md#旁路顾问)を作る:実行がまだ走っている最中に「いまどこまで進んだ?」と聞くと、直近のイベントとワークベンチを一目見てから答える。
**その発言はその実行のコンテキストには入らない。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | ロール名、位置引数 |
| `instructions` | `str` | `""` | 追加指示。`ORACLE_RULES` の後に連結される |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | **`12`** | デフォルトでブレーキ付き |
| `max_budget_usd` | `float \| None` | **`0.5`** | デフォルトでブレーキ付き。これは「ついでに一言聞く」ものであり、暴走してはいけない |

返される `AgentSpec`:`allowed_tools = ["Read", "Glob", "Grep"]`(**channel なし** —— 質問はせず、
答えるだけ)、`workbench=True`(**5 つのロールの中で唯一、コーディネーターでないのにワークベンチを開くもの** —— 成果物とノートを読みに行くのが仕事だから)。

### 5 つのルールテキスト {#rules}

5 つの定数はすべて `__all__` に入っており、直接 `import` して読む・連結する・書き換えることができる。

| 定数 | 注入先 | 注入方法 | 要点 |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | あなたは「Claude Code を使える人」であって、ワーカーではない。ファイルを書く/コードを直す/テストを走らせるのは禁止。`Bash` は「一目見る」程度で、結果は古くなる。**[タスクブリーフ](glossary.md#任务书)には今回のタスク固有のことだけを書く**。まだ伝える必要がある唯一の決まりは「ワークベンチの場所 + 長い成果物は `artifacts/` へ + 返答はパスだけ」。一区切りの動作が終わるたびに `inbox` を 1 回見る。`ask` はブロックするので、本当の分岐点でのみ使う |
| `WORKER_RULES` | `worker()` | subagent の `prompt` の **後ろ** に連結 | 返答フォーマットは **結論 / 根拠 / 成果物 / 未検証**、30 行を超えない。ファイル内容・コマンド出力・ログ・diff 原文の貼り付けは禁止。試行錯誤の過程の再現も禁止。手を動かす前にまず `.flower/scripts/` を見る。**「長い成果物は `artifacts/` へ」は意図的に書いていない** —— 実際のパスは `Workbench` が生成するので、ハードコードすると間違う |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | 作業はせず、要件を問い詰めるだけ。**回数制限はなく、はっきりするまで聞く**。人が不在のこともあるので、タイムアウトしたら自分で判断して「未知与假设」に書く。出力は**ちょうど 4 セクション**。コードを書かない、ファイル内容を貼らない |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | 2 つのうちどちらか一方。**目標設定**:各チェック項目はその場で検証可能でなければならない。リストの長さは失敗のしかたの数で決まる。**境界は判定項目ではない**。検証できない項目は末尾に `[此环境无法验证:原因]` を付ける。**そのラウンドの判定**:出力は**ちょうど 3 セクション**、判定対象は**成果物であってソースではない**。「やり終えた」はデフォルトで信じない。「達成できていない」と「ここでは検証できない」は別々の結論であり、後者は**絶対に合格にしてはいけない** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | あなたはバイパス。その実行はまだ走っており、あなたは中断もせず参加もしない。**読み取り専用**。答えたら捨てられ、あなたの発言はその実行のコンテキストには入らない。手元にあるのは「直近イベントのウィンドウ」と「ワークベンチ」だけ。まず見てから答え、答えられなければ答えられないと言う、短く |

---

## agent 定義 {#agent-定义}

ソース:[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` は 1 つの専用 agent の完全な宣言であり、`build_options` がそれを SDK の `ClaudeAgentOptions` にコンパイルする。
[ロールファクトリ](#角色工厂)が返すのがこの `AgentSpec` だ —— ファクトリの外の組み合わせが必要なら、直接構築すればいい。

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
| `name` | `str` | 必須 | ロール名。`Runtime.run` のデフォルト `step_name` でもあり、`whitelist_guard` の拒否メッセージ中の自称でもある |
| `instructions` | `str` | 必須 | ドメイン指示。**Claude Code ネイティブの system prompt の後ろに[アペンド](glossary.md#叠加)される。置き換えではない** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **無承認リストであって排他ホワイトリストではない** —— モデルはここにないツールも呼べる。排他は [`whitelist_guard`](#whitelist-guard) が担う |
| `disallowed_tools` | `list[str]` | `[]` | **セッション単位**。下の警告を参照 |
| `model` | `str \| None` | `None` | モデル |
| `effort` | `str \| None` | `None` | 思考強度 |
| `max_turns` | `int \| None` | `None` | ターン数上限 |
| `max_budget_usd` | `float \| None` | `None` | [予算](glossary.md#预算)上限 |
| `permission_mode` | `str` | `"default"` | パーミッションモード |
| `agents` | `dict[str, Any] \| None` | `None` | subagent 定義テーブル。値は `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP server テーブル。`HumanChannel.mcp_servers()` がそのままここに入る |
| `hooks` | `dict[str, Any] \| None` | `None` | 追加の hook。`Runtime` が `merge_hooks` で自前のものとマージする |
| `compact` | `CompactPolicy \| None` | `None` | 渡せば `Runtime` に `no_summary` へ強制変更されない |
| `env` | `dict[str, str]` | `{}` | 子プロセスに注入する環境変数。`compact.env()` が update される |
| `glance` | `bool` | `False` | コーディネーター自身が「一目見るだけ」の `Bash` を実行するのを許す。何を通すかは [`is_ephemeral`](#is-ephemeral) が決め、結果は `EphemeralPolicy` によって期限切れとマークされる |
| `workbench` | `bool` | `True` | この agent の system prompt にワークベンチのインデックスを注入するか。**書き込みツールを持たないロールでは切るべき**(`clarify()` / `judge()` はデフォルトで `False`) |
| `delegate_only` | `bool` | `False` | 調整だけで手を動かさない。`True` のとき `Runtime` は `delegate_guard` を装着し、`whitelist_guard` は **装着しない** |

!!! warning "`disallowed_tools` はセッション単位で、subagent まで禁止してしまう"
    実測のエラー原文:`"Bash is disabled for this session, in subagents as well as here"`。
    つまり、コーディネーターに手を動かさせないつもりで `disallowed_tools=["Bash"]` を使うと、送り出したワーカーもコマンドを実行できない ——
    実行全体が台無しになる。

    「調整だけして手を動かさない」を実現するには、`delegate_only=True` + `allowed_tools` に入れない、を使い、
    [`delegate_guard`](#delegate-guard) に `agent_id` を見てメインスレッドだけを止めさせる。

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

`AgentSpec` を SDK の `ClaudeAgentOptions` にコンパイルする。`Runtime._attempt` が内部で呼んでいるのがこれだ。
自分で SDK を駆動する(`Runtime` を使わない)場合もここから入る。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `spec` | `AgentSpec` | 必須、位置引数 | コンパイル対象の宣言 |
| `cwd` | `str \| Path \| None` | `None` | `None` でないときだけ `cwd` に書き込む |
| `session_store` | `SessionStore \| None` | `None` | `None` でないときだけ `session_store` と `session_store_flush` を書き込む |
| `resume` | `str \| None` | `None` | どのセッションを再開するか |
| `fork` | `bool` | `False` | `fork_session` になる。**`if resume:` の中にネストされている** |
| `resume_at` | `str \| None` | `None` | `resume_session_at` になる。**これも `if resume:` の中** |
| `use_plugin` | `bool` | `True` | `True` かつ `PLUGIN_DIR` が存在 → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`;`False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | 追加で許可するディレクトリ。**ワークベンチがワークスペースの外にあるときは必須** |
| `flush` | `str` | `"eager"` | `session_store_flush` になる |
| `prelude` | `str` | `""` | `instructions` の後ろに追加される 1 段(ワークベンチのインデックスはここを通る) |

対応関係:

| 生成される option キー | 値 |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | `spec` からそのまま |
| `setting_sources` | `[]`(ポータブル)または `["project"]` |
| `plugins` | リポジトリルートの `plugin/` ディレクトリが存在するときだけ |
| `cwd` / `add_dirs` | 空でないときだけ書き込む |
| `session_store` / `session_store_flush` | `session_store` が `None` でないときだけ書き込む |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | それぞれ空でないときだけ書き込む |
| `env` | `dict(spec.env)` に `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **`resume` が真のときだけ有効** |

`PLUGIN_DIR` はリポジトリルートの `plugin/`(`flower/core/agent.py` から 3 階層上)。pip でインストールしただけではこのディレクトリが存在するとは限らないので、
コードは `is_dir()` で判定している。

!!! warning "`fork=True` に `resume` を渡さないと静かに無効になる"
    `fork_session` と `resume_session_at` はどちらも `if resume:` の中にネストされている —— `resume` を渡さなければ一切効かず、
    **エラーも出ない**。同様に `Runtime.run(resume_at=...)` も `resume` を渡したときだけ効き、
    しかも **`Workflow` は `resume_at` を決して渡さない**:メッセージ単位で巻き戻したいなら `Runtime.run` を直接呼ぶしかない。

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

auto-[compact](glossary.md#压缩) のスイッチパネル。成果物は子プロセスに注入する環境変数の組だ。
compact のアルゴリズム自体は harness のバイナリの中にあり変更できない。変えられるのは「発火するかどうか」だけ。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = 何も設定しない。閾値 = ウィンドウ − 33k;`"no_summary"` → `DISABLE_AUTO_COMPACT=1`;`"off"` → `DISABLE_COMPACT=1`(`/compact` まで含めて無効化)。**それ以外の値は `ValueError` を投げる**。静かに無視はしない |
| `window` | `int \| None` | `None` | `None` でない → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`。CLI 側の制限は 100k–1M で、100k 未満を設定すると 100k に引き上げられる |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `env` | `() -> dict[str, str]` | 環境変数を生成する。**不正な `mode` はここで `ValueError` を投げる。コンストラクタではない** —— `build_options` から呼ばれるので、エラーは `Runtime.run` の中で露出する |

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

コンテキストが埋まりかけたときに compact ではなく「[引き継ぎ書](glossary.md#交接书)を書いて新しいセッションに切り替える」ためのポリシーオブジェクト。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 切ると auto-compact に戻る |
| `window` | `int` | `default_window()` | モデルのコンテキストウィンドウをどれだけと見なすか |
| `headroom` | `int` | `50_000` | どれだけ余裕を残すか。理由:auto-compact はウィンドウ −33k で発火するので、世代交代はその前に間に合わせる必要があり、しかも「引き継ぎを書く」こと自体に 1 ターン要る |
| `max_generations` | `int` | `8` | 1 ステップで何世代まで交代するか。**これは暴走防止のブレーキであって、容量計画ではない** |

| プロパティ | 型 | 説明 |
|---|---|---|
| `at` | `@property -> int` | 世代交代の閾値 `max(10_000, window - headroom)`。**10k の下限がある** —— これより低いと引き継ぎすら書けない |
| `warn_at` | `@property -> int` | 接近通知の位置 `max(1_000, at - 20_000)`。1 世代につき 1 回だけ送る |

!!! warning "`window` を小さくしすぎると無限に世代交代して金が燃える"
    `at` がそのロールの**起動フロア**(コーディネーターは実測で約 34k)を下回ると、新しいセッションは口を開いた瞬間に線を越える。しかも
    **世代交代はリトライ枠を消費しない**(`attempt -= 1`)ので、無限に空回りする。唯一のブレーキは `max_generations=8` で、
    それにぶつかると `error` が診断メッセージに差し替わり、`window` を大きくするか世代交代を切るよう促す。

### `default_window()` {#default-window}

```python
def default_window() -> int
```

環境変数 `ANTHROPIC_MODEL` または `ANTHROPIC_DEFAULT_OPUS_MODEL` の**モデル名文字列**からコンテキストウィンドウを推測する:

| 条件 | 戻り値 |
|---|---|
| 名前に独立した `1m` という語がある(正規表現 `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| 名前に `haiku` を含む | `200_000` |
| その他(**両方の変数が未設定の場合も含む**) | `1_000_000` |

**デフォルトは強気の値を取る**。大きく見積もっても致命傷ではない:API が `prompt is too long` で弾き返し、`Runtime` はこのシグナル
(内部の `is_overflow`)を認識してその場で世代交代する —— ただしその世代の引き継ぎは劣化版になる。

---

## 文書 {#文书}

ソース:[`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

4 つの dataclass。どれも「モデルの返答を決まった数のセクションにパースし、ディスクに書き出す」ものだ。共通の形:
`parse()` でパース、`missing()` / `complete()` で揃っているか確認、`to_markdown()` は人が読む用、
`prompt_block()` は下流のモデルが読む用、`write()` / `load()` で書き出しと読み戻し。

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

[要件確認書](glossary.md#需求确认书)。**ちょうど 4 セクション**、順序は固定で
`goal` → `accept` → `bounds` → `unknowns`。中国語のセクション名はそれぞれ「目标」「验收标准」「边界」「未知与假设」。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `goal` | `str` | `""` | 目標 |
| `accept` | `str` | `""` | 受け入れ基準 |
| `bounds` | `str` | `""` | 境界 |
| `unknowns` | `str` | `""` | 未知と仮定 |
| `path` | `Path \| None` | `None` | 書き出し先。`compare=False` なので等価判定には参加しない |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `missing` | `() -> list[str]` | 欠けているセクションの**中国語名**。そのまま表示できる |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | モデルの返答から 4 セクションをパースする。**先にフェンス付きコードブロックを剥がす**。取れなかったものは空のまま |
| `to_markdown` | `() -> str` | ヘッダのメタ情報付きの完全な文書。空のセクションは `"(未填)"` と書く |
| `prompt_block` | `() -> str` | 下流に食わせるコンパクト版。**空でないセクションのみ**、メタ情報なし |
| `write` | `(path: str \| Path) -> Path` | 親ディレクトリを作り、ディスクに書き、`self.path` を resolve 後のパスに設定して返す |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | ファイルが存在しないか `OSError` なら `None` を返す。**`"(未填)"` のプレースホルダは空文字列に戻す** |

パースのルール(間違いが集中するところ):

- フェンスを剥がすとき、**閉じられていない ``` や `~~~` に出会ったらそこから後ろを丸ごと捨てる** —— 実測でクラリファイアはコード全体を返答に貼り付けてくる。
  モデルの出力が途中で切れると、以降のセクションが一切パースできなくなり、`complete()` が `False` になって gate が差し戻す。
- 見出しの正規表現は `## 目标` / `**目标**` / `目标:` / `3. 边界` を許容し、見出しの直後に本文が続く形も許容する。
- 別名テーブルは長さの降順でコンパイルする。そうしないと「未知」が「未知与假设」を先に食ってしまう。
- 同名のセクションが複数回現れた場合は**最初に中身のあるもの**を取る。
- 確認書を手で編集するときに `to_markdown()` の `"(未填)"` プレースホルダをそのまま写すと、そのセクションは依然として欠けている扱いになる。

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

[世代交代](glossary.md#换代)のときに書く[引き継ぎ書](glossary.md#交接书)。5 セクション。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `doing` | `str` | `""` | 何をしているか。**必須** |
| `decided` | `str` | `""` | 何が決まったか |
| `deadends` | `str` | `""` | 通らなかった道 |
| `next` | `str` | `""` | 次の一手。**必須** |
| `scene` | `str` | `""` | 現場 |
| `step` | `str` | `""` | 文書のヘッダにのみ使う。**パースには関与しない** |
| `path` | `Path \| None` | `None` | 書き出し先 |

**必須は `doing` と `next` の 2 セクションだけ** —— 「通らなかった道」を空にできないと強制すると、モデルは捏造する。

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `missing` | `() -> list[str]` | **必須の 2 セクションだけを確認する** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | 本文に劣化マーカー `[降级:交接没写成]` が含まれているか |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | `Brief` のセクション分割器を再利用する |
| `to_markdown` | `() -> str` | 空のセクションは `"(空)"` と書く |
| `prompt_block` | `() -> str` | **ヘッダで引き継ぎ手に「あなたは引き継いでいる」とはっきり伝える**。振り返って人に背景を要求するのを防ぐ |
| `write` | `(path) -> Path` | `Brief.write` と同じ |
| `load` | `@classmethod (path) -> Handoff \| None` | `Brief.load` と同じ |

同じモジュール内にある、**エクスポートされていないが意味的に重要な** 3 つのメンバー:`is_overflow(*texts)` は `prompt is too long`、
`context length exceeded`、`maximum context length`、`too many total text bytes`、
`input length and max_tokens exceed` などにマッチし、「ハードエラー」を「その場での世代交代」に変える;`HANDOFF_PROMPT` は
**現在のセッション自身**に引き継ぎを書かせるプロンプト(`{used}` `{window}` の 2 つのプレースホルダを含む。**新しいロールではない** ——
そのコンテキストを持っているのは自分だけだから);`degraded(step, prompt, *, why="")` は引き継ぎが書けなかったときに機械的に 1 部を組み立て、
`scene` には元のタスクの先頭 **1200** 文字を入れる。

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

[目標ガード](glossary.md#目标看守)における目標 + 判定チェックリスト。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `statement` | `str` | `""` | 目標の記述 |
| `checks` | `list[str]` | `[]` | 判定チェックリスト。1 行 1 項目 |
| `path` | `Path \| None` | `None` | 書き出し先 |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | `checks` のうち `[此环境无法验证:…]` が付いた項目。**目標を設定したその瞬間に不合格が確定している** |
| `missing` | `() -> list[str]` | `statement` が空でなく、**かつ** `checks` が空でないことを要求する |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` は 1 行 1 項目。`-` / `*` / `1.` の記号は自動で取り除く |
| `to_markdown` | `() -> str` | リストが空のときは `"(空)"` と書く |
| `prompt_block` | `() -> str` | 下流に食わせるコンパクト版 |
| `write` / `load` | `Brief` と同じ | 書き出しと読み戻し |
| `amend` | `(extra: str) -> Goal` | **上書きではなく追記**:`statement` の後ろに `"\n\n(已修改)" + extra` を連結し、`self` を返す |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

[ジャッジ](glossary.md#判定者)による 1 ラウンドの判定結果。**ちょうど 3 セクション**:結論 / 理由 / 未通過。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`。パースできなかった場合は `""` |
| `reason` | `str` | `""` | 理由 |
| `failed` | `list[str]` | `[]` | 通らなかったチェック項目 |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | 結論をパースできたかどうか。**`ok=False` は「未達成」として扱わねばならず、達成として扱ってはいけない** |
| `parse` | `@classmethod (text) -> Verdict` | 下記参照 |
| `feedback` | `() -> str` | ワーカーに差し戻すときの言葉:「どこが足りないか」だけを渡し、解決策は渡さない |

`parse` の識別順序:

1. まず見出しセクションで「结论」/「判定」を取る。
2. 見出しセクションがない場合、全体を strip して `fullmatch(r"1|true")` → 達成;`fullmatch(r"0|false")` → 未達。
3. それ以外は結論テキストの中を状態語テーブル(**長い語が先**)で走査し、最初にヒットした語を取る。
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」はすべて `unreachable` に寄せる** ——
   実測で踏んだ:ターゲットプラットフォームが macOS で Linux コンテナ上で走っており、ジャッジがソースの分岐を見ただけで合格を出した。
4. それでも決まらなければ、孤立した `\b1\b` を探して達成、`\b0\b` を探して未達。
5. すべて外れたら `state=""`、`ok=False`。

`unreachable` と `not_yet` は**別々の結論**だ:前者は「立ち止まって人に聞く」道に進むのであって、「もう 1 ラウンド」ではない。

---

## hook 層 {#hook}

ソース:[`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

この層は flower の**実行境界**である:どのツールを main thread に触らせないか、長すぎる結果をどう刈るか、
どの役割を独立した worktree に送るか、すべて SDK hook が強制する。**prompt には頼らない**。理由は単純で ——
prompt は提案でしかなく、モデルは従わなくてよい:system prompt に「worktree を使うな」と明記していても、
`isolate_guard` の注入はそのまま効くことを実測している(モデルが渡したのは `None`、実際に適用されたのは `'worktree'`)。

エクスポートは 9 つ:`HookMatcher` を返す guard ファクトリ 5 つ(`whitelist_guard` は `None` を返しうる)、組み立て関数 1 つ、マージ関数 1 つ、isolation マーカー関数 2 つ。
手で登録する必要はない —— [`Runtime`](#runtime) が `AgentSpec` に応じて自動で組み立てる。手で登録するのは自分で SDK を直接駆動する
(`Runtime` を通さない)場合だけだ。

**main thread の判定は 1 つの関数に統一されている**:`_is_main_thread(data) = not data.get("agent_id")` ——
subagent の tool-lifecycle hook データには `agent_id` が入り、[main thread](glossary.md#主线程) には入らない。
「main thread だけを止める」guard はすべてこの 1 行に依っている。

ツールグループ定数(モジュールレベル、未エクスポート。ただしデフォルト matcher を決める):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### 早見表:どの guard がどの SDK イベントに付くか {#hook-速查表}

| 関数 | SDK hook イベント | matcher | 止める対象 | 何を返すか | 誰が登録するか |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` のうち **`allowed_tools` に無い**もの | **main thread のみ**の禁止ツール呼び出し | `permissionDecision: "deny"` + 理由 | `Runtime._attempt`、**`spec.delegate_only is False` のときのみ** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit`(`tools=` で変更可) | **main thread のみ**の手作業;`allow_glance=True` のときは `is_ephemeral()` を通った `Bash` は許可 | `deny` +「subagent を派遣せよ」 | `workbench_hooks(delegate_only=True)`、**`Runtime` に workbench がある場合のみ** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` に `cwd` も `isolation` も無く、かつ `subagent_type` が `isolated()` でマークされている | `permissionDecision: "allow"` + `updatedInput`(`isolation="worktree"` を注入) | `workbench_hooks`、**`agents` にマーク済みの役割がある場合のみ** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` が `workbench.root` 内に落ちる場合 | `{}`(副作用は `workbench.refresh()`) | `workbench_hooks`、常に登録 |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | `tool_response` 内の ≥ `threshold` 文字の**文字列フィールド**;spill ディレクトリ自体の読み取りは許可 | `updatedToolOutput`(spill + 1 行のポインタ + 先頭 400 文字) | `workbench_hooks`、**`spill_threshold` が真のときのみ** |

**この表から読み取れる重要な帰結**:`Runtime(workbench=False)` のときは `workbench_hooks` が丸ごと登録されない。
そして `delegate_only=True` の coordinator では `whitelist_guard` もスキップされる —— **main thread には壁が 1 枚も無い**。
詳細は [Runtime](#runtime) の警告を参照。

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**`allowed_tools` を、手を動かす 4 つのツールに対して本当に排他的にする。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `allowed` | `list[str] \| None` | 必須、位置引数 | 通常はそのまま `spec.allowed_tools` を渡す |
| `role` | `str` | `"这个角色"` | 拒否文中の自称。`Runtime` は `spec.name` を渡す |

- **`PreToolUse` に付く**。matcher は `"|".join(banned)`、`banned` = `Bash` `Write` `Edit` `NotebookEdit`
  のうち `allowed` に無いもの。
- ヒットしたら `permissionDecision: "deny"`。文面の趣旨:「XX には YY が無い。**これは意図的であって、設定漏れではない。**
  結論は返答本文に書け、フレームワークはそこから拾う —— 別の書き方で回避しようとするな。」
- **止めるのはこのセッションの main thread だけ**で、subagent は通す —— subagent のツールは `AgentDefinition.tools` が決める。
- 止めるべきツールが 1 つも無い場合は **`None`** を返す(たとえば `worker()` のようなフルセットの役割)。呼び出し側はこれを見て登録するかを決める。

**なぜこれが必須か**:`allowed_tools` は**承認不要リストであって、排他的ホワイトリストではない**。実測での証拠が 2 つ ——
目標を設定した judge が `Bash` を 11 回実行した;$0.1 のプローブでは
`allowed_tools=["Read"]` の agent が普通に `Write`/`Bash` を呼べた。
したがって `clarify()` / `judge()` の「書き込みツールが無い」状態は**この hook によるもの**であって、ホワイトリスト自体によるものではない。

利点は `allowed_tools` から派生している点で、`judge(can_run=True)` は自動的に `Bash` を残しつつ
`Write`/`Edit` は止め続ける —— 追加のスイッチは要らない。

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**main thread が自分で手を動かす → 拒否し、行き先を示す。**

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher。正規表現文字列であってリストではない |
| `allow_glance` | `bool` | `False` | `True` のとき `tool_name == "Bash"` かつ [`is_ephemeral(command)`](#is-ephemeral) が真なら通す |

- **`PreToolUse` に付く**。matcher はそのまま `tools`。
- main thread がこの 4 つのツールを呼ぶ → deny。理由の中で**次に何をすべきか**を示す:`Agent` ツールで subagent を派遣し、
  タスクに目標と受け入れ基準を明記し、長い成果物は `.flower/artifacts/` に書き、返答にはパスと結論だけを載せるよう要求する。
- subagent は一律に通す。

`whitelist_guard` との違いは**言い回し**である:止めるツールは同じだが、こちらは「人を派遣しろ」と言うので、より筋が通る。
だから `delegate_only=True` の役割にはこちらだけを登録する。両方登録するとモデルは矛盾した 2 つの指示を受け取る。

`allow_glance=True` の許可判定と「結果が刈られるかどうか」は**同じ関数**([`is_ephemeral`](#is-ephemeral))である ——
許可集合は期限切れ集合と一致していなければならず、片方を変えたらもう片方も変えなければならない。

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

閾値を超えたツール結果をその場で[spill](glossary.md#落盘) し、コンテキストには 1 行のポインタだけを残す ——
コンテキストが埋まってから遡って compact するのではない。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | spill 先は `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | 何文字を超えたら spill するか |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False`(デフォルト)= subagent の結果も spill する |

- **`PostToolUse` に付き**、
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <刈った後>}}` を返す。
- spill ファイル名は内容の `sha256` 先頭 16 桁 + `.txt`。コンテキストでは 1 行のポインタ + **先頭 400 文字**に置き換わる。
- `updatedToolOutput` は**元のツールの出力構造を保たなければならない**ので、dict 内の長すぎる**文字列フィールド**だけを差し替える。
  **list には一切触れない**(中身が画像ブロックである可能性がある)。構造が合わないと拒否される(原文のまま、エラーは出ない)。
- **spill ファイル自体を読むときは必ず通す** —— でないと「`Read` でそれを読む」は空文句になる:読み戻した全文がまた spill され、無限ループになる。
  実測でぶつかった。モデルは 5 通りの書き方で回避を試みた。

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

[workbench](glossary.md#工作台) に何かを書いたら `INDEX.md` を更新し、次の agent が開始時点でその存在を知れるようにする。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | 判定範囲であり、更新対象でもある |

**`PostToolUse` に付き**、matcher は `"Write|Edit"`。`tool_input["file_path"]` を resolve した結果が
`workbench.root` 内なら `workbench.refresh()` を呼ぶ。**常に `{}` を返す** —— 何も書き換えず、副作用だけを持つ。

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

役割ごとに subagent へ独立した git worktree を割り当て、[isolation](glossary.md#隔离) を実現する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | 必須、位置引数 | 役割テーブル。`subagent_type` がマークされているかを引くのに使う |
| `on_inject` | `Any` | `None` | 任意のコールバック。`on_inject(subagent_type, description)` の形で呼ばれる |

**`PreToolUse` に付き**、matcher は `"Agent"`。3 つの条件が同時に成り立つときだけ注入する:`tool_name == "Agent"`、
`tool_input` に **`cwd` も `isolation` も無い**、`subagent_type` に対応する役割が `isolated()` でマークされている。
成立すれば `permissionDecision: "allow"` + `updatedInput`(`isolation` を `"worktree"` に設定)を返す。

`isolation` と `cwd` は `Agent` ツールにおいて**排他**である —— モデル自身が `cwd` を指定したならそれを尊重する。
「隔離するかどうか」は**役割の属性**であって、グローバルスイッチでも、派遣のたびに判断するものでもない。隔離が不要な役割には 1 バイトも追加されない。

**隔離を有効にするなら [workbench](glossary.md#工作台) をリポジトリの外に出すこと。** 隔離された agent は共有 checkout に書き込めないので、
workbench は `home=` でリポジトリ外を指す必要がある。`starter_flow(isolate=True)` は
`<ws>.parent/.flower-<ws.name>` を、`Runtime(workbench=True)` は `<run_dir>/workbench` を使う ——
どちらもリポジトリ外だが、**同じディレクトリではない**。混ぜて使わないこと。

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

subagent 定義に「独立した作業領域が必要」というマークを付け、またそれを読み戻す。

| 関数 | 引数 | デフォルト | 説明 |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | 必須 | マークを付ける定義。**返るのは同一オブジェクト** |
| | `flag: bool` | `True` | 位置引数。`False` = マークを外す |
| `wants_isolation` | `agent: AgentDefinition \| None` | 必須 | `None` も受け付け、その場合 `False` を返す |

マークは `object.__setattr__` で付けた Python 側の属性 `_flower_isolate` であって、**dataclass のフィールドではない** ——
SDK は `asdict()` でシリアライズし、宣言済みフィールドしか見ないので、このマークが CLI 側に漏れることはない(実測済み)。

**代償**:`AgentDefinition` に `dataclasses.replace()` をかけるとこのマークが失われ、隔離が黙って無効になる。

`worker(isolate=True)` は内部で `isolated()` を使っている。

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

workbench に必要な hook をまとめて登録する。`Runtime._attempt` が呼ぶのはこれ。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workbench` | `Workbench` | 必須、位置引数 | `index_guard` と `spill_guard` に渡される |
| `delegate_only` | `bool` | `True` | `True` のときだけ `delegate_guard` を登録 |
| `spill_threshold` | `int \| None` | `4000` | 真のときだけ `spill_guard` を登録 |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | この中に **1 つでも** `isolated()` マーク済みがあれば `isolate_guard` を追加 |
| `allow_glance` | `bool` | `False` | `delegate_guard(allow_glance=)` にそのまま渡す |

出力:

- `PreToolUse`:`delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  マーク済みの役割があれば `isolate_guard(agents)` を追加。
- `PostToolUse`:常に `[index_guard(workbench)]`;`spill_threshold` が真なら
  `spill_guard(workbench, threshold=spill_threshold)` を追加。
- **空リストになるイベントキーは削られ**、空 list は返らない。

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

イベント名ごとに複数の hook 設定を**連結**する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | 可変長引数 | いくつでも。`None` のグループはスキップ |

`extend` を使い、**重複除去はしない** —— 同じ guard を 2 回渡せば 2 回登録される。`Runtime` はこれで `spec.hooks`、
`workbench_hooks(...)`、`whitelist_guard` を 1 つにまとめる。

---

## workbench {#工作台}

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

spill 用の作業ディレクトリ。サブディレクトリ 3 つ + インデックス 1 つ。インデックスは **system prompt に注入される**ので、
agent は毎ターン手元に何があるかを知っている。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `workspace` | `Path` | 必須、位置引数 | ワークスペース。`__post_init__` で resolve される |
| `dirname` | `str` | `".flower"` | workbench のディレクトリ名。`workspace` からの相対 |
| `max_index_entries` | `int` | `40` | **`prompt_block()` にのみ効く**:system prompt に注入する部分で種類ごとに最大何件並べるか。超えた分は「…他 N 件」の 1 行にまとめる。`INDEX.md` 自体は制限されず全件を並べる |
| `home` | `Path \| None` | `None` | 指定すればそれを `root` として使い、**`dirname` は無視**。`None` でない場合も resolve される |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `root` | `@property -> Path` | `home` があればそれ、無ければ `workspace / dirname` |
| `external` | `@property -> bool` | `root` が `workspace` の**外**にあるか。隔離モードでは `True` であるべき |
| `scripts` | `@property -> Path` | `root / "scripts"`。2 回目も実行するスクリプト |
| `artifacts` | `@property -> Path` | `root / "artifacts"`。2000 文字を超える長い成果物 |
| `notes` | `@property -> Path` | `root / "notes"`。重要な決定を、1 決定 1 ファイルで |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | モデルに見せるパス:ワークスペース内なら相対パス、外なら絶対パス |
| `ensure` | `() -> Workbench` | 3 つのディレクトリを mkdir し、`self` を返す(チェーン可:`Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(表示パス, 説明, バイト数)`。`rglob("*")` で再帰し、`.` 始まりのファイルはスキップ |
| `refresh` | `() -> str` | `INDEX.md` を書き直し、その内容を返す |
| `prompt_block` | `() -> str` | **system prompt に注入される部分**。意図的に短くしてある —— 毎ターン存在するからだ |

スクリプトの自己記述フォーマット:先頭 8 行以内の `# desc: 一文`(`//` と `--` のコメント記号も認識)。
無ければ最初の非空コメント行、または docstring の先頭行にフォールバック(100 文字で切る)。

`prompt_block()` が注入する 3 つのルール:

1. 2 回目も実行するスクリプトは `scripts/` に書き、先頭行に `# desc:` を付ける。
2. **2000 文字**を超える成果物は `artifacts/` に書き、会話にはパスと結論だけを載せる。
3. 重要な決定は `notes/` に書き、1 決定 1 ファイルにする。

`external=True` のとき、`prompt_block()` は「絶対パスでアクセスすること」の一文を追加で挿入する。

**インデックスは subagent には継承されない。** これはセッションレベルの `system_prompt.append` を通っており、subagent は自分の
system prompt を持つ(実測 $0.2461)。したがって「長い成果物は `artifacts/` へ、workbench はどこにあるか」の 2 点は
[coordinator](glossary.md#协调者) が[task brief](glossary.md#任务书) の中で伝え直すしかない —— **それが唯一の経路**であって、冗長ではない。
`WORKER_RULES` には**意図的に書いていない**:実際のパスは `Workbench` が生成するもので、ハードコードすれば間違う。

---

## session store {#会话存储}

ソース:[`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

3 層の継承:`SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`。
`Runtime` は**常に最外層を使い**、3 層それぞれの方針はコンストラクタ引数で制御する。

3 層はそれぞれ 1 つのことを担う:永続化、サイズと価値による[trim](glossary.md#裁剪)、「エラーかどうか」による[prune](glossary.md#剪除)。
trim も prune も **`load()`**(つまり resume が履歴をモデルに戻す)瞬間に起きるだけで、SQLite 内の生レコードは 1 バイトも変わらない。

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

SDK の `SessionStore` プロトコルを実装する。テーブルは 3 つ、`entries` / `meta` / `summaries`。
store key は `project_key/session_id[/subpath]` —— **サブ agent の transcript は subpath で区別する**。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `str \| Path` | 必須、位置引数 | データベースファイル。接続は `check_same_thread=False` |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `append` | `async (key, entries) -> None` | uuid で冪等に重複排除(まず既に保存済みのものを除き、次にバッチ内の重複を除く)。バッチ全体が再生されたときは **mtime を進めず、fold summary も重複させない**;summary に参加するのは主 transcript(`subpath is None`)だけ |
| `projects` | `() -> list[str]` | DB に実在する `project_key`。**SDK は cwd から推測するので、クエリの前にこれで確認すること。推測しない** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **同期で、payload を読まず**、meta の 1 行を見るだけ。「同じパスで continuity する」用途 —— 存在しないセッションを resume すると子プロセスが起動するまで落ちない |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | 最後のターンでモデルが実際に見たコンテキストの大きさ。見つからなければ `0`。末尾から `scan` 件だけ逆走査する;`input + cache_read + cache_creation` の 3 項をすべて加算する(`input_tokens` だけを見ると大幅に過小評価する) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | seq 順でソート;行が無ければ `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | 主 transcript のみ |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | セッションのサマリを列挙 |
| `delete` | `async (key) -> None` | 主 transcript を削除するとき**サブ agent のものもカスケード削除**し、孤児を避ける |
| `list_subkeys` | `async (key) -> list[str]` | このセッション配下のサブ transcript を列挙 |
| `close` | `() -> None` | 接続を閉じる |

内部の `_next_mtime` は**厳密な単調性**を保証する —— `list_sessions` と summary sidecar がこの時計を共有しており、
そうでないと SDK の staleness 高速パスが誤判定する。

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
| `keep_recent` | `int` | `20` | 直近 N 件の `tool_result` は原文のまま残す |
| `min_chars` | `int` | `2000` | 短い結果は刈る価値がない |
| `spill_dirname` | `str` | `".flower/spill"` | **`workspace` からの相対で、ワークスペース内でなければならない** —— でないと agent の `Read` が届かない |
| `enabled` | `bool` | `True` | `Runtime(trim=False)` のときここが `False` になる |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | 本文を置き換えるポインタ行を生成する |

**2 つの spill ディレクトリは同じものではない。** `spill_guard` は `<workbench.root>/spill/`(ワークスペース外でもよい)に落とし、
`TrimPolicy.spill_dirname` は `<workspace>/.flower/spill/`(**ワークスペース内でなければならない**)に落とす。
それぞれ「その場で刈る」と「resume 時に刈る」に対応しており、ディレクトリが違うのは意図的だ。1 つにまとめないこと。

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

[ephemeral command](glossary.md#一次性命令) の結果に対する期限切れ方針。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `enabled` | `bool` | `True` | 切ると期限切れマーク自体を一切行わない |
| `keep_recent` | `int` | `6` | 直近 N 件は免除。**`TrimPolicy` の 20 よりずっと小さい** |
| `max_chars` | `int` | `2000` | 超えたらスキップし、`TrimPolicy` のアーカイブに任せる |
| `text` | `str` | シグネチャ参照 | 置換文面。プレースホルダは `{cmd}` と `{age}` の 2 つ |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | `text` を埋めて置換本文を生成する |

**`Bash` ツールの結果にのみ作用し**、かつコマンドが ephemeral command のホワイトリストに一致する必要がある。**`Read` は対象外** ——
ファイルの内容は、時間の経過によって誤解を招くほど劣化するものではない。期限切れの内容は**spill せず**、そのまま捨てる。

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Bash コマンドが [ephemeral command](glossary.md#一次性命令) かどうかを判定する。
**`delegate_guard` の許可判定と trim の期限切れ判定は、この 1 つの関数を共有している** —— coordinator が自分で実行できるコマンドの集合は、
結果が期限切れとマークされる集合と一致しなければならない。許可するのに trim しなければ、期限切れの `git status` が永久にコンテキストを占め、しかも誤導する。
trim するのに許可しなければ、coordinator は `ls` 1 本のために subagent を派遣し、4.3k の起動コストで数十文字を得ることになる。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `cmd` | `str` | 必須、位置引数 | コマンドライン全体 |

判定の順序:

1. 空 / 全部空白 → `False`。
2. コマンド置換(`$(`、バッククォート、`<(`、`>(`)、または「状態を変える」書き方にヒット → `False`。
3. 安全なリダイレクト(`2>&1`、`&> /dev/null` など)を取り除いてもなお `>` または `<` を含む → `False`。
4. `&&` / `||` / `;` / `|` を取り除いてもなお単独の `&` が残る(バックグラウンド実行)→ `False`。
5. `&&` / `||` / `;` / `|` で分割し、**各セグメントがすべてホワイトリストにヒットしなければならない**。

ホワイトリストの動詞の大分類:読み取り専用の `git` サブコマンド(`status` `diff` `log` `show` `branch` `rev-parse` など)、
ディレクトリとシステム情報(`ls` `pwd` `df` `du` `date` `whoami` `env` など)、プロセスとコンテナ
(`ps` `top` `lsof` `docker ps` `kubectl get` など)、ファイル閲覧(`cat` `head` `tail` `wc` `stat` `find` `tree`)、
パス検索(`which` `whereis` `command -v` `type`)、テキスト処理(`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` など)。

動詞がホワイトリストにあっても、次の書き方は止められる:`xargs`、`exec`、`eval`、`source`、`tee`、
`find -delete` / `-ok` / `-fprint`、`sed -i`、`sort -o`、`awk` 内の `system(` と `print >`、
`git branch -D/-d/-m`、`git * --force/--hard/--prune`。

初版は複合コマンドを一律に拒否していたが、**実測で glance が完全に機能しなくなった**(coordinator の 3 回の試行がすべて止められた)ので、
セグメントごとの判定に変えた。

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
| `path` | `str \| Path` | 必須 | データベースファイル |
| `workspace` | `str \| Path` | 必須 | spill ディレクトリの基準 |
| `policy` | `TrimPolicy \| None` | `None` | 渡さなければデフォルトの `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 渡さなければデフォルトの `EphemeralPolicy()` |

公開属性:`workspace`、`policy`、`ephemeral`、`last_report: dict[str, int]`。

`load()` の順序:`super().load()` → `last_report` をクリア → `ephemeral.enabled` なら `expire()` →
`policy.enabled` なら `trim()`。**`enabled=False` のときはそのステップを丸ごとスキップする。**

| メソッド | 説明 |
|---|---|
| `expire(entries)` | 期限切れの時効性のある `Bash` 結果を、**本文だけ差し替え、ブロックは残す**。コマンドは直前の assistant メッセージの `tool_use` から探す;`isCompactSummary` / `isMeta` はスキップ;`max_chars` を超えるものはスキップ(`trim` に任せる);最後の `keep_recent` 件は免除。`last_report["expired"]` に書く |
| `trim(entries)` | `>= min_chars` の `tool_result` 本文を `<workspace>/<spill_dirname>/<sha256先頭16桁>.txt` に spill し、ブロックの内容をポインタに差し替える;最後の `keep_recent` 件は免除。`last_report` の `cleared` / `kept` / `chars_saved` に書く |

**刈るのはプレーンテキストだけ**:`image` / `document` ブロックはそのまま残す。

**構造上の 2 つのレッドライン**:`tool_result` **ブロック自体は必ず残す**。差し替えてよいのは content だけ(1 つでも欠ければ
「Missing Tool Result Block」になる);`isCompactSummary` のエントリには触れない。

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

`store.last_report` を 1 行の中国語にレンダリングする。UI のログ用。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | 必須、位置引数 | サブクラスの `PruningSessionStore` も受け付ける |

出力は 3 通り:何もしていない → `"未裁剪"`;期限切れのみ → `"N 个时效性结果标记为过期"`;
それ以外は `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`。ここで X = `chars_saved // 4`。

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    heal_orphans: bool = True
    orphan_text: str = "[这一步被打断了,没有结果。需要的话重做。]"
    keep_denials: int = 1
```

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | 合成された API エラーメッセージ(切断の残骸)を取り除く |
| `neutralize_interrupts` | `bool` | `True` | 中断で残った `tool_result` を中立的な説明に差し替える |
| `interrupt_text` | `str` | シグネチャ参照 | 中立的な説明の文面 |
| `heal_orphans` | `bool` | `True` | 「`tool_use` はあるのに `tool_result` が無い」孤児呼び出しに合成結果を 1 件補う |
| `orphan_text` | `str` | シグネチャ参照 | 補われた `tool_result` の本文 |
| `keep_denials` | `int` | `1` | 直近 N 件の拒否されたツール呼び出しを残す |

`heal_orphans` が治すのは**中断後に resume が毎回 400 になる**問題だ:中断はメッセージ境界で切れるので、
そのとき飛行中だった `tool_use` の後ろに `tool_result` がまったく無いことがあり、API は両者が対になっていることを要求する —— この壊れた履歴が transcript に残ると、
その後の**毎回**の resume がそれで弾かれる。`heal_orphans()` は孤児を含む assistant の直後に
`user` エントリを 1 件挿入して欠けた結果を補い、元々その assistant を指していた `parentUuid` を補ったエントリに向け直して、チェーンの連続性を保つ
(`prune.py:95-147`)。**補うのであって削らない**:孤児を削るには assistant の親子チェーンを繋ぎ直す必要があり、同じエントリの中に正常なブロックや
テキスト、thinking が同居している可能性があって巻き添えになりやすい(`prune.py:195-204`)。

`keep_denials` の理由:拒否された呼び出しは実行されたことがなく、結果に情報は無いが、占有する場所は小さくない(実測で 1 件 273 文字 =
拒否文 93 字 + **死んだコマンドの原文** 180 字)。さらに重要なのは**それが誤導する**ことだ —— 実測で coordinator が
「Bash を直接使うな」を何件か読んだ後、許可されるはずの `git status` すら試さなくなり、学習性無力感を身につけてしまった。
**デフォルトは 0 ではなく 1 件残す**:最新の拒否 1 件は、同じターン内で止められたコマンドを繰り返し再試行するのを防ぐ。

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
| `path` | `str \| Path` | 必須 | データベースファイル |
| `workspace` | `str \| Path` | 必須 | spill ディレクトリの基準 |
| `policy` | `TrimPolicy \| None` | `None` | trim 方針 |
| `prune` | `PrunePolicy \| None` | `None` | prune 方針 |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | 期限切れ方針 |

公開属性は親クラスに加えて 3 つ:`prune_policy`、`pruned`、`denials_dropped`。

`load()` = `super().load()`(先に `expire` + `trim`)→ `self.prune(entries)`。`prune` は 3 つのことをする:

1. **古すぎる拒否された呼び出しを取り除く**:harness の構造的マーカー `toolDenialKind == "permission-rule"` で判定する
   (拒否文のテキストマッチより信頼できる)。最後の `keep_denials` 件を残し、残りは `tool_use` **と** `tool_result`
   ブロックを一緒に取り除く。同じ assistant メッセージに複数の `tool_use` がある場合は**該当するものだけを取り除く**。でないと
   「Missing Tool Result Block」になる;テキストと thinking のブロックは残す。
2. **合成された API エラーメッセージを取り除く。** SQLite にはそのまま残り、戻さないだけ。
3. **中断で残った `tool_result` を中立的な説明に差し替える** —— 本文だけを差し替え、エントリは取り除かない。

**唯一の構造的レッドライン**:transcript は `parentUuid` の単一チェーンなので、1 件取り除いたらその子を最も近い生存中の祖先に繋ぎ直さなければならない。
内部の `relink` に渡す `entries` は**取り除く対象を含む完全なリストでなければならず**、フィルタは `relink` 自身が行う ——
呼び出し側が先に除いてから渡すとチェーンがそこで切れ、それより前の履歴が全部失われる(**踏み抜き済み:取り除く対象が末尾にあるときは表面化せず、
中間にあると爆発する**)。

**引数の順序が親クラスと違う**:親は `(path, workspace, policy, ephemeral)`、子は
`(path, workspace, policy, prune, ephemeral)` —— **4 番目の位置引数が `ephemeral` から `prune` に変わっている**。
位置で渡すと黙ってずれる。必ずキーワードで渡すこと。

---

## resilience {#韧性}

ソース:[`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

ネットワークが切れたときは、失敗して終了するのではなく、ぶら下がって待つ。エクスポートは 4 つ:方針の dataclass 1 つ + 単独でも使える探査関数 3 つ。

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
| `probe_interval` | `float` | `15.0` | プローブとプローブの間隔 |
| `max_offline_wait` | `float` | `3600.0` | ぶら下がって待つ最大時間。デフォルト 1 時間 |
| `retry_unknown` | `bool` | `True` | 分類できないエラーを再試行するかどうか |
| `resume_prompt` | `str` | シグネチャ参照 | 続きを走らせるときに言う言葉。**エラーの詳細は意図的に一切含まない** —— モデルが知る必要があるのは「中断された、続けろ」であって、`ENOTFOUND` か 503 かではない |

| メソッド | シグネチャ | 説明 |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` にさらに `0.75 + random()*0.5` を掛ける(±25% のジッタ) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`、または `kind == "unknown"` かつ `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | ネットワークが戻るまでぶら下がって待つ。戻れば `True`、`max_offline_wait` を超えたら `False`。`notify` は `(str) -> None` のコールバックで、**最初に到達不能になったとき**と**復旧したとき**に 1 回ずつ発火する |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

エラーテキストを `"transient"` / `"fatal"` / `"unknown"` の 3 種に分類する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `text` | `str \| None` | 必須、位置引数 | エラーメッセージの原文。空なら `"unknown"` を返す |

**先に fatal を判定してから transient を判定する** —— 401 のようなテキストには `connection` の語がよく含まれ、順序を逆にすると永遠に待つことになる。

| 種別 | 何にヒットするか |
|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`network error`、`Connection error`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`too many requests`、`timeout` / `timed out`、`temporarily unavailable`、`service unavailable`、`internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

探査するホストとポート。`ANTHROPIC_BASE_URL` に従い、デフォルトは `https://api.anthropic.com`;
ポートはデフォルトで `80`(http)または `443`。

**自前のゲートウェイを使うならそれを探査すること** —— `api.anthropic.com` が通ってもゲートウェイが通る証拠にはならない。

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `host` | `str` | 必須、位置引数 | ホスト名 |
| `port` | `int` | 必須、位置引数 | ポート |
| `timeout` | `float` | `5.0` | 秒 |

**DNS(`getaddrinfo`)+ TCP ハンドシェイクだけを行い**、HTTP は送らず、資格情報も付けず、**課金もされない**。例外はすべて到達不能とみなす。

---

## イベントとインタラクション {#事件与交互}

ソース:[`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[イベント](glossary.md#事件)は SDK のメッセージ列を平坦化した安定構造だ。**[インタラクション層](glossary.md#交互层)は
`Event` しか知らず、SDK の型を一切 import しない** —— これが UI を差し替えてもコアを触らずに済む境界線だ。[インタラクション層の差し替え](../guide/interaction.md)を参照。

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
| `tool` | `str` | `""` | ツール名。`tool_call` のみ |
| `payload` | `dict[str, Any]` | `{}` | 構造化された付加情報 |
| `raw` | `Any` | `None` | 生の SDK オブジェクト。深掘りしたいときに使う |

`__str__`:`tool_call` のときは `f"[{tool}] {text}"`、それ以外は `text`、`text` が空なら `f"<{kind}>"`。
だから `print(ev)` はそのまま読める。

`EventKind` は全部で **15** 個:

| kind | 発生元 | 説明 |
|---|---|---|
| `text` | `normalize` | assistant の本文 |
| `thinking` | `normalize` | 思考ブロック |
| `tool_call` | `normalize` | ツール呼び出し。`text` は `file_path` / `command` / `pattern` の要約で 200 文字まで |
| `tool_result` | `normalize` | ツール結果。`text` は 500 文字まで、payload に `tool_use_id` / `is_error` |
| `task` | `normalize` | 3 種類の Task メッセージ。`text` は**空**で、クラス名は `payload["kind"]` に入る |
| `system` | `normalize` | その他のシステムメッセージ。`text` は subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`。payload に `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | 合成 API エラーメッセージ。payload に `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`。**本文は入力であってモデルの出力ではない**ので `StepResult.text` には入らない |
| `unknown` | `normalize` | 判別できなかったもの |
| `retry` | `Runtime` | リトライ通知 |
| `step` | `Workflow.run` | payload:`{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | payload の `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | 質問。**人が自発的に発した言葉も運ぶ** |

**最後の 4 つは `normalize()` が生成するものではない。**

すべての assistant / user イベントの `payload` には次が入る:

| キー | 型 | 説明 |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | `subagent` が真のときのみ |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。**[ハンドオフ](glossary.md#换代)判定の唯一の情報源**であり、long-horizon な実行で最も可視化されるべき数字 |

**`ask` という kind は「質問」と「人が自発的に発した言葉」の両方を運ぶ。** 後者は `payload["kind"] == "mail"` で、
**`options` / `remaining` を持たない**。UI は必ず `payload.get("kind")` を先に判定してから描画を決めること。
さもないと、ただの一言を「未回答の質問」として吊るしたままにしてしまう。

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

SDK メッセージ 1 件を 0〜N 個の `Event` に平坦化する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `message` | `Any` | 必須、位置引数 | 任意の SDK メッセージオブジェクト |

主要な分岐:

- **合成 API エラーメッセージ**(`isApiErrorMessage=True` または `model == "<synthetic>"`)→ 単一の
  `Event("error", payload={"synthetic": True})`。**これは意図的だ** —— そうしないと切断時の文言が本文として
  `StepResult.text` に入り、次のステップへ渡ってしまう。
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
| `id` | `str` | 必須 | 回答時に対象を特定するために使う |
| `question` | `str` | 必須 | 質問本文 |
| `options` | `list[str]` | `[]` | 選択肢。人は選ばずに自分で打ってもよい |
| `asked_at` | `float` | `time.time()` | 質問した時刻 |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | 回答本文 |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `waited_s` | `@property -> float` | どれだけ待ったか |
| `event` | `(remaining: int = 0) -> Event` | `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` を返す |

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

**プロセス内 MCP server**(ツール 2 個)+ UI 向けのメソッド群。モデル側からは
`mcp__human__ask` と `mcp__human__inbox` しか見えない。コンストラクタ引数はすべて keyword-only。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | **プッシュ**モードの出口。渡すと `Workflow.run` は配線しない |
| `max_asks` | `int \| None` | `None` | **回数無制限**。数値を渡すとハード上限、`0` = 質問禁止(全自動 / CI)。超過時はツールが**即座に断り、ブロックしない** |
| `timeout_s` | `float \| None` | `1800.0` | 30 分。`None` = 永久に待つ;**`<= 0` = 待たず、すべての質問が即座に空振り** |
| `log_path` | `str \| Path \| None` | `None` | Q&A をディスクへ**追記**する。コンテキストを消費しない |
| `amend_path` | `str \| Path \| None` | `None` | 実行途中で人が言ったことをこのファイルに追記する(通常は要件確認書)。**ディスクに書かなければステップ境界を越えられない** —— 次のステップは新しいセッションで、凍結物しか読まない |
| `over_budget_text` | `str` | モジュール定数 | 上限超過時にモデルへ返す文言 |
| `timeout_text` | `str` | モジュール定数 | タイムアウト時にモデルへ返す文言 |
| `declined_text` | `str` | モジュール定数 | スキップされたときにモデルへ返す文言 |

公開属性:コンストラクタ引数と同名の 8 個に加えて `asks: list[Ask]`、`mail: list[Mail]`、
`ui_errors: list[str]`(**UI コールバックが投げた例外はここに集められ、実行は止まらない**)。

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | そのまま `AgentSpec.mcp_servers` に渡す。**キー名は server 名と一致していなければならない**ので、ここでまとめて生成する |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | 人の応答を待ってブロックする。**`CancelledError` 以外の例外は決して投げない** —— 誰も答えないこともひとつの答えであり、`ask.state` で区別する |
| `send` | `(text: str) -> Mail \| None` | 人が自発的に一言送る。**任意のスレッドから呼べる**。agent を中断しない;内部で自動的に `amend()` を呼ぶ |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | `amend_path` に追記する。実際に書けたかを返す(パス未設定・空文字列・`OSError` はいずれも `False`) |
| `pending_mail` | `() -> list[Mail]` | まだ取り出されていない mail |
| `remaining` | `@property -> int` | あと何回質問できるか。**`max_asks=None` のときは `-1` を返す**。0 でも無限大でもない |
| `pending` | `() -> list[Ask]` | 現在回答待ちで吊るされている質問 |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | **プル**モード用。タイムアウトなら `None`、キャンセルされたら例外 |
| `answer` | `(ask_id: str, text: str) -> bool` | 回答する。`False` = その質問はもう待っていない(タイムアウト / 回答済み) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | スキップし、モデル自身に判断させる |
| `transcript` | `() -> str` | Q&A 記録の markdown |

**2 つの取り方はどちらか一方を選ぶ**:**プッシュ** —— `HumanChannel(on_event=...)` で構築;**プル** —— `await channel.next_ask()`。
`Workflow.run` は `channel.on_event is None` のときだけ自動配線するので、自分で渡していれば上書きされない。

**スレッド跨ぎ**:`answer` / `decline` / `send` は内部で `loop.call_soon_threadsafe` を通すので、
Web バックエンドや TUI の入力スレッドから直接呼ぶのが普通だ。

3 つの「0 / None」の意味はそれぞれ違う。混同しないこと:`max_asks=None` = 無制限、`max_asks=0` = 質問禁止;
`timeout_s=None` = 永久に待つ、`timeout_s<=0` = 即タイムアウト;`remaining` は `max_asks=None` のとき `-1`。

エクスポートされていないが戻り値に現れる `Mail` は dataclass で、フィールドは `id` / `text` / `sent_at` / `taken`。

---

## リネージ {#血缘}

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

「どのステップがどのセッションを使ったか」をプロセスを跨いで記録する。[継続](glossary.md#接续)はこれを頼りに前回どこまで進んだかを見つける。
ファイルは `<run_dir>/lineage.json`。

| フィールド | 型 | デフォルト | 説明 |
|---|---|---|---|
| `path` | `Path` | 必須 | リネージファイルのパス |
| `workspace` | `Path` | 必須 | ワークスペース。`__post_init__` で resolve される |
| `steps` | `dict[str, str]` | `{}` | ステップ名 → `session_id` |
| `woke` | `int` | `0` | ウェイクした回数 |

| メンバー | シグネチャ | 説明 |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | `<run_dir>/lineage.json` を読む。**ファイルが無い・読めない・`workspace` フィールドが一致しない場合は、一律で空を返しエラーにしない** |
| `remember` | `(step: str, session_id: str) -> None` | 対応を記憶して**即座にディスクへ書く**。step または sid が空ならそのまま返る |
| `bump` | `() -> int` | ウェイク回数を +1 して書き込み、新しい値を返す(初回は `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | リネージファイルと `extra` を `<into>/<YYYYmmdd-HHMMSS>/` へ**移動**し、`steps` / `woke` をゼロに戻す。**削除ではなく移動** |

書き込みは `tmp.replace(path)` によるアトミック置換。`OSError` は黙って握り潰す —— 書き込み失敗でこの実行を巻き添えにすべきではない。

**`workspace` はガードだ**:SDK の `project_key` はワークスペースのパスから導出されるため、ディレクトリをコピーして移した後では古い `session_id` は引けない。
だからパスが一致しなければ無かったことにする。

`Workflow.run` はリネージを読み込むとき、各レコードについて `runtime.has_session(sid)` で DB にまだ存在するか検証し、生きているものだけを使う ——
リネージファイルは `sessions.db` より長生きすることがある。

---

## 最小構成の実例 {#示例}

5 本ともそのまま動く。前提:`claude-agent-sdk` がインストール済みで、`ANTHROPIC_API_KEY` または `ANTHROPIC_AUTH_TOKEN` が使えること
(そうでなければ `Runtime(...)` の構築時点で `RuntimeError` を投げる)。

### 1 つの agent で 1 ステップ {#示例-单-agent}

最小の骨格:`AgentSpec` を宣言し、`Runtime` を作り、`await rt.run(...)` して `StepResult` を読む。

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

`Runtime` の引数は**すべて keyword-only**;`rt.run()` の `spec` と `prompt` は位置引数で、それ以外は keyword-only。
`AgentSpec` はデフォルトで `allowed_tools=["Read", "Glob", "Grep"]`、`delegate_only=False` なので、
`Runtime` が自動的に [`whitelist_guard`](#whitelist-guard) を装着し、`Bash`/`Write`/`Edit`/`NotebookEdit` をすべて遮断する。

### コーディネーター + ワーカー {#示例-协调}

手を動かさない[コーディネーター](glossary.md#协调者)が、実作業をする[ワーカー](glossary.md#执行者)を 1 人連れている。
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
    # ワークベンチを開かないとコーディネーターの Bash/Write を止める hook が 1 つも無い。
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
後ろに `WORKER_RULES` が自動で連結される)。`coordinator()` は最初の 3 つが位置引数:`name`、`instructions`、`workers`。

### 自分で Workflow を書く {#示例-workflow}

2 ステップ。後のステップが前の結果を自分の prompt に注入する —— 安く、隔離され、セッションを共有しない。

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
        # 新しいセッション:prompt に入っているものしか食べない
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # 新しいセッション + 前ステップの結果を prompt に注入(安い、汚染を防ぐ)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # 同じセッションを続けたいなら resume_from="造句";分岐させるなら fork=True を足す
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text(reduce を渡さない場合)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # on_fail="stop" のとき、どのステップで失敗したか


asyncio.run(main())
```

`Step` の最初の 3 フィールド(`name` / `spec` / `prompt`)は位置引数で、`Workflow` の `steps` も同様。
`Workflow.run(runtime, *, on_event=None, on_step=None)` —— `runtime` は位置引数、2 つのコールバックは keyword-only。
**`continuous=True` がデフォルトである点に注意**:同じ `run_dir` + 同じ `workspace` で 2 回目を走らせると、
`resume_from=None` のステップも前回のセッションの続きから話し始める。

### ゴールガードを 1 枚足す {#示例-目标}

まず[判定者](glossary.md#判定者)に目標と判定チェックリストを決めさせ、それから実作業のステップに判定を受けさせる ——
通らなければフィードバック付きでやり直し、最大 3 ラウンド。

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
        # clarify_step が無いときは自分で流し込む。さもないと "(没有确认书)" しか見えない。
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY:Goal オブジェクト
    print(ctx["_verdict"])     # VERDICT_KEY:直近の Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY:何ラウンド回ったか
    print(ctx.get("_aborted")) # StepAbort の理由(達成不能かつ誰も応答しないとき)


asyncio.run(main())
```

`with_goal` は `gate` / `on_reject` / `retries` だけを差し替え、残りのフィールドは `dataclasses.replace` でそのまま持っていく。
判定者は**独立したセッション**だ:`gate` の内部で `rt.run(judger, ..., step_name=f"{label}#{轮次}")` を単独で呼び、
`resume` は常に `None`。

### インタラクション層を差し替える {#示例-交互层}

ターミナルを Web / TUI / HTTP に替えるとき、変えるものは 2 つだけだ:`Event` を描画する関数と、質問を取り出すコルーチン。

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event を自分の UI に描画する —— 差し替えが必要なのはここだけ。"""
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
    # kind == "ask" かつ mail でないものは、下の answerer に任せる(プル式)


async def answerer(ch: HumanChannel) -> None:
    """プル式で質問を取り出す。Web バックエンド / HTTP サービスに替えるとき、変えるのはこのコルーチンだけ。"""
    while True:
        ask = await ch.next_ask()          # timeout が無い場合はずっと待つ
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # または ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime は workflow が自分で作ったワークベンチを使う —— 別物を組み立てないこと
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

プッシュとプルは**どちらか一方**:プッシュは `HumanChannel(on_event=...)` で構築、プルは `await channel.next_ask()`。
`Workflow.run` は `channel.on_event is None` のときだけ自動配線するので、自分で `on_event` を渡していれば上書きされない。
`answer()` / `decline()` / `send()` / `interrupt()` は**いずれも別スレッドから呼べる**。

---

## 落とし穴とハマりどころ {#陷阱}

踏む順に並べてある。モジュール順ではない。各項目には実測の出所がある。

### 組み立て {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = メインスレッドに壁が 1 枚も無い。**
   `delegate_guard` はワークベンチがあるときしか装着されず、`whitelist_guard` は `delegate_only=True` でスキップされる。
   コーディネーターを使うならワークベンチを開くこと。詳細は [Runtime](#runtime)。
2. **ワークベンチの位置は 2 つある。組み間違えるな。** `Runtime(workbench=True)` は `<run_dir>/workbench` に置かれ、
   `Workbench(ws)` のデフォルトは `<ws>/.flower` だ。自分で `brief_path` を組むなら後者に合わせること。
   **確認書は A ディレクトリに書かれ、注入されるインデックスは B ディレクトリを走査し、しかもエラーにならない。**
   正しいやり方:workflow 側で `Workbench(...).ensure()` して `Workflow.workbench` に載せ、
   **同じオブジェクト**を `Runtime(workbench=wb)` に渡す。
3. **`allowed_tools` は排他的なホワイトリストではなく、承認不要リストだ。** モデルはそこに無いツールも呼べる。
   `clarify()` / `judge()` に「書き込みツールが無い」のは [`whitelist_guard`](#whitelist-guard) という hook のおかげだ。
   一方 `coordinator()` はデフォルトで `permission_mode="acceptEdits"` —— この値を
   `clarify()` / `judge()` に渡した瞬間、保護は消える。
4. **`disallowed_tools` はセッション単位**で、subagent の同名ツールもまとめて禁止する。
5. **ワークベンチのインデックスは subagent に入らない。** 「長い成果物は `artifacts/` へ書く」はコーディネーターがタスク指示書で伝え直すしかなく、
   それが唯一の経路だ。
6. **`Runtime(...)` は認証情報が無いと構築段階で `RuntimeError` を投げる。** `run()` まで待たない。
7. **`Runtime.run_id` はインスタンスごとに一意でなければならない。** `manifest.json` は `run` フィールドで重複排除するので、2 つの id が衝突すると
   後から書いた側が相手の行を「自分が前回書いたもの」と見なして削除する。

### ワークフロー {#陷阱-流程}

8. **`Workflow.continuous=True` はデフォルト値**であり、`resume_from=None` は「まっさらな新セッション」を意味しない。
   毎回新規で開きたいなら明示的に `continuous=False`。**ステップ名を変えればリネージは切れる。**
9. **`with_goal(rounds=N)` は総ラウンド数であって追加ラウンド数ではない**:`retries = max(0, rounds - 1)`。
10. **`on_fail="skip"` は `ctx[step.name]` を書かない** —— 下流の `lambda ctx: ctx["某步"]` は `KeyError` になる。
    不完全な結果を持って先へ進みたいなら `on_fail="continue"` を使う。
11. **`resume_from` が未実行 / 失敗済みのステップを指していると `ValueError` を投げる。** 黙ってスキップはしない。
12. **`Step.reduce` は同期関数でなければならない;`gate` / `when` / `on_reject` は async でよい。**
13. **`fork=True` は `resume` を渡さないと黙って無効になる。** `Workflow` は `resume_at` を決して渡さないので、
    メッセージ単位でロールバックしたいなら `Runtime.run` を直接呼ぶしかない。
14. **自分で `Runtime` を駆動する場合、`on_session` は gate の前に必ず外すこと。** さもないと判定者のセッションが
    実作業ステップのリネージに書き込まれる。`Workflow` は `try/finally` でこれを保証している。
15. **`step_name` が manifest とリネージのキーを決める。** `Workflow` は `#retryN` / `#roundN` を付け、
    判定者は `#轮次` を付ける —— **サフィックス付きの名前はプロセス跨ぎのリネージに入らない**。これが「判定者は常に新しいセッション」を実装する方法のひとつだ。

### ロール {#陷阱-角色}

16. **`clarify(max_turns=<小さい数>)` は「質問回数無制限」を空文句に変える** —— 質問 1 回が 1 ターンだからだ。
17. **`goal_step()` に `can_run` の仮引数は無い。** `**spec_kw` 経由で `can_run=True` を渡すしかない。
    渡さなければ目標を立てる判定者は `Bash` を得られず、`JUDGE_RULES` の「まず自分がどんな環境にいるかを見極めろ」という条項が実行できない。
18. **`judge(can_run=True)` は判定者がワークスペースを書き換えられるようにする** —— `whitelist_guard` は `allowed_tools` から導出されるので、
    `Bash` を与えれば `Bash` は通る(`Write`/`Edit` は依然として止めるが、`Bash` 自体でファイルは書ける)。絶対中立を求めるなら開けないこと。
19. **`worker(isolate=True)` は workspace が git リポジトリであることを要求する。** そうでなければ `Agent` ツールが直ちに
    `"not in a git repository"` を返す。黙って劣化はしない。しかも隔離マーカーは Python の属性なので、
    **`AgentDefinition` に `dataclasses.replace()` をかけると失われる**。
20. **`AgentDefinition` を直接構築するときの引数はキャメルケース**:`maxTurns`、`permissionMode`。
    `worker()` は既に変換してくれている。

### ハンドオフとコンテキスト {#陷阱-换代}

21. **ハンドオフを有効にすると auto-compact は強制的に切られ、フォールバックは無い。** だから引き継ぎ書を書くステップには必ず劣化経路が要る。
    auto-compact を残したいなら `AgentSpec.compact` を明示的に渡すこと。
22. **`HandoffPolicy.window` を小さく設定すると無限にハンドオフして金を燃やす。** 唯一のブレーキは `max_generations=8`。
    逆側では、**`default_window()` は 2 つの環境変数がどちらも未設定のとき `1_000_000` を返す** ——
    大きすぎる判定は `is_overflow()` が受け止める(劣化ハンドオフ 1 回になる)ので致命的ではないが、その世代の引き継ぎは劣化版になる。
23. **ワークベンチが無いとハンドオフはディスクに残らない。** 文書は prompt 経由で後任に渡るが、人は後から見返せない。

### ストレージ {#陷阱-存储}

24. **`Runtime(trim=False)`(デフォルト)は「何も消さない」ではない。** store は常に `PruningSessionStore` であり、
    `trim=False` は大きな結果のトリムを切るだけだ。**切断の残骸の除去、拒否された呼び出しの除去、中断の残留物の中和、時効切れの処理は行われる。**
25. **2 つの spill ディレクトリは別物**:`spill_guard` は `<workbench.root>/spill/` に置き、
    `TrimPolicy.spill_dirname` は `<workspace>/.flower/spill/` に置く(ワークスペース内でなければならない)。
26. **`PruningSessionStore.__init__` の 4 番目の位置引数は `ephemeral` ではなく `prune`** で、
    親クラスとは異なる。位置で渡すと黙ってずれる。

### 文書とインタラクション {#陷阱-文书}

27. **`Verdict` が結論を解析できなかったときは `state=""`、`ok=False` であり、達成と見なしては絶対にいけない。**
    また「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」はすべて `unreachable` に分類され、
    「立ち止まって人に聞く」経路に入る。「もう 1 ラウンド」ではない。
28. **`Brief.parse` は閉じていないコードフェンスに出会うと、それ以降の内容をすべて捨てる** —— モデルの出力が切り詰められた場合、
    後続のセクションは一切解析されず、`complete()` は `False` になり、gate が差し戻す。
29. **`Brief.load` は `"(未填)"` を空と見なす。** 確認書を手で編集するときにプレースホルダの文言をそのまま写すと、その節は依然として欠落扱いだ。
30. **`HumanChannel` の 3 つの「0 / None」は意味がそれぞれ違う**:`max_asks=None` は無制限、`max_asks=0` は質問禁止;
    `timeout_s=None` は永久に待つ、`timeout_s<=0` は即タイムアウト;`remaining` は `max_asks=None` のとき **`-1`** を返す。
31. **`Event("ask")` は質問と人が自発的に発した言葉の両方を運ぶ**。後者は `payload["kind"] == "mail"`。UI は先にこれを判定すること。
32. **`Workflow.run` は `channel.on_event is None` のときだけ自動配線する** ——
    自分で `HumanChannel(on_event=...)` を構築した場合、質問イベントは workflow の `on_event` 出口には同時に流れない。
