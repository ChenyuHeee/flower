# Deploy e extensão

Levar o flower para outro lugar envolve três coisas: contêiner (cercar o Bash irrestrito e, de quebra, verificar a afirmação "sem depender do CLI"),
[plugin](glossary.md#plugin) (capacidade de domínio viaja junto com o repositório, sem olhar o que está instalado na máquina host) e o site de documentação (push para `main`
publica sozinho; o `install.sh` fica pendurado no domínio do Pages). As três seções são independentes; leia conforme a necessidade.

## 1. Contêiner {#一容器}

### Por que contêiner {#为什么要容器}

**Primeiro: para cercar.** O [worker](glossary.md#执行者) que faz o trabalho tem **Bash irrestrito** — a whitelist de Bash do flower
(`delegate_guard`) só cobre a [main thread](glossary.md#主线程); quem é despachado precisa poder rodar testes, então isso é intencional.
No contêiner só é montado o diretório do seu projeto; o código do framework fica em `/opt/flower` dentro da imagem, e o resto do host não é visível.

**Segundo: ele próprio é a verificação daquela restrição de [portabilidade](glossary.md#可移植).** Na imagem não há Claude Code CLI,
não há Node, só Python e `claude-agent-sdk` — as requisições saem pelo binário nativo que vem no wheel.
Se roda aqui, "sem depender do CLI" deixa de ser conversa no papel.

Verificado na prática (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| O que foi verificado | Resultado |
|---|---|
| Existe CLI na imagem? | `claude`, `node`, `npm`, `npx` **não existem** |
| Binário embutido | `\177ELF` (207M) |
| Requisição real | enviada via `cloud.infini-ai.com/maas` e respondida, `$0.1741 / 1 rodada` (esse é o piso de uma única rodada com Opus 5 + janela de 1M) |
| Propriedade dos arquivos | arquivos escritos em `/work` dentro do contêiner aparecem no host como `hechenyu:staff`, mapeamento correto |
| Visibilidade do host | dentro do contêiner, `ls /Users` → `No such file or directory` |

### O que está instalado na imagem {#镜像里装了什么}

Imagem base `python:3.13-slim`, e em cima dela o apt instala apenas três pacotes. Cada um tem motivo:

| O que | Por quê |
|---|---|
| `python:3.13-slim` | só é preciso Python ≥ 3.10. Sem Node, sem CLI do claude |
| `git` | `--isolate` precisa dar uma worktree para cada [subagent](glossary.md#subagent) |
| `ca-certificates` | passa por gateway HTTPS |
| `libstdc++6` | o binário embutido no SDK é um arquivo único compilado com Bun; no Linux ele precisa disso, e a imagem slim não traz |

O código do framework entra na imagem por `COPY`, **não por bind mount** — por isso o agent dentro do contêiner não alcança o código do framework no host:

| Caminho na imagem | Conteúdo | Vem de |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, e ali roda `pip install .` | `COPY` |
| `/work` | diretório de trabalho (`WORKDIR`), onde o `$PWD` do host é montado em tempo de execução | `docker run -v` |

O entrypoint é `ENTRYPOINT ["flower"]` e o `CMD` está vazio — rodar o contêiner sem argumentos cai na entrada interativa
(ele pergunta o que você quer fazer) em vez de imprimir `--help`. Assim não é preciso pôr aspas num pedido em linguagem natural no shell.

### Por que não dá para montar o `.venv` do host {#为什么不能把宿主的-venv-挂进去}

O SDK publica wheels por plataforma, e o binário embutido é específico de plataforma:

```text
host      claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
          → _bundled/claude é Mach-O 64-bit arm64, 191M
contêiner claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Montado, não roda; por isso a imagem tem de fazer seu próprio `pip install`. Visto de outro ângulo, isso também é prova de portabilidade: o mesmo
`pyproject.toml`, troca-se de plataforma e troca-se o binário nativo, sem mudar uma linha do código do framework.

### Os dois scripts {#两个脚本}

| Script | O que faz |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | constrói a imagem. `cd` para a raiz do repositório, `docker build -f docker/Dockerfile -t flower-box .`; com `FLOWER_MIRRORS=1` (padrão) primeiro puxa `python:3.13-slim` de um mirror de registry e faz retag, passando os `--build-arg` de pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | roda uma vez. Checa o arquivo de credenciais → checa se `$PWD` pode mesmo ser montado → verifica se há TTY → `docker run` |

As chaves do `docker/build` são todas variáveis de ambiente:

| Variável | Padrão | Semântica |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | tag da imagem |
| `FLOWER_MIRRORS` | `1` | `0` = não troca nenhum mirror, tudo direto no upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | puxa a imagem base daqui e faz retag para `python:3.13-slim`, para que o `FROM` acerte o local |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | vai para `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | vai para `--build-arg APT_MIRROR` |

As três últimas só têm efeito com `FLOWER_MIRRORS=1` — o ramo `FLOWER_MIRRORS=0` simplesmente não define build-arg nenhum.

O `docker/flowerbox` reconhece duas:

| Variável | Padrão | Semântica |
|---|---|---|
| `FLOWER_HOME` | um nível acima da posição do próprio script (ou seja, a raiz do repositório) | onde procurar o `.env`. Se não achar `$FLOWER_HOME/.env`, sai com 1 |
| `FLOWER_IMAGE` | `flower-box` | qual imagem rodar |

`FLOWER_HOME` é derivado da posição do próprio script, sem caminho fixo, então funciona onde quer que o repositório seja clonado.

### Construir a imagem e subir o contêiner {#跑起来}

```bash
docker/build                       # uma vez basta
cd ~/任意项目目录                   # precisa estar sob $HOME, veja os limites de montagem abaixo
/path/to/flower/docker/flowerbox   # sem argumentos → ele pergunta o que você quer, sem aspas
```

Se a rede até pypi.org / Docker Hub estiver normal, construa assim:

```bash
FLOWER_MIRRORS=0 docker/build
```

Os argumentos do `flowerbox` são exatamente os do `flower` — ele repassa `"$@"` tal e qual depois do `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout 秒`, `--isolate`, `-v` valem todos; a tabela completa está em [Linha de comando](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

O que é executado de fato é esta linha (`-t` só é acrescentado quando há TTY, veja abaixo):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Limites de montagem e persistência {#挂载边界与持久化}

```text
host $PWD  ──montado──>  /work       ← o agent trabalha aqui, os artefatos ficam no host
na imagem                /opt/flower ← código do framework, **não montado**, não alcança o host
```

Por isso rodar dentro de um subdiretório do próprio repositório, como `flower/human-test/HT001`, também é seguro: só o `HT001` é montado,
e o código do framework fica fora do escopo da montagem.

| Coisa | Continua lá depois de sair? | Por quê |
|---|---|---|
| tudo sob o `$PWD` do host, incluindo `runs/` e o [workbench](glossary.md#工作台) `.flower/` | sim | é exatamente o diretório montado como `/work` |
| o que for escrito em outros caminhos dentro do contêiner | não | `--rm`, o contêiner é apagado ao sair |
| credenciais | não entram nas camadas da imagem | vão por `--env-file`; o `.dockerignore` exclui o `.env`, então nem um `COPY . .` levaria |

!!! danger "O diretório do projeto precisa estar sob `$HOME`, senão os artefatos somem em silêncio"
    **O colima, por padrão, só monta `$HOME` dentro da VM** (`mount | grep virtiofs` → `mount0 on /Users/<você>`).
    Rodar em lugares como `/tmp` faz o `-v` criar um **diretório vazio** dentro da VM; o que for escrito ali o host nunca verá,
    **e não há erro nenhum** — artefatos, [brief](glossary.md#需求确认书), `runs/`, tudo perdido. Já aconteceu uma vez:
    um `once` terminou, $0.17 gastos, e `runs/` simplesmente não existia no host.

    O `flowerbox` agora barra esse caso: se `$PWD` está sob `$HOME`, libera direto; se não está, ele escreve um
    arquivo-sonda em `$PWD` e sobe um contêiner para testar `test -f /work/<探针>` de verdade (montagens extras configuradas também passam). Se não passar, sai com 1
    e informa `colima start --mount '<路径>:w'`. A sonda precisa subir um contêiner, então antes é preciso rodar `docker/build`.

### Como as credenciais entram no contêiner {#凭证}

Via `docker run --env-file`, **não entram nas camadas da imagem**. O `flowerbox` lê `$FLOWER_HOME/.env`,
que por padrão é o `.env` na raiz do repositório:

```bash
cp .env.example .env       # preencha o token; o .env já está no gitignore
```

Atenção: o `flower setup` escreve em `~/.config/flower/.env`, e **o `flowerbox` não olha esse caminho**.
Se você já configurou com `setup` e não quer duplicar, aponte `FLOWER_HOME` para lá:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Nomes de chave, precedência e como preencher o gateway: veja [Configuração](config.md).

!!! warning "Sem TTY, uma pergunta trava até o `--timeout`"
    O `flowerbox` só acrescenta `-t` quando `[ -t 0 ]` — `docker run -t` num pipe / CI dá direto
    "the input device is not a TTY"; o `-i` é sempre necessário, senão a stdin nem chega.

    Responder às perguntas passa pela entrada padrão. Sem TTY, o `input()` lança `EOFError` já na primeira vez → a pergunta atual é tratada como
    "entrada fechada" e pulada, e **a thread de resposta encerra**, de modo que a partir da segunda pergunta não há mais ninguém atendendo e só resta esperar
    o `--timeout` inteiro (padrão 1800 segundos). Para rodar sem supervisão, use explicitamente `--timeout 0`. O script imprime um aviso
    quando detecta ausência de TTY.

### git submodule {#git-submodule}

O `.gitmodules` tem uma entrada só:

| path | url | o que é |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | o repositório de código **produzido** por aquele run do [HT001](../cases/ht001.md), guardado como registro |

Um `git clone` comum não puxa isso, e `human-test/HT001` fica sendo um diretório vazio (o `-` na frente no `git submodule status`
é exatamente esse estado). Se você precisa se importar:

| O que você quer fazer | Precisa inicializar? |
|---|---|
| rodar o flower, construir a imagem | **não**. O `.dockerignore` exclui `human-test/`, e o `Dockerfile` de qualquer forma só faz `COPY` de `pyproject.toml` / `flower` / `examples` |
| olhar localmente o código produzido no HT001 | sim: `git submodule update --init human-test/HT001`, ou já clonar com `git clone --recurse-submodules` |

### Rede na China: por que aquela pilha de substituições de mirror {#国内网络为什么有那一堆镜像替换}

Instalar isso atrás do Great Firewall é lento não por banda, mas pela rota internacional. O `docker/build` padrão já troca tudo o que precisa ser trocado,
e `FLOWER_MIRRORS=0` desliga tudo de uma vez. Abaixo vêm os números medidos e o porquê das quatro substituições — se sua rede não tem esse problema, pule.

??? note "Tabela de velocidades medidas e as quatro substituições (2026-09-06, macOS/arm64)"

    | Origem | Velocidade |
    |---|---|
    | `pypi.org` (índice) | 32 KB/s |
    | `files.pythonhosted.org` (arquivos de pacote) | **284 B/s** |
    | `github.com` (release asset direto) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (dentro da VM) | 26 KB/s |
    | `download.docker.com` | **inacessível** (HTTP 000); 4 KB/s dentro da VM |
    | `mirrors.tuna.tsinghua.edu.cn` | **inacessível** |
    | `mirrors.aliyun.com/pypi` (**arquivos de pacote**) | 1.4 MB/s (host) / 152 KB/s (dentro da VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (dentro da VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (proxy do GitHub) | **2.5 MB/s** |
    | `gh-proxy.com` (proxy do GitHub) | 1.5 MB/s |
    | `dockerproxy.net` (proxy do Docker Hub) | funciona (devolve o manifest direto) |

    Ao medir, não confunda **página de índice** com arquivo de pacote: a página `mirrors.aliyun.com/pypi/simple/` dá 7.4 MB/s,
    enquanto o wheel real de 95.9 MB dá só 1.4 MB/s (152 KB/s dentro da VM — a rede em user space do colima tem perda).
    Estime o tempo pelos números dos arquivos de pacote.

    **Substituição 1 — a imagem de VM do colima.** O colima não usa uma cloud image comum do Ubuntu, e sim uma imagem própria
    **com docker pré-instalado** (release asset de `abiosoft/colima-core`), de modo que subir a VM não exige apt para instalar docker,
    contornando o inacessível `download.docker.com`. Baixe você mesmo e passe com `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # verificação: pegue o digest pela API do GitHub. Não pule — isto vai virar uma VM em execução
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    O proxy corta o fluxo no meio (curl 56 na prática); com `-C -` basta retomar algumas vezes.

    **Substituição 2 — o apt dentro da VM.** Mesmo usando a imagem com docker pré-instalado, o script de boot do lima
    `30-install-packages.sh` ainda roda um `apt-get update` para instalar `rsync` —
    batendo em `ports.ubuntu.com` (26 KB/s) e `download.docker.com` (4 KB/s), o que trava por dezenas de minutos.

    Solução (**leia `/mnt/lima-cidata/boot.sh` antes de mexer**: para scripts de boot que falham ele só emite `WARNING` +
    `CODE=1` e segue, e no fim **sempre** escreve `/run/lima-boot-done`, então deixar aquele passo falhar é seguro):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh segue até o fim e escreve a marca de conclusão
    '
    # o colima start então sai normalmente; depois instale o rsync (agora a 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Aproveite e acrescente `127.0.0.1 lima-colima` ao `/etc/hosts` da VM, para eliminar aquela sequência de avisos
    `sudo: unable to resolve host`.

    **Substituição 3 — a imagem base.** O `docker/build` primeiro puxa `python:3.13-slim` de `dockerproxy.net`
    e faz retag, para que o `FROM` do Dockerfile acerte o local. Na prática, `dockerproxy.net` devolve o manifest direto
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` devolvem 401, `hub.rat.dev` 302 e
    `docker.xuanyuan.me` 403.

    **Substituição 4 — apt e pip dentro do contêiner.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) e
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Note que `PIP_INDEX_URL`
    é também uma variável de ambiente que o próprio pip reconhece, então basta declarar o `ARG` para que o pip no RUN a leia —
    funciona mesmo sem escrever `--index-url` explicitamente.

    O preparo único leva, naquelas condições de rede, cerca de 25 minutos, a maior parte nos 364 MB da imagem de VM e nos 95.9 MB
    do wheel do SDK. Depois disso, subir o `flowerbox` é questão de segundos.

## 2. plugin {#plugin}

### O que é um plugin e como o SDK o carrega {#它是什么}

Um **pacote de capacidade de domínio** que viaja com o repositório. O código do framework não contém conhecimento de domínio algum; todo o conhecimento de domínio fica no diretório `plugin/`
na raiz do repositório e é clonado, revisado e tagueado junto com o código.

A ligação do lado do SDK está em `build_options()`, em
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py),
em duas linhas:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Combinado com `setting_sources=[]` (tratado separadamente abaixo), é por isso que o flower consegue ser ao mesmo tempo "[portável](glossary.md#可移植)"
e "conhecedor do seu domínio": ele não pergunta o que está instalado na máquina host, só reconhece este diretório que veio no repositório.

### Layout de diretórios {#目录布局}

| Caminho | O que guarda | Quando vale | Quem decide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | identidade do pacote: `name`, `description`, `version`, `author` | lido uma vez no carregamento | — |
| `plugin/skills/<name>/SKILL.md` | conhecimento de domínio, carregado sob demanda | **probabilístico** — só é usado se o modelo julgar relevante | modelo |
| `plugin/agents/<name>.md` | subagent, janela de contexto própria | delegado pelo modelo, ou indicado explicitamente no [workflow](glossary.md#流程) | modelo / você |
| `plugin/hooks/hooks.json` | intercepta chamadas de ferramenta | **determinístico** — casou, executa | código |
| `plugin/.mcp.json` | conexão de ferramentas externas | registradas como ferramentas, iguais às embutidas | modelo |

**A diferença entre probabilístico e determinístico é o critério de escolha, não uma diferença de palavras:**

- skill é **conhecimento parado ali**. O modelo vê a `description` e só vai lê-lo se achar relevante para a tarefa atual.
  O julgamento de relevância é do modelo, então a mesma frase rodada duas vezes pode usar numa e não usar na outra.
- hook é **código**. Casou o evento, roda, independentemente de o modelo querer ou saber. O [spill](glossary.md#落盘) e a
  [isolation](glossary.md#隔离) do próprio flower são hooks, justamente porque não podem valer "às vezes".

Então o critério é um só: **isto precisa acontecer todas as vezes?** Precisa — escreva um hook. É só "bom saber" —
escreva um skill. Escrever como skill algo que é obrigatório é apostar a disciplina num julgamento pontual do modelo.

Hoje o `plugin/` do repositório tem só duas coisas: `.claude-plugin/plugin.json` e `skills/example/SKILL.md`.
`agents/`, `hooks/` e `.mcp.json` **ainda não existem** — se for usar, crie você mesmo, com os nomes de diretório exatamente como na tabela acima.

### Escrevendo um skill: exemplo completo {#写一个-skill完整例子}

Tomando "gerar notas de versão" como exemplo, do zero até confirmar que está valendo.

**Passo 1: criar o diretório.** O nome do diretório é o nome do skill, e deve bater com o `name` no frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Passo 2: escrever `plugin/skills/release-notes/SKILL.md`.** O nome do arquivo tem de ser `SKILL.md`, em maiúsculas.
O formato é frontmatter YAML + corpo em Markdown, com dois campos no frontmatter:

| Campo | Função |
|---|---|
| `name` | identificador do skill. Igual ao nome do diretório |
| `description` | **o modelo decide usá-lo ou não olhando só esta linha**. Escreva "quando usar", não "o que é" |

Um arquivo mínimo e utilizável:

````markdown
---
name: release-notes
description: Use ao preparar notas de versão. Acione quando o usuário disser "escreva as release notes", "o que mudou nesta versão", "vamos publicar".
---

# Notas de versão

## Como levantar o material

```bash
git describe --tags --abbrev=0        # tag anterior
git log --oneline <上一个 tag>..HEAD   # commits desta versão
```

## Formato de saída

Divida em três blocos, cada um uma lista não ordenada, um item por linha, descrevendo mudanças perceptíveis para o usuário, sem refatorações internas:

- **Novidades** — o que esta versão passa a permitir que antes não dava
- **Correções** — o que foi corrigido, com o sintoma em uma frase
- **Incompatibilidades** — o que precisa ser mexido ao atualizar. Se não houver, omita o bloco inteiro

## Limites

- Não invente o número de versão; leia do campo `version` do `pyproject.toml`.
- Se estiver em dúvida se algum commit é perceptível para o usuário, liste e pergunte, não decida pelo usuário.
````

O corpo não tem formato obrigatório — é apenas um texto que será lido para dentro do contexto. Siga o estilo de
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
deixar claro **quando usar**, os **passos**, **como deve ficar a saída** e **onde estão os limites** rende mais do que empilhar conhecimento de fundo.

**Passo 3: confirmar que foi carregado.** Verifique só uma coisa certa — se o diretório existe ou não:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Só se imprimir `/path/to/flower/plugin True` é que aquele `if` de `build_options()` vai entrar.
Se imprimir `False`, não foi carregado — e **em execução não haverá erro nenhum**, veja o aviso abaixo.

**Não tome "rodar uma frase e ver se o skill `example` foi acionado" como verificação.** Skill é probabilístico: se o modelo não o chamou,
tanto pode ser que não esteja instalado quanto que ele simplesmente não achou necessário para a tarefa — esse sinal não distingue os dois casos. Além disso,
`build_options()` nunca define a opção `skills=` de nível de sessão do SDK; se os skills do plugin realmente aparecem na lista
disponível para o coordinator, isso não foi verificado na prática. O `True`/`False` daquele `PLUGIN_DIR` acima é determinístico; use ele.

Para habilitar skills específicos num [worker](glossary.md#执行者), use `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
o nome é o `name` do `SKILL.md`, e o SDK também aceita a forma qualificada `nome-do-plugin:nome-do-skill`.

!!! warning "A instalação do flower não traz `plugin/` — nenhuma das três formas traz"
    `PLUGIN_DIR` sobe três níveis a partir de `flower/core/agent.py` e entra em `plugin/`. Rodando de um checkout do código-fonte, isso é o
    `plugin/` na raiz do repositório; mas o wheel empacota apenas o diretório `flower` (no `pyproject.toml`,
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), e depois de instalado em site-packages
    `site-packages/plugin` não existe, `PLUGIN_DIR.is_dir()` é falso — **pulado em silêncio, sem erro, sem aviso**.

    **Isso não é um problema do contêiner; o alcance é bem maior.** Todos os caminhos do `install.sh` — `uv tool install`,
    `pipx install`, bootstrap do uv e depois uso do uv, e o fallback `pip install --user` — instalam o wheel.
    Ou seja, **no flower instalado por uma linha de comando, o pacote de capacidade de domínio não funciona, silenciosamente**. O contêiner é só mais uma instância do mesmo problema:
    o `docker/Dockerfile` só faz `COPY` de `pyproject.toml`, `flower/` e `examples/`; `plugin/` não entra na imagem.

    Registrado na [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Depois de instalar, rode aquele comando
    `PLUGIN_DIR` acima para checar: se sair `False`, esta instalação não tem pacote de capacidade de domínio. Para usá-lo,
    por enquanto só rodando de um checkout do código-fonte.

### Por que `setting_sources=[]` obriga a capacidade de domínio a passar pelo plugin {#setting_sources-为什么逼着领域能力走-plugin}

Na mesma função há também esta linha:

```python
"setting_sources": [] if portable else ["project"],
```

O padrão do SDK é `None` = ler as três origens: `~/.claude/settings.json` (usuário),
`.claude/settings.json` (projeto) e `.claude/settings.local.json` (local). O flower passa `[]` por padrão,
**desligando todas**.

| | Lê? | Consequência |
|---|---|---|
| `~/.claude/` (máquina host) | não | comportamento igual ao trocar de máquina, sem resultado diferente por "nesta aqui eu configurei" |
| `.claude/` do projeto | não | o que estiver em `.claude/skills/`, `.claude/agents/` **não vale nada** sob o flower |
| `plugin/` | sim | caminho fixo no código, viaja com o repositório |
| credenciais | não passam por aqui | é preciso trazer o `.env`; os blocos `env` de `~/.claude/settings.json` e `settings.local.json` só servem de último fallback e **só rendem 9 chaves de credencial**, veja [Configuração](config.md) |

O `.claude/` não valer **não é configuração esquecida, é a definição dessa restrição**: bastaria ler um byte da máquina host para que "comportamento igual ao trocar de máquina"
deixasse de valer. Sobra então um único canal para a capacidade de domínio — o `plugin/` que viaja com o repositório.

Duas chaves (ambas em `build_options()`, com os padrões já na configuração portável):

| Parâmetro | Padrão | O que muda se você alterar |
|---|---|---|
| `portable` | `True` | passar `False` → `setting_sources` vira `["project"]`, e o `.claude/` do projeto passa a ser lido (do lado do SDK: para ler `CLAUDE.md` é obrigatório conter `"project"`). A portabilidade se perde junto |
| `use_plugin` | `True` | passar `False` → o `plugin/` não é montado de forma alguma, e a capacidade de domínio depende só de `AgentSpec.instructions` |

De passagem: `instructions` usa [append](glossary.md#叠加) (`append` do `system_prompt`),
que é um canal diferente do plugin — o primeiro está no contexto em toda rodada, o segundo é carregado sob demanda. Disciplina curta e obrigatória vai em `instructions`;
conhecimento longo e usado de vez em quando vai em skill.

## 3. Site de documentação {#三文档站}

O site que você está lendo é feito com mkdocs-material; os arquivos-fonte estão em `docs/` no repositório, e um push para `main` publica sozinho.

| Etapa | O que é |
|---|---|
| configuração | `mkdocs.yml`, `docs_dir: docs` |
| multilíngue | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`… idioma padrão `zh` |
| dependências | `docs-requirements.txt` (versões travadas). **Não** o extra `docs` do `pyproject.toml` — o CI instala o primeiro |
| build | `mkdocs build --strict`. Links internos quebrados ou nav apontando para páginas inexistentes fazem o build falhar, em vez de publicar um 404 em silêncio |
| redirecionamentos | `hooks/redirects.py`, **depois** do build, escreve páginas-ponte com meta-refresh pelas URLs finais, ligando os antigos endereços planos (`/start/`, `/workflow/`, `/case-ht001/`…) às novas posições |
| deploy | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publicando no GitHub Pages |

Editando a documentação localmente:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # preview local
mkdocs build --strict         # rode antes de commitar, é o mesmo comando do CI
```

O CI dispara em push para `main` **e** desde que as mudanças toquem estes caminhos; além disso dá para acionar
`workflow_dispatch` manualmente na página de Actions:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Por que o `install.sh` é publicado pelo Pages {#installsh-为什么从-pages-发}

No fim da etapa de build há esta linha:

```yaml
- run: cp install.sh site/install.sh
```

O script de instalação é enfiado no artefato do site e, com isso, fica pendurado no domínio da documentação; a instalação em uma linha fica assim:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

O motivo é bem prático: **`raw.githubusercontent.com` não passa na China, enquanto `*.github.io` passa** (medido).
O script em si fica na raiz do repositório; na publicação só é copiado mais uma vez — não é preciso manter duas cópias de conteúdo nem uma CDN extra.

O que o próprio `install.sh` faz: escolher um instalador de ferramentas Python (`uv` > `pipx` > instalar `uv` > `pip --user`),
instalar o flower a partir do GitHub e indicar o próximo passo. Ele **não toca em credenciais** — na primeira execução o `flower` pergunta e guarda em
`~/.config/flower/.env`.
