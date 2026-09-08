# Continuidade

Rode `flower` de novo no mesmo diretório e ele continua aquela conversa de onde parou — processo morto por kill, terminal que travou, máquina reiniciada, tanto faz. Você não precisa saber o que é uma session, nem guardar id nenhum. Esta página explica em que isso se apoia, quando falha em silêncio e como deliberadamente não retomar.

!!! note "Continuidade não é handoff"
    [Continuidade](../reference/glossary.md#接续) é **entre processos**: o próximo processo pega de onde parou a [execução](../reference/glossary.md#运行) anterior.
    [Handoff](../reference/glossary.md#换代) é **dentro da mesma execução**: o contexto está quase cheio, a [session](../reference/glossary.md#会话) atual
    escreve um [documento de handoff](../reference/glossary.md#交接书) e uma session nova assume — veja [handoff](handoff.md).

    Os dois se encaixam automaticamente, sem fiação extra: o [lineage](../reference/glossary.md#血缘) sempre registra a **última** session
    que assumiu aquele passo, então o próximo despertar retoma justamente a sucessora.

## Que problema resolve {#解决什么问题}

No disco, na verdade, está tudo. `runs/sessions.db` tem o transcript **completo** de cada session histórica, `需求.md` / `目标.md`
são artefatos congelados, o código está no workspace.

**O que se perde é uma única linha de mapeamento** — "qual passo usou qual session". Antes ela só existia em memória, em `ctx["_sessions"]`,
e sumia assim que o processo saía. Aí o processo novo subia e o [coordenador](../reference/glossary.md#协调者) era um novato amnésico: quem ele já despachou,
quais becos sem saída já testou, por que descartou determinada abordagem — tudo de novo, do zero.

No [HT002](../cases/ht002.md) ele gastou uma hora testando flags de compilação. Troque o processo e aquela hora foi jogada fora.

## Como usar (código mínimo) {#怎么用最小代码}

Na linha de comando não há nada para configurar; o caminho `flower` já vem com continuidade ligada:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # primeira vez
# …terminou, ou você deu Ctrl-C e foi embora, ou a máquina reiniciou

cd ~/proj && flower "顺便支持代码块高亮"          # continua aquela mesma conversa
cd ~/proj && flower                              # não dizer nada = continuar de onde parou
cd ~/proj && flower --new "另一件事"              # desta vez, não retome
```

Quando você escreve seu próprio [workflow](../reference/glossary.md#流程), a continuidade também vem ligada — o padrão de `Workflow.continuous` é
`True`:

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
    print(ctx["_woke"])                  # qual despertar; na primeira execução é 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Execute esse mesmo código uma segunda vez no mesmo diretório: `ctx["_woke"]` vale `2`, e `ctx["_sessions"]["取词"]` é **o mesmo id**
da primeira vez — o passo "取词" retomou aquela session anterior, em vez de abrir uma nova.

!!! tip "Só quer saber se este diretório dá para retomar"
    `wake_state()` é uma sondagem somente-leitura, **não escreve um único byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Retorna `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = o brief existe e tem as quatro seções completas;
    `checks` = quantos itens na lista de verificação; `woke` = quantas vezes já despertou; `steps` = mapeamento de nome de passo para session_id.
    É com isso que a linha de comando decide se o prompt pergunta "o que fazer" ou "continuar de onde parou".

## O que ele faz de fato {#它实际做了什么}

### Os três arquivos que caem no disco {#落在磁盘上的三个文件}

`run_dir` é `./runs` por padrão, **relativo ao diretório de trabalho atual, não ao workspace**.

| Caminho | O que guarda |
|---|---|
| `runs/lineage.json` | Lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. A continuidade depende inteiramente dele |
| `runs/sessions.db` | SQLite, transcript integral. As tabelas são `entries` / `meta` / `summaries`, a chave é `project_key/session_id[/subpath]` — o transcript dos subagents fica separado pelo subpath |
| `runs/manifest.json` | Array JSON, o manifesto de execução **acumulado entre processos**. Uma linha por passo; é o único lugar para achar um session_id depois do fato |

O arquivo de lineage é assim:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Cada linha do `manifest.json` traz todos os campos de `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — mais `duration_s` acrescentado à mão (é uma `@property`, `asdict()` não pega) e
`run` (marca do processo, `YYYYmmdd-HHMMSS-<6 dígitos hex>`).

O nome do passo aparece ali em quatro formatos, e dá para ver de relance como aquele passo terminou: `<步骤名>` (primeira tentativa),
`<步骤名>#retry<N>` (retry comum), `<步骤名>#round<N>` (o veredito reprovou, voltou para continuar),
`<步骤名>·判定#<N>` (a rodada do [juiz](../reference/glossary.md#判定者)).

A gravação é **append, não sobrescrita**: a cada gravação o arquivo é relido e as linhas são deduplicadas pelo campo `run` — as linhas
deste processo são substituídas pelas mais recentes, as dos outros ficam intactas. Por isso rodar vários flower em paralelo no mesmo diretório é seguro.

### `continuous=True` muda a semântica de `resume_from` {#continuoustrue-改变了-resume_from-的语义}

É o ponto que mais passa batido: `Workflow.continuous` é `True` por padrão, e portanto `resume_from=None`
**não significa "session totalmente nova"**.

| Como escrever | Dentro da mesma execução | Entre processos (`continuous=True`) |
|---|---|---|
| `resume_from=None` (padrão) | Session nova, apoiada apenas no contexto passado no prompt | **Pega a session do passo de mesmo nome no lineage e retoma** |
| `resume_from="nome do passo anterior"` | Retoma a mesma session, contexto completo | Idem |
| `resume_from=…, fork=True` | Bifurca, sem contaminar a session original | Idem |

Para que todo processo comece com uma session limpa, escreva explicitamente `Workflow(..., continuous=False)`.

Ao carregar o lineage há ainda uma verificação: cada `(nome do passo, session_id)` lido é conferido com `runtime.has_session(sid)`
para garantir que ainda está no `sessions.db`; só é usado se estiver vivo. A razão é que o arquivo de lineage pode sobreviver ao `sessions.db`,
e retomar uma session inexistente só explode depois que o subprocesso sobe.

!!! warning "O nome do passo é a chave estável entre processos"
    O lineage é indexado por `Step.name`. **Mudar o nome do passo equivale a cortar o lineage** — não dá erro, apenas a próxima execução vira uma session nova.
    Nomes com sufixo (`#retry`, `#round`, `·判定#`) não entram no lineage; `Lineage.remember` sempre usa o nome original.

### Duas invariantes {#两条不变式}

**Um: assim que o session_id chega, grava no disco imediatamente, sem esperar o passo terminar.**

O processo ser morto à força é justamente o cenário a defender. Já levamos esse tombo na prática: em 2026-09-07 o Terminal.app travou duas vezes, o kernel mandou SIGHUP,
e a ação padrão do SIGHUP é terminar direto — o `finally` não roda uma linha sequer. Naquela época o lineage era gravado **na fronteira dos passos**,
então a execução que morreu ainda dentro do primeiro passo tinha `steps` vazio, e a pessoa foi obrigada a responder de novo perguntas que já tinha respondido (veja a issue #6).

Hoje `Runtime.on_session` grava no disco no exato instante em que o id chega — na prática, o mais cedo possível é a primeira mensagem do assistant,
porque a mensagem de sistema de init não traz `session_id` no SDK Python. A gravação escreve primeiro um `.tmp` e depois faz a substituição atômica,
então ser morto no meio não deixa meio arquivo; falha ao gravar em disco (`OSError`) é engolida em silêncio e não derruba a execução.

Esse hook **cobre apenas a chamada `runtime.run`**; antes do gate ele é removido com `try/finally`. O juiz usa o mesmo
`Runtime`, e se o hook ainda estivesse pendurado a session dele seria gravada no lineage do passo de trabalho.

**Dois: se não bater, trate como inexistente, sem erro.**

Três formas de não bater: o caminho do workspace mudou (o diretório foi copiado para outro lugar — o [HT001](../cases/ht001.md) foi copiado de dentro de um contêiner),
a session não está mais no banco (`sessions.db` foi apagado), ou o arquivo de lineage está corrompido. Qualquer uma delas cai silenciosamente de volta para "começar do zero".

O campo `workspace` é a guarda: o `project_key` do SDK é derivado do caminho do workspace (`/`, `_`, `.` viram todos `-`),
e depois que o diretório é copiado o session_id antigo simplesmente não é encontrável na nova localização; então, se o caminho não bate, trata-se como inexistente.

**Continuidade é bônus; a falha dela não deve impedir a pessoa de trabalhar.**

### Processo morto e máquina reiniciada {#进程被杀和机器重启}

O resultado das duas coisas é o mesmo — dá para retomar — mas o percurso é diferente:

| Situação | O que acontece | Próxima execução |
|---|---|---|
| `Ctrl-C` uma vez | Interrupção cooperativa, corta limpo no **limite de mensagem**. Dá para aproveitar e dizer alguma coisa; dentro do mesmo processo retoma a mesma session e continua. A interrupção não conta como tentativa falha, não consome cota de retry | Não envolve continuidade |
| `Ctrl-C` duas vezes | Levanta `KeyboardInterrupt` e sai direto. O encerramento só chega a fechar o store, **o passo em voo não entra no `manifest.json`** | O lineage já tinha sido gravado, dá para retomar |
| `SIGTERM` / `SIGHUP` | O handler chama `rescue()` primeiro, escrevendo também o passo em voo no `manifest.json` (marcado `error="killed-by-signal"`), e só então restaura a ação padrão e sai de verdade | Idem, dá para retomar |
| `SIGKILL`, queda de energia, reboot | Nenhum encerramento | Também dá para retomar — os três arquivos estão no disco, e o lineage foi gravado no instante em que o id chegou |

A única condição: **o mesmo `workspace` e o mesmo `run_dir`**. `run_dir` é relativo ao diretório de trabalho atual,
então chamar `flower` a partir de outro diretório vai procurar um `runs/` diferente, e não retoma.

### O juiz é sempre uma session nova {#判定者永远是新会话}

Isso é **garantido por construção**, não por lembrança.

O juiz não é um `Step` — ele é despachado direto com `rt.run()` dentro do gate de `with_goal`
(veja [guarda de objetivo](goal.md)), nunca passa pelo caminho do lineage. Por isso, em cada rodada e em cada despertar, ele é um par de olhos totalmente novo.

E é exatamente aí que está todo o valor dele: **ele não sabe quantas vezes o executor tentou nem quanto sofreu, e portanto não inventa desculpas por ele.**
Se ele acompanhasse a continuidade, a guarda de objetivo degeneraria em autoauditoria.

A seção 4 de `tests/lineage_offline.py` crava isso.

### A frase dita no despertar precisa cair em três lugares {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` num diretório já usado **não é uma tarefa nova, é mais uma frase dita**.
Ela faz três coisas ao mesmo tempo — se faltar uma, falha em silêncio:

| Onde vai parar | O que acontece se faltar |
|---|---|
| Acrescentada ao `需求.md` (`## 唤醒时追加`) | Não sobrevive à fronteira do passo. O passo seguinte é uma session nova e só lê os artefatos congelados |
| Usada como prompt do passo de trabalho | O coordenador simplesmente não recebe |
| **Dispara a rededução do `目标.md`** | O juiz continua lendo a lista antiga, e **o que foi acrescentado nem entra no veredito** |

O terceiro é o mais fácil de esquecer. O juiz só lê o `目标.md` congelado; o que você acrescentou no meio do caminho ele não vê — sem a rededução, ele julga "atingido" pela lista antiga
e aquilo que você queria não foi verificado de forma alguma. O custo é rodar mais uma definição de objetivo a cada acréscimo ([HT002](../cases/ht002.md) mediu
$0.41 / 3 minutos).

**Despertar sem dizer nada** (só Enter) não acrescenta nem rededuz, e não custa um centavo a mais.

### Morrer dentro do primeiro passo (confirmar requisitos) também retoma {#崩在第一步确认需求之内也能接上}

`clarify_step` traz um `resume_prompt` (a constante `CLARIFY_RESUME`): se morrer no meio da confirmação e você iniciar de novo,
o que se diz ao [clarificador](../reference/glossary.md#确认者) é "continue aquela clarificação de requisitos que ficou pela metade —
não recomece", em vez de reenviar o pedido original como uma tarefa nova. Junto com a invariante "grava assim que o session_id chega",
a execução que morre no primeiro passo, com o `需求.md` ainda não congelado, agora também retoma, sem precisar responder tudo de novo.

Na direção oposta, passos anteriores já congelados são **pulados por inteiro**: com as quatro seções do `需求.md` completas, a confirmação de requisitos é pulada (mas o conteúdo ainda é injetado no ctx),
e com o `目标.md` completo, a definição de objetivo é pulada.

### Ao retomar, a frase enviada não é a mesma {#接续时发的不是同一句话}

Quem cuida disso é `Step.resume_prompt`. O contexto do outro lado **já contém** o brief, o objetivo e até onde se chegou da última vez; reenviar
"faça conforme este requisito: <brief inteiro>" tal e qual é puro ruído, e pior: pode ser lido como "o requisito mudou, releia tudo".

Sem `resume_prompt`, o `prompt` é reaproveitado — alguns passos devem mesmo reenviar o texto completo (ao rededuzir a lista na definição de objetivo,
é justamente o brief completo que ele precisa).

### Uma linha de aviso no despertar {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sem esse aviso, "ele lembra ou não?" fica completamente imperceptível — e é exatamente aí que está todo o valor desta camada. No banner,
`需求已确认` aparece sempre, `目标 N 条` só quando a lista de verificação não está vazia, e `干活上下文 X` exige que se consiga consultar no `sessions.db`
o tamanho de contexto da última rodada daquela session.

**O número do contexto está ali de propósito** — a razão vem na seção "custo", abaixo.

### Resiliência: espera pendurado quando a rede cai, e o erro não entra no contexto retomado {#韧性断网时挂着等而且错误不进接续后的上下文}

[Resiliência](../reference/glossary.md#韧性) e continuidade andam juntas: uma execução de várias horas necessariamente perde a rede alguma vez, e o comportamento padrão é péssimo —
no instante da queda, o harness enfia no transcript uma **mensagem sintética de assistant** (`isApiErrorMessage=true`,
`model="<synthetic>"`), com o corpo "API Error: Can't reach the API server …". Essa mensagem vira a folha da session,
e no resume seguinte é devolvida ao modelo como "a última coisa que eu disse"; o modelo então acha que está discutindo uma falha de rede.

`Resilience` faz três coisas:

**Um: a sonda faz apenas DNS + TCP.** `reachable(host, port, timeout=5.0)` só roda `getaddrinfo` mais um handshake TCP,
**não envia HTTP, não leva credencial, não custa dinheiro**; qualquer exceção conta como inalcançável. Qual endereço sondar é decidido por `endpoint()`, que segue
`ANTHROPIC_BASE_URL`, com padrão `https://api.anthropic.com` e porta padrão `443` (para http, `80`).
**Com um gateway próprio, é obrigatório sondar o gateway** — `api.anthropic.com` estar acessível não diz nada sobre o gateway.

**Dois: separar o que se deve esperar do que se deve interromper.** `classify(text)` retorna `"transient"` / `"fatal"` / `"unknown"`,
e **testa fatal antes de transient** — textos de 401 e afins costumam trazer a palavra "connection", e com a ordem invertida a espera seria eterna.
Padrões: `max_attempts=6` (incluindo a primeira), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 hora), `retry_unknown=True`.
O backoff é `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por um jitter de ±25%.

Se já houver um session_id, ele **retoma em vez de recomeçar**, e o gasto anterior não se perde. Ao retomar, o que se envia é
`Resilience.resume_prompt`: "a rodada anterior foi interrompida no meio e não terminou. Verifique o que já foi gravado no workbench,
continue do ponto de interrupção, não recomece do zero." Ele **deliberadamente não contém nenhum detalhe do erro** — o modelo precisa saber "fui interrompido, continue",
não precisa saber se foi ENOTFOUND ou 503.

**Três: os erros gerados pela tempestade de retries não entram no contexto depois do resume.** Esse é o trabalho do [prune](../reference/glossary.md#剪除).
O session store do `Runtime` é fixado como `PruningSessionStore`, que no `load()` faz três coisas:

- Remove as mensagens sintéticas de erro de API. **No SQLite elas permanecem intactas**, apenas não são devolvidas ao modelo
- Remove chamadas negadas antigas demais, mantendo só as `keep_denials=1` mais recentes
- Substitui o `tool_result` residual de uma interrupção por uma nota neutra "[a rodada anterior foi interrompida aqui, este resultado de ferramenta não foi produzido]", trocando só o corpo, sem remover a entrada

Manter 1 em vez de 0 tem razão: a chamada negada nunca foi executada, o resultado não traz informação, mas ocupa espaço não trivial
(numa medição, 273 caracteres = 93 caracteres de recusa + 180 caracteres do **comando bloqueado original**), e **ela induz ao erro** —
na prática, depois de ler algumas linhas de "não use Bash diretamente", o coordenador deixou de tentar até o `git status` que era liberado, aprendendo desamparo adquirido.
Mas manter a mais recente é útil: evita que o modelo tente repetidamente o mesmo comando bloqueado dentro da mesma rodada.

A remoção tem uma linha vermelha estrutural: o transcript é uma cadeia simples por `parentUuid`; ao remover uma entrada é obrigatório religar os filhos ao ancestral vivo mais próximo,
caso contrário a cadeia se rompe ali e todo o histórico anterior se perde.

O [HT001](../cases/ht001.md) bateu nisso uma vez: linha do tempo da queda de rede 01:52:40 → 01:55:41, e no `manifest.json` aquele passo ficou
`attempts=2` / `resumed=True` / `ok=True`; depois de retomado, rodou mais de 8 horas até concluir.

Um último ponto que gera confusão: **`Runtime(trim=False)` não significa "não limpar nada"**. `trim` já é `False` por padrão,
mas ele desliga apenas a camada de **[trim](../reference/glossary.md#裁剪) de resultados grandes de ferramenta**. Remover resíduos de queda de conexão, remover chamadas negadas,
neutralizar resíduos de interrupção e marcar como expirados os resultados de [comandos efêmeros](../reference/glossary.md#一次性命令) — essas quatro continuam acontecendo
(`ephemeral` é `True` por padrão, `keep_denials` é `1` por padrão).

### Custo: o contexto cresce sem parar, e não há fim {#代价上下文会一直涨而且没有尽头}

Esse é o custo inerente da continuidade, não é bug.

O passo "trabalhar" do [HT001](../cases/ht001.md) rodou 10.44 horas seguidas; o contexto da [thread principal](../reference/glossary.md#主线程)
foi **28.7K** na rodada 1, **35.2K** na rodada 20, **108.6K** na rodada 35, **158.2K** na rodada 50 e **185.9K** na rodada 70,
crescendo monotonicamente, com inclinação de cerca de **2.2K/rodada**; nunca houve compact, e usou **18.6%** da janela de 1M. Extrapolando por essa inclinação,
a parede vem por volta da rodada **440** — o teto de "long-horizon" na forma atual é cerca de **6 vezes** aquela execução. Continuidade perpétua significa que um dia se bate na janela.

Dois mecanismos cuidam disso:

1. **Trim** (`flower --no-trim` desliga; no caminho `flower` vem ligado) — no resume, troca resultados grandes e antigos de ferramenta por
   ponteiros de arquivo; o conteúdo não se perde, só não fica residente
2. **[Handoff](handoff.md)** — ao atingir o limiar, escreve um documento de transição e troca por uma session nova. **Não é [compact](../reference/glossary.md#压缩)**:
   o documento é legível e editável, você vê o que se perdeu. Por isso o contexto cai periodicamente, em vez de subir até bater na parede

**Por isso a linha do despertar precisa mostrar o número do contexto**: se a pessoa vê, ela tem a chance de decidir recomeçar antes da parede.

De quebra: `--rounds` (total de rodadas de trabalho) **é zerado a cada despertar**. Isso é proposital — um novo despertar é uma nova intenção,
e não deve herdar as rodadas já consumidas.

### Recomeçar com outra coisa {#重开一件事}

```bash
flower --new "另一件事"
```

Ou digitar `/new` direto no prompt de despertar:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Arquiva, não apaga.** `lineage.json`, `需求.md` e `目标.md` são **movidos juntos** para `notes/archive/<YYYYmmdd-HHMMSS>/`,
e ao mesmo tempo `steps` e `woke` do lineage são zerados. Os três são três faces do mesmo histórico; recolher só parte deles deixaria um estado pela metade,
tipo "o objetivo ainda está aqui, mas a conversa sumiu".

O `sessions.db` não é tocado — ele é o arquivo morto, e cada transcript lá dentro continua consultável.

No código, isso corresponde a `Lineage.archive(into, extra=[...])`.

## Quando não usar {#什么时候不该用它}

- **Cenários que exigem um ponto de partida limpo toda vez.** Rodar o mesmo workflow em lote, fazer avaliação comparativa, reproduzir um bug para outra pessoa —
  nada disso deve carregar o contexto anterior. Escreva `Workflow(..., continuous=False)`, ou troque de `run_dir` a cada execução.
- **O diretório vai ser movido, copiado, ou o `run_dir` não é persistente.** Rodar em contêiner com o `runs/` num sistema de arquivos interno do contêiner,
  ou fazer rsync do workspace para outra máquina — a continuidade **falha em silêncio** (a guarda de caminho rejeita o lineage que não bate);
  não trate isso como garantia.
- **Esta é uma intenção nova e o contexto já está grande.** A continuidade carrega junto todo o histórico irrelevante, e você paga token por ele a cada rodada.
  Em vez de aguentar, use `--new` para arquivar e recomeçar.
- **Agente único, de uma vez só.** `flower once` não passa por `Workflow`, não tem lineage; para retomar, você mesmo precisa passar `--resume <session_id>`.
- **Usar continuidade como backup.** Ela só registra "qual passo usou qual session". Código, artefatos e decisões devem cair no workspace e no
  [workbench](../reference/glossary.md#工作台), e não se deve contar em desenterrá-los do transcript.

## O que ler em seguida {#相关}

- [Handoff](handoff.md) — o que fazer quando o contexto enche dentro da mesma execução; é a mesma coisa desta página, na outra direção
- [Guarda de objetivo](goal.md) — por que o juiz não retoma
- [Economia de contexto](context.md) — do que cuidam trim, prune e spill, cada um
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Linha de comando](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Código-fonte: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
