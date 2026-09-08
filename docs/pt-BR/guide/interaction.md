# Trocar a camada de interação

O núcleo do flower não sabe que a UI existe. Tudo o que acontece dentro de uma run — o modelo falando, chamando uma ferramenta, o contexto quase cheio, a necessidade de perguntar algo a uma pessoa — é achatado na mesma estrutura de dados: [`Event`](../reference/glossary.md#事件).
**A [camada de interação](../reference/glossary.md#交互层) só conhece `Event`; ela não importa nenhum tipo do SDK.**
É essa a fronteira que permite trocar a UI sem mexer no núcleo: terminal, Web, serviço HTTP, execução totalmente automática sem supervisão — o que muda é o consumidor dos `Event`, e nada mais precisa ser alterado.

## Que problema resolve {#解决什么问题}

O fluxo de mensagens do SDK usa **tipos internos**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`,
`ResultMessage`, `SystemMessage`… Consumi-los diretamente na UI tem duas consequências: a cada atualização do SDK o front-end precisa acompanhar; e como cada tipo de mensagem tem um formato diferente, cada UI precisa reescrever do zero a lógica de "isto é texto ou uma chamada de ferramenta".

`normalize(message)` converte uma mensagem do SDK em 0 a N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
O custo é uma conversão; o ganho é não haver dependência de tipos entre a camada de interação e o SDK.

Essa fronteira ainda resolve, de quebra, quatro coisas menos óbvias — todas dentro de `normalize()`:

1. **As falas dos [subagents](../reference/glossary.md#subagent) ficam marcadas** (`payload["subagent"]`).
   Sem isso, a [task brief](../reference/glossary.md#任务书) enviada e as falas intermediárias do subagent se misturariam ao texto da [main thread](../reference/glossary.md#主线程) e, seguindo o [workflow](../reference/glossary.md#流程), contaminariam o prompt do passo seguinte.
2. **As mensagens de erro sintéticas geradas em quedas de conexão são desviadas para `kind="error"`.** Ao cair a conexão, o lado do SDK escreve `API Error: …` no transcript como se fosse uma mensagem de assistant, e ela se parece com fala do modelo (`model` é `"<synthetic>"`).
   Se não for barrada aqui, entra em `StepResult.text` e é repassada ao [step](../reference/glossary.md#步骤) seguinte.
3. **As fronteiras de compact são reportadas explicitamente** (`kind="reset"`). Depois da fronteira, o que o modelo "lembra" é apenas o resumo, e o cache de prompt também é cortado ali — uma run [long-horizon](../reference/glossary.md#长程) precisa poder enxergar isso.
4. **O nível de contexto sai junto de cada mensagem** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). É a única fonte do critério de
   [handoff](../reference/glossary.md#换代).

## Como usar (código mínimo) {#怎么用最小代码}

Uma camada de interação precisa ligar três coisas: **saída de eventos** (para onde renderizar), **canal de perguntas** (quem responde) e **interrupção** (como mandar parar). O trecho abaixo liga as três e roda direto:

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
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" que não seja mail fica com o answerer abaixo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Busca perguntas em modo pull. Ao migrar para Web / HTTP, esta corrotina é o outro ponto a mudar."""
    while True:
        ask = await ch.next_ask()           # sem timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # O Runtime usa o workbench que o próprio workflow criou — não monte outro
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # fecha a conexão SQLite
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

Dois detalhes de finalização fáceis de esquecer: `rt.close()` sempre no `finally`; e se `ctx["_failed_at"]` tiver valor, a run parou no meio (`on_fail="stop"`) — não trate como sucesso.

!!! note "Só existe um workbench; não monte outro"
    O [workbench](../reference/glossary.md#工作台) criado por `Runtime(workbench=True)` fica em
    `<run_dir>/workbench`, enquanto `Workbench(ws)` fica por padrão em `<ws>/.flower` —
    não são o mesmo diretório. Se o programa que dirige a execução montar o caminho por conta própria para achar `需求.md`, você acaba com "o brief escrito no diretório A e o índice injetado varrendo o diretório B", sem nenhum erro.
    Ou passe para o `Runtime` aquele que o workflow criou (como acima),
    ou use a sondagem somente leitura `wake_state()` para perguntar onde ele está.

### As três saídas de evento {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. um único agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. o workflow inteiro, repassado a cada passo
wf = Workflow(steps=[...], channel=ch)                  # 3. o canal de perguntas, ligado à mesma saída
```

A terceira ligação acontece dentro de `Workflow.run`: **só é feita automaticamente quando `on_event` não é `None` e `channel.on_event` ainda é `None`**. Se você já ligou a sua, ela não é sobrescrita:

```python
ch = HumanChannel(on_event=my_own_sink)     # ligada por você; o Workflow não mexe nela
```

`on_step(step, result)` é outro callback, chamado uma vez ao fim de cada passo (**inclusive em falha**), recebendo o `StepResult` completo. Barra de progresso, gravação em disco e alertas vão aqui; não tente montar isso a partir do fluxo de `Event` — o texto é quebrado em vários pedaços por handoff e retry.

### Terminal: o padrão {#终端默认的那个}

Já existe um, sem escrever código. `flower "帮我做一个 X"` passa por
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
que é a **implementação de referência da camada de interação, não parte do framework**; pode ser substituída inteira. Para os flags, veja a [referência da CLI](../reference/cli.md).
Falando de tamanho com honestidade: o `cli.py` inteiro tem 1264 linhas, 57KB — mas **não é o arquivo inteiro que precisa ser trocado**.
O ponto real de substituição é a `class Render` lá dentro (`cli.py:489-687`, 197 linhas), cuja docstring diz exatamente isso: "Event → terminal. Trocar a UI é trocar esta única classe." As outras mil e tantas linhas são interrupção, oracle, recibos de caixa de entrada, resgate por sinal — acessórios **específicos do terminal** que, ao migrar para Web ou HTTP, você não copiaria de qualquer forma.

Ou seja, a afirmação "cerca de 200 linhas substituíveis em bloco" se sustenta — desde que se refira a `Render`, e não ao `cli.py`.

Se você escrever a sua própria UI de terminal, o ponto crítico é a thread que lê a entrada padrão:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lê a entrada padrão continuamente: se há pergunta pendente é resposta, senão vai para a caixa de entrada. Devolve o bit de parada."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # polling, só assim o bit de parada é respeitado
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # seguro entre threads
            else:
                ch.send(raw)                    # vai para a caixa de entrada, não interrompe o trabalho em voo

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

As três regras vieram de tropeços reais:

- **Use uma thread daemon, não `asyncio.to_thread(input, ...)`.** `input()` bloqueado não pode ser cancelado, e antes de sair o `asyncio.run` precisa dar join nas threads do executor padrão — resultado: o trabalho termina e você ainda precisa apertar Enter mais uma vez para sair.
- **Use polling com `select`, não `input()` direto dentro do laço.** Mesmo problema de cancelamento: uma thread bloqueada em `input()` não é mais acordada por `stop.set()`.
- **Leia sempre, não só quando houver pergunta.** Se você só lê quando há pergunta, tudo o que a pessoa digitou durante as horas de trabalho fica no buffer do terminal e é engolido como resposta na próxima pergunta — a pessoa nem viu a pergunta e ela já foi "respondida".

### Web: fila + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # síncrono, na thread do event loop, não pode bloquear
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # um erro no front-end não deve levar junto três horas de trabalho
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # thread que trata a requisição — outra thread, e isso é o normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` é o objeto bruto do SDK (nos eventos `ask`, é um `Ask`); **não é serializável em JSON e não deve ser enviado ao front-end** — usar `raw` equivale a amarrar o front-end de volta aos tipos do SDK, e toda essa camada perde o sentido. Os quatro campos `kind` / `text` / `tool` / `payload` bastam.

### HTTP: número de sequência + polling {#http序号--轮询}

Sem conexão persistente, numere os eventos e deixe o cliente buscar:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # guarda só os mais recentes; a memória não cresce com a duração da run


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # o que está pendurado esperando resposta agora
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = esta pergunta já não está mais esperando
```

Duas fronteiras a reconhecer: quando o `maxlen` enche, os mais antigos são descartados, então um cliente que volta com um `after` muito antigo não consegue recuperar tudo — o intervalo de polling precisa ser compatível com esse tamanho; e **é obrigatório dar um valor finito a `timeout_s`** — sem ninguém fazendo polling, a pergunta nunca termina sozinha, e `timeout_s=None` deixa a run inteira pendurada para sempre. O padrão de `1800.0` segundos é adequado.

### Totalmente automático, sem supervisão: não há ninguém {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # todos os eventos são descartados
```

O equivalente na linha de comando é `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (negativos idem) é o modo totalmente automático: a pergunta **não entra na fila de espera nem emite evento `asked`**; ela é liquidada imediatamente como `state="timeout"`, e a ferramenta devolve este texto fixo —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— e assim a run segue normalmente. As perguntas e respostas continuam sendo anexadas a `HumanChannel(log_path=...)` (o `starter_flow` liga por padrão em `<工作台>/notes/问答记录.md`), então depois é possível ver o que foi perguntado e quais suposições foram adotadas.

Se você não quer que ele abra a boca, use `max_asks=0`: a pergunta é recusada direto (`state="over_budget"`), também sem bloquear.
Note que isso **não é** "tirar a ferramenta" — `allowed_tools` não é exclusivo, e assim que o [coordenador](../reference/glossary.md#协调者) recebe um `channel` ele ganha as duas ferramentas `mcp__human__ask` e `mcp__human__inbox` juntas, estando ou não na lista. Só a cota e o timeout barram perguntas.

!!! warning "Sem supervisão, não deixe uma pergunta esperar para sempre"
    `timeout_s=None` significa "esperar para sempre". Sem ninguém olhando, uma única pergunta trava no lugar uma run de dez horas — sem erro, sem timeout, sem diferença visível no log. Sem supervisão existem apenas dois valores corretos: `0` (falha imediatamente) ou um número finito de segundos.

## O que ele realmente faz {#它实际做了什么}

### O formato do `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valores possíveis, ver tabela abaixo
    text: str = ""
    tool: str = ""                      # só tool_call tem valor
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objeto bruto do SDK / Ask; tocou nele, amarrou-se de volta ao SDK
```

`str(ev)`: para `tool_call` é `[nome da ferramenta] resumo`; para os demais é `text`; quando `text` está vazio, é `<kind>`.

### Os 15 `EventKind` {#15-个-eventkind}

| `kind` | Quem emite | Quando aparece | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Texto do modelo | O texto | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloco de raciocínio | Conteúdo do raciocínio | idem acima |
| `prompt` | `normalize()` | **Entrada**: seu prompt, a task brief enviada ao subagent | Texto de entrada | idem acima |
| `tool_call` | `normalize()` | O modelo inicia uma chamada de ferramenta | Resumo (`file_path` / `command` / `pattern`, cortado em 200 caracteres) | `id`, `input` + idem acima; `tool` é o nome da ferramenta |
| `tool_result` | `normalize()` | Retorno da ferramenta | Primeiros 500 caracteres (vazio quando o conteúdo não é string) | `tool_use_id`, `is_error` + idem acima |
| `result` | `normalize()` | Fim de uma consulta ao SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Mensagem sintética de queda de conexão | Texto do erro | `synthetic: True` |
| `reset` | `normalize()` | Fronteira de compact ou reset de sessão | `压缩(trigger) 167000 → 42000 tokens`; em reset de sessão, `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vazio em reset de sessão) |
| `system` | `normalize()` | Demais mensagens de sistema do SDK | subtype | `data` repassado tal como veio |
| `task` | `normalize()` | Mensagem de progresso de tarefa | **vazio** | `kind` = nome da classe de mensagem do SDK |
| `unknown` | `normalize()` | Tipo de mensagem não reconhecido | Nome da classe | — |

!!! note "O texto de `task` é vazio; não o imprima direto"
    `TaskProgressMessage` e afins são tipos internos de mensagem do SDK. Antes, `normalize()` emitia o nome da classe como texto; na tela isso é ruído puro e, misturado ao texto do agent, parece erro (medido na prática). Agora ele vira um evento **sem texto**, com o nome da classe em `payload["kind"]` — exibir ou não é decisão da camada de interação
    (`events.py`).
| `ask` | `HumanChannel` | Precisa de resposta humana, uma pergunta chegou a um desfecho, ou uma pessoa falou por iniciativa própria | Pergunta / fala da pessoa | Duas identidades, ver abaixo |
| `retry` | `Runtime` | Repetindo / pendurado esperando a rede | Uma frase de explicação | `step`, `attempt` |
| `step` | `Workflow.run` | Fronteira de passo | Nome do passo | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: se aproximando / escrevendo / concluído | Uma frase com o nível de contexto | `phase`, `step`, `context`, `window` + ver abaixo |

**Quatro kinds não são produzidos por `normalize()`**: `ask` vem do `HumanChannel`, `retry` e `handoff` vêm do `Runtime`, e `step` vem de `Workflow.run`. Colocá-los no mesmo `EventKind` é proposital — **a UI conhece um único conjunto de `Event` e não precisa abrir outro caminho para "precisa de resposta humana" ou "fronteira de passo".**

Ao escrever a UI, deixe um ramo `else`. `EventKind` ainda vai ganhar novos membros, e UIs antigas não devem quebrar por causa disso.

### As três phases do `handoff` {#handoff-的三个-phase}

| `phase` | Quando é emitido | Extras no `payload` |
|---|---|---|
| `near` | O nível passou de `warn_at`. **Emitido uma única vez por geração**, sem inundar a tela | `at` (limiar de handoff) |
| `writing` | Começou a escrever o [documento de handoff](../reference/glossary.md#交接书). Escrever leva dezenas de segundos; sem este evento a interface parece travada | — |
| `done` | Handoff escrito, nova sessão iniciada | `degraded` (se é a versão degradada), `path` (onde foi escrito; string vazia quando não há workbench), `sections` |

O mecanismo em si está em [handoff](handoff.md).

### As duas identidades do `ask` {#ask-的两种身份}

`Event("ask")` carrega ao mesmo tempo "uma pergunta" e "algo que a pessoa disse por iniciativa própria"; **a UI precisa olhar primeiro `payload["kind"]`**:

| Identidade | Como reconhecer | `payload` |
|---|---|---|
| Uma pergunta | Não tem a chave `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` é aquele `Ask` |
| Fala espontânea da pessoa | `payload["kind"] == "mail"` | `kind`, `state` (`queued` ao entrar / `delivered` ao ser retirada), `id`, `amended` (em qual arquivo foi anexada; string vazia se não configurado). **Não tem `options` nem `remaining`** |

Uma pergunta emite **pelo menos dois** eventos: um ao ser feita (`state="asked"`) e outro ao ter desfecho (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). Basta a UI atualizar a mesma entrada pelo `payload["id"]`.

### Perguntar a uma pessoa: `Ask` e `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # os cinco desfechos citados acima
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # segundos de espera, uma casa decimal
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` é um servidor MCP in-process mais um conjunto de métodos para a UI. Do lado do modelo, só duas ferramentas são visíveis: `mcp__human__ask` (perguntar, fica pendurado esperando) e `mcp__human__inbox` (consultar a caixa de entrada, **não bloqueia**; se estiver vazia, retorna imediatamente uma frase explicando). Construtor completo:

```python
HumanChannel(
    *,                                  # tudo keyword-only
    on_event=None,                      # saída em modo push. O Workflow só liga automaticamente se for None
    max_asks=None,                      # None = sem limite; 0 = proibido perguntar. Excedeu, recusa direto, sem bloquear
    timeout_s=1800.0,                   # None = espera para sempre; <= 0 = falha imediatamente
    log_path=None,                      # perguntas e respostas são anexadas neste arquivo, sem ocupar contexto
    amend_path=None,                    # o que a pessoa disser durante a run é anexado neste arquivo, normalmente o brief
    over_budget_text=OVER_BUDGET,       # três respostas fixas, podem ser substituídas pelas suas
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` é o mais fácil de esquecer, e é ele que determina se "o requisito que a pessoa mudou no meio do caminho sobrevive à fronteira do passo".
Cada passo é uma [sessão](../reference/glossary.md#会话) nova, com artefatos congelados somente leitura: o que foi dito durante a run entrou apenas no contexto daquele agent; o passo seguinte (por exemplo, o [veredito](../reference/glossary.md#判定)) é uma sessão totalmente nova, que lê `需求.md` e `目标.md` e **não enxerga aquilo que você disse**, então julga pelas fronteiras antigas e classifica o que foi corrigido como fora de escopo.
`amend_path` **anexa** cada mensagem ao [brief](../reference/glossary.md#需求确认书) — anexa, não sobrescreve; o requisito original é histórico, e ver o que mudou é melhor do que não ver. O `starter_flow` liga por padrão em `<工作台>/notes/需求.md`.

Na prática ($0.6767) isso funcionou melhor do que o esperado: a pessoa disse "de passagem, reporte o total de bytes"; o coordenador consultou a caixa de entrada e reportou —
"hand já leu isso no complemento em execução de `.flower/notes/需求.md` e já calculou, não precisa despachar de novo".
**O subagent leu do arquivo; não dependeu de ninguém repassar.**

Membros públicos:

| Membro | Assinatura | Semântica |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Passa direto para `AgentSpec.mcp_servers`. A chave precisa coincidir com o nome do servidor, por isso ele mesmo fornece o par |
| `ask` | `async (question, options=None) -> Ask` | Fica pendurado esperando alguém. **Nunca lança exceção, exceto `CancelledError`** — ninguém responder também é uma resposta; distinga por `ask.state` |
| `pending` | `() -> list[Ask]` | Perguntas atualmente penduradas esperando resposta |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Para UIs em modo pull. Retorna `None` no timeout; lança se for cancelado |
| `answer` | `(ask_id, text) -> bool` | Responde. `False` = esta pergunta já não está mais esperando (timeout / já respondida) |
| `decline` | `(ask_id, reason="") -> bool` | Pula, deixando o modelo decidir sozinho e escrever a suposição em «未知与假设» |
| `send` | `(text) -> Mail \| None` | A pessoa fala por iniciativa própria, vai para a caixa de entrada. Não interrompe o agent; chama `amend()` internamente |
| `amend` | `(text, *, label="运行中补充") -> bool` | Anexa a `amend_path`. Retorna se realmente escreveu (sem caminho configurado / texto vazio / `OSError` dão `False`) |
| `pending_mail` | `() -> list[Mail]` | Falas ainda não retiradas |
| `remaining` | `-> int` | Quantas perguntas ainda cabem. Com `max_asks=None` retorna **`-1`**, não 0 |
| `transcript` | `() -> str` | O markdown do registro de perguntas e respostas |
| `asks` / `mail` / `ui_errors` | `list` | Todas as perguntas / tudo o que a pessoa disse / exceções lançadas pelos callbacks da UI |

`answer`, `decline` e `send` **podem ser chamados de qualquer thread**. A thread de tratamento de requisições de um back-end Web e a thread de entrada de uma TUI estão em outras threads — isso é o normal, não um caso de borda. Internamente usa `loop.call_soon_threadsafe`, porque `asyncio.Future.set_result` não é thread-safe.

Push e pull: **escolha um**.

| | Como obter | Adequado para |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, recebendo `kind == "ask"` com `payload["state"] == "asked"` | UIs orientadas a evento (push Web, redesenho de TUI) |
| **Pull** | `await channel.next_ask()` | Uma task de entrada independente |

Os três significados de "0 / None" são todos diferentes; confundi-los resulta em travamento sem supervisão ou em nunca perguntar nada:

| Escrita | Significado |
|---|---|
| `max_asks=None` | Sem limite de vezes (padrão) |
| `max_asks=0` | Proibido perguntar, recusa direto |
| `timeout_s=None` | Espera para sempre |
| `timeout_s<=0` | Não espera, a pergunta falha imediatamente |
| `remaining` retorna `-1` | O valor quando `max_asks=None`, não 0 |

### Interrupção: qualquer thread pode mandar parar {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`; string vazia interrompe sem dizer nada. Três propriedades:

- **Continua na mesma sessão** (`resume`), não recomeça do zero — o trabalho já feito e o contexto continuam lá. Reaproveita o caminho já existente de retry por queda de rede, apenas trocando o "motivo da falha" por "uma pessoa interrompeu" e o `resume_prompt` pelo que a pessoa disse.
- **Não consome `max_attempts`.** Aquela cota é para falhas, não para pessoas.
- **É cooperativa**: corta numa fronteira de mensagem, não cancela a task à força. O custo é o atraso até a próxima mensagem (se um subagent estiver rodando, é preciso esperá-lo voltar); o ganho é não rasgar o estado no meio do caminho.

E o custo, dito como é: a interrupção faz o **subagent em voo perder o trabalho pela metade** (medido naquela queda de rede em HT001, ver [issue #2](https://github.com/ChenyuHeee/flower/issues/2)). A implementação de referência do terminal escreve isso no aviso, para a pessoa saber antes de apertar; a sua UI deveria fazer o mesmo.

Se você não quer interromper, apenas acrescentar um requisito, use a caixa de entrada (`ch.send(...)`) — ela não interrompe nada, e o atraso é até o próximo checkpoint do agent.

### Oracle: perguntar algo sem atrapalhar a run {#旁路顾问问一句而不打扰运行}

Para saber "onde estamos agora" não é preciso interromper, e não se deve perguntar ao coordenador: essa troca de perguntas **ocupa permanentemente o contexto da main thread** (que guarda decisões, não registros de perguntas e respostas) e ainda o obriga a largar o que está fazendo. Numa run de dez horas, três perguntas casuais já pagam os dois custos.

O [oracle](../reference/glossary.md#旁路顾问) é um desvio somente leitura. Suas ferramentas são apenas `Read` / `Glob` / `Grep`, com o workbench aberto e freios por padrão: `max_turns=12`, `max_budget_usd=0.5`. No terminal, uma linha começando com `?` o dispara, e ele responde com base em duas coisas: a janela recente de eventos (fixa em 60 itens) e o brief, o objetivo, as notas e os artefatos dentro do workbench.
Ele usa um `Runtime` independente (`<run_dir>/aside`), então custo e [linhagem](../reference/glossary.md#血缘) de sessão **não se misturam ao manifest principal** — aquele manifesto registra "quais passos esta run executou", e uma pergunta casual não é um passo.

Na prática, duas perguntas custaram $0.5190 no total, e o manifest da run principal não cresceu um único byte.

### Duas regras rígidas {#两条硬规矩}

!!! warning "on_event não pode bloquear nem deixar exceções escaparem"
    **Um: `on_event` é uma função síncrona, chamada na thread do event loop.** Portanto `asyncio.Queue.put_nowait()` é seguro, `await` não é (ela não é corrotina), e **bloqueá-la é bloquear a run inteira**. Se precisar fazer algo lento, jogue numa fila e deixe outra task fazer.

    **Dois: lançar exceção dentro de `on_event` machuca a própria run.** Os eventos de texto são emitidos dentro do bloco `try` de `Runtime._attempt`, e a exceção é registrada como `result.error` — o passo é dado como falho; os eventos `retry` são emitidos fora desse bloco, e a exceção sobe direto por `Runtime.run`. O front-end não deve levar junto três horas de trabalho: **envolva tudo num try seu**.

    Exceção: os eventos `ask` emitidos pelo próprio `HumanChannel` já estão envolvidos; as exceções vão para `channel.ui_errors` e não interrompem a run.

## Quando não usar isto {#什么时候不该用它}

### O que não fazer na camada de interação {#交互层里不该做的事}

| Não faça | Por quê | Faça assim |
|---|---|---|
| `from claude_agent_sdk import ...` | Se a camada de interação depender de tipos do SDK, a cada atualização do SDK o front-end muda junto, e a camada perde o sentido | Use apenas `kind` / `text` / `tool` / `payload` do `Event` |
| Ler `ev.raw` | Idem acima, e além disso ele não é serializável em JSON | Faltando algum detalhe, acrescente-o ao `payload` em `normalize()`; não contorne a fronteira |
| `await`, requisição de rede ou escrita lenta em disco dentro de `on_event` | Ela é síncrona e chamada na thread do event loop; bloqueá-la é bloquear a run inteira | `put_nowait()` numa fila e consuma em outra task |
| Deixar `on_event` lançar exceção | A exceção em eventos de texto vira `result.error` e o passo é dado como falho | Envolva o corpo do callback inteiro num `try` |
| Usar `disallowed_tools` para desligar as perguntas | É **em nível de sessão** e desabilita junto a ferramenta homônima nos subagents (erro medido, no original: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` ou `timeout_s=0` |
| Remover `mcp__human__ask` de `allowed_tools` achando que isso proíbe perguntas | `allowed_tools` não é exclusivo; é uma lista de dispensa de aprovação, não uma whitelist; com um `channel` ligado, as duas ferramentas vão juntas | Idem acima |
| Montar o caminho na mão para achar `需求.md` / `目标.md` | O workbench pode estar em dois lugares; errar o caminho não gera erro, apenas falha em silêncio | `wake_state()` ou `wf.workbench` |
| Montar progresso e resultado a partir do fluxo de `Event` | O texto é quebrado em vários pedaços por handoff e retry | `on_step(step, result)` entrega o `StepResult` completo |
| Usar `timeout_s=None` sem supervisão | Ninguém responde, a run fica pendurada para sempre, sem erro e sem timeout | `0`, ou um número finito de segundos |

### Quando não é preciso trocar nada {#什么时候根本不用换}

- **Você só quer mudar as cores, imprimir uma linha a mais ou a menos** — basta alterar a função de renderização. Reescrever do zero a interrupção, o oracle, os recibos da caixa de entrada, o resgate em SIGHUP / SIGTERM e a espera pelo encerramento do desvio antes de sair, tudo isso presente na implementação de referência do terminal, custa caro.
- **Você só quer rodar um passo, sem interação** — use `flower once`. Ele não passa pelo caminho dirigido por interação, e portanto já não tem interrupção por Ctrl+C, thread de resposta pela entrada padrão, oracle nem resgate por sinal.
- **O que você quer trocar é o workflow, não a UI** — veja [projetar workflows](workflow.md). A camada de interação só decide quem observa e quem responde; quem decide quantos passos rodar, como julgar e quando sair mais cedo é o `Workflow`.
- **O que você quer trocar é o session store, o modelo ou o orçamento** — nenhum dos três está nesta fronteira; veja a [referência da API Python](../reference/api.md).
