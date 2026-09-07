# Configuração

flower não tem formato de arquivo de configuração, nem um subcomando de configuração que dê para
usar de verdade — toda a configuração é feita por **variáveis de ambiente** mais **arquivos `.env`**,
mais um punhado de objetos de política que só podem ser passados pelo lado Python. Esta página junta
num só lugar o que está espalhado por cinco: cada variável, em que ordem as credenciais são
procuradas, que sintaxe o `.env` aceita, o que exatamente `setting_sources=[]` isola, o que uma run
deixa em disco, o que cada uma das três camadas do session store descarta, e como ele espera quando a
rede cai. A terminologia segue o [glossário](glossary.md).

| Quer saber | Vá para |
|---|---|
| Quais variáveis de ambiente o flower lê | [Tabela completa de variáveis de ambiente](#环境变量) |
| De onde afinal veio meu token | [Prioridade de busca de credenciais](#凭证查找优先级) |
| Por que aquela linha do `.env` não teve efeito | [Regras de parsing do `.env`](#env-解析) |
| O que levar ao trocar de máquina | [O preço da portabilidade](#可移植性) |
| O que tem dentro de `.flower/` e `runs/` | [Layout em disco](#磁盘布局) |
| Quais mensagens não voltam para o modelo | [As três camadas do session store](#会话存储) |
| O que ele está esperando quando a rede cai | [Resiliência a queda de rede](#韧性) |

## Tabela completa de variáveis de ambiente {#环境变量}

Quatro grupos: credenciais e endpoint que o flower lê diretamente, seleção de modelo, busca de
caminhos, e as que o flower **escreve para** o subprocesso do agent. O último grupo você não precisa
definir — e se definir, será sobrescrito.

### Credenciais e endpoint {#凭证变量}

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Key oficial da Anthropic. Se existir, a requisição usa o header `x-api-key` | nenhum | **obrigatória em conjunto com** `ANTHROPIC_AUTH_TOKEN` (uma das duas) | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token emitido por gateway. Sem `ANTHROPIC_API_KEY`, usa `authorization: Bearer` | nenhum | idem | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | Raiz do endpoint da API. Gateways de terceiros põem o próprio endereço, **sem `/v1`** — a sonda monta `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | não | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

Se nenhuma das duas estiver definida (ou ambas forem string vazia), `check_credentials()` retorna
aquele erro de quatro linhas e `Runtime.__init__` levanta `RuntimeError`
(`env.py:184-194`;`runtime.py:156-158`).

### Seleção de modelo {#模型变量}

O flower lê apenas três delas para tomar decisões próprias; as demais são carregadas e repassadas ao
SDK.

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nome do modelo principal. Também define o valor padrão da janela de [handoff](glossary.md#换代): se o nome contém `1m` ou não contém `haiku` → 1 milhão; se contém `haiku` → 200 mil | nenhum (decidido do lado do cliente) | não | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapeamento de modelo da faixa opus. Com `ANTHROPIC_MODEL` vazio, a decisão da janela recai sobre ela | nenhum | não | `agent.py:78`;`cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapeamento de modelo da faixa sonnet. O flower não lê, só carrega e toma emprestado | nenhum | não | `env.py:34`;`cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapeamento de modelo da faixa haiku. **A sonda de credenciais usa esta primeiro** | a sonda recai em `ANTHROPIC_MODEL`, depois em `claude-3-5-haiku-20241022` | não | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Qual modelo o [subagent](glossary.md#subagent) usa. O flower não interpreta, quem consome é o SDK | nenhum | não | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Nível de esforço de raciocínio. Idem, só carrega, não interpreta | nenhum | não | `env.py:35` |

Se o `flower setup` preencher o nome do modelo, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` e
`ANTHROPIC_DEFAULT_SONNET_MODEL` são **escritas as três juntas** (`cli.py:1204-1206`).

### Caminhos e busca {#路径变量}

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `FLOWER_ENV` | Aponta para um arquivo `.env` específico, que vem **antes** de todos os outros | nenhum | não | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Define onde fica o arquivo global de credenciais: `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | não | `env.py:41-42` |
| `HOME` | Origem de `Path.home()`; tanto `~/.config` quanto `~/.claude` são derivados dela | dado pelo sistema | não | `env.py:41`、`:67` |

### O que o flower escreve para o subprocesso do agent {#写出的变量}

Estas três são geradas por `CompactPolicy.env()` e injetadas em `ClaudeAgentOptions.env`
(`agent.py:48-58`、`:241-245`), controlando o [compact](glossary.md#压缩) embutido no harness.
**Defini-las no seu shell não tem efeito** — o que vale é a cópia que o flower passa ao subprocesso.

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` desliga o compact automático. Com [handoff](glossary.md#换代) ligado é **escrita à força** — dois mecanismos rodando ao mesmo tempo tornam impossível saber quem causou a queda de contexto | handoff vem ligado por padrão, então na prática é sempre `1` | não (quem escreve é o flower) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` desliga até o `/compact`. Só é escrita com `CompactPolicy(mode="off")` | não escrita | não (quem escreve é o flower) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Janela do compact automático (tokens). Só é escrita com `CompactPolicy(window=N)` | não escrita | não (quem escreve é o flower) | `agent.py:56-57` |

### Lidas pelo wrapper de container {#容器变量}

Estas duas não são lidas pelo flower em si, e sim pelo wrapper shell `docker/flowerbox`. Uso completo
em [deploy](deploy.md).

| Variável | Função | Padrão | Obrigatória | Origem |
|---|---|---|---|---|
| `FLOWER_HOME` | Onde procurar o `.env` que será passado em `--env-file` | diretório acima do próprio script | não | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Qual imagem usar | `flower-box` | não | `docker/flowerbox:13` |

**As chaves no `.env` não se limitam às acima.** O parser carrega **todas** as linhas `k=v` em
`os.environ`, sem lista branca (`env.py:30`、`:102-107`). O `KNOWN`, formado por aquelas 9 chaves de
credencial, só atua em dois pontos: como lista branca ao tomar emprestada a configuração de
`~/.claude` (`env.py:72`), e como conjunto de campos impressos por `describe()` quando se usa `-v`
(`env.py:205`).

## Prioridade de busca de credenciais {#凭证查找优先级}

Quando `load_dotenv()` é chamado sem caminho, ele lê **todos os arquivos existentes** na ordem abaixo
(`env.py:45-53`、`:78-112`):

1. **Variáveis de ambiente do processo** — sempre no topo. Nenhum `.env` sobrepõe um valor já exportado. (`env.py:91`)
2. **O arquivo apontado por `$FLOWER_ENV`** — só existe se estiver definida. (`env.py:48-49`)
3. **`$PWD/.env`** — o diretório de trabalho atual. Você faz `cd` para um projeto e ele lê o `.env` de lá. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — o local global, um por usuário; é o que o `flower setup` escreve. (`env.py:51`、`:39-42`)
5. **O `.env` na raiz do repositório de código-fonte** — três níveis acima de `flower/core/env.py`. Só existe se você rodar a partir do código-fonte; um flower instalado via pip / pipx / uv fica em site-packages e não tem esse item. (`env.py:52`)
6. **O bloco `env` de `~/.claude/settings.json`, e depois de `~/.claude/settings.local.json`** — o último fallback, **pegando apenas as 9 chaves de credencial**. (`env.py:56-75`、`:109-111`)

**Qual arquivo vence**: o item 3 (`.env` do projeto) vence o item 4 (`.env` global), o item 4 vence o
item 5 (`.env` da raiz do repositório), os três vencem o item 6 (configuração do Claude Code), e todos
perdem para o item 1 (ambiente do processo).

A implementação é "**chave que já tem valor não é sobrescrita**" (`env.py:90-93`): quem vem primeiro
ocupa a chave, e os seguintes só preenchem lacunas. Ou seja, a prioridade é **por chave, não por
arquivo** — se o `.env` do projeto só define `ANTHROPIC_BASE_URL`, o token pode perfeitamente vir do
global. Para chaves de mesmo nome, o primeiro valor encontrado vale para sempre.

O item 6 só entra em cena na **busca automática**. Se um caminho for dado explicitamente
(`load_dotenv("/path/to/.env")`), só aquele arquivo é lido, sem nenhum fallback
(`env.py:86-87`、`:109`).

### Item 6: tomar emprestado o token do Claude Code {#借用}

Ele lê, nessa ordem, `~/.claude/settings.json` e `~/.claude/settings.local.json`, pega o dict
`data["env"]` e seleciona estas 9 chaves (`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Se o arquivo não existir, não puder ser lido, ou não for JSON válido (`OSError` / `ValueError`), ele
retorna um dict vazio e segue adiante — **um fallback que falha não deve derrubar a run**
(`env.py:62-63`、`:66-69`).

A posição no código é: o que se toma emprestado é apenas "onde encontrar o token"; nada mais do
settings.json (regras de permissão, hooks, configuração de modelo) é assumido, então isso não viola a
promessa de portabilidade do `setting_sources=[]` (`env.py:17-19`、`:59-61`). O `install.sh:77` chega a
anunciar isso como feature: quem já tem Claude Code configurado na máquina nem vê a tela de
configuração.

!!! warning "O texto de erro dentro do produto contradiz o comportamento real"
    Quando nenhuma credencial é encontrada, a última linha do erro que o flower imprime é:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, a frase está em `:192`; a mesma afirmação aparece em `.env.example:2`,
    `env.py:3-4`, `agent.py:10-12`.) **Vale o código: ele lê.** `env.py:56-75` mais `:109-111` leem
    explicitamente aqueles dois arquivos, e o `install.sh:77` ainda usa isso como argumento de venda.
    Esse texto hoje é enganoso — numa máquina que já tem Claude Code configurado, seu token muito
    provavelmente veio de lá.

## Regras de parsing do `.env` {#env-解析}

As regras são curtas o bastante para decorar (`env.py:95-107`, 13 linhas): `strip` linha a linha,
pulando linhas vazias, linhas começadas com `#` e linhas sem `=`; o restante é cortado no **primeiro**
`=` em chave e valor, cada lado leva um `strip`, e o valor passa ainda por `.strip("'\"")` — aspas
simples ou duplas no começo e no fim são removidas, **sem exigir que estejam pareadas**.

**Ele aceita isto**:

| Escrita | Resultado |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — os espaços em volta do sinal de igual são removidos pelo strip |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — as aspas nas pontas são removidas |
| `KEY=a=b` | o valor é `a=b` — corta no primeiro `=`, os demais ficam no valor |
| `# comentário` | linha inteira ignorada |
| linha vazia | ignorada |

**Ele não aceita isto**. Escrever assim não dá erro; você só recebe silenciosamente um valor
inesperado:

| Escrita | Resultado real |
|---|---|
| `export KEY=VALUE` | a chave vira `export KEY`, e `KEY` continua sem valor |
| `KEY=value # explicação` | o valor é `value # explicação` — comentário de fim de linha não é removido |
| `KEY=$OTHER` | o literal `$OTHER`, sem interpolação de variável |
| valor multilinha (com aspas atravessando linhas) | processa linha a linha; a segunda linha não tem `=` e é ignorada inteira |

**Um valor vazio ocupa a chave.** Se `ANTHROPIC_AUTH_TOKEN=` aparece num arquivo de prioridade alta,
`take()` executa `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, e os arquivos seguintes não conseguem
preencher porque "a chave já existe" (`env.py:90-93`); já `check_credentials()` avalia veracidade, e
string vazia conta como não configurada (`env.py:186`). **O resultado é ficar sem credencial e sem
fallback.** Se não quiser uma chave, apague a linha inteira em vez de deixá-la vazia.

## O preço da portabilidade {#可移植性}

Todo o mecanismo está naquela linha de `build_options()` (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` é o padrão do `Runtime`, e **não existe flag de linha de comando para desligar** —
para desligar, só pela API Python, escrevendo `Runtime(portable=False)`, o que passa a `["project"]`,
ou seja, lê o `.claude/` do projeto.

### O que fica isolado

| O que fica isolado | Consequência |
|---|---|
| Configurações de `~/.claude/` da máquina host | Regras de permissão, hooks e configuração de modelo de lá não valem. **A credencial é a única exceção**, veja [tomar emprestado](#借用) |
| O `.claude/` do projeto | Idem; só é lido com `portable=False` |

Capacidade de domínio não passa por esse caminho — ela é distribuída junto com o repositório e
carregada via `plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`、`:210-212`), veja
[deploy](deploy.md). Já as instruções de domínio são **append** ao system prompt nativo do Claude
Code, não substituição (`agent.py:198-202`), de modo que a especialização não custa a capacidade
geral.

### O que levar ao trocar de máquina

- **Credenciais: um arquivo**. Basta copiar `~/.config/flower/.env`, ou reconfigurar na máquina nova.
  Sem isso nada roda — nada é herdado automaticamente.
- **Estado de continuidade: o diretório inteiro**. `runs/` (banco de sessões, manifesto, linhagem) e
  `.flower/` (workbench).
- **Mas os caminhos precisam bater**. O `lineage.json` guarda o caminho absoluto do workspace; se não
  bater, é como se não existisse — volta silenciosamente para uma sessão nova, **sem erro**
  (`lineage.py:65-66`). O motivo é que o `project_key` do SDK é derivado do caminho do workspace
  (`/`, `_` e `.` viram `-`, `runtime.py:40-41`); se o diretório muda de lugar, o `session_id` antigo
  não é mais encontrado.

## Layout em disco {#磁盘布局}

Uma run do flower escreve duas árvores: `<run_dir>/` guarda a contabilidade e as sessões,
`<workspace>/.flower/` guarda o [workbench](glossary.md#工作台). Ambas ficam por padrão sob o
diretório atual, mas **suas bases são diferentes**.

!!! warning "`runs/` acompanha o diretório atual, não o `-w`"
    `-r/--run-dir` tem padrão `"runs"`, e o que o `Runtime` faz com ele é `Path(run_dir).resolve()`
    (`runtime.py:93-94`) — relativo ao **diretório de trabalho atual**, não ao workspace indicado por
    `-w`. Rodar `flower -w /path/to/proj` a partir de `~` faz o banco de sessões cair em `~/runs/`,
    não dentro do projeto.

### `<run_dir>/` — padrão `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript completo (inclui o de cada subagent)
  manifest.json      manifesto da run: session_id / custo / retentativas / motivo da falha de cada passo, acumulado entre processos
  lineage.json       linhagem: nome do passo → session_id, é o que permite retomar ao rodar de novo no mesmo diretório
  aside/             Runtime independente das perguntas ao oráculo, com sessions.db + manifest.json próprios
  workbench/         só no caminho run / once e quando -W foi passado
```

| Caminho | Conteúdo | Origem |
|---|---|---|
| `runs/sessions.db` | Transcript completo. Quem escreve é o `PruningSessionStore`; as três camadas de política estão [mais abaixo](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Array JSON, o [manifesto da run](glossary.md#运行清单) **acumulado entre processos**. Campos na tabela abaixo | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Escreve `.tmp` primeiro e depois faz `replace`, substituição atômica | `lineage.py:31`、`:87-97` |
| `runs/aside/` | Runtime independente do [oráculo](glossary.md#旁路顾问). **Custo e linhagem não se misturam ao manifesto principal** | `cli.py:632-634` |
| `runs/workbench/` | Local padrão do workbench com `Runtime(workbench=True)`, fora do workspace. O caminho `go` não usa isso | `runtime.py:148-151` |

Cada linha do `manifest.json` é um `asdict(StepResult)` mais dois remendos
(`runtime.py:44-71`、`:579-582`):

| Campo | Tipo | Significado |
|---|---|---|
| `step` | `str` | Nome do passo. Quatro formas: `<名>`, `<名>#round<N>` (devolvido para refazer), `<名>#retry<N>` (retentativa comum), `<名>·判定#<N>` ([juiz](glossary.md#判定者)) |
| `session_id` | `str \| None` | A última [sessão](glossary.md#会话) viva deste passo |
| `ok` | `bool` | Deu certo ou não |
| `cost_usd` | `float` | Quanto este passo custou |
| `num_turns` | `int` | Quantos turnos rodaram |
| `text` | `str` | A resposta final deste passo |
| `error` | `str \| None` | Motivo da falha. Ao ser morto por SIGHUP / SIGTERM é `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Segundos epoch |
| `attempts` | `int` | Número real de tentativas. `>1` significa que houve retentativa |
| `errors` | `list[str]` | Motivos de todas as falhas anteriores. **Só aqui; o modelo não vê** |
| `resumed` | `bool` | Se retomou do ponto de interrupção via resume em vez de começar do zero |
| `retired` | `list[str]` | Os session_id queimados no [handoff](glossary.md#换代) deste passo, em ordem |
| `context` | `int` | Tamanho de contexto que a [thread principal](glossary.md#主线程) de fato viu no último turno |
| `duration_s` | `float` | Preenchido à mão — é uma `@property`, e `asdict()` não a captura |
| `run` | `str` | Marca deste processo: `YYYYmmdd-HHMMSS-<6 dígitos hex>`. **Precisa ser único por instância** |

A estratégia de escrita é **append, não overwrite**: a cada gravação o arquivo é relido, as linhas cujo
`run` é o próprio são substituídas pelas mais recentes, e as linhas dos outros ficam intactas
(`runtime.py:564-586`). Assim vários flower rodando em paralelo no mesmo diretório não zeram a
contabilidade uns dos outros.

O que está em `runs/` é dado puro; dá para inspecionar offline a qualquer momento com sqlite3 ou com
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — o workbench {#工作台目录}

```text
.flower/
  INDEX.md      índice gerado automaticamente, injetado no system prompt do agent principal
  scripts/      scripts que vão rodar uma segunda vez. A primeira linha `# desc: uma frase` aparece no índice
  artifacts/    saídas longas, acima de 2000 caracteres: relatórios, dados, logs
  notes/        registros de decisão entre passos
  spill/        resultados grandes de ferramenta jogados em disco, nome do arquivo = primeiros 16 dígitos do sha256 do conteúdo + `.txt`
```

Os três subdiretórios mais o índice são criados pelo `Workbench` (`workbench.py:73-92`). O `INDEX.md`
vai por `system_prompt.append` no nível da sessão, e **subagents não herdam isso** — por isso a regra
"saída longa vai para `artifacts/`" precisa ser repassada pelo [coordenador](glossary.md#协调者)
dentro do [task brief](glossary.md#任务书); esse é o único canal.

O caminho `go` gera sempre estes arquivos sob `notes/`:

| Arquivo | Conteúdo | Origem |
|---|---|---|
| `notes/需求.md` | O [brief](glossary.md#需求确认书) congelado, quatro seções: objetivo / critérios de aceite / limites / incógnitas e premissas | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | As duas seções congeladas: objetivo / checklist de verdict | `workflow/goal.py:124` |
| `notes/问答记录.md` | Registro em append de todas as perguntas e respostas, incluindo as entradas da caixa de entrada em que "o humano falou por iniciativa própria". **Não entra no contexto, é só arquivo** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | O [documento de handoff](glossary.md#交接书). A geração anterior é recolhida em `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `lineage.json` + `需求.md` + `目标.md` arquivados por `--new` / `/new` (**movidos, não apagados**) | `lineage.py:100-117` |

**Com `--isolate` o workbench sai do repositório**: vai para
`<diretório pai do workspace>/.flower-<nome do workspace>/` (`starter.py:47-55`). O worktree é a cópia
privada de cada agent, enquanto o workbench é a camada compartilhada entre agents; o que é
compartilhado não pode ficar dentro de uma cerca privada. Nesse caso os caminhos dados ao modelo são
absolutos (`workbench.py:69-71`、`:142-145`).

**`spill/` tem dois escritores, com algoritmos de destino diferentes**:

| Quem escreve | Quando | Escreve onde | Limiar |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **antes** de o resultado da ferramenta chegar ao modelo | `<root do workbench>/spill/` (`guard.py:130`) | `spill_threshold`, padrão 4000 caracteres |
| `TrimPolicy` (no `load`) | ao reproduzir o histórico antes do resume | `<workspace>/.flower/spill/` — string fixa relativa ao workspace (`trim.py:49`、`:303`) | `min_chars`, padrão 2000 caracteres |

No layout padrão é o mesmo diretório. Mas quando o workbench é movido (`-W` fazendo-o cair em
`runs/workbench/`, ou `--isolate` levando-o para fora do repositório) os dois se separam — a parte do
`TrimPolicy` fica sempre dentro do workspace, porque o `Read` do agent precisa alcançá-la.

O que o `spill_guard` coloca no lugar não é uma linha só, e sim uma linha de ponteiro mais os
**primeiros 400 caracteres** (`guard.py:132-140`). As chamadas que leem o próprio arquivo de spill são
liberadas, senão "use Read para ver o conteúdo completo" seria conversa fiada — a leitura voltaria
acima do limiar, seria jogada em spill de novo, num laço infinito (`guard.py:155-170`).

### Esquema de tabelas do `sessions.db` {#sessions-db}

Três tabelas; os `CREATE TABLE` estão em `stores/sqlite.py:27-51`:

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
| `entries` | Uma entrada do transcript; `payload` é o JSON original | `uid` é o `uuid` da entrada, usado como **chave de idempotência**: lotes que falham são retentados 3 vezes, e a reprodução não pode gerar linhas duplicadas. Entradas sem `uuid` (títulos, tags, marcadores de modo) não são deduplicadas, por isso o índice único tem `WHERE uid IS NOT NULL` |
| `meta` | O cursor de uma sessão | `next_seq` é o próximo número de sequência; `mtime` é um timestamp em milissegundos e **estritamente monotônico** (`sqlite.py:72-79`) — `list_sessions` e o summary compartilham esse relógio, e sem monotonicidade a comparação de recência do SDK entra no caminho rápido errado |
| `summaries` | O sidecar de resumo de uma thread principal | **Só o transcript principal participa**; os dos subagents não contam (`sqlite.py:122-123`) |

Construção do `store_key` (`sqlite.py:54-58`): `<project_key>/<session_id>`, com mais um trecho
`subpath` para subagents. O `project_key` é derivado pelo SDK a partir do caminho do workspace — `/`,
`_` e `.` viram todos `-`.

Uma olhada numa amostra real
([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Essa amostra tem 956 `entries`, 10 `meta` e 4 `summaries` — das 10 sessões, 4 são transcripts
principais e 6 são de subagents, e `summaries` é exatamente igual ao número de transcripts principais.

## As três camadas do session store {#会话存储}

!!! note "As três camadas são uma cadeia de herança, não uma combinação opcional"
    `PruningSessionStore` herda de `TrimmingSessionStore`, que herda de `SqliteSessionStore`.
    O `Runtime` **sempre** constrói a camada mais externa (`runtime.py:109-112`), e não há nos
    parâmetros do construtor nenhuma entrada para trocar o backend. A forma de "desligar uma camada" é
    pôr `enabled=False` no objeto de política dela, não trocar de classe.

O `append` (escrita) sempre grava tudo em disco, sem alterar uma vírgula. As três camadas só afetam o
`load` (a versão que volta para alimentar o modelo). A ordem real do `load` é:

```text
SqliteSessionStore.load     lê tudo da tabela entries por seq
  → TrimmingSessionStore.expire()   resultados Bash sensíveis ao tempo → trocados por "expirado"
  → TrimmingSessionStore.trim()     tool_result grandes e antigos → spill + troca por ponteiro
    → PruningSessionStore.prune()   mensagens de erro sintéticas / chamadas negadas antigas → entrada removida e cadeia reconectada
```

| Camada | Classe | O que descarta | Critério |
|---|---|---|---|
| 1 | `SqliteSessionStore` | não descarta nada | —— |
| 2 | `TrimmingSessionStore` | corpo de resultados grandes de ferramenta, resultados expirados de comandos efêmeros | volume + validade temporal |
| 3 | `PruningSessionStore` | resíduo de queda de conexão, chamadas negadas antigas | é erro ou não |

A camada 2 é [trim](glossary.md#裁剪), a camada 3 é [prune](glossary.md#剪除) —
**trim descarta por volume e valor, prune descarta por "é erro ou não"**; não confunda. Assinaturas
completas na [API Python](api.md).

### `SqliteSessionStore` — a fundação {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implementação SQLite sem dependências externas. Para trocar por Postgres / S3 / Redis, basta
implementar o mesmo protocolo; o SDK traz a suíte de testes de conformidade
`claude_agent_sdk.testing.session_store_conformance`, que pode ser usada diretamente para validar
(`sqlite.py:1-8`).

Além dos métodos do protocolo, há três consultas **síncronas**, para uso do próprio flower:

| Método | Retorno | Para que serve |
|---|---|---|
| `projects()` | `list[str]` | Os `project_key` que realmente existem no banco. O SDK o deriva do cwd; confirme com isto antes de consultar, não chute |
| `has_session(project_key, session_id)` | `bool` | Consulta apenas uma linha de `meta`, sem ler o payload. Consulte antes de iniciar a [continuidade](glossary.md#接续) — dar resume numa sessão inexistente só explode depois que o subprocesso subiu, quando dinheiro e tempo já foram gastos |
| `last_context(project_key, session_id, scan=60)` | `int` | Quanto contexto esta sessão viu no último turno. Varre de trás para frente só as últimas 60 entradas. Soma `input_tokens` e os dois `cache_*` — olhar só o primeiro subestima muito, porque com cache hit ele fica perto de 0 |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Duas regras ortogonais. `TrimPolicy` cuida do **volume**:

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Os N `tool_result` mais recentes mantêm o texto original — o contexto em uso não deve ser cortado |
| `min_chars` | `int` | `2000` | Abaixo disso não corta. Trocar por um ponteiro gastaria mais tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Diretório de arquivamento, **relativo ao workspace**. Precisa estar dentro do workspace, senão o `Read` do agent não alcança |
| `enabled` | `bool` | `True` | É `False` com `Runtime(trim=False)` (o padrão) |

O corpo cortado é escrito como `<primeiros 16 dígitos do sha256>.txt`, e no lugar original entra
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`、`:308-317`).

`EphemeralPolicy` cuida da **validade temporal**: resultados como `git status`, `ls` e `ps` são curtos
e, por volume, nunca chegariam a ser cortados, mas a corretude deles decai com o tempo — um
`git status` de 20 turnos atrás não é "inútil", ele **induz ao erro**.

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Convertido de `Runtime(ephemeral=…)`, **ligado por padrão** |
| `keep_recent` | `int` | `6` | Os N mais recentes mantêm o texto original. Bem menor que os 20 do `TrimPolicy` — para esse tipo de coisa, a janela do "recente" é naturalmente curta |
| `max_chars` | `int` | `2000` | Acima disso passa para o `TrimPolicy` arquivar em disco, não segue por este caminho |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texto de substituição |

Só atua sobre resultados da ferramenta **Bash**, e o comando precisa casar com `EPHEMERAL_CMD`. `Read`
não entra nessa lista: o conteúdo de um arquivo não se deteriora com o tempo a ponto de induzir ao
erro, e ainda pode ser justamente a base do raciocínio do modelo (`trim.py:153-160`). Conteúdo
expirado **não vai para o spill** — arquivar um `git status` expirado não tem sentido, basta rodar de
novo.

A função de decisão é `is_ephemeral(cmd)`, e ela **também é a lista de permissões devolvida ao
coordenador**: `delegate_guard(allow_glance=True)` usa a mesma função (`trim.py:63-68`、`:128-150`).
Os dois conjuntos precisam ser sempre iguais — liberar sem cortar faz o `git status` expirado ocupar o
contexto para sempre; cortar sem liberar faz o coordenador despachar um subagent por causa de um `ls`,
trocando 4.3k de custo de inicialização por algumas dezenas de caracteres. Adicionar um comando à
lista branca equivale a dizer as duas coisas ao mesmo tempo.

**Quando usar o quê**:

- Só quer que resíduo de queda de conexão não entre no contexto → não precisa fazer nada, o `Runtime`
  já usa `PruningSessionStore` por padrão. `trim=False` apenas deixa de cortar resultados grandes; o
  prune continua acontecendo.
- Runs longas com saídas de ferramenta muito grandes → `trim=True`. No caminho `go` o CLI já vem com
  isso ligado; use `--no-trim` para desligar.
- [Coordenador](glossary.md#协调者) com `glance=True` → `ephemeral` precisa continuar ligado, pelo
  motivo do parágrafo anterior.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Remove mensagens sintéticas com `isApiErrorMessage=true` ou `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Para `tool_result` de `[Request interrupted …]`, **troca o corpo, não remove o bloco** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texto de substituição do item anterior |
| `keep_denials` | `int` | `1` | Mantém as N chamadas de ferramenta mais recentes negadas pelo permission hook; as anteriores são removidas **junto com a chamada e o resultado** |

`keep_denials` é o único parâmetro do construtor do `Runtime` repassado a esta camada
(`Runtime(keep_denials=N)`). O motivo de o padrão ser 1 e não 0: a negação mais recente é sinal útil e
evita que o modelo fique retentando o mesmo comando bloqueado dentro do mesmo turno.
**Não aumente** — uma chamada negada nunca foi executada, não há nenhuma informação no resultado dela,
e medido na prática ela ocupa 273 caracteres (93 caracteres de recusa mais 180 caracteres do comando
morto); além disso ela **induz ao erro**: nos testes, depois de ler algumas mensagens de "não use Bash
diretamente", o coordenador deixou de tentar até o `git status` que era liberado, dizendo direto "o
Bash está restrito, vou despachar um agent para olhar" (`prune.py:135-148`).

Três linhas vermelhas estruturais; violar qualquer uma faz a API dar erro na hora:

1. **O bloco `tool_result` em si precisa continuar existindo**; só se pode trocar o `content`. Se
   faltar um, é "Missing Tool Result Block" (`trim.py:20-22`;`prune.py:79-92`).
2. **Entradas `isCompactSummary` / `isMeta` não podem ser mexidas** — elas são a única forma de
   existência daquele trecho de histórico que foi comprimido (`trim.py:179-181`).
3. **Ao remover uma entrada, é obrigatório religar os filhos dela ao pai dela.** O transcript é uma
   lista encadeada simples por `parentUuid`, e o harness percorre das folhas para trás; onde a cadeia
   quebrar, todo o histórico anterior se perde (`prune.py:95-122`). Por isso o `relink()` precisa
   receber a lista completa **incluindo** as entradas a remover, e fazer a filtragem por conta própria.

**No SQLite o texto original não muda uma vírgula** — as três camadas só afetam "a cópia que volta ao
modelo" (`trim.py:18`;`prune.py:8`).

## Resiliência a queda de rede {#韧性}

Um workflow long-horizon roda por horas, e a rede inevitavelmente cai em algum momento. O
comportamento padrão é péssimo: no instante da queda, o harness insere no transcript uma mensagem
sintética de assistant (`model="<synthetic>"`, `isApiErrorMessage=true`) cujo corpo é
`API Error: Can't reach the API server …`; ela vira a folha da sessão, e no resume seguinte é
devolvida ao modelo como "a última coisa que o modelo disse", fazendo-o achar que está discutindo uma
falha de rede; e ainda entra em `StepResult.text`, sendo propagada pelo workflow para o prompt do
passo seguinte (`resilience.py:1-22`).

A camada de [resiliência](glossary.md#韧性) faz três coisas, e nenhuma pode faltar: sondar, continuar
em vez de recomeçar, e manter o erro fora do contexto.

### Parâmetros de `Resilience` {#resilience}

| Parâmetro | Tipo | Padrão | Semântica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Convertido de `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Número máximo de tentativas de um [passo](glossary.md#步骤), **incluindo a primeira** |
| `base_delay` | `float` | `4.0` | Ponto de partida do backoff exponencial, em segundos |
| `max_delay` | `float` | `120.0` | Teto do backoff, em segundos |
| `probe_timeout` | `float` | `5.0` | Timeout de cada sonda, em segundos |
| `probe_interval` | `float` | `15.0` | Intervalo entre sondas enquanto a rede está caída, em segundos |
| `max_offline_wait` | `float` | `3600.0` | Tempo máximo de espera com a rede caída. Padrão de 1 hora — mais que isso normalmente não é oscilação, é problema de verdade |
| `retry_unknown` | `bool` | `True` | Retenta também erros que não foram classificados. A maioria dos erros desconhecidos é transitória, e os fatais já são barrados à parte |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | O que se diz ao modelo ao continuar |

Fórmula do backoff (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Ou seja, jitter de `±25%`, para evitar que um monte de processos avance ao mesmo tempo no instante em
que a rede volta. Com os padrões: a 1ª espera é de 4 segundos (na prática 3~5), a 2ª de 8 segundos
(6~10), e a partir da 5ª satura em 120 segundos (90~150).

### Estratégia da sonda {#探针}

- **Ela sonda o host:port de `ANTHROPIC_BASE_URL`**, não `api.anthropic.com` (`resilience.py:67-72`).
  Com um gateway próprio, o segundo estar acessível não diz nada sobre o primeiro.
- **Só faz DNS mais handshake TCP**: `getaddrinfo`, depois `connect_tcp`, e fecha em seguida. Não
  envia HTTP, não leva credencial, não custa dinheiro (`resilience.py:75-85`). A sonda precisa ser
  gratuita, senão "sondar a cada 15 segundos enquanto a rede está caída" vira a própria falha.
- Qualquer falha conta como inacessível — não distingue DNS caído de recusa TCP.
- `wait_online()` fica ali esperando: retorna `True` quando volta, e `False` ao esgotar
  `max_offline_wait`. Na primeira vez que fica inacessível, notifica uma linha
  `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, e ao recuperar notifica outra linha
  `<host>:<port> 恢复,继续`, **sem poluir a tela no meio** (`resilience.py:126-140`).

A sonda de credenciais feita antes de começar é outra coisa: ela realmente dispara um
`POST <BASE_URL>/v1/messages` com `max_tokens=16` e timeout padrão de 20 segundos (`env.py:126-181`).
**Não defina `max_tokens` como 1** — na prática, modelos com cadeia de raciocínio forçada não têm nem
espaço para pensar, e o servidor se arrasta por 30 segundos até responder; com 16 leva só 3.6 segundos
(`env.py:120-123`).

### Classificação de erros {#错误分类}

`classify(text)` retorna um de três valores. **Fatal é avaliado primeiro**: o texto de um 401 e afins
muitas vezes contém palavras como "connection", e inverter a ordem levaria a esperar para sempre
(`resilience.py:53-64`).

| Classificação | O que casa (regex em `resilience.py:37-50`) | Comportamento |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Para na hora, sem retentar. Retentar quantas vezes for dá o mesmo resultado, e cada vez custa dinheiro |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Espera a rede voltar e então continua via resume |
| `unknown` | não casa com nada | Com `retry_unknown=True` (padrão), também retenta |

Distinguir o que é retentável do que não é constitui o núcleo desta camada: **oscilação de rede merece
espera, credencial errada merece parada imediata** — esperar para sempre com a rede caída está certo;
esperar para sempre com a key errada é só queimar tempo.

### O que fica barrado fora do contexto {#错误不进上下文}

1. **A mensagem de erro sintética.** O `PruningSessionStore` remove a entrada inteira no `load` e
   religa o `parentUuid` (`prune.py:27-32`、`:191-195`). **No SQLite ela permanece intacta**; apenas
   não é devolvida ao modelo.
2. **No stream de eventos ela é `kind="error"`, não `"text"`**, então não entra em `StepResult.text` e
   portanto não é propagada pelo workflow para o prompt do passo seguinte (`resilience.py:17-18`).
3. **O `resume_prompt` deliberadamente não contém nenhum detalhe do erro.** O modelo precisa saber
   "foi interrompido, continue", não precisa saber se foi `ENOTFOUND` ou `503`. **Isso é log, não é
   contexto** (`resilience.py:112-113`). Para ver o log, olhe o campo `errors` do `manifest.json`.

Continuar em vez de recomeçar: quando a falha acontece o `session_id` já foi obtido, então o resume
retoma do ponto de interrupção e o que já foi gasto não se perde.

## Relacionados {#相关}

- [Linha de comando](cli.md) — como cada flag mapeia para a configuração desta página.
- [API Python](api.md) — assinaturas completas de `Runtime`, dos três stores e de `Resilience`.
- [Deploy](deploy.md) — rodar em container, distribuir capacidade de domínio via plugin.
- [Glossário](glossary.md) — o significado exato de cada termo usado nesta página.
