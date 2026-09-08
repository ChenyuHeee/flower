# Economia de contexto

O contexto da [thread principal](../reference/glossary.md#主线程) é a única coisa que atravessa
uma execução [long-horizon](../reference/glossary.md#长程) inteira: o que ela carrega e o que
ela não carrega determina até onde essa execução vai. O formato do flower — o
[coordenador](../reference/glossary.md#协调者) não põe a mão na massa, produções longas vão para o
disco, hooks podam na hora — sai todo dessa única premissa. Esta página explica por quê.

## Que problema resolve {#解决什么问题}

[Compact](../reference/glossary.md#压缩) é esperar o contexto encher para só então resumir o que
já passou: trata o sintoma. O problema de verdade é:
**as coisas triviais nunca deveriam ter entrado na thread principal.**

A diferença está no momento. A saída de um `pytest` passa facilmente de dezenas de milhares de
caracteres; o modelo dá uma olhada, tira uma conclusão, e os caracteres restantes seguem sendo
reenviados a cada turno. Quando a janela enche, o compact resume esses caracteres junto com as
decisões que estavam ao lado deles num único parágrafo — o que se economiza é volume, o que se
perde é o "por que decidimos assim". O limiar de disparo do auto-compact é **janela − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py));
quando ele chega, o que devia ser descartado e o que não devia já estão deitados lado a lado.

O flower resolve em quatro camadas, e a ordem é a prioridade — ordenadas por quanto economizam:

| Camada | O que faz | Onde |
|---|---|---|
| 1. Divisão de trabalho | O trabalho braçal vai para um [subagent](../reference/glossary.md#subagent), tentativa e erro ficam no transcript dele | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Scripts / produções longas / decisões vão para o disco, o índice é injetado no system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill na hora | O hook `PostToolUse` faz spill dos resultados de ferramenta acima do limiar; no contexto fica só uma linha de caminho | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim e prune | Reescreve a sessão antes do resume: resultados expirados, chamadas recusadas e resíduos de desconexão não voltam a ser alimentados | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

As duas primeiras camadas controlam **o que entra**; as duas últimas, **o que fica do que já
entrou**. A ordem não pode ser invertida: por mais agressiva que seja a quarta camada, ela não
recupera o volume que vazou pela primeira.

## Como usar (código mínimo) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model é "inherit" por padrão

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Essas poucas linhas instalam as três primeiras camadas: `coordinator()` sempre define
`delegate_only=True` (camada um); `workbench=True` cria o
[workbench](../reference/glossary.md#工作台) e injeta o índice no system prompt do coordenador
(camada dois), e ao mesmo tempo faz o `Runtime` instalar o `spill_guard` (camada três). A quarta
camada já está lá por padrão — o [session store](../reference/glossary.md#会话存储) do `Runtime` é
fixo em `PruningSessionStore`, e não há parâmetro de construção para trocá-lo.

!!! warning "`workbench=True` não é opcional"
    O `delegate_guard`, que impede o coordenador de pôr a mão na massa, está pendurado em
    `workbench_hooks`, e `workbench_hooks` só é instalado quando o `Runtime` tem workbench;
    já o `whitelist_guard` é pulado por causa de `delegate_only=True`.
    Conclusão: **com `Runtime(workbench=False)` combinado com `coordinator()`, Bash / Write / Edit
    na thread principal não têm nenhuma barreira.**

## O que ele realmente faz {#它实际做了什么}

### Camada um: divisão de trabalho (a que mais economiza) {#第一层分工省得最多}

O coordenador interpreta "uma pessoa que sabe usar o Claude Code": decompõe, delega, lê relatórios,
decide. Ele não tem Bash / Write / Edit — as ferramentas são apenas `Agent`, `TodoWrite`, `Read`
(com `glance=True`, mais um `Bash` restrito, ver abaixo). Todo o trabalho braçal vai para os
[executores](../reference/glossary.md#执行者).

**Quando dispara**: a cada chamada de `Bash|Write|Edit|NotebookEdit` na thread principal, o hook
`PreToolUse` `delegate_guard` nega na hora e indica o caminho — "use a ferramenta Agent para
despachar um subagent, escreva na tarefa o objetivo e os critérios de aceitação, e exija que ele
grave produções longas em `.flower/artifacts/` e responda só com caminhos e conclusões". Subagents
passam sempre. O critério é a presença de `agent_id` nos dados do hook: **quem não tem é a thread
principal**.

**Quanto economiza**: as chamadas de ferramenta e a tentativa-e-erro do subagent **vão para o
transcript dele** (o session store distingue por `subpath`); na thread principal fica apenas aquela
chamada de `Agent` e o relatório final. O processo de tentativa e erro não foi compactado: ele
**nunca entrou na thread principal**.

- Medido (uma tarefa que gera muita saída de ferramenta): 83% do transcript ficou nos subagents;
  13 mensagens e 21K caracteres na thread principal, 105K caracteres nos subagents.
- Medido (escala real, uma execução de 10.4 horas, ver [HT001](../cases/ht001.md)): os subagents
  absorveram **97.7%** dos turnos e **94.8%** dos caracteres de corpo; 1,893 chamadas de ferramenta
  de execução contra 32 na thread principal (**59:1**). Compactar cedo deixa de ser o caminho
  principal.

As duas linhas são duas medições diferentes: a primeira é um teste pequeno anterior, a segunda é a
remedição em escala real. Mesmo mecanismo; quanto maior a escala, mais ele economiza.

O que se economiza é contexto, não classe de modelo: `worker()` usa `model="inherit"` por padrão —
o executor não deve ser rebaixado.

O único custo na direção contrária da divisão de trabalho é o
[task brief](../reference/glossary.md#任务书) — aquele parágrafo que o coordenador escreve ao
delegar. Ele entra na thread principal e fica lá para sempre. Medido: 8/8 task briefs repetiam
disciplinas que o outro lado já conhecia; no mais curto, de 521 caracteres, só cerca de 120 eram
específicos da tarefa, ou seja, cerca de 4.8k de contexto permanente desperdiçado por rodada. Por
isso `COORDINATOR_RULES` fixa uma regra: **o task brief só escreve o que é específico desta
tarefa**. A única regra que ainda precisa ser dita é "onde fica o workbench + produções longas vão
para `artifacts/` + responda só com caminhos e conclusões" — porque o índice do workbench não chega
ao subagent, e o task brief é o único canal.

### Camada dois: workbench (cura o "reescrever toda vez") {#第二层工作台治每次重写}

Três diretórios sob `.flower/`, que acompanham o workspace:

| Diretório | O que guarda | O que resolve |
|---|---|---|
| `scripts/` | Scripts de verificação / reprodução que vão rodar uma segunda vez, com `# desc: uma frase` na primeira linha | Escreve uma vez, depois é só rodar. Acaba o "se perdeu no compact, reescreve toda vez" |
| `artifacts/` | Produções longas acima de 2000 caracteres: logs, dados, relatórios, diffs | Na conversa aparecem só o caminho e a conclusão |
| `notes/` | Decisões-chave e seus motivos, um arquivo por decisão | Compactou, reiniciou, trocou de máquina — a conclusão continua lá |

**Quando dispara**: o `INDEX.md` é gerado automaticamente (no máximo 40 entradas por padrão);
`refresh()` é chamado pelo `index_guard` do `PostToolUse` quando um `Write` / `Edit` cai dentro do
workbench, e também é atualizado antes de cada passo começar. As três regras acima são injetadas no
system prompt do coordenador por `prompt_block()` — ele já começa sabendo quais scripts existem,
sem gastar uma chamada de ferramenta para descobrir.

**Quanto economiza**: medido numa execução de 10.4 horas, **61 scripts foram escritos 95 vezes e
executados 331 vezes; 92% foram executados mais de uma vez, e 0 foram escritos sem serem rodados**.
Qualitativamente, `audit-fake-ai-server.py` foi reaproveitado por 7 scripts.

Essa camada funciona por causa de uma diferença: o compact limpa o contexto, mas **não limpa o
disco, nem limpa o índice dentro do system prompt**.

!!! warning "O índice não é herdado pelos subagents"
    O índice vai pelo `system_prompt.append` no nível da sessão; o subagent tem seu próprio system
    prompt e **não herda** isso (medido, $0.2461, `tests/prelude_live.py`). Por isso "onde fica o
    workbench + produções longas vão para `artifacts/`" precisa ser repassado pelo coordenador no
    task brief — é o único canal, não é redundância.

### Camada três: spill na hora {#第三层当场落盘}

O `spill_guard` é um hook `PostToolUse` que olha o resultado da ferramenta **antes de ele entrar no
modelo**: o que passar de `threshold` (padrão **4000** caracteres) vai para
[spill](../reference/glossary.md#落盘) no diretório `spill/` do workbench, e no contexto vira uma
linha de ponteiro + os **primeiros 400 caracteres**. Nada é perdido; apenas deixa de ser residente.

**Quando dispara**: o matcher é `Bash|Read|Grep|Glob|WebFetch|WebSearch`; por padrão
`main_only=False`, então os resultados dos subagents também sofrem spill. Ele só substitui os
**campos de string** longos demais dentro da estrutura de saída da ferramenta; listas nunca são
tocadas (podem conter blocos de imagem), porque `updatedToolOutput` precisa preservar a estrutura de
saída da ferramenta original.

**Ler o próprio arquivo de spill é liberado e não sofre spill de novo.** Caso contrário, o "use Read
para ler o texto completo" daquela linha de aviso seria conversa fiada: lê de volta, passa do
limiar, sofre spill, recebe outra linha de ponteiro, laço infinito. Isso aconteceu de verdade
(`tests/handoff_live.py`, na primeira execução real): o modelo tentou cinco formas de contornar,
disse ele mesmo "The spill read loops back on itself", e no fim mastigou o arquivo em blocos de 40
linhas, queimando sete ou oito turnos à toa. O sentido do spill é "**não** enfiar automaticamente
coisas grandes no contexto"; se ele decidir ler o texto completo, é escolha dele.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None ou 0 = não instala esse hook
```

**Quanto economiza**: naquela execução do [HT001](../cases/ht001.md), 103 spills trocaram 791.4K
caracteres por ponteiros de caminho, sem residir no contexto.

### Camada quatro: trim e prune {#第四层裁剪与剪除}

Essa camada vive no [session store](../reference/glossary.md#会话存储). O store do `Runtime` é
sempre `PruningSessionStore` (cadeia de herança `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), e ele reescreve o histórico que será realimentado dentro do `load()` — ou
seja, **antes do resume**. O texto original no SQLite não é alterado em um caractere sequer. Quatro
coisas:

**① Expiração por validade** (`ephemeral`, ligado por padrão). Resultados de
[comandos efêmeros](../reference/glossary.md#一次性命令) como `git status`, `ls`, `cat` têm o corpo
trocado por uma nota depois de alguns turnos, mantendo os 6 mais recentes. Conteúdo expirado **não
sofre spill** — arquivar um `git status` velho não tem sentido, basta rodar de novo:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Medido num resume ao vivo: `expired: 2`; num transcript real, com `keep_recent` em 2, 5 entradas
expiraram.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **desligado por padrão**). Corpos de
tool_result com `>= 2000` caracteres sofrem spill para `<workspace>/.flower/spill/`, e o conteúdo do
bloco vira um ponteiro de arquivo, mantendo os 20 mais recentes em texto original. Note que esse
diretório **não é o mesmo** do spill da camada três: aquele escreve na raiz do workbench, enquanto
este precisa cair dentro do workspace, senão o `Read` do agent não alcança.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True também serve
```

**③ [Prune](../reference/glossary.md#剪除) das chamadas recusadas** (`keep_denials`, padrão 1). O
próprio ato de barrar também polui o contexto: a mensagem de recusa é um `tool_result` e fica
permanentemente lá, junto com **o comando que nunca foi executado**. Medido uma vez: 273 caracteres
(93 de texto de recusa + 180 do comando morto); o comando morto é mais caro que a recusa.

Mais importante que os tokens é que isso **induz ao erro**: medido, depois de ler algumas mensagens
de "não use Bash diretamente", o coordenador parou até de tentar o `git status` que era liberado e
disse direto "Bash está restrito, vou despachar um agent para olhar" — desamparo aprendido, gastando
uma inicialização de subagent a mais. O padrão mantém 1 e não 0: a recusa mais recente é sinal útil
e evita que o modelo repita a mesma chamada barrada dentro do mesmo turno. A identificação usa a
marca estrutural que o próprio harness escreve, `toolDenialKind: "permission-rule"`, e não a
correspondência de texto — o texto muda a qualquer momento, a marca não. Medido ao vivo: 2 recusas →
remove 1, mantém 1, a cadeia não quebra, o resume funciona e o modelo continua sabendo o que
aconteceu.

**④ Prune dos resíduos de desconexão**. Mensagens de erro de API sintéticas geradas durante
retentativas de queda de rede não são realimentadas; um `tool_result` deixado por uma interrupção
vira uma nota neutra (`[上一轮在此处被中断,该工具结果未产生]`), mas a entrada em si é preservada.

**Linhas vermelhas ao remover**: `tool_use` e seu `tool_result` precisam ser removidos **juntos**
(faltar um é `Missing Tool Result Block`), as outras chamadas dentro da mesma mensagem do assistant
não podem ser atingidas por engano, e a cadeia de `parentUuid` precisa ser reconectada.

`Runtime(trim=False)` (o padrão) **não significa não limpar nada**: ele só desliga o trim de
resultados grandes; expiração, chamadas recusadas e resíduos de desconexão continuam valendo.

### Contraexemplo: tarefas de dar uma olhada, faça você mesmo {#反例看一眼的活自己干}

As três primeiras camadas dizem "delegue", mas há um contraexemplo: comandos como `git status`,
`ls`, `cat` produzem resultados de algumas dezenas de caracteres, enquanto **só a inicialização de
um subagent custa cerca de 4.3k de contexto** (medido, não amortizável). Pagar esse preço por um
`ls` é prejuízo líquido.

Por isso o coordenador recebe de volta um Bash restrito (`coordinator(..., glance=True)`, ligado por
padrão). O critério não é "o comando é curto", e sim **se o resultado expira**; além disso,
"liberar" e "expirar" são decididos pela mesma função, `is_ephemeral()`:

| | Liberado para rodar sozinho | Resultado marcado como expirado |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delega | — |

Os dois lados precisam ser a mesma tabela, porque qualquer um deles sozinho é nocivo: **liberar sem
fazer trim** faz um `git status` expirado ocupar contexto para sempre e ainda ser lido como estado
atual, induzindo decisões erradas; **fazer trim sem liberar** obriga o coordenador a pagar 4.3k por
um `ls`. `tests/glance.py` prega essa invariante como asserção — medido, 46 comandos com julgamento
idêntico dos dois lados, incluindo 10 amostras adversariais.

**Armadilha (pisamos nela duas vezes)**: o modelo não escreve comandos únicos; ele escreve
`git status -s && echo "--- LOG ---" && git log --oneline -10`. A primeira versão recusava em bloco
todo comando com `&&` / `|` / `2>&1`, e o resultado foi que o **glance parou de funcionar por
completo** — medido, as três tentativas do coordenador foram barradas e ele acabou voltando a
despachar subagent. Agora a checagem quebra por segmento: só libera se cada segmento estiver na
whitelist, e `git status && rm -rf x` continua barrado (a segunda parte não está na tabela).

### Append, não substituição {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Quando `build_options()` compila o `AgentSpec` em opções do SDK, `instructions` vai por
[`append`](../reference/glossary.md#叠加) — anexado **depois** do system prompt nativo do Claude
Code, não no lugar dele. Ou seja, todos aqueles textos de disciplina (`COORDINATOR_RULES`,
`WORKER_RULES` etc.) são adição: **a especialização não custa a capacidade geral.**

O índice do workbench usa o mesmo canal. Ele está presente a cada turno, mas faz parte do system
prompt, não ocupa o histórico da conversa, e o compact não o apaga — o preço é o que já foi dito:
**só chega ao coordenador**.

!!! warning "Não use `disallowed_tools` para impedir que o coordenador execute"
    `disallowed_tools` é **no nível da sessão** e bloqueia os subagents junto. Erro medido, texto
    original:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    O jeito certo tem dois passos: não conceder em `allowed_tools` e depois usar um hook
    `PreToolUse` que barra apenas a thread principal, com base no `agent_id`. `coordinator()` já faz
    exatamente isso — define `delegate_only=True`, e o `delegate_guard` barra a thread principal e
    libera os subagents.

    Só `allowed_tools` também não basta: é uma **lista de dispensa de aprovação, não uma whitelist
    exclusiva**. Medido: o modelo consegue chamar ferramentas que não estão nela — numa sonda de
    $0.1, um agent com `allowed_tools=["Read"]` chamou Write / Bash sem problema. Quem realmente
    barra é o hook.

## Quando não usar {#什么时候不该用它}

As quatro camadas economizam sobre o **material bruto**. Os problemas abaixo elas não resolvem, e
alguns ficam até mais difíceis de enxergar por causa delas:

1. **Entendimento errado do objetivo — essas quatro camadas agravam isso.** Depois que o material
   bruto é descartado, o que sobra é exatamente a decisão construída sobre a premissa errada, e ela
   **parece idêntica a uma decisão correta**. O long-horizon amplifica isso ao máximo: a premissa
   errada roda por horas, despacha uma dezena de subagents, deixa uma pilha de produções em disco, e
   só então aparece. Nessa altura o caro não são os tokens, é que cada produção foi construída sobre
   o requisito errado. Quem barra isso é o [clarify](clarify.md), não nenhuma das camadas desta
   página.
2. **A thread principal continua crescendo monotonicamente.** As quatro camadas achatam a
   inclinação, não a direção. Medido: em 70 turnos a thread principal foi de 28.7K a 185.9K,
   inclinação de 2.2K/turno, sem nenhum compact, consumindo 18.6% de uma janela de 1M —
   **extrapolando, bate no teto por volta do turno 440**. Quem atravessa essa parede é o
   [handoff](handoff.md).
3. **Depois de desligar o compact completo, não há rede de segurança.** Com o handoff ligado, o
   `Runtime` força `CompactPolicy(mode="no_summary")` no spec, e o auto-compact fica desligado (se o
   próprio spec definiu `compact` explicitamente, isso é respeitado). Bater no limite é erro duro,
   então essas quatro camadas precisam ser usadas em conjunto com o handoff — desligar o compact e
   parar por aí não serve.
4. **A camada quatro só age no resume.** Trim e prune acontecem no `load()`; uma sessão rodando
   continuamente não encolhe por causa disso. Depois de fazer a divisão de trabalho descrita acima,
   essa camada provavelmente nem será necessária — a thread principal já não carrega muitos
   resultados de ferramenta.
5. **Delegar tarefas de dar uma olhada é prejuízo líquido.** A inicialização do subagent custa cerca
   de 4.3k, ver a seção do glance acima.
6. **Antes de reordenar o contexto, faça a conta do cache.** Medido numa execução: 299.4M tokens de
   entrada, **96.1% de acerto de cache**; os $171 só se sustentam por causa disso. Qualquer
   otimização que reescreva o histórico precisa fazer essa conta primeiro.
7. **Resultados de ferramenta com imagens ou documentos não sofrem spill.** O `spill_guard` só
   altera campos de string na estrutura de saída; listas nunca são tocadas.

Os valores padrão completos e as assinaturas dos parâmetros estão em
[Python API](../reference/api.md); os termos estão no
[glossário](../reference/glossary.md).
