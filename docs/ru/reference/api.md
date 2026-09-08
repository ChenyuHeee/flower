# Python API

Эта страница исчерпывающе описывает **62 публичных символа** верхнего уровня `__all__` в `flower`: сигнатуры, параметры, значения по умолчанию, семантику, публичные атрибуты и методы. После прочтения не нужно лезть в исходники за параметрами.

Материал организован по **тому, что вас интересует**, а не по файлам модулей — хотите знать «как не дать [координатору](glossary.md#协调者) делать всё самому», идите в [слой hook](#hook); хотите знать «как результат предыдущего шага попадает в следующий», идите в [workflow](#流程). Терминология — строго по [глоссарию](glossary.md).

Версия `0.1.0`, зависимость `claude-agent-sdk>=0.2.152`. Все сигнатуры дословно соответствуют исходникам.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # один импорт верхнего уровня
```

## Что на этой странице {#索引}

| Что интересует | Символы |
|---|---|
| [Запустить агента](#运行时) | `Runtime` `StepResult` |
| [Связать шаги в цепочку](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Создать роль](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Написать определение агента вручную](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Структурированные документы](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Перехватить инструмент, обрезать результат, развести изоляцию](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Рабочий каталог для spill](#工作台) | `Workbench` |
| [Как и что хранится в сессиях](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Что делать при обрыве сети](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Заменить UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Подхватить прошлый запуск между процессами](#血缘) | `Lineage` |

## Шесть значений по умолчанию, которые кусаются {#危险默认值}

Эти шесть — не мелочи, а шесть самых частых аварий. Каждая полностью разобрана в соответствующем разделе.

| Значение по умолчанию | Последствие | Подробнее |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` главного потока **не прикрыты ни одним hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | принудительно ставит spec `CompactPolicy(mode="no_summary")`, то есть `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | шаг с `resume_from=None` всё равно подхватит прошлую сессию между процессами | [Workflow](#workflow) |
| `build_options(fork=True)` без `resume` | молча не срабатывает, без ошибки | [build_options](#build-options) |
| `clarify(max_turns=<маленькое число>)` | превращает «вопросов можно задавать сколько угодно» в пустые слова — каждый вопрос это один раунд | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | уровень сессии, запрещает инструмент и для subagent тоже | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Исходник: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` — ядро исполнения. Он держит рабочую область, [хранилище сессий](glossary.md#会话存储), [workbench](glossary.md#工作台), политику [устойчивости](glossary.md#韧性) и политику [handoff](glossary.md#换代), а наружу отдаёт один глагол: `run` один шаг. Повторы, продолжение после прерывания, handoff при переполнении контекста — всё делается внутри этого одного вызова.

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

Все параметры конструктора **keyword-only** (`*` в самом начале), `workspace` обязателен.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `str \| Path` | обязателен | `cwd` агента. При конструировании resolve и `mkdir(parents=True, exist_ok=True)`. `project_key` в SDK выводится из него — стоит скопировать каталог в другое место, и старый `session_id` уже не найдётся |
| `run_dir` | `str \| Path` | `"runs"` | Здесь лежат `sessions.db`, `manifest.json`, `lineage.json`, а также workbench по умолчанию при `workbench=True`. Так же resolve и mkdir |
| `portable` | `bool` | `True` | Пробрасывается в `build_options(portable=)`, то есть `setting_sources=[]`: не читает ни `~/.claude/` хоста, ни `.claude/` проекта. См. [переносимость](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Экземпляр используется как есть; `bool` превращается в `TrimPolicy(enabled=bool(trim))`. **Выключение означает лишь, что большие результаты не режутся trim; prune работает по-прежнему** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Те же правила преобразования. Идёт в паре с `coordinator(glance=True)` — если главному потоку разрешено запускать `git status`, надо гарантировать, что этот результат протухнет |
| `keep_denials` | `int` | `1` | Передаётся в `PrunePolicy(keep_denials=)`. Сохраняет последние N отклонённых вызовов инструментов, более ранние снимаются вместе с вызовом и результатом |
| `workbench` | `Workbench \| bool` | `False` | Экземпляр используется как есть; `True` создаёт `Workbench(workspace, home=run_dir / "workbench")` (**по умолчанию вне рабочей области**). Сразу после этого вызывается `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | С какого числа символов результат инструмента уходит в [spill](glossary.md#落盘). `None` или `0` = `spill_guard` не ставится |
| `resilience` | `Resilience \| bool` | `True` | Те же правила преобразования |
| `handoff` | `HandoffPolicy \| bool` | `True` | Те же правила преобразования |

**Хранилище сессий зашито жёстко**: это всегда
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Параметры конструктора **не дают** точки входа для смены бэкенда — если нужно сменить, соберите `AgentSpec` + `build_options(session_store=...)` сами либо перезапишите `rt.store` после конструирования.

Последние два шага конструктора — `load_dotenv()` и `check_credentials()`, **вторая при ошибке делает `raise RuntimeError`**. Без учётных данных всё падает уже на этапе конструирования, а не при `run()`.

!!! warning "`workbench=False` + `coordinator()` = у главного потока нет ни одной стены"
    `delegate_guard` ставится только внутри `workbench_hooks`, а `workbench_hooks` вызывается только когда `self.workbench is not None`; `whitelist_guard` же пропускается из-за `if not spec.delegate_only`. При этом `coordinator()` всегда ставит `delegate_only=True`, а `glance=True` по умолчанию выдаёт `Bash`.

    **Вывод: когда координатор работает с `Runtime(workbench=False)`, его `Bash`/`Write`/`Edit` не перехватывает ни один hook.**
    Используете `coordinator()` — включайте `workbench`: `Runtime(..., workbench=True)` или передайте экземпляр `Workbench`.

!!! warning "`handoff=True` (по умолчанию) принудительно выключает auto-compact"
    Внутри `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, а в дочернем процессе это `DISABLE_AUTO_COMPACT=1`. Причина: когда оба механизма включены одновременно, непонятно, кто именно уронил объём контекста.

    **Цена: у шага, который пишет handoff, обязан быть путь деградации** (`handoff.degraded`), потому что compact больше не подстрахует.
    Чтобы сохранить auto-compact, задайте `AgentSpec.compact` явно (если spec задал его сам, значение уважается и не перезаписывается).

#### Публичные атрибуты {#runtime-属性}

| Атрибут | Тип | Описание |
|---|---|---|
| `workspace` | `Path` | Рабочая область после resolve |
| `run_dir` | `Path` | Каталог запуска после resolve |
| `portable` | `bool` | Сохраняется как есть |
| `store` | `PruningSessionStore` | Хранилище сессий. Сменить бэкенд можно только перезаписью после конструирования |
| `resilience` | `Resilience` | Приведённый экземпляр |
| `handoff` | `HandoffPolicy` | Приведённый экземпляр |
| `workbench` | `Workbench \| None` | При `workbench=False` — `None` |
| `spill_threshold` | `int \| None` | Сохраняется как есть, в `_attempt` передаётся в `workbench_hooks` |
| `results` | `list[StepResult]` | Каждый шаг, пройденный в этом процессе, добавляется по порядку |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Обязан быть уникальным для каждого экземпляра** — `manifest.json` дедуплицирует по полю `run`, и при коллизии двух id тот, кто пишет позже, снесёт чужую строку, приняв её за свою предыдущую |
| `on_session` | `Callable[[str], None] \| None` | Колбэк вызывается **сразу** при получении нового `session_id`, по умолчанию `None`. **Должен накрывать только сам вызов `runtime.run`** — [судья](glossary.md#判定者) использует тот же `Runtime`, и если колбэк останется висеть во время gate, сессия судьи попадёт в [lineage](glossary.md#血缘) рабочего шага |

Константы класса: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (кусок текста, который при продолжении после прерывания приписывается после реплики человека и поясняет, что «инструментальные вызовы, бывшие в полёте, вернули interrupted — это нормальный побочный эффект прерывания, а не сбой окружения»).

#### Публичные методы {#runtime-方法}

| Метод | Сигнатура | Описание |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Прогнать один шаг. См. ниже |
| `interrupt` | `(message: str = "") -> None` | Запросить прерывание текущего раунда. **Можно вызывать из любого потока**. Кооперативно: чистый разрыв **на границе сообщения**, без жёсткой отмены. Пустая строка = прервать, ничего не говоря |
| `rescue` | `() -> None` | Перед жёстким убийством по возможности дописать учёт; вызывается обработчиками `SIGHUP`/`SIGTERM`. Шаг, бывший в полёте, тоже пишется в manifest с `error="killed-by-signal"`. Делает только маленькую синхронную запись на диск |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | В `str(workspace.resolve())` все `/`, `_`, `.` заменены на `-`. **SDK выводит его из cwd, вызывающая сторона задать не может** |
| `has_session` | `(session_id: str) -> bool` | Находится ли ещё этот id **в текущей рабочей области**. Синхронно, payload не читает |
| `context_of` | `(session_id: str) -> int` | Объём контекста последнего раунда указанной сессии; делегирует `store.last_context` |
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

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `spec` | `AgentSpec` | обязателен, позиционный | Объявление агента, который будет запущен |
| `prompt` | `str` | обязателен, позиционный | Реплика этого раунда |
| `step_name` | `str \| None` | `None` | Ключ, который попадёт в `StepResult.step`, manifest и lineage. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Продолжить эту `session_id` |
| `fork` | `bool` | `False` | Ответвить новую сессию, не пачкая исходную. **Работает только когда `resume` истинно** |
| `resume_at` | `str \| None` | `None` | Продолжить с определённого сообщения (откат). Так же **работает только когда `resume` истинно** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Выход для событий, см. [`Event`](#event) |

В начале каждого шага уровень контекста обнуляется (`self._ctx, self._warned = 0, False`). Дальше идёт цикл с четырьмя выходами:

1. **Успех** → выход из цикла.
2. **Прерывание человеком** (`result.error == INTERRUPTED`) → **не ограничено `max_attempts`**, сети не ждёт.
   `resume` той же сессии с репликой человека, `attempt -= 1` (прерывание не считается неудачной попыткой), prompt = реплика человека + `INTERRUPT_NOTE`.
   **Если `session_id` не получен, остаётся только остановиться**.
3. **Контекст полон** (`result.error == HANDOFF_DUE` либо `handoff.enabled`, получен `session_id` и сработал `is_overflow(...)`) → **тоже не ограничено `max_attempts`**. Сначала проверка `len(result.retired) >= handoff.max_generations`;
   если превышено — error заменяется диагностической строкой и выход из цикла; иначе пишется [handoff-документ](glossary.md#交接书) → `resume=None, fork=False`
   (**совершенно новая сессия**) → prompt заменяется на `h.prompt_block()` → уровень контекста обнуляется → `attempt -= 1`.
4. **Повторяемый сбой** → при `not resilience.enabled or attempt >= max_attempts` — выход;
   если `classify(error)` решает, что повторять не следует, — тоже выход; иначе отправляется `Event("retry")`, `wait_online()` виснет в ожидании сети,
   `sleep(delay_for(attempt))`; **если `session_id` был получен, идёт `resume`** (prompt заменяется на
   `resilience.resume_prompt`), а `result.resumed` ставится в `True`.

Завершение: пишется `ended_at`, результат добавляется в `self.results`, пишется `manifest.json`.

У `manifest.json` семантика **добавления**: при каждой записи файл перечитывается с диска и дедуплицируется по полю `run` (своя строка обновляется, чужие остаются), поэтому два параллельных flower в одном `run_dir` — безопасно, при условии что `run_id` не совпадут.

**Три точки наблюдения за handoff** (все — `Event("handoff")`, различаются по `payload["phase"]`):
`near` (приближение к `warn_at`, отправляется один раз на поколение), `writing` (идёт запись handoff, это больше десятка секунд),
`done` (в payload есть `degraded` / `path` / `sections`). Раунд записи handoff запускается с
`replace(spec, max_budget_usd=None)` — handoff обязан быть написан и не должен упереться в бюджет;
и `on_event=None`, этот раунд в UI не выводится.

Handoff пишется на диск в `<workbench.notes>/交接-<步骤名>.md`; **без workbench на диск ничего не пишется**, документ всё равно передаётся преемнику через prompt, просто потом его не найти. Старые handoff переезжают в `notes/archive/交接/<名>-<时间戳>.md`.

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

Весь учёт по одному завершённому шагу.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `step` | `str` | обязательно | Имя шага (`step_name` либо `spec.name`) |
| `session_id` | `str \| None` | `None` | **Всегда та сессия, которая приняла смену последней** — сожжённые по пути handoff лежат в `retired` |
| `ok` | `bool` | `False` | Удался шаг или нет |
| `cost_usd` | `float` | `0.0` | В долларах. При повторах и handoff **накапливается** |
| `num_turns` | `int` | `0` | Число раундов, так же накапливается |
| `text` | `str` | `""` | **Только основной текст главного потока**. Реплики subagent остаются в его собственном transcript, а переданное ему задание имеет `kind="prompt"` — ни то, ни другое сюда не попадает |
| `error` | `str \| None` | `None` | Причина сбоя. Особые значения см. `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix-таймстемпы |
| `attempts` | `int` | `1` | Фактическое число попыток. Прерывания и handoff **не учитываются** |
| `errors` | `list[str]` | `[]` | Собранные синтетические сообщения об ошибках API, **в `text` не попадают** |
| `resumed` | `bool` | `False` | Был ли по ходу resume |
| `retired` | `list[str]` | `[]` | `session_id`, сожжённые при handoff на этом шаге, по порядку |
| `context` | `int` | `0` | Объём контекста, который фактически видел главный поток в последнем раунде, то есть критерий handoff |

| Свойство | Тип | Описание |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, если шаг не завершён — `0.0` |

---

## Workflow {#流程}

Исходники: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[Workflow](glossary.md#流程) — это набор [шагов](glossary.md#步骤), выстроенных по порядку, плюс правила
передачи состояния между шагами и условия досрочного выхода. **Фреймворк не даёт готовых workflow, workflow пишете вы** —
`starter_flow` — всего лишь рабочий образец.

Псевдоним типа `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, входит в `flower.workflow.__all__`,
но не в `__all__` верхнего уровня).

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

**Декларация** одного шага. Сам `Step` не является функцией — выполняет всё `Runtime.run(step.spec, prompt, ...)`.
Первые три поля — позиционные аргументы, `Step("取词", terse, "读 seed.txt …")` — допустимая запись.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязательный | Имя шага. **Ключ, стабильный между процессами** — попадает в `ctx[name]`, `ctx["_results"]`, manifest и lineage. Переименование = разрыв lineage |
| `spec` | `AgentSpec` | обязательный | Какого агента запускать |
| `prompt` | `str \| Callable[[Ctx], str]` | обязательный | Что сказать. Может быть замыканием, которое считает текст по `ctx` на месте |
| `resume_from` | `str \| None` | `None` | Сессию какого шага продолжать. Если у указанного шага сессии не было — **бросается `ValueError`**, а не молчаливый пропуск |
| `fork` | `bool` | `False` | Ответвиться от сессии `resume_from`. **Без `resume_from` не действует** |
| `retries` | `int` | `0` | Сколько раз ещё пробовать, если gate не пройден. `retries=0` = один заход |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Решает, засчитан ли этот заход. **Может быть async**. `False` считается провалом. **Вызывается ровно один раз на попытку** — у него могут быть побочные эффекты (например, запись brief на диск), повторно дёргать его нельзя |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, см. ниже |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | `False` → **шаг пропускается целиком**: result не создаётся, в `ctx["_results"]` ничего не пишется. **Может быть async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Что сказать **на следующем круге**, если gate не пройден. **Может быть async**. Если задан — семантика повтора меняется, см. ниже |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt для случая продолжения (а не старта с нуля) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Решает, что положить в `ctx[name]`. По умолчанию — исходный `result.text`. **Должна быть синхронной функцией** |

| Метод | Сигнатура | Описание |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Если `resuming` и задан `resume_prompt` — берётся он, иначе `prompt`; если это вызываемый объект, ему передаётся `ctx` |

**Три способа подключить сессию** (в пределах одного run):

| Запись | Эффект |
|---|---|
| `resume_from=None` (по умолчанию) | Новая сессия, только тот контекст, что передан в prompt. Дёшево, изолированно. **Но при `Workflow(continuous=True)` будет взята сессия одноимённого шага из межпроцессного lineage** |
| `resume_from="имя предыдущего шага"` | Продолжение той же сессии, полный контекст. Дорого, но связно |
| `resume_from="имя предыдущего шага", fork=True` | Ответвление, исходная сессия не загрязняется. Для перепроверки / параллельных вариантов |

**`on_reject` меняет семантику повтора**:

- Не задан → следующая попытка **стартует с нуля** (тот же prompt, тот же `resume_from`).
- Задан → следующая попытка **продолжает ту самую сессию, которую только что забраковали**, prompt заменяется на возвращённое значение, `fork` принудительно `False`.
- Возвращена пустая строка → отбоя нет, деградирует до старта с нуля.
- `result.session_id` равен `None` → тоже деградирует до старта с нуля.

**Три значения `on_fail`**:

| Значение | Поведение |
|---|---|
| `"stop"` (по умолчанию) | Пишет `ctx["_failed_at"] = name`, **прерывает весь workflow** |
| `"skip"` | Переход к следующему шагу, **`ctx[name]` не записывается** — ниже по течению `lambda ctx: ctx["некий шаг"]` даст `KeyError` |
| `"continue"` | `ctx[name] = result.text`, идём дальше с неполным результатом |

Независимо от того, пройден gate или нет, `ctx["_results"][name] = result` записывается всегда; если `result.session_id`
непустой, он ещё попадает в `ctx["_sessions"]` и в `lineage.remember(...)`.

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

Выполняет цепочку `Step` по порядку и возвращает итоговый `ctx`. `steps` — позиционный аргумент, `Workflow([...])` допустимо.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `steps` | `list[Step]` | обязательный | Выполняются по порядку |
| `name` | `str` | `"workflow"` | Имя workflow |
| `context` | `Ctx` | `{}` | Начальный словарь контекста. **При втором запуске того же `Workflow` это тот же самый dict** |
| `channel` | `HumanChannel \| None` | `None` | Сюда вешается канал, если нужно остановиться и спросить человека. `run()` автоматически подключит его `on_event` к тому же выходу, **только если `channel.on_event is None`**; драйвер по этому же полю понимает, кому отвечать |
| `workbench` | `Workbench \| None` | `None` | Workbench, заданный самим workflow, чтобы драйвер мог его найти |
| `continuous` | `bool` | `True` | Один и тот же путь = один и тот же разговор. Реализация — [`Lineage`](#lineage) |

| Параметр `run()` | Тип | По умолчанию | Описание |
|---|---|---|---|
| `runtime` | `Runtime` | обязательный, позиционный | На каком runtime выполнять |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Выход событий, пробрасывается в каждый `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Колбэк после каждого шага |

!!! warning "`continuous=True` — значение по умолчанию, и `resume_from=None` не значит «новая сессия»"
    Когда continuity включена, `run()` сначала делает `Lineage.open(run_dir, workspace)`, затем по каждой записи
    проверяет через `runtime.has_session(sid)`, жива ли она в хранилище, и только живые заливает в `ctx["_sessions"]`. В итоге
    **шаг с `resume_from=None` тоже продолжит прошлую сессию** — даже если процесс убили или машину перезагрузили.

    Чтобы каждый раз была новая сессия, пишите явно `Workflow(..., continuous=False)`.
    И ещё: **имя шага — это ключ, стабильный между процессами; переименовали шаг — разорвали lineage.**

**Приватные ключи**, которые `run()` пишет в ctx (все начинаются с `_`, с именами шагов не сталкиваются):

| Ключ | Содержимое |
|---|---|
| `_runtime` | Переданный `Runtime`. **Через него gate запускает агентов** |
| `_on_event` | Выход событий. Агент внутри gate тоже должен доставать до UI, иначе интерфейс останется чёрным |
| `_sessions` | `dict[имя шага, session_id]`, читается через `setdefault` |
| `_results` | `dict[имя шага, StepResult]` |
| `_lineage` | Объект `Lineage`. Есть только при `continuous=True` и наличии у runtime `run_dir` + `workspace` |
| `_woke` | Возврат `lineage.bump()` — какое это по счёту пробуждение |
| `_aborted` | Сообщение `StepAbort` |
| `_failed_at` | Имя провалившегося шага при `on_fail="stop"` |

Payload события `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Метки повторов**: на нулевой попытке — `step.name`; далее при наличии `on_reject` — `f"{name}#round{attempt+1}"`,
без него — `f"{name}#retry{attempt}"`. В manifest сразу видно, как этот шаг доехал до конца.
**Имена с суффиксом в межпроцессный lineage не попадают** — `Lineage.remember` использует исходное имя.

`runtime.on_session` оборачивает ровно один вызов `runtime.run`, а `try/finally` гарантирует, что до gate он снят.
`prompt_cur` / `resume_cur` / `fork_cur` — локальные переменные, обратно в `step` они не пишутся: один и тот же объект `Step` может быть запущен второй раз.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Брошено из `gate` = **немедленно стоп, повторов не будет**. Отличие от «вернуть `False`»: `False` — это «в этот раз не вышло, ещё круг»;
`StepAbort` — «ещё круг не поможет».

После броска: `ctx["_aborted"] = str(exc)`, `passed = False`, **выход из цикла повторов (остаток `retries` не тратится)**,
далее — обычная обработка провала по `on_fail` (по умолчанию `"stop"`).

`with_goal` бросает его в двух местах: когда не удалось получить `ctx["_runtime"]`, и когда verdict — `unreachable`, а человек не ответил.

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

Собирает `Step`, выполняющий [clarify](glossary.md#前置确认): выяснить требования → разобрать в [`Brief`](#brief) →
если все четыре раздела на месте, заморозить и записать на диск.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `channel` | `HumanChannel` | обязательный, позиционный | Канал вопросов |
| `brief_path` | `str \| Path` | обязательный | Куда положить [brief](glossary.md#需求确认书). **Обязательно в тот самый workbench, который реально индексируется и инъектируется** |
| `prompt` | `str \| Callable[[Ctx], str]` | обязательный | Исходная просьба человека |
| `name` | `str` | `"确认需求"` | Имя шага, оно же ключ в `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Без него берётся `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Дополнительные инструкции [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = спрашивать заново каждый раз, независимо от наличия brief |
| `on_fail` | `str` | `"stop"` | Как у `Step.on_fail` |
| `retries` | `int` | `0` | Сколько раз переспросить, если четыре раздела не собрались |
| `**spec_kw` | | | Пробрасывается напрямую в [`clarify()`](#clarify-role), поэтому можно писать `can_read=False`, `max_budget_usd=...` |

Поля получившегося `Step` заполняются так:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: при `always_ask=True` → всегда `True`; иначе, если `Brief.load(brief_path)` полон, он заливается в ctx,
  **а затем возвращается `False` (пропуск)** — заливать нужно и при пропуске, иначе нижестоящие шаги останутся без требований.
- `gate`: `Brief.parse(result.text)`, неполон → пишет `ctx[MISSING_KEY]` и возвращает `False`;
  полон → `b.write(brief_path)` замораживает, заливает в ctx, возвращает `True`.
- `reduce`: возвращает `ctx[BRIEF_KEY].prompt_block()`, **а не исходный текст модели** — в исходнике может быть налеплено лишнее.
- `resume_from` **остаётся по умолчанию `None`**: следующий шаг — новая сессия, ему достаётся только brief, но не тот диалог.
  Вопросы и ответы clarify **никогда не попадали** в контекст координатора — их не вырезали оттуда, их там и не было.

Три места, куда заливается ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Константа | Значение | Описание |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` — объект `Brief`; `ctx[step.name]` — его `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Каких разделов не хватило при провале clarify (имена разделов по-китайски), для отображения в UI |
| `CLARIFY_RESUME` | промпт на китайском | «Продолжай то самое незаконченное уточнение требований — **не начинай заново**……». Без этой фразы при продолжении исходная просьба уйдёт как новая задача, и clarifier может переспросить уже спрошенное |

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

Собирает `Step`, **задающий цель**: [judge](glossary.md#判定者) читает brief, пишет цель + список проверок,
результат разбирается в [`Goal`](#goal), замораживается и пишется на диск. Форма та же, что у `clarify_step`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `channel` | `HumanChannel` | обязательный, позиционный | Канал вопросов |
| `goal_path` | `str \| Path` | обязательный | Куда положить файл цели |
| `brief_key` | `str` | `"确认需求"` | Откуда взять текст brief для prompt — из `ctx[brief_key]`. **Если не нашлось — будет `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Имя шага |
| `spec` | `AgentSpec \| None` | `None` | Без него берётся `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Дополнительные инструкции |
| `always_set` | `bool` | `False` | `True` = переписывать список проверок заново, независимо от наличия файла цели |
| `on_fail` | `str` | `"stop"` | Как выше |
| `retries` | `int` | `0` | Как выше |
| `**spec_kw` | | | Пробрасывается в [`judge()`](#judge-role) |

**Формального параметра `can_run` нет** — чтобы judge, задающий цель, мог запускать команды, `can_run=True` передаётся только через `**spec_kw`.
Без этого у него не будет `Bash`, и пункт «сначала разберись, в какой ты среде» из `JUDGE_RULES` выполнить нечем.

Помимо разбора и заморозки `gate` делает ещё одно: если в цели есть пункты `[此环境无法验证:…]`, он **тут же**
шлёт через `ctx["_on_event"]` событие `Event("task", payload={"unverifiable", "total", "path"})` как предупреждение —
судьба этих пунктов решается именно в момент постановки цели, а к моменту вынесения verdict деньги за целый круг работы уже потрачены.

**`resume_prompt` не задан** — при постановке цели brief и должен пересылаться целиком.

| Константа | Значение | Описание |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` — объект `Goal`; `ctx[step.name]` — markdown |
| `VERDICT_KEY` | `"_verdict"` | Последний [`Verdict`](#verdict), для UI |
| `ROUND_KEY` | `"_goal_rounds"` | Сколько кругов отработала проверка |

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

Надевает на существующий `Step` [goal guard](glossary.md#目标看守): после каждого круга judge независимо выносит verdict,
и если цель не достигнута — отбивает работу обратно.

Результат — `replace(step, retries=max(0, rounds - 1), gate=<новый gate>, on_reject=<новый on_reject>)`:
используется `dataclasses.replace`, а не пересборка по полям, потому что при пересборке однажды потеряли `resume_prompt`, **и ошибки при этом не было**,
просто при продолжении заново отправлялся весь brief целиком.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `step` | `Step` | обязательный, позиционный | Шаг, который берётся под охрану |
| `channel` | `HumanChannel` | обязательный, позиционный | Канал обращения к человеку, когда verdict вынести невозможно |
| `goal_path` | `str \| Path` | обязательный | Файл цели, читается, когда `ctx[GOAL_KEY]` неполон |
| `spec` | `AgentSpec \| None` | `None` | Без него берётся `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Общее число кругов, а не дополнительных**: `rounds=3` → `retries=2` → максимум три круга работы. `rounds=1` = один круг, один verdict, не прошёл — провал |
| `instructions` | `str` | `""` | Дополнительные инструкции judge |
| `can_run` | `bool` | `False` | Может ли judge запускать `Bash` |
| `name` | `str \| None` | `None` | Имя judge, по умолчанию `f"{step.name}·判定"` |
| `**spec_kw` | | | Пробрасывается в `judge()` |

`gate` — **async**, порядок действий:

1. Нет `ctx["_runtime"]` → **бросить `StepAbort`** («не удалось получить Runtime, verdict по цели вынести нельзя»). **Не притворяйтесь, что прошло.**
2. `ctx[ROUND_KEY] += 1`.
3. Взять цель: сначала полный `Goal` из `ctx[GOAL_KEY]`, иначе `Goal.load(goal_path)`, иначе пустой `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Judge — это отдельный вызов `Runtime.run`, `resume` всегда `None` — это всегда новая сессия**; `step_name` содержит номер круга,
   поэтому в межпроцессный lineage он не попадает.
5. `Verdict.parse(vr.text)` записывается в `ctx[VERDICT_KEY]`.
6. `v.achieved` → вернуть `True`.
7. Не `unreachable` (включая размытые случаи с `v.ok=False`) → при размытости дописать дефолтную reason, вернуть `False`.
   **Размытое всегда считается недостигнутым** — нельзя, чтобы фраза «вроде бы работает» закрывала работу.
8. `unreachable` → `await channel.ask(...)`, спросить человека, три варианта:
   - Никто не ответил (`a.state != "answered"`) → **бросить `StepAbort`**. Крутиться вхолостую — самый дорогой выбор.
   - «Принять этот результат и идти дальше» → вернуть `True`.
   - «Изменить цель» → спросить новую цель, `g.amend(...).write(goal_path)`, обновить `ctx[GOAL_KEY]`, вернуть `False`.
   - Всё остальное (включая свободный ответ человека) → трактуется как «ты вынес неверный verdict», слова человека записываются в `v.reason`, вернуть `False`.

`on_reject` — **синхронный**: возвращает `ctx[VERDICT_KEY].feedback()`, а при отсутствии `Verdict` — `""`
(деградация до старта с нуля).

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

Собирает готовый к запуску workflow из трёх шагов: **уточнить требования → задать цель → работать** (с goal guard). Именно его использует команда `flower`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `ask` | `str` | обязательный, позиционный | Одна фраза-просьба. **При пробуждении это не новая задача, а «человек сказал ещё кое-что»** |
| `workspace` | `str \| Path` | `"."` | Рабочая область |
| `run_dir` | `str \| Path` | `"runs"` | Каталог run |
| `new` | `bool` | `False` | `True` = заархивировать lineage + brief + цель (все три сразу) и начать с нуля |
| `isolate` | `bool` | `False` | Дать worker'у worktree-[изоляцию](glossary.md#隔离). Workbench при этом переезжает в `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Вернуть Workflow только с шагом уточнения |
| `goal` | `bool` | `True` | Ставить ли [goal guard](glossary.md#目标看守). `False` = работа считается законченной, как только шаг отработал |
| `rounds` | `int` | `3` | Пробрасывается в `with_goal(rounds=)`, общее число кругов |
| `judge_can_run` | `bool` | `False` | Пробрасывается в `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Пробрасывается в `HumanChannel`, `None` = без ограничения |
| `timeout_s` | `float \| None` | `1800.0` | Пробрасывается в `HumanChannel`. `0` = полностью автоматический режим, все вопросы сразу проваливаются |
| `instructions` | `str` | `""` | Дополнительные инструкции clarifier |
| `worker_prompt` | `str` | см. сигнатуру | System prompt worker'а |
| `brief_name` | `str` | `"需求.md"` | Имя файла brief, кладётся в `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Имя файла цели, там же |
| `log_name` | `str` | `"问答记录.md"` | Имя файла журнала вопросов и ответов, там же |

Фиксированная сборка:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Ветвления в поведении:

- `isolate=True`, а workspace не является git-репозиторием → **бросается `ValueError`**, а не ожидание, пока об этом сообщит инструмент `Agent`
  (к тому моменту деньги уже потрачены).
- **Определение пробуждения**: если `Brief.load(brief_path)` существует и `complete()`, это пробуждение. Если это не пробуждение и `ask` пуст →
  **бросается `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- При пробуждении эта фраза уходит **в три места** сразу, и потеря любого из них тихо ломает всё: дописывается в brief
  (`ch.amend(said, label="唤醒时追加")`, если уже есть в файле — повторно не пишется);
  заставляет `goal_step(always_set=True)` переписать список проверок (без этого judge читает старую цель);
  и подаётся напрямую координатору (в его контексте лежит **старая** цель, и без этой фразы он будет работать по старым критериям, а оцениваться по новым).

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

**Разведка только на чтение до старта, не пишет ни байта.** Нужна, чтобы до реального запуска сказать человеку: «это продолжение прошлого раза» или «начинаем с нуля».

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Рабочая область, позиционный аргумент |
| `run_dir` | `str \| Path` | `"runs"` | Каталог run |
| `isolate` | `bool` | `False` | Определяет положение workbench, значение должно совпадать с переданным в `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Имя файла brief |
| `goal_name` | `str` | `"目标.md"` | Имя файла цели |

Возвращаемый dict:

| Ключ | Тип | Описание |
|---|---|---|
| `waking` | `bool` | Brief существует и все четыре раздела на месте |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Число пунктов в списке проверок, при отсутствии цели — `0` |
| `woke` | `int` | `Lineage.woke`, сколько раз уже просыпались |
| `steps` | `dict` | Копия `Lineage.steps`, имя шага → `session_id` |

Положение workbench **определяется ровно один раз здесь и в `starter_flow`**: `isolate=True` → `<ws>.parent/.flower-<ws.name>`
(вне репозитория); иначе `<ws>/.flower`. Драйвер, желающий узнать, где лежит brief, тоже идёт через эту функцию — если склеить путь самому и ошибиться, ошибки не будет,
всё просто тихо перестанет работать.

---

## Фабрика ролей {#角色工厂}

Исходный код: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Все пять ролей — фабричные функции. Каждая роль = **фрагмент внедряемого текста правил + набор инструментов + набор hook'ов**.
`worker()` возвращает `AgentDefinition` из SDK (для передачи subagent'у), остальные четыре — [`AgentSpec`](#agentspec)
(каждая поднимает собственную session).

Сами роли **hook'и не вешают** — перехват инструментов навешивает `Runtime._attempt` автоматически по `spec.delegate_only`,
см. [слой hook'ов](#hook).

Внутренние константы групп инструментов (не экспортируются, но определяют значения по умолчанию):

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

Создаёт [coordinator](glossary.md#协调者), живущий в [main thread](glossary.md#主线程): разбирает задачу, раздаёт работу, читает отчёты, принимает решения,
**но сам руками ничего не делает**. Первые три параметра — позиционные.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязательный | Имя роли, оно же имя step по умолчанию |
| `instructions` | `str` | обязательный | Доменные инструкции. В итоге получается `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | обязательный | Какие роли у него в подчинении, попадает в `AgentSpec.agents`. **Их read-only web-инструменты дополнительно вливаются в собственный `allowed_tools` координатора**, см. ниже |
| `channel` | `HumanChannel \| None` | `None` | Если задан — добавляются сразу два инструмента, `inbox` **и** `ask`, а также выставляется `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → без `Read` |
| `glance` | `bool` | `True` | Добавляет `"Bash"` и выставляет `AgentSpec.glance`. **Что именно можно запускать, решает `delegate_guard`**, а не этот флаг |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | `None` | Лимит числа ходов |
| `max_budget_usd` | `float \| None` | `None` | Лимит [бюджета](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Режим прав. **Обратите внимание на это значение по умолчанию** — передав его в `clarify()`/`judge()`, вы снимете защиту с этих двух ролей |
| `compact` | `CompactPolicy \| None` | `None` | Если задан, `Runtime` не будет принудительно менять политику на `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Дополнительные hook'и, сливаются с `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Дополнительные переменные окружения |

Три поля в полученном `AgentSpec` фиксированы: `delegate_only=True`, `agents=workers`,
а `workbench` остаётся со значением по умолчанию `True` из `AgentSpec`.

#### Web-инструменты из `workers` вливаются сюда же {#coordinator-web-merge}

После сборки списка `coordinator()` проходит по `AgentDefinition.tools` каждого worker'а, и всё, что попадает в
`WEB_TOOLS` (`WebFetch`, `WebSearch`, `roles.py:33`), добавляется ещё и в собственный
`allowed_tools` координатора (`roles.py:523-526`).

**Причина: `allowed_tools`, как и `disallowed_tools`, действует на уровне session.** Это самое жёсткое во всём тексте
доказательство данного факта — влияние не ограничивается main thread. Инструмент, которого нет в этом списке уровня session,
при вызове из **subagent'а** тоже пойдёт через запрос разрешения; в автономном режиме подтверждать некому, и harness отвечает
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`), а модель раз за разом повторяет тот же вызов. На этом реально спотыкались: worker'у дали
`WebFetch`/`WebSearch`, но записали их только в `AgentDefinition.tools` — тот прогон novel получил больше двадцати
user-rejected и не написал ни слова (`roles.py:513-518`).

Оба поля одинаково действуют на уровне session, но **симптомы разные**: `disallowed_tools` даёт ошибку сразу,
`allowed_tools` — молчаливые повторы до самой смерти. Второе искать труднее, потому что на экране ничто не похоже на ошибку.

**Вливаются только read-only инструменты без побочных эффектов.** `Write`/`Edit`/`Bash` **намеренно не вливаются**: как только
main thread получит их без подтверждения, стена «координатор руками не работает», выстроенная `delegate_guard`, теряет смысл;
а `Bash`/`Write` у subagent'а и так проходят (замерено 462 пропуска, `roles.py:520-522`).

В исходниках прямо написано: **не реализуйте «только координировать, руками не работать» через `disallowed_tools`** — это уровень session,
и запрет заодно отключит `Bash`/`Write` у subagent'ов, см. предупреждение в [`AgentSpec`](#agentspec).
Правильный способ — как здесь: `delegate_only=True` + не давать `allowed_tools`,
а [`delegate_guard`](#delegate-guard) по `agent_id` перехватит только main thread.

Если задан `channel`, приходят **сразу два инструмента**, это не опция: как только подключён MCP server, есть оба, а
`allowed_tools` не является эксклюзивным — вызвать можно и то, чего в списке нет. В автономном режиме каждый `ask` будет висеть до истечения `timeout_s` —
для таких сценариев используйте `HumanChannel(timeout_s=0)`.

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

Создаёт определение [subagent](glossary.md#subagent), который действительно делает работу. Первые два параметра — позиционные.
Возвращается `AgentDefinition` из SDK, его сразу можно класть в `coordinator(workers={...})`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `description` | `str` | обязательный | **Основание, по которому координатор выбирает исполнителя** — пишите чётко, «какую работу ему поручать» |
| `prompt` | `str` | обязательный | Его system prompt. При `discipline=True` склеивается как `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Worker'а не следует понижать в модели |
| `effort` | `str \| int \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | `None` | Попадает в **`maxTurns`** SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Попадает в **`permissionMode`** SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Какие skill'ы ему разрешены |
| `discipline` | `bool` | `True` | Приклеивать ли блок дисциплины отчётности `WORKER_RULES` |
| `isolate` | `bool` | `False` | Ставит метку [изоляции](glossary.md#隔离), идёт через `isolated()`, **это не поле `AgentDefinition`** |

`isolate=True` требует, чтобы workspace был git-репозиторием, иначе инструмент `Agent` сразу выдаёт `"not in a git repository"`,
**без молчаливой деградации**. Кроме того, метка — это атрибут Python: `dataclasses.replace()` над `AgentDefinition`
её потеряет, и изоляция молча перестанет работать.

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

Создаёт [clarifier](glossary.md#确认者): прежде чем что-то делать, выясняет требования; ничего не делает, только спрашивает, а в конце выдаёт ровно четыре раздела.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязательный | Имя роли, позиционный |
| `channel` | `HumanChannel` | обязательный | Канал для вопросов, позиционный |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | При `True` добавляются `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | `None` | **Без ограничения по числу ходов** |
| `max_budget_usd` | `float \| None` | `None` | Лимит бюджета |

Полученный `AgentSpec`: `allowed_tools = [channel.tool_name] + (те пять при can_read)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (у него нет инструментов записи, индекс для него бессмыслен),
`permission_mode` наследует значение по умолчанию `AgentSpec` — `"default"`.
**Нет ни `Write` / `Edit` / `Bash` / `Agent`, ни `inbox`** (в отличие от координатора).

!!! warning "Маленькое `max_turns` превращает «неограниченные вопросы» в пустой звук"
    Каждый вопрос — это один ход. `max_turns=16` означает «максимум десяток с небольшим вопросов», и фраза в канале
    «ограничения по числу ходов нет» тут же становится ложью.

    Чтобы действительно разрешить спрашивать, нужно снять ограничение **сразу в двух местах**: `HumanChannel.max_asks`
    (по умолчанию уже `None` = без ограничения) и `max_turns` (по умолчанию уже `None`).

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

Создаёт [judge](glossary.md#判定者): он либо задаёт цель перед стартом, либо выносит вердикт после каждого раунда.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязательный | Имя роли, позиционный |
| `channel` | `HumanChannel` | обязательный | Канал для вопросов, позиционный |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `JUDGE_RULES` |
| `can_run` | `bool` | `False` | При `True` в белый список добавляется `Bash`, и `whitelist_guard` пропускает `Bash`, продолжая блокировать `Write`/`Edit` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | `None` | Лимит числа ходов |
| `max_budget_usd` | `float \| None` | `None` | Лимит бюджета |

Полученный `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (при `can_run`) `["Bash"]`,
`workbench=False`, остальное как у `clarify()`. **Нет ни `Write` / `Edit` / `Agent`, ни `inbox`.**

**Компромисс**: при `can_run=True` вердикт жёстче (можно реально запустить приёмочные команды), ценой того, что judge
получает возможность менять workspace — `Bash` сам по себе умеет писать файлы. Если нужен абсолютно нейтральный вердикт, не включайте.

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

Создаёт [oracle](glossary.md#旁路顾问): пока run ещё идёт, его можно спросить «где мы сейчас», и он посмотрит на последние events и workbench,
а потом ответит. **Сказанное им не попадает в контекст этого run.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Имя роли, позиционный |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | **`12`** | По умолчанию с ограничителем |
| `max_budget_usd` | `float \| None` | **`0.5`** | По умолчанию с ограничителем. Это «спросить мимоходом», оно не должно выходить из-под контроля |

Полученный `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]` (**без channel** — он не спрашивает,
а только отвечает), `workbench=True` (**единственный из пяти, кто не координатор, но с включённым workbench** — ему как раз нужно читать эти артефакты и заметки).

### Пять текстов правил {#rules}

Все пять констант есть в `__all__`, их можно напрямую `import`, читать, склеивать и менять.

| Константа | Кому внедряется | Способ внедрения | Суть |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Ты — «человек, который умеет пользоваться Claude Code», а не worker; нельзя писать файлы / править код / запускать тесты; `Bash` хватает лишь «взглянуть», и результат устаревает; **в [task brief](glossary.md#任务书) пиши только то, что специфично именно для этой задачи**; единственное правило, которое ещё нужно проговорить, — «где workbench + длинные артефакты пиши в `artifacts/` + в ответе давай только путь»; после каждого завершённого этапного действия проверяй `inbox`; `ask` блокирует, используй его только на настоящей развилке |
| `WORKER_RULES` | `worker()` | Приклеивается **после** `prompt` subagent'а | Формат ответа — **вывод / основания / артефакты / непроверенное**, не более 30 строк; запрещено вставлять содержимое файлов, вывод команд, логи, сырые diff'ы; запрещено пересказывать процесс проб и ошибок; перед работой загляни в `.flower/scripts/`. **Намеренно не сказано «длинные артефакты пиши в `artifacts/`»** — реальный путь генерирует `Workbench`, зашитый жёстко будет неверным |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Ничего не делать, только выяснять требования; **ограничения по числу вопросов нет, спрашивай, пока не станет ясно**; человека может не быть на месте — по таймауту решай сам и записывай это в «Неизвестное и допущения»; вывод — **ровно четыре раздела**; не писать код, не вставлять содержимое файлов |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Одно из двух. **Задать цель**: каждый пункт списка должен проверяться на месте, длина списка определяется числом способов провалиться, **границы не являются пунктом проверки**, к непроверяемым пунктам в конце добавляется `[此环境无法验证:原因]`. **Вынести вердикт по раунду**: вывод — **ровно три раздела**, судят **артефакты, а не исходники**, «сделано» по умолчанию не принимается на веру, «не сделано» и «здесь это нельзя проверить» — два разных вывода, и второй **ни в коем случае нельзя признавать пройденным** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Ты — боковая линия; тот run ещё идёт, ты его не прерываешь и в нём не участвуешь; **только чтение**; ответил — забыл, сказанное тобой не попадёт в контекст того run; у тебя на руках только «окно последних events» и «workbench»; сначала смотри, потом отвечай, не можешь ответить — так и скажи, кратко |

---

## Определение agent {#agent-定义}

Исходный код: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` — полное объявление специализированного agent, а `build_options` компилирует его в `ClaudeAgentOptions` из SDK.
[Фабрика ролей](#角色工厂) как раз и возвращает `AgentSpec` — если нужна комбинация вне фабрик, конструируйте его напрямую.

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

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязательное | Имя роли. Оно же `step_name` по умолчанию в `Runtime.run` и самоназвание в тексте отказа `whitelist_guard` |
| `instructions` | `str` | обязательное | Доменные инструкции. **[Добавляются](glossary.md#叠加) после нативного system prompt Claude Code, а не заменяют его** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Список без подтверждения, а не эксклюзивный белый список** — модель по-прежнему может вызвать то, чего в нём нет. Эксклюзивность обеспечивает [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Уровень session**. См. предупреждение ниже |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность размышления |
| `max_turns` | `int \| None` | `None` | Лимит числа ходов |
| `max_budget_usd` | `float \| None` | `None` | Лимит [бюджета](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Режим прав |
| `agents` | `dict[str, Any] \| None` | `None` | Таблица определений subagent'ов, значения — `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Таблица MCP server'ов. `HumanChannel.mcp_servers()` подставляется прямо сюда |
| `hooks` | `dict[str, Any] \| None` | `None` | Дополнительные hook'и, `Runtime` сольёт их со своими через `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Если задан, `Runtime` не будет принудительно менять политику на `no_summary` |
| `env` | `dict[str, str]` | `{}` | Переменные окружения для дочернего процесса. Поверх делается `update` из `compact.env()` |
| `glance` | `bool` | `False` | Позволяет координатору самому запускать `Bash` в режиме «только взглянуть». Что пропускать, решает [`is_ephemeral`](#is-ephemeral), а результат помечается `EphemeralPolicy` как устаревающий |
| `workbench` | `bool` | `True` | Внедрять ли индекс workbench в system prompt этого agent. **Для ролей без инструментов записи выключайте** (у `clarify()` / `judge()` по умолчанию как раз `False`) |
| `delegate_only` | `bool` | `False` | Только координировать, руками не работать. При `True` `Runtime` навешивает `delegate_guard` и **не навешивает** `whitelist_guard` |

!!! warning "`disallowed_tools` действует на уровне session и заодно блокирует subagent'ов"
    Реальный текст ошибки: `"Bash is disabled for this session, in subagents as well as here"`.
    То есть если, желая лишить координатора рук, вы напишете `disallowed_tools=["Bash"]`, то и отправленный worker не сможет запускать команды —
    весь run насмарку.

    Для «только координировать, руками не работать» используйте `delegate_only=True` + не давать `allowed_tools`, чтобы
    [`delegate_guard`](#delegate-guard) по `agent_id` перехватывал только main thread.

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

Компилирует `AgentSpec` в `ClaudeAgentOptions` из SDK. Именно её вызывает `Runtime._attempt` внутри;
если вы сами управляете SDK (без `Runtime`), вход тоже здесь.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `spec` | `AgentSpec` | обязательный, позиционный | Компилируемое объявление |
| `cwd` | `str \| Path \| None` | `None` | Записывается в `cwd` только если не `None` |
| `session_store` | `SessionStore \| None` | `None` | Только если не `None`, записываются `session_store` и `session_store_flush` |
| `resume` | `str \| None` | `None` | Какую session продолжать |
| `fork` | `bool` | `False` | Ложится в `fork_session`. **Вложено внутрь `if resume:`** |
| `resume_at` | `str \| None` | `None` | Ложится в `resume_session_at`. **Тоже вложено внутрь `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` и `PLUGIN_DIR` существует → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Дополнительно разрешённые каталоги. **Обязательно, если workbench находится вне workspace** |
| `flush` | `str` | `"eager"` | Ложится в `session_store_flush` |
| `prelude` | `str` | `""` | Фрагмент, добавляемый после `instructions` (сюда идёт индекс workbench) |

Соответствие:

| Ключ полученного option | Значение |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Берутся напрямую из `spec` |
| `setting_sources` | `[]` (portable) либо `["project"]` |
| `plugins` | Появляется только если каталог `plugin/` в корне репозитория существует |
| `cwd` / `add_dirs` | Записываются только если непустые |
| `session_store` / `session_store_flush` | Записываются только если `session_store` не `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Каждое записывается только если непустое |
| `env` | `dict(spec.env)`, затем `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Действуют только когда `resume` истинно** |

`PLUGIN_DIR` — это каталог `plugin/` в корне репозитория (на три уровня вверх относительно `flower/core/agent.py`). После установки через pip этого каталога может не быть,
код проверяет через `is_dir()`.

!!! warning "`fork=True` без `resume` молча не работает"
    И `fork_session`, и `resume_session_at` вложены в `if resume:` — без `resume` они не действуют вообще,
    **и ошибки при этом нет**. Аналогично `Runtime.run(resume_at=...)` срабатывает только при заданном `resume`,
    а **`Workflow` никогда не передаёт `resume_at`**: откатиться по сообщению можно только прямым вызовом `Runtime.run`.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Панель переключателей auto-[compact](glossary.md#压缩); результат — набор переменных окружения для дочернего процесса.
Сам алгоритм compact зашит в бинарник harness и не меняется, менять можно только «срабатывать или нет».

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = ничего не выставлять, порог = окно − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (отключает и `/compact` тоже). **Прочие значения бросают `ValueError`**, а не игнорируются молча |
| `window` | `int \| None` | `None` | Не `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. На стороне CLI ограничение 100k–1M, значение меньше 100k будет поднято до 100k |

| Метод | Сигнатура | Описание |
|---|---|---|
| `env` | `() -> dict[str, str]` | Возвращает переменные окружения. **Недопустимый `mode` бросает `ValueError` именно здесь, а не при конструировании** — вызывается из `build_options`, поэтому ошибка всплывает внутри `Runtime.run` |

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

Объект политики: когда контекст почти заполнен, «написать [handoff document](glossary.md#交接书) и перейти в новую session» вместо compact.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | `bool` | `True` | Выключить — вернётся auto-compact |
| `window` | `int` | `default_window()` | Каким считается окно контекста модели |
| `headroom` | `int` | `50_000` | Сколько запаса оставлять. Причина: auto-compact срабатывает на отметке «окно −33k», handoff должен успеть раньше, а само «написать handoff» требует ещё одного хода |
| `max_generations` | `int` | `8` | Сколько поколений максимум на один step. **Это предохранитель от разноса, а не планирование ёмкости** |

| Свойство | Тип | Описание |
|---|---|---|
| `at` | `@property -> int` | Порог handoff `max(10_000, window - headroom)`. **Есть нижняя граница 10k** — ниже уже не написать даже handoff |
| `warn_at` | `@property -> int` | Точка предупреждения о приближении `max(1_000, at - 20_000)`, отправляется по одному разу на поколение |

!!! warning "Слишком маленькое `window` приведёт к бесконечным handoff'ам и сожжёт деньги"
    Если `at` окажется ниже **стартового пола** роли (у координатора замерено около 34k), каждая новая session переступает черту с первого же слова; при этом
    **handoff не расходует попытки повтора** (`attempt -= 1`), и получается бесконечная прокрутка вхолостую. Единственный предохранитель — `max_generations=8`,
    при его срабатывании `error` заменяется на диагностическое сообщение с предложением увеличить `window` либо отключить handoff.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Угадывает окно контекста по **строке имени модели** из переменных окружения `ANTHROPIC_MODEL` или `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Условие | Возврат |
|---|---|
| В имени есть отдельное слово `1m` (регулярка `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| В имени есть `haiku` | `200_000` |
| Остальное (**включая случай, когда обе переменные не заданы**) | `1_000_000` |

**По умолчанию берётся оптимистичное значение.** Переоценка — не жёсткая ошибка: API вернёт `prompt is too long`, `Runtime` распознаёт этот сигнал
(внутренняя `is_overflow`) и делает handoff на месте — но handoff этого поколения будет деградированной версией.

---

## Документы {#文书}

Исходный код: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Четыре dataclass'а, все они — «разобрать ответ модели на фиксированные разделы и записать на диск». Общая форма:
`parse()` разбирает, `missing()` / `complete()` проверяют полноту, `to_markdown()` для человека,
`prompt_block()` для нижестоящей модели, `write()` / `load()` — запись на диск и чтение обратно.

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

[Brief](glossary.md#需求确认书), **ровно четыре раздела**, фиксированный порядок
`goal` → `accept` → `bounds` → `unknowns`, китайские названия разделов соответственно «目标», «验收标准», «边界», «未知与假设».

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `goal` | `str` | `""` | Цель |
| `accept` | `str` | `""` | Критерии приёмки |
| `bounds` | `str` | `""` | Границы |
| `unknowns` | `str` | `""` | Неизвестное и допущения |
| `path` | `Path \| None` | `None` | Место записи на диск. `compare=False`, в сравнении не участвует |

| Метод | Сигнатура | Описание |
|---|---|---|
| `missing` | `() -> list[str]` | **Китайские названия** отсутствующих разделов, можно выводить как есть |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Разбирает четыре раздела из ответа модели. **Сначала снимает блоки кода в ограждениях**, неразобранное остаётся пустым |
| `to_markdown` | `() -> str` | Полный документ с шапкой метаинформации, пустые разделы пишутся как `"(未填)"` |
| `prompt_block` | `() -> str` | Компактная версия для подачи вниз по потоку, **только непустые разделы**, без метаинформации |
| `write` | `(path: str \| Path) -> Path` | Создаёт родительский каталог, пишет на диск, выставляет `self.path` в resolve-путь и возвращает его |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Если файла нет или случился `OSError`, возвращает `None`. **Заглушки `"(未填)"` восстанавливаются в пустые строки** |

Правила разбора (здесь сконцентрированы все ловушки):

- При снятии ограждений **незакрытый ``` или `~~~` приводит к отбрасыванию всего от него и дальше** — на практике clarifier вставлял в ответ весь код целиком.
  Когда вывод модели обрезан, все последующие разделы не разбираются, `complete()` даёт `False`, и gate отправляет на повтор.
- Регулярка заголовка допускает `## 目标` / `**目标**` / `目标:` / `3. 边界`, а также текст сразу после заголовка.
- Таблица псевдонимов компилируется в порядке убывания длины, иначе «未知» съест «未知与假设» раньше.
- При повторе одноимённых разделов **берётся первый непустой**.
- Если при ручном редактировании brief вы скопировали заглушку `"(未填)"` из `to_markdown()`, этот раздел по-прежнему считается отсутствующим.

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

[Handoff document](glossary.md#交接书), который пишется при [handoff](glossary.md#换代), пять разделов.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `doing` | `str` | `""` | Чем занимаемся. **Обязательное** |
| `decided` | `str` | `""` | Что решено |
| `deadends` | `str` | `""` | Тупиковые пути |
| `next` | `str` | `""` | Следующий шаг. **Обязательное** |
| `scene` | `str` | `""` | Обстановка |
| `step` | `str` | `""` | Используется только в шапке документа, **в разборе не участвует** |
| `path` | `Path \| None` | `None` | Место записи на диск |

**Обязательны только два раздела — `doing` и `next`**: жёсткое требование непустых «тупиковых путей» вынудило бы модель их выдумывать.

| Член | Сигнатура | Описание |
|---|---|---|
| `missing` | `() -> list[str]` | **Проверяет только эти два обязательных раздела** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Есть ли в тексте метка деградации `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Переиспользует разбиватель разделов из `Brief` |
| `to_markdown` | `() -> str` | Пустые разделы пишутся как `"(空)"` |
| `prompt_block` | `() -> str` | **Шапка прямо сообщает принимающему, что он принимает дела**, чтобы он не пошёл искать людей за контекстом |
| `write` | `(path) -> Path` | Как `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Как `Brief.load` |

Три члена того же модуля, **не экспортируемые, но семантически ключевые**: `is_overflow(*texts)` матчит `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` и т. п., превращая «жёсткую ошибку» в «немедленный handoff»; `HANDOFF_PROMPT` — тот промпт, который заставляет
**текущую session саму** написать handoff (содержит два плейсхолдера `{used}` и `{window}`, **это не новая роль** —
только у неё самой есть этот контекст); `degraded(step, prompt, *, why="")` механически собирает handoff, когда его не удалось написать,
запихивая в `scene` первые **1200** символов исходной задачи.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

Цель и список проверок в [goal guard](glossary.md#目标看守).

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `statement` | `str` | `""` | Формулировка цели |
| `checks` | `list[str]` | `[]` | Список проверок, по одной на строку |
| `path` | `Path \| None` | `None` | Место записи на диск |

| Член | Сигнатура | Описание |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Пункты `checks`, помеченные `[此环境无法验证:…]`. **Их провал предрешён в момент постановки цели** |
| `missing` | `() -> list[str]` | Требуется непустой `statement` **и** непустой `checks` |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` — по одному на строку, маркеры `-` / `*` / `1.` снимаются автоматически |
| `to_markdown` | `() -> str` | При пустом списке пишется `"(空)"` |
| `prompt_block` | `() -> str` | Компактная версия для подачи вниз по потоку |
| `write` / `load` | Как у `Brief` | Запись на диск и чтение обратно |
| `amend` | `(extra: str) -> Goal` | **Дописывает, а не перезаписывает**: после `statement` приклеивается `"\n\n(已修改)" + extra`, возвращает `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Результат одного раунда работы [judge](glossary.md#判定者), **ровно три раздела**: вывод / обоснование / не пройдено.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, при неудачном разборе — `""` |
| `reason` | `str` | `""` | Обоснование |
| `failed` | `list[str]` | `[]` | Непройденные пункты списка |

| Член | Сигнатура | Описание |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Удалось ли вообще разобрать вывод. **`ok=False` обязан трактоваться как «не достигнуто», а не как достигнуто** |
| `parse` | `@classmethod (text) -> Verdict` | См. ниже |
| `feedback` | `() -> str` | Что возвращается worker'у: только «в чём недостача», без решения |

Порядок распознавания в `parse`:

1. Сначала берётся раздел по заголовку «结论» / «判定».
2. Если разделов с заголовками нет, весь текст после strip: `fullmatch(r"1|true")` → достигнуто; `fullmatch(r"0|false")` → не достигнуто.
3. Иначе в тексте вывода ищется первое совпадение по таблице слов состояния (**длинные слова первыми**).
   **«无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» — всё это относится к `unreachable`** —
   на этом реально спотыкались: целевая платформа macOS, запуск в Linux-контейнере, а judge посмотрел на ветку в исходниках и признал пройденным.
4. Всё ещё нет — ищется отдельно стоящее `\b1\b` → достигнуто, `\b0\b` → не достигнуто.
5. Ничего не подошло → `state=""`, `ok=False`.

`unreachable` и `not_yet` — **два разных вывода**: первый ведёт по ветке «остановиться и спросить человека», а не «ещё один раунд».

## Слой hook {#hook}

Исходник: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Этот слой — **граница исполнения** flower: каких инструментов не должен касаться главный поток, как подрезать сверхдлинные результаты, какая роль уходит в отдельный worktree — всё это принудительно задаётся hook'ами SDK, **а не промптом**. Причина прямая: промпт — это рекомендация, модель может её проигнорировать. Замерено: даже когда в системном промпте прямо написано «не используй worktree», инъекция `isolate_guard` всё равно срабатывает (модель передаёт `None`, а на диск ложится `'worktree'`).

Девять экспортов: пять фабрик guard'ов, возвращающих `HookMatcher` (`whitelist_guard` может вернуть `None`), один сборщик, один объединитель, две функции маркировки изоляции. Вручную их вешать не нужно — [`Runtime`](#runtime) собирает всё автоматически по `AgentSpec`. Ручная установка нужна только если вы сами управляете SDK (минуя `Runtime`).

**Определение главного потока идёт через одну функцию**: `_is_main_thread(data) = not data.get("agent_id")` — в данных tool-lifecycle hook'а у subagent есть `agent_id`, у [главного потока](glossary.md#主线程) его нет. На этом держатся все guard'ы, которые «перехватывают только главный поток».

Константы групп инструментов (уровня модуля, не экспортируются, но определяют matcher'ы по умолчанию):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Шпаргалка: какой guard висит на каком событии SDK {#hook-速查表}

| Функция | Событие SDK hook | matcher | Что перехватывает | Что возвращает | Кто устанавливает |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | те из `Bash\|Write\|Edit\|NotebookEdit`, которых **нет в `allowed_tools`** | вызов запрещённого инструмента **только главным потоком** | `permissionDecision: "deny"` + причина | `Runtime._attempt`, **только если `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (меняется через `tools=`) | **только главный поток** работает руками; при `allow_glance=True` `Bash`, прошедший `is_ephemeral()`, пропускается | `deny` + «отправь subagent» | `workbench_hooks(delegate_only=True)`, **только если у `Runtime` есть верстак** |
| `isolate_guard` | `PreToolUse` | `Agent` | в `tool_input` нет ни `cwd`, ни `isolation`, и `subagent_type` помечен через `isolated()` | `permissionDecision: "allow"` + `updatedInput` (инъекция `isolation="worktree"`) | `workbench_hooks`, **только если в `agents` есть помеченная роль** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` попадает внутрь `workbench.root` | `{}` (побочный эффект — `workbench.refresh()`) | `workbench_hooks`, всегда |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **строковые поля** в `tool_response` длиной ≥ `threshold`; чтение самого каталога сброса пропускается | `updatedToolOutput` (сброс на диск + строка-указатель + первые 400 символов) | `workbench_hooks`, **только если `spill_threshold` истинно** |

**Ключевой вывод из этой таблицы**: при `Runtime(workbench=False)` весь `workbench_hooks` не ставится вообще; а для координатора с `delegate_only=True` пропускается ещё и `whitelist_guard` — **у главного потока не остаётся ни одной стены**. Подробности — в предупреждении в разделе [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Делает `allowed_tools` действительно исключающим для тех четырёх инструментов, что работают руками.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `allowed` | `list[str] \| None` | обязательный, позиционный | обычно сюда напрямую идёт `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | самоназвание в тексте отказа. `Runtime` передаёт `spec.name` |

- **Висит на `PreToolUse`**, matcher — `"|".join(banned)`, где `banned` = те из `Bash` `Write` `Edit` `NotebookEdit`, которых нет в `allowed`.
- Срабатывание = `permissionDecision: "deny"`, смысл текста: «У XX нет YY. **Это сделано намеренно, а не забыто в конфиге.** Впиши вывод в тело своего ответа, фреймворк возьмёт его оттуда — не пытайся обойти это другой формулировкой».
- **Перехватывает только главный поток текущей сессии**, subagent'ы проходят — их инструменты определяются `AgentDefinition.tools`.
- Если перехватывать нечего, возвращает **`None`** (например, для роли вроде `worker()` с полным набором инструментов), и вызывающая сторона по этому решает, ставить его или нет.

**Почему он обязан существовать**: `allowed_tools` — это **список без запроса подтверждения, а не исключающий белый список**. Два замера: судья с заданной целью выполнил `Bash` 11 раз; в пробнике за $0.1 агент с `allowed_tools=["Read"]` спокойно вызывал `Write`/`Bash`. Поэтому «отсутствие инструментов записи» у `clarify()` / `judge()` **держится на этом hook'е**, а не на самом белом списке.

Плюс в том, что он выводится из `allowed_tools`: `judge(can_run=True)` автоматически сохраняет `Bash` и по-прежнему перехватывает `Write`/`Edit` — отдельный переключатель не нужен.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Главный поток работает руками → отказ с указанием, что делать дальше.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. Это строка-регулярка, а не список |
| `allow_glance` | `bool` | `False` | при `True` пропускает, если `tool_name == "Bash"` и [`is_ephemeral(command)`](#is-ephemeral) истинно |

- **Висит на `PreToolUse`**, matcher — это и есть `tools`.
- Главный поток вызывает один из этих четырёх инструментов → deny, и в причине **сказано, как поступить дальше**: отправить subagent через инструмент `Agent`, прописав в задании цель и критерии приёмки, и потребовать, чтобы длинный вывод он писал в `.flower/artifacts/`, а в ответе давал только путь и вывод.
- Subagent'ы пропускаются всегда.

Отличие от `whitelist_guard` — **в формулировке**: оба перехватывают один и тот же набор инструментов, но этот говорит «делегируй», что здесь уместнее. Поэтому роли с `delegate_only=True` получают только его — при дублировании модель получит две противоречащие инструкции.

Критерий пропуска при `allow_glance=True` и критерий «будет ли результат подрезан» — **это одна и та же функция** ([`is_ephemeral`](#is-ephemeral)): множество пропускаемого обязано совпадать с множеством устаревающего, меняешь одно — меняй и другое.

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

Результаты инструментов сверх порога **сразу [сбрасываются на диск](glossary.md#落盘)**, в контексте остаётся одна строка-указатель — а не ждём, пока контекст заполнится, чтобы потом его сжимать.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | каталог сброса — `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | со скольких символов сбрасывать |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (по умолчанию) = результаты subagent'ов тоже сбрасываются |

- **Висит на `PostToolUse`**, возвращает `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <подрезанное>}}`.
- Имя файла сброса — первые 16 знаков `sha256` содержимого + `.txt`, в контексте вместо содержимого остаётся строка-указатель + **первые 400 символов**.
- `updatedToolOutput` **обязан сохранить структуру вывода исходного инструмента**, поэтому заменяются только слишком длинные **строковые поля** словаря; **списки не трогаются вообще** (внутри могут быть блоки изображений). Неверная структура будет отвергнута (оригинал останется как есть, без ошибки).
- **Чтение самих сброшенных файлов обязано пропускаться** — иначе «прочитай его через `Read`» пустые слова: прочитанный текст снова сбрасывается, бесконечный цикл. Напоролись на практике, модель перепробовала пять формулировок обхода.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Записали что-то на [верстак](glossary.md#工作台) — обновляем `INDEX.md`, и следующий агент с самого начала знает, что это есть.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | область проверки и объект обновления |

**Висит на `PostToolUse`**, matcher `"Write|Edit"`. Если `tool_input["file_path"]` после resolve попадает внутрь `workbench.root`, вызывается `workbench.refresh()`. **Всегда возвращает `{}`** — он ничего не меняет, только побочный эффект.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Выдаёт subagent'ам отдельный git worktree по роли, реализуя [изоляцию](glossary.md#隔离).

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | обязательный, позиционный | таблица ролей, по ней проверяется, помечен ли `subagent_type` |
| `on_inject` | `Any` | `None` | необязательный колбэк, вызывается как `on_inject(subagent_type, description)` |

**Висит на `PreToolUse`**, matcher `"Agent"`. Инъекция происходит только при одновременном выполнении трёх условий: `tool_name == "Agent"`, в `tool_input` **нет ни `cwd`, ни `isolation`**, и роль, соответствующая `subagent_type`, помечена через `isolated()`. Тогда возвращается `permissionDecision: "allow"` + `updatedInput` (в котором `isolation` выставлен в `"worktree"`).

`isolation` и `cwd` **взаимоисключающи** в инструменте `Agent` — если модель сама указала `cwd`, это уважается. «Нужна ли изоляция» — **свойство роли**, а не глобальный переключатель и не решение на каждую выдачу задачи; ролям, которым изоляция не нужна, не добавляется ни байта.

**Включили изоляцию — выносите [верстак](glossary.md#工作台) из репозитория.** Изолированный агент не может писать в общий checkout, поэтому верстак обязан указывать через `home=` наружу от репозитория. `starter_flow(isolate=True)` использует `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` — `<run_dir>/workbench`: оба вне репозитория, **но это не один и тот же каталог**, не смешивайте их.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Ставит определению subagent'а метку «нужна отдельная рабочая область» и читает эту метку обратно.

| Функция | Параметр | По умолчанию | Описание |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | обязательный | определение, которое помечаем. **Возвращается тот же самый объект** |
| | `flag: bool` | `True` | позиционный. `False` = снять метку |
| `wants_isolation` | `agent: AgentDefinition \| None` | обязательный | принимает и `None`, тогда возвращает `False` |

Метка ставится через `object.__setattr__` как атрибут Python-стороны `_flower_isolate`, **а не поле dataclass**: SDK сериализует через `asdict()` и признаёт только объявленные поля, так что метка не утекает в CLI (проверено).

**Цена**: `dataclasses.replace()` над `AgentDefinition` теряет эту метку, и изоляция молча отключается.

`worker(isolate=True)` внутри просто вызывает `isolated()`.

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

Ставит за один раз все hook'и, нужные верстаку. Именно это вызывает `Runtime._attempt`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | передаётся в `index_guard` и `spill_guard` |
| `delegate_only` | `bool` | `True` | `delegate_guard` ставится только при `True` |
| `spill_threshold` | `int \| None` | `4000` | `spill_guard` ставится только если истинно |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | `isolate_guard` добавляется, если помечена через `isolated()` **хотя бы одна** роль |
| `allow_glance` | `bool` | `False` | пробрасывается в `delegate_guard(allow_glance=)` |

Результат:

- `PreToolUse`: при `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`; если есть помеченные роли → добавляется `isolate_guard(agents)`.
- `PostToolUse`: всегда `[index_guard(workbench)]`; если `spill_threshold` истинно → добавляется `spill_guard(workbench, threshold=spill_threshold)`.
- **Ключи событий с пустым списком выбрасываются**, пустой list не возвращается.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Склеивает** несколько групп конфигурации hook'ов по имени события.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | переменное число аргументов | сколько угодно групп. Группы `None` пропускаются |

Использует `extend`, **дубликаты не убирает** — передадите один guard дважды, он и установится дважды. `Runtime` через него объединяет `spec.hooks`, `workbench_hooks(...)` и `whitelist_guard`.

---

## Верстак {#工作台}

Исходник: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

Рабочий каталог для сброса на диск: три подкаталога + один индекс. Индекс **инъектируется в system prompt**, поэтому агент на каждом ходу знает, что у него под рукой.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `Path` | обязательный, позиционный | рабочая область. `__post_init__` делает resolve |
| `dirname` | `str` | `".flower"` | имя каталога верстака, относительно `workspace` |
| `max_index_entries` | `int` | `40` | **касается только `prompt_block()`**: сколько записей каждого типа максимум перечисляется во фрагменте, инъектируемом в system prompt; лишние сворачиваются в строку «…ещё N штук». Сам `INDEX.md` не ограничен, там перечисляется всё |
| `home` | `Path \| None` | `None` | если задан, используется как `root`, **`dirname` игнорируется**. При не-`None` тоже делается resolve |

| Член | Сигнатура | Описание |
|---|---|---|
| `root` | `@property -> Path` | если задан `home` — он, иначе `workspace / dirname` |
| `external` | `@property -> bool` | находится ли `root` **вне** `workspace`. В режиме изоляции должно быть `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, скрипты, которые запустят второй раз |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, длинные результаты свыше 2000 символов |
| `notes` | `@property -> Path` | `root / "notes"`, ключевые решения, одно решение — один файл |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | путь для показа модели: внутри рабочей области — относительный, снаружи — абсолютный |
| `ensure` | `() -> Workbench` | mkdir трёх каталогов, возвращает `self` (можно по цепочке: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(отображаемый путь, описание, размер в байтах)`. Рекурсивный `rglob("*")`, файлы, начинающиеся с `.`, пропускаются |
| `refresh` | `() -> str` | перезаписывает `INDEX.md` и возвращает содержимое |
| `prompt_block` | `() -> str` | **тот самый фрагмент, что инъектируется в system prompt**. Намеренно короткий — он присутствует на каждом ходу |

Формат самоописания скрипта: `# desc: 一句话` в пределах первых 8 строк (распознаются также комментарии `//` и `--`), с откатом на первый непустой комментарий или первую строку docstring (обрезается до 100 символов).

Три правила, которые инъектирует `prompt_block()`:

1. Скрипты, которые понадобится запустить второй раз, писать в `scripts/`, первой строкой `# desc:`.
2. Результаты длиннее **2000 символов** писать в `artifacts/`, в диалог давать только путь и вывод.
3. Ключевые решения писать в `notes/`, одно решение — один файл.

При `external=True` `prompt_block()` дополнительно вставляет фразу «обращайся к нему по абсолютному пути».

**Индекс subagent'ам не наследуется.** Он идёт через `system_prompt.append` уровня сессии, а у subagent'а свой system prompt (замерено на $0.2461). Поэтому два пункта — «длинные результаты в `artifacts/`» и «где находится верстак» — обязан пересказать [координатор](glossary.md#协调者) в [задании](glossary.md#任务书): **это единственный канал**, а не избыточность. В `WORKER_RULES` этого **намеренно нет**: реальные пути генерирует `Workbench`, зашитые в текст они будут неверными.

---

## Хранилище сессий {#会话存储}

Исходник: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Три уровня наследования: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`. `Runtime` **всегда использует самый внешний**, а политики всех трёх уровней задаются параметрами конструктора.

Каждый уровень отвечает за своё: запись на диск, [подрезка](glossary.md#裁剪) по объёму и ценности, [отсечение](glossary.md#剪除) по признаку «это ошибка или нет». И подрезка, и отсечение происходят в момент **`load()`** (то есть когда resume скармливает историю модели обратно), исходные записи в SQLite не меняются ни на байт.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Реализация протокола `SessionStore` из SDK, три таблицы `entries` / `meta` / `summaries`. Ключ хранилища — `project_key/session_id[/subpath]`: **транскрипты дочерних агентов различаются по subpath**.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `str \| Path` | обязательный, позиционный | файл базы. Соединение с `check_same_thread=False` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `append` | `async (key, entries) -> None` | идемпотентная дедупликация по uuid (сначала убираются уже записанные, потом дубли внутри пачки). При повторном проигрывании всей пачки **mtime не сдвигается и fold summary не повторяется**; в summary участвует только основной транскрипт (`subpath is None`) |
| `projects` | `() -> list[str]` | реально существующие в базе `project_key`. **SDK выводит его из cwd; перед запросом проверьте по этому методу, не гадайте** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **синхронный, payload не читает**, смотрит одну строку в meta. Нужен для «продолжения по тому же пути»: resume несуществующей сессии рванёт только после запуска дочернего процесса |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | сколько контекста модель реально видела на последнем ходу; если не найдено — `0`. Сканирует с конца только последние `scan` записей; считаются все три составляющие `input + cache_read + cache_creation` (если смотреть только `input_tokens`, оценка будет сильно занижена) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | сортировка по seq; если строк нет — `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | только основные транскрипты |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | перечисляет сводки сессий |
| `delete` | `async (key) -> None` | при удалении основного транскрипта **каскадно удаляет дочерние агентские**, чтобы не остались сироты |
| `list_subkeys` | `async (key) -> list[str]` | перечисляет дочерние транскрипты этой сессии |
| `close` | `() -> None` | закрывает соединение |

Внутренний `_next_mtime` гарантирует **строгую монотонность** — `list_sessions` и summary sidecar используют эти часы совместно, иначе быстрый путь проверки staleness в SDK ошибётся.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `keep_recent` | `int` | `20` | последние N `tool_result` сохраняются целиком |
| `min_chars` | `int` | `2000` | короткие результаты подрезать не стоит |
| `spill_dirname` | `str` | `".flower/spill"` | **относительно `workspace`, обязан быть внутри рабочей области** — иначе `Read` агента до него не дотянется |
| `enabled` | `bool` | `True` | при `Runtime(trim=False)` здесь `False` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | формирует ту самую строку-указатель, заменяющую тело |

**Два каталога сброса — не один и тот же.** `spill_guard` пишет в `<workbench.root>/spill/` (может быть вне рабочей области); `TrimPolicy.spill_dirname` пишет в `<workspace>/.flower/spill/` (**обязан быть внутри рабочей области**). Они соответствуют «подрезке на месте» и «подрезке при resume»; разные каталоги — это намеренно, не сводите их в один.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Политика устаревания результатов [одноразовых команд](glossary.md#一次性命令).

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | `bool` | `True` | если выключить, пометка устаревания не делается вообще |
| `keep_recent` | `int` | `6` | последние N освобождаются от пометки. **Заметно меньше, чем 20 у `TrimPolicy`** |
| `max_chars` | `int` | `2000` | что длиннее — пропускается и отдаётся на архивирование `TrimPolicy` |
| `text` | `str` | см. сигнатуру | текст замены, два плейсхолдера `{cmd}` и `{age}` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | подставляет в `text` и формирует тело замены |

**Действует только на результаты инструмента `Bash`**, и команда должна попадать в белый список одноразовых команд. **`Read` сюда не входит** — содержимое файла со временем не искажается настолько, чтобы вводить в заблуждение. Устаревшее содержимое **на диск не сбрасывается**, а просто выбрасывается.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Определяет, является ли Bash-команда [одноразовой командой](glossary.md#一次性命令). **Проверка пропуска в `delegate_guard` и проверка устаревания при подрезке используют одну и ту же функцию**: множество команд, которые координатор может выполнить сам, обязано совпадать с множеством результатов, помечаемых как устаревшие. Пропускать без подрезки — устаревший `git status` навсегда займёт контекст да ещё и введёт в заблуждение; подрезать без пропуска — координатор ради одного `ls` отправит subagent'а, отдав 4.3k стоимости запуска за несколько десятков символов.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `cmd` | `str` | обязательный, позиционный | полная командная строка |

Порядок проверки:

1. Пусто / одни пробелы → `False`.
2. Подстановка команд (`$(`, обратные кавычки, `<(`, `>(`) или конструкции «меняющие состояние» → `False`.
3. Если после снятия безопасных перенаправлений (`2>&1`, `&> /dev/null` и т. п.) всё ещё есть `>` или `<` → `False`.
4. Если после снятия `&&` / `||` / `;` / `|` остаётся одиночный `&` (запуск в фоне) → `False`.
5. Разбить по `&&` / `||` / `;` / `|`, **каждый сегмент обязан попасть в белый список**.

Крупные категории глаголов в белом списке: подкоманды `git` только на чтение (`status` `diff` `log` `show` `branch` `rev-parse` и др.), сведения о каталогах и системе (`ls` `pwd` `df` `du` `date` `whoami` `env` и др.), процессы и контейнеры (`ps` `top` `lsof` `docker ps` `kubectl get` и др.), просмотр файлов (`cat` `head` `tail` `wc` `stat` `find` `tree`), поиск путей (`which` `whereis` `command -v` `type`), обработка текста (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` и др.).

Даже если глагол в белом списке, такие конструкции всё равно перехватываются: `xargs`, `exec`, `eval`, `source`, `tee`, `find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` и `print >` внутри `awk`, `git branch -D/-d/-m`, `git * --force/--hard/--prune`.

Первая версия рубила все составные команды подряд, и **на практике glance перестал работать вообще** (все три попытки координатора были перехвачены), поэтому проверку переделали на посегментную.

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

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `str \| Path` | обязательный | файл базы |
| `workspace` | `str \| Path` | обязательный | база отсчёта для каталога сброса |
| `policy` | `TrimPolicy \| None` | `None` | если не задан, берётся `TrimPolicy()` по умолчанию |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | если не задан, берётся `EphemeralPolicy()` по умолчанию |

Публичные атрибуты: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Порядок в `load()`: `super().load()` → очистка `last_report` → если `ephemeral.enabled`, то `expire()` → если `policy.enabled`, то `trim()`. **При `enabled=False` соответствующий шаг пропускается целиком.**

| Метод | Описание |
|---|---|
| `expire(entries)` | у устаревших результатов `Bash`, зависящих от времени, **заменяется только тело, блок остаётся**. Команда ищется в `tool_use` предыдущего сообщения assistant; записи `isCompactSummary` / `isMeta` пропускаются; всё длиннее `max_chars` пропускается (уходит в `trim`); последние `keep_recent` освобождаются. Пишет `last_report["expired"]` |
| `trim(entries)` | тело `tool_result` размером `>= min_chars` сбрасывается на диск в `<workspace>/<spill_dirname>/<первые 16 знаков sha256>.txt`, содержимое блока заменяется указателем; последние `keep_recent` освобождаются. Пишет `cleared` / `kept` / `chars_saved` в `last_report` |

**Подрезается только чистый текст**: блоки `image` / `document` остаются как есть.

**Две структурные красные линии**: сам **блок `tool_result` обязан остаться**, менять можно только content (пропадёт один — получите «Missing Tool Result Block»); записи `isCompactSummary` трогать нельзя.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Рендерит `store.last_report` в одну строку на китайском для логов UI.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | обязательный, позиционный | принимает и подкласс `PruningSessionStore` |

Три варианта вывода: ничего не сделано → `"未裁剪"`; только устаревание → `"N 个时效性结果标记为过期"`; иначе `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, где X = `chars_saved // 4`.

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

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | убирать синтетические сообщения об ошибках API (остатки после обрыва связи) |
| `neutralize_interrupts` | `bool` | `True` | заменять оставшиеся после прерывания `tool_result` на нейтральное пояснение |
| `interrupt_text` | `str` | см. сигнатуру | текст нейтрального пояснения |
| `heal_orphans` | `bool` | `True` | достраивать синтетический результат для осиротевших вызовов, где есть `tool_use`, но нет `tool_result` |
| `orphan_text` | `str` | см. сигнатуру | тело того самого достроенного `tool_result` |
| `keep_denials` | `int` | `1` | сохранять последние N отклонённых вызовов инструментов |

`heal_orphans` лечит **400 при каждом resume после прерывания**: прерывание рвёт поток на границе сообщения, и за `tool_use`, который был в полёте, может вообще не оказаться `tool_result`, а API требует их парности — эта испорченная история остаётся в транскрипте, и потом **каждый** resume ею отбивается. `heal_orphans()` вставляет после того сообщения assistant с сиротой запись `user` с недостающим результатом и переписывает `parentUuid`, ранее указывавший на то сообщение assistant, на эту новую запись, сохраняя непрерывность цепочки (`prune.py:95-147`). **Достраиваем, а не удаляем**: удаление сироты потребовало бы перешивки родительской цепочки assistant, а в той же записи могут быть нормальные блоки, текст и thinking — легко зацепить лишнее (`prune.py:195-204`).

Обоснование `keep_denials`: отклонённый вызов никогда не выполнялся, информации в результате нет, а места занимает немало (замерено: 273 символа за раз = 93 знака текста отказа + 180 знаков **оригинала мёртвой команды**). Важнее другое — **он вводит в заблуждение**: замерено, что прочитав несколько «не используй Bash напрямую», координатор перестаёт пробовать даже разрешённый `git status`, выучивая беспомощность. **По умолчанию оставляем 1, а не 0**: самый свежий отказ мешает модели в пределах одного хода раз за разом повторять одну и ту же перехваченную команду.

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

**Store по умолчанию у `Runtime`.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `str \| Path` | обязательный | файл базы |
| `workspace` | `str \| Path` | обязательный | база отсчёта для каталога сброса |
| `policy` | `TrimPolicy \| None` | `None` | политика подрезки |
| `prune` | `PrunePolicy \| None` | `None` | политика отсечения |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | политика устаревания |

Сверх родительских есть три публичных атрибута: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (сначала `expire` + `trim`) → `self.prune(entries)`. `prune` делает три вещи:

1. **Убирает слишком старые отклонённые вызовы**: определяются по структурной метке harness'а `toolDenialKind == "permission-rule"` (надёжнее, чем сопоставление текста отказа), последние `keep_denials` сохраняются, у остальных убираются блоки `tool_use` **и** `tool_result` вместе. Если в одном сообщении assistant несколько `tool_use`, **убирается только попавший под критерий**, иначе получится «Missing Tool Result Block»; блоки с текстом и thinking сохраняются.
2. **Убирает синтетические сообщения об ошибках API.** В SQLite они остаются как есть, просто не скармливаются обратно.
3. **Заменяет оставшиеся после прерывания `tool_result` на нейтральное пояснение** — меняется только тело, запись не убирается.

**Единственная структурная красная линия**: транскрипт — односвязная цепочка по `parentUuid`, убрав запись, надо подцепить её детей к ближайшему выжившему предку. Внутреннему `relink` в `entries` **обязательно передавать полный список (включая те, что будут убраны)**, фильтрацию он делает сам: если вызывающая сторона отфильтрует заранее, цепочка порвётся на этом месте и вся предыдущая история пропадёт (**наступали: когда убираемые записи в конце, это не проявляется, а в середине — взрывается**).

**Порядок параметров отличается от родителя**: у родителя `(path, workspace, policy, ephemeral)`, у подкласса `(path, workspace, policy, prune, ephemeral)` — **четвёртый позиционный параметр сменился с `ephemeral` на `prune`**, и передача по позиции молча всё сдвинет. Передавайте только по ключевым словам.

---

## Устойчивость {#韧性}

Исходник: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

При обрыве сети — висеть и ждать, а не падать с ошибкой. Четыре экспорта: один dataclass с политикой + три функции-пробы, которые можно использовать по отдельности.

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

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | `bool` | `True` | если выключить, никакие сбои не будут повторяться |
| `max_attempts` | `int` | `6` | **включая первую попытку** |
| `base_delay` | `float` | `4.0` | база отката, секунды |
| `max_delay` | `float` | `120.0` | верхняя граница отката, секунды |
| `probe_timeout` | `float` | `5.0` | таймаут одной пробы |
| `probe_interval` | `float` | `15.0` | пауза между двумя пробами |
| `max_offline_wait` | `float` | `3600.0` | максимум времени висеть в ожидании, по умолчанию 1 час |
| `retry_unknown` | `bool` | `True` | повторять ли ошибки, которые не удалось классифицировать |
| `resume_prompt` | `str` | см. сигнатуру | что говорим при продолжении. **Намеренно не содержит никаких деталей ошибки** — модели нужно знать «тебя прервали, продолжай», а не то, был это `ENOTFOUND` или 503 |

| Метод | Сигнатура | Описание |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)`, умноженное на `0.75 + random()*0.5` (джиттер ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, либо `kind == "unknown"` при `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | висит и ждёт возврата сети. Вернулась — `True`, вышли за `max_offline_wait` — `False`. `notify` — колбэк `(str) -> None`, вызывается по одному разу **при первой недоступности** и **при восстановлении** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Раскладывает текст ошибки на три класса: `"transient"` / `"fatal"` / `"unknown"`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `text` | `str \| None` | обязательный, позиционный | исходный текст сообщения об ошибке. Пустой → `"unknown"` |

**Сначала проверяем fatal, потом transient** — в текстах вроде 401 часто встречается слово `connection`, и при обратном порядке будешь ждать вечно.

| Класс | На что срабатывает |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

Хост и порт для пробы, берутся из `ANTHROPIC_BASE_URL`, по умолчанию `https://api.anthropic.com`; порт по умолчанию `80` (http) или `443`.

**При своём шлюзе пробовать нужно именно его** — доступность `api.anthropic.com` ничего не говорит о доступности шлюза.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `host` | `str` | обязательный, позиционный | имя хоста |
| `port` | `int` | обязательный, позиционный | порт |
| `timeout` | `float` | `5.0` | секунды |

**Только DNS (`getaddrinfo`) + TCP-рукопожатие**, HTTP не отправляется, учётные данные не передаются, **денег не стоит**. Любое исключение считается недоступностью.

---

## События и взаимодействие {#事件与交互}

Исходники: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[События](glossary.md#事件) — это поток сообщений SDK, сплющенный в стабильную структуру.
**[Слой взаимодействия](glossary.md#交互层) знает только `Event` и не импортирует ни одного типа SDK** — это и есть
граница, благодаря которой смена UI не требует правок в ядре. См. [Замена слоя взаимодействия](../guide/interaction.md).

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

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `kind` | `EventKind` | обязательное | см. таблицу ниже |
| `text` | `str` | `""` | основной текст |
| `tool` | `str` | `""` | имя инструмента, есть только у `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | структурированная дополнительная информация |
| `raw` | `Any` | `None` | исходный объект SDK, когда хочется копнуть глубже |

`__str__`: для `tool_call` это `f"[{tool}] {text}"`, иначе `text`, а если `text` пуст — `f"<{kind}>"`.
Поэтому `print(ev)` сразу читаем.

Всего `EventKind` — **15**:

| kind | кто порождает | Описание |
|---|---|---|
| `text` | `normalize` | основной текст assistant |
| `thinking` | `normalize` | блок размышления |
| `tool_call` | `normalize` | вызов инструмента. `text` — сводка `file_path` / `command` / `pattern`, обрезано до 200 символов |
| `tool_result` | `normalize` | результат инструмента. `text` обрезан до 500 символов, в payload есть `tool_use_id` / `is_error` |
| `task` | `normalize` | три вида сообщений Task. `text` **пустой**, имя класса лежит в `payload["kind"]` |
| `system` | `normalize` | прочие системные сообщения, `text` — это subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, в payload есть `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | синтетическое сообщение об ошибке API, в payload `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Это ввод, а не продукт модели**, поэтому не попадает в `StepResult.text` |
| `unknown` | `normalize` | то, что не опознано |
| `retry` | `Runtime` | уведомление о повторе |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | в payload `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | вопрос, **а также «то, что человек сказал по своей инициативе»** |

**Последние четыре не порождаются `normalize()`.**

В `payload` всех событий assistant / user есть:

| Ключ | Тип | Описание |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | есть только когда `subagent` истинно |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Это единственный источник критерия [handoff](glossary.md#换代)** и то число, которое в long-horizon запуске нужно видеть в первую очередь |

**Один и тот же kind `ask` несёт и «вопрос», и «то, что человек сказал сам».** У второго
`payload["kind"] == "mail"` и **нет `options` / `remaining`**. UI обязан сначала проверить `payload.get("kind")`
и только потом решать, как это рисовать, иначе обычная реплика повиснет как вопрос, ожидающий ответа.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Сплющивает одно сообщение SDK в от 0 до N `Event`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `message` | `Any` | обязательный, позиционный | любой объект сообщения SDK |

Ключевые ветки:

- **Синтетическое сообщение об ошибке API** (`isApiErrorMessage=True` или `model == "<synthetic>"`) → одно
  `Event("error", payload={"synthetic": True})`. **Это сделано намеренно** — иначе текст об обрыве связи ушёл бы
  как основной текст в `StepResult.text` и был бы передан следующему шагу.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<сводка>, tool=block.name, payload={"id", "input"})`.
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`.
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`.
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`.

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

Один вопрос человеку.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `id` | `str` | обязательное | по нему находят вопрос при ответе |
| `question` | `str` | обязательное | текст вопроса |
| `options` | `list[str]` | `[]` | варианты. Человек может ничего не выбирать и написать своё |
| `asked_at` | `float` | `time.time()` | момент вопроса |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | текст ответа |

| Член | Сигнатура | Описание |
|---|---|---|
| `waited_s` | `@property -> float` | сколько уже ждём |
| `event` | `(remaining: int = 0) -> Event` | выдаёт `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

**Внутрипроцессный MCP-сервер** (два инструмента) + набор методов для UI. Со стороны модели видны только
`mcp__human__ask` и `mcp__human__inbox`. Все параметры конструктора — keyword-only.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | выход в режиме **push**. Если он задан, `Workflow.run` уже не будет подключать свой |
| `max_asks` | `int \| None` | `None` | **без ограничения по числу**. Число — жёсткая квота, `0` = спрашивать нельзя (полностью автоматический режим / CI). При превышении инструмент **сразу отказывает, не блокируясь** |
| `timeout_s` | `float \| None` | `1800.0` | 30 минут. `None` = ждать вечно; **`<= 0` = не ждать, все вопросы сразу уходят в пустоту** |
| `log_path` | `str \| Path \| None` | `None` | вопросы и ответы **дописываются** на диск, контекст не занимают |
| `amend_path` | `str \| Path \| None` | `None` | сказанное человеком по ходу запуска дописывается в этот файл (обычно это бриф). **Без записи на диск это не переживёт границу шага** — следующий шаг это новая сессия, читающая только замороженный файл |
| `over_budget_text` | `str` | константа модуля | что вернуть модели при превышении квоты |
| `timeout_text` | `str` | константа модуля | что вернуть модели при таймауте |
| `declined_text` | `str` | константа модуля | что вернуть модели, когда вопрос пропущен |

Публичные атрибуты: восемь одноимённых с параметрами конструктора, плюс `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**исключения, брошенные колбэком UI, собираются сюда и не прерывают запуск**).

| Член | Сигнатура | Описание |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | напрямую кладётся в `AgentSpec.mcp_servers`. **Имя ключа обязано совпадать с именем сервера**, поэтому он отдаёт их вместе |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | висит и ждёт человека. **Кроме `CancelledError` не бросает исключений никогда** — отсутствие ответа тоже ответ, различайте по `ask.state` |
| `send` | `(text: str) -> Mail \| None` | человек говорит что-то сам. **Можно звать из любого потока.** Агента не прерывает; внутри автоматически вызывает `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | дописывает в `amend_path`. Возвращает, была ли запись на самом деле (нет пути, пустой текст, `OSError` — всё это `False`) |
| `pending_mail` | `() -> list[Mail]` | не забранные mail |
| `remaining` | `@property -> int` | сколько раз ещё можно спросить. **При `max_asks=None` возвращает `-1`**, не 0 и не бесконечность |
| `pending` | `() -> list[Ask]` | вопросы, висящие в ожидании ответа |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | для режима **pull**. По таймауту возвращает `None`, при отмене бросает |
| `answer` | `(ask_id: str, text: str) -> bool` | ответить. `False` = этот вопрос уже не ждёт ответа (таймаут / уже отвечен) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | пропустить, пусть модель решает сама |
| `transcript` | `() -> str` | markdown с записью вопросов и ответов |

**Выберите один из двух способов забирать**: **push** — конструктор `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` подключает свой выход только когда `channel.on_event is None`, так что переданный вами не будет перезаписан.

**Между потоками**: `answer` / `decline` / `send` внутри идут через `loop.call_soon_threadsafe`,
вызов из веб-бэкенда или из потока ввода TUI — норма.

Три семантики «0 / None» различаются, не путайте: `max_asks=None` = без ограничения, `max_asks=0` = спрашивать нельзя;
`timeout_s=None` = ждать вечно, `timeout_s<=0` = таймаут мгновенно; `remaining` при `max_asks=None` равно `-1`.

`Mail` не экспортируется, но встречается в возвращаемых значениях: это dataclass с полями `id` / `text` / `sent_at` / `taken`.

---

## Происхождение {#血缘}

Исходник: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Межпроцессная запись «какой шаг какой сессией пользовался»; [непрерывность](glossary.md#接续) через неё находит,
до чего дошли в прошлый раз. Файл — `<run_dir>/lineage.json`.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `Path` | обязательное | путь к файлу происхождения |
| `workspace` | `Path` | обязательное | workspace. `__post_init__` делает resolve |
| `steps` | `dict[str, str]` | `{}` | имя шага → `session_id` |
| `woke` | `int` | `0` | сколько раз просыпались |

| Член | Сигнатура | Описание |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | читает `<run_dir>/lineage.json`. **Файла нет, файл не читается или поле `workspace` не совпало — всегда возвращает пустой объект, без ошибки** |
| `remember` | `(step: str, session_id: str) -> None` | запоминает соответствие и **сразу пишет на диск**. При пустом step или пустом sid просто выходит |
| `bump` | `() -> int` | счётчик пробуждений +1, запись на диск, возврат нового значения (при первом запуске это `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **перемещает** файл происхождения + `extra` в `<into>/<YYYYmmdd-HHMMSS>/` и обнуляет `steps` / `woke`. **Перемещает, а не удаляет** |

Запись на диск идёт через атомарную подмену `tmp.replace(path)`; `OSError` молча проглатывается — неудачная запись
не должна уносить с собой запуск.

**`workspace` — это охранник**: SDK выводит `project_key` из пути workspace, после копирования каталога старый
`session_id` не находится, поэтому при несовпадении пути считаем, что записи нет.

Загружая происхождение, `Workflow.run` проверяет каждую запись через `runtime.has_session(sid)` — что она ещё есть
в базе, и использует только живые: файл происхождения может пережить `sessions.db`.

---

## Минимальные рабочие примеры {#示例}

Все пять запускаются как есть. Предпосылки: установлен `claude-agent-sdk`, доступен `ANTHROPIC_API_KEY` или
`ANTHROPIC_AUTH_TOKEN` (иначе `Runtime(...)` бросит `RuntimeError` прямо в конструкторе).

### Один агент, один шаг {#示例-单-agent}

Минимальный каркас: объявить `AgentSpec`, создать `Runtime`, `await rt.run(...)`, прочитать `StepResult`.

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

Параметры `Runtime` **все keyword-only**; у `rt.run()` `spec` и `prompt` позиционные, остальные keyword-only.
У `AgentSpec` по умолчанию `allowed_tools=["Read", "Glob", "Grep"]` и `delegate_only=False`,
поэтому `Runtime` автоматически навесит [`whitelist_guard`](#whitelist-guard), который перекроет
`Bash`/`Write`/`Edit`/`NotebookEdit`.

### Координатор + исполнитель {#示例-协调}

Не работающий руками [координатор](glossary.md#协调者) с одним работающим [исполнителем](glossary.md#执行者).
Это первый слой экономии контекста в flower.

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

    # workbench=True обязателен: delegate_guard висит в workbench_hooks,
    # без включённого workbench у Bash/Write координатора нет ни одного hook-заслона.
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

Первые два параметра `worker()` позиционные: `description` (по нему координатор выбирает исполнителя) и `prompt`
(его system prompt, к которому дальше автоматически приклеивается `WORKER_RULES`). У `coordinator()` первые три
позиционные: `name`, `instructions`, `workers`.

### Свой Workflow {#示例-workflow}

Два шага, второй вставляет результат первого в собственный prompt — дёшево, изолированно, без общей сессии.

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
        # Новая сессия: ест только то, что в prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Новая сессия + результат прошлого шага, вставленный в prompt (дёшево, защищает от загрязнения)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Хотите продолжить ту же сессию — пишите resume_from="造句"; нужна ветка — добавьте fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (когда reduce не задан)
    print(ctx["_sessions"])            # имя шага -> session_id
    print(ctx.get("_failed_at"))       # на каком шаге упало при on_fail="stop"


asyncio.run(main())
```

Первые три поля `Step` (`name` / `spec` / `prompt`) позиционные, `steps` у `Workflow` тоже.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` позиционный, оба колбэка keyword-only.
**Обратите внимание: `continuous=True` — значение по умолчанию**: при втором запуске с тем же `run_dir` и тем же
`workspace` шаги с `resume_from=None` тоже продолжат прошлую сессию.

### Добавить страж цели {#示例-目标}

Сначала пусть [судья](glossary.md#判定者) зафиксирует цель и список критериев, а затем рабочий шаг примет вердикт:
не прошло — идём заново с обратной связью, максимум три круга.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = полная автоматика: все вопросы сразу уходят в пустоту, никто не притворяется ждущим
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds — это **общее число кругов**: rounds=3 → retries=2 → максимум три круга работы
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # prompt у goal_step читает ctx["确认需求"] (значение brief_key по умолчанию).
        # Без clarify_step залейте это сами, иначе он увидит только "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: объект Goal
    print(ctx["_verdict"])     # VERDICT_KEY: последний Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: сколько кругов прошло
    print(ctx.get("_aborted")) # причина StepAbort (когда цель недостижима и никто не отвечает)


asyncio.run(main())
```

`with_goal` подменяет только `gate` / `on_reject` / `retries`, остальные поля переносятся как есть через
`dataclasses.replace`. Судья работает в **отдельной сессии**: внутри `gate` отдельно вызывается
`rt.run(judger, ..., step_name=f"{label}#{轮次}")`, `resume` всегда `None`.

### Заменить слой взаимодействия {#示例-交互层}

Чтобы заменить терминал на Web / TUI / HTTP, нужно поменять всего две вещи: функцию, рисующую `Event`,
и корутину, забирающую вопросы.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Отрисовать Event в вашем UI — это единственное, что нужно менять."""
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
    # kind == "ask", который не mail, обрабатывает answerer ниже (pull-режим)


async def answerer(ch: HumanChannel) -> None:
    """Pull-режим забора вопросов. При переезде на веб-бэкенд / HTTP-сервис менять надо только эту корутину."""
    while True:
        ask = await ch.next_ask()          # без timeout будет ждать бесконечно
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # или ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime использует workbench, который workflow уже создал сам — не собирайте второй
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push и pull — **выберите одно**: push — это конструктор `HumanChannel(on_event=...)`, pull — это `await channel.next_ask()`.
`Workflow.run` подключает свой выход только когда `channel.on_event is None`, так что переданный вами `on_event`
не будет перезаписан. `answer()` / `decline()` / `send()` / `interrupt()` **можно звать из другого потока**.

---

## Ловушки и типичные ошибки {#陷阱}

Порядок — по тому, на что натыкаешься, а не по модулям. У каждого пункта есть замеренный источник.

### Сборка {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = у главного потока нет ни одной стены.**
   `delegate_guard` ставится только при наличии workbench, а `whitelist_guard` пропускается из-за `delegate_only=True`.
   Используете координатора — включайте workbench. Подробнее в [Runtime](#runtime).
2. **Мест для workbench два, не перепутайте.** `Runtime(workbench=True)` кладёт его в `<run_dir>/workbench`;
   `Workbench(ws)` по умолчанию — в `<ws>/.flower`. Собирая `brief_path` вручную, пишите по второму варианту:
   **бриф уйдёт в каталог A, а внедряемый индекс просканирует каталог B — и никакой ошибки не будет**.
   Правильно так: workflow сам делает `Workbench(...).ensure()` и вешает на `Workflow.workbench`,
   а **тот же самый объект** передаётся в `Runtime(workbench=wb)`.
3. **`allowed_tools` — это не исключающий белый список, а перечень того, что не требует подтверждения.**
   Модель по-прежнему может вызвать инструмент не из него. «Отсутствие пишущих инструментов» у
   `clarify()` / `judge()` держится на hook [`whitelist_guard`](#whitelist-guard).
   А у `coordinator()` по умолчанию `permission_mode="acceptEdits"` — кто передаст это значение в
   `clarify()` / `judge()`, тот снимет защиту.
4. **`disallowed_tools` действует на уровне сессии** и заодно запретит одноимённые инструменты у subagent.
5. **Индекс workbench не попадает в subagent.** «Длинный вывод писать в `artifacts/`» координатор обязан
   пересказать в задании — это единственный канал.
6. **`Runtime(...)` без учётных данных бросает `RuntimeError` уже на этапе конструирования**, а не при `run()`.
7. **`Runtime.run_id` должен быть уникален для каждого экземпляра.** `manifest.json` дедуплицируется по полю `run`,
   и при столкновении двух id тот, кто пишет позже, удалит чужие строки, приняв их за «свои прошлые».

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` — значение по умолчанию**, `resume_from=None` не означает «совсем новая сессия».
   Хотите каждый раз начинать заново — явно ставьте `continuous=False`. **Смена имени шага рвёт происхождение.**
9. **`with_goal(rounds=N)` — это общее число кругов, а не число дополнительных**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` не пишет `ctx[step.name]`** — у нижестоящего `lambda ctx: ctx["某步"]` будет `KeyError`.
    Чтобы идти дальше с неполным результатом, используйте `on_fail="continue"`.
11. **`resume_from`, указывающий на невыполненный / упавший шаг, бросает `ValueError`**, а не молча пропускается.
12. **`Step.reduce` обязан быть синхронной функцией; `gate` / `when` / `on_reject` могут быть async.**
13. **`fork=True` без `resume` молча не работает.** `Workflow` никогда не передаёт `resume_at`,
    откат по сообщениям возможен только через прямой вызов `Runtime.run`.
14. **Когда вы сами управляете `Runtime`, `on_session` нужно снять до gate**, иначе сессия судьи запишется
    в происхождение рабочего шага. `Workflow` гарантирует это через `try/finally`.
15. **`step_name` определяет ключ в manifest и в происхождении.** `Workflow` добавляет суффиксы `#retryN` / `#roundN`,
    судья добавляет `#轮次` — **имена с суффиксом не попадают в межпроцессное происхождение**, и это один из
    способов реализовать «судья всегда в новой сессии».

### Роли {#陷阱-角色}

16. **`clarify(max_turns=<маленькое число>)` превращает «вопросы без ограничения» в пустой звук** — каждый вопрос это один круг.
17. **У `goal_step()` нет параметра `can_run`**, передать `can_run=True` можно только через `**spec_kw`.
    Без этого судья, ставящий цель, не получит `Bash`, и пункт `JUDGE_RULES` «сначала разберись, в какой ты среде»
    выполнить невозможно.
18. **`judge(can_run=True)` даёт судье возможность менять workspace** — `whitelist_guard` выводится из `allowed_tools`,
    и если дан `Bash`, то `Bash` пропускается (`Write`/`Edit` по-прежнему блокируются, но сам `Bash` умеет писать файлы).
    Нужна абсолютная нейтральность — не включайте.
19. **`worker(isolate=True)` требует, чтобы workspace был git-репозиторием**, иначе инструмент `Agent` сразу вернёт
    `"not in a git repository"` и молчаливой деградации не будет. Кроме того, метка изоляции — это Python-атрибут,
    и **`dataclasses.replace()` над `AgentDefinition` её потеряет**.
20. **При прямом конструировании `AgentDefinition` параметры в camelCase**: `maxTurns`, `permissionMode`.
    `worker()` уже сделал это преобразование за вас.

### Handoff и контекст {#陷阱-换代}

21. **Когда handoff включён, auto-compact принудительно отключается, подстраховки нет.** Поэтому у шага записи
    передаточного документа обязан быть путь деградации. Хотите сохранить auto-compact — задайте `AgentSpec.compact` явно.
22. **Слишком маленький `HandoffPolicy.window` приводит к бесконечным handoff и сжиганию денег.** Единственный
    тормоз — `max_generations=8`. С другой стороны, **`default_window()` при обеих незаданных переменных окружения
    тоже возвращает `1_000_000`** — завышенная оценка подхватывается `is_overflow()` (превращаясь в один деградированный
    handoff), это не жёсткая ошибка, но передача того поколения будет деградированной.
23. **Без workbench передаточный документ не пишется на диск.** Он всё равно уходит преемнику через prompt,
    но человек потом его не найдёт.

### Хранилище {#陷阱-存储}

24. **`Runtime(trim=False)` (по умолчанию) не означает «ничего не чистится».** store всегда `PruningSessionStore`,
    `trim=False` отключает только обрезку больших результатов; **снятие обрывков разрыва связи, снятие отклонённых
    вызовов, нейтрализация остатков прерывания и истечение срока актуальности выполняются по-прежнему.**
25. **Два каталога spill — это не одно и то же**: `spill_guard` кладёт в `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` — в `<workspace>/.flower/spill/` (обязан быть внутри workspace).
26. **Четвёртый позиционный параметр `PruningSessionStore.__init__` — это `prune`, а не `ephemeral`**,
    в отличие от родительского класса. Передача по позиции молча съедет.

### Документы и взаимодействие {#陷阱-文书}

27. **Если `Verdict` не смог разобрать заключение, то `state=""`, `ok=False`, и это ни в коем случае нельзя
    считать достижением цели.** Кроме того, «无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» — всё это
    сводится к `unreachable` и запускает ветку «остановиться и спросить человека», а не «ещё один круг».
28. **`Brief.parse` при незакрытом ограждении кода отбрасывает всё содержимое после него** — если вывод модели
    обрезан, следующие разделы вообще не распарсятся, `complete()` вернёт `False`, и gate отправит на новый круг.
29. **`Brief.load` считает `"(未填)"` пустым.** Если при ручном редактировании брифа вы скопировали текст-заглушку,
    этот раздел всё ещё считается отсутствующим.
30. **Три «0 / None» у `HumanChannel` означают разное**: `max_asks=None` — без ограничения, `max_asks=0` — спрашивать нельзя;
    `timeout_s=None` — ждать вечно, `timeout_s<=0` — таймаут мгновенно; `remaining` при `max_asks=None` возвращает **`-1`**.
31. **`Event("ask")` несёт и вопрос, и сказанное человеком по своей инициативе**, у второго `payload["kind"] == "mail"`.
    UI должен сначала это проверить.
32. **`Workflow.run` подключает свой выход только когда `channel.on_event is None`** —
    если вы сконструировали `HumanChannel(on_event=...)` сами, события-вопросы не пойдут заодно в выход `on_event` у workflow.
