# Handoff

Quando o contexto está quase cheio, deixe **a própria sessão atual** escrever um
[documento de handoff](../reference/glossary.md#交接书) que uma pessoa consegue ler e editar,
e então abra uma nova sessão para assumir. Sem compact. O processo inteiro fica visível no
terminal, o documento cai no disco e você pode editá-lo a qualquer momento — a sessão que
assume lê exatamente esse arquivo.

!!! note "Handoff não é continuidade"
    [Handoff](../reference/glossary.md#换代) troca de [sessão](../reference/glossary.md#会话)
    **dentro de uma mesma run**; [continuidade](../reference/glossary.md#接续) retoma a
    [run](../reference/glossary.md#运行) anterior **entre processos**, veja
    [Continuidade](continuity.md).

    Os dois se encaixam automaticamente, sem fiação extra: a
    [linhagem](../reference/glossary.md#血缘) registra o `session_id` **final** daquele passo,
    e esse é justamente o sucessor — então o próximo wake retoma o sucessor, não a geração
    que foi queimada.

## Que problema resolve

O auto-compact que vem com o SDK dispara na **janela −33k** (medido na prática: com janela
`200000` o limiar é `167000`; o algoritmo de compactação está dentro do binário do harness e não
dá para mudar, só dá para mudar se ele dispara ou não), e o que ele faz é **resumir o histórico
em um parágrafo**. Isso está torto em relação a todo o resto do framework:

| | Quando decide | O que deixa |
|---|---|---|
| `spill_guard` | No instante em que a ferramenta retorna | Resultado grande vai para [spill](../reference/glossary.md#落盘), sobra uma linha de caminho no contexto |
| Artefatos congelados (brief / objetivo) | Ao fim daquele passo | Um documento; o passo seguinte só lê ele |
| **auto-compact** | **Só olha para trás quando o contexto encheu** | **Um resumo escrito pelo próprio modelo** |

O que o flower faz do início ao fim é **decidir na hora o que deve ficar**.
[Compact](../reference/glossary.md#压缩) é o único ponto de "remendo posterior", e o produto dele
tem quatro defeitos:

- **É gerado pelo modelo** — o que entra no resumo depende do julgamento do modelo naquele
  momento, você não participa
- **Não é legível** — foi escrito para o modelo da rodada seguinte, não para uma pessoa
- **Não é editável** — está dentro do harness, não existe arquivo nenhum para você abrir
- **Você não sabe o que se perdeu** — nem vê o que sumiu, nem consegue dizer "esse aí não
  perca" antes de perder

O handoff traz isso de volta para a mesma prática: **mais um artefato congelado**, do mesmo
formato do brief e do objetivo — estruturado, no disco, **você abre, muda uma linha e manda
continuar**. E é exatamente assim que este próprio projeto trabalha — o `HANDOFF.md` na raiz do
repositório é a mesma coisa, escrita por uma pessoa.

## Como usar (código mínimo)

A linha de comando já vem com handoff por padrão:

```bash
flower                       # handoff ligado por padrão
flower --window 200000       # só precisa passar se a detecção errar (padrão: 1 milhão)
flower --no-handoff          # desliga — volta para o auto-compact do SDK
```

Escrevendo código, o handoff é controlado por `Runtime(handoff=…)`, com padrão `True`:

```python
from flower import HandoffPolicy, Runtime

# Padrão: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# Janela explícita (é o que mais precisa de ajuste ao trocar de gateway ou de modelo)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # desliga, volta para o auto-compact
```

`Runtime.__init__` é inteiramente keyword-only e `workspace` é obrigatório. `handoff` aceita uma
instância de `HandoffPolicy` ou um `bool`; passar `bool` equivale a `HandoffPolicy(enabled=…)`.

!!! warning "Handoff ligado = auto-compact forçadamente desligado"
    `Runtime(handoff=True)` é o **valor padrão**, e ele faz o seguinte ao montar cada tentativa:
    se `handoff.enabled` e `spec.compact is None`, a spec é trocada por
    `CompactPolicy(mode="no_summary")` — ou seja, injeta **`DISABLE_AUTO_COMPACT=1`** no
    subprocesso.

    A razão é que, com os dois mecanismos rodando juntos, fica impossível dizer quem causou
    determinada queda de contexto. O preço é **não haver rede de segurança**: quando a rodada que
    escreve o handoff falha, não dá para parar nem para fingir que está tudo bem e aguentar até o
    limite duro — por isso é obrigatório existir um caminho de degradação (veja abaixo).

    Para manter o auto-compact como rede, é preciso passar **explicitamente**
    `AgentSpec(compact=CompactPolicy(mode="auto"))` — se a spec já traz um valor, ele é
    respeitado e não é sobrescrito. Note que isso **vence em silêncio** as premissas do lado do
    handoff.

## O que ele faz de fato

### Quando dispara: dois caminhos para o handoff

**Um: o nível de água chega ao limiar.** O critério é `_handoff_due`: `handoff.enabled`, **não
estar na rodada que escreve o handoff**, `_ctx >= handoff.at` e este passo já ter obtido um
`session_id`. `_ctx` é o tamanho de contexto que a **main thread** viu de fato na última rodada —
só a [main thread](../reference/glossary.md#主线程) conta; o contexto de um
[subagent](../reference/glossary.md#subagent) é assunto do transcript dele, some quando ele
termina, e não deve forçar a main thread a trocar de geração.

Em `warn_at` sai um aviso de aproximação, uma vez por geração, sem poluir a tela.

**Dois: a API responde diretamente "não cabe".** Veja a seção sobre `is_overflow` abaixo.

Nenhum dos dois caminhos é **limitado por `max_attempts`**, e nenhum **consome cota de retentativa**
(internamente `attempt -= 1`) — handoff não é falha.

### O documento de handoff: cinco seções, só duas obrigatórias

Cada seção bloqueia um tipo de erro que quem assume vai cometer:

| Seção | Campo | O que evita |
|---|---|---|
| O que está sendo feito agora | `doing` **obrigatório** | Não saber onde se está |
| O que já foi decidido | `decided` | Rediscutir o que já foi decidido (precisa vir com o **porquê**) |
| Caminhos sem saída | `deadends` | **A seção mais cara** — veja abaixo |
| Próximo passo | `next` **obrigatório** | Gastar meia hora só para decidir o que fazer |
| Cena | `scene` | **Caminhos** dos arquivos-chave e das saídas. Ponteiros, não conteúdo |

`Handoff.missing()` só verifica as duas de `REQUIRED = ("doing", "next")`; `complete()` é a
negação disso. **Exigir "caminhos sem saída" não vazio força invenção** — no começo da tarefa ela
deve mesmo estar vazia. E o veredito de `complete()` tem consequência: faltando uma seção
obrigatória, o handoff inteiro é **substituído por um artefato degradado montado mecanicamente**
(veja abaixo), o que é bem pior do que um handoff verdadeiro com uma seção a menos. Por isso as
outras três são opcionais — ajudam quando escritas, mas não bloqueiam o handoff quando ausentes.

Em `to_markdown()` as seções vazias viram `(空)`; o cabeçalho de `prompt_block()` diz
explicitamente a quem assume "você está assumindo", para que não volte pedindo contexto a alguém.
O campo `step` só aparece no cabeçalho do documento e não participa do parsing.

#### Por que "caminhos sem saída" é a seção mais cara

Porque é **o que custa mais caro para quem assume redescobrir**, e é justamente o que quem escreve
mais esquece.

O worker tem viés sistemático de otimismo (o [goal guard](goal.md) argumenta exatamente a mesma
coisa): ele escreve o que conseguiu fazer e esquece de escrever o que tentou e não funcionou. E é
o segundo que é caro de verdade — em [HT002](../cases/ht002.md) foi uma hora dando voltas em um
problema de compilação; se a conclusão dessa hora não tivesse sido escrita, quem assumisse daria
exatamente as mesmas voltas.

Por isso o `HANDOFF_PROMPT` tem um parágrafo dedicado a esse ponto, com o custo medido junto.

### Como aparece

```text
# 上下文 130.0K/200K · 还有约 20K 到换代

# 上下文 152.0K/200K —— 写交接准备换代
  - 现在在做  在给 Makefile 加 macOS 垫片头,让 sigemptyset 宏不再展开成语法错误。
  - 已定的事  不改业务源码 —— 用户明确说过边界,所以走 Makefile 生成 shim 这条路。
  - 走不通的  -D_ANSI_SOURCE 会把别的宏一起关掉;改 include 顺序无效。
  - 下一步    在干净 clone 上跑一次 make 验证 shim 成立。
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 152.0K 重新开始
```

**Totalmente automático, não para para esperar você** — uma run long-horizon não deveria travar
porque a pessoa foi almoçar.

O evento é `Event("handoff")`, e `payload["phase"]` tem **três** valores: `near` (aproximando),
`writing` (escrevendo — escrever o handoff leva uns dez e tantos segundos, e sem esse evento a
interface parece travada) e `done` (troca concluída). O payload de `done` traz ainda `context`,
`window`, `degraded`, `path` e `sections`.

### Como o limiar é calculado

```python
at      = max(10_000, window - headroom)   # linha de handoff, com piso de 10k
warn_at = max(1_000, at - 20_000)          # linha do aviso de aproximação
```

O piso de 10k em `at` é obrigatório — abaixo disso nem o handoff consegue ser escrito.

O diagrama de escala abaixo usa `--window 200000` como exemplo; a **janela padrão é 1 milhão**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       提醒  换代          硬上限
```

Quando `window` não é informado, `default_window()` decide pela **string do nome do modelo**,
olhando só para as variáveis de ambiente `ANTHROPIC_MODEL` e `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Nome do modelo | Detectado como |
|---|---|
| Contém a palavra isolada `1m` | `1_000_000` |
| Contém `haiku` | `200_000` |
| Todo o resto, **e também quando nenhuma das duas variáveis está definida** | `1_000_000` |

Atenção à ordem: `1m` casa primeiro, então `claude-haiku[1m]` é detectado como 1 milhão, não como
200 mil.

Por que `headroom` é `50_000`: o auto-compact dispara na janela −33k e o handoff precisa chegar
antes dele; além disso, "escrever o handoff" ainda gasta uma rodada. 50k atende as duas coisas ao
mesmo tempo.

**`--window` é o botão mais importante ao trocar de modelo ou de gateway.** Do lado do SDK não há
como obter o tamanho real da janela, só dá para adivinhar pelo nome. Janela real maior → handoff
cedo demais (desperdício, mas não quebra); menor → não dá tempo, e aí é obrigatório ajustar. Vale
mencionar uma medição: o gateway desta máquina de desenvolvimento está configurado com
`claude-opus-5[1m]`. Calculando com 200 mil, haveria uma troca de geração a cada 150 mil, quando
na verdade ele vai até 950 mil — **5 vezes de diferença**, o que picota qualquer trabalho
long-horizon.

Com `flower -v` dá para ver, antes de começar, qual configuração de credencial está em vigor
(endpoint, nome do modelo, token mascarado com só os 4 primeiros caracteres).

### `is_overflow`: transformar erro duro em handoff na hora

Essa é a premissa que permite **ter coragem de deixar `default_window()` em 1 milhão por padrão**.

Se a janela foi superestimada, o limiar nunca é alcançado e o auto-compact está desligado — aí a
batida é direto na API. `is_overflow(*texts)` reconhece esse sinal: `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, entre outros.

Uma vez reconhecido, segue-se **o mesmo caminho de handoff**, só que o documento desta geração
será necessariamente degradado — aquela sessão já não consegue rodar "mais uma rodada para
escrever o handoff", então usa-se direto o artefato montado mecanicamente, troca-se de sessão
normalmente e o trabalho continua: **este passo não falha**.

Assim o custo de superestimar a janela cai de "este passo falha" para "o handoff desta geração é
degradado".

`is_overflow` é uma **função de módulo**, não um método de `Handoff`, e recebe argumentos
variádicos.

### Quando o handoff não consegue ser escrito: degradação, não parada

A rodada que escreve o handoff também pode falhar — rede caiu, modelo surtou, o parsing veio sem
uma seção obrigatória. Como o auto-compact já está desligado, **não há rede**: parar aqui é bater
na janela.

O que se faz: montar mecanicamente um **handoff incompleto** com o que se tem em mãos, marcar
`doing` com `[降级:交接没写成]` (constante `DEGRADED`), enfiar em `scene` os primeiros **1200**
caracteres do prompt original, e trocar de geração assim mesmo. Quem assume é informado
explicitamente de que o que recebeu está incompleto e de que deve ir olhar a cena por conta
própria. Ao mesmo tempo, `StepResult.errors` ganha uma entrada "交接降级(…)" e o motivo fica
consultável em `manifest.json`.

A função correspondente é `degraded(step, prompt, *, why="")`, também de módulo;
`Handoff.degraded` é uma property somente-leitura que verifica se aquela marca está em `doing`.

> **Um handoff incompleto é muito melhor do que bater na janela.**

A rodada que escreve o handoff tem ainda dois arranjos deliberados: roda com
`max_budget_usd=None` — **o handoff tem que sair, não pode travar no budget**; e `on_event=None` —
essa rodada não atualiza a UI.

### Uma mina: a rodada que escreve o handoff precisa ser isenta do limiar

Ela roda **depois da linha ter sido cruzada** — nesse momento o nível de água já está acima do
limiar por definição. Sem a isenção, a primeira mensagem da rodada de handoff julga de novo "está
na hora de trocar de geração", e ela é interrompida sem ter escrito uma única palavra: **toda
geração produz artefato degradado**, e tudo parece normal (o caminho de degradação funciona muito
bem).

Levei essa na prática: na primeira execução real de `tests/handoff_live.py`, **os dois handoffs
foram versões degradadas**. Os testes offline não pegaram — lá o `_attempt` inteiro era
substituído, e o fake não passava por esse critério. Agora o critério foi extraído para
`Runtime._handoff_due()` e é verificado diretamente offline.

### Um freio contra disparada

`max_generations=8`.

!!! danger "`window` pequeno demais gera handoffs infinitos queimando dinheiro"
    O perigo é: **limiar abaixo do piso de partida daquele papel** (no
    [coordenador](../reference/glossary.md#协调者) medi cerca de 34k, só o system prompt mais o
    índice do [workbench](../reference/glossary.md#工作台) já consomem isso), e então toda sessão
    nova cruza a linha já na primeira frase → escreve handoff, troca de geração, cruza de novo,
    **para sempre**. E como handoff não consome cota de retentativa — o que é intencional — o
    único freio é `max_generations=8`.

    Uma run longa normal não chega a 8 gerações; se chegou, quase certamente o `window` está
    pequeno demais — a mensagem de erro ao atingir o limite diz isso mesmo ("o limiar provavelmente
    está abaixo do piso de partida deste papel; aumente window, ou use `--no-handoff`").

### O processo completo de um handoff

```text
trabalho (sessão A)
  |  contexto da main thread cruza o limiar   <- só a main thread conta. O contexto de um subagent
  |                                             é assunto do transcript dele, some ao terminar, e
  |                                             não deve forçar a sessão principal a trocar
  |- corta na fronteira de mensagem           <- mesma ideia do Ctrl-C: cortar limpo, sem rasgar o estado
  |                                             (mesmo preço: subagents em voo se perdem. Os 50k de
  |                                             folga existem para isso)
  |- mais uma rodada na mesma sessão: escrever o handoff
  |     por que é ela mesma que escreve — só ela tem aquele contexto. Qualquer outro teria que ler
  |     tudo antes, e aí a troca não teria servido para nada
  |- congela em <workbench>/notes/交接-<nome do passo>.md, a geração anterior vai para notes/archive/交接/
  |- nova sessão (resume=None, fork=False), prompt = prompt_block() do documento de handoff
trabalho (sessão B) continua
```

`HANDOFF_PROMPT` é o prompt que faz a sessão atual escrever o handoff; contém os dois
placeholders `{used}` e `{window}`. **Não é um papel novo** — só a sessão atual tem aquele
contexto.

### Handoff não conta como retentativa; como a contabilidade é feita

| Campo | O que acontece no handoff |
|---|---|
| `attempts` | **Não sobe** — ele conta tentativas fracassadas |
| `retired[]` | Os session_id queimados neste passo ficam aqui, **em ordem** |
| `session_id` | Sempre o **último sucessor**, nunca um dos queimados |
| `context` | Tamanho de contexto que a main thread viu de fato na última rodada |
| `cost_usd` / `num_turns` | **Acumulam** entre retentativas e handoffs |

Todos esses campos vão para o `manifest.json`, o que permite reconstruir depois "quantas gerações
este passo queimou e quanto cada uma custou".

### Onde o handoff cai

`<workbench>/notes/交接-<nome do passo sem caracteres inválidos>.md`; a geração anterior, se
existir, é movida para `notes/archive/交接/<nome do passo>-<timestamp>.md`.

**Sem workbench não há spill** — nesse caso `_handoff_path` retorna `None`, o documento continua
sendo entregue a quem assume via prompt e o handoff acontece normalmente, só que **depois não há
arquivo para a pessoa consultar**. Para poder consultar depois, ligue o workbench
(`Runtime(workbench=True)`, ou deixe o [workflow](../reference/glossary.md#流程) montar um).

## Quando não usar

- **Você quer mesmo usar compact.** `flower --no-handoff`, ou `Runtime(handoff=False)`.
  O handoff desliga o auto-compact junto; se esse efeito colateral não interessa, não ligue.
- **Você quer os dois ao mesmo tempo.** Passar explicitamente
  `AgentSpec(compact=CompactPolicy(mode="auto"))` preserva o auto-compact, mas depois disso não dá
  mais para dizer quem causou determinada queda de contexto, e a investigação fica mais difícil.
  Confie no handoff ou confie no compact, não nos dois.
- **Tarefas curtas, trabalho de uma rodada.** O handoff nunca vai disparar e configurá-lo não faz
  sentido — mas lembre que `Runtime` com `handoff=True` (padrão) ainda assim desliga o
  auto-compact.
- **Sem workbench, mas esperando ler o handoff depois.** Ligue o workbench antes; caso contrário o
  documento só existiu dentro do contexto daquela run.
- **Começar uma run longa antes de acertar `window`.** Se a janela real for menor que o padrão, as
  primeiras gerações produzirão só artefatos degradados — e artefato degradado é exatamente o tipo
  de handoff mais inútil. Acerte com `--window` primeiro, ou rode algo curto e olhe o nome do
  modelo em `-v`.
- **Tratar handoff como toda a governança de contexto.** Ele é a última linha. As camadas que
  cortam na hora (spill, [trim](../reference/glossary.md#裁剪),
  [prune](../reference/glossary.md#剪除)) são mais baratas, veja
  [Economia de contexto](context.md).

## Botões

| Sintoma | Qual girar |
|---|---|
| Handoff frequente demais, trabalho sempre interrompido | Ajuste `--window` para a janela real do modelo (`-v` mostra o nome do modelo em vigor) |
| Handoff logo na abertura, com aviso de "piso de partida" | Mesma coisa, `window` pequeno demais |
| Handoff sempre degradado | Veja `errors` em `runs/manifest.json`, o motivo da degradação está lá |
| Quem assume refaz sempre o trabalho da geração anterior | A seção "caminhos sem saída" está fina demais. Dá para editar o arquivo direto |
| Quer ler o handoff depois e não acha o arquivo | Workbench desligado. O handoff não caiu no disco, só passou pelo prompt |
| Quer mesmo é usar compact | `--no-handoff` |

## Relacionados

- [Continuidade](continuity.md) — retomar a run anterior entre processos; é a mesma coisa desta
  página vista do outro lado
- [Economia de contexto](context.md) — as camadas que cortam na hora
- [Goal guard](goal.md) — o argumento do "worker tem viés sistemático de otimismo"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Linha de comando](../reference/cli.md) — `--window`, `--no-handoff`
- Código-fonte: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
