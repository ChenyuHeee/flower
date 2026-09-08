# Configuração

flower não tem formato de arquivo de configuração, nem um subcomando de configuração que dê para usar de verdade — toda a configuração são **variáveis de ambiente** mais **arquivos `.env`**, mais um punhado de objetos de política que só podem ser passados pelo lado Python. Esta página junta numa coisa só o que está espalhado por cinco lugares: cada variável, em que ordem as credenciais são procuradas, que sintaxe o `.env` reconhece, o que exatamente `setting_sources=[]` isola, o que uma execução deixa em disco, o que cada uma das três camadas do session store descarta, e como ele espera quando a rede cai. A terminologia segue o [glossário](glossary.md).

| Quer saber | Vá para |
|---|---|
| Quais variáveis de ambiente o flower reconhece | [Tabela completa de variáveis de ambiente](#环境变量) |
| De onde meu token realmente veio | [Prioridade de busca de credenciais](#凭证查找优先级) |
| Por que aquela linha do `.env` não fez efeito | [Regras de parsing do `.env`](#env-解析) |
| O que levar ao trocar de máquina | [O preço da portabilidade](#可移植性) |
| O que tem dentro de `.flower/` e `runs/` | [Layout em disco](#磁盘布局) |
| Quais mensagens não voltam para o modelo | [As três camadas do session store](#会话存储) |
| O que ele está esperando quando a rede cai | [Resiliência a queda de rede](#韧性) |

## Tabela completa de variáveis de ambiente {#环境变量}

Cinco grupos: credenciais e endpoint lidos diretamente pelo flower, seleção de modelo, busca de caminhos, chaves de comportamento, e as que o flower **escreve para** o subprocesso do agent. O último grupo você não precisa definir — se definir, será sobrescrito.

### Credenciais e endpoint {#凭证变量}

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Key oficial da Anthropic. Com ela, as requisições vão com o header `x-api-key` | nenhum | **uma das duas, junto com `ANTHROPIC_AUTH_TOKEN`** | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token emitido por gateway. Sem `ANTHROPIC_API_KEY`, usa `authorization: Bearer` | nenhum | idem acima | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | Raiz do endpoint da API. Um gateway de terceiros põe o endereço dele aqui, **sem `/v1`** — a sonda monta `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | não | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

Se nenhuma das duas estiver definida (ou ambas forem string vazia), `check_credentials()` devolve aquele erro de quatro linhas e `Runtime.__init__` também levanta `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Seleção de modelo {#模型变量}

O flower lê só três delas para tomar decisões próprias; o resto é carregado e repassado ao SDK.

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nome do modelo principal. Determina também o padrão da janela de [handoff](glossary.md#换代): nome com `1m` ou sem `haiku` → 1 milhão; com `haiku` → 200 mil | nenhum (decidido do lado do endpoint) | não | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapeamento de modelo do nível opus. Se `ANTHROPIC_MODEL` estiver vazia, a decisão da janela cai nela | nenhum | não | `agent.py:78`; `cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapeamento de modelo do nível sonnet. O flower não lê, só carrega e empresta | nenhum | não | `env.py:34`; `cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapeamento de modelo do nível haiku. **A sonda de credenciais prefere esta** | a sonda cai para `ANTHROPIC_MODEL` e depois para `claude-3-5-haiku-20241022` | não | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Qual modelo o [subagent](glossary.md#subagent) usa. O flower não interpreta, quem consome é o SDK | nenhum | não | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Nível de raciocínio. Idem, só carrega sem interpretar | nenhum | não | `env.py:35` |

Se o `flower setup` preencher o nome do modelo, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` e `ANTHROPIC_DEFAULT_SONNET_MODEL` são **escritas as três juntas** (`cli.py:1383-1385`).

### Caminhos e busca {#路径变量}

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `FLOWER_ENV` | Aponta um caminho de `.env` que vem **antes** de todos os outros arquivos | nenhum | não | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Determina o local do arquivo global de credenciais `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | não | `env.py:41-42` |
| `HOME` | Origem de `Path.home()`; os dois caminhos `~/.config` e `~/.claude` derivam dela | dado pelo sistema | não | `env.py:41`, `:67` |

### Chaves de comportamento {#行为开关}

As duas são saídas de emergência: o normal é não definir; definir serve para o flower fazer uma coisa a menos. **Qualquer valor não vazio ativa**, o valor em si não é interpretado (`update.py:121`; `cli.py:1413`).

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | Desliga a [atualização automática](../getting-started/install.md#自动更新). Sem ela, um flower instalado por pip / pipx / uv sobe uma thread em background no start para ver se há versão nova e instala se houver, **valendo só na próxima vez que você rodar `flower`**; verifica no máximo uma vez a cada 24 horas, com o timestamp em `~/.config/flower/.update` | nenhum (atualização automática ligada) | não | `update.py:32-33`, `:121-124` |
| `FLOWER_NO_PROBE` | Pula aquela [sonda de credenciais](cli.md#第二道-凭证能不能用) do start. Em modo não interativo (pipe / CI / stdin redirecionado) já não sonda de qualquer forma; esta variável é a saída para terminais interativos | nenhum (sonda em modo interativo) | não | `cli.py:1413` |

Um flower rodando a partir do código-fonte git não é afetado pela atualização automática, e `FLOWER_NO_UPDATE` é no-op para ele — o passo do comando de update reconhece que há um `.git` no repositório e retorna `None` direto (`update.py:83-87`).

### O que o flower escreve para o subprocesso do agent {#写出的变量}

Estas três são geradas por `CompactPolicy.env()` e enfiadas em `ClaudeAgentOptions.env` (`agent.py:48-58`, `:241-245`), controlando o [compact](glossary.md#压缩) embutido no harness. **Defini-las no seu shell não tem efeito** — o que vale é a cópia que o flower passa ao subprocesso.

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` desliga o compact automático. Com [handoff](glossary.md#换代) ligado é **escrita à força** — com os dois mecanismos rodando juntos não dá para saber quem causou a queda de contexto | handoff vem ligado por padrão, então na prática é sempre `1` | não (o flower escreve) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` desliga também o `/compact`. Só é escrita com `CompactPolicy(mode="off")` | não é escrita | não (o flower escreve) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Janela do compact automático (tokens). Só é escrita com `CompactPolicy(window=N)` | não é escrita | não (o flower escreve) | `agent.py:56-57` |

### Lidas pelo wrapper de container {#容器变量}

Estas duas não são lidas pelo flower em si, e sim pelo wrapper shell `docker/flowerbox`. Uso completo em [deploy](deploy.md).

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `FLOWER_HOME` | Onde procurar o `.env` usado no `--env-file` | diretório acima da posição do próprio script | não | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Qual imagem usar | `flower-box` | não | `docker/flowerbox:13` |

**As chaves do `.env` não se limitam às acima.** O parser carrega **todas** as linhas `k=v` em `os.environ`, sem whitelist (`env.py:30`, `:102-107`). O conjunto `KNOWN`, formado por aquelas 9 chaves de credencial, só atua em dois pontos: como whitelist ao emprestar a configuração de `~/.claude` (`env.py:72`), e como escopo de campos impressos por `describe()` ao subir com `-v` (`env.py:205`).

## Prioridade de busca de credenciais {#凭证查找优先级}

Quando `load_dotenv()` é chamado sem caminho, ele lê em sequência **todos os arquivos existentes** na ordem abaixo (`env.py:45-53`, `:78-112`):

1. **Variáveis de ambiente do processo** — sempre no topo. Nenhum `.env` sobrepõe um valor já exportado. (`env.py:91`)
2. **O arquivo apontado por `$FLOWER_ENV`** — só existe se estiver definida. (`env.py:48-49`)
3. **`$PWD/.env`** — o diretório de trabalho atual. Você faz `cd` num projeto e ele lê o mais próximo. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — o local global, um por pessoa; é este que o `flower setup` escreve. (`env.py:51`, `:39-42`)
5. **O `.env` na raiz do repositório de código** — três níveis acima de `flower/core/env.py`. Só existe rodando a partir do fonte; um flower instalado por pip / pipx / uv fica em site-packages e não tem esta entrada. (`env.py:52`)
6. **O bloco `env` de `~/.claude/settings.json` e depois de `~/.claude/settings.local.json`** — o fallback final, **pegando só as 9 chaves de credencial**. (`env.py:56-75`, `:109-111`)

**Qual arquivo ganha**: o item 3 (`.env` do projeto) ganha do item 4 (`.env` global), o item 4 ganha do item 5 (`.env` da raiz do repositório), os três ganham do item 6 (configuração do Claude Code), e nenhum deles ganha do item 1 (ambiente do processo).

A implementação é "**chave que já tem valor não é sobrescrita**" (`env.py:90-93`): quem vem antes ocupa a chave, quem vem depois só preenche as lacunas. Ou seja, a prioridade é **por chave, não por arquivo** — se o `.env` do projeto só tem `ANTHROPIC_BASE_URL`, o token pode perfeitamente vir do global. O primeiro valor de uma chave homônima define o destino dela.

O item 6 só entra na **busca automática**. Se você passar um caminho explícito (`load_dotenv("/path/to/.env")`), ele lê apenas aquele arquivo, sem nenhum fallback (`env.py:86-87`, `:109`).

### Item 6: emprestar o token do Claude Code {#借用}

Lê em sequência `~/.claude/settings.json` e `~/.claude/settings.local.json`, pega o dict `data["env"]` e seleciona dele estas 9 chaves (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Se o arquivo não existir, não puder ser lido, ou não for JSON válido (`OSError` / `ValueError`), retorna um dict vazio e segue adiante — **um fallback que falha não deve derrubar esta execução** (`env.py:62-63`, `:66-69`).

A posição no código é: o que se empresta é só "onde achar o token"; nada mais do settings.json (regras de permissão, hooks, configuração de modelo) é assumido, então isso não viola a promessa de portabilidade do `setting_sources=[]` (`env.py:17-19`, `:59-61`). O `install.sh:77` divulga isso como um recurso: quem já tem Claude Code configurado na máquina nem chega a ver a tela de configuração.

!!! warning "O texto de erro dentro do produto contradiz o comportamento real"
    Quando nenhuma credencial é encontrada, a última linha do erro que o flower imprime é:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, essa frase está em `:192`; a mesma afirmação aparece ainda em `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **Vale o código: ele lê.** `env.py:56-75` mais `:109-111` vão explicitamente ler aqueles dois arquivos, e o `install.sh:77` ainda usa isso como argumento de venda. Esse texto hoje é enganoso — numa máquina que já tem Claude Code configurado, é bem provável que seu token venha exatamente de lá.

## Regras de parsing do `.env` {#env-解析}

As regras de parsing são curtas o bastante para decorar (`env.py:95-107`, 13 linhas): `strip` em cada linha, pula linhas vazias, linhas começando com `#` e linhas sem `=`; o resto é cortado no **primeiro** `=` em key e value, com `strip` dos dois lados, e o value passa ainda por um `.strip("'\"")` — aspas simples ou duplas no início e no fim são removidas, **sem exigir que sejam pareadas**.

**Reconhece estas formas**:

| Forma | Resultado |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — os espaços em volta do sinal de igual são removidos pelo strip |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — as aspas das pontas são removidas |
| `KEY=a=b` | o value é `a=b` — corta no primeiro `=`, os iguais seguintes ficam no valor |
| `# comentário` | linha inteira pulada |
| linha vazia | pulada |

**Não reconhece estas.** Escrever assim não dá erro, apenas produz silenciosamente um valor inesperado:

| Forma | Resultado real |
|---|---|
| `export KEY=VALUE` | a key vira `export KEY`; a `KEY` em si continua sem valor |
| `KEY=value # comentário` | o value é `value # comentário` — comentário de fim de linha não é removido |
| `KEY=$OTHER` | literal `$OTHER`, sem interpolação de variável |
| valor multilinha (aspas cruzando linhas) | processado linha a linha; a segunda linha não contém `=` e é pulada inteira |

**Um valor vazio ocupa a chave.** Se `ANTHROPIC_AUTH_TOKEN=` aparecer num arquivo de prioridade mais alta, `take()` executa `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, e os arquivos seguintes não conseguem preencher porque "a chave já existe" (`env.py:90-93`); enquanto `check_credentials()` avalia por veracidade, e string vazia conta como não configurado (`env.py:186`). **O resultado é ficar sem credencial e sem fallback.** Se não quer uma chave, apague a linha inteira; não deixe uma vazia.

## O preço da portabilidade {#可移植性}

Aquela única linha em `build_options()` é todo o mecanismo (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` é o padrão do `Runtime`, e **não existe flag de linha de comando para desligar** — só dá pela API Python, escrevendo `Runtime(portable=False)`, o que passa a `["project"]`, ou seja, lê o `.claude/` do projeto.

### O que fica isolado {#被隔绝的东西}

| O que é isolado | Consequência |
|---|---|
| Configurações de `~/.claude/` da máquina host | Regras de permissão, hooks e configuração de modelo de lá não valem. **Credenciais são a única exceção**, ver [empréstimo](#借用) |
| O `.claude/` do projeto | Idem; só é lido com `portable=False` |

Capacidades de domínio não passam por esse caminho — elas são distribuídas junto com o repositório e carregadas via `plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`, `:210-212`), ver [deploy](deploy.md). Já as instruções de domínio são **append** depois do system prompt nativo do Claude Code, não substituição (`agent.py:198-202`), de modo que a especialização não custa a capacidade geral.

### O que levar ao trocar de máquina {#换台机器要带什么}

- **Credenciais: um arquivo**. Copie `~/.config/flower/.env`, ou refaça a configuração na máquina nova. Sem isso nada roda — nada é herdado automaticamente.
- **Estado de continuidade: o diretório inteiro**. `runs/` (session store, manifesto, linhagem) e `.flower/` (workbench).
- **Mas os caminhos precisam bater**. O `lineage.json` guarda o caminho absoluto do workspace; se não bater, é como se não existisse e ele cai silenciosamente numa session nova, **sem erro** (`lineage.py:65-66`). O motivo é que o `project_key` do SDK é derivado do caminho do workspace (`/`, `_` e `.` viram `-`, `runtime.py:40-41`); se o diretório muda de lugar, o `session_id` antigo não é mais encontrado.

## Layout em disco {#磁盘布局}

Uma execução do flower escreve duas árvores: `<run_dir>/` guarda a contabilidade e as sessions, `<workspace>/.flower/` guarda o [workbench](glossary.md#工作台). Por padrão as duas ficam no diretório atual, mas **as bases delas são diferentes**.

!!! warning "`runs/` segue o diretório atual, não o `-w`"
    `-r/--run-dir` tem padrão `"runs"`, e o que o `Runtime` faz com ele é `Path(run_dir).resolve()` (`runtime.py:93-94`) — relativo ao **diretório de trabalho atual**, não ao workspace indicado por `-w`. Rodando `flower -w /path/to/proj` a partir de `~`, o session store vai parar em `~/runs/`, e não dentro do projeto.

### `<run_dir>/` — padrão `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript completo (incluindo a de cada subagent)
  manifest.json      manifesto de execução: session_id / custo / retries / motivo de falha de cada passo, acumulado entre processos
  lineage.json       linhagem: nome do passo → session_id; é por ela que uma nova execução no mesmo diretório retoma
  aside/             Runtime independente das perguntas do oracle, com seus próprios sessions.db + manifest.json
  workbench/         só no caminho run / once e quando -W é passado
```

| Caminho | Conteúdo | Origem |
|---|---|---|
| `runs/sessions.db` | Transcript completo. Quem escreve é o `PruningSessionStore`; as três camadas de política estão [abaixo](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Array JSON, o [manifesto de execução](glossary.md#运行清单) **acumulado entre processos**. Campos na tabela abaixo | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Escreve primeiro `.tmp` e depois `replace`, substituição atômica | `lineage.py:31`, `:87-97` |
| `runs/aside/` | Runtime independente do [oracle](glossary.md#旁路顾问). **Custo e linhagem não se misturam ao manifesto principal** | `cli.py:741-743` |
| `runs/workbench/` | Local padrão do workbench com `Runtime(workbench=True)`, fora do workspace. O caminho `go` não usa | `runtime.py:148-151` |

Cada linha do `manifest.json` é um `asdict(StepResult)` mais dois remendos (`runtime.py:44-71`, `:579-582`):

| Campo | Tipo | Significado |
|---|---|---|
| `step` | `str` | Nome do passo. Quatro formas: `<名>`, `<名>#round<N>` (devolvido para refazer), `<名>#retry<N>` (retry comum), `<名>·判定#<N>` ([juiz](glossary.md#判定者)) |
| `session_id` | `str \| None` | A [session](glossary.md#会话) que ficou viva no fim deste passo |
| `ok` | `bool` | Deu certo ou não |
| `cost_usd` | `float` | Quanto este passo gastou |
| `num_turns` | `int` | Quantos turnos rodou |
| `text` | `str` | A resposta final deste passo |
| `error` | `str \| None` | Motivo da falha. Quando morto por SIGHUP / SIGTERM, é `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Segundos epoch |
| `attempts` | `int` | Número real de tentativas. `>1` indica que houve retry |
| `errors` | `list[str]` | Motivos de todas as falhas. **Só aqui; o modelo não vê** |
| `resumed` | `bool` | Se retomou do ponto de interrupção via resume em vez de recomeçar do zero |
| `retired` | `list[str]` | Os session_id queimados no [handoff](glossary.md#换代) deste passo, em ordem |
| `context` | `int` | O tamanho de contexto que a [thread principal](glossary.md#主线程) realmente viu no último turno |
| `duration_s` | `float` | Remendado à mão — é uma `@property`, e `asdict()` não a captura |
| `run` | `str` | Marca deste processo, `YYYYmmdd-HHMMSS-<6 位 hex>`. **Precisa ser único por instância** |

A estratégia de escrita é **append, não overwrite**: a cada gravação ele relê o arquivo, troca as linhas cujo `run` é o dele mesmo pelas mais recentes e deixa as dos outros intactas (`runtime.py:564-586`). Assim, vários flower rodando em paralelo no mesmo diretório não sobrescrevem a contabilidade um do outro.

O que está em `runs/` é dado puro, e pode ser vasculhado offline a qualquer momento com sqlite3 ou com [`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — o workbench {#工作台目录}

```text
.flower/
  INDEX.md      índice gerado automaticamente, injetado no system prompt do agent principal
  scripts/      scripts que serão executados de novo. A primeira linha `# desc: uma frase` aparece no índice
  artifacts/    saídas longas acima de 2000 caracteres: relatórios, dados, logs
  notes/        registros de decisão que atravessam passos
  spill/        resultados grandes de ferramenta que foram para o spill; nome do arquivo = primeiros 16 dígitos do sha256 do conteúdo + `.txt`
```

Os três subdiretórios e o índice são criados pelo `Workbench` (`workbench.py:73-92`). O `INDEX.md` vai pelo `system_prompt.append` no nível da session, e **subagents não herdam** — por isso a regra "saída longa vai para `artifacts/`" tem que ser repassada pelo [coordenador](glossary.md#协调者) dentro do [task brief](glossary.md#任务书); é o único canal.

O caminho `go` gera sempre estes arquivos em `notes/`:

| Arquivo | Conteúdo | Origem |
|---|---|---|
| `notes/需求.md` | O [brief](glossary.md#需求确认书) congelado, em quatro seções: objetivo / critérios de aceite / fronteiras / incógnitas e premissas | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Duas seções congeladas: objetivo / checklist de veredito | `workflow/goal.py:124` |
| `notes/问答记录.md` | Registro acumulado de todas as perguntas e respostas, incluindo os itens da caixa de entrada em que "a pessoa falou por iniciativa própria". **Não entra no contexto, é só arquivo** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | O [documento de handoff](glossary.md#交接书). A geração anterior é recolhida em `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | O `lineage.json` + `需求.md` + `目标.md` arquivados por `--new` / `/new` (**movidos, não apagados**) | `lineage.py:100-117` |

**Com `--isolate`, o workbench sai do repositório**: `<diretório pai do workspace>/.flower-<nome do workspace>/` (`starter.py:47-55`). O worktree é a cópia privada de cada agent, e o workbench é a camada compartilhada entre agents; o que é compartilhado não pode ficar dentro da cerca privada. Nesse caso, o caminho dado ao modelo é absoluto (`workbench.py:69-71`, `:142-145`).

**O `spill/` tem dois escritores, com algoritmos de destino diferentes**:

| Quem escreve | Quando | Onde escreve | Limiar |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **antes** de o resultado da ferramenta entrar no modelo | `<root do workbench>/spill/` (`guard.py:130`) | `spill_threshold`, padrão 4000 caracteres |
| `TrimPolicy` (no `load`) | ao reproduzir o histórico antes do resume | `<workspace>/.flower/spill/` — string fixa relativa ao workspace (`trim.py:49`, `:303`) | `min_chars`, padrão 2000 caracteres |

No layout padrão é o mesmo diretório. Mas quando o workbench é movido (com `-W`, caindo em `runs/workbench/`, ou com `--isolate`, caindo fora do repositório) os dois se separam — a parte do `TrimPolicy` fica sempre dentro do workspace, porque o `Read` do agent precisa alcançá-la.

O que o `spill_guard` coloca no lugar não é uma linha, é uma linha de ponteiro mais os **primeiros 400 caracteres** (`guard.py:132-140`). As chamadas que leem o próprio arquivo do spill são liberadas, senão "use Read para pegar o texto completo" seria conversa fiada — leria de volta, passaria do limiar, iria para o spill de novo, num laço infinito (`guard.py:155-170`).

### Estrutura de tabelas do `sessions.db` {#sessions-db}

Três tabelas, com os CREATE em `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| Tabela | O que é uma linha | Pontos-chave |
|---|---|---|
| `entries` | Um item do transcript; `payload` é o JSON original | `uid` é o `uuid` do item, servindo de **chave de idempotência**: lotes que falham são repetidos até 3 vezes, e a repetição não pode gerar linhas duplicadas. Itens sem `uuid` (título, tags, marcas de modo) não são deduplicados, por isso o índice único tem `WHERE uid IS NOT NULL` |
| `meta` | O cursor de uma session | `next_seq` é o próximo número de sequência, e `mtime` é um timestamp em milissegundos **estritamente monotônico** (`sqlite.py:72-79`) — `list_sessions` e o summary compartilham esse relógio, e sem monotonicidade a comparação de novo/velho do SDK entra no caminho rápido errado |
| `summaries` | O sidecar de resumo de uma thread principal | **Só o transcript principal participa**; o de subagent não conta (`sqlite.py:122-123`) |

Construção do `store_key` (`sqlite.py:54-58`): `<project_key>/<session_id>`, e para subagent acrescenta-se ainda um `subpath`. O `project_key` é derivado pelo SDK a partir do caminho do workspace — `/`, `_` e `.` viram `-`.

Uma olhada numa amostra real ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Aquela amostra tem 956 `entries`, 10 `meta` e 4 `summaries` — das 10 sessions, 4 são transcript principal e 6 são de subagent, e `summaries` bate exatamente com o número de transcripts principais.

## As três camadas do session store {#会话存储}

!!! note "As três camadas são uma cadeia de herança, não uma combinação opcional"
    `PruningSessionStore` herda de `TrimmingSessionStore`, que herda de `SqliteSessionStore`. O `Runtime` **sempre** constrói o mais externo (`runtime.py:109-112`), e não há nos parâmetros de construção nenhuma entrada para trocar de backend. A forma de "desligar uma camada" é pôr `enabled` como `False` no objeto de política dela, não trocar de classe.

O `append` (escrita) sempre grava tudo, sem mudar uma palavra. As três camadas só afetam o `load` (a cópia que volta para o modelo). A ordem real do `load` é:

```text
SqliteSessionStore.load     lê tudo da tabela entries por seq
  → TrimmingSessionStore.expire()   resultados de Bash sensíveis ao tempo → viram "expirado"
  → TrimmingSessionStore.trim()     tool_result grandes e antigos → spill + ponteiro
    → PruningSessionStore.prune()   mensagens de erro sintéticas / chamadas negadas antigas → item removido e cadeia religada
```

| Camada | Classe | O que descarta | Critério |
|---|---|---|---|
| 1 | `SqliteSessionStore` | não descarta nada | — |
| 2 | `TrimmingSessionStore` | corpo de resultados grandes de ferramenta, resultados expirados de comandos efêmeros | volume + validade temporal |
| 3 | `PruningSessionStore` | resíduo de queda de conexão, chamadas negadas antigas | se é erro ou não |

A camada 2 é [trim](glossary.md#裁剪) e a camada 3 é [prune](glossary.md#剪除) — **trim descarta por volume e valor, prune descarta por "é erro ou não"**; não confunda. As assinaturas completas estão na [API Python](api.md).

### `SqliteSessionStore` — a fundação {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implementação SQLite sem dependências externas. Para trocar por Postgres / S3 / Redis, basta implementar o mesmo protocolo; o SDK traz a suíte de testes de conformidade `claude_agent_sdk.testing.session_store_conformance`, que valida direto (`sqlite.py:1-8`).

Além dos métodos do protocolo, há três consultas **síncronas** para uso do próprio flower:

| Método | Retorno | Uso |
|---|---|---|
| `projects()` | `list[str]` | Os `project_key` que realmente existem no banco. O SDK deriva isso do cwd; confirme com esta consulta antes de consultar, não chute |
| `has_session(project_key, session_id)` | `bool` | Consulta só uma linha de `meta`, sem ler payload. Consulte antes de começar a [continuidade](glossary.md#接续) — dar resume numa session inexistente só explode depois que o subprocesso subiu, e aí já se gastou dinheiro e tempo |
| `last_context(project_key, session_id, scan=60)` | `int` | Quanto contexto esta session viu no último turno. Varre de trás para frente só os últimos 60 itens. `input_tokens` mais os dois `cache_*` entram na conta — olhar só o primeiro, com cache hit, dá quase 0 e subestima gravemente |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Duas regras ortogonais. A `TrimPolicy` cuida do **volume**:

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Os N `tool_result` mais recentes ficam com o texto original — contexto em uso não deve ser trimado |
| `min_chars` | `int` | `2000` | Nada menor que isso é trimado. Trocar por ponteiro sairia mais caro em tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Diretório de arquivo, **relativo ao workspace**. Precisa estar dentro do workspace, senão o `Read` do agent não alcança |
| `enabled` | `bool` | `True` | É `False` com `Runtime(trim=False)` (o padrão) |

O corpo trimado é escrito como `<primeiros 16 dígitos do sha256>.txt`, e no lugar original entra `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

A `EphemeralPolicy` cuida da **validade temporal**: resultados de `git status`, `ls`, `ps` e afins são curtos, e por volume nunca seriam trimados, mas a correção deles decai com o tempo — aquele `git status` de 20 turnos atrás não é "inútil", ele **engana**.

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Convertido de `Runtime(ephemeral=…)`; **ligado por padrão** |
| `keep_recent` | `int` | `6` | Os N mais recentes ficam com o texto original. Bem menor que os 20 da `TrimPolicy` — a janela de "recente" desse tipo de coisa é curta mesmo |
| `max_chars` | `int` | `2000` | Acima disso passa para a `TrimPolicy` arquivar no spill, e não segue por este caminho |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texto de substituição |

Age apenas sobre resultados da ferramenta **Bash**, e o comando precisa casar com `EPHEMERAL_CMD`. `Read` não entra: o conteúdo de um arquivo não se distorce com o tempo a ponto de enganar, e pode ser justamente a base do raciocínio do modelo (`trim.py:153-160`). Conteúdo expirado **não vai para o spill** — arquivar um `git status` expirado não tem sentido, basta rodar de novo.

A função de decisão é `is_ephemeral(cmd)`, e ela **é ao mesmo tempo a lista de permissões devolvida ao coordenador**: `delegate_guard(allow_glance=True)` usa a mesma função (`trim.py:63-68`, `:128-150`). Os dois conjuntos têm que ser sempre iguais — liberar sem trimar faz um `git status` expirado ocupar contexto para sempre; trimar sem liberar faz o coordenador despachar um subagent para um `ls`, trocando 4.3k de custo de inicialização por algumas dezenas de caracteres. Acrescentar um comando à whitelist equivale a dizer as duas coisas ao mesmo tempo.

**Quando usar o quê**:

- Só quer que o resíduo de queda de conexão não entre no contexto → não precisa fazer nada, o `Runtime` já usa `PruningSessionStore` por padrão. `trim=False` apenas deixa de trimar resultados grandes; a remoção continua acontecendo.
- Execução longa, com saídas de ferramenta muito grandes → `trim=True`. No caminho `go` o CLI já vem com isso ligado; use `--no-trim` para desligar.
- [Coordenador](glossary.md#协调者) com `glance=True` → `ephemeral` precisa continuar ligado, pelo motivo do parágrafo anterior.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Remove mensagens sintéticas com `isApiErrorMessage=true` ou `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Para `tool_result` com `[Request interrupted …]`, **troca o corpo, não remove o bloco** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texto de substituição do item anterior |
| `heal_orphans` | `bool` | `True` | **Acrescenta** um resultado sintético para chamadas órfãs, com `tool_use` mas sem `tool_result` |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | Corpo do `tool_result` acrescentado |
| `keep_denials` | `int` | `1` | Mantém as N chamadas de ferramenta mais recentes negadas pelo permission hook; as mais antigas são removidas **junto com a chamada e o resultado** |

`keep_denials` é o único parâmetro de construção do `Runtime` que é repassado a esta camada (`Runtime(keep_denials=N)`). O motivo de o padrão ser 1 e não 0: a negação mais recente é sinal útil e evita que o modelo repita o mesmo comando bloqueado várias vezes no mesmo turno. **Não aumente** — uma chamada negada nunca foi executada, não há informação alguma no resultado, e na medição cada uma ocupa 273 caracteres (93 caracteres de mensagem de recusa mais 180 caracteres do comando morto original); além disso, ela **engana**: na prática, depois de ler algumas mensagens do tipo "não use Bash diretamente", o coordenador parava de tentar até o `git status` que era liberado, dizendo direto "o Bash está restrito, manda um agent olhar" (`prune.py:135-148`).

`heal_orphans` trata o caso de **cada resume dar 400 depois de uma interrupção**: a interrupção corta na fronteira de mensagem, e o `tool_use` que estava em voo pode simplesmente não ter um `tool_result` depois dele, sendo que a API exige que venham em par. Esse histórico ruim fica no transcript e não some sozinho, então todo resume seguinte é rejeitado por ele. A correção insere um item `user` logo depois daquele assistant que contém os órfãos, preenchendo de uma vez os resultados de todos os órfãos daquele item, e depois muda o `parentUuid` que apontava para aquele assistant para apontar para o item inserido (`prune.py:95-147`). **Acrescenta em vez de apagar**: apagar órfãos exigiria religar a cadeia pai-filho, e o mesmo assistant pode ter blocos normais, texto e thinking, que seriam levados junto (`prune.py:195-204`).

Três linhas vermelhas estruturais; violá-las faz a API dar erro na hora:

1. **O próprio bloco `tool_result` precisa existir**, só o `content` pode ser trocado. Faltar um é "Missing Tool Result Block" (`trim.py:20-22`; `prune.py:79-92`).
2. **Itens `isCompactSummary` / `isMeta` não podem ser mexidos** — são a única forma de existência daquele trecho de histórico que foi comprimido (`trim.py:179-181`).
3. **Ao remover um item é obrigatório religar os filhos dele ao pai dele**. O transcript é uma cadeia simples por `parentUuid`, e o harness caminha das folhas para trás; onde a cadeia quebra, todo o histórico anterior se perde (`prune.py:95-122`). Por isso `relink()` precisa receber a lista completa **incluindo** os itens a remover, e faz a filtragem por conta própria.

**Nenhuma palavra do original no SQLite é alterada** — as três camadas só afetam "a cópia que volta para o modelo" (`trim.py:18`; `prune.py:8`).

## Resiliência a queda de rede {#韧性}

Um workflow long-horizon roda por horas, e a rede vai cair pelo menos uma vez. O comportamento padrão é péssimo: no instante da queda o harness enfia no transcript uma mensagem assistant sintética (`model="<synthetic>"`, `isApiErrorMessage=true`) com o corpo `API Error: Can't reach the API server …`; ela vira a folha da session, e no resume seguinte é devolvida ao modelo como "a última coisa que o modelo disse", fazendo o modelo achar que está discutindo uma falha de rede; e ainda se mistura ao `StepResult.text`, sendo propagada pelo workflow para o prompt do passo seguinte (`resilience.py:1-22`).

A camada de [resiliência](glossary.md#韧性) faz três coisas, e nenhuma pode faltar: sonda, continuar em vez de recomeçar, e erro fora do contexto.

### Parâmetros de `Resilience` {#resilience}

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Convertido de `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Quantas tentativas no máximo por [passo](glossary.md#步骤), **incluindo a primeira** |
| `base_delay` | `float` | `4.0` | Ponto de partida do backoff exponencial, em segundos |
| `max_delay` | `float` | `120.0` | Teto do backoff, em segundos |
| `probe_timeout` | `float` | `5.0` | Timeout de uma sonda, em segundos |
| `probe_interval` | `float` | `15.0` | De quanto em quanto tempo sondar com a rede caída, em segundos |
| `max_offline_wait` | `float` | `3600.0` | Quanto esperar no máximo com a rede caída. Padrão de 1 hora — mais que isso normalmente não é oscilação, é problema de verdade |
| `retry_unknown` | `bool` | `True` | Também repete erros não classificáveis. A maioria dos erros desconhecidos é transitória, e os fatais já foram barrados à parte |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | O que é dito ao modelo ao continuar |

Fórmula do backoff (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Ou seja, jitter de `±25%`, para evitar que um monte de processos se atire junto no instante em que a rede volta. Com os padrões: 1ª espera de 4 segundos (na prática 3~5), 2ª de 8 segundos (6~10), da 5ª em diante teto de 120 segundos (90~150).

### Estratégia da sonda {#探针}

- **Sonda o host:port de `ANTHROPIC_BASE_URL`**, não `api.anthropic.com` (`resilience.py:67-72`). Com gateway próprio, o segundo responder não diz nada sobre o primeiro.
- **Só DNS mais handshake TCP**: `getaddrinfo`, depois `connect_tcp`, e fecha em seguida. Não manda HTTP, não leva credencial, não custa nada (`resilience.py:75-85`). A sonda precisa ser gratuita, senão "sondar a cada 15 segundos com a rede caída" vira ela mesma uma falha.
- Qualquer falha conta como inacessível — não distingue DNS caído de TCP recusado.
- `wait_online()` fica ali esperando: retorna `True` se voltar, e `False` se estourar `max_offline_wait`. Na primeira vez que fica inacessível, notifica uma linha `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, e ao voltar notifica outra linha `<host>:<port> 恢复,继续`, **sem encher a tela no meio** (`resilience.py:126-140`).

Aquela sonda de credenciais antes de começar é outra coisa: ela realmente dispara um `POST <BASE_URL>/v1/messages` com `max_tokens=16` e timeout padrão de 20 segundos (`env.py:126-181`). **Não coloque `max_tokens` em 1** — na medição, modelos com cadeia de raciocínio forçada não cabem nem o raciocínio, e o servidor se debate até 30 segundos para responder; com 16 leva apenas 3.6 segundos (`env.py:120-123`).

### Classificação de erros {#错误分类}

`classify(text)` devolve uma de três. **Avalia fatal primeiro**: textos de 401 e afins costumam trazer palavras como "connection", e com a ordem invertida o processo espera para sempre (`resilience.py:53-64`).

| Classe | O que casa (regex em `resilience.py:37-50`) | Comportamento |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Para na hora, sem retry. Repetir dá o mesmo resultado quantas vezes for, e cada vez custa dinheiro |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Espera a rede voltar e então continua via resume |
| `unknown` | não casa com nada | Com `retry_unknown=True` (padrão), também repete |

Separar o que é repetível do que não é é o núcleo desta camada: **oscilação de rede merece espera, credencial errada merece parada imediata** — esperar com a rede caída é o certo; esperar com a key errada é queimar tempo.

### O que fica barrado fora do contexto {#错误不进上下文}

1. **Mensagens de erro sintéticas**. O `PruningSessionStore` remove o item inteiro no `load` e religa o `parentUuid` (`prune.py:27-32`, `:191-195`). **Fica intacto no SQLite**, só não é devolvido ao modelo.
2. **No stream de eventos ele é `kind="error"` e não `"text"`**, então não entra em `StepResult.text` e portanto não é propagado pelo workflow para o prompt do passo seguinte (`resilience.py:17-18`).
3. **O `resume_prompt` deliberadamente não traz nenhum detalhe do erro**. O modelo precisa saber "fui interrompido, continue"; não precisa saber se foi `ENOTFOUND` ou `503`. **Isso pertence ao log, não ao contexto** (`resilience.py:112-113`). O log está no campo `errors` do `manifest.json`.

Continuar em vez de recomeçar: quando a falha acontece o `session_id` já foi obtido, então o resume retoma do ponto de interrupção e o que já foi gasto não é jogado fora.

## Relacionados {#相关}

- [Linha de comando](cli.md) — como cada flag mapeia para a configuração desta página.
- [API Python](api.md) — assinaturas completas de `Runtime`, dos três stores e de `Resilience`.
- [Deploy](deploy.md) — rodar em container, distribuir capacidades de domínio via plugin.
- [Glossário](glossary.md) — o significado exato de cada termo usado nesta página.
