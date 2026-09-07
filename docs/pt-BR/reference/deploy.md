# Deploy e extensão

Levar o flower para outro lugar exige lidar com três coisas: container (cercar o Bash irrestrito e, de quebra, verificar a frase "sem depender da CLI"),
[plugin](glossary.md#plugin) (a capacidade de domínio viaja com o repositório, sem depender do que está instalado na máquina host) e o site de documentação (empurrou para `main`,
publica sozinho; o `install.sh` fica pendurado no domínio do Pages). As três seções são independentes; leia conforme a necessidade.

## 1. Container

### Por que container

**Primeiro, para cercar.** O [worker](glossary.md#执行者) que faz o trabalho tem **Bash irrestrito** — a allowlist de Bash
do flower (`delegate_guard`) só vale para a [thread principal](glossary.md#主线程); quem é despachado precisa poder rodar testes, então isso é intencional.
No container só o diretório do seu projeto é montado; o código-fonte do framework fica em `/opt/flower` dentro da imagem, e o resto do host não é visível.

**Segundo, o container é em si a verificação daquela restrição de [portabilidade](glossary.md#可移植).** Na imagem não há Claude Code CLI,
não há Node, só Python e o `claude-agent-sdk` — as requisições saem pelo binário nativo que vem no wheel.
Se roda aqui, "sem depender da CLI" deixa de ser uma afirmação no papel.

Verificado na prática (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| O que foi verificado | Resultado |
|---|---|
| Existe CLI na imagem? | `claude`, `node`, `npm`, `npx` **nenhum existe** |
| Binário embutido | `\177ELF` (207M) |
| Requisição real | enviada via `cloud.infini-ai.com/maas` e resposta recebida, `$0.1741 / 1 turno` (esse é o piso de um único turno com Opus 5 + janela de 1M) |
| Propriedade dos arquivos | arquivos escritos em `/work` dentro do container aparecem como `hechenyu:staff` no host; mapeamento correto |
| Visibilidade do host | dentro do container, `ls /Users` → `No such file or directory` |

### O que está instalado na imagem

Imagem base `python:3.13-slim`, e em cima dela o apt instala apenas três pacotes. Cada um tem um motivo:

| O que | Por quê |
|---|---|
| `python:3.13-slim` | só precisa de Python ≥ 3.10. Sem Node, sem a CLI claude |
| `git` | `--isolate` precisa dar um worktree para cada [subagent](glossary.md#subagent) |
| `ca-certificates` | o gateway é HTTPS |
| `libstdc++6` | o binário que vem com o SDK é um arquivo único compilado com Bun; no Linux ele precisa disso, e a imagem slim não traz |

O código-fonte do framework entra na imagem via `COPY`, **não por bind mount** — por isso o agent dentro do container não alcança o código-fonte do framework no host:

| Caminho na imagem | Conteúdo | Vem de |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, e aqui roda `pip install .` | `COPY` |
| `/work` | diretório de trabalho (`WORKDIR`), em tempo de execução monta o `$PWD` do host | `docker run -v` |

O entrypoint é `ENTRYPOINT ["flower"]` e o `CMD` está vazio — rodar o container sem argumentos cai na entrada interativa
(ele pergunta o que você quer fazer) em vez de imprimir `--help`. Assim não é preciso colocar aspas em uma frase de pedido em linguagem natural no shell.

### Por que não dá para montar o `.venv` do host

O SDK publica wheels por plataforma, e o binário embutido é específico da plataforma:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Montado, não roda; por isso a imagem precisa fazer seu próprio `pip install`. Visto por outro ângulo, isso é prova de portabilidade: o mesmo
`pyproject.toml`, troca de plataforma, troca o binário nativo, e o código do framework não muda uma linha.

### Os dois scripts

| Script | O que faz |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | constrói a imagem. `cd` para a raiz do repositório, `docker build -f docker/Dockerfile -t flower-box .`; com `FLOWER_MIRRORS=1` (padrão) puxa antes o `python:3.13-slim` de um espelho de registry, faz retag, e passa os `--build-arg` de pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | roda uma vez. Checa o arquivo de credenciais → checa se o `$PWD` pode ser montado → detecta se há TTY → `docker run` |

As chaves do `docker/build`, todas por variável de ambiente:

| Variável | Padrão | Semântica |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | tag da imagem |
| `FLOWER_MIRRORS` | `1` | `0` = não troca nenhum espelho, tudo vai para o upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | puxa a imagem base daqui e faz retag para `python:3.13-slim`, para o `FROM` acertar o cache local |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | passado como `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | passado como `--build-arg APT_MIRROR` |

As três últimas só têm efeito com `FLOWER_MIRRORS=1` — o ramo `FLOWER_MIRRORS=0` simplesmente não define build-arg nenhum.

O `docker/flowerbox` reconhece duas:

| Variável | Padrão | Semântica |
|---|---|---|
| `FLOWER_HOME` | um nível acima da posição do próprio script (ou seja, a raiz do repositório) | onde procurar o `.env`. Se não achar `$FLOWER_HOME/.env`, sai com 1 |
| `FLOWER_IMAGE` | `flower-box` | qual imagem rodar |

O `FLOWER_HOME` é deduzido da posição do próprio script, sem caminho fixo no código, então o repositório funciona clonado em qualquer lugar.

### Rodando

```bash
docker/build                       # 一次就够
cd ~/任意项目目录                   # 必须在 $HOME 下面,见下面的挂载边界
/path/to/flower/docker/flowerbox   # 不带参数 → 它问你要做什么,不用打引号
```

Se a rede até pypi.org / Docker Hub estiver normal, o build fica assim:

```bash
FLOWER_MIRRORS=0 docker/build
```

Os argumentos do `flowerbox` são exatamente os do `flower` — ele repassa `"$@"` tal e qual depois do `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout segundos`, `--isolate`, `-v`, todos valem; a tabela completa está na [linha de comando](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

O que de fato roda é esta linha (o `-t` só entra quando há TTY, veja abaixo):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Fronteira de montagem e persistência

```text
宿主 $PWD  ──挂载──>  /work       ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

Por isso rodar dentro de um subdiretório do próprio repositório, como `flower/human-test/HT001`, também é seguro: só o `HT001` é montado,
e o código-fonte do framework está fora do escopo da montagem.

| Coisa | Sobrevive à saída? | Por quê |
|---|---|---|
| tudo sob o `$PWD` do host, incluindo `runs/` e o [workbench](glossary.md#工作台) `.flower/` | sim | é justamente o diretório montado como `/work` |
| o que foi escrito em outros caminhos dentro do container | não | `--rm`, o container é apagado ao sair |
| credenciais | não entram nas camadas da imagem | vão por `--env-file`; o `.dockerignore` exclui o `.env`, então nem um `COPY . .` levaria |

!!! danger "O diretório do projeto precisa estar sob `$HOME`, senão os artefatos somem em silêncio"
    **Por padrão o colima só monta `$HOME` dentro da VM** (`mount | grep virtiofs` → `mount0 on /Users/<你>`).
    Rodando em lugares como `/tmp`, o `-v` cria um **diretório vazio** dentro da VM, e o que for escrito ali o host nunca vê,
    **e nada é reportado como erro** — artefatos, [brief](glossary.md#需求确认书), `runs/`, tudo perdido. Já aconteceu aqui:
    um `once` terminou, $0.17 gastos, e o `runs/` simplesmente não existia no host.

    O `flowerbox` agora barra esse caso: se o `$PWD` está sob `$HOME`, passa direto; se não está, ele escreve um
    arquivo de sonda no `$PWD` e sobe um container para testar `test -f /work/<探针>` de fato (montagens extras configuradas também passam). Se não passar, sai com 1
    e te diz `colima start --mount '<路径>:w'`. A sonda precisa subir um container, então rode `docker/build` antes.

### Credenciais

Vão por `docker run --env-file`, **não entram nas camadas da imagem**. O `flowerbox` lê o `$FLOWER_HOME/.env`,
que por padrão é o `.env` da raiz do repositório:

```bash
cp .env.example .env       # 填 token;.env 已被 gitignore
```

Atenção: o `flower setup` escreve em `~/.config/flower/.env`, e **o `flowerbox` não olha para esse caminho**.
Se você já configurou com o `setup` e não quer manter uma segunda cópia, aponte o `FLOWER_HOME` para lá:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Nomes de chave, precedência e como preencher o gateway estão em [configuração](config.md).

!!! warning "Sem TTY, as perguntas travam até o `--timeout`"
    O `flowerbox` só adiciona `-t` quando `[ -t 0 ]` — `docker run -t` em pipe / CI reclama na hora com
    "the input device is not a TTY"; o `-i` é sempre necessário, senão o stdin nem chega lá dentro.

    As respostas às perguntas passam pela entrada padrão. Sem TTY, o `input()` já lança `EOFError` na primeira vez → a pergunta atual é tratada como
    "entrada fechada" e pulada, e **a thread de resposta encerra**, de modo que da segunda pergunta em diante não há ninguém para atender e só resta esperar
    o `--timeout` inteiro (padrão 1800 segundos). Para execução desassistida, use `--timeout 0` explicitamente. Quando detecta ausência de TTY, o script
    imprime antes uma linha de aviso.

### git submodule

No `.gitmodules` só existe uma entrada:

| path | url | o que é |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | o repositório de código **produzido** por aquele run do [HT001](../cases/ht001.md), guardado como registro |

Um `git clone` comum não puxa isso, e `human-test/HT001` fica como um diretório vazio (o `-` na frente no `git submodule status` é exatamente esse estado).
Precisa se importar com ele?

| O que você quer fazer | Precisa inicializar? |
|---|---|
| rodar o flower, construir a imagem | **não**. O `.dockerignore` exclui `human-test/`, e o `Dockerfile` de qualquer forma só faz `COPY` de `pyproject.toml` / `flower` / `examples` |
| ler localmente o código produzido no HT001 | sim: `git submodule update --init human-test/HT001`, ou já clonar com `git clone --recurse-submodules` |

### Rede na China: por que toda aquela troca de espelhos

Instalar isso atrás do firewall não é lento por banda, é lento pela rota internacional. O `docker/build` padrão já troca o que precisa ser trocado,
e `FLOWER_MIRRORS=0` desliga tudo de uma vez. Abaixo estão os números medidos e o porquê das quatro substituições — se sua rede não tem esse problema, não precisa ler.

??? note "Tabela de velocidades medidas e as quatro substituições (2026-09-06, macOS/arm64)"

    | Origem | Velocidade |
    |---|---|
    | `pypi.org` (índice) | 32 KB/s |
    | `files.pythonhosted.org` (arquivos de pacote) | **284 B/s** |
    | `github.com` (asset de release, direto) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (dentro da VM) | 26 KB/s |
    | `download.docker.com` | **inacessível** (HTTP 000); dentro da VM 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **inacessível** |
    | `mirrors.aliyun.com/pypi` (**arquivos de pacote**) | 1.4 MB/s (host) / 152 KB/s (dentro da VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (dentro da VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (proxy do GitHub) | **2.5 MB/s** |
    | `gh-proxy.com` (proxy do GitHub) | 1.5 MB/s |
    | `dockerproxy.net` (proxy do Docker Hub) | funciona (devolve o manifest direto) |

    Ao medir, não confunda a **página de índice** com os arquivos de pacote: aquela página de `mirrors.aliyun.com/pypi/simple/` dá 7.4 MB/s,
    enquanto o wheel real de 95.9 MB dá só 1.4 MB/s (152 KB/s dentro da VM — a rede em espaço de usuário do colima tem perda).
    Estime o tempo pelos números dos arquivos de pacote.

    **Substituição 1 — a imagem de VM do colima.** O colima não usa uma cloud image comum do Ubuntu, e sim uma imagem própria
    **com docker pré-instalado** (asset de release de `abiosoft/colima-core`), então subir a VM não exige instalar docker via apt,
    o que contorna o inacessível `download.docker.com`. Baixe você mesmo e entregue com `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 校验:digest 从 GitHub API 拿。别跳过 —— 这是要当 VM 跑的东西
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    O proxy corta no meio do caminho (curl 56, medido); com `-C -` é só retomar e repetir algumas vezes.

    **Substituição 2 — o apt dentro da VM.** Mesmo usando a imagem com docker pré-instalado, o script de boot do lima
    `30-install-packages.sh` ainda roda um `apt-get update` para instalar `rsync` —
    batendo em `ports.ubuntu.com` (26 KB/s) e `download.docker.com` (4 KB/s), o que trava por dezenas de minutos.

    Tratamento (**leia `/mnt/lima-cidata/boot.sh` antes de mexer**: para scripts de boot que falham ele só emite `WARNING` +
    `CODE=1` e segue, e no fim **sempre** escreve `/run/lima-boot-done`, então fazer aquele passo falhar é seguro):

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
      pkill -f "apt-get update"          # boot.sh 会继续走完并写完成标记
    '
    # colima start 随即正常退出;之后补上 rsync(现在 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Já aproveite e adicione `127.0.0.1 lima-colima` ao `/etc/hosts` da VM, para matar aquela série de avisos `sudo: unable to resolve host`.

    **Substituição 3 — a imagem base.** O `docker/build` primeiro puxa `python:3.13-slim` de `dockerproxy.net`
    e faz retag, para o `FROM` do Dockerfile acertar o local. Medido: `dockerproxy.net` devolve o manifest direto
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` devolvem 401, `hub.rat.dev` 302,
    `docker.xuanyuan.me` 403.

    **Substituição 4 — apt e pip dentro do container.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) e
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Note que `PIP_INDEX_URL`
    também é uma variável de ambiente que o próprio pip reconhece, então basta declarar o `ARG` para o pip dentro do RUN lê-la —
    funciona sem escrever `--index-url` explicitamente.

    O preparo único, naquelas condições de rede, leva cerca de 25 minutos, e o grosso é a imagem de VM de 364 MB e o wheel de 95.9 MB
    do SDK. Depois disso, subir o `flowerbox` é questão de segundos.

## 2. plugin {#plugin}

### O que é

Um **pacote de capacidade de domínio** que viaja com o repositório. O código do framework não contém nenhum conhecimento de domínio; todo o conhecimento de domínio fica no diretório
`plugin/` na raiz do repositório, e é clonado junto com o código, revisado junto e tagueado junto.

A ligação do lado do SDK está em
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py),
dentro de `build_options()`, em duas linhas:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Junto com `setting_sources=[]` (tratado à parte abaixo), é isso que permite ao flower ser ao mesmo tempo "[portátil](glossary.md#可移植)"
e "entender o seu domínio": ele não pergunta o que está instalado na máquina host, só reconhece esse único diretório que veio com o repositório.

### Layout de diretórios

| Caminho | O que guarda | Quando entra em ação | Quem decide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | identidade do pacote: `name`, `description`, `version`, `author` | lido uma vez no carregamento | — |
| `plugin/skills/<name>/SKILL.md` | conhecimento de domínio, carregado sob demanda | **probabilístico** — só é usado se o modelo julgar relevante | modelo |
| `plugin/agents/<name>.md` | subagent, janela de contexto própria | delegação do modelo, ou indicação explícita no [workflow](glossary.md#流程) | modelo / você |
| `plugin/hooks/hooks.json` | interceptação de chamadas de ferramenta | **determinístico** — casou, executa | código |
| `plugin/.mcp.json` | integração de ferramentas externas | registradas como ferramentas, iguais às nativas | modelo |

**A diferença entre probabilístico e determinístico é o critério de escolha, não uma questão de redação:**

- skill é **conhecimento posto ali**. O modelo vê a `description` e só vai ler se achar que tem a ver com a tarefa atual.
  O julgamento de relevância é do modelo, então a mesma frase rodada duas vezes pode usar numa e não usar na outra.
- hook é **código**. Casou o evento, roda, independente do que o modelo quer ou sabe. O [spill](glossary.md#落盘) e o
  [isolamento](glossary.md#隔离) do próprio flower são hooks, justamente porque não podem "às vezes funcionar".

Então o critério é um só: **isso precisa acontecer todas as vezes?** Precisa — escreva um hook. É só "bom saber" —
escreva um skill. Escrever como skill algo que é obrigatório é apostar a disciplina num julgamento pontual do modelo.

Hoje o `plugin/` no repositório tem só duas coisas: `.claude-plugin/plugin.json` e `skills/example/SKILL.md`.
`agents/`, `hooks/` e `.mcp.json` **ainda não existem** — se for usar, crie você mesmo, com os nomes de diretório exatamente como na tabela acima.

### Escrevendo um skill: exemplo completo

Tomando "gerar notas de release" como exemplo, do zero até confirmar que está ativo.

**Passo 1: crie o diretório.** O nome do diretório é o nome do skill, e deve bater com o `name` do frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Passo 2: escreva `plugin/skills/release-notes/SKILL.md`.** O nome do arquivo tem que ser `SKILL.md`, em maiúsculas.
O formato é frontmatter YAML + corpo em Markdown, com dois campos no frontmatter:

| Campo | Função |
|---|---|
| `name` | identificador do skill. Igual ao nome do diretório |
| `description` | **o modelo escolhe ou não com base só nesta linha**. Diga "quando usar", não "o que é" |

Um arquivo mínimo pronto para uso:

````markdown
---
name: release-notes
description: Use ao montar notas de release. Quando o usuário disser "escreva as release notes", "o que mudou nesta versão", "vamos publicar", use isto.
---

# Notas de release

## Como levantar o material

```bash
git describe --tags --abbrev=0        # tag anterior
git log --oneline <tag anterior>..HEAD   # commits desta versão
```

## Formato de saída

Divida em três blocos, cada bloco uma lista não ordenada, um item por linha, escrevendo mudanças que o usuário percebe, sem refatoração interna:

- **Novidades** — o que esta versão faz que antes não dava para fazer
- **Correções** — o que foi corrigido, com o sintoma em uma frase
- **Quebras de compatibilidade** — o que precisa ser mudado à mão ao atualizar. Se não houver, omita o bloco inteiro

## Limites

- Não invente o número de versão; leia do campo `version` do `pyproject.toml`.
- Se não tiver certeza se um commit é perceptível para o usuário, liste e pergunte, não decida pelo usuário.
````

Não há formato obrigatório para o corpo — é apenas um texto que será lido para dentro do contexto. Siga o estilo de
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
deixar claro **quando usar**, os **passos**, **como deve ser a saída** e **onde estão os limites** é mais útil do que empilhar conhecimento de fundo.

**Passo 3: confirme que foi carregado.** Verifique só uma coisa determinística — se o diretório existe:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Só imprimindo `/path/to/flower/plugin True` é que aquele `if` do `build_options()` entra.
Se imprimir `False`, não foi carregado — e **em tempo de execução não haverá erro nenhum**, veja o aviso abaixo.

**Não use "rodar uma frase e ver se o skill `example` foi acionado" como verificação.** Skill é probabilístico: se o modelo não chamou,
tanto pode ser que não esteja instalado quanto que ele simplesmente não achou necessário para a tarefa — esse sinal não distingue as duas coisas. Além disso,
o `build_options()` nunca define a opção `skills=` de nível de sessão do SDK; se os skills do plugin aparecem ou não na lista de opções do
coordenador nunca foi medido. Aquele `True`/`False` do `PLUGIN_DIR` acima é determinístico; use ele.

Para nomear quais skills abrir para um determinado [worker](glossary.md#执行者), use `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
o nome é o `name` do `SKILL.md`, e o SDK também aceita a forma qualificada `nome-do-plugin:nome-do-skill`.

!!! warning "O flower instalado não tem `plugin/` — nenhuma das três formas de instalação tem"
    O `PLUGIN_DIR` sobe três níveis a partir de `flower/core/agent.py` e entra em `plugin/`. Rodando a partir de um checkout do código-fonte, isso é o
    `plugin/` da raiz do repositório; mas o wheel empacota apenas o diretório `flower` (no `pyproject.toml`,
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), então depois de instalado em site-packages
    `site-packages/plugin` não existe e `PLUGIN_DIR.is_dir()` é falso — **pula em silêncio, sem erro e sem aviso**.

    **Isso não é um problema do container; o alcance é bem maior.** Todos os caminhos do `install.sh` — `uv tool install`,
    `pipx install`, bootstrap do uv e depois uv, e o fallback `pip install --user` — instalam o wheel.
    Ou seja, **no flower instalado com uma linha, o pacote de capacidade de domínio falha silenciosamente, sempre**. O container é só uma instância do mesmo problema:
    o `docker/Dockerfile` só faz `COPY` de `pyproject.toml`, `flower/` e `examples/`; o `plugin/` não entra na imagem.

    Registrado na [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Depois de instalar, rode antes aquele comando do
    `PLUGIN_DIR` para se autoverificar: se imprimir `False`, esta instalação está sem o pacote de capacidade de domínio. Para usar o pacote de capacidade de domínio,
    hoje só rodando a partir de um checkout do código-fonte.

### Por que `setting_sources=[]` obriga a capacidade de domínio a passar pelo plugin

Na mesma função há também esta linha:

```python
"setting_sources": [] if portable else ["project"],
```

O padrão do SDK é `None` = ler as três origens: `~/.claude/settings.json` (usuário),
`.claude/settings.json` (projeto) e `.claude/settings.local.json` (local). O flower passa `[]` por padrão,
**desligando todas**.

| | Lê? | Consequência |
|---|---|---|
| `~/.claude/` (máquina host) | não | o comportamento é o mesmo em outra máquina; o resultado não muda porque "nesta aqui eu configurei" |
| `.claude/` do projeto | não | o que estiver em `.claude/skills/`, `.claude/agents/` **não vale nada** sob o flower |
| `plugin/` | sim | caminho fixo no código, viaja com o repositório |
| credenciais | não passam por aqui | precisa trazer o próprio `.env`; os blocos `env` de `~/.claude/settings.json` e `settings.local.json` servem só como último fallback e **só 9 chaves de credencial são lidas**, veja [configuração](config.md) |

O `.claude/` não valer **não é configuração esquecida, é a definição dessa restrição**: bastando ler um byte da máquina host, "mesmo comportamento em outra máquina"
deixa de valer. A capacidade de domínio tem, então, um único canal — o `plugin/` que viaja com o repositório.

Duas chaves (ambas em `build_options()`, com os valores padrão sendo os da portabilidade):

| Parâmetro | Padrão | O que muda ao alterar |
|---|---|---|
| `portable` | `True` | passando `False` → `setting_sources` vira `["project"]` e passa a ler o `.claude/` do projeto (lado do SDK: para ler `CLAUDE.md` é obrigatório conter `"project"`). A portabilidade cai junto |
| `use_plugin` | `True` | passando `False` → o `plugin/` não é montado de forma alguma, e a capacidade de domínio depende inteiramente de `AgentSpec.instructions` |

De passagem: `instructions` vai por [append](glossary.md#叠加) (o `append` do `system_prompt`),
que é um canal diferente do plugin — o primeiro está no contexto a cada turno, o segundo é carregado sob demanda. Disciplina curta e obrigatória vai em `instructions`;
conhecimento longo e ocasionalmente útil vai em skill.

## 3. Site de documentação

O site que você está lendo é feito com mkdocs-material; os arquivos-fonte estão em `docs/` no repositório, e um push para `main` publica sozinho.

| Etapa | O que é |
|---|---|
| Configuração | `mkdocs.yml`, `docs_dir: docs` |
| Multi-idioma | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`… idioma padrão é `zh` |
| Dependências | `docs-requirements.txt` (versões fixadas). **Não é** o extra `docs` do `pyproject.toml` — o CI instala o primeiro |
| Build | `mkdocs build --strict`. Link interno quebrado, ou nav apontando para página inexistente, faz o build falhar direto, em vez de publicar um 404 em silêncio |
| Redirecionamentos | `hooks/redirects.py`, **depois** do build, escreve páginas-stub de meta-refresh conforme as URLs finais, ligando os endereços planos antigos (`/start/`, `/workflow/`, `/case-ht001/`…) às novas posições |
| Deploy | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publicando no GitHub Pages |

Editando a documentação localmente:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # 本地预览
mkdocs build --strict         # 提交前跑一遍,和 CI 同一条命令
```

O CI dispara com push para `main` **e** mudanças que casem com estes caminhos; além disso, dá para acionar manualmente
via `workflow_dispatch` na página de Actions:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Por que o `install.sh` é publicado pelo Pages

No fim da etapa de build há esta linha:

```yaml
- run: cp install.sh site/install.sh
```

O script de instalação é enfiado no artefato do site e, com isso, fica pendurado no domínio da documentação; a instalação em uma linha fica assim:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

O motivo é bem prático: **`raw.githubusercontent.com` é inacessível na China, e `*.github.io` funciona** (medido).
O script em si fica na raiz do repositório; na publicação só é copiado mais uma vez — não é preciso manter dois conteúdos, nem uma CDN adicional.

O que o próprio `install.sh` faz: escolhe um instalador de ferramentas Python (`uv` > `pipx` > instalar `uv` > `pip --user`),
instala o flower a partir do GitHub e indica o próximo passo. Ele **não toca em credenciais** — o primeiro `flower` pergunta e salva em
`~/.config/flower/.env`.
