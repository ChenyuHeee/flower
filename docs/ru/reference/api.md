# Python API

Эта страница исчерпывающе разбирает **62 публичных символа** верхнего уровня `__all__` в `flower`:
сигнатуры, параметры, значения по умолчанию, семантику, публичные атрибуты и методы. Прочитав её,
не придётся лезть в исходники за параметрами.

Организация — по **тому, что вас волнует**, а не по файлам модулей: хотите знать, «как не дать
[координатору](glossary.md#协调者) взяться за дело самому» — идите в [слой hook](#hook); хотите знать,
«как результат прошлого шага попадает в следующий» — идите в [workflow](#流程).
Терминология — строго по [глоссарию](glossary.md).

Версия `0.1.0`, зависимость `claude-agent-sdk>=0.2.152`. Все сигнатуры дословно соответствуют исходникам.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # один импорт верхнего уровня
```

## Что есть на этой странице {#索引}

| Что интересует | Символы |
|---|---|
| [Запустить агента](#运行时) | `Runtime` `StepResult` |
| [Связать несколько шагов](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Собрать роль](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Написать определение агента вручную](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Структурированные документы](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Перехватить инструмент, обрезать результат, развести изоляцию](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Рабочий каталог для spill](#工作台) | `Workbench` |
| [Как и что хранит хранилище сессий](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Что делать при обрыве сети](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Заменить UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Подхватить прошлый запуск между процессами](#血缘) | `Lineage` |

## Шесть значений по умолчанию, которые кусаются {#危险默认值}

Эти шесть пунктов — не мелочи по краям, а шесть самых частых аварий. Каждый разобран полностью
в соответствующем разделе.

| Значение по умолчанию | Последствие | Подробнее |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | На `Bash`/`Write`/`Edit` главного потока **нет ни одного hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Принудительно ставит spec `CompactPolicy(mode="no_summary")`, то есть `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Шаг с `resume_from=None` всё равно подхватит прошлую сессию между процессами | [Workflow](#workflow) |
| `build_options(fork=True)` без `resume` | Молча не работает, ошибки нет | [build_options](#build-options) |
| `clarify(max_turns=<маленькое число>)` | Превращает «спрашивать можно сколько угодно» в пустой звук — каждый вопрос это один раунд | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Уровень сессии, запрещает и для subagent тоже | [AgentSpec](#agentspec) |

---

## Рантайм {#运行时}

Исходники: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` — ядро исполнения. Он держит рабочую область, [хранилище сессий](glossary.md#会话存储),
[workbench](glossary.md#工作台), политику [устойчивости](glossary.md#韧性) и политику
[handoff](glossary.md#换代), а наружу отдаёт один-единственный глагол: `run` один шаг.
Повторы, продолжение после прерывания, handoff при переполнении контекста — всё это происходит
внутри этого одного вызова.

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

Все параметры конструктора **только keyword-only** (`*` в самом начале), `workspace` обязателен.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `str \| Path` | обязателен | `cwd` агента. При конструировании делается resolve и `mkdir(parents=True, exist_ok=True)`. `project_key` в SDK выводится из него — стоит скопировать каталог в другое место, и старый `session_id` уже не найти |
| `run_dir` | `str \| Path` | `"runs"` | Здесь лежат `sessions.db`, `manifest.json`, `lineage.json`, а также workbench по умолчанию при `workbench=True`. Тоже resolve и mkdir |
| `portable` | `bool` | `True` | Пробрасывается в `build_options(portable=)`, то есть `setting_sources=[]`: не читается ни `~/.claude/` хост-машины, ни `.claude/` проекта. См. [переносимость](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Экземпляр используется как есть; `bool` превращается в `TrimPolicy(enabled=bool(trim))`. **Выключение лишь отменяет усечение больших результатов, отсечение выполняется по-прежнему** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | То же правило приведения. Работает в паре с `coordinator(glance=True)` — раз вы пускаете главный поток запускать `git status`, надо гарантировать, что этот результат протухнет |
| `keep_denials` | `int` | `1` | Передаётся в `PrunePolicy(keep_denials=)`. Сохраняет последние N отклонённых вызовов инструментов, более ранние снимаются вместе с вызовом и результатом |
| `workbench` | `Workbench \| bool` | `False` | Экземпляр используется как есть; при `True` создаётся `Workbench(workspace, home=run_dir / "workbench")` (**по умолчанию вне рабочей области**). Сразу после этого вызывается `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | С какого количества символов результат инструмента уходит в [spill](glossary.md#落盘). `None` или `0` = `spill_guard` не ставится |
| `resilience` | `Resilience \| bool` | `True` | То же правило приведения |
| `handoff` | `HandoffPolicy \| bool` | `True` | То же правило приведения |

**Хранилище сессий зашито жёстко**: всегда
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Параметры конструктора **не дают** входа для смены бэкенда — если нужна замена, конструируйте
`AgentSpec` + `build_options(session_store=...)` сами либо перезапишите `rt.store` после конструирования.

Последние два шага конструирования — `load_dotenv()` и `check_credentials()`,
**второй при ошибке делает `raise RuntimeError`**. Без учётных данных всё падает уже на стадии
конструирования, а не при `run()`.

!!! warning "`workbench=False` + `coordinator()` = у главного потока нет ни одной стены"
    `delegate_guard` ставится только внутри `workbench_hooks`, а `workbench_hooks` вызывается только
    при `self.workbench is not None`; `whitelist_guard` же пропускается из-за `if not spec.delegate_only`.
    А `coordinator()` всегда ставит `delegate_only=True` и по умолчанию `glance=True` для `Bash`.

    **Вывод: у координатора в связке с `Runtime(workbench=False)` его `Bash`/`Write`/`Edit` не перехватывает ни один hook.**
    Используете `coordinator()` — включайте workbench: `Runtime(..., workbench=True)` или передайте
    экземпляр `Workbench`.

!!! warning "`handoff=True` (по умолчанию) принудительно выключает auto-compact"
    В `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    что в дочернем процессе означает `DISABLE_AUTO_COMPACT=1`. Причина: когда оба механизма включены
    одновременно, невозможно сказать, кто именно уронил контекст.

    **Цена: у шага, который пишет handoff-документ, обязан быть путь деградации** (`handoff.degraded`),
    потому что compact больше не подстрахует. Хотите сохранить auto-compact — задайте `AgentSpec.compact`
    явно (если spec задал его сам, это уважается и не перезаписывается).

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
| `results` | `list[StepResult]` | Каждый шаг, выполненный в этом процессе, в порядке добавления |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Обязан быть уникален для каждого экземпляра** — `manifest.json` дедуплицируется по полю `run`, и при совпадении двух id тот, кто пишет позже, примет чужую строку за собственную прошлую запись и удалит её |
| `on_session` | `Callable[[str], None] \| None` | Колбэк **немедленно** при получении нового `session_id`, по умолчанию `None`. **Должен накрывать только вызов `runtime.run`** — [судья](glossary.md#判定者) использует тот же `Runtime`, и если колбэк останется висеть на время gate, сессия судьи попадёт в [lineage](glossary.md#血缘) рабочего шага |

Константы класса: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (кусок текста, приписываемый после реплики человека при продолжении после прерывания,
поясняющий, что «вызовы инструментов, находившиеся в полёте, вернули interrupted — это нормальный
побочный эффект прерывания, а не сбой окружения»).

#### Публичные методы {#runtime-方法}

| Метод | Сигнатура | Описание |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Выполнить шаг. См. ниже |
| `interrupt` | `(message: str = "") -> None` | Запросить прерывание текущего раунда. **Можно звать из любого потока**. Кооперативно: чисто разрывает на **границе сообщения**, без жёсткой отмены. Пустая строка = прервать молча |
| `rescue` | `() -> None` | Перед жёстким убийством дописать учёт настолько полно, насколько возможно; вызывается обработчиками `SIGHUP`/`SIGTERM`. Шаг, находившийся в полёте, тоже пишется в manifest с `error="killed-by-signal"`. Только небольшая синхронная запись на диск |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | В `str(workspace.resolve())` все `/`, `_`, `.` заменены на `-`. **SDK выводит его из cwd, вызывающая сторона задать его не может** |
| `has_session` | `(session_id: str) -> bool` | Находится ли ещё этот id в **данной рабочей области**. Синхронно, payload не читается |
| `context_of` | `(session_id: str) -> int` | Размер контекста в последнем раунде указанной сессии, делегируется `store.last_context` |
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
| `spec` | `AgentSpec` | обязателен, позиционный | Декларация агента, который будет запущен |
| `prompt` | `str` | обязателен, позиционный | Реплика этого раунда |
| `step_name` | `str \| None` | `None` | Ключ, попадающий в `StepResult.step`, manifest и lineage. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Продолжить эту сессию по `session_id` |
| `fork` | `bool` | `False` | Ответвить новую сессию, не пачкая исходную. **Действует, только если `resume` истинен** |
| `resume_at` | `str \| None` | `None` | Продолжить с определённого сообщения (откат). Тоже **действует, только если `resume` истинен** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Выход для событий, см. [`Event`](#event) |

В начале каждого шага уровень контекста обнуляется (`self._ctx, self._warned = 0, False`).
Дальше идёт цикл с четырьмя выходами:

1. **Успех** → выйти.
2. **Человек прервал** (`result.error == INTERRUPTED`) → **не ограничено `max_attempts`**, сети не ждём.
   С репликой человека делается `resume` той же сессии, `attempt -= 1` (прерывание не считается
   неудачной попыткой), prompt = реплика человека + `INTERRUPT_NOTE`.
   **Если `session_id` не получен, остаётся только остановиться.**
3. **Контекст переполнен** (`result.error == HANDOFF_DUE`, либо `handoff.enabled`, `session_id` получен и
   сработал `is_overflow(...)`) → **тоже не ограничено `max_attempts`**. Сначала проверяется
   `len(result.retired) >= handoff.max_generations`; если превышено, error заменяется диагностической
   фразой и цикл прерывается; иначе пишется [handoff-документ](glossary.md#交接书) → `resume=None, fork=False`
   (**совершенно новая сессия**) → prompt заменяется на `h.prompt_block()` → уровень контекста
   обнуляется → `attempt -= 1`.
4. **Повторяемый сбой** → при `not resilience.enabled or attempt >= max_attempts` выходим;
   если `classify(error)` решает, что повторять не следует, тоже выходим; иначе отправляется
   `Event("retry")`, `wait_online()` ждёт сеть, затем `sleep(delay_for(attempt))`;
   **если `session_id` уже был получен, делается `resume`** (prompt заменяется на
   `resilience.resume_prompt`), а `result.resumed` ставится в `True`.

Завершение: записывается `ended_at`, результат добавляется в `self.results`, пишется `manifest.json`.

`manifest.json` имеет семантику **добавления**: при каждой записи диск перечитывается, дедупликация идёт
по полю `run` (своя строка обновляется, чужие остаются), поэтому запускать два flower параллельно
в одном `run_dir` безопасно — при условии, что `run_id` не совпадут.

**Три точки наблюдения за handoff** (все — `Event("handoff")`, различаются по `payload["phase"]`):
`near` (приближение к `warn_at`, отправляется по одному разу на поколение), `writing`
(handoff-документ пишется прямо сейчас, это занимает с десяток секунд),
`done` (payload содержит `degraded` / `path` / `sections`). Раунд, в котором пишется handoff-документ,
исполняется с `replace(spec, max_budget_usd=None)` — документ обязан быть написан, он не должен
упереться в бюджет; и `on_event=None`, этот раунд в UI не транслируется.

Handoff-документ пишется в `<workbench.notes>/交接-<步骤名>.md`; **без workbench запись на диск не происходит**,
документ всё равно передаётся преемнику через prompt, просто потом его не найти.
Старый handoff-документ перемещается в `notes/archive/交接/<名>-<时间戳>.md`.

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

Полный учёт по завершённому шагу.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `step` | `str` | обязательно | Имя шага (`step_name` или `spec.name`) |
| `session_id` | `str \| None` | `None` | **Всегда та сессия, что приняла смену последней** — сожжённые по ходу handoff лежат в `retired` |
| `ok` | `bool` | `False` | Удался ли шаг |
| `cost_usd` | `float` | `0.0` | Доллары. При повторах и handoff **накапливается** |
| `num_turns` | `int` | `0` | Число раундов, тоже накапливается |
| `text` | `str` | `""` | **Только основной текст главного потока**. Реплики subagent остаются в его собственном transcript, выданное ему техзадание имеет `kind="prompt"` — ни то, ни другое сюда не попадает |
| `error` | `str \| None` | `None` | Причина неудачи. Особые значения см. `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix-таймстемпы |
| `attempts` | `int` | `1` | Фактическое число попыток. Прерывания и handoff **не учитываются** |
| `errors` | `list[str]` | `[]` | Собранные синтетические сообщения об ошибках API, **в `text` не попадают** |
| `resumed` | `bool` | `False` | Был ли по ходу resume |
| `retired` | `list[str]` | `[]` | `session_id`, сожжённые при handoff на этом шаге, по порядку |
| `context` | `int` | `0` | Размер контекста, который главный поток фактически видел в последнем раунде, то есть критерий для handoff |

| Атрибут | Тип | Описание |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, у незавершённого шага `0.0` |

---

## Workflow {#流程}

Исходники: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

[Workflow](glossary.md#流程) — это набор [шагов](glossary.md#步骤), выстроенных по порядку, плюс правила
передачи состояния между шагами и условия досрочного выхода. **Фреймворк не поставляет готовых workflow,
workflow пишете вы** — `starter_flow` это всего лишь рабочий образец.

Псевдоним типа `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, он есть в `flower.workflow.__all__`,
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
Первые три поля позиционные, `Step("取词", terse, "读 seed.txt …")` — законная запись.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязателен | Имя шага. **Ключ, стабильный между процессами** — попадает в `ctx[name]`, `ctx["_results"]`, manifest и lineage. Переименовал = порвал lineage |
| `spec` | `AgentSpec` | обязателен | Какой agent запускать |
| `prompt` | `str \| Callable[[Ctx], str]` | обязателен | Что сказать. Может быть замыканием, которое считает по `ctx` на месте |
| `resume_from` | `str \| None` | `None` | Session какого шага продолжать. Если у указанного шага session не появилось — **бросается `ValueError`**, а не тихий пропуск |
| `fork` | `bool` | `False` | Форк поверх `resume_from`. **Без `resume_from` не действует** |
| `retries` | `int` | `0` | Сколько раз пробовать ещё, если gate не пройден. `retries=0` = один круг |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Решает, засчитан ли этот раз. **Может быть async**. Возврат `False` считается провалом. **Вызывается ровно один раз на попытку** — у него могут быть побочные эффекты (например, запись brief на диск), повторно дёргать его нельзя |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, см. ниже |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Возврат `False` — **шаг пропускается целиком**: result не создаётся, в `ctx["_results"]` ничего не попадает. **Может быть async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Что сказать **на следующем круге**, если gate не пройден. **Может быть async**. Если задан — семантика повтора меняется, см. ниже |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt, используемый при continuity (а не при старте с нуля) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Решает, что кладётся в `ctx[name]`. По умолчанию — исходный `result.text`. **Обязан быть синхронной функцией** |

| Метод | Сигнатура | Описание |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Если `resuming` и есть `resume_prompt` — берётся он, иначе `prompt`; если это вызываемый объект, ему передаётся `ctx` |

**Три способа подключить session** (внутри одного run):

| Запись | Эффект |
|---|---|
| `resume_from=None` (по умолчанию) | Новая session, только тот контекст, что передан в prompt. Дёшево, изолированно. **Но при `Workflow(continuous=True)` подтянется session одноимённого шага из межпроцессного lineage** |
| `resume_from="имя предыдущего шага"` | Продолжение той же session, полный контекст. Дорого, связно |
| `resume_from="имя предыдущего шага", fork=True` | Форк, исходная session не загрязняется. Для перепроверки / параллельных вариантов |

**`on_reject` меняет семантику повтора**:

- Не задан → следующая попытка **начинается с нуля** (тот же prompt, тот же `resume_from`).
- Задан → следующая попытка **продолжает ту самую session, которую только что отклонили**, prompt заменяется на его возвращаемое значение, `fork` принудительно `False`.
- Вернул пустую строку → возврата нет, деградирует до запуска с нуля.
- `result.session_id` равен `None` → тоже деградирует до запуска с нуля.

**Три значения `on_fail`**:

| Значение | Поведение |
|---|---|
| `"stop"` (по умолчанию) | Пишет `ctx["_failed_at"] = name`, **прерывает весь workflow** |
| `"skip"` | Переход к следующему шагу, **`ctx[name]` не пишется** — ниже по потоку `lambda ctx: ctx["某步"]` даст `KeyError` |
| `"continue"` | `ctx[name] = result.text`, идём дальше с ущербным результатом |

Прошёл шаг или нет, `ctx["_results"][name] = result` пишется всегда; если `result.session_id` непустой,
он ещё пишется в `ctx["_sessions"]` и делается `lineage.remember(...)`.

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

Выполняет цепочку `Step` по порядку и возвращает итоговый `ctx`. `steps` — позиционный параметр,
`Workflow([...])` законно.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `steps` | `list[Step]` | обязателен | Выполняются по порядку |
| `name` | `str` | `"workflow"` | Имя workflow |
| `context` | `Ctx` | `{}` | Начальный словарь контекста. **При втором запуске того же `Workflow` ctx — тот же самый dict** |
| `channel` | `HumanChannel \| None` | `None` | Сюда вешается канал, если нужно остановиться и спросить человека. `run()` автоматически подключит его `on_event` к тому же выходу, **но только если `channel.on_event is None`**; драйвер по этому же полю понимает, кому отвечать |
| `workbench` | `Workbench \| None` | `None` | Workbench, заданный workflow, чтобы драйвер мог его найти |
| `continuous` | `bool` | `True` | Один и тот же путь = один и тот же разговор. Реализуется через [`Lineage`](#lineage) |

| Параметры `run()` | Тип | По умолчанию | Описание |
|---|---|---|---|
| `runtime` | `Runtime` | обязателен, позиционный | На каком runtime выполнять |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Выход событий, пробрасывается в каждый `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Колбэк после каждого шага |

!!! warning "`continuous=True` — значение по умолчанию, `resume_from=None` не означает новую session"
    При включённой continuity `run()` сначала делает `Lineage.open(run_dir, workspace)`, затем для каждой
    записи проверяет через `runtime.has_session(sid)`, жива ли она ещё в хранилище, и только живые заливает
    в `ctx["_sessions"]`. В итоге **шаг с `resume_from=None` тоже продолжит говорить в прошлой session** —
    даже если процесс убили или машину перезагрузили.

    Чтобы каждый раз была новая session, пишите явно `Workflow(..., continuous=False)`.
    И ещё: **имя шага — ключ, стабильный между процессами; переименовали шаг — порвали lineage.**

**Приватные ключи**, которые `run()` пишет в ctx (все начинаются с `_`, с именами шагов не столкнутся):

| Ключ | Содержимое |
|---|---|
| `_runtime` | Переданный `Runtime`. **Через него gate отправляет agent** |
| `_on_event` | Выход событий. Agent внутри gate тоже должен доставать до UI, иначе экран будет пустым |
| `_sessions` | `dict[имя шага, session_id]`, берётся через `setdefault` |
| `_results` | `dict[имя шага, StepResult]` |
| `_lineage` | Объект `Lineage`. Есть только при `continuous=True` и когда у runtime есть `run_dir` + `workspace` |
| `_woke` | Возврат `lineage.bump()`, номер текущего пробуждения |
| `_aborted` | Сообщение `StepAbort` |
| `_failed_at` | Имя провалившегося шага при `on_fail="stop"` |

Payload у `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Метки повторов**: нулевая попытка использует `step.name`; далее при наличии `on_reject` —
`f"{name}#round{attempt+1}"`, иначе `f"{name}#retry{attempt}"`. По manifest сразу видно, как этот шаг дошёл до конца.
**Имена с суффиксом не попадают в межпроцессный lineage** — `Lineage.remember` использует исходное имя.

`runtime.on_session` накрывает только строку `runtime.run`, а `try/finally` гарантирует, что до gate он снят.
`prompt_cur` / `resume_cur` / `fork_cur` — локальные переменные, обратно в `step` не пишутся: один и тот же
объект `Step` может быть запущен второй раз.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Брошено из `gate` = **немедленно стоп, больше не пробовать**. Отличие от «вернуть `False`»: `False` — это
«в этот раз не вышло, давай ещё круг»; `StepAbort` — это «ещё круг не поможет».

После броска: `ctx["_aborted"] = str(exc)`, `passed = False`, **выход из цикла повторов (оставшиеся `retries` не тратятся)**,
дальше обычная обработка провала через `on_fail` (по умолчанию `"stop"`).

`with_goal` бросает его в двух местах: когда не удалось получить `ctx["_runtime"]`, и когда verdict —
`unreachable`, а человек не ответил.

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

Создаёт `Step`, выполняющий [clarify](glossary.md#前置确认): выяснить требования → разобрать в [`Brief`](#brief) →
если все четыре раздела на месте, заморозить и записать на диск.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `channel` | `HumanChannel` | обязателен, позиционный | Канал вопросов |
| `brief_path` | `str \| Path` | обязателен | Куда ложится [brief](glossary.md#需求确认书). **Обязан лежать в том workbench, индекс которого реально инжектится** |
| `prompt` | `str \| Callable[[Ctx], str]` | обязателен | Исходная просьба человека |
| `name` | `str` | `"确认需求"` | Имя шага, оно же ключ в `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Если не задан, используется `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Дополнительные инструкции [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = спрашивать заново каждый раз, независимо от наличия brief |
| `on_fail` | `str` | `"stop"` | Как у `Step.on_fail` |
| `retries` | `int` | `0` | Сколько раз переспросить, если четыре раздела не собрались |
| `**spec_kw` | | | Пробрасывается напрямую в [`clarify()`](#clarify-role), поэтому можно писать `can_read=False`, `max_budget_usd=...` |

Поля в получившемся `Step` заполняются так:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: при `always_ask=True` → всегда `True`; иначе, если `Brief.load(brief_path)` полон, он заливается в ctx,
  **а затем возвращается `False` (пропуск)** — заливать нужно даже при пропуске, иначе ниже по потоку требований не будет.
- `gate`: `Brief.parse(result.text)`, неполный → пишет `ctx[MISSING_KEY]` и возвращает `False`;
  полный → `b.write(brief_path)` замораживает, заливает в ctx, возвращает `True`.
- `reduce`: возвращает `ctx[BRIEF_KEY].prompt_block()`, **а не исходный текст модели** — в исходнике может быть намешано лишнее.
- `resume_from` **остаётся по умолчанию `None`**: следующий шаг — новая session, получает только brief, но не тот диалог.
  Вопросы и ответы clarify **никогда не попадали** в контекст coordinator, их не вырезали после попадания.

Три места, куда заливается ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Константа | Значение | Описание |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` — объект `Brief`; `ctx[step.name]` — его `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Каких разделов не хватило при провале clarify (имена разделов по-китайски), для показа в UI |
| `CLARIFY_RESUME` | фрагмент подсказки на китайском | «Продолжай то незаконченное уточнение требований — **не начинай заново**…». Без этой фразы continuity отправит исходную просьбу как новую задачу, и clarifier может переспросить уже спрошенное |

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

Создаёт `Step`, **задающий цель**: [judge](glossary.md#判定者) читает brief, пишет цель + список критериев,
результат разбирается в [`Goal`](#goal), замораживается и пишется на диск. По форме то же самое, что `clarify_step`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `channel` | `HumanChannel` | обязателен, позиционный | Канал вопросов |
| `goal_path` | `str \| Path` | обязателен | Куда ложится файл цели |
| `brief_key` | `str` | `"确认需求"` | Из `ctx[brief_key]` берётся текст brief и вставляется в prompt. **Если не нашлось — будет `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Имя шага |
| `spec` | `AgentSpec \| None` | `None` | Если не задан, используется `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Дополнительные инструкции |
| `always_set` | `bool` | `False` | `True` = пересчитывать список заново, независимо от наличия файла цели |
| `on_fail` | `str` | `"stop"` | Как выше |
| `retries` | `int` | `0` | Как выше |
| `**spec_kw` | | | Пробрасывается в [`judge()`](#judge-role) |

**Формального параметра `can_run` нет** — чтобы judge на этапе постановки цели мог выполнять команды,
`can_run=True` передаётся только через `**spec_kw`.
Без этого у него не будет `Bash`, и пункт «сначала разберись, в какой ты среде» из `JUDGE_RULES` выполнить нельзя.

`gate`, помимо разбора и заморозки, делает ещё одну вещь: если в цели есть пункты `[此环境无法验证:…]`,
он **тут же** через `ctx["_on_event"]` шлёт `Event("task", payload={"unverifiable", "total", "path"})` как предупреждение —
судьба этих пунктов решается именно в момент постановки цели, а к моменту verdict деньги за целый круг работы уже потрачены.

**`resume_prompt` не задан** — при постановке цели brief и должен отправляться целиком заново.

| Константа | Значение | Описание |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` — объект `Goal`; `ctx[step.name]` — markdown |
| `VERDICT_KEY` | `"_verdict"` | Последний [`Verdict`](#verdict), для UI |
| `ROUND_KEY` | `"_goal_rounds"` | Сколько кругов отработал verdict |

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

Надевает на готовый `Step` [goal guard](glossary.md#目标看守): после каждого круга judge независимо выносит verdict,
и если цель не достигнута — возвращает на доработку.

Результат — `replace(step, retries=max(0, rounds - 1), gate=<новый gate>, on_reject=<новый on_reject>)`:
используется `dataclasses.replace`, а не пересборка по полям, потому что при пересборке однажды потеряли
`resume_prompt`, **причём без всякой ошибки** — просто при continuity весь brief отправлялся заново.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `step` | `Step` | обязателен, позиционный | Шаг, который охраняется |
| `channel` | `HumanChannel` | обязателен, позиционный | Канал обращения к человеку, когда судить невозможно |
| `goal_path` | `str \| Path` | обязателен | Файл цели, читается отсюда, если `ctx[GOAL_KEY]` неполон |
| `spec` | `AgentSpec \| None` | `None` | Если не задан, используется `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Общее число кругов, а не дополнительных**: `rounds=3` → `retries=2` → максимум три круга работы. `rounds=1` = один круг, один verdict, не прошёл — провал |
| `instructions` | `str` | `""` | Дополнительные инструкции judge |
| `can_run` | `bool` | `False` | Может ли judge выполнять `Bash` |
| `name` | `str \| None` | `None` | Имя judge, по умолчанию `f"{step.name}·判定"` |
| `**spec_kw` | | | Пробрасывается в `judge()` |

`gate` — **async**, порядок такой:

1. `ctx["_runtime"]` отсутствует → **бросить `StepAbort`** («拿不到 Runtime,无法判定目标»). **Не притворяться, что прошло.**
2. `ctx[ROUND_KEY] += 1`.
3. Взять цель: сначала полный `Goal` из `ctx[GOAL_KEY]`, иначе `Goal.load(goal_path)`, иначе пустой `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Judge — это отдельный вызов `Runtime.run`, `resume` всегда `None`, то есть всегда новая session**; в `step_name` есть номер круга,
   поэтому в межпроцессный lineage он не попадает.
5. `Verdict.parse(vr.text)` пишется в `ctx[VERDICT_KEY]`.
6. `v.achieved` → вернуть `True`.
7. Не `unreachable` (включая размытые случаи с `v.ok=False`) → при размытости дописать дефолтный reason, вернуть `False`.
   **Размытость всегда считается недостижением** — нельзя, чтобы фраза «вроде бы годится» закрыла работу.
8. `unreachable` → `await channel.ask(...)`, спросить человека, три варианта:
   - Никто не ответил (`a.state != "answered"`) → **бросить `StepAbort`**. Крутиться вхолостую дальше — самый дорогой выбор.
   - «接受这个结果,就这样往下走» → вернуть `True`.
   - «修改目标» → спросить новую цель, `g.amend(...).write(goal_path)`, обновить `ctx[GOAL_KEY]`, вернуть `False`.
   - Остальное (включая свободный ответ, набранный человеком) → считается «ты ошибся в оценке», слова человека записываются в `v.reason`, вернуть `False`.

`on_reject` — **синхронный**: возвращает `ctx[VERDICT_KEY].feedback()`, а если `Verdict` нет — `""`
(деградирует до запуска с нуля).

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

Собирает готовый к запуску трёхшаговый workflow: **уточнение требований → постановка цели → работа** (с goal guard).
Именно им пользуется команда `flower`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `ask` | `str` | обязателен, позиционный | Одна фраза-просьба. **При пробуждении это не новая задача, а «ещё одна сказанная фраза»** |
| `workspace` | `str \| Path` | `"."` | Рабочая область |
| `run_dir` | `str \| Path` | `"runs"` | Каталог run |
| `new` | `bool` | `False` | `True` = заархивировать lineage + brief + цель (все три сразу) и начать с нуля |
| `isolate` | `bool` | `False` | Открыть worker'у worktree-[изоляцию](glossary.md#隔离). Workbench вместе с этим переезжает в `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Вернуть Workflow только с шагом уточнения |
| `goal` | `bool` | `True` | Ставить ли [goal guard](glossary.md#目标看守). `False` = шаг работы отработал, и на этом всё |
| `rounds` | `int` | `3` | Пробрасывается в `with_goal(rounds=)`, общее число кругов |
| `judge_can_run` | `bool` | `False` | Пробрасывается в `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Пробрасывается в `HumanChannel`, `None` = без ограничения |
| `timeout_s` | `float \| None` | `1800.0` | Пробрасывается в `HumanChannel`. `0` = полностью автоматически, все вопросы уходят в пустоту |
| `instructions` | `str` | `""` | Дополнительные инструкции clarifier |
| `worker_prompt` | `str` | см. сигнатуру | System prompt worker'а |
| `brief_name` | `str` | `"需求.md"` | Имя файла brief, ложится в `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Имя файла цели, туда же |
| `log_name` | `str` | `"问答记录.md"` | Имя файла с записью вопросов и ответов, туда же |

Фиксированная сборка:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Ветвления поведения:

- `isolate=True`, а workspace не является git-репозиторием → **бросается `ValueError`**, чтобы не выяснять это
  из ошибки инструмента `Agent` (тогда деньги уже потрачены).
- **Определение пробуждения**: если `Brief.load(brief_path)` существует и `complete()`, это пробуждение.
  Если это не пробуждение и `ask` пуст → **бросается `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- При пробуждении сказанная фраза попадает сразу в **три места**, и без любого из них она тихо перестанет работать:
  дописывается в brief (`ch.amend(said, label="唤醒时追加")`, если уже есть в файле — повторно не пишется);
  заставляет `goal_step(always_set=True)` пересчитать список (без пересчёта judge будет читать старую цель);
  отправляется напрямую coordinator'у (в его контексте лежит **старая** цель, и без этого он будет работать
  по старым критериям, а судить его будут по новым).

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

**Разведка только на чтение до старта, не пишет ни байта.** Нужна, чтобы до реального запуска сказать человеку:
«это продолжение прошлого раза» или «это старт с нуля».

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Рабочая область, позиционный параметр |
| `run_dir` | `str \| Path` | `"runs"` | Каталог run |
| `isolate` | `bool` | `False` | Определяет расположение workbench, должен совпадать со значением, переданным в `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Имя файла brief |
| `goal_name` | `str` | `"目标.md"` | Имя файла цели |

Возвращаемый dict:

| Ключ | Тип | Описание |
|---|---|---|
| `waking` | `bool` | Brief существует и все четыре раздела на месте |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Число пунктов в списке цели, при отсутствии цели `0` |
| `woke` | `int` | `Lineage.woke`, сколько раз уже просыпались |
| `steps` | `dict` | Копия `Lineage.steps`, имя шага → `session_id` |

Расположение workbench **определяется ровно один раз — здесь и в `starter_flow`**: `isolate=True` → `<ws>.parent/.flower-<ws.name>`
(вне репозитория); иначе `<ws>/.flower`. Драйвер, которому надо узнать, где лежит brief, тоже идёт через эту функцию —
если склеить путь самому и ошибиться, ошибки не будет, просто всё тихо перестанет работать.

---

## Фабрика ролей {#角色工厂}

Исходник: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Все пять ролей — фабричные функции. Каждая роль = **кусок внедряемого текста правил + набор инструментов + набор hook'ов**.
`worker()` отдаёт `AgentDefinition` из SDK (для назначения subagent'у), остальные четыре — [`AgentSpec`](#agentspec)
(они поднимают собственную сессию).

Сами роли **hook'и не вешают** — перехват инструментов навешивает `Runtime._attempt` автоматически по `spec.delegate_only`,
см. [слой hook](#hook).

Внутренние константы наборов инструментов (не экспортируются, но определяют значения по умолчанию):

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

Создаёт [координатора](glossary.md#主线程) в [главном потоке](glossary.md#协调者): он разбирает задачу, раздаёт работу, читает отчёты, принимает решения,
**но руками ничего не делает**. Первые три параметра — позиционные.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязателен | Имя роли, оно же имя шага по умолчанию |
| `instructions` | `str` | обязателен | Предметные инструкции. В итоге получается `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | обязателен | Какие роли у него в подчинении, попадает в `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Если задан — добавляются сразу **оба** инструмента, `inbox` **и** `ask`, и выставляется `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → без `Read` |
| `glance` | `bool` | `True` | Добавляет `"Bash"` и выставляет `AgentSpec.glance`. **Что именно можно запускать, решает `delegate_guard`**, а не этот флаг |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | `None` | Лимит раундов |
| `max_budget_usd` | `float \| None` | `None` | Лимит [бюджета](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Режим прав. **Обратите внимание на это значение по умолчанию** — передав его в `clarify()`/`judge()`, вы снимете защиту с этих двух ролей |
| `compact` | `CompactPolicy \| None` | `None` | Если задан, `Runtime` не станет принудительно менять его на `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Дополнительные hook'и, будут слиты с `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Дополнительные переменные окружения |

Три поля в получившемся `AgentSpec` фиксированы: `delegate_only=True`, `agents=workers`,
а `workbench` остаётся со значением `True` по умолчанию из `AgentSpec`.

В исходнике прямо написано: **не реализуйте «только координировать, руками не делать» через `disallowed_tools`** — это уровень сессии,
такой запрет заодно отключит `Bash`/`Write` у subagent'ов, см. предупреждение в [`AgentSpec`](#agentspec).
Правильный способ — именно этот: `delegate_only=True` + не выдавать `allowed_tools`,
а дальше [`delegate_guard`](#delegate-guard) по `agent_id` перехватывает только главный поток.

Если задан `channel`, **оба инструмента приходят вместе**, это не опция: как только подключён MCP server, доступны оба, а
`allowed_tools` не эксклюзивен — вызвать их можно независимо от того, перечислены они там или нет. В режиме без человека каждый `ask` будет висеть весь `timeout_s` —
для таких случаев используйте `HumanChannel(timeout_s=0)`.

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

Создаёт определение [subagent](glossary.md#subagent), который реально делает работу. Первые два параметра — позиционные.
Возвращается `AgentDefinition` из SDK, его можно напрямую положить в `coordinator(workers={...})`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `description` | `str` | обязателен | **Основание, по которому координатор выбирает исполнителя** — пишите чётко, «какую работу ему отдавать» |
| `prompt` | `str` | обязателен | Его system prompt. При `discipline=True` склеивается как `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Исполнителя не следует понижать |
| `effort` | `str \| int \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | `None` | Уходит в **`maxTurns`** SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Уходит в **`permissionMode`** SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Какие skill'ы ему разрешены |
| `discipline` | `bool` | `True` | Приклеивать ли блок дисциплины отчётности `WORKER_RULES` |
| `isolate` | `bool` | `False` | Ставит метку [изоляции](glossary.md#隔离), идёт через `isolated()`, **это не поле `AgentDefinition`** |

`isolate=True` требует, чтобы workspace был git-репозиторием, иначе инструмент `Agent` сразу выдаёт `"not in a git repository"`,
**без тихой деградации**. Кроме того, метка — это атрибут Python: `dataclasses.replace()` над `AgentDefinition`
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

Создаёт [уточнителя](glossary.md#确认者): до начала работы выяснить требования, ничего не делать, только задавать вопросы, на выходе — ровно четыре раздела.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязателен | Имя роли, позиционный параметр |
| `channel` | `HumanChannel` | обязателен | Канал для вопросов, позиционный параметр |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | При `True` добавляются `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | `None` | **Без лимита раундов** |
| `max_budget_usd` | `float \| None` | `None` | Лимит бюджета |

В получившемся `AgentSpec`: `allowed_tools = [channel.tool_name] + (те пять, если разрешено чтение)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (у него нет инструментов записи, индекс ему бессмыслен),
`permission_mode` наследует значение по умолчанию `"default"` из `AgentSpec`.
**Ни `Write` / `Edit` / `Bash` / `Agent`, ни `inbox`** (в отличие от координатора).

!!! warning "Маленький `max_turns` превращает «без ограничения на число вопросов» в пустые слова"
    Каждый вопрос — это раунд. `max_turns=16` означает «максимум десяток с небольшим вопросов», и фраза в канале «лимита раундов нет» тут же становится ложью.

    Чтобы вопросы действительно были свободны, надо снять ограничение **в обоих местах**: `HumanChannel.max_asks` (по умолчанию уже `None` = без лимита)
    и `max_turns` (по умолчанию уже `None`).

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

Создаёт [судью](glossary.md#判定者): либо он ставит цель перед стартом, либо после каждого раунда выносит вердикт по этому раунду.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | обязателен | Имя роли, позиционный параметр |
| `channel` | `HumanChannel` | обязателен | Канал для вопросов, позиционный параметр |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `JUDGE_RULES` |
| `can_run` | `bool` | `False` | При `True` в белый список добавляется `Bash`, и `whitelist_guard` соответственно пропускает `Bash`, по-прежнему перехватывая `Write`/`Edit` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | `None` | Лимит раундов |
| `max_budget_usd` | `float \| None` | `None` | Лимит бюджета |

В получившемся `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (при `can_run`) `["Bash"]`,
`workbench=False`, остальное как в `clarify()`. **Ни `Write` / `Edit` / `Agent`, ни `inbox`.**

**Компромисс**: при `can_run=True` вердикт жёстче (можно реально прогнать приёмочные команды), но ценой того, что судья получает возможность изменить рабочую область —
`Bash` сам по себе умеет писать файлы. Если нужен абсолютно нейтральный вердикт, не включайте.

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

Создаёт [оракула](glossary.md#旁路顾问): пока запуск ещё идёт, у него можно спросить «где мы сейчас», он посмотрит последние события и верстак
и ответит. **Сказанное им в контекст этого запуска не попадает.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Имя роли, позиционный параметр |
| `instructions` | `str` | `""` | Дополнительные инструкции, приклеиваются после `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | **`12`** | По умолчанию с тормозом |
| `max_budget_usd` | `float \| None` | **`0.5`** | По умолчанию с тормозом. Это «спросить мимоходом», оно не должно выходить из-под контроля |

В получившемся `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]` (**без channel** — он не спрашивает,
он отвечает), `workbench=True` (**единственная из пяти ролей, которая не координатор, но с включённым верстаком** — ему как раз и нужно читать результаты и заметки).

### Пять текстов правил {#rules}

Все пять констант входят в `__all__`, их можно напрямую `import`, прочитать, склеить, поменять.

| Константа | Кому внедряется | Способ внедрения | Суть |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Ты — «человек, умеющий пользоваться Claude Code», а не исполнитель; нельзя писать файлы / править код / гонять тесты; `Bash` годится только «взглянуть», и результат устаревает; **в [техзадании](glossary.md#任务书) пишется только то, что специфично именно для этой задачи**; единственное правило, которое ещё нужно проговорить, — «где верстак + длинные результаты в `artifacts/` + в ответе только пути»; после каждого завершённого этапного действия проверять `inbox`; `ask` блокирует, использовать только на настоящей развилке |
| `WORKER_RULES` | `worker()` | Приклеивается **после** `prompt` subagent'а | Формат ответа — **вывод / основания / результаты / непроверенное**, не более 30 строк; запрещено вставлять содержимое файлов, вывод команд, логи, сырые diff'ы; запрещено пересказывать процесс проб и ошибок; перед работой сначала посмотреть `.flower/scripts/`. **Про «длинные результаты в `artifacts/`» здесь намеренно не написано** — реальные пути генерирует `Workbench`, зашитые вручную будут неверными |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Ничего не делать, только выяснять требования; **лимита на количество вопросов нет, спрашивай, пока не станет ясно**; человека может не быть на месте, при таймауте решай сам и записывай это в «未知与假设»; на выходе — **ровно четыре раздела**; не писать код, не вставлять содержимое файлов |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Одно из двух. **Поставить цель**: каждый пункт списка должен проверяться на месте, длина списка определяется числом способов провалиться, **границы не являются пунктом проверки**, к непроверяемым пунктам в конец добавляется `[此环境无法验证:原因]`. **Вынести вердикт по раунду**: на выходе **ровно три раздела**, судят **результат, а не исходники**, «сделано» по умолчанию не верить, «не достигнуто» и «здесь это не проверить» — два разных вывода, и второй **ни в коем случае нельзя засчитывать как пройденное** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Ты на боковой ветке; тот запуск ещё идёт, ты его не прерываешь и в нём не участвуешь; **только чтение**; ответил — и всё, сказанное тобой в контекст того запуска не попадёт; у тебя на руках только «окно последних событий» и «верстак»; сначала посмотри, потом отвечай, не можешь ответить — так и скажи, коротко |

---

## Определение agent {#agent-定义}

Исходник: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` — полное объявление одного специализированного agent'а, а `build_options` компилирует его в `ClaudeAgentOptions` из SDK.
[Фабрика ролей](#角色工厂) как раз и производит `AgentSpec` — если нужна комбинация вне фабрик, конструируйте его напрямую.

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
| `name` | `str` | обязательно | Имя роли. Оно же `step_name` по умолчанию в `Runtime.run` и самоназвание в тексте отказа `whitelist_guard` |
| `instructions` | `str` | обязательно | Предметные инструкции. **[Дописываются](glossary.md#叠加) после родного system prompt Claude Code, а не заменяют его** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Список без запроса подтверждения, а не эксклюзивный белый список** — модель по-прежнему может вызвать инструмент, которого тут нет. Эксклюзивность обеспечивает [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Уровень сессии**. См. предупреждение ниже |
| `model` | `str \| None` | `None` | Модель |
| `effort` | `str \| None` | `None` | Интенсивность рассуждения |
| `max_turns` | `int \| None` | `None` | Лимит раундов |
| `max_budget_usd` | `float \| None` | `None` | Лимит [бюджета](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Режим прав |
| `agents` | `dict[str, Any] \| None` | `None` | Таблица определений subagent'ов, значения — `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Таблица MCP server'ов. `HumanChannel.mcp_servers()` подставляется прямо сюда |
| `hooks` | `dict[str, Any] \| None` | `None` | Дополнительные hook'и, `Runtime` сольёт их со своими через `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Если задан, `Runtime` не станет принудительно менять его на `no_summary` |
| `env` | `dict[str, str]` | `{}` | Переменные окружения, внедряемые в дочерний процесс. Сверху делается `update` из `compact.env()` |
| `glance` | `bool` | `False` | Разрешает координатору самому запускать `Bash` «только взглянуть». Что именно пропускается, решает [`is_ephemeral`](#is-ephemeral), а результат помечается `EphemeralPolicy` как устаревающий |
| `workbench` | `bool` | `True` | Внедрять ли индекс верстака в system prompt этого agent'а. **Роли без инструментов записи должны это выключать** (`clarify()` / `judge()` по умолчанию уже `False`) |
| `delegate_only` | `bool` | `False` | Только координировать, руками не делать. При `True` `Runtime` вешает `delegate_guard` и **не вешает** `whitelist_guard` |

!!! warning "`disallowed_tools` действует на уровне сессии и отключит инструменты и у subagent'ов"
    Дословный текст ошибки из практики: `"Bash is disabled for this session, in subagents as well as here"`.
    То есть если вы захотели, чтобы координатор не работал руками, и написали `disallowed_tools=["Bash"]`, то и отправленный исполнитель не сможет запускать команды —
    весь запуск пропал.

    Чтобы получить «только координировать, руками не делать», используйте `delegate_only=True` + не выдавайте `allowed_tools`, и пусть
    [`delegate_guard`](#delegate-guard) по `agent_id` перехватывает только главный поток.

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

Компилирует `AgentSpec` в `ClaudeAgentOptions` из SDK. Именно её и вызывает внутри `Runtime._attempt`;
если вы сами управляете SDK (без `Runtime`), входить тоже нужно отсюда.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `spec` | `AgentSpec` | обязателен, позиционный | Объявление, которое компилируем |
| `cwd` | `str \| Path \| None` | `None` | Записывается в `cwd` только если не `None` |
| `session_store` | `SessionStore \| None` | `None` | Только если не `None`, записываются `session_store` и `session_store_flush` |
| `resume` | `str \| None` | `None` | Какую сессию продолжать |
| `fork` | `bool` | `False` | Уходит в `fork_session`. **Вложено внутрь `if resume:`** |
| `resume_at` | `str \| None` | `None` | Уходит в `resume_session_at`. **Тоже вложено внутрь `if resume:`** |
| `use_plugin` | `bool` | `True` | При `True` и существующем `PLUGIN_DIR` → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Дополнительно авторизованные каталоги. **Обязательно задавать, если верстак лежит вне рабочей области** |
| `flush` | `str` | `"eager"` | Уходит в `session_store_flush` |
| `prelude` | `str` | `""` | Кусок, дописываемый после `instructions` (индекс верстака идёт сюда) |

Соответствие:

| Ключ в получившихся options | Значение |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Берутся прямо из `spec` |
| `setting_sources` | `[]` (переносимый режим) или `["project"]` |
| `plugins` | Только если существует каталог `plugin/` в корне репозитория |
| `cwd` / `add_dirs` | Записываются, только если непустые |
| `session_store` / `session_store_flush` | Записываются, только если `session_store` не `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Каждое записывается, только если непустое |
| `env` | `dict(spec.env)`, затем `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Действуют только если `resume` истинен** |

`PLUGIN_DIR` — это каталог `plugin/` в корне репозитория (три уровня вверх относительно `flower/core/agent.py`). После установки через pip этого каталога может и не быть,
код проверяет наличие через `is_dir()`.

!!! warning "`fork=True` без `resume` молча не работает"
    И `fork_session`, и `resume_session_at` вложены внутрь `if resume:` — без `resume` они не срабатывают вообще,
    **и ошибки при этом нет**. Точно так же `Runtime.run(resume_at=...)` работает только если задан `resume`,
    а **`Workflow` никогда не передаёт `resume_at`**: откатиться по сообщениям можно только вызвав `Runtime.run` напрямую.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Панель переключателей auto-[compact](glossary.md#压缩); результат — набор переменных окружения для внедрения в дочерний процесс.
Сам алгоритм compact зашит в бинарник harness и не меняется, менять можно только «срабатывать или нет».

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = ничего не выставляем, порог = окно − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (выключает заодно и `/compact`). **Любое другое значение бросает `ValueError`**, а не игнорируется молча |
| `window` | `int \| None` | `None` | Не `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Со стороны CLI ограничение 100k–1M, значение меньше 100k будет поднято до 100k |

| Метод | Сигнатура | Описание |
|---|---|---|
| `env` | `() -> dict[str, str]` | Выдаёт переменные окружения. **`ValueError` на недопустимый `mode` бросается именно здесь, а не при конструировании** — вызывает её `build_options`, поэтому ошибка всплывает внутри `Runtime.run` |

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

Объект политики «когда контекст почти полон, написать [документ передачи](glossary.md#交接书) и перейти в новую сессию» вместо compact.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | `bool` | `True` | Выключить — откатимся к auto-compact |
| `window` | `int` | `default_window()` | Какого размера мы считаем окно контекста модели |
| `headroom` | `int` | `50_000` | Сколько запаса оставить. Обоснование: auto-compact срабатывает на отметке окно − 33k, смена поколения должна успеть раньше, а само «написать передачу» требует ещё одного раунда |
| `max_generations` | `int` | `8` | Максимум поколений на один шаг. **Это тормоз от разгона, а не планирование ёмкости** |

| Свойство | Тип | Описание |
|---|---|---|
| `at` | `@property -> int` | Порог смены поколения `max(10_000, window - headroom)`. **Есть нижняя граница 10k** — ниже уже не получится даже написать передачу |
| `warn_at` | `@property -> int` | Точка предупреждения о приближении `max(1_000, at - 20_000)`, отправляется один раз за поколение |

!!! warning "Слишком маленький `window` приводит к бесконечной смене поколений и сжиганию денег"
    Если `at` окажется ниже **стартового пола** этой роли (для координатора на практике около 34k), то каждая новая сессия переходит порог с первого же слова, а
    **смена поколения не расходует лимит повторов** (`attempt -= 1`), и получается бесконечный холостой ход. Единственный тормоз — `max_generations=8`,
    при упоре в него `error` заменяется диагностическим сообщением с подсказкой увеличить `window` или отключить смену поколений.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Угадывает размер окна контекста по **строке имени модели** из переменных окружения `ANTHROPIC_MODEL` или `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Условие | Возврат |
|---|---|
| В имени есть отдельное слово `1m` (регулярка `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| В имени содержится `haiku` | `200_000` |
| Всё остальное (**включая случай, когда обе переменные не заданы**) | `1_000_000` |

**По умолчанию берётся агрессивное значение.** Завысить — не жёсткая ошибка: API отобьёт запрос с `prompt is too long`, `Runtime` распознает этот сигнал
(внутренняя `is_overflow`) и тут же сменит поколение — но передача у того поколения будет деградировавшей версией.

---

## Документы {#文书}

Исходники: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Четыре dataclass, и все они про одно: «разобрать ответ модели на фиксированный набор разделов и записать на диск». Общая форма:
`parse()` разбирает, `missing()` / `complete()` проверяют полноту, `to_markdown()` — для человека,
`prompt_block()` — для модели ниже по цепочке, `write()` / `load()` — запись на диск и чтение обратно.

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

[Бриф](glossary.md#需求确认书), **ровно четыре раздела**, фиксированный порядок
`goal` → `accept` → `bounds` → `unknowns`, китайские названия разделов — соответственно «目标», «验收标准», «边界», «未知与假设».

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `goal` | `str` | `""` | Цель |
| `accept` | `str` | `""` | Критерии приёмки |
| `bounds` | `str` | `""` | Границы |
| `unknowns` | `str` | `""` | Неизвестное и допущения |
| `path` | `Path \| None` | `None` | Путь сохранения на диск. `compare=False`, в сравнении не участвует |

| Метод | Сигнатура | Описание |
|---|---|---|
| `missing` | `() -> list[str]` | **Китайские названия** отсутствующих разделов, можно показывать как есть |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Разбирает четыре раздела из ответа модели. **Сначала снимает блоки кода в ограждении**, что не разобралось — остаётся пустым |
| `to_markdown` | `() -> str` | Полный документ с шапкой-метаинформацией, пустые разделы пишутся как `"(未填)"` |
| `prompt_block` | `() -> str` | Компактная версия для передачи дальше, **только непустые разделы**, без метаинформации |
| `write` | `(path: str \| Path) -> Path` | Создаёт родительский каталог, пишет файл, выставляет `self.path` в resolve-нутый путь и возвращает его |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Если файла нет или случился `OSError` — возвращает `None`. **Заглушки `"(未填)"` восстанавливаются обратно в пустые строки** |

Правила разбора (концентрация мест, где легко ошибиться):

- При снятии ограждений **незакрытый ``` или `~~~` приводит к отбрасыванию всего текста от него и дальше** — на практике уточнитель вставляет в ответ целиком весь код.
  Если вывод модели обрезан, все последующие разделы не разбираются, `complete()` даёт `False`, и gate отправляет на повтор.
- Регулярка заголовков допускает `## 目标` / `**目标**` / `目标:` / `3. 边界`, а также текст сразу после заголовка.
- Таблица псевдонимов компилируется в порядке убывания длины, иначе «未知» съест «未知与假设» первым.
- При повторе одноимённых разделов **берётся первый непустой**.
- Если при ручном редактировании брифа вы скопировали заглушку `"(未填)"` из `to_markdown()`, этот раздел по-прежнему считается отсутствующим.

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

[Документ передачи](glossary.md#换代), который пишется при [смене поколения](glossary.md#交接书), пять разделов.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `doing` | `str` | `""` | Что делается. **Обязательно** |
| `decided` | `str` | `""` | Что решено |
| `deadends` | `str` | `""` | Тупиковые пути |
| `next` | `str` | `""` | Следующий шаг. **Обязательно** |
| `scene` | `str` | `""` | Обстановка |
| `step` | `str` | `""` | Только для шапки документа, **в разборе не участвует** |
| `path` | `Path \| None` | `None` | Путь сохранения на диск |

**Обязательных разделов только два: `doing` и `next`** — жёсткое требование непустых «тупиковых путей» заставит модель их выдумывать.

| Член | Сигнатура | Описание |
|---|---|---|
| `missing` | `() -> list[str]` | **Проверяет только те два обязательных раздела** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Есть ли в тексте метка деградации `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Переиспользует разбиватель разделов из `Brief` |
| `to_markdown` | `() -> str` | Пустые разделы пишутся как `"(空)"` |
| `prompt_block` | `() -> str` | **Шапка прямо сообщает принимающему, что он принимает работу**, чтобы он не побежал выспрашивать контекст у человека |
| `write` | `(path) -> Path` | Как `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Как `Brief.load` |

Три члена того же модуля, **не экспортируемые, но семантически ключевые**: `is_overflow(*texts)` матчит `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` и т. п., превращая «жёсткую ошибку» в «немедленную смену поколения»; `HANDOFF_PROMPT` — это тот промпт, которым
**текущая сессия сама** пишет передачу (содержит два плейсхолдера `{used}` и `{window}`, **это не новая роль** —
только у неё самой есть этот контекст); `degraded(step, prompt, *, why="")` механически собирает документ, когда передачу написать не удалось,
в `scene` кладутся первые **1200** символов исходной задачи.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

Цель и список проверок для [стража цели](glossary.md#目标看守).

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `statement` | `str` | `""` | Формулировка цели |
| `checks` | `list[str]` | `[]` | Список проверок, по одной на строку |
| `path` | `Path \| None` | `None` | Путь сохранения на диск |

| Член | Сигнатура | Описание |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Пункты `checks`, помеченные `[此环境无法验证:…]`. **Они обречены не пройти уже в момент постановки цели** |
| `missing` | `() -> list[str]` | Требуется непустой `statement` **и** непустой `checks` |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` — по одной на строку, маркеры `-` / `*` / `1.` снимаются автоматически |
| `to_markdown` | `() -> str` | Если список пуст, пишется `"(空)"` |
| `prompt_block` | `() -> str` | Компактная версия для передачи дальше |
| `write` / `load` | Как у `Brief` | Запись на диск и чтение обратно |
| `amend` | `(extra: str) -> Goal` | **Дописывает, а не перезаписывает**: после `statement` приклеивается `"\n\n(已修改)" + extra`, возвращается `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Результат одного раунда вердикта от [судьи](glossary.md#判定者), **ровно три раздела**: вывод / основание / не пройдено.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, если разобрать не удалось — `""` |
| `reason` | `str` | `""` | Основание |
| `failed` | `list[str]` | `[]` | Непройденные пункты списка |

| Член | Сигнатура | Описание |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Удалось ли вообще разобрать вывод. **`ok=False` обязан трактоваться как «не достигнуто», а не как достигнуто** |
| `parse` | `@classmethod (text) -> Verdict` | См. ниже |
| `feedback` | `() -> str` | Текст, отправляемый исполнителю обратно: только «чего не хватает», без решения |

Порядок распознавания в `parse`:

1. Сначала берётся раздел по заголовку «结论» / «判定».
2. Если разделов с заголовками нет, весь текст после strip проверяется `fullmatch(r"1|true")` → достигнуто; `fullmatch(r"0|false")` → ещё нет.
3. Иначе в тексте вывода ищется первое совпадение по таблице слов-состояний (**длинные слова раньше**).
   **«无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» — всё это относится к `unreachable`** —
   на этом уже обжигались: целевая платформа macOS, запуск в Linux-контейнере, судья посмотрел ветку в исходниках и засчитал проход.
4. Всё ещё ничего → ищется изолированное `\b1\b` → достигнуто, `\b0\b` → ещё нет.
5. Ничего не подошло → `state=""`, `ok=False`.

`unreachable` и `not_yet` — **два разных вывода**: первый ведёт по ветке «остановиться и спросить человека», а не «ещё один раунд».

---

## Слой hook {#hook}

Исходник: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Этот слой — **граница исполнения** flower: какие инструменты запрещено трогать главному потоку,
как обрезать сверхдлинные результаты, какая роль уходит в отдельный worktree —
всё это принудительно навязано hook'ами SDK, а **не промптом**. Причина прямая: промпт — это
совет, модель может его не слушать. Уже измерено: даже когда в системном промпте прямо написано
«не используй worktree», внедрение `isolate_guard` всё равно срабатывает (модель передала `None`,
на диск ушло `'worktree'`).

Девять экспортов: пять фабрик guard'ов, возвращающих `HookMatcher` (`whitelist_guard` может вернуть `None`),
один сборщик, один объединитель и две функции маркировки изоляции.
Вручную их подключать не нужно — [`Runtime`](#runtime) собирает их автоматически по `AgentSpec`.
Ручное подключение нужно только если вы сами управляете SDK (в обход `Runtime`).

**Проверка главного потока идёт через одну функцию**: `_is_main_thread(data) = not data.get("agent_id")` —
в данных tool-lifecycle hook'ов у subagent есть `agent_id`, у [главного потока](glossary.md#主线程) его нет.
На этом одном условии держатся все guard'ы, которые «ловят только главный поток».

Константы групп инструментов (уровень модуля, не экспортируются, но задают matcher'ы по умолчанию):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Шпаргалка: какой guard на каком событии SDK {#hook-速查表}

| Функция | Событие hook SDK | matcher | Что перехватывает | Что возвращает | Кто устанавливает |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | те из `Bash\|Write\|Edit\|NotebookEdit`, которых **нет в `allowed_tools`** | вызов запрещённого инструмента **только в главном потоке** | `permissionDecision: "deny"` + причина | `Runtime._attempt`, **только если `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (меняется через `tools=`) | работа руками **только в главном потоке**; при `allow_glance=True` `Bash`, прошедший `is_ephemeral()`, пропускается | `deny` + «отправь subagent» | `workbench_hooks(delegate_only=True)`, **только если у `Runtime` есть верстак** |
| `isolate_guard` | `PreToolUse` | `Agent` | в `tool_input` нет ни `cwd`, ни `isolation`, а роль `subagent_type` помечена через `isolated()` | `permissionDecision: "allow"` + `updatedInput` (внедряет `isolation="worktree"`) | `workbench_hooks`, **только если в `agents` есть помеченная роль** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` попадает внутрь `workbench.root` | `{}` (побочный эффект — `workbench.refresh()`) | `workbench_hooks`, всегда |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **строковые поля** в `tool_response` длиной ≥ `threshold`; чтение самого каталога spill пропускается | `updatedToolOutput` (spill + строка-указатель + первые 400 символов) | `workbench_hooks`, **только если `spill_threshold` истинно** |

**Ключевой вывод из этой таблицы**: при `Runtime(workbench=False)` весь `workbench_hooks` не ставится;
а для координатора с `delegate_only=True` пропускается ещё и `whitelist_guard` — то есть
**у главного потока не остаётся ни одной стены**. Подробнее — в предупреждении в разделе [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Делает `allowed_tools` действительно исключающим для тех четырёх инструментов, которые работают руками.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `allowed` | `list[str] \| None` | обязательный, позиционный | обычно передаётся прямо `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | самоназвание в тексте отказа. `Runtime` передаёт `spec.name` |

- **Ставится на `PreToolUse`**, matcher — `"|".join(banned)`, где `banned` = те из `Bash` `Write` `Edit` `NotebookEdit`,
  которых нет в `allowed`.
- Попадание — сразу `permissionDecision: "deny"`, текст по смыслу: «у XX нет YY. **Это сделано намеренно,
  это не пропущенная настройка.** Впиши вывод в тело своего ответа, фреймворк возьмёт его оттуда —
  не пытайся обойти это другими формулировками».
- **Ловит только главный поток текущей сессии**, subagent'ы пропускаются — их инструменты определяет
  `AgentDefinition.tools`.
- Если перехватывать нечего, возвращает **`None`** (например, для роли вроде `worker()` с полным набором
  инструментов) — вызывающая сторона по этому решает, ставить hook или нет.

**Почему он обязателен**: `allowed_tools` — это **список без запроса подтверждения, а не исключающий белый список**.
Две измеренные проверки: судья, которому поставили цель, запустил `Bash` 11 раз; в пробе за $0.1
агент с `allowed_tools=["Read"]` спокойно вызывал `Write`/`Bash`.
Поэтому «у `clarify()` / `judge()` нет инструментов записи» **держится именно на этом hook'е**, а не на самом белом списке.

Плюс в том, что он выводится из `allowed_tools`, поэтому `judge(can_run=True)` автоматически сохраняет `Bash`
и всё равно блокирует `Write`/`Edit` — отдельный переключатель не нужен.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Главный поток берётся делать сам → отказ с указанием, что делать вместо этого.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. Это строка-регулярка, а не список |
| `allow_glance` | `bool` | `False` | при `True` пропускается, если `tool_name == "Bash"` и [`is_ephemeral(command)`](#is-ephemeral) истинно |

- **Ставится на `PreToolUse`**, matcher — это и есть `tools`.
- Главный поток вызывает один из этих четырёх инструментов → deny, и в причине **написано, что делать дальше**:
  отправить subagent через инструмент `Agent`, в задании явно указать цель и критерии приёмки, и потребовать
  писать длинные результаты в `.flower/artifacts/`, а в ответе давать только путь и вывод.
- Subagent'ы пропускаются всегда.

Отличие от `whitelist_guard` — **в формулировке**: оба ловят один и тот же набор инструментов, но этот говорит
«отправь исполнителя», что здесь уместнее. Поэтому роли с `delegate_only=True` получают только его —
двойная установка выдаст модели две противоречащие инструкции.

Условие пропуска при `allow_glance=True` и условие «обрежется ли результат» — **это одна и та же функция**
([`is_ephemeral`](#is-ephemeral)): множество пропускаемых команд обязано совпадать с множеством устаревающих;
меняешь одно — обязан менять другое.

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

Результат инструмента, превысивший порог, **сразу уходит в [spill](glossary.md#落盘)**, а в контексте остаётся
одна строка-указатель — а не так, что ждём заполнения контекста и потом сжимаем.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | каталог spill — `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | со скольких символов начинать сбрасывать |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (по умолчанию) = результаты subagent'ов тоже сбрасываются |

- **Ставится на `PostToolUse`**, возвращает
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <обрезанное>}}`.
- Имя файла — первые 16 символов `sha256` содержимого + `.txt`, в контексте вместо содержимого — строка-указатель
  + **первые 400 символов**.
- `updatedToolOutput` **обязан сохранять структуру вывода исходного инструмента**, поэтому заменяются только
  слишком длинные **строковые поля** в dict; **list'ы не трогаются никогда** (внутри могут быть блоки изображений).
  Неправильная структура будет отвергнута (текст остаётся исходным, ошибки нет).
- **При чтении самого файла spill необходимо пропускать** — иначе «прочитай его через `Read`» превращается в пустые
  слова: прочитанный полный текст снова уходит в spill, бесконечный цикл.
  На это уже наступали: модель перепробовала пять способов обойти.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Записали что-то на [верстак](glossary.md#工作台) — обновляем `INDEX.md`, и следующий агент с самого начала знает,
что это существует.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | область проверки и объект обновления |

**Ставится на `PostToolUse`**, matcher `"Write|Edit"`. Если `tool_input["file_path"]` после resolve попадает
внутрь `workbench.root`, вызывается `workbench.refresh()`. **Всегда возвращает `{}`** — он ничего не меняет,
у него только побочный эффект.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Выдаёт subagent'ам отдельный git worktree по роли — так реализуется [изоляция](glossary.md#隔离).

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | обязательный, позиционный | таблица ролей, по ней проверяется, помечен ли `subagent_type` |
| `on_inject` | `Any` | `None` | необязательный колбэк, вызывается как `on_inject(subagent_type, description)` |

**Ставится на `PreToolUse`**, matcher `"Agent"`. Внедрение происходит только при одновременном выполнении трёх условий:
`tool_name == "Agent"`, в `tool_input` **нет ни `cwd`, ни `isolation`**, и роль, соответствующая `subagent_type`,
помечена через `isolated()`. Тогда возвращается `permissionDecision: "allow"` + `updatedInput`
(`isolation` выставляется в `"worktree"`).

`isolation` и `cwd` в инструменте `Agent` **взаимоисключающи** — если модель сама задала `cwd`, это уважается.
«Нужна ли изоляция» — это **свойство роли**, а не глобальный переключатель и не решение при каждой отправке задания;
роли, которой изоляция не нужна, не будет добавлено ни одного байта.

**Включив изоляцию, нужно вынести [верстак](glossary.md#工作台) из репозитория.** Изолированный агент не может писать
в общий checkout, поэтому верстак обязан указывать через `home=` куда-то вне репозитория. `starter_flow(isolate=True)`
использует `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` — `<run_dir>/workbench`;
оба вне репозитория, **но это не один и тот же каталог**, не смешивайте их.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Помечает определение subagent'а как «нужна отдельная рабочая область» и читает эту метку обратно.

| Функция | Параметр | По умолчанию | Описание |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | обязательный | определение, которое помечаем. **Возвращается тот же самый объект** |
| | `flag: bool` | `True` | позиционный. `False` = снять метку |
| `wants_isolation` | `agent: AgentDefinition \| None` | обязательный | `None` тоже принимается, возвращает `False` |

Метка — это атрибут `_flower_isolate` на стороне Python, выставленный через `object.__setattr__`,
**а не поле dataclass**: SDK сериализует через `asdict()` и признаёт только объявленные поля, поэтому метка
не утечёт в CLI (проверено).

**Цена**: `dataclasses.replace()` над `AgentDefinition` теряет эту метку, и изоляция молча перестаёт работать.

`worker(isolate=True)` внутри как раз вызывает `isolated()`.

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

Ставит одним вызовом все hook'и, нужные верстаку. Именно её вызывает `Runtime._attempt`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workbench` | `Workbench` | обязательный, позиционный | передаётся в `index_guard` и `spill_guard` |
| `delegate_only` | `bool` | `True` | `delegate_guard` ставится только при `True` |
| `spill_threshold` | `int \| None` | `4000` | `spill_guard` ставится, только если значение истинно |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | `isolate_guard` добавляется, если **хотя бы одна** роль помечена через `isolated()` |
| `allow_glance` | `bool` | `False` | пробрасывается в `delegate_guard(allow_glance=)` |

Что получается:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  есть помеченные роли → добавляется `isolate_guard(agents)`.
- `PostToolUse`: всегда `[index_guard(workbench)]`; при истинном `spill_threshold` → добавляется
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Ключи событий с пустым списком выбрасываются**, пустой list не возвращается.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Склеивает** несколько групп конфигураций hook'ов по имени события.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | переменное число аргументов | сколько угодно групп. Группы `None` пропускаются |

Использует `extend`, **дубликаты не убирает** — передадите один guard дважды, он и установится дважды.
`Runtime` через неё объединяет `spec.hooks`, `workbench_hooks(...)` и `whitelist_guard`.

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

Рабочий каталог на диске: три подкаталога + один индекс. Индекс **внедряется в system prompt**,
поэтому агент на каждом ходу знает, что у него есть под рукой.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `workspace` | `Path` | обязательное, позиционное | рабочая область. `__post_init__` делает resolve |
| `dirname` | `str` | `".flower"` | имя каталога верстака, относительно `workspace` |
| `max_index_entries` | `int` | `40` | **касается только `prompt_block()`**: сколько записей каждого типа максимум перечислять во фрагменте, внедряемом в system prompt; остальное сворачивается в строку «…и ещё N». Сам `INDEX.md` не ограничен, в нём перечисляется всё |
| `home` | `Path \| None` | `None` | если задан, используется как `root`, а **`dirname` игнорируется**. При не-`None` тоже делается resolve |

| Член | Сигнатура | Описание |
|---|---|---|
| `root` | `@property -> Path` | если задан `home` — он, иначе `workspace / dirname` |
| `external` | `@property -> bool` | находится ли `root` **вне** `workspace`. В режиме изоляции должно быть `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, скрипты, которые понадобится запустить второй раз |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, длинные результаты свыше 2000 символов |
| `notes` | `@property -> Path` | `root / "notes"`, ключевые решения, одно решение — один файл |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | путь для показа модели: внутри рабочей области — относительный, вне — абсолютный |
| `ensure` | `() -> Workbench` | mkdir трёх каталогов, возвращает `self` (можно цепочкой: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(путь для показа, описание, число байт)`. Рекурсивный `rglob("*")`, файлы, начинающиеся с `.`, пропускаются |
| `refresh` | `() -> str` | перезаписывает `INDEX.md` и возвращает содержимое |
| `prompt_block` | `() -> str` | **тот самый фрагмент, который внедряется в system prompt**. Сделан коротким намеренно — он присутствует на каждом ходу |

Формат самоописания скрипта: `# desc: 一句话` в пределах первых 8 строк (распознаются также символы комментария
`//` и `--`), иначе — первый непустой комментарий или первая строка docstring (обрезается до 100 символов).

Три правила, которые внедряет `prompt_block()`:

1. Скрипты, которые понадобится запустить второй раз, пишутся в `scripts/`, в первой строке — `# desc:`.
2. Результаты длиннее **2000 символов** пишутся в `artifacts/`, в диалог идут только путь и вывод.
3. Ключевые решения пишутся в `notes/`, одно решение — один файл.

При `external=True` `prompt_block()` дополнительно вставляет фразу «обращайся к нему по абсолютному пути».

**Индекс не наследуется subagent'ами.** Он идёт через `system_prompt.append` уровня сессии, а у subagent'а свой
system prompt (измерено, $0.2461). Поэтому два пункта — «длинные результаты в `artifacts/`» и «где находится верстак» —
обязан пересказать [координатор](glossary.md#协调者) в [задании](glossary.md#任务书); **это единственный канал**, а не дублирование.
В `WORKER_RULES` этого **намеренно нет**: реальные пути генерирует `Workbench`, зашитые жёстко они будут неверными.

---

## Хранилище сессий {#会话存储}

Исходники: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Три уровня наследования: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **всегда использует самый внешний**, а политики всех трёх уровней задаются параметрами конструктора.

Каждый уровень отвечает за одно: запись на диск, [trim](glossary.md#裁剪) по объёму и ценности,
[prune](glossary.md#剪除) по признаку «это ошибка или нет».
И trim, и prune происходят в момент **`load()`** (то есть когда resume скармливает историю обратно модели),
а исходные записи в SQLite не меняются ни на байт.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Реализует протокол `SessionStore` из SDK, три таблицы: `entries` / `meta` / `summaries`.
Ключ store — `project_key/session_id[/subpath]`; **transcript'ы дочерних агентов различаются по subpath**.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `str \| Path` | обязательный, позиционный | файл БД. Соединение открывается с `check_same_thread=False` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `append` | `async (key, entries) -> None` | идемпотентная дедупликация по uuid (сначала убираются уже записанные, затем дубликаты внутри пачки). При повторе всей пачки **mtime не продвигается и summary не сворачивается повторно**; в summary участвует только основной transcript (`subpath is None`) |
| `projects` | `() -> list[str]` | реально существующие в БД `project_key`. **SDK выводит его из cwd; перед запросом сверяйтесь с этим методом, не угадывайте** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **синхронный, payload не читает**, только одна строка из meta. Нужен для «продолжения по тому же пути»: resume несуществующей сессии падает только после старта дочернего процесса |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | какого размера контекст модель фактически видела на последнем ходу; если не нашлось — `0`. Сканирует с конца только последние `scan` записей; учитываются все три составляющие `input + cache_read + cache_creation` (если смотреть только `input_tokens`, оценка будет сильно занижена) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | сортировка по seq; если строк нет — `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | только основные transcript'ы |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | перечисляет сводки сессий |
| `delete` | `async (key) -> None` | при удалении основного transcript'а **каскадно удаляет и дочерние агентские**, чтобы не оставалось сирот |
| `list_subkeys` | `async (key) -> list[str]` | перечисляет дочерние transcript'ы этой сессии |
| `close` | `() -> None` | закрывает соединение |

Внутренний `_next_mtime` гарантирует **строгую монотонность** — `list_sessions` и sidecar со summary используют
эти общие часы, иначе быстрый путь проверки staleness в SDK ошибётся.

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
| `min_chars` | `int` | `2000` | короткие результаты обрезать не стоит |
| `spill_dirname` | `str` | `".flower/spill"` | **относительно `workspace`, обязан быть внутри рабочей области** — иначе `Read` агента до него не достанет |
| `enabled` | `bool` | `True` | при `Runtime(trim=False)` здесь `False` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | формирует ту самую строку-указатель, заменяющую текст |

**Два каталога spill — это не один и тот же каталог.** `spill_guard` пишет в `<workbench.root>/spill/`
(может быть вне рабочей области); `TrimPolicy.spill_dirname` — в `<workspace>/.flower/spill/`
(**обязан быть внутри рабочей области**).
Они соответствуют «обрезать на месте» и «обрезать при resume», разные каталоги здесь сделаны намеренно,
не сводите их в один.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Политика устаревания результатов [эфемерных команд](glossary.md#一次性命令).

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `enabled` | `bool` | `True` | если выключить, пометка устаревания не делается вообще |
| `keep_recent` | `int` | `6` | последние N освобождаются от пометки. **Существенно меньше, чем 20 у `TrimPolicy`** |
| `max_chars` | `int` | `2000` | что длиннее — пропускается, этим займётся архивирование `TrimPolicy` |
| `text` | `str` | см. сигнатуру | текст замены, два плейсхолдера: `{cmd}` и `{age}` |

| Метод | Сигнатура | Описание |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | подставляет в `text` и формирует замену текста |

**Действует только на результаты инструмента `Bash`**, и команда должна попадать в белый список эфемерных команд.
**`Read` сюда не входит**: содержимое файла со временем не искажается настолько, чтобы вводить в заблуждение.
Устаревшее содержимое **в spill не пишется**, оно просто выбрасывается.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Определяет, является ли команда Bash [эфемерной командой](glossary.md#一次性命令).
**Проверка пропуска в `delegate_guard` и проверка устаревания при обрезке используют одну и ту же функцию** —
множество команд, которые координатор может запускать сам, обязано совпадать с множеством команд, чьи результаты
помечаются как устаревшие. Пропускать без обрезки — устаревший `git status` навсегда займёт контекст и будет вводить
в заблуждение; обрезать без пропуска — координатор отправит subagent за одной командой `ls`, отдав стартовую
стоимость 4.3k ради десятков символов.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `cmd` | `str` | обязательный, позиционный | полная командная строка |

Порядок проверок:

1. Пусто / только пробелы → `False`.
2. Подстановка команд (`$(`, обратные кавычки, `<(`, `>(`) или конструкция «меняет состояние» → `False`.
3. После снятия безопасных перенаправлений (`2>&1`, `&> /dev/null` и т. п.) всё ещё содержит `>` или `<` → `False`.
4. После снятия `&&` / `||` / `;` / `|` остался одиночный `&` (запуск в фоне) → `False`.
5. Разбиваем по `&&` / `||` / `;` / `|`, и **каждый фрагмент обязан попасть в белый список**.

Крупные группы глаголов белого списка: только читающие подкоманды `git` (`status` `diff` `log` `show` `branch`
`rev-parse` и др.), информация о каталогах и системе (`ls` `pwd` `df` `du` `date` `whoami` `env` и др.),
процессы и контейнеры (`ps` `top` `lsof` `docker ps` `kubectl get` и др.), просмотр файлов
(`cat` `head` `tail` `wc` `stat` `find` `tree`), поиск путей (`which` `whereis` `command -v` `type`),
обработка текста (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` и др.).

Даже если глагол в белом списке, такие конструкции всё равно блокируются: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` и `print >` внутри `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

Первая версия огульно отвергала все составные команды, и **на практике это полностью убивало glance**
(все три попытки координатора были заблокированы), поэтому проверку переделали на пофрагментную.

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
| `path` | `str \| Path` | обязательный | файл БД |
| `workspace` | `str \| Path` | обязательный | база для каталога spill |
| `policy` | `TrimPolicy \| None` | `None` | если не задано, используется `TrimPolicy()` по умолчанию |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | если не задано, используется `EphemeralPolicy()` по умолчанию |

Публичные атрибуты: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Порядок в `load()`: `super().load()` → очистка `last_report` → если `ephemeral.enabled`, то `expire()` →
если `policy.enabled`, то `trim()`. **При `enabled=False` соответствующий шаг пропускается целиком.**

| Метод | Описание |
|---|---|
| `expire(entries)` | у устаревших зависящих от времени результатов `Bash` **заменяется только текст, блок сохраняется**. Команда ищется в `tool_use` предыдущего сообщения assistant; `isCompactSummary` / `isMeta` пропускаются; что длиннее `max_chars` — пропускается (этим займётся `trim`); последние `keep_recent` освобождаются. Записывает `last_report["expired"]` |
| `trim(entries)` | текст `tool_result` размером `>= min_chars` сбрасывается в `<workspace>/<spill_dirname>/<первые 16 символов sha256>.txt`, содержимое блока заменяется указателем; последние `keep_recent` освобождаются. Записывает `cleared` / `kept` / `chars_saved` в `last_report` |

**Обрезается только чистый текст**: блоки `image` / `document` остаются как есть.

**Две структурные красные линии**: сам блок `tool_result` **обязан остаться на месте**, менять можно только content
(пропал хотя бы один — получаем «Missing Tool Result Block»); записи `isCompactSummary` трогать нельзя.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Рендерит `store.last_report` в одну строку на китайском, для логов UI.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | обязательный, позиционный | подкласс `PruningSessionStore` тоже принимается |

Три варианта вывода: ничего не делали → `"未裁剪"`; только устаревание → `"N 个时效性结果标记为过期"`;
иначе `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, где X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | убирать синтетические сообщения об ошибках API (мусор после обрыва связи) |
| `neutralize_interrupts` | `bool` | `True` | заменять `tool_result`, оставшиеся после прерывания, нейтральным пояснением |
| `interrupt_text` | `str` | см. сигнатуру | текст нейтрального пояснения |
| `keep_denials` | `int` | `1` | сохранять последние N отклонённых вызовов инструментов |

Обоснование `keep_denials`: отклонённый вызов вообще не выполнялся, информации в результате нет, а места занимает
немало (измерено: один такой — 273 символа = 93 символа текста отказа + 180 символов **исходного мёртвого текста команды**).
Важнее другое: **он вводит модель в заблуждение** — на практике координатор, прочитав несколько строк
«не используй Bash напрямую», перестал пробовать даже разрешённый `git status`, выучив беспомощность.
**По умолчанию оставляется 1, а не 0**: самый свежий отказ мешает модели раз за разом в пределах одного хода
повторять одну и ту же заблокированную команду.

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

**Store по умолчанию для `Runtime`.**

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `str \| Path` | обязательный | файл БД |
| `workspace` | `str \| Path` | обязательный | база для каталога spill |
| `policy` | `TrimPolicy \| None` | `None` | политика trim |
| `prune` | `PrunePolicy \| None` | `None` | политика prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | политика устаревания |

Публичных атрибутов, помимо родительских, три: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (сначала `expire` + `trim`) → `self.prune(entries)`. `prune` делает три вещи:

1. **Убирает слишком старые отклонённые вызовы**: определяет их по структурной метке harness'а
   `toolDenialKind == "permission-rule"` (надёжнее, чем сопоставление текста отказа), сохраняет последние
   `keep_denials`, у остальных убираются блоки `tool_use` **и** `tool_result` вместе.
   Если в одном сообщении assistant несколько `tool_use`, **убирается только попавший под условие**, иначе
   получим «Missing Tool Result Block»; текстовые и thinking-блоки сохраняются.
2. **Убирает синтетические сообщения об ошибках API.** В SQLite они остаются как есть, просто не скармливаются обратно.
3. **Заменяет `tool_result`, оставшиеся после прерывания, нейтральным пояснением** — меняется только текст,
   запись не удаляется.

**Единственная структурная красная линия**: transcript — это односвязная цепочка по `parentUuid`, убрав запись,
обязательно нужно перевесить её детей на ближайшего живого предка.
В параметр `entries` внутреннего `relink` **обязательно передаётся полный список (включая те, что надо убрать)**,
фильтрацию он делает сам: если вызывающая сторона отфильтрует заранее, цепочка порвётся в этом месте и вся
предыдущая история будет потеряна (**уже наступали: если удаляемая запись в конце — ошибка не проявляется,
если в середине — всё ломается**).

**Порядок параметров отличается от родительского**: у родителя `(path, workspace, policy, ephemeral)`,
у подкласса `(path, workspace, policy, prune, ephemeral)` — **четвёртый позиционный параметр сменился
с `ephemeral` на `prune`**, при передаче по позиции произойдёт молчаливый сдвиг. Передавайте только по имени.

---

## Устойчивость {#韧性}

Исходник: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

При обрыве сети — висеть и ждать, а не падать с ошибкой. Четыре экспорта: одна dataclass с политикой
+ три функции проверки, которые можно использовать по отдельности.

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
| `enabled` | `bool` | `True` | если выключить, никакой сбой не будет повторяться |
| `max_attempts` | `int` | `6` | **включая первую попытку** |
| `base_delay` | `float` | `4.0` | база backoff, секунды |
| `max_delay` | `float` | `120.0` | верхняя граница backoff, секунды |
| `probe_timeout` | `float` | `5.0` | таймаут одной проверки |
| `probe_interval` | `float` | `15.0` | сколько ждать между двумя проверками |
| `max_offline_wait` | `float` | `3600.0` | сколько максимум висеть в ожидании, по умолчанию 1 час |
| `retry_unknown` | `bool` | `True` | повторять ли ошибки, которые не удалось классифицировать |
| `resume_prompt` | `str` | см. сигнатуру | что сказать при продолжении. **Намеренно не содержит никаких деталей ошибки** — модели нужно знать «тебя прервали, продолжай», а не то, был это `ENOTFOUND` или 503 |

| Метод | Сигнатура | Описание |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)`, умноженное на `0.75 + random()*0.5` (джиттер ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, либо `kind == "unknown"` при `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | висит и ждёт возврата сети. Вернулась — `True`, превышено `max_offline_wait` — `False`. `notify` — колбэк `(str) -> None`, вызывается по одному разу **при первой недоступности** и **при восстановлении** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Делит текст ошибки на три класса: `"transient"` / `"fatal"` / `"unknown"`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `text` | `str \| None` | обязательный, позиционный | исходный текст сообщения об ошибке. Если пусто, возвращается `"unknown"` |

**Сначала проверяется fatal, потом transient** — в текстах вроде 401 часто встречается слово `connection`,
и при обратном порядке процесс будет ждать вечно.

| Класс | По чему срабатывает |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

Хост и порт, которые нужно проверять, берутся из `ANTHROPIC_BASE_URL`, по умолчанию `https://api.anthropic.com`;
порт по умолчанию `80` (http) или `443`.

**При использовании своего шлюза проверять нужно именно его** — доступность `api.anthropic.com`
ничего не говорит о доступности шлюза.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `host` | `str` | обязательный, позиционный | имя хоста |
| `port` | `int` | обязательный, позиционный | порт |
| `timeout` | `float` | `5.0` | секунды |

**Только DNS (`getaddrinfo`) + TCP-рукопожатие**: HTTP не отправляется, учётные данные не передаются,
**денег не тратится**. Любое исключение считается недоступностью.

---

## События и взаимодействие {#事件与交互}

Исходники: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[Событие](glossary.md#事件) — это стабильная структура, в которую сплющивается поток сообщений SDK.
**[Слой взаимодействия](glossary.md#交互层) знает только `Event` и не импортирует ни одного типа SDK** —
это и есть граница, благодаря которой смена UI не требует правки ядра. См. [Смена слоя взаимодействия](../guide/interaction.md).

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
| `raw` | `Any` | `None` | исходный объект SDK, для случаев, когда нужно копнуть глубже |

`__str__`: для `tool_call` это `f"[{tool}] {text}"`, иначе `text`, а если `text` пустой — `f"<{kind}>"`.
Так что `print(ev)` читается напрямую.

Всего `EventKind` — **15**:

| kind | Кто отправляет | Описание |
|---|---|---|
| `text` | `normalize` | основной текст assistant |
| `thinking` | `normalize` | блок размышлений |
| `tool_call` | `normalize` | вызов инструмента. `text` — сводка по `file_path` / `command` / `pattern`, обрезано до 200 символов |
| `tool_result` | `normalize` | результат инструмента. `text` обрезан до 500 символов, в payload есть `tool_use_id` / `is_error` |
| `task` | `normalize` | три вида сообщений Task, `text` — имя класса сообщения |
| `system` | `normalize` | остальные системные сообщения, `text` — subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, в payload есть `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | синтетическое сообщение об ошибке API, в payload `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Текст здесь — это ввод, а не вывод модели**, поэтому он не попадает в `StepResult.text` |
| `unknown` | `normalize` | то, что не распознано |
| `retry` | `Runtime` | уведомление о повторе |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | в payload `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | вопрос, **а также «то, что человек сказал сам»** |

**Последние четыре не создаются `normalize()`.**

В `payload` всех событий assistant / user есть:

| Ключ | Тип | Описание |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | есть только когда `subagent` истинно |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Это единственный источник критерия [handoff](glossary.md#换代)** и то число, которое при long-horizon запуске нужно видеть в первую очередь |

**Один и тот же kind `ask` несёт и «вопрос», и «то, что человек сказал сам».** У второго
`payload["kind"] == "mail"`, и **нет `options` / `remaining`**. UI обязан сначала проверить
`payload.get("kind")` и только потом решать, как рендерить, иначе одна фраза повиснет как
вопрос, ожидающий ответа.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Сплющивает одно сообщение SDK в от 0 до N `Event`.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `message` | `Any` | обязательный, позиционный | любой объект сообщения SDK |

Ключевые ветки:

- **Синтетическое сообщение об ошибке API** (`isApiErrorMessage=True` или `model == "<synthetic>"`) →
  один `Event("error", payload={"synthetic": True})`. **Так сделано намеренно** — иначе текст об
  обрыве связи попал бы в `StepResult.text` как основной текст и был бы передан в следующий шаг.
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
| `options` | `list[str]` | `[]` | варианты. Человек может ничего не выбрать и написать своё |
| `asked_at` | `float` | `time.time()` | момент вопроса |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | текст ответа |

| Член | Сигнатура | Описание |
|---|---|---|
| `waited_s` | `@property -> float` | сколько уже прождали |
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

**Внутрипроцессный MCP server** (два инструмента) + набор методов для UI. Со стороны модели видны
только `mcp__human__ask` и `mcp__human__inbox`. Все параметры конструктора — keyword-only.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | выход в режиме **push**. Если задан, `Workflow.run` уже не подключает свой |
| `max_asks` | `int \| None` | `None` | **без ограничения по числу**. Число задаёт жёсткую квоту, `0` = запрещено спрашивать (полностью автоматический режим / CI). При превышении инструмент **сразу отказывает, не блокируя** |
| `timeout_s` | `float \| None` | `1800.0` | 30 минут. `None` = ждать вечно; **`<= 0` = не ждать, все вопросы сразу уходят в пустоту** |
| `log_path` | `str \| Path \| None` | `None` | вопросы и ответы **дописываются** на диск и не занимают контекст |
| `amend_path` | `str \| Path \| None` | `None` | то, что человек сказал в середине запуска, дописывается в этот файл (обычно это и есть brief). **Без записи на диск это не переживёт границу шага** — следующий шаг это новая сессия, читающая только замороженный документ |
| `over_budget_text` | `str` | константа модуля | что ответить модели при превышении квоты |
| `timeout_text` | `str` | константа модуля | что ответить модели при таймауте |
| `declined_text` | `str` | константа модуля | что ответить модели, когда вопрос пропущен |

Публичные атрибуты: восемь одноимённых с параметрами конструктора плюс `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**исключения, брошенные колбэком UI, собираются здесь и не прерывают запуск**).

| Член | Сигнатура | Описание |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | напрямую передаётся в `AgentSpec.mcp_servers`. **Имя ключа обязано совпадать с именем server**, поэтому оно выдаётся вместе |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | зависает в ожидании человека. **Кроме `CancelledError` никогда не бросает исключений** — отсутствие ответа тоже ответ, различайте по `ask.state` |
| `send` | `(text: str) -> Mail \| None` | человек говорит фразу сам. **Можно вызывать из любого потока**. Агента не прерывает; внутри автоматически вызывает `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | дописывает в `amend_path`. Возвращает, была ли запись фактически (не настроен путь, пустой текст, `OSError` — всё это `False`) |
| `pending_mail` | `() -> list[Mail]` | не забранные mail |
| `remaining` | `@property -> int` | сколько вопросов ещё можно задать. **При `max_asks=None` возвращает `-1`**, не 0 и не бесконечность |
| `pending` | `() -> list[Ask]` | вопросы, висящие в ожидании ответа |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | для режима **pull**. При таймауте возвращает `None`, при отмене бросает |
| `answer` | `(ask_id: str, text: str) -> bool` | ответить. `False` = этот вопрос больше не ждёт ответа (таймаут / уже отвечен) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | пропустить, пусть модель решает сама |
| `transcript` | `() -> str` | markdown с записью вопросов и ответов |

**Из двух способов выберите один**: **push** — конструировать `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` подключает провод автоматически только когда `channel.on_event is None`, так что переданный вами колбэк не будет перезаписан.

**Межпоточность**: `answer` / `decline` / `send` внутри идут через `loop.call_soon_threadsafe`,
вызов из web-бэкенда / потока ввода TUI — норма.

Три семантики «0 / None» различны, не путайте: `max_asks=None` = без лимита, `max_asks=0` = спрашивать нельзя;
`timeout_s=None` = ждать вечно, `timeout_s<=0` = таймаут немедленно; `remaining` при `max_asks=None` равно `-1`.

Не экспортируемый, но встречающийся в возвращаемых значениях `Mail` — это dataclass с полями `id` / `text` / `sent_at` / `taken`.

---

## Родословная {#血缘}

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

Межпроцессная запись «какой шаг какую сессию использовал»; [непрерывность](glossary.md#接续) через неё находит,
до чего дошли в прошлый раз. Файл — `<run_dir>/lineage.json`.

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `path` | `Path` | обязательное | путь к файлу родословной |
| `workspace` | `Path` | обязательное | рабочая область. `__post_init__` делает resolve |
| `steps` | `dict[str, str]` | `{}` | имя шага → `session_id` |
| `woke` | `int` | `0` | сколько раз пробуждались |

| Член | Сигнатура | Описание |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | читает `<run_dir>/lineage.json`. **Файл не существует, не читается или поле `workspace` не совпадает — во всех случаях возвращается пустая, без ошибки** |
| `remember` | `(step: str, session_id: str) -> None` | запоминает соответствие и **сразу пишет на диск**. Пустой step или пустой sid — сразу возврат |
| `bump` | `() -> int` | счётчик пробуждений +1, запись на диск, возврат нового значения (при первом запуске это `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **перемещает** файл родословной + `extra` в `<into>/<YYYYmmdd-HHMMSS>/` и обнуляет `steps` / `woke`. **Перемещение, а не удаление** |

Запись на диск идёт через атомарную подмену `tmp.replace(path)`; `OSError` молча проглатывается — неудача записи не должна уносить с собой этот запуск.

**`workspace` — это охранник**: `project_key` у SDK выводится из пути рабочей области, после копирования каталога старые `session_id` не находятся,
поэтому при несовпадении пути считаем, что родословной нет.

При загрузке родословной `Workflow.run` проверяет каждую запись через `runtime.has_session(sid)` — жива ли она ещё в базе, и использует только живые:
файл родословной может пережить `sessions.db`.

---

## Минимальные рабочие примеры {#示例}

Все пять запускаются как есть. Предпосылки: установлен `claude-agent-sdk`, доступен `ANTHROPIC_API_KEY` или `ANTHROPIC_AUTH_TOKEN`
(иначе `Runtime(...)` бросит `RuntimeError` уже при конструировании).

### Один агент, один шаг {#示例-单-agent}

Минимальный скелет: объявить `AgentSpec`, создать `Runtime`, `await rt.run(...)`, прочитать `StepResult`.

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

Все параметры `Runtime` — **keyword-only**; у `rt.run()` `spec` и `prompt` позиционные, остальные keyword-only.
По умолчанию у `AgentSpec` `allowed_tools=["Read", "Glob", "Grep"]` и `delegate_only=False`,
поэтому `Runtime` автоматически навесит [`whitelist_guard`](#whitelist-guard) и заблокирует `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Координатор + исполнитель {#示例-协调}

Ничего не делающий руками [координатор](glossary.md#协调者) с одним работающим [исполнителем](glossary.md#执行者).
Это первый уровень экономии контекста в flower.

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
    # без включённого workbench у Bash/Write координатора нет ни одного перехватывающего hook.
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

Первые два параметра `worker()` позиционные: `description` (по нему координатор выбирает исполнителя) и `prompt` (его system prompt,
к которому дальше автоматически приклеивается `WORKER_RULES`). У `coordinator()` позиционные первые три: `name`, `instructions`, `workers`.

### Свой Workflow {#示例-workflow}

Два шага, второй впрыскивает результат первого в собственный prompt — дёшево, изолированно, без общей сессии.

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
        # Новая сессия: питается только тем, что есть в prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Новая сессия + результат предыдущего шага впрыснут в prompt (дёшево, защищает от загрязнения)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Хотите продолжить разговор в той же сессии — напишите resume_from="造句"; нужна ветка — добавьте fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (когда reduce не задан)
    print(ctx["_sessions"])            # имя шага -> session_id
    print(ctx.get("_failed_at"))       # при on_fail="stop" — на каком шаге упало


asyncio.run(main())
```

Первые три поля `Step` (`name` / `spec` / `prompt`) позиционные, `steps` у `Workflow` тоже.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` позиционный, оба колбэка keyword-only.
**Обратите внимание: `continuous=True` — значение по умолчанию**: при втором запуске с тем же `run_dir` + той же `workspace`
даже шаги с `resume_from=None` продолжат ту же сессию, что и в прошлый раз.

### Добавляем стражу цели {#示例-目标}

Сначала пусть [судья](glossary.md#判定者) зафиксирует цель и список критериев, а затем рабочий шаг примет вердикт —
не прошёл, значит повтор с обратной связью, максимум три круга.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = полностью автоматически: все вопросы сразу уходят в пустоту, никто не притворяется, что ждёт человека
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
        # Без clarify_step залейте его сами, иначе он увидит только "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: объект Goal
    print(ctx["_verdict"])     # VERDICT_KEY: последний Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: сколько кругов пройдено
    print(ctx.get("_aborted")) # причина StepAbort (когда цель недостижима и человек не отвечает)


asyncio.run(main())
```

`with_goal` подменяет только `gate` / `on_reject` / `retries`, остальные поля переносятся как есть через `dataclasses.replace`.
Судья — это **отдельная сессия**: внутри `gate` отдельно вызывается `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
а `resume` всегда `None`.

### Меняем слой взаимодействия {#示例-交互层}

Чтобы заменить терминал на Web / TUI / HTTP, нужно изменить только две вещи: функцию, которая рендерит `Event`, и корутину, которая забирает вопросы.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Рендерит Event в ваш собственный UI — это единственное, что нужно менять."""
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
    """Забор вопросов в pull-режиме. При переходе на web-бэкенд / HTTP-сервис менять нужно только эту корутину."""
    while True:
        ask = await ch.next_ask()          # без timeout ждёт бесконечно
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # или ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime использует workbench, уже созданный самим workflow — не собирайте второй
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push и pull — **выберите один**: push это конструирование `HumanChannel(on_event=...)`, pull это `await channel.next_ask()`.
`Workflow.run` подключает провод автоматически только когда `channel.on_event is None`, так что переданный вами `on_event` не будет перезаписан.
`answer()` / `decline()` / `send()` / `interrupt()` **можно вызывать из других потоков**.

---

## Ловушки и типичные ошибки {#陷阱}

Порядок — по вероятности напороться, не по модулям. У каждого пункта есть подтверждение на практике.

### Сборка {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = у главного потока нет ни одной стены.**
   `delegate_guard` навешивается только при наличии workbench, а `whitelist_guard` пропускается из-за `delegate_only=True`.
   Используете координатора — включайте workbench. Подробности в [Runtime](#runtime).
2. **У workbench два возможных места, не перепутайте пути.** `Runtime(workbench=True)` кладёт его в `<run_dir>/workbench`;
   `Workbench(ws)` по умолчанию — в `<ws>/.flower`. Собирая `brief_path` руками, пишите по второму варианту, иначе
   **brief запишется в каталог A, а впрыснутый индекс просканирует каталог B — и ошибки не будет**.
   Правильно так: workflow сам делает `Workbench(...).ensure()` и вешает результат на `Workflow.workbench`,
   а потом **тот же самый объект** передаётся в `Runtime(workbench=wb)`.
3. **`allowed_tools` — не исключающий белый список, а список того, что не требует одобрения.** Модель по-прежнему может вызвать инструмент, которого там нет.
   «Отсутствие пишущих инструментов» у `clarify()` / `judge()` держится на hook [`whitelist_guard`](#whitelist-guard).
   А у `coordinator()` по умолчанию `permission_mode="acceptEdits"` — кто передаст это значение в
   `clarify()` / `judge()`, тот снимет защиту.
4. **`disallowed_tools` действует на уровне сессии** и запретит одноимённые инструменты и у subagent.
5. **Индекс workbench не попадает в subagent.** «Длинные результаты писать в `artifacts/`» координатор обязан пересказать в task brief —
   это единственный канал.
6. **`Runtime(...)` без учётных данных бросает `RuntimeError` уже на этапе конструирования**, а не при `run()`.
7. **`Runtime.run_id` обязан быть уникальным для каждого экземпляра.** `manifest.json` дедуплицирует по полю `run`, и при совпадении двух id
   тот, кто пишет позже, примет строки другого за «свои прошлые» и удалит их.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` — значение по умолчанию**, `resume_from=None` не означает «совершенно новая сессия».
   Нужна новая каждый раз — задайте `continuous=False` явно. **Смена имени шага равносильна обрыву родословной.**
9. **`with_goal(rounds=N)` — общее число кругов, а не дополнительных**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` не пишет `ctx[step.name]`** — ниже по потоку `lambda ctx: ctx["某步"]` даст `KeyError`.
    Хотите идти дальше с неполным результатом — используйте `on_fail="continue"`.
11. **`resume_from`, указывающий на не запущенный / упавший шаг, бросает `ValueError`**, а не молча пропускается.
12. **`Step.reduce` обязан быть синхронной функцией; `gate` / `when` / `on_reject` могут быть async.**
13. **`fork=True` без `resume` молча не действует.** `Workflow` никогда не передаёт `resume_at`;
    откат по сообщениям возможен только прямым вызовом `Runtime.run`.
14. **Когда вы сами управляете `Runtime`, `on_session` необходимо снять до gate**, иначе сессия судьи будет записана
    в родословную рабочего шага. `Workflow` гарантирует это через `try/finally`.
15. **`step_name` определяет ключи в manifest и родословной.** `Workflow` добавляет суффиксы `#retryN` / `#roundN`,
    судья добавляет `#轮次` — **имена с суффиксами не попадают в межпроцессную родословную**, и это один из способов, которым реализовано
    «судья всегда новая сессия».

### Роли {#陷阱-角色}

16. **`clarify(max_turns=<маленькое число>)` превращает «вопросы без ограничения по числу» в пустые слова** — каждый вопрос это один круг.
17. **У `goal_step()` нет параметра `can_run`**, `can_run=True` можно передать только через `**spec_kw`.
    Если не передать, судья, ставящий цель, не получит `Bash`, и пункт `JUDGE_RULES` «сначала разберись, в каком ты окружении» выполнить не сможет.
18. **`judge(can_run=True)` даёт судье возможность менять рабочую область** — `whitelist_guard` выводится из `allowed_tools`,
    и раз дали `Bash`, то `Bash` пропускается (`Write`/`Edit` по-прежнему блокируются, но сам `Bash` умеет писать файлы). Нужна абсолютная нейтральность — не включайте.
19. **`worker(isolate=True)` требует, чтобы workspace был git-репозиторием**, иначе инструмент `Agent` прямо сообщит
    `"not in a git repository"`, без молчаливой деградации. Кроме того, метка изоляции — это Python-атрибут,
    и **`dataclasses.replace()` над `AgentDefinition` её теряет**.
20. **При прямом конструировании `AgentDefinition` параметры в camelCase**: `maxTurns`, `permissionMode`.
    `worker()` уже сделал преобразование за вас.

### Handoff и контекст {#陷阱-换代}

21. **Когда включён handoff, auto-compact принудительно выключается, страховки нет.** Поэтому у шага записи документа handoff обязательно должен быть путь деградации.
    Хотите сохранить auto-compact — задайте `AgentSpec.compact` явно.
22. **Слишком маленький `HandoffPolicy.window` приведёт к бесконечным handoff и сжиганию денег.** Единственный тормоз — `max_generations=8`.
    С другой стороны, **`default_window()` при незаданных обеих переменных окружения тоже возвращает `1_000_000`** —
    завышенную оценку подхватывает `is_overflow()` (превращая её в один деградированный handoff); это не жёсткая ошибка, но handoff того поколения будет деградированным.
23. **Без workbench документ handoff не пишется на диск.** Он всё равно передаётся принимающему через prompt, но человек потом его не найдёт.

### Хранилище {#陷阱-存储}

24. **`Runtime(trim=False)` (по умолчанию) не означает «ничего не чистится».** store всегда `PruningSessionStore`,
    а `trim=False` отключает только trim крупных результатов; **удаление остатков от обрывов, удаление отклонённых вызовов, нейтрализация остатков прерываний и истечение срока актуальности выполняются по-прежнему.**
25. **Два каталога spill — это не одно и то же**: `spill_guard` кладёт в `<workbench.root>/spill/`,
    а `TrimPolicy.spill_dirname` — в `<workspace>/.flower/spill/` (обязательно внутри рабочей области).
26. **Четвёртый позиционный параметр `PruningSessionStore.__init__` — это `prune`, а не `ephemeral`**,
    в отличие от родительского класса. Передача по позиции молча сдвинет аргументы.

### Документы и взаимодействие {#陷阱-文书}

27. **Когда `Verdict` не может разобрать заключение, `state=""`, `ok=False`, и это ни в коем случае нельзя считать достижением цели.**
    Кроме того, «无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» — всё это относится к `unreachable`
    и запускает ветку «остановиться и спросить человека», а не «ещё один круг».
28. **`Brief.parse`, встретив незакрытую ограду кода, выбрасывает всё, что идёт после неё** — если вывод модели обрезан,
    последующие разделы вообще не распарсятся, `complete()` даст `False`, и gate отправит на повтор.
29. **`Brief.load` считает `"(未填)"` пустым.** Если при ручной правке brief вы скопировали текст-заполнитель, этот раздел всё равно считается отсутствующим.
30. **Три семантики «0 / None» у `HumanChannel` различны**: `max_asks=None` без лимита, `max_asks=0` спрашивать нельзя;
    `timeout_s=None` ждать вечно, `timeout_s<=0` таймаут немедленно; `remaining` при `max_asks=None` возвращает **`-1`**.
31. **`Event("ask")` несёт одновременно вопросы и то, что человек сказал сам**, у второго `payload["kind"] == "mail"`. UI должен проверять это первым делом.
32. **`Workflow.run` подключает провод автоматически только когда `channel.on_event is None`** —
    если вы сами сконструировали `HumanChannel(on_event=...)`, события-вопросы не попадут одновременно и в выход `on_event` у workflow.
