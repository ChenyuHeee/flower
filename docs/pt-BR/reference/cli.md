# Referência de linha de comando

Depois de instalado, o `flower` é um único executável, 4 subcomandos, 23 flags. Esta página lista
todas elas: tipo, valor padrão e semântica exata de cada flag, mais como interromper no meio da
execução, o que ele pergunta na primeira vez, quais são os códigos de saída e quais arquivos ele
deixa nos seus diretórios. Depois de ler esta página você não precisa abrir o código-fonte.

Código-fonte: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcomando | O que faz | Argumento posicional | Flags próprias |
|---|---|---|---|
| `go` | Tudo de uma vez: clarificar a demanda → definir o objetivo → despachar o trabalho → veredito a cada rodada. É o padrão quando você não escreve subcomando | `ask` (opcional) | 11 |
| `run` | Executa um [workflow](glossary.md#流程) escrito por você | `target` (obrigatório) | 0 |
| `once` | Executa um único agent uma vez, sem workflow e sem veredito | `prompt` (obrigatório) | 6 |
| `setup` | Configura credenciais, grava em `~/.config/flower/.env` | nenhum | 0 |

Total de 23 flags = 5 globais + 11 próprias do `go` + 6 próprias do `once` + `-h/--help`. `run` e
`setup` não têm flags próprias.

---

## Formas de invocação {#调用形式}

Todo o argv do `flower` passa primeiro por `_with_default_cmd()`, que completa o subcomando padrão,
e só então vai para o argparse (`cli.py:1253-1255`). É por isso que `flower "帮我做一个 X"` funciona
— ele é reescrito para `flower go "帮我做一个 X"`.

Regras para completar o subcomando padrão (`cli.py:761-797`):

1. O conjunto de flags globais é **derivado do próprio parser principal**, não é uma lista
   hardcoded. Flags com `nargs == 0` contam como flags puras; as demais contam como flags com valor.
2. Varre da esquerda para a direita, pulando as flags globais. As que levam valor são puladas junto
   com o valor, e a forma com `=`, tipo `--workspace=/tmp`, também é reconhecida.
3. Para no primeiro token que não é uma flag global. Se ele for `go`, `run` ou `once`, é entregue ao
   argparse como está; **caso contrário, insere um `go` antes dele**, e ele vira o corpo da demanda
   do `go`.
4. Se a varredura terminar sem encontrar nenhum argumento posicional (argv vazio, ou só flags
   globais) → acrescenta `go` no fim e entra na entrada interativa.
5. Exceção: se o argv contiver `-h` ou `--help`, é devolvido como está, para o argparse imprimir a
   ajuda.

A constante usada nessa decisão é `_CMDS = ("go", "run", "once")` (`cli.py:758`) — **`setup` não
está nela**, com as consequências descritas em [`setup`](#setup).

### O resultado real da reescrita {#实际的改写结果}

| O que você digita | Como é de fato parseado | Efeito |
|---|---|---|
| `flower` | `["go"]` | Pergunta interativamente "要做什么?" |
| `flower -v` | `["-v", "go"]` | Idem, com verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Começa a executar direto |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Flags globais podem vir antes |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | A forma com `=` também é reconhecida |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Flags do subcomando podem vir depois da demanda |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Também podem vir antes |
| `flower --new` | `["go", "--new"]` | Só flag, sem demanda → entrada interativa |
| `flower once "hi"` | `["once", "hi"]` | Inalterado |
| `flower run flows:main` | `["run", "flows:main"]` | Inalterado |
| `flower run` | `["run"]` | argparse reclama do `target` faltando; **não** trata como demanda |
| `flower go run` | `["go", "run"]` | Desambiguação explícita: o corpo da demanda é `run` |
| `flower setup` | `["go", "setup"]` | Executa `go`, com a demanda sendo a string `setup`, ver [`setup`](#setup) |
| `flower --help` | Inalterado | argparse imprime a ajuda |

As palavras `run` e `once` **não podem** ser usadas diretamente como corpo da demanda; essa
ambiguidade é intencional (`cli.py:770-771`). Para usá-las como demanda, escreva `flower go run`.

### As seis formas que funcionam {#六种能用的写法}

```bash
flower                                    # 1. Puro: pergunta “要做什么?” ou “接着上次?”
flower "帮我做一个 X"                       # 2. Demanda como argumento posicional
echo "帮我做一个 X" | flower --timeout 0    # 3. Alimentando o stdin por pipe
flower once "读一眼这个仓库"                 # 4. Agent único
flower run flows.py:main                  # 5. Executa um workflow próprio
flower go setup                           # 6. go explícito, com setup como corpo da demanda
```

A forma de módulo `python -m flower.cli` é equivalente a `flower` (`cli.py:1263-1264`).
O wrapper de contêiner `docker/flowerbox` aceita exatamente os mesmos argumentos que o `flower`.

### Alimentando o stdin por pipe {#管道喂-stdin}

`ask_for_prompt()` **não imprime o cabeçalho do prompt** quando `sys.stdin.isatty()` é falso; lê uma
linha direto com `input("> ")` (`cli.py:814-822`). Por isso `echo "..." | flower` funciona.

Mas logo em seguida ele imprime um aviso, e a thread de stdin recebe EOF imediatamente e sai:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Rodar por pipe pede `--timeout 0`: as perguntas deixam de fingir esperar 30 minutos, falham na hora,
e o agent decide sozinho e escreve as suposições na seção "未知与假设" do brief.

---

## Subcomandos {#子命令}

### `go` {#go}

Texto de ajuda: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Argumento posicional `ask`, com `nargs="?"` — sem ele, entra na entrada interativa. É a porta de
entrada mais usada; `flower "做 X"` passa por aqui.

O que ele faz (`cli.py:1011-1042`):

1. `ensure_credentials()` — verifica as credenciais e realmente dispara uma sonda de API; ver
   [O fluxo de configuração da primeira execução](#首次运行的配置流程).
2. Sondagem de [despertar](glossary.md#唤醒): apenas olha, em modo leitura, se este diretório já foi
   usado, sem escrever um único byte.
3. Se `ask` não foi dado, imprime o prompt e pergunta; digitar `/new` equivale a `--new`, e então ele
   **pergunta de novo** a demanda.
4. Se for [continuidade](glossary.md#接续), imprime uma linha de banner de despertar.
5. Monta o [workflow](glossary.md#流程) de três passos: `确认需求` → `设定目标` → `干活`, com um
   `干活·判定#N` depois de cada rodada de trabalho. `--clarify-only` mantém só o primeiro passo.
6. Executa.

O banner de despertar é assim (o home no caminho é substituído por `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` aparece sempre; `目标 N 条` só aparece quando existe checklist de veredito;
`干活上下文 X` exige que o contexto da última rodada daquela [session](glossary.md#会话) seja
encontrado em `sessions.db` — se não for, não é exibido.

!!! warning "`-W` e `-T` são silenciosamente sobrescritas no caminho do `go`"
    Essas duas flags globais não têm efeito no `go`; não dá erro nem aviso:

    - `-W/--workbench`: o workflow montado pelo `go` sempre traz seu próprio
      [workbench](glossary.md#工作台), e o código usa
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — o do workflow sempre tem
      prioridade. Então o workbench é sempre `<workspace>/.flower/`
      (com `--isolate`, `<workspace>.parent/.flower-<nome>/`), e `-W` não muda isso.
    - `-T/--trim`: o `go` chama `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`), usando
      diretamente a negação de `--no-trim` e **sem nem olhar para `args.trim`**. Ou seja, no caminho
      do `go` o [trim](glossary.md#裁剪) já vem ligado por padrão, e a única forma de desligá-lo é
      `--no-trim`.

    Essas duas flags só valem no `run` (quando o workflow não traz workbench próprio) e no `once`.

#### As 11 flags do `go` {#go-的-11-个开关}

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `--asks N` | int | `-1` | Cota de perguntas. `-1` ou qualquer negativo = **ilimitado**; `0` = proibido perguntar, a primeira pergunta já vira `over_budget`; `N` = cota rígida. Estourada a cota, a ferramenta recusa direto, sem bloquear a execução |
| `--rounds N` | int | `3` | Teto do número **total** de rodadas de trabalho, não de rodadas extras. No fim de cada rodada, um [juiz](glossary.md#判定者) independente decide se "está pronto"; se não estiver, devolve e continua na mesma session |
| `--no-goal` | flag | `False` | Desliga o [guarda de objetivo](glossary.md#目标看守): não gera `目标.md`, não faz [veredito](glossary.md#判定); terminado o trabalho, acabou |
| `--judge-can-run` | flag | `False` | Permite que o juiz execute comandos. O veredito fica mais duro, ao custo de ele também poder alterar o workspace |
| `--timeout segundos` | float | `1800.0` | Quanto tempo esperar por uma resposta humana. `0` ou negativo = totalmente automático, todas as perguntas falham **imediatamente**, sem fingir espera. Semântica em [Timeout](#超时) |
| `--isolate` | flag | `False` | Dá a cada [subagent](glossary.md#subagent) um git worktree próprio, ou seja, [isolamento](glossary.md#隔离). **Exige que o workspace seja um repositório git**, caso contrário sai com código 1. Também move o workbench para fora do repositório |
| `--window N` | int | nenhum (inferido do nome do modelo) | Janela de contexto do modelo. Sem valor: nome do modelo contendo `1m` ou não contendo `haiku` → 1,000,000; contendo `haiku` → 200,000. Ao chegar em `janela − 50000`, escreve o [documento de handoff](glossary.md#交接书) e faz o [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Desliga o handoff, voltando ao [compact](glossary.md#压缩) nativo do SDK |
| `--new` | flag | `False` | Não continuar de onde parou. **Move** (não apaga) o `lineage.json` + `需求.md` + `目标.md` do trecho anterior para `notes/archive/<YYYYmmdd-HHMMSS>/` e recomeça do zero |
| `--clarify-only` | flag | `False` | Só faz a [clarificação prévia](../guide/clarify.md), sem seguir para o trabalho — o workflow fica só com o passo `确认需求` |
| `--no-trim` | flag | `False` | Desliga o trim. No caminho do `go` o trim vem **ligado** por padrão; esta é a única forma de desligar |

Casos de borda nos valores, todos sem erro e sem aviso:

- `--rounds 0` e `--rounds 1` são equivalentes — internamente é `retries = max(0, rounds - 1)`, ambos
  rodam 1 rodada.
- Qualquer valor negativo em `--asks` significa ilimitado, não só `-1`.
- Qualquer valor negativo em `--timeout` equivale a `0`, ou seja, totalmente automático.
- `--window 0` é **silenciosamente ignorado** (`0` é falsy, nem chega a ser repassado), voltando ao
  padrão inferido do nome do modelo. Valores negativos são repassados e depois limitados a `10000`.
- `--clarify-only` é **no-op** em um diretório já clarificado — o passo `确认需求` vê um `需求.md`
  completo e pula, e como o workflow só tem esse passo, nada acontece (exceto a contagem de
  despertares +1). Para clarificar de novo, combine com `--new`.
- O `--help` do `go` termina dizendo "全局开关(-v/-w/-r/-T)见 `flower --help`"; essa linha
  **esqueceu o `-W`**.

### `run` {#run}

Texto de ajuda: `运行一个 workflow` (`cli.py:1130-1133`).

Argumento posicional `target`, na forma `módulo:atributo`. As duas formas são suportadas
(`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # import pelo nome do módulo
flower run flows.py:build        # caminho de arquivo; enfia o diretório pai no sys.path e importa pelo nome do arquivo
```

Se o atributo obtido for chamável, ele é chamado uma vez e o retorno vira o
[workflow](glossary.md#流程); se já for um objeto de workflow, é usado direto.

**`run` não tem nenhuma flag própria**, apenas as 5 flags globais. Ou seja, `--window`,
`--no-handoff` e companhia ficam sempre no valor padrão nesse caminho (o código usa `getattr` como
fallback, `cli.py:862-864`). Para ajustá-las, escreva os parâmetros dentro do seu próprio workflow.

### `once` {#once}

Texto de ajuda: `跑一次单 agent` (`cli.py:1135-1145`). O argumento posicional `prompt` é obrigatório.

Ele constrói um `AgentSpec(name="ad-hoc", …)` e executa direto, **sem passar pelo `_drive`**. Por
isso o `once` não tem:

- Ctrl-C para interromper e falar (apertar gera um `KeyboardInterrupt` comum)
- Thread de resposta via stdin, prompt de entrada fixo no rodapé
- Consulta ao oráculo
- Resgate da contabilidade em SIGHUP / SIGTERM
- A linha final `总花费 … · 清单 …`
- A reconfiguração guiada automática depois de falha de credenciais

O nome desse passo no [manifesto de execução](glossary.md#运行清单) é fixo: `ad-hoc`.

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-i`, `--instructions` | str | vazio | Instruções de domínio, [acrescentadas](glossary.md#叠加) **depois** do system prompt nativo do Claude Code, sem substituí-lo |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Lista branca de ferramentas separada por vírgula. Sem valor, são essas três ferramentas somente-leitura |
| `-p`, `--permission-mode` | str | `default` | Só aceita `default`, `acceptEdits`, `plan` ou `bypassPermissions`; qualquer outro valor faz o argparse sair com código 2 |
| `-b`, `--budget` | float | sem teto | Teto de [orçamento](glossary.md#预算) em dólares; ao estourar, para |
| `--resume SESSION_ID` | str | nenhum | Continua uma session existente |
| `--fork` | flag | `False` | Bifurca em vez de continuar; usado junto com `--resume` |

!!! warning "O tempo e o custo acumulado exibidos pelo `once` são sempre 0"
    O `once` cria uma nova instância do renderizador a cada evento recebido (`cli.py:579-581`,
    `cli.py:1060`), mas o marco inicial do cronômetro e o custo acumulado ficam guardados na
    instância (`cli.py:393-394`). Resultado:

    - O `用时` da linha final é sempre `0:00`
    - O `累计 $0.00` da linha de status é sempre 0, e o `上下文` também nunca acumula

    O custo real do passo tem que ser consultado no campo `cost_usd` de `runs/manifest.json`. Os
    caminhos `go` e `run` mantêm a mesma instância do renderizador e não têm esse problema.

### `setup` {#setup}

Texto de ajuda: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`).
Não tem nenhuma flag.

O que ele faz: lê o `.env` → decide se já foi configurado → inicia o fluxo interativo de
configuração, com `reason` sendo `重新配置。` ou `还没配过凭证。`. O que aparece na tela está em
[O fluxo de configuração da primeira execução](#首次运行的配置流程).

!!! warning "Hoje é impossível chegar no subcomando `flower setup`"
    A constante de decisão do subcomando padrão, `_CMDS = ("go", "run", "once")` (`cli.py:758`),
    **esqueceu `"setup"`**, embora o `setup` esteja de fato registrado no parser (`cli.py:1147`).
    Assim, `flower setup` é reescrito para `flower go setup` — **o que roda é o fluxo completo do
    `go`, com a string `setup` como corpo da demanda**: primeiro valida credenciais, depois pergunta
    a demanda, e então começa mesmo a despachar trabalho. Com flags globais é igual:
    `flower -v setup` → `["-v", "go", "setup"]`.

    **Não existe nenhum argv capaz de alcançar o subcomando `setup`.**

    Para configurar credenciais, hoje só há dois caminhos, e ambos levam à mesma interface
    interativa:

    - Rodar `flower "随便一句诉求"` direto; sem credenciais configuradas, ele pergunta antes;
    - Ou escrever `~/.config/flower/.env` à mão; os nomes das chaves estão em
      [As chaves gravadas](#写出来的键).

    Alguns textos também ficam contaminados por isso: o ``跑 `flower setup` 重配。`` impresso quando
    a credencial é rejeitada e o comentário da primeira linha do `.env`, ``由 `flower setup` 写``,
    apontam ambos para esse comando inalcançável.

---

## Flags globais {#全局开关}

As 5 flags globais estão registradas simultaneamente no parser principal e em cada subcomando
(`cli.py:1071-1087`). A cópia dos subcomandos usa `argparse.SUPPRESS`: se não for passada, nenhum
atributo é escrito, então **tanto faz escrevê-las antes ou depois do subcomando**, elas não se
sobrescrevem. O efeito colateral é que elas não aparecem no `--help` do subcomando — para vê-las,
rode `flower --help`.

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Diretório de trabalho do agent. Passa por `resolve()` virando caminho absoluto, e por `mkdir -p`. O [workbench](glossary.md#工作台) `.flower/` é criado aqui dentro |
| `-r`, `--run-dir` | str | `runs` | Diretório do [session store](glossary.md#会话存储) e do manifesto de execução. **Relativo ao CWD atual, não ao workspace** |
| `-v`, `--verbose` | flag | `False` | Imprime mais coisas, ver abaixo |
| `-W`, `--workbench` | flag | `False` | Ativa o workbench. **Sem efeito no `go`**; só vale para `run` (quando o workflow não traz workbench próprio) e `once`, caso em que o workbench fica em `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | No resume, troca resultados grandes de ferramentas antigas por ponteiros de arquivo, ou seja, [trim](glossary.md#裁剪). **Sem efeito no `go`**, onde o controle é invertido via `--no-trim` |
| `-h`, `--help` | flag | — | Existe em todo parser. Quando aparece no argv, a reescrita do subcomando padrão é pulada e a ajuda é impressa direto |

O fato de `-r/--run-dir` ser relativo ao CWD morde: `flower -w /other/proj "做 X"` cria `runs/` **no
diretório onde você digitou o comando**, enquanto `.flower/` fica em `/other/proj/` — os dois
estados se separam. Para mantê-los juntos, passe explicitamente `-r /other/proj/runs`.

O help de `-v` diz "显示思考与工具结果", mas o pensamento da
[thread principal](glossary.md#主线程) **já é exibido por padrão**. O que `-v` realmente liga a mais
é:

- O corpo do texto dos subagents (por padrão não é exibido, só suas chamadas de ferramenta)
- Os resultados normais de ferramentas (por padrão só os que deram erro)
- O evento `prompt`
- Uma impressão da configuração de credenciais em vigor antes de começar, com o token mascarado
  deixando só os 4 primeiros caracteres

Esse último item usa `print()` puro, **sem passar pela sanitização de saída, sem quebra de linha e
sem a proteção do lock de escrita do terminal**; ao rodar vários `flower` em paralelo, essas linhas
podem sair rasgadas.

---

## Como falar com ele durante a execução {#运行中怎么和它说话}

Depois que a execução começa, o terminal **está o tempo todo lendo o que você digita**. Não é preciso
esperar ele perguntar, nem apertar nenhuma tecla para entrar em modo de entrada — a última linha é
sempre a linha onde se digita.

### O prompt de entrada fixo no rodapé {#常驻在最下面的输入提示符}

Há uma thread daemon `flower-stdin` lendo o stdin o tempo todo (`cli.py:655-755`), usando `select`
com polling a cada 0.2 segundo em vez de leitura bloqueante (assim o sinal de parada consegue
acordá-la; em fluxos que não suportam `select`, como no Windows, degrada para leitura bloqueante).

**Ele lê o tempo todo, não só quando há pergunta.** A razão: se lesse apenas durante as perguntas,
tudo o que você digitasse durante as horas de trabalho ficaria no buffer do terminal e seria engolido
como resposta na próxima pergunta — a pergunta seria respondida antes mesmo de você vê-la.

Na exibição, `_say()` é a única saída: antes de cada impressão ele apaga o prompt e o redesenha
depois (`cli.py:299-305`), então o prompt nunca é empurrado para cima pela saída de eventos. O prompt
tem dois textos, alternando conforme haja ou não pergunta pendente:

| Estado | Última linha da tela |
|---|---|
| Com pergunta pendente | `你的回答 (回车=跳过,让它自己判断) > ` |
| Sem pergunta pendente | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Para onde vai o que você digita {#你敲的东西去哪了}

| O que você digita | Com pergunta pendente | Sem pergunta pendente |
|---|---|---|
| **Linha vazia (Enter direto)** | Pula a pergunta, deixa ele decidir sozinho | Não faz nada |
| **Começando com `?`** | Consulta ao oráculo, ver abaixo | Idem |
| **Só dígitos**, dentro da faixa de opções | Substitui pela opção correspondente e responde | Tratado como texto comum |
| Qualquer outro texto | Vai como resposta ao agent que perguntou | Vai para a caixa de entrada, como demanda adicional |
| EOF (Ctrl-D ou pipe fechado) | Recusa a pergunta, remove o prompt, thread sai | Remove o prompt, thread sai |

Ao cair na caixa de entrada, ele imprime um recibo:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Quando não há [brief](glossary.md#需求确认书) para gravar em disco, a segunda metade vira
`没有确认书可落盘 —— 它可能活不过下一个步骤`. A caixa de entrada **não interrompe** o executor que
está trabalhando; ele só pega o conteúdo na próxima vez que consultar a caixa por conta própria. A
mesma frase também é acrescentada em `notes/需求.md` — sem gravar em disco ela não sobrevive à
fronteira de passo, já que o próximo passo é uma session nova que só lê os arquivos congelados.

### Linha iniciada por `?` = consulta ao oráculo {#旁路问答}

Uma linha começando com `?` não vai para o agent em execução; vai para o
[oráculo](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Ele sobe um Runtime **independente**, com `run_dir` em `<run_dir>/aside/`, de modo que seu custo e
sua linhagem de sessions não se misturam ao `manifest.json` principal. O papel é somente-leitura, com
apenas as ferramentas `Read`, `Glob`, `Grep`, no máximo 12 turnos e teto de custo de **$0.5**. O
contexto que ele enxerga são os **60** eventos mais recentes (eventos `thinking` e `prompt` não
entram nessa janela), cada um truncado em 200 caracteres, mais a descrição do caminho do workbench.

Ele roda **concorrentemente**; a execução em andamento não espera um segundo sequer. A resposta é
assim:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Em caso de falha, imprime uma linha em vermelho `# 旁路问答失败:<类型>: <消息>`, **sem afetar o
fluxo principal**. Na saída, espera no máximo **120 segundos** pelo encerramento das consultas ao
oráculo, imprimindo antes uma linha `(等 N 条旁路问答收尾…)`.

O que ele diz não entra no contexto daquela execução — perguntar não afeta a execução, e a resposta é
descartada assim que sai.

!!! warning "O `？` de largura total não dispara a consulta ao oráculo — quem usa IME chinês vai tropeçar"
    A linha de código que decide isso é (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Os dois caracteres **são ambos o `?` ASCII de meia largura** (`0x3f`) — verificado byte a byte.
    Pela forma como está escrito, a intenção óbvia era aceitar tanto o `?` de meia largura quanto o
    `？` de largura total (U+FF1F) produzido pelos IMEs chineses, mas na prática ficou o mesmo
    caractere duas vezes.

    Consequência: **uma linha começando com o `？` de largura total não é tratada como consulta ao
    oráculo**, e sim silenciosamente enviada à caixa de entrada como "demanda adicional", sendo em
    seguida acrescentada a `notes/需求.md`. O recibo que você vê é `+ 收到`, não `# 旁路`.

    Para consultar o oráculo, **é obrigatório usar o `?` de meia largura** — mude o IME para inglês
    antes de digitar, ou digite ao menos o primeiro caractere em meia largura.

### O que aparece na tela {#屏幕上都是什么}

Os ícones são **todos ASCII**, não emoji (`cli.py:49-67`). O motivo está no comentário do código:
emoji, junto com caracteres de moldura, formas geométricas e setas, dispara fallback de glifos no
terminal, o que já causou dois travamentos de terminal.

| Ícone | Significado | Ícone | Significado |
|---|---|---|---|
| `=` | Separador de passo | `+` | Concluído / respondido / recebido |
| `~` | Pensamento, retentativa | `x` | Falha / erro |
| `>` | Despacho | `#` | Handoff, oráculo, tarefa |
| `*` | Chamada de ferramenta | `-` | Linha de status, item de lista |
| `?` | Pergunta | `<-` | Continuação, ponto de queda do handoff |
| `!` | Aviso / interrupção | `.` | Pulado |
| `\| ` | Barra vertical de indentação do subagent | | |

!!! warning "Os `❓` e `↩` da documentação antiga não existem no terminal real"
    A documentação antiga usava `❓` para pergunta e `↩` para a linha de despertar. **Nunca foram
    esses caracteres no código** — o ícone de pergunta é o `?` de meia largura, e o ícone de
    despertar e de ponto de queda do handoff são os dois caracteres ASCII `<-`.

    Então o que o terminal real imprime é:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Não `❓ 这个工具……`, nem `↩ 在 ~/proj 接上上次`. Fazer grep nos logs seguindo a documentação
    antiga não encontra nada.

Os cinco estados de uma pergunta, na tela:

| Estado | Saída na tela |
|---|---|
| Perguntada | `  ? <问题>`, seguido das opções, uma por linha: `     1) 选项一`; havendo cota, mais `     (还能问 N 次)` |
| Respondida | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Cota esgotada | `  ! 提问额度用完` |
| Você pulou | `  . 已跳过` |

Quando `--asks` está ilimitado (o padrão), a última linha "还能问 N 次" não é exibida.

Quando o [handoff](glossary.md#换代) termina de escrever o documento de handoff, sai um bloco
inteiro:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Quando o documento de handoff cai para a versão degradada, é inserida uma linha em vermelho a mais:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

A saída ainda faz duas coisas que você não vê: todas as linhas passam por uma sanitização que
**só deixa passar os códigos SGR de cor do próprio flower**, engolindo inteiras as sequências de
limpar tela e mover cursor cuspidas por modelos ou ferramentas; e a largura é
`max(40, min(colunas do terminal, 110))`, de modo que em terminais largos a saída não preenche a
linha toda — isso é intencional.

### O prompt de largada {#起跑时的提示符}

Ao rodar `flower` puro (sem demanda), ele pergunta antes. Dois textos:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

O segundo só aparece quando este diretório já foi usado e as quatro seções de `需求.md` estão
completas.

Esse prompt lê via `input()`, **sem passar pelo parsing do shell**. Aspas chinesas, espaços e pontos
de exclamação podem ser digitados direto — essa é toda a razão de ele existir. O zsh, ao encontrar
uma aspa direita chinesa, entra em continuação `dquote>`, o que parece travamento, mas na verdade
nada chegou a ser iniciado.

- Entrada vazia + primeira vez → sai, imprimindo
  ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Entrada vazia + despertar → **válido**, significa "continuar de onde parou"
- Digitar `/new` → equivale a `--new`; depois de arquivar o trecho anterior, **pergunta de novo** a
  demanda
- Ctrl-C / Ctrl-D → sai, imprimindo `已取消`

### Timeout {#超时}

`--timeout` é float, em segundos, padrão `1800.0`. Três faixas de valor:

| Valor | Comportamento |
|---|---|
| `> 0` | Espera esses segundos. Ao estourar, a pergunta é fechada como `timeout` e o agent decide sozinho |
| `0` ou negativo | **Totalmente automático**. A pergunta não entra na fila de espera, não emite evento `asked`, não aparece na tela, e é fechada imediatamente como `timeout` |
| Esperar para sempre | **Impossível pela linha de comando**. Internamente há suporte a "esperar para sempre", mas `--timeout` é float e tem valor padrão, e nenhuma forma de escrita produz isso. O teto é passar um número de segundos muito grande |

`--timeout 0` e `--timeout -1` são completamente equivalentes. Rodar por pipe, em CI ou sem
supervisão usa exatamente isso.

Quando uma pergunta não recebe resposta, o resultado de ferramenta devolvido ao modelo é um texto
fixo, em quatro variantes:

| Resultado | Texto devolvido ao modelo |
|---|---|
| Cota esgotada | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| Você pulou | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Pergunta vazia | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**A semântica do Ctrl-C é completamente diferente em dois lugares.**

**No prompt de largada `> `** — sai do programa direto, imprimindo `已取消`.

**Durante a execução** — interrompe a rodada atual e te dá uma chance de falar:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Dar Enter direto aqui significa apenas interromper sem falar nada e seguir. Se houver perguntas
pendentes no momento, sai uma linha a mais: `  (有 N 个提问还等着,打断不影响它们)`.

**Um segundo Ctrl+C sai de verdade**, e é um `KeyboardInterrupt` não capturado — a tela mostra um
traceback do Python, não é uma saída limpa.

A interrupção é cooperativa: ela corta de forma limpa numa fronteira de mensagem, sem cancelar
tarefas à força. Ela **não conta como tentativa fracassada** e não consome retentativas. Ao
continuar, é anexada uma explicação dizendo ao modelo que "chamadas de ferramenta em voo retornando
interrupted é efeito colateral normal da interrupção, não falha de ambiente".

Esse Ctrl-C customizado só é instalado quando `sys.stdin.isatty()` (`cli.py:918`). Rodando por pipe,
o comportamento padrão do Python é mantido, ou seja, sai já na primeira vez. O caminho do `once` não
passa por aqui, então o Ctrl-C no `once` também sai já na primeira vez.

### SIGHUP / SIGTERM {#sighup-sigterm}

Os caminhos `go` e `run` instalam handlers para `SIGHUP` e `SIGTERM`: primeiro gravam **o passo em
voo** no `manifest.json`, marcando-o como `killed-by-signal`, depois restauram a ação padrão e
efetivamente saem.

A origem disso: quando o terminal trava, o kernel manda SIGHUP, cuja ação padrão encerra o processo
na hora — o `finally` não roda, o manifesto não é escrito, e a contabilidade daquela execução se
perde. Em threads que não são a principal do sistema operacional, ou em plataformas sem suporte, isso
é silenciosamente pulado.

---

## O fluxo de configuração da primeira execução {#首次运行的配置流程}

As três portas de entrada `go`, `run` e `once` chamam `ensure_credentials()` logo no início
(`cli.py:1213-1244`), com **duas barreiras**.

### Primeira barreira: existe credencial? {#第一道-有没有凭证}

Procura credenciais por ordem de prioridade. Se não encontrar `ANTHROPIC_API_KEY` nem
`ANTHROPIC_AUTH_TOKEN`, inicia a configuração interativa; em modo não interativo (stdin não é
terminal) não bloqueia, apenas imprime este texto e sai:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Esse texto tem dois pontos que não batem com a implementação: o `flower setup` da segunda linha hoje
é inalcançável (ver [`setup`](#setup)); e a quarta linha **diz o contrário do código** — o flower de
fato usa o bloco `env` de `~/.claude/settings.json` e `settings.local.json` como **último nível de
fallback**, tomando emprestado apenas 9 chaves de credenciais, sem assumir nenhuma outra
configuração. O lugar que imprime essa linha é `env.py:192` (a função `check_credentials()` está
definida em `env.py:184`), enquanto quem realmente lê aqueles dois arquivos é `env.py:56-75` e
`:109-111`; registrado na [issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**Vale o código: ele lê.** A ordem completa de busca e as 9 chaves estão na
[referência de configuração](config.md#借用).

### O que a configuração interativa pergunta {#交互配置问什么}

```text
== 配置 flower ========================================
<为什么要配这一行>
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   > 

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   > 

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   > 

+ 存好了:/Users/you/.config/flower/.env
```

- A pergunta 1 é **obrigatória**. Deixando vazia, ele imprime em vermelho `没给 token,取消。` e
  abandona a configuração.
- As perguntas 2 e 3 podem ficar vazias.
- Quando o stdin não é terminal, todo o fluxo é pulado, sem bloquear.

### As chaves gravadas {#写出来的键}

| O que você digitou | Chave gravada |
|---|---|
| Token começando com `sk-ant-` | `ANTHROPIC_API_KEY` |
| Qualquer outro token | `ANTHROPIC_AUTH_TOKEN` |
| Endereço de gateway não vazio | `ANTHROPIC_BASE_URL` |
| Nome de modelo não vazio | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` e `ANTHROPIC_DEFAULT_SONNET_MODEL`, as três de uma vez |

O caminho do arquivo é `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, e o diretório pai é criado
automaticamente. A escrita é **sobrescrita integral**, pulando chaves com valor vazio; ao final faz
`chmod 0600` e carrega imediatamente — não é preciso reabrir o shell. A primeira linha é sempre um
comentário lembrando de não commitar isso no versionamento.

### Segunda barreira: a credencial funciona? {#第二道-凭证能不能用}

Com a configuração completa, imprime a linha `- 验一下凭证…` e então **dispara uma chamada de API de
verdade**.

Detalhes da sonda: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, timeout padrão de 20 segundos,
usando o `urllib` da stdlib, sem trazer dependências. O modelo é escolhido na ordem
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. Havendo
`ANTHROPIC_API_KEY`, usa o header `x-api-key`; caso contrário,
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` foi propositalmente definido em 16, e não em 1: na prática, modelos com cadeia de
pensamento forçada não cabem nem o pensamento, e o servidor demora agonizantes 30 segundos para
responder; com 16, são só 3.6 segundos.

O resultado da sonda é tratado em três classes, e **a diferença importa**:

| Conclusão | Condição | O que o flower faz |
|---|---|---|
| `auth` | HTTP 401 / 403, ou nenhuma credencial | Imprime `! 凭证被拒:<响应体前 160 字>`, inicia a reconfiguração interativa e valida de novo ao final. Em modo não interativo, sai com código 1 |
| `config` | HTTP 404, ou 400 com o corpo mencionando `model` | Imprime `! 网关地址或模型名不对:<…>`, idem acima |
| `net` | Sem conexão / timeout / falha de DNS / falha de TLS / 5xx | Imprime `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **não pede reconfiguração, começa a executar direto** |
| `ok` | Menor que 400, ou qualquer caso indeterminado, tudo liberado | Segue em silêncio |

O caso `net` é intencional: uma oscilação de rede não deveria obrigar você a redigitar o token, e o
próprio flower tem mecanismo de suspender e reconectar em queda de rede. Ver "探针没打通" não exige
ação; é só continuar.

A chance de reconfiguração é dada **no máximo uma vez**. Se falhar de novo, sai.

### A reconfiguração automática depois de uma quebra {#跑挂了之后的自动重配}

Quando o workflow falha, o flower casa a mensagem de erro do passo que falhou contra uma expressão
regular (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). Se casar e
o stdin for terminal, imprime na hora `! 看起来是凭证不对:<前 120 字>` e inicia a configuração
interativa; concluída, imprime:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

E então sai com código 1 de qualquer forma. O caminho do `once` não tem essa parte.

---

## Códigos de saída {#退出码}

| Código | Quando |
|---|---|
| `0` | Terminou normalmente |
| `1` | Todas as saídas deliberadas. A mensagem vai para o **stderr**, sem traceback. Lista abaixo |
| `2` | Erro de argumento do argparse: flag desconhecida, argumento posicional faltando, `-p` com valor fora das choices |
| `130` | Dois Ctrl+C seguidos durante a execução. É um `KeyboardInterrupt` não capturado, **com traceback do Python** |
| Morto por sinal | SIGHUP / SIGTERM: grava o passo em voo no manifesto e então segue a ação padrão |

Todas as mensagens de código de saída 1:

| Mensagem | Quando |
|---|---|
| `已取消` | Ctrl-C ou Ctrl-D no prompt de largada |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Diretório novo + Enter direto |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 linhas no total) | Não interativo + sem credencial |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Não interativo + sonda concluiu `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Não interativo + sonda concluiu `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` usado em diretório que não é git |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Demanda vazia e diretório sem despertar |
| `在步骤 '<步骤名>' 中止` | Um passo do workflow falhou e a política é parar |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, faltou os dois-pontos |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Falha ao importar o módulo alvo |
| `'<模块>' 里没有 '<属性>'` | O atributo não existe no módulo |

Ao terminar (caminhos `go` / `run`), a última linha impressa é:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

Esse valor conta apenas o custo **deste processo**, sem incluir execuções anteriores — embora o
próprio arquivo de manifesto acumule entre processos.

---

## O que ele cria no seu projeto {#它在项目里创建了什么}

Duas árvores: `<run_dir>/` (padrão `./runs/`, relativo ao CWD) guarda a contabilidade e as sessions;
`<workspace>/.flower/` guarda o [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Caminho | O que guarda |
|---|---|
| `runs/sessions.db` | SQLite, transcript completo. É a base material que permite a [continuidade](glossary.md#接续) |
| `runs/manifest.json` | [Manifesto de execução](glossary.md#运行清单). Array JSON, **acumulado entre processos**; todos os números das páginas de casos podem ser reconferidos aqui |
| `runs/lineage.json` | [Linhagem](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Gravado por substituição atômica |
| `runs/aside/` | Runtime independente das consultas ao oráculo, com `sessions.db` e `manifest.json` próprios. **Custo e linhagem não se misturam ao manifesto principal** |
| `runs/workbench/` | Só aparece quando `-W` foi usado e o workflow não traz workbench próprio (caminhos `run` / `once`) |

Campos de cada registro do `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` é a marca deste processo, no formato `YYYYmmdd-HHMMSS-<6 dígitos hex>`. A política de gravação
é **acrescentar sem sobrescrever**: antes de cada escrita, o arquivo é relido e deduplicado por
`run` — as linhas deste processo são substituídas pelas mais recentes, e as linhas de outros
processos permanecem intactas.

Os nomes dos passos têm quatro formas:

| Forma | Quando |
|---|---|
| `<步骤名>` | Primeira tentativa |
| `<步骤名>#retry<N>` | Retentativa comum |
| `<步骤名>#round<N>` | Veredito não passou e o trabalho foi devolvido para continuar |
| `<步骤名>·判定#<N>` | O passo do [juiz](glossary.md#判定者) |

Quando morto por sinal, o passo em voo também é gravado, com o campo `error` valendo
`killed-by-signal`.

**Vários flower em paralelo no mesmo diretório**: `manifest.json` é seguro (releitura + merge por
`run`), mas `lineage.json` é sobrescrito inteiro, e dois processos vão apagar mutuamente a linhagem
de passos de mesmo nome. Para rodar em paralelo, use `-r` diferentes.

O `lineage.json` guarda o caminho absoluto do workspace. Se não bater, é como se não existisse: volta
**silenciosamente** para uma session nova, sem erro — afinal, depois que o diretório é copiado para
outro lugar, os `session_id` antigos também não seriam encontrados.

### `.flower/` {#flower-目录}

| Caminho | O que guarda |
|---|---|
| `.flower/scripts/` | Scripts que serão executados uma segunda vez. A primeira linha traz `# desc: 一句话`, e essa frase aparece no índice |
| `.flower/artifacts/` | Saídas longas, acima de 2000 caracteres: relatórios, dados, logs. Na conversa aparece só o caminho |
| `.flower/notes/` | Registros de decisão entre passos |
| `.flower/spill/` | [Spill](glossary.md#落盘): resultados de ferramentas acima de 4000 caracteres caem aqui, e no contexto fica só uma linha de ponteiro mais os 400 primeiros caracteres. O nome do arquivo são os 16 primeiros dígitos do sha256 do conteúdo mais `.txt` |
| `.flower/INDEX.md` | Índice dos diretórios acima, **injetado no system prompt do coordenador** (subagents não herdam) |

O caminho do `go` gera sempre estes arquivos sob `notes/`:

| Arquivo | Conteúdo |
|---|---|
| `notes/需求.md` | O [brief](glossary.md#需求确认书) congelado, quatro seções: objetivo / critérios de aceitação / fronteiras / desconhecidos e suposições |
| `notes/目标.md` | O objetivo congelado, duas seções: objetivo / checklist de veredito |
| `notes/问答记录.md` | Registro incremental de todas as perguntas e respostas (com estado), incluindo o que você disse por conta própria. **Não entra no contexto, serve só de arquivo** |
| `notes/交接-<步骤名>.md` | O [documento de handoff](glossary.md#交接书) escrito no handoff; a geração anterior é recolhida em `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | O `lineage.json`, `需求.md` e `目标.md` arquivados por `--new` ou `/new`. É **movido**, não apagado |

Com `--isolate`, o workbench é deslocado para fora do repositório:
`<workspace>.parent/.flower-<nome do workspace>/`. O worktree é a cópia privada de cada agent, e o
workbench é a camada compartilhada entre agents; o que é compartilhado não pode ficar dentro da cerca
privada. Nesse caso, o caminho do workbench passado ao modelo é absoluto.
