# Trocar a camada de interação

O núcleo do flower não sabe que existe UI. Tudo o que acontece numa execução — o modelo falando, chamando ferramentas, o contexto quase cheio, a necessidade de perguntar algo a uma pessoa — é achatado numa mesma estrutura de dados: [`Event`](../reference/glossary.md#事件).
**A [camada de interação](../reference/glossary.md#交互层) só conhece `Event`, não importa nenhum tipo do SDK.**
Essa é a fronteira que permite trocar a UI sem mexer no núcleo: terminal, Web, serviço HTTP, modo totalmente automático sem supervisão — o que muda é o consumidor de `Event`, e nenhuma outra linha precisa mudar.

## Que problema resolve {#解决什么问题}

O fluxo de mensagens do SDK é de **tipos internos**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage`… Consumi-los diretamente na UI tem duas consequências: qualquer upgrade do SDK obriga o frontend a acompanhar; e como cada mensagem tem um formato diferente, cada UI reescreve do zero a lógica de "isto é texto ou é chamada de ferramenta".

`normalize(message)` converte uma mensagem do SDK em 0 a N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
O custo é uma conversão; o ganho é não haver dependência de tipos entre a camada de interação e o SDK.

Essa fronteira ainda resolve, de passagem, quatro coisas menos óbvias — todas dentro de `normalize()`:

1. **As falas do [subagent](../reference/glossary.md#subagent) ficam marcadas** (`payload["subagent"]`).
   Sem isso, o [task brief](../reference/glossary.md#任务书) despachado e as falas intermediárias do subagent se misturam ao texto da [thread principal](../reference/glossary.md#主线程) e, seguindo o [workflow](../reference/glossary.md#流程), contaminam o prompt do passo seguinte.
2. **A mensagem de erro sintética da queda de conexão é desviada para `kind="error"`.** Quando a conexão cai, o lado do SDK escreve `API Error: …` no transcript como se fosse uma mensagem do assistant, e ela parece fala do modelo (`model` é `"<synthetic>"`).
   Se não for barrada aqui, entra no `StepResult.text` e é passada ao [passo](../reference/glossary.md#步骤) seguinte.
3. **A fronteira de compact é reportada explicitamente** (`kind="reset"`). Depois da fronteira, o modelo só "lembra" do resumo, e o cache de prompt também é rompido ali — uma execução [long-horizon](../reference/glossary.md#长程) precisa poder enxergar isso.
4. **O nível do contexto sai junto com cada mensagem** (`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`). É a única fonte para o critério de [handoff](../reference/glossary.md#换代).

## Como usar (código mínimo) {#怎么用最小代码}

Uma camada de interação precisa conectar três coisas: **a saída de eventos** (para onde renderizar), **o canal de perguntas** (quem responde) e a **interrupção** (como mandar parar).
O trecho abaixo conecta as três e roda direto:

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
    """Busca perguntas em modo pull. Ao trocar para Web / HTTP, esta corrotina é o outro ponto a mudar."""
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

Dois detalhes de encerramento fáceis de esquecer: `rt.close()` sempre no `finally`; e se `ctx["_failed_at"]` tiver valor, a execução parou no meio (`on_fail="stop"`) — não trate como sucesso.

!!! note "Só existe um workbench, não monte outro"
    O [workbench](../reference/glossary.md#工作台) criado por `Runtime(workbench=True)` fica em
    `<run_dir>/workbench`, enquanto `Workbench(ws)` fica, por padrão, em `<ws>/.flower` —
    não são o mesmo diretório. Se o programa que dirige a execução montar o caminho na mão para achar `需求.md`,
    você acaba com "o brief escrito no diretório A e o índice injetado varrendo o diretório B", sem nenhum erro.
    Ou você entrega ao `Runtime` o workbench que o workflow criou (como no código acima),
    ou usa a sondagem somente-leitura `wake_state()` para perguntar onde ele está.

### Três saídas de eventos {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. um único agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. o workflow inteiro, repassado a cada passo
wf = Workflow(steps=[...], channel=ch)                  # 3. o canal de perguntas, ligado à mesma saída
```

A ligação do terceiro caso está em `Workflow.run`: **só é feita automaticamente quando `on_event` não é `None` e `channel.on_event` ainda é `None`**. Se você já ligou o seu, ele não é sobrescrito:

```python
ch = HumanChannel(on_event=my_own_sink)     # ligado por você, o Workflow não mexe
```

`on_step(step, result)` é outro callback, chamado uma vez ao fim de cada passo (**inclusive em falha**), recebendo o `StepResult` completo. Barra de progresso, gravação em disco e alertas ficam aqui; não tente remontar isso a partir do fluxo de `Event` — o texto é quebrado em vários pedaços por handoffs e retries.

### Terminal: o que já vem pronto {#终端默认的那个}

Existe um mesmo sem escrever código. `flower "帮我做一个 X"` passa por
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
que é a **implementação de referência da camada de interação, não parte do framework**, e pode ser trocada inteira; as flags estão na [referência da CLI](../reference/cli.md).

Vamos ser exatos sobre o tamanho. O `cli.py` inteiro tem 1264 linhas, 57KB — mas **não é ele todo que precisa ser trocado**.
O ponto de substituição real é a `class Render` dentro dele (`cli.py:382-578`, 197 linhas), cuja docstring já diz: "Event → terminal. Trocar de UI é trocar esta classe." As outras mil e tantas linhas são interrupção, oracle, recibos de caixa de entrada, resgate por sinal — acessórios **específicos de terminal**, que de qualquer forma não precisam ser copiados ao migrar para Web ou HTTP.

Ou seja, a afirmação "cerca de 200 linhas substituíveis por inteiro" se sustenta — desde que se refira a `Render`, e não a `cli.py`.

Ao escrever sua própria UI de terminal, o ponto crítico é a thread que lê a entrada padrão:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lê a entrada padrão continuamente: se há pergunta pendente, é resposta; senão, vai para a caixa de entrada. Retorna o flag de parada."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # polling, é o que permite responder ao flag de parada
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

- **Use uma thread daemon, não `asyncio.to_thread(input, ...)`.** `input()` não pode ser cancelado enquanto bloqueia, e o `asyncio.run` precisa dar join nas threads do executor padrão antes de sair — o resultado é que, com o trabalho já concluído, você ainda precisa apertar Enter mais uma vez para o programa terminar.
- **Use polling com `select`, não `input()` direto no laço.** Mesmo problema de cancelamento: uma thread bloqueada em `input()` nunca mais acorda com `stop.set()`.
- **Leia sempre, não só quando houver pergunta.** Se você só lê quando há pergunta, tudo o que a pessoa digitou durante as horas de trabalho fica no buffer do terminal e será consumido como resposta na próxima pergunta — a pessoa nem viu a pergunta e ela já foi "respondida".

### Web: fila + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # síncrono, na thread do event loop, não pode bloquear
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # um erro no frontend não deve levar junto três horas de trabalho
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # thread de tratamento da requisição — outra thread, e isso é o normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` é o objeto original do SDK (num evento `ask`, é um `Ask`), **não é serializável em JSON e não deve ir para o frontend** — usar `raw` significa amarrar o frontend de volta aos tipos do SDK, e toda essa camada foi em vão. Os quatro campos `kind` / `text` / `tool` / `payload` bastam.

### HTTP: número de sequência + polling {#http序号--轮询}

Sem conexão persistente, numere os eventos e deixe o cliente buscá-los:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # guarda só os mais recentes, memória não cresce com a duração da execução


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
    return {"ok": ch.answer(ask_id, text)}      # False = esta pergunta já não está esperando
```

Dois limites a reconhecer: quando `maxlen` enche, os mais antigos são descartados, e um cliente que volte com um `after` muito velho não consegue recuperar tudo — o intervalo de polling precisa ser compatível com esse tamanho; e **é obrigatório dar um valor finito a `timeout_s`** — sem ninguém fazendo polling, a pergunta não se encerra sozinha, e `timeout_s=None` deixa a execução inteira pendurada para sempre. O padrão de `1800.0` segundos é adequado.

### Totalmente automático, sem supervisão: não há ninguém {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # eventos todos descartados
```

O equivalente na linha de comando é `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (valores negativos idem) é o modo totalmente automático: a pergunta **não entra na fila de espera e não emite evento `asked`**, é liquidada imediatamente como `state="timeout"`, e a ferramenta devolve este texto fixo —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— e a execução segue normalmente. As perguntas e respostas continuam sendo acrescentadas em `HumanChannel(log_path=...)` (o `starter_flow` liga por padrão em `<工作台>/notes/问答记录.md`), então depois dá para ver o que foi perguntado e que suposições foram adotadas.

Se você não quer que ele abra a boca, use `max_asks=0`: a pergunta é recusada direto (`state="over_budget"`), também sem bloquear.
Note que isso **não é** "tirar a ferramenta" — `allowed_tools` não é exclusivo, e assim que o [coordenador](../reference/glossary.md#协调者) recebe um `channel`, as duas ferramentas `mcp__human__ask` e `mcp__human__inbox` vêm juntas, listadas ou não, e podem ser chamadas. O que realmente barra as perguntas é só a cota e o timeout.

!!! warning "Sem supervisão, nunca deixe uma pergunta esperar para sempre"
    `timeout_s=None` é "espera para sempre". Sem ninguém olhando, uma única pergunta trava no lugar uma execução de dez horas,
    sem erro, sem timeout e sem diferença visível no log. Sem supervisão há apenas dois valores corretos: `0` (fracassa imediatamente)
    ou um número finito de segundos.

## O que ele realmente faz {#它实际做了什么}

### O formato do `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valores, ver tabela abaixo
    text: str = ""
    tool: str = ""                      # só tool_call tem valor
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objeto original do SDK / Ask; tocou nele, amarrou-se ao SDK
```

`str(ev)`: para `tool_call` é `[nome da ferramenta] resumo`, para os demais é `text`; quando `text` está vazio, é `<kind>`.

### Os 15 `EventKind` {#15-个-eventkind}

| `kind` | Quem emite | Quando aparece | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Texto do modelo | O texto | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloco de raciocínio | O raciocínio | Idem acima |
| `prompt` | `normalize()` | **Entrada**: seu prompt, o task brief despachado ao subagent | Texto de entrada | Idem acima |
| `tool_call` | `normalize()` | O modelo inicia uma chamada de ferramenta | Resumo (`file_path` / `command` / `pattern`, cortado em 200 caracteres) | `id`, `input` + idem acima; `tool` é o nome da ferramenta |
| `tool_result` | `normalize()` | Retorno da ferramenta | Primeiros 500 caracteres (vazio quando o conteúdo não é string) | `tool_use_id`, `is_error` + idem acima |
| `result` | `normalize()` | Fim de uma consulta ao SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Mensagem sintética da queda de conexão | Texto do erro | `synthetic: True` |
| `reset` | `normalize()` | Fronteira de compact ou reset de sessão | `压缩(trigger) 167000 → 42000 tokens`; no reset de sessão, `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vazio no reset de sessão) |
| `system` | `normalize()` | Demais mensagens de sistema do SDK | subtype | `data` repassado como está |
| `task` | `normalize()` | Mensagem de progresso de tarefa | Nome da classe da mensagem | — |
| `unknown` | `normalize()` | Tipo de mensagem não reconhecido | Nome da classe | — |
| `ask` | `HumanChannel` | Precisa de resposta humana, uma pergunta chegou a um desfecho, ou a pessoa falou por iniciativa própria | A pergunta / o que a pessoa disse | Duas identidades, ver abaixo |
| `retry` | `Runtime` | Retentando / esperando a rede | Uma linha de explicação | `step`, `attempt` |
| `step` | `Workflow.run` | Fronteira de passo | Nome do passo | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: aproximando / escrevendo / concluído | Uma linha com o nível de contexto | `phase`, `step`, `context`, `window` + ver abaixo |

**Quatro kinds não são produzidos por `normalize()`**: `ask` vem do `HumanChannel`, `retry` e `handoff` vêm do `Runtime`, `step` vem de `Workflow.run`. Colocá-los no mesmo `EventKind` é proposital —
**a UI conhece um único conjunto de `Event`, e não precisa abrir outro caminho para "precisa de resposta humana" ou "fronteira de passo".**

Ao escrever a UI, deixe um ramo `else`. Novos membros serão adicionados a `EventKind`, e uma UI antiga não deve quebrar por causa disso.

### As três phases de `handoff` {#handoff-的三个-phase}

| `phase` | Quando é emitido | Extras no `payload` |
|---|---|---|
| `near` | O nível passou de `warn_at`. **Emitido uma vez por geração**, sem inundar a tela | `at` (limiar de handoff) |
| `writing` | Começou a escrever o [documento de handoff](../reference/glossary.md#交接书). Escrever leva dezenas de segundos; sem este evento a interface parece travada | — |
| `done` | Handoff escrito, nova sessão iniciada | `degraded` (se é a versão degradada), `path` (onde foi escrito; string vazia quando não há workbench), `sections` |

O mecanismo em si está em [handoff](handoff.md).

### As duas identidades de `ask` {#ask-的两种身份}

`Event("ask")` carrega ao mesmo tempo "uma pergunta" e "algo que a pessoa disse por iniciativa própria"; **a UI precisa olhar `payload["kind"]` primeiro**:

| Identidade | Como identificar | `payload` |
|---|---|---|
| Uma pergunta | Não há chave `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` é o `Ask` |
| Fala da pessoa | `payload["kind"] == "mail"` | `kind`, `state` (`queued` ao entrar / `delivered` ao ser retirado), `id`, `amended` (em qual arquivo foi acrescentado; string vazia se não configurado). **Não tem `options` nem `remaining`** |

Uma pergunta emite **dois ou mais** eventos: um ao ser feita (`state="asked"`) e outro no desfecho
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). Basta a UI atualizar a mesma entrada pelo `payload["id"]`.

### Perguntar a uma pessoa: `Ask` e `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # os cinco desfechos acima
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # segundos de espera, uma casa decimal
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` é um servidor MCP in-process mais um conjunto de métodos para a UI. Do lado do modelo, só aparecem duas ferramentas:
`mcp__human__ask` (perguntar, fica pendurado esperando) e `mcp__human__inbox` (checar a caixa de entrada, **não bloqueia**; se estiver vazia, devolve na hora uma frase explicativa). Construtor completo:

```python
HumanChannel(
    *,                                  # tudo keyword-only
    on_event=None,                      # saída em modo push. O Workflow só liga automaticamente se for None
    max_asks=None,                      # None = sem limite; 0 = proibido perguntar. Excedeu, recusa direto, sem bloquear
    timeout_s=1800.0,                   # None = espera para sempre; <= 0 = fracassa imediatamente
    log_path=None,                      # perguntas e respostas são acrescentadas neste arquivo, não ocupam contexto
    amend_path=None,                    # o que a pessoa diz durante a execução é acrescentado neste arquivo, normalmente o brief
    over_budget_text=OVER_BUDGET,       # três respostas fixas, podem ser substituídas pelas suas
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` é o mais fácil de esquecer, e é ele que decide se um requisito alterado no meio do caminho sobrevive à fronteira do passo.
Cada passo é uma nova [sessão](../reference/glossary.md#会话) sobre um snapshot congelado e somente-leitura: o que foi dito durante a execução entrou apenas no contexto daquele agent; o passo seguinte (por exemplo o [veredito](../reference/glossary.md#判定)) é uma sessão totalmente nova, que lê `需求.md` e `目标.md` e **não enxerga o que você disse**, então julga pelas fronteiras antigas e classifica o que foi corrigido como fora de escopo.
`amend_path` **acrescenta** cada mensagem ao [brief](../reference/glossary.md#需求确认书) — acrescenta, não sobrescreve: o requisito original vira histórico, e ver o que mudou é melhor do que não ver. O `starter_flow` liga por padrão em `<工作台>/notes/需求.md`.

Na prática ($0.6767) isso funcionou melhor do que o esperado: a pessoa disse "de passagem, reporte o total de bytes", o coordenador viu na caixa de entrada e reportou —
"hand já leu do complemento em execução em `.flower/notes/需求.md` e calculou, não precisa despachar de novo".
**O subagent leu do arquivo, sem depender de ninguém repassar.**

Membros públicos:

| Membro | Assinatura | Semântica |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Vai direto para `AgentSpec.mcp_servers`. A chave precisa bater com o nome do servidor, por isso é ele que fornece |
| `ask` | `async (question, options=None) -> Ask` | Fica pendurado esperando. **Nunca lança exceção, exceto `CancelledError`** — ninguém responder também é uma resposta; distinga por `ask.state` |
| `pending` | `() -> list[Ask]` | Perguntas atualmente esperando resposta |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Para UI em modo pull. Retorna `None` no timeout; se for cancelada, lança |
| `answer` | `(ask_id, text) -> bool` | Responde. `False` = esta pergunta já não está esperando (timeout / já respondida) |
| `decline` | `(ask_id, reason="") -> bool` | Pula, deixando o modelo decidir sozinho e escrever a suposição na seção「未知与假设」 |
| `send` | `(text) -> Mail \| None` | A pessoa diz algo por iniciativa própria, vai para a caixa de entrada. Não interrompe o agent; internamente chama `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | Acrescenta em `amend_path`. Retorna se realmente escreveu (sem caminho configurado / texto vazio / `OSError` são todos `False`) |
| `pending_mail` | `() -> list[Mail]` | Falas ainda não retiradas |
| `remaining` | `-> int` | Quantas perguntas ainda cabem. Com `max_asks=None` retorna **`-1`**, não 0 |
| `transcript` | `() -> str` | O markdown do registro de perguntas e respostas |
| `asks` / `mail` / `ui_errors` | `list` | Todas as perguntas / tudo que a pessoa disse / exceções lançadas pelo callback da UI |

`answer`, `decline` e `send` **podem ser chamados de qualquer thread**. A thread de tratamento de requisições do backend Web e a thread de entrada da TUI estão em outras threads — isso é o normal, não um caso de borda. Internamente usa-se `loop.call_soon_threadsafe`, porque `asyncio.Future.set_result` não é thread-safe.

Push e pull são duas formas de obter as perguntas; **escolha uma**:

| | Como obter | Adequado a |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, receber `kind == "ask"` com `payload["state"] == "asked"` | UIs orientadas a eventos (push Web, redesenho de TUI) |
| **Pull** | `await channel.next_ask()` | Uma tarefa de entrada independente |

Os três "0 / None" têm semânticas diferentes; confundi-los significa travar a execução sem supervisão ou nunca perguntar nada:

| Forma | Significado |
|---|---|
| `max_asks=None` | Sem limite de vezes (padrão) |
| `max_asks=0` | Proibido perguntar, recusa direto |
| `timeout_s=None` | Espera para sempre |
| `timeout_s<=0` | Não espera, a pergunta fracassa imediatamente |
| `remaining` retorna `-1` | O valor quando `max_asks=None`, não 0 |

### Interrupção: qualquer thread pode mandar parar {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`; string vazia apenas interrompe, sem dizer nada. Três propriedades:

- **Continua na mesma sessão** (`resume`), não recomeça do zero — o que já foi feito e o contexto continuam lá. Reaproveita o caminho já existente do retry por queda de rede, só trocando o "motivo da falha" por "uma pessoa interrompeu" e o `resume_prompt` pela fala da pessoa.
- **Não consome `max_attempts`.** Aquela cota é para falhas, não para pessoas.
- **É cooperativa**: interrompe na fronteira de mensagem, não cancela a tarefa à força. O custo é o atraso até a próxima mensagem (se um subagent estiver rodando, é preciso esperar ele voltar); o ganho é não rasgar o estado no meio do caminho.

Dizendo o custo com honestidade: a interrupção faz o **subagent em voo perder o trabalho pela metade** (medido na queda de rede do HT001, ver [issue #2](https://github.com/ChenyuHeee/flower/issues/2)). A implementação de referência do terminal diz isso explicitamente no prompt, para a pessoa saber antes de apertar; quem escrever a própria UI deve fazer o mesmo.

Se você não quer interromper, só acrescentar um requisito, use a caixa de entrada (`ch.send(...)`) — ela não interrompe nada, e o atraso é até o próximo checkpoint do agent.

### Oracle: perguntar algo sem atrapalhar a execução {#旁路顾问问一句而不打扰运行}

Para saber "onde estamos agora", não é preciso interromper, e não se deve perguntar ao coordenador: essa conversa **ocupa permanentemente o contexto da thread principal** (que guarda decisões, não registro de perguntas e respostas), e ele teria que largar o que está fazendo. Numa execução de dez horas, três perguntinhas casuais já pagam os dois custos.

O [oracle](../reference/glossary.md#旁路顾问) é um desvio somente-leitura. Suas ferramentas são apenas `Read` / `Glob` / `Grep`, com o workbench ligado e travas por padrão: `max_turns=12`, `max_budget_usd=0.5`. No terminal, uma linha começando com `?` o dispara, e ele responde a partir de duas coisas: a janela de eventos recente (fixa em 60 entradas) e o brief, os objetivos, as notas e os artefatos no workbench. Ele usa um `Runtime` independente (`<run_dir>/aside`), então o custo e a [linhagem](../reference/glossary.md#血缘) de sessão **não se misturam ao manifesto principal** — aquele manifesto registra "quais passos esta execução realizou", e uma pergunta casual não é um passo.

Medido na prática: duas perguntas custaram $0.5190 no total, e o manifesto da execução principal não cresceu um byte.

### Duas regras duras {#两条硬规矩}

!!! warning "on_event não pode bloquear nem deixar exceções escaparem"
    **Um: `on_event` é uma função síncrona, chamada na thread do event loop.** Portanto
    `asyncio.Queue.put_nowait()` é seguro, `await` não é (ela não é corrotina), e **bloqueá-la é bloquear a execução inteira**.
    Para trabalho lento, jogue numa fila e deixe outra tarefa fazer.

    **Dois: lançar exceção dentro de `on_event` machuca a própria execução.** Os eventos de texto são emitidos dentro do bloco `try` de `Runtime._attempt`, e a exceção é registrada como `result.error` — o passo é dado como falho; o evento `retry` é emitido fora desse bloco, e a exceção sobe direto por `Runtime.run`. O frontend não deve levar junto três horas de trabalho: **embrulhe tudo num try**.

    Exceção: o evento `ask` emitido pelo próprio `HumanChannel` já está embrulhado; a exceção é recolhida em `channel.ui_errors` e não interrompe a execução.

## Quando não usar {#什么时候不该用它}

### O que não fazer dentro da camada de interação {#交互层里不该做的事}

| Não faça | Por quê | O que fazer |
|---|---|---|
| `from claude_agent_sdk import ...` | Se a camada de interação depender de tipos do SDK, cada upgrade do SDK arrasta o frontend, e a camada perde o sentido | Use apenas `kind` / `text` / `tool` / `payload` do `Event` |
| Ler `ev.raw` | Mesmo motivo, e além disso não é serializável em JSON | Se falta algum detalhe, adicione-o ao `payload` em `normalize()`, não contorne a fronteira |
| `await`, requisições de rede ou escritas lentas dentro de `on_event` | Ela é síncrona e chamada na thread do event loop; bloqueá-la é bloquear a execução inteira | `put_nowait()` numa fila e outra tarefa consome |
| Deixar `on_event` lançar exceção | A exceção num evento de texto vira `result.error`, e o passo é dado como falho | Embrulhe o corpo do callback inteiro num `try` |
| Usar `disallowed_tools` para desligar as perguntas | É **no nível da sessão** e desabilita também a ferramenta homônima nos subagents (erro real medido: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` ou `timeout_s=0` |
| Tirar `mcp__human__ask` de `allowed_tools` achando que isso proíbe perguntar | `allowed_tools` não é exclusivo, é uma lista de dispensa de aprovação e não uma whitelist; com um `channel` ligado, as duas ferramentas vêm juntas | Idem acima |
| Montar caminhos na mão para achar `需求.md` / `目标.md` | O workbench pode estar em dois lugares; errar o caminho não dá erro, apenas falha em silêncio | `wake_state()` ou `wf.workbench` |
| Remontar progresso e resultado a partir do fluxo de `Event` | O texto é quebrado em vários pedaços por handoffs e retries | `on_step(step, result)` entrega o `StepResult` completo |
| Usar `timeout_s=None` sem supervisão | Sem ninguém para responder, a execução fica pendurada para sempre, sem erro e sem timeout | `0`, ou um número finito de segundos |

### Quando simplesmente não é preciso trocar {#什么时候根本不用换}

- **Só quer mudar cores, imprimir uma linha a mais ou a menos** — basta alterar a função de renderização. Reescrever a interrupção, o oracle, os recibos da caixa de entrada, o resgate em SIGHUP / SIGTERM e a espera pelo encerramento do desvio antes de sair custa caro.
- **Só quer rodar um passo, sem interação** — use `flower once`. Ele não passa pelo caminho dirigido por interação, e por definição não tem interrupção por Ctrl+C, thread de resposta pela entrada padrão, oracle nem resgate por sinal.
- **O que você quer trocar é o workflow, não a UI** — veja [Projetar workflows](workflow.md). A camada de interação só decide quem olha e quem responde; quantos passos rodar, como julgar e quando sair mais cedo é decisão do `Workflow`.
- **O que você quer trocar é o session store, o modelo ou o orçamento** — nenhum dos três está nessa fronteira; veja a [referência da API Python](../reference/api.md).
