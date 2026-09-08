# Economia de contexto

O contexto da [thread principal](../reference/glossary.md#主线程) é a única coisa que atravessa
inteira uma execução [long-horizon](../reference/glossary.md#长程); o que ele carrega, e o que não
carrega, decide até onde essa execução vai. A forma do flower — o
[coordenador](../reference/glossary.md#协调者) não põe a mão na massa, saídas longas vão para o
disco, hooks podam na hora — sai toda dessa única premissa. Esta página explica por quê.

## Que problema resolve {#解决什么问题}

O [compact](../reference/glossary.md#压缩) espera o contexto encher para só então voltar e resumir:
trata o sintoma. O problema de verdade é: **as coisas triviais não deveriam entrar na thread
principal desde o começo.**

A diferença está no momento. A saída de um `pytest` tem facilmente dezenas de milhares de
caracteres; o modelo dá uma olhada, tira uma conclusão, e daí em diante os caracteres restantes são
reenviados a cada turno; quando a janela enche, o compact resume tudo isso junto com as decisões
que estavam ao lado num único parágrafo — o que se economiza é volume, o que se perde é o "porquê
aquilo foi decidido assim". O limiar de disparo do auto-compact é **janela − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)); naquele
instante, o que devia ser jogado fora e o que não devia já estão deitados lado a lado.

O flower resolve em quatro camadas, e a ordem é a prioridade — do que mais economiza para o que
menos:

| Camada | O que faz | Onde |
|---|---|---|
| 1. Divisão de trabalho | O trabalho de mão na massa vai para um [subagent](../reference/glossary.md#subagent); tentativa e erro ficam no transcript dele | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Scripts / saídas longas / decisões vão para o disco; o índice é injetado no system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill na hora | Um hook `PostToolUse` faz spill dos resultados de ferramenta acima do limiar; no contexto fica só uma linha com o caminho | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim e prune | Reescreve a sessão antes do resume: resultados expirados, chamadas recusadas e restos de queda de conexão não voltam a ser alimentados | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

As duas primeiras camadas cuidam de **o que entra**, as duas últimas de **o que fica do que já
entrou**. A ordem não pode ser invertida: por mais dura que seja a quarta camada, ela não recupera
o volume que vazou pela primeira.

## Como usar (código mínimo) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model padrão é "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Essas poucas linhas instalam as três primeiras camadas: `coordinator()` sempre define
`delegate_only=True` (camada 1); `workbench=True` cria o [workbench](../reference/glossary.md#工作台)
e injeta o índice no system prompt do coordenador (camada 2), além de fazer o `Runtime` instalar o
`spill_guard` (camada 3). A quarta camada já vem por padrão — o
[session store](../reference/glossary.md#会话存储) do `Runtime` é fixo em `PruningSessionStore`, e
não há parâmetro de construção para trocá-lo.

!!! warning "`workbench=True` não é opcional"
    O `delegate_guard`, que impede o coordenador de pôr a mão na massa, está pendurado em
    `workbench_hooks`, e `workbench_hooks` só é instalado quando o `Runtime` tem workbench; o
    `whitelist_guard`, por sua vez, é pulado por causa de `delegate_only=True`.
    Conclusão: **com `Runtime(workbench=False)` mais `coordinator()`, não há uma única parede
    diante de Bash / Write / Edit na thread principal.**

## O que ele realmente faz {#它实际做了什么}

### Camada 1: divisão de trabalho (a que mais economiza) {#第一层分工省得最多}

O coordenador faz o papel de "uma pessoa que sabe usar o Claude Code": decompõe, delega, lê
relatórios, decide. Ele não recebe Bash / Write / Edit — suas ferramentas são apenas `Agent`,
`TodoWrite` e `Read` (com `glance=True`, mais um `Bash` restrito, veja abaixo). Todo o trabalho de
mão na massa vai para os [executores](../reference/glossary.md#执行者).

**Quando dispara**: a cada chamada de `Bash|Write|Edit|NotebookEdit` na thread principal, o hook
`PreToolUse` `delegate_guard` faz deny na hora e aponta o caminho — "use a ferramenta Agent para
despachar um subagent, escreva na tarefa o objetivo e os critérios de aceite, e exija que ele
escreva saídas longas em `.flower/artifacts/` e responda só com caminhos e conclusões". Subagents
passam sempre. O critério é haver ou não `agent_id` nos dados do hook: **quem não tem é a thread
principal**.

**Quanto economiza**: as chamadas de ferramenta e as tentativas e erros do subagent **vão para o
transcript dele** (distinguido no session store por `subpath`); na thread principal fica apenas
aquela chamada de `Agent` e o relatório final. O processo de tentativa e erro não foi comprimido —
ele **nunca entrou na thread principal**.

- Medido (uma tarefa que gera muita saída de ferramenta): 83% do transcript ficou no subagent —
  thread principal com 13 entradas e 21K caracteres, subagent com 105K caracteres.
- Medido (escala real, uma execução de 10.4 horas, veja [HT001](../cases/ht001.md)): o subagent
  respondeu por **97.7%** dos turnos e **94.8%** dos caracteres de corpo; 1,893 chamadas de
  ferramenta de mão na massa contra 32 da thread principal (**59:1**). O compact precoce deixa de
  ser o eixo principal.

As duas linhas são duas medições diferentes: a de cima é um teste pequeno mais antigo, a de baixo é
a repetição em escala real. Mesmo mecanismo; quanto maior a escala, mais ele economiza.

O que se economiza é contexto, não categoria de modelo: `worker()` usa `model="inherit"` por
padrão — o executor não deve ser rebaixado.

O único custo na direção contrária da divisão de trabalho é o
[task brief](../reference/glossary.md#任务书) — aquele texto que o coordenador escreve ao delegar;
ele entra na thread principal e fica lá para sempre. Medido: 8/8 task briefs repetiam disciplinas
que o outro lado já conhecia; no mais curto, de 521 caracteres, só cerca de 120 eram específicos da
tarefa — cerca de 4.8k de contexto permanente desperdiçados por rodada. Por isso `COORDINATOR_RULES`
fixa uma regra: **o task brief só escreve o que é específico desta tarefa**. A única disciplina que
ainda precisa ser dita é "onde fica o workbench + saídas longas vão para `artifacts/` + responda só
com caminhos e conclusões" — porque o índice do workbench não chega ao subagent, e o task brief é o
único canal.

### Camada 2: workbench (cura o "reescrever toda vez") {#第二层工作台治每次重写}

Três diretórios sob `.flower/` acompanham o workspace:

| Diretório | O que guarda | O que resolve |
|---|---|---|
| `scripts/` | Scripts de verificação / reprodução que serão rodados uma segunda vez, com `# desc: 一句话` na primeira linha | Escreve uma vez, depois é só rodar. Acaba o "perdeu no compact, reescreve toda vez" |
| `artifacts/` | Saídas longas acima de 2000 caracteres: logs, dados, relatórios, diffs | Na conversa aparecem só o caminho e a conclusão |
| `notes/` | Decisões-chave e seus motivos, um arquivo por decisão | Depois de compact, de reinício, de troca de máquina, as conclusões continuam lá |

**Quando dispara**: o `INDEX.md` é gerado automaticamente (no máximo 40 entradas por padrão);
`refresh()` é chamado pelo `index_guard` de `PostToolUse` quando um `Write` / `Edit` cai dentro do
workbench, e também há um refresh antes de cada passo começar. Essas três regras acima são
injetadas por `prompt_block()` no system prompt do coordenador — ele já começa sabendo quais
scripts prontos existem, sem gastar uma chamada de ferramenta para descobrir.

**Quanto economiza**: medido numa execução de 10.4 horas, **61 scripts foram escritos 95 vezes e
executados 331 vezes; 92% foram executados mais de uma vez, e 0 foram escritos sem serem rodados**.
Qualitativamente, `audit-fake-ai-server.py` foi reaproveitado por 7 scripts.

Esta camada funciona por causa de uma diferença: o compact limpa o contexto, mas **não limpa o
disco, nem limpa o índice dentro do system prompt**.

!!! warning "O índice não é herdado pelo subagent"
    O índice passa pelo `system_prompt.append` de nível de sessão; o subagent tem seu próprio
    system prompt e **não o herda** (medido, $0.2461, `tests/prelude_live.py`). Por isso "onde fica
    o workbench + saídas longas em `artifacts/`" tem de ser repassado pelo coordenador no task
    brief — esse é o único canal, não é redundância.

### Camada 3: spill na hora {#第三层当场落盘}

O `spill_guard` é um hook `PostToolUse` que olha o resultado da ferramenta **antes de ele entrar no
modelo**: o que passar de `threshold` (padrão **4000** caracteres) sofre
[spill](../reference/glossary.md#落盘) para o diretório `spill/` do workbench, e no contexto vira
uma linha de ponteiro + os **400 caracteres iniciais**. O conteúdo não se perde, só deixa de ser
residente.

**Quando dispara**: o matcher é `Bash|Read|Grep|Glob|WebFetch|WebSearch`; por padrão
`main_only=False`, então resultados de subagents também sofrem spill. Ele só substitui os **campos
de string** longos demais dentro da estrutura de saída da ferramenta; listas nunca são tocadas
(podem conter blocos de imagem), porque `updatedToolOutput` precisa preservar a estrutura de saída
da ferramenta original.

**Ler o próprio arquivo de spill é liberado e não gera novo spill.** Do contrário, o "use Read para
ler o texto completo" daquela linha de aviso seria conversa fiada: lê de volta, passa do limiar,
sofre spill de novo, recebe outra linha de ponteiro — loop infinito. Já batemos nisso na prática
(`tests/handoff_live.py`, na primeira execução de verdade): o modelo tentou cinco formas diferentes
de contornar, disse ele mesmo "The spill read loops back on itself" e no fim engoliu o arquivo em
blocos de 40 linhas, queimando sete ou oito turnos à toa. O sentido do spill é "**não** enfiar
automaticamente coisas grandes no contexto"; se ele decide que quer ver o texto inteiro, isso é
escolha dele.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None ou 0 = não instala este hook
```

**Quanto economiza**: naquela execução do [HT001](../cases/ht001.md), 103 spills, 791.4K caracteres
trocados por ponteiros de caminho, sem residir no contexto.

### Camada 4: trim e prune {#第四层裁剪与剪除}

Esta camada vive no [session store](../reference/glossary.md#会话存储). O store do `Runtime` é
sempre `PruningSessionStore` (cadeia de herança `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), e ele reescreve o histórico que será alimentado de volta dentro de `load()`
— ou seja, **antes do resume**. O texto original no SQLite não muda uma letra. Quatro coisas:

**① Expiração por validade** (`ephemeral`, ligado por padrão). Resultados de
[comandos efêmeros](../reference/glossary.md#一次性命令) como `git status`, `ls`, `cat` têm o corpo
trocado por uma nota depois de alguns turnos, mantendo os 6 mais recentes. Conteúdo expirado **não
sofre spill** — arquivar um `git status` velho não tem sentido, basta rodar de novo:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Em resume ao vivo, medido `expired: 2`; num transcript real, com `keep_recent` baixado para 2,
expiraram 5 entradas.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **desligado por padrão**). O corpo de
tool_results com `>= 2000` caracteres sofre spill para `<workspace>/.flower/spill/`, e o conteúdo
do bloco vira um ponteiro de arquivo, mantendo os 20 originais mais recentes. Atenção: este
diretório **não é o mesmo** do spill da camada 3, do `spill_guard`: aquele escreve na raiz do
workbench, enquanto este precisa cair dentro do workspace, senão o `Read` do agent não o alcança.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True 也行
```

**③ [Prune](../reference/glossary.md#剪除) das chamadas recusadas** (`keep_denials`, padrão 1). O
próprio ato de barrar também polui o contexto: a mensagem de recusa é um `tool_result` e fica lá
para sempre junto com **o comando que nunca foi executado**. Medido: 273 caracteres numa ocorrência
(93 de mensagem de recusa + 180 do comando morto) — o comando morto sai mais caro que a recusa.

Mais importante que os tokens é que isso **induz ao erro**: medido, depois de ler algumas mensagens
de "não use Bash diretamente", o coordenador parou até de tentar o `git status` liberado e passou a
dizer "Bash está restrito, vou despachar um agent para ver" — aprendeu desamparo aprendido e ainda
gastou mais uma inicialização de subagent. O padrão mantém 1 e não 0: a recusa mais recente é sinal
útil e evita que o modelo repita várias vezes o mesmo comando barrado dentro do mesmo turno. A
identificação usa a marca estrutural que o próprio harness escreve,
`toolDenialKind: "permission-rule"`, e não casamento de texto — o texto muda a qualquer momento, a
marca não. Medido ao vivo: 2 recusas → remove 1, mantém 1, cadeia intacta, resume normal e o modelo
continua sabendo o que aconteceu.

**④ Prune dos restos de queda de conexão**. Mensagens sintéticas de erro de API geradas durante as
retentativas de rede não voltam a ser alimentadas; o `tool_result` deixado por uma interrupção vira
uma nota neutra (`[上一轮在此处被中断,该工具结果未产生]`), mas a entrada em si é preservada.

**A linha vermelha ao remover**: um `tool_use` e seu `tool_result` precisam ser removidos
**juntos** (faltar um é `Missing Tool Result Block`), as outras chamadas dentro da mesma mensagem
de assistant não podem ser atingidas por engano, e a cadeia de `parentUuid` precisa ser reconectada.

`Runtime(trim=False)` (o padrão) **não significa não limpar nada**: ele só desliga o trim de
resultados grandes; expiração, chamadas recusadas e restos de queda de conexão continuam
acontecendo.

### Contraexemplo: o trabalho de dar uma olhada, faça você mesmo {#反例看一眼的活自己干}

As três primeiras camadas dizem "delegue", mas há um contraexemplo: comandos como `git status`,
`ls`, `cat` produzem resultados de algumas dezenas de caracteres, enquanto **despachar um subagent
custa cerca de 4.3k de contexto só para iniciar** (medido, não diluível). Pagar esse preço por um
`ls` é prejuízo líquido.

Por isso o coordenador recupera um Bash restrito (`coordinator(..., glance=True)`, ligado por
padrão). O critério não é "o comando é curto", e sim **se o resultado expira**; além disso,
"liberar" e "expirar" são decididos pela mesma função, `is_ephemeral()`:

| | Liberado para rodar sozinho | Resultado é marcado como expirado |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delega | — |

Os dois lados precisam ser a mesma tabela; qualquer um deles sozinho é nocivo: **liberar sem
trimar** faz um `git status` expirado ocupar contexto para sempre e ainda ser tomado como estado
atual, distorcendo decisões; **trimar sem liberar** obriga o coordenador a pagar 4.3k por um `ls`.
`tests/glance.py` prega essa invariante como asserção — medido, 46 comandos com julgamento idêntico
dos dois lados, incluindo 10 amostras adversariais.

**Armadilha (pisamos duas vezes)**: o modelo não escreve comandos únicos, ele escreve
`git status -s && echo "--- LOG ---" && git log --oneline -10`. A primeira versão recusava em bloco
todo comando com `&&` / `|` / `2>&1`, e o resultado foi **o glance parar de funcionar por completo**
— medido, as três tentativas do coordenador foram barradas e ele voltou a despachar subagent. Agora
a checagem quebra o comando em segmentos: só libera se cada segmento estiver na lista branca;
`git status && rm -rf x` continua barrado (a segunda metade não está na tabela).

### Append, não substituição {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Quando `build_options()` compila um `AgentSpec` em opções do SDK, `instructions` vai por
[`append`](../reference/glossary.md#叠加) — acrescentado **depois** do system prompt nativo do
Claude Code, não no lugar dele. Portanto todos aqueles textos de disciplina (`COORDINATOR_RULES`,
`WORKER_RULES` etc.) são adição: **a especialização não custa a capacidade geral.**

O índice do workbench também passa por esse canal. Ele está presente a cada turno, mas é parte do
system prompt, não ocupa o histórico da conversa e o compact não consegue limpá-lo — o preço é
aquele já dito: **só chega ao coordenador**.

!!! warning "Não use `disallowed_tools` para impedir o coordenador de pôr a mão na massa"
    `disallowed_tools` é **de nível de sessão** e desabilita junto os subagents. Erro medido, no
    original:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    O jeito certo tem dois passos: não conceder em `allowed_tools` e depois usar um hook
    `PreToolUse` para barrar apenas a thread principal, pelo `agent_id`. `coordinator()` já faz
    isso — ele define `delegate_only=True`, e o `delegate_guard` barra a thread principal e libera
    os subagents.

    Só `allowed_tools` também não basta: é uma **lista de dispensa de aprovação, não uma lista
    branca exclusiva**. Medido, o modelo consegue chamar ferramentas que não estão nela — numa
    sonda de $0.1, um agent com `allowed_tools=["Read"]` chamou Write / Bash sem problema. Quem
    barra de verdade é o hook.

    **`allowed_tools` também é de nível de sessão — a mesma lição, aprendida duas vezes.**
    Ferramentas fora dessa lista também passam por aprovação de permissão quando chamadas por um
    **subagent**. Sem supervisão humana não há quem aprove, então não dá erro nem para: o modelo
    repete a mesma chamada indefinidamente (`toolDenialKind=user-rejected`). Medido: adicionamos
    `WebFetch`/`WebSearch` ao executor mas só escrevemos em `AgentDefinition.tools`; naquela
    execução foram mais de vinte user-rejected e nenhuma palavra produzida (`roles.py:513-518`).
    O sintoma é mais difícil de investigar que o de `disallowed_tools` — este dá erro na hora,
    aquele não parece erro nenhum na tela. Por isso `coordinator()` hoje une as ferramentas web
    somente-leitura dos seus executores ao próprio `allowed_tools` (`roles.py:523-526`), enquanto
    `Write`/`Edit`/`Bash` **de propósito não são unidos** — uni-los equivaleria a desmontar aquele
    hook acima.

## Quando não usar {#什么时候不该用它}

As quatro camadas economizam no **material bruto**. Os problemas abaixo elas não resolvem, e alguns
ficam até mais difíceis de enxergar por causa delas:

1. **Objetivo mal entendido — as quatro camadas agravam isso.** Depois que o material bruto é
   descartado, o que fica é justamente a decisão construída sobre a premissa errada — e ela
   **parece exatamente igual a uma decisão correta**. O long-horizon amplia isso ao pior caso: a
   premissa errada roda por horas, despacha uma dúzia de subagents, deposita uma pilha de saídas no
   disco, e só então se revela. A essa altura o caro não são os tokens, é que cada saída foi
   construída sobre o requisito errado. Quem barra isso é a [confirmação prévia](clarify.md), não
   nenhuma camada desta página.
2. **A thread principal continua crescendo monotonicamente.** As quatro camadas achatam a
   inclinação, não mudam a direção. Medido: a thread principal foi de 28.7K a 185.9K em 70 turnos,
   inclinação de 2.2K/turno, sem nenhum compact no caminho, consumindo 18.6% de uma janela de 1M;
   **extrapolando, bate na parede por volta do turno 440**. Quem atravessa aquela parede é o
   [handoff](handoff.md).
3. **Depois de desligar o compact completo não há rede de segurança.** Com o handoff ligado, o
   `Runtime` força `CompactPolicy(mode="no_summary")` no spec, e o auto-compact fica desligado (se o
   próprio spec definiu `compact` explicitamente, isso é respeitado). Bater no limite é erro duro,
   então estas quatro camadas precisam ser usadas em conjunto com o handoff — não basta simplesmente
   desligar o compact.
4. **A camada 4 só age no resume.** Trim e prune acontecem em `load()`; uma sessão que está rodando
   continuamente não encolhe por causa deles. Depois de fazer a divisão de trabalho descrita acima,
   essa camada quase não será necessária — a thread principal já não comporta muitos resultados de
   ferramenta mesmo.
5. **Delegar o trabalho de dar uma olhada é prejuízo líquido.** Iniciar um subagent custa cerca de
   4.3k; veja a seção do glance acima.
6. **Antes de reordenar o contexto, faça a conta do cache.** Medido, uma execução com 299.4M tokens
   de entrada e **96.1% de acerto de cache**; os $171 só se sustentam por causa disso. Qualquer
   otimização que reescreva o histórico precisa fazer essa conta primeiro.
7. **Resultados de ferramenta de imagem e documento não sofrem spill.** O `spill_guard` só altera
   campos de string na estrutura de saída; listas nunca são tocadas.

Os valores padrão completos e as assinaturas dos parâmetros estão na
[Python API](../reference/api.md); os termos, no [glossário](../reference/glossary.md).
