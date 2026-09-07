# Python API

Esta página esgota os **62 símbolos públicos** do `__all__` de topo do `flower`: assinaturas, parâmetros, valores default, semântica, atributos e métodos públicos. Depois de ler, você não precisa mais abrir o código-fonte para descobrir um parâmetro.

A organização segue **o que te interessa**, não os arquivos de módulo — se você quer saber "como impedir que o [coordenador](glossary.md#协调者) meta a mão ele mesmo", vá para a [camada de hooks](#hook); se quer saber "como o resultado do passo anterior chega ao próximo", vá para [workflow](#流程). A terminologia segue o [glossário](glossary.md) sem exceção.

Versão `0.1.0`, dependência `claude-agent-sdk>=0.2.152`. Todas as assinaturas correspondem literalmente ao código-fonte.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # um único import de topo
```

## O que tem nesta página {#索引}

| O que te interessa | Símbolos |
|---|---|
| [Rodar um agent](#运行时) | `Runtime` `StepResult` |
| [Encadear vários passos](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Construir um papel](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Escrever uma definição de agent à mão](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documentos estruturados](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Barrar ferramentas, recortar resultados, separar isolamento](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [O diretório de trabalho do spill](#工作台) | `Workbench` |
| [Como e o que a session é guardada](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [O que fazer quando a rede cai](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Trocar a UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Retomar a última execução entre processos](#血缘) | `Lineage` |

## Seis defaults que mordem {#危险默认值}

Estes seis não são detalhe periférico; são os seis capotamentos mais comuns. Cada um tem explicação completa na seção correspondente.

| Default | Consequência | Detalhes |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` da thread principal ficam **sem um único hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Força `CompactPolicy(mode="no_summary")` na spec, ou seja, `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Um passo com `resume_from=None` ainda assim retoma aquela session da execução anterior, entre processos | [Workflow](#workflow) |
| `build_options(fork=True)` sem `resume` | Falha em silêncio, sem erro | [build_options](#build-options) |
| `clarify(max_turns=<número pequeno>)` | Transforma "perguntar sem limite de vezes" em conversa fiada — cada pergunta é um turno | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | É por session, e proíbe junto para os subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Código-fonte: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` é o núcleo de execução. Ele guarda o workspace, o [session store](glossary.md#会话存储), o [workbench](glossary.md#工作台), a política de [resiliência](glossary.md#韧性) e a política de [handoff](glossary.md#换代), e expõe um único verbo: `run` de um passo. Retry, retomada depois de uma interrupção e handoff quando o contexto enche — tudo acontece dentro dessa mesma chamada.

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

Os parâmetros do construtor são **todos keyword-only** (`*` na frente de tudo), e `workspace` é obrigatório.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | obrigatório | O `cwd` do agent. Resolvido na construção, com `mkdir(parents=True, exist_ok=True)`. O `project_key` do SDK é derivado dele — se o diretório for copiado para outro lugar, os `session_id` antigos deixam de ser encontrados |
| `run_dir` | `str \| Path` | `"runs"` | Onde ficam `sessions.db`, `manifest.json`, `lineage.json` e o workbench default quando `workbench=True`. Também resolvido, com mkdir |
| `portable` | `bool` | `True` | Repassado para `build_options(portable=)`, ou seja, `setting_sources=[]`: não lê o `~/.claude/` da máquina hospedeira, nem o `.claude/` do projeto. Ver [portátil](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Se você passa uma instância, ela é usada direto; se passa um `bool`, vira `TrimPolicy(enabled=bool(trim))`. **Desligar só significa não recortar resultados grandes; a poda continua acontecendo** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Mesma regra de conversão. Anda em par com `coordinator(glance=True)` — se você libera a thread principal para rodar `git status`, tem que garantir que esse resultado expire |
| `keep_denials` | `int` | `1` | Passado para `PrunePolicy(keep_denials=)`. Mantém as últimas N chamadas de ferramenta negadas; as mais antigas são removidas junto com chamada e resultado |
| `workbench` | `Workbench \| bool` | `False` | Se você passa uma instância, ela é usada direto; se passa `True`, cria `Workbench(workspace, home=run_dir / "workbench")` (**por default fica fora do workspace**). Em seguida chama `refresh()` imediatamente |
| `spill_threshold` | `int \| None` | `4000` | A partir de quantos caracteres o resultado de uma ferramenta vai para [spill](glossary.md#落盘). `None` ou `0` = não instala o `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Mesma regra de conversão |
| `handoff` | `HandoffPolicy \| bool` | `True` | Mesma regra de conversão |

**O session store é fixo no código**: é sempre
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Os parâmetros do construtor **não oferecem** um ponto de entrada para trocar o backend — se quiser trocar, construa você mesmo `AgentSpec` + `build_options(session_store=...)`, ou sobrescreva `rt.store` depois de construir.

Os dois últimos passos da construção são `load_dotenv()` e `check_credentials()`, e **o segundo faz `raise RuntimeError` se houver erro**. Sem credenciais, o estouro acontece na construção, não quando `run()` é chamado.

!!! warning "`workbench=False` + `coordinator()` = a thread principal sem nenhuma parede"
    O `delegate_guard` só é instalado dentro de `workbench_hooks`, e `workbench_hooks` só é chamado quando `self.workbench is not None`; já o `whitelist_guard` é pulado pelo `if not spec.delegate_only`. E `coordinator()` sempre define `delegate_only=True` e, por default, `glance=True` dá `Bash`.

    **Conclusão: com um coordenador em cima de `Runtime(workbench=False)`, seus `Bash`/`Write`/`Edit` não têm nenhum hook barrando.** Se usar `coordinator()`, ligue o `workbench` — `Runtime(..., workbench=True)` ou passe uma instância de `Workbench`.

!!! warning "`handoff=True` (o default) força o desligamento do auto-compact"
    Dentro de `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, o que chega ao subprocesso como `DISABLE_AUTO_COMPACT=1`. O motivo é que, com os dois mecanismos ligados ao mesmo tempo, fica impossível dizer quem causou a queda do contexto.

    **O preço: o passo que escreve o handoff precisa ter um caminho degradado** (`handoff.degraded`), porque não existe mais o compact como rede de segurança. Para preservar o auto-compact, informe explicitamente `AgentSpec.compact` (se a spec já traz o seu, ele é respeitado e não sobrescrito).

#### Atributos públicos {#runtime-属性}

| Atributo | Tipo | Descrição |
|---|---|---|
| `workspace` | `Path` | O workspace depois de resolvido |
| `run_dir` | `Path` | O diretório de execução depois de resolvido |
| `portable` | `bool` | Guardado como veio |
| `store` | `PruningSessionStore` | O session store. Trocar o backend só é possível sobrescrevendo isto depois da construção |
| `resilience` | `Resilience` | A instância normalizada |
| `handoff` | `HandoffPolicy` | A instância normalizada |
| `workbench` | `Workbench \| None` | É `None` quando `workbench=False` |
| `spill_threshold` | `int \| None` | Guardado como veio, repassado para `workbench_hooks` dentro de `_attempt` |
| `results` | `list[StepResult]` | Cada passo executado neste processo, acrescentado em ordem |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Precisa ser único por instância** — o `manifest.json` deduplica pelo campo `run`, e se dois ids colidirem, o que escreve depois trata a linha do outro como se fosse a sua própria escrita anterior e a apaga |
| `on_session` | `Callable[[str], None] \| None` | Callback disparado **imediatamente** ao obter um novo `session_id`, default `None`. **Só deve envolver a linha do `runtime.run`** — o [juiz](glossary.md#判定者) usa o mesmo `Runtime`, e se o callback continuar pendurado durante o gate, a session do juiz vai parar na [linhagem](glossary.md#血缘) do passo que fez o trabalho |

Constantes de classe: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`, `INTERRUPT_NOTE` (um trecho anexado depois da fala da pessoa ao retomar de uma interrupção, explicando que "chamadas de ferramenta em voo retornarem interrupted é um efeito colateral normal da interrupção, não uma falha de ambiente").

#### Métodos públicos {#runtime-方法}

| Método | Assinatura | Descrição |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Roda um passo. Ver abaixo |
| `interrupt` | `(message: str = "") -> None` | Pede a interrupção do turno atual. **Pode ser chamado de qualquer thread.** Cooperativo: desliga limpo numa **fronteira de mensagem**, sem cancelamento forçado. String vazia = interromper sem dizer nada |
| `rescue` | `() -> None` | Antes de ser morto à força, tenta fechar as contas; chamado pelos handlers de `SIGHUP`/`SIGTERM`. O passo em voo também é escrito no manifesto, com `error="killed-by-signal"`. Só faz escritas síncronas pequenas |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())` com `/`, `_` e `.` todos trocados por `-`. **O SDK deriva isso do cwd; quem chama não pode especificar** |
| `has_session` | `(session_id: str) -> bool` | Esse id ainda é encontrável **neste workspace**? Síncrono, não lê o payload |
| `context_of` | `(session_id: str) -> int` | O tamanho do contexto no último turno de uma session; delega para `store.last_context` |
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

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `spec` | `AgentSpec` | obrigatório, posicional | A declaração do agent a rodar |
| `prompt` | `str` | obrigatório, posicional | O que é dito neste turno |
| `step_name` | `str \| None` | `None` | A chave que aparece em `StepResult.step`, no manifesto e na linhagem. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Retomar este `session_id` |
| `fork` | `bool` | `False` | Bifurca uma nova session sem poluir a original. **Só tem efeito quando `resume` é verdadeiro** |
| `resume_at` | `str \| None` | `None` | Retomar a partir de uma mensagem específica (rollback). Também **só tem efeito quando `resume` é verdadeiro** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | A saída de eventos, ver [`Event`](#event) |

No início de cada passo o nível de contexto é zerado (`self._ctx, self._warned = 0, False`). Depois vem um laço com quatro saídas:

1. **Sucesso** → sai do laço.
2. **Interrupção humana** (`result.error == INTERRUPTED`) → **não está sujeita a `max_attempts`** e não espera pela rede. Faz `resume` na mesma session levando a fala da pessoa, com `attempt -= 1` (interrupção não conta como tentativa fracassada), e o prompt = fala da pessoa + `INTERRUPT_NOTE`. **Se não houver `session_id`, só resta parar.**
3. **Contexto cheio** (`result.error == HANDOFF_DUE`, ou `handoff.enabled` e há `session_id` e `is_overflow(...)` dispara) → **também não está sujeito a `max_attempts`**. Primeiro verifica `len(result.retired) >= handoff.max_generations`; se passou, troca o error por uma frase de diagnóstico e sai do laço; senão escreve o [documento de handoff](glossary.md#交接书) → `resume=None, fork=False` (**session totalmente nova**) → o prompt vira `h.prompt_block()` → nível de contexto zerado → `attempt -= 1`.
4. **Falha retentável** → se `not resilience.enabled or attempt >= max_attempts`, sai do laço; se `classify(error)` decidir que não se deve retentar, também sai; caso contrário emite `Event("retry")`, fica pendurado em `wait_online()` esperando a rede e faz `sleep(delay_for(attempt))`; **se algum `session_id` já foi obtido, retoma com `resume`** (o prompt vira `resilience.resume_prompt`), e marca `result.resumed` como `True`.

Encerramento: escreve `ended_at`, acrescenta em `self.results`, escreve `manifest.json`.

O `manifest.json` tem semântica de **append**: cada escrita relê o disco e deduplica pelo campo `run` (a linha própria é substituída, as dos outros ficam), então rodar dois flower em paralelo no mesmo `run_dir` é seguro — desde que os `run_id` não colidam.

**Os três pontos de observação do handoff** (todos `Event("handoff")`, diferenciados por `payload["phase"]`): `near` (aproximando-se de `warn_at`, emitido uma única vez por geração), `writing` (o handoff está sendo escrito, leva uns dez e tantos segundos), `done` (o payload traz `degraded` / `path` / `sections`). O turno que escreve o handoff roda com `replace(spec, max_budget_usd=None)` — o handoff precisa conseguir ser escrito, não pode travar no orçamento; e com `on_event=None`, esse turno não vai para a UI.

O handoff é gravado em `<workbench.notes>/交接-<步骤名>.md`; **sem workbench não há gravação**, o documento é entregue ao sucessor pelo prompt do mesmo jeito, só não dá para consultá-lo depois. Handoffs antigos são movidos para `notes/archive/交接/<名>-<时间戳>.md`.

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

Todas as contas de um passo terminado.

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `step` | `str` | obrigatório | Nome do passo (`step_name` ou `spec.name`) |
| `session_id` | `str \| None` | `None` | **É sempre a última session que assumiu** — as queimadas por handoff no meio do caminho estão em `retired` |
| `ok` | `bool` | `False` | Se o passo deu certo ou não |
| `cost_usd` | `float` | `0.0` | Em dólares. **Acumulado** ao longo de retries e handoffs |
| `num_turns` | `int` | `0` | Número de turnos, também acumulado |
| `text` | `str` | `""` | **Contém apenas o corpo da thread principal.** As falas dos subagents ficam nos transcripts deles, e o brief de tarefa que lhes é delegado é `kind="prompt"`; nenhum dos dois entra aqui |
| `error` | `str \| None` | `None` | Motivo da falha. Valores especiais em `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Número real de tentativas. Interrupções e handoffs **não contam** |
| `errors` | `list[str]` | `[]` | Mensagens de erro sintéticas da API, recolhidas; **não entram em `text`** |
| `resumed` | `bool` | `False` | Se houve retomada com resume no meio do caminho |
| `retired` | `list[str]` | `[]` | Os `session_id` queimados pelos handoffs deste passo, em ordem |
| `context` | `int` | `0` | O tamanho de contexto que a thread principal de fato viu no último turno, ou seja, o critério de handoff |

| Propriedade | Tipo | Descrição |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`; é `0.0` se não terminou |

---

## Workflow {#流程}

Código-fonte: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Um [workflow](glossary.md#流程) é um conjunto de [passos](glossary.md#步骤) encadeados em ordem, mais
as regras de como o estado passa de um passo a outro e quando sair mais cedo. **O framework não fornece
workflows prontos; o workflow é você quem escreve** — `starter_flow` é apenas um modelo que roda.

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

A **declaração** de um passo. `Step` em si não é uma função — quem executa de fato é
`Runtime.run(step.spec, prompt, ...)`. Os três primeiros campos são posicionais, então
`Step("取词", terse, "读 seed.txt …")` é escrita válida.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do passo. **Chave estável entre processos** — cai em `ctx[name]`, `ctx["_results"]`, no manifesto e na linhagem. Renomear = quebrar a linhagem |
| `spec` | `AgentSpec` | obrigatório | Qual agent executar |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | O que dizer. Pode ser um closure que recebe o `ctx` e calcula na hora |
| `resume_from` | `str \| None` | `None` | De qual passo retomar a sessão. Se o passo apontado não produziu sessão, **lança `ValueError`** — não é pulado silenciosamente |
| `fork` | `bool` | `False` | Bifurca a partir de `resume_from`. **Sem `resume_from` não tem efeito** |
| `retries` | `int` | `0` | Quantas tentativas a mais quando o gate não passa. `retries=0` = uma única rodada |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide se esta tentativa passou. **Pode ser async**. Retornar `False` conta como falha. **Chamado uma única vez por tentativa** — ele pode ter efeitos colaterais (gravar o brief em disco, por exemplo) e não deve ser disparado repetidamente |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, ver abaixo |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Retornar `False` **pula o passo inteiro**: não produz result, não entra em `ctx["_results"]`. **Pode ser async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **O que dizer na próxima rodada** quando o gate não passa. **Pode ser async**. Fornecê-lo muda a semântica do retry, ver abaixo |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt usado quando há continuidade (em vez de recomeçar do zero) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decide o que vai em `ctx[name]`. Por padrão, o texto original de `result.text`. **Tem que ser função síncrona** |

| Método | Assinatura | Descrição |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Com `resuming` e havendo `resume_prompt`, usa este último; caso contrário usa `prompt`; se for chamável, invoca passando `ctx` |

**Três formas de encadear sessões** (dentro da mesma execução):

| Escrita | Efeito |
|---|---|
| `resume_from=None` (padrão) | Sessão nova, só com o contexto passado no prompt. Barato, isolado. **Mas com `Workflow(continuous=True)` ele pega a sessão do passo de mesmo nome na linhagem entre processos** |
| `resume_from="nome do passo anterior"` | Retoma a mesma sessão, contexto completo. Caro, coerente |
| `resume_from="nome do passo anterior", fork=True` | Bifurca sem contaminar a sessão original. Para revisão / múltiplas alternativas em paralelo |

**`on_reject` muda a semântica do retry**:

- Não fornecido → a próxima tentativa **recomeça do zero** (mesmo prompt, mesmo `resume_from`).
- Fornecido → a próxima tentativa **retoma exatamente a sessão que acabou de ser rejeitada**, o prompt vira o valor retornado e `fork` é forçado para `False`.
- Retorna string vazia → não devolve nada, degrada para recomeço do zero.
- `result.session_id` é `None` → também degrada para recomeço do zero.

**Os três valores de `on_fail`**:

| Valor | Comportamento |
|---|---|
| `"stop"` (padrão) | Escreve `ctx["_failed_at"] = name` e **interrompe o workflow inteiro** |
| `"skip"` | Vai para o próximo passo, **`ctx[name]` não é escrito** — um `lambda ctx: ctx["algum passo"]` a jusante vai dar `KeyError` |
| `"continue"` | `ctx[name] = result.text`, segue adiante com o resultado incompleto |

Passando ou não, `ctx["_results"][name] = result` é sempre escrito; quando `result.session_id` não é
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

Executa uma sequência de `Step` em ordem e devolve o `ctx` final. `steps` é posicional, então
`Workflow([...])` é válido.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `steps` | `list[Step]` | obrigatório | Executados em ordem |
| `name` | `str` | `"workflow"` | Nome do workflow |
| `context` | `Ctx` | `{}` | Dicionário de contexto inicial. **Na segunda execução do mesmo `Workflow`, o ctx é o mesmo dict** |
| `channel` | `HumanChannel \| None` | `None` | Onde pendurar o canal quando for preciso parar e perguntar a um humano. `run()` liga automaticamente o `on_event` dele à mesma saída, **apenas se `channel.on_event is None`**; o programa driver também usa esse campo para saber a quem responder |
| `workbench` | `Workbench \| None` | `None` | Workbench indicado pelo workflow, para o driver conseguir encontrá-lo |
| `continuous` | `bool` | `True` | Mesmo caminho = mesma conversa. A implementação é [`Lineage`](#lineage) |

| Parâmetros de `run()` | Tipo | Padrão | Descrição |
|---|---|---|---|
| `runtime` | `Runtime` | obrigatório, posicional | Com qual runtime executar |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída de eventos, repassada a cada `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback disparado ao fim de cada passo |

!!! warning "`continuous=True` é o padrão, e `resume_from=None` não significa sessão nova"
    Com continuidade ligada, `run()` primeiro chama `Lineage.open(run_dir, workspace)` e depois valida
    cada registro com `runtime.has_session(sid)` para ver se ainda está na base; só os vivos são
    injetados em `ctx["_sessions"]`. Ou seja, **passos com `resume_from=None` também continuam falando
    na sessão da vez anterior** — inclusive depois de o processo ser morto ou a máquina reiniciar.

    Para ter sempre sessão nova, escreva explicitamente `Workflow(..., continuous=False)`.
    Além disso: **o nome do passo é a chave estável entre processos; mudar o nome do passo é quebrar a linhagem.**

As **chaves privadas** que `run()` escreve no ctx (todas começam com `_`, então não colidem com nomes de passo):

| Chave | Conteúdo |
|---|---|
| `_runtime` | O `Runtime` recebido. **É por ele que um gate despacha agents** |
| `_on_event` | Saída de eventos. Aquele agent dentro do gate também precisa chegar na UI, senão a interface fica no escuro |
| `_sessions` | `dict[nome do passo, session_id]`, lido com `setdefault` |
| `_results` | `dict[nome do passo, StepResult]` |
| `_lineage` | Objeto `Lineage`. Só existe com `continuous=True` e quando o runtime tem `run_dir` + `workspace` |
| `_woke` | Retorno de `lineage.bump()`, qual despertar é este |
| `_aborted` | Mensagem do `StepAbort` |
| `_failed_at` | Nome do passo que falhou quando `on_fail="stop"` |

Payload de `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Rótulos de retry**: a tentativa 0 usa `step.name`; depois disso, havendo `on_reject`, usa
`f"{name}#round{attempt+1}"`, e sem ele `f"{name}#retry{attempt}"`. No manifesto dá para ver de
relance como aquele passo terminou.
**Nomes com sufixo não entram na linhagem entre processos** — `Lineage.remember` usa o nome original.

`runtime.on_session` cobre apenas a chamada `runtime.run`, com `try/finally` para garantir que seja
removido antes do gate.
`prompt_cur` / `resume_cur` / `fork_cur` são variáveis locais e não são escritas de volta no `step` —
o mesmo objeto `Step` pode ser executado uma segunda vez.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Lançado pelo `gate` = **pare agora, não tente de novo**. A diferença para "retornar `False`": `False`
é "desta vez não deu, mais uma rodada"; `StepAbort` é "de novo também não vai adiantar".

Depois de lançado: `ctx["_aborted"] = str(exc)`, `passed = False`, **sai do laço de retry (sem consumir
os `retries` restantes)** e depois segue o `on_fail` como uma falha comum (padrão `"stop"`).

`with_goal` o lança em dois pontos: quando não consegue obter `ctx["_runtime"]` e quando o veredito é
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

Produz um `Step` que faz a [clarificação prévia](glossary.md#前置确认): esclarecer os requisitos →
parsear para um [`Brief`](#brief) → congelar e gravar em disco quando as quatro seções estiverem completas.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `brief_path` | `str \| Path` | obrigatório | Onde o [brief](glossary.md#需求确认书) é gravado. **Tem que cair no workbench que é de fato injetado no índice** |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | O pedido original da pessoa |
| `name` | `str` | `"确认需求"` | Nome do passo, e também a chave no `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções adicionais para o [clarificador](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = pergunta tudo de novo toda vez, exista o brief ou não |
| `on_fail` | `str` | `"stop"` | Igual a `Step.on_fail` |
| `retries` | `int` | `0` | Quantas vezes perguntar de novo quando as quatro seções não fecham |
| `**spec_kw` | | | Repassado direto para [`clarify()`](#clarify-role), então dá para escrever `can_read=False`, `max_budget_usd=...` |

Os campos do `Step` produzido são preenchidos assim:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: com `always_ask=True` → sempre `True`; caso contrário, se `Brief.load(brief_path)` estiver
  completo, injeta no ctx **e então retorna `False` (pula)** — mesmo pulando é preciso injetar, senão
  os passos a jusante ficam sem os requisitos.
- `gate`: `Brief.parse(result.text)`; incompleto → escreve `ctx[MISSING_KEY]` e retorna `False`;
  completo → `b.write(brief_path)` congela, injeta no ctx e retorna `True`.
- `reduce`: retorna `ctx[BRIEF_KEY].prompt_block()`, **não o texto original do modelo** — nesse texto
  pode vir junto coisa que ele escreveu a mais.
- `resume_from` **fica no padrão `None`**: o próximo passo é uma sessão nova, recebe só o brief, não
  aquela sequência de perguntas e respostas. As perguntas da clarificação prévia **nunca entraram** no
  contexto do coordenador; não é que entraram e depois foram cortadas.

Os três pontos de injeção no ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`,
`ctx.pop(MISSING_KEY, None)`.

| Constante | Valor | Descrição |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` é o objeto `Brief`; `ctx[step.name]` é o `prompt_block()` dele |
| `MISSING_KEY` | `"_brief_missing"` | Quais seções faltam quando a clarificação falha (nomes das seções em chinês), para a UI exibir |
| `CLARIFY_RESUME` | um prompt em chinês | "Continue a confirmação de requisitos que ficou pela metade — **não recomece do zero**…". Sem essa frase, a continuidade reenvia o pedido original como se fosse tarefa nova e o clarificador pode repetir perguntas já feitas |

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

Produz um `Step` que **define o objetivo**: faz o [juiz](glossary.md#判定者) ler o brief e escrever o
objetivo + a lista de verificações, parseia para um [`Goal`](#goal) e congela em disco. Tem o mesmo
formato de `clarify_step`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `goal_path` | `str \| Path` | obrigatório | Onde o arquivo de objetivo é gravado |
| `brief_key` | `str` | `"确认需求"` | Pega o texto do brief em `ctx[brief_key]` e enfia no prompt. **Se não achar, vira `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nome do passo |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções adicionais |
| `always_set` | `bool` | `False` | `True` = refaz a lista, exista o arquivo de objetivo ou não |
| `on_fail` | `str` | `"stop"` | Idem acima |
| `retries` | `int` | `0` | Idem acima |
| `**spec_kw` | | | Repassado para [`judge()`](#judge-role) |

**Não existe parâmetro `can_run`** — para deixar o juiz que define o objetivo rodar comandos, só
passando `can_run=True` via `**spec_kw`. Sem isso ele não tem `Bash`, e a regra "primeiro entenda em
que ambiente você está" do `JUDGE_RULES` não pode ser executada.

Além de parsear e congelar, o `gate` faz mais uma coisa: quando o objetivo contém itens
`[此环境无法验证:…]`, ele emite **na hora**, via `ctx["_on_event"]`, um
`Event("task", payload={"unverifiable", "total", "path"})` como aviso — o destino desses itens já está
selado no momento em que o objetivo é definido; na hora do veredito você já gastou o dinheiro de uma
rodada inteira de trabalho.

**Não define `resume_prompt`** — definir o objetivo deve mesmo reenviar o brief por inteiro.

| Constante | Valor | Descrição |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` é o objeto `Goal`; `ctx[step.name]` é o markdown |
| `VERDICT_KEY` | `"_verdict"` | O [`Verdict`](#verdict) mais recente, para a UI |
| `ROUND_KEY` | `"_goal_rounds"` | Quantas rodadas de veredito já rodaram |

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

Coloca uma [guarda de objetivo](glossary.md#目标看守) sobre um `Step` já existente: ao fim de cada
rodada o juiz emite um veredito independente e, se o objetivo não foi atingido, devolve o trabalho para
continuar.

O resultado é `replace(step, retries=max(0, rounds - 1), gate=<novo gate>, on_reject=<novo on_reject>)` —
usando `dataclasses.replace` em vez de reconstruir campo a campo; reconstruir já deixou passar o
`resume_prompt` uma vez, **e sem erro nenhum**, só que na continuidade o brief inteiro era reenviado.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `step` | `Step` | obrigatório, posicional | O passo sob guarda |
| `channel` | `HumanChannel` | obrigatório, posicional | Canal para pedir ajuda humana quando o veredito trava |
| `goal_path` | `str \| Path` | obrigatório | Arquivo de objetivo, lido daqui quando `ctx[GOAL_KEY]` não está completo |
| `spec` | `AgentSpec \| None` | `None` | Se não for dado, usa `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Total de rodadas, não rodadas extras**: `rounds=3` → `retries=2` → no máximo três rodadas de trabalho. `rounds=1` = uma rodada, um veredito, e se não passar, falhou |
| `instructions` | `str` | `""` | Instruções adicionais para o juiz |
| `can_run` | `bool` | `False` | Se o juiz pode rodar `Bash` |
| `name` | `str \| None` | `None` | Nome do juiz, por padrão `f"{step.name}·判定"` |
| `**spec_kw` | | | Repassado para `judge()` |

O `gate` é **async**, e o fluxo é:

1. `ctx["_runtime"]` ausente → **lança `StepAbort`** ("não consegui o Runtime, impossível julgar o objetivo"). **Não finja que passou.**
2. `ctx[ROUND_KEY] += 1`.
3. Obtém o objetivo: primeiro um `Goal` completo em `ctx[GOAL_KEY]`, senão `Goal.load(goal_path)`, senão um `Goal()` vazio.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{rodada}", on_event=...)`.
   **O juiz é uma chamada `Runtime.run` independente, com `resume` sempre `None` — é sempre sessão nova**;
   o `step_name` carrega a rodada, então não entra na linhagem entre processos.
5. `Verdict.parse(vr.text)` é escrito em `ctx[VERDICT_KEY]`.
6. `v.achieved` → retorna `True`.
7. Não é `unreachable` (incluindo o caso ambíguo de `v.ok=False`) → em caso ambíguo acrescenta uma reason padrão e retorna `False`.
   **Ambiguidade conta sempre como não atingido** — não dá para deixar um "parece que dá" encerrar o trabalho.
8. `unreachable` → `await channel.ask(...)` pergunta à pessoa, com três opções:
   - Ninguém responde (`a.state != "answered"`) → **lança `StepAbort`**. Continuar girando em falso é a opção mais cara.
   - «Aceitar este resultado e seguir assim» → retorna `True`.
   - «Alterar o objetivo» → pergunta de novo qual é o novo objetivo, `g.amend(...).write(goal_path)`, atualiza `ctx[GOAL_KEY]` e retorna `False`.
   - Qualquer outra coisa (inclusive uma resposta livre digitada pela pessoa) → tratado como "você julgou errado", registra o que a pessoa disse em `v.reason` e retorna `False`.

O `on_reject` é **síncrono**: retorna `ctx[VERDICT_KEY].feedback()`, e sem `Verdict` retorna `""`
(degrada para recomeço do zero).

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

Monta um workflow de três passos que roda de imediato: **clarificar requisitos → definir objetivo →
trabalhar** (com guarda de objetivo). É isso que a linha de comando `flower` usa.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `ask` | `str` | obrigatório, posicional | Uma frase com o pedido. **Ao despertar, ela não é uma tarefa nova, é "mais uma frase dita"** |
| `workspace` | `str \| Path` | `"."` | Área de trabalho |
| `run_dir` | `str \| Path` | `"runs"` | Diretório de execução |
| `new` | `bool` | `False` | `True` = arquiva linhagem + brief + objetivo (os três juntos) e recomeça do zero |
| `isolate` | `bool` | `False` | Abre um worktree de [isolamento](glossary.md#隔离) para o worker. O workbench se muda junto para `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Devolve apenas o Workflow com o passo de clarificação |
| `goal` | `bool` | `True` | Instalar ou não a [guarda de objetivo](glossary.md#目标看守). `False` = terminou o passo de trabalho, acabou |
| `rounds` | `int` | `3` | Repassado a `with_goal(rounds=)`, total de rodadas |
| `judge_can_run` | `bool` | `False` | Repassado a `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Repassado ao `HumanChannel`, `None` = sem limite |
| `timeout_s` | `float \| None` | `1800.0` | Repassado ao `HumanChannel`. `0` = totalmente automático, toda pergunta cai no vazio imediatamente |
| `instructions` | `str` | `""` | Instruções adicionais para o clarificador |
| `worker_prompt` | `str` | ver assinatura | System prompt do worker |
| `brief_name` | `str` | `"需求.md"` | Nome do arquivo de brief, gravado em `<workbench.notes>/` |
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

- `isolate=True` com um workspace que não é repositório git → **lança `ValueError`**, sem esperar a
  ferramenta `Agent` dar erro para só então descobrir (a essa altura o dinheiro já foi gasto).
- **Detecção de despertar**: se `Brief.load(brief_path)` existe e está `complete()`, é um despertar.
  Se não é despertar e `ask` está vazio →
  **lança `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Ao despertar, aquela frase cai em **três lugares** ao mesmo tempo, e faltar um só já a torna
  silenciosamente inócua: é anexada ao brief
  (`ch.amend(said, label="唤醒时追加")`, sem reescrever se já estiver no arquivo),
  faz `goal_step(always_set=True)` refazer a lista (sem refazer, o juiz continua lendo o objetivo antigo)
  e vai direto para o coordenador (o contexto dele tem o objetivo **antigo**; sem isso ele trabalha
  pelo critério antigo e depois é julgado pelo critério novo).

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

**Sondagem somente leitura antes da largada; não escreve um único byte.** Serve para dizer à pessoa,
antes de começar de verdade, "isto é continuação da vez passada ou é do zero".

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Área de trabalho, posicional |
| `run_dir` | `str \| Path` | `"runs"` | Diretório de execução |
| `isolate` | `bool` | `False` | Determina a posição do workbench; tem que ser o mesmo valor passado a `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nome do arquivo de brief |
| `goal_name` | `str` | `"目标.md"` | Nome do arquivo de objetivo |

O dict devolvido:

| Chave | Tipo | Descrição |
|---|---|---|
| `waking` | `bool` | O brief existe e as quatro seções estão completas |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Número de itens da lista do objetivo, `0` quando não há objetivo |
| `woke` | `int` | `Lineage.woke`, quantas vezes já despertou |
| `steps` | `dict` | Cópia de `Lineage.steps`, nome do passo → `session_id` |

A posição do workbench **é definida uma única vez, aqui e em `starter_flow`**: `isolate=True` →
`<ws>.parent/.flower-<ws.name>` (fora do repositório); caso contrário `<ws>/.flower`. O driver que
quiser saber onde está o brief também passa por esta função — montar o caminho por conta própria e
errar não dá erro, só falha em silêncio.

---

## Fábrica de papéis {#角色工厂}

Código-fonte: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Os cinco papéis são funções fábrica. Cada papel = **um trecho de texto de regras injetado + um conjunto de ferramentas + um conjunto de hooks**.
`worker()` produz um `AgentDefinition` do SDK (para uso como subagent); os outros quatro produzem [`AgentSpec`](#agentspec) (que abre uma sessão própria).

Os papéis em si **não instalam hooks** — quem intercepta ferramentas é `Runtime._attempt`, que instala automaticamente conforme `spec.delegate_only`; veja [camada de hooks](#hook).

Constantes internas de grupos de ferramentas (não exportadas, mas determinam os valores padrão):

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

Cria o [coordenador](glossary.md#主线程) que roda na [thread principal](glossary.md#协调者): decompõe a tarefa, delega, lê relatórios, decide, **mas não põe a mão na massa**. Os três primeiros parâmetros são posicionais.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, também o nome padrão do step |
| `instructions` | `str` | obrigatório | Instruções de domínio. O resultado final é `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obrigatório | Quais papéis ele comanda; vai para `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Se fornecido, acrescenta as duas ferramentas `inbox` **e** `ask`, e define `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → remove `Read` |
| `glance` | `bool` | `True` | Acrescenta `"Bash"` e define `AgentSpec.glance`. **O que exatamente pode ser executado é decidido por `delegate_guard`**, não aqui |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [orçamento](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Modo de permissão. **Atenção a esse padrão** — passá-lo para `clarify()`/`judge()` desmonta a proteção desses dois papéis |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, o `Runtime` não o força para `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks adicionais, mesclados com `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variáveis de ambiente adicionais |

Três itens fixos no `AgentSpec` produzido: `delegate_only=True`, `agents=workers` e `workbench` mantendo o padrão `True` do `AgentSpec`.

O código-fonte diz explicitamente para **não usar `disallowed_tools` para implementar "só coordena, não executa"** — isso é a nível de sessão e desabilitaria também `Bash`/`Write` dos subagents; veja o aviso em [`AgentSpec`](#agentspec).
O jeito correto é o daqui: `delegate_only=True` + não passar `allowed_tools`, deixando [`delegate_guard`](#delegate-guard) barrar apenas a thread principal pelo `agent_id`.

Se `channel` for fornecido, **as duas ferramentas vêm juntas**, não é opcional: uma vez montado o MCP server, ambas estão lá, e `allowed_tools` não é exclusivo — listadas ou não, são chamáveis. Sem supervisão humana, cada `ask` fica travado até estourar o `timeout_s` — nesse cenário use `HumanChannel(timeout_s=0)`.

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

Cria a definição do [subagent](glossary.md#subagent) que de fato executa. Os dois primeiros parâmetros são posicionais.
O retorno é um `AgentDefinition` do SDK, que vai direto para `coordinator(workers={...})`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `description` | `str` | obrigatório | **É por aqui que o coordenador escolhe quem chamar** — deixe claro "que tipo de trabalho vai para ele" |
| `prompt` | `str` | obrigatório | O system prompt dele. Com `discipline=True`, vira `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | O worker não deve ser rebaixado |
| `effort` | `str \| int \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Vai para o **`maxTurns`** do SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Vai para o **`permissionMode`** do SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Quais skills ele pode usar |
| `discipline` | `bool` | `True` | Concatenar ou não o trecho de disciplina de relato `WORKER_RULES` |
| `isolate` | `bool` | `False` | Marca de [isolamento](glossary.md#隔离), passa por `isolated()`; **não é um campo do `AgentDefinition`** |

`isolate=True` exige que o workspace seja um repositório git; caso contrário a ferramenta `Agent` reporta direto `"not in a git repository"` e **não degrada silenciosamente**. Além disso, a marca é um atributo Python — fazer `dataclasses.replace()` sobre o `AgentDefinition` a perde, e o isolamento falha em silêncio.

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

Cria o [clarificador](glossary.md#确认者): antes de agir, esclarece o requisito; não faz nada, só pergunta, e ao final produz exatamente quatro seções.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Se `True`, acrescenta `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | **Sem limite de turnos** |
| `max_budget_usd` | `float \| None` | `None` | Teto de orçamento |

No `AgentSpec` produzido: `allowed_tools = [channel.tool_name] + (as cinco de leitura, quando permitido)`, `mcp_servers = channel.mcp_servers()`, `workbench=False` (ele não tem ferramenta de escrita, o índice não lhe serve de nada) e `permission_mode` herdando o padrão `"default"` do `AgentSpec`.
**Não tem `Write` / `Edit` / `Bash` / `Agent`, e nem `inbox`** (diferente do coordenador).

!!! warning "Um `max_turns` pequeno transforma o "perguntar sem limite" em conversa fiada"
    Cada pergunta é um turno. `max_turns=16` equivale a "pergunte no máximo umas dezena e meia", e aquela frase do canal — "não há limite de turnos" — vira letra morta na hora.

    Para liberar de fato as perguntas é preciso liberar **os dois lados**: `HumanChannel.max_asks` (já é `None` = sem limite por padrão) e `max_turns` (já é `None` por padrão).

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

Cria o [juiz](glossary.md#判定者): ou define o objetivo antes da largada, ou emite o veredito ao fim de cada rodada.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Se `True`, adiciona `Bash` à whitelist; `whitelist_guard` passa a liberar `Bash` e continua barrando `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de orçamento |

No `AgentSpec` produzido: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (quando `can_run`) `["Bash"]`, `workbench=False`, e o resto igual a `clarify()`. **Não tem `Write` / `Edit` / `Agent`, e nem `inbox`.**

**Trade-off**: `can_run=True` dá um veredito mais duro (ele pode rodar de verdade os comandos de aceitação), ao custo de o juiz poder alterar a área de trabalho — `Bash` por si só já escreve arquivos. Se você quer um veredito absolutamente neutro, não ligue.

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

Cria o [oracle](glossary.md#旁路顾问): com a run ainda em andamento, você pergunta "onde estamos agora" e ele dá uma olhada nos eventos recentes e na bancada antes de responder. **O que ele diz não entra no contexto daquela run.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nome do papel, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | **`12`** | Vem com freio por padrão |
| `max_budget_usd` | `float \| None` | **`0.5`** | Vem com freio por padrão. Isso é uma "pergunta de passagem", não deve sair do controle |

No `AgentSpec` produzido: `allowed_tools = ["Read", "Glob", "Grep"]` (**sem channel** — ele não pergunta, só responde), `workbench=True` (**o único dos cinco papéis que não é coordenador e mesmo assim tem a bancada ligada** — é justamente para ler os artefatos e as notas).

### Os cinco textos de regras {#rules}

As cinco constantes estão em `__all__`; dá para importá-las direto para ler, concatenar e alterar.

| Constante | Injetada em quem | Forma de injeção | Pontos principais |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Você é "uma pessoa que sabe usar o Claude Code", não o worker; não pode escrever arquivos/alterar código/rodar testes; `Bash` só serve para "dar uma olhada" e o resultado expira; **o [task brief](glossary.md#任务书) só descreve o que é específico desta tarefa**; a única regra que ainda precisa ser transmitida é "onde fica a bancada + artefatos longos vão para `artifacts/` + na resposta só passe o caminho"; consulte o `inbox` a cada ação concluída; `ask` bloqueia, use só em bifurcações reais |
| `WORKER_RULES` | `worker()` | Concatenada **depois** do `prompt` do subagent | Formato de resposta **结论 / 依据 / 产出 / 未验证**, no máximo 30 linhas; proibido colar conteúdo de arquivo, saída de comando, log ou diff; proibido narrar o processo de tentativa e erro; antes de agir, olhe `.flower/scripts/`. **Deliberadamente não diz "artefatos longos vão para `artifacts/`"** — o caminho real é gerado pela `Workbench`, e fixá-lo no texto daria errado |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Não executa nada, só esclarece o requisito; **não há limite de vezes, pergunte até ficar claro**; a pessoa pode não estar presente — em caso de timeout, decida por conta própria e registre em 「未知与假设」; a saída tem **exatamente quatro seções**; não escreva código, não cole conteúdo de arquivo |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Duas tarefas, uma ou outra. **Definir o objetivo**: cada item da lista precisa ser verificável na hora, o tamanho da lista é ditado pelo número de modos de falha, **limites não são itens de veredito**, e itens não verificáveis levam no final `[此环境无法验证:原因]`. **Julgar a rodada**: saída com **exatamente três seções**, julga-se **o artefato, não o código-fonte**, por padrão não se acredita em "terminei", "não atingiu" e "aqui não dá para verificar" são conclusões diferentes, e a segunda **jamais pode ser julgada como aprovada** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Um canal lateral; aquela run continua rodando, você não a interrompe nem participa dela; **somente leitura**; responde e descarta, o que você diz não entra no contexto daquela run; você só tem a "janela de eventos recentes" e a "bancada"; olhe antes de responder, se não souber diga que não sabe, seja breve |

---

## Definição de agent {#agent-定义}

Código-fonte: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` é a declaração completa de um agent especializado, e `build_options` a compila para o `ClaudeAgentOptions` do SDK.
O que a [fábrica de papéis](#角色工厂) produz é exatamente um `AgentSpec` — quando você precisa de uma combinação fora da fábrica, construa-o diretamente.

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
| `instructions` | `str` | obrigatório | Instruções de domínio. **[Somadas](glossary.md#叠加) depois do system prompt nativo do Claude Code, não o substituem** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Lista de dispensa de aprovação, não whitelist exclusiva** — o modelo continua podendo chamar ferramentas fora dela. A exclusividade vem do [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Nível de sessão**. Veja o aviso abaixo |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [orçamento](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Modo de permissão |
| `agents` | `dict[str, Any] \| None` | `None` | Tabela de definições de subagents; os valores são `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabela de MCP servers. `HumanChannel.mcp_servers()` preenche direto aqui |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks adicionais; o `Runtime` os mescla com os seus via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, o `Runtime` não o força para `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variáveis de ambiente injetadas no subprocesso. `compact.env()` faz update sobre elas |
| `glance` | `bool` | `False` | Permite ao coordenador rodar por conta própria um `Bash` de "só dar uma olhada". O que passa é decidido por [`is_ephemeral`](#is-ephemeral), e o resultado é marcado como expirado pela `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Injetar ou não o índice da bancada no system prompt deste agent. **Papéis sem ferramenta de escrita devem desligar** (`clarify()` / `judge()` já vêm com `False`) |
| `delegate_only` | `bool` | `False` | Só coordena, não executa. Com `True`, o `Runtime` instala `delegate_guard` e **não instala** `whitelist_guard` |

!!! warning "`disallowed_tools` é a nível de sessão e desabilita também os subagents"
    Texto real do erro observado: `"Bash is disabled for this session, in subagents as well as here"`.
    Ou seja: se você usar `disallowed_tools=["Bash"]` para impedir o coordenador de agir, os workers despachados também ficam sem poder rodar comandos — a run inteira vai por água abaixo.

    Para "só coordenar sem executar", use `delegate_only=True` + não passar `allowed_tools`, deixando o [`delegate_guard`](#delegate-guard) barrar apenas a thread principal pelo `agent_id`.

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

Compila um `AgentSpec` para o `ClaudeAgentOptions` do SDK. É o que `Runtime._attempt` chama internamente; quando você dirige o SDK por conta própria (sem `Runtime`), entra por aqui também.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `spec` | `AgentSpec` | obrigatório, posicional | A declaração a compilar |
| `cwd` | `str \| Path \| None` | `None` | Só é escrito em `cwd` se for diferente de `None` |
| `session_store` | `SessionStore \| None` | `None` | Só escreve `session_store` e `session_store_flush` se for diferente de `None` |
| `resume` | `str \| None` | `None` | Qual sessão retomar |
| `fork` | `bool` | `False` | Vira `fork_session`. **Está aninhado dentro de `if resume:`** |
| `resume_at` | `str \| None` | `None` | Vira `resume_session_at`. **Também aninhado dentro de `if resume:`** |
| `use_plugin` | `bool` | `True` | Se `True` e `PLUGIN_DIR` existir → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Diretórios adicionais autorizados. **Obrigatório quando a bancada fica fora da área de trabalho** |
| `flush` | `str` | `"eager"` | Vira `session_store_flush` |
| `prelude` | `str` | `""` | Trecho acrescentado depois de `instructions` (o índice da bancada passa por aqui) |

Mapeamento:

| Chave de option produzida | Valor |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Vêm diretamente do `spec` |
| `setting_sources` | `[]` (portável) ou `["project"]` |
| `plugins` | Só existe se o diretório `plugin/` na raiz do repositório existir |
| `cwd` / `add_dirs` | Só escritos se não forem vazios |
| `session_store` / `session_store_flush` | Só escritos se `session_store` for diferente de `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Cada um só é escrito se não for vazio |
| `env` | `dict(spec.env)` e depois `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Só têm efeito quando `resume` é verdadeiro** |

`PLUGIN_DIR` é o diretório `plugin/` na raiz do repositório (três níveis acima de `flower/core/agent.py`). Depois de instalar via pip esse diretório pode não existir; o código verifica com `is_dir()`.

!!! warning "`fork=True` sem `resume` falha em silêncio"
    Tanto `fork_session` quanto `resume_session_at` estão aninhados em `if resume:` — sem `resume` eles simplesmente não têm efeito, **e nenhum erro é reportado**. Da mesma forma, `Runtime.run(resume_at=...)` só funciona quando `resume` é fornecido, e **o `Workflow` nunca passa `resume_at`**: para voltar até uma mensagem específica, só chamando `Runtime.run` diretamente.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

O painel de controle do auto-[compact](glossary.md#压缩); o produto é um conjunto de variáveis de ambiente a injetar no subprocesso.
O algoritmo de compact em si está no binário do harness e não pode ser alterado; o que dá para mudar é apenas "dispara ou não".

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = não define nada, limiar = janela − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (desliga inclusive o `/compact`). **Outros valores lançam `ValueError`**, não são ignorados em silêncio |
| `window` | `int \| None` | `None` | Diferente de `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Do lado da CLI o limite é 100k–1M; valores menores que 100k são elevados para 100k |

| Método | Assinatura | Descrição |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produz as variáveis de ambiente. **Um `mode` inválido lança `ValueError` aqui, não na construção** — e como é chamado por `build_options`, o erro aparece dentro de `Runtime.run` |

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

O objeto de política que, quando o contexto está quase cheio, "escreve um [documento de handoff](glossary.md#交接书) e abre uma sessão nova" em vez de compactar.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | Desligar volta ao auto-compact |
| `window` | `int` | `default_window()` | Qual se assume ser o tamanho da janela de contexto do modelo |
| `headroom` | `int` | `50_000` | Quanta folga deixar. Motivo: o auto-compact dispara na janela −33k, o handoff precisa chegar antes disso, e "escrever o handoff" ainda consome um turno |
| `max_generations` | `int` | `8` | Quantas gerações no máximo por step. **Isso é um freio contra descontrole, não planejamento de capacidade** |

| Propriedade | Tipo | Descrição |
|---|---|---|
| `at` | `@property -> int` | Limiar de handoff `max(10_000, window - headroom)`. **Tem piso de 10k** — abaixo disso nem dá para escrever o handoff |
| `warn_at` | `@property -> int` | Posição do aviso de aproximação `max(1_000, at - 20_000)`, emitido uma vez por geração |

!!! warning "Um `window` pequeno demais gera handoffs infinitos e queima dinheiro"
    Se `at` ficar abaixo do **piso de partida** daquele papel (medido em cerca de 34k para o coordenador), toda sessão nova já nasce acima da linha; e como **o handoff não consome cota de retentativa** (`attempt -= 1`), fica girando em falso indefinidamente. O único freio é `max_generations=8`; ao bater nele, o `error` é trocado por uma mensagem de diagnóstico sugerindo aumentar `window` ou desligar o handoff.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Adivinha a janela de contexto pela **string do nome do modelo** nas variáveis de ambiente `ANTHROPIC_MODEL` ou `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Condição | Retorno |
|---|---|
| O nome contém a palavra isolada `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| O nome contém `haiku` | `200_000` |
| Demais casos (**incluindo nenhuma das duas variáveis definida**) | `1_000_000` |

**O padrão é agressivo.** Superestimar não é erro fatal: a API devolve `prompt is too long`, o `Runtime` reconhece esse sinal (o `is_overflow` interno) e faz o handoff na hora — mas o handoff daquela geração sai em versão degradada.

---

## Documentos {#文书}

Código-fonte: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatro dataclasses, todas fazendo "transformar uma resposta do modelo em um número fixo de seções e gravar em disco". Formato comum: `parse()` analisa, `missing()` / `complete()` verificam completude, `to_markdown()` é para humanos, `prompt_block()` é para o modelo seguinte, `write()` / `load()` gravam e releem.

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

O [brief](glossary.md#需求确认书), **exatamente quatro seções**, em ordem fixa `goal` → `accept` → `bounds` → `unknowns`, cujos nomes de seção em chinês são, respectivamente, 「目标」「验收标准」「边界」「未知与假设」.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `goal` | `str` | `""` | Objetivo |
| `accept` | `str` | `""` | Critérios de aceitação |
| `bounds` | `str` | `""` | Limites |
| `unknowns` | `str` | `""` | Incógnitas e premissas |
| `path` | `Path \| None` | `None` | Local em disco. `compare=False`, não participa da comparação de igualdade |

| Método | Assinatura | Descrição |
|---|---|---|
| `missing` | `() -> list[str]` | Os **nomes em chinês** das seções faltantes, prontos para exibição |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Extrai as quatro seções da resposta do modelo. **Primeiro remove os blocos de código cercados**; o que não for identificado fica vazio |
| `to_markdown` | `() -> str` | Documento completo com cabeçalho de metadados; seções vazias viram `"(未填)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar o modelo seguinte, **apenas seções não vazias**, sem metadados |
| `write` | `(path: str \| Path) -> Path` | Cria o diretório pai, grava, define `self.path` com o caminho resolvido e o retorna |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Retorna `None` se o arquivo não existir ou em caso de `OSError`. **Converte o placeholder `"(未填)"` de volta para string vazia** |

Regras de parsing (onde os erros se concentram):

- Ao remover as cercas, **se encontrar um ``` ou `~~~` não fechado, descarta tudo a partir dali** — na prática o clarificador cola o código inteiro dentro da resposta. Quando a saída do modelo é truncada, todas as seções seguintes deixam de ser reconhecidas, `complete()` fica `False` e o gate manda refazer.
- O regex de título tolera `## 目标` / `**目标**` / `目标:` / `3. 边界`, e também título seguido diretamente do corpo.
- A tabela de aliases é compilada em ordem decrescente de tamanho; caso contrário "未知" engoliria "未知与假设" antes.
- Quando a mesma seção aparece repetida, **vale a primeira com conteúdo**.
- Se ao editar o brief à mão você copiar o placeholder `"(未填)"` do `to_markdown()`, aquela seção continua contando como faltante.

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

O [documento de handoff](glossary.md#换代) escrito no [handoff](glossary.md#交接书) de geração, com cinco seções.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `doing` | `str` | `""` | O que está sendo feito. **Obrigatório** |
| `decided` | `str` | `""` | O que já foi decidido |
| `deadends` | `str` | `""` | Caminhos que não deram certo |
| `next` | `str` | `""` | Próximo passo. **Obrigatório** |
| `scene` | `str` | `""` | Situação atual |
| `step` | `str` | `""` | Usado apenas no cabeçalho do documento, **não participa do parsing** |
| `path` | `Path \| None` | `None` | Local em disco |

**Só `doing` e `next` são obrigatórios** — exigir "caminhos que não deram certo" não vazio forçaria o modelo a inventar.

| Membro | Assinatura | Descrição |
|---|---|---|
| `missing` | `() -> list[str]` | **Verifica apenas as duas seções obrigatórias** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Se o corpo carrega a marca de degradação `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reaproveita o segmentador do `Brief` |
| `to_markdown` | `() -> str` | Seções vazias viram `"(空)"` |
| `prompt_block` | `() -> str` | **O cabeçalho diz explicitamente a quem assume que "você está assumindo"**, para evitar que ele volte a pedir contexto a alguém |
| `write` | `(path) -> Path` | Igual a `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Igual a `Brief.load` |

Três membros do mesmo módulo **não exportados mas semanticamente centrais**: `is_overflow(*texts)` casa com `prompt is too long`, `context length exceeded`, `maximum context length`, `too many total text bytes`, `input length and max_tokens exceed` etc., convertendo um "erro fatal" em "handoff imediato"; `HANDOFF_PROMPT` é o prompt que faz **a própria sessão atual** escrever o handoff (contém os dois placeholders `{used}` e `{window}`; **não é um papel novo** — só ela tem aquele contexto); `degraded(step, prompt, *, why="")` monta mecanicamente um documento quando o handoff não sai, colocando em `scene` os primeiros **1200** caracteres da tarefa original.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

O objetivo + a lista de verificação do [goal guard](glossary.md#目标看守).

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `statement` | `str` | `""` | Enunciado do objetivo |
| `checks` | `list[str]` | `[]` | Lista de verificação, um item por linha |
| `path` | `Path \| None` | `None` | Local em disco |

| Membro | Assinatura | Descrição |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Os itens de `checks` marcados com `[此环境无法验证:…]`. **Já nascem condenados a nunca passar, desde o momento em que o objetivo foi definido** |
| `missing` | `() -> list[str]` | Exige `statement` não vazio **e** `checks` não vazio |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` um por linha, removendo automaticamente marcadores `-` / `*` / `1.` |
| `to_markdown` | `() -> str` | Lista vazia vira `"(空)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar o modelo seguinte |
| `write` / `load` | Igual a `Brief` | Gravar e reler |
| `amend` | `(extra: str) -> Goal` | **Acrescenta, não sobrescreve**: concatena `"\n\n(已修改)" + extra` depois de `statement` e retorna `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

O resultado de uma rodada de julgamento do [juiz](glossary.md#判定者), **exatamente três seções**: 结论 / 理由 / 未通过.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` quando não é possível identificar |
| `reason` | `str` | `""` | Justificativa |
| `failed` | `list[str]` | `[]` | Itens da lista que não passaram |

| Membro | Assinatura | Descrição |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Se a conclusão foi identificada ou não. **`ok=False` tem que ser tratado como "não atingido", nunca como atingido** |
| `parse` | `@classmethod (text) -> Verdict` | Veja abaixo |
| `feedback` | `() -> str` | O que volta para o worker: só o que está faltando, sem solução |

Ordem de reconhecimento do `parse`:

1. Primeiro busca as seções por título 「结论」/「判定」.
2. Sem seções com título, aplica `strip` no texto todo e testa `fullmatch(r"1|true")` → atingido; `fullmatch(r"0|false")` → ainda não.
3. Caso contrário, procura no texto da conclusão a primeira ocorrência na tabela de palavras de estado (**palavras mais longas primeiro**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 caem todas em `unreachable`** — já tropeçamos nisso: a plataforma-alvo era macOS, a execução se dava em um contêiner Linux, e o juiz olhou o branch no código-fonte e aprovou.
4. Ainda sem resultado → procura um `\b1\b` isolado → atingido; `\b0\b` → ainda não.
5. Nada disso casando → `state=""`, `ok=False`.

`unreachable` e `not_yet` **são conclusões diferentes**: a primeira segue o caminho de "parar e perguntar a um humano", não o de "mais uma rodada".

## Camada de hooks {#hook}

Código-fonte: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Esta camada é a **fronteira de execução** do flower: quais ferramentas o main thread não pode tocar, como cortar resultados longos demais, qual papel vai para um worktree independente —
tudo é imposto por hooks do SDK, **não por prompt**. A razão é direta: prompt é sugestão, o modelo pode ignorar. Já foi medido que, mesmo com o system prompt dizendo explicitamente "não use worktree", a injeção do `isolate_guard` funciona do mesmo jeito (o modelo passa `None`, o que chega é `'worktree'`).

Nove exports: cinco fábricas de guard que retornam `HookMatcher` (`whitelist_guard` pode retornar `None`), um montador, um combinador e duas funções de marcação de isolation.
Não é preciso pendurá-las à mão — o [`Runtime`](#runtime) monta tudo automaticamente a partir do `AgentSpec`. Pendurar à mão só é necessário se você mesmo dirige o SDK
(sem passar pelo `Runtime`).

**A decisão de "é o main thread?" passa por uma única função**: `_is_main_thread(data) = not data.get("agent_id")` —
os dados de hook de tool-lifecycle de um subagent trazem `agent_id`, os do [main thread](glossary.md#主线程) não.
Todo guard que só barra o main thread se apoia nessa única linha.

Constantes de grupos de ferramentas (nível de módulo, não exportadas, mas determinam os matchers padrão):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tabela de consulta: qual guard entra em qual evento do SDK {#hook-速查表}

| Função | Evento de hook do SDK | matcher | O que barra | O que retorna | Quem instala |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | as ferramentas de `Bash\|Write\|Edit\|NotebookEdit` que **não estão em `allowed_tools`** | **só o main thread** chamando uma ferramenta proibida | `permissionDecision: "deny"` + motivo | `Runtime._attempt`, **só quando `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (mutável via `tools=`) | **só o main thread** pondo a mão na massa; com `allow_glance=True`, um `Bash` que passa por `is_ephemeral()` é liberado | `deny` + "vá despachar um subagent" | `workbench_hooks(delegate_only=True)`, **só quando o `Runtime` tem workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sem `cwd` nem `isolation`, e o `subagent_type` foi marcado com `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injeta `isolation="worktree"`) | `workbench_hooks`, **só quando há algum papel marcado em `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` cai dentro de `workbench.root` | `{}` (o efeito é o `workbench.refresh()`) | `workbench_hooks`, sempre instalado |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **campos string** com ≥ `threshold` caracteres no `tool_response`; ler o próprio diretório de spill é liberado | `updatedToolOutput` (spill + um ponteiro de uma linha + os 400 primeiros caracteres) | `workbench_hooks`, **só quando `spill_threshold` é verdadeiro** |

**A conclusão-chave que se lê nessa tabela**: com `Runtime(workbench=False)`, o `workbench_hooks` inteiro não é instalado;
e para um coordenador com `delegate_only=True`, o `whitelist_guard` também é pulado — **o main thread fica sem nenhuma parede**.
Veja aquele aviso em [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Faz `allowed_tools` ser realmente exclusivo para aquelas quatro ferramentas que põem a mão na massa.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obrigatório, posicional | normalmente é só passar `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | como o agente se refere a si mesmo no texto de recusa. O `Runtime` passa `spec.name` |

- **Entra em `PreToolUse`**, o matcher é `"|".join(banned)`, onde `banned` = as ferramentas de
  `Bash` `Write` `Edit` `NotebookEdit` que não estão em `allowed`.
- Ao dar match, `permissionDecision: "deny"`, com texto no espírito de: "XX não tem YY. **Isso é intencional, não é configuração faltando.**
  Escreva a conclusão no corpo da sua resposta, o framework vai buscá-la lá — não tente outras formas de contornar."
- **Barra apenas o main thread desta sessão**, subagents passam — as ferramentas de um subagent são decididas por `AgentDefinition.tools`.
- Quando não há nada a barrar, retorna **`None`** (por exemplo, um papel com o kit completo como `worker()`), e quem chama decide se instala ou não.

**Por que ele tem que existir**: `allowed_tools` é uma **lista de dispensa de aprovação, não uma whitelist exclusiva**. Duas evidências medidas:
o judge que definia o objetivo rodou `Bash` 11 vezes; na sonda de $0.1,
um agent com `allowed_tools=["Read"]` conseguiu chamar `Write`/`Bash` do mesmo jeito.
Ou seja, o "não tem ferramenta de escrita" de `clarify()` / `judge()` **vem deste hook**, não da whitelist em si.

A vantagem é que ele é derivado de `allowed_tools`, então `judge(can_run=True)` mantém `Bash` automaticamente e continua barrando
`Write`/`Edit` — sem precisar de um interruptor extra.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Main thread pondo a mão na massa → recusa, com indicação de caminho.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. É uma string de regex, não uma lista |
| `allow_glance` | `bool` | `False` | com `True`, libera quando `tool_name == "Bash"` e [`is_ephemeral(command)`](#is-ephemeral) é verdadeiro |

- **Entra em `PreToolUse`**, com matcher igual a `tools`.
- Main thread chamando uma dessas quatro ferramentas → deny, e o motivo **diz qual é o próximo passo**: usar a ferramenta `Agent` para despachar um subagent,
  escrevendo no task brief o objetivo e os critérios de aceitação, e exigindo que ele grave produções longas em `.flower/artifacts/` e devolva na resposta apenas caminho e conclusão.
- Subagents passam sempre.

A diferença em relação ao `whitelist_guard` está no **texto**: os dois barram o mesmo conjunto de ferramentas, mas este diz "vá delegar", o que é mais adequado.
Por isso um papel com `delegate_only=True` instala só este; instalar os dois faria o modelo receber duas orientações contraditórias.

O critério de liberação de `allow_glance=True` e o critério de "esse resultado vai ser cortado?" são **a mesma função** ([`is_ephemeral`](#is-ephemeral)) —
o conjunto liberado tem que ser igual ao conjunto que expira; mudar um lado obriga a mudar o outro.

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

Resultados de ferramenta acima do limiar sofrem [spill](glossary.md#落盘) **na hora**, deixando no contexto apenas um ponteiro de uma linha — não é esperar o contexto encher
para então compactar.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | o diretório de spill é `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | a partir de quantos caracteres fazer spill |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (padrão) = resultados de subagents também sofrem spill |

- **Entra em `PostToolUse`** e retorna
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <cortado>}}`.
- O nome do arquivo de spill são os 16 primeiros caracteres do `sha256` do conteúdo + `.txt`, e no contexto ele é substituído por um ponteiro de uma linha + os **400 primeiros caracteres**.
- `updatedToolOutput` **precisa preservar a estrutura de saída da ferramenta original**, então só os **campos string** longos demais do dict são substituídos;
  **listas nunca são tocadas** (podem conter blocos de imagem). Estrutura errada é rejeitada (o original fica como estava, sem erro).
- **Ler o próprio arquivo de spill tem que ser liberado** — senão "leia com `Read`" é conversa vazia: o texto completo lido volta a sofrer spill, num laço infinito.
  Já aconteceu na prática: o modelo tentou cinco formas diferentes de contornar.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Escreveu algo no [workbench](glossary.md#工作台) → atualiza o `INDEX.md`, e o próximo agent já sabe da existência daquilo desde a abertura.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | escopo da decisão e alvo do refresh |

**Entra em `PostToolUse`**, matcher `"Write|Edit"`. Se `tool_input["file_path"]`, após resolve, cair dentro de
`workbench.root`, chama `workbench.refresh()`. **Sempre retorna `{}`** — não muda nada, só tem efeito colateral.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Atribui um git worktree independente ao subagent conforme o papel, implementando o [isolation](glossary.md#隔离).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obrigatório, posicional | tabela de papéis, usada para verificar se o `subagent_type` foi marcado |
| `on_inject` | `Any` | `None` | callback opcional, chamado como `on_inject(subagent_type, description)` |

**Entra em `PreToolUse`**, matcher `"Agent"`. A injeção só ocorre com as três condições simultâneas: `tool_name == "Agent"`,
`tool_input` **sem `cwd` e sem `isolation`**, e o papel correspondente ao `subagent_type` marcado com `isolated()`.
Satisfeitas, retorna `permissionDecision: "allow"` + `updatedInput` (com `isolation` valendo `"worktree"`).

`isolation` e `cwd` são **mutuamente exclusivos** na ferramenta `Agent` — se o modelo especificou `cwd` por conta própria, isso é respeitado.
"Precisa de isolation?" é **atributo do papel**, não interruptor global nem decisão tomada a cada despacho; para papéis que não precisam, nenhum byte é acrescentado.

**Ligar isolation exige tirar o [workbench](glossary.md#工作台) do repositório.** Um agent isolado não consegue escrever no checkout compartilhado,
então o workbench precisa apontar para fora do repositório via `home=`. `starter_flow(isolate=True)` usa
`<ws>.parent/.flower-<ws.name>`, e `Runtime(workbench=True)` usa `<run_dir>/workbench` —
os dois ficam fora do repositório, **mas não são o mesmo diretório**; não misture.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marca uma definição de subagent como "precisa de área de trabalho independente", e lê essa marca de volta.

| Função | Parâmetro | Padrão | Descrição |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obrigatório | a definição a marcar. **Retorna o mesmo objeto** |
| | `flag: bool` | `True` | posicional. `False` = remove a marca |
| `wants_isolation` | `agent: AgentDefinition \| None` | obrigatório | aceita `None` também, retornando `False` |

A marca é um atributo do lado Python, `_flower_isolate`, escrito via `object.__setattr__`, **não um campo de dataclass** —
o SDK serializa com `asdict()`, que só reconhece campos declarados, então essa marca não escapa para o lado da CLI (já verificado).

**Custo**: fazer `dataclasses.replace()` sobre um `AgentDefinition` perde essa marca, e o isolation falha silenciosamente.

`worker(isolate=True)` internamente passa por `isolated()`.

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

Instala de uma vez os hooks de que o workbench precisa. É o que o `Runtime._attempt` chama.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | passado a `index_guard` e `spill_guard` |
| `delegate_only` | `bool` | `True` | só instala `delegate_guard` quando `True` |
| `spill_threshold` | `int \| None` | `4000` | só instala `spill_guard` quando verdadeiro |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | só acrescenta `isolate_guard` se **algum** deles estiver marcado com `isolated()` |
| `allow_glance` | `bool` | `False` | repassado para `delegate_guard(allow_glance=)` |

Resultado:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  havendo papel marcado → acrescenta `isolate_guard(agents)`.
- `PostToolUse`: sempre `[index_guard(workbench)]`; `spill_threshold` verdadeiro → acrescenta
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Chaves de evento com lista vazia são removidas**, nunca se retorna list vazia.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatena** vários grupos de configuração de hook por nome de evento.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variádico | quantos grupos quiser. Grupos `None` são pulados |

Usa `extend`, **sem deduplicar** — passar o mesmo guard duas vezes o instala duas vezes. O `Runtime` usa isso para juntar `spec.hooks`,
`workbench_hooks(...)` e `whitelist_guard`.

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

O diretório de trabalho para spill: três subdiretórios + um índice. O índice é **injetado no system prompt**, então o agent sabe a cada turno
o que tem em mãos.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `Path` | obrigatório, posicional | a área de trabalho. O `__post_init__` faz resolve |
| `dirname` | `str` | `".flower"` | nome do diretório do workbench, relativo a `workspace` |
| `max_index_entries` | `int` | `40` | **vale só para `prompt_block()`**: quantas entradas por categoria no trecho injetado no system prompt; o excedente vira uma linha "…e outros N". O próprio `INDEX.md` não tem limite, lista tudo |
| `home` | `Path \| None` | `None` | se dado, é usado como `root` e **`dirname` é ignorado**. Quando não é `None`, também sofre resolve |

| Membro | Assinatura | Descrição |
|---|---|---|
| `root` | `@property -> Path` | `home` se dado, senão `workspace / dirname` |
| `external` | `@property -> bool` | se `root` está **fora** de `workspace`. No modo isolation deve ser `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts que serão rodados uma segunda vez |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, produções longas com mais de 2000 caracteres |
| `notes` | `@property -> Path` | `root / "notes"`, decisões-chave, um arquivo por decisão |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | o caminho que o modelo vê: relativo dentro da área de trabalho, absoluto fora dela |
| `ensure` | `() -> Workbench` | faz mkdir dos três diretórios e retorna `self` (encadeável: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(caminho exibido, descrição, bytes)`. `rglob("*")` recursivo, pulando arquivos que começam com `.` |
| `refresh` | `() -> str` | reescreve o `INDEX.md` e retorna o conteúdo |
| `prompt_block` | `() -> str` | **o trecho injetado no system prompt**. Curto de propósito — ele está em todos os turnos |

Formato de auto-descrição de script: `# desc: uma frase` dentro das 8 primeiras linhas (também reconhece `//` e `--` como marcadores de comentário),
com fallback para o primeiro comentário não vazio ou a primeira linha da docstring (cortada em 100 caracteres).

As três regras injetadas por `prompt_block()`:

1. Scripts que serão rodados uma segunda vez vão para `scripts/`, com `# desc:` na primeira linha.
2. Produções acima de **2000 caracteres** vão para `artifacts/`, e na conversa só entram caminho e conclusão.
3. Decisões-chave vão para `notes/`, um arquivo por decisão.

Quando `external=True`, o `prompt_block()` insere uma frase adicional: "acesse-o por caminho absoluto".

**O índice não é herdado por subagents.** Ele vai pelo `system_prompt.append` de nível de sessão, e um subagent tem seu próprio
system prompt (medido: $0.2461). Então "produções longas vão para `artifacts/`" e "onde está o workbench" precisam ser repassadas pelo
[coordenador](glossary.md#协调者) dentro do [task brief](glossary.md#任务书) — **esse é o único canal**, não é redundância.
Em `WORKER_RULES` isso está **deliberadamente ausente**: o caminho real é gerado pelo `Workbench`, e fixá-lo no texto daria errado.

---

## Session store {#会话存储}

Código-fonte: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Três camadas de herança: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
O `Runtime` **usa sempre a camada mais externa**, e as políticas das três camadas são controladas por parâmetros de construção.

Cada camada cuida de uma coisa: persistir, [trim](glossary.md#裁剪) por volume e valor, [prune](glossary.md#剪除) por "isso é erro?".
Trim e prune acontecem no momento do **`load()`** (isto é, quando o resume realimenta o histórico ao modelo); o registro original no SQLite não muda um byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementa o protocolo `SessionStore` do SDK, com três tabelas: `entries` / `meta` / `summaries`.
A chave do store é `project_key/session_id[/subpath]` — **o transcript de um subagent é distinguido pelo subpath**.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `str \| Path` | obrigatório, posicional | arquivo do banco. A conexão usa `check_same_thread=False` |

| Método | Assinatura | Descrição |
|---|---|---|
| `append` | `async (key, entries) -> None` | idempotente por uuid (primeiro remove os já persistidos, depois os duplicados dentro do lote). Em replay de um lote inteiro, **não avança o mtime e não refaz o fold do summary**; só o transcript principal (`subpath is None`) participa do summary |
| `projects` | `() -> list[str]` | os `project_key` que realmente existem no banco. **O SDK o deriva do cwd; confirme com isso antes de consultar, não adivinhe** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **síncrono, não lê payload**, só consulta uma linha de meta. Serve para "continuity no mesmo caminho" — dar resume numa sessão inexistente só estoura quando o subprocesso sobe |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | qual o tamanho de contexto que o modelo realmente viu no último turno; retorna `0` se não achar. Varre de trás para frente só as últimas `scan` entradas; soma os três itens `input + cache_read + cache_creation` (olhar só `input_tokens` subestima gravemente) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | ordenado por seq; retorna `None` se não houver linhas |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | só o transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | lista os resumos de sessão |
| `delete` | `async (key) -> None` | ao apagar o transcript principal, **apaga em cascata os dos subagents**, evitando órfãos |
| `list_subkeys` | `async (key) -> list[str]` | lista os sub-transcripts sob essa sessão |
| `close` | `() -> None` | fecha a conexão |

O `_next_mtime` interno garante **monotonicidade estrita** — `list_sessions` e o sidecar de summary compartilham esse relógio,
senão o fast path de staleness do SDK julga errado.

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
| `min_chars` | `int` | `2000` | resultados curtos não valem o trim |
| `spill_dirname` | `str` | `".flower/spill"` | **relativo a `workspace`, tem que estar dentro da área de trabalho** — senão o `Read` do agent não alcança |
| `enabled` | `bool` | `True` | fica `False` quando `Runtime(trim=False)` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | gera a linha de ponteiro que substitui o corpo |

**Os dois diretórios de spill não são o mesmo.** O `spill_guard` grava em `<workbench.root>/spill/` (pode estar fora da área de trabalho);
o `TrimPolicy.spill_dirname` grava em `<workspace>/.flower/spill/` (**tem que estar dentro da área de trabalho**).
Os dois correspondem a "cortar na hora" e "cortar no resume"; diretórios distintos é intencional, não unifique.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

A política de expiração dos resultados de [ephemeral commands](glossary.md#一次性命令).

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | desligado, a marcação de expiração não é feita de forma alguma |
| `keep_recent` | `int` | `6` | os N mais recentes ficam isentos. **Muito menor que o 20 do `TrimPolicy`** |
| `max_chars` | `int` | `2000` | acima disso, pula e deixa o `TrimPolicy` arquivar |
| `text` | `str` | ver assinatura | texto de substituição, com dois placeholders: `{cmd}` e `{age}` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | aplica `text` para gerar o corpo substituto |

**Atua apenas sobre resultados da ferramenta `Bash`**, e o comando precisa casar com a whitelist de ephemeral commands. **`Read` não entra nisso** —
o conteúdo de um arquivo não se distorce com o tempo até o ponto de enganar. Conteúdo expirado **não sofre spill**, é descartado direto.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Decide se um comando Bash é um [ephemeral command](glossary.md#一次性命令).
**A decisão de liberação do `delegate_guard` e a decisão de expiração do trim compartilham esta mesma função** — o conjunto de comandos que o coordenador
pode rodar sozinho tem que ser igual ao conjunto cujos resultados são marcados como expirados. Liberar sem cortar faz um `git status` expirado ocupar o contexto para sempre e ainda enganar;
cortar sem liberar faz o coordenador despachar um subagent para um `ls`, trocando um custo de partida de 4.3k por algumas dezenas de caracteres.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cmd` | `str` | obrigatório, posicional | a linha de comando completa |

Ordem de decisão:

1. Vazio / só espaços → `False`.
2. Substituição de comando (`$(`, backtick, `<(`, `>(`) ou alguma forma que "muda estado" → `False`.
3. Após remover redirecionamentos seguros (`2>&1`, `&> /dev/null` e afins), se ainda contiver `>` ou `<` → `False`.
4. Após remover `&&` / `||` / `;` / `|`, se ainda restar um `&` isolado (execução em background) → `False`.
5. Separa por `&&` / `||` / `;` / `|`, e **cada trecho precisa casar com a whitelist**.

Grandes categorias de verbos da whitelist: subcomandos `git` somente-leitura (`status`, `diff`, `log`, `show`, `branch`, `rev-parse` etc.),
informação de diretório e sistema (`ls`, `pwd`, `df`, `du`, `date`, `whoami`, `env` etc.), processos e contêineres
(`ps`, `top`, `lsof`, `docker ps`, `kubectl get` etc.), leitura de arquivos (`cat`, `head`, `tail`, `wc`, `stat`, `find`, `tree`),
consulta de caminhos (`which`, `whereis`, `command -v`, `type`), processamento de texto (`grep`, `rg`, `sort`, `uniq`, `awk`, `sed`, `jq`, `diff` etc.).

Mesmo com o verbo na whitelist, estas formas são barradas: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` e `print >` dentro de `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

A primeira versão recusava todo comando composto de forma cega, e **na prática isso desativou o glance por completo** (as três tentativas do coordenador foram barradas),
por isso passou a decidir trecho por trecho.

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
| `policy` | `TrimPolicy \| None` | `None` | se não dado, usa o `TrimPolicy()` padrão |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | se não dado, usa o `EphemeralPolicy()` padrão |

Atributos públicos: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Ordem no `load()`: `super().load()` → limpa `last_report` → se `ephemeral.enabled`, `expire()` →
se `policy.enabled`, `trim()`. **Com `enabled=False`, o passo é pulado inteiro.**

| Método | Descrição |
|---|---|
| `expire(entries)` | resultados `Bash` de validade temporal já expirados têm **só o corpo substituído; o bloco fica**. O comando é buscado no `tool_use` da mensagem assistant anterior; pula `isCompactSummary` / `isMeta`; acima de `max_chars` pula (fica para o `trim`); os últimos `keep_recent` ficam isentos. Escreve `last_report["expired"]` |
| `trim(entries)` | `tool_result` com `>= min_chars` têm o corpo despejado em `<workspace>/<spill_dirname>/<16 primeiros do sha256>.txt`, e o conteúdo do bloco é trocado por um ponteiro; os últimos `keep_recent` ficam isentos. Escreve `cleared` / `kept` / `chars_saved` em `last_report` |

**Só corta texto puro**: blocos `image` / `document` ficam intactos.

**Duas linhas vermelhas estruturais**: o **bloco `tool_result` tem que continuar existindo**, só o content pode ser trocado (faltar um é
"Missing Tool Result Block"); entradas `isCompactSummary` não podem ser mexidas.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renderiza `store.last_report` em uma linha, para log de UI.

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
    keep_denials: int = 1
```

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | remove mensagens de erro de API sintéticas (resíduo de queda de conexão) |
| `neutralize_interrupts` | `bool` | `True` | `tool_result` residuais de interrupção são trocados por uma nota neutra |
| `interrupt_text` | `str` | ver assinatura | o texto da nota neutra |
| `keep_denials` | `int` | `1` | mantém as N recusas de chamada de ferramenta mais recentes |

A razão do `keep_denials`: uma chamada recusada nunca foi executada, o resultado não traz informação, mas ocupa um espaço não trivial (medido: 273 caracteres numa ocorrência =
93 caracteres de texto de recusa + 180 caracteres do **comando morto na íntegra**). Mais grave é que **isso engana** — na prática, depois de ler algumas
mensagens de "não use Bash diretamente", o coordenador parou de tentar até o `git status` que era liberado, aprendendo desamparo adquirido.
**O padrão é manter 1 e não 0**: a recusa mais recente evita que o modelo insista repetidamente no mesmo comando barrado dentro do mesmo turno.

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

Além dos da classe-pai, três atributos públicos a mais: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (primeiro `expire` + `trim`) → `self.prune(entries)`. O `prune` faz três coisas:

1. **Remove as chamadas recusadas antigas**: decide pela marca estrutural do harness `toolDenialKind == "permission-rule"`
   (mais confiável que casar o texto da recusa), mantém as últimas `keep_denials` e, nas demais, remove os blocos `tool_use` **e** `tool_result`
   juntos. Quando uma mesma mensagem assistant tem vários `tool_use`, **só o marcado é removido**, senão vira
   "Missing Tool Result Block"; blocos de texto e de thinking são preservados.
2. **Remove as mensagens de erro de API sintéticas.** Elas ficam intactas no SQLite, só não são realimentadas.
3. **Troca `tool_result` residuais de interrupção por uma nota neutra** — só o corpo, sem remover a entrada.

**A única linha vermelha estrutural**: o transcript é uma cadeia simples por `parentUuid`, então remover uma entrada obriga a religar seus filhos ao ancestral vivo mais próximo.
O `entries` do `relink` interno **precisa ser a lista completa (incluindo as que serão removidas)**, pois a filtragem é feita por ele mesmo —
se quem chama remover antes de passar, a cadeia arrebenta ali e todo o histórico anterior se perde (**já pisamos nisso: quando a entrada removida está no fim não aparece,
no meio explode**).

**A ordem dos parâmetros difere da classe-pai**: a pai é `(path, workspace, policy, ephemeral)`, a filha é
`(path, workspace, policy, prune, ephemeral)` — **o quarto posicional deixou de ser `ephemeral` e passou a ser `prune`**,
e passar por posição desalinha silenciosamente. Use sempre argumentos por palavra-chave.

---

## Resilience {#韧性}

Código-fonte: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Quando a rede cai, ele fica pendurado esperando em vez de falhar e sair. Quatro exports: uma dataclass de política + três funções de sondagem usáveis isoladamente.

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
| `max_attempts` | `int` | `6` | **inclui a primeira** |
| `base_delay` | `float` | `4.0` | base do backoff, em segundos |
| `max_delay` | `float` | `120.0` | teto do backoff, em segundos |
| `probe_timeout` | `float` | `5.0` | timeout de uma sondagem |
| `probe_interval` | `float` | `15.0` | quanto esperar entre duas sondagens |
| `max_offline_wait` | `float` | `3600.0` | quanto tempo no máximo ficar pendurado esperando, por padrão 1 hora |
| `retry_unknown` | `bool` | `True` | retentar ou não erros que não se conseguiu classificar |
| `resume_prompt` | `str` | ver assinatura | o que dizer ao retomar. **Deliberadamente sem nenhum detalhe do erro** — o modelo precisa saber "foi interrompido, continue", não se foi `ENOTFOUND` ou 503 |

| Método | Assinatura | Descrição |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` com `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | fica pendurado esperando a rede voltar. Voltou, retorna `True`; passou de `max_offline_wait`, retorna `False`. `notify` é um callback `(str) -> None`, disparado uma vez **na primeira inacessibilidade** e uma vez **na recuperação** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classifica o texto de erro em três categorias: `"transient"` / `"fatal"` / `"unknown"`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `text` | `str \| None` | obrigatório, posicional | o texto original da mensagem de erro. Vazio retorna `"unknown"` |

**Testa fatal antes de transient** — textos como os de 401 frequentemente trazem a palavra `connection`, e com a ordem invertida você espera para sempre.

| Categoria | O que casa |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

O host e a porta a sondar, seguindo `ANTHROPIC_BASE_URL`, com padrão `https://api.anthropic.com`;
porta padrão `80` (http) ou `443`.

**Ao usar um gateway próprio, é ele que precisa ser sondado** — `api.anthropic.com` responder não diz nada sobre o gateway.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `host` | `str` | obrigatório, posicional | nome do host |
| `port` | `int` | obrigatório, posicional | porta |
| `timeout` | `float` | `5.0` | segundos |

**Só faz DNS (`getaddrinfo`) + handshake TCP**, sem enviar HTTP, sem credenciais, **sem custo**. Qualquer exceção conta como inacessível.

---

## Eventos e interação {#事件与交互}

Código-fonte: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[Evento](glossary.md#事件) é a estrutura estável para a qual o fluxo de mensagens do SDK é achatado.
**A [camada de interação](glossary.md#交互层) só conhece `Event` e não importa nenhum tipo do SDK** — é essa a
fronteira que permite trocar de UI sem mexer no núcleo. Veja [trocar a camada de interação](../guide/interaction.md).

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
| `text` | `str` | `""` | corpo |
| `tool` | `str` | `""` | nome da ferramenta, só existe em `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | informação estruturada adicional |
| `raw` | `Any` | `None` | objeto original do SDK, para quando você quiser cavar fundo |

`__str__`: em `tool_call` é `f"[{tool}] {text}"`, caso contrário é `text`; se `text` for vazio, `f"<{kind}>"`.
Ou seja, `print(ev)` já é legível.

`EventKind` tem **15** valores:

| kind | Quem emite | Descrição |
|---|---|---|
| `text` | `normalize` | corpo do assistant |
| `thinking` | `normalize` | bloco de raciocínio |
| `tool_call` | `normalize` | chamada de ferramenta. `text` é o resumo de `file_path` / `command` / `pattern`, cortado em 200 caracteres |
| `tool_result` | `normalize` | resultado da ferramenta. `text` cortado em 500 caracteres, `payload` traz `tool_use_id` / `is_error` |
| `task` | `normalize` | os três tipos de mensagem Task; `text` é o nome da classe da mensagem |
| `system` | `normalize` | demais mensagens de sistema; `text` é o subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` traz `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | mensagem sintética de erro de API, `payload` traz `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **O corpo é entrada, não produção do modelo**, por isso não entra em `StepResult.text` |
| `unknown` | `normalize` | o que não foi reconhecido |
| `retry` | `Runtime` | aviso de retentativa |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | no payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | pergunta e **também carrega "o que a pessoa disse por iniciativa própria"** |

**Os quatro últimos não são produzidos por `normalize()`.**

O `payload` de todos os eventos de assistant / user traz:

| Chave | Tipo | Descrição |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | só existe quando `subagent` é verdadeiro |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **É a única fonte do critério de [handoff](glossary.md#换代)** e também o número que mais merece ser visto numa execução de longo alcance |

**O kind `ask` carrega ao mesmo tempo "pergunta" e "o que a pessoa disse por iniciativa própria".** No segundo caso,
`payload["kind"] == "mail"` e **não há `options` / `remaining`**. A UI precisa checar `payload.get("kind")` antes de
decidir como renderizar, senão vai tratar uma frase como uma pergunta pendente e travar nela.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Achata uma mensagem do SDK em 0 a N `Event`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `message` | `Any` | obrigatório, posicional | qualquer objeto de mensagem do SDK |

Ramificações principais:

- **Mensagem sintética de erro de API** (`isApiErrorMessage=True` ou `model == "<synthetic>"`) → um único
  `Event("error", payload={"synthetic": True})`. **Isso é intencional** — caso contrário o texto da queda de conexão
  entraria como corpo em `StepResult.text` e seria repassado ao passo seguinte.
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

Um **servidor MCP in-process** (duas ferramentas) + um conjunto de métodos para a UI. Do lado do modelo só aparecem
`mcp__human__ask` e `mcp__human__inbox`. Todos os parâmetros do construtor são keyword-only.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | saída do modo **push**. Se você passar, `Workflow.run` não faz mais a ligação |
| `max_asks` | `int \| None` | `None` | **sem limite de vezes**. Um número vira cota rígida; `0` = proibido perguntar (totalmente automático / CI). Ao estourar, a ferramenta **recusa direto, sem bloquear** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutos. `None` = espera para sempre; **`<= 0` = não espera, toda pergunta cai no vazio imediatamente** |
| `log_path` | `str \| Path \| None` | `None` | perguntas e respostas são **anexadas** ao disco, sem ocupar contexto |
| `amend_path` | `str \| Path \| None` | `None` | o que a pessoa disser durante a execução é anexado a este arquivo (normalmente o próprio brief). **Sem gravar em disco não sobrevive à fronteira do passo** — o próximo passo é uma nova session e só lê o artefato congelado |
| `over_budget_text` | `str` | constante do módulo | o que é devolvido ao modelo quando a cota estoura |
| `timeout_text` | `str` | constante do módulo | o que é devolvido ao modelo quando dá timeout |
| `declined_text` | `str` | constante do módulo | o que é devolvido ao modelo quando a pergunta é pulada |

Atributos públicos: os oito com o mesmo nome dos parâmetros do construtor, mais `asks: list[Ask]`, `mail: list[Mail]` e
`ui_errors: list[str]` (**exceções lançadas pelo callback da UI ficam aqui, sem interromper a execução**).

| Membro | Assinatura | Descrição |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | passe direto para `AgentSpec.mcp_servers`. **O nome da chave precisa bater com o nome do server**, por isso ele já entrega os dois juntos |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | fica pendurado esperando a pessoa. **Nunca lança exceção, exceto `CancelledError`** — ninguém responder também é uma resposta; distinga por `ask.state` |
| `send` | `(text: str) -> Mail \| None` | a pessoa fala por iniciativa própria. **Pode ser chamado de qualquer thread**. Não interrompe o agente; internamente chama `amend()` automaticamente |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | anexa em `amend_path`. Retorna se realmente escreveu (sem caminho configurado, texto vazio ou `OSError` dão `False`) |
| `pending_mail` | `() -> list[Mail]` | mails ainda não recolhidos |
| `remaining` | `@property -> int` | quantas perguntas ainda cabem. **Com `max_asks=None` retorna `-1`**, não 0 nem infinito |
| `pending` | `() -> list[Ask]` | perguntas atualmente penduradas esperando resposta |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | usado no modo **pull**. Em timeout retorna `None`; se cancelado, lança |
| `answer` | `(ask_id: str, text: str) -> bool` | responde. `False` = essa pergunta já não está esperando (timeout / já respondida) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | pula, deixando o modelo decidir sozinho |
| `transcript` | `() -> str` | o markdown do registro de perguntas e respostas |

**Escolha uma das duas formas de consumo**: **push** — construa `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` só faz a ligação automática quando `channel.on_event is None`, então se você passou o seu ele não é sobrescrito.

**Entre threads**: `answer` / `decline` / `send` usam `loop.call_soon_threadsafe` internamente; chamar direto do backend web
ou da thread de entrada da TUI é o uso normal.

Os três significados de "0 / None" são diferentes entre si, não confunda: `max_asks=None` = sem limite, `max_asks=0` = proibido perguntar;
`timeout_s=None` = espera para sempre, `timeout_s<=0` = timeout imediato; `remaining` é `-1` quando `max_asks=None`.

`Mail`, que não é exportado mas aparece nos valores de retorno, é uma dataclass com os campos `id` / `text` / `sent_at` / `taken`.

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

Registra entre processos "qual passo usou qual session"; é por ela que a [continuidade](glossary.md#接续) descobre até onde
a execução anterior foi. O arquivo é `<run_dir>/lineage.json`.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `Path` | obrigatório | caminho do arquivo de linhagem |
| `workspace` | `Path` | obrigatório | workspace. `__post_init__` faz o resolve |
| `steps` | `dict[str, str]` | `{}` | nome do passo → `session_id` |
| `woke` | `int` | `0` | quantas vezes despertou |

| Membro | Assinatura | Descrição |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lê `<run_dir>/lineage.json`. **Se o arquivo não existir, não puder ser lido ou o campo `workspace` não bater, retorna vazio sem erro** |
| `remember` | `(step: str, session_id: str) -> None` | memoriza o mapeamento e **grava em disco na hora**. Step vazio ou sid vazio retorna direto |
| `bump` | `() -> int` | incrementa o contador de despertares em 1, grava e retorna o novo valor (na primeira execução é `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **move** o arquivo de linhagem + `extra` para `<into>/<YYYYmmdd-HHMMSS>/` e zera `steps` / `woke`. **Move, não apaga** |

A gravação usa substituição atômica via `tmp.replace(path)`; `OSError` é engolido em silêncio — uma falha de gravação
não deve derrubar a execução.

**`workspace` é uma guarda**: o `project_key` do SDK é derivado do caminho do workspace; depois que o diretório é copiado
para outro lugar, os `session_id` antigos não são encontrados, então caminho que não bate é tratado como inexistente.

Ao carregar a linhagem, `Workflow.run` valida cada registro com `runtime.has_session(sid)` para ver se ainda está na base e
só usa os vivos — o arquivo de linhagem pode sobreviver mais tempo que o `sessions.db`.

---

## Exemplos mínimos utilizáveis {#示例}

Os cinco trechos rodam direto. Pré-requisito: `claude-agent-sdk` instalado e `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN`
disponível (senão `Runtime(...)` já lança `RuntimeError` na construção).

### Um agente rodando um passo {#示例-单-agent}

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
É a primeira camada de economia de contexto do flower.

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

    # workbench=True é obrigatório: o delegate_guard é montado dentro de workbench_hooks,
    # sem workbench o Bash/Write do coordenador não tem nenhum hook barrando.
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

Os dois primeiros parâmetros de `worker()` são posicionais: `description` (que o coordenador usa para escolher quem chamar)
e `prompt` (o system prompt dele, com `WORKER_RULES` concatenado automaticamente depois). Em `coordinator()`, os três
primeiros são posicionais: `name`, `instructions`, `workers`.

### Escrevendo um Workflow você mesmo {#示例-workflow}

Dois passos, com o segundo injetando o resultado do primeiro no próprio prompt — barato, isolado, sem compartilhar session.

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
        # Nova session: só consome o que está no prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Nova session + resultado do passo anterior injetado no prompt (barato, evita contaminação)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Para continuar na mesma session, escreva resume_from="造句"; para bifurcar, acrescente fork=True
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

Os três primeiros campos de `Step` (`name` / `spec` / `prompt`) são posicionais, assim como `steps` em `Workflow`.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` posicional, os dois callbacks keyword-only.
**Atenção: `continuous=True` é o padrão**: ao rodar uma segunda vez com o mesmo `run_dir` + mesmo `workspace`,
até os passos com `resume_from=None` continuam a session da vez anterior.

### Acrescentando um goal guard {#示例-目标}

Primeiro deixe o [juiz](glossary.md#判定者) fixar o objetivo e a lista de verificação, depois faça o passo de trabalho
aceitar o veredicto — se não passar, refaz com o feedback, no máximo três rodadas.

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
        # Sem clarify_step, injete um você mesmo, senão ele só vai ver "(没有确认书)".
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
    print(ctx.get("_aborted")) # motivo do StepAbort (quando é inalcançável e ninguém responde)


asyncio.run(main())
```

`with_goal` só troca `gate` / `on_reject` / `retries`; os demais campos são levados intactos via `dataclasses.replace`.
O juiz roda em **session independente**: dentro do `gate` há uma chamada separada
`rt.run(judger, ..., step_name=f"{label}#{轮次}")`, com `resume` sempre `None`.

### Trocando a camada de interação {#示例-交互层}

Para trocar o terminal por Web / TUI / HTTP, só duas coisas mudam: a função que renderiza `Event` e a corrotina que
recolhe as perguntas.

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
    # kind == "ask" que não seja mail fica para o answerer abaixo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Recolhe perguntas no modo pull. Ao trocar por backend web / serviço HTTP, esta corrotina é o único ponto a mudar."""
    while True:
        ask = await ch.next_ask()          # sem timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # O Runtime usa o workbench que o workflow já criou — não monte outro
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push e pull: **escolha um**. Push é construir `HumanChannel(on_event=...)`; pull é `await channel.next_ask()`.
`Workflow.run` só faz a ligação automática quando `channel.on_event is None`, então se você passou `on_event` ele não é sobrescrito.
`answer()` / `decline()` / `send()` / `interrupt()` **podem todos ser chamados de outra thread**.

---

## Armadilhas e pontos fáceis de errar {#陷阱}

Na ordem em que você vai tropeçar, não por módulo. Cada item vem de observação real.

### Montagem {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = nenhuma parede na thread principal.**
   O `delegate_guard` só é instalado quando há workbench, e o `whitelist_guard` é pulado por `delegate_only=True`.
   Se usa coordenador, ligue o workbench. Veja [Runtime](#runtime).
2. **Há dois lugares possíveis para o workbench, não erre a montagem.** `Runtime(workbench=True)` cai em `<run_dir>/workbench`;
   `Workbench(ws)` fica por padrão em `<ws>/.flower`. Ao montar `brief_path` na mão, siga o segundo:
   **o brief é escrito no diretório A, o índice injetado varre o diretório B, e não dá erro nenhum.**
   O jeito certo: o próprio workflow faz `Workbench(...).ensure()`, pendura em `Workflow.workbench`
   e entrega **o mesmo objeto** para `Runtime(workbench=wb)`.
3. **`allowed_tools` não é uma whitelist exclusiva, é uma lista de dispensa de aprovação.** O modelo ainda consegue chamar
   ferramentas que não estão nela. O "não tem ferramenta de escrita" de `clarify()` / `judge()` depende do hook
   [`whitelist_guard`](#whitelist-guard). E `coordinator()` usa `permission_mode="acceptEdits"` por padrão — quem passar
   esse valor para `clarify()` / `judge()` perde a proteção.
4. **`disallowed_tools` é a nível de session**, e proíbe junto as ferramentas de mesmo nome nos subagents.
5. **O índice do workbench não chega aos subagents.** "Produção longa vai para `artifacts/`" precisa ser repassado pelo
   coordenador no task brief; esse é o único canal.
6. **`Runtime(...)` lança `RuntimeError` já na construção quando não há credencial**, não espera até o `run()`.
7. **`Runtime.run_id` precisa ser único por instância.** O `manifest.json` deduplica pelo campo `run`; quando dois ids colidem,
   quem escreve depois trata as linhas do outro como "as suas da vez anterior" e as apaga.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` é o padrão**, e `resume_from=None` não significa "session totalmente nova".
   Para abrir uma nova sempre, use explicitamente `continuous=False`. **Mudar o nome do passo equivale a cortar a linhagem.**
9. **`with_goal(rounds=N)` é o total de rodadas, não rodadas extras**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` não escreve `ctx[step.name]`** — um `lambda ctx: ctx["某步"]` a jusante vai dar `KeyError`.
    Para seguir adiante com o resultado incompleto, use `on_fail="continue"`.
11. **`resume_from` apontando para um passo não executado / que falhou lança `ValueError`**, não pula em silêncio.
12. **`Step.reduce` precisa ser função síncrona; `gate` / `when` / `on_reject` podem ser async.**
13. **`fork=True` sem `resume` é silenciosamente inócuo.** `Workflow` nunca passa `resume_at`;
    para voltar por mensagem, só chamando `Runtime.run` diretamente.
14. **Ao dirigir o `Runtime` você mesmo, `on_session` precisa ser desconectado antes do gate**, senão a session do juiz
    é gravada na linhagem do passo de trabalho. O `Workflow` garante isso com `try/finally`.
15. **`step_name` determina as chaves no manifest e na linhagem.** O `Workflow` acrescenta os sufixos `#retryN` / `#roundN`,
    e o juiz acrescenta `#轮次` — **nomes com sufixo não entram na linhagem entre processos**, e é justamente uma das formas
    de implementar "o juiz é sempre uma session nova".

### Papéis {#陷阱-角色}

16. **`clarify(max_turns=<número pequeno>)` transforma "perguntas ilimitadas" em conversa fiada** — cada pergunta é um turno.
17. **`goal_step()` não tem o parâmetro `can_run`**, só dá para passar `can_run=True` via `**spec_kw`.
    Sem isso, o juiz que define o objetivo não recebe `Bash`, e a regra do `JUDGE_RULES` de "primeiro entenda em que
    ambiente você está" não pode ser executada.
18. **`judge(can_run=True)` permite que o juiz altere o workspace** — o `whitelist_guard` é derivado de `allowed_tools`,
    e dar `Bash` libera `Bash` (`Write`/`Edit` continuam barrados, mas o próprio `Bash` escreve arquivos).
    Para neutralidade absoluta, não ligue.
19. **`worker(isolate=True)` exige que o workspace seja um repositório git**, senão a ferramenta `Agent` reporta direto
    `"not in a git repository"` — não degrada em silêncio. Além disso, a marca de isolamento é um atributo Python:
    **fazer `dataclasses.replace()` num `AgentDefinition` a perde.**
20. **Ao construir `AgentDefinition` diretamente, os parâmetros são camelCase**: `maxTurns`, `permissionMode`.
    `worker()` já faz essa conversão por você.

### Handoff e contexto {#陷阱-换代}

21. **Com handoff ligado, o auto-compact é desligado à força, sem rede de segurança.** Por isso o passo que escreve o
    handoff document precisa ter caminho de degradação. Para manter o auto-compact, informe `AgentSpec.compact` explicitamente.
22. **Um `HandoffPolicy.window` pequeno demais gera handoffs infinitos queimando dinheiro.** A única trava é `max_generations=8`.
    Do outro lado, **`default_window()` também retorna `1_000_000` quando nenhuma das duas variáveis de ambiente está definida** —
    estimar alto é segurado por `is_overflow()` (vira um handoff degradado), não é erro fatal, mas o handoff daquela geração é degradado.
23. **Sem workbench, o handoff não é gravado em disco.** O documento ainda é entregue ao sucessor pelo prompt,
    mas depois ninguém consegue encontrá-lo.

### Armazenamento {#陷阱-存储}

24. **`Runtime(trim=False)` (o padrão) não significa "não limpa nada".** O store é sempre `PruningSessionStore`;
    `trim=False` só desliga o trim de resultados grandes; **a remoção de restos de desconexão, a remoção de chamadas
    recusadas, a neutralização de resíduos de interrupção e a expiração por validade continuam acontecendo.**
25. **Os dois diretórios de spill não são o mesmo**: o `spill_guard` grava em `<workbench.root>/spill/`,
    e `TrimPolicy.spill_dirname` cai em `<workspace>/.flower/spill/` (tem que estar dentro do workspace).
26. **O quarto parâmetro posicional de `PruningSessionStore.__init__` é `prune`, não `ephemeral`**,
    diferente da classe pai. Passar por posição desalinha em silêncio.

### Documentos e interação {#陷阱-文书}

27. **Quando o `Verdict` não consegue extrair a conclusão, `state=""` e `ok=False`; isso jamais pode ser tratado como alcançado.**
    Além disso, "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" caem todos em `unreachable`,
    o que dispara o caminho de "parar e perguntar à pessoa", não o de "mais uma rodada".
28. **`Brief.parse` descarta todo o conteúdo depois de uma cerca de código não fechada** — quando a saída do modelo é truncada,
    nenhuma das seções seguintes é interpretada, `complete()` fica `False` e o gate manda refazer.
29. **`Brief.load` trata `"(未填)"` como vazio.** Se ao editar o brief à mão você copiou o texto de placeholder,
    aquela seção continua contando como faltante.
30. **Os três "0 / None" do `HumanChannel` têm significados diferentes**: `max_asks=None` sem limite, `max_asks=0` proibido perguntar;
    `timeout_s=None` espera para sempre, `timeout_s<=0` timeout imediato; `remaining` retorna **`-1`** quando `max_asks=None`.
31. **`Event("ask")` carrega ao mesmo tempo perguntas e falas espontâneas da pessoa**, sendo que as últimas têm `payload["kind"] == "mail"`.
    A UI precisa checar isso primeiro.
32. **`Workflow.run` só faz a ligação automática quando `channel.on_event is None`** —
    se você construiu `HumanChannel(on_event=...)` por conta própria, os eventos de pergunta não vão simultaneamente
    para a saída `on_event` do workflow.
