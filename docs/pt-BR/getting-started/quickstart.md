# Início rápido

Três comandos bastam para colocar isso no ar: instalar, entrar no diretório do projeto e digitar `flower`. Esta página coloca esses três na frente de tudo e depois explica o que acontece na tela depois do Enter, como responder quando ele te pergunta algo e o que checar primeiro quando nada roda.

## Instale, entre no diretório, digite flower {#跑起来}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
cd /path/to/your/project
flower
```

O primeiro comando é um script que procura sozinho `uv` / `pipx` / `pip` para instalar o comando `flower`; basta Python ≥ 3.10, sem Node e sem o Claude Code CLI. O terceiro não leva nenhum argumento e **não exige aspas no shell**.

Se quiser outro método de instalação (pipx / pip / a partir do código-fonte), ou se esse script não funcionar na sua máquina, veja [Instalação](install.md) — mas não é preciso ler aquela página inteira antes de voltar.

## Depois do Enter {#回车之后}

Na primeira execução nesta máquina, ele começa perguntando as credenciais: API key ou endereço do gateway. Configure uma vez, fica salvo em `~/.config/flower/.env` e vale em todo lugar dali em diante. Se o Claude Code já estiver instalado e configurado na máquina, ele pega aquele token emprestado direto, sem nem perguntar.

Com as credenciais no lugar, o cursor para no `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Essa linha lê da entrada padrão, **sem passar pelo parser do shell** — aspas chinesas, espaços e pontos de exclamação podem ser digitados direto.

Antes de começar ele imprime uma linha `- 验一下凭证…`, que é uma sonda de API de verdade. Se a credencial for recusada, imprime `! 凭证被拒:…` e pergunta na hora se você quer reconfigurar; se não conseguir conectar, imprime `(探针没打通:… —— 当作网络问题,照常开跑)` e **não** faz você reconfigurar um token que estava perfeitamente bom.

