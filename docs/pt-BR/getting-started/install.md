# Instalação

Instalar o flower só exige Python ≥ 3.10. A única dependência de runtime é `claude-agent-sdk` — o binário nativo que faz as requisições vem dentro da wheel dele, então **não precisa instalar Node nem o Claude Code CLI**. Esta página percorre tudo do zero: instalação em uma linha, instalação a partir do código-fonte, a primeira configuração de credenciais e um comando que prova que "de fato ficou certo". Depois que isso rodar, vá para [Início rápido](quickstart.md).

## Antes de instalar: confirme o Python

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Uma saída como `True 3.13.7` já basta. Se imprimir `False` ou se não existir `python3`, instale um primeiro (`brew install python` / `apt install python3`); caso contrário o script de instalação sai na hora.

| Precisa | Não precisa |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` também confere) | Node.js |
| Rede até o endpoint da API | Claude Code CLI |
| Uma API key ou token de gateway (você fornece depois de instalar) | As configurações em `~/.claude/` da máquina host (as credenciais são a única exceção, veja abaixo) |

Nome do pacote `flower`, versão `0.1.0`, única dependência de runtime `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). O `mkdocs-material` só é usado quando o CI constrói o site de documentação; rodar o flower não precisa dele.

## Instalação em uma linha

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Depois de instalar, o terminal deve ficar assim (sem as cores):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

O que importa é aquela linha `== 装好了 <caminho absoluto>` — ela é o resultado de o próprio script ter rodado um `command -v flower` (`install.sh:60-61`). Se imprimiu o caminho, é porque `flower` já está no PATH.

### O que o instalador realmente faz

