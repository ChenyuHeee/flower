# Perguntas frequentes e diagnóstico

Quando algo quebra, a pessoa não sabe qual módulo quebrou — só sabe o que viu. Por isso esta página
é organizada pelo **sintoma que você observou**, não por subsistema.

Toda entrada tem a mesma estrutura: **sintoma** (o que você realmente vê) → **causa** → **o que fazer**.

Cinco delas são **defeitos conhecidos**, não decisões de projeto. Essas entradas dizem explicitamente
que são bugs, dão o link da issue e a forma de contornar — não vão fingir que aquilo é intencional.

## Não instala / não roda {#装不上}

O fluxo completo de instalação está em [install.md](../getting-started/install.md#一句话安装). Esta seção
cobre só os casos de "instalou, mas o comando não roda".

### Versão do Python abaixo de 3.10 {#python-版本}

**Sintoma**: erro de sintaxe durante a instalação, ou o pip dizendo direto que não encontra versão que
satisfaça a condição.

**Causa**: o flower exige Python ≥ 3.10. A única dependência de execução é `claude-agent-sdk`, e o
binário nativo vem dentro da wheel dela — então falha de instalação quase sempre é versão do
interpretador, não rede.

**O que fazer**: primeiro confirme em qual interpretador você está instalando.

```bash
python3 --version
```

Abaixo de 3.10, troque antes de instalar. O `python3` do sistema muitas vezes não é o mesmo para o
qual o `python` do seu terminal aponta; conferir a versão antes de instalar sai mais barato do que
investigar depois (ver [install.md](../getting-started/install.md#装之前确认-python)).

### Instalou, e mesmo assim `flower: command not found` {#command-not-found}

**Sintoma**:

```text
zsh: command not found: flower
```

**Causa**: o pacote foi instalado, mas o diretório onde o executável gerado ficou não está no `PATH`.
Isso é diferente de "não instalou" — se `python3 -c "import flower"` não dá erro, o pacote está bom.

**O que fazer**: o shebang do script `flower` é um caminho absoluto, então basta um symlink para um
diretório que já esteja no `PATH`; não é preciso dar source em nada.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: adicionei o PATH conforme o `install.sh` mandou e continua command not found {#macos-path}

!!! warning "Problema conhecido ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Essa recomendação falha exatamente na máquina que precisa dela.

**Sintoma**: no macOS, você roda o `install.sh`, segue a última mensagem dele e adiciona `~/.local/bin`
ao `PATH`, reabre o terminal, e `flower` continua command not found.

**Causa**: quando o caminho percorrido é o fallback do pip, o pip do macOS instala o executável em
`~/Library/Python/3.X/bin`, enquanto o `install.sh` manda adicionar `~/.local/bin`. Os dois diretórios
não batem, e seguir a instrução não adianta.

??? note "Em que ordem o `install.sh` escolhe o método, e o texto exato daquela mensagem"

    A prioridade tem quatro etapas, não duas (`install.sh:35-56`):

    ```text
    1. tem uv          → uv tool install --force
    2. senão tem pipx  → pipx install --force
    3. senão           → curl astral.sh/uv/install.sh para bootstrap do uv; se der certo, instala com uv
    4. bootstrap falhou → "$PY" -m pip install --user --upgrade    ← o problema está nesta
    ```

    O texto exato daquela mensagem sobre o PATH (`install.sh:62-68`, impressa só quando
    `command -v flower` não encontra nada):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` está fixo em `$HOME/.local/bin` (`install.sh:63`). Para os caminhos 1 e 3 isso está certo
    — é lá que o uv instala; **só o fallback do pip, no caminho 4, não bate no macOS**. Por isso essa
    armadilha só aparece em máquinas onde nenhum dos três primeiros caminhos deu certo.

**O que fazer**: não adivinhe o diretório, pergunte ao interpretador.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Adicione o diretório impresso ao `PATH`, ou crie um symlink dele para `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip instalaram flowers diferentes {#三种装法}

**Sintoma**: `flower` roda, mas mexer no código-fonte não surte efeito; ou você atualiza e continua na
versão antiga; ou dois terminais na mesma máquina se comportam de forma diferente.

**Causa**: os três métodos colocam o pacote e o executável em lugares diferentes, e roda o primeiro que
o `PATH` encontrar.

??? note "Onde cada um dos três métodos cai"

    | Método | Executável | Quando usar |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Quando você vai mexer no código. Vale na hora |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Só usar, sem mexer, com ambiente isolado |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Diretório: ver entrada anterior |

**O que fazer**: primeiro confirme qual está rodando, depois decida qual editar.

```bash
which -a flower                      # lista todos os homônimos no PATH
head -1 "$(which flower)"            # o shebang aponta o interpretador; o pacote está naquele ambiente
```

Para mexer no código use venv + `-e .`, e não deixe conviver com a instalação por `uv` / `pipx` — com
as duas juntas, o custo de investigar é muito maior que reinstalar uma vez
(ver [install.md](../getting-started/install.md#从源码装)).

## Credenciais e gateway {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Sintoma**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Causa**: o flower isola a configuração da máquina hospedeira com `setting_sources=[]`; a credencial
precisa vir com você. A ordem completa de busca está em
[config.md](config.md#凭证查找优先级).

**O que fazer**: escreva no `.env` na raiz do repositório, ou no ambiente do processo.

```bash
cp .env.example .env        # preencha ANTHROPIC_AUTH_TOKEN ou ANTHROPIC_API_KEY
```

O `.env` já está no gitignore. Para containers, ver [deploy.md](deploy.md#凭证).

### Ele diz "o flower não lê `~/.claude/settings.json`" — essa frase está errada {#settings-json}

**Sintoma**: quando a credencial não está configurada, `env.py:192` imprime:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Causa**: essa frase não corresponde ao código. `env.py:56-75` **de fato lê** `~/.claude/settings.json`,
pegando só os campos de credencial, como último fallback — e é exatamente isso que o `install.sh`
anuncia. A frase só é impressa depois que o fallback já veio vazio, então ela não faz nada falhar; mas
leva a pessoa à conclusão de que "o flower não consegue usar o token do meu Claude Code", e isso é
falso. Registrado em [issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**O que fazer**: se você já tem o Claude Code instalado na máquina, não precisa pedir credencial nova —
o fallback pega sozinho
(ver [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Se você realmente viu essa frase, é porque naquele arquivo também não há campo de credencial usável —
escreva o `.env` conforme a entrada anterior.

### Não sei quais credenciais e endpoint estão realmente valendo {#生效值}

**Sintoma**: você mudou o `.env` e as requisições continuam indo para o gateway antigo; ou você não
sabe dizer qual modelo está em uso.

**Causa**: credencial e endpoint têm várias origens (ambiente do processo, `.env`, fallback), e quem
ganhou não se descobre no arquivo de configuração, se descobre em tempo de execução.

**O que fazer**: suba uma vez com `-v`. Na inicialização ele imprime o `describe()`: a `BASE_URL` em
vigor e o mapeamento de modelos, com o token mascarado.

```bash
flower -v
```

A tabela completa de flags está em [cli.md](cli.md#全局开关); a de variáveis, em
[config.md](config.md#环境变量).

### Deixei `KEY=` no `.env` e agora nada mais consegue preencher {#空值占位}

**Sintoma**: você exportou o token no ambiente do processo, o `.env` também tem a linha
`ANTHROPIC_AUTH_TOKEN=`, e ainda assim dá "credencial ausente".

**Causa**: valor vazio também é uma atribuição. O `KEY=` da origem de prioridade mais alta **ocupa** a
chave, e as origens de prioridade menor não preenchem mais nada; e `check_credentials()` (definida em
`env.py:184`) verifica "valor não vazio", então reporta ausência do mesmo jeito. "Ocupado" e "ausente"
são duas coisas diferentes, mas o sintoma é idêntico — é o que torna esse tipo de problema o mais
difícil de enxergar sozinho.

**O que fazer**: apague a linha inteira, não deixe valor vazio.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # lista todas as linhas com valor vazio
```

Depois de apagar, confirme os valores em vigor com `-v`. As regras de parsing estão em
[config.md](config.md#env-解析).

### Gateway de terceiros: conecta, mas falha logo na primeira rodada {#网关}

**Sintoma**: 401 / 403; ou erro de nome de modelo inexistente; ou [handoff](glossary.md#换代) logo de
saída, com aviso de "piso de inicialização".

**Causa**: três tipos de configuração errada, com sintomas distintos.

??? note "Três erros de configuração de gateway e como identificar cada um"

    | Sintoma | Provavelmente é | Onde mexer |
    |---|---|---|
    | 401 / 403 | A credencial é válida, mas não foi emitida por este gateway; ou a `BASE_URL` está sem o caminho, ou com barra sobrando no fim | [config.md](config.md#凭证变量) |
    | Nome de modelo inexistente | O gateway só aceita o conjunto próprio de nomes de modelo, e o mapeamento não foi configurado | [config.md](config.md#模型变量) |
    | Handoff logo de saída, com "piso de inicialização" | A janela ficou pequena demais: o limiar está abaixo do piso de inicialização do papel (o [coordinator](glossary.md#协调者) mediu cerca de 34k) | `--window`, ver [handoff.md](../guide/handoff.md#阈值怎么算) |

**O que fazer**: rode `-v` para ver os valores em vigor antes de mexer na configuração. A janela é o
item que mais vale conferir — o gateway da máquina de desenvolvimento está configurado com
`claude-opus-5[1m]`; se você calculasse por 200k, trocaria de geração a cada 150k, quando na verdade
ela aguenta 950k, **5 vezes de diferença**, e trabalho [long-horizon](glossary.md#长程) acaba picotado.

---

## Roda, mas o comportamento está errado {#行为不对}

Os sintomas deste grupo não são erros: **o comando termina, o código de saída é 0, e mesmo assim ele
faz a coisa errada**. As quatro primeiras entradas são defeitos de código confirmados, com issue
aberta; o que está aqui é a forma de contornar, não a correção. A última é decisão de projeto.

### `flower setup` sobe um agent {#setup-跑成了-agent}

**Sintoma**: você executa `flower setup` esperando que ele pergunte o endpoint e o token, e ele começa
a perguntar "o que você quer fazer", segue o fluxo completo do go e trata a palavra `setup` como
descrição da tarefa. No fim, nenhuma credencial foi escrita.

**Causa**: o `_CMDS` em `cli.py:937` só lista `"go"`, `"run"` e `"once"`, e esqueceu `"setup"`. O passo
que completa o subcomando padrão então reescreve o argv `["setup"]` como `["go", "setup"]` — `setup`
é rebaixado de subcomando para primeiro argumento posicional do `go`, ou seja, a própria demanda.
**Nenhum argv leva ao assistente de configuração.** Reportado em
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**O que fazer**: mate com Ctrl-C e escreva o arquivo de configuração direto. O que o `setup` faria era
apenas escrever nesse arquivo:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Os nomes completos das variáveis e a ordem de busca das credenciais estão em
[config.md](config.md#凭证变量).
Depois de escrever, rode `flower -v` em qualquer diretório: o endpoint em vigor impresso na
inicialização é a conferência.

### `？` de largura total não dispara a pergunta ao oracle {#全角问号}

**Sintoma**: você segue a forma descrita em [pergunta ao oracle](cli.md#旁路问答) e digita
`？这个目录能删吗` no prompt de entrada, e ele não sobe o [oracle](glossary.md#旁路顾问) — trata a
frase como resposta à pergunta atual, ou joga tal e qual na caixa de entrada.

**Causa**: `cli.py:907` faz duas verificações `startswith("?")` seguidas, **as duas com o mesmo
caractere ASCII**. Pela intenção do código, a segunda deveria testar o `？` de largura total. O IME
chinês, por padrão, produz justamente o de largura total — ou seja, exatamente o público principal do
recurso não consegue usá-lo. Reportado em [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Isso contamina a demanda"
    O `？` que não pega não dá erro nem é descartado. Ele é tratado como entrada comum:
    na fase de clarify vira resposta à pergunta atual; nas demais, vai para a caixa de entrada.
    **Uma frase que você só queria perguntar em particular acaba escrita no brief.** Se notar o erro,
    corrija na hora o `.flower/notes/需求.md`, porque é esse arquivo que serve de referência rio abaixo.

**O que fazer**: mude para meia largura e digite `?`, ou digite `?` em meia largura primeiro e volte
para o chinês para escrever o corpo.

### No `once`, o custo acumulado é sempre `$0.00` e o tempo sempre `0:00` {#once-计数为零}

**Sintoma**: `flower once` roda do início ao fim, a linha de status do rodapé mostra
`累计 $0.00` o tempo todo, o cronômetro fica em `0:00`, enquanto o mesmo modelo com o mesmo trabalho
contabiliza normalmente no `go`.

**Causa**: o `render()` do `once` **cria um novo `Render` a cada evento recebido**, e os acumuladores
são recriados junto, começando do zero toda vez. Os totais estão sendo zerados repetidamente, não é
que não sejam contados. Reportado em [#14](https://github.com/ChenyuHeee/flower/issues/14).

**O que fazer**: se você quer números corretos, use o `go`, que não é afetado. Se você quer a forma de
rodada única do `once` e ainda ver a conta, consulte `runs/manifest.json` depois — o custo de cada step
está registrado lá, e esse registro está certo. Detalhes em [config.md](config.md#run-dir).

### A skill colocada em `plugin/` nunca é carregada {#plugin-不加载}

**Sintoma**: você escreveu a skill conforme [deploy.md](deploy.md#写一个-skill完整例子), a estrutura de
diretórios está correta, mas o agent age como se nem soubesse que ela existe — **sem erro e sem uma
linha de log**.

**Causa**: `plugin/` não é empacotado na wheel. No pacote instalado, `PLUGIN_DIR` aponta para
`<site-packages>/plugin`, que não existe, e a verificação de existência antes do carregamento pula em
silêncio. **Os três caminhos do `install.sh` caem nisso**; só um repositório com checkout do
código-fonte carrega. Reportado em [#15](https://github.com/ChenyuHeee/flower/issues/15).

**O que fazer**: primeiro verifique para onde o caminho está sendo resolvido.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Se imprimir `False`, é este caso. Para usar skills hoje só há um jeito: **rodar a partir de um checkout
do código-fonte**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Um pacote instalado com `-e` aponta de volta para o diretório do checkout, `PLUGIN_DIR` cai no
`plugin/` de verdade, e a verificação acima passa a imprimir `True`.

### `-T` não faz diferença no `go` {#trim-与-go}

**Sintoma**: você adiciona `-T` ao `flower go`, compara com e sem, e o comportamento é idêntico, como
se a flag estivesse quebrada.

**Causa**: **isto é decisão de projeto, não defeito.** O caminho do `go` já liga o
[trim](glossary.md#裁剪) por padrão; a intenção expressa por `-T` já está atendida, então dá-la de novo
não muda nada. A flag que realmente existe nesse caminho é a inversa, `--no-trim` — só é preciso passar
explicitamente para desligar o trim. `-T` só é uma flag significativa no `run` e no `once`.

**O que fazer**: para confirmar no `go` que o trim está ligado, use `-v` e veja o que é impresso na
inicialização, em vez de julgar pela presença de `-T`; para desligar, passe `--no-trim`. A semântica
completa das flags está em [cli.md](cli.md#全局开关).

## Ele diz que terminou, mas não terminou {#没做完}

O [goal guard](../guide/goal.md) existe justamente para barrar esta categoria — o worker tem um viés
otimista sistemático: ele sabe o que fez, não sabe o que deixou de fazer. Mas o próprio guard também
erra, e erra numa direção com padrão. As cinco entradas abaixo estão separadas entre "ele liberou o que
não devia" e "ele nunca libera".

### Ele diz "não dá para verificar aqui" e passa {#无法达成不是未达成}

**Sintoma**: o veredicto diz "o ambiente atual não permite verificar este item, considera-se atingido",
e o workflow segue em frente.

**Causa**: o [judge](glossary.md#判定者) misturou «inatingível» e «não atingido» numa conclusão só.
São **conclusões diferentes**, e é disso que trata
[três conclusões, não duas](../guide/goal.md#三个结论不是两个):
«não atingido» é devolver para continuar trabalhando; «inatingível» é **parar e perguntar a uma
pessoa**, que escolhe aceitar, mudar o objetivo, ou dizer que o judge errou. Com apenas duas conclusões
("atingido/não atingido"), um objetivo que de fato não dá para cumprir faz o coordinator girar em falso
rodada após rodada até estourar o orçamento.

**O que fazer**: **"não dá para verificar aqui" nunca pode virar atingido**. Nas `instructions` do
judge, diga com todas as letras o que conta como impossível no seu cenário, para que ele dê
«inatingível» quando for o caso. Se você realmente não quer ser interrompido com perguntas, use
`--timeout 0`: em caso de inatingível ele para direto, e o motivo fica registrado em disco, em vez de
passar batido.

### Ele leu o código-fonte e disse que estava pronto {#判产出物}

**Sintoma**: a justificativa do veredicto diz "X já está implementado no código", "a assinatura da
função atende ao requisito", mas nem o artefato compilado, nem a saída do comando, nem o serviço no ar
foram tocados.

**Causa**: o judge foi conduzido ao código-fonte. [O que se julga é o artefato, não o
código-fonte](../guide/goal.md#判的是产出物不是源码) — se o código parece certo e se o que foi entregue
funciona são duas coisas distintas. A primeira é aquilo de que o worker já está convencido, e
convencer-se de novo não produz informação nova.

**O que fazer**: os itens do veredicto devem ser escritos como afirmações sobre o **artefato**.
"Implementou a exportação" não vale; "rodar `./app export out.csv` e `out.csv` ter 3 colunas de
cabeçalho" vale. Isso já deve ser escrito assim na etapa de definição do objetivo, senão o judge só
pode completar por conta própria itens vagos.

### O judge não pode rodar comandos, então leu o Makefile e liberou {#判定者不能跑命令}

**Sintoma**: o objetivo é "produzir um binário que roda no Linux", o veredicto passou. Você mesmo roda
`file` e o artefato é Mach-O, não é ELF de jeito nenhum.

**Causa**: por padrão o judge é `judge(can_run=False)`, e tem **apenas `Read` / `Glob` / `Grep`** na
mão. Essas três ferramentas leem arquivos, mas **não rodam `file` nem `./app --version`**. Então ele
apela para ler o Makefile, vê no ramo de Darwin uma compilação cruzada e conclui que a condição está
satisfeita. Ele não mentiu; ele apenas **achou a coisa mais parecida com evidência dentro da sua
capacidade**.

??? note "Quando é obrigatório ligar `can_run`"
    O critério é simples: **se o objetivo contém palavras do tipo "a coisa construída", tem que ligar.**

    - Artefato: binário, imagem, pacote, dados gerados — ligar
    - Comportamento: o serviço sobe, o comando retorna 0, a saída bate com um padrão — ligar
    - Texto puro: se a documentação foi escrita, se um campo foi adicionado ao schema — não precisa

    Na linha de comando é `--judge-can-run`. Ligando na mão, cada ponto de entrada tem uma forma
    diferente, mas no fim todas caem no mesmo parâmetro de `judge()`:

    | Entrada | Como passar | Origem |
    |---|---|---|
    | `judge()` | `can_run=` é parâmetro de verdade | `roles.py:361` |
    | `with_goal()` | `can_run=` é parâmetro, encaminhado para `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **não tem parâmetro `can_run`**, mas ele cai em `**spec_kw`, e essa linha é justamente `judge(..., **spec_kw)` — chega lá | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, convertido em `with_goal(can_run=…)`; é por aqui que passa `--judge-can-run` | `starter.py:105` → `:196` |

    O preço é que o judge realmente executa comandos, e cada rodada de veredicto fica mais lenta e mais
    cara; em troca, ele verifica o **cenário real**, não o manual do cenário. Ver
    [o judge pode ou não rodar comandos](../guide/goal.md#判定者能不能跑命令).

**O que fazer**: se o objetivo é sobre artefato, ligue `--judge-can-run`. Quando não ligar, use "dá
para julgar só lendo" como restrição rígida ao escrever os itens do veredicto — um item que não cabe
nessa forma é justamente um item que precisa de comando.

### A checklist do veredicto tem mais de dez itens e nunca passa {#清单长度}

**Sintoma**: toda rodada é devolvida, com uma lista comprida do que falta, e quanto mais se corrige
mais aparece; o trabalho não termina.

**Causa**: a checklist foi escrita por "quão rigoroso eu quero ser", não por "de quantos jeitos este
trabalho pode falhar". [O tamanho da checklist é determinado por quantos modos de falha
existem](../guide/goal.md#清单的长度由有多少种失败方式决定):
para uma tarefa como `git clone && make && ./app`, **três a cinco itens bastam** — build passou, sobe,
dá para usar. No desastre real registrado em
[HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了), uma tarefa de "instalar o repositório
e colocar para rodar" foi escrita com **15 itens**: só 5 verificavam se a coisa funcionava, 6
verificavam se o processo seguiu as regras, e outros 4 **eram inverificáveis por princípio**.

**O que fazer**: edite `.flower/notes/目标.md`, porque é esse arquivo que serve de base ao veredicto.
Pergunte item por item "a qual modo de falha isto corresponde" e apague os que você não souber
responder. A etapa de definição do objetivo já reclama de itens inverificáveis; não insista em manter
os que ela apontou.

### Limites foram escritos como itens do veredicto {#边界不是判定项}

**Sintoma**: aparecem na checklist itens como "não rodou `brew install`", "não alterou arquivos fora do
diretório do projeto", e o judge, para provar inocência, vai checar o mtime de `~/.zshrc` e se o
diretório `.flower/` foi mexido.

**Causa**: limites e itens de veredicto restringem coisas diferentes; misturá-los foi a causa principal
daquele episódio do HT002 ([causa raiz um](../cases/ht002.md#根因一边界被当成了判定项)).

| | O que restringe | Como cumprir |
|---|---|---|
| **Limites** | **Como você trabalha** ("só instalar dentro do diretório do projeto", "não mexer no código de negócio") | **Não ultrapassando**, não provando depois |
| **Itens do veredicto** | **O que foi entregue** ("subiu ou não", "o resultado está certo") | Verificando na hora |

Os limites são justamente a parte que a fase de clarify incentiva a preencher bastante. Transportá-los
item por item para a checklist significa que cada limite a mais vira uma checagem a mais — e a maioria
dessas checagens é inverificável, e um item inverificável arrasta a rodada inteira de veredicto para a
falha.

**O que fazer**: deixe os limites na seção «limites» do brief, cumpridos por não ultrapassá-los, fora
da checklist do veredicto. Se realmente for preciso prestar contas, resolva numa frase; **não desdobre
em seis itens**.

---

## Contexto e custo {#上下文与花费}

Numa execução long-horizon, contexto e dinheiro são o mesmo problema: quando o contexto encosta no
teto, ou há handoff ou aquele step estoura; e cada frase repetida numa rodada é paga de novo em todas
as rodadas seguintes.

### No meio da execução ele abriu uma sessão nova, dizendo "handoff" {#换代打断}

**Sintoma** Aparece `handoff` no fluxo de eventos, com `payload["phase"]` primeiro `near` e depois
`done`, mais uma rodada gasta no meio escrevendo o [handoff document](glossary.md#交接书), e depois o
trabalho segue normalmente.

**Causa** O contexto se aproximou do limiar. O flower **não faz compact** — ele escreve o estado da
sessão atual em um handoff document de cinco seções e sobe uma sessão nova que lê esse documento e
continua. O [compact](glossary.md#压缩) apagaria junto a informação mais cara, como "os caminhos que não
funcionam", enquanto o handoff document é explícito, está em disco e pode ser editado a qualquer
momento: é justamente esse arquivo que a sessão sucessora lê.

**O que fazer** Este é o caminho normal, não precisa fazer nada. Handoff não conta como retry — o
`attempts` não sobe (ele conta falhas), e o session_id queimado fica registrado em
`StepResult.retired`, enquanto o `session_id` exposto é sempre o sucessor ainda vivo
(ver [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Se você realmente quiser voltar ao auto-compact do SDK, use `--no-handoff`.

??? note "De onde vem o limiar, e por que o padrão é tão agressivo"
    `at = window - headroom`. O `window` tem **padrão de 1M**, decidido pelo nome do modelo: nome com
    `haiku` conta como 200k, o resto conta como 1M. O `headroom` tem padrão de 50k — o auto-compact
    dispara em −33k, o handoff precisa chegar antes dele, e ainda é preciso mais uma rodada para
    "escrever o handoff"; 50k atende às duas coisas ao mesmo tempo.

    Superestimar não é erro fatal: se a janela real for menor, o limiar nunca é alcançado, a requisição
    é rejeitada pela API com «prompt longo demais», e o flower reconhece esse sinal
    (`handoff.is_overflow()`) e faz na hora um handoff com o documento degradado montado
    mecanicamente; o step não falha
    (ver [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Uma medição que vale mencionar: o gateway da máquina de desenvolvimento está configurado com
    `claude-opus-5[1m]`. Calculando por 200k, haveria uma troca de geração a cada 150k, quando na
    verdade ela aguenta 950k — **5 vezes de diferença**, e trabalho long-horizon acaba picotado.

### Handoff logo de saída, e não para mais {#一开局就换代}

**Sintoma** O erro menciona "piso de inicialização", ou o mesmo step faz handoff repetidamente até
bater em `max_generations=8`.

**Causa** O `window` foi configurado pequeno demais, e o limiar ficou abaixo do piso de inicialização
daquele papel — no coordinator, medido em cerca de 34k, ocupado só pelo system prompt mais o índice do
[workbench](glossary.md#工作台). A sessão nova ultrapassa a linha na primeira frase, então escreve o
handoff, troca de geração, ultrapassa de novo, para sempre (handoff não consome cota de retry, e isso é
intencional).

**O que fazer** Ajuste `--window` para a janela real do modelo; `-v` imprime o endpoint e o mapeamento
de modelos em vigor. Uma execução longa normal não chega a 8 gerações; se bateu, quase certamente é
isso, e a mensagem de erro diz exatamente isso
(ver [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Outro sintoma relacionado é "o handoff sempre sai degradado": o motivo fica em `errors`, dentro de
`runs/manifest.json`.

### Parou no meio dizendo que o orçamento estourou {#预算到顶}

**Sintoma** O [step](glossary.md#步骤) para sem terminar, com a justificativa de custo excedido.

**Causa** `AgentSpec(max_budget_usd=...)` é um **teto rígido**, não um aviso suave; `Runtime.total_cost()`
é o total daquela execução.

**O que fazer** Antes de levantar o teto, confirme que ele não está girando em falso. Rodada após
rodada sendo devolvida sem nenhum progresso costuma significar que o judge deveria ter dado
«inatingível» e deu «não atingido» — um objetivo que de fato não dá para cumprir queima até o fim da
cota (ver [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirme que está de fato trabalhando e só então levante o teto.

### Por que essa execução saiu tão cara {#为什么这么贵}

**Sintoma** O custo foi muito além do esperado, mas olhando a saída não dá para ver onde o dinheiro foi.

**Causa** A conta não está no contexto do modelo. O `session_id`, o custo, o número de retries e o
motivo da falha de cada step ficam registrados apenas em `runs/manifest.json`, **em append entre
processos**. O histórico de retries e o texto original dos erros também só ficam ali — o modelo não vê,
e isso é intencional: chamadas negadas acumuladas no contexto ensinam o coordinator que "o Bash vai ser
bloqueado de qualquer jeito", e ele para de tentar até `git status`
(`Runtime(keep_denials=1)` já limpa por padrão; não aumente).

**O que fazer** Abra `runs/manifest.json` e confira o custo step a step (o layout em disco está em
[config.md#磁盘布局](config.md#磁盘布局)). Alguns valores medidos como referência:

| | Custo |
|---|---|
| Piso de inicialização de um subagent (não diluível) | ~4.3k tokens |
| Piso de inicialização do coordinator | ~34k tokens |
| `tests/smoke.py`, cadeia completa com um agent | ~$0.21 |
| `tests/flow_demo.py`, três formas de ligar um workflow | ~$0.39 |
| `tests/delegation.py`, divisão de trabalho + medição da distribuição de contexto | ~$0.71 |
| `tests/isolation.py`, três issues em três worktrees | ~$0.9 |

### O contexto cresce mais rápido que o trabalho anda {#上下文涨得快}

**Sintoma** Todo [task brief](glossary.md#任务书) repete a mesma disciplina ("leia o arquivo antes de
alterar", "não mexa no código de negócio", "rode os testes depois de alterar"), enquanto o
[worker](glossary.md#执行者) já está fazendo isso.

**Causa** Toda frase que o coordinator diz entra no transcript dele, e o transcript só cresce. Repetir
a disciplina custa dinheiro nesta rodada e **é pago de novo em cada rodada seguinte**. Repetir aquilo
que o outro lado já sabe tem ganho zero e custo permanente.

**O que fazer** Disciplina vai para o mecanismo, não para a fala de cada rodada: o que puder ser
expresso por `allowed_tools`, pela seção «limites» do brief ou pelo índice do workbench não deve entrar
no task brief; o task brief só descreve o que mudou nesta rodada. A divisão de trabalho é a camada que
mais economiza
(ver [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Ao dar resume, resultados grandes de ferramentas antigas podem ser trocados por ponteiros de arquivo
com `-T`.

## Interrupção e continuidade {#中断与接续}

### O processo foi morto, a máquina reiniciou {#进程被杀}

**Sintoma** Sumiu no meio do caminho, e ao reabrir o terminal você não sabe como retomar.

**Causa** Não há nada para retomar. A [lineage](glossary.md#血缘) (`runs/lineage.json`) registra nome do
step → session_id, é gravada em disco ao fim de cada step, e a gravação escreve primeiro um `.tmp` e
depois faz substituição atômica — ser morto no meio não deixa meio arquivo.

**O que fazer** Volte ao **mesmo diretório** e rode `flower` de novo; cada step continua da sessão
anterior: ele não vai interrogar a demanda outra vez, não vai redefinir o objetivo, e até lembra quais
becos sem saída o coordinator já testou. Se você não quiser dizer nada, é só dar Enter
(ver [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
O judge é a exceção — ele não é um `Step`, é despachado direto pelo gate e nunca passa pela lineage,
então cada rodada tem um par de olhos totalmente novo.

### Toda vez começa do zero, não retoma nada {#接不上}

**Sintoma** Rodando de novo no mesmo diretório, ele interroga a demanda outra vez.

**Causa** Três tipos de "não bate", e o flower **volta silenciosamente ao começo, sem erro** — a
[continuity](glossary.md#接续) é um bônus, e falhar nela não deve impedir a pessoa de trabalhar:

- `runs/lineage.json` não existe, ou o `workspace` dentro dele não corresponde ao seu caminho atual (é o
  que acontece se o diretório foi copiado para outro lugar)
- A sessão já não está em `runs/sessions.db` (o banco foi apagado)
- O arquivo de lineage está corrompido

**O que fazer** Verifique primeiro se `runs/lineage.json` existe e se o `workspace` está correto
(as responsabilidades dos três arquivos estão em
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Não retomar depois de trocar de diretório é **intencional**: o `project_key` é derivado do caminho do
workspace, e a sessão antiga não é encontrada no novo lugar.

### Quero recomeçar, mas sem perder o histórico {#想重开}

**Sintoma** A demanda mudou de direção e você não quer que ele continue falando da leva anterior.

**Causa** O comportamento padrão é continuar. Num diretório já usado, `flower "顺便支持代码块高亮"` não
é uma tarefa nova, é mais uma frase dita.

**O que fazer** `--new`. Ele **arquiva, não apaga**: o material antigo fica em `notes/archive/`.
No [wake](glossary.md#唤醒) ele antes informa numa linha o tamanho do contexto atual; se achar grande,
use este mesmo caminho.

### Caiu a rede, ele não dá erro e não anda {#断网}

**Sintoma** Nenhum evento novo na interface, o processo continua vivo, parece travado.

**Causa** Queda de rede é tratada como "espere um pouco", não como falha. O flower fica pendurado
esperando: primeiro sonda DNS, depois TCP, e só continua quando passa
(ver [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
No HT001 isso foi validado por uma falha real
(ver [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**O que fazer** Espere; com `-v` dá para ver as sondagens rodando. Os erros acumulados durante a espera
**não entram no contexto depois da continuidade** — ficam apenas em `runs/manifest.json`, e a sessão
sucessora vê um cenário limpo, sem ser desviada por uma sequência de timeouts.

### Dois Ctrl-C seguidos e o encerramento não completa {#双重-ctrl-c}

**Sintoma** Fechar com `kill` (SIGTERM) e apertar Ctrl-C duas vezes deixam cenários diferentes.

**Causa** Lacuna conhecida. O duplo Ctrl-C lança `KeyboardInterrupt`: no `cli.py`, o `finally` de
`_drive` chama `rt.close()`, mas **não** chama `rt.rescue()` — só os handlers de SIGHUP/SIGTERM chamam
`rescue()`.

**O que fazer** A lineage é preservada nos dois caminhos (gravação atômica ao fim de cada step), então
rodar de novo retoma normalmente e essa lacuna não faz você perder progresso. Para um encerramento
completo, use `kill <pid>` em vez de martelar Ctrl-C.

## Paralelismo e isolamento {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Sintoma** Com isolamento ligado ele não sobe, e reporta `not in a git repository`.

**Causa** `worker(..., isolate=True)` usa git worktree para dar a cada agent uma cópia privada; se o
workspace não é um repositório git, não há como criá-la.

**O que fazer** Este caso **não degrada em silêncio** — ou você roda de fato dentro de um repositório,
ou desliga o `isolate`. O isolamento garante que "vários agents alterem ao mesmo tempo sem enxergar a
árvore de trabalho um do outro"; ele não garante que o merge não terá conflito.

### O agent isolado não consegue escrever no workbench {#隔离写不进工作台}

**Sintoma** O subagent reporta "permissão de escrita negada", scripts e artefatos não vão para o disco;
ou o artefato cai dentro de uma worktree e os outros agents não veem.

**Causa** A worktree é a **cópia privada** de cada agent; o workbench é a **camada compartilhada** entre
agents. Colocar o que é compartilhado dentro de uma cerca privada obviamente deixa os outros sem acesso.

**O que fazer** Com isolamento ligado, aponte o workbench para **fora do repositório**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Quando fica fora do workspace, o `Runtime` autoriza automaticamente com `add_dirs`;
`Runtime(workbench=True)` já cuida disso, mas um `Workbench` construído por você exige que você mesmo
conceda a autorização.

!!! warning "O workbench tem dois locais padrão, e eles são diferentes"
    `Workbench(workspace)` — o caminho usado pela CLI e por `starter_flow()` — coloca o workbench em
    `<workspace>/.flower`; já `Runtime(workbench=True)` (ou seja, `-W`) coloca em `<run_dir>/workbench`,
    isto é, `runs/workbench`. Então rodar `flower` uma vez te dá `.flower/`, e chamar
    `Runtime(workbench=True)` em Python **não**.

### Rodando flower aparece `.flower/`, mas no meu script não {#两个工作台默认值}

**Sintoma** O brief foi escrito em `.flower/notes/需求.md`, mas o coordinator age como se nunca tivesse
lido; **sem erro**.

**Causa** Você tem dois objetos workbench em mãos. O brief foi escrito no diretório A, e o índice
injetado no system prompt varre o diretório B; a promessa de "já saber onde está o arquivo de demanda
desde o início" **falha em silêncio**. As duas formas de errar não dão erro: montar um `brief_path`
relativo ao cwd do processo é um diretório diferente do `<run_dir>/workbench` criado por `-W`; e tentar
pegá-lo de volta a partir do `Runtime` também não funciona — o `cli.py` chama `main()` para construir o
`Workflow` primeiro e só depois cria o `Runtime`, quando o `brief_path` já está fixado.

**O que fazer** Construa você mesmo um `Workbench` e passe o **mesmo objeto** ao `Workflow` e ao
`Runtime`; a posição fica travada:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` trava esse comportamento: a 5ª asserção verifica que o brief aparece em
`prompt_block()`. Além disso, o índice só é injetado no system prompt do **coordinator**; subagents não
herdam (medido em $0.2461, `tests/prelude_live.py`) — o caminho precisa ser repassado pelo coordinator,
não é algo que cada subagent saiba automaticamente
(ver [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
