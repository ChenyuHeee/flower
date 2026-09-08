# API Python

Esta página esgota os **62 símbolos públicos** do `__all__` de topo de `flower`: assinaturas, parâmetros, valores padrão, semântica,
atributos e métodos públicos. Depois de ler, não é preciso abrir o código-fonte para procurar parâmetros.

A organização segue **aquilo com que você se importa**, não os arquivos de módulo — se quer saber "como impedir que o [coordenador](glossary.md#协调者)
faça o trabalho por conta própria", vá para a [camada de hooks](#hook); se quer saber "como o resultado do passo anterior chega ao próximo", vá para [workflow](#流程).
A terminologia segue estritamente o [glossário](glossary.md).

Versão `0.1.0`, depende de `claude-agent-sdk>=0.2.152`. Todas as assinaturas correspondem literalmente ao código-fonte.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## O que tem nesta página {#索引}

| Assunto | Símbolos |
|---|---|
| [Rodar um agent](#运行时) | `Runtime` `StepResult` |
| [Encadear vários passos](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Construir um papel](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Escrever definições de agent à mão](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documentos estruturados](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Barrar ferramentas, cortar resultados, isolar](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [O diretório de trabalho do spill](#工作台) | `Workbench` |
| [Como e o que a sessão armazena](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [O que fazer quando cai a rede](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Trocar a UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Retomar entre processos](#血缘) | `Lineage` |

## Seis padrões que mordem {#危险默认值}

Estes seis não são detalhes marginais; são os seis acidentes mais comuns. Cada um tem explicação completa na seção correspondente.

| Padrão | Consequência | Detalhes |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` da main thread ficam **sem um único hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Força `CompactPolicy(mode="no_summary")` no spec, ou seja, `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Passos com `resume_from=None` ainda retomam aquela sessão anterior entre processos | [Workflow](#workflow) |
| `build_options(fork=True)` sem `resume` | Falha silenciosamente, sem erro | [build_options](#build-options) |
| `clarify(max_turns=<número pequeno>)` | Transforma "perguntar sem limite de vezes" em conversa fiada — cada pergunta é um turno | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | É a nível de sessão; proíbe também nos subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Código-fonte: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` é o núcleo de execução. Ele detém o workspace, o [session store](glossary.md#会话存储), a [workbench](glossary.md#工作台),
a política de [resiliência](glossary.md#韧性) e a política de [handoff](glossary.md#换代); para fora, tem apenas um verbo: `run` um passo.
Retentativa, continuação após interrupção, handoff quando o contexto enche — tudo acontece dentro dessa única chamada.

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

Os parâmetros do construtor são **todos keyword-only** (`*` logo no início), e `workspace` é obrigatório.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | obrigatório | O `cwd` do agent. É resolvido na construção e recebe `mkdir(parents=True, exist_ok=True)`. O `project_key` do SDK é derivado dele — se o diretório for copiado para outro lugar, o `session_id` antigo deixa de ser encontrável |
| `run_dir` | `str \| Path` | `"runs"` | Guarda `sessions.db`, `manifest.json`, `lineage.json` e, quando `workbench=True`, a workbench padrão. Também é resolvido e criado com mkdir |
| `portable` | `bool` | `True` | Repassado para `build_options(portable=)`, ou seja, `setting_sources=[]`: não lê o `~/.claude/` da máquina hospedeira, nem o `.claude/` do projeto. Ver [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Se receber uma instância, usa direto; se receber `bool`, vira `TrimPolicy(enabled=bool(trim))`. **Desligar só significa não fazer trim de resultados grandes; o prune continua acontecendo** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Mesma regra de conversão. Forma par com `coordinator(glance=True)` — se você libera a main thread para rodar `git status`, precisa garantir que aquele resultado expire |
| `keep_denials` | `int` | `1` | Passado para `PrunePolicy(keep_denials=)`. Mantém as N chamadas de ferramenta negadas mais recentes; as mais antigas são removidas junto com chamada e resultado |
| `workbench` | `Workbench \| bool` | `False` | Se receber uma instância, usa direto; se receber `True`, cria `Workbench(workspace, home=run_dir / "workbench")` (**por padrão fica fora do workspace**). Em seguida chama `refresh()` imediatamente |
| `spill_threshold` | `int \| None` | `4000` | A partir de quantos caracteres um resultado de ferramenta vai para [spill](glossary.md#落盘). `None` ou `0` = não instala o `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Mesma regra de conversão |
| `handoff` | `HandoffPolicy \| bool` | `True` | Mesma regra de conversão |

**O session store é fixo no código**: sempre
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Os parâmetros do construtor **não oferecem** ponto de entrada para trocar de backend — para trocar, construa seu próprio `AgentSpec` + `build_options(session_store=...)`,
ou sobrescreva `rt.store` depois de construir.

Os dois últimos passos da construção são `load_dotenv()` e `check_credentials()`, e **este último faz `raise RuntimeError` em caso de erro**.
Sem credenciais, a explosão acontece já na construção, não ao chegar em `run()`.

!!! warning "`workbench=False` + `coordinator()` = a main thread fica sem nenhuma barreira"
    O `delegate_guard` só é instalado dentro de `workbench_hooks`, e `workbench_hooks` só é chamado quando `self.workbench is not None`;
    o `whitelist_guard`, por sua vez, é pulado por `if not spec.delegate_only`. E `coordinator()` sempre define
    `delegate_only=True` e, por padrão, `glance=True` dá acesso a `Bash`.

    **Conclusão: com um coordenador em `Runtime(workbench=False)`, seus `Bash`/`Write`/`Edit` não são barrados por hook nenhum.**
    Ao usar `coordinator()`, ligue a workbench — `Runtime(..., workbench=True)` ou passe uma instância de
    `Workbench`.

!!! warning "`handoff=True` (padrão) força o desligamento do auto-compact"
    Em `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    o que no subprocesso vira `DISABLE_AUTO_COMPACT=1`. A razão é que, com os dois mecanismos ligados ao mesmo tempo, não dá para dizer quem causou a queda do contexto.

    **Custo: o passo que escreve o handoff precisa ter um caminho degradado** (`handoff.degraded`), porque não há mais compact como rede de segurança.
    Para manter o auto-compact, defina `AgentSpec.compact` explicitamente (se o spec já traz o seu, ele é respeitado e não sobrescrito).

#### Atributos públicos {#runtime-属性}

| Atributo | Tipo | Descrição |
|---|---|---|
| `workspace` | `Path` | Workspace após resolve |
| `run_dir` | `Path` | Diretório de run após resolve |
| `portable` | `bool` | Guardado como veio |
| `store` | `PruningSessionStore` | Session store. Para trocar de backend só sobrescrevendo após a construção |
| `resilience` | `Resilience` | Instância normalizada |
| `handoff` | `HandoffPolicy` | Instância normalizada |
| `workbench` | `Workbench \| None` | É `None` quando `workbench=False` |
| `spill_threshold` | `int \| None` | Guardado como veio; em `_attempt` é passado para `workbench_hooks` |
| `results` | `list[StepResult]` | Cada passo executado neste processo, anexado em ordem |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Precisa ser único por instância** — o `manifest.json` deduplica pelo campo `run`, e quando dois ids colidem, o que escreve depois apaga as linhas do outro achando que são as suas da vez anterior |
| `on_session` | `Callable[[str], None] \| None` | Callback disparado **imediatamente** ao obter um novo `session_id`; padrão `None`. **Só deve envolver a linha `runtime.run`** — o [judge](glossary.md#判定者) usa o mesmo `Runtime`, e deixá-lo pendurado durante o gate escreve a sessão do judge na [linhagem](glossary.md#血缘) do passo que fez o trabalho |

Constantes de classe: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (o trecho anexado após a fala da pessoa ao continuar depois de uma interrupção, explicando que "chamadas de ferramenta em voo retornando interrupted
são efeito colateral normal da interrupção, não falha de ambiente").

#### Métodos públicos {#runtime-方法}

| Método | Assinatura | Descrição |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Roda um passo. Ver abaixo |
| `interrupt` | `(message: str = "") -> None` | Solicita interrupção do turno atual. **Pode ser chamado de qualquer thread**. Cooperativo: desconecta limpo na **fronteira de mensagem**, sem cancelamento forçado. String vazia = interromper sem dizer nada |
| `rescue` | `() -> None` | Antes de ser morto à força, tenta registrar as contas por completo; chamado pelos handlers de `SIGHUP`/`SIGTERM`. O passo em voo também é escrito no manifest, com `error="killed-by-signal"`. Faz apenas escritas síncronas pequenas |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | Em `str(workspace.resolve())`, `/`, `_` e `.` são todos trocados por `-`. **O SDK deriva isso do cwd; quem chama não pode especificar** |
| `has_session` | `(session_id: str) -> bool` | Este id ainda é encontrável **sob este workspace**? Síncrono, não lê payload |
| `context_of` | `(session_id: str) -> int` | Tamanho de contexto do último turno de uma sessão; delega para `store.last_context` |
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

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `spec` | `AgentSpec` | obrigatório, posicional | Declaração do agent a rodar |
| `prompt` | `str` | obrigatório, posicional | O que é dito neste turno |
| `step_name` | `str \| None` | `None` | Chave que aparece em `StepResult.step`, no manifest e na linhagem. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Continua a partir deste `session_id` |
| `fork` | `bool` | `False` | Bifurca para uma nova sessão, sem poluir a original. **Só tem efeito quando `resume` é verdadeiro** |
| `resume_at` | `str \| None` | `None` | Continua a partir de uma mensagem específica (rollback). Também **só tem efeito quando `resume` é verdadeiro** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída de eventos, ver [`Event`](#event) |

No início de cada passo, o nível de contexto é zerado (`self._ctx, self._warned = 0, False`). Depois vem um laço com quatro saídas:

1. **Sucesso** → sai do laço.
2. **Interrupção humana** (`result.error == INTERRUPTED`) → **não está sujeita a `max_attempts`**, não espera a rede.
   Faz `resume` na mesma sessão levando a fala da pessoa, `attempt -= 1` (interrupção não conta como tentativa falha), prompt = fala da pessoa + `INTERRUPT_NOTE`.
   **Se não obteve `session_id`, só resta parar**.
3. **Contexto cheio** (`result.error == HANDOFF_DUE`, ou `handoff.enabled` com `session_id` obtido e
   `is_overflow(...)` acionado) → **também não está sujeito a `max_attempts`**. Primeiro verifica `len(result.retired) >= handoff.max_generations`;
   se passou, troca o error por uma linha de diagnóstico e sai do laço; caso contrário escreve o [documento de handoff](glossary.md#交接书) → `resume=None, fork=False`
   (**sessão totalmente nova**) → prompt vira `h.prompt_block()` → nível zerado → `attempt -= 1`.
4. **Falha retentável** → sai se `not resilience.enabled or attempt >= max_attempts`;
   sai também se `classify(error)` decidir que não se deve retentar; caso contrário emite `Event("retry")`, fica pendurado em `wait_online()` esperando a rede,
   `sleep(delay_for(attempt))`; **se algum `session_id` já foi obtido, continua com `resume`** (o prompt vira
   `resilience.resume_prompt`) e define `result.resumed` como `True`.

Encerramento: escreve `ended_at`, anexa a `self.results`, escreve o `manifest.json`.

O `manifest.json` tem semântica de **append**: cada escrita relê o disco e deduplica pelo campo `run` (a própria linha é substituída, as dos outros permanecem),
então rodar dois flowers em paralelo no mesmo `run_dir` é seguro — desde que os `run_id` não colidam.

**Os três pontos de observação do handoff** (todos `Event("handoff")`, diferenciados por `payload["phase"]`):
`near` (aproximando-se de `warn_at`, emitido uma vez por geração), `writing` (escrevendo o handoff, leva dezenas de segundos),
`done` (payload traz `degraded` / `path` / `sections`). O turno que escreve o handoff roda com
`replace(spec, max_budget_usd=None)` — o handoff precisa conseguir ser escrito, não pode travar no orçamento;
além disso `on_event=None`, esse turno não atualiza a UI.

O handoff é gravado em `<workbench.notes>/交接-<步骤名>.md`; **sem workbench não há gravação**, o documento ainda é
entregue a quem assume via prompt, apenas não fica consultável depois. Handoffs antigos são movidos para `notes/archive/交接/<名>-<时间戳>.md`.

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

Toda a contabilidade de um passo concluído.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `step` | `str` | obrigatório | Nome do passo (`step_name` ou `spec.name`) |
| `session_id` | `str \| None` | `None` | **É sempre a última sessão que assumiu** — as queimadas em handoffs no meio do caminho estão em `retired` |
| `ok` | `bool` | `False` | Se este passo deu certo |
| `cost_usd` | `float` | `0.0` | Em dólares. Nas retentativas e handoffs é **acumulado** |
| `num_turns` | `int` | `0` | Número de turnos, também acumulado |
| `text` | `str` | `""` | **Contém apenas o texto da main thread**. As falas dos subagents ficam no transcript deles, e o task brief entregue a eles é `kind="prompt"`; nenhum dos dois entra aqui |
| `error` | `str \| None` | `None` | Motivo da falha. Valores especiais em `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Número real de tentativas. Interrupções e handoffs **não contam** |
| `errors` | `list[str]` | `[]` | Mensagens de erro sintéticas da API coletadas; **não entram em `text`** |
| `resumed` | `bool` | `False` | Se houve resume no meio do caminho |
| `retired` | `list[str]` | `[]` | Os `session_id` queimados por handoff neste passo, em ordem |
| `context` | `int` | `0` | Tamanho de contexto realmente visto pela main thread no último turno, ou seja, o critério de handoff |

| Atributo | Tipo | Descrição |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`; é `0.0` se não terminou |

---

## Workflow {#流程}

Código-fonte: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Um [workflow](glossary.md#流程) é um conjunto de [steps](glossary.md#步骤) encadeados em ordem, mais
como o estado passa de um step para o outro e quando se sai mais cedo.
**O framework não fornece workflows prontos; o workflow é você que escreve** — `starter_flow` é
apenas um modelo que roda.

Alias de tipo `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, está em `flower.workflow.__all__`,
não no `__all__` de topo).

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

A **declaração** de um step. `Step` em si não é uma função — quem executa de fato é
`Runtime.run(step.spec, prompt, ...)`.
Os três primeiros campos são argumentos posicionais; `Step("取词", terse, "读 seed.txt …")` é uma
escrita válida.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do step. **Chave estável entre processos** — cai em `ctx[name]`, `ctx["_results"]`, no manifest e na lineage. Renomear = romper a lineage |
| `spec` | `AgentSpec` | obrigatório | Qual agent rodar |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | O que dizer. Pode ser um closure que calcula na hora a partir de `ctx` |
| `resume_from` | `str \| None` | `None` | De qual step retomar a sessão. Se o step apontado não produziu sessão, **lança `ValueError`**, não pula em silêncio |
| `fork` | `bool` | `False` | Faz fork sobre a base de `resume_from`. **Sem `resume_from` não tem efeito** |
| `retries` | `int` | `0` | Quantas tentativas extras quando o gate não passa. `retries=0` = uma única rodada |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide se esta tentativa passou. **Pode ser async.** Retornar `False` conta como falha. **É chamado uma única vez por tentativa** — ele pode ter efeitos colaterais (por exemplo, gravar o brief em disco) e não deve ser disparado repetidamente |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, ver abaixo |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Retornar `False` **pula o step inteiro**: não gera result, não entra em `ctx["_results"]`. **Pode ser async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **O que dizer na próxima rodada** quando o gate não passa. **Pode ser async.** Fornecê-lo muda a semântica de retry, ver abaixo |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt usado quando há continuidade (em vez de recomeçar do zero) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decide o que vai em `ctx[name]`. Por padrão, o texto original de `result.text`. **Tem de ser uma função síncrona** |

| Método | Assinatura | Descrição |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Se `resuming` e houver `resume_prompt`, usa este último; caso contrário usa `prompt`; se for chamável, passa `ctx` ao invocá-lo |

**Três formas de conectar sessões** (dentro de uma mesma run):

| Escrita | Efeito |
|---|---|
| `resume_from=None` (padrão) | Sessão nova, contando só com o contexto passado no prompt. Barato, isolado. **Mas com `Workflow(continuous=True)` ele pega a sessão do step de mesmo nome na lineage entre processos** |
| `resume_from="nome do step anterior"` | Continua na mesma sessão, contexto completo. Caro, coerente |
| `resume_from="nome do step anterior", fork=True` | Faz fork, sem poluir a sessão original. Para revisão / múltiplas alternativas em paralelo |

**`on_reject` muda a semântica do retry**:

- Não fornecido → a próxima tentativa **recomeça do zero** (mesmo prompt, mesmo `resume_from`).
- Fornecido → a próxima tentativa **continua a sessão que acabou de ser rejeitada**, com o prompt
  trocado pelo valor de retorno dele, e `fork` forçado para `False`.
- Retornar string vazia → não devolve nada; degrada para recomeçar do zero.
- `result.session_id` sendo `None` → também degrada para recomeçar do zero.

**Os três valores de `on_fail`**:

| Valor | Comportamento |
|---|---|
| `"stop"` (padrão) | Escreve `ctx["_failed_at"] = name` e **interrompe o workflow inteiro** |
| `"skip"` | Vai para o próximo step, **`ctx[name]` não é escrito** — um `lambda ctx: ctx["某步"]` a jusante vai dar `KeyError` |
| `"continue"` | `ctx[name] = result.text`, segue em frente com um resultado incompleto |

Passando ou não, `ctx["_results"][name] = result` sempre é escrito; quando `result.session_id` não é
vazio, também é escrito em `ctx["_sessions"]` e chamado `lineage.remember(...)`.

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

Roda uma sequência de `Step` em ordem e retorna o `ctx` final. `steps` é argumento posicional, então
`Workflow([...])` é válido.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `steps` | `list[Step]` | obrigatório | Executados em ordem |
| `name` | `str` | `"workflow"` | Nome do workflow |
| `context` | `Ctx` | `{}` | Dicionário de contexto inicial. **Ao rodar o mesmo `Workflow` uma segunda vez, o ctx é o mesmo dict** |
| `channel` | `HumanChannel \| None` | `None` | Onde pendurar o canal quando for preciso parar e perguntar a alguém. `run()` liga automaticamente o `on_event` dele à mesma saída, **apenas quando `channel.on_event is None`**; o driver também usa este campo para saber a quem responder |
| `workbench` | `Workbench \| None` | `None` | Workbench indicado pelo workflow, para que o driver consiga encontrá-lo |
| `continuous` | `bool` | `True` | Mesmo caminho = mesma conversa. A implementação é [`Lineage`](#lineage) |

| Parâmetro de `run()` | Tipo | Padrão | Descrição |
|---|---|---|---|
| `runtime` | `Runtime` | obrigatório, posicional | Com qual runtime rodar |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída de eventos, repassada a cada `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback uma vez ao fim de cada step |

!!! warning "`continuous=True` é o padrão; `resume_from=None` não significa sessão nova"
    Com continuidade ligada, `run()` primeiro chama `Lineage.open(run_dir, workspace)` e depois
    valida registro por registro com `runtime.has_session(sid)` se ainda estão no banco; só os vivos
    são injetados em `ctx["_sessions"]`. Assim, **até os steps com `resume_from=None` continuam
    falando na sessão da vez anterior** — mesmo com o processo morto ou a máquina reiniciada.

    Para ter sessão nova toda vez, escreva explicitamente `Workflow(..., continuous=False)`.
    Além disso: **o nome do step é a chave estável entre processos; mudar o nome do step equivale a
    romper a lineage.**

As **chaves privadas** que `run()` escreve no ctx (todas começam com `_`, não colidem com nomes de step):

| Chave | Conteúdo |
|---|---|
| `_runtime` | O `Runtime` passado. **É por ele que um gate despacha agents** |
| `_on_event` | Saída de eventos. O agent dentro do gate também precisa chegar à UI, senão a interface fica no escuro |
| `_sessions` | `dict[nome do step, session_id]`, lido com `setdefault` |
| `_results` | `dict[nome do step, StepResult]` |
| `_lineage` | Objeto `Lineage`. Só existe quando `continuous=True` e o runtime tem `run_dir` + `workspace` |
| `_woke` | Valor de retorno de `lineage.bump()`, qual é este wake |
| `_aborted` | Mensagem do `StepAbort` |
| `_failed_at` | Nome do step que falhou com `on_fail="stop"` |

Payload de `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Rótulos de retry**: a tentativa 0 usa `step.name`; depois disso, com `on_reject` usa
`f"{name}#round{attempt+1}"`, sem ele usa `f"{name}#retry{attempt}"`. No manifest dá para ver de
relance como aquele step chegou ao fim.
**Nomes com sufixo não entram na lineage entre processos** — `Lineage.remember` usa o nome original.

`runtime.on_session` cobre apenas a linha `runtime.run`, com `try/finally` garantindo que seja
removido antes do gate.
`prompt_cur` / `resume_cur` / `fork_cur` são variáveis locais e não são escritas de volta no `step` —
o mesmo objeto `Step` pode ser rodado uma segunda vez.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Lançada pelo `gate` = **pare já, não tente de novo**. A diferença para "retornar `False`": `False` é
"desta vez não deu, mais uma rodada"; `StepAbort` é "tentar de novo não adianta".

Depois de lançada: `ctx["_aborted"] = str(exc)`, `passed = False`, **sai do laço de retry (sem
consumir os `retries` restantes)** e então segue o `on_fail` como uma falha comum (padrão `"stop"`).

`with_goal` a lança em dois pontos: quando não consegue obter `ctx["_runtime"]`, e quando o verdict é
`unreachable` e ninguém responde.

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

Produz um `Step` que faz o [clarify](glossary.md#前置确认): esclarecer a demanda → parsear para
[`Brief`](#brief) → congelar e gravar em disco quando as quatro seções estiverem completas.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `brief_path` | `str \| Path` | obrigatório | Onde o [brief](glossary.md#需求确认书) é gravado. **Tem de cair no workbench que é de fato injetado no índice** |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | A demanda original da pessoa |
| `name` | `str` | `"确认需求"` | Nome do step, e ao mesmo tempo a chave no `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções complementares anexadas ao [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = pergunta tudo de novo toda vez, exista ou não o brief |
| `on_fail` | `str` | `"stop"` | Igual a `Step.on_fail` |
| `retries` | `int` | `0` | Quantas vezes perguntar de novo quando as quatro seções não se completam |
| `**spec_kw` | | | Repassado direto para [`clarify()`](#clarify-role), então dá para escrever `can_read=False`, `max_budget_usd=...` |

No `Step` produzido, os campos ficam assim:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: `always_ask=True` → sempre `True`; caso contrário, se `Brief.load(brief_path)` estiver
  completo, injeta-o no ctx **e então retorna `False` (pula)** — mesmo pulando é preciso injetar,
  senão quem vem depois não recebe a demanda.
- `gate`: `Brief.parse(result.text)`; incompleto → escreve `ctx[MISSING_KEY]` e retorna `False`;
  completo → `b.write(brief_path)` para congelar, injeta no ctx, retorna `True`.
- `reduce`: retorna `ctx[BRIEF_KEY].prompt_block()`, **não o texto original do modelo** — no texto
  original pode vir junto coisa que ele escreveu a mais.
- `resume_from` **fica no padrão `None`**: o próximo step é uma sessão nova, que recebe só o brief e
  não a rodada de perguntas e respostas. As perguntas do clarify **nunca entraram** no contexto do
  coordinator; não é que entraram e foram podadas depois.

Os três pontos injetados no ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`,
`ctx.pop(MISSING_KEY, None)`.

| Constante | Valor | Descrição |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` é o objeto `Brief`; `ctx[step.name]` é o `prompt_block()` dele |
| `MISSING_KEY` | `"_brief_missing"` | Quais seções faltam quando o clarify falha (nomes das seções em chinês), para exibir na UI |
| `CLARIFY_RESUME` | um prompt em chinês | «continue a confirmação de requisitos que ficou incompleta — **não recomece**…». Sem essa frase, a continuidade reenvia a demanda original como se fosse tarefa nova, e o clarifier pode repetir perguntas já feitas |

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

Produz um `Step` que **define o objetivo**: faz o [judge](glossary.md#判定者) ler o brief, escrever o
objetivo + o checklist de verdict, e depois de parsear para [`Goal`](#goal) congelar e gravar em
disco. Tem o mesmo formato de `clarify_step`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `goal_path` | `str \| Path` | obrigatório | Onde o arquivo de objetivo é gravado |
| `brief_key` | `str` | `"确认需求"` | Pega o texto do brief em `ctx[brief_key]` para colocar no prompt. **Se não achar, vira `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nome do step |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções anexadas |
| `always_set` | `bool` | `False` | `True` = refaz o checklist, exista ou não o arquivo de objetivo |
| `on_fail` | `str` | `"stop"` | Como acima |
| `retries` | `int` | `0` | Como acima |
| `**spec_kw` | | | Repassado para [`judge()`](#judge-role) |

**Não existe o parâmetro `can_run`** — para que o judge que define o objetivo possa rodar comandos, só
passando `can_run=True` via `**spec_kw`. Sem isso ele não recebe `Bash`, e a regra
"primeiro veja bem em que ambiente você está" de `JUDGE_RULES` não pode ser executada.

Além de parsear e congelar, o `gate` faz mais uma coisa: quando há itens `[此环境无法验证:…]` no
objetivo, ele emite **na hora**, via `ctx["_on_event"]`, um
`Event("task", payload={"unverifiable", "total", "path"})` como aviso — o destino desses itens já está
selado no momento em que o objetivo é definido, e quando chega a hora do verdict o dinheiro de uma
rodada inteira de trabalho já foi gasto.

**Não define `resume_prompt`** — definir o objetivo deve mesmo reenviar o brief por inteiro.

| Constante | Valor | Descrição |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` é o objeto `Goal`; `ctx[step.name]` é o markdown |
| `VERDICT_KEY` | `"_verdict"` | O [`Verdict`](#verdict) mais recente, para uso da UI |
| `ROUND_KEY` | `"_goal_rounds"` | Quantas rodadas de verdict já rodaram |

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

Envolve um `Step` existente com o [goal guard](glossary.md#目标看守): ao fim de cada rodada o judge
emite um verdict independente; se o objetivo não foi alcançado, devolve para continuar trabalhando.

O resultado é `replace(step, retries=max(0, rounds - 1), gate=<novo gate>, on_reject=<novo on_reject>)` —
usa `dataclasses.replace` em vez de reconstruir campo a campo; uma reconstrução já deixou o
`resume_prompt` escapar, **e sem erro nenhum**, apenas reenviando o brief inteiro de novo na
continuidade.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `step` | `Step` | obrigatório, posicional | O step a ser guardado |
| `channel` | `HumanChannel` | obrigatório, posicional | Canal para pedir ajuda a uma pessoa quando não dá para decidir |
| `goal_path` | `str \| Path` | obrigatório | Arquivo de objetivo, lido daqui quando `ctx[GOAL_KEY]` não está completo |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Total de rodadas, não rodadas extras**: `rounds=3` → `retries=2` → no máximo três rodadas de trabalho. `rounds=1` = uma rodada, um verdict, e falha se não passar |
| `instructions` | `str` | `""` | Instruções anexadas ao judge |
| `can_run` | `bool` | `False` | Se o judge pode rodar `Bash` |
| `name` | `str \| None` | `None` | Nome do judge, por padrão `f"{step.name}·判定"` |
| `**spec_kw` | | | Repassado para `judge()` |

O `gate` é **async**, e o fluxo é:

1. `ctx["_runtime"]` ausente → **lança `StepAbort`** ("拿不到 Runtime,无法判定目标").
   **Não finja que passou.**
2. `ctx[ROUND_KEY] += 1`.
3. Pega o objetivo: primeiro um `Goal` completo em `ctx[GOAL_KEY]`, senão `Goal.load(goal_path)`,
   senão um `Goal()` vazio.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **O judge é um `Runtime.run` independente, com `resume` sempre `None` — é sempre uma sessão nova**;
   o `step_name` carrega o número da rodada, então não entra na lineage entre processos.
5. `Verdict.parse(vr.text)` é escrito em `ctx[VERDICT_KEY]`.
6. `v.achieved` → retorna `True`.
7. Não sendo `unreachable` (inclusive os casos ambíguos com `v.ok=False`) → nos casos ambíguos
   acrescenta um reason padrão e retorna `False`.
   **Ambiguidade é sempre tratada como não alcançado** — não dá para deixar um "parece que dá" encerrar
   o trabalho.
8. `unreachable` → `await channel.ask(...)` pergunta a uma pessoa, com três opções:
   - Ninguém responde (`a.state != "answered"`) → **lança `StepAbort`**. Continuar girando em falso é a
     escolha mais cara.
   - 「接受这个结果,就这样往下走」 → retorna `True`.
   - 「修改目标」 → pergunta de novo o novo objetivo, faz `g.amend(...).write(goal_path)`, atualiza
     `ctx[GOAL_KEY]` e retorna `False`.
   - Qualquer outra coisa (inclusive resposta livre digitada pela pessoa) → é tratada como "você julgou
     errado", registra a fala da pessoa em `v.reason` e retorna `False`.

O `on_reject` é **síncrono**: retorna `ctx[VERDICT_KEY].feedback()`; sem `Verdict`, retorna `""`
(degrada para recomeçar do zero).

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

Monta um workflow de três steps que roda de imediato: **confirmar requisitos → definir objetivo →
trabalhar** (com goal guard). É o que a linha de comando `flower` usa.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `ask` | `str` | obrigatório, posicional | Uma frase de demanda. **No wake ela não é uma tarefa nova, é "mais uma coisa dita"** |
| `workspace` | `str \| Path` | `"."` | Workspace |
| `run_dir` | `str \| Path` | `"runs"` | Diretório da run |
| `new` | `bool` | `False` | `True` = arquiva lineage + brief + objetivo (os três juntos) e começa do zero |
| `isolate` | `bool` | `False` | Abre um worktree de [isolamento](glossary.md#隔离) para o worker. O workbench passa junto para `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Retorna apenas o Workflow com o step de clarify |
| `goal` | `bool` | `True` | Instalar ou não o [goal guard](glossary.md#目标看守). `False` = acabou o step de trabalho, acabou tudo |
| `rounds` | `int` | `3` | Repassado a `with_goal(rounds=)`, total de rodadas |
| `judge_can_run` | `bool` | `False` | Repassado a `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Repassado ao `HumanChannel`, `None` = sem limite |
| `timeout_s` | `float \| None` | `1800.0` | Repassado ao `HumanChannel`. `0` = totalmente automático, toda pergunta cai no vazio na hora |
| `instructions` | `str` | `""` | Instruções anexadas ao clarifier |
| `worker_prompt` | `str` | ver assinatura | System prompt do worker |
| `brief_name` | `str` | `"需求.md"` | Nome do arquivo do brief, gravado em `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nome do arquivo de objetivo, idem |
| `log_name` | `str` | `"问答记录.md"` | Nome do arquivo de registro de perguntas e respostas, idem |

Montagem fixa:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Ramificações de comportamento:

- `isolate=True` com o workspace não sendo um repositório git → **lança `ValueError`**, em vez de só
  descobrir quando a ferramenta `Agent` reclama (aí o dinheiro já foi gasto).
- **Detecção de wake**: se `Brief.load(brief_path)` existe e está `complete()`, é um wake. Se não é wake
  e `ask` está vazio → **lança `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- No wake, essa frase cai em **três lugares** ao mesmo tempo; faltar um deles causa falha silenciosa:
  anexada ao brief (`ch.amend(said, label="唤醒时追加")`, sem reescrever se já estiver no arquivo);
  fazendo `goal_step(always_set=True)` refazer o checklist (sem isso, o judge continua lendo o objetivo
  antigo); e entregue direto ao coordinator (no contexto dele está o objetivo **antigo**, e sem isso ele
  trabalha pelo critério antigo e é julgado pelo critério novo).

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

**Uma sondagem somente-leitura antes da largada, que não escreve um único byte.** Serve para dizer à
pessoa, antes de começar de verdade, "isto é continuação da vez passada ou começo do zero".

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Workspace, argumento posicional |
| `run_dir` | `str \| Path` | `"runs"` | Diretório da run |
| `isolate` | `bool` | `False` | Determina a posição do workbench; tem de ser o mesmo valor passado a `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nome do arquivo do brief |
| `goal_name` | `str` | `"目标.md"` | Nome do arquivo de objetivo |

O dict retornado:

| Chave | Tipo | Descrição |
|---|---|---|
| `waking` | `bool` | O brief existe e as quatro seções estão completas |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Número de itens do checklist do objetivo; `0` quando não há objetivo |
| `woke` | `int` | `Lineage.woke`, quantos wakes já houve |
| `steps` | `dict` | Cópia de `Lineage.steps`, nome do step → `session_id` |

A posição do workbench é **definida uma única vez, aqui e em `starter_flow`**: `isolate=True` →
`<ws>.parent/.flower-<ws.name>` (fora do repositório); caso contrário `<ws>/.flower`. Um driver que
queira saber onde está o brief também passa por esta função — montar o caminho por conta própria e
errar não dá erro, apenas falha em silêncio.

---

## Fábrica de papéis {#角色工厂}

Código-fonte: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Os cinco papéis são funções de fábrica. Cada papel = **um trecho de texto de regras injetado + um conjunto de ferramentas + um conjunto de hooks**.
`worker()` produz o `AgentDefinition` do SDK (para ser despachado a um subagent); os outros quatro produzem [`AgentSpec`](#agentspec)
(abrem a própria sessão).

Os papéis em si **não montam hooks** — interceptar ferramentas é trabalho que `Runtime._attempt` instala automaticamente conforme `spec.delegate_only`,
veja [camada de hooks](#hook).

Constantes internas de grupos de ferramentas (não exportadas, mas determinam os padrões):

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

Constrói o [coordenador](glossary.md#协调者) que fica na [thread principal](glossary.md#主线程): decompõe a tarefa, despacha trabalho, lê relatórios, decide,
**mas não põe a mão na massa**. Os três primeiros parâmetros são posicionais.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, e também o nome padrão do step |
| `instructions` | `str` | obrigatório | Instruções de domínio. No final vira `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obrigatório | Quais papéis estão sob seu comando; cai em `AgentSpec.agents`. **As ferramentas web somente-leitura deles também são mescladas no próprio `allowed_tools` do coordenador**, veja abaixo |
| `channel` | `HumanChannel \| None` | `None` | Se fornecido, acrescenta ao mesmo tempo as ferramentas `inbox` **e** `ask`, e define `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → remove `Read` |
| `glance` | `bool` | `True` | Acrescenta `"Bash"` e define `AgentSpec.glance`. **O que exatamente pode ser executado quem decide é o `delegate_guard`**, não isto aqui |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [orçamento](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Modo de permissão. **Atenção a este padrão** — passá-lo para `clarify()`/`judge()` desmonta a proteção desses dois papéis |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, não será forçado pelo `Runtime` para `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extras, mesclados com `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variáveis de ambiente extras |

Três itens fixos no `AgentSpec` produzido: `delegate_only=True`, `agents=workers`,
e `workbench` mantém o padrão `True` do `AgentSpec`.

#### As ferramentas web dos `workers` são mescladas aqui {#coordinator-web-merge}

Depois de montar a lista, `coordinator()` percorre cada `AgentDefinition.tools`; toda ferramenta que caia em
`WEB_TOOLS` (`WebFetch`, `WebSearch`, `roles.py:33`) também é adicionada ao próprio
`allowed_tools` do coordenador (`roles.py:523-526`).

**Motivo: `allowed_tools`, assim como `disallowed_tools`, é de escopo de sessão.** Esta é a evidência mais dura do texto inteiro sobre esse ponto —
ela não afeta só a thread principal. Uma ferramenta que não esteja nessa lista de escopo de sessão também exige aprovação de permissão quando um **subagent** a chama;
sem supervisão não há quem aprove, e o harness responde
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`), enquanto o modelo repete a mesma chamada indefinidamente. Já tropeçamos nisso na prática: acrescentamos
`WebFetch`/`WebSearch` ao worker, mas só escrevemos em `AgentDefinition.tools`; aquela run de novel teve mais de vinte
user-rejected e não escreveu uma única palavra (`roles.py:513-518`).

Os dois campos têm a mesma natureza de escopo de sessão, mas **sintomas diferentes**: `disallowed_tools` dá erro na hora,
`allowed_tools` fica repetindo em silêncio até morrer. O segundo é mais difícil de diagnosticar, porque nada na tela parece um erro.

**Só as somente-leitura, sem efeitos colaterais, são mescladas.** `Write`/`Edit`/`Bash` **são deliberadamente deixadas de fora**: se a thread principal ficar isenta de aprovação para elas,
o muro do `delegate_guard` — "o coordenador não põe a mão na massa" — perde o sentido; e `Bash`/`Write` do subagent
já funcionam de qualquer maneira (462 liberações medidas, `roles.py:520-522`).

O código-fonte diz explicitamente para **não usar `disallowed_tools` para implementar "só coordena, não executa"** — aquilo é de escopo de sessão,
e desabilitaria junto o `Bash`/`Write` dos subagents; veja o aviso em [`AgentSpec`](#agentspec).
O jeito correto é o daqui: `delegate_only=True` + não conceder em `allowed_tools`,
e deixar o [`delegate_guard`](#delegate-guard) interceptar apenas a thread principal por `agent_id`.

Fornecer `channel` traz **as duas ferramentas juntas**, não é opcional: montado o MCP server, as duas estão lá, e como
`allowed_tools` não é exclusivo, ambas podem ser chamadas estejam listadas ou não. Sem supervisão, cada `ask` trava até estourar o `timeout_s` —
nesses cenários, use `HumanChannel(timeout_s=0)`.

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

Constrói a definição do [subagent](glossary.md#subagent) que de fato trabalha. Os dois primeiros parâmetros são posicionais.
Retorna o `AgentDefinition` do SDK, para ser colocado diretamente em `coordinator(workers={...})`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `description` | `str` | obrigatório | **É por aqui que o coordenador escolhe quem chamar** — deixe claro "que tipo de trabalho vai para ele" |
| `prompt` | `str` | obrigatório | Seu system prompt. Com `discipline=True`, vira `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | O worker não deve ser rebaixado |
| `effort` | `str \| int \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Vira **`maxTurns`** (camelCase) no SDK |
| `permission_mode` | `str \| None` | `None` | Vira **`permissionMode`** (camelCase) no SDK |
| `skills` | `list[str] \| None` | `None` | Quais skills ele pode usar |
| `discipline` | `bool` | `True` | Concatenar ou não o trecho de disciplina de reporte `WORKER_RULES` |
| `isolate` | `bool` | `False` | Marca de [isolamento](glossary.md#隔离), passa por `isolated()`; **não é um campo do `AgentDefinition`** |

`isolate=True` exige que o workspace seja um repositório git; caso contrário, a ferramenta `Agent` reporta direto `"not in a git repository"`,
**não há degradação silenciosa**. E como a marca é um atributo Python, fazer `dataclasses.replace()` sobre o `AgentDefinition`
a perde, e o isolamento deixa de valer silenciosamente.

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

Constrói o [clarificador](glossary.md#确认者): esclarece o requisito antes de agir, não faz nada além de perguntar, e no fim produz exatamente quatro seções.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas após `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Quando `True`, acrescenta `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | **Sem limite de turnos** |
| `max_budget_usd` | `float \| None` | `None` | Teto de orçamento |

O `AgentSpec` produzido: `allowed_tools = [channel.tool_name] + (os cinco acima, quando pode ler)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (ele não tem ferramenta de escrita, o índice não lhe serve de nada),
`permission_mode` herda o padrão `"default"` do `AgentSpec`.
**Sem `Write` / `Edit` / `Bash` / `Agent`, e sem `inbox`** (diferente do coordenador).

!!! warning "Um `max_turns` pequeno transforma o "perguntar sem limite" em conversa fiada"
    Cada pergunta é um turno. `max_turns=16` equivale a "no máximo uma dúzia de perguntas", e a frase do canal "não há limite de turnos" perde a validade na hora.

    Para liberar as perguntas é preciso liberar **os dois** lugares: `HumanChannel.max_asks` (já é `None` = sem limite por padrão)
    e `max_turns` (já é `None` por padrão).

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

Constrói o [juiz](glossary.md#判定者): ou define o objetivo antes de começar, ou emite o veredito ao fim de cada rodada.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas após `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Quando `True`, acrescenta `Bash` à whitelist; o `whitelist_guard` passa a liberar `Bash` e continua barrando `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de orçamento |

O `AgentSpec` produzido: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (quando `can_run`) `["Bash"]`,
`workbench=False`, o resto igual a `clarify()`. **Sem `Write` / `Edit` / `Agent`, e sem `inbox`.**

**Trade-off**: `can_run=True` dá um veredito mais duro (consegue de fato rodar os comandos de aceitação), ao custo de o juiz passar a poder alterar o workspace —
`Bash` por si só já escreve arquivos. Se você quer um veredito absolutamente neutro, não ligue.

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

Constrói o [oracle](glossary.md#旁路顾问): com a run ainda em andamento, você pergunta "onde estamos agora" e ele dá uma olhada nos eventos recentes e na bancada
antes de responder. **O que ele diz não entra no contexto daquela run.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nome do papel, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas após `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | **`12`** | Vem com freio por padrão |
| `max_budget_usd` | `float \| None` | **`0.5`** | Vem com freio por padrão. Isto é "uma perguntinha de passagem", não deve sair do controle |

O `AgentSpec` produzido: `allowed_tools = ["Read", "Glob", "Grep"]` (**sem channel** — ele não pergunta,
só responde), `workbench=True` (**o único dos cinco papéis que não é coordenador e ainda assim abre a bancada** — é exatamente lá que ele vai ler os artefatos e as notas).

### Os cinco textos de regras {#rules}

As cinco constantes estão em `__all__`; dá para `import` direto e ler, concatenar, alterar.

| Constante | Injetada em quem | Forma de injeção | Pontos-chave |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Você é "uma pessoa que sabe usar o Claude Code", não um worker; não pode escrever arquivos/alterar código/rodar testes; `Bash` só dá para "dar uma olhada" e o resultado envelhece; **o [briefing de tarefa](glossary.md#任务书) só escreve o que é exclusivo desta tarefa**; a única regra que ainda precisa ser dita é "onde fica a bancada + artefatos longos vão para `artifacts/` + a resposta traz só o caminho"; consultar o `inbox` a cada ação concluída; `ask` bloqueia, use só em bifurcações de verdade |
| `WORKER_RULES` | `worker()` | Concatenado **depois** do `prompt` do subagent | Formato de resposta **conclusão / evidências / artefatos / não verificado**, no máximo 30 linhas; proibido colar conteúdo de arquivo, saída de comando, log ou diff bruto; proibido narrar a sequência de tentativa e erro; antes de agir, olhar `.flower/scripts/`. **Deliberadamente não menciona "artefatos longos vão para `artifacts/`"** — o caminho real é gerado pelo `Workbench`, cravá-lo daria errado |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Não faz nada, só esclarece o requisito; **sem limite de perguntas, pergunte até ficar claro**; a pessoa pode não estar; ao dar timeout, decida sozinho e registre em «Incógnitas e premissas»; a saída tem **exatamente quatro seções**; não escreva código nem cole conteúdo de arquivo |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Duas tarefas, escolha uma. **Definir o objetivo**: cada item da lista tem de ser verificável na hora, o tamanho da lista é determinado pelo número de modos de falha, **fronteiras não são itens de veredito**, e itens não verificáveis terminam com `[此环境无法验证:原因]`. **Julgar a rodada**: saída com **exatamente três seções**, julga-se o **artefato, não o código-fonte**, por padrão não se acredita em "está pronto"; "não conseguiu" e "aqui não dá para verificar" são conclusões diferentes, e a segunda **jamais pode ser julgada como aprovada** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Você é uma via lateral; a run continua rodando, você não interrompe nem participa; **somente leitura**; responde e é descartado, o que você diz não entra no contexto daquela run; você só tem "a janela de eventos recentes" e "a bancada"; olhe antes de responder, se não der para responder diga que não dá, e seja breve |

---

## Definição de agent {#agent-定义}

Código-fonte: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` é a declaração completa de um agent especializado, e `build_options` a compila no `ClaudeAgentOptions` do SDK.
O que a [fábrica de papéis](#角色工厂) produz é justamente um `AgentSpec` — quando você precisa de uma combinação fora da fábrica, construa-o diretamente.

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

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel. Também é o `step_name` padrão de `Runtime.run`, e como o `whitelist_guard` se refere a si mesmo no texto de recusa |
| `instructions` | `str` | obrigatório | Instruções de domínio. **[Anexadas](glossary.md#叠加) depois do system prompt nativo do Claude Code, não substituem** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Lista de isenção de aprovação, não é uma whitelist exclusiva** — o modelo continua conseguindo chamar ferramentas fora dela. A exclusividade vem do [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Escopo de sessão**. Veja o aviso abaixo |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [orçamento](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Modo de permissão |
| `agents` | `dict[str, Any] \| None` | `None` | Tabela de definições de subagents; os valores são `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabela de MCP servers. `HumanChannel.mcp_servers()` preenche direto aqui |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extras; o `Runtime` os mescla com os seus via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, não será forçado pelo `Runtime` para `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variáveis de ambiente injetadas no subprocesso. `compact.env()` faz update por cima |
| `glance` | `bool` | `False` | Permite ao coordenador rodar por conta própria um `Bash` de "só dar uma olhada". O que é liberado é decidido por [`is_ephemeral`](#is-ephemeral), e o resultado é marcado como expirado pelo `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Se injeta ou não o índice da bancada no system prompt deste agent. **Papéis sem ferramenta de escrita devem desligar** (`clarify()` / `judge()` já vêm com `False`) |
| `delegate_only` | `bool` | `False` | Só coordena, não executa. Quando `True`, o `Runtime` instala `delegate_guard` e **não instala** `whitelist_guard` |

!!! warning "`disallowed_tools` é de escopo de sessão e desabilita junto os subagents"
    Erro medido, texto original: `"Bash is disabled for this session, in subagents as well as here"`.
    Ou seja: se você usar `disallowed_tools=["Bash"]` para impedir o coordenador de agir, os workers despachados também não conseguem rodar comandos —
    a run inteira vai por água abaixo.

    Para "só coordena, não executa", use `delegate_only=True` + não conceder em `allowed_tools`, deixando o
    [`delegate_guard`](#delegate-guard) interceptar apenas a thread principal por `agent_id`.

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

Compila o `AgentSpec` no `ClaudeAgentOptions` do SDK. É o que `Runtime._attempt` chama internamente;
quando você mesmo dirige o SDK (sem `Runtime`), a entrada também é por aqui.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `spec` | `AgentSpec` | obrigatório, posicional | A declaração a compilar |
| `cwd` | `str \| Path \| None` | `None` | Só escreve `cwd` se não for `None` |
| `session_store` | `SessionStore \| None` | `None` | Só escreve `session_store` e `session_store_flush` se não for `None` |
| `resume` | `str \| None` | `None` | Qual sessão retomar |
| `fork` | `bool` | `False` | Vira `fork_session`. **Está aninhado dentro de `if resume:`** |
| `resume_at` | `str \| None` | `None` | Vira `resume_session_at`. **Também aninhado dentro de `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` e `PLUGIN_DIR` existindo → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Diretórios autorizados adicionais. **Obrigatório quando a bancada fica fora do workspace** |
| `flush` | `str` | `"eager"` | Vira `session_store_flush` |
| `prelude` | `str` | `""` | Trecho anexado depois de `instructions` (o índice da bancada passa por aqui) |

Mapeamento:

| Chave de option produzida | Valor |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Vêm diretamente do `spec` |
| `setting_sources` | `[]` (portável) ou `["project"]` |
| `plugins` | Só existe se o diretório `plugin/` na raiz do repositório existir |
| `cwd` / `add_dirs` | Só escritos se não vazios |
| `session_store` / `session_store_flush` | Só escritos se `session_store` não for `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Cada um só é escrito se não for vazio |
| `env` | `dict(spec.env)` e depois `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Só têm efeito quando `resume` é verdadeiro** |

`PLUGIN_DIR` é o `plugin/` na raiz do repositório (três níveis acima de `flower/core/agent.py`). Após instalar por pip esse diretório pode não existir;
o código verifica com `is_dir()`.

!!! warning "`fork=True` sem `resume` não faz nada, em silêncio"
    `fork_session` e `resume_session_at` estão ambos aninhados dentro de `if resume:` — sem `resume` eles simplesmente não têm efeito,
    **e nenhum erro é levantado**. Do mesmo modo, `Runtime.run(resume_at=...)` só funciona quando `resume` é dado,
    e **o `Workflow` nunca passa `resume_at`**: para voltar até uma mensagem específica, só chamando `Runtime.run` diretamente.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

O painel de chaves do auto-[compact](glossary.md#压缩); o produto é um conjunto de variáveis de ambiente a injetar no subprocesso.
O algoritmo de compact em si está no binário do harness e não pode ser mudado; o que dá para mudar é apenas "dispara ou não".

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = não define nada, limiar = janela − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (desliga junto o `/compact`). **Outros valores levantam `ValueError`**, não são ignorados em silêncio |
| `window` | `int \| None` | `None` | Se não for `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. O lado do CLI limita a 100k–1M; valores abaixo de 100k são elevados para 100k |

| Método | Assinatura | Descrição |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produz as variáveis de ambiente. **É aqui que um `mode` inválido levanta `ValueError`, não na construção** — como é chamado por `build_options`, o erro aparece dentro de `Runtime.run` |

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

O objeto de política que, quando o contexto está quase cheio, "escreve o documento de handoff e troca de sessão" em vez de fazer compact.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | Desligar faz cair de volta no auto-compact |
| `window` | `int` | `default_window()` | Qual o tamanho assumido da janela de contexto do modelo |
| `headroom` | `int` | `50_000` | Quanta folga deixar. Motivo: o auto-compact dispara em janela −33k, e o handoff precisa acontecer antes dele — e "escrever o handoff" ainda consome um turno |
| `max_generations` | `int` | `8` | Quantas gerações no máximo em um step. **Isto é um freio contra descontrole, não planejamento de capacidade** |

| Propriedade | Tipo | Descrição |
|---|---|---|
| `at` | `@property -> int` | Limiar de handoff `max(10_000, window - headroom)`. **Tem piso de 10k** — abaixo disso nem o handoff sai |
| `warn_at` | `@property -> int` | Posição do aviso de aproximação `max(1_000, at - 20_000)`, emitido uma vez por geração |

!!! warning "Um `window` pequeno demais gera handoffs infinitos queimando dinheiro"
    Se `at` ficar abaixo do **piso de partida** daquele papel (medido em cerca de 34k para o coordenador), toda nova sessão cruza a linha na primeira fala; e como
    **handoff não consome cota de retentativa** (`attempt -= 1`), o sistema gira em falso indefinidamente. O único freio é `max_generations=8`;
    ao bater nele, o `error` é substituído por um diagnóstico sugerindo aumentar `window` ou desligar o handoff.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Adivinha a janela de contexto a partir da **string do nome do modelo** nas variáveis de ambiente `ANTHROPIC_MODEL` ou `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Condição | Retorno |
|---|---|
| O nome contém a palavra isolada `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| O nome contém `haiku` | `200_000` |
| Demais casos (**inclusive nenhuma das duas variáveis definida**) | `1_000_000` |

**O padrão é o valor agressivo.** Estimar alto não é um erro fatal: a API rejeita com `prompt is too long`, o `Runtime` reconhece esse sinal
(o `is_overflow` interno) e faz handoff na hora — mas o handoff dessa geração sai em versão degradada.

---

## Documentos {#文书}

Código-fonte: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatro dataclasses, todas "parseiam uma resposta do modelo em um número fixo de seções e gravam em disco". Formato comum:
`parse()` parseia, `missing()` / `complete()` verificam completude, `to_markdown()` é para humanos,
`prompt_block()` é para os modelos a jusante, `write()` / `load()` gravam e leem de volta.

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

O [brief](glossary.md#需求确认书), **exatamente quatro seções**, na ordem fixa
`goal` → `accept` → `bounds` → `unknowns`; os nomes em chinês são «目标», «验收标准», «边界», «未知与假设».

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `goal` | `str` | `""` | Objetivo |
| `accept` | `str` | `""` | Critérios de aceitação |
| `bounds` | `str` | `""` | Fronteiras |
| `unknowns` | `str` | `""` | Incógnitas e premissas |
| `path` | `Path \| None` | `None` | Local de gravação. `compare=False`, não participa da comparação de igualdade |

| Método | Assinatura | Descrição |
|---|---|---|
| `missing` | `() -> list[str]` | **Nomes em chinês** das seções faltantes, exibíveis diretamente |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parseia as quatro seções da resposta do modelo. **Primeiro remove os blocos de código cercados**; o que não for parseado fica vazio |
| `to_markdown` | `() -> str` | Documento completo com cabeçalho de metadados; seções vazias viram `"(未填)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar os agentes a jusante, **só com as seções não vazias**, sem metadados |
| `write` | `(path: str \| Path) -> Path` | Cria o diretório pai, grava, define `self.path` como o caminho resolvido e o retorna |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Retorna `None` se o arquivo não existir ou em `OSError`. **Converte o placeholder `"(未填)"` de volta em string vazia** |

Regras de parsing (onde os erros se concentram):

- Ao remover as cercas, **um ``` ou `~~~` não fechado faz descartar tudo a partir dele** — na prática o clarificador cola o código inteiro na resposta.
  Quando a saída do modelo é truncada, todas as seções seguintes deixam de ser parseadas, `complete()` fica `False` e o gate manda refazer.
- A regex de título tolera `## 目标` / `**目标**` / `目标:` / `3. 边界`, e também tolera texto logo após o título.
- A tabela de aliases é compilada em ordem decrescente de comprimento; senão "未知" engoliria "未知与假设" primeiro.
- Quando a mesma seção aparece repetida, **prevalece a primeira com conteúdo**.
- Se, ao editar o brief à mão, você copiar o placeholder `"(未填)"` de `to_markdown()`, aquela seção continua contando como faltante.

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

O [documento de handoff](glossary.md#交接书) escrito na hora do [handoff](glossary.md#换代), cinco seções.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `doing` | `str` | `""` | O que está sendo feito. **Obrigatório** |
| `decided` | `str` | `""` | O que já foi decidido |
| `deadends` | `str` | `""` | Caminhos que não deram certo |
| `next` | `str` | `""` | Próximo passo. **Obrigatório** |
| `scene` | `str` | `""` | Situação atual |
| `step` | `str` | `""` | Usado apenas no cabeçalho do documento, **não participa do parsing** |
| `path` | `Path \| None` | `None` | Local de gravação |

**Obrigatórias são só `doing` e `next`** — exigir rigidamente que "caminhos que não deram certo" seja não vazio forçaria o modelo a inventar.

| Membro | Assinatura | Descrição |
|---|---|---|
| `missing` | `() -> list[str]` | **Verifica apenas as duas seções obrigatórias** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Se o corpo carrega a marca de degradação `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reaproveita o divisor de seções do `Brief` |
| `to_markdown` | `() -> str` | Seções vazias viram `"(空)"` |
| `prompt_block` | `() -> str` | **O cabeçalho diz explicitamente a quem assume que "você está assumindo"**, para evitar que ele volte a pedir contexto a alguém |
| `write` | `(path) -> Path` | Igual a `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Igual a `Brief.load` |

Três membros do mesmo módulo **não exportados, mas semanticamente cruciais**: `is_overflow(*texts)` casa com `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` etc., convertendo um "erro fatal" em "handoff imediato"; `HANDOFF_PROMPT` é o prompt que faz
**a própria sessão atual** escrever o handoff (contém os dois placeholders `{used}` e `{window}`; **não é um novo papel** —
só ela tem aquele contexto); `degraded(step, prompt, *, why="")` monta mecanicamente um handoff quando ele não pôde ser escrito,
enfiando em `scene` os primeiros **1200** caracteres da tarefa original.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

O objetivo + a lista de verificação usados pelo [goal guard](glossary.md#目标看守).

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `statement` | `str` | `""` | Enunciado do objetivo |
| `checks` | `list[str]` | `[]` | Lista de verificação, um item por linha |
| `path` | `Path \| None` | `None` | Local de gravação |

| Membro | Assinatura | Descrição |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Itens de `checks` marcados com `[此环境无法验证:…]`. **Já nascem condenados a nunca passar, desde o momento em que o objetivo foi definido** |
| `missing` | `() -> list[str]` | Exige `statement` não vazio **e** `checks` não vazio |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` um por linha, removendo automaticamente os marcadores `-` / `*` / `1.` |
| `to_markdown` | `() -> str` | Quando a lista está vazia, escreve `"(空)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar os agentes a jusante |
| `write` / `load` | Igual a `Brief` | Gravação e leitura de volta |
| `amend` | `(extra: str) -> Goal` | **Anexa, não sobrescreve**: concatena `"\n\n(已修改)" + extra` após `statement` e retorna `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

O resultado de uma rodada de julgamento do [juiz](glossary.md#判定者), **exatamente três seções**: conclusão / motivo / não aprovados.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` quando não se consegue parsear |
| `reason` | `str` | `""` | Motivo |
| `failed` | `list[str]` | `[]` | Itens da lista que não passaram |

| Membro | Assinatura | Descrição |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Se a conclusão foi parseada ou não. **`ok=False` tem obrigatoriamente de ser tratado como "não atingido", nunca como atingido** |
| `parse` | `@classmethod (text) -> Verdict` | Veja abaixo |
| `feedback` | `() -> str` | O que é devolvido ao worker: só "o que está faltando", nunca a solução |

Ordem de reconhecimento do `parse`:

1. Primeiro busca as seções tituladas «结论» / «判定».
2. Sem seções tituladas, faz strip do texto inteiro e `fullmatch(r"1|true")` → atingido; `fullmatch(r"0|false")` → ainda não.
3. Caso contrário, procura no texto da conclusão a primeira ocorrência de uma palavra da tabela de estados (**palavras longas primeiro**).
   **«无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» são todas mapeadas para `unreachable`** —
   já tropeçamos nisso: plataforma-alvo macOS, execução em container Linux, e o juiz olhou o branch no código-fonte e deu aprovado.
4. Ainda nada → procura um `\b1\b` isolado → atingido, `\b0\b` → ainda não.
5. Nenhum caso → `state=""`, `ok=False`.

`unreachable` e `not_yet` **são conclusões diferentes**: a primeira leva ao caminho de "parar e perguntar a alguém", não ao de "mais uma rodada".

---

## Camada de hooks {#hook}

Código-fonte: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Esta camada é a **fronteira de execução** do flower: quais ferramentas a thread principal não pode
tocar, como recortar resultados gigantes, qual papel vai para um worktree independente — tudo é
imposto por hooks do SDK, **não por prompt**. O motivo é direto: prompt é sugestão, o modelo pode
ignorar. Já foi medido na prática que, mesmo com o system prompt dizendo explicitamente "não use
worktree", a injeção do `isolate_guard` funcionou do mesmo jeito (o modelo passou `None`, o que
chegou no disco foi `'worktree'`).

Nove exports: cinco fábricas de guard que retornam `HookMatcher` (`whitelist_guard` pode retornar
`None`), um montador, um combinador, duas funções de marcação de isolamento.
Não é preciso instalá-los à mão — o [`Runtime`](#runtime) monta tudo automaticamente a partir do
`AgentSpec`. Instalação manual só é necessária quando você mesmo dirige o SDK (sem passar pelo
`Runtime`).

**A detecção da thread principal passa por uma única função**: `_is_main_thread(data) = not
data.get("agent_id")` — os dados de tool-lifecycle hook de um subagent trazem `agent_id`, os da
[thread principal](glossary.md#主线程) não. Todos os guards que "só barram a thread principal" se
apoiam nessa única regra.

Constantes de grupos de ferramentas (nível de módulo, não exportadas, mas definem os matchers
padrão):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tabela de referência: qual guard entra em qual evento do SDK {#hook-速查表}

| Função | Evento de hook do SDK | matcher | O que intercepta | O que retorna | Quem instala |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | as ferramentas de `Bash\|Write\|Edit\|NotebookEdit` que **não estão em `allowed_tools`** | **apenas a thread principal** chamando ferramenta proibida | `permissionDecision: "deny"` + motivo | `Runtime._attempt`, **apenas quando `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (alterável por `tools=`) | **apenas a thread principal** pondo a mão; com `allow_glance=True`, um `Bash` que passa em `is_ephemeral()` é liberado | `deny` + "vá delegar a um subagent" | `workbench_hooks(delegate_only=True)`, **apenas quando o `Runtime` tem workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sem `cwd` e sem `isolation`, e `subagent_type` marcado por `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injeta `isolation="worktree"`) | `workbench_hooks`, **apenas quando há algum papel marcado em `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` cai dentro de `workbench.root` | `{}` (o efeito colateral é `workbench.refresh()`) | `workbench_hooks`, sempre instalado |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **campos string** com ≥ `threshold` caracteres em `tool_response`; ler o próprio diretório de spill é liberado | `updatedToolOutput` (spill + uma linha de ponteiro + os 400 primeiros caracteres) | `workbench_hooks`, **apenas quando `spill_threshold` for verdadeiro** |

**A conclusão importante que se lê nessa tabela**: com `Runtime(workbench=False)`, os
`workbench_hooks` inteiros não são instalados; e para um coordenador com `delegate_only=True`, o
`whitelist_guard` também é pulado — **a thread principal fica sem nenhuma barreira**.
Veja o aviso em [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Faz `allowed_tools` ser de fato exclusivo para as quatro ferramentas de ação.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obrigatório, posicional | normalmente se passa `spec.allowed_tools` direto |
| `role` | `str` | `"这个角色"` | como o papel se refere a si mesmo no texto de recusa. O `Runtime` passa `spec.name` |

- **Entra em `PreToolUse`**, com matcher `"|".join(banned)`, onde `banned` = as ferramentas entre
  `Bash` `Write` `Edit` `NotebookEdit` que não estão em `allowed`.
- Ao acertar, `permissionDecision: "deny"`, com texto no espírito de: "XX não tem YY. **Isso é
  intencional, não é configuração faltando.** Escreva a conclusão no corpo da sua resposta, o
  framework a lê de lá — não tente outra formulação para contornar."
- **Só barra a thread principal desta sessão**, subagents passam — as ferramentas de um subagent
  são decididas por `AgentDefinition.tools`.
- Quando não há nada a barrar, retorna **`None`** (por exemplo, um papel com o kit completo como
  `worker()`); quem chama decide se instala ou não.

**Por que ele precisa existir**: `allowed_tools` é uma **lista de dispensa de aprovação, não uma
whitelist exclusiva**. Duas evidências medidas na prática: um judge com meta definida rodou `Bash`
11 vezes; na sonda de $0.1, um agent com `allowed_tools=["Read"]` chamou `Write`/`Bash` sem
problema.
Ou seja, o "não tem ferramenta de escrita" de `clarify()` / `judge()` **vem deste hook**, não da
whitelist em si.

A vantagem é que ele deriva de `allowed_tools`, então `judge(can_run=True)` mantém `Bash`
automaticamente e continua barrando `Write`/`Edit` — sem precisar de flag extra.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Thread principal pondo a mão → recusa, com indicação do caminho.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. É uma string de regex, não uma lista |
| `allow_glance` | `bool` | `False` | com `True`, libera quando `tool_name == "Bash"` e [`is_ephemeral(command)`](#is-ephemeral) é verdadeiro |

- **Entra em `PreToolUse`**, matcher é o próprio `tools`.
- Thread principal chamando uma dessas quatro ferramentas → deny, e o motivo **diz qual é o próximo
  passo**: usar a ferramenta `Agent` para despachar um subagent, escrever no encargo o objetivo e os
  critérios de aceitação, e exigir que ele escreva produções longas em `.flower/artifacts/` e
  devolva só caminho e conclusão.
- Subagents sempre passam.

A diferença para o `whitelist_guard` é a **formulação**: ambos barram o mesmo conjunto de
ferramentas, mas este diz "vá delegar", que é o mais adequado ali. Por isso um papel com
`delegate_only=True` instala só este; instalar os dois faria o modelo receber duas orientações
contraditórias.

O critério de liberação de `allow_glance=True` e o critério de "o resultado vai ser recortado" são a
**mesma função** ([`is_ephemeral`](#is-ephemeral)) — o conjunto liberado tem que ser igual ao
conjunto que expira; mexeu em um lado, tem que mexer no outro.

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

Resultados de ferramenta acima do limiar vão **para o disco na hora** ([spill](glossary.md#落盘)),
deixando no contexto só uma linha de ponteiro — não é esperar o contexto encher para depois
compactar.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | o diretório de spill é `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | a partir de quantos caracteres vai para o disco |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (padrão) = resultados de subagent também sofrem spill |

- **Entra em `PostToolUse`**, retorna
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <recortado>}}`.
- O nome do arquivo é os 16 primeiros caracteres do `sha256` do conteúdo + `.txt`; no contexto entra
  uma linha de ponteiro + os **400 primeiros caracteres**.
- O `updatedToolOutput` **precisa preservar a estrutura de saída da ferramenta original**, então só
  os **campos string** longos demais do dict são substituídos; **listas nunca são tocadas** (podem
  conter blocos de imagem). Estrutura errada é rejeitada (fica o original, sem erro).
- **Ler o próprio arquivo de spill tem que ser liberado** — senão "use `Read` para lê-lo" é conversa
  fiada: o texto lido de volta sofre spill de novo, em loop infinito. Já aconteceu na prática; o
  modelo tentou cinco formulações seguidas para contornar.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Escreveu algo no [workbench](glossary.md#工作台), o `INDEX.md` é atualizado, e o próximo agent já
começa sabendo que aquilo existe.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | escopo da checagem e alvo do refresh |

**Entra em `PostToolUse`**, matcher `"Write|Edit"`. Se `tool_input["file_path"]`, depois de
resolvido, cai dentro de `workbench.root`, chama `workbench.refresh()`. **Sempre retorna `{}`** —
não altera nada, só tem efeito colateral.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Dá a cada subagent, conforme o papel, um git worktree independente — é assim que o
[isolamento](glossary.md#隔离) acontece.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obrigatório, posicional | tabela de papéis, usada para ver se o `subagent_type` está marcado |
| `on_inject` | `Any` | `None` | callback opcional, chamado como `on_inject(subagent_type, description)` |

**Entra em `PreToolUse`**, matcher `"Agent"`. A injeção só ocorre com as três condições
simultâneas: `tool_name == "Agent"`, `tool_input` **sem `cwd` e sem `isolation`**, e o papel
correspondente ao `subagent_type` marcado por `isolated()`. Nesse caso retorna
`permissionDecision: "allow"` + `updatedInput` (define `isolation` como `"worktree"`).

`isolation` e `cwd` são **mutuamente exclusivos** na ferramenta `Agent` — se o modelo especificou um
`cwd`, isso é respeitado.
"Isolar ou não" é uma **propriedade do papel**, não um botão global nem uma decisão tomada a cada
despacho; papéis que não precisam de isolamento não ganham um byte a mais.

**Ligar isolamento exige tirar o [workbench](glossary.md#工作台) de dentro do repositório.** Um agent
isolado não consegue escrever no checkout compartilhado, então o workbench precisa apontar para fora
do repositório via `home=`. `starter_flow(isolate=True)` usa
`<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` usa `<run_dir>/workbench` —
os dois ficam fora do repositório, **mas não são o mesmo diretório**, não misture.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marca uma definição de subagent como "precisa de workspace próprio", e lê essa marca de volta.

| Função | Parâmetro | Padrão | Descrição |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obrigatório | a definição a marcar. **Retorna o mesmo objeto** |
| | `flag: bool` | `True` | posicional. `False` = remove a marca |
| `wants_isolation` | `agent: AgentDefinition \| None` | obrigatório | aceita `None` também, retornando `False` |

A marca é um atributo `_flower_isolate` do lado Python, gravado com `object.__setattr__`, **não é um
campo de dataclass** — o SDK serializa com `asdict()` e só reconhece campos declarados, então essa
marca não vaza para o lado da CLI (medido na prática).

**Custo**: fazer `dataclasses.replace()` sobre um `AgentDefinition` perde essa marca, e o isolamento
falha silenciosamente.

Por dentro, `worker(isolate=True)` passa por `isolated()`.

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

Instala de uma vez os hooks de que o workbench precisa. É o que `Runtime._attempt` chama.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | repassado a `index_guard` e `spill_guard` |
| `delegate_only` | `bool` | `True` | só instala `delegate_guard` quando `True` |
| `spill_threshold` | `int \| None` | `4000` | só instala `spill_guard` quando verdadeiro |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | se **qualquer um** deles estiver marcado com `isolated()`, acrescenta `isolate_guard` |
| `allow_glance` | `bool` | `False` | repassado a `delegate_guard(allow_glance=)` |

Saída:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  havendo papel marcado → acrescenta `isolate_guard(agents)`.
- `PostToolUse`: sempre `[index_guard(workbench)]`; `spill_threshold` verdadeiro → acrescenta
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Chaves de evento com lista vazia são removidas**, não se retorna lista vazia.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatena** vários grupos de configuração de hook por nome de evento.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variádico | qualquer quantidade de grupos. Grupos `None` são pulados |

Usa `extend`, **sem deduplicação** — passar o mesmo guard duas vezes o instala duas vezes. O
`Runtime` o usa para juntar `spec.hooks`, `workbench_hooks(...)` e `whitelist_guard`.

---

## Workbench {#工作台}

Código-fonte: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

O diretório de trabalho em disco: três subdiretórios + um índice. O índice é **injetado no system
prompt**, então o agent sabe a cada turno o que tem em mãos.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `Path` | obrigatório, posicional | o workspace. `__post_init__` faz resolve |
| `dirname` | `str` | `".flower"` | nome do diretório do workbench, relativo a `workspace` |
| `max_index_entries` | `int` | `40` | **só afeta `prompt_block()`**: quantas entradas por categoria no trecho injetado no system prompt; o excedente vira uma linha "…mais N". O próprio `INDEX.md` não tem limite, lista tudo |
| `home` | `Path \| None` | `None` | se dado, é usado como `root` e **`dirname` é ignorado**. Quando não for `None`, também sofre resolve |

| Membro | Assinatura | Descrição |
|---|---|---|
| `root` | `@property -> Path` | usa `home` se dado, senão `workspace / dirname` |
| `external` | `@property -> bool` | se `root` está **fora** de `workspace`. Em modo isolado deve ser `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts que serão rodados uma segunda vez |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, produções longas acima de 2000 caracteres |
| `notes` | `@property -> Path` | `root / "notes"`, decisões-chave, um arquivo por decisão |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | o caminho mostrado ao modelo: relativo dentro do workspace, absoluto fora dele |
| `ensure` | `() -> Workbench` | faz mkdir dos três diretórios e retorna `self` (encadeável: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(caminho exibido, descrição, bytes)`. `rglob("*")` recursivo, pulando arquivos que começam com `.` |
| `refresh` | `() -> str` | reescreve o `INDEX.md` e devolve o conteúdo |
| `prompt_block` | `() -> str` | **o trecho injetado no system prompt**. Curto de propósito — ele está lá em todos os turnos |

Formato de autodescrição de script: `# desc: uma frase` dentro das 8 primeiras linhas (também
reconhece os comentadores `//` e `--`), com fallback para o primeiro comentário não vazio ou a
primeira linha da docstring (cortada em 100 caracteres).

As três regras que `prompt_block()` injeta:

1. Scripts que serão rodados uma segunda vez vão em `scripts/`, com `# desc:` na primeira linha.
2. Produções acima de **2000 caracteres** vão em `artifacts/`; na conversa, só caminho e conclusão.
3. Decisões-chave vão em `notes/`, um arquivo por decisão.

Quando `external=True`, `prompt_block()` acrescenta uma frase dizendo "acesse por caminho absoluto".

**O índice não é herdado pelos subagents.** Ele vai pelo `system_prompt.append` no nível da sessão, e
subagents têm system prompt próprio (medido: $0.2461). Por isso as duas informações — "produção
longa vai em `artifacts/`" e "onde fica o workbench" — precisam ser repassadas pelo
[coordenador](glossary.md#协调者) dentro do [task brief](glossary.md#任务书): **esse é o único
canal**, não é redundância.
Em `WORKER_RULES` isso **foi deliberadamente omitido**: o caminho real é gerado pelo `Workbench`,
escrevê-lo fixo daria errado.

---

## Session store {#会话存储}

Código-fonte: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Três níveis de herança: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
O `Runtime` **usa sempre o mais externo**; as políticas dos três níveis são controladas por
parâmetros de construção.

Cada nível cuida de uma coisa: persistir, fazer [trim](glossary.md#裁剪) por volume e valor, e fazer
[prune](glossary.md#剪除) pelo critério "isso é um erro?".
Tanto o trim quanto o prune acontecem no momento do **`load()`** (ou seja, quando o resume devolve o
histórico ao modelo); os registros originais no SQLite não mudam um byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementa o protocolo `SessionStore` do SDK, com três tabelas: `entries` / `meta` / `summaries`.
A chave do store é `project_key/session_id[/subpath]` — **o transcript de um subagent se distingue
pelo subpath**.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `str \| Path` | obrigatório, posicional | arquivo do banco. A conexão usa `check_same_thread=False` |

| Método | Assinatura | Descrição |
|---|---|---|
| `append` | `async (key, entries) -> None` | deduplicação idempotente por uuid (primeiro remove os já gravados, depois os repetidos dentro do lote). Em replay de um lote inteiro, **não avança o mtime nem refaz o fold do summary**; só o transcript principal (`subpath is None`) participa do summary |
| `projects` | `() -> list[str]` | os `project_key` que existem de fato no banco. **O SDK o deriva do cwd; confirme com isto antes de consultar, não chute** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **síncrono, não lê payload**, só consulta uma linha de meta. Serve para "continuidade no mesmo caminho" — dar resume numa sessão inexistente só estoura depois que o subprocesso sobe |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | quão grande era o contexto que o modelo realmente viu no último turno; `0` se não achar. Varre de trás para frente só as últimas `scan` entradas; soma `input + cache_read + cache_creation` (olhar só `input_tokens` subestima gravemente) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | ordenado por seq; sem linhas, retorna `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | só o transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | lista os resumos de sessão |
| `delete` | `async (key) -> None` | ao apagar o transcript principal, **apaga em cascata os dos subagents**, evitando órfãos |
| `list_subkeys` | `async (key) -> list[str]` | lista os sub-transcripts sob essa sessão |
| `close` | `() -> None` | fecha a conexão |

O `_next_mtime` interno garante monotonicidade **estrita** — `list_sessions` e o sidecar de summary
compartilham esse relógio; sem isso, o caminho rápido de staleness do SDK erra o julgamento.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `keep_recent` | `int` | `20` | os N `tool_result` mais recentes mantêm o texto original |
| `min_chars` | `int` | `2000` | resultados curtos não valem o corte |
| `spill_dirname` | `str` | `".flower/spill"` | **relativo a `workspace`, tem que ficar dentro do workspace** — senão o `Read` do agent não alcança |
| `enabled` | `bool` | `True` | com `Runtime(trim=False)` isto vira `False` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | gera a linha de ponteiro que substitui o corpo |

**Os dois diretórios de spill não são o mesmo.** O `spill_guard` grava em
`<workbench.root>/spill/` (pode estar fora do workspace); o `TrimPolicy.spill_dirname` grava em
`<workspace>/.flower/spill/` (**tem que estar dentro do workspace**).
Um corresponde ao "corte na hora" e o outro ao "corte no resume"; os diretórios serem diferentes é
intencional, não unifique.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Política de expiração dos resultados de [comandos efêmeros](glossary.md#一次性命令).

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | desligado, a marcação de expiração não acontece de forma alguma |
| `keep_recent` | `int` | `6` | os N mais recentes ficam isentos. **Bem menor que os 20 do `TrimPolicy`** |
| `max_chars` | `int` | `2000` | acima disso é pulado, fica para o `TrimPolicy` arquivar |
| `text` | `str` | ver assinatura | texto de substituição, com os placeholders `{cmd}` e `{age}` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | aplica `text` para gerar o corpo substituto |

**Só age sobre resultados da ferramenta `Bash`**, e o comando precisa bater com a whitelist de
comandos efêmeros. **`Read` não entra nisso** — o conteúdo de um arquivo não se distorce com o
tempo a ponto de enganar. Conteúdo expirado **não sofre spill**, é descartado direto.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Decide se um comando Bash é um [comando efêmero](glossary.md#一次性命令).
**A liberação do `delegate_guard` e a checagem de expiração do trim usam esta mesma função** — o
conjunto de comandos que o coordenador pode rodar sozinho tem que ser igual ao conjunto de
resultados que serão marcados como expirados. Liberar sem recortar faz um `git status` expirado
ocupar contexto para sempre e ainda enganar; recortar sem liberar faz o coordenador despachar um
subagent para um `ls`, trocando 4.3k de custo de arranque por algumas dezenas de caracteres.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cmd` | `str` | obrigatório, posicional | a linha de comando completa |

Ordem de decisão:

1. Vazio / só espaços → `False`.
2. Substituição de comando (`$(`, crase, `<(`, `>(`) ou alguma forma que "muda estado" → `False`.
3. Depois de remover redirecionamentos seguros (`2>&1`, `&> /dev/null` e afins), ainda contém `>` ou
   `<` → `False`.
4. Depois de remover `&&` / `||` / `;` / `|`, ainda sobra um `&` isolado (execução em background) →
   `False`.
5. Quebra por `&&` / `||` / `;` / `|`, e **cada segmento tem que bater com a whitelist**.

Grandes categorias de verbos na whitelist: subcomandos `git` somente-leitura (`status` `diff` `log`
`show` `branch` `rev-parse` etc.), informação de diretório e sistema (`ls` `pwd` `df` `du` `date`
`whoami` `env` etc.), processos e containers (`ps` `top` `lsof` `docker ps` `kubectl get` etc.),
leitura de arquivos (`cat` `head` `tail` `wc` `stat` `find` `tree`), busca de caminhos (`which`
`whereis` `command -v` `type`), processamento de texto (`grep` `rg` `sort` `uniq` `awk` `sed` `jq`
`diff` etc.).

Mesmo com o verbo na whitelist, estas formas são barradas: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` e `print >` dentro de `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

A primeira versão recusava todo comando composto de forma indiscriminada, e **na prática isso matou
o glance por completo** (as três tentativas do coordenador foram todas barradas), então passou a
avaliar segmento por segmento.

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

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `str \| Path` | obrigatório | arquivo do banco |
| `workspace` | `str \| Path` | obrigatório | base do diretório de spill |
| `policy` | `TrimPolicy \| None` | `None` | sem valor, usa o `TrimPolicy()` padrão |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | sem valor, usa o `EphemeralPolicy()` padrão |

Atributos públicos: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Ordem no `load()`: `super().load()` → limpa `last_report` → se `ephemeral.enabled`, `expire()` →
se `policy.enabled`, `trim()`. **Com `enabled=False`, o passo inteiro é pulado.**

| Método | Descrição |
|---|---|
| `expire(entries)` | nos resultados `Bash` sensíveis ao tempo que expiraram, **troca só o corpo, mantém o bloco**. O comando é buscado no `tool_use` da mensagem assistant anterior; pula `isCompactSummary` / `isMeta`; pula os acima de `max_chars` (ficam para o `trim`); os últimos `keep_recent` são isentos. Escreve `last_report["expired"]` |
| `trim(entries)` | o corpo de `tool_result` com `>= min_chars` vai para `<workspace>/<spill_dirname>/<16 primeiros do sha256>.txt`, e o conteúdo do bloco vira um ponteiro; os últimos `keep_recent` são isentos. Escreve `cleared` / `kept` / `chars_saved` em `last_report` |

**Só recorta texto puro**: blocos `image` / `document` são deixados como estão.

**Duas linhas vermelhas estruturais**: o **bloco `tool_result` tem que continuar existindo**, só se
pode trocar o content (faltar um já é "Missing Tool Result Block"); entradas `isCompactSummary` não
podem ser tocadas.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renderiza `store.last_report` como uma linha de texto em chinês, para log da UI.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obrigatório, posicional | aceita também a subclasse `PruningSessionStore` |

Três saídas possíveis: nada feito → `"未裁剪"`; só expiração → `"N 个时效性结果标记为过期"`;
caso contrário `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, onde X = `chars_saved // 4`.

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

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | remove mensagens sintéticas de erro da API (resíduo de queda de conexão) |
| `neutralize_interrupts` | `bool` | `True` | `tool_result` residual de interrupção vira uma nota neutra |
| `interrupt_text` | `str` | ver assinatura | o texto dessa nota neutra |
| `heal_orphans` | `bool` | `True` | insere um resultado sintético para chamadas órfãs ("tem `tool_use` mas não tem `tool_result`") |
| `orphan_text` | `str` | ver assinatura | o corpo do `tool_result` inserido |
| `keep_denials` | `int` | `1` | mantém as N chamadas de ferramenta recusadas mais recentes |

`heal_orphans` cura o caso de **todo resume dar 400 depois de uma interrupção**: a interrupção corta
na fronteira de mensagem, e o `tool_use` que estava em voo pode simplesmente não ter `tool_result`
depois dele, enquanto a API exige os dois em par — esse histórico defeituoso fica no transcript e
derruba **cada uma** das tentativas de resume seguintes. `heal_orphans()` insere uma entrada `user`
logo após a mensagem assistant que contém o órfão, completando o resultado que falta, e redireciona
o `parentUuid` que apontava para aquela assistant para a entrada inserida, mantendo a cadeia contínua
(`prune.py:95-147`). **Completa em vez de remover**: remover o órfão exigiria refazer a cadeia
pai-filho da assistant, e na mesma mensagem pode haver blocos normais, texto e thinking, o que
facilmente causa dano colateral (`prune.py:195-204`).

O motivo de `keep_denials`: uma chamada recusada nunca foi executada, não há informação no resultado,
mas ocupa espaço razoável (medido: 273 caracteres em um caso = 93 caracteres de texto de recusa +
180 caracteres do **comando morto na íntegra**). Mais grave: **ela engana** — medido na prática, o
coordenador, depois de ler algumas entradas de "não use Bash diretamente", parou de tentar até mesmo
o `git status` liberado, aprendendo desamparo adquirido.
**O padrão é 1 e não 0**: a recusa mais recente evita que o modelo repita várias vezes o mesmo
comando barrado dentro do mesmo turno.

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

**O store padrão do `Runtime`.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `str \| Path` | obrigatório | arquivo do banco |
| `workspace` | `str \| Path` | obrigatório | base do diretório de spill |
| `policy` | `TrimPolicy \| None` | `None` | política de trim |
| `prune` | `PrunePolicy \| None` | `None` | política de prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | política de expiração |

Além dos da classe-mãe, três atributos públicos: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (primeiro `expire` + `trim`) → `self.prune(entries)`. O `prune` faz três
coisas:

1. **Remove as chamadas recusadas antigas demais**: identificadas pela marca estrutural
   `toolDenialKind == "permission-rule"` do harness (mais confiável do que casar o texto da recusa),
   mantendo as últimas `keep_denials` e removendo, das demais, o bloco `tool_use` **e** o
   `tool_result` juntos. Quando há vários `tool_use` na mesma mensagem assistant, **só o acertado é
   removido**, senão vira "Missing Tool Result Block"; blocos de texto e thinking são preservados.
2. **Remove as mensagens sintéticas de erro da API.** Elas continuam intactas no SQLite, só não são
   realimentadas.
3. **Troca o `tool_result` residual de interrupção por uma nota neutra** — só o corpo, a entrada não
   é removida.

**A única linha vermelha estrutural**: o transcript é uma cadeia simples por `parentUuid`; ao remover
uma entrada é obrigatório reconectar seus filhos ao ancestral vivo mais próximo.
O `entries` do `relink` interno **tem que ser a lista completa (incluindo as que serão removidas)**,
pois a filtragem é feita por ele mesmo — se quem chama filtrar antes de passar, a cadeia quebra ali
e todo o histórico anterior se perde (**já pisamos nisso: não aparece quando as entradas removidas
estão no fim, mas estoura quando estão no meio**).

**A ordem dos parâmetros difere da classe-mãe**: a mãe é `(path, workspace, policy, ephemeral)`, a
filha é `(path, workspace, policy, prune, ephemeral)` — **o quarto posicional mudou de `ephemeral`
para `prune`**, e passar por posição desloca tudo silenciosamente. Sempre passe por palavra-chave.

---

## Resiliência {#韧性}

Código-fonte: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Quando a rede cai, fica pendurado esperando em vez de sair com falha. Quatro exports: uma dataclass
de política + três funções de sondagem que podem ser usadas isoladamente.

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

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | desligado, nenhuma falha é retentada |
| `max_attempts` | `int` | `6` | **inclui a primeira tentativa** |
| `base_delay` | `float` | `4.0` | base do backoff, em segundos |
| `max_delay` | `float` | `120.0` | teto do backoff, em segundos |
| `probe_timeout` | `float` | `5.0` | timeout de uma sondagem |
| `probe_interval` | `float` | `15.0` | espera entre duas sondagens |
| `max_offline_wait` | `float` | `3600.0` | quanto tempo no máximo fica pendurado esperando; padrão 1 hora |
| `retry_unknown` | `bool` | `True` | se erros não classificáveis devem ser retentados |
| `resume_prompt` | `str` | ver assinatura | o que se diz ao retomar. **Deliberadamente sem nenhum detalhe do erro** — o modelo precisa saber "foi interrompido, continue", não se foi `ENOTFOUND` ou 503 |

| Método | Assinatura | Descrição |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` com `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | fica pendurado esperando a rede voltar. Voltou, retorna `True`; passou de `max_offline_wait`, retorna `False`. `notify` é um callback `(str) -> None`, disparado uma vez **na primeira vez que fica inacessível** e uma vez **na recuperação** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classifica o texto do erro em três categorias: `"transient"` / `"fatal"` / `"unknown"`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `text` | `str \| None` | obrigatório, posicional | a mensagem de erro original. Vazia retorna `"unknown"` |

**Testa fatal antes de transient** — textos como os de 401 costumam trazer a palavra `connection`;
com a ordem invertida, ficaria esperando para sempre.

| Categoria | O que casa |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

Host e porta a sondar, seguindo `ANTHROPIC_BASE_URL`, com padrão `https://api.anthropic.com`;
a porta padrão é `80` (http) ou `443`.

**Ao usar um gateway próprio, é ele que precisa ser sondado** — `api.anthropic.com` responder não
prova nada sobre o gateway.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `host` | `str` | obrigatório, posicional | nome do host |
| `port` | `int` | obrigatório, posicional | porta |
| `timeout` | `float` | `5.0` | segundos |

**Faz só DNS (`getaddrinfo`) + handshake TCP**, sem HTTP, sem credenciais, **sem gastar dinheiro**.
Qualquer exceção conta como inacessível.

---

## Eventos e interação {#事件与交互}

Código-fonte: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[Evento](glossary.md#事件) é a estrutura estável em que o fluxo de mensagens do SDK é achatado. **A [camada de interação](glossary.md#交互层) só conhece
`Event`, não importa nenhum tipo do SDK** — é essa a fronteira que permite trocar de UI sem mexer no núcleo. Veja [Trocar a camada de interação](../guide/interaction.md).

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

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `kind` | `EventKind` | obrigatório | veja a tabela abaixo |
| `text` | `str` | `""` | corpo do texto |
| `tool` | `str` | `""` | nome da ferramenta, só existe em `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | informação adicional estruturada |
| `raw` | `Any` | `None` | objeto original do SDK, para quando você quiser cavar fundo |

`__str__`: em `tool_call` é `f"[{tool}] {text}"`, caso contrário é `text`, e se `text` estiver vazio é `f"<{kind}>"`.
Ou seja, `print(ev)` já sai legível.

`EventKind` tem **15** valores no total:

| kind | Quem emite | Descrição |
|---|---|---|
| `text` | `normalize` | corpo de texto do assistant |
| `thinking` | `normalize` | bloco de raciocínio |
| `tool_call` | `normalize` | chamada de ferramenta. `text` é o resumo de `file_path` / `command` / `pattern`, cortado em 200 caracteres |
| `tool_result` | `normalize` | resultado da ferramenta. `text` cortado em 500 caracteres, payload traz `tool_use_id` / `is_error` |
| `task` | `normalize` | três tipos de mensagem Task. `text` **está vazio**, o nome da classe fica em `payload["kind"]` |
| `system` | `normalize` | demais mensagens de sistema, `text` é o subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, payload traz `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | mensagem sintética de erro de API, payload traz `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **O corpo é entrada, não produção do modelo**, por isso não entra em `StepResult.text` |
| `unknown` | `normalize` | não reconhecido |
| `retry` | `Runtime` | aviso de retentativa |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | no payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | pergunta, **também carrega "o que a pessoa disse por iniciativa própria"** |

**Os quatro últimos não são produzidos por `normalize()`.**

Todos os eventos de assistant / user trazem no `payload`:

| Chave | Tipo | Descrição |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | só existe quando `subagent` é verdadeiro |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **É a única fonte do critério de [handoff](glossary.md#换代)**, e também o número que mais merece ser visto numa run long-horizon |

**O kind `ask` carrega ao mesmo tempo "pergunta" e "fala espontânea da pessoa".** No segundo caso, `payload["kind"] == "mail"`,
**sem `options` / `remaining`**. A UI precisa checar `payload.get("kind")` antes de decidir como renderizar,
senão vai tratar uma frase como uma pergunta pendente e ficar travada nela.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Achata uma mensagem do SDK em 0 a N `Event`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `message` | `Any` | obrigatório, posicional | qualquer objeto de mensagem do SDK |

Ramificações-chave:

- **Mensagem sintética de erro de API** (`isApiErrorMessage=True` ou `model == "<synthetic>"`) → um único
  `Event("error", payload={"synthetic": True})`. **Isso é intencional** — caso contrário o texto de queda de conexão seria tratado como corpo,
  entraria em `StepResult.text` e seria repassado ao passo seguinte.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<resumo>, tool=block.name, payload={"id", "input"})`.
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

Uma pergunta feita à pessoa.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `id` | `str` | obrigatório | usado para localizar a pergunta na hora de responder |
| `question` | `str` | obrigatório | corpo da pergunta |
| `options` | `list[str]` | `[]` | alternativas. A pessoa também pode não escolher e digitar a própria resposta |
| `asked_at` | `float` | `time.time()` | momento da pergunta |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | corpo da resposta |

| Membro | Assinatura | Descrição |
|---|---|---|
| `waited_s` | `@property -> float` | há quanto tempo está esperando |
| `event` | `(remaining: int = 0) -> Event` | produz `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

Um **servidor MCP dentro do processo** (duas ferramentas) + um conjunto de métodos para a UI. Do lado do modelo só aparecem
`mcp__human__ask` e `mcp__human__inbox`. Todos os parâmetros do construtor são keyword-only.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | a saída do modo **push**. Se você passar isso, `Workflow.run` não conecta mais nada |
| `max_asks` | `int \| None` | `None` | **sem limite de vezes**. Um número é cota rígida, `0` = proibido perguntar (totalmente automático / CI). Ao estourar, a ferramenta **recusa direto, sem bloquear** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutos. `None` = espera para sempre; **`<= 0` = não espera, toda pergunta cai no vazio imediatamente** |
| `log_path` | `str \| Path \| None` | `None` | perguntas e respostas são **anexadas** ao disco, não ocupam contexto |
| `amend_path` | `str \| Path \| None` | `None` | o que a pessoa disser no meio da run é anexado a este arquivo (em geral o próprio brief). **Sem spill não sobrevive à fronteira de passo** — o próximo passo é uma sessão nova, que só lê o artefato congelado |
| `over_budget_text` | `str` | constante do módulo | o que responder ao modelo quando a cota estourar |
| `timeout_text` | `str` | constante do módulo | o que responder ao modelo em caso de timeout |
| `declined_text` | `str` | constante do módulo | o que responder ao modelo quando a pergunta for pulada |

Atributos públicos: os oito com o mesmo nome dos parâmetros do construtor, mais `asks: list[Ask]`, `mail: list[Mail]` e
`ui_errors: list[str]` (**exceções lançadas pelo callback da UI são recolhidas aqui, sem interromper a run**).

| Membro | Assinatura | Descrição |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | entra direto em `AgentSpec.mcp_servers`. **A chave precisa bater com o nome do server**, por isso é ele quem entrega o dicionário pronto |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | fica pendurado esperando a pessoa. **Fora de `CancelledError`, nunca lança exceção** — ninguém responder também é uma resposta, distinga por `ask.state` |
| `send` | `(text: str) -> Mail \| None` | a pessoa fala algo por iniciativa própria. **Pode ser chamado de qualquer thread**. Não interrompe o agent; internamente chama `amend()` automaticamente |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | anexa em `amend_path`. Retorna se realmente escreveu (sem caminho configurado, texto vazio ou `OSError` são todos `False`) |
| `pending_mail` | `() -> list[Mail]` | mails ainda não retirados |
| `remaining` | `@property -> int` | quantas perguntas restam. **Com `max_asks=None` retorna `-1`**, não 0 nem infinito |
| `pending` | `() -> list[Ask]` | perguntas atualmente penduradas aguardando resposta |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | usado no modo **pull**. Retorna `None` em timeout; se for cancelado, lança |
| `answer` | `(ask_id: str, text: str) -> bool` | responde. `False` = essa pergunta já não está esperando (timeout / já respondida) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | pula, deixando o modelo decidir sozinho |
| `transcript` | `() -> str` | o markdown do registro de perguntas e respostas |

**Escolha uma das duas formas de consumir**: **push** — construa `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` só faz a ligação automática quando `channel.on_event is None`, então se você passou o seu, ele não é sobrescrito.

**Entre threads**: `answer` / `decline` / `send` usam `loop.call_soon_threadsafe` internamente,
chamar direto de um backend Web / thread de entrada da TUI é o uso normal.

Os três "0 / None" têm semânticas diferentes, não misture: `max_asks=None` = sem limite, `max_asks=0` = proibido perguntar;
`timeout_s=None` = espera para sempre, `timeout_s<=0` = timeout imediato; `remaining` é `-1` quando `max_asks=None`.

`Mail`, que não é exportado mas aparece em valores de retorno, é um dataclass com os campos `id` / `text` / `sent_at` / `taken`.

---

## Linhagem {#血缘}

Código-fonte: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Registra entre processos "qual passo usou qual sessão"; é por ela que a [continuidade](glossary.md#接续) descobre onde a run parou.
O arquivo é `<run_dir>/lineage.json`.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `Path` | obrigatório | caminho do arquivo de linhagem |
| `workspace` | `Path` | obrigatório | área de trabalho. `__post_init__` faz resolve |
| `steps` | `dict[str, str]` | `{}` | nome do passo → `session_id` |
| `woke` | `int` | `0` | quantas vezes acordou |

| Membro | Assinatura | Descrição |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lê `<run_dir>/lineage.json`. **Se o arquivo não existir, não puder ser lido, ou o campo `workspace` não bater, retorna vazio sem erro** |
| `remember` | `(step: str, session_id: str) -> None` | guarda o mapeamento e **faz spill na hora**. Step vazio ou sid vazio retornam direto |
| `bump` | `() -> int` | incrementa o contador de wake em 1, faz spill, retorna o novo valor (na primeira execução é `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **move** o arquivo de linhagem + `extra` para `<into>/<YYYYmmdd-HHMMSS>/` e zera `steps` / `woke`. **Mover não é apagar** |

O spill usa substituição atômica via `tmp.replace(path)`; `OSError` é engolido em silêncio — uma falha de escrita não deve derrubar a run.

**`workspace` é uma guarda**: a `project_key` do SDK é derivada do caminho da área de trabalho; se o diretório for copiado para outro lugar, os `session_id` antigos não são encontrados,
então caminho que não bate é tratado como inexistente.

Ao carregar a linhagem, `Workflow.run` valida cada registro com `runtime.has_session(sid)` para ver se ainda está no banco, e só usa o que estiver vivo —
o arquivo de linhagem pode viver mais que o `sessions.db`.

---

## Exemplos mínimos utilizáveis {#示例}

Os cinco trechos rodam direto. Pré-requisito: `claude-agent-sdk` instalado e `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` disponível
(caso contrário `Runtime(...)` já lança `RuntimeError` na construção).

### Um agent rodando um passo {#示例-单-agent}

Esqueleto mínimo: declare um `AgentSpec`, crie um `Runtime`, `await rt.run(...)`, leia o `StepResult`.

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

Os parâmetros de `Runtime` são **todos keyword-only**; em `rt.run()`, `spec` e `prompt` são posicionais e o resto é keyword-only.
`AgentSpec` tem por padrão `allowed_tools=["Read", "Glob", "Grep"]` e `delegate_only=False`,
então o `Runtime` instala automaticamente o [`whitelist_guard`](#whitelist-guard) nele, barrando `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordenador + executor {#示例-协调}

Um [coordenador](glossary.md#协调者) que não põe a mão na massa com um [executor](glossary.md#执行者) que trabalha.
Essa é a primeira camada de economia de contexto do flower.

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

    # workbench=True é obrigatório: o delegate_guard fica pendurado em workbench_hooks;
    # sem a workbench, o Bash/Write do coordenador não tem nenhum hook barrando.
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

Os dois primeiros parâmetros de `worker()` são posicionais: `description` (o coordenador usa para escolher quem chamar) e `prompt` (o system prompt dele,
com `WORKER_RULES` concatenado automaticamente depois). Em `coordinator()`, os três primeiros são posicionais: `name`, `instructions`, `workers`.

### Escrevendo seu próprio Workflow {#示例-workflow}

Dois passos, com o segundo injetando o resultado do primeiro no próprio prompt — barato, isolado, sem compartilhar sessão.

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
        # Sessão nova: só consome o que está no prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Sessão nova + resultado do passo anterior injetado no prompt (barato, evita contaminação)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Para continuar falando na mesma sessão, escreva resume_from="造句"; para bifurcar, acrescente fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (quando não há reduce)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # com on_fail="stop", em qual passo falhou


asyncio.run(main())
```

Os três primeiros campos de `Step` (`name` / `spec` / `prompt`) são posicionais, e o `steps` de `Workflow` também.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` posicional, os dois callbacks keyword-only.
**Atenção: `continuous=True` é o padrão**: na segunda execução com o mesmo `run_dir` + o mesmo `workspace`,
até os passos com `resume_from=None` continuam falando na mesma sessão da vez anterior.

### Acrescentando um goal guard {#示例-目标}

Primeiro o [judge](glossary.md#判定者) fixa o objetivo e a lista de critérios, depois o passo de trabalho passa a aceitar o veredito —
se não passar, refaz com o feedback, no máximo três rodadas.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = totalmente automático: toda pergunta cai no vazio na hora, sem fingir que espera alguém
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds é o **total de rodadas**: rounds=3 → retries=2 → no máximo três rodadas de trabalho
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # O prompt do goal_step lê ctx["确认需求"] (valor padrão de brief_key).
        # Sem um clarify_step, preencha você mesmo; senão ele só verá "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: objeto Goal
    print(ctx["_verdict"])     # VERDICT_KEY: o Verdict mais recente
    print(ctx["_goal_rounds"]) # ROUND_KEY: quantas rodadas rodaram
    print(ctx.get("_aborted")) # motivo do StepAbort (inalcançável e sem ninguém respondendo)


asyncio.run(main())
```

`with_goal` só troca `gate` / `on_reject` / `retries`; os demais campos são levados intactos por `dataclasses.replace`.
O judge roda em **sessão independente**: internamente o `gate` chama `rt.run(judger, ..., step_name=f"{label}#{轮次}")` à parte,
com `resume` sempre `None`.

### Trocando a camada de interação {#示例-交互层}

Para trocar o terminal por Web / TUI / HTTP, só é preciso mudar duas coisas: a função que renderiza `Event` e a corrotina que pega as perguntas.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Renderiza o Event na sua própria UI — é a única coisa que precisa ser trocada."""
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
    # kind == "ask" que não seja mail fica a cargo do answerer abaixo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Coleta de perguntas em modo pull. Ao trocar por backend Web / serviço HTTP, esta corrotina é o único ponto a mudar."""
    while True:
        ask = await ch.next_ask()          # sem timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # O Runtime usa a workbench que o workflow já criou — não monte outra
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push e pull: **escolha um**. Push é construir `HumanChannel(on_event=...)`, pull é `await channel.next_ask()`.
`Workflow.run` só faz a ligação automática quando `channel.on_event is None`, então se você passou o seu `on_event`, ele não é sobrescrito.
`answer()` / `decline()` / `send()` / `interrupt()` **podem todos ser chamados de outra thread**.

---

## Armadilhas e pontos de erro {#陷阱}

Na ordem em que você vai tropeçar, não por módulo. Cada item tem origem medida na prática.

### Montagem {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = nenhuma barreira na main thread.**
   O `delegate_guard` só é instalado quando existe workbench, e o `whitelist_guard` é pulado por `delegate_only=True`.
   Se usa coordenador, ligue a workbench. Veja [Runtime](#runtime).
2. **A workbench tem dois lugares possíveis, não confunda.** `Runtime(workbench=True)` cai em `<run_dir>/workbench`;
   `Workbench(ws)` cai por padrão em `<ws>/.flower`. Ao montar `brief_path` na mão, siga o segundo caso,
   senão **o brief é escrito no diretório A, o índice injetado varre o diretório B, e não dá erro nenhum**.
   Jeito correto: o próprio workflow faz `Workbench(...).ensure()` e pendura em `Workflow.workbench`,
   e então entrega **o mesmo objeto** para `Runtime(workbench=wb)`.
3. **`allowed_tools` não é uma whitelist exclusiva, é uma lista de dispensa de aprovação.** O modelo continua podendo chamar ferramentas que não estão nela.
   O "não tem ferramenta de escrita" de `clarify()` / `judge()` depende do hook [`whitelist_guard`](#whitelist-guard).
   Já `coordinator()` usa por padrão `permission_mode="acceptEdits"` — quem repassar esse valor para
   `clarify()` / `judge()` perde a proteção.
4. **`disallowed_tools` é a nível de sessão**, e proíbe junto as ferramentas de mesmo nome nos subagents.
5. **O índice da workbench não chega aos subagents.** "Produção longa vai para `artifacts/`" precisa ser repassado pelo coordenador no task brief;
   esse é o único canal.
6. **`Runtime(...)` lança `RuntimeError` já na construção quando não há credencial**, não na hora do `run()`.
7. **`Runtime.run_id` precisa ser único por instância.** O `manifest.json` deduplica pelo campo `run`; quando dois ids colidem,
   o que escreve depois apaga as linhas do outro achando que são "as que eu mesmo escrevi da última vez".

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` é o padrão**, e `resume_from=None` não significa "sessão totalmente nova".
   Para abrir sessão nova sempre, passe explicitamente `continuous=False`. **Mudar o nome de um passo equivale a cortar a linhagem.**
9. **`with_goal(rounds=N)` é o total de rodadas, não rodadas extras**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` não escreve `ctx[step.name]`** — um `lambda ctx: ctx["某步"]` a jusante dá `KeyError`.
    Para seguir adiante carregando o resultado incompleto, use `on_fail="continue"`.
11. **`resume_from` apontando para um passo não executado / que falhou lança `ValueError`**, não pula em silêncio.
12. **`Step.reduce` precisa ser função síncrona; `gate` / `when` / `on_reject` podem ser async.**
13. **`fork=True` sem `resume` é silenciosamente inócuo.** O `Workflow` nunca passa `resume_at`;
    para retroceder por mensagem só chamando `Runtime.run` diretamente.
14. **Ao dirigir o `Runtime` você mesmo, `on_session` precisa ser removido antes do gate**, senão a sessão do judge é gravada na linhagem
    do passo de trabalho. O `Workflow` garante isso com `try/finally`.
15. **`step_name` define a chave no manifest e na linhagem.** O `Workflow` acrescenta sufixos `#retryN` / `#roundN`,
    e o judge acrescenta `#轮次` — **nomes com sufixo não entram na linhagem entre processos**, e é exatamente assim que se implementa "o judge é sempre sessão nova".

### Papéis {#陷阱-角色}

16. **`clarify(max_turns=<número pequeno>)` transforma "perguntas ilimitadas" em conversa fiada** — cada pergunta é um turno.
17. **`goal_step()` não tem o parâmetro formal `can_run`**, só dá para passar `can_run=True` via `**spec_kw`.
    Sem isso, o judge que define o objetivo não recebe `Bash`, e a regra "primeiro entenda em que ambiente você está" das `JUDGE_RULES` não pode ser executada.
18. **`judge(can_run=True)` permite que o judge altere a área de trabalho** — o `whitelist_guard` é derivado de `allowed_tools`,
    e dar `Bash` libera `Bash` (ainda bloqueia `Write`/`Edit`, mas o próprio `Bash` escreve arquivos). Para neutralidade absoluta, não ligue.
19. **`worker(isolate=True)` exige que a workspace seja um repositório git**, senão a ferramenta `Agent` retorna direto
    `"not in a git repository"`, sem degradar em silêncio. Além disso, a marca de isolamento é um atributo Python,
    e **fazer `dataclasses.replace()` sobre um `AgentDefinition` a perde**.
20. **Ao construir `AgentDefinition` diretamente, os parâmetros são camelCase**: `maxTurns`, `permissionMode`.
    `worker()` já faz essa conversão por você.

### Handoff e contexto {#陷阱-换代}

21. **Com o handoff ligado, o auto-compact é forçadamente desligado, sem rede de segurança.** Por isso o passo que escreve o handoff document precisa ter caminho de degradação.
    Para manter o auto-compact, passe `AgentSpec.compact` explicitamente.
22. **Um `HandoffPolicy.window` pequeno demais gera handoffs infinitos queimando dinheiro.** A única comporta é `max_generations=8`.
    Do outro lado, **`default_window()` também retorna `1_000_000` quando nenhuma das duas variáveis de ambiente está definida** —
    um valor alto demais é amparado por `is_overflow()` (vira um handoff degradado), não é erro fatal, mas o handoff daquela geração é degradado.
23. **Sem workbench, o handoff não faz spill.** O documento continua sendo entregue ao sucessor pelo prompt, mas depois ninguém consegue recuperá-lo.

### Armazenamento {#陷阱-存储}

24. **`Runtime(trim=False)` (padrão) não significa "não limpa nada".** O store é sempre `PruningSessionStore`;
    `trim=False` só desliga o trim de resultados grandes; **remover resíduo de queda de conexão, remover chamadas recusadas, neutralizar restos de interrupção e expirar conteúdo com prazo continuam acontecendo.**
25. **Os dois diretórios de spill não são o mesmo**: o `spill_guard` cai em `<workbench.root>/spill/`,
    e `TrimPolicy.spill_dirname` cai em `<workspace>/.flower/spill/` (precisa estar dentro da área de trabalho).
26. **O quarto parâmetro posicional de `PruningSessionStore.__init__` é `prune`, não `ephemeral`**,
    diferente da classe base. Passar por posição desalinha silenciosamente.

### Documentos e interação {#陷阱-文书}

27. **Quando o `Verdict` não consegue extrair a conclusão, `state=""` e `ok=False`; isso jamais pode ser tratado como aprovado.**
    Além disso, "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" caem todos em `unreachable`,
    o que dispara o caminho de "parar e perguntar à pessoa", não o de "mais uma rodada".
28. **`Brief.parse` descarta todo o conteúdo posterior a uma cerca de código não fechada** — quando a saída do modelo é truncada,
    nenhuma das seções seguintes é analisada, `complete()` fica `False` e o gate manda refazer.
29. **`Brief.load` trata `"(未填)"` como vazio.** Se, ao editar o brief à mão, você copiar o texto de placeholder, aquela seção continua contando como faltante.
30. **Os três "0 / None" de `HumanChannel` têm semânticas diferentes**: `max_asks=None` sem limite, `max_asks=0` proibido perguntar;
    `timeout_s=None` espera para sempre, `timeout_s<=0` timeout imediato; `remaining` retorna **`-1`** quando `max_asks=None`.
31. **`Event("ask")` carrega ao mesmo tempo perguntas e falas espontâneas da pessoa**, com `payload["kind"] == "mail"` no segundo caso. A UI precisa checar isso antes.
32. **`Workflow.run` só faz a ligação automática quando `channel.on_event is None`** —
    se você construir `HumanChannel(on_event=...)` por conta própria, os eventos de pergunta não passam também pela saída `on_event` do workflow.
