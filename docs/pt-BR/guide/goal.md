# Goal guard

"Está pronto?" não é o worker quem diz. O [judge](../reference/glossary.md#判定者) é um papel que só define o objetivo,
só emite verdict e não põe a mão na massa: antes de começar, transforma o [brief](../reference/glossary.md#需求确认书) numa
checklist verificável; depois disso, ao fim de cada rodada de trabalho, **julga uma vez de forma independente** e produz um [verdict](../reference/glossary.md#判定) —
alcançado, segue em frente; não alcançado, devolve com o "o que falta" para continuar;
julgado como impossível, para e pergunta a uma pessoa.

## Que problema isso resolve

O [clarify](clarify.md) barra **"o que está sendo feito não é o que se queria"**. Esta camada barra outra coisa:
**"na verdade não terminou, mas ele disse que terminou"**. As duas coisas precisam ficar separadas, porque falham de formas diferentes:

| | Como a falha aparece | Quando ela vem à tona |
|---|---|---|
| Requisito errado | Todo entregável foi construído em cima do requisito errado | Horas depois, com tudo perdido |
| Julgamento de conclusão errado | Testes rodados pela metade, um ponto corrigido e três esquecidos, "deve estar ok" | Quando você mesmo vai usar |

Por que o segundo tipo não pode ficar a cargo do próprio worker: **ele tem um viés otimista sistemático**.
Não é desonestidade — é que ele não enxerga o próprio ponto cego. Ele sabe o que fez; não sabe o que deixou passar.

Por isso o verdict fica com um papel que **não participou do trabalho e roda na própria [sessão](../reference/glossary.md#会话)**.
Ele vê só o objetivo e o estado real; não sabe quantas tentativas o worker fez nem o quanto sofreu, e portanto não arruma desculpas por ele.
É a mesma razão pela qual o clarifier roda numa sessão independente.

## Como usar (código mínimo)

### Zero código: linha de comando

```bash
flower                      # já vem com goal guard por padrão
flower --no-goal            # desliga: terminou o trabalho, terminou o passo
flower --rounds 5           # no máximo cinco rodadas de trabalho (padrão 3)
flower --judge-can-run      # deixa o judge rodar comandos (verdict mais duro)
```

### Ligação manual

Duas funções, cada uma com metade da tarefa; não misture: `goal_step()` **define o objetivo** (um step independente),
e `with_goal()` é o **loop de verdict** (embrulha um step de trabalho).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # por padrão, sem limite de perguntas
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
| `goal_path` | — | Onde o objetivo é gravado. Coloque sob `notes/` do [workbench](../reference/glossary.md#工作台), pelo mesmo motivo do brief |
| `brief_key` | `"确认需求"` | De qual chave do `ctx` ler o brief. **Se não achar, recebe apenas `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nome do step, e também a chave no `ctx` |
| `spec` / `instructions` | `None` / `""` | `AgentSpec` próprio, ou instruções de domínio anexadas ao judge |
| `always_set` | `False` | `True` = redefine sempre |
| `on_fail` / `retries` | `"stop"` / `0` | Igual ao `Step` |
| `**spec_kw` | — | Repassado para `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` embrulha um step de trabalho num loop com verdict:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` é o total de rodadas, não rodadas extras** — ele vira `retries = max(0, rounds - 1)`,
então `rounds=3` roda no máximo três rodadas de trabalho, e `rounds=1` significa "roda uma vez, julga uma vez, e falha se não passar".
Assinatura completa e semântica dos campos em [Python API](../reference/api.md).

O `ctx` ganha três chaves:

```python
ctx[GOAL_KEY]     # "_goal" —— objeto Goal; ctx["设定目标"] é o markdown dele
ctx[VERDICT_KEY]  # "_verdict" —— o Verdict mais recente, para a UI
ctx[ROUND_KEY]    # "_goal_rounds" —— quantas rodadas já correram
```

O judge é despachado via `ctx["_runtime"]` — o `Workflow.run` coloca o runtime e a saída de eventos no `ctx`,
então o `gate` consegue subir um agent sozinho, e o processo de verdict continua chegando na sua UI
(caso contrário, aqueles dez e tantos segundos de tela preta parecem travamento).

Quando não estiver saindo redondo, mexa primeiro nestes botões:

| Sintoma | O que ajustar |
|---|---|
| Verdict frouxo demais, diz alcançado sem estar | `--judge-can-run` para ele rodar de verdade; ou acrescente critérios de domínio em `instructions` |
| Verdict rígido demais, devolve sempre | Veja se a checklist de verificação em `目标.md` está mais exigente que o requisito. **Edite esse arquivo** |
| Rodadas girando em falso | O judge deveria dar "inalcançável" e deu "ainda não". Adicione instruções dizendo o que conta como impossível |
| Caro demais | `--rounds 1`, ou `--no-goal` para desligar por completo |
| Não quer ser interrompido | `--timeout 0`: em caso de inalcançável, não pergunta a ninguém, simplesmente para (o motivo fica em disco) |

## O que ele realmente faz

### Como é um objetivo

`goal_step` lê o brief, produz duas seções e congela em `.flower/notes/目标.md`:

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**A checklist de verificação é todo o valor desta camada.** "Implementação completa" não é verificável; "rodar o quê, ver o quê" é.
A checklist sai dos «critérios de aceitação» do brief, mas precisa ser reescrita de forma que cada linha possa ser verificada na hora — as linhas vagas o judge completa.
Só é considerada completa quando as duas seções não estão vazias (`statement` com conteúdo, `checks` não vazio); caso contrário, este step não libera.

### O tamanho da checklist é decidido por "quantos modos de falha existem"

Não pelo rigor do judge. Para uma tarefa do tipo `git clone && make && ./app`, **três a cinco linhas bastam**:
build ok, roda, dá para usar.

**Já tropeçamos nisso na prática** ([HT002](../cases/ht002.md)): uma tarefa de "instalar o repositório e colocar para rodar" virou uma checklist de **15 linhas**,
das quais apenas **5** verificavam "se a coisa funciona", **6** verificavam "se o processo seguiu as regras"
(incluindo checar o mtime de `~/.zshrc` e se o diretório `.flower/` foi alterado — que é o diretório do próprio framework),
e **4** eram inverificáveis por princípio.

#### Fronteiras não são itens de verificação

Essa foi a causa principal daquele caso:

| | O que restringe | Como se cumpre |
|---|---|---|
| **Fronteira** | **Como você trabalha** ("instale só dentro do diretório do projeto", "não toque no código de negócio") | Por **não ultrapassar**, não por autoprova posterior |
| **Item de verificação** | **O que foi entregue** ("está rodando?", "o resultado está certo?") | Por verificação na hora |

Transformar "não rodei `brew install`" num item de verificação equivale a somar uma checagem a cada fronteira acrescentada —
e é justamente na fase de clarify que se incentiva listar todas as fronteiras. Se realmente precisar prestar contas, uma frase resolve; não desdobre em seis itens.

### Itens inverificáveis são apontados já na definição do objetivo

Para itens marcados com `[此环境无法验证:原因]` na checklist, o `goal_step` emite um aviso **no exato momento em que congela o objetivo**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Por que avisar antes**: o destino desses itens já está selado no momento em que o objetivo é definido — no verdict eles inevitavelmente não passam.
No HT002, gastaram-se primeiro **$35.90 de trabalho + $1.40 de verdict** para só então descobrir isso —
antecipando a descoberta para o step de definição do objetivo, a mesma informação custa **$0** em vez de **$37**.

Apenas avisa, não bloqueia: a pessoa pode escolher rodar assim mesmo (no HT002 a escolha final foi "aceitar este resultado").
`Goal.unverifiable` é essa lista, e o payload do evento traz os dados estruturados para a UI.

### Três conclusões, não duas

```text
trabalho ──> verdict ──alcançado─────> segue em frente
                     ├─ainda não─────> devolve com o "o que falta", resume a mesma sessão e continua
                     └─inalcançável──> para e pergunta: aceitar / mudar o objetivo / você julgou errado
```

A terceira conclusão é a chave. Com apenas "alcançado/ainda não", um objetivo **que de fato é impossível** faria o coordinator
girar em falso rodada após rodada até estourar o crédito — aí sim é queimar dinheiro. Por isso o judge recebe uma exigência explícita:
só é inalcançável quando "mais uma rodada não adianta" (falta uma condição externa necessária, o requisito se contradiz, o item de verificação simplesmente não pode ser verificado);
"ainda não terminou" é ainda não alcançado.

Quando é inalcançável, o framework para e pergunta:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Aceitar** → o step conta como aprovado, e o motivo fica no registro
- **Mudar o objetivo** → ele pergunta qual é o novo objetivo e o **anexa** ao objetivo original (assim dá para ver o que mudou), e roda mais uma rodada
- **Você julgou errado** (assim como qualquer resposta livre que você digite) → devolve com o seu argumento e roda mais uma rodada

**Se ninguém responde, ele para**, em vez de continuar girando em falso — isso é intencional. Julgado impossível e sem ninguém para perguntar,
continuar rodando é queimar dinheiro rodada após rodada, e é exatamente isso que mais se quer evitar. Ao parar, lança `StepAbort`, o motivo vai para
`ctx["_aborted"]`, o arquivo de objetivo e `runs/manifest.json` continuam lá, e a pessoa decide quando voltar.

!!! warning ""Não foi feito" e "aqui não dá para verificar" são conclusões diferentes"
    Os três valores de `Verdict` são `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` jamais pode ser tratado como aprovação** — ele segue o caminho de "parar e perguntar", não o de "mais uma rodada".
    Tudo que o judge escreve como "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" cai **inteiramente** em
    `UNREACHABLE`. Tratar "aqui não dá para verificar" como "alcançado" é fechar o trabalho com um "parece que deve funcionar";
    tratar como "ainda não" é obrigá-lo a refazer, rodada após rodada, algo que nunca poderia ser verificado.

### Verdict ambíguo = não alcançado

Ordem de reconhecimento do `Verdict.parse`: primeiro pega a seção "结论 / 判定" pelo título; se não houver seção com título,
um texto inteiro igual a `1` / `true` conta como alcançado, e `0` / `false` como não alcançado (quando se pede ao judge para "responder só 0/1",
é bem provável que ele devolva de fato só um número); se ainda não bater, procura palavras-chave no texto da conclusão (termos mais longos primeiro); por fim, procura um `1` / `0` isolado.

**Quando nada bate, `state` fica vazio, `ok` é `False` e o framework trata como não alcançado.** Isso é deliberado:
"não deu para julgar" e "está pronto" são coisas diferentes; ambiguidade é sempre não alcançado, com um motivo padrão anexado
("判定者没给出明确结论,按未达成处理").

### Julga-se o artefato entregue, não o código-fonte

!!! warning "Verdict que só lê código-fonte não julga o entregável"
    No [HT001](../cases/ht001.md), o critério de aceitação dizia literalmente "compilar um executável independente, rodando direto
    no terminal do macOS", e o verdict apenas leu que `Makefile:25-38` de fato tinha um ramo Darwin e deu **aprovado** —
    o artefato entregue era `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Quem errou não foi o goal guard**: naquela run esse mecanismo ainda não existia, e quem julgou esse item foi um
    auditor independente despachado ad hoc pelo próprio coordinator. Mas com goal guard teria escapado igual — o judge tem `can_run=False` por padrão,
    com apenas `Read` / `Glob` / `Grep` na mão; ele **não consegue rodar `file`**, então também só poderia ler o `Makefile` e também
    daria alcançado ao ver o ramo Darwin. O ponto dessa falha não é "quem julga", e sim "com qual evidência se julga".

    Essa lição virou regra em `JUDGE_RULES`: julga-se o **artefato**, e não se aceitam inferências do tipo "o código tem um ramo macOS, logo
    deve rodar".

O [HT002](../cases/ht002.md) foi a vez em que `judge_can_run` estava ligado e o judge realmente rodou `file` / `lsof`,
e por isso escapou dessa armadilha — a primeira frase dele foi "não tiro conclusão a partir daquela resposta. Vou ao campo." E então:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

Aquela frase no prompt de verdict quer dizer o mesmo: vá ver com os próprios olhos, confira item por item da checklist, e **item de verificação sem evidência
visível é item não aprovado**.

### "Devolver" é continuar, não recomeçar

A devolução usa `Step.on_reject`: na rodada seguinte, **faz `resume` na sessão que acabou de ser rejeitada**, trocando o prompt pelo feedback do verdict
(`Verdict.feedback()` só entrega "o que falta", não entrega solução). Assim, o trabalho já feito, os arquivos já lidos e os desvios já percorridos
continuam no contexto; basta fechar a lacuna.

A diferença fica no nome do step, visível de bate-pronto em `runs/manifest.json`:

```text
干活            primeira rodada
干活#round2     continua após devolução     ← on_reject em ação, resume da rodada anterior
干活#retry1     retry comum (recomeça)      ← comportamento antigo, sem on_reject
```

Já o judge **é sempre uma sessão nova**: o gate do `with_goal` chama `Runtime.run` direto, sem `resume`;
o nome do step carrega a rodada (`干活·判定#1`), e nomes com sufixo não entram na [lineage](../reference/glossary.md#血缘) entre processos.
Quando o gate não consegue obter `ctx["_runtime"]`, lança `StepAbort` — **não finge que passou**.

### Pular e redefinir

Quando o arquivo de objetivo já existe e está completo, este step é **pulado** (igual ao brief) — se uma run [long-horizon](../reference/glossary.md#长程)
quebrou e foi reiniciada, não se deve recalcular as conclusões anteriores. Para redefinir, apague o arquivo, ou use `always_set=True`.

**Exceção: no wake você disse mais uma coisa.** Essa frase é anexada ao brief, e então este step **rededuz o objetivo**
(`always_set=True`). Sem rededuzir, o judge continuaria lendo a checklist antiga congelada, e aquilo que você acabou de acrescentar
nem entraria no verdict — ele daria "alcançado" pela lista velha. O custo medido da rededução é **$0.41 / 3 minutos**.
Veja [continuity](continuity.md).

### O judge pode rodar comandos?

Por padrão, **não**. A lista de pré-aprovação de `judge()` são as ferramentas de pergunta mais `Read` / `Glob` / `Grep`;
só com `can_run=True` entra `Bash`. O trade-off:

- Dar `Bash` (`--judge-can-run` na CLI) → dá para rodar de verdade os comandos de aceitação, e o verdict fica mais duro
- Mas aí ele pode alterar o workspace → ele pode "dar um jeitinho" e então aprovar, e o verdict perde sentido

Assim como o clarifier, **não há `Write` / `Edit` / `Agent`**. Quem impõe isso é o hook `whitelist_guard`,
**não `allowed_tools`** — este último é uma **lista de pré-aprovação, não uma whitelist exclusiva**, e o modelo continua conseguindo chamar ferramentas fora dela.
Evidência medida de que as duas coisas continuam valendo: no HT002, o judge do step "设定目标" rodou **11 vezes `Bash`**,
enquanto naquele momento `Bash` sequer estava na sua lista de pré-aprovação; e na **sonda de $0.1**,
um agent com `allowed_tools=["Read"]` emitiu chamadas de `Write` e `Bash` do mesmo jeito, barradas pela camada de permissão e pela segurança de caminho
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Hoje essas duas chamadas levam `deny` do hook na hora —
**quem barra é o hook, não a lista**.

!!! warning "O judge que define o objetivo não recebe `Bash` por padrão"
    `goal_step()` **não tem parâmetro `can_run`**; só via `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Sem passar explicitamente, ele não tem `Bash`, e a regra de `JUDGE_RULES` que manda "primeiro rodar `uname -a` para saber onde você está" não pode ser executada —
    e aí ele pode escrever uma checklist que nesta máquina não tem como ser verificada. `with_goal()` é outra história:
    tem um parâmetro `can_run` próprio (padrão `False`).

### Por que as rodadas têm teto e as perguntas não

Perguntar quase não custa nada; uma rodada de trabalho é dinheiro vivo. Portanto:

- **Perguntas sem limite** (`max_asks=None`) — pergunta até ficar claro, com o clarifier decidindo por conta própria
- **Rodadas com teto** (`rounds=3`) — mas a rede de segurança real não é esse número, e sim a terceira conclusão «inalcançável»:
  assim que ela aparece, para e pergunta a alguém, sem depender de esgotar as rodadas

## Quando não usar

**A tarefa é tão pequena que o verdict é mais prolixo que o trabalho.** Esta camada complica o simples, e isso foi medido:
no HT002, aquele "clonar um repositório, instalar e rodar no macOS" virou uma checklist de 15 linhas,
das quais 6 verificavam conformidade de processo e 4 eram inverificáveis por princípio; aquela rodada de verdict custou **$1.4037 / 37 turnos / 0.09h**,
e a run inteira, **$38.2409 / 0.97h**. Quando a tarefa só tem dois ou três modos de falha, `--no-goal` sai mais em conta.

**O objetivo não vira uma checklist verificável.** Trabalho exploratório ("dá uma olhada e me diz do que se trata este repositório") não tem critério de "terminou";
forçar um objetivo só produz uma checklist bonita e inaplicável. Para isso, use `flower once`, ou `--no-goal`.

**O item de verificação crucial não pode ser verificado neste ambiente.** O judge tem `can_run=False` por padrão, com ferramentas
apenas `Read` / `Glob` / `Grep` — **ele não consegue rodar `file`**, só ler o código. No [HT001](../cases/ht001.md),
aquele critério de "rodar direto no terminal do macOS" existia numa run inteira dentro de um contêiner Linux:
**nenhum judge consegue validar um binário macOS dentro do contêiner**, seja ele auto-avaliador ou independente.
`--judge-can-run` salva uma parte (ao menos dá para rodar `file`); a parte que não salva deveria ser marcada, já na definição do objetivo,
como `[此环境无法验证:…]`, para seguir o caminho de "parar e perguntar", em vez de esperar que o judge fique mais esperto.

**Execução desassistida em que interrupção não é permitida.** Quando o verdict é inalcançável e ninguém responde, este step **para**, e o [workflow](../reference/glossary.md#流程) inteiro termina aí.
Se o que você quer é "rodar até o fim, e depois a gente vê", use `--no-goal`; se o que você quer é "parar, mas sem esperar", use `--timeout 0` —
a pergunta cai no vazio imediatamente e o motivo é gravado em disco.

**Ele não cuida de o requisito estar certo.** A checklist é deduzida do brief; se o brief está errado, o verdict apenas verificará com precisão a coisa errada.
Isso é assunto da camada de [clarify](clarify.md).
