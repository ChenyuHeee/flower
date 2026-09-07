# Perguntas frequentes e diagnóstico

Quando algo dá errado, a pessoa não sabe qual módulo quebrou — só sabe o que viu. Por isso esta
página é organizada pelo **sintoma que você observa**, não por subsistema.

Cada entrada tem a mesma estrutura: **sintoma** (o que você realmente vê) → **causa** → **o que fazer**.

Cinco delas são **defeitos conhecidos**, não decisões de projeto. Essas entradas dizem
explicitamente que é um bug, dão o link da issue e a forma de contornar — não são apresentadas
como intencionais.

## Não instala / não roda {#装不上}

O fluxo completo de instalação está em [install.md](../getting-started/install.md#一句话安装). Esta seção
cobre apenas os casos "instalou, mas o comando não roda".

### Versão do Python abaixo de 3.10 {#python-版本}

**Sintoma**: erros de sintaxe durante a instalação, ou o pip dizendo diretamente que não encontra
versão que satisfaça os requisitos.

**Causa**: flower exige Python ≥ 3.10. A única dependência de execução é `claude-agent-sdk`, e o
binário nativo vem dentro do wheel dela — então falha de instalação quase sempre é versão do
interpretador, não rede.

**O que fazer**: primeiro confirme em qual interpretador você está instalando.

```bash
python3 --version
```

Se for menor que 3.10, troque antes de instalar. O `python3` do sistema muitas vezes não é o mesmo
para onde o `python` do seu terminal aponta; conferir a versão antes sai mais barato do que
investigar depois (veja [install.md](../getting-started/install.md#装之前确认-python)).

### Instalou, mas `flower: command not found` {#command-not-found}

**Sintoma**:

```text
zsh: command not found: flower
```

**Causa**: o pacote foi instalado, mas o diretório onde o executável gerado ficou não está no
`PATH`. Isso é diferente de "não instalou" — se `python3 -c "import flower"` não dá erro, o pacote
está íntegro.

**O que fazer**: o shebang do script `flower` é um caminho absoluto, então basta um link simbólico
para um diretório que já esteja no `PATH`; não é preciso dar source em nada.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: segui a dica de PATH do `install.sh` e continua command not found {#macos-path}

!!! warning "Problema conhecido ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Essa recomendação falha justamente na máquina que precisa dela.

**Sintoma**: no macOS, você roda `install.sh`, segue a última mensagem dele e adiciona
`~/.local/bin` ao `PATH`, reabre o terminal, e `flower` continua command not found.

**Causa**: quando o caminho de fallback via pip é usado, o pip do macOS instala o executável em
`~/Library/Python/3.X/bin`, enquanto o `install.sh` manda adicionar `~/.local/bin`. Os dois
diretórios não batem, e seguir a dica não adianta.

??? note "Em que ordem o `install.sh` escolhe o método, e o texto exato da dica"

    A prioridade tem quatro etapas, não duas (`install.sh:35-56`):

    ```text
    1. 有 uv        → uv tool install --force
    2. 否则有 pipx  → pipx install --force
    3. 否则         → curl astral.sh/uv/install.sh 自举 uv,成功则用 uv 装
    4. 自举也失败   → "$PY" -m pip install --user --upgrade    ← 出问题的是这一条
    ```

    O texto exato da dica final de PATH (`install.sh:62-68`, impresso só quando `command -v flower`
    não encontra nada):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` é fixo em `$HOME/.local/bin` (`install.sh:63`). Para os caminhos 1 e 3 isso está certo
    — o uv instala lá mesmo; **só o fallback pip do caminho 4 não bate no macOS**. Ou seja, essa
    armadilha só aparece em máquinas onde os três primeiros caminhos falharam.

**O que fazer**: não adivinhe o diretório, pergunte ao interpretador.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Adicione o diretório impresso ao `PATH`, ou crie um link simbólico dele para `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip não instalam o mesmo flower {#三种装法}

**Sintoma**: `flower` roda, mas mudanças no código-fonte não têm efeito; ou você atualiza e
continua na versão antiga; ou dois terminais na mesma máquina se comportam de forma diferente.

**Causa**: os três métodos colocam pacote e executável em lugares diferentes, e o que roda é o
primeiro que o `PATH` encontrar.

??? note "Onde cada método coloca as coisas"

    | Método | Executável | Quando usar |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Quando você vai mexer no código. Mudanças valem na hora |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Só usar, sem alterar, com um ambiente isolado |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Diretório conforme a entrada anterior |

**O que fazer**: primeiro confirme qual está rodando, depois decida qual alterar.

```bash
which -a flower                      # lista todos os homônimos no PATH
head -1 "$(which flower)"            # o shebang aponta para o interpretador; o pacote está naquele ambiente
```

Para mexer no código, use venv + `-e .`, e não deixe conviver com a instalação de `uv` / `pipx` —
com as duas juntas, o custo de diagnóstico é muito maior que o de reinstalar uma vez
(veja [install.md](../getting-started/install.md#从源码装)).

## Credenciais e gateway {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Sintoma**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Causa**: flower isola a configuração da máquina hospedeira com `setting_sources=[]`, então as
credenciais precisam vir junto. A ordem completa de busca está em
[config.md](config.md#凭证查找优先级).

**O que fazer**: escreva no `.env` da raiz do repositório, ou no ambiente do processo.

```bash
cp .env.example .env        # preencha ANTHROPIC_AUTH_TOKEN ou ANTHROPIC_API_KEY
```

O `.env` já está no gitignore. Para containers, veja [deploy.md](deploy.md#凭证).

### Ele diz "flower não lê `~/.claude/settings.json`" — essa frase está errada {#settings-json}

**Sintoma**: quando as credenciais não estão configuradas, `env.py:192` imprime:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Causa**: essa frase não corresponde ao código. `env.py:56-75` **de fato lê**
`~/.claude/settings.json`, pegando apenas os campos de credencial, como último nível de fallback —
e é exatamente isso que o `install.sh` anuncia. A frase só é impressa depois que o fallback também
veio vazio, então ela não faz nada falhar; mas leva as pessoas a concluir que "flower não consegue
usar o token do meu Claude Code", o que é falso. Registrado em
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**O que fazer**: quem já tem Claude Code instalado na máquina não precisa pedir credenciais novas,
o fallback recolhe sozinho
(veja [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Se você realmente viu essa frase, é porque aquele arquivo também não tem campo de credencial
utilizável — escreva o `.env` como na entrada anterior.

### Não tenho certeza de quais credenciais e endpoint estão valendo {#生效值}

**Sintoma**: você alterou o `.env`, mas as requisições continuam indo para o gateway antigo; ou
você não sabe dizer qual modelo está em uso.

**Causa**: credenciais e endpoint têm várias origens (ambiente do processo, `.env`, fallback), e
quem venceu não se descobre pelo arquivo de configuração, e sim em tempo de execução.

**O que fazer**: suba uma vez com `-v`. Na inicialização ele imprime `describe()`: a `BASE_URL`
efetiva e o mapeamento de modelos, com o token mascarado.

```bash
flower -v
```

Tabela completa de flags em [cli.md](cli.md#全局开关), tabela completa de variáveis em
[config.md](config.md#环境变量).

### Deixei `KEY=` no `.env` e nada mais consegue preencher {#空值占位}

**Sintoma**: você exportou o token no ambiente do processo, o `.env` tem a linha
`ANTHROPIC_AUTH_TOKEN=`, e mesmo assim aparece "credencial ausente".

**Causa**: valor vazio também é uma atribuição. O `KEY=` de uma origem de prioridade mais alta
**ocupa** a chave, e origens de prioridade menor não preenchem mais; já `check_credentials()`
(definida em `env.py:184`) verifica "valor não vazio", então acusa ausência do mesmo jeito.
"Ocupado" e "ausente" são coisas diferentes, mas o sintoma é idêntico — é aí que esse tipo de
problema fica mais difícil de enxergar sozinho.

**O que fazer**: apague a linha inteira, não deixe valor vazio.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # lista todas as linhas com valor vazio
```

Depois de apagar, confirme os valores efetivos com `-v`. Regras de parsing em
[config.md](config.md#env-解析).

### Gateway de terceiros: conecta, mas falha logo na primeira rodada {#网关}

**Sintoma**: 401 / 403; ou erro dizendo que o nome do modelo não existe; ou já faz
[handoff](glossary.md#换代) na largada, reclamando de "piso de inicialização".

**Causa**: três tipos de erro de configuração, com sintomas distintos.

??? note "Três erros de configuração de gateway e como reconhecer cada um"

    | Sintoma | Provavelmente | Onde mexer |
    |---|---|---|
    | 401 / 403 | A credencial é válida, mas não foi emitida por esse gateway; ou a `BASE_URL` está sem o caminho, ou com barra final sobrando | [config.md](config.md#凭证变量) |
    | Nome de modelo inexistente | O gateway só aceita a própria lista de nomes, e o mapeamento não foi configurado | [config.md](config.md#模型变量) |
    | Handoff já na largada, com "piso de inicialização" | Janela configurada pequena demais: o limiar está abaixo do piso de inicialização do papel ([coordenador](glossary.md#协调者) medido em ~34k) | `--window`, veja [handoff.md](../guide/handoff.md#阈值怎么算) |

**O que fazer**: rode `-v` para ver os valores efetivos antes de mexer na configuração. A janela em
especial vale conferir — o gateway da máquina de desenvolvimento está configurado com
`claude-opus-5[1m]`; se você calcular com 200 mil, faz um handoff a cada 150 mil, enquanto na
prática ela chega a 950 mil, **5 vezes de diferença**, e trabalho
[de longo alcance](glossary.md#长程) acaba picotado.

---

## Roda, mas o comportamento está errado {#行为不对}

Os sintomas deste grupo não são erros: **o comando termina, o código de saída é 0, e o que foi
feito está errado**. As quatro primeiras entradas são defeitos de código confirmados, com issue
aberta; o que damos aqui é contorno, não correção. A última é intencional.

### `flower setup` sobe um agent {#setup-跑成了-agent}

**Sintoma**: você executa `flower setup` esperando que ele pergunte endpoint e token, e ele começa
a perguntar "o que você quer fazer", segue todo o fluxo do go e trata a palavra `setup` como a
descrição da tarefa. No fim, nenhuma credencial foi escrita.

**Causa**: o `_CMDS` em `cli.py:758` lista apenas `"go"`, `"run"` e `"once"`, e esqueceu de
`"setup"`. A etapa que completa o subcomando padrão então reescreve o argv `["setup"]` como
`["go", "setup"]` — `setup` deixa de ser subcomando e vira o primeiro argumento posicional do `go`,
ou seja, a própria demanda. **Nenhum argv chega ao assistente de configuração.** Reportado em
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**O que fazer**: mate com Ctrl-C e escreva o arquivo de configuração direto. Tudo o que o `setup`
faria é escrever nesse arquivo:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Os nomes completos das variáveis e a ordem de busca de credenciais estão em
[config.md](config.md#凭证变量).
Depois de escrever, rode `flower -v` em qualquer diretório: o endpoint efetivo impresso na
inicialização é a sua conferência.

### `？` de largura completa não dispara a consulta lateral {#全角问号}

**Sintoma**: seguindo o formato de [consulta lateral](cli.md#旁路问答), você digita no prompt de
entrada `？这个目录能删吗`, e ele não aciona o [oracle](glossary.md#旁路顾问): trata a frase como
resposta à pergunta atual, ou a joga na caixa de entrada tal como está.

**Causa**: `cli.py:733` faz duas verificações `startswith("?")` seguidas, **usando o mesmo
caractere ASCII nas duas**. Pela intenção do código, a segunda deveria testar o `？` de largura
completa. O que o método de entrada chinês produz por padrão é justamente o de largura completa —
ou seja, o principal público desse recurso não consegue usá-lo. Reportado em
[#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Isto contamina a demanda"
    O `？` que não pega não gera erro e não é descartado. Ele é tratado como entrada comum: na
    fase de clarificação, vira resposta à pergunta atual; nas demais, vai para a caixa de entrada.
    **Uma frase que você só queria perguntar em particular acaba escrita no brief.** Se perceber o
    erro, corrija `.flower/notes/需求.md` na hora — é esse arquivo que serve de referência rio abaixo.

**O que fazer**: mude para largura simples e digite `?`, ou digite o `?` simples primeiro e depois
volte para o chinês para escrever o corpo.

### O custo acumulado do `once` é sempre `$0.00` e o tempo sempre `0:00` {#once-计数为零}

**Sintoma**: `flower once` roda do início ao fim e a linha de status no rodapé mostra sempre
`累计 $0.00`, com o cronômetro sempre em `0:00`, enquanto o mesmo modelo com o mesmo trabalho
mostra números no `go`.

**Causa**: o `render()` do `once` **cria um novo `Render` a cada evento recebido**, e os
acumuladores são recriados junto, começando do zero toda vez. O acumulado é zerado repetidamente,
não é falta de contabilização. Reportado em
[#14](https://github.com/ChenyuHeee/flower/issues/14).

**O que fazer**: se você precisa dos números, use `go`, que não é afetado. Se quer a forma de
rodada única do `once` e ainda ver a conta, consulte `runs/manifest.json` depois — o custo de cada
step está lá, e esse registro está correto. Detalhes em [config.md](config.md#run-dir).

### A skill colocada em `plugin/` nunca é carregada {#plugin-不加载}

**Sintoma**: você escreveu a skill conforme [deploy.md](deploy.md#写一个-skill完整例子), a estrutura
de diretórios está certa, mas o agent age como se ela não existisse — **sem erro, sem uma linha de
log**.

**Causa**: `plugin/` não é empacotado no wheel. No pacote instalado, `PLUGIN_DIR` aponta para
`<site-packages>/plugin`, esse diretório não existe, e a verificação de existência antes do
carregamento simplesmente pula em silêncio. **Os três caminhos do `install.sh` caem nisso**; só um
checkout do código-fonte consegue carregar. Reportado em
[#15](https://github.com/ChenyuHeee/flower/issues/15).

**O que fazer**: primeiro verifique para onde o caminho está sendo resolvido.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Se imprimir `False`, é esse caso. Para usar skills, hoje só existe um jeito: **rodar a partir de um
checkout do código-fonte**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

O pacote instalado com `-e` aponta de volta para o diretório do checkout, `PLUGIN_DIR` cai no
`plugin/` real, e a verificação acima passa a imprimir `True`.

### `-T` não faz diferença no `go` {#trim-与-go}

**Sintoma**: você adiciona `-T` ao `flower go`, compara com e sem, e o comportamento é idêntico,
como se a flag estivesse quebrada.

**Causa**: **isto é intencional, não um defeito.** O caminho do `go` já liga o
[trim](glossary.md#裁剪) por padrão; a intenção do `-T` já está satisfeita, então repeti-la não muda
nada. A flag que realmente importa nesse caminho é a inversa, `--no-trim` — só é preciso passá-la
explicitamente para desligar o trim. `-T` só é uma flag com efeito em `run` e `once`.

**O que fazer**: para confirmar que o trim está ligado no `go`, use `-v` e olhe o que é impresso na
inicialização, em vez de julgar pela presença do `-T`; para desligar, passe `--no-trim`. A semântica
completa das flags está em [cli.md](cli.md#全局开关).

## Ele diz que terminou, mas não terminou {#没做完}

O [guarda de objetivo](../guide/goal.md) existe justamente para barrar esse tipo de caso — o worker
tem um viés otimista sistemático: sabe o que fez, não sabe o que deixou passar. Mas o próprio
guarda também erra, e erra de forma previsível. As cinco entradas abaixo se dividem entre "ele
aprovou o que não devia" e "ele nunca aprova".

### Ele diz "não dá para verificar aqui" e passa mesmo assim {#无法达成不是未达成}

**Sintoma**: o veredito diz "não é possível verificar este item no ambiente atual, considerado
atingido", e o workflow segue adiante.

**Causa**: o [judge](glossary.md#判定者) misturou «inatingível» com «não atingido». São **conclusões
diferentes**, e é exatamente disso que trata
[Três conclusões, não duas](../guide/goal.md#三个结论不是两个):
«não atingido» é devolver para continuar trabalhando; «inatingível» é **parar e perguntar a uma
pessoa**, para decidir se aceita, muda o objetivo, ou se o judge errou. Com apenas duas conclusões
("atingido/não atingido"), um objetivo que de fato não é possível faz o coordenador girar em falso
rodada após rodada até esgotar o orçamento.

**O que fazer**: **"não dá para verificar aqui" nunca pode ser tratado como atingido**. Nas
`instructions` do judge, diga explicitamente o que conta como impossível no seu cenário, para que
ele dê «inatingível» quando for o caso. Se você realmente não quer ser interrompido, use
`--timeout 0`: em caso de inatingível ele para direto, com a razão registrada em disco, em vez de
passar batido.

### Ele leu o código-fonte e disse que terminou {#判产出物}

**Sintoma**: a justificativa do veredito diz "o código já implementa X", "a assinatura da função
atende ao requisito", mas nenhum artefato compilado, saída de comando ou serviço em execução foi
tocado.

**Causa**: o judge foi direcionado ao código-fonte.
[O que se julga é o artefato, não o código](../guide/goal.md#判的是产出物不是源码) — se o código
parece correto e se a entrega funciona são duas coisas distintas. A primeira já é algo de que o
worker está convencido; convencer-se de novo não produz informação nova.

**O que fazer**: os itens de veredito devem ser afirmações sobre o **artefato**. "Implementou a
funcionalidade de exportação" não serve; "rodar `./app export out.csv` e `out.csv` ter 3 colunas de
cabeçalho" serve. Já na etapa de escrever o objetivo é assim que deve ser redigido, senão o judge
só pode completar sozinho itens vagos.

### O judge não pode rodar comandos, então leu o Makefile e aprovou {#判定者不能跑命令}

**Sintoma**: o objetivo era "produzir um binário que rode em Linux", o veredito passou. Você mesmo
roda `file` e o artefato é Mach-O, nem de longe um ELF.

**Causa**: o judge por padrão é `judge(can_run=False)`, e tem em mãos **apenas `Read` / `Glob` /
`Grep`**. Essas três ferramentas leem arquivos, mas **não rodam `file` nem `./app --version`**.
Então ele se contenta em ler o Makefile, vê que o ramo Darwin faz compilação cruzada e conclui que
a condição está satisfeita. Ele não mentiu; ele apenas **encontrou o que mais se parecia com
evidência dentro da sua capacidade**.

??? note "Quando é obrigatório ligar `can_run`"
    O critério é simples: **se o objetivo contém palavras do tipo "a coisa construída", ligue.**

    - Artefato: binário, imagem, pacote, dados gerados — ligue
    - Comportamento: o serviço sobe, o comando retorna 0, a saída bate com um padrão — ligue
    - Texto puro: a documentação foi escrita, um campo foi adicionado ao schema — não precisa

    Na linha de comando é `--judge-can-run`. Ligando na mão, cada ponto de entrada tem uma forma
    diferente, mas todos acabam no mesmo parâmetro de `judge()`:

    | Entrada | Como passar | Origem |
    |---|---|---|
    | `judge()` | `can_run=` é parâmetro formal | `roles.py:361` |
    | `with_goal()` | `can_run=` é parâmetro, repassado a `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **não tem parâmetro `can_run`**, mas ele cai em `**spec_kw`, e aquela linha é justamente `judge(..., **spec_kw)` — chega lá | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, convertido em `with_goal(can_run=…)`; é por aqui que passa `--judge-can-run` | `starter.py:105` → `:196` |

    O custo é que o judge realmente executa comandos, e uma rodada de veredito fica mais lenta e
    mais cara; em troca, ele verifica o **local real**, não o manual do local. Veja
    [O judge pode ou não rodar comandos](../guide/goal.md#判定者能不能跑命令).

**O que fazer**: se o objetivo é sobre artefatos, ligue `--judge-can-run`. Quando não ligar, use
"dá para julgar só lendo" como restrição rígida ao escrever os itens de veredito — um item que não
se deixa escrever assim é, por definição, um item que exige rodar comando.

### A lista de veredito tem uma dúzia de itens e nunca passa {#清单长度}

**Sintoma**: toda rodada é devolvida, com uma longa lista do que faltou, que só cresce a cada
correção, e o trabalho nunca termina.

**Causa**: a lista foi escrita segundo "quão rigoroso eu quero ser", não segundo "de quantas formas
esse trabalho pode falhar".
[O tamanho da lista é determinado por quantos modos de falha existem](../guide/goal.md#清单的长度由有多少种失败方式决定):
para uma tarefa como `git clone && make && ./app`, **três a cinco itens bastam** — compila, sobe,
funciona. No desastre real relatado em
[HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了), uma tarefa de "instalar e rodar o
repositório" virou **15 itens**: só 5 verificavam se a coisa funcionava, 6 verificavam se o processo
seguiu as regras, e 4 eram **impossíveis de verificar por princípio**.

**O que fazer**: edite `.flower/notes/目标.md`, que é o arquivo que serve de base ao veredito.
Pergunte item por item "a qual modo de falha isto corresponde"; apague o que não tiver resposta. A
etapa de definir objetivos já reclama de itens não verificáveis — não insista em manter justamente
os que ela apontou.

### Limites foram escritos como itens de veredito {#边界不是判定项}

**Sintoma**: aparecem na lista itens como "não executou `brew install`", "não alterou arquivos fora
do diretório do projeto", e o judge, para se provar inocente, vai checar a mtime de `~/.zshrc` e se
o diretório `.flower/` foi mexido.

**Causa**: limites e itens de veredito restringem coisas diferentes; misturá-los foi a causa
principal do episódio HT002
([causa raiz um](../cases/ht002.md#根因一边界被当成了判定项)).

| | Restringe o quê | Como cumprir |
|---|---|---|
| **Limites** | **Como você trabalha** ("instale só dentro do diretório do projeto", "não toque no código de negócio") | Cumprindo **sem ultrapassar**, não se justificando depois |
| **Itens de veredito** | **O que foi entregue** ("subiu ou não", "o resultado está certo") | Verificando na hora |

Os limites são exatamente a seção que a fase de clarificação estimula a preencher bem. Transportá-los
item a item para a lista significa uma verificação a mais para cada limite, e a maioria dessas
verificações não é possível — itens não verificáveis arrastam a rodada inteira de veredito para a
falha.

**O que fazer**: deixe os limites na seção «limites» do brief, cumpridos por não os ultrapassar,
fora da lista de veredito. Se realmente precisa de uma prestação de contas, resolva em uma frase,
**não desdobre em seis itens**.

---

## Contexto e custo {#上下文与花费}

Em execuções de longo alcance, contexto e dinheiro são o mesmo problema: o contexto sobe até o teto
e ou você faz handoff ou aquele step explode; e cada frase repetida numa rodada é paga de novo em
todas as rodadas seguintes.

### No meio da execução ele abre uma sessão nova e diz "handoff" {#换代打断}

**Sintoma** Aparece `handoff` no fluxo de eventos, com `payload["phase"]` primeiro em `near` e
depois em `done`, gastando uma rodada extra para escrever o
[documento de handoff](glossary.md#交接书), e o trabalho segue normalmente.

**Causa** O contexto se aproximou do limiar. flower **não faz compact** — ele grava o estado da
sessão atual em um documento de handoff de cinco seções e sobe uma sessão nova que o lê e continua.
O [compact](glossary.md#压缩) apagaria junto informações caríssimas como "os caminhos que não deram
certo", enquanto o documento de handoff é explícito, fica em disco e pode ser editado a qualquer
momento: a sessão que assume lê exatamente aquele arquivo.

**O que fazer** Esse é o caminho normal, não precisa fazer nada. Handoff não conta como retentativa
— `attempts` não sobe (ele conta falhas), e o session_id queimado fica registrado em
`StepResult.retired`; o `session_id` exposto é sempre o sucessor ainda vivo
(veja [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Se você realmente quiser voltar ao auto-compact do SDK, use `--no-handoff`.

??? note "De onde vem o limiar, e por que o padrão é tão agressivo"
    `at = window - headroom`. `window` é **1 milhão por padrão**, decidido pelo nome do modelo:
    nomes com `haiku` valem 200 mil, os demais valem 1 milhão. `headroom` é 50k por padrão — o
    auto-compact dispara em −33k, e o handoff precisa chegar antes dele, sendo que "escrever o
    handoff" ainda consome uma rodada; 50k atende às duas coisas.

    Estimar para cima não é erro fatal: se a janela real for menor, o limiar nunca é alcançado, a
    requisição é rejeitada pela API com «prompt longo demais», e flower reconhece esse sinal
    (`handoff.is_overflow()`), fazendo na hora um handoff com um documento degradado montado
    mecanicamente; o step não falha
    (veja [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Vale mencionar a medição real: o gateway da máquina de desenvolvimento está configurado com
    `claude-opus-5[1m]`. Calculando com 200 mil, faria um handoff a cada 150 mil, quando na prática
    ela chega a 950 mil — **5 vezes de diferença**, e o trabalho de longo alcance sai picotado.

### Handoff logo na largada, e não para {#一开局就换代}

**Sintoma** O erro menciona "piso de inicialização", ou o mesmo step faz handoff repetidamente até
bater em `max_generations=8`.

**Causa** A `window` foi configurada pequena demais, e o limiar ficou abaixo do piso de
inicialização daquele papel — o coordenador foi medido em cerca de 34k, só com o system prompt e o
índice da [bancada](glossary.md#工作台). A sessão nova já ultrapassa a linha na primeira fala, então
escreve o handoff, troca de geração, ultrapassa de novo, sem fim (handoff não consome cota de
retentativa, e isso é intencional).

**O que fazer** Ajuste `--window` para a janela real do modelo; `-v` imprime o endpoint e o
mapeamento de modelos efetivos. Uma execução longa normal não chega a 8 gerações; se chegou, é quase
certo que seja isso, e a mensagem de erro diz exatamente isso
(veja [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Outro sintoma relacionado é "o handoff sempre sai degradado": a razão fica em `errors` no
`runs/manifest.json`.

### Para no meio, dizendo que o orçamento estourou {#预算到顶}

**Sintoma** O [step](glossary.md#步骤) para antes de terminar, alegando custo acima do limite.

**Causa** `AgentSpec(max_budget_usd=...)` é um **teto rígido**, não um aviso suave;
`Runtime.total_cost()` é o total daquela execução.

**O que fazer** Antes de subir o teto, confirme que ele não está girando em falso. Rodada após
rodada devolvida sem progresso costuma ser o judge dando «não atingido» quando devia dar
«inatingível» — um objetivo de fato impossível queima até esgotar a cota
(veja [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirme que ele está trabalhando de verdade e só então suba o teto.

### Por que esta execução saiu tão cara {#为什么这么贵}

**Sintoma** O custo passa muito do esperado, mas olhando a saída não dá para ver onde o dinheiro
foi.

**Causa** A contabilidade não está no contexto do modelo. `session_id`, custo, número de
retentativas e razão da falha de cada step ficam registrados apenas em `runs/manifest.json`,
**anexados entre processos**. O histórico de retentativas e o texto original dos erros também só
existem ali — o modelo não os vê, e isso é intencional: acumular chamadas negadas no contexto faz o
coordenador aprender que "Bash vai ser bloqueado de qualquer jeito" e nem tentar um `git status`
(`Runtime(keep_denials=1)` já limpa por padrão, não aumente esse valor).

**O que fazer** Abra `runs/manifest.json` e confira o custo por step (o layout em disco está em
[config.md#磁盘布局](config.md#磁盘布局)). Alguns valores medidos como referência:

| | Custo |
|---|---|
| Piso de inicialização de um subagent (não diluível) | ~4.3k tokens |
| Piso de inicialização do coordenador | ~34k tokens |
| `tests/smoke.py`, cadeia completa com um agent | ~$0.21 |
| `tests/flow_demo.py`, três formas de ligar um workflow | ~$0.39 |
| `tests/delegation.py`, divisão de trabalho + medição da distribuição de contexto | ~$0.71 |
| `tests/isolation.py`, três issues em três worktrees | ~$0.9 |

### O contexto cresce mais rápido que o trabalho {#上下文涨得快}

**Sintoma** Toda [task brief](glossary.md#任务书) repete a mesma disciplina ("leia o arquivo antes de
alterar", "não toque no código de negócio", "rode os testes depois de mudar"), sendo que o
[worker](glossary.md#执行者) já estava fazendo exatamente isso.

**Causa** Cada frase dita pelo coordenador entra no transcript dele, e o transcript só cresce.
Repetir a disciplina custa dinheiro nesta rodada e **volta a custar em todas as rodadas seguintes**.
Repetir o que o outro já sabe tem ganho zero e custo permanente.

**O que fazer** Disciplina vai para o mecanismo, não para a fala de cada rodada: o que puder ser
expresso por `allowed_tools`, pela seção «limites» do brief ou pelo índice da bancada não deve ir
para a task brief; a task brief só escreve o que mudou nesta rodada. A divisão de trabalho em si é
a camada que mais economiza
(veja [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
No resume, resultados grandes de ferramentas antigas podem ser trocados por ponteiros de arquivo
com `-T`.

## Interrupção e continuidade {#中断与接续}

### O processo foi morto, a máquina reiniciou {#进程被杀}

**Sintoma** Sumiu no meio do caminho, e ao reabrir o terminal você não sabe como retomar.

**Causa** Não há o que retomar. A [linhagem](glossary.md#血缘) (`runs/lineage.json`) registra nome do
step → session_id, gravado em disco ao fim de cada step, escrevendo primeiro um `.tmp` e depois
substituindo atomicamente — ser morto no meio não deixa meio arquivo.

**O que fazer** Volte ao **mesmo diretório** e rode `flower` de novo; cada step retoma a sessão
anterior: ele não vai reinterrogar a demanda, não vai redefinir os objetivos, e até lembra quais
becos sem saída o coordenador já tentou. Se não quiser dizer nada, é só dar Enter
(veja [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
O judge é a exceção — ele não é um `Step`, é despachado direto dentro do gate e nunca passa pela
linhagem, então cada rodada tem um par de olhos totalmente novo.

### Sempre começa do zero, não retoma nada {#接不上}

**Sintoma** Rodando de novo no mesmo diretório, ele interroga a demanda outra vez.

**Causa** Três tipos de "não bate", e flower sempre **volta silenciosamente ao começo, sem erro** —
a [continuidade](glossary.md#接续) é um bônus, e a falha dela não deve impedir a pessoa de trabalhar:

- `runs/lineage.json` não existe, ou o `workspace` dentro dele não corresponde ao caminho atual (é o
  que acontece se o diretório foi copiado para outro lugar)
- A sessão não está mais em `runs/sessions.db` (o banco foi apagado)
- O arquivo de linhagem está corrompido

**O que fazer** Verifique se `runs/lineage.json` existe e se o `workspace` está certo
(as responsabilidades dos três arquivos estão em
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Não retomar depois de trocar de diretório é **intencional**: `project_key` é derivado do caminho da
área de trabalho, e a sessão antiga não é encontrada na posição nova.

### Quero recomeçar, mas sem perder o histórico {#想重开}

**Sintoma** A demanda mudou de direção, e você não quer que ele continue falando sobre o assunto
anterior.

**Causa** O comportamento padrão é continuar. Em um diretório já usado, `flower "顺便支持代码块高亮"`
não é uma tarefa nova, é mais uma frase dita.

**O que fazer** `--new`. Ele **arquiva, não apaga**: o material antigo fica em `notes/archive/`.
No [wake](glossary.md#唤醒) ele imprime primeiro uma linha com o tamanho atual do contexto; se achar
grande demais, este é o caminho.

### Caiu a rede, ele não dá erro nem se mexe {#断网}

**Sintoma** Nenhum evento novo na interface, o processo continua vivo, parece travado.

**Causa** Queda de rede é tratada como "espere um pouco", não como falha. flower fica pendurado
esperando: primeiro sonda DNS, depois TCP, e só continua quando passa
(veja [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
No HT001 isso foi validado por uma falha real
(veja [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**O que fazer** Espere; com `-v` dá para ver a sondagem rodando. Os erros acumulados durante a
espera **não entram no contexto após a continuidade** — eles ficam só em `runs/manifest.json`, e a
sessão que assume vê um cenário limpo, sem ser desviada por uma sequência de timeouts.

### Dois Ctrl-C seguidos, e a finalização fica incompleta {#双重-ctrl-c}

**Sintoma** Encerrar com `kill` (SIGTERM) e apertar Ctrl-C duas vezes deixam cenários diferentes.

**Causa** Lacuna conhecida. O duplo Ctrl-C lança `KeyboardInterrupt`: o `finally` de `_drive` em
`cli.py` chama `rt.close()`, mas **não** chama `rt.rescue()` — só os handlers de SIGHUP/SIGTERM
chamam `rescue()`.

**O que fazer** A linhagem se preserva nos dois caminhos (gravação atômica ao fim de cada step),
então rodar de novo retoma normalmente; essa lacuna não faz você perder progresso. Para uma
finalização completa, use `kill <pid>` em vez de martelar o Ctrl-C.

## Paralelismo e isolamento {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Sintoma** Com isolamento ligado ele não sobe, acusando `not in a git repository`.

**Causa** `worker(..., isolate=True)` usa git worktree para dar a cada agent uma cópia privada; se a
workspace não é um repositório git, não dá para criar.

**O que fazer** Este caso **não degrada em silêncio** — ou você roda de fato dentro de um
repositório, ou desliga o `isolate`. O isolamento garante que "vários agents editem ao mesmo tempo
sem enxergar a árvore de trabalho um do outro"; ele não garante que o merge não tenha conflitos.

### O agent isolado não consegue escrever na bancada {#隔离写不进工作台}

**Sintoma** O subagent acusa "permissão de escrita negada", scripts e artefatos não chegam ao disco;
ou os artefatos caem dentro de uma worktree e os outros agents não os veem.

**Causa** A worktree é a **cópia privada** de cada agent, e a bancada é a **camada compartilhada**
entre agents. Coisa compartilhada colocada dentro de uma cerca privada, obviamente, não chega aos
outros.

**O que fazer** Com isolamento ligado, aponte a bancada para **fora do repositório**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Quando ela fica fora da área de trabalho, o `Runtime` autoriza automaticamente via `add_dirs`;
`Runtime(workbench=True)` já cuida disso, mas uma `Workbench` construída à mão precisa ter a
autorização dada por você.

!!! warning "A bancada tem dois padrões de local, e eles são diferentes"
    `Workbench(workspace)` — o caminho usado pela CLI e por `starter_flow()` — coloca a bancada em
    `<workspace>/.flower`; já `Runtime(workbench=True)` (ou seja, `-W`) coloca em
    `<run_dir>/workbench`, isto é, `runs/workbench`. Por isso, rodar `flower` uma vez produz
    `.flower/`, mas chamar `Runtime(workbench=True)` em Python **não**.

### Rodando flower aparece `.flower/`, mas no meu script não {#两个工作台默认值}

**Sintoma** O brief foi escrito em `.flower/notes/需求.md`, mas o coordenador age como se não o
tivesse lido; **sem erro**.

**Causa** Você tem dois objetos de bancada nas mãos. O brief foi escrito no diretório A, e o índice
injetado no system prompt varre o diretório B; a promessa de "já saber onde está o arquivo de
demanda desde a largada" **falha silenciosamente**. As duas formas de errar não dão erro: montar um
`brief_path` na mão relativo ao cwd do processo dá um diretório diferente do `<run_dir>/workbench`
criado pelo `-W`; e tentar obter o caminho de volta a partir do `Runtime` também não funciona —
`cli.py` chama `main()` para construir o `Workflow` primeiro e só depois cria o `Runtime`, quando o
`brief_path` já está fixado.

**O que fazer** Crie você mesmo uma `Workbench` e passe o **mesmo objeto** para o `Workflow` e para
o `Runtime`; assim a posição fica fixa:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` fixa isso: a 5ª asserção verifica que o brief aparece em `prompt_block()`.
Além disso, o índice só é injetado no system prompt do **coordenador**, e o subagent não o herda
(medido em $0.2461, `tests/prelude_live.py`) — o caminho precisa ser repassado pelo coordenador, não
é algo que cada subagent saiba automaticamente
(veja [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