O [`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) faz apenas três coisas: escolhe um instalador de ferramentas Python, instala a partir do GitHub e diz qual é o próximo passo. **Ele não toca em uma única letra das suas credenciais** (`install.sh:7-8`). A origem da instalação é fixa: `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

O instalador tenta em ordem e para na primeira opção que funcionar (`install.sh:33-57`):

| Ordem | Condição de disparo | Comando real | Onde o executável cai |
|---|---|---|---|
| 1 | `uv` está no PATH | `uv tool install --force <REPO>` | Diretório de bin de ferramentas do uv, normalmente `~/.local/bin/flower` |
| 2 | Sem `uv`, mas com `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Nenhum dos dois | Primeiro instala o uv com `curl -LsSf https://astral.sh/uv/install.sh \| sh`; se instalar, volta para o caso 1 | Igual ao caso 1 |
| 4 | No caso 3 o uv também não instalou | `python3 -m pip install --user --upgrade <REPO>` | Diretório de scripts do usuário — **no macOS não é `~/.local/bin`** |

Os quatro casos instalam o mesmo console script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Depois de instalado também dá para chamar por `python -m flower.cli`, com o mesmo efeito (`cli.py:1263-1264`).

!!! warning "Rodar o script de instalação de novo sobrescreve à força, sem pedir confirmação"
    Os três comandos de instalação levam, respectivamente, `--force`, `--force` e `--upgrade` (`install.sh:37`, `:40`, `:54`). Rodar de novo é passar por cima da instalação existente — é exatamente assim que se atualiza, mas não espere que ele pergunte antes.

### Como o comando `flower` entra no PATH

Quando o `command -v flower` não encontra nada, o script sugere adicionar `$HOME/.local/bin` ao `~/.zshrc` ou ao `~/.bashrc` (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Tanto `uv tool install` quanto `pipx install` colocam o binário aí, então essa sugestão é correta para eles. **Mas o caso 4 (`pip install --user`) não necessariamente** — o diretório naquela mensagem está escrito no código, e o diretório de scripts de usuário do pip depende da plataforma. No macOS ele é `~/Library/Python/3.13/bin`. Confira você mesmo:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

A saída é algo como `/Users/you/Library/Python/3.13/bin` — adicione esse diretório ao PATH, e não `~/.local/bin`; depois reabra o terminal ou faça um `source`.

## Instalar a partir do código-fonte

Se você quer ler o código, alterar o framework ou rodar aquelas verificações offline em `tests/`, instale a partir do código-fonte:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Depois disso, `.venv/bin/flower --help` deve imprimir aquelas linhas de usage.

O shebang daquele executável dentro do venv é um **caminho absoluto**, então não é preciso ativar o venv: basta um symlink para usá-lo em qualquer diretório:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Se `~/.local/bin` estiver no PATH, dar `cd` em qualquer diretório de projeto e digitar `flower` usa esse interpretador do venv e este código-fonte.

A instalação a partir do código-fonte ainda tem um lugar extra para as credenciais: o **`.env` na raiz do repositório** (é o 5º na ordem de busca, veja [Configuração · Prioridade de busca de credenciais](../reference/config.md#凭证查找优先级)). Durante o desenvolvimento:

```bash
cp .env.example .env        # preencha ANTHROPIC_AUTH_TOKEN
```

O `.env` já está no `.gitignore`, então não vai para o versionamento. Um flower instalado por pip / pipx / uv **não** tem esse lugar disponível — ele fica em site-packages, não existe "raiz do repositório" — então nessas instalações use o arquivo global de credenciais descrito abaixo.

## Primeira execução: configurar credenciais

As três entradas que realmente executam algo — `go`, `run` e `once` — chamam `ensure_credentials()` no começo (`cli.py:1013`, `:981`, `:1046`), com duas checagens:

1. **Existe?** — busca na ordem de prioridade; se não achar, pergunta ali mesmo.
2. **Funciona?** — faz uma chamada real à API. Uma requisição mínima com `max_tokens=16` (`env.py:120-123`), que quase não custa nada. Um token expirado ou um endereço de gateway errado não aparecem só olhando as variáveis de ambiente; sem a sonda, o erro só explodiria alguns minutos depois.

Sem credenciais, a primeira execução do `flower` para nesta tela (`cli.py:1179-1209`):

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

A pergunta 1 é obrigatória; se deixar em branco, ele imprime em vermelho `没给 token,取消。` e sai. As perguntas 2 e 3 podem ser respondidas com Enter direto. Para usar o endpoint oficial, deixe a pergunta 2 vazia; para um gateway de terceiros, preencha o endereço raiz dele, **sem `/v1`** — a sonda do flower chama `<BASE_URL>/v1/messages` (`env.py:162`).

As chaves escritas depois de você responder (`cli.py:1199-1207`):

| O que você preencheu | Chave escrita no `.env` |
|---|---|
| Token que começa com `sk-ant-` | `ANTHROPIC_API_KEY` |
| Qualquer outro token | `ANTHROPIC_AUTH_TOKEN` |
| Endereço de gateway não vazio | `ANTHROPIC_BASE_URL` |
| Nome de modelo não vazio | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **as três de uma vez** |

O arquivo fica em `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), é **sobrescrito por inteiro** e, depois de escrito, recebe `chmod 0o600` (`cli.py:1157-1168`). É esse o arquivo do "configura uma vez, vale em todo lugar" — trocar de diretório de projeto não exige reconfigurar. O significado de cada variável está em [Configuração](../reference/config.md#环境变量).

### Se esta máquina já tem o Claude Code, talvez nenhuma pergunta apareça

A busca de credenciais tem um **último fallback**: ler `~/.claude/settings.json` e depois `~/.claude/settings.local.json`, pegando 9 chaves de credencial do bloco `env` deles (`env.py:56-75`, `:109-111`). Quem já tem o Claude Code configurado na máquina consegue começar a trabalhar rodando `flower` direto, e a tela de configuração nem aparece — é justamente isso que o `install.sh:77` anuncia.

!!! warning "A frase dentro do produto 'flower 不读 ~/.claude/settings.json' está errada"
    Quando nenhuma credencial é encontrada, a última linha do erro que o flower imprime é
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, a frase está em `:192`). **Vale o código: ele lê.**
    `env.py:56-75` lê explicitamente o bloco `env` daqueles dois arquivos; só pega 9 chaves de credencial e não assume nenhuma outra configuração. Ao ler aquela frase, não conclua que a configuração local do Claude Code está sendo ignorada. A cadeia completa está em [Configuração · Prioridade de busca de credenciais](../reference/config.md#凭证查找优先级).

### Quando quiser reconfigurar

O subcomando `flower setup` está registrado (`cli.py:1147-1149`), mas ficou de fora de `_CMDS` (`cli.py:758`); então `flower setup` acaba reescrito como `flower go setup` — tratando "setup" como uma demanda e rodando o workflow completo. **Hoje não existe nenhuma forma de linha de comando que alcance aquele subcomando**, ainda que vários textos de erro continuem mandando você rodá-lo. Para trocar as credenciais:

```bash
$EDITOR ~/.config/flower/.env
```

Ou apague o token daquele arquivo e rode `flower` de novo — a checagem de credencial ausente volta a perguntar (desde que não exista credencial em nenhum outro lugar, como `~/.claude/settings.json`). Quando a credencial é rejeitada (HTTP 401 / 403), a mesma tela também aparece na hora para você reconfigurar, com no máximo uma chance (`cli.py:1229-1244`).

## Verificar se ficou instalado

Dois níveis, do mais barato ao mais caro.

**Primeiro nível — o comando existe? (custo zero)**:

```bash
flower --help
```

Ver estas linhas significa que o console script foi instalado e está no PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Segundo nível — credenciais, endpoint e binário nativo todos funcionando (alguns centavos)**: a execução real mais barata é `once` — um único agent, por padrão só com as três ferramentas somente-leitura `Read` / `Glob` / `Grep`, sem [guarda de objetivo](../reference/glossary.md#目标看守), sem [workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

O `-v` imprime a configuração vigente **antes** de começar, deixando apenas os 4 primeiros caracteres do token (`cli.py:1257-1259`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Essas linhas confirmam que você não conectou no gateway errado. Depois vêm a sonda de credenciais e a execução de verdade:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Não há cabeçalho de passo.** O `once` vai por `_run_once` → `rt.run()`, sem passar por `_drive` / `Workflow.run`, e o `Event("step", …)` só é emitido em `workflow/base.py:220` — então linhas separadoras como `== 步骤名 ===== 1/1` não aparecem no `once`; só `go` / `run` as têm.

**Se aquela linha `+ 完成` aparecer, passou**, e ela prova três coisas ao mesmo tempo: a credencial funciona, o endpoint está acessível e o binário nativo dentro da wheel do `claude-agent-sdk` roda nesta máquina. Se abaixo de `- 验一下凭证…` vier `! 凭证被拒` ou `! 网关地址或模型名不对`, vá para a tabela de problemas mais abaixo.

!!! note "No `once`, o tempo e o custo acumulado aparecem como 0"
    O `once` cria um renderizador novo para cada evento (`cli.py:1060`, `:579-581`), então `用时` é sempre `0:00` e o `累计 $` da linha de status nunca acumula — **o custo daquele passo único é real, o tempo não**.

    O `1 轮 · $0.1741` da linha acima é uma **medição real com procedência**: em 2026-09-06, dentro de um contêiner Linux/arm64, uma requisição real enviada via `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), isto é, o **piso de preço por rodada** do Opus 5 + janela de 1M. Rodar o comando acima você mesmo exige ler o repositório, então haverá mais rodadas e o custo ficará um pouco acima desse piso. A conta completa está em `runs/manifest.json`, veja [Configuração · Layout em disco](../reference/config.md#磁盘布局).

## Quando não instala

| Sintoma | Causa | O que fazer |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Nem `python3` nem `python` atendem a 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3` e rode o script de novo |
| O script diz que instalou, mas `flower: command not found` | Foi instalado num diretório fora do PATH | Veja "Como o comando `flower` entra no PATH" acima. No caminho `pip --user`, no macOS é `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Todos os caminhos falharam, geralmente rede inacessível até o GitHub ou o PyPI | Rode manualmente conforme a sugestão para ver o erro real |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 linhas) | Ambiente não interativo (pipe, CI, `nohup`) sem credenciais — ali a tela de configuração não aparece, ele simplesmente sai | Rode `flower` uma vez num terminal real para configurar, ou escreva direto em `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | Token expirado ou errado | Num terminal interativo ele pede reconfiguração na hora; no não interativo, sai |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` ou nome do modelo errado | Escreva o BASE_URL até a raiz do gateway, sem `/v1`; use os nomes de modelo do próprio gateway |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Não é problema de credencial**; o flower deliberadamente não pede reconfiguração, segue a execução normalmente e deixa isso para a camada de [resiliência](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Rodando em pipe ou em CI | Adicione `--timeout 0` para ele decidir sozinho, sem esperar por ninguém |
| `flower setup` roda e pergunta "o que fazer" | `setup` ficou de fora de `_CMDS` (`cli.py:758`) | Edite `~/.config/flower/.env` direto, veja "Quando quiser reconfigurar" acima |

## Próximos passos

- [Início rápido](quickstart.md) — entre num diretório de projeto e leve a primeira tarefa real até o fim.
- [Configuração](../reference/config.md) — todas as variáveis de ambiente, prioridade das credenciais, sintaxe do `.env`, o que fica no disco.
- [Linha de comando](../reference/cli.md) — todos os subcomandos e flags.
- [Deploy](../reference/deploy.md) — rodar em contêiner, distribuir capacidades de domínio via plugin.
- [Glossário](../reference/glossary.md) — o significado exato de cada termo da documentação.
