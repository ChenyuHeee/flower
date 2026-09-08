# Clarificação prévia

Antes de pôr a mão na massa, esclareça o que é preciso fazer. O [clarificador](../reference/glossary.md#确认者) é um papel que só pergunta e não executa nada; pergunta até estar claro e, no fim, emite um [brief](../reference/glossary.md#需求确认书) de exatamente quatro seções, congelado em disco. Cada [passo](../reference/glossary.md#步骤) seguinte abre lendo esse documento e não volta a adivinhar o requisito — e aquele diálogo de perguntas e respostas **nunca entrou** no contexto de quem vem depois.

## Que problema isso resolve {#解决什么问题}

Tudo o que os mecanismos de limpeza de contexto do flower removem é **material de trabalho transitório**: expiração por tempo, remoção de chamadas negadas, remoção de mensagens de erro, [spill](../reference/glossary.md#落盘) de resultados grandes. Perder esse material não é grave: basta reexecutar para tê-lo de volta.

Há uma classe de erro que não funciona assim: **entender o objetivo errado**. É a única classe de erro que **fica pior quando o contexto é limpo**. Depois que o material transitório é descartado, o que sobra é exatamente aquela decisão construída sobre a premissa errada — e ela parece idêntica a uma decisão correta; não há nenhum rastro indicando que sua premissa é suspeita.

O [longo horizonte](../reference/glossary.md#长程) amplifica isso até o pior caso: a premissa errada roda por horas, dispara mais de dez [subagents](../reference/glossary.md#subagent), deixa uma pilha de artefatos em disco, e só então se revela. Nessa altura o caro não são os tokens, é que **cada artefato foi construído em cima do requisito errado**. A conta do [HT001](../cases/ht001.md) mede essa proporção: o passo que confirma o requisito custou **$0.3704 / 5 turnos / 0.06h**; o passo que faz o trabalho custou **$171.2476 / 31 turnos / 10.44h**.

Por isso é preciso um canal capaz de "parar e perguntar" — e ele tem que estar **antes** do início do trabalho.

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

- Digite o **número** para escolher uma opção, ou responda com texto livre
- **Enter = pular** a pergunta: ele decide sozinho e registra a premissa em 「未知与假设」 (Desconhecidos e Premissas)
- Só passa com as quatro seções completas; o brief fica congelado em `.flower/notes/需求.md`
- **Reexecutar não repete o interrogatório** — para reconfirmar, apague esse arquivo ou passe `--new`

Se você só quer ver o que ele pergunta, sem seguir para o trabalho: `flower --clarify-only`. Para dar uma cota rígida de perguntas: `--asks 12` (só com essa opção aparece, sob as alternativas, a linha extra `(还能问 N 次)`; por padrão não há limite e essa linha não aparece). Sem ninguém de plantão: `--timeout 0`. A implementação desse caminho está em [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "As respostas vêm da entrada padrão; rode num terminal de verdade"
    Em pipe, `nohup` ou CI não há ninguém para responder: assim que o stdin chega a EOF, a pergunta pendente naquele momento é tratada como "entrada fechada" e pulada, e todas as perguntas seguintes ficam esperando o `--timeout` inteiro. Nesses casos, passe direto `--timeout 0` — todas as perguntas caem no vazio imediatamente, ele decide sozinho e escreve as premissas em 「未知与假设」.

### Ligando na mão {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # sem limite de perguntas por padrão, espera 30 minutos por alguém
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

No `prompt` você escreve apenas **a sua** demanda original; uma frase basta. O que perguntar é decisão do clarificador — quais perguntas cabem no seu domínio, o framework não sabe e nem deveria saber. O `协调者` acima é um `AgentSpec` que você mesmo cria com `coordinator()`; veja [Desenhar o workflow](workflow.md).

Parâmetros de `clarify_step()`:

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `channel` | — | `HumanChannel`. **A mesma instância** também precisa ser pendurada em `Workflow(channel=...)` |
| `brief_path` | — | Onde o brief é gravado. Tem que estar dentro do [workbench](../reference/glossary.md#工作台) que foi pendurado; veja abaixo |
| `prompt` | — | Sua demanda original. `str` ou `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nome do passo, e também a chave dentro do `ctx` |
| `spec` | `None` | Traga um `AgentSpec` próprio; se fornecido, `clarify()` não é usado |
| `instructions` | `""` | Instruções de domínio anexadas depois de `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = reconfirmar sempre (use ao mudar requisitos) |
| `on_fail` | `"stop"` | Para onde ir quando faltar alguma das quatro seções; igual a `Step.on_fail` |
| `retries` | `0` | Quantas vezes tentar de novo quando faltar seção |
| `**spec_kw` | — | Repassado a `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Ao final, o `ctx` contém três coisas:

```python
ctx["确认需求"]     # str, versão compacta das quatro seções (prompt_block), pronta para entrar no prompt seguinte; chave = nome do passo
ctx[BRIEF_KEY]     # "_brief" —— objeto Brief, use este para pegar seção por seção
ctx[MISSING_KEY]   # "_brief_missing" —— só existe quando falta seção: quais faltam, para exibir na UI
```

Quando não estiver saindo bem, mexa nestes botões primeiro:

| Sintoma | Qual ajustar |
|---|---|
| Pergunta demais, em pedaços miúdos | Dê uma cota rígida em `max_asks`; escreva em `instructions` o que é óbvio no seu domínio |
| Pergunta de menos e já começa | Nomeie em `instructions` as coisas que ele obrigatoriamente precisa esclarecer (o número de perguntas já é ilimitado por padrão; mexer na cota não adianta) |
| Preenche as quatro seções de qualquer jeito | Dê em `instructions` um exemplo do seu próprio domínio |
| Trava sem ninguém de plantão | `timeout_s=0` |
| Quer reconfirmar toda vez | `always_ask=True`, ou apague o arquivo do brief |

## O que ele faz de fato {#它实际做了什么}

### Quando dispara: três pontos de ligação, nenhum campo novo {#触发时机三处接线一个新字段都没加}

O que `clarify_step()` produz é um `Step` comum, só com três callbacks preenchidos:

| Onde liga | Quando roda | O que faz |
|---|---|---|
| `Step.when` | Antes de entrar no passo | Se o brief já existe e tem as quatro seções, **pula** e injeta o conteúdo no `ctx` |
| `Step.gate` | Depois de rodar o passo, antes de entregar o resultado adiante | Se as quatro seções não estiverem completas, **não deixa seguir**; se estiverem, faz `write()` e **congela** |
| `Step.reduce` | Depois de passar | Repassa adiante **as quatro seções já parseadas**, não o texto bruto do modelo |

**Pular também injeta no `ctx`.** É fácil deixar escapar: quando `when` retorna `False`, o `Workflow` não executa o passo e, portanto, não escreve `ctx[step.name]` — então o `clarify_step` injeta o brief existente já dentro do `when`. Sem isso, numa reexecução o passo seguinte receberia um `KeyError`.

O `reduce` repassa `Brief.prompt_block()` e não o texto bruto do modelo, porque o texto bruto pode vir com coisas a mais (na prática, ele cola o código inteiro na resposta).

Na [continuidade](../reference/glossary.md#接续), esse passo abre com outra frase — `CLARIFY_RESUME`: "continue de onde a confirmação de requisitos parou — **não recomece do zero**…". Sem essa frase, a retomada reenvia a demanda original como se fosse uma tarefa nova, e o clarificador pode repetir perguntas já feitas.

### Fronteira: o diálogo não entra no contexto de quem vem depois {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

O `resume_from` do `clarify_step` fica no padrão `None`, então o passo seguinte é uma **sessão nova** e só recebe o brief. Aquele diálogo **nunca entrou** no contexto do [coordenador](../reference/glossary.md#协调者) — não é que "entrou e foi podado". A diferença é substantiva: o que foi podado continua no `sessions.db` e ainda pode voltar por um resume; o que nunca entrou não tem esse problema.

O diálogo em si é **anexado ao `log_path`**. Essa cópia não ocupa contexto, não sofre com compact e sobrevive à troca de máquina — mesma ideia do workbench.

### Cada uma das quatro seções barra um tipo de falha {#四段各挡一类失败}

| Seção | O que escrever | O que acontece se faltar |
|---|---|---|
| **目标** (Objetivo) | Uma frase: o que fazer e para quem | O que sai é outra coisa |
| **验收标准** (Critérios de aceitação) | Condições julgáveis, uma por linha. "Ficar bom" não vale; "rodar `x` e sair `y`" vale | Ninguém consegue julgar se "acabou" |
| **边界** (Fronteiras) | **O que explicitamente não será feito** | Escopo se espalha. Esta seção segura **cada** subagent seguinte |
| **未知与假设** (Desconhecidos e premissas) | O que não foi perguntado, o que caiu no vazio por timeout, o que ele adivinhou — um por linha | **Premissa errada some sem deixar rastro** |

A quarta seção é o fusível da execução de longo horizonte. Se qualquer uma das três primeiras estiver errada, desde que a premissa esteja escrita explicitamente na quarta, quem ler depois tem chance de barrar; se ficar enterrada, só se descobre horas mais tarde, quando todo o artefato virou lixo. Premissa errada não dá para evitar por completo, mas dá para torná-la **explícita**.

Só passa com as quatro seções completas; quais faltam é reportado por `Brief.missing()` — ele retorna os nomes das seções em chinês, prontos para exibir.

O parser é bem tolerante quanto à forma: `## 目标` / `**目标**` / `目标:` / `3. 边界` são todos reconhecidos; texto colado logo depois do título (`目标: 做一个 X`) também; apelidos comuns também (`验收条件`→验收标准, `不做什么`→边界, `未知项与假设`→未知与假设); se a mesma seção aparecer várias vezes, vale a primeira com conteúdo. Há duas exceções que você precisa conhecer:

- `Brief.parse()` **remove primeiro os blocos de código cercados** e, ao encontrar uma cerca **não fechada**, descarta tudo dali para a frente. Quando a saída do modelo é truncada, nenhuma seção posterior é parseada → faltam seções → o `gate` manda refazer.
- `Brief.load()` trata `"(未填)"` como vazio. Se você editar o brief à mão e copiar o texto de placeholder de `to_markdown()`, aquela seção continua contando como ausente.

### Fronteira: o que o clarificador pode tocar {#边界确认者能碰什么}

Já rodamos um clarificador **sem restrição** (`/tmp/probe_ask.py`, **$0.8908 / 230 segundos**): ele fez duas perguntas e **começou a escrever código na hora**; barrado pelas permissões, **colou o código inteiro no corpo da resposta**. Escrever "não escreva código" no prompt não segura isso — o system prompt dele já dizia algo assim. Por isso existem dois mecanismos:

**Um: um hook barra as ferramentas de escrita.** A lista de pré-aprovação de `clarify()` é `mcp__human__ask` mais (quando `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`; não tem `Write` / `Edit` / `Bash` / `Agent`. Quem de fato aplica isso é o `whitelist_guard` que o `Runtime` instala automaticamente: a partir da lista de pré-aprovação ele deduz quais entre `Bash` / `Write` / `Edit` / `NotebookEdit` devem ser barradas e faz `deny` no que casar. Não é "pedido para não trabalhar", é **impossibilidade de trabalhar**.

Dar leitura a ele compensa: uma olhada no repositório economiza várias perguntas, e essa sessão é descartada depois de usada — sujar o contexto lendo não faz diferença (`can_read=False` corta até a leitura).

**Isso tem que ser um hook, não dá para depender só de `allowed_tools`.** Este último é **lista de pré-aprovação, não whitelist exclusiva** — o modelo continua conseguindo chamar ferramentas que não estão nela. Duas evidências medidas que continuam válidas:

- No [HT002](../cases/ht002.md), o [juiz](../reference/glossary.md#判定者) do passo "definir objetivo" rodou **11 vezes `Bash`**, sendo que `judge()` tem `can_run=False` por padrão e `Bash` nem aparece na lista (aquela execução ainda não tinha esse hook — hoje a mesma chamada levaria `deny` do `whitelist_guard` na hora, o que mostra justamente que quem segura é o hook e não a lista).
- **Sonda de $0.1**: deu-se a um agent com `allowed_tools=["Read"]` a tarefa de escrever um arquivo — `Write` foi recusado pela camada de permissão (`"requested permissions to write ... but you haven't granted it yet"`) e `Bash` foi recusado pela segurança de caminhos (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **As chamadas saíram**; quem barrou foram outras camadas.

`clarify()` não define `permission_mode` explicitamente e herda o padrão do `AgentSpec`, `"default"`. O padrão de `coordinator()` é `"acceptEdits"` — quem repassar esse valor ao clarificador perde essa proteção.

**Dois: o framework só parseia aquelas quatro seções e joga fora o resto.** `Brief.parse()` primeiro extrai os blocos de código cercados e depois procura os títulos — o que foi colado não chega adiante. Essa é a última comporta contra "ele contaminar quem vem depois".

### Fronteira: o canal de perguntas {#边界提问通道}

Do lado do modelo, a ferramenta de perguntar se chama `mcp__human__ask` (parâmetro `question`, `options` opcional). O `HumanChannel` é um servidor MCP in-process e **registra duas ferramentas** — `mcp__human__ask` e `mcp__human__inbox`; a lista de pré-aprovação do clarificador só tem a primeira (a caixa de entrada é para o coordenador).

```python
HumanChannel(
    on_event=None,        # callback para UI push. Ao pendurar no Workflow, Workflow.run liga automaticamente
    max_asks=None,        # sem limite de perguntas por padrão
    timeout_s=1800.0,     # 30 minutos. None = espera para sempre; <= 0 = totalmente automático
    log_path=None,        # o diálogo é anexado a este arquivo, sem ocupar contexto
    amend_path=None,      # o que a pessoa disser durante a execução é anexado a este arquivo (normalmente o próprio brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # texto para os três tipos de resposta vazia
)
```

O normal em um agent de longo horizonte é **não ter ninguém olhando**, então "parar e esperar alguém" precisa falhar com elegância:

| Configuração | Comportamento |
|---|---|
| `timeout_s=1800.0` (padrão) | Espera meia hora; no fim retorna uma frase de explicação, **não um erro** |
| `timeout_s=None` | Espera para sempre. Use só quando há certeza de plantão (a CLI não consegue produzir esse valor; `--timeout` é float) |
| `timeout_s=0` (negativo idem) | **Totalmente automático**: todas as perguntas caem no vazio na hora, sem fingir que espera |
| `max_asks=None` (padrão) | **Sem limite** — quantas perguntas fazer é decisão do clarificador |
| `max_asks=N` | Cota rígida. Perguntas além disso são **recusadas direto** pela ferramenta, sem bloquear e sem erro |
| `max_asks=0` | Proibido perguntar (CI / sem plantão) |

Com `max_asks=None`, `remaining` retorna `-1` (não 0, nem infinito), e é por isso que o terminal não mostra "ainda pode perguntar N vezes".

O texto retornado no timeout é:

> Ninguém respondeu. Siga com seu próprio julgamento e escreva esta pergunta e a premissa que você adotou na seção 「未知与假设」. Não repita a pergunta e não pare aqui.

Os três tipos de resposta vazia (timeout / cota esgotada / pessoa pulou ativamente) apontam todos para a mesma ação: **escrever a premissa na quarta seção**. É por isso que a quarta seção continua tendo conteúdo mesmo sem plantão, e é por isso que a execução de longo horizonte consegue seguir. Cota escrita no prompt é sugestão; **contada no canal é garantia**.

Um fato de mecânica já medido: dentro de um handler de ferramenta MCP in-process, dar `await` em uma future externa **não causa deadlock** — enquanto o handler está pendurado, o event loop continua girando, e tanto outra task quanto **outra thread** podem preencher a resposta. Por isso `answer()` / `decline()` podem ser chamados direto de um backend Web ou da thread de input de uma TUI (internamente via `loop.call_soon_threadsafe`); isso é o caso normal, não o caso de borda. Exceções lançadas pelos callbacks de UI são coletadas em `ui_errors` e **não interrompem a execução** — o front-end quebrar não deve levar junto três horas de trabalho. A lista completa de membros está na [API Python](../reference/api.md).

!!! warning "Com `max_turns` baixo, "perguntar até estar claro" vira conversa fiada"
    O `max_turns` de `clarify()` é `None` por padrão (sem limite). **Cada pergunta é um turno** — colocar 16 equivale a "no máximo uma dúzia de perguntas", e o efeito é **silencioso**: do lado do canal, `max_asks=None` continua dizendo "sem limite", e ninguém percebe quem estrangulou. Para liberar as perguntas, **os dois padrões precisam continuar em `None`**: `HumanChannel.max_asks` e `clarify(max_turns=...)`.

### Onde o brief é gravado: tem que ser o workbench que foi pendurado {#确认书落在哪必须是挂上去的那个工作台}

O índice do workbench é injetado no system prompt, então o coordenador já sabe de saída onde está o arquivo de requisitos; ao distribuir trabalho basta passar o caminho adiante, sem copiar o conteúdo para dentro do [brief de tarefa](../reference/glossary.md#任务书).

!!! warning "O índice só chega ao coordenador"
    O subagent tem seu próprio system prompt e **não herda** o trecho de nível de sessão (medido: **$0.2461**, `tests/prelude_live.py`). Ou seja, é "o coordenador repassa o caminho", não "cada subagent sabe automaticamente".

O ponto é **qual** workbench. Só uma forma está certa: criar você mesmo, pendurar no `Workflow` e deixar o driver entregar o mesmo objeto ao `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← pendurado aqui
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Duas formas erradas, e nenhuma delas **dá erro** — por isso exigem atenção redobrada:

```python
# ✗ Montar um caminho na mão: ele é relativo ao cwd do processo, e o <run_dir>/workbench criado por
#   Runtime(workbench=True) é outro diretório. O brief vai para A, o índice injetado varre B —
#   e a promessa acima falha em silêncio.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Tentar pegar de volta a partir do Runtime: pela cli.py isso é impossível. Ela chama main() para
#   construir o Workflow e só depois cria o Runtime — a essa altura brief_path já está fixado.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Ao escrever seu próprio driver (sem passar pela `cli.py`), crie o `Workbench` primeiro e entregue **o mesmo objeto** tanto a `Workflow(workbench=wb)` quanto a `Runtime(workbench=wb)`. O item 5 de `tests/trial_offline.py` afirma diretamente que "o brief aparece dentro de `prompt_block()`"; o item 11 confirma que essa asserção pega a regressão.

### Estado da validação {#验证状态}

**Offline todo verde** (`tests/clarify.py`, **52 itens**, sem custo): as cinco semânticas do canal de perguntas (bloquear esperando resposta / cota esgotada / vazio por timeout / pulado / resposta vinda de outra thread), o parse das quatro seções (incluindo a amostra com "código colado dentro"), o papel de `clarify()` **não ter** ferramentas de escrita, e os três pontos de ligação do `clarify_step`.

**Caminho da CLI validado offline**: brief completo pré-carregado → primeiro passo pula → canal conecta automaticamente à thread da entrada padrão → brief injetado no `ctx` → saída limpa.

**Nunca rodou contra a API real.** Aquela sonda de $0.8908 foi uma **requisição real**, mas ela testou "o que faz um clarificador sem restrição", não este caminho atual.

## Quando não usar {#什么时候不该用它}

**Quando o requisito já é peça congelada.** Requisito escrito num arquivo, definido por um sistema a montante, ou esta execução é só refazer a mesma coisa — não há o que perguntar. Alimente o texto do requisito direto no passo de trabalho, ou mantenha o `clarify_step` e deixe o `when` pular (com o brief presente, ele já não pergunta).

**Quando não há ninguém para perguntar e você não quer que ele adivinhe.** Com `timeout_s=0` todas as perguntas caem no vazio na hora e a quarta seção é preenchida com uma pilha de premissas dele mesmo — é o comportamento projetado, mas a confiabilidade daquele brief passa a ser exatamente a confiabilidade dessas premissas. Em CI, o mais limpo é `max_asks=0` (proibir explicitamente perguntar) e fornecer o requisito completo por fora.

**Trabalhinho pontual.** O passo de confirmação custa dinheiro: no [HT002](../cases/ht002.md), para algo como "clonar um repositório, instalar e rodar no macOS", confirmar o requisito custou **$0.5306 / 9 turnos / 0.10h**. Quanto menor o trabalho, pior fica essa proporção. O caminho de agent único do `flower once` não inclui este passo.

**Ao mudar o requisito, não se deve reabrir o diálogo.** O brief é peça congelada; a partir do momento em que vai para o disco, o requisito é o arquivo — o certo é **editar esse arquivo**. `--clarify-only` num diretório já confirmado é **no-op** (aquele workflow só tem esse passo, e ele pula); para reconfirmar, combine com `--new`, ou use `always_ask=True` na sua própria fiação.

**Ele não julga se "acabou".** Isso é outra camada; veja [guardião de objetivo](goal.md). A clarificação prévia barra "o que saiu não é o que se queria"; ela não barra "disse que terminou, mas não terminou".
