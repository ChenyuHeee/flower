# Glossário

Esta página é a base terminológica da documentação do flower. Cada coisa tem um único nome em
todo o site, e a correspondência chinês-inglês está fixada aqui — as versões traduzidas seguem
esta mesma tabela.

Cada entrada dá três coisas: **o que o termo designa**, **o que ele é no código** e **o que ele
não é**. A terceira costuma ser a mais útil, porque a maioria dos mal-entendidos vem de confundir
um termo com outro.

---

## Framework e run {#框架与运行}

### Long-horizon {#长程}

**long-horizon**

Um run que atravessa horas ou dias, várias sessions e reinícios de processo — não uma pergunta e
uma resposta. Todos os mecanismos do flower existem para que esse tipo de run não desmonte no meio
do caminho.

Referência medida: [HT001](../cases/ht001.md) rodou 10.4 horas seguidas.

### Run {#运行}

**run**

O processo completo de um `Runtime`, do início ao fim. Um run pode conter vários
[steps](#步骤), várias [sessions](#会话), e pode ser interrompido e depois
[continuado](#接续). O registro do run fica em `runs/manifest.json` e `runs/sessions.db`.

**Não é**: uma chamada de API, nem uma session.

### Session {#会话}

**session**

Um contexto do lado do modelo. Tem seu próprio `session_id`, pode sofrer resume e fork. Um
[run](#运行) pode queimar várias sessions — cada [handoff](#换代) troca por uma nova.

### Step {#步骤}

**step** · `Step`

Uma unidade executável dentro de um [workflow](#流程). Recebe um dicionário de contexto, roda um
agent e escreve o resultado de volta no dicionário. `Step` é uma classe, veja a
[Python API](api.md#step).

### Workflow {#流程}

**workflow** · `Workflow`

Um conjunto de [steps](#步骤) encadeados em ordem, mais as regras de como o estado passa entre
eles e quando sair mais cedo.

!!! note "O framework não fornece workflows prontos"
    O flower só fornece mecanismo. **O workflow é você quem escreve.** Veja
    [Desenhar o workflow](../guide/workflow.md).

---

## Papéis {#角色}

Papéis são a divisão de trabalho que o flower faz entre agents. Cada papel = um trecho de regras
injetado + um conjunto de ferramentas + um conjunto de hooks. Os cinco papéis são funções de
fábrica, veja a [Python API](api.md#角色工厂).

### Coordinator {#协调者}

**coordinator** · `coordinator()`

O agent que fica na [main thread](#主线程). Ele decompõe a tarefa, delega, lê relatórios e decide,
**mas não põe a mão** — não recebe `Write` / `Edit`. As ferramentas básicas são `Agent`,
`TodoWrite`, `Read` (`roles.py:27`), mas essa não é a lista final: conforme os parâmetros, mais
três coisas entram. `glance=True` (padrão) adiciona um `Bash` restrito (o suficiente para
comandos do tipo `git status` / `ls`, que se resolvem numa olhada, com o `delegate_guard`
controlando); se houver um canal de perguntas, entram `inbox` e `ask`; e se os
[workers](#执行者) sob seu comando têm `WebFetch` / `WebSearch`, esses dois também são
incorporados — `allowed_tools` é de **nível de session**, e sem essa incorporação o subagent
trava numa aprovação de permissão que ninguém responde (`roles.py:513-526`).

O papel é definido como "alguém que sabe usar o Claude Code", não como executor.

**Não é**: um agent mais inteligente. Ele e o [worker](#执行者) usam por padrão a mesma classe de
modelo; o que se economiza é contexto, não modelo.

### Worker {#执行者}

**worker** · `worker()`

O [subagent](#subagent) que realmente trabalha: escreve código, roda testes, pesquisa. As
ferramentas são `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

O formato da resposta é restringido pelo texto de regras a quatro seções — **conclusão /
evidências / entregas / não verificado** —, no máximo 30 linhas, proibido colar conteúdo de
arquivo, saída de comando, log ou diff bruto.

### Clarifier {#确认者}

**clarifier** · `clarify()`

O papel que esclarece o requisito antes de se pôr a mão na massa. Ele não executa nada, só
pergunta, até ficar claro (**sem limite de rodadas**), e ao final produz um
[brief](#需求确认书). Veja [Clarify](../guide/clarify.md).

### Judge {#判定者}

**judge** · `judge()`

O papel que decide "está pronto ou não". Ele faz uma de duas coisas: antes do run, **define o
objetivo** (produz o objetivo + a checklist de julgamento); ou, ao fim de cada rodada, **julga
aquela rodada** (produz um [verdict](#判定)). Veja [Goal guard](../guide/goal.md).

**Ponto-chave**: o judge julga o **artefato entregue**, não o código-fonte.

Em [HT001](../cases/ht001.md) isso deu errado uma vez: o critério de aceite dizia "roda
diretamente no terminal do macOS", e o artefato entregue, passado pelo `file`, deu
`ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux` — e mesmo assim o veredito foi aprovado.

Dois pontos precisam ficar claros, senão esse exemplo é lido errado:

1. **O que errou ali não foi o goal guard** — o HT001 ainda não tinha esse mecanismo; quem errou
   foi um auditor que o coordinator despachou por conta própria.
2. **O judge na configuração padrão provavelmente também deixaria passar.** `judge()` usa
   `can_run=False` por padrão, e as ferramentas são só `Read/Glob/Grep` — **ele não consegue rodar
   `file`**; só vai ler o `Makefile`, ver que existe mesmo um ramo Darwin, e julgar como atingido.

O que de fato funciona é [HT002](../cases/ht002.md): lá o judge estava com `judge_can_run` ligado,
rodou `file` e `lsof` para olhar a cena, e evitou explicitamente esse buraco. **Ou seja: "julgar o
artefato" só se sustenta com `can_run=True`.**

### Oracle {#旁路顾问}

**oracle** · `oracle()`

Um desvio somente-leitura. Com o run ainda em andamento, você pode perguntar "onde estamos agora",
e ele dá uma olhada nos eventos recentes e no [workbench](#工作台) antes de responder. **O que ele
diz não entra no contexto daquele run** — perguntar não afeta o run, e a resposta é descartada
depois.

### subagent {#subagent}

Conceito do Claude Agent SDK: um agent filho despachado pelo agent principal via a ferramenta
`Agent`. Ele tem **um transcript próprio**; as chamadas de ferramenta e as tentativas erradas
ficam registradas ali, e a main thread só recebe o relatório final.

Esta é a primeira camada de economia de contexto do flower, e a que mais economiza. Veja
[Economia de contexto](../guide/context.md).

---

## Os quatro mecanismos {#四个机制}

### Clarify {#前置确认}

**clarify**

Esclarecer o requisito antes de agir, congelá-lo em um [brief](#需求确认书) e só então executar.
Barra o "fizeram, mas não é o que eu queria". Veja [Clarify](../guide/clarify.md).

### Brief {#需求确认书}

**brief** · `Brief`

O documento que o [clarifier](#确认者) produz depois de perguntar tudo, com **exatamente quatro
seções**. Os steps seguintes o leem, em vez de adivinhar o requisito de novo.

**Não confunda** com [task brief](#任务书). O brief é "o que a pessoa quer"; o task brief é "o que
este subagent vai fazer desta vez".

### Task brief {#任务书}

**task brief**

O texto que o [coordinator](#协调者) escreve para o [worker](#执行者) ao delegar. **Escreva apenas
o que é específico desta tarefa** — não repita a disciplina que o outro lado já conhece.

Medido: 8/8 dos task briefs repetiam disciplina já conhecida pelo destinatário; no mais curto
deles, de 521 caracteres, só cerca de 120 caracteres eram específicos da tarefa — cerca de 4.8k de
contexto permanente desperdiçados por rodada.

### Goal guard {#目标看守}

**goal guard**

Ao fim de cada rodada, o [judge](#判定者) decide de forma independente se o objetivo foi atingido;
se não foi, devolve para continuar. Barra o "disse que terminou, mas não terminou". Veja
[Goal guard](../guide/goal.md).

### Verdict {#判定}

**verdict** · `Verdict`

O resultado de uma rodada de julgamento do [judge](#判定者), com **exatamente três seções**:
conclusão / motivo / não aprovado.

A conclusão tem três valores: `ACHIEVED` (atingido), `NOT_YET` (ainda não), `UNREACHABLE` (não dá
para verificar neste ambiente). **Os dois últimos são conclusões diferentes** — "aqui não dá para
verificar" jamais é julgado como aprovado.

### Continuidade {#接续}

**continuity**

Rodar de novo no mesmo diretório retoma automaticamente o progresso da vez anterior — inclusive se
o processo foi morto ou a máquina reiniciou. Barra o "rodou horas, quebrou, e começa tudo de
novo". Veja [Continuidade](../guide/continuity.md).

**Não confunda** com [handoff](#换代): continuidade retoma o run anterior **entre processos**;
handoff troca por uma session nova **dentro do mesmo run**.

### Handoff {#换代}

**handoff**

Quando o contexto está quase cheio, a session atual escreve um
[documento de handoff](#交接书) que uma pessoa consegue ler e editar, e então uma nova session
assume. Barra o "o contexto encheu e virou um resumo de um parágrafo". Veja
[Handoff](../guide/handoff.md).

**Não é** compact. Veja [compact](#压缩).

### Documento de handoff {#交接书}

**handoff document** · `Handoff`

O documento escrito no handoff, com cinco seções: `doing` (o que está sendo feito), `decided` (o
que foi decidido), `deadends` (caminhos sem saída), `next` (próximo passo), `scene` (a cena).

**Só `doing` e `next` são obrigatórios** — exigir rigidamente que "caminhos sem saída" não seja
vazio força o modelo a inventar.

### Compact {#压缩}

**compact**

A abordagem nativa do Claude Code: quando o contexto enche, resume a conversa anterior em um
parágrafo.

O flower **não usa isso**, usa [handoff](#换代) no lugar. A diferença: o resumo é gerado pelo
modelo, não é legível nem editável, e você não sabe o que se perdeu; o documento de handoff é
estruturado, gravado em disco, e você pode abrir, mudar uma linha e mandar continuar.

---

## Gestão de contexto {#上下文管理}

### Main thread {#主线程}

**main thread**

O contexto de session onde vive o [coordinator](#协调者). É o único contexto que atravessa o run
inteiro, então é o que mais precisa ser economizado.

Como o código identifica a main thread: os dados do hook **não têm** `agent_id`. Os hooks de
subagent trazem `agent_id`.

### Workbench {#工作台}

**workbench** · `Workbench`

O diretório de trabalho gravado em disco, com três subdiretórios:

| Diretório | O que guarda |
|---|---|
| `scripts/` | Scripts que serão rodados uma segunda vez; primeira linha com `# desc: uma frase` |
| `artifacts/` | Saídas longas, acima de 2000 caracteres |
| `notes/` | Decisões-chave, um arquivo por decisão |

`INDEX.md` é o índice desses três diretórios e é **injetado no system prompt**, para que o agent
saiba a cada rodada o que tem em mãos.

!!! warning "Duas entradas, dois locais padrão"
    Onde o workbench fica depende de como ele é criado, e isso é fácil de pisar na bola:

    | Forma de criação | Raiz do workbench |
    |---|---|
    | `Workbench(workspace)` — também o caminho de `starter_flow()` / `wake_state()` | `<workspace>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (padrão `runs/workbench`) |

    A linha de comando usa a primeira, então rodar `flower` produz `.flower/`; mas chamar
    `Runtime(workbench=True)` direto no Python dá `runs/workbench`. Para definir o local, passe
    uma instância de `Workbench` já construída, não confie no padrão.

!!! warning "O índice não é herdado pelos subagents"
    O índice vai pelo `system_prompt.append` de nível de session, e **os subagents não o recebem**.
    Por isso, a regra "saída longa vai para `artifacts/`" tem que ser repassada pelo
    [coordinator](#协调者) dentro do [task brief](#任务书) — esse é o único canal.

### Spill {#落盘}

**spill**

Quando o resultado de uma ferramenta passa do limite (4000 caracteres por padrão), o hook
`PostToolUse` o grava em `<raiz do workbench>/spill/`, e no contexto fica apenas uma linha com o
caminho.

O caminho **acompanha o [workbench](#工作台)**, não é fixo — só quando o workbench está no local
padrão `<workspace>/.flower` é que ele fica exatamente em `.flower/spill/`. Com
[isolamento](#隔离) ligado, e o workbench apontado para fora do repositório via `home=`, o spill
se muda junto.

**Corta na hora**, em vez de esperar o contexto encher para depois fazer [compact](#压缩).

### Comando efêmero {#一次性命令}

**ephemeral command**

Comandos cujo resultado expira e não tem valor de retenção — `ls`, `git status`, `ps` e afins. O
resultado deles não entra no registro persistido da session. A decisão de "pode liberar a main
thread para dar uma olhada" e a de "o resultado será cortado" usam a mesma função, então os dois
conjuntos são sempre iguais.

### Trim {#裁剪}

**trim** · `TrimmingSessionStore`

Reescreve, **antes do resume**, a cópia de mensagens que será alimentada de volta ao modelo
(resultados de [comandos efêmeros](#一次性命令), saídas de ferramenta muito longas).

Ele só sobrescreve `load()`: **o texto original no SQLite nunca é tocado**; o que se corta é só
aquela cópia enviada ao contexto neste resume. Portanto o trim é reversível — troque a política,
faça resume de novo, e o registro completo volta.

### Prune {#剪除}

**prune** · `PruningSessionStore`

Mantém as **mensagens de erro** fora do contexto. A pilha de erros produzida durante retentativas
com a rede caída não deve ocupar o contexto depois do resume.

**Não confunda** com [trim](#裁剪): o trim descarta por volume e valor; o prune descarta por "é
erro ou não".

---

## Runtime {#运行时}

### Isolamento {#隔离}

**isolation**

Papéis marcados recebem automaticamente um git worktree próprio, imposto por hook, sem depender do
prompt. Assim não há briga ao alterar o mesmo repositório em paralelo.

!!! warning "Ligou isolamento, tire o workbench do repositório"
    Com isolamento por worktree ligado, o [workbench](#工作台) precisa ser apontado para fora do
    repositório via `home=`; caso contrário o agent isolado não consegue escrever no checkout
    compartilhado.

### Resiliência {#韧性}

**resilience** · `Resilience`

Com a rede caída, espera em vez de falhar e sair: sondas de DNS + TCP monitoram, e quando a rede
volta o run continua via resume. As mensagens de erro geradas durante a espera são mantidas fora
do contexto pelo [prune](#剪除).

### Linhagem {#血缘}

**lineage** · `Lineage`

Registra, entre processos, "de qual session este run foi forkado", gravado em `lineage.json`. A
[continuidade](#接续) usa isso para achar onde a última vez parou.

**Não confunda** com o [run manifest](#运行清单) — aquele é `runs/manifest.json`, e registra a
contabilidade de cada run.

### Run manifest {#运行清单}

**run manifest** · `runs/manifest.json`

O registro contábil de cada [run](#运行): quanto custou, quanto tempo levou, qual o tamanho do
contexto. Todos os números das páginas de caso podem ser recalculados a partir daqui.

### Wake {#唤醒}

**wake** · `wake_state()`

Uma **sondagem somente-leitura** antes da largada: verifica se este workspace já tem um
[brief](#需求确认书) e um objetivo, para decidir se esta vez é um começo do zero ou uma
[continuidade](#接续). **Não escreve um único byte.**

`wake_state()` é o único lugar que define a localização do workbench — se o programa driver quiser
saber onde está o brief, também tem que passar por ele. Montar o caminho na mão e errar não gera
erro, só falha em silêncio.

### Evento {#事件}

**event** · `Event`

O fluxo de mensagens do SDK achatado numa estrutura estável. **A [camada de interação](#交互层)
só conhece `Event` e não importa nenhum tipo do SDK** — é essa a fronteira que permite trocar de
UI sem mexer no núcleo.

### Camada de interação {#交互层}

**interaction layer**

A camada de UI entre a pessoa e o run. O padrão é o terminal; pode ser trocada por Web, TUI, HTTP,
ou por operação totalmente automática sem supervisão. Veja
[Trocar a camada de interação](../guide/interaction.md).

### Session store {#会话存储}

**session store** · `SessionStore`

O backend de persistência das mensagens de session. O padrão, `SqliteSessionStore`, escreve em
`runs/sessions.db`, e pode receber as duas camadas de wrapper: [trim](#裁剪) e [prune](#剪除).

### Budget {#预算}

**budget** · `max_budget_usd`

O teto de gasto de um run; ao ultrapassar, para. Sem isso, um run long-horizon fica caro —
[HT001](../cases/ht001.md) custou $171.62.

---

## Portabilidade {#可移植性}

### Portável {#可移植}

**portable**

Troque de máquina e o comportamento é o mesmo. A forma é `setting_sources=[]` — não lê o
`~/.claude/` da máquina hospedeira, nem o `.claude/` do projeto. A capacidade de domínio viaja com
o repositório via [plugin](#plugin), e as credenciais vêm no `.env`.

O custo: **as credenciais precisam vir junto**, não há herança automática da configuração da
máquina.

### Append {#叠加}

**append**

As instruções de domínio são acrescentadas **depois** do system prompt nativo do Claude Code, em
vez de substituí-lo:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Assim, a especialização não custa a capacidade geral.

### plugin {#plugin}

Um pacote de capacidade de domínio que viaja com o repositório. Carregado via `plugins=[local]`, e
o diretório pode conter `skills/`, `agents/`, `hooks/`, `.mcp.json`. Veja
[Deploy](deploy.md#plugin).
