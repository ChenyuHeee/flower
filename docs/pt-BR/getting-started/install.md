# Instalação

Instalar o flower exige apenas Python ≥ 3.10. A única dependência de runtime é `claude-agent-sdk` — o binário nativo que faz as requisições já vem dentro da wheel dele, então **não é preciso instalar Node nem o Claude Code CLI**. Esta página percorre tudo do zero: instalação em uma linha, instalação a partir do código-fonte, a primeira configuração de credenciais e um comando que prova que "instalou mesmo". Depois que isso funcionar, vá para o [Começo rápido](quickstart.md).

## Antes de instalar: confira o Python {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Uma saída como `True 3.13.7` já basta. Se sair `False` ou se `python3` nem existir, instale um antes
(`brew install python` / `apt install python3`), senão o script de instalação sai na hora.

| Necessário | Desnecessário |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` também confere) | Node.js |
| Rede até o endpoint da API | Claude Code CLI |
| Uma API key ou token de gateway (dá para fornecer depois da instalação) | As configurações em `~/.claude/` da máquina (as credenciais são a única exceção, veja abaixo) |

Nome do pacote `flower`, versão `0.1.0`, única dependência de runtime `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material` só é usado no CI para construir o site de documentação; para rodar o flower não é preciso.

## Instalação em uma linha {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Terminada a instalação, o terminal deve mostrar algo assim (sem as cores):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

O que importa é a linha `== 装好了 <caminho absoluto>` — ela é o resultado de o próprio script ter rodado um `command -v flower`
(`install.sh:60-61`). Se o caminho foi impresso, `flower` já está no PATH.

### O que o instalador realmente faz {#安装器实际做了什么}

O [`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) faz só três coisas: escolhe um
instalador de ferramentas Python, instala a partir do GitHub e diz qual é o próximo passo. **Ele não toca em uma única letra das suas credenciais** (`install.sh:7-8`).
A fonte de instalação é fixa: `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

O instalador tenta em ordem e para na primeira que funcionar (`install.sh:33-57`):

| Ordem | Condição de disparo | Comando efetivo | Onde cai o executável |
|---|---|---|---|
| 1 | `uv` está no PATH | `uv tool install --force <REPO>` | O diretório bin de ferramentas do uv, normalmente `~/.local/bin/flower` |
| 2 | Sem `uv`, mas com `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Nenhum dos dois | Primeiro instala o uv com `curl -LsSf https://astral.sh/uv/install.sh \| sh`; se der certo, volta para o caso 1 | Igual ao caso 1 |
| 4 | O uv também não instalou no caso 3 | `python3 -m pip install --user --upgrade <REPO>` | Diretório de scripts do usuário — **no macOS não é `~/.local/bin`** |

Nos quatro casos instala-se o mesmo console script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Depois de instalado também dá para chamar com
`python -m flower.cli`, com o mesmo efeito (`cli.py:1451-1452`).

!!! warning "Rodar o script de instalação de novo sobrescreve à força, sem pedir confirmação"
    Os três comandos de instalação levam, respectivamente, `--force`, `--force` e `--upgrade` (`install.sh:37`, `:40`, `:54`).
    Rodar de novo é sobrescrever a instalação existente na hora — é exatamente assim que se atualiza, mas não espere que ele pergunte antes.

### Como o comando `flower` entra no PATH {#flower-命令怎么上-path}

