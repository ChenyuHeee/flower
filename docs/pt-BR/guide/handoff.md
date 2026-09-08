# Handoff

Quando o contexto está quase cheio, faça com que **a própria sessão atual** escreva um [documento de handoff](../reference/glossary.md#交接书) que uma pessoa consiga ler e editar,
e então abra uma nova sessão para assumir. Sem compact. Todo o processo é visível no terminal, e o documento fica em disco,
editável a qualquer momento — a sessão que assume lê exatamente esse arquivo.

!!! note "Handoff não é continuidade"
    [Handoff](../reference/glossary.md#换代) é trocar de [sessão](../reference/glossary.md#会话) **dentro da mesma run**;
    [continuidade](../reference/glossary.md#接续) é retomar a [run](../reference/glossary.md#运行) anterior **entre processos**,
    veja [Continuidade](continuity.md).

    Os dois se encaixam automaticamente, sem fiação extra: a [linhagem](../reference/glossary.md#血缘) registra o **último**
    `session_id` daquele passo, e esse é justamente o sucessor — então o próximo wake retoma no sucessor, não na geração queimada.

## Que problema resolve {#解决什么问题}

O auto-compact que vem no SDK dispara em **janela −33k** (medido: com janela `200000` o limiar é `167000`;
o algoritmo de compactação está dentro do binário do harness, não dá para alterar, só dá para alterar se dispara ou não), e o que ele faz é **resumir o histórico em um parágrafo**.
Isso vai na contramão do resto deste framework:

| | Quando decide | O que deixa |
|---|---|---|
| `spill_guard` | No instante em que a ferramenta retorna | Resultado grande vai para [spill](../reference/glossary.md#落盘), sobra uma linha de caminho no contexto |
| Artefatos congelados (brief / objetivo) | No fim daquele passo | Um documento; o passo seguinte só lê ele |
| **auto-compact** | **Só olha para trás quando o contexto encheu** | **Um resumo escrito pelo próprio modelo** |

O que o flower faz do começo ao fim é **decidir na hora o que deve ficar**. O [compact](../reference/glossary.md#压缩) é o único ponto de "remediação a posteriori",
e o produto dele tem quatro defeitos:

- **É gerado pelo modelo** — o que entra no resumo depende do julgamento do modelo naquele momento; você não participa
- **É ilegível** — foi escrito para o modelo da rodada seguinte, não para uma pessoa
- **Não é editável** — está dentro do harness, não há arquivo nenhum para você abrir
- **Você não sabe o que se perdeu** — nem enxerga o que foi descartado, nem consegue dizer antes "esse aqui não descarte"

O handoff traz isso de volta para a mesma abordagem: **mais um artefato congelado**, com a mesma forma do brief e do objetivo —
estruturado, gravado em disco, **você abre, edita uma linha e manda continuar**. E é exatamente assim que este próprio projeto opera —
o `HANDOFF.md` na raiz do repositório é a mesma coisa, escrita por uma pessoa.

## Como usar (código mínimo) {#怎么用最小代码}

A linha de comando já vem com handoff por padrão:

```bash
flower                       # já vem com handoff por padrão
flower --window 200000       # só precisa passar se ele errar a estimativa (padrão: 1 milhão)
flower --no-handoff          # desliga — volta ao auto-compact do SDK
```

Escrevendo código, o handoff é controlado por `Runtime(handoff=…)`, com padrão `True`:

```python
from flower import HandoffPolicy, Runtime

# padrão: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# janela explícita (é o que mais se ajusta ao trocar de gateway ou de modelo)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # desliga, volta ao auto-compact
```

`Runtime.__init__` é inteiramente keyword-only, e `workspace` é obrigatório. `handoff` aceita uma instância de `HandoffPolicy` ou
um `bool`; passar `bool` equivale a `HandoffPolicy(enabled=…)`.

!!! warning "Handoff ligado = auto-compact desligado à força"
    `Runtime(handoff=True)` é o **valor padrão**, e ele faz o seguinte ao montar cada tentativa: sempre que
    `handoff.enabled` e `spec.compact is None`, troca a spec por
    `CompactPolicy(mode="no_summary")` — ou seja, injeta **`DISABLE_AUTO_COMPACT=1`** no subprocesso.

    A razão é que, com os dois mecanismos rodando juntos, fica impossível dizer quem causou determinada queda de contexto. O preço é **não haver rede de segurança**:
    quando a rodada que escreve o handoff falha, não dá para parar nem para fingir que está tudo bem e esticar até o teto duro, então é obrigatório ter um caminho degradado (veja abaixo).

    Para manter o auto-compact como último recurso, é preciso passar **explicitamente** `AgentSpec(compact=CompactPolicy(mode="auto"))` —
    se a spec traz o valor, ele é respeitado, não sobrescrito. Note que isso **vence silenciosamente** as premissas do lado do handoff.

## O que ele faz de fato {#它实际做了什么}

### Momento do disparo: dois caminhos para o handoff {#触发时机两条路进换代}

**Um: o nível chega ao limiar.** O critério é `_handoff_due`: `handoff.enabled` e **não estar na rodada que escreve o handoff**
e `_ctx >= handoff.at` e o passo já ter obtido um `session_id`. `_ctx` é o tamanho de contexto que a **main thread**
efetivamente viu na última rodada — só olha a [main thread](../reference/glossary.md#主线程); o contexto de um
[subagent](../reference/glossary.md#subagent) é problema da transcript dele, que se dissolve ao terminar, e não deve forçar handoff na main thread.

Em `warn_at` sai antes um aviso de aproximação, uma vez por geração, sem poluir a tela.

**Dois: a API responde direto "não cabe".** Veja a seção `is_overflow` abaixo.

Os dois caminhos **não são limitados por `max_attempts`** e **não consomem cota de retentativa** (internamente `attempt -= 1`) —
handoff não é falha.

### Documento de handoff: cinco seções, só duas obrigatórias {#交接书五段必填只有两段}

Cada seção barra um tipo de erro que quem assume vai cometer:

| Seção | Campo | O que barra |
|---|---|---|
| O que está sendo feito | `doing` **obrigatório** | Não saber onde se está |
| O que já foi decidido | `decided` | Rediscutir o que já foi decidido (com o **porquê**) |
| Caminhos sem saída | `deadends` | **A seção mais cara** — veja abaixo |
| Próximo passo | `next` **obrigatório** | Gastar meia hora só para decidir o que fazer |
| Cena | `scene` | Os **caminhos** dos arquivos e artefatos-chave. Ponteiros, não conteúdo |

`Handoff.missing()` só verifica as duas de `REQUIRED = ("doing", "next")`, e `complete()` é a negação disso.
**Exigir "caminhos sem saída" não-vazio forçaria invenção** — no começo de uma tarefa essa seção deve mesmo estar vazia.
E o veredicto de `complete()` tem consequência: faltando uma seção obrigatória, o handoff inteiro é **substituído por um artefato degradado montado mecanicamente**
(veja abaixo), o que é muito pior do que um handoff real com uma seção a menos. Por isso as outras três são opcionais — se escritas, ajudam; se não, não impedem o handoff.

Em `to_markdown()` as seções vazias saem como `(空)`; o cabeçalho de `prompt_block()` diz explicitamente a quem assume "você está assumindo",
para que não volte pedindo contexto a alguém. O campo `step` só é usado no cabeçalho do documento, não entra no parsing.

#### Por que "caminhos sem saída" é a seção mais cara {#走不通的路为什么最贵}

Porque é **o que custa mais caro para quem assume redescobrir**, e é justamente o que quem escreve mais esquece.

O worker tem viés sistemático de otimismo (o [goal guard](goal.md) argumenta a mesma coisa): ele escreve o que conseguiu fazer,
e esquece de escrever o que tentou e não deu. E é o segundo que é realmente caro — em [HT002](../cases/ht002.md) foram uma hora de voltas em torno de um problema de compilação;
se a conclusão daquela hora não tivesse sido registrada, quem assumisse daria exatamente as mesmas voltas.

Por isso o `HANDOFF_PROMPT` dedica um parágrafo a esse ponto, incluindo esse custo medido.

### Como é um documento de handoff real {#长什么样}

```text
# Contexto 130.0K/200K · faltam ~20K para o handoff

# Contexto 152.0K/200K —— escrevendo o handoff para trocar de geração
  - Fazendo agora   adicionando um header de shim para macOS no Makefile, para a macro sigemptyset parar de expandir em erro de sintaxe.
  - Já decidido     não mexer no código-fonte de negócio —— o usuário definiu esse limite explicitamente, então gerar o shim pelo Makefile.
  - Sem saída       -D_ANSI_SOURCE desliga outras macros junto; mudar a ordem dos includes não teve efeito.
  - Próximo passo   rodar make em um clone limpo para verificar que o shim funciona.
<- handoff escrito em ~/proj/.flower/notes/交接-干活.md
<- nova sessão assume, contexto recomeça a partir de 152.0K
```

**Totalmente automático, não para para esperar você** — uma run long-horizon não deve travar porque alguém foi almoçar.

O evento é `Event("handoff")`, e `payload["phase"]` tem **três** valores: `near` (aproximação), `writing` (escrevendo — escrever o handoff leva uns dez e poucos segundos, e sem esse evento a interface parece travada) e `done` (troca concluída). O payload de `done` traz ainda
`context`, `window`, `degraded`, `path` e `sections`.

### Como o limiar é calculado {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # linha de handoff, com piso de 10k
warn_at = max(1_000, at - 20_000)          # linha de aviso de aproximação
```

O piso de 10k em `at` é indispensável — abaixo disso não dá nem para escrever o handoff.

A escala abaixo usa `--window 200000` como exemplo; **a janela padrão é 1 milhão**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       aviso handoff      teto duro
```

Quando `window` não é passado, `default_window()` decide pela **string do nome do modelo**, olhando apenas as variáveis de ambiente `ANTHROPIC_MODEL` ou
`ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Nome do modelo | É julgado como |
|---|---|
| Tem a palavra isolada `1m` no nome | `1_000_000` |
| Contém `haiku` no nome | `200_000` |
| Todo o resto, **e também quando nenhuma das duas variáveis está setada** | `1_000_000` |

Atenção à ordem: `1m` casa primeiro, então `claude-haiku[1m]` é julgado como 1 milhão, não 200 mil.

Por que `headroom` é `50_000`: o auto-compact dispara em janela −33k, e o handoff tem que chegar antes dele;
e "escrever o handoff" ainda consome uma rodada. 50k atende às duas coisas ao mesmo tempo.

**`--window` é o botão que mais deve ser ajustado ao trocar de modelo ou de gateway.** Do lado do SDK não há como obter o tamanho real da janela, só dá para adivinhar pelo nome.
Janela real maior → handoff cedo demais (desperdício, sem erro); menor → não dá tempo, e aí é obrigatório ajustar. Vale citar a medição:
o gateway da máquina de desenvolvimento está configurado com `claude-opus-5[1m]`. Calculando por 200 mil, trocaria de geração a cada 150 mil,
quando na verdade ela aguenta até 950 mil — **5x de diferença**, e um trabalho long-horizon acabaria picotado.

Com `flower -v` dá para ver, antes de começar, a configuração de credenciais em vigor (endpoint, nome do modelo, token mascarado deixando só os 4 primeiros caracteres).

### `is_overflow`: transformar erro duro em handoff imediato {#is_overflow把硬错变成当场换代}

Esta é a premissa que permite **ousar deixar 1 milhão como padrão de `default_window()`**.

Se a janela for superestimada, o limiar nunca é alcançado, e o auto-compact está desligado — aí a batida é direto na API.
`is_overflow(*texts)` reconhece esse sinal: `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, e assim por diante.

Reconhecido o sinal, segue-se **o mesmo caminho do handoff**, só que o handoff dessa geração é necessariamente degradado — aquela sessão já não consegue rodar
"mais uma rodada para escrever o handoff", então usa-se direto o artefato degradado montado mecanicamente e troca-se de sessão para continuar, **sem falhar o passo**.

Assim o custo de superestimar cai de "o passo falha" para "o handoff dessa geração é degradado".

`is_overflow` é uma **função de nível de módulo**, não um método de `Handoff`, e recebe argumentos variádicos.

### Quando o handoff não sai: degradar, não parar {#交接写不出来时降级不是停下}

A rodada que escreve o handoff também pode falhar — rede caiu, modelo surtou, o parsing veio sem uma seção obrigatória. Como
o auto-compact já está desligado, **não há rede de segurança**, e parar aqui equivale a bater na janela.

O que se faz: montar mecanicamente um **handoff incompleto** com o que já se sabe, marcar em `doing` o `[降级:交接没写成]`
(constante `DEGRADED`), colocar em `scene` os primeiros **1200** caracteres do prompt original, e trocar de geração normalmente. Quem assume é avisado explicitamente
de que recebeu algo incompleto e de que deve ir olhar a cena por conta própria. Ao mesmo tempo, `StepResult.errors` ganha uma entrada "交接降级(…)",
e o motivo fica consultável em `manifest.json`.

Isso corresponde à função de nível de módulo `degraded(step, prompt, *, why="")`; `Handoff.degraded` é uma property somente-leitura,
que verifica se aquela marca está em `doing`.

> **Um handoff incompleto é muito melhor do que bater na janela.**

A rodada que escreve o handoff tem ainda dois arranjos deliberados: roda com `max_budget_usd=None` — **o handoff tem que sair,
não pode travar no orçamento**; e `on_event=None` — essa rodada não emite para a UI.

### Uma mina: a rodada que escreve o handoff precisa ser isenta do limiar {#一颗地雷写交接那一轮必须豁免阈值}

O handoff é escrito **depois de cruzada a linha** — nesse momento o nível já está acima do limiar por definição. Sem a isenção, a primeira mensagem
da rodada do handoff julga de novo "hora de trocar de geração", e ela é interrompida sem escrever uma palavra, **produzindo artefato degradado em toda geração**,
e com tudo parecendo normal (o caminho degradado funciona muito bem).

Isso já pegou de verdade: na primeira execução real de `tests/handoff_live.py`, **as duas gerações de handoff vieram degradadas**. Os testes offline não pegaram —
lá o `_attempt` inteiro era substituído, e o dublê não rodava esse critério. Agora o critério foi promovido a `Runtime._handoff_due()`,
e o offline o verifica diretamente.

### Uma trava contra disparada {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "`window` configurada pequena demais gera handoff infinito e queima dinheiro"
    O perigo é: **o limiar ficar abaixo do piso de partida daquele papel** (no [coordenador](../reference/glossary.md#协调者), medido em cerca de 34k,
    só o system prompt mais o índice do [workbench](../reference/glossary.md#工作台) já consomem isso); aí cada sessão nova cruza a linha logo na primeira fala
    → escreve handoff, troca de geração, cruza de novo, **sem fim**. E como handoff não consome cota de retentativa — o que é intencional —, a única trava é
    `max_generations=8`.

    Uma run longa normal não chega a 8 gerações; se chegar, é quase certo que `window` está pequena demais — ao atingir o limite, a mensagem de erro diz exatamente isso
    ("o limiar provavelmente está abaixo do piso de partida deste papel; aumente window, ou use `--no-handoff`").

### O processo completo de um handoff {#一次换代的完整过程}

```text
trabalhando (sessão A)
  |  contexto da main thread cruza o limiar   <- só olha a main thread. O contexto do subagent é
  |                                             problema da transcript dele, se dissolve ao terminar,
  |                                             e não deve forçar handoff na sessão principal
  |- corta na fronteira de mensagem          <- mesma lógica de interromper com Ctrl-C: cortar limpo,
  |                                             sem rasgar o estado (mesmo preço: subagents em voo
  |                                             se perdem. A folga de 50k existe para isso)
  |- roda mais uma vez na mesma sessão: escrever o handoff
  |     por que é ela mesma que escreve —— só ela tem aquele contexto. Qualquer outro teria que ler tudo antes, o que anula a troca
  |- congela em <workbench>/notes/交接-<nome-do-passo>.md, e a geração anterior vai para notes/archive/交接/
  |- nova sessão (resume=None, fork=False), prompt = prompt_block() do documento de handoff
trabalhando (sessão B) continua
```

`HANDOFF_PROMPT` é o prompt que faz a sessão atual escrever o handoff, com os dois placeholders `{used}` e `{window}`.
**Não é um papel novo** — só esta sessão tem aquele contexto.

### Handoff não conta como retentativa; como fica a contabilidade {#换代不算重试账怎么记}

| Campo | Como muda no handoff |
|---|---|
| `attempts` | **Não sobe** — ele conta tentativas que falharam |
| `retired[]` | Os session_id queimados neste passo ficam aqui, **em ordem** |
| `session_id` | É sempre **o último sucessor**, não o queimado |
| `context` | Tamanho de contexto que a main thread efetivamente viu na última rodada |
| `cost_usd` / `num_turns` | **Acumulam** ao longo de retentativas e handoffs |

Todos esses campos vão para o `manifest.json`, e depois dá para reconstruir integralmente "quantas gerações este passo queimou e quanto cada uma custou".

### Onde o handoff é gravado {#交接落在哪}

`<workbench>/notes/交接-<nome do passo sem caracteres inválidos>.md`; a geração anterior, se existir, é movida para
`notes/archive/交接/<nome-do-passo>-<timestamp>.md`.

**Sem workbench não há gravação** — nesse caso `_handoff_path` retorna `None`, o documento ainda assim é entregue ao sucessor via prompt
e o handoff acontece normalmente; só que **depois ninguém consegue achar aquele arquivo**. Para poder consultar depois, ligue o workbench
(`Runtime(workbench=True)`, ou deixe o próprio [workflow](../reference/glossary.md#流程) montar um).

## Quando não usar {#什么时候不该用它}

- **Você quer mesmo o compact.** `flower --no-handoff`, ou `Runtime(handoff=False)`.
  O handoff desliga o auto-compact junto; se não quer esse efeito colateral, não ligue.
- **Você quer os dois ao mesmo tempo.** Passar explicitamente `AgentSpec(compact=CompactPolicy(mode="auto"))` preserva o auto-compact,
  mas depois disso fica impossível dizer quem causou determinada queda de contexto, e o diagnóstico piora. Confie no handoff ou confie no compact, não nos dois.
- **Tarefas curtas, de uma rodada só.** O handoff nunca vai disparar, e configurá-lo não faz sentido — mas lembre que o `Runtime` com
  `handoff=True` por padrão continua desligando o auto-compact.
- **Sem workbench e esperando ler o handoff depois.** Ligue o workbench antes, senão o documento só existiu no contexto daquela run.
- **Começar uma run longa com `window` ainda desajustada.** Quando a janela real é menor que o padrão, as primeiras gerações produzem só artefatos degradados,
  e o degradado é justamente o tipo mais inútil de handoff. Acerte com `--window` antes, ou rode algo curto para ver o nome do modelo no `-v`.
- **Tratar o handoff como toda a governança de contexto.** Ele é a última linha. As camadas que cortam na hora
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) são mais baratas,
  veja [Economia de contexto](context.md).

## Sintoma × botão a girar {#旋钮}

| Sintoma | Qual botão |
|---|---|
| Handoff frequente demais, o trabalho vive sendo interrompido | Ajuste `--window` para a janela real do modelo (`-v` mostra o nome do modelo em vigor) |
| Handoff logo na largada, com aviso de "piso de partida" | Idem; `window` está pequena demais |
| Handoff sempre degradado | Veja `errors` em `runs/manifest.json`, o motivo da degradação está lá |
| Quem assume repete o trabalho da geração anterior | A seção "caminhos sem saída" ficou rala. Dá para editar aquele arquivo direto |
| Quer ler o handoff depois e não acha o arquivo | Workbench desligado. O handoff não foi gravado, só passou pelo prompt |
| Só quer usar o compact | `--no-handoff` |

## O que ler em seguida {#相关}

- [Continuidade](continuity.md) — retomar a run anterior entre processos; é a outra direção da mesma coisa desta página
- [Economia de contexto](context.md) — as camadas que cortam na hora
- [Goal guard](goal.md) — o argumento do "worker tem viés sistemático de otimismo"
- [API Python](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Linha de comando](../reference/cli.md) — `--window`, `--no-handoff`
- Código-fonte: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
