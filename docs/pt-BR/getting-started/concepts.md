# Conceitos centrais

O flower tem um vocabulário próprio: execução, etapa, session, coordenador, executor, clarificação prévia, guardião de objetivo, continuidade, handoff.
Esta página explica todos eles de uma vez; depois de lê-la, você não precisa mais adivinhar nada nas outras páginas. Dá para ler em cinco minutos.

Aqui só há conceitos, **sem assinaturas de API** — para assinaturas vá para a [API Python](../reference/api.md),
para definições de uma linha e o pareamento chinês-inglês vá para o [glossário](../reference/glossary.md), para flags de linha de comando vá para a
[referência de linha de comando](../reference/cli.md).

## Qual é o formato de uma execução {#形状}

Três níveis, do maior para o menor:

| Termo | O que é | Onde fica registrado |
|---|---|---|
| [execução](../reference/glossary.md#运行) run | O processo completo de um `Runtime`, do início ao fim. No caminho padrão, uma execução é uma vez que você digita `flower` | `runs/manifest.json` |
| [etapa](../reference/glossary.md#步骤) step | Uma unidade executável dentro da execução: recebe um dicionário de contexto, roda um agent, escreve o resultado de volta no dicionário. Cada linha de `==` na tela é uma fronteira de etapa | idem, uma linha por etapa |
| [session](../reference/glossary.md#会话) session | Um contexto do lado do modelo. Tem seu próprio `session_id`, pode sofrer resume e pode sofrer fork | `runs/sessions.db` |

O aninhamento entre eles não é um-para-um:

```text
execução ── esta vez que você digitou flower
 ├── etapa confirmar requisitos ── session A
 ├── etapa definir objetivo ────── session B
 └── etapa executar ───────────── session C ──[contexto quase cheio]──> session C'
      └── executar·veredito#1 ─── session D
```

- **Uma etapa pode queimar várias sessions.** Quando o contexto está quase cheio, ela não faz compact; escreve um documento de handoff e abre uma session nova para assumir —
  isso é o [handoff](../reference/glossary.md#换代), e acontece **dentro da mesma execução**.
- **Uma execução nova pode retomar uma session antiga.** Digitando `flower` de novo no mesmo diretório, cada etapa reconecta à session da vez anterior —
  isso é a [continuidade](../reference/glossary.md#接续), e acontece **entre processos**. Ela se apoia em `runs/lineage.json`
  para lembrar "qual nome de etapa corresponde a qual `session_id`".
- **A rodada de veredito é sempre uma session nova.** Ela não faz continuidade e não entra na linhagem — quem julga "está pronto ou não" não pode ser o executor que acabou de trabalhar.

Um conjunto de etapas encadeadas em ordem se chama [workflow](../reference/glossary.md#流程).
Rodando `flower` puro, usa-se o workflow de três etapas que vem com o framework: confirmar requisitos → definir objetivo → executar.

## Divisão de trabalho: o coordenador não põe a mão na massa {#分工}

**É sobre isto que todo o framework se apoia.**

O [coordenador](../reference/glossary.md#协调者) é o agent que está na [thread principal](../reference/glossary.md#主线程).
Ele decompõe a tarefa, despacha trabalho, lê relatórios, toma decisões — mas **não recebe `Write` nem `Edit`**,
e o `Bash` dele só dá para rodar [comandos efêmeros](../reference/glossary.md#一次性命令) como `ls` e `git status`, para dar uma olhada
(fiscalizado por hook, não por restrição de prompt; e esse tipo de resultado não entra no registro persistido da session).
A lista de ferramentas dele é `Agent`, `TodoWrite`, `Read` mais aquele `Bash` restrito.

Quem realmente trabalha é o [executor](../reference/glossary.md#执行者) — um
[subagent](../reference/glossary.md#subagent) despachado pela ferramenta `Agent`.

**Por que essa divisão.** O subagent tem **a sua própria transcript**: quantos arquivos leu, quantas vezes rodou os testes,
quantas voltas deu tentando e errando, tudo fica registrado ali; a thread principal só recebe o relatório final. E a thread principal é o único contexto que atravessa a execução inteira,
então é ela que mais precisa ser economizada.

Medido na prática ([HT001](../cases/ht001.md), uma execução de 10.4 horas):

| | thread principal | subagent | proporção que afundou |
|---|---|---|---|
| Turnos de modelo | 70 | 3.0K | 97.7 % |
| Caracteres de texto | 200.1K | 3.6M | **94.8 %** |
| Chamadas de ferramenta | 32 | 1,893 | —— |

Em média, a cada despacho, **82 chamadas de ferramenta a thread principal simplesmente não vê**. Essa é a primeira camada de economia de contexto, e a que economiza mais;
a argumentação completa está em [economia de contexto](../guide/context.md).

Dois pontos que costumam ser mal entendidos:

- **O coordenador não é um agent mais inteligente.** Por padrão ele usa o mesmo nível de modelo que o executor; o que se economiza é contexto, não modelo.
- **O formato da resposta é restrito.** A resposta do executor tem exatamente quatro seções — conclusão / evidências / entregas / não verificado, no máximo 30 linhas,
  e é proibido colar conteúdo de arquivo, saída de comando, log ou diff bruto. Coisas longas vão para `artifacts/`, na
  [workbench](../reference/glossary.md#工作台); na resposta só entra o caminho.

O flower tem cinco papéis ao todo, todos feitos da mesma forma: um trecho de texto de regras injetado + um conjunto de ferramentas + um conjunto de hooks.

| Papel | O que faz | O que tem na mão |
|---|---|---|
| [coordenador](../reference/glossary.md#协调者) coordinator | decompõe, despacha, decide | `Agent` `TodoWrite` `Read` + `Bash` restrito |
| [executor](../reference/glossary.md#执行者) worker | escreve código, roda testes, pesquisa | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [clarificador](../reference/glossary.md#确认者) clarify | antes de agir, só pergunta, até ficar claro | ferramentas de pergunta + ferramentas somente-leitura, **nenhuma ferramenta de escrita** |
| [juiz](../reference/glossary.md#判定者) judge | define o objetivo, ou julga se "esta rodada está pronta" | ferramentas de pergunta + `Read` `Glob` `Grep` (para ele rodar comandos, é preciso habilitar explicitamente) |
| [oráculo](../reference/glossary.md#旁路顾问) oracle | responde "onde estamos agora" no meio da execução | `Read` `Glob` `Grep`. **O que ele diz não entra no contexto daquela execução** |

Os parâmetros e valores padrão das funções fábrica estão na [API Python](../reference/api.md#角色工厂).

## O longo alcance quebra em quatro lugares {#四个机制}

Uma execução de [longo alcance](../reference/glossary.md#长程) atravessa horas ou dias, atravessa várias sessions, atravessa reinícios de processo.
Ela se desmonta de umas poucas maneiras, e cada uma tem um mecanismo correspondente:

| O que você teme | Mecanismo | O que ele faz | Detalhes |
|---|---|---|---|
| O que sai não é o que você queria | [clarificação prévia](../reference/glossary.md#前置确认) | Antes de agir, esclarece o requisito e congela num [brief](../reference/glossary.md#需求确认书); cada etapa seguinte lê esse brief, sem ficar adivinhando de novo | [clarificação prévia](../guide/clarify.md) |
| Ele diz que terminou, mas não terminou | [guardião de objetivo](../reference/glossary.md#目标看守) | No fim de cada rodada, um juiz que não participou do trabalho julga de forma independente; se o objetivo não foi alcançado, devolve para continuar | [guardião de objetivo](../guide/goal.md) |
| Rodou por horas, caiu, e volta tudo do zero | [continuidade](../reference/glossary.md#接续) | Rodar de novo no mesmo diretório retoma automaticamente o progresso anterior — vale também se o processo foi morto ou a máquina reiniciou | [continuidade](../guide/continuity.md) |
| O contexto encheu e virou um resumo comprimido | [handoff](../reference/glossary.md#换代) | Quando está quase cheio, a session atual escreve um [documento de handoff](../reference/glossary.md#交接书) legível e editável por pessoas, e uma session nova assume | [handoff](../guide/handoff.md) |

Duas coisas merecem ser lembradas à parte:

**O [veredito](../reference/glossary.md#判定) tem três conclusões, não duas.** Alcançado, não alcançado, **este ambiente não consegue verificar**.
As duas últimas são conclusões diferentes — "aqui não dá para verificar" nunca é aprovado; para tudo e pergunta para a pessoa.
Além disso, o juiz julga o **artefato produzido**, não o código-fonte: em [HT002](../cases/ht002.md) isso deu errado uma vez,
o juiz olhou apenas o ramo macOS do Makefile e aprovou, quando o que foi entregue era um ELF Linux.

**Handoff não é [compact](../reference/glossary.md#压缩).** O compact é o modelo, por conta própria e às escuras, resumindo a conversa anterior num parágrafo:
ilegível, não editável, e você não sabe o que se perdeu. O documento de handoff é estruturado e fica em disco; você pode abrir, mudar uma linha e mandar continuar.
O flower desliga por padrão o auto-compact nativo e coloca o handoff no lugar.

Ainda há duas camadas que não estão nessa tabela, mas rodam em toda execução:

- [spill](../reference/glossary.md#落盘) — resultado de ferramenta acima de 4000 caracteres é escrito em `.flower/spill/`,
  e no contexto fica só uma linha com o caminho. **Corta na hora**, não espera encher para depois comprimir.
- [workbench](../reference/glossary.md#工作台) — os três diretórios `scripts/`, `artifacts/` e `notes/` dentro de `.flower/`,
  mais um índice `INDEX.md` injetado no system prompt, de modo que o agent sabe a cada rodada o que tem na mão.
  Naquela execução do HT001 acumularam-se **61 scripts, executados 331 vezes**, dos quais **92 %** foram executados mais de uma vez.

## O que o flower não faz {#不做什么}

**Um: ele não fornece workflows prontos.** O framework cuida só dos mecanismos: como uma etapa roda, como economizar contexto, como retomar depois de cair a rede,
como não haver conflito quando várias execuções mexem no mesmo repositório em paralelo, como parar quando é preciso perguntar para a pessoa. **O workflow é você que escreve.**
As três etapas do `flower` puro vêm de
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
genéricas a ponto de não conterem nenhuma suposição de domínio — servem para você começar, não são o limite da capacidade do framework.
Para escrever o seu, veja [projetar workflows](../guide/workflow.md).

**Dois: ele não herda a configuração da máquina hospedeira.** O flower roda com `setting_sources=[]`: não lê o `~/.claude/` da máquina,
nem o `.claude/` do projeto. Isso é ser [portável](../reference/glossary.md#可移植) — em outra máquina o comportamento é o mesmo.
A capacidade de domínio vem de [plugins](../reference/glossary.md#plugin) que viajam junto com o repositório, não do que por acaso está instalado nesta máquina.

**Três: as credenciais precisam ser trazidas por você.** Esse é o preço do item dois. O flower busca credenciais numa ordem fixa (variáveis de ambiente do processo →
`$FLOWER_ENV` → `.env` do diretório atual → `~/.config/flower/.env` → `.env` na raiz do repositório de código),
e por último vai pegar emprestadas, do bloco `env` do `~/.claude/settings.json`, aquelas 9 chaves de credencial como fallback —
**empresta só a informação de "onde encontrar o token"**; nada mais dentro do settings.json afeta o comportamento do agent.
A ordem completa e a semântica de cada variável estão na [referência de configuração](../reference/config.md).

**Quatro: ele não substitui o system prompt.** As instruções de domínio são [anexadas](../reference/glossary.md#叠加) **depois** do
system prompt nativo do Claude Code, não o substituem. Por isso a especialização não custa a capacidade geral.

---

Chegando até aqui, você já deve conseguir ler todas aquelas saídas do [início rápido](quickstart.md).
Para saber como ajustar cada um desses mecanismos e quando não usá-los, comece por [economia de contexto](../guide/context.md);
se você só quer copiar comandos, vá para a [referência de linha de comando](../reference/cli.md).
