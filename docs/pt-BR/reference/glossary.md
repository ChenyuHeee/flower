# Glossário

Esta página é a referência terminológica da documentação do flower. A mesma coisa tem um único nome em todo o site; a correspondência com o inglês fica fixada aqui — as versões traduzidas seguem esta mesma tabela.

Cada verbete traz três coisas: **o que o termo designa**, **o que ele é no código** e **o que ele não é**. A terceira costuma ser a mais útil, porque a maioria dos mal-entendidos vem de tomar um termo por outro.

---

## Framework e execução

### Long-horizon {#长程}

**long-horizon**

Uma execução que atravessa horas ou dias, várias sessions e reinícios de processo, em vez de ser pergunta-e-resposta. Todos os mecanismos do flower existem para que esse tipo de execução não se desfaça no meio do caminho.

Referência medida: [HT001](../cases/ht001.md) rodou 10.4 horas seguidas.

### Execução {#运行}

**run**

O processo completo de um `Runtime`, do início ao fim. Uma execução pode ter vários [passos](#步骤), várias [sessions](#会话), e pode ser interrompida e depois retomada por [continuidade](#接续). O registro da execução fica em `runs/manifest.json` e `runs/sessions.db`.

**Não é**: uma chamada de API, nem uma session.

### Session {#会话}

**session**

Um contexto do lado do modelo. Tem seu próprio `session_id`, pode sofrer resume e pode sofrer fork. Uma [execução](#运行) pode queimar várias sessions — cada [handoff](#换代) troca por uma nova.

### Passo {#步骤}

**step** · `Step`

Uma unidade executável dentro do [fluxo de trabalho](#流程). Recebe um dicionário de contexto, roda um agent e escreve o resultado de volta no dicionário. `Step` é uma classe, veja a [Python API](api.md#step).

### Fluxo de trabalho {#流程}

**workflow** · `Workflow`

Um conjunto de [passos](#步骤) encadeados em ordem, mais as regras de como o estado passa entre eles e quando sair mais cedo.

!!! note "O framework não fornece fluxos prontos"
    O flower só fornece mecanismos. **O fluxo de trabalho é você que escreve.** Veja [Desenhar o fluxo de trabalho](../guide/workflow.md).

---

## Papéis

Papel é a divisão de trabalho que o flower impõe aos agents. Cada papel = um trecho de texto de regras injetado + um conjunto de ferramentas + um conjunto de hooks. Os cinco papéis são funções de fábrica, veja a [Python API](api.md#角色工厂).

### Coordenador {#协调者}

**coordinator** · `coordinator()`

O agent que fica na [thread principal](#主线程). Ele decompõe a tarefa, despacha trabalho, lê relatórios e decide, **mas não põe a mão na massa** — não recebe `Bash` / `Write` / `Edit`. As ferramentas são apenas `Agent`, `TodoWrite`, `Read`.

O papel é definido como "uma pessoa que sabe usar o Claude Code", não como executor.

**Não é**: um agent mais inteligente. Ele e o [executor](#执行者) usam por padrão o mesmo nível de modelo; o que se economiza é contexto, não modelo.

### Executor {#执行者}

**worker** · `worker()`

O [subagent](#subagent) que de fato trabalha: escreve código, roda testes, pesquisa. As ferramentas são `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

O formato de resposta é restringido pelo texto de regras a quatro blocos — **conclusão / evidência / entregas / não verificado** —, no máximo 30 linhas, proibido colar conteúdo de arquivos, saída de comandos, logs ou diffs literais.

### Esclarecedor {#确认者}

**clarifier** · `clarify()`

O papel que deixa o requisito claro antes de qualquer trabalho. Ele não executa nada, só pergunta, até ficar claro (**não há limite de rodadas**), e no fim produz um [brief de requisitos](#需求确认书). Veja [Esclarecimento prévio](../guide/clarify.md).

### Juiz {#判定者}

**judge** · `judge()`

O papel que julga "acabou ou não". Ele faz uma de duas coisas: antes de começar, **define o objetivo** (produz o objetivo + a lista de verificação); ou, ao fim de cada rodada, **julga aquela rodada** (produz um [veredito](#判定)). Veja [Guardião do objetivo](../guide/goal.md).

**Ponto-chave**: o juiz julga o **artefato entregue**, não o código-fonte.

No [HT001](../cases/ht001.md) houve um tropeço: o critério de aceitação dizia "rodar direto no terminal do macOS"; rodar `file` no artefato entregue devolvia `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`, e mesmo assim o veredito foi de aprovação.

Dois pontos precisam ficar claros, senão esse exemplo é mal lido:

1. **Quem errou o julgamento não foi o guardião do objetivo** — o HT001 ainda não tinha esse mecanismo; quem errou foi um auditor que o coordenador despachou por conta própria.
2. **O juiz na configuração padrão provavelmente também deixaria passar.** `judge()` usa `can_run=False` por padrão, com apenas `Read/Glob/Grep` — **ele não consegue rodar `file`**; só leria o `Makefile`, veria que existe mesmo um ramo Darwin e julgaria o objetivo alcançado.

O que funcionou de verdade foi o [HT002](../cases/ht002.md): o juiz estava com `judge_can_run` ligado, rodou `file` e `lsof` por conta própria para ver a cena e evitou explicitamente essa armadilha. **Ou seja: a frase "julgar o artefato" só se sustenta com `can_run=True`.**

### Oráculo {#旁路顾问}

**oracle** · `oracle()`

Uma via lateral somente leitura. Com a execução ainda rodando, você pode perguntar "onde estamos agora"; ele dá uma olhada nos eventos recentes e na [bancada](#工作台) antes de responder. **O que ele diz não entra no contexto daquela execução** — perguntar não afeta a execução, e a resposta é descartada depois.

### subagent {#subagent}

Conceito do Claude Agent SDK: um agent filho despachado pelo agent principal via ferramenta `Agent`. Ele tem **um transcript próprio**; as chamadas de ferramenta e as tentativas frustradas ficam registradas ali, e a thread principal só recebe o relatório final.

Essa é a primeira camada de economia de contexto do flower, e a que mais economiza. Veja [Economia de contexto](../guide/context.md).

---

## Os quatro mecanismos

### Esclarecimento prévio {#前置确认}

**clarify**

Deixar o requisito claro antes de trabalhar, congelá-lo num [brief de requisitos](#需求确认书) e só então executar. Barra o "entregou algo que não era o que se queria". Veja [Esclarecimento prévio](../guide/clarify.md).

### Brief de requisitos {#需求确认书}

**brief** · `Brief`

O documento produzido pelo [esclarecedor](#确认者) depois de perguntar, com **exatamente quatro blocos**. Os passos seguintes leem esse documento e não voltam a adivinhar o requisito.

**Não confunda** com o [briefing de tarefa](#任务书). O brief de requisitos é "o que a pessoa quer"; o briefing de tarefa é "o que este subagent vai fazer desta vez".

### Briefing de tarefa {#任务书}

**task brief**

O texto que o [coordenador](#协调者) escreve para o [executor](#执行者) ao despachar trabalho. **Só escreva o que é específico desta tarefa** — não repita disciplinas que o outro lado já conhece.

Medição: 8/8 dos briefings de tarefa repetiam disciplinas já conhecidas pelo destinatário; no mais curto deles, de 521 caracteres, só cerca de 120 caracteres eram específicos da tarefa — cerca de 4.8k de contexto permanente desperdiçado por rodada.

### Guardião do objetivo {#目标看守}

**goal guard**

O [juiz](#判定者) julga de forma independente, ao fim de cada rodada, se o objetivo foi alcançado; se não foi, devolve para continuar. Barra o "disse que terminou, mas não terminou". Veja [Guardião do objetivo](../guide/goal.md).

### Veredito {#判定}

**verdict** · `Verdict`

O resultado de uma rodada de julgamento do [juiz](#判定者), com **exatamente três blocos**: conclusão / justificativa / pendências.

A conclusão tem três valores: `ACHIEVED` (alcançado), `NOT_YET` (ainda não), `UNREACHABLE` (não dá para verificar neste ambiente). **Os dois últimos são conclusões diferentes** — "aqui não dá para verificar" jamais é julgado como aprovado.

### Continuidade {#接续}

**continuity**

Rodar de novo no mesmo diretório e retomar automaticamente o progresso da vez anterior — inclusive se o processo foi morto ou a máquina reiniciou. Barra o "rodou horas, caiu, começa tudo de novo". Veja [Continuidade](../guide/continuity.md).

**Não confunda** com [handoff](#换代): continuidade retoma a execução anterior **entre processos**; handoff troca por uma nova session **dentro da mesma execução**.

### Handoff {#换代}

**handoff**

Quando o contexto está quase cheio, a session atual escreve um [documento de handoff](#交接书) legível e editável por humanos, e uma nova session assume. Barra o "o contexto encheu e virou um parágrafo de resumo". Veja [Handoff](../guide/handoff.md).

**Não é** compact. Veja [compact](#压缩).

### Documento de handoff {#交接书}

**handoff document** · `Handoff`

O documento escrito no handoff, com cinco blocos: `doing` (o que está sendo feito), `decided` (o que foi decidido), `deadends` (caminhos sem saída), `next` (próximo passo), `scene` (a cena).

**Só `doing` e `next` são obrigatórios** — exigir que "caminhos sem saída" nunca esteja vazio força o modelo a inventar.

### compact {#压缩}

**compact**

O jeito nativo do Claude Code: o contexto enche e a conversa anterior é resumida num sumário.

O flower **não usa isso**; usa [handoff](#换代) no lugar. A diferença: o sumário é gerado pelo modelo, não dá para ler nem editar, e você não sabe o que se perdeu; o documento de handoff é estruturado, gravado em disco, e você pode abrir, mudar uma linha e mandar continuar.

---

## Gestão de contexto

### Thread principal {#主线程}

**main thread**

O contexto de session onde vive o [coordenador](#协调者). É o único contexto que atravessa a execução inteira, e por isso é o que mais precisa ser economizado.

Como o código identifica a thread principal: os dados do hook **não têm** `agent_id`. Os hooks de subagent trazem `agent_id`.

### Bancada {#工作台}

**workbench** · `Workbench`

O diretório de trabalho em disco, com três subdiretórios:

| Diretório | O que vai lá |
|---|---|
| `scripts/` | Scripts que serão rodados uma segunda vez; a primeira linha traz `# desc: uma frase` |
| `artifacts/` | Saídas longas, acima de 2000 caracteres |
| `notes/` | Decisões-chave, um arquivo por decisão |

`INDEX.md` é o índice desses três diretórios e é **injetado no system prompt**, então o agent sabe a cada rodada o que tem em mãos.

!!! warning "Duas portas de entrada, dois locais padrão"
    Onde a bancada fica depende de como você a cria, e é fácil tropeçar nisso:

    | Forma de criação | Raiz da bancada |
    |---|---|
    | `Workbench(workspace)` — também é o caminho usado por `starter_flow()` / `wake_state()` | `<workspace>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (padrão `runs/workbench`) |

    A linha de comando usa a primeira forma, então rodar `flower` produz `.flower/`; mas no Python, `Runtime(workbench=True)` direto entrega `runs/workbench`. Para definir o local, passe uma instância de `Workbench` já construída; não confie no padrão.

!!! warning "O índice não é herdado pelos subagents"
    O índice vai pelo `system_prompt.append` no nível da session, e **subagents não o recebem**. Portanto, a regra "saída longa vai para `artifacts/`" tem de ser repassada pelo [coordenador](#协调者) dentro do [briefing de tarefa](#任务书) — esse é o único canal.

### spill {#落盘}

**spill**

Quando o resultado de uma ferramenta passa do limite (padrão: 4000 caracteres), o hook `PostToolUse` o grava em `<raiz da bancada>/spill/` e deixa no contexto apenas uma linha com o caminho.

O caminho **acompanha a [bancada](#工作台)**, não é fixo no código — só quando a bancada está no local padrão `<workspace>/.flower` é que ele corresponde a `.flower/spill/`. Com [isolamento](#隔离) ligado e a bancada apontada para fora do repositório via `home=`, o spill se muda junto.

**Corta na hora**, em vez de esperar o contexto encher para fazer [compact](#压缩) depois.

### Comando efêmero {#一次性命令}

**ephemeral command**

Comandos cujo resultado expira e não tem valor de arquivo — `ls`, `git status`, `ps` e afins. Os resultados deles não entram no registro persistido da session. A decisão de "liberar a thread principal para dar uma olhada" e a decisão de "esse resultado será recortado" usam a mesma função, então os dois conjuntos são sempre iguais.

### Recorte {#裁剪}

**trim** · `TrimmingSessionStore`

Reescreve, **antes do resume**, a cópia de mensagens que vai ser realimentada no modelo (resultados de [comandos efêmeros](#一次性命令), saídas de ferramenta gigantes).

Ele só sobrescreve `load()`: **o texto original no SQLite nunca é tocado**; o que é recortado é apenas a cópia enviada ao contexto neste resume. Por isso o recorte é reversível — troque de política, faça resume de novo e você recebe o registro completo.

### Poda {#剪除}

**prune** · `PruningSessionStore`

Mantém **mensagens de erro** fora do contexto. A pilha de erros gerada durante as retentativas de queda de rede não deve ocupar o contexto depois do resume.

**Não confunda** com [recorte](#裁剪): o recorte descarta por volume e valor; a poda descarta por "é erro ou não".

---

## Runtime

### Isolamento {#隔离}

**isolation**

Papéis marcados recebem automaticamente um git worktree próprio, imposto por hook, sem depender de prompt. Assim, alterações paralelas no mesmo repositório não se atropelam.

!!! warning "Ligou isolamento, tire a bancada do repositório"
    Com o isolamento por worktree ligado, a [bancada](#工作台) precisa ser apontada para fora do repositório via `home=`; caso contrário, o agent isolado não consegue escrever no checkout compartilhado.

### Resiliência {#韧性}

**resilience** · `Resilience`

Quando a rede cai, fica pendurado esperando em vez de sair com erro: sondas de DNS + TCP monitoram, e quando a rede volta o resume continua a execução. As mensagens de erro geradas durante a espera são barradas do contexto pela [poda](#剪除).

### Linhagem {#血缘}

**lineage** · `Lineage`

Registra, entre processos, "de qual session esta execução foi bifurcada", em `lineage.json`. A [continuidade](#接续) usa esse arquivo para descobrir onde a execução anterior parou.

**Não confunda** com o [manifesto de execução](#运行清单) — aquele é o `runs/manifest.json`, a contabilidade de cada execução.

### Manifesto de execução {#运行清单}

**run manifest** · `runs/manifest.json`

O registro contábil de cada [execução](#运行): quanto custou, quanto tempo durou, qual o tamanho do contexto. Todos os números das páginas de casos podem ser refeitos a partir daqui.

### Despertar {#唤醒}

**wake** · `wake_state()`

Uma **sondagem somente leitura** antes da largada: verifica se este workspace já tem um [brief de requisitos](#需求确认书) e um objetivo, para decidir se esta rodada é um começo do zero ou uma [continuidade](#接续). **Não escreve um único byte.**

`wake_state()` é o único lugar onde a localização da bancada é definida — até o programa driver, para saber onde está o brief, tem de passar por ele. Montar o caminho na mão e errar não dá erro; falha em silêncio.

### Evento {#事件}

**event** · `Event`

A estrutura estável em que o fluxo de mensagens do SDK é achatado. **A [camada de interação](#交互层) só conhece `Event` e não importa nenhum tipo do SDK** — essa é a fronteira que permite trocar a UI sem mexer no núcleo.

### Camada de interação {#交互层}

**interaction layer**

A camada de UI entre a pessoa e a execução. O padrão é o terminal; pode ser trocada por Web, TUI, HTTP, ou por operação totalmente automática e sem supervisão. Veja [Trocar a camada de interação](../guide/interaction.md).

### Session store {#会话存储}

**session store** · `SessionStore`

O backend de persistência das mensagens de session. O padrão, `SqliteSessionStore`, grava em `runs/sessions.db`, e pode ser envolvido pelas duas camadas de [recorte](#裁剪) e [poda](#剪除).

### Orçamento {#预算}

**budget** · `max_budget_usd`

O teto de gasto de uma execução; ao estourar, ela para. Sem isso, uma execução long-horizon fica cara — o [HT001](../cases/ht001.md) gastou $171.62.

---

## Portabilidade

### Portátil {#可移植}

**portable**

Troque de máquina e o comportamento é o mesmo. Isso é feito com `setting_sources=[]` — não lê o `~/.claude/` da máquina hospedeira nem o `.claude/` do projeto. A capacidade de domínio viaja com o repositório via [plugin](#plugin), e as credenciais vêm no `.env`.

O custo: **as credenciais têm de vir junto**; nada é herdado automaticamente da configuração da máquina hospedeira.

### append {#叠加}

**append**

As instruções de domínio são acrescentadas **depois** do system prompt nativo do Claude Code, em vez de substituí-lo:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Assim, a especialização não custa a capacidade geral.

### plugin {#plugin}

Pacote de capacidade de domínio que viaja com o repositório. Carregado via `plugins=[local]`; o diretório pode conter `skills/`, `agents/`, `hooks/`, `.mcp.json`. Veja [Implantação](deploy.md#plugin).
