# Continuidade

Rode `flower` de novo no mesmo diretório e ele retoma a conversa de onde parou — processo morto,
terminal que travou, máquina reiniciada, tanto faz. Você não precisa conhecer a palavra session,
nem guardar id nenhum. Esta página explica em que isso se apoia, quando falha em silêncio e como
deliberadamente não continuar.

!!! note "Continuidade não é handoff"
    [Continuidade](../reference/glossary.md#接续) é **entre processos**: o próximo processo pega
    onde a [run](../reference/glossary.md#运行) anterior parou.
    [Handoff](../reference/glossary.md#换代) é **dentro da mesma run**: o contexto está quase cheio,
    a [sessão](../reference/glossary.md#会话) atual escreve um
    [documento de handoff](../reference/glossary.md#交接书) e uma sessão nova assume — veja
    [handoff](handoff.md).

    Os dois se encaixam automaticamente, sem fiação extra: a [linhagem](../reference/glossary.md#血缘)
    sempre registra a **última** sessão que assumiu aquele passo, então o próximo wake retoma pela
    sucessora.

## Que problema resolve {#解决什么问题}

Em disco está tudo. `runs/sessions.db` guarda o transcript **completo** de cada sessão histórica,
`需求.md` / `目标.md` são artefatos congelados, o código está no workspace.

**O que se perde é uma única linha de mapeamento** — "qual passo usou qual session". Antes ela só
vivia em memória, em `ctx["_sessions"]`, e sumia quando o processo saía. Aí o processo novo sobe e o
[coordenador](../reference/glossary.md#协调者) é um recém-chegado amnésico: quem já despachou, quais
becos sem saída já tentou, por que rejeitou determinada abordagem — tudo de novo.

No [HT002](../cases/ht002.md) ele gastou uma hora tentando flags de compilação. Troque o processo e
essa hora foi jogada fora.

## Como usar (código mínimo) {#怎么用最小代码}

Na linha de comando não há nada para configurar; o caminho `flower` já vem com continuidade ligada:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # 第一次
# …跑完,或者你按 Ctrl-C 走人,或者机器重启了

cd ~/proj && flower "顺便支持代码块高亮"          # 接着上次那段对话
cd ~/proj && flower                              # 什么都不说 = 接着做
cd ~/proj && flower --new "另一件事"              # 这次别接上次
```

Quando você escreve o seu próprio [workflow](../reference/glossary.md#流程), a continuidade também é o
padrão — `Workflow.continuous` tem valor padrão `True`:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous é True por padrão
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # qual wake é este; na primeira run, 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Execute esse mesmo código uma segunda vez no mesmo diretório: `ctx["_woke"]` vale `2`, e
`ctx["_sessions"]["取词"]` é **o mesmo id** da primeira vez — o passo "取词" retomou a sessão anterior
em vez de abrir uma nova.

!!! tip "Só quero saber se este diretório dá continuidade"
    `wake_state()` é uma sondagem somente leitura, **não escreve um byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Retorna `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = o brief existe e tem as
    quatro seções completas; `checks` = quantos itens tem o checklist de verdict; `woke` = quantos wakes
    já houve; `steps` = mapeamento de nome de passo para session_id.
    É com isso que a linha de comando decide se o prompt pergunta "要做什么" ou "接着上次".

## O que ele faz de fato {#它实际做了什么}

### Os três arquivos que ficam em disco {#落在磁盘上的三个文件}

`run_dir` é `./runs` por padrão, **relativo ao diretório de trabalho atual, não ao workspace**.

| Caminho | O que guarda |
|---|---|
| `runs/lineage.json` | Linhagem: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. A continuidade inteira depende disso |
| `runs/sessions.db` | SQLite, transcript completo. As tabelas são `entries` / `meta` / `summaries`, a chave é `project_key/session_id[/subpath]` — o transcript de subagent fica separado pelo subpath |
| `runs/manifest.json` | Array JSON, o run manifest **acumulado entre processos**. Uma linha por passo; é o único lugar para achar um session_id depois |

O arquivo de linhagem é assim:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Cada linha do `manifest.json` traz todos os campos de `StepResult` — `step`, `session_id`, `ok`,
`cost_usd`, `num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — mais dois adicionados à mão: `duration_s` (é uma `@property`, e `asdict()` não
a captura) e `run` (marcador do processo, `YYYYmmdd-HHMMSS-<6 位 hex>`).

O nome do passo aparece ali em quatro formas, e dá para ver de relance como aquele passo terminou:
`<步骤名>` (primeira tentativa), `<步骤名>#retry<N>` (retry comum), `<步骤名>#round<N>` (o verdict
reprovou e devolveu para continuar), `<步骤名>·判定#<N>` (a rodada do
[judge](../reference/glossary.md#判定者)).

A escrita é **append, não overwrite**: a cada gravação o arquivo é relido e a deduplicação usa o campo
`run` — as linhas deste processo são substituídas pelas mais recentes, as dos outros ficam intactas. Por
isso é seguro rodar vários flower em paralelo no mesmo diretório.

### `continuous=True` muda a semântica de `resume_from` {#continuoustrue-改变了-resume_from-的语义}

Este é o ponto mais fácil de deixar passar: `Workflow.continuous` é `True` por padrão, e portanto
`resume_from=None` **não significa "sessão totalmente nova"**.

| Forma | Dentro da mesma run | Entre processos (`continuous=True`) |
|---|---|---|
| `resume_from=None` (padrão) | Sessão nova, só com o contexto passado no prompt | **Retoma a sessão do passo de mesmo nome na linhagem** |
| `resume_from="上一步名"` | Retoma a mesma sessão, contexto completo | idem |
| `resume_from=…, fork=True` | Faz um fork, sem sujar a sessão original | idem |

Para que cada processo comece com uma sessão limpa, é preciso escrever explicitamente
`Workflow(..., continuous=False)`.

Ao carregar a linhagem ainda há uma verificação: cada `(nome do passo, session_id)` lido é conferido com
`runtime.has_session(sid)` para garantir que ainda está no `sessions.db`; só é usado se estiver vivo. A
razão é que o arquivo de linhagem pode sobreviver ao `sessions.db`, e dar resume numa session inexistente
só explode depois que o subprocesso sobe.

!!! warning "O nome do passo é a chave estável entre processos"
    A linhagem é indexada por `Step.name`. **Mudar o nome do passo equivale a cortar a linhagem** — não dá
    erro, apenas a próxima run vira uma sessão totalmente nova. Nomes com sufixo (`#retry`, `#round`,
    `·判定#`) não entram na linhagem; `Lineage.remember` sempre usa o nome original.

### Duas invariantes {#两条不变式}

**Um: assim que o session_id chega, ele vai para o disco — sem esperar o passo terminar.**

Processo morto na força é exatamente o cenário a evitar. Já custou caro na prática: em 2026-09-07 o
Terminal.app travou duas vezes, o kernel mandou SIGHUP, e a ação padrão do SIGHUP é terminar direto —
o `finally` não executa uma linha sequer. Naquele momento a linhagem era escrita nas **fronteiras de
passo**, então a run que morreu dentro do primeiro passo tinha `steps` vazio e a pessoa foi obrigada a
responder de novo perguntas que já havia respondido (veja a issue #6).

Hoje `Runtime.on_session` grava no instante em que o id chega — na prática o mais cedo possível é a
primeira mensagem assistant, porque a mensagem de sistema de init não traz `session_id` no SDK Python. A
escrita passa por um `.tmp` seguido de substituição atômica, então ser morto no meio não deixa meio
arquivo; falha de escrita (`OSError`) é engolida em silêncio e não derruba a run.

Esse hook **cobre apenas a chamada `runtime.run`**; antes do gate ele é removido com `try/finally`. O
judge usa o mesmo `Runtime`, e se o hook ainda estivesse ligado a session dele seria escrita na linhagem
do passo de trabalho.

**Dois: se não bater, é como se não existisse — sem erro.**

Há três formas de não bater: o caminho do workspace mudou (o diretório foi copiado para outro lugar —
o [HT001](../cases/ht001.md) foi justamente copiado de dentro de um container), a session não está mais
no banco (`sessions.db` foi apagado), o arquivo de linhagem está corrompido. Qualquer uma delas leva
silenciosamente de volta a "começar do zero".

O campo `workspace` é a guarda: o `project_key` do SDK é derivado do caminho do workspace (`/`, `_` e `.`
viram `-`), e depois que o diretório é copiado o session_id antigo simplesmente não é encontrado na nova
posição; então caminho que não bate é tratado como inexistente.

**Continuidade é um bônus; a falha dela não deve impedir ninguém de trabalhar.**

### Processo morto, e máquina reiniciada {#进程被杀和机器重启}

O resultado das duas coisas é o mesmo — dá para continuar — mas o percurso difere:

| Situação | O que acontece | Próxima run |
|---|---|---|
| `Ctrl-C` uma vez | Interrupção cooperativa, corte limpo na **fronteira de mensagem**. Você pode aproveitar e dizer algo; dentro do mesmo processo a mesma sessão é retomada e segue. A interrupção não conta como tentativa falha, não consome cota de retry | Não envolve continuidade |
| `Ctrl-C` duas vezes | Levanta `KeyboardInterrupt` e sai. O encerramento só chega a fechar o store, e **o passo em voo não entra no `manifest.json`** | A linhagem já foi para o disco há tempo; dá para continuar |
| `SIGTERM` / `SIGHUP` | O handler chama `rescue()` primeiro, grava também o passo em voo no `manifest.json` (marcado `error="killed-by-signal"`), depois restaura a ação padrão e sai de verdade | Idem, dá para continuar |
| `SIGKILL`, queda de energia, reboot | Nenhum encerramento | Dá para continuar do mesmo jeito — os três arquivos estão em disco, e a linhagem foi escrita no instante em que o id chegou |

Há uma única premissa: **o mesmo `workspace` e o mesmo `run_dir`**. `run_dir` é relativo ao diretório de
trabalho atual, então chamar `flower` de outro diretório procura outro `runs/` e não continua nada.

### O judge é sempre uma sessão nova {#判定者永远是新会话}

Isso é **garantido por construção**, não por lembrança.

O judge não é um `Step` — ele é despachado direto por `rt.run()` dentro do gate de `with_goal`
(veja [goal guard](goal.md)), e nunca passa pelo caminho da linhagem. Por isso ele é um par de olhos novos
em cada rodada e em cada wake.

E esse é todo o valor dele: **ele não sabe quantas vezes o worker tentou nem o quanto sofreu, e portanto
não inventa desculpas por ele.** Se ele acompanhasse a continuidade, o goal guard degeneraria em
autoauditoria.

A seção 4 de `tests/lineage_offline.py` fixa isso.

### A frase dita no wake precisa cair em três lugares {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` num diretório já usado **não é uma tarefa nova; é mais uma frase dita**.
Ela faz três coisas ao mesmo tempo — falhar em qualquer uma delas causa falha silenciosa:

| Onde cai | O que acontece se faltar |
|---|---|
| É anexada ao `需求.md` (`## 唤醒时追加`) | Não sobrevive à fronteira de passo. O próximo passo é uma session nova que só lê os artefatos congelados |
| Vira o prompt do passo de trabalho | O coordenador simplesmente não recebe |
| **Dispara a rederivação do `目标.md`** | O judge continua lendo o checklist antigo, e **o que foi acrescentado nem entra no verdict** |

O terceiro é o mais fácil de esquecer. O judge só lê o `目标.md` congelado; o que você acrescentou no meio
do caminho ele não vê — sem rederivar, ele julga "atingido" pelo checklist velho, e justamente aquilo que
você queria não foi verificado. O custo é uma execução extra de 设定目标 a cada append (no
[HT002](../cases/ht002.md), medidos $0.41 / 3 minutos).

**Um wake sem dizer nada** (só Enter) não anexa e não rederiva: não custa um centavo a mais.

### Uma queda dentro do primeiro passo (确认需求) também continua {#崩在第一步确认需求之内也能接上}

`clarify_step` traz um `resume_prompt` (a constante `CLARIFY_RESUME`): se a queda ocorreu no meio da
clarificação, ao subir de novo o que se diz ao [clarifier](../reference/glossary.md#确认者) é "continue a
clarificação que ficou pela metade — não recomece", em vez de reenviar o pedido original como se fosse
tarefa nova. Junto com a regra "grava assim que o session_id chega", agora até a run que morreu no
primeiro passo, com o `需求.md` ainda não congelado, dá para continuar sem responder tudo de novo.

Na direção oposta, passos anteriores já congelados são **pulados por inteiro**: com as quatro seções do
`需求.md` completas, 确认需求 é pulado (mas o conteúdo ainda é injetado no ctx); com o `目标.md` completo,
设定目标 é pulado.

### Ao continuar, não é a mesma frase que é enviada {#接续时发的不是同一句话}

Quem cuida disso é `Step.resume_prompt`. O contexto do outro lado **já tem** o brief, o goal e onde parou;
reenviar "faça conforme este brief: <brief inteiro>" é puro ruído e, pior, tende a ser lido como "os
requisitos mudaram, releia tudo".

Sem `resume_prompt`, o `prompt` é reaproveitado — alguns passos realmente devem reenviar o texto completo
(ao rederivar o checklist, 设定目标 quer exatamente o brief inteiro).

### No wake, uma linha de relatório primeiro {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sem esse relatório, "ele lembra ou não?" fica completamente imperceptível — e é exatamente aí que está o
valor desta camada. No banner, `需求已确认` sempre aparece; `目标 N 条` só quando o checklist de verdict
não está vazio; `干活上下文 X` exige conseguir consultar no `sessions.db` o tamanho de contexto da última
rodada daquela sessão.

**Esse número de contexto está exposto de propósito** — o motivo está na seção "Custo", abaixo.

### Resiliência: esperar de pé quando a rede cai, e o erro não entra no contexto retomado {#韧性断网时挂着等而且错误不进接续后的上下文}

[Resiliência](../reference/glossary.md#韧性) e continuidade andam juntas: numa run de várias horas a rede
inevitavelmente cai uma vez, e o comportamento padrão é péssimo — no instante da queda o harness enfia no
transcript uma **mensagem assistant sintética** (`isApiErrorMessage=true`, `model="<synthetic>"`), com o
corpo "API Error: Can't reach the API server …". Essa mensagem vira a folha da sessão, e no resume seguinte
ela é devolvida como "a última coisa que o modelo disse"; o modelo então acha que está discutindo uma falha
de rede.

`Resilience` faz três coisas:

**Um: a sonda faz só DNS + TCP.** `reachable(host, port, timeout=5.0)` roda apenas `getaddrinfo` mais um
handshake TCP, **sem HTTP, sem credencial, sem custo**; qualquer exceção conta como inalcançável. Qual
endereço sondar é decidido por `endpoint()`, que segue o `ANTHROPIC_BASE_URL`, com padrão
`https://api.anthropic.com` e porta padrão `443` (`80` para http).
**Com gateway próprio é obrigatório sondar o gateway** — `api.anthropic.com` respondendo não diz nada sobre
o gateway.

**Dois: separa o que se deve esperar do que se deve interromper.** `classify(text)` devolve
`"transient"` / `"fatal"` / `"unknown"`, **avaliando fatal antes de transient** — textos de 401 e afins
costumam conter a palavra "connection", e com a ordem invertida a espera seria eterna.
Padrões: `max_attempts=6` (incluindo a primeira), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 hora), `retry_unknown=True`.
O backoff é `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por um jitter de ±25%.

Se já houve um session_id, ele **retoma em vez de recomeçar**, e o que já foi gasto não se perde. Na
retomada é enviado o `Resilience.resume_prompt`: "a rodada anterior foi interrompida no meio e não terminou.
Confira o que já foi para o disco no workbench e continue do ponto de interrupção, sem recomeçar do zero."
Ele **deliberadamente não contém nenhum detalhe do erro** — o modelo precisa saber "foi interrompido,
continue", não se foi ENOTFOUND ou 503.

**Três: os erros gerados pela tempestade de retries não entram no contexto pós-resume.** Isso é trabalho da
[poda](../reference/glossary.md#剪除). O session store do `Runtime` é fixo em `PruningSessionStore`, que faz
três coisas no `load()`:

- Remove as mensagens sintéticas de erro de API. **No SQLite ficam preservadas como estão**; só não são
  devolvidas ao modelo
- Remove chamadas negadas antigas demais, mantendo apenas as `keep_denials=1` mais recentes
- Substitui os `tool_result` remanescentes de interrupção por uma nota neutra "[a rodada anterior foi
  interrompida aqui, este resultado de ferramenta não foi produzido]", trocando só o corpo, sem remover a
  entrada

Manter 1 em vez de 0 tem motivo: uma chamada negada nunca foi executada, o resultado não tem informação e
ainda assim ocupa um espaço nada desprezível (medidos 273 caracteres numa ocasião = 93 caracteres de recusa
+ 180 caracteres com **o comando bloqueado na íntegra**), e além disso **ela induz ao erro** — na prática, o
coordenador, depois de ler algumas negativas do tipo "não use Bash diretamente", parou de tentar até o
`git status` liberado, aprendendo desamparo. Mas manter a mais recente é útil: evita que o modelo repita a
mesma chamada bloqueada várias vezes na mesma rodada.

A remoção tem uma linha vermelha estrutural: o transcript é uma cadeia simples de `parentUuid`; ao remover
uma entrada é obrigatório religar seus filhos ao ancestral vivo mais próximo, senão a cadeia arrebenta ali e
todo o histórico anterior se perde.

No [HT001](../cases/ht001.md) isso aconteceu de verdade uma vez: linha do tempo da queda de rede
01:52:40 → 01:55:41, e no `manifest.json` aquele passo ficou com `attempts=2` / `resumed=True` / `ok=True`;
depois da retomada ele ainda rodou mais de 8 horas até concluir.

Um último ponto que gera confusão: **`Runtime(trim=False)` não significa "não limpa nada"**. `trim` já é
`False` por padrão, mas ele só desliga a camada de **[trim](../reference/glossary.md#裁剪) de resultados
grandes de ferramenta**. Remover resíduo de queda de rede, remover chamadas negadas, neutralizar o resto da
interrupção e marcar como expirado o resultado de [comando efêmero](../reference/glossary.md#一次性命令) —
essas quatro continuam acontecendo (`ephemeral` é `True` por padrão, `keep_denials` é `1` por padrão).

### Custo: o contexto só cresce, e não tem fim {#代价上下文会一直涨而且没有尽头}

Este é um custo inerente da continuidade, não um bug.

O passo "干活" do [HT001](../cases/ht001.md) rodou 10.44 horas seguidas; o contexto da
[thread principal](../reference/glossary.md#主线程) foi **28.7K** na rodada 1, **35.2K** na rodada 20,
**108.6K** na rodada 35, **158.2K** na rodada 50 e **185.9K** na rodada 70 — monotonicamente crescente, com
inclinação de cerca de **2.2K/rodada**; sem nenhum compact no percurso, usando **18.6%** da janela de 1M.
Extrapolando por essa inclinação, a parede fica por volta da rodada **440** — o teto de "long-horizon" na
forma atual é cerca de **6 vezes** aquela run. Continuidade permanente significa que um dia se bate na
janela.

Dois mecanismos cuidam disso:

1. **Trim** (`flower --no-trim` desliga; no caminho `flower` vem ligado) — no resume, resultados grandes e
   antigos de ferramenta viram ponteiros de arquivo; o conteúdo não some, só deixa de ser residente
2. **[Handoff](handoff.md)** — ao atingir o limiar, escreve um documento de handoff e troca de sessão.
   **Não é [compact](../reference/glossary.md#压缩)**: o documento é legível e editável, você enxerga o que
   foi perdido. Por isso o contexto cai periodicamente em vez de subir até bater na parede

**É por isso que a linha do wake precisa mostrar o número do contexto**: se a pessoa vê, ela tem chance de
decidir recomeçar antes da parede.

De quebra: `--rounds` (total de rodadas de trabalho) **é reiniciado a cada wake**. Isso é proposital — um
wake novo é uma intenção nova, e não deve herdar as rodadas já consumidas antes.

### Recomeçar com outra coisa {#重开一件事}

```bash
flower --new "另一件事"
```

Ou digite `/new` direto no prompt de wake:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Arquiva, não apaga.** `lineage.json`, `需求.md` e `目标.md` são **movidos juntos** para
`notes/archive/<YYYYmmdd-HHMMSS>/`, e ao mesmo tempo `steps` e `woke` da linhagem são zerados. Os três são
três faces do mesmo trecho de história; recolher só parte deixaria um estado pela metade, do tipo "o goal
ainda está aqui mas a conversa sumiu".

O `sessions.db` não é tocado — ele é o arquivo permanente, e cada transcript ali continua consultável.

No código, isso corresponde a `Lineage.archive(into, extra=[...])`.

## Quando não usar {#什么时候不该用它}

- **Cenários que exigem um ponto de partida limpo toda vez.** Rodar o mesmo workflow em lote, fazer avaliação
  comparativa, reproduzir um bug para outra pessoa — nada disso deve carregar o contexto da vez anterior.
  Escreva `Workflow(..., continuous=False)`, ou use um `run_dir` diferente a cada vez.
- **O diretório vai ser movido ou copiado, ou o `run_dir` não é persistente.** Rodar em container com o
  `runs/` no filesystem interno da imagem, ou dar rsync do workspace para outra máquina — a continuidade
  **falha em silêncio** (a guarda de caminho rejeita a linhagem que não bate); não trate isso como garantia.
- **A intenção agora é nova e o contexto já está grande.** A continuidade carrega junto todo o histórico
  irrelevante, e você paga token por ele em cada rodada. Em vez de aguentar, use `--new`, arquive e recomece.
- **Agente único e descartável.** `flower once` não passa por `Workflow` e não tem linhagem; para retomar é
  preciso passar `--resume <session_id>` na mão.
- **Usar continuidade como backup.** Ela só registra "qual passo usou qual session". Código, entregáveis e
  decisões devem ficar no workspace e no [workbench](../reference/glossary.md#工作台); não conte com escavá-los
  do transcript.

## Relacionados {#相关}

- [Handoff](handoff.md) — o que fazer quando o contexto enche dentro da mesma run; é a mesma coisa desta
  página vista pela outra direção
- [Goal guard](goal.md) — por que o judge não tem continuidade
- [Economia de contexto](context.md) — do que cuidam trim, poda e spill, cada um
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Linha de comando](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Código-fonte: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
