# Projetar um workflow

O framework cuida apenas do mecanismo: como um passo roda, como as sessões se encadeiam, o que fazer quando falha, como economizar contexto.
**O [workflow](../reference/glossary.md#流程) é você quem escreve** — o framework não sabe em que projeto você está, nem em que linguagem,
e nem deveria saber. Esta página trata de como projetar um workflow; a tabela completa de campos de `Step` e `Workflow` está na
[API Python](../reference/api.md).

## Que problema resolve

Uma run [long-horizon](../reference/glossary.md#长程) não cabe em um único prompt: primeiro esclarecer o requisito,
depois pesquisar, depois implementar, depois revisar — cada trecho tem seu próprio papel, seu próprio contexto, seus próprios critérios de aceitação.
Se você escrever tudo em um único prompt, o modelo decide sozinho qual trecho pular; escrito como workflow, **a ordem, as condições de saída e a passagem de estado viram
código Python** — legível, testável, e você pode re-rodar apenas o passo que quebrou.

O `Workflow` faz apenas três coisas:

- roda uma sequência de [passos](../reference/glossary.md#步骤) em ordem
- decide o que cada passo enxerga do que veio antes (três formas de encadear sessões + um dicionário `ctx`)
- decide quando tentar de novo e quando sair mais cedo

Ele não carrega nenhuma suposição de domínio. Onde cortar, o que aceitar em cada passo, o que fazer quando não passa — essas quatro coisas são "projetar um workflow".

## Como usar (código mínimo)

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
        # Sessão nova: só consome o que foi passado no prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Ainda uma sessão nova, injetando o resultado do passo anterior no prompt (barato, evita contaminação)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

O argumento de `flower run` é `módulo:atributo` ou `caminho/do/arquivo:atributo`. Se o objeto obtido for chamável, ele é chamado uma vez;
com o `Workflow` em mãos, a run começa. Ao terminar, o terminal imprime o custo total e o caminho do run manifest.

Escrever seu próprio driver também funciona; o primeiro argumento de `Workflow.run` é um `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## O que ele faz de fato

### O que um Step recebe e o que precisa devolver

`Step` não é uma função, é uma **declaração**. O que realmente executa é `Runtime.run(step.spec, prompt renderizado, ...)` —
**um passo = uma chamada de `Runtime.run` = uma [sessão](../reference/glossary.md#会话)**.

Os três primeiros campos são posicionais, `Step(name, spec, prompt)`:

- `name` — nome do passo. É ao mesmo tempo a chave em `ctx`, o nome da linha em `runs/manifest.json`
  e a chave da [linhagem](../reference/glossary.md#血缘) entre processos.
- `spec` — qual `AgentSpec` roda este passo. Ele define a whitelist de ferramentas, o modelo e o budget deste passo.
- `prompt` — `str`, ou `(ctx) -> str`. Quando chamável, recebe o `ctx` atual;
  **essa é a forma mais barata de alimentar o resultado do passo anterior** (a outra é encadear a sessão, veja abaixo).

O que o passo "devolve" é um `StepResult`, mas dentro do workflow você recebe duas coisas:

- `ctx[step.name]` — por padrão `result.text`; se você passou `reduce`, é o valor de retorno de `reduce`;
- `ctx["_results"][step.name]` — o `StepResult` completo (custo, número de turnos, tentativas, `session_id`).

`result.text` **só coleta o texto da main thread**: as falas do subagent ficam no transcript dele, a [task brief](../reference/glossary.md#任务书)
enviada a ele é `kind="prompt"`, e o erro sintético de desconexão é `kind="error"`
— nenhum dos três entra.

### reduce: não é açúcar sintático

Por padrão, o que é repassado adiante é a fala literal do modelo. Em alguns passos, essa fala literal **não deveria** ser repassada como está:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

Na prática, o passo de clarify **cola o código inteiro** além das quatro seções. O que segue para jusante precisa ser as quatro seções já parseadas,
senão aquele monte de código entra no prompt do passo seguinte. É esse campo que segura o `clarify_step`.

`reduce` **precisa ser uma função síncrona**; `gate` / `when` / `on_reject` podem ser async.

### Como o estado flui pelo ctx

`ctx` é um `dict[str, Any]` — é o próprio `Workflow.context`. Ao fim de cada passo, a escrita segue esta tabela:

| Situação | `ctx[nome do passo]` | Outros |
|---|---|---|
| `when(ctx)` retorna False | **não escreve**, o passo inteiro é pulado | não produz result, nem entra em `_results` |
| Passou | `reduce(result, ctx)`, ou `result.text` se não houver reduce | |
| Falhou + `on_fail="stop"` (padrão) | **não escreve** | escreve `ctx["_failed_at"]`, o workflow inteiro para neste passo |
| Falhou + `on_fail="skip"` | **não escreve** | continua adiante |
| Falhou + `on_fail="continue"` | `result.text` (incompleto, **sem passar por `reduce`**) | continua adiante |

Passando ou não, `ctx["_results"][nome do passo]` é sempre escrito; se `result.session_id` não for vazio, ele também vai para
`ctx["_sessions"]` e é registrado na linhagem.

**Para saber se esta run do workflow deu certo, olhe `ctx.get("_failed_at")`**, não se o último passo produziu saída.

As chaves iniciadas com underscore são todas colocadas pelo próprio `Workflow.run`: `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — não use nenhuma delas como nome de passo. Cada mecanismo também coloca as suas
(`_brief` / `_goal` / `_verdict` etc.); a lista completa está na [API Python](../reference/api.md).

Dentre elas, `_runtime` e `_on_event` existem para o `gate`: um gate pode despachar seu próprio agent para emitir um verdict,
e esse processo continua sendo exibido na UI — caso contrário aqueles dez e poucos segundos ficariam com a tela preta, parecendo travamento.
O [goal guard](goal.md) é implementado exatamente assim.

`ctx` é o mesmo dict: **se você rodar o mesmo objeto `Workflow` uma segunda vez, as chaves da vez anterior ainda estão lá**.
Para começar limpo, crie um novo, ou passe `context={}` explicitamente.

!!! warning "com on_fail=skip, `ctx[nome do passo]` não é escrito"
    Um passo a jusante que faça `lambda ctx: ctx["某步"]` vai levar `KeyError` direto. Para seguir adiante carregando o resultado incompleto, use
    `on_fail="continue"`; se você realmente quer pular, o passo a jusante precisa se defender com `ctx.get(...)`.

### Verdict e devolução: gate, on_reject, StepAbort

`gate(result, ctx) -> bool` julga "rodou até o fim, mas está aceitável?". Dois detalhes que você precisa saber:

- **quando `result.ok` é falso o `gate` simplesmente não é chamado** (curto-circuito);
- **é chamado uma única vez por tentativa**, e a conclusão fica guardada para depois — porque ele pode ter efeitos colaterais. O gate de `clarify_step` faz spill do
  [brief](../reference/glossary.md#需求确认书) em disco; disparar de novo escreve o arquivo de novo.

O que acontece depois que o gate reprova depende de você ter passado ou não `on_reject`:

| | Como roda a próxima rodada | Nome no manifest |
|---|---|---|
| Só `retries` | roda do zero, prompt original, `resume_from` original | `X#retry1` |
| Com `on_reject` | **continua a sessão que acabou de ser reprovada**, o prompt vira o retorno de `on_reject`, `fork` forçado a False | `X#round2` |

A segunda opção é "devolver, dizendo o que faltou, e deixar que complete" — o trabalho já feito e o contexto continuam lá.
Se `on_reject` retornar string vazia, ou se aquela tentativa nem chegou a obter um `session_id`, o comportamento degrada para rodar do zero.

O `gate` também pode lançar `StepAbort`, o que significa **tentar de novo não adianta, não gaste os turnos restantes**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Depois do lançamento: o motivo é registrado em `ctx["_aborted"]`, o passo é tratado como falha e segue o `on_fail` (padrão `"stop"`),
o **loop de retry quebra na hora**, e nenhum dos `retries` restantes é consumido.

Guarde a diferença: **retornar False é "desta vez não deu, mais uma rodada"; `StepAbort` é "outra rodada não resolve".**
O caso típico é quando o objetivo foi julgado impossível neste ambiente e não há a quem perguntar — continuar girando em falso é a opção mais cara.

### Não confunda as duas camadas de retry

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Cuida do quê | falha de negócio: `gate` reprovou, `result.ok` falso | infraestrutura: oscilação de rede, queda, 5xx |
| Como repete | **repete o passo inteiro**, mesmo prompt e mesmo `resume_from` | **resume a partir do ponto de interrupção**, o custo já gasto não se perde |
| O que faz antes | nada | sondas DNS + TCP esperando a rede voltar (sem HTTP, sem credenciais; a sonda precisa ser gratuita) |
| O que não é retriável | — | credencial errada ou parâmetro errado param imediatamente, sem espera |

O prompt usado na continuação **propositalmente não contém nenhum detalhe do erro** — o modelo precisa saber "você foi interrompido, continue",
não precisa saber se foi ENOTFOUND ou 503.

### Encadear os passos

Há três formas de passar estado entre passos, e a escolha define o que o próximo passo enxerga:

| Forma | O que o próximo passo enxerga | Onde usar |
|---|---|---|
| `resume_from=None` (padrão) + injeção no prompt | só o texto que você injetou | passos independentes. Barato, evita contaminação |
| `resume_from="nome do passo anterior"` | o histórico completo da sessão | quando é preciso memória contínua |
| `resume_from="nome do passo anterior"` + `fork=True` | histórico completo, mas em outro ramo | revisão / propostas paralelas / retry sem sujar a linha original |

O passo apontado por `resume_from` **precisa ter realmente produzido uma sessão**. Se ele foi pulado por `when`, ou nem rodou,
`Workflow.run` lança `ValueError` direto — sem degradar silenciosamente para uma sessão nova, porque isso faria a premissa de "memória contínua"
falhar sem alarde.

Algumas lições de projeto que já custaram caro mais de uma vez:

1. **Um objetivo aceitável por passo.** A fronteira do passo é a fronteira do contexto: onde há `resume_from=None`,
   todos aqueles resultados de ferramenta anteriores deixam de ocupar espaço permanentemente. Veja [Economia de contexto](context.md).
2. **Na dúvida, comece com `clarify_step`.** Em long-horizon, "entendi o objetivo errado" é o erro mais caro,
   e é justamente o tipo que aquelas camadas de economia de contexto não conseguem limpar. Veja [Clarify](clarify.md).
3. **A tarefa despachada precisa ser autossuficiente.** O subagent tem contexto limpo; ele não sabe o que o [coordinator](../reference/glossary.md#协调者)
   sabe. Escreva o contexto necessário na task brief, ou diga a ele qual artifact ler.
4. **Saída longa vai para o disco, não de volta pela conversa.** Isso já está escrito em `WORKER_RULES`; não deixe suas `instructions`
   cancelarem essa regra ("cole o log completo de volta para eu ver").
5. **`gate` primeiro barra condições duras.** Se o arquivo existe, se o exit code é 0 — o que uma linha de Python decide não deve ser despachado a um modelo.
   Se você precisa mesmo do modelo para julgar, use o `with_goal` pronto — ele troca o gate por uma implementação que roda um
   [judge](../reference/glossary.md#判定者) independente; não improvise isso à mão dentro do gate.
6. **Trabalho paralelo no mesmo repositório usa `worker(isolate=True)`.** O fechamento (merge, limpar worktree, abrir PR) hoje fica
   por conta do seu workflow; o harness só garante que as alterações caiam cada uma na sua worktree.

### O workbench precisa estar pendurado no Workflow

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

Pendurar o `channel` no workflow tem duas razões: `run()` liga o `on_event` dele à mesma saída de eventos
(apenas se `channel.on_event` ainda for `None`), e o driver também depende desse campo para saber a quem responder.

!!! warning "Montar o caminho do workbench na mão falha silenciosamente"
    A posição padrão de `Runtime(workbench=True)` é `<run_dir>/workbench`, enquanto a de `Workbench(ws)` é
    `<ws>/.flower` — **não são o mesmo diretório**. Quando o workflow é invocado pela CLI, ele não enxerga `run_dir`; montar o caminho na mão
    só aponta para outro lugar, e então o brief é escrito no diretório A enquanto o índice injetado varre o diretório B, **e nada acusa erro**.
    Criar um único objeto e compartilhá-lo dos dois lados elimina o problema; quando `Workflow.workbench` existe, o `-W` da linha de comando é ignorado
    e prevalece o do workflow.

### `continuous=True`: rodar de novo no mesmo caminho

As três formas acima falam de passo a passo **dentro de uma run**. Entre processos, o eixo é outro:

```python
Workflow([...], continuous=True)     # valor padrão
```

Rodando de novo no mesmo workspace, cada passo continua falando na mesma sessão da vez anterior — via o mapeamento
«nome do passo → session_id» em `<run_dir>/lineage.json`. No carregamento, cada registro passa por `runtime.has_session()` para verificar se a sessão ainda está no banco,
e só é usada se estiver viva: o arquivo de linhagem pode sobreviver ao `sessions.db`, e dar resume em uma sessão inexistente só explode depois que o subprocesso sobe.

Três consequências:

- **`resume_from=None` não significa "sessão totalmente nova".** Na primeira run sim; na segunda, não. Para que seja sempre sessão nova,
  escreva explicitamente `Workflow(..., continuous=False)`.
- **Na [continuidade](../reference/glossary.md#接续), o contexto cresce sem parar.** Se quiser dizer outra coisa na continuação, use
  `Step.resume_prompt` — o que já está no contexto do outro lado não deve ser reenviado.
- Passos com `resume_from` explícito não são afetados; ele tem prioridade.

!!! warning "O nome do passo é a chave entre processos"
    Renomear um passo equivale a cortar a linhagem daquele passo: na próxima run não há continuidade, **e nada acusa erro**. Nomes de retry com sufixo `#retry1` /
    `#round2` **não entram na linhagem** (o que se registra é sempre o nome original), e essa é uma das formas de implementar "o judge é sempre uma sessão nova".

O projeto completo e o `--new` estão em [Continuidade](continuity.md).

## Quando não usar

- **Um único agent e nenhum verdict necessário** — não envolva em `Workflow`. Chame `await rt.run(spec, "…")` direto,
  ou use a linha de comando `flower once "读一眼这个仓库"`.
- **O formato é exatamente "esclarecer requisito → definir objetivo → executar"** — use o
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) pronto,
  sem escrever nada:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    São **três passos**: `确认需求` → `设定目标` → `干活` (com loop de verdict; o passo de verdict se chama `干活·判定#N`).
    Com `goal=False` não há o segundo passo nem o loop de verdict; com `clarify_only=True` só resta o primeiro passo.
    Ele já traz seu próprio `HumanChannel` e `Workbench`, pendurados no workflow, então
    `Runtime(workbench=wf.workbench)` é usar direto — não monte outro.

    Sem escrever código também funciona: entrar no diretório do projeto e rodar `flower "帮我做一个 X"` executa exatamente isso.
    **Ele não é "o projeto de workflow recomendado"**, é só o que permite rodar com zero configuração.

- **Passos cortados mais finos que "um objetivo aceitável"** — prejuízo líquido. Cada passo abre uma sessão nova,
  e uma sessão nova tem piso de partida (no coordinator, medido em cerca de 34k de contexto), que não dilui.
- **Querer voltar a uma mensagem específica depois do fato** — por `Workflow` não dá, ele nunca passa `resume_at`.
  Chame direto `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`.

Como escolher o papel (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) e a semântica campo a campo de `Step` e `Workflow`
estão na [API Python](../reference/api.md); os termos, no [Glossário](../reference/glossary.md).
