# Início rápido

Esta página vai de "instalei" até "rodei uma vez de verdade e entendi o que apareceu na tela". Quatro trechos, na ordem:
primeiro um disparo baratíssimo para provar que as credenciais e o binário funcionam, depois um workflow completo sem escrever código,
em seguida aprender a interromper e falar com ele enquanto roda, e por fim colocá-lo num script para rodar sem supervisão.

Só existe um pré-requisito: `flower` instalado, no PATH, com as credenciais configuradas. Se ainda não instalou, veja [Instalação](install.md).

## Passo 1: valide com o disparo mais barato {#冒烟}

Não comece pelo workflow completo. Primeiro dê um disparo com um único agent e ferramentas somente de leitura, para provar que credenciais e binário funcionam nas duas pontas:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Este trecho | O que é |
|---|---|
| `once` | Roda um único agent uma vez: não pergunta requisitos, não define objetivo, não delega |
| `-w PATH` | Diretório de trabalho do agent. Sem isso, é o diretório atual |
| `-v` | Antes de começar, imprime a configuração de credenciais em vigor; do token só ficam os 4 primeiros caracteres |

`once` entrega por padrão apenas três ferramentas — `Read`, `Glob`, `Grep`. Ele não consegue escrever nada, então este disparo é bem barato.
Referência medida: Opus 5 com janela de 1 milhão via gateway de terceiros, **o piso de uma rodada é $0.1741**; modelos mais baratos ficam abaixo disso.

!!! tip "Quem veio da página de instalação pode pular"
    O "verifique se instalou" da página de [Instalação](install.md) roda exatamente este comando. Se já rodou, siga adiante;
    o trecho abaixo só ensina a ler a saída.

Ao terminar, você deve ver esta forma — os números e o texto variam, **os ícones não**:

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

Quatro coisas para reconhecer; os passos seguintes dependem delas:

- As primeiras linhas são a configuração em vigor impressa por `-v`. **Apontar para o gateway errado fica visível de imediato** — essa é a razão principal de esse flag existir.
- `- 验一下凭证…` é uma sonda real de API antes de começar. Se a credencial for rejeitada, ele imprime `! 凭证被拒:…` e pergunta na hora se você quer reconfigurar;
  se não conseguir conectar, imprime `(探针没打通:… —— 当作网络问题,照常开跑)` e **não** manda você reconfigurar um token que estava perfeitamente bom.
- Os ícones são todos ASCII: `~` pensamento, `*` chamada de ferramenta, `>` delegação, `+` sucesso, `x` falha, `?` pergunta, `<-` retomada da vez anterior.
  Não são emojis — emojis e caracteres de moldura disparam fallback de glifo no terminal; na prática travaram o terminal duas vezes. **Todos os exemplos de terminal
  neste documento usam esse conjunto ASCII, igual ao que aparece na sua tela.**
- O `$` na linha `+ 完成` é real; `累计` e `用时` são sempre 0 neste caminho do `once`
  (cada evento cria um renderizador novo, então o estado não acumula).

Se este disparo funcionar, credenciais, gateway, nome do modelo e binário embutido estão todos certos. Se não funcionar, é assunto de instalação: volte para [Instalação](install.md).

## Passo 2: rode um workflow completo sem escrever código {#跑一次}

Não precisa escrever código nenhum e **não precisa digitar aspas no shell**. Entre no diretório do seu projeto e digite:

```bash
cd /path/to/your/project
flower
```

Ele pergunta o que você quer fazer, com o cursor parado no `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Essa linha lê a entrada padrão, **sem passar pelo parsing do shell** — aspas chinesas, espaços e exclamações podem ser digitados direto.

Depois do Enter, ele segue três etapas. Cada linha de traços `==` na tela é uma fronteira de [etapa](../reference/glossary.md#步骤);
o `1/3` à direita é o progresso:

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

Três pontos merecem um olhar mais atento:

- As duas últimas linhas `+ 完成` não são repetição. A primeira é a rodada de trabalho; a segunda é a rodada de **veredito** —
  o veredito roda na própria session, mas **não abre uma nova linha `==`**, porque é uma rodada interna da etapa `干活`.
  No [manifesto de execução](../reference/glossary.md#运行清单) o nome dela é `干活·判定#1`.
