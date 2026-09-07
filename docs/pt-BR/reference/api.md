# Python API

Esta página esgota os **62 símbolos públicos** do `__all__` de topo do `flower`: assinaturas, parâmetros, valores padrão, semântica, atributos e métodos públicos. Depois de ler, você não precisa abrir o código-fonte para procurar parâmetros.

A organização é por **aquilo que você quer resolver**, não por arquivo de módulo — se a pergunta é "como impedir o [coordenador](glossary.md#协调者) de fazer o trabalho ele mesmo", vá para a [camada de hooks](#hook); se é "como o resultado da etapa anterior chega à próxima", vá para [workflow](#流程). Os termos seguem sempre o [glossário](glossary.md).

Versão `0.1.0`, depende de `claude-agent-sdk>=0.2.152`. Todas as assinaturas correspondem literalmente ao código-fonte.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # uma única importação de topo
```

## O que tem nesta página {#索引}

| O que você quer | Símbolos |
|---|---|
| [Executar um agent](#运行时) | `Runtime` `StepResult` |
| [Encadear várias etapas](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Construir um papel](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Escrever a definição do agent à mão](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documentos estruturados](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Interceptar ferramentas, cortar resultados, separar isolamento](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [O diretório de trabalho do spill](#工作台) | `Workbench` |
| [Como a sessão é armazenada e o que é armazenado](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [O que fazer quando a rede cai](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Trocar a UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Retomar a execução anterior entre processos](#血缘) | `Lineage` |

## Seis valores padrão que mordem {#危险默认值}

Estes seis não são detalhes marginais: são os seis acidentes mais comuns. Cada um tem explicação completa na seção correspondente.

| Valor padrão | Consequência | Detalhes |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` da thread principal ficam **sem nenhum hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Força um `CompactPolicy(mode="no_summary")` no spec, ou seja, `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Etapas com `resume_from=None` ainda retomam, entre processos, a sessão da execução anterior | [Workflow](#workflow) |
| `build_options(fork=True)` sem `resume` | Falha silenciosamente, sem erro | [build_options](#build-options) |
| `clarify(max_turns=<número pequeno>)` | Transforma "perguntas ilimitadas" em conversa fiada — cada pergunta é um turno | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | É de nível de sessão; proíbe junto nos subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Código-fonte: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` é o núcleo de execução. Ele mantém o workspace, o [armazenamento de sessão](glossary.md#会话存储), o [workbench](glossary.md#工作台), a política de [resiliência](glossary.md#韧性) e a política de [handoff](glossary.md#换代), e expõe um único verbo: `run` de uma etapa. Retry, retomada após interrupção e handoff quando o contexto enche — tudo acontece dentro dessa mesma chamada.

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

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | obrigatório | O `cwd` do agent. É resolvido e criado com `mkdir(parents=True, exist_ok=True)` na construção. O `project_key` do SDK é derivado dele — se o diretório for copiado para outro lugar, os `session_id` antigos deixam de ser encontráveis |
| `run_dir` | `str \| Path` | `"runs"` | Guarda `sessions.db`, `manifest.json`, `lineage.json` e, quando `workbench=True`, o workbench padrão. Também é resolvido e criado |
| `portable` | `bool` | `True` | Repassado a `build_options(portable=)`, ou seja, `setting_sources=[]`: não lê o `~/.claude/` da máquina hospedeira nem o `.claude/` do projeto. Veja [portátil](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Se receber uma instância, usa direto; se receber `bool`, vira `TrimPolicy(enabled=bool(trim))`. **Desligar apenas evita o trim de resultados grandes; o prune continua acontecendo** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Mesma regra de conversão. Forma par com `coordinator(glance=True)` — se você libera a thread principal para rodar `git status`, precisa garantir que aquele resultado expire |
| `keep_denials` | `int` | `1` | Passado a `PrunePolicy(keep_denials=)`. Mantém as N chamadas de ferramenta negadas mais recentes; as anteriores são removidas junto com seus resultados |
| `workbench` | `Workbench \| bool` | `False` | Se receber uma instância, usa direto; com `True`, cria `Workbench(workspace, home=run_dir / "workbench")` (**por padrão fica fora do workspace**). Em seguida chama `refresh()` imediatamente |
| `spill_threshold` | `int \| None` | `4000` | A partir de quantos caracteres o resultado de uma ferramenta sofre [spill](glossary.md#落盘). `None` ou `0` = não instala `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Mesma regra de conversão |
| `handoff` | `HandoffPolicy \| bool` | `True` | Mesma regra de conversão |

**O armazenamento de sessão é fixo no código**: é sempre
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Os parâmetros do construtor **não oferecem** um ponto de troca de backend — para trocar, construa você mesmo `AgentSpec` + `build_options(session_store=...)`, ou sobrescreva `rt.store` depois de construir.

Os dois últimos passos da construção são `load_dotenv()` e `check_credentials()`, e **este último faz `raise RuntimeError` se algo estiver errado**. Sem credenciais, a explosão acontece já na fase de construção, não em `run()`.

!!! warning "`workbench=False` + `coordinator()` = nenhuma barreira na thread principal"
    `delegate_guard` só é instalado dentro de `workbench_hooks`, e `workbench_hooks` só é chamado quando `self.workbench is not None`; `whitelist_guard`, por sua vez, é pulado pelo `if not spec.delegate_only`. E `coordinator()` sempre define `delegate_only=True` e, por padrão, `glance=True`, o que libera `Bash`.

    **Conclusão: com o coordenador em um `Runtime(workbench=False)`, seus `Bash`/`Write`/`Edit` não têm hook nenhum interceptando.** Se você usa `coordinator()`, ligue o workbench — `Runtime(..., workbench=True)` ou passe uma instância de `Workbench`.

!!! warning "`handoff=True` (padrão) desliga o auto-compact à força"
    Em `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, o que chega ao subprocesso como `DISABLE_AUTO_COMPACT=1`. A razão: com os dois mecanismos ligados ao mesmo tempo, não se sabe quem causou a queda do contexto.

    **O custo: a etapa que escreve o handoff precisa ter um caminho degradado** (`handoff.degraded`), porque não há mais o compact como rede de segurança. Para preservar o auto-compact, informe `AgentSpec.compact` explicitamente (se o próprio spec define, isso é respeitado e não sobrescrito).

#### Atributos públicos {#runtime-属性}

| Atributo | Tipo | Descrição |
|---|---|---|
| `workspace` | `Path` | O workspace já resolvido |
| `run_dir` | `Path` | O diretório de execução já resolvido |
| `portable` | `bool` | Guardado como veio |
| `store` | `PruningSessionStore` | O armazenamento de sessão. Trocar de backend só é possível sobrescrevendo isso depois de construir |
| `resilience` | `Resilience` | A instância normalizada |
| `handoff` | `HandoffPolicy` | A instância normalizada |
| `workbench` | `Workbench \| None` | É `None` quando `workbench=False` |
| `spill_threshold` | `int \| None` | Guardado como veio; em `_attempt` é passado a `workbench_hooks` |
| `results` | `list[StepResult]` | Cada etapa executada neste processo, acrescentada em ordem |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Precisa ser único por instância** — o `manifest.json` deduplica pelo campo `run`; se dois ids colidirem, quem escreve depois trata a linha do outro como sua própria escrita anterior e a apaga |
| `on_session` | `Callable[[str], None] \| None` | Chamado **imediatamente** ao obter um novo `session_id`; padrão `None`. **Deve cobrir apenas a chamada `runtime.run`** — o [juiz](glossary.md#判定者) usa o mesmo `Runtime`, e se o callback continuar instalado durante o gate, a sessão do juiz vai para a [linhagem](glossary.md#血缘) da etapa que fez o trabalho |

Constantes de classe: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"` e `INTERRUPT_NOTE` (trecho anexado depois da fala da pessoa ao retomar de uma interrupção, explicando que "chamadas de ferramenta em voo retornando interrupted é um efeito colateral normal da interrupção, não uma falha de ambiente").

#### Métodos públicos {#runtime-方法}

| Método | Assinatura | Descrição |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Executa uma etapa. Veja abaixo |
| `interrupt` | `(message: str = "") -> None` | Pede a interrupção do turno atual. **Chamável de qualquer thread.** Cooperativo: corta de forma limpa na **fronteira de mensagem**, sem cancelamento forçado. String vazia = interromper sem dizer nada |
| `rescue` | `() -> None` | Fecha as contas o máximo possível antes de ser morto à força; chamado pelos handlers de `SIGHUP`/`SIGTERM`. A etapa em voo também vai para o manifest, com `error="killed-by-signal"`. Só faz pequenas escritas síncronas em disco |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | Em `str(workspace.resolve())`, `/`, `_` e `.` são todos trocados por `-`. **O SDK deriva isso do `cwd`; quem chama não pode especificar** |
| `has_session` | `(session_id: str) -> bool` | Este id ainda é encontrável **neste workspace**? Síncrono, não lê o payload |
| `context_of` | `(session_id: str) -> int` | O tamanho do contexto no último turno de uma sessão; delega para `store.last_context` |
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
| `spec` | `AgentSpec` | obrigatório, posicional | A declaração do agent a executar |
| `prompt` | `str` | obrigatório, posicional | O que é dito neste turno |
| `step_name` | `str \| None` | `None` | A chave que aparece em `StepResult.step`, no manifest e na linhagem. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Retoma este `session_id` |
| `fork` | `bool` | `False` | Cria uma sessão nova por bifurcação, sem contaminar a original. **Só tem efeito quando `resume` é verdadeiro** |
| `resume_at` | `str \| None` | `None` | Retoma a partir de uma mensagem específica (rollback). Também **só tem efeito quando `resume` é verdadeiro** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída de eventos, veja [`Event`](#event) |

No começo de cada etapa o nível de contexto é zerado (`self._ctx, self._warned = 0, False`). Depois vem um laço com quatro saídas:

1. **Sucesso** → sai do laço.
2. **Interrupção humana** (`result.error == INTERRUPTED`) → **não está sujeita a `max_attempts`** e não espera a rede. Faz `resume` da mesma sessão levando a fala da pessoa, `attempt -= 1` (interrupção não conta como tentativa falha), prompt = fala da pessoa + `INTERRUPT_NOTE`. **Sem um `session_id` em mãos, só resta parar.**
3. **Contexto cheio** (`result.error == HANDOFF_DUE`, ou `handoff.enabled` com um `session_id` em mãos e `is_overflow(...)` acionado) → **também não está sujeito a `max_attempts`**. Primeiro verifica `len(result.retired) >= handoff.max_generations`; se passou, troca o error por uma frase de diagnóstico e sai do laço; caso contrário escreve o [documento de handoff](glossary.md#交接书) → `resume=None, fork=False` (**sessão totalmente nova**) → prompt trocado por `h.prompt_block()` → nível zerado → `attempt -= 1`.
4. **Falha retentável** → sai do laço se `not resilience.enabled or attempt >= max_attempts`; sai também se `classify(error)` decidir que não se deve tentar de novo; caso contrário emite `Event("retry")`, fica pendurado em `wait_online()` esperando a rede, `sleep(delay_for(attempt))`; **se já houve um `session_id`, faz `resume`** (prompt trocado por `resilience.resume_prompt`) e marca `result.resumed` como `True`.

Encerramento: escreve `ended_at`, faz append em `self.results`, escreve `manifest.json`.

O `manifest.json` tem semântica de **append**: cada escrita relê o disco e deduplica pelo campo `run` (a própria linha é substituída, as dos outros ficam), então rodar dois flower em paralelo no mesmo `run_dir` é seguro — desde que os `run_id` não colidam.

**Os três pontos de observação do handoff** (todos são `Event("handoff")`, distinguidos por `payload["phase"]`): `near` (aproximando-se de `warn_at`, emitido uma única vez por geração), `writing` (escrevendo o handoff, leva mais de dez segundos) e `done` (o payload traz `degraded` / `path` / `sections`). O turno que escreve o handoff roda com `replace(spec, max_budget_usd=None)` — o handoff precisa conseguir ser escrito, não pode travar por orçamento; e com `on_event=None`, esse turno não vai para a UI.

O handoff sofre spill em `<workbench.notes>/交接-<步骤名>.md`; **sem workbench não há spill**, e o documento continua sendo entregue a quem assume via prompt, só não é recuperável depois. Handoffs antigos são movidos para `notes/archive/交接/<名>-<时间戳>.md`.

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

Todas as contas de uma etapa concluída.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `step` | `str` | obrigatório | Nome da etapa (`step_name` ou `spec.name`) |
| `session_id` | `str \| None` | `None` | **Sempre a última sessão a assumir** — as queimadas por handoff no meio do caminho ficam em `retired` |
| `ok` | `bool` | `False` | Se esta etapa deu certo ou não |
| `cost_usd` | `float` | `0.0` | Em dólares. **Acumulado** ao longo de retries e handoffs |
| `num_turns` | `int` | `0` | Número de turnos, também acumulado |
| `text` | `str` | `""` | **Contém apenas o corpo da thread principal.** As falas do subagent ficam no transcript dele, e o task brief entregue a ele é `kind="prompt"`; nenhum dos dois entra aqui |
| `error` | `str \| None` | `None` | Motivo da falha. Valores especiais em `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Número real de tentativas. Interrupções e handoffs **não contam** |
| `errors` | `list[str]` | `[]` | Mensagens de erro sintéticas da API, recolhidas; **não entram em `text`** |
| `resumed` | `bool` | `False` | Se houve `resume` no meio do caminho |
| `retired` | `list[str]` | `[]` | Os `session_id` queimados nos handoffs desta etapa, em ordem |
| `context` | `int` | `0` | O tamanho de contexto que a thread principal realmente viu no último turno, isto é, o critério de handoff |

| Propriedade | Tipo | Descrição |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`; `0.0` se não terminou |

---

## Workflow {#流程}

Fonte: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Um [workflow](glossary.md#流程) é um conjunto de [steps](glossary.md#步骤) encadeados em ordem, mais
as regras de como o estado passa de um step para o outro e quando sair mais cedo.
**O framework não entrega workflows prontos; o workflow é você que escreve** — `starter_flow` é
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

A **declaração** de um step. `Step` em si não é uma função — quem executa de verdade é
`Runtime.run(step.spec, prompt, ...)`.
Os três primeiros campos são posicionais: `Step("取词", terse, "读 seed.txt …")` é escrita válida.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do step. **Chave estável entre processos** — aparece em `ctx[name]`, `ctx["_results"]`, no manifest e na lineage. Renomear = romper a lineage |
| `spec` | `AgentSpec` | obrigatório | Qual agent rodar |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | O que dizer. Pode ser um closure que calcula na hora a partir do `ctx` |
| `resume_from` | `str \| None` | `None` | De qual step retomar a sessão. Se o step apontado não produziu sessão, **lança `ValueError`** — não é pulado em silêncio |
| `fork` | `bool` | `False` | Bifurca a partir de `resume_from`. **Sem `resume_from` não tem efeito** |
| `retries` | `int` | `0` | Quantas tentativas extras quando o gate não passa. `retries=0` = uma rodada só |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide se esta tentativa conta como aprovada. **Pode ser async**. `False` é tratado como falha. **É chamado uma única vez por tentativa** — ele pode ter efeitos colaterais (gravar o brief em disco, por exemplo) e não deve ser disparado repetidamente |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, ver abaixo |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Se retornar `False`, **o step inteiro é pulado**: não gera result, não entra em `ctx["_results"]`. **Pode ser async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **O que dizer na próxima rodada** quando o gate não passa. **Pode ser async**. Fornecê-lo muda a semântica de retry, ver abaixo |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt usado quando há continuidade (em vez de recomeçar do zero) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decide o que vai em `ctx[name]`. Por padrão, o `result.text` cru. **Precisa ser função síncrona** |

| Método | Assinatura | Descrição |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Com `resuming` e `resume_prompt` definido, usa o segundo; senão usa `prompt`; se for chamável, invoca passando `ctx` |

**Três formas de encadear sessões** (dentro de uma mesma run):

| Forma | Efeito |
|---|---|
| `resume_from=None` (padrão) | Sessão nova, contando apenas com o contexto passado no prompt. Barato, isolado. **Mas com `Workflow(continuous=True)` pega a sessão do step de mesmo nome na lineage entre processos** |
| `resume_from="nome do step anterior"` | Continua a mesma sessão, contexto completo. Caro, coerente |
| `resume_from="nome do step anterior", fork=True` | Bifurca sem contaminar a sessão original. Use para revisão / múltiplas alternativas em paralelo |

**`on_reject` muda a semântica de retry**:

- Não fornecido → a próxima tentativa **recomeça do zero** (mesmo prompt, mesmo `resume_from`).
- Fornecido → a próxima tentativa **continua a sessão que acabou de ser reprovada**, com o prompt
  substituído pelo valor de retorno e `fork` forçado para `False`.
- Retornou string vazia → nada é devolvido para revisão, degrada para recomeçar do zero.
- `result.session_id` é `None` → também degrada para recomeçar do zero.

**Os três valores de `on_fail`**:

| Valor | Comportamento |
|---|---|
| `"stop"` (padrão) | Escreve `ctx["_failed_at"] = name` e **interrompe o workflow inteiro** |
| `"skip"` | Pula para o próximo step, **`ctx[name]` não é escrito** — um `lambda ctx: ctx["algum step"]` mais adiante dará `KeyError` |
| `"continue"` | `ctx[name] = result.text`, segue em frente com o resultado incompleto |

Passando ou não, `ctx["_results"][name] = result` é sempre escrito; quando `result.session_id` não é
vazio, também vai para `ctx["_sessions"]` e chama `lineage.remember(...)`.

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

Roda uma sequência de `Step` em ordem e devolve o `ctx` final. `steps` é posicional, então
`Workflow([...])` é válido.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `steps` | `list[Step]` | obrigatório | Executados em ordem |
| `name` | `str` | `"workflow"` | Nome do workflow |
| `context` | `Ctx` | `{}` | Dicionário de contexto inicial. **Rodar o mesmo `Workflow` uma segunda vez usa o mesmo dict de ctx** |
| `channel` | `HumanChannel \| None` | `None` | Onde pendurar o canal quando é preciso parar e perguntar a uma pessoa. `run()` conecta automaticamente o `on_event` dele à mesma saída, **apenas se `channel.on_event is None`**; o driver também usa este campo para saber a quem responder |
| `workbench` | `Workbench \| None` | `None` | Workbench indicado pelo workflow, para que o driver consiga encontrá-lo |
| `continuous` | `bool` | `True` | Mesmo caminho = mesma conversa. Implementado por [`Lineage`](#lineage) |

| Parâmetros de `run()` | Tipo | Padrão | Descrição |
|---|---|---|---|
| `runtime` | `Runtime` | obrigatório, posicional | Com qual runtime rodar |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída de eventos, repassada a cada `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback disparado ao final de cada step |

!!! warning "`continuous=True` é o padrão, e `resume_from=None` não significa sessão nova"
    Com continuidade ligada, `run()` primeiro chama `Lineage.open(run_dir, workspace)` e depois
    valida cada registro com `runtime.has_session(sid)` para ver se ainda existe no banco; só os
    vivos entram em `ctx["_sessions"]`. Ou seja,
    **steps com `resume_from=None` também continuam falando na sessão da vez anterior** — inclusive
    depois de o processo ser morto ou a máquina reiniciar.

    Para ter sessão nova sempre, escreva explicitamente `Workflow(..., continuous=False)`.
    E mais: **o nome do step é a chave estável entre processos; mudar o nome do step é romper a lineage.**

**Chaves privadas** que `run()` escreve no ctx (todas começam com `_`, então não colidem com nomes de step):

| Chave | Conteúdo |
|---|---|
| `_runtime` | O `Runtime` recebido. **É por ele que um gate despacha agents** |
| `_on_event` | Saída de eventos. O agent dentro do gate também precisa alcançar a UI, senão a tela fica no escuro |
| `_sessions` | `dict[nome do step, session_id]`, lido com `setdefault` |
| `_results` | `dict[nome do step, StepResult]` |
| `_lineage` | Objeto `Lineage`. Existe só quando `continuous=True` e o runtime tem `run_dir` + `workspace` |
| `_woke` | Valor de retorno de `lineage.bump()`, o número deste wake |
| `_aborted` | Mensagem do `StepAbort` |
| `_failed_at` | Nome do step que falhou com `on_fail="stop"` |

Payload de `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Rótulos de retry**: a tentativa 0 usa `step.name`; depois, com `on_reject` usa
`f"{name}#round{attempt+1}"`, sem ele usa `f"{name}#retry{attempt}"`. No manifest dá para ver de
relance como aquele step chegou ao fim.
**Nomes com sufixo não entram na lineage entre processos** — `Lineage.remember` usa o nome original.

`runtime.on_session` cobre apenas a linha do `runtime.run`, com `try/finally` para garantir que seja
removido antes do gate.
`prompt_cur` / `resume_cur` / `fork_cur` são variáveis locais e não são gravadas de volta no `step` —
o mesmo objeto `Step` pode ser rodado uma segunda vez.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Lançada pelo `gate` = **pare agora, não tente de novo**. A diferença para "retornar `False`": `False`
é "desta vez não deu, mais uma rodada"; `StepAbort` é "outra rodada não vai adiantar".

Depois de lançada: `ctx["_aborted"] = str(exc)`, `passed = False`, **sai do laço de retry (sem
consumir os `retries` restantes)** e segue para o `on_fail` como uma falha comum (por padrão `"stop"`).

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

Produz um `Step` que faz o [clarify](glossary.md#前置确认): pergunta até entender a demanda → converte
em [`Brief`](#brief) → com as quatro seções completas, congela e grava em disco.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `brief_path` | `str \| Path` | obrigatório | Onde o [brief](glossary.md#需求确认书) é gravado. **Precisa cair no workbench que realmente é indexado e injetado** |
| `prompt` | `str \| Callable[[Ctx], str]` | obrigatório | A demanda original da pessoa |
| `name` | `str` | `"确认需求"` | Nome do step, e também a chave no `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Sem ele, usa `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções extras acrescentadas ao [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = pergunta tudo de novo, exista o brief ou não |
| `on_fail` | `str` | `"stop"` | Igual a `Step.on_fail` |
| `retries` | `int` | `0` | Quantas vezes perguntar de novo quando as quatro seções não fecham |
| `**spec_kw` | | | Repassado direto para [`clarify()`](#clarify-role), então dá para escrever `can_read=False`, `max_budget_usd=...` |

Os campos do `Step` produzido são preenchidos assim:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: com `always_ask=True` → sempre `True`; senão, se `Brief.load(brief_path)` estiver completo,
  injeta no ctx **e então retorna `False` (pula)** — mesmo pulando é preciso injetar, senão os steps
  seguintes ficam sem a demanda.
- `gate`: `Brief.parse(result.text)`; incompleto → escreve `ctx[MISSING_KEY]` e retorna `False`;
  completo → congela com `b.write(brief_path)`, injeta no ctx e retorna `True`.
- `reduce`: retorna `ctx[BRIEF_KEY].prompt_block()`, **não o texto cru do modelo** — o texto cru pode
  vir com coisas a mais que ele escreveu.
- `resume_from` **fica no padrão `None`**: o próximo step é uma sessão nova, recebe só o brief e não
  aquela conversa de perguntas e respostas.
  As perguntas do clarify **nunca entraram** no contexto do coordenador; não é que entraram e depois
  foram cortadas.

Os três pontos injetados no ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`,
`ctx.pop(MISSING_KEY, None)`.

| Constante | Valor | Descrição |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` é o objeto `Brief`; `ctx[step.name]` é o `prompt_block()` dele |
| `MISSING_KEY` | `"_brief_missing"` | Quais seções faltaram quando o clarify falhou (nomes em chinês), para exibir na UI |
| `CLARIFY_RESUME` | um prompt em chinês | "接着刚才那次没问完的需求确认继续 —— **不是重新开始**……". Sem essa frase, a continuidade reenvia a demanda original como se fosse tarefa nova e o clarifier pode repetir perguntas já feitas |

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

Produz um `Step` que **define o objetivo**: o [judge](glossary.md#判定者) lê o brief, escreve o
objetivo + a lista de checagens, e o resultado é convertido em [`Goal`](#goal), congelado e gravado em
disco. Tem o mesmo formato de `clarify_step`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `channel` | `HumanChannel` | obrigatório, posicional | Canal de perguntas |
| `goal_path` | `str \| Path` | obrigatório | Onde o arquivo de objetivo é gravado |
| `brief_key` | `str` | `"确认需求"` | Pega o texto do brief em `ctx[brief_key]` para colocar no prompt. **Se não achar, vira `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nome do step |
| `spec` | `AgentSpec \| None` | `None` | Sem ele, usa `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instruções extras |
| `always_set` | `bool` | `False` | `True` = refaz a lista, exista o arquivo de objetivo ou não |
| `on_fail` | `str` | `"stop"` | Igual ao anterior |
| `retries` | `int` | `0` | Igual ao anterior |
| `**spec_kw` | | | Repassado para [`judge()`](#judge-role) |

**Não existe parâmetro `can_run`** — para que o judge que define o objetivo possa rodar comandos, só
passando `can_run=True` via `**spec_kw`. Sem isso ele não tem `Bash` e a regra do `JUDGE_RULES` de
"antes de tudo, entenda em que ambiente você está" não pode ser executada.

Além de parsear e congelar, o `gate` faz mais uma coisa: quando o objetivo tem itens
`[此环境无法验证:…]`, **na hora** emite via `ctx["_on_event"]` um
`Event("task", payload={"unverifiable", "total", "path"})` como aviso — o destino desses itens já
está selado no momento em que o objetivo é definido; na hora do verdict o dinheiro de uma rodada
inteira de trabalho já foi gasto.

**Não define `resume_prompt`** — definir o objetivo deve mesmo reenviar o brief por inteiro.

| Constante | Valor | Descrição |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` é o objeto `Goal`; `ctx[step.name]` é o markdown |
| `VERDICT_KEY` | `"_verdict"` | O [`Verdict`](#verdict) mais recente, para a UI |
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

Coloca um [goal guard](glossary.md#目标看守) sobre um `Step` existente: ao fim de cada rodada, o judge
emite um verdict de forma independente; se o objetivo não foi atingido, devolve o trabalho para
continuar.

O resultado é `replace(step, retries=max(0, rounds - 1), gate=<novo gate>, on_reject=<novo on_reject>)` —
usa `dataclasses.replace` em vez de reconstruir campo a campo; numa reconstrução o `resume_prompt`
ficou de fora, **e não deu erro nenhum**, só reenviou o brief inteiro de novo na continuidade.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `step` | `Step` | obrigatório, posicional | O step guardado |
| `channel` | `HumanChannel` | obrigatório, posicional | Canal para pedir ajuda humana quando o verdict trava |
| `goal_path` | `str \| Path` | obrigatório | Arquivo de objetivo, lido daqui quando `ctx[GOAL_KEY]` não está completo |
| `spec` | `AgentSpec \| None` | `None` | Sem ele, usa `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Total de rodadas, não rodadas extras**: `rounds=3` → `retries=2` → no máximo três rodadas de trabalho. `rounds=1` = uma rodada, um verdict, e falha se não passar |
| `instructions` | `str` | `""` | Instruções extras para o judge |
| `can_run` | `bool` | `False` | Se o judge pode usar `Bash` |
| `name` | `str \| None` | `None` | Nome do judge, por padrão `f"{step.name}·判定"` |
| `**spec_kw` | | | Repassado para `judge()` |

O `gate` é **async**, e o fluxo é:

1. `ctx["_runtime"]` ausente → **lança `StepAbort`** ("não foi possível obter o Runtime, impossível
   julgar o objetivo"). **Não finja que passou.**
2. `ctx[ROUND_KEY] += 1`.
3. Obtém o objetivo: prioriza um `Goal` completo em `ctx[GOAL_KEY]`, senão `Goal.load(goal_path)`,
   senão um `Goal()` vazio.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **O judge é um `Runtime.run` independente, com `resume` sempre `None` — é sempre sessão nova**;
   o `step_name` carrega o número da rodada, portanto não entra na lineage entre processos.
5. `Verdict.parse(vr.text)` é escrito em `ctx[VERDICT_KEY]`.
6. `v.achieved` → retorna `True`.
7. Não é `unreachable` (inclui o caso ambíguo com `v.ok=False`) → em caso de ambiguidade, acrescenta
   um reason padrão e retorna `False`.
   **Ambiguidade é sempre tratada como não atingido** — não dá para deixar um "parece ok" encerrar o
   trabalho.
8. `unreachable` → `await channel.ask(...)` pergunta à pessoa, com três opções:
   - Ninguém responde (`a.state != "answered"`) → **lança `StepAbort`**. Continuar girando em falso é
     a opção mais cara.
   - 「接受这个结果,就这样往下走」→ retorna `True`.
   - 「修改目标」→ pergunta o novo objetivo, faz `g.amend(...).write(goal_path)`, atualiza
     `ctx[GOAL_KEY]` e retorna `False`.
   - Qualquer outra coisa (incluindo resposta livre digitada pela pessoa) → trata como "você julgou
     errado", registra o que a pessoa disse em `v.reason` e retorna `False`.

O `on_reject` é **síncrono**: retorna `ctx[VERDICT_KEY].feedback()`, ou `""` se não houver `Verdict`
(degradando para recomeçar do zero).

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

Monta um workflow de três steps que roda de imediato: **clarify → definir objetivo → trabalhar** (com
goal guard). É o que a linha de comando `flower` usa.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `ask` | `str` | obrigatório, posicional | Uma frase de demanda. **No wake ela não é uma tarefa nova, é "mais uma coisa que a pessoa disse"** |
| `workspace` | `str \| Path` | `"."` | Área de trabalho |
| `run_dir` | `str \| Path` | `"runs"` | Diretório da run |
| `new` | `bool` | `False` | `True` = arquiva lineage + brief + objetivo (os três juntos) e começa do zero |
| `isolate` | `bool` | `False` | Abre um worktree de [isolamento](glossary.md#隔离) para o worker. O workbench muda junto para `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Retorna apenas o Workflow com o step de clarify |
| `goal` | `bool` | `True` | Instalar ou não o [goal guard](glossary.md#目标看守). `False` = o step de trabalho terminou, acabou |
| `rounds` | `int` | `3` | Repassado a `with_goal(rounds=)`, total de rodadas |
| `judge_can_run` | `bool` | `False` | Repassado a `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Repassado ao `HumanChannel`, `None` = sem limite |
| `timeout_s` | `float \| None` | `1800.0` | Repassado ao `HumanChannel`. `0` = totalmente automático, toda pergunta cai no vazio na hora |
| `instructions` | `str` | `""` | Instruções extras para o clarifier |
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
  ferramenta `Agent` reclamar (àquela altura o dinheiro já foi gasto).
- **Detecção de wake**: se `Brief.load(brief_path)` existe e `complete()`, é um wake. Se não for wake
  e `ask` estiver vazio →
  **lança `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- No wake, essa frase vai para **três lugares** ao mesmo tempo; faltando um deles, ela falha em
  silêncio: é acrescentada ao brief
  (`ch.amend(said, label="唤醒时追加")`, sem reescrever se já estiver no arquivo);
  faz `goal_step(always_set=True)` refazer a lista (sem refazer, o judge continua lendo o objetivo
  antigo); e é entregue direto ao coordenador (no contexto dele o objetivo é o **antigo**; sem isso
  ele trabalha pelo critério velho e é julgado pelo critério novo).

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

**Sondagem somente leitura antes da largada: não escreve um byte sequer.** Serve para dizer à pessoa,
antes de rodar de verdade, se isto é continuação da vez anterior ou começo do zero.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Área de trabalho, posicional |
| `run_dir` | `str \| Path` | `"runs"` | Diretório da run |
| `isolate` | `bool` | `False` | Determina a localização do workbench; precisa ser o mesmo valor passado a `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nome do arquivo de brief |
| `goal_name` | `str` | `"目标.md"` | Nome do arquivo de objetivo |

O dict retornado:

| Chave | Tipo | Descrição |
|---|---|---|
| `waking` | `bool` | O brief existe e as quatro seções estão completas |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Quantidade de itens da lista do objetivo, `0` quando não há objetivo |
| `woke` | `int` | `Lineage.woke`, quantos wakes já houve |
| `steps` | `dict` | Cópia de `Lineage.steps`, nome do step → `session_id` |

A localização do workbench é **definida em um único lugar, aqui e em `starter_flow`**: `isolate=True`
→ `<ws>.parent/.flower-<ws.name>` (fora do repositório); senão `<ws>/.flower`. O driver que quiser
saber onde está o brief também passa por esta função — montar o caminho na mão e errar não gera erro,
apenas falha em silêncio.

---

## Fábrica de papéis {#角色工厂}

Código-fonte: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Os cinco papéis são funções-fábrica. Cada papel = **um trecho de texto de regras injetado + um conjunto de ferramentas + um conjunto de hooks**.
`worker()` produz um `AgentDefinition` do SDK (para ser despachado como subagent); os outros quatro produzem [`AgentSpec`](#agentspec) (abrem a própria sessão).

Os papéis em si **não instalam hooks** — quem intercepta ferramentas é `Runtime._attempt`, que monta automaticamente conforme `spec.delegate_only`; veja [camada de hooks](#hook).

Constantes internas de grupos de ferramentas (não exportadas, mas determinam os defaults):

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

Cria o [coordinator](glossary.md#主线程) que fica na [main thread](glossary.md#协调者): decompõe a tarefa, despacha trabalho, lê relatórios, toma decisões, **mas não põe a mão na massa**. Os três primeiros parâmetros são posicionais.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, também o nome default do step |
| `instructions` | `str` | obrigatório | Instruções de domínio. No fim vira `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obrigatório | Quais papéis estão sob seu comando; vai para `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Se fornecido, acrescenta as ferramentas `inbox` **e** `ask` juntas, e define `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → sem `Read` |
| `glance` | `bool` | `True` | Acrescenta `"Bash"` e define `AgentSpec.glance`. **O que efetivamente pode rodar é decidido pelo `delegate_guard`**, não aqui |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [budget](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Modo de permissão. **Atenção a esse default** — passá-lo para `clarify()`/`judge()` desmonta a proteção desses dois papéis |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, o `Runtime` não força a troca para `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extras, mesclados com `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variáveis de ambiente extras |

Os três itens fixos no `AgentSpec` produzido: `delegate_only=True`, `agents=workers` e `workbench` mantendo o default `True` do `AgentSpec`.

O código-fonte diz explicitamente para **não usar `disallowed_tools` para implementar "só coordena, não executa"** — isso é a nível de sessão e desabilitaria `Bash`/`Write` também para os subagents; veja o aviso em [`AgentSpec`](#agentspec). A forma correta é a daqui: `delegate_only=True` + não fornecer `allowed_tools`, deixando o [`delegate_guard`](#delegate-guard) barrar só a main thread com base no `agent_id`.

Se `channel` for fornecido, **as duas ferramentas vêm juntas**, não é opcional: uma vez montado o MCP server, ambas estão lá, e `allowed_tools` não é exclusivo — listadas ou não, dá para chamar. Sem supervisão humana, cada `ask` trava pelo `timeout_s` inteiro — nesse cenário use `HumanChannel(timeout_s=0)`.

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

Cria a definição do [subagent](glossary.md#subagent) que de fato faz o trabalho. Os dois primeiros parâmetros são posicionais. Retorna um `AgentDefinition` do SDK, que vai direto para `coordinator(workers={...})`.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `description` | `str` | obrigatório | **A base que o coordinator usa para escolher quem chamar** — escreva claramente "que tipo de trabalho é despachado para ele" |
| `prompt` | `str` | obrigatório | O system prompt dele. Com `discipline=True`, vira `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | O worker não deve ser rebaixado |
| `effort` | `str \| int \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Vai para o **`maxTurns`** do SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Vai para o **`permissionMode`** do SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Quais skills ele pode usar |
| `discipline` | `bool` | `True` | Se concatena ou não o trecho de disciplina de relato do `WORKER_RULES` |
| `isolate` | `bool` | `False` | Marca de [isolamento](glossary.md#隔离), passa por `isolated()`; **não é um campo do `AgentDefinition`** |

`isolate=True` exige que a workspace seja um repositório git; caso contrário a ferramenta `Agent` reporta direto `"not in a git repository"` e **não degrada silenciosamente**. Além disso, a marca é um atributo Python — fazer `dataclasses.replace()` sobre o `AgentDefinition` a perde, e o isolamento deixa de valer silenciosamente.

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

Cria o [clarifier](glossary.md#确认者): esclarece o requisito antes de qualquer execução, não faz nada além de perguntar e, no fim, emite exatamente quatro seções.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Quando `True`, acrescenta `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | **Sem limite de turnos** |
| `max_budget_usd` | `float \| None` | `None` | Teto de budget |

O `AgentSpec` produzido: `allowed_tools = [channel.tool_name] + (as cinco quando pode ler)`, `mcp_servers = channel.mcp_servers()`, `workbench=False` (ele não tem ferramentas de escrita, o índice não faz sentido para ele), e `permission_mode` herda o default `"default"` do `AgentSpec`.
**Não tem `Write` / `Edit` / `Bash` / `Agent`, e nem `inbox`** (diferente do coordinator).

!!! warning "Definir um `max_turns` pequeno transforma o "pergunte à vontade" em conversa fiada"
    Cada pergunta é um turno. `max_turns=16` equivale a "no máximo uma dúzia de perguntas", e a frase do canal "não há limite de turnos" vira letra morta na hora.

    Para liberar as perguntas é preciso liberar **os dois** lados: `HumanChannel.max_asks` (já é `None` por default = sem limite) e `max_turns` (já é `None` por default).

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

Cria o [judge](glossary.md#判定者): ou define o objetivo antes da largada, ou emite o verdict de cada rodada ao final dela.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel, posicional |
| `channel` | `HumanChannel` | obrigatório | Canal de perguntas, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Quando `True`, acrescenta `Bash` à whitelist; o `whitelist_guard` passa a liberar `Bash` e continua barrando `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de budget |

O `AgentSpec` produzido: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (quando `can_run`) `["Bash"]`, `workbench=False`, o resto igual a `clarify()`. **Não tem `Write` / `Edit` / `Agent`, e nem `inbox`.**

**Trade-off**: `can_run=True` deixa o verdict mais duro (pode de fato rodar os comandos de aceitação), ao custo de o judge passar a poder alterar a workspace — `Bash` por si só já escreve arquivos. Se você quer um verdict absolutamente neutro, não ative.

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

Cria o [oracle](glossary.md#旁路顾问): com o run ainda em andamento, você pergunta "onde estamos agora" e ele dá uma olhada nos eventos recentes e na workbench antes de responder. **O que ele diz não entra no contexto daquele run.**

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nome do papel, posicional |
| `instructions` | `str` | `""` | Instruções complementares, concatenadas depois de `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | **`12`** | Vem com freio por default |
| `max_budget_usd` | `float \| None` | **`0.5`** | Vem com freio por default. Isso é "uma pergunta de passagem", não deve sair do controle |

O `AgentSpec` produzido: `allowed_tools = ["Read", "Glob", "Grep"]` (**sem channel** — ele não pergunta, só responde), `workbench=True` (**o único dos cinco papéis que não é coordinator e ainda assim tem workbench ligada** — é justamente para ler os artefatos e as notas).

### Os cinco textos de regras {#rules}

As cinco constantes estão em `__all__`; dá para importá-las direto para ler, concatenar e modificar.

| Constante | Injetada em quem | Forma de injeção | Pontos-chave |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Você é "uma pessoa que sabe usar o Claude Code", não um worker; não pode escrever arquivos/alterar código/rodar testes; `Bash` só dá para "dar uma olhada" e o resultado expira; **o [task brief](glossary.md#任务书) só descreve o que é específico desta tarefa**; a única regra que ainda precisa ser dita é "onde fica a workbench + saídas longas vão para `artifacts/` + na resposta só o caminho"; verificar o `inbox` a cada ação de etapa concluída; `ask` bloqueia, use só em bifurcações reais |
| `WORKER_RULES` | `worker()` | concatenado **depois** do `prompt` do subagent | Formato da resposta **conclusão / evidências / artefatos / não verificado**, no máximo 30 linhas; proibido colar conteúdo de arquivos, saída de comandos, logs ou diffs; proibido narrar tentativa e erro; antes de agir, olhar `.flower/scripts/`. **De propósito não diz "saídas longas vão para `artifacts/`"** — o caminho real é gerado pela `Workbench`, e fixá-lo daria errado |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Não executa nada, só esclarece o requisito; **não há limite de perguntas, pergunte até ficar claro**; a pessoa pode não estar presente — em caso de timeout, decida sozinho e registre em «incógnitas e premissas»; a saída tem **exatamente quatro seções**; não escreva código, não cole conteúdo de arquivos |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Duas tarefas, uma de cada vez. **Definir o objetivo**: cada item da lista precisa ser verificável na hora, o tamanho da lista é determinado pela quantidade de formas de falhar, **limites não são itens de verdict**, e itens não verificáveis levam `[此环境无法验证:原因]` no final. **Emitir o verdict da rodada**: saída com **exatamente três seções**, o que se julga é o **artefato, não o código-fonte**, por default não se acredita em "está pronto", "não atingiu" e "aqui não dá para verificar" são conclusões diferentes, e a segunda **jamais pode ser julgada como aprovada** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Você é uma via lateral; aquele run ainda está rodando, você não o interrompe nem participa dele; **somente leitura**; responde e descarta, o que você disser não entra no contexto daquele run; você só tem em mãos a "janela de eventos recentes" e a "workbench"; olhe antes de responder, se não puder responder diga que não pode, e seja breve |

---

## Definição de agent {#agent-定义}

Código-fonte: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` é a declaração completa de um agent específico; `build_options` a compila para o `ClaudeAgentOptions` do SDK. A [fábrica de papéis](#角色工厂) produz exatamente `AgentSpec` — quando precisar de uma combinação fora da fábrica, construa-o diretamente.

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

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `name` | `str` | obrigatório | Nome do papel. Também é o `step_name` default de `Runtime.run` e o nome com que o `whitelist_guard` se refere a si mesmo no texto de recusa |
| `instructions` | `str` | obrigatório | Instruções de domínio. **[Anexadas](glossary.md#叠加) depois do system prompt nativo do Claude Code, não substituem** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Lista de isenção de aprovação, não uma whitelist exclusiva** — o modelo continua podendo chamar ferramentas fora dela. Exclusividade vem do [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Nível de sessão**. Veja o aviso abaixo |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidade de raciocínio |
| `max_turns` | `int \| None` | `None` | Limite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Teto de [budget](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Modo de permissão |
| `agents` | `dict[str, Any] \| None` | `None` | Tabela de definições de subagents; os valores são `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabela de MCP servers. `HumanChannel.mcp_servers()` preenche isso diretamente |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extras; o `Runtime` os mescla com os seus via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Se fornecido, o `Runtime` não força a troca para `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variáveis de ambiente injetadas no subprocesso. `compact.env()` faz update por cima |
| `glance` | `bool` | `False` | Permite que o coordinator rode `Bash` de "só dar uma olhada". O que passa é decidido por [`is_ephemeral`](#is-ephemeral), e o resultado é marcado como expirado pela `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Se injeta ou não o índice da workbench no system prompt deste agent. **Papéis sem ferramentas de escrita devem desligar** (`clarify()` / `judge()` já vêm com `False`) |
| `delegate_only` | `bool` | `False` | Só coordena, não executa. Quando `True`, o `Runtime` instala o `delegate_guard` e **não instala** o `whitelist_guard` |

!!! warning "`disallowed_tools` é nível de sessão e desabilita também os subagents"
    Mensagem de erro observada na prática: `"Bash is disabled for this session, in subagents as well as here"`.
    Ou seja: se você usar `disallowed_tools=["Bash"]` para impedir o coordinator de executar, os workers despachados também não conseguem rodar comandos — o run inteiro vira lixo.

    Para "só coordenar, não executar", use `delegate_only=True` + não fornecer `allowed_tools`, deixando o [`delegate_guard`](#delegate-guard) barrar só a main thread com base no `agent_id`.

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

Compila um `AgentSpec` para o `ClaudeAgentOptions` do SDK. É o que `Runtime._attempt` chama internamente; quando você dirige o SDK por conta própria (sem `Runtime`), a entrada também é aqui.

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `spec` | `AgentSpec` | obrigatório, posicional | A declaração a compilar |
| `cwd` | `str \| Path \| None` | `None` | Só é escrito em `cwd` se não for `None` |
| `session_store` | `SessionStore \| None` | `None` | Só escreve `session_store` e `session_store_flush` se não for `None` |
| `resume` | `str \| None` | `None` | Qual sessão continuar |
| `fork` | `bool` | `False` | Vira `fork_session`. **Está aninhado dentro do `if resume:`** |
| `resume_at` | `str \| None` | `None` | Vira `resume_session_at`. **Também aninhado dentro do `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` e `PLUGIN_DIR` existindo → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Diretórios autorizados adicionais. **Obrigatório quando a workbench fica fora da workspace** |
| `flush` | `str` | `"eager"` | Vira `session_store_flush` |
| `prelude` | `str` | `""` | Trecho anexado depois de `instructions` (é por aqui que passa o índice da workbench) |

Mapeamento:

| Chave de option produzida | Valor |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Tirados diretamente de `spec` |
| `setting_sources` | `[]` (portável) ou `["project"]` |
| `plugins` | Só existe se o diretório `plugin/` na raiz do repositório existir |
| `cwd` / `add_dirs` | Só escritos se não estiverem vazios |
| `session_store` / `session_store_flush` | Só escritos se `session_store` não for `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Cada um só é escrito se não estiver vazio |
| `env` | `dict(spec.env)` e depois `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Só valem quando `resume` é verdadeiro** |

`PLUGIN_DIR` é o `plugin/` na raiz do repositório (três níveis acima de `flower/core/agent.py`). Depois de instalar via pip esse diretório pode não existir; o código verifica com `is_dir()`.

!!! warning "`fork=True` sem `resume` não faz nada, silenciosamente"
    `fork_session` e `resume_session_at` estão ambos aninhados dentro do `if resume:` — sem `resume`, nada disso tem efeito, **e nenhum erro é levantado**. Do mesmo modo, `Runtime.run(resume_at=...)` só funciona quando `resume` é fornecido, e o **`Workflow` nunca passa `resume_at`**: para voltar a uma mensagem específica, só chamando `Runtime.run` diretamente.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

O painel de controle do auto-[compact](glossary.md#压缩); o produto é um conjunto de variáveis de ambiente a injetar no subprocesso. O algoritmo de compact em si vive no binário do harness e não dá para mudar; o que dá para mudar é só "dispara ou não".

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = não define nada, limiar = janela − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (desliga junto o `/compact`). **Outros valores lançam `ValueError`**, não são ignorados em silêncio |
| `window` | `int \| None` | `None` | Se não for `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Do lado da CLI o limite é 100k–1M; valores abaixo de 100k são elevados a 100k |

| Método | Assinatura | Descrição |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produz as variáveis de ambiente. **É aqui que um `mode` inválido lança `ValueError`, não na construção** — como é chamado por `build_options`, o erro aparece dentro de `Runtime.run` |

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

O objeto de política que, quando o contexto está quase cheio, "escreve o [handoff document](glossary.md#交接书) e troca de sessão" em vez de fazer compact.

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `enabled` | `bool` | `True` | Desligado, cai de volta no auto-compact |
| `window` | `int` | `default_window()` | Qual o tamanho assumido da janela de contexto do modelo |
| `headroom` | `int` | `50_000` | Quanta folga deixar. Motivo: o auto-compact dispara na janela −33k, o handoff precisa acontecer antes disso, e "escrever o handoff" ainda consome um turno |
| `max_generations` | `int` | `8` | Quantas gerações no máximo por step. **É um freio contra descontrole, não planejamento de capacidade** |

| Propriedade | Tipo | Descrição |
|---|---|---|
| `at` | `@property -> int` | Limiar de handoff `max(10_000, window - headroom)`. **Tem piso de 10k** — abaixo disso não dá nem para escrever o handoff |
| `warn_at` | `@property -> int` | Ponto do aviso de aproximação `max(1_000, at - 20_000)`; emitido uma vez por geração |

!!! warning "Um `window` pequeno demais leva a handoffs infinitos queimando dinheiro"
    Se `at` ficar abaixo do **piso de partida** do papel (medido em cerca de 34k para o coordinator), cada nova sessão já cruza o limite na primeira fala; e como **handoff não consome cota de retentativa** (`attempt -= 1`), o loop gira infinitamente em falso. O único freio é `max_generations=8`; ao bater nele, `error` é substituído por uma mensagem de diagnóstico sugerindo aumentar `window` ou desligar o handoff.

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

**O default é agressivo.** Superestimar não é um erro fatal: a API devolve `prompt is too long`, e o `Runtime` reconhece esse sinal (o `is_overflow` interno) e faz o handoff na hora — mas o handoff dessa geração é a versão degradada.

---

## Documentos {#文书}

Código-fonte: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatro dataclasses, todas do tipo "parseia uma resposta do modelo em um número fixo de seções e grava em disco". Formato comum: `parse()` parseia, `missing()` / `complete()` verificam completude, `to_markdown()` é para humanos, `prompt_block()` é para o modelo a jusante, `write()` / `load()` gravam e releem.

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

O [brief](glossary.md#需求确认书), **exatamente quatro seções**, em ordem fixa `goal` → `accept` → `bounds` → `unknowns`; os nomes das seções em chinês são, respectivamente, 「目标」(objetivo), 「验收标准」(critérios de aceitação), 「边界」(limites) e 「未知与假设」(incógnitas e premissas).

| Campo | Tipo | Default | Descrição |
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
| `parse` | `@classmethod (text: str) -> Brief` | Parseia as quatro seções da resposta do modelo. **Primeiro remove os blocos de código cercados**; o que não for reconhecido fica vazio |
| `to_markdown` | `() -> str` | Documento completo com cabeçalho de metadados; seções vazias viram `"(未填)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar o modelo a jusante, **só com seções não vazias**, sem metadados |
| `write` | `(path: str \| Path) -> Path` | Cria o diretório pai, grava, define `self.path` com o caminho resolvido e o retorna |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Retorna `None` se o arquivo não existir ou em `OSError`. **Converte o placeholder `"(未填)"` de volta em string vazia** |

Regras de parsing (onde os erros se concentram):

- Ao remover cercas, **se encontrar um ``` ou `~~~` não fechado, descarta tudo a partir dali** — na prática o clarifier chega a colar o código inteiro na resposta. Quando a saída do modelo é truncada, todas as seções seguintes deixam de ser parseadas, `complete()` vira `False` e o gate manda refazer.
- A regex de título tolera `## 目标` / `**目标**` / `目标:` / `3. 边界`, e também tolera o corpo vindo logo após o título.
- A tabela de aliases é compilada em ordem decrescente de comprimento; caso contrário 「未知」comeria 「未知与假设」primeiro.
- Quando a mesma seção aparece repetida, **vale a primeira com conteúdo**.
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

O [handoff document](glossary.md#换代) escrito no momento do [handoff](glossary.md#交接书), com cinco seções.

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `doing` | `str` | `""` | O que está sendo feito. **Obrigatório** |
| `decided` | `str` | `""` | O que já foi decidido |
| `deadends` | `str` | `""` | Caminhos sem saída |
| `next` | `str` | `""` | Próximo passo. **Obrigatório** |
| `scene` | `str` | `""` | Situação atual |
| `step` | `str` | `""` | Usado apenas no cabeçalho do documento, **não participa do parsing** |
| `path` | `Path \| None` | `None` | Local em disco |

**Só `doing` e `next` são obrigatórios** — exigir que "caminhos sem saída" seja não vazio forçaria o modelo a inventar.

| Membro | Assinatura | Descrição |
|---|---|---|
| `missing` | `() -> list[str]` | **Verifica apenas as duas seções obrigatórias** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Se o corpo carrega a marca de degradação `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reaproveita o segmentador do `Brief` |
| `to_markdown` | `() -> str` | Seções vazias viram `"(空)"` |
| `prompt_block` | `() -> str` | **O cabeçalho diz explicitamente a quem assume "você está assumindo"**, para impedir que ele volte a pedir contexto a alguém |
| `write` | `(path) -> Path` | Igual a `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Igual a `Brief.load` |

No mesmo módulo há três membros **não exportados, mas semanticamente cruciais**: `is_overflow(*texts)` casa com `prompt is too long`, `context length exceeded`, `maximum context length`, `too many total text bytes`, `input length and max_tokens exceed` etc., transformando um "erro fatal" em "handoff imediato"; `HANDOFF_PROMPT` é o prompt que faz a **própria sessão atual** escrever o handoff (contém os placeholders `{used}` e `{window}`; **não é um novo papel** — só ela tem aquele contexto); e `degraded(step, prompt, *, why="")` monta mecanicamente um handoff quando não foi possível escrevê-lo, enfiando em `scene` os primeiros **1200** caracteres da tarefa original.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

O objetivo + a lista de verdict do [goal guard](glossary.md#目标看守).

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `statement` | `str` | `""` | Enunciado do objetivo |
| `checks` | `list[str]` | `[]` | Lista de verdict, um item por linha |
| `path` | `Path \| None` | `None` | Local em disco |

| Membro | Assinatura | Descrição |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Os itens de `checks` marcados com `[此环境无法验证:…]`. **Já nascem condenados a não passar, no instante em que o objetivo é definido** |
| `missing` | `() -> list[str]` | Exige `statement` não vazio **e** `checks` não vazio |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` é um item por linha; remove automaticamente marcadores `-` / `*` / `1.` |
| `to_markdown` | `() -> str` | Lista vazia vira `"(空)"` |
| `prompt_block` | `() -> str` | Versão compacta para alimentar o modelo a jusante |
| `write` / `load` | Igual a `Brief` | Grava e relê |
| `amend` | `(extra: str) -> Goal` | **Acrescenta, não sobrescreve**: concatena `"\n\n(已修改)" + extra` após `statement` e retorna `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

O resultado de uma rodada de julgamento do [judge](glossary.md#判定者), **exatamente três seções**: conclusão / motivo / não aprovados.

| Campo | Tipo | Default | Descrição |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` quando não foi possível parsear |
| `reason` | `str` | `""` | Motivo |
| `failed` | `list[str]` | `[]` | Itens da lista que não passaram |

| Membro | Assinatura | Descrição |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Se a conclusão foi ou não parseada. **`ok=False` tem obrigatoriamente de ser tratado como "não atingido", nunca como atingido** |
| `parse` | `@classmethod (text) -> Verdict` | Veja abaixo |
| `feedback` | `() -> str` | O texto devolvido ao worker: só diz onde está a falha, não dá a solução |

Ordem de reconhecimento do `parse`:

1. Primeiro tenta pelas seções tituladas 「结论」/「判定」.
2. Sem seções tituladas, com o texto inteiro após strip: `fullmatch(r"1|true")` → atingido; `fullmatch(r"0|false")` → ainda não.
3. Caso contrário, procura no texto da conclusão a primeira ocorrência da tabela de palavras de estado (**palavras mais longas primeiro**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 caem todas em `unreachable`** — já tomamos esse tombo: plataforma alvo macOS, rodando em container Linux, e o judge olhou os branches do código-fonte e deu como aprovado.
4. Ainda nada → procura um `\b1\b` isolado → atingido, `\b0\b` → ainda não.
5. Nada casou → `state=""`, `ok=False`.

`unreachable` e `not_yet` **são conclusões diferentes**: a primeira leva ao caminho de "parar e perguntar a um humano", não ao de "mais uma rodada".

---

## Camada de hooks {#hook}

Código-fonte: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Esta camada é a **fronteira de execução** do flower: quais ferramentas a main thread não pode tocar, como cortar resultados excessivamente longos, qual papel vai para um worktree independente —
tudo é imposto por hooks do SDK, **não por prompt**. A razão é direta: prompt é sugestão, e o modelo pode ignorá-la. Já foi medido que, mesmo com o system prompt dizendo explicitamente "não use worktree", a injeção do `isolate_guard` funciona do mesmo jeito (o modelo passa `None`, e o que fica gravado é `'worktree'`).

Nove exportações: cinco fábricas de guard que retornam `HookMatcher` (`whitelist_guard` pode retornar `None`), um montador, um combinador e duas funções de marcação de isolamento.
Não é preciso instalá-las à mão — o [`Runtime`](#runtime) monta tudo automaticamente conforme o `AgentSpec`. Instalação manual só é necessária quando você dirige o SDK por conta própria (sem passar pelo `Runtime`).

**A decisão sobre main thread passa por uma única função**: `_is_main_thread(data) = not data.get("agent_id")` —
os dados de hook de ciclo de vida de ferramenta de um subagent trazem `agent_id`, os da [main thread](glossary.md#主线程) não.
Todos os guards que "só barram a main thread" se apoiam nisso.

Constantes de grupos de ferramentas (nível de módulo, não exportadas, mas determinam os matchers padrão):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tabela rápida: qual guard entra em qual evento do SDK {#hook-速查表}

| Função | Evento hook do SDK | matcher | O que intercepta | O que retorna | Quem instala |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | as de `Bash\|Write\|Edit\|NotebookEdit` que **não estão em `allowed_tools`** | **só a main thread** chamando uma ferramenta proibida | `permissionDecision: "deny"` + justificativa | `Runtime._attempt`, **apenas quando `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (alterável via `tools=`) | **só a main thread** pondo a mão na massa; com `allow_glance=True`, `Bash` que passa em `is_ephemeral()` é liberado | `deny` + "despache um subagent" | `workbench_hooks(delegate_only=True)`, **apenas quando o `Runtime` tem workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sem `cwd` e sem `isolation`, e `subagent_type` marcado com `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injeta `isolation="worktree"`) | `workbench_hooks`, **apenas quando há algum papel marcado em `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` caindo dentro de `workbench.root` | `{}` (o efeito colateral é `workbench.refresh()`) | `workbench_hooks`, sempre instalado |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **campos string** com ≥ `threshold` caracteres em `tool_response`; ler o próprio diretório de spill é liberado | `updatedToolOutput` (spill + uma linha de ponteiro + os 400 primeiros caracteres) | `workbench_hooks`, **apenas quando `spill_threshold` é verdadeiro** |

**A inferência importante que se lê nesta tabela**: com `Runtime(workbench=False)`, o `workbench_hooks` inteiro não é instalado;
e para um coordinator com `delegate_only=True`, o `whitelist_guard` também é pulado — **a main thread fica sem nenhuma barreira**.
Veja o aviso em [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Faz `allowed_tools` ser realmente exclusivo para as quatro ferramentas que põem a mão na massa.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obrigatório, posicional | normalmente se passa `spec.allowed_tools` direto |
| `role` | `str` | `"这个角色"` | como o papel se autodenomina no texto da recusa. O `Runtime` passa `spec.name` |

- **Entra em `PreToolUse`**, com matcher `"|".join(banned)`, onde `banned` = as ferramentas entre `Bash`, `Write`, `Edit` e `NotebookEdit` que não estão em `allowed`.
- Ao dar match, `permissionDecision: "deny"`, com texto do tipo: "XX não tem YY. **Isso é intencional, não é configuração faltando.**
  Escreva a conclusão no corpo da sua resposta, o framework a pega de lá — não tente contornar com outra formulação."
- **Só barra a main thread da sessão**, subagents passam — as ferramentas de um subagent são decididas por `AgentDefinition.tools`.
- Quando não há nada a barrar, retorna **`None`** (por exemplo, um papel com o conjunto completo de ferramentas, como o `worker()`), e o chamador decide se instala ou não.

**Por que ele precisa existir**: `allowed_tools` é uma **lista de dispensa de aprovação, não uma whitelist exclusiva**. Duas evidências medidas:
um judge configurado rodou `Bash` 11 vezes; numa sonda de $0.1,
um agent com `allowed_tools=["Read"]` chamou `Write`/`Bash` do mesmo jeito.
Portanto, o "não tem ferramenta de escrita" de `clarify()` / `judge()` **vem deste hook**, não da whitelist em si.

A vantagem é que ele é derivado de `allowed_tools`, então `judge(can_run=True)` preserva `Bash` automaticamente e continua barrando `Write`/`Edit` — sem precisar de um flag extra.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Main thread pondo a mão na massa → recusa, com indicação do caminho.**

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. É uma string de regex, não uma lista |
| `allow_glance` | `bool` | `False` | com `True`, libera quando `tool_name == "Bash"` e [`is_ephemeral(command)`](#is-ephemeral) é verdadeiro |

- **Entra em `PreToolUse`**, matcher é o próprio `tools`.
- Main thread chamando uma dessas quatro ferramentas → deny, e a justificativa **diz o próximo passo**: despachar um subagent com a ferramenta `Agent`,
  escrevendo na tarefa o objetivo e os critérios de aceitação, e exigindo que ele grave saídas longas em `.flower/artifacts/` e responda apenas com o caminho e a conclusão.
- Subagents sempre passam.

A diferença para o `whitelist_guard` está na **formulação**: os dois barram o mesmo conjunto de ferramentas, mas este diz "vá delegar", o que é mais adequado.
Por isso um papel com `delegate_only=True` instala só este; instalar os dois faria o modelo receber duas orientações contraditórias.

O critério de liberação de `allow_glance=True` e o critério de "o resultado vai ser cortado" são **a mesma função** ([`is_ephemeral`](#is-ephemeral)) —
o conjunto liberado precisa ser igual ao conjunto que expira; mudar um lado obriga a mudar o outro.

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

Resultados de ferramenta acima do limiar sofrem [spill](glossary.md#落盘) **na hora**, restando no contexto apenas uma linha de ponteiro — não se espera o contexto encher para depois compactar.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | o diretório de spill é `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | a partir de quantos caracteres o spill acontece |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (padrão) = resultados de subagent também sofrem spill |

- **Entra em `PostToolUse`**, retorna
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <cortado>}}`.
- O nome do arquivo de spill são os 16 primeiros dígitos do `sha256` do conteúdo + `.txt`, e no contexto entra uma linha de ponteiro + os **400 primeiros caracteres**.
- `updatedToolOutput` **precisa preservar a estrutura de saída da ferramenta original**, então só se substituem os **campos string** longos demais do dict;
  **listas nunca são tocadas** (podem conter blocos de imagem). Estrutura errada é rejeitada (o original permanece, sem erro).
- **Ler o próprio arquivo de spill precisa ser liberado** — caso contrário, "leia com `Read`" é conversa fiada: o texto completo lido de volta sofre spill de novo, em loop infinito.
  Isso foi observado na prática; o modelo tentou cinco formulações diferentes para contornar.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Escreveu algo no [workbench](glossary.md#工作台) → atualiza o `INDEX.md`, e o próximo agent já começa sabendo que aquilo existe.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | escopo da decisão e alvo da atualização |

**Entra em `PostToolUse`**, matcher `"Write|Edit"`. Se `tool_input["file_path"]`, depois de resolvido, cair dentro de
`workbench.root`, chama `workbench.refresh()`. **Sempre retorna `{}`** — não altera nada, só tem efeito colateral.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Atribui um git worktree independente ao subagent conforme o papel, implementando [isolamento](glossary.md#隔离).

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obrigatório, posicional | tabela de papéis, usada para checar se o `subagent_type` está marcado |
| `on_inject` | `Any` | `None` | callback opcional, chamado como `on_inject(subagent_type, description)` |

**Entra em `PreToolUse`**, matcher `"Agent"`. A injeção só ocorre com as três condições simultâneas: `tool_name == "Agent"`,
`tool_input` **sem `cwd` e sem `isolation`**, e o papel correspondente ao `subagent_type` marcado com `isolated()`.
Satisfeitas, retorna `permissionDecision: "allow"` + `updatedInput` (com `isolation` definido como `"worktree"`).

`isolation` e `cwd` são **mutuamente exclusivos** na ferramenta `Agent` — se o próprio modelo especificou `cwd`, isso é respeitado.
"Precisa de isolamento?" é um **atributo do papel**, não um interruptor global nem uma decisão tomada a cada despacho; um papel que não precisa de isolamento não recebe um byte a mais.

**Ligar isolamento exige mover o [workbench](glossary.md#工作台) para fora do repositório.** Um agent isolado não consegue escrever no checkout compartilhado,
então o workbench precisa apontar para fora do repositório via `home=`. `starter_flow(isolate=True)` usa
`<ws>.parent/.flower-<ws.name>`, e `Runtime(workbench=True)` usa `<run_dir>/workbench` —
ambos fora do repositório, **mas não são o mesmo diretório**; não misture.

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

A marca é um atributo do lado Python, `_flower_isolate`, gravado via `object.__setattr__`, **não um campo da dataclass** —
o SDK serializa com `asdict()`, que só reconhece campos declarados, então essa marca não vaza para o lado da CLI (verificado na prática).

**O custo**: um `dataclasses.replace()` sobre o `AgentDefinition` perde a marca, e o isolamento deixa de funcionar silenciosamente.

`worker(isolate=True)` passa internamente por `isolated()`.

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

Instala de uma vez os hooks que o workbench precisa. É o que o `Runtime._attempt` chama.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workbench` | `Workbench` | obrigatório, posicional | passado para `index_guard` e `spill_guard` |
| `delegate_only` | `bool` | `True` | só instala `delegate_guard` se `True` |
| `spill_threshold` | `int \| None` | `4000` | só instala `spill_guard` se verdadeiro |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | acrescenta `isolate_guard` se **qualquer um** deles estiver marcado com `isolated()` |
| `allow_glance` | `bool` | `False` | repassado a `delegate_guard(allow_glance=)` |

Saída:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  havendo papéis marcados → acrescenta `isolate_guard(agents)`.
- `PostToolUse`: sempre `[index_guard(workbench)]`; `spill_threshold` verdadeiro → acrescenta
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Chaves de evento com lista vazia são removidas**, não se retorna lista vazia.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatena** vários conjuntos de configuração de hook por nome de evento.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variádico | quantos conjuntos quiser. Grupos `None` são ignorados |

Usa `extend`, **sem deduplicação** — passar o mesmo guard duas vezes o instala duas vezes. O `Runtime` usa isso para juntar `spec.hooks`,
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

O diretório de trabalho para spill: três subdiretórios + um índice. O índice é **injetado no system prompt**, então o agent sabe a cada rodada o que tem em mãos.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `workspace` | `Path` | obrigatório, posicional | a área de trabalho. `__post_init__` faz o resolve |
| `dirname` | `str` | `".flower"` | nome do diretório do workbench, relativo a `workspace` |
| `max_index_entries` | `int` | `40` | **afeta só `prompt_block()`**: quantas entradas de cada tipo no máximo aparecem no trecho injetado no system prompt; o excedente vira uma linha "…mais N". O próprio `INDEX.md` não tem esse limite e lista tudo |
| `home` | `Path \| None` | `None` | se fornecido, é usado como `root`, **ignorando `dirname`**. Quando não é `None`, também sofre resolve |

| Membro | Assinatura | Descrição |
|---|---|---|
| `root` | `@property -> Path` | usa `home` se fornecido, senão `workspace / dirname` |
| `external` | `@property -> bool` | se `root` está **fora** de `workspace`. No modo isolado deve ser `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts que serão rodados uma segunda vez |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, saídas longas acima de 2000 caracteres |
| `notes` | `@property -> Path` | `root / "notes"`, decisões-chave, um arquivo por decisão |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | o caminho mostrado ao modelo: relativo dentro da área de trabalho, absoluto fora dela |
| `ensure` | `() -> Workbench` | faz mkdir dos três diretórios e retorna `self` (encadeável: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(caminho exibido, descrição, bytes)`. `rglob("*")` recursivo, pulando arquivos que começam com `.` |
| `refresh` | `() -> str` | reescreve o `INDEX.md` e retorna o conteúdo |
| `prompt_block` | `() -> str` | **o trecho injetado no system prompt**. Curto de propósito — ele está presente em toda rodada |

Formato da autodescrição de script: `# desc: uma frase` nas 8 primeiras linhas (também reconhece os comentadores `//` e `--`),
com fallback para o primeiro comentário não vazio ou a primeira linha da docstring (truncada em 100 caracteres).

As três regras injetadas por `prompt_block()`:

1. Scripts que serão rodados uma segunda vez vão em `scripts/`, com `# desc:` na primeira linha.
2. Saídas acima de **2000 caracteres** vão em `artifacts/`, e na conversa entram só o caminho e a conclusão.
3. Decisões-chave vão em `notes/`, um arquivo por decisão.

Quando `external=True`, o `prompt_block()` acrescenta uma frase: "acesse-o por caminho absoluto".

**Subagents não herdam o índice.** Ele passa pelo `system_prompt.append` de nível de sessão, e o subagent tem seu próprio
system prompt (medido em $0.2461). Por isso, as duas informações "saídas longas vão em `artifacts/`" e "onde fica o workbench" precisam ser repassadas pelo
[coordinator](glossary.md#协调者) dentro do [task brief](glossary.md#任务书) — **esse é o único canal**, não é redundância.
Em `WORKER_RULES` isso **foi deixado de fora de propósito**: o caminho real é gerado pelo `Workbench`, e escrevê-lo fixo daria errado.

---

## Session store {#会话存储}

Código-fonte: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Três camadas de herança: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
O `Runtime` **sempre usa a camada mais externa**, e as políticas das três são controladas por parâmetros de construção.

Cada camada cuida de uma coisa: persistir, [trimar](glossary.md#裁剪) por volume e valor, e [prunar](glossary.md#剪除) por "isso é um erro?".
Trim e prune acontecem no momento do **`load()`** (ou seja, quando o resume realimenta o histórico no modelo); os registros originais no SQLite não mudam um byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementa o protocolo `SessionStore` do SDK, com três tabelas: `entries` / `meta` / `summaries`.
A chave do store é `project_key/session_id[/subpath]` — **os transcripts de subagents são distinguidos pelo subpath**.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `str \| Path` | obrigatório, posicional | arquivo do banco. A conexão usa `check_same_thread=False` |

| Método | Assinatura | Descrição |
|---|---|---|
| `append` | `async (key, entries) -> None` | deduplicação idempotente por uuid (primeiro remove o já persistido, depois as repetições dentro do lote). Em replay de lote inteiro, **não avança o mtime nem refaz o fold do summary**; só o transcript principal (`subpath is None`) participa do summary |
| `projects` | `() -> list[str]` | os `project_key` que realmente existem no banco. **O SDK deriva isso do cwd; confirme com esta função antes de consultar, não chute** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **síncrono, não lê payload**, consulta só uma linha da meta. Serve para "continuidade no mesmo caminho" — dar resume numa sessão inexistente só explode depois que o subprocesso sobe |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | qual foi o tamanho de contexto que o modelo realmente viu na última rodada; retorna `0` se não encontrar. Varre de trás para frente apenas as últimas `scan` entradas; soma `input + cache_read + cache_creation` (olhar só `input_tokens` subestima gravemente) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | ordenado por seq; retorna `None` se não houver linhas |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | só o transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | lista os resumos de sessão |
| `delete` | `async (key) -> None` | ao apagar o transcript principal, **apaga em cascata os dos subagents**, evitando órfãos |
| `list_subkeys` | `async (key) -> list[str]` | lista os subtranscripts sob esta sessão |
| `close` | `() -> None` | fecha a conexão |

O `_next_mtime` interno garante **monotonicidade estrita** — `list_sessions` e o sidecar de summary compartilham esse relógio,
senão o caminho rápido de staleness do SDK erra o julgamento.

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
| `min_chars` | `int` | `2000` | resultados curtos não compensam trimar |
| `spill_dirname` | `str` | `".flower/spill"` | **relativo a `workspace`, precisa estar dentro da área de trabalho** — senão o `Read` do agent não alcança |
| `enabled` | `bool` | `True` | com `Runtime(trim=False)` isso vira `False` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | gera a linha de ponteiro que substitui o corpo |

**Os dois diretórios de spill não são o mesmo.** O `spill_guard` grava em `<workbench.root>/spill/` (pode estar fora da área de trabalho);
o `TrimPolicy.spill_dirname` grava em `<workspace>/.flower/spill/` (**precisa estar dentro da área de trabalho**).
Cada um corresponde a "cortar na hora" e "cortar no resume"; os diretórios são diferentes de propósito, não unifique.

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
| `keep_recent` | `int` | `6` | os N mais recentes ficam isentos. **Bem menor que o 20 do `TrimPolicy`** |
| `max_chars` | `int` | `2000` | acima disso, pula e deixa o `TrimPolicy` arquivar |
| `text` | `str` | ver assinatura | texto de substituição, com os placeholders `{cmd}` e `{age}` |

| Método | Assinatura | Descrição |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | aplica `text` para gerar o corpo substituto |

**Atua apenas em resultados da ferramenta `Bash`**, e o comando precisa casar com a whitelist de comandos efêmeros. **`Read` não entra aqui** —
o conteúdo de um arquivo não se distorce com o tempo a ponto de enganar. Conteúdo expirado **não sofre spill**, é descartado direto.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Decide se um comando Bash é um [comando efêmero](glossary.md#一次性命令).
**A decisão de liberação do `delegate_guard` e a decisão de expiração do trim compartilham esta mesma função** — o conjunto de comandos que o coordinator pode rodar sozinho
precisa ser igual ao conjunto cujos resultados serão marcados como expirados. Liberar sem trimar faz um `git status` expirado ocupar contexto para sempre e ainda induzir ao erro;
trimar sem liberar faz o coordinator despachar um subagent para um `ls`, trocando 4.3k de custo de partida por algumas dezenas de caracteres.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `cmd` | `str` | obrigatório, posicional | linha de comando completa |

Ordem da decisão:

1. Vazio / só espaços → `False`.
2. Substituição de comando (`$(`, crase, `<(`, `>(`) ou construções que "alteram estado" → `False`.
3. Depois de remover redirecionamentos seguros (`2>&1`, `&> /dev/null` e similares), ainda contendo `>` ou `<` → `False`.
4. Depois de remover `&&` / `||` / `;` / `|`, ainda sobrando um `&` isolado (execução em background) → `False`.
5. Quebra por `&&` / `||` / `;` / `|`, e **cada segmento precisa casar com a whitelist**.

Grandes categorias de verbos na whitelist: subcomandos `git` somente-leitura (`status`, `diff`, `log`, `show`, `branch`, `rev-parse` etc.),
informações de diretório e sistema (`ls`, `pwd`, `df`, `du`, `date`, `whoami`, `env` etc.), processos e contêineres
(`ps`, `top`, `lsof`, `docker ps`, `kubectl get` etc.), leitura de arquivos (`cat`, `head`, `tail`, `wc`, `stat`, `find`, `tree`),
busca de caminhos (`which`, `whereis`, `command -v`, `type`), processamento de texto (`grep`, `rg`, `sort`, `uniq`, `awk`, `sed`, `jq`, `diff` etc.).

Mesmo com o verbo na whitelist, estas construções são barradas: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` e `print >` dentro de `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

A primeira versão recusava todo comando composto de forma indiscriminada, e **na prática isso anulou o glance por completo** (as três tentativas do coordinator foram barradas),
então passou a decidir segmento a segmento.

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
| `workspace` | `str \| Path` | obrigatório | base para o diretório de spill |
| `policy` | `TrimPolicy \| None` | `None` | sem valor, usa o `TrimPolicy()` padrão |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | sem valor, usa o `EphemeralPolicy()` padrão |

Atributos públicos: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Ordem do `load()`: `super().load()` → limpa `last_report` → se `ephemeral.enabled`, `expire()` →
se `policy.enabled`, `trim()`. **Com `enabled=False`, o passo inteiro é pulado.**

| Método | Descrição |
|---|---|
| `expire(entries)` | resultados `Bash` sensíveis ao tempo que expiraram têm **apenas o corpo substituído; o bloco permanece**. O comando é buscado no `tool_use` da mensagem assistant anterior; pula `isCompactSummary` / `isMeta`; acima de `max_chars` pula (fica para o `trim`); os últimos `keep_recent` ficam isentos. Escreve `last_report["expired"]` |
| `trim(entries)` | o corpo dos `tool_result` com `>= min_chars` sofre spill para `<workspace>/<spill_dirname>/<16 primeiros do sha256>.txt`, e o conteúdo do bloco vira um ponteiro; os últimos `keep_recent` ficam isentos. Escreve `cleared` / `kept` / `chars_saved` em `last_report` |

**Só trima texto puro**: blocos `image` / `document` são mantidos como estão.

**Duas linhas vermelhas estruturais**: o **bloco `tool_result` precisa continuar lá**, só se pode trocar o content (faltar um já é
"Missing Tool Result Block"); entradas `isCompactSummary` não podem ser mexidas.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renderiza `store.last_report` em uma linha, para log de UI.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obrigatório, posicional | aceita também a subclasse `PruningSessionStore` |

Três saídas: nenhuma ação → `"未裁剪"`; só expiração → `"N 个时效性结果标记为过期"`;
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
| `drop_api_errors` | `bool` | `True` | remove mensagens de erro sintéticas da API (resíduo de queda de conexão) |
| `neutralize_interrupts` | `bool` | `True` | `tool_result` residuais de interrupção são trocados por uma explicação neutra |
| `interrupt_text` | `str` | ver assinatura | o texto dessa explicação neutra |
| `keep_denials` | `int` | `1` | mantém as N recusas de chamada de ferramenta mais recentes |

A razão do `keep_denials`: uma chamada recusada nunca foi executada, o resultado não tem informação, mas ocupa um espaço nada desprezível (medido: 273 caracteres numa ocorrência =
93 caracteres de texto de recusa + 180 caracteres com **o comando morto na íntegra**). Mais grave é que **isso induz ao erro** — na prática, depois de ler algumas
mensagens de "não use Bash diretamente", o coordinator parou de tentar até mesmo um `git status` liberado, aprendendo desamparo adquirido.
**O padrão é manter 1, não 0**: a recusa mais recente evita que o modelo repita a mesma tentativa barrada várias vezes na mesma rodada.

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
| `workspace` | `str \| Path` | obrigatório | base para o diretório de spill |
| `policy` | `TrimPolicy \| None` | `None` | política de trim |
| `prune` | `PrunePolicy \| None` | `None` | política de prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | política de expiração |

Além dos da classe pai, três atributos públicos a mais: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (primeiro `expire` + `trim`) → `self.prune(entries)`. O `prune` faz três coisas:

1. **Remove as chamadas recusadas antigas demais**: identificadas pela marca estrutural `toolDenialKind == "permission-rule"` do harness
   (mais confiável que casar o texto da recusa), mantendo as últimas `keep_denials` e removendo, das demais, o bloco `tool_use` **e** o `tool_result` juntos.
   Quando há vários `tool_use` na mesma mensagem assistant, **remove só os atingidos**, senão vira
   "Missing Tool Result Block"; blocos de texto e de thinking são preservados.
2. **Remove mensagens de erro sintéticas da API.** Elas continuam intactas no SQLite, só não são realimentadas.
3. **`tool_result` residuais de interrupção viram uma explicação neutra** — só o corpo é trocado, a entrada não é removida.

**A única linha vermelha estrutural**: o transcript é uma cadeia simples por `parentUuid`, então remover uma entrada obriga a religar seus filhos ao ancestral vivo mais próximo.
O `entries` do `relink` interno **precisa ser a lista completa (incluindo as que serão removidas)**; a filtragem é feita por ele mesmo —
se o chamador remover antes de passar, a cadeia se rompe ali e todo o histórico anterior se perde (**já pisamos nesse: não aparece quando as entradas removidas estão no fim,
mas explode quando estão no meio**).

**A ordem dos parâmetros difere da classe pai**: na pai é `(path, workspace, policy, ephemeral)`, na filha é
`(path, workspace, policy, prune, ephemeral)` — **o quarto posicional mudou de `ephemeral` para `prune`**,
e passar por posição desalinha silenciosamente. Passe sempre por palavra-chave.

---

## Resiliência {#韧性}

Código-fonte: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Quando a rede cai, fica esperando pendurado em vez de sair com falha. Quatro exportações: uma dataclass de política + três funções de sondagem utilizáveis isoladamente.

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
| `probe_interval` | `float` | `15.0` | intervalo entre duas sondagens |
| `max_offline_wait` | `float` | `3600.0` | quanto tempo no máximo esperar pendurado, padrão 1 hora |
| `retry_unknown` | `bool` | `True` | retentar erros que não se consegue classificar |
| `resume_prompt` | `str` | ver assinatura | o que se diz ao retomar. **Deliberadamente sem nenhum detalhe do erro** — o modelo precisa saber "foi interrompido, continue", não se foi `ENOTFOUND` ou 503 |

| Método | Assinatura | Descrição |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` com `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | espera pendurado a rede voltar. Retorna `True` se voltar, `False` se passar de `max_offline_wait`. `notify` é um callback `(str) -> None`, disparado uma vez **na primeira vez em que fica inalcançável** e uma vez na recuperação |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classifica o texto do erro em três categorias: `"transient"` / `"fatal"` / `"unknown"`.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `text` | `str \| None` | obrigatório, posicional | o texto original do erro. Vazio retorna `"unknown"` |

**Avalia fatal antes de transient** — textos como os de 401 costumam trazer a palavra `connection`, e inverter a ordem leva a esperar para sempre.

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

**Ao usar um gateway próprio, é ele que precisa ser sondado** — `api.anthropic.com` respondendo não prova nada sobre o gateway.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `host` | `str` | obrigatório, posicional | nome do host |
| `port` | `int` | obrigatório, posicional | porta |
| `timeout` | `float` | `5.0` | segundos |

**Faz apenas DNS (`getaddrinfo`) + handshake TCP**, sem enviar HTTP, sem credenciais, **sem custo**. Qualquer exceção conta como inalcançável.

---

## Eventos e interação {#事件与交互}

Código-fonte: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

[Evento](glossary.md#事件) é a estrutura estável na qual o fluxo de mensagens do SDK é achatado. **A [camada de interação](glossary.md#交互层) só conhece
`Event`, não importa nenhum tipo do SDK** — essa é a fronteira que permite trocar a UI sem mexer no núcleo. Veja [Trocar a camada de interação](../guide/interaction.md).

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
| `payload` | `dict[str, Any]` | `{}` | informação estruturada adicional |
| `raw` | `Any` | `None` | objeto original do SDK, para quando você quiser cavar fundo |

`__str__`: em `tool_call` é `f"[{tool}] {text}"`, caso contrário é `text`, e se `text` estiver vazio, `f"<{kind}>"`.
Ou seja, `print(ev)` já é legível.

`EventKind` tem **15** valores ao todo:

| kind | Quem emite | Descrição |
|---|---|---|
| `text` | `normalize` | corpo do assistant |
| `thinking` | `normalize` | bloco de raciocínio |
| `tool_call` | `normalize` | chamada de ferramenta. `text` é o resumo de `file_path` / `command` / `pattern`, truncado em 200 caracteres |
| `tool_result` | `normalize` | resultado da ferramenta. `text` truncado em 500 caracteres, `payload` traz `tool_use_id` / `is_error` |
| `task` | `normalize` | três tipos de mensagem Task, `text` é o nome da classe da mensagem |
| `system` | `normalize` | demais mensagens de sistema, `text` é o subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` traz `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | mensagem sintética de erro de API, `payload` traz `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **O corpo é entrada, não produção do modelo**, por isso não entra em `StepResult.text` |
| `unknown` | `normalize` | o que não foi reconhecido |
| `retry` | `Runtime` | aviso de retry |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | no payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | pergunta, **também carrega "o que a pessoa disse por iniciativa própria"** |

**Os quatro últimos não são produzidos por `normalize()`.**

O `payload` de todos os eventos de assistant / user traz:

| Chave | Tipo | Descrição |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | só existe quando `subagent` é verdadeiro |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Esta é a única fonte do critério de [handoff](glossary.md#换代)**, e também o número que mais merece ser visto numa execução de longo horizonte |

**O kind `ask` carrega ao mesmo tempo "pergunta" e "o que a pessoa disse por iniciativa própria".** No segundo caso, `payload["kind"] == "mail"`,
e **não há `options` / `remaining`**. A UI precisa checar `payload.get("kind")` antes de decidir como renderizar;
senão vai tratar uma frase como uma pergunta pendente de resposta e travar nela.

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
  `Event("error", payload={"synthetic": True})`. **Isso é intencional** — caso contrário o texto de desconexão entraria como corpo
  em `StepResult.text` e seria repassado ao passo seguinte.
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
| `options` | `list[str]` | `[]` | opções. A pessoa também pode não escolher nenhuma e digitar a sua |
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

Um **MCP server dentro do processo** (duas ferramentas) + um conjunto de métodos para a UI. Do lado do modelo, só aparecem
`mcp__human__ask` e `mcp__human__inbox`. Todos os parâmetros do construtor são keyword-only.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | Saída do modo **push**. Se você fornecer, `Workflow.run` não faz mais o ligamento |
| `max_asks` | `int \| None` | `None` | **Sem limite de vezes**. Um número vira cota rígida; `0` = proibido perguntar (totalmente automático / CI). Ao estourar, a ferramenta **recusa direto, sem bloquear** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutos. `None` = espera para sempre; **`<= 0` = não espera, toda pergunta cai no vazio imediatamente** |
| `log_path` | `str \| Path \| None` | `None` | perguntas e respostas são **anexadas** ao disco, sem ocupar contexto |
| `amend_path` | `str \| Path \| None` | `None` | o que a pessoa disser durante a execução é anexado a este arquivo (normalmente o próprio brief). **Sem gravar em disco não sobrevive à fronteira do passo** — o próximo passo é uma sessão nova, que só lê o artefato congelado |
| `over_budget_text` | `str` | constante do módulo | resposta devolvida ao modelo quando a cota estourou |
| `timeout_text` | `str` | constante do módulo | resposta devolvida ao modelo em caso de timeout |
| `declined_text` | `str` | constante do módulo | resposta devolvida ao modelo quando a pergunta foi pulada |

Atributos públicos: os oito com o mesmo nome dos parâmetros do construtor, mais `asks: list[Ask]`, `mail: list[Mail]` e
`ui_errors: list[str]` (**exceções lançadas pelo callback da UI são recolhidas aqui, sem interromper a execução**).

| Membro | Assinatura | Descrição |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | passe direto para `AgentSpec.mcp_servers`. **A chave precisa bater com o nome do server**, por isso ele já entrega os dois juntos |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | bloqueia esperando a pessoa. **Nunca lança exceção, exceto `CancelledError`** — ninguém responder também é uma resposta; distinga pelo `ask.state` |
| `send` | `(text: str) -> Mail \| None` | a pessoa fala algo por iniciativa própria. **Pode ser chamado de qualquer thread**. Não interrompe o agent; internamente chama `amend()` automaticamente |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | anexa em `amend_path`. Retorna se realmente escreveu (sem caminho configurado, texto vazio ou `OSError` dão `False`) |
| `pending_mail` | `() -> list[Mail]` | mails ainda não recolhidos |
| `remaining` | `@property -> int` | quantas perguntas ainda cabem. **Com `max_asks=None` retorna `-1`**, não 0 nem infinito |
| `pending` | `() -> list[Ask]` | perguntas atualmente pendentes de resposta |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | usado no modo **pull**. Retorna `None` em timeout; se cancelado, lança |
| `answer` | `(ask_id: str, text: str) -> bool` | responde. `False` = esta pergunta já não está esperando (timeout / já respondida) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | pula, deixando o modelo julgar sozinho |
| `transcript` | `() -> str` | markdown com o registro de perguntas e respostas |

**Escolha um dos dois modos**: **push** — construa `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` só faz o ligamento automático quando `channel.on_event is None`, então se você passou o seu, ele não é sobrescrito.

**Entre threads**: `answer` / `decline` / `send` usam internamente `loop.call_soon_threadsafe`,
chamar direto do backend Web / da thread de input do TUI é o normal.

Os três significados de "0 / None" são diferentes entre si; não confunda: `max_asks=None` = sem limite, `max_asks=0` = proibido perguntar;
`timeout_s=None` = espera para sempre, `timeout_s<=0` = timeout imediato; `remaining` com `max_asks=None` é `-1`.

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

Registra entre processos "qual passo usou qual sessão"; é dela que a [continuidade](glossary.md#接续) depende para achar onde a execução parou.
O arquivo é `<run_dir>/lineage.json`.

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `path` | `Path` | obrigatório | caminho do arquivo de linhagem |
| `workspace` | `Path` | obrigatório | workspace. `__post_init__` faz resolve |
| `steps` | `dict[str, str]` | `{}` | nome do passo → `session_id` |
| `woke` | `int` | `0` | quantas vezes despertou |

| Membro | Assinatura | Descrição |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lê `<run_dir>/lineage.json`. **Arquivo inexistente, ilegível, ou com o campo `workspace` divergente: retorna vazio em todos os casos, sem erro** |
| `remember` | `(step: str, session_id: str) -> None` | guarda o mapeamento e **grava em disco imediatamente**. Step vazio ou sid vazio retorna direto |
| `bump` | `() -> int` | incrementa em 1 a contagem de despertares, grava em disco, retorna o novo valor (na primeira execução é `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **move** o arquivo de linhagem + `extra` para `<into>/<YYYYmmdd-HHMMSS>/` e zera `steps` / `woke`. **Mover não é apagar** |

A gravação usa substituição atômica via `tmp.replace(path)`; `OSError` é engolido em silêncio — falhar ao gravar não deve derrubar esta execução.

**`workspace` é a guarda**: o `project_key` do SDK é derivado do caminho do workspace; depois que o diretório é copiado para outro lugar, o `session_id` antigo não é encontrado,
então caminho divergente vale como inexistente.

Ao carregar a linhagem, `Workflow.run` valida cada registro com `runtime.has_session(sid)` para ver se ainda está na base, e só usa os vivos —
o arquivo de linhagem pode viver mais que o `sessions.db`.

---

## Exemplos mínimos utilizáveis {#示例}

Os cinco trechos rodam direto. Pré-requisito: `claude-agent-sdk` instalado e `ANTHROPIC_API_KEY` ou `ANTHROPIC_AUTH_TOKEN` disponível
(caso contrário, `Runtime(...)` já lança `RuntimeError` na construção).

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
`AgentSpec` tem como padrão `allowed_tools=["Read", "Glob", "Grep"]` e `delegate_only=False`,
então o `Runtime` instala automaticamente o [`whitelist_guard`](#whitelist-guard) nele, barrando `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordenador + executor {#示例-协调}

Um [coordenador](glossary.md#协调者) que não põe a mão na massa comandando um [executor](glossary.md#执行者) que trabalha.
Esta é a primeira camada de economia de contexto do flower.

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

    # workbench=True é obrigatório: o delegate_guard fica pendurado em workbench_hooks,
    # sem workbench ligado, o Bash/Write do coordenador não tem nenhum hook barrando.
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

Os dois primeiros parâmetros de `worker()` são posicionais: `description` (usado pelo coordenador para escolher quem chamar) e `prompt` (o system prompt dele,
com `WORKER_RULES` concatenado automaticamente depois). Os três primeiros de `coordinator()` são posicionais: `name`, `instructions`, `workers`.

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
        # Para continuar falando na mesma sessão, escreva resume_from="造句"; para bifurcar, some fork=True
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

Os três primeiros campos de `Step` (`name` / `spec` / `prompt`) são posicionais, e `steps` de `Workflow` também.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` posicional, os dois callbacks keyword-only.
**Atenção: `continuous=True` é o padrão**: na segunda execução com o mesmo `run_dir` + o mesmo `workspace`,
até os passos com `resume_from=None` continuam falando na sessão anterior.

### Adicionando uma guarda de objetivo {#示例-目标}

Primeiro deixe o [juiz](glossary.md#判定者) fixar o objetivo e a lista de critérios, depois faça o passo de trabalho se submeter ao veredito —
se não passar, refaz com o feedback, em no máximo três rodadas.

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
        # o prompt do goal_step lê ctx["确认需求"] (valor padrão de brief_key).
        # Sem clarify_step, você mesmo precisa preencher; senão ele só vai ver "(没有确认书)".
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
    print(ctx.get("_aborted")) # motivo do StepAbort (quando é inatingível e ninguém responde)


asyncio.run(main())
```

`with_goal` só troca `gate` / `on_reject` / `retries`; os demais campos são levados intactos via `dataclasses.replace`.
O juiz roda em **sessão independente**: dentro do `gate` ele chama separadamente `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
com `resume` sempre `None`.

### Trocando a camada de interação {#示例-交互层}

Para trocar o terminal por Web / TUI / HTTP, só precisa mudar duas coisas: a função que renderiza `Event` e a corrotina que recolhe as perguntas.

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
    # os de kind == "ask" que não são mail ficam a cargo do answerer abaixo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Recolhe perguntas no modo pull. Ao migrar para backend Web / serviço HTTP, esta corrotina é o único lugar a mudar."""
    while True:
        ask = await ch.next_ask()          # sem timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # O Runtime usa o workbench que o próprio workflow criou — não monte outro
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
`Workflow.run` só faz o ligamento automático quando `channel.on_event is None`, então se você passou o seu `on_event`, ele não é sobrescrito.
`answer()` / `decline()` / `send()` / `interrupt()` **podem todos ser chamados de outra thread**.

---

## Armadilhas e pontos de erro {#陷阱}

Na ordem em que você vai tropeçar neles, não por módulo. Cada item tem origem medida na prática.

### Montagem {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = a thread principal sem nenhuma parede.**
   O `delegate_guard` só é instalado quando há workbench, e o `whitelist_guard` é pulado por `delegate_only=True`.
   Se usa coordenador, ligue o workbench. Detalhes em [Runtime](#runtime).
2. **Existem dois locais de workbench; não monte o caminho errado.** `Runtime(workbench=True)` cai em `<run_dir>/workbench`;
   `Workbench(ws)` fica por padrão em `<ws>/.flower`. Ao montar `brief_path` à mão, siga o segundo,
   senão **o brief é escrito no diretório A, o índice injetado varre o diretório B, e nada dá erro**.
   Jeito certo: o próprio workflow faz `Workbench(...).ensure()` e pendura em `Workflow.workbench`,
   e então entrega **o mesmo objeto** para `Runtime(workbench=wb)`.
3. **`allowed_tools` não é uma whitelist exclusiva, é uma lista de dispensa de aprovação.** O modelo continua podendo chamar ferramentas que não estão nela.
   O "não tem ferramenta de escrita" de `clarify()` / `judge()` depende do hook [`whitelist_guard`](#whitelist-guard).
   E `coordinator()` tem `permission_mode="acceptEdits"` por padrão — quem passar esse valor para
   `clarify()` / `judge()` perde a proteção.
4. **`disallowed_tools` é de nível de sessão**, e desabilita junto as ferramentas de mesmo nome nos subagents.
5. **O índice do workbench não chega até o subagent.** "Escreva saídas longas em `artifacts/`" precisa ser repassado pelo coordenador dentro do task brief;
   esse é o único canal.
6. **`Runtime(...)` lança `RuntimeError` já na construção** quando não há credencial, não na hora do `run()`.
7. **`Runtime.run_id` precisa ser único por instância.** O `manifest.json` deduplica pelo campo `run`; quando dois ids colidem,
   quem escreve depois apaga as linhas do outro achando que são "as que eu mesmo escrevi da última vez".

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` é o padrão**, e `resume_from=None` não significa "sessão totalmente nova".
   Para abrir uma nova a cada vez, use explicitamente `continuous=False`. **Mudar o nome do passo equivale a cortar a linhagem.**
9. **`with_goal(rounds=N)` é o total de rodadas, não rodadas adicionais**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` não escreve `ctx[step.name]`** — um `lambda ctx: ctx["某步"]` a jusante vai dar `KeyError`.
    Para seguir adiante carregando o resultado incompleto, use `on_fail="continue"`.
11. **`resume_from` apontando para um passo não executado / já falho lança `ValueError`**, não é ignorado em silêncio.
12. **`Step.reduce` tem que ser função síncrona; `gate` / `when` / `on_reject` podem ser async.**
13. **`fork=True` sem `resume` é silenciosamente inócuo.** O `Workflow` nunca passa `resume_at`;
    para voltar por mensagem só chamando `Runtime.run` diretamente.
14. **Ao dirigir o `Runtime` você mesmo, `on_session` precisa ser removido antes do gate**, senão a sessão do juiz será gravada
    na linhagem do passo de trabalho. O `Workflow` garante isso com `try/finally`.
15. **`step_name` determina a chave no manifesto e na linhagem.** O `Workflow` acrescenta sufixos `#retryN` / `#roundN`,
    e o juiz acrescenta `#轮次` — **nomes com sufixo não entram na linhagem entre processos**, e essa é justamente uma das formas
    de implementar "o juiz é sempre uma sessão nova".

### Papéis {#陷阱-角色}

16. **`clarify(max_turns=<número pequeno>)` transforma "perguntas ilimitadas" em conversa fiada** — cada pergunta é um turno.
17. **`goal_step()` não tem parâmetro `can_run`**, só dá para passar `can_run=True` via `**spec_kw`.
    Sem isso, o juiz que define o objetivo não recebe `Bash`, e a regra do `JUDGE_RULES` que diz "primeiro entenda em que ambiente você está" não é executável.
18. **`judge(can_run=True)` permite ao juiz alterar o workspace** — o `whitelist_guard` é derivado de `allowed_tools`,
    e dar `Bash` libera `Bash` (`Write`/`Edit` continuam barrados, mas o próprio `Bash` escreve arquivos). Para neutralidade absoluta, não ligue.
19. **`worker(isolate=True)` exige que o workspace seja um repositório git**, senão a ferramenta `Agent` responde direto
    `"not in a git repository"`, sem degradação silenciosa. E a marca de isolamento é um atributo Python:
    **fazer `dataclasses.replace()` sobre um `AgentDefinition` a perde**.
20. **Ao construir `AgentDefinition` diretamente, os parâmetros são camelCase**: `maxTurns`, `permissionMode`.
    `worker()` já faz essa conversão por você.

### Handoff e contexto {#陷阱-换代}

21. **Com o handoff ligado, o auto-compact é forçadamente desligado, sem rede de segurança.** Por isso o passo que escreve o documento de handoff precisa ter caminho de degradação.
    Para manter o auto-compact, defina explicitamente `AgentSpec.compact`.
22. **`HandoffPolicy.window` configurado pequeno demais queima dinheiro em handoffs infinitos.** A única trava é `max_generations=8`.
    Do outro lado, **`default_window()` retorna `1_000_000` quando nenhuma das duas variáveis de ambiente está definida** —
    estimar alto é amortecido por `is_overflow()` (vira um handoff degradado), não é erro fatal, mas o handoff daquela geração sai degradado.
23. **Sem workbench, o handoff não é gravado em disco.** O documento ainda é entregue ao sucessor via prompt, mas a pessoa não consegue consultá-lo depois.

### Armazenamento {#陷阱-存储}

24. **`Runtime(trim=False)` (padrão) não significa "não limpa nada".** O store é sempre `PruningSessionStore`;
    `trim=False` só desliga o trim de resultados grandes; **remover restos de desconexão, remover chamadas recusadas, neutralizar resíduos de interrupção e expirar conteúdo com validade continuam acontecendo.**
25. **Os dois diretórios de spill não são o mesmo**: o `spill_guard` grava em `<workbench.root>/spill/`,
    e o `TrimPolicy.spill_dirname` grava em `<workspace>/.flower/spill/` (tem que ficar dentro do workspace).
26. **O quarto parâmetro posicional de `PruningSessionStore.__init__` é `prune`, não `ephemeral`**,
    diferente da classe-pai. Passar por posição desalinha silenciosamente.

### Documentos e interação {#陷阱-文书}

27. **Quando o `Verdict` não consegue extrair a conclusão, `state=""` e `ok=False`; jamais trate isso como atingido.**
    Além disso, "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" caem todos em `unreachable`,
    o que dispara o caminho "parar e perguntar à pessoa", não "mais uma rodada".
28. **`Brief.parse` descarta todo o conteúdo após um fence de código não fechado** — quando a saída do modelo é truncada,
    todas as seções seguintes deixam de ser parseadas, `complete()` fica `False`, e o gate manda refazer.
29. **`Brief.load` trata `"(未填)"` como vazio.** Se ao editar o brief à mão você copiou o texto de placeholder, aquela seção continua contando como faltante.
30. **Os três "0 / None" de `HumanChannel` têm significados diferentes**: `max_asks=None` sem limite, `max_asks=0` proibido perguntar;
    `timeout_s=None` espera para sempre, `timeout_s<=0` timeout imediato; `remaining` com `max_asks=None` retorna **`-1`**.
31. **`Event("ask")` carrega ao mesmo tempo perguntas e falas espontâneas da pessoa**, estas últimas com `payload["kind"] == "mail"`. A UI precisa checar isso antes.
32. **`Workflow.run` só faz o ligamento automático quando `channel.on_event is None`** —
    se você mesmo construir `HumanChannel(on_event=...)`, os eventos de pergunta não sairão também pelo `on_event` do workflow.
