# Projetar um workflow

O framework cuida apenas do mecanismo: como um step roda, como as sessions se encadeiam, o que fazer quando algo falha, como economizar contexto.
**[O workflow](../reference/glossary.md#流程) é você quem escreve** — o framework não sabe em que projeto você está nem em que linguagem,
e nem deve saber. Esta página trata de como projetar um workflow; a tabela completa de campos de `Step` e `Workflow` está na
[API Python](../reference/api.md).

## Que problema resolve {#解决什么问题}

Um run [long-horizon](../reference/glossary.md#长程) não é algo que caiba em um único prompt: primeiro esclarecer o requisito,
depois pesquisar, depois implementar, depois revisar — cada trecho tem seu próprio papel, seu próprio contexto, seu próprio critério de aceitação.
Se você escrever tudo em um único prompt, o modelo decide sozinho qual trecho pular; escrito como workflow, **a ordem, as condições de saída e a passagem de estado viram
código Python** — legível, testável, e você pode reexecutar só o step que quebrou.

`Workflow` faz apenas três coisas:

- roda uma sequência de [steps](../reference/glossary.md#步骤) em ordem
- decide o que cada step enxerga do que veio antes (três formas de encadear session + um dicionário `ctx`)
- decide quando repetir e quando sair antes do fim

Ele não contém nenhuma suposição de domínio. Onde cortar, o que aceitar em cada step, o que fazer quando não passa — essas quatro coisas são "projetar o workflow".

## Como usar (código mínimo) {#怎么用最小代码}

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # Session nova: só consome o que foi passado no prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Ainda uma session nova, injetando no prompt o resultado do step anterior (barato, evita contaminação)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

O argumento de `flower run` é `módulo:atributo` ou `caminho/arquivo:atributo`. Se o objeto obtido for chamável, ele é chamado uma vez;
com o `Workflow` em mãos, roda. Ao terminar, o terminal imprime o custo total e o caminho do run manifest.

Você também pode escrever seu próprio driver; o primeiro argumento de `Workflow.run` é um `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## O que ele faz de fato {#它实际做了什么}

### O que um Step recebe e o que precisa retornar {#一个-step-收到什么必须返回什么}

`Step` não é uma função, é uma **declaração**. Quem executa de fato é `Runtime.run(step.spec, prompt renderizado, ...)` —
**um step = uma chamada de `Runtime.run` = uma [session](../reference/glossary.md#会话)**.

Os três primeiros campos são posicionais, `Step(name, spec, prompt)`:

- `name` — nome do step. É ao mesmo tempo a chave no `ctx`, o nome da linha em `runs/manifest.json`
  e a chave da [linhagem](../reference/glossary.md#血缘) entre processos.
- `spec` — com qual `AgentSpec` rodar. Define a whitelist de ferramentas, o modelo e o budget deste step.
- `prompt` — `str`, ou `(ctx) -> str`. Se for chamável, recebe o `ctx` atual;
  **essa é a forma mais barata de alimentar o resultado do step anterior** (a outra é encadear a session, veja abaixo).

O que este step "retorna" é um `StepResult`, mas dentro do workflow você recebe duas coisas:

- `ctx[step.name]` — por padrão `result.text`; se você passou `reduce`, é o retorno de `reduce`;
- `ctx["_results"][step.name]` — o `StepResult` completo (custo, número de turnos, tentativas, `session_id`).

`result.text` **só coleta o corpo da main thread**: as falas do subagent ficam no transcript dele, o
[task brief](../reference/glossary.md#任务书) despachado para ele é `kind="prompt"`, o erro sintético de queda de conexão é `kind="error"`
— nenhum dos três entra.

### reduce: não é açúcar sintático {#reduce不是糖}

Por padrão, o que passa adiante é literalmente o que o modelo disse. Em alguns steps, o que foi dito **não deve** ser repassado como está:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

Na prática, o step de esclarecimento do requisito **cola o código inteiro** além dos quatro blocos. O que vai para os steps seguintes precisa ser os quatro blocos já parseados,
senão aquele monte de código entra no prompt do próximo step. É com esse campo que `clarify_step` se protege.

`reduce` **precisa ser uma função síncrona**; `gate` / `when` / `on_reject` podem ser async.

### Como o estado flui pelo ctx {#状态怎么在-ctx-里流动}

`ctx` é um `dict[str, Any]` — é o próprio `Workflow.context`. Ao fim de cada step, a escrita segue esta tabela:

| Situação | `ctx[nome do step]` | Outros |
|---|---|---|
| `when(ctx)` retorna False | **não escreve**, o step inteiro é pulado | não produz result nem entra em `_results` |
| Passou | `reduce(result, ctx)`; sem `reduce`, `result.text` | |
| Falhou + `on_fail="stop"` (padrão) | **não escreve** | escreve `ctx["_failed_at"]`, o workflow inteiro para neste step |
| Falhou + `on_fail="skip"` | **não escreve** | continua para o próximo |
| Falhou + `on_fail="continue"` | `result.text` (incompleto, **não passa por `reduce`**) | continua para o próximo |

Passando ou não, `ctx["_results"][nome do step]` é sempre escrito; se `result.session_id` não for vazio, também é escrito em
`ctx["_sessions"]` e registrado na linhagem.

**Para saber se o workflow foi bem-sucedido, olhe `ctx.get("_failed_at")`**, não se o último step produziu saída.

As chaves iniciadas por underscore são colocadas pelo próprio `Workflow.run`: `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — não use nenhuma delas como nome de step. Cada mecanismo também coloca as suas
(`_brief` / `_goal` / `_verdict` etc.); a lista completa está na [API Python](../reference/api.md).

Dentre elas, `_runtime` e `_on_event` são para o `gate`: um gate pode despachar um agent próprio para emitir um verdict,
e esse processo continua sendo impresso na UI — senão a interface fica preta por uma dúzia de segundos e parece travada.
É assim que o [goal guard](goal.md) é implementado.

`ctx` é o mesmo dict: **se você rodar o mesmo objeto `Workflow` uma segunda vez, as chaves da primeira ainda estão lá**.
Para recomeçar limpo, crie um novo, ou passe `context={}` explicitamente.

!!! warning "com on_fail=skip, `ctx[nome do step]` não é escrito"
    Um step posterior que faça `lambda ctx: ctx["某步"]` estoura `KeyError` direto. Para seguir com o resultado incompleto, use
    `on_fail="continue"`; se realmente quiser pular, os steps seguintes precisam se proteger com `ctx.get(...)`.

### Verdict e devolução: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` julga "terminou, mas está aceitável?". Dois detalhes que você precisa saber:

- **Quando `result.ok` é falso, o `gate` nem é chamado** (curto-circuito).
- **É chamado uma única vez por tentativa**, e a conclusão fica guardada para uso posterior — ele pode ter efeitos colaterais. O gate de `clarify_step` faz o
  [brief](../reference/glossary.md#需求确认书) ir para o disco; disparar de novo significa escrever no disco de novo.

O que acontece depois de um gate reprovar depende de você ter fornecido ou não `on_reject`:

| | Como roda a próxima rodada | Nome no manifest |
|---|---|---|
| Só `retries` | roda do zero, prompt original, `resume_from` original | `X#retry1` |
| Com `on_reject` | **continua a session que acabou de ser reprovada**, o prompt vira o retorno de `on_reject`, `fork` é forçado a False | `X#round2` |

O segundo caso é "devolver, dizendo o que faltou, e deixar continuar" — o trabalho já feito e o contexto continuam lá.
Se `on_reject` retornar string vazia, ou se aquela tentativa simplesmente não obteve `session_id`, o comportamento degrada para rodar do zero.

O `gate` também pode levantar `StepAbort`, que significa **não adianta tentar de novo, não gaste os turnos restantes**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Depois de levantado: o motivo é registrado em `ctx["_aborted"]`, o step é tratado como falha e segue o `on_fail` (padrão `"stop"`),
o **loop de retry dá break na hora**, e nenhum dos `retries` restantes é consumido.

Guarde bem a diferença: **retornar False é "desta vez não deu, mais uma rodada"; `StepAbort` é "mais uma rodada não resolve".**
O caso típico é o objetivo ser julgado impossível neste ambiente e não haver a quem perguntar — continuar girando em falso é a opção mais cara.

### Não confunda as duas camadas de retry {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Cobre o quê | falha de negócio: `gate` reprovou, `result.ok` falso | infraestrutura: oscilação de rede, queda, 5xx |
| Como refaz | **refaz o step inteiro**, mesmo prompt e mesmo `resume_from` | **resume a partir do ponto de interrupção**, o custo anterior não é jogado fora |
| O que faz antes | nada | sondas DNS + TCP esperando a rede voltar (sem HTTP, sem credencial; a sonda tem que ser gratuita) |
| Não retentáveis | — | credencial errada ou parâmetro errado param imediatamente, sem espera |

O prompt usado na continuação **deliberadamente não contém nenhum detalhe do erro** — o modelo precisa saber "você foi interrompido, continue",
não precisa saber se foi ENOTFOUND ou 503.

### Encadear os steps {#把步骤串起来}

Há três formas de passar estado entre steps; a escolha determina o que o próximo step enxerga:

| Forma | O próximo step enxerga | Onde usar |
|---|---|---|
| `resume_from=None` (padrão) + injeção no prompt | só o texto que você injetou | steps independentes. Barato, evita contaminação |
| `resume_from="nome do step anterior"` | histórico completo da session | quando é preciso memória contínua |
| `resume_from="nome do step anterior"` + `fork=True` | histórico completo, mas em outro ramo | revisão / múltiplas alternativas em paralelo / retry sem sujar a linha original |

O step apontado por `resume_from` **precisa ter realmente produzido uma session**. Se ele foi pulado por `when`, ou simplesmente não rodou,
`Workflow.run` levanta `ValueError` direto — não degrada silenciosamente para uma session nova, porque isso faria a suposição de "memória contínua"
falhar sem alarde.

Algumas lições de projeto pagas repetidamente:

1. **Um step, um objetivo aceitável.** A fronteira do step é a fronteira do contexto: onde há `resume_from=None`,
   todos aqueles resultados de ferramenta anteriores deixam de ser residentes. Veja [Economia de contexto](context.md).
2. **Na dúvida, comece por `clarify_step`.** Em long-horizon, "entendi o objetivo errado" é o erro mais caro,
   e é justamente daquele tipo que nenhuma das camadas de economia de contexto consegue limpar. Veja [Clarify](clarify.md).
3. **A tarefa despachada tem que ser autossuficiente.** O subagent tem contexto limpo; ele não sabe o que o [coordenador](../reference/glossary.md#协调者)
   sabe. Escreva o contexto necessário no task brief, ou diga a ele qual artifact ler.
4. **Saída longa vai para o disco, não para a conversa.** Isso já está escrito em `WORKER_RULES`; não anule com suas `instructions`
   ("cole o log completo de volta para eu ver").
5. **No `gate`, priorize condições duras.** Se o arquivo existe, se o exit code é 0 — coisas decidíveis em uma linha de Python não devem ser despachadas para um modelo.
   Se precisar de um modelo para julgar, use o `with_goal` pronto — ele troca o gate por uma implementação que roda um
   [judge](../reference/glossary.md#判定者) independente; não improvise isso à mão dentro do gate.
6. **Alterações paralelas no mesmo repositório: `worker(isolate=True)`.** O encerramento (merge, limpar worktree, abrir PR) hoje fica
   por conta do seu workflow; o harness só garante que as alterações caiam cada uma no seu próprio worktree.

### O workbench precisa estar pendurado no Workflow {#工作台要挂在-workflow-上}

Sempre que o workflow precisar escrever arquivos no [workbench](../reference/glossary.md#工作台) — o caso típico é
`clarify_step(brief_path=...)` — você precisa criar um `Workbench` e pendurá-lo **ao mesmo tempo** em `Workflow.workbench`
e entregá-lo ao `Runtime`:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

Pendurar o `channel` no workflow tem duas razões: `run()` conecta o `on_event` dele à mesma saída de eventos
(apenas se `channel.on_event` ainda for `None`), e o driver depende desse campo para saber a quem responder.

!!! warning "montar o caminho do workbench à mão falha em silêncio"
    O local padrão de `Runtime(workbench=True)` é `<run_dir>/workbench`, enquanto o de `Workbench(ws)` é
    `<ws>/.flower` — **não são o mesmo diretório**. Quando o workflow é chamado pela CLI, ele não enxerga `run_dir`; montar o caminho à mão
    só o leva para outro lugar, e então o brief é escrito no diretório A enquanto o índice injetado varre o diretório B, **e não dá erro**.
    Criar um objeto e compartilhá-lo dos dois lados elimina o problema; quando `Workflow.workbench` existe, o `-W` da linha de comando é ignorado
    e ele prevalece.

### `continuous=True`: rodar o mesmo caminho outra vez {#continuoustrue同一个路径再跑一次}

As três formas acima falam de step a step **dentro de um único run**. Entre processos é outro eixo:

```python
Workflow([...], continuous=True)     # 默认值
```

Ao rodar de novo no mesmo workspace, cada step continua a session da vez anterior — via o mapeamento
«nome do step → session_id» em `<run_dir>/lineage.json`. Ao carregar, cada registro passa por `runtime.has_session()` para verificar se a session ainda existe na base,
e só é usada se estiver viva: o arquivo de linhagem pode sobreviver ao `sessions.db`, e dar resume numa session inexistente só estoura depois que o subprocesso sobe.

Três consequências:

- **`resume_from=None` não significa "session totalmente nova".** Na primeira execução sim; na segunda, não. Para ter sempre session nova,
  escreva explicitamente `Workflow(..., continuous=False)`.
- **Na [continuidade](../reference/glossary.md#接续), o contexto só cresce.** Se quiser dizer outra coisa na continuidade, use
  `Step.resume_prompt` — o que já está no contexto do outro lado não deve ser reenviado.
- Steps com `resume_from` explícito não são afetados; ele tem prioridade.

!!! warning "o nome do step é a chave entre processos"
    Mudar o nome de um step equivale a cortar a linhagem daquele step: na próxima execução ele não continua mais, e **não dá erro**. Os nomes de retry com sufixo `#retry1` /
    `#round2` **não entram na linhagem** (o que se registra é sempre o nome original); essa é uma das formas de garantir que "o judge é sempre uma session nova".

O design completo e `--new` estão em [Continuidade](continuity.md).

## Quando não usar {#什么时候不该用它}

- **Só um agent, sem necessidade de verdict** — não embrulhe em `Workflow`. Chame `await rt.run(spec, "…")` direto,
  ou na linha de comando `flower once "读一眼这个仓库"`.
- **O formato é exatamente "esclarecer requisito → definir objetivo → trabalhar"** — use o
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) pronto,
  sem escrever o seu:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    São **três steps**: `确认需求` → `设定目标` → `干活` (com loop de verdict; o step de verdict se chama `干活·判定#N`).
    Com `goal=False` não há o segundo step nem o loop de verdict; com `clarify_only=True` fica só o primeiro step.
    Ele já traz `HumanChannel` e `Workbench` pendurados no workflow, então
    `Runtime(workbench=wf.workbench)` é usado direto — não monte outro.

    Também dá para não escrever código: entre no diretório do projeto e rode `flower "帮我做一个 X"`, que é exatamente isso.
    **Ele não é "o design de workflow recomendado"**, é só o que permite rodar com zero configuração.

- **Steps cortados mais fino que "um objetivo aceitável"** — prejuízo líquido. Cada step abre uma session nova,
  e uma session nova tem um piso de inicialização (medido em cerca de 34k de contexto para o coordenador) que não se dilui.
- **Querer voltar a uma mensagem específica depois do fato** — por `Workflow` não dá; ele nunca passa `resume_at`.
  Chame `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` diretamente.

Como escolher o papel (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) e a semântica campo a campo de `Step` e `Workflow`
estão na [API Python](../reference/api.md); os termos, no [Glossário](../reference/glossary.md).
