# Clarify

Antes de pôr a mão na massa, deixe os requisitos claros. O [clarifier](../reference/glossary.md#确认者)
é um papel que só pergunta e não executa nada: pergunta até ficar claro e, no fim, emite um
[brief](../reference/glossary.md#需求确认书) com exatamente quatro seções, congelado em disco.
Cada [passo](../reference/glossary.md#步骤) seguinte abre lendo esse documento, sem adivinhar os
requisitos de novo — e aquele diálogo **nunca entrou** no contexto a jusante.

## Que problema isso resolve {#解决什么问题}

Os mecanismos de limpeza de contexto do flower limpam sempre **material de trabalho**: expiração por
tempo de vida, remoção de chamadas negadas, remoção de mensagens de erro, spill de resultados
grandes. Perder material de trabalho não é grave — basta rodar de novo que ele reaparece.

Existe uma classe de erro que não é assim: **entender o objetivo errado**. É a única classe de erro
que **piora quando o contexto é limpo**. Depois que o material de trabalho é jogado fora, o que fica
é justamente aquela decisão construída sobre uma premissa errada — e ela parece exatamente igual a
uma decisão correta. Não sobra nenhum rastro indicando que a premissa é suspeita.

Execuções long-horizon amplificam isso até o pior caso: a premissa errada roda por horas, despacha
uma dúzia de [subagents](../reference/glossary.md#subagent), deixa uma pilha de artefatos em disco —
e só então aparece. Nesse ponto o caro não são os tokens, é que **cada artefato foi construído sobre
o requisito errado**. As contas de [HT001](../cases/ht001.md) medem essa proporção: o passo de
confirmar os requisitos custou **$0.3704 / 5 turnos / 0.06h**, e o passo de execução seguinte
**$171.2476 / 31 turnos / 10.44h**.

Por isso é preciso um canal capaz de "parar e perguntar" — e ele tem de vir **antes** de começar o
trabalho.

## Como usar (código mínimo) {#怎么用最小代码}

### Zero código: linha de comando {#零代码命令行}

Entre no diretório do projeto e rode:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

No terminal você verá perguntas assim:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Digite o **número** para escolher uma opção, ou responda escrevendo direto
- **Enter = pular** a pergunta; ele decide sozinho e registra a suposição na seção
  「未知与假设」 (incógnitas e suposições)
- Só passa com as quatro seções completas; o brief é congelado em `.flower/notes/需求.md`
- **Rodar de novo não repete o interrogatório** — para reconfirmar, apague aquele arquivo ou use
  `--new`

Se você só quer ver o que ele pergunta, sem seguir para a execução: `flower --clarify-only`. Para dar
um teto rígido de perguntas: `--asks 12` (só com esse valor aparece uma linha extra abaixo das
opções, `(还能问 N 次)`; por padrão não há limite e essa linha não aparece). Sem ninguém de plantão:
`--timeout 0`. A implementação desse caminho está em
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "As respostas vêm da entrada padrão: rode num terminal de verdade"
    Em pipes, `nohup` ou CI não há quem responda: assim que o stdin lê EOF, a pergunta pendente
    naquele momento é tratada como "entrada fechada" e pulada, e cada pergunta seguinte fica esperando
    o `--timeout` inteiro. Nesses cenários passe `--timeout 0` direto — todas as perguntas caem no
    vazio imediatamente, ele decide sozinho e escreve as suposições em 「未知与假设」.

### Fiação manual {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # sem limite de perguntas por padrão; espera 30 minutos por uma pessoa
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

Em `prompt` escreva apenas **o seu** pedido original — uma frase basta. O que perguntar é decisão do
clarifier: quais perguntas cabem no seu domínio o framework não sabe, e nem deveria saber. O
`协调者` acima é um `AgentSpec` que você mesmo constrói com `coordinator()`; veja
[Desenhar um workflow](workflow.md).

Parâmetros de `clarify_step()`:

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `channel` | — | `HumanChannel`. **A mesma instância** também precisa ser pendurada em `Workflow(channel=...)` |
| `brief_path` | — | Onde o brief cai. Tem de estar dentro do [workbench](../reference/glossary.md#工作台) que você pendurou; veja abaixo |
| `prompt` | — | Seu pedido original. `str` ou `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nome do passo, e também a chave no `ctx` |
| `spec` | `None` | Traga seu próprio `AgentSpec`; se dado, `clarify()` não é usado |
| `instructions` | `""` | Instruções de domínio acrescentadas depois de `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = reconfirma toda vez (use ao mudar requisitos) |
| `on_fail` | `"stop"` | Para onde ir quando faltam seções; igual a `Step.on_fail` |
| `retries` | `0` | Quantas vezes repetir quando faltam seções |
| `**spec_kw` | — | Repassado a `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Depois de rodar, o `ctx` tem três coisas:

```python
ctx["确认需求"]     # str, versão compacta das quatro seções (prompt_block), plugável direto no prompt seguinte; chave = nome do passo
ctx[BRIEF_KEY]     # "_brief" —— objeto Brief, use este para pegar seção por seção
ctx[MISSING_KEY]   # "_brief_missing" —— só existe quando faltam seções: quais faltam, para exibir na UI
```

Quando não estiver saindo como você quer, mexa primeiro nestes botões:

| Sintoma | O que ajustar |
|---|---|
| Pergunta demais, em migalhas | Dê um teto rígido em `max_asks`; escreva em `instructions` o que é óbvio no seu domínio |
| Pergunta de menos e já começa | Nomeie em `instructions` quais coisas ele precisa esclarecer (o número já é ilimitado por padrão; mexer no teto não adianta) |
| As quatro seções vêm preenchidas de qualquer jeito | Dê em `instructions` um exemplo do seu próprio domínio |
| Trava sem ninguém de plantão | `timeout_s=0` |
| Quer reconfirmar toda vez | `always_ask=True`, ou apague o arquivo do brief |

## O que ele faz de fato {#它实际做了什么}

### Quando dispara: três pontos de fiação, nenhum campo novo {#触发时机三处接线一个新字段都没加}

O que `clarify_step()` constrói é um `Step` comum, apenas com três callbacks preenchidos:

| Onde conecta | Quando roda | O que faz |
|---|---|---|
| `Step.when` | Antes de entrar no passo | Se o brief já existe e tem as quatro seções, **pula** e injeta o brief no `ctx` |
| `Step.gate` | Depois que o passo roda, antes de entregar o resultado a jusante | Se faltar alguma seção, **não deixa seguir**; se estiver completo, `write()` **congela** |
| `Step.reduce` | Depois de passar | Repassa a jusante **as quatro seções parseadas**, não o texto bruto do modelo |

**Pular também injeta o `ctx`.** É fácil esquecer disso: quando `when` devolve `False`, o `Workflow`
não executa o passo e, naturalmente, não escreve `ctx[step.name]` — por isso `clarify_step` injeta o
brief existente já dentro do `when`. Sem isso, ao rodar de novo o passo a jusante receberia um
`KeyError`.

O `reduce` repassa `Brief.prompt_block()` e não o texto bruto do modelo, porque o texto bruto pode
vir com coisas a mais (na prática, ele cola o código inteiro dentro da resposta).

Na [continuidade](../reference/glossary.md#接续) esse passo abre com outra frase — `CLARIFY_RESUME`:
«接着刚才那次没问完的需求确认继续 —— **不是重新开始**……». Sem essa frase, a continuidade reenvia o
pedido original como se fosse uma tarefa nova, e o clarifier pode repetir perguntas que já fez.

### Fronteira: o diálogo não entra no contexto a jusante {#边界问答不进下游的上下文}

```text
确认需求        sessão isolada  ────→  brief congelado de quatro seções, em disco
                                                │
干活(próximo)   sessão nova (resume_from=None)◄─┘   recebe só as quatro seções
```

O `resume_from` de `clarify_step` fica no padrão `None`, então o passo seguinte é uma **sessão nova**
que recebe apenas o brief. Aquele diálogo **nunca entrou** no contexto do
[coordinator](../reference/glossary.md#协调者) — não é "entrou e depois foi podado". A diferença é
substantiva: o que foi podado continua no `sessions.db` e pode voltar por um resume; o que nunca
entrou não tem esse problema.

O diálogo em si é **acrescentado a `log_path`**. Essa cópia não ocupa contexto, não sofre com compact
e continua lá em outra máquina — mesma ideia do workbench.

### Cada uma das quatro seções barra um tipo de falha {#四段各挡一类失败}

| Seção | O que escrever | O que acontece se faltar |
|---|---|---|
| **目标** (objetivo) | Uma frase: o que fazer e para quem | Sai outra coisa |
| **验收标准** (critérios de aceite) | Condições julgáveis, uma por linha. "Ficar bom" não vale; "rodar `x` imprime `y`" vale | Ninguém consegue julgar que "acabou" |
| **边界** (fronteira) | **Dizer explicitamente o que não será feito** | Escopo se espalha. Essa seção segura **cada um** dos subagents seguintes |
| **未知与假设** (incógnitas e suposições) | O que não foi perguntado, o que caiu por timeout, o que ele chutou — um por linha | **Premissas erradas são enterradas em silêncio** |

A quarta seção é o fusível da execução long-horizon. Se qualquer uma das três primeiras estiver
errada, basta que a suposição esteja escrita explicitamente na quarta para que quem ler depois tenha
chance de barrar; se ficar enterrada, só se descobre horas depois, quando todos os artefatos viram
lixo. Premissa errada não dá para evitar por completo, mas dá para torná-la **explícita**.

Só passa com as quatro seções completas; quais faltam é reportado por `Brief.missing()` — ele devolve
os nomes das seções em chinês, que podem ser exibidos direto.

O parser é bem tolerante quanto à forma: `## 目标` / `**目标**` / `目标:` / `3. 边界` são todos
aceitos; título seguido do corpo na mesma linha (`目标: 做一个 X`) também; apelidos comuns também
(`验收条件`→验收标准, `不做什么`→边界, `未知项与假设`→未知与假设). Se a mesma seção aparecer várias
vezes, vale a primeira com conteúdo. Duas exceções que você precisa saber:

- `Brief.parse()` **primeiro tira os blocos de código cercados**; ao encontrar uma cerca **não
  fechada**, descarta tudo dali para frente. Quando a saída do modelo é truncada, nenhuma das seções
  seguintes é parseada → faltam seções → o `gate` rejeita e manda repetir.
- `Brief.load()` trata `"(未填)"` como vazio. Se ao editar o brief à mão você copiar o texto de
  placeholder de `to_markdown()`, aquela seção continua contando como faltante.

### Fronteira: o que o clarifier pode tocar {#边界确认者能碰什么}

Rodamos um clarifier **sem restrição** (`/tmp/probe_ask.py`, **$0.8908 / 230 s**): ele fez duas
perguntas e **começou a escrever código direto**; barrado pela camada de permissão, **colou o código
inteiro no corpo da resposta**. Escrever "não escreva código" no prompt não impede isso — o system
prompt dele já tinha uma frase assim. Por isso existem dois mecanismos:

**1. Um hook barra as ferramentas de escrita.** A lista de dispensa de aprovação de `clarify()` é
`mcp__human__ask` mais (quando `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`;
sem `Write` / `Edit` / `Bash` / `Agent`. Quem executa isso de fato é o `whitelist_guard` que o
`Runtime` instala automaticamente: a partir da lista de dispensa ele deduz quais entre `Bash` /
`Write` / `Edit` / `NotebookEdit` devem ser barrados e responde `deny` quando batem. Não é "pediram
para ele não começar o trabalho": ele **não consegue** começar.

Dar leitura a ele compensa: uma olhada no repositório economiza várias perguntas, e essa sessão é
descartada depois de usada, então não importa se o contexto ficar sujo (com `can_read=False` dá para
tirar até a leitura).

**Isso tem de ser um hook; não dá para depender só de `allowed_tools`.** Essa segunda é uma **lista
de dispensa de aprovação, não uma whitelist exclusiva** — o modelo continua conseguindo chamar
ferramentas que não estão nela. Duas evidências medidas que continuam valendo:

- Em [HT002](../cases/ht002.md), o [judge](../reference/glossary.md#判定者) do passo "设定目标" rodou
  de fato **11 vezes** o `Bash`, mesmo com `judge()` tendo `can_run=False` por padrão e `Bash` nem
  aparecendo na lista (aquela execução ainda não tinha esse hook — hoje a mesma chamada levaria um
  `deny` do `whitelist_guard` na hora, o que mostra justamente que quem barra é o hook, não a lista).
- **Sonda de $0.1**: um agent com `allowed_tools=["Read"]` recebe a ordem de escrever um arquivo —
  `Write` é recusado pela camada de permissão (`"requested permissions to write ... but you haven't
  granted it yet"`) e `Bash` é recusado pela segurança de caminho (`"Output redirection was blocked.
  For security, Claude Code may only write to files in the allowed working directories"`). **A chamada
  saiu**; quem barrou foram outras camadas.

`clarify()` não define `permission_mode` explicitamente e herda o padrão `"default"` do `AgentSpec`.
`coordinator()` usa `"acceptEdits"` por padrão — quem repassar esse valor para o clarifier perde essa
proteção.

**2. O framework só parseia aquelas quatro seções; o resto é descartado.** `Brief.parse()` primeiro
extrai os blocos de código cercados e só então procura os títulos — mesmo colado, o código não chega
a jusante. Essa é a última comporta contra "ele contaminar o que vem depois".

### Fronteira: o canal de perguntas {#边界提问通道}

A ferramenta de pergunta do lado do modelo se chama `mcp__human__ask` (parâmetro `question`, opcional
`options`). O `HumanChannel` é um servidor MCP in-process e **registra duas ferramentas** —
`mcp__human__ask` e `mcp__human__inbox`; a lista de dispensa de aprovação do clarifier só tem a
primeira (a caixa de entrada é para o coordinator).

```python
HumanChannel(
    on_event=None,        # callback para UI push. Ao pendurar no Workflow, Workflow.run conecta sozinho
    max_asks=None,        # sem limite de perguntas por padrão
    timeout_s=1800.0,     # 30 minutos. None = espera para sempre; <= 0 = totalmente automático
    log_path=None,        # perguntas e respostas acrescentadas a este arquivo, sem ocupar contexto
    amend_path=None,      # o que a pessoa disser durante a execução é acrescentado a este arquivo (normalmente o próprio brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # as três formulações de resposta vazia
)
```

O normal em agents long-horizon é **não ter ninguém olhando**, então "parar e esperar uma pessoa" tem
de falhar de forma elegante:

| Configuração | Comportamento |
|---|---|
| `timeout_s=1800.0` (padrão) | Espera meia hora; no fim devolve uma explicação, **não um erro** |
| `timeout_s=None` | Espera para sempre. Só use quando há alguém de plantão com certeza (a CLI não consegue passar esse valor; `--timeout` é float) |
| `timeout_s=0` (negativos idem) | **Totalmente automático**: toda pergunta cai no vazio na hora, sem fingir que espera |
| `max_asks=None` (padrão) | **Sem limite** — quantas perguntas fazer é decisão do clarifier |
| `max_asks=N` | Teto rígido. Perguntas além disso são **recusadas direto** pela ferramenta, sem bloquear e sem erro |
| `max_asks=0` | Proibido perguntar (CI / sem plantão) |

Com `max_asks=None`, `remaining` devolve `-1` (não 0, nem infinito), e o terminal usa isso para não
mostrar `(还能问 N 次)`.

O texto literal devolvido no timeout é:

> 无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。
> 不要重复提问,也不要停在这里。

As três formas de resposta vazia (timeout / teto esgotado / a pessoa pulou) apontam todas para a
mesma ação: **escrever a suposição na quarta seção**. É por isso que a quarta seção ainda tem conteúdo
quando não há ninguém de plantão, e é por isso que a execução long-horizon consegue seguir em frente.
O teto escrito no prompt é uma sugestão; **contar no canal é a garantia**.

Um fato de mecanismo verificado na prática: dentro de um handler de ferramenta MCP in-process, dar
`await` numa future externa **não causa deadlock** — enquanto o handler está pendurado o event loop
continua girando, e outra task ou **outra thread** consegue preencher a resposta. Por isso `answer()`
/ `decline()` podem ser chamados direto de um backend web ou da thread de entrada da TUI
(internamente via `loop.call_soon_threadsafe`); isso é o caso normal, não a exceção. Exceções lançadas
pelos callbacks de UI são recolhidas em `ui_errors` e **não interrompem a execução** — um front-end
que quebra não deve levar junto três horas de trabalho. A lista completa de membros está na
[API Python](../reference/api.md).

!!! warning "Com `max_turns` pequeno, "perguntar até ficar claro" vira letra morta"
    O `max_turns` de `clarify()` é `None` (sem limite) por padrão. **Cada pergunta consome um turno** —
    colocar 16 equivale a "no máximo uma dúzia de perguntas", e o efeito é **silencioso**: do lado do
    canal, `max_asks=None` continua dizendo "sem limite", e ninguém percebe quem cortou. Para deixar as
    perguntas livres, **os dois padrões precisam continuar em `None`**: `HumanChannel.max_asks` e
    `clarify(max_turns=...)`.

### Onde o brief cai: tem de ser o workbench que você pendurou {#确认书落在哪必须是挂上去的那个工作台}

O índice do workbench é injetado no system prompt, então o coordinator já sabe de saída onde está o
arquivo de requisitos; ao distribuir trabalho basta repassar o caminho, sem copiar o conteúdo para
dentro do [task brief](../reference/glossary.md#任务书).

!!! warning "O índice só chega ao coordinator"
    Subagents têm o próprio system prompt e **não herdam** o trecho de nível de sessão (medido:
    **$0.2461**, `tests/prelude_live.py`). Ou seja, é "o coordinator repassa o caminho", não "cada
    subagent sabe automaticamente".

O que importa é **qual** workbench. Só uma forma está certa: construa você mesmo, pendure no
`Workflow` e deixe o driver entregar o mesmo objeto ao `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← pendurado aqui
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Duas formas erradas, e nenhuma delas **dá erro** — por isso exigem cuidado extra:

```python
# ✗ Montar um caminho na mão: é relativo ao cwd do processo, e o <run_dir>/workbench criado por
#   Runtime(workbench=True) é outro diretório. O brief é escrito em A, o índice injetado varre B —
#   a promessa acima falha em silêncio.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Tentar pegar de volta a partir do Runtime: passando por cli.py isso não é possível. Ele primeiro
#   chama main() para construir o Workflow e só depois cria o Runtime — nessa altura brief_path já
#   está fixado.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Quando você escreve o próprio driver (sem passar por `cli.py`), construa o `Workbench` primeiro e
entregue **o mesmo objeto** a `Workflow(workbench=wb)` e a `Runtime(workbench=wb)`. O item 5 de
`tests/trial_offline.py` afirma diretamente que "o brief aparece dentro de `prompt_block()`", e o item
11 confirma que essa asserção pega a regressão.

### O que foi verificado e o que não foi {#验证状态}

**Tudo verde offline** (`tests/clarify.py`, **52 itens**, sem custo): as cinco semânticas do canal de
perguntas (bloquear esperando resposta / teto esgotado / timeout vazio / pular / responder de outra
thread), o parse das quatro seções (incluindo a amostra com "código colado dentro"), o papel de
`clarify()` **não ter** ferramentas de escrita, e os três pontos de fiação de `clarify_step`.

**Caminho da CLI verificado offline**: brief completo pré-instalado → primeiro passo pulado → canal
conectado automaticamente à thread de entrada padrão → brief injetado no `ctx` → saída limpa.

**Não foi rodado contra a API real.** Aquela sonda de $0.8908 foi uma **requisição real**, mas ela
testava "o que um clarifier sem restrição faz", não este caminho atual.

## Quando não usar {#什么时候不该用它}

**Os requisitos já são um artefato congelado.** Requisitos escritos num arquivo, dados por um sistema
a montante, ou uma reexecução da mesma coisa — não há o que perguntar. Alimente o texto dos requisitos
direto no passo de execução, ou deixe o `clarify_step` lá para que o `when` o pule (com o brief
presente, ele já não pergunta).

**Não há ninguém para perguntar e você não quer que ele chute.** Com `timeout_s=0` toda pergunta cai
no vazio na hora e a quarta seção fica cheia de suposições dele — é o comportamento projetado, mas a
confiabilidade daquele brief passa a ser igual à confiabilidade dessas suposições. Em CI, o mais limpo
é `max_asks=0` (proibido perguntar) e fornecer os requisitos completos de fora.

**Trabalho pequeno e pontual.** O passo de confirmação custa dinheiro: em [HT002](../cases/ht002.md),
para algo como "clonar um repositório, instalar e rodar no macOS", confirmar os requisitos custou
**$0.5306 / 9 turnos / 0.10h**. Quanto menor a tarefa, pior fica essa proporção. O caminho de agent
único do `flower once` não inclui esse passo.

**Ao mudar requisitos, não é hora de reabrir o diálogo.** O brief é um artefato congelado; a partir do
momento em que cai em disco, o arquivo é a fonte de verdade — o certo é **editar aquele arquivo**. Num
diretório já confirmado, `--clarify-only` é uma **operação vazia** (aquele workflow só tem esse passo,
e esse passo é pulado); para reconfirmar, combine com `--new`, ou passe `always_ask=True` na sua
própria fiação.

**Ele não julga "se está pronto".** Isso é outra camada; veja [goal guard](goal.md). Clarify barra "o
que foi construído não é o que se queria"; não barra "disse que terminou, mas não terminou".
