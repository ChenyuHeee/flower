# Guarda de objetivo

"Está pronto?" não é o executor quem responde. O [julgador](../reference/glossary.md#判定者) é um papel que só define objetivo,
só julga e não põe a mão na massa: antes da largada transforma o [brief](../reference/glossary.md#需求确认书) numa lista
julgável e, ao fim de cada rodada de trabalho, **julga uma vez, de forma independente**, produzindo um [veredito](../reference/glossary.md#判定) —
atingido, segue adiante; não atingido, devolve com "o que está faltando" para continuar;
julgado inalcançável, para e pergunta a uma pessoa.

## Que problema resolve {#解决什么问题}

A [confirmação prévia](clarify.md) barra **"fez a coisa errada"**. Esta camada barra outra coisa:
**"na verdade não terminou, mas ele mesmo disse que terminou"**. As duas precisam ficar separadas, porque falham de formas diferentes:

| | Como a falha aparece | Quando ela se revela |
|---|---|---|
| Requisito errado | Todo entregável foi construído em cima do requisito errado | Horas depois, tudo vai para o lixo |
| Julgamento de conclusão errado | Metade dos testes rodados, um ponto corrigido e três esquecidos, "deve estar ok" | Quando você mesmo vai usar |

Por que o segundo caso não pode ficar a cargo do próprio executor: **ele tem um viés otimista sistemático**.
Não é desonestidade — ele não enxerga o próprio ponto cego. Sabe o que fez, não sabe o que deixou passar.

Por isso o julgamento vai para um papel que **não participou do trabalho e roda na própria [sessão](../reference/glossary.md#会话)**.
Ele só vê o objetivo e o estado real; não sabe quantas tentativas o executor fez nem quanto sofreu, e assim não arruma desculpas por ele.
É a mesma razão pela qual o confirmador roda em sessão independente.

## Como usar (código mínimo) {#怎么用最小代码}

### Zero código: linha de comando {#零代码命令行}

```bash
flower                      # 默认就带目标看守
flower --no-goal            # 关掉:干活跑完就算完
flower --rounds 5           # 最多五轮活(默认 3)
flower --judge-can-run      # 让判定者能跑命令(判定更硬)
```

### Ligando na mão {#自己接线}

Duas funções cuidam de metades diferentes; não misture: `goal_step()` **define o objetivo** (um passo independente),
`with_goal()` é que é o **laço de julgamento** (envolve um passo de trabalho).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # 默认不限提问次数
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)`:

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `goal_path` | — | Onde o objetivo é gravado. Ponha sob `notes/` do [workbench](../reference/glossary.md#工作台), pelo mesmo motivo do brief |
| `brief_key` | `"确认需求"` | De qual chave do `ctx` ler o brief. **Se não achar, recebe só `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nome do passo, e também o nome da chave no `ctx` |
| `spec` / `instructions` | `None` / `""` | Trazer o próprio `AgentSpec`, ou acrescentar instruções de domínio ao julgador |
| `always_set` | `False` | `True` = redefine toda vez |
| `on_fail` / `retries` | `"stop"` / `0` | Igual ao `Step` |
| `**spec_kw` | — | Repassados a `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` envolve um passo de trabalho num laço com julgamento:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` é o total de rodadas, não rodadas extras** — vira `retries = max(0, rounds - 1)`,
então `rounds=3` roda no máximo três rodadas de trabalho e `rounds=1` significa "roda uma vez, julga uma vez, se não passar falhou".
Assinatura completa e semântica dos campos em [Python API](../reference/api.md).

Aparecem três chaves a mais no `ctx`:

```python
ctx[GOAL_KEY]     # "_goal" —— Goal 对象;ctx["设定目标"] 是它的 markdown
ctx[VERDICT_KEY]  # "_verdict" —— 最近一次 Verdict,给 UI 用
ctx[ROUND_KEY]    # "_goal_rounds" —— 跑了几轮
```

O julgador é despachado via `ctx["_runtime"]` — o `Workflow.run` coloca o runtime e a saída de eventos no `ctx`,
então o `gate` consegue subir um agente por conta própria e o processo de julgamento continua aparecendo na sua UI
(senão a interface fica preta por uns quinze segundos e parece travada).

Quando não estiver saindo direito, mexa primeiro nestes botões:

| Sintoma | Qual girar |
|---|---|
| Julgamento frouxo demais, diz atingido sem estar | `--judge-can-run` para ele rodar de verdade; ou acrescente critérios de domínio em `instructions` |
| Julgamento rígido demais, devolve sempre | Veja se a lista de verificação em `目标.md` está mais alta que o próprio requisito. **Edite esse arquivo** |
| Rodada atrás de rodada girando em falso | O julgador deveria dar "inalcançável" e deu "não atingido". Acrescente instruções explicando o que conta como impossível |
| Caro demais | `--rounds 1`, ou `--no-goal` para desligar de vez |
| Não quer ser interrompido | `--timeout 0`: quando inalcançável, não pergunta a ninguém, para direto (o motivo fica no disco) |

## O que ele faz de fato {#它实际做了什么}

### Com o que se parece um objetivo {#目标长什么样}

`goal_step` lê o brief, produz duas seções e as congela em `.flower/notes/目标.md`:

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**A lista de verificação é todo o valor desta camada.** "Implementação completa" não é julgável; "rode isto, veja aquilo" é.
A lista vem dos «critérios de aceitação» do brief, mas precisa ser reescrita de forma que cada item possa ser verificado na hora — o item vago o julgador completa.
Só está íntegro quando as duas seções não estão vazias (`statement` com texto, `checks` não vazio); caso contrário este passo não libera.

### O tamanho da lista é definido por "quantas formas de falhar existem" {#清单的长度由有多少种失败方式决定}

Não pelo rigor do julgador. Numa tarefa do tipo `git clone && make && ./app`, **três a cinco itens bastam**:
compilou, sobe, dá para usar.

**Erramos isso na prática** ([HT002](../cases/ht002.md)): uma tarefa de "instalar e rodar o repositório" virou uma lista de **15 itens**,
dos quais só **5** verificavam "a coisa funciona", **6** verificavam "o processo seguiu as regras"
(incluindo checar o mtime de `~/.zshrc` e checar se o diretório `.flower/` tinha sido alterado — que é o diretório do próprio framework)
e **4** eram inverificáveis por princípio.

#### Fronteira não é item de julgamento {#边界不是判定项}

Esta foi a causa principal daquela vez:

| | O que restringe | Como se cumpre |
|---|---|---|
| **Fronteira** | **Como você trabalha** ("instale só dentro do diretório do projeto", "não mexa no código de negócio") | Por **não ultrapassar**, não por auto-comprovação depois |
| **Item de julgamento** | **O que foi entregue** ("subiu ou não", "o resultado está certo") | Por verificação na hora |

Escrever "não rodei `brew install`" como item de julgamento equivale a criar uma verificação a cada fronteira adicionada —
e é justamente na fase de confirmação que se incentiva escrever fronteiras à vontade. Se for mesmo preciso prestar contas, uma frase basta; não desdobre em seis itens.

### Itens inverificáveis já são sinalizados na definição do objetivo {#验不了的条目设目标时就会喊}

Para itens marcados com `[此环境无法验证:原因]`, o `goal_step` emite um aviso **no exato momento em que congela o objetivo**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Por que antecipar**: o destino desses itens já está selado no momento em que o objetivo é definido — no julgamento eles inevitavelmente não passam.
No HT002 gastou-se primeiro **$35.90 de trabalho + $1.40 de julgamento** para só então descobrir isso —
antecipando a descoberta para o passo de definição do objetivo, o custo da mesma informação cai de **$37** para **$0**.

Só avisa, não bloqueia: a pessoa pode escolher rodar assim mesmo (no HT002 a escolha final foi "aceitar esse resultado").
`Goal.unverifiable` é essa lista, e o payload do evento traz dados estruturados para a UI.

### São três conclusões, não duas {#三个结论不是两个}

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

A terceira conclusão é a chave. Só com "atingido/não atingido", um objetivo **que de fato não dá para cumprir** faz o coordenador
girar em falso rodada após rodada até o crédito acabar — aí sim é dinheiro queimado. Por isso o julgador recebe uma exigência explícita:
inalcançável é "mais uma rodada não adianta" (falta uma condição externa necessária, o requisito se contradiz, o item de julgamento simplesmente não pode ser verificado);
"ainda não terminou" é não atingido.

Quando inalcançável, o framework para e pergunta:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Aceitar** → este passo conta como aprovado, o motivo fica no registro
- **Alterar o objetivo** → em seguida pergunta qual é o novo objetivo e o **anexa** ao objetivo original (dá para ver o que mudou), e roda mais uma rodada
- **Você julgou errado** (e qualquer resposta livre que você escreva) → devolve com a sua argumentação e roda mais uma rodada

**Se ninguém responder, ele para**, em vez de continuar girando em falso — isso é intencional. Julgado impossível e sem ninguém a quem perguntar,
continuar rodando é queimar dinheiro rodada após rodada, que é exatamente o que mais se quer evitar. Ao parar, lança `StepAbort`, com o motivo escrito em
`ctx["_aborted"]`; o arquivo de objetivo e o `runs/manifest.json` continuam lá, e a pessoa volta depois para decidir.

!!! warning ""Não conseguiu" e "aqui não dá para verificar" são conclusões diferentes"
    Os três valores de `Verdict` são `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` jamais pode ser tratado como aprovado** — ele segue o caminho "parar e perguntar", não o "mais uma rodada".
    Quando o julgador escreve "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable", **tudo** cai em
    `UNREACHABLE`. Tratar "aqui não dá para verificar" como "atingido" é encerrar o trabalho com um "parece que deve funcionar";
    tratar como "não atingido" é mandá-lo refazer rodada após rodada algo que nunca poderia ser verificado.

### Julgamento ambíguo = não atingido {#判定含糊--未达成}

Ordem de reconhecimento de `Verdict.parse`: primeiro pega, pelas seções de título, a seção "结论 / 判定"; sem seções de título,
o texto inteiro sendo `1` / `true` conta como atingido e `0` / `false` como não atingido (quando se pede ao julgador "devolva só 0/1",
é bem provável que ele realmente devolva só um número); se ainda não bater, procura palavras-chave no texto da conclusão (as mais longas primeiro); por último, procura um `1` / `0` isolado.

**Se nada bater, `state` fica vazio, `ok` é `False` e o framework trata como não atingido.** Isso é deliberado:
"não deu para julgar" e "está pronto" são coisas diferentes; toda ambiguidade vira não atingido, com um motivo padrão acrescentado
("判定者没给出明确结论,按未达成处理").

### Julga-se o artefato, não o código-fonte {#判的是产出物不是源码}

!!! warning "Julgamento que só lê o código-fonte não julga o entregável"
    No [HT001](../cases/ht001.md), o texto original do critério de aceitação era "compilar um executável independente, que rode direto
    no terminal do macOS", e o julgamento apenas leu `Makefile:25-38`, viu que havia mesmo um ramo Darwin e deu **aprovado** —
    o artefato entregue era `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Quem errou não foi a guarda de objetivo**: aquela execução ainda não tinha esse mecanismo, e quem julgou esse item foi um
    auditor independente que o próprio coordenador despachou na hora. Mas com a guarda de objetivo teria escapado igual — o julgador tem
    `can_run=False` por padrão, e nas mãos só `Read` / `Glob` / `Grep`; ele **não consegue rodar `file`**, então também só poderia
    ler o `Makefile` e também daria atingido ao ver o ramo Darwin. O ponto crítico dessa falha não é "quem julga", é "com que evidência se julga".

    Essa lição foi escrita em `JUDGE_RULES`: julga-se o **artefato**, não se aceita inferência do tipo "o código-fonte tem um ramo macOS,
    então deve rodar".

[HT002](../cases/ht002.md) foi a vez em que `judge_can_run` estava ligado e o julgador realmente rodou `file` / `lsof`,
e por isso escapou dessa armadilha — sua primeira frase foi "não vou concluir nada lendo aquela resposta. Vou ao local." E então:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

Aquela frase no prompt de julgamento diz exatamente isso: vá ver o estado real por conta própria, confira item por item da lista, e **item de julgamento sem evidência à vista
é item não aprovado**.

### "Devolver" é continuar, não recomeçar {#打回是接着做不是重头做}

A devolução usa `Step.on_reject`: na rodada seguinte, **dá `resume` na mesma sessão que acabou de ser reprovada**, com o prompt trocado pelo feedback do julgamento
(`Verdict.feedback()` só dá "o que está faltando", não dá a solução). Então o trabalho já feito, os arquivos já lidos e os caminhos errados já percorridos
continuam no contexto; basta cobrir a diferença.

A diferença fica no nome do passo, visível de relance no `runs/manifest.json`:

```text
干活            第一轮
干活#round2     被打回后接着做      ← on_reject 生效,resume 上一轮
干活#retry1     普通重试(重头跑)    ← 没有 on_reject 时的老行为
```

Já o julgador é **sempre uma sessão nova**: o gate do `with_goal` chama `Runtime.run` diretamente, sem `resume`;
o nome do passo carrega a rodada (`干活·判定#1`), e nomes com sufixo não entram na [linhagem](../reference/glossary.md#血缘) entre processos.
Quando o gate não consegue obter `ctx["_runtime"]`, lança `StepAbort`, **não finge aprovação**.

### Pular e redefinir {#跳过与重设}

Quando o arquivo de objetivo já existe e está íntegro, este passo é **pulado** (igual ao brief) — se uma execução de
[longo alcance](../reference/glossary.md#长程) quebrou e foi reiniciada, não faz sentido recalcular as conclusões anteriores. Para redefinir, apague o arquivo ou use `always_set=True`.

**Exceção: no wake você disse mais uma coisa.** Essa frase é anexada ao brief, e então este passo **rededuz** o objetivo
(`always_set=True`). Sem rededuzir, o julgador continuaria lendo a lista antiga congelada, e aquilo que você acrescentou nem entraria no julgamento —
ele daria "atingido" pela lista velha. O custo medido da redução é **$0.41 / 3 minutos**.
Veja [continuidade](continuity.md).

### O julgador pode rodar comandos? {#判定者能不能跑命令}

Por padrão **não**. A lista de dispensa de aprovação de `judge()` são as ferramentas de pergunta mais `Read` / `Glob` / `Grep`;
só com `can_run=True` entra o `Bash`. O trade-off:

- Dar `Bash` (o `--judge-can-run` da CLI) → dá para rodar de verdade os comandos de aceitação, o julgamento fica mais duro
- Mas aí ele consegue alterar a área de trabalho → pode "dar uma ajeitadinha de passagem" e então aprovar, e o julgamento perde sentido

Como o confirmador, **não tem `Write` / `Edit` / `Agent`**. Quem impõe isso é o hook `whitelist_guard`,
**não `allowed_tools`** — este último é uma **lista de dispensa de aprovação, não uma whitelist exclusiva**; o modelo continua conseguindo chamar ferramentas que não estão nela.
Evidência empírica de que as duas afirmações continuam valendo: no HT002, o julgador do passo "设定目标" rodou **11 vezes `Bash`**,
sendo que naquele momento sua lista de dispensa não tinha `Bash` nenhum; na **sonda de $0.1**,
um agente com `allowed_tools=["Read"]` mesmo assim emitiu chamadas de `Write` e `Bash`, e foram a camada de permissão e a segurança de caminho que as barraram
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Hoje esses dois tipos de chamada levam `deny` na hora, pelo hook —
**quem barra é o hook, não a lista**.

!!! warning "O julgador que define o objetivo não recebe `Bash` por padrão"
    `goal_step()` **não tem o parâmetro `can_run`**; só via `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Sem passar explicitamente, ele fica sem `Bash`, e a regra do `JUDGE_RULES` de "primeiro `uname -a` para saber onde você está" não pode ser executada —
    e aí ele pode te escrever uma lista que nesta máquina não tem como ser verificada. `with_goal()` é outra história:
    tem um parâmetro `can_run` próprio (padrão `False`).

### Por que as rodadas têm teto e as perguntas não {#为什么轮数有上限而提问次数没有}

Perguntar quase não custa nada; uma rodada de trabalho é dinheiro vivo. Então:

- **Perguntas sem limite de quantidade** (`max_asks=None`) — pergunta até ficar claro, o próprio confirmador decide
- **Rodadas com teto** (`rounds=3`) — mas a rede de segurança de verdade não é esse número, e sim a terceira conclusão «inalcançável»:
  assim que ela aparece, para e pergunta a uma pessoa, sem depender de esgotar rodadas

## Quando não usar isto {#什么时候不该用它}

**Tarefa tão pequena que julgar dá mais trabalho que fazer.** Esta camada complica o simples, e isso foi medido:
naquele "clonar um repositório, instalar e rodar no macOS" do HT002, a lista de julgamento virou 15 itens,
dos quais 6 verificavam obediência de processo e 4 eram inverificáveis por princípio; aquela rodada de julgamento sozinha custou **$1.4037 / 37 turnos / 0.09h**,
e a execução inteira **$38.2409 / 0.97h**. Quando a tarefa só tem duas ou três formas de falhar, `--no-goal` compensa mais.

**O objetivo não vira uma lista julgável.** Trabalho exploratório ("dá uma olhada nesse repositório para ver do que se trata") não tem critério de "terminou";
forçar um objetivo só produz uma lista bonita e injulgável. Para esse tipo de trabalho use `flower once`, ou `--no-goal`.

**O item de julgamento crítico não é verificável neste ambiente.** O julgador tem `can_run=False` por padrão, com ferramentas apenas
`Read` / `Glob` / `Grep` — **ele não consegue rodar `file`**, só ler o código-fonte. No [HT001](../cases/ht001.md),
aquele critério de aceitação "roda direto no terminal do macOS" conviveu com uma execução inteira dentro de um contêiner Linux:
**nenhum julgador consegue verificar um binário macOS dentro do contêiner**, seja ele auto-avaliação ou independente.
`--judge-can-run` salva uma parte (pelo menos consegue rodar `file`); a parte que não salva deveria ser marcada, já na definição do objetivo,
como `[此环境无法验证:…]`, para seguir o caminho "parar e perguntar", em vez de esperar que o julgador fique mais esperto.

**Não supervisionado e sem permissão para interromper.** Quando julga inalcançável e ninguém responde, este passo **para**, e todo o [fluxo de trabalho](../reference/glossary.md#流程) acaba ali.
Se o que você quer é "termine de rodar e depois a gente vê", use `--no-goal`; se é "pare, mas não fique esperando", use `--timeout 0` —
a pergunta cai no vazio imediatamente e o motivo é escrito no disco.

**Ele não cuida se o requisito está certo.** A lista de julgamento é deduzida do brief; se o brief está errado, o julgamento apenas verifica com precisão uma coisa errada.
Isso é assunto da camada de [confirmação prévia](clarify.md).
