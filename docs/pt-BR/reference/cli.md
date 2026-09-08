# Referência da linha de comando

Depois de instalado, `flower` é um único executável, 4 subcomandos, 23 flags. Esta página lista todas
elas: o tipo de cada flag, o valor padrão, a semântica exata, mais como falar com a run no meio do
caminho, o que ele pergunta na primeira execução, quais são os códigos de saída e quais arquivos ele
coloca no seu diretório. Depois de ler esta página você não precisa abrir o código-fonte.

Código-fonte: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcomando | O que faz | Argumento posicional | Flags próprias |
|---|---|---|---|
| `go` | Tudo em um: esclarecer o pedido → definir o objetivo → delegar o trabalho → verdict a cada rodada. É o padrão quando você não escreve subcomando | `ask` (opcional) | 11 |
| `run` | Executa um [workflow](glossary.md#流程) escrito por você | `target` (obrigatório) | 0 |
| `once` | Executa um único agent uma vez, sem workflow e sem verdict | `prompt` (obrigatório) | 6 |
| `setup` | Configura credenciais, grava em `~/.config/flower/.env` | nenhum | 0 |

Total de 23 flags = 5 globais + 11 próprias do `go` + 6 próprias do `once` + `-h/--help`. `run` e
`setup` não têm flags próprias.

---

## Formas de invocação {#调用形式}

Todo o argv do `flower` passa primeiro por `_with_default_cmd()`, que completa o subcomando padrão,
e só depois vai para o argparse (`cli.py:1437-1439`). É por isso que `flower "帮我做一个 X"` funciona —
ele é reescrito como `flower go "帮我做一个 X"`.

As regras para completar o subcomando padrão (`cli.py:940-976`):

1. O conjunto de flags globais é **derivado do próprio parser principal**, não é uma lista fixa no
   código. As que têm `nargs == 0` contam como flags puras; as demais contam como flags com valor.
2. Varre da esquerda para a direita, pulando as flags globais. As que levam valor são puladas junto
   com o valor, e a forma com `=`, tipo `--workspace=/tmp`, também é reconhecida.
3. Para no primeiro token que não é uma flag global. Se ele for `go`, `run` ou `once`, é entregue ao
   argparse como está; **caso contrário, insere um `go` antes dele**, e ele vira o corpo do pedido
   do `go`.
4. Se a varredura terminar sem encontrar argumento posicional (argv vazio, ou só com flags globais)
   → acrescenta `go` no final e entra na entrada interativa.
5. Exceção: se o argv contiver `-h` ou `--help`, é devolvido como está, para o argparse imprimir a ajuda.

A constante usada nessa decisão é `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup` não está
lá dentro**, veja as consequências em [`setup`](#setup).

### O que a reescrita realmente produz {#实际的改写结果}

| O que você digitou | Como é realmente interpretado | Efeito |
|---|---|---|
| `flower` | `["go"]` | Pergunta interativamente "要做什么?" |
| `flower -v` | `["-v", "go"]` | Idem, com verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Começa direto |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Flags globais podem vir antes |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | A forma com `=` também é reconhecida |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Flags do subcomando podem vir depois do pedido |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Também podem vir antes |
| `flower --new` | `["go", "--new"]` | Só flag, sem pedido → entrada interativa |
| `flower once "hi"` | `["once", "hi"]` | Como está |
| `flower run flows:main` | `["run", "flows:main"]` | Como está |
| `flower run` | `["run"]` | O argparse reclama que falta `target`, **não** trata como pedido |
| `flower go run` | `["go", "run"]` | Desambiguação explícita: o corpo do pedido é `run` |
| `flower setup` | `["go", "setup"]` | Executa o `go`, com o pedido sendo a string `setup`, veja [`setup`](#setup) |
| `flower --help` | Como está | O argparse imprime a ajuda |

As palavras `run` e `once` **não** podem ser usadas diretamente como corpo do pedido; essa ambiguidade
foi deixada de propósito (`cli.py:949-950`). Para usá-las como pedido, escreva `flower go run`.

### As seis formas que funcionam {#六种能用的写法}

```bash
flower                                    # 1. Sem nada: pergunta "要做什么?" ou "接着上次?"
flower "帮我做一个 X"                       # 2. Pedido como argumento posicional
echo "帮我做一个 X" | flower --timeout 0    # 3. Alimenta o stdin por pipe
flower once "读一眼这个仓库"                 # 4. Agent único
flower run flows.py:main                  # 5. Executa um workflow próprio
flower go setup                           # 6. go explícito, com setup como corpo do pedido
```

A forma de módulo `python -m flower.cli` é equivalente a `flower` (`cli.py:1451-1452`).
Os parâmetros do wrapper de container `docker/flowerbox` são exatamente iguais aos do `flower`.

### Alimentar o stdin por pipe {#管道喂-stdin}

Quando `sys.stdin.isatty()` é falso, `ask_for_prompt()` **não imprime o cabeçalho do prompt** e lê uma
linha direto com `input("> ")` (`cli.py:993-1001`). Por isso `echo "..." | flower` funciona.

Mas logo em seguida ele imprime um aviso, e a thread de stdin encontra EOF imediatamente e sai:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Rodar por pipe deve vir com `--timeout 0`: as perguntas deixam de fingir que esperam 30 minutos,
falham na hora, e o agent decide sozinho e escreve as suposições na seção "未知与假设" do brief.

---

## Subcomandos {#子命令}

### `go` {#go}

Texto de ajuda: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Argumento posicional `ask`, com `nargs="?"` — se não for dado, entra na entrada interativa. É a porta
de entrada mais usada; `flower "做 X"` passa por aqui.

O que ele faz (`cli.py:1190-1221`):

1. `ensure_credentials()` — verifica as credenciais e realmente dispara uma sonda à API, veja
   [Fluxo de configuração na primeira execução](#首次运行的配置流程).
2. Sondagem de [wake](glossary.md#唤醒): apenas dá uma olhada de leitura para ver se este diretório já
   foi usado, sem gravar um único byte.
3. Se `ask` não foi dado, mostra o prompt e pergunta; digitar `/new` equivale a `--new`, e então
   **pergunta o pedido de novo**.
4. Se for [continuity](glossary.md#接续), imprime uma linha de banner de wake.
5. Monta o [workflow](glossary.md#流程) de três steps: `确认需求` → `设定目标` → `干活`,
   com um `干活·判定#N` depois de cada rodada de trabalho. `--clarify-only` deixa só o primeiro step.
6. Começa a rodar.

O banner de wake é assim (o diretório home no caminho é trocado por `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` aparece sempre; `目标 N 条` só aparece quando existe lista de verdict; `干活上下文 X`
exige que o contexto da última rodada daquela [session](glossary.md#会话) possa ser consultado em
`sessions.db` — se não for encontrado, não é exibido.

!!! warning "`-W` e `-T` são silenciosamente sobrescritas no caminho do `go`"
    Essas duas flags globais não fazem nada no `go`, sem erro e sem aviso:

    - `-W/--workbench`: o workflow montado pelo `go` sempre já traz seu próprio
      [workbench](glossary.md#工作台), e o código pega
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) — o do workflow sempre tem
      prioridade. Ou seja, o workbench é sempre `<workspace>/.flower/`
      (com `--isolate` é `<workspace>.parent/.flower-<nome>/`), e `-W` não muda isso.
    - `-T/--trim`: o `go` passa por `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`),
      usando diretamente o inverso de `--no-trim` e **sem nem olhar para `args.trim`**. Isto é, no
      caminho do `go` o [trim](glossary.md#裁剪) já vem ligado por padrão, e a única forma de desligar
      é `--no-trim`.

    Essas duas flags só têm efeito em `run` (quando o workflow não traz workbench próprio) e em `once`.

#### As 11 flags do `go` {#go-的-11-个开关}

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `--asks N` | int | `-1` | Cota de perguntas. `-1` ou qualquer negativo = **sem limite**; `0` = proibido perguntar, a primeira pergunta já dá `over_budget`; `N` = cota rígida. Ao estourar, a ferramenta recusa direto, sem bloquear a run |
| `--rounds N` | int | `3` | Limite do **número total de rodadas** de trabalho, não de rodadas extras. Ao fim de cada rodada, um [judge](glossary.md#判定者) independente decide "está pronto ou não"; se não estiver, devolve e continua a mesma session |
| `--no-goal` | flag | `False` | Desliga o [goal guard](glossary.md#目标看守): não gera `目标.md`, não faz [verdict](glossary.md#判定), o trabalho termina quando o step termina |
| `--judge-can-run` | flag | `False` | Deixa o judge executar comandos. O verdict fica mais duro, ao custo de ele também poder alterar o workspace |
| `--timeout segundos` | float | `1800.0` | Quanto tempo esperar por uma resposta humana. `0` ou negativo = totalmente automático, todas as perguntas falham **imediatamente**, sem fingir espera. Semântica em [timeout](#超时) |
| `--isolate` | flag | `False` | Dá a cada [subagent](glossary.md#subagent) um git worktree próprio, ou seja, [isolation](glossary.md#隔离). **Exige que o workspace seja um repositório git**, senão código de saída 1. Também move o workbench para fora do repositório |
| `--window N` | int | nenhum (inferido pelo nome do modelo) | Janela de contexto do modelo. Quando não dado: nome do modelo contém `1m` ou não contém `haiku` → 1,000,000; contém `haiku` → 200,000. Ao chegar em `janela − 50000` escreve o [handoff document](glossary.md#交接书) e faz o [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Desliga o handoff e volta ao [compact](glossary.md#压缩) nativo do SDK |
| `--new` | flag | `False` | Não continua de onde parou. **Move** (não apaga) o `lineage.json` + `需求.md` + `目标.md` do trecho anterior para `notes/archive/<YYYYmmdd-HHMMSS>/` e recomeça do zero |
| `--clarify-only` | flag | `False` | Faz só o [clarify](../guide/clarify.md), sem seguir para o trabalho — sobra apenas o step `确认需求` no workflow |
| `--no-trim` | flag | `False` | Desliga o trim. No caminho do `go` o trim vem **ligado** por padrão, e esta é a única forma de desligá-lo |

Cantos dos valores, todos silenciosos, sem erro e sem aviso:

- `--rounds 0` e `--rounds 1` são equivalentes — internamente é `retries = max(0, rounds - 1)`, ambos
  rodam 1 rodada.
- Qualquer negativo em `--asks` significa sem limite, não só `-1`.
- Qualquer negativo em `--timeout` equivale a `0`, ou seja, totalmente automático.
- `--window 0` é **silenciosamente ignorado** (`0` é falsy, nem chega a ser repassado) e volta ao valor
  padrão inferido pelo nome do modelo. Negativos são repassados e depois presos em `10000`.
- `--clarify-only` é uma **operação vazia** num diretório já esclarecido — o step `确认需求` vê um
  `需求.md` completo e pula, e como esse é o único step do workflow, nada acontece (fora o contador de
  wake +1). Para reesclarecer, combine com `--new`.
- O `--help` do `go` termina com "全局开关(-v/-w/-r/-T)见 `flower --help`"; essa linha
  **esqueceu o `-W`**.

### `run` {#run}

Texto de ajuda: `运行一个 workflow` (`cli.py:1309-1312`).

Argumento posicional `target`, escrito como `módulo:atributo`. As duas formas são suportadas
(`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # import pelo nome do módulo
flower run flows.py:build        # caminho de arquivo; coloca o diretório pai no sys.path e importa pelo nome do arquivo
```

Se o atributo obtido for chamável, ele é chamado uma vez e o retorno vira o
[workflow](glossary.md#流程); se já for um objeto de workflow, é usado direto.

**`run` não tem nenhuma flag própria**, só as 5 globais. Então `--window`, `--no-handoff` e afins ficam
sempre no padrão nesse caminho (o código usa `getattr` como fallback, `cli.py:1041-1043`). Para
ajustá-los, escreva os parâmetros dentro do seu próprio workflow.

### `once` {#once}

Texto de ajuda: `跑一次单 agent` (`cli.py:1314-1324`). O argumento posicional `prompt` é obrigatório.

Ele monta um `AgentSpec(name="ad-hoc", …)` e executa direto, **sem passar pelo `_drive`**. Por isso o
`once` não tem:

- Ctrl-C para interromper e falar (apertar gera um `KeyboardInterrupt` comum)
- Thread de resposta no stdin, nem o prompt de entrada fixo na parte de baixo
- Perguntas ao oracle
- Gravação de emergência da contabilidade em SIGHUP / SIGTERM
- A linha final `总花费 … · 清单 …`
- Guia de reconfiguração automática depois de falha de credencial

No [run manifest](glossary.md#运行清单), o nome deste step é sempre `ad-hoc`.

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-i`, `--instructions` | str | vazio | Instruções de domínio, feitas em [append](glossary.md#叠加) **depois** do system prompt nativo do Claude Code, sem substituí-lo |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Lista branca de ferramentas separada por vírgula. Sem valor, são essas três ferramentas somente-leitura |
| `-p`, `--permission-mode` | str | `default` | Só aceita `default`, `acceptEdits`, `plan` ou `bypassPermissions`; qualquer outro valor faz o argparse abortar com código de saída 2 |
| `-b`, `--budget` | float | sem limite | Teto de [budget](glossary.md#预算) em dólares; ao estourar, para |
| `--resume SESSION_ID` | str | nenhum | Continua uma session existente |
| `--fork` | flag | `False` | Bifurca em vez de continuar, usado junto com `--resume` |

!!! warning "O tempo e o custo acumulado mostrados pelo `once` são sempre 0"
    O `once` cria uma nova instância de renderizador a cada evento recebido (`cli.py:688-690`,
    `cli.py:1239`), e tanto o início da contagem de tempo quanto o custo acumulado ficam guardados na
    instância (`cli.py:500-501`). Portanto:

    - O `用时` da linha final é sempre `0:00`
    - O `累计 $0.00` da linha de status é sempre 0, e o `上下文` também nunca acumula

    O custo real de cada step tem que ser lido no campo `cost_usd` de `runs/manifest.json`. Os caminhos
    `go` e `run` mantêm a mesma instância de renderizador e não têm esse problema.

### `setup` {#setup}

Texto de ajuda: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`).
Sem nenhuma flag.

O que ele faz: lê o `.env` → decide se já foi configurado → inicia o fluxo interativo de configuração,
com `reason` sendo `重新配置。` ou `还没配过凭证。`. O conteúdo da tela está em
[Fluxo de configuração na primeira execução](#首次运行的配置流程).

!!! warning "`flower setup` hoje não chega nesse subcomando"
    A constante de decisão do subcomando padrão, `_CMDS = ("go", "run", "once")` (`cli.py:937`),
    **esqueceu `"setup"`**, mas o `setup` está de fato registrado no parser (`cli.py:1326`). Assim,
    `flower setup` é reescrito como `flower go setup` — **o que roda é o workflow completo do `go`, com
    o corpo do pedido sendo a string `setup`**: primeiro valida as credenciais, depois pergunta o
    pedido e então começa mesmo a delegar o trabalho. Com flags globais é igual:
    `flower -v setup` → `["-v", "go", "setup"]`.

    **Não existe nenhum argv capaz de chegar ao subcomando `setup`.**

    Para configurar credenciais, hoje só há estes dois caminhos, e ambos levam à mesma interface
    interativa:

    - Rodar direto `flower "随便一句诉求"`; se não houver credencial configurada, ele pergunta antes;
    - Ou escrever `~/.config/flower/.env` à mão, com as chaves listadas em
      [As chaves que ele grava](#写出来的键).

    Alguns textos também ficam afetados: o ``跑 `flower setup` 重配。`` impresso quando a credencial é
    recusada, e o comentário da primeira linha do `.env`, ``由 `flower setup` 写``, apontam todos para
    esse comando inalcançável.

---

## Flags globais {#全局开关}

As 5 flags globais ficam penduradas ao mesmo tempo no parser principal e em cada subcomando
(`cli.py:1250-1266`). A cópia dos subcomandos usa `argparse.SUPPRESS`: se não for passada, não escreve
o atributo, então **tanto faz escrevê-las antes ou depois do subcomando**, uma não sobrescreve a outra.
O efeito colateral é que elas não aparecem no `--help` dos subcomandos — para vê-las, rode
`flower --help`.

| Flag | Tipo | Padrão | Descrição |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Diretório de trabalho do agent. É passado por `resolve()` para caminho absoluto e criado com `mkdir -p`. O [workbench](glossary.md#工作台) `.flower/` é criado aqui dentro |
| `-r`, `--run-dir` | str | `runs` | Diretório do [session store](glossary.md#会话存储) e do run manifest. **Relativo ao CWD atual, não ao workspace** |
| `-v`, `--verbose` | flag | `False` | Imprime mais coisas, veja abaixo |
| `-W`, `--workbench` | flag | `False` | Habilita o workbench. **Não tem efeito no `go`**, só vale para `run` (quando o workflow não traz workbench próprio) e `once`, e nesse caso o workbench fica em `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | No resume, troca resultados grandes de ferramenta antigos por ponteiros de arquivo, ou seja, [trim](glossary.md#裁剪). **Não tem efeito no `go`**, que controla isso ao contrário com `--no-trim` |
| `-h`, `--help` | flag | — | Existe em todo parser. Quando aparece no argv, a reescrita do subcomando padrão é pulada e a ajuda é impressa direto |

O detalhe de `-r/--run-dir` ser relativo ao CWD morde: `flower -w /other/proj "做 X"` cria `runs/` no
**diretório onde você digitou o comando**, enquanto `.flower/` é criado dentro de `/other/proj/` — os
dois estados se separam. Para mantê-los juntos, passe explicitamente `-r /other/proj/runs`.

A ajuda do `-v` diz "显示思考与工具结果", mas o pensamento da [main thread](glossary.md#主线程)
**já é exibido por padrão**. O que o `-v` realmente liga a mais é:

- O corpo do texto dos subagents (não exibido por padrão, só as chamadas de ferramenta deles)
- Resultados normais de ferramenta (por padrão só os que deram erro)
- Eventos `prompt`
- Antes de iniciar, imprime uma vez a configuração de credenciais em vigor, com o token mascarado
  deixando só os 4 primeiros caracteres

Esta última passa por um `print()` cru, **sem sanitização de saída, sem quebra de linha e sem a
proteção do lock de escrita do terminal**; ao rodar vários `flower` em paralelo, essas linhas podem
sair rasgadas.

---

## Como falar com ele durante a run {#运行中怎么和它说话}

Depois que a run começa, o terminal **está o tempo todo lendo o que você digita**. Não é preciso
esperar uma pergunta nem apertar nada para entrar em modo de entrada — a última linha é sempre a linha
onde você pode digitar.

### O prompt de entrada fixo embaixo {#常驻在最下面的输入提示符}

Há uma thread daemon `flower-stdin` lendo o stdin o tempo todo (`cli.py:764-934`), usando `select` com
polling a cada 0.2 segundos, não leitura bloqueante (assim o sinal de parada consegue acordá-la; em
streams que não suportam `select`, como no Windows, ela degrada para leitura bloqueante).

**Ela lê o tempo todo, não só quando há uma pergunta.** A razão é: se só lesse durante as perguntas, o
que você digitou nas horas de trabalho ficaria no buffer do terminal e seria engolido como resposta na
pergunta seguinte — você seria respondido antes mesmo de ver a pergunta.

Na exibição, `_say()` é a única saída; antes de cada escrita ele apaga o prompt e redesenha depois
(`cli.py:309-315`), então o prompt nunca é empurrado para cima pela saída de eventos. **No redesenho,
os caracteres que você digitou pela metade e ainda não deu Enter voltam junto** — eles ficam em
`_PROMPT["buf"]` (`cli.py:183-192`). Sem isso, o conteúdo na verdade não se perde (ainda está no buffer
de linha do terminal, e o Enter o envia normalmente), mas você não o vê, fica inseguro e redigita.

O prompt tem dois textos, alternando conforme haja ou não pergunta pendente:

| Estado | Última linha da tela |
|---|---|
| Com pergunta pendente | `你的回答 (回车=跳过,让它自己判断) > ` |
| Sem pergunta pendente | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Modo de entrada caractere a caractere e teclas {#逐字符输入}

Para redesenhar "os caracteres digitados pela metade", o flower precisa assumir a entrada. Quando o
stdin é um terminal e é possível `import termios`, o terminal é colocado em `cbreak` **antes** de
iniciar a thread `flower-stdin` (`cli.py:793-807`) — usa `cbreak` e não `raw` para que Ctrl+C continue
gerando `SIGINT`, mantendo todo o comportamento de [Ctrl-C](#ctrl-c). Tem que ser antes de iniciar a
thread: colocar isso dentro da thread cria uma corrida real, e os caracteres digitados no instante em
que a thread ainda não pegou CPU são engolidos pelo modo de linha, aparecendo como "a entrada sumiu"
(reproduzido de forma estável uma vez a cada três testes, `cli.py:928-934`).

Se não der para configurar, volta ao `readline()` de linha inteira (não é terminal, `termios`
indisponível, `tcgetattr` falhou). Os dois caminhos funcionam, só que no modo de linha as teclas abaixo
não existem (`cli.py:883-899`).

A lógica de edição está em `LineEditor` (`cli.py:320-414`), uma máquina de estados pura que não toca no
terminal:

| Tecla | Efeito |
|---|---|
| Caractere imprimível | Inserido na posição do cursor. UTF-8 usa um decodificador incremental e só entra no buffer quando um caractere completo é formado |
| Backspace / Ctrl+H | Apaga **um caractere** antes do cursor. No modo de linha o terminal apaga por byte, um caractere chinês exige três toques e ainda sai lixo; aqui não |
| ← / → | Move o cursor de verdade. A sequência de escape inteira é consumida, sem inserir coisas como `[A` na entrada |
| Home / End (ou `[1~` / `[4~`) | Salta para o início / fim da linha |
| Delete (`[3~`) | Apaga um caractere para frente |
| Ctrl+A / Ctrl+E | Início / fim da linha |
| Ctrl+U | Limpa a linha inteira |
| Ctrl+D | Só é EOF quando o buffer está vazio; com conteúdo, é ignorado |
| ↑ / ↓ | **Não fazem nada**. Não há histórico, e mexer só faria você achar que perdeu algo (`cli.py:335`) |
| Outros caracteres de controle | Ignorados |

O Enter entrega o buffer e o esvazia, além de pular uma linha na tela — o que você disse fica ali em
cima (`cli.py:811-827`).

### Para onde vai o que você digita {#你敲的东西去哪了}

| O que você digita | Com pergunta pendente | Sem pergunta pendente |
|---|---|---|
| **Linha vazia (só Enter)** | Pula a pergunta, deixa ele decidir sozinho | Não faz nada |
| **Começando com `?`** | Pergunta ao oracle, veja abaixo | Idem |
| **Só dígitos**, dentro da faixa das opções | Substitui pela opção correspondente e responde | Tratado como texto comum |
| Outro texto | Enviado como resposta ao agent que perguntou | Vai para a caixa de entrada, como requisito adicional |
| EOF (Ctrl-D ou pipe fechado) | Recusa a pergunta, remove o prompt, a thread sai | Remove o prompt, a thread sai |

Ao entrar na caixa de entrada, ele imprime um recibo:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Quando não há [brief](glossary.md#需求确认书) onde fazer o spill, a segunda metade vira
`没有确认书可落盘 —— 它可能活不过下一个步骤`. A caixa de entrada **não interrompe** o worker que está
trabalhando; ele só pega da próxima vez que consultar a caixa por iniciativa própria. A mesma frase
também é anexada a `notes/需求.md`; sem spill, ela não sobrevive à fronteira do step — o próximo step é
uma session nova, que só lê os artefatos congelados.

### Começar com `?` = pergunta ao oracle {#旁路问答}

Uma linha que começa com `?` não é enviada ao agent em execução, e sim ao
[oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Ele sobe um Runtime **independente**, com `run_dir` em `<run_dir>/aside/`, então o custo e a lineage de
sessions dele não se misturam ao `manifest.json` principal. O papel é somente-leitura, as ferramentas
são apenas `Read`, `Glob`, `Grep`, no máximo 12 rodadas, com teto de custo de **$0.5**. O contexto que
ele vê são os **60** eventos mais recentes (eventos `thinking` e `prompt` não entram nessa janela),
cada um truncado em 200 caracteres, mais a descrição do caminho do workbench.

Ele roda **concorrentemente**; a run em andamento não espera um segundo. A resposta é assim:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Em caso de falha, imprime uma linha em vermelho `# 旁路问答失败:<类型>: <消息>`, **sem afetar o fluxo
principal**. Na saída, espera no máximo **120** segundos pelo encerramento do oracle, e antes de
esperar imprime uma linha `(等 N 条旁路问答收尾…)`.

O que ele diz não entra no contexto daquela run — perguntar não afeta a run, e a resposta é descartada
depois.

!!! warning "O `？` de largura total não aciona o oracle — usuários de IME chinês vão tropeçar"
    A linha de código que decide a pergunta ao oracle é (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Os dois caracteres **são o `?` ASCII de meia largura** (`0x3f`) — verificado byte a byte. Pela
    forma como foi escrito, a intenção era claramente aceitar tanto o `?` de meia largura quanto o `？`
    de largura total (U+FF1F) produzido por IMEs chineses, mas na prática ficou o mesmo caractere.

    Consequência: **uma linha que começa com o `？` de largura total não é tratada como pergunta ao
    oracle**, e sim enviada silenciosamente à caixa de entrada como "requisito adicional", sendo então
    anexada a `notes/需求.md`. O recibo que você vê é `+ 收到`, não `# 旁路`.

    Para perguntar ao oracle, **é obrigatório usar o `?` de meia largura** — troque o IME para inglês
    antes de digitar, ou digite ao menos o primeiro caractere em meia largura.

### O que aparece na tela {#屏幕上都是什么}

Os ícones são **sempre ASCII**, não emoji (`cli.py:51-69`). A razão está no comentário do código: emoji
junto com caracteres de moldura, geométricos e setas dispara fallback de glifos no terminal, o que já
causou dois travamentos de terminal.

| Ícone | Significado | Ícone | Significado |
|---|---|---|---|
| `=` | Separador de step | `+` | Concluído / respondido / recebido |
| `~` | Pensamento, retentativa | `x` | Falha / erro |
| `>` | Delegação | `#` | Handoff, oracle, tarefa |
| `*` | Chamada de ferramenta | `-` | Linha de status, item de lista |
| `?` | Pergunta | `<-` | Continuação, ponto de aterrissagem do handoff |
| `!` | Aviso / interrupção | `.` | Pulado |
| `\| ` | Barra vertical de indentação do subagent | | |

!!! warning "O `❓` e o `↩` da documentação antiga não existem no terminal real"
    A documentação inicial usava `❓` para pergunta e `↩` para a linha de wake. **No código nunca
    foram esses dois caracteres** — o ícone de pergunta é o `?` de meia largura, e o ícone de wake e do
    ponto de aterrissagem do handoff são os dois caracteres ASCII `<-`.

    Então o que o terminal real imprime é:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Não é `❓ 这个工具……`, nem `↩ 在 ~/proj 接上上次`. Fazer grep nos logs seguindo a documentação
    antiga não encontra nada.

Os cinco estados de uma pergunta, na tela, são:

| Estado | Saída na tela |
|---|---|
| Perguntou | `  ? <问题>`, seguido das opções uma a uma `     1) 选项一`, e havendo cota, mais `     (还能问 N 次)` |
| Respondeu | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Cota esgotada | `  ! 提问额度用完` |
| Você pulou | `  . 已跳过` |

Quando `--asks` está sem limite (o padrão), a última linha "还能问 N 次" não é exibida.

Quando o [handoff](glossary.md#换代) termina de escrever o handoff document, sai um bloco inteiro:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Quando o handoff document é degradado, entra uma linha vermelha extra
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

A saída também faz duas coisas que você não vê: todas as linhas passam por uma sanitização que
**só deixa passar os códigos SGR de cor do próprio flower**, engolindo por inteiro sequências de limpar
tela e mover cursor cuspidas pelo modelo ou pelas ferramentas; e a largura é
`max(40, min(colunas do terminal, 110))`, então em terminais largos o texto não ocupa a linha inteira —
isso é intencional.

### O prompt na largada {#起跑时的提示符}

Rodando `flower` puro (sem pedido), ele pergunta antes. Dois textos:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

O segundo só aparece quando este diretório já foi usado e as quatro seções de `需求.md` estão completas.

Esse prompt lê via `input()`, **sem passar pelo parsing do shell**. Aspas chinesas, espaços e pontos de
exclamação podem ser digitados direto — essa é toda a razão de ele existir. O zsh, ao encontrar a aspa
direita chinesa, entra em `dquote>` esperando continuação, o que parece travamento, mas na verdade nada
chegou a iniciar.

- Entrada vazia + primeira vez → sai, imprimindo ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Entrada vazia + wake → **é válido**, significa "continuar"
- Digitar `/new` → equivale a `--new`, arquiva o trecho anterior e **pergunta o pedido de novo**
- Ctrl-C / Ctrl-D → sai, imprimindo `已取消`

### Timeout {#超时}

`--timeout` é float, em segundos, padrão `1800.0`. Três faixas de valor:

| Valor | Comportamento |
|---|---|
| `> 0` | Espera esses segundos. Ao estourar, a pergunta é liquidada como `timeout` e o agent decide sozinho |
| `0` ou negativo | **Totalmente automático**. A pergunta não entra na fila de espera, não emite evento `asked`, não aparece na tela, e é liquidada como `timeout` na hora |
| Esperar para sempre | **Impossível pela linha de comando**. Internamente há suporte a "esperar para sempre", mas `--timeout` é float e tem valor padrão, e nenhuma forma de escrita o produz. O teto é passar um número muito grande de segundos |

`--timeout 0` e `--timeout -1` são completamente equivalentes. Rodar por pipe, em CI ou sem supervisão
usa exatamente isso.

Quando a pergunta não obtém resposta, o resultado de ferramenta devolvido ao modelo é um texto fixo,
em quatro variantes:

| Resultado | Texto devolvido ao modelo |
|---|---|
| Cota esgotada | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| Você pulou | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| A pergunta estava vazia | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**A semântica do Ctrl-C nos dois lugares é completamente diferente.**

**Apertado no prompt de largada `> `** — sai do programa direto, imprimindo `已取消`.

**Apertado no meio da run** — interrompe a rodada atual e te dá uma chance de falar:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Dar Enter direto aqui significa apenas interromper sem dizer nada e seguir. Se houver perguntas
pendentes no momento, sai uma linha a mais: `  (有 N 个提问还等着,打断不影响它们)`.

**Apertar Ctrl+C outra vez é sair de verdade**, e é um `KeyboardInterrupt` não capturado — vai aparecer
um traceback de Python na tela, não é uma saída limpa.

A interrupção é cooperativa: corta de forma limpa na fronteira de mensagem, sem cancelar tarefas à
força. Ela **não conta como tentativa falha** e não consome retentativas. Ao continuar, é anexada uma
explicação dizendo ao modelo que "chamadas de ferramenta em voo retornando interrupted é um efeito
colateral normal da interrupção, não uma falha de ambiente".

Esse Ctrl-C customizado só é instalado quando `sys.stdin.isatty()` (`cli.py:1097`). Rodando por pipe,
mantém o comportamento padrão do Python, ou seja, sai já na primeira vez. O caminho do `once` não passa
por aqui, então o Ctrl-C no `once` também sai já na primeira vez.

### SIGHUP / SIGTERM {#sighup-sigterm}

Os caminhos `go` e `run` instalam tratamento para `SIGHUP` e `SIGTERM`: primeiro gravam também o
**step em voo** no `manifest.json`, marcado como `killed-by-signal`, depois restauram a ação padrão e
realmente saem.

A origem disso é que, quando o terminal trava, o kernel manda SIGHUP, cuja ação padrão encerra o
processo direto: o `finally` não roda, o manifest não é gravado — e a contabilidade daquela run se
perde. Em threads que não são a principal do sistema operacional, ou em plataformas sem suporte, isso
é pulado silenciosamente.

---

## Fluxo de configuração na primeira execução {#首次运行的配置流程}

As três portas de entrada `go`, `run` e `once` chamam `ensure_credentials()` logo no começo
(`cli.py:1392-1428`), com **duas barreiras**.

### Primeira barreira: existe credencial? {#第一道-有没有凭证}

Procura credenciais por ordem de prioridade. Se não achar `ANTHROPIC_API_KEY` nem
`ANTHROPIC_AUTH_TOKEN`, inicia a configuração interativa; em modo não interativo (stdin não é
terminal), não bloqueia, imprime este bloco e sai:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Este texto tem dois pontos que não batem com a implementação: o `flower setup` da segunda linha hoje é
inalcançável (veja [`setup`](#setup)); e a quarta linha **contradiz o código** — o flower de fato usa o
bloco `env` de `~/.claude/settings.json` e `settings.local.json` como **último nível de fallback**,
pegando emprestado apenas 9 chaves de credencial dali, sem assumir nenhuma outra configuração. O lugar
que imprime essa linha é `env.py:192` (a função `check_credentials()` está definida em `env.py:184`),
enquanto quem realmente lê esses dois arquivos é `env.py:56-75` e `:109-111`; registrado na
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).
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

- A pergunta 1 é **obrigatória**. Deixar em branco imprime em vermelho `没给 token,取消。` e a
  configuração é abandonada.
- As perguntas 2 e 3 podem ficar em branco.
- Quando o stdin não é terminal, todo o fluxo é pulado, sem bloquear.

### As chaves que ele grava {#写出来的键}

| O que você digitou | Chave gravada |
|---|---|
| Token começando com `sk-ant-` | `ANTHROPIC_API_KEY` |
| Outros tokens | `ANTHROPIC_AUTH_TOKEN` |
| Endereço de gateway não vazio | `ANTHROPIC_BASE_URL` |
| Nome de modelo não vazio | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` e `ANTHROPIC_DEFAULT_SONNET_MODEL`, os três de uma vez |

O caminho do arquivo é `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, e o diretório pai é criado
automaticamente. A escrita é **sobrescrita integral**, chaves com valor vazio são puladas, e ao
terminar faz `chmod 0600` e carrega na hora — não precisa reabrir o shell. A primeira linha é sempre um
comentário lembrando de não versionar o arquivo.

### Segunda barreira: a credencial funciona? {#第二道-凭证能不能用}

Com a configuração completa, imprime uma linha `- 验一下凭证…` e então **dispara uma chamada real à API**.

Detalhes da sonda: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, timeout padrão de 20 segundos, via
`urllib` da stdlib, sem trazer dependências. O modelo é escolhido na ordem
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. Havendo
`ANTHROPIC_API_KEY`, usa o header `x-api-key`; caso contrário,
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` é 16 de propósito, e não 1: em testes, modelos com cadeia de pensamento forçada não cabem
nem o pensamento, e o servidor demora até 30 segundos para responder; com 16, leva só 3.6 segundos.

A conclusão da sonda é tratada em três classes, e **a diferença importa**:

| Conclusão | Condição de disparo | O que o flower faz |
|---|---|---|
| `auth` | HTTP 401 / 403, ou simplesmente nenhuma credencial | Imprime `! 凭证被拒:<响应体前 160 字>`, inicia a reconfiguração interativa e valida de novo ao fim. Em modo não interativo, código de saída 1 |
| `config` | HTTP 404, ou 400 **e** o corpo da resposta dizendo explicitamente que não foi encontrado / não existe (`not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Imprime `! 网关地址或模型名不对:<…>`, idem acima |
| `net` | Sem conexão / timeout / falha de DNS / falha de TLS / 5xx | Imprime `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **não pede reconfiguração e começa a rodar** |
| `ok` | Menor que 400, ou qualquer caso indeterminado, tudo é liberado | Continua em silêncio |

O critério de `config` foi **apertado**: em JSONs de erro no estilo da Anthropic, a palavra `model`
aparece quase sempre, e usá-la como "nome de modelo errado" transformaria um 400 transitório em erro de
configuração e forçaria uma reconfiguração — só vale quando a resposta diz explicitamente
"não encontrado / não existe" (`env.py:176-182`).

O `net` é intencional: uma oscilação de rede não deve forçar você a redigitar o token, e o próprio
flower tem mecanismo de suspender e reconectar em queda de rede. Ao ver "探针没打通", ignore e siga.

A chance de reconfiguração é dada **no máximo uma vez**. Se falhar de novo na segunda, sai.

**A sonda só é disparada em terminal interativo.** `ensure_credentials()` retorna direto, sem essa
chamada à API, se qualquer uma destas condições valer (`cli.py:1413`): quem chamou passou
`probe=False`, [`FLOWER_NO_PROBE`](config.md#行为开关) está setado, ou **o stdin não é terminal**
(pipe / CI / testes offline). O motivo é que, sem interatividade, descobrir o problema não permite
consertá-lo, e o único efeito seria "falhar mais cedo" — e falhar mais cedo, em caso de **falso
positivo**, é pior do que não sondar. Se a credencial for realmente ruim, a run vai explodir sozinha,
e esse caminho é capturado pela
[reconfiguração automática depois de uma falha](#跑挂了之后的自动重配).

### Reconfiguração automática depois de uma falha {#跑挂了之后的自动重配}

Quando o workflow falha, o flower pega a mensagem de erro do step que falhou e a compara com uma regex
(401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). Se casar e o stdin
for um terminal, ele imprime na hora `! 看起来是凭证不对:<前 120 字>` e inicia a configuração
interativa; ao terminar, imprime:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

E depois sai com código de saída 1 de qualquer forma. O caminho do `once` não tem essa parte.

---

## Códigos de saída {#退出码}

| Código | Quando |
|---|---|
| `0` | Terminou normalmente |
| `1` | Todas as saídas deliberadas. A mensagem vai para o **stderr**, sem traceback. Lista abaixo |
| `2` | Erro de argumento do argparse: flag desconhecida, argumento posicional faltando, `-p` com valor fora das choices |
| `130` | Dois Ctrl+C seguidos no meio da run. É um `KeyboardInterrupt` não capturado, **com traceback de Python** |
| Morto por sinal | SIGHUP / SIGTERM: grava primeiro o step em voo no manifest e depois segue a ação padrão |

Todas as mensagens do código de saída 1:

| Mensagem | Quando |
|---|---|
| `已取消` | Ctrl-C ou Ctrl-D no prompt de largada |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Diretório novo + Enter direto |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 linhas no total) | Não interativo + sem credencial |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Não interativo + sonda concluiu `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Não interativo + sonda concluiu `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` usado em diretório não git |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Pedido vazio e diretório sem wake |
| `在步骤 '<步骤名>' 中止` | Algum step do workflow falhou e a política é parar |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, faltou os dois-pontos |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Falha no import do módulo alvo |
| `'<模块>' 里没有 '<属性>'` | O atributo não existe no módulo |

Ao terminar (caminhos `go` / `run`), imprime uma última linha:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

Esse valor conta apenas o gasto **deste processo**, sem incluir a run anterior — ainda que o próprio
arquivo de manifest acumule entre processos.

---

## O que ele cria no projeto {#它在项目里创建了什么}

Duas árvores: `<run_dir>/` (padrão `./runs/`, relativo ao CWD) guarda a contabilidade e as sessions;
`<workspace>/.flower/` guarda o [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Caminho | O que guarda |
|---|---|
| `runs/sessions.db` | SQLite, transcript completo. É a base material que permite a [continuity](glossary.md#接续) |
| `runs/manifest.json` | [Run manifest](glossary.md#运行清单). Array JSON, **acumulado entre processos**; todos os números das páginas de caso podem ser reconferidos aqui |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Escrito com substituição atômica |
| `runs/aside/` | Runtime independente das perguntas ao oracle, com seu próprio `sessions.db` e `manifest.json`. **Custo e lineage não se misturam ao manifest principal** |
| `runs/workbench/` | Só aparece quando `-W` foi usado e o workflow não traz workbench próprio (caminhos `run` / `once`) |

Campos de cada registro do `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` é a marca deste processo, no formato `YYYYmmdd-HHMMSS-<6 dígitos hex>`. A política de gravação é
**anexar sem sobrescrever**: antes de cada escrita, relê o arquivo e deduplica por `run` — as linhas
deste processo são substituídas pelas mais recentes, e as linhas de outros processos ficam como estão.

Os nomes de step têm quatro formatos:

| Formato | Quando |
|---|---|
| `<步骤名>` | Primeira tentativa |
| `<步骤名>#retry<N>` | Retentativa comum |
| `<步骤名>#round<N>` | O verdict não passou e o step foi devolvido para continuar |
| `<步骤名>·判定#<N>` | O step do [judge](glossary.md#判定者) |

Quando morre por sinal, o step em voo também é gravado, com o campo `error` valendo
`killed-by-signal`.

**Vários flower em paralelo no mesmo diretório**: o `manifest.json` é seguro (relê e mescla por `run`),
mas o `lineage.json` é sobrescrito por inteiro, e dois processos vão apagar a lineage um do outro para
steps de mesmo nome. Para rodar em paralelo, use `-r` diferentes.

O `lineage.json` guarda o caminho absoluto do workspace. Se não bater, é tratado como inexistente e o
sistema volta **silenciosamente** para uma session nova, sem erro — depois que o diretório é copiado
para outro lugar, o `session_id` antigo não seria encontrado mesmo.

### `.flower/` {#flower-目录}

| Caminho | O que guarda |
|---|---|
| `.flower/scripts/` | Scripts que serão rodados uma segunda vez. A primeira linha traz `# desc: uma frase`, e essa frase aparece no índice |
| `.flower/artifacts/` | Saídas longas, acima de 2000 caracteres: relatórios, dados, logs. Na conversa aparece só o caminho |
| `.flower/notes/` | Registros de decisão entre steps |
| `.flower/spill/` | [Spill](glossary.md#落盘): resultados de ferramenta acima de 4000 caracteres caem aqui, e no contexto fica só uma linha de ponteiro mais os 400 primeiros caracteres. O nome do arquivo são os 16 primeiros dígitos do sha256 do conteúdo mais `.txt` |
| `.flower/INDEX.md` | Índice dos diretórios acima, **injetado no system prompt do coordinator** (subagents não o herdam) |

O caminho do `go` gera sempre estes arquivos sob `notes/`:

| Arquivo | Conteúdo |
|---|---|
| `notes/需求.md` | O [brief](glossary.md#需求确认书) congelado, em quatro seções: objetivo / critérios de aceitação / fronteiras / incógnitas e suposições |
| `notes/目标.md` | O objetivo congelado, em duas seções: objetivo / lista de verdict |
| `notes/问答记录.md` | Registro em append de todas as perguntas e respostas (com estado), incluindo o que você falou por iniciativa própria. **Não entra no contexto, é só arquivo** |
| `notes/交接-<步骤名>.md` | O [handoff document](glossary.md#交接书) escrito no handoff; a geração anterior é recolhida em `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | O `lineage.json`, `需求.md` e `目标.md` arquivados por `--new` ou `/new`. É **movimentação**, não remoção |

Com `--isolate`, o workbench é movido para fora do repositório:
`<workspace>.parent/.flower-<nome do workspace>/`. O worktree é a cópia privada de cada agent, e o
workbench é a camada compartilhada entre agents; o que é compartilhado não pode ficar dentro de uma
cerca privada. Nesse caso, o caminho do workbench passado ao modelo é absoluto.