Passada a sonda, ele começa a trabalhar, em três passos. Cada linha de traços `==` na tela é uma fronteira de [passo](../reference/glossary.md#步骤); o `1/3` à direita é o progresso:

```text
== 确认需求 ======================================================== 1/3

  ? X 要跑在什么环境上?
     1) 只在我这台 macOS 上
     2) Linux 服务器
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
  + 只在我这台 macOS 上

  ? 「做完了」以什么为准?
你的回答 (回车=跳过,让它自己判断) > 能跑起来,并且 pytest 全绿
  + 能跑起来,并且 pytest 全绿

  + 完成 9 轮 · $0.53 · 用时 6:02

== 设定目标 ======================================================== 2/3

  ~ 把这份需求拆成能当场验证的条目
  + 完成 12 轮 · $0.41 · 用时 9:06

== 干活 ============================================================ 3/3

  ~ 先看一眼现在有什么,再决定第一刀切哪
  * Read README.md
  > 派人 coder 实现 X 的第一版,带最小测试
  先让 coder 把骨架搭起来,我再看要不要拆第二个人。
  - 上下文 36.8K · 累计 $0.94 · 12:44
  + 完成 12 轮 · $12.34 · 用时 52:53
  + 完成 37 轮 · $1.40 · 用时 58:19

总花费 $14.68 · 清单 /path/to/your/project/runs/manifest.json
```

Os ícones são sempre ASCII: `~` pensando, `*` chamada de ferramenta, `>` despachando alguém, `+` sucesso, `x` falha, `?` pergunta, `<-` retomando a última vez. Não são emoji — emoji e caracteres de moldura disparam fallback de glifo no terminal, e na prática travaram o terminal duas vezes. **Todos os exemplos de terminal deste documento usam esse mesmo ASCII, idêntico ao que aparece na sua tela.**

Outros três pontos merecem uma segunda olhada:

- As duas últimas linhas `+ 完成` não são repetição. A primeira é a rodada de trabalho; a segunda é a rodada de **veredito** — o veredito roda na própria session, mas **não abre uma nova linha `==`**, porque é uma rodada interna do passo `干活`. No [manifesto da run](../reference/glossary.md#运行清单) o nome dele é `干活·判定#1`.
- O `$` na linha `+ 完成` é o custo **daquela rodada**; `用时` é o tempo total **desde o início da execução até agora** — são duas medidas diferentes.
- As linhas de estado do tipo `- 上下文 … · 累计 … · …` seguem apenas a [thread principal](../reference/glossary.md#主线程); o contexto dos subagents não entra ali. As chamadas de ferramenta dos subagents aparecem por padrão, indentadas atrás de uma barra vertical `|`; o que eles **dizem** só aparece com `-v` — isso é o chão de fábrica, não a decisão.

## Quem roda cada um desses três passos na tela {#三步}

| Passo na tela | Quem roda | O que faz | Congela em | Detalhes |
|---|---|---|---|---|
| `确认需求` | [Clarificador](../reference/glossary.md#确认者) | Só pergunta, não mexe em nada, **pergunta até ficar claro, sem limite de rodadas**; no fim produz um [brief](../reference/glossary.md#需求确认书) de quatro seções | `.flower/notes/需求.md` | [Clarificação prévia](../guide/clarify.md) |
| `设定目标` | [Juiz](../reference/glossary.md#判定者) | Traduz o brief em "objetivo + lista de veredito", em que cada item precisa poder ser verificado na hora | `.flower/notes/目标.md` | [Guarda de objetivo](../guide/goal.md) |
| `干活` | [Coordenador](../reference/glossary.md#协调者) despacha [subagents](../reference/glossary.md#subagent) para trabalhar | O coordenador divide o trabalho e despacha gente, lê os relatórios e decide; ao fim de cada rodada um juiz que **não participou do trabalho** julga de forma independente se "está feito", e se não estiver devolve para continuar | O próprio código | [Guarda de objetivo](../guide/goal.md) |

Os dois primeiros passos são a materialização de dois mecanismos: [clarificação prévia](../reference/glossary.md#前置确认) e [guarda de objetivo](../reference/glossary.md#目标看守); o terceiro é o trecho que os dois governam juntos. Por padrão são no máximo 3 rodadas de veredito (`--rounds`), e `--no-goal` desliga tudo isso — desligado, "ele disse que terminou" passa a valer como terminado de verdade.

O veredito tem só três conclusões: atingido, não atingido e **não dá para verificar neste ambiente**. As duas últimas são conclusões diferentes — "não dá para verificar aqui" nunca é julgado como aprovado; ele para e pergunta para você.

Uma run completa não é barata. Referências medidas: [HT002](../cases/ht002.md) instalou e colocou um projeto existente para rodar no macOS — 4 passos, cerca de 1 hora, **$38.24**; [HT001](../cases/ht001.md) escreveu do zero uma IDE de terminal — **10.4 horas, $171.62**. Se quiser ver primeiro o que ele vai perguntar antes de decidir seguir, use `--clarify-only`.

## Como responder às perguntas {#答提问}

O trecho que começa com `?` é ele te perguntando; há três formas de responder:

- **Digitar o número** (`1` / `2` / `3`) — escolhe aquela opção, e a tela devolve uma linha `+ <选中的那条>`.
- **Digitar texto direto** — resposta livre, não precisa ser uma das opções.
- **Só Enter** — pula e deixa ele decidir sozinho; a tela devolve uma linha `. 已跳过`.

Por padrão ele espera 1800 segundos (`--timeout`). Se ninguém responder, imprime
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` e segue em frente, sem travar.
O número de perguntas é **ilimitado por padrão** (`--asks` vale `-1`); um número positivo vira cota rígida, e ao esgotar imprime `! 提问额度用完`.

## Você pode falar enquanto ele roda {#插话}

Há sempre um prompt digitável na última linha da tela. Não é decoração — ele é apagado antes de cada saída e redesenhado depois, então **não é empurrado para cima pelo log**. São dois textos, alternando conforme haja ou não uma pergunta pendente:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Sem pergunta pendente, você pode fazer duas coisas.

**Digitar uma frase = adicionar requisito.** Ele não é interrompido; só vê na próxima vez que checar a caixa de entrada. O recibo é assim:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

O "已追加进确认书" é importante: essa frase também foi gravada em `需求.md`, então ela sobrevive à fronteira do passo — o próximo passo é uma session nova, que só lê os artefatos congelados; sem gravar em disco, falar é o mesmo que não ter falado.

**Começar com `?` = perguntar de passagem.** Ele abre uma session somente-leitura à parte para te responder, com apenas os últimos 60 eventos e o que estiver na [bancada](../reference/glossary.md#工作台) em mãos. Esse desvio é rodado pelo [oráculo](../reference/glossary.md#旁路顾问), com teto padrão de 12 rodadas / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Descartado assim que responde** — aquela troca não entra no contexto desta run, e o custo não entra no manifesto principal: fica registrado num arquivo próprio sob `runs/aside/`. Então perguntar não afeta a run, e não é preciso se preocupar com aquele valor entrando na conta.

!!! warning "O `？` de largura total não conta; tem que ser o `?` de largura normal"
    O reconhecimento da pergunta de desvio só aceita o `?` de **largura normal** (ASCII `0x3f`). O `？` de largura total, que os IMEs chineses produzem por padrão, não é reconhecido — aquela linha é tratada como "adicionar requisito" e vai para a caixa de entrada, **sem erro nenhum**, só que a resposta que você espera nunca chega.
    É um erro de digitação no código, já anotado na lista de defeitos; até estar corrigido, troque o IME para inglês antes de digitar `?`.

A propósito, sobre Ctrl+C: apertar pela primeira vez durante a run **interrompe esta rodada e abre espaço para você falar**, não sai do programa.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Só o segundo Ctrl+C sai de verdade. (No prompt inicial `要做什么?`, Ctrl-C sai direto e imprime `已取消`.)

## Rodar de novo é continuar de onde parou {#再跑一次}

Digite `flower` outra vez no mesmo diretório e a primeira frase muda:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

A linha `<-` é o banner de [despertar](../reference/glossary.md#唤醒) e reporta o estado atual deste diretório. Ele não vai interrogar os requisitos de novo nem redefinir os objetivos; vale igual se o processo tiver sido morto ou a máquina reiniciada. A frase dita nesse momento é anexada a `需求.md` e **dispara uma rededução da lista de veredito** — sem isso o juiz continuaria lendo a lista antiga, e o que você acabou de acrescentar simplesmente não entraria no veredito. Detalhes e custo (o contexto só cresce) em [continuidade](../guide/continuity.md).

Se não quiser continuar, digite `/new`: os requisitos, os objetivos e a [linhagem](../reference/glossary.md#血缘) do trecho anterior são **movidos** para `notes/archive/<时间戳>/` (não apagados), e tudo recomeça do zero.

## Em scripts, sem supervisão {#脚本}

A demanda também pode ir direto como argumento, e as flags podem vir antes ou depois dela:

```bash
flower "帮我做一个 X"                      # demanda como argumento
flower --rounds 5 "帮我做一个 X"           # flag antes
flower "帮我做一个 X" --rounds 5           # flag depois, equivalente
echo "帮我做一个 X" | flower --timeout 0   # alimenta a entrada padrão por pipe, tudo automático
```

Dar só as flags, sem demanda, também funciona — `flower --clarify-only` primeiro pergunta o que você quer fazer e depois segue.

**Por que o caminho de "digitar depois do Enter" continua existindo.** Aquele par de aspas na linha de comando é puro fardo. Já aconteceu na prática: a aspa de fechamento saiu como o `”` chinês, o zsh ficou esperando a aspa de fechamento de verdade (caiu no prompt de continuação `dquote>`), parecia que o programa tinha travado, mas na verdade ele nunca chegou a iniciar. Rodando `flower` puro, a leitura é da entrada padrão, sem parser de shell: aspas chinesas, espaços, exclamações e quebras de linha podem ser digitados direto. O caminho do pipe usa a mesma entrada — quando a entrada padrão não é um terminal, ele não imprime o cabeçalho do prompt e lê uma linha direto.

!!! danger "Sem supervisão, `--timeout 0` é obrigatório e explícito"
    Em pipe, `nohup` ou CI não há ninguém para responder às perguntas. Sem `--timeout 0`: a primeira pergunta é pulada por "entrada fechada", e **cada pergunta seguinte espera os 1800 segundos inteiros** — algumas perguntas viram horas de giro em falso, e esse tempo está queimando dinheiro.
    `--timeout 0` faz toda pergunta falhar na hora, retornando "ninguém respondeu", e ele segue decidindo sozinho.
    Quando a entrada padrão não é um terminal, o flower imprime antes uma linha de aviso:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Se não rodar {#冒烟}

Se digitar `flower` e nada acontecer, se der erro de credencial, ou se a saída já parecer errada de cara, verifique credenciais e binário separadamente com o disparo mais barato possível. Um único agent, ferramentas somente-leitura, um tiro para ver se as duas pontas se falam:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Este trecho | O que é |
|---|---|
| `once` | Roda uma vez com um único agent: não pergunta requisitos, não define objetivos, não despacha ninguém |
| `-w PATH` | Diretório de trabalho do agent. Sem isso, é o diretório atual |
| `-v` | Antes de começar, imprime a configuração de credenciais em vigor; do token ficam só os 4 primeiros caracteres |

Por padrão o `once` dá só três ferramentas — `Read`, `Glob`, `Grep` — e ele não consegue escrever nada, então esse disparo é bem barato. Referência medida: Opus 5 com janela de 1 milhão via gateway de terceiros, **o piso de uma rodada é $0.1741**; modelos mais baratos ficam abaixo disso. O "verificar se a instalação deu certo" da página [Instalação](install.md) roda exatamente este comando.

Funcionando, o formato é este — os números e o texto vão diferir, **os ícones não**:

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 19 位)
ANTHROPIC_BASE_URL = https://your-gateway.example.com
ANTHROPIC_MODEL = claude-opus-5[1m]
- 验一下凭证…
  ~ 先看目录结构,再挑一两个文件读
  * Glob **/*.py
  * Read README.md
  这是一个用 Rust 写的命令行 HTTP 压测工具。
  - 累计 $0.00 · 0:00
  + 完成 4 轮 · $0.0932 · 用时 0:00
```

Duas coisas a reconhecer:

- As primeiras linhas são a configuração em vigor impressa pelo `-v`. **Conectar no gateway errado se vê de cara** — essa é a principal razão de essa flag existir.
- O `$` da linha `+ 完成` é real; `累计` e `用时` são sempre 0 nesse caminho do `once` (cada evento cria um renderizador novo, então o estado não acumula).

Se esse disparo funcionar, credenciais, gateway, nome do modelo e binário embutido estão todos certos, e o problema está em outro lugar. Se não funcionar, é assunto de instalação: volte para [Instalação](install.md).

## O que ler em seguida {#接下来}

| Se quer saber | Leia |
|---|---|
| O que essas palavras na tela significam de fato | [Conceitos centrais](concepts.md) |
| Todos os subcomandos e flags, sem faltar nenhum | [Referência da linha de comando](../reference/cli.md) |
| Por que ele faz um monte de perguntas antes, e como fazê-lo perguntar menos | [Clarificação prévia](../guide/clarify.md) |
| Quem julga se "está feito", e como escrever a lista de veredito | [Guarda de objetivo](../guide/goal.md) |
| Por que rodar de novo no mesmo diretório continua de onde parou | [Continuidade](../guide/continuity.md) |
| O que ele faz quando o contexto enche (não é compact) | [Handoff](../guide/handoff.md) |
| Credenciais, gateway, nome do modelo, variáveis de ambiente | [Referência de configuração](../reference/config.md) |
| Trocar o terminal, ligar em Web / TUI / totalmente automático | [Camada de interação](../guide/interaction.md) |
| Dispensar os três passos embutidos e escrever seu próprio workflow | [Desenhar workflows](../guide/workflow.md) · [Python API](../reference/api.md) |
| O que de fato acontece numa run long-horizon real | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| A definição exata de algum termo | [Glossário](../reference/glossary.md) |