Quando `command -v flower` não encontra nada, o script sugere adicionar `$HOME/.local/bin` ao `~/.zshrc` ou `~/.bashrc`
(`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Tanto `uv tool install` quanto `pipx install` colocam o binário ali, então para eles a dica está correta. **Mas o caso 4
(`pip install --user`) nem sempre** — o diretório dessa mensagem está fixo no código, enquanto o diretório de scripts de usuário do pip depende da plataforma.
No macOS ele é `~/Library/Python/3.13/bin`. Confira você mesmo:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

A saída pode ser, por exemplo, `/Users/you/Library/Python/3.13/bin` — adicione esse diretório ao PATH, não `~/.local/bin`,
e depois reabra o terminal ou dê um `source`.

## Instalar a partir do código-fonte {#从源码装}

Se você quer ler o código, alterar o framework ou rodar as verificações offline de `tests/`, instale a partir do código-fonte:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Feito isso, `.venv/bin/flower --help` deve imprimir as linhas de usage.

O shebang daquele executável dentro do venv é um **caminho absoluto**, então não é preciso ativar o venv; basta um symlink para usá-lo em qualquer diretório:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Com `~/.local/bin` no PATH, `cd` para qualquer diretório de projeto e digite `flower`: vai rodar o interpretador desse venv
e esse código-fonte.

A instalação a partir do código-fonte ainda traz um lugar a mais para as credenciais: **o `.env` na raiz do repositório** (é o 5º na ordem de busca, veja
[Configuração · Prioridade de busca de credenciais](../reference/config.md#凭证查找优先级)). Durante o desenvolvimento:

```bash
cp .env.example .env        # preencha ANTHROPIC_AUTH_TOKEN
```

O `.env` já está no `.gitignore` e não entra no controle de versão. O flower instalado por pip / pipx / uv **não** tem esse lugar
disponível — ele fica em site-packages, não existe "raiz do repositório" — então nesse tipo de instalação use o arquivo global de credenciais descrito abaixo.

## Atualização automática {#自动更新}

O flower ainda está iterando rápido, então **a instalação feita por pip / pipx / uv se atualiza sozinha por padrão**: quem instalou uma versão de três dias atrás
pode reportar um bug que já foi corrigido há muito tempo, e os dois lados perdem tempo. Isso não vem em forma de pergunta "quer ativar?" —
vem ativado por padrão, e para desligar você define uma variável de ambiente.

O que ele faz (`update.py:116-129`):

1. A cada inicialização do `flower`, consulta em uma **thread em segundo plano** o commit mais recente de `main` no GitHub
   (`update.py:70-80`). O fluxo principal não espera nem um segundo — essa é a primeira invariante.
2. Se for diferente do commit instalado localmente, roda um comando de atualização conforme o método de instalação original: com `uv`, usa
   `uv tool install --force`; com `pipx`, `pipx install --force`; sem nenhum dos dois,
   `pip install --user --upgrade` (`update.py:83-93`).
3. **Mesmo depois de instalada, a nova versão não substitui o processo em execução** — só o próximo `flower` usa a versão nova
   (`update.py:113`). Ser trocado no meio da execução é um dos tipos de falha mais difíceis de investigar.
4. Throttle: no máximo uma consulta a cada 24 horas, com o timestamp gravado em `~/.config/flower/.update`
   (`update.py:32`, `:36-37`, `:124`).
5. **Toda falha é silenciosa.** Sem rede, GitHub fora do ar, instalação que não completa — nada disso interrompe seu trabalho (`update.py:79`, `:108-110`).

**Quem roda a partir do código-fonte (git) não é afetado.** A etapa do comando de atualização primeiro verifica se existe `.git` no repositório; se existir, retorna
`None` na hora e não faz nada (`update.py:83-87`) — sua árvore de trabalho é assunto do `git`, não dele.
Em modo não interativo (stdin não é um terminal, por exemplo em pipe / CI) tudo isso é pulado (`update.py:121`).

Para desligar:

```bash
export FLOWER_NO_UPDATE=1
```

Qualquer valor não vazio conta (`update.py:33`, `:121`). Use em CI, ambientes offline ou quando precisar reproduzir o comportamento de uma versão antiga.

## Primeira execução: configurar as credenciais {#第一次跑配凭证}

As três entradas de execução — `go`, `run` e `once` — chamam `ensure_credentials()` logo no início (`cli.py:1192`, `:1160`, `:1225`),
com dois portões:

1. **Existe ou não** — busca na ordem de prioridade; se não achar, pergunta a você na hora.
2. **Funciona ou não** — faz uma chamada de verdade à API. Uma requisição mínima com `max_tokens=16` (`env.py:120-123`), praticamente sem custo.
   Token expirado, endereço de gateway digitado errado — isso não se descobre olhando variáveis de ambiente; sem a sondagem, o erro só estouraria minutos depois.

Sem credenciais, a primeira execução do `flower` para nesta tela (`cli.py:1358-1388`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

A pergunta 1 é obrigatória; deixar em branco imprime em vermelho `没给 token,取消。` e sai. Nas perguntas 2 e 3 basta dar Enter.
Se usa o endpoint oficial, deixe a pergunta 2 vazia; para um gateway de terceiros, informe o endereço raiz dele, **sem `/v1`** — a sondagem do
flower chama `<BASE_URL>/v1/messages` (`env.py:162`).

As chaves gravadas depois das respostas (`cli.py:1378-1386`):

| O que você digitou | Chave escrita no `.env` |
|---|---|
| Token começando com `sk-ant-` | `ANTHROPIC_API_KEY` |
| Outros tokens | `ANTHROPIC_AUTH_TOKEN` |
| Endereço de gateway não vazio | `ANTHROPIC_BASE_URL` |
| Nome de modelo não vazio | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **os três de uma vez** |

O arquivo fica em `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), é **sobrescrito por inteiro** e, ao final,
recebe `chmod 0o600` (`cli.py:1336-1347`). É esse o arquivo do "configure uma vez, vale em todo lugar" —
trocar de diretório de projeto não exige reconfigurar; o significado de cada variável está em [Configuração](../reference/config.md#环境变量).

### Se a máquina já tem o Claude Code instalado, talvez ele não pergunte nada {#本机装过-claude-code-的话可能一个问题都不问}

A busca de credenciais tem um **fallback final**: lê `~/.claude/settings.json` e depois `~/.claude/settings.local.json`,
pegando 9 chaves de credencial do bloco `env` deles (`env.py:56-75`, `:109-111`). Quem já tem o Claude Code configurado na máquina
pode simplesmente rodar `flower` e começar a trabalhar; a tela de configuração nem aparece — é exatamente isso que o `install.sh:77` anuncia.

!!! warning "A frase dentro do produto que diz "flower 不读 ~/.claude/settings.json" está errada"
    Quando não encontra nenhuma credencial, a última linha do erro que o flower imprime é
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, essa frase está em `:192`). **Vale o código: ele lê.**
    `env.py:56-75` lê explicitamente o bloco `env` desses dois arquivos, só que pega apenas 9 chaves de credencial e não assume nenhuma outra configuração.
    Ao ler aquela frase, não conclua que a configuração local do Claude Code está sendo ignorada. A cadeia completa está em
    [Configuração · Prioridade de busca de credenciais](../reference/config.md#凭证查找优先级).

### Quando você quiser reconfigurar {#想重新配的时候}

O subcomando `flower setup` está registrado (`cli.py:1326-1328`), mas `_CMDS` esqueceu dele (`cli.py:937`),
então `flower setup` é reescrito para `flower go setup` — tratando "setup" como um pedido e rodando o workflow inteiro.
**No momento não existe nenhuma forma de linha de comando que chegue àquele subcomando**, embora vários textos de erro ainda mandem você rodá-lo. Para trocar as credenciais:

```bash
$EDITOR ~/.config/flower/.env
```

Ou apague o token daquele arquivo e rode `flower` de novo — o portão da credencial ausente vai perguntar outra vez (desde que também não exista em outro lugar,
como `~/.claude/settings.json`). Quando a credencial é rejeitada (HTTP 401 / 403), a mesma tela aparece na hora para você reconfigurar,
com no máximo uma chance (`cli.py:1416-1428`).

## Verificar se instalou {#验证装好了没有}

Dois níveis, do mais barato ao mais caro.

**Nível 1 — o comando existe (sem custo)**:

```bash
flower --help
```

Ver estas linhas significa que o console script está instalado e no PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Nível 2 — credenciais, endpoint e binário nativo, tudo funcionando (alguns centavos)**: a execução real mais barata é `once` —
um único agent, por padrão apenas as três ferramentas somente leitura `Read` / `Glob` / `Grep`, sem [goal guard](../reference/glossary.md#目标看守),
sem [workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` imprime a configuração em vigor **antes** de começar a rodar, mantendo só os 4 primeiros caracteres do token (`cli.py:1445-1447`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Essas linhas confirmam que você não se conectou ao gateway errado. Em seguida vêm a sondagem de credenciais e a execução de verdade:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Não há cabeçalho de step.** O `once` passa por `_run_once` → `rt.run()`, sem `_drive` / `Workflow.run`,
e o `Event("step", …)` só é emitido em `workflow/base.py:220` — portanto linhas separadoras como `== 步骤名 ===== 1/1`
não aparecem no `once`; só existem em `go` / `run`.

**Se a linha `+ 完成` aparecer, passou**, e ela prova três coisas ao mesmo tempo: as credenciais funcionam, o endpoint está acessível e
o binário nativo dentro da wheel do `claude-agent-sdk` roda nesta máquina. Se depois de
`- 验一下凭证…` vier `! 凭证被拒` ou `! 网关地址或模型名不对`, vá para a tabela de diagnóstico abaixo.

!!! note "O tempo e o custo acumulado do `once` aparecem como 0"
    O `once` cria um renderizador novo para cada evento (`cli.py:1239`, `:579-581`), então `用时` é sempre `0:00` e
    o `累计 $` da linha de status nunca acumula — **o custo daquele passo único é real, o tempo não é**.

    O `1 轮 · $0.1741` da linha acima é uma **medição real com procedência**: em 2026-09-06, em um contêiner Linux/arm64,
    uma requisição real enviada via `cloud.infini-ai.com/maas` (`docker/README.md:24-25`),
    ou seja, o **piso de preço de uma única rodada** com Opus 5 + janela de 1M. Rodar o comando acima na sua máquina exige ler o repositório,
    com mais rodadas, então o custo fica um pouco acima desse piso.
    A conta completa está em `runs/manifest.json`, veja [Configuração · Layout em disco](../reference/config.md#磁盘布局).

## Quando não instala {#装不上的时候}

| Sintoma | Causa | O que fazer |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Nem `python3` nem `python` atendem a 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3` e rode o script de novo |
| O script diz que instalou, mas `flower: command not found` | Instalou em um diretório que não está no PATH | Veja "Como o comando `flower` entra no PATH" acima. Pelo caminho `pip --user`, no macOS é `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Todos os caminhos falharam, normalmente por falta de rede até o GitHub ou o PyPI | Rode manualmente conforme a mensagem e veja o erro real |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 linhas) | Ambiente não interativo (pipe, CI, `nohup`) sem credenciais — ali a tela de configuração não aparece, ele sai direto | Rode `flower` uma vez em um terminal real para configurar, ou escreva `~/.config/flower/.env` diretamente |
| `! 凭证被拒:HTTP 401 …` | Token expirado ou errado | Em terminal interativo ele deixa você reconfigurar na hora; em modo não interativo, sai |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` ou nome do modelo errado | Escreva a BASE_URL até a raiz do gateway, sem `/v1`; use os nomes de modelo próprios do gateway |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Não é problema de credencial**; o flower propositalmente não pede reconfiguração, começa a rodar normalmente e deixa isso para a camada de [resiliência](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Rodando em pipe ou CI | Adicione `--timeout 0` para que ele decida sozinho, sem esperar alguém |
| `flower setup` roda e fica perguntando "o que fazer" | `_CMDS` esqueceu de `setup` (`cli.py:937`) | Edite `~/.config/flower/.env` diretamente, veja "Quando você quiser reconfigurar" acima |

## Próximo passo {#下一步}

- [Começo rápido](quickstart.md) — entre em um diretório de projeto e faça o primeiro trabalho real.
- [Configuração](../reference/config.md) — todas as variáveis de ambiente, prioridade de credenciais, sintaxe do `.env`, o que fica em disco.
- [Linha de comando](../reference/cli.md) — todos os subcomandos e flags.
- [Deploy](../reference/deploy.md) — rodar em contêiner, distribuir capacidades de domínio via plugin.
- [Glossário](../reference/glossary.md) — o significado exato de cada termo da documentação.