- Na linha `+ 完成`, o `$` é o dinheiro **desta rodada**, e `用时` é o tempo total **do início até agora**: são dois critérios diferentes.
- Linhas de estado do tipo `- 上下文 … · 累计 … · …` acompanham só a [thread principal](../reference/glossary.md#主线程);
  o contexto dos subagents não entra ali. As chamadas de ferramenta dos subagents aparecem por padrão, indentadas depois de uma barra `|`;
  o que eles **falam** só aparece com `-v` — aquilo é o chão de fábrica, não a decisão.

### O que são essas três etapas que você viu {#三步}

| Etapa na tela | Quem roda | O que faz | Congela em | Detalhes |
|---|---|---|---|---|
| `确认需求` | [Clarificador](../reference/glossary.md#确认者) | Só pergunta, não mexe em nada, **pergunta até ficar claro, sem limite de rodadas**; no fim produz um [brief](../reference/glossary.md#需求确认书) de quatro seções | `.flower/notes/需求.md` | [Confirmação prévia](../guide/clarify.md) |
| `设定目标` | [Juiz](../reference/glossary.md#判定者) | Traduz o brief em "objetivo + checklist de veredito"; cada item precisa ser verificável na hora | `.flower/notes/目标.md` | [Guarda de objetivo](../guide/goal.md) |
| `干活` | [Coordenador](../reference/glossary.md#协调者) delega a [subagents](../reference/glossary.md#subagent) | O coordenador divide o trabalho, delega, lê relatórios e decide; ao fim de cada rodada, um juiz que **não participou do trabalho** julga de forma independente se "está pronto", e se não atingiu devolve para continuar | o próprio código | [Guarda de objetivo](../guide/goal.md) |

As duas primeiras etapas são a materialização dos mecanismos de [confirmação prévia](../reference/glossary.md#前置确认) e
[guarda de objetivo](../reference/glossary.md#目标看守); a terceira é o trecho que os dois governam juntos. Por padrão, no máximo 3 rodadas de veredito (`--rounds`);
`--no-goal` desliga tudo — desligado, "ele disse que terminou" realmente conta como terminado.

O veredito tem apenas três conclusões: atingido, não atingido e **não verificável neste ambiente**. As duas últimas são conclusões diferentes —
"não dá para verificar aqui" nunca é aprovado; ele para e pergunta a você.

Uma execução completa não é barata. Referência medida: [HT002](../cases/ht002.md) instalou e colocou um projeto existente para rodar no macOS,
4 etapas, cerca de 1 hora, **$38.24**; [HT001](../cases/ht001.md) escreveu um IDE de terminal do zero,
**10.4 horas, $171.62**. Se quiser ver primeiro o que ele vai perguntar antes de decidir se continua, use `--clarify-only`.

### Como responder às perguntas {#答提问}

O trecho que começa com `?` é ele perguntando para você. Três formas de responder:

- **Digitar o número** (`1` / `2` / `3`) — escolhe aquela opção, e a tela responde com uma linha `+ <选中的那条>`.
- **Digitar texto livre** — resposta livre, não precisa ser uma das opções.
- **Só Enter** — pula e deixa ele decidir; a tela responde com uma linha `. 已跳过`.

Por padrão, ele espera 1800 segundos (`--timeout`). Se ninguém responder, imprime
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` e segue adiante, sem travar.
O número de perguntas é **ilimitado por padrão** (`--asks` vale `-1`); um número positivo é cota rígida, e ao esgotar ele imprime `! 提问额度用完`.

### Rodar de novo é continuar de onde parou {#再跑一次}

Digite `flower` outra vez no mesmo diretório e a primeira frase muda:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

A linha `<-` é o banner de [wake](../reference/glossary.md#唤醒) e informa o estado atual deste diretório.
Ele não vai interrogar os requisitos de novo, nem redefinir o objetivo; vale igual se o processo foi morto ou a máquina reiniciou.
A frase que você digitar aqui é anexada ao `需求.md` e **dispara a re-derivação do checklist de veredito** —
sem re-derivar, o juiz continuaria lendo o checklist antigo, e o que você acabou de acrescentar nem entraria no veredito.
Detalhes e custo (o contexto só cresce) em [Continuidade](../guide/continuity.md).

Se não quiser continuar, digite `/new`: os requisitos, o objetivo e a [linhagem](../reference/glossary.md#血缘) do trecho anterior
são **movidos** para `notes/archive/<时间戳>/` (não são apagados) e tudo começa do zero.

## Passo 3: depois que ele começa a rodar, você ainda pode falar {#插话}

Na parte de baixo da tela há sempre uma linha de prompt onde você pode digitar. Não é enfeite — antes de cada saída ela é apagada, depois é redesenhada,
então ela **não é empurrada para cima pelo log**. Há dois textos, alternados conforme "existe ou não pergunta pendente":

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Quando não há pergunta pendente, você pode fazer duas coisas.

**Digitar uma frase = adicionar requisito.** Ele não é interrompido; só vê na próxima vez que checar a caixa de entrada. O recibo é assim:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

O "已追加进确认书" é importante: essa frase também foi gravada em disco no `需求.md`, e por isso sobrevive à fronteira de etapa —
a etapa seguinte é uma session nova, que lê apenas os artefatos congelados; sem gravar em disco, dizer é o mesmo que não dizer.

**Começar com `?` = perguntar de passagem.** Ele abre uma session somente de leitura para responder, com apenas os 60 eventos mais recentes e o que está na
[workbench](../reference/glossary.md#工作台) em mãos. Esse desvio é rodado pelo
[oráculo](../reference/glossary.md#旁路顾问), com teto padrão de 12 rodadas / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Descartado logo após responder** — aquela pergunta e resposta não entram no contexto desta execução, e o custo não entra no manifesto principal:
fica registrado num arquivo próprio dentro de `runs/aside/`. Ou seja, perguntar não afeta a execução, e você não precisa se preocupar com esse dinheiro na conta.

!!! warning "O `？` de largura total não conta; tem de ser o `?` ASCII"
    O reconhecimento de pergunta em desvio aceita apenas o `?` **de meia largura** (ASCII `0x3f`). O `？` de largura total, que o IME chinês produz por padrão, não é reconhecido —
    aquela linha é tratada como "adicionar requisito" e vai para a caixa de entrada, **sem erro nenhum**; só a resposta que você espera nunca chega.
    É um deslize no código, já registrado na lista de defeitos; até que seja corrigido, mude o IME para inglês antes de digitar `?`.

Aproveitando, sobre Ctrl+C: durante a execução, o primeiro toque **interrompe esta rodada e deixa você falar**, não sai do programa.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Só o segundo toque sai de verdade. (No prompt inicial `要做什么?`, Ctrl-C sai direto e imprime `已取消`.)

## Passo 4: coloque num script {#脚本}

O pedido também pode ser passado direto como argumento, e os flags podem vir antes ou depois dele:

```bash
flower "帮我做一个 X"                      # pedido como argumento
flower --rounds 5 "帮我做一个 X"           # flag antes
flower "帮我做一个 X" --rounds 5           # flag depois, equivalente
echo "帮我做一个 X" | flower --timeout 0   # pipe na entrada padrão, totalmente automático
```

Passar só os flags, sem pedido, também funciona — `flower --clarify-only` pergunta primeiro o que você quer fazer e depois segue.

**Por que o caminho "digitar depois do Enter" continua existindo.** Aquele par de aspas na linha de comando é puro ônus. Já tropeçamos nisso na prática:
a aspa de fechamento saiu como o `”` chinês, o zsh ficou esperando a aspa de fechamento de verdade (caiu no prompt de continuação `dquote>`),
parecia que o programa tinha travado, mas ele nunca sequer iniciou. Rodando `flower` puro, ele lê a entrada padrão, sem parsing do shell,
e aspas chinesas, espaços, exclamações e quebras de linha podem ser digitados direto. O caminho do pipe usa a mesma entrada —
quando a entrada padrão não é um terminal, ele não imprime o cabeçalho do prompt e lê uma linha direto.

!!! danger "Execução sem supervisão exige `--timeout 0` explícito"
    Em pipe, `nohup` ou CI não há ninguém para responder às perguntas. Sem `--timeout 0`: a primeira pergunta é pulada porque
    "a entrada está fechada", e **cada pergunta seguinte fica esperando os 1800 segundos completos** — algumas perguntas significam horas de espera à toa,
    e nesse tempo você está queimando dinheiro.
    `--timeout 0` faz toda pergunta falhar imediatamente e retornar "ninguém respondeu"; ele decide sozinho e segue adiante.
    Quando a entrada padrão não é um terminal, o flower imprime primeiro uma linha de aviso:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## O que ler depois {#接下来}

| Se você quer saber | Leia |
|---|---|
| O que essas palavras na tela significam de fato | [Conceitos centrais](concepts.md) |
| Todos os subcomandos e flags, sem faltar nenhum | [Referência da linha de comando](../reference/cli.md) |
| Por que ele faz um monte de perguntas primeiro e como reduzir isso | [Confirmação prévia](../guide/clarify.md) |
| Quem julga se "está pronto" e como escrever o checklist de veredito | [Guarda de objetivo](../guide/goal.md) |
| Por que rodar de novo no mesmo diretório continua de onde parou | [Continuidade](../guide/continuity.md) |
| O que ele faz quando o contexto enche (não é compact) | [Handoff](../guide/handoff.md) |
| Credenciais, gateway, nome do modelo, variáveis de ambiente | [Referência de configuração](../reference/config.md) |
| Trocar o terminal, plugar Web / TUI / modo totalmente automático | [Camada de interação](../guide/interaction.md) |
| Não usar as três etapas embutidas e escrever seu próprio workflow | [Desenhar workflows](../guide/workflow.md) · [Python API](../reference/api.md) |
| O que realmente aconteceu numa execução longa real | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| A definição exata de algum termo | [Glossário](../reference/glossary.md) |
