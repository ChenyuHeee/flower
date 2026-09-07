# Installation

Installer flower ne demande que Python ≥ 3.10. Il n'y a qu'une seule dépendance d'exécution,
`claude-agent-sdk` — le binaire natif qui émet les requêtes est déjà dans sa wheel, donc **pas besoin
d'installer Node, ni le CLI Claude Code**. Cette page fait le parcours complet depuis zéro :
installation en une ligne, installation depuis les sources, première configuration des identifiants,
et une commande qui prouve que « c'est bien installé ». Une fois que ça tourne, passez au
[Démarrage rapide](quickstart.md).

## Avant d'installer : vérifier Python

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Une sortie du genre `True 3.13.7` suffit. Si ça affiche `False` ou s'il n'y a pas de `python3` du
tout, installez-le d'abord (`brew install python` / `apt install python3`), sinon le script
d'installation s'arrête immédiatement.

| Nécessaire | Pas nécessaire |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5` ; `install.sh:22-31` le revérifie) | Node.js |
| Un accès réseau vers le point de terminaison de l'API | Le CLI Claude Code |
| Une API key ou un token de passerelle (à fournir après l'installation) | Les réglages dans le `~/.claude/` de la machine (les identifiants sont la seule exception, voir plus bas) |

Nom du paquet `flower`, version `0.1.0`, unique dépendance d'exécution `claude-agent-sdk>=0.2.152`
(`pyproject.toml:2-6`). `mkdocs-material` ne sert qu'à construire le site de documentation en CI ;
faire tourner flower n'en a pas besoin.

## Installation en une ligne

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Une fois l'installation terminée, le terminal devrait ressembler à ça (couleurs en moins) :

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

L'essentiel est la ligne `== 装好了 <chemin absolu>` — c'est le résultat d'un `command -v flower`
que le script exécute lui-même (`install.sh:60-61`). Si un chemin s'affiche, c'est que `flower` est
bien dans le PATH.

### Ce que fait réellement l'installateur

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) ne fait que trois choses :
choisir un installateur d'outils Python, installer depuis GitHub, et vous dire quoi faire ensuite.
**Il ne touche pas à un seul octet de vos identifiants** (`install.sh:7-8`). La source d'installation
est figée sur `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

L'installateur essaie dans l'ordre et s'arrête à la première option qui marche (`install.sh:33-57`) :

| Ordre | Condition de déclenchement | Commande réelle | Où atterrit l'exécutable |
|---|---|---|---|
| 1 | `uv` est dans le PATH | `uv tool install --force <REPO>` | Le répertoire tool bin de uv, en général `~/.local/bin/flower` |
| 2 | Pas de `uv`, mais `pipx` présent | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Ni l'un ni l'autre | D'abord `curl -LsSf https://astral.sh/uv/install.sh \| sh` pour installer uv, puis retour au cas 1 | Comme au cas 1 |
| 4 | uv n'a pas pu être installé au cas 3 | `python3 -m pip install --user --upgrade <REPO>` | Le répertoire de scripts utilisateur — **ce n'est pas `~/.local/bin` sur macOS** |

Les quatre cas installent le même console script : `flower = "flower.cli:main"` (`pyproject.toml:12`).
Une fois installé, on peut aussi l'appeler via `python -m flower.cli`, c'est équivalent
(`cli.py:1263-1264`).

!!! warning "Relancer le script d'installation écrase de force, sans demander confirmation"
    Les trois commandes d'installation portent respectivement `--force`, `--force`, `--upgrade`
    (`install.sh:37`, `:40`, `:54`). Relancer le script écrase directement l'installation
    existante — c'est exactement comme ça qu'on met à jour, mais ne comptez pas sur lui pour vous
    poser la question.

### Comment la commande `flower` arrive dans le PATH

Quand `command -v flower` ne trouve rien, le script suggère d'ajouter `$HOME/.local/bin` à
`~/.zshrc` ou `~/.bashrc` (`install.sh:62-70`) :

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` et `pipx install` déposent tous deux ici, donc le conseil est correct pour eux.
**Mais pas forcément pour le cas 4 (`pip install --user`)** — le répertoire de ce message est codé
en dur, alors que le répertoire de scripts utilisateur de pip dépend de la plateforme. Sur macOS,
c'est `~/Library/Python/3.13/bin`. Vérifiez vous-même :

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Sortie par exemple `/Users/you/Library/Python/3.13/bin` — ajoutez ce répertoire-là au PATH plutôt
que `~/.local/bin`, puis rouvrez le terminal ou faites un `source`.

## Installation depuis les sources

Si vous voulez lire le code, modifier le framework, ou lancer les vérifications hors-ligne de
`tests/`, installez depuis les sources :

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Après ça, `.venv/bin/flower --help` doit afficher les quelques lignes d'usage.

Le shebang de l'exécutable dans le venv est un **chemin absolu**, donc inutile d'activer quoi que ce
soit : un lien symbolique suffit pour l'utiliser depuis n'importe quel répertoire :

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Si `~/.local/bin` est dans le PATH, taper `flower` depuis n'importe quel répertoire de projet
passera par l'interpréteur de ce venv et par ces sources-là.

L'installation depuis les sources ajoute un emplacement d'identifiants supplémentaire : **le `.env`
à la racine du dépôt** (5ᵉ dans l'ordre de recherche, voir
[Configuration · Ordre de priorité de recherche des identifiants](../reference/config.md#凭证查找优先级)).
En développement :

```bash
cp .env.example .env        # remplir ANTHROPIC_AUTH_TOKEN
```

`.env` est déjà ignoré par `.gitignore`, il n'entrera pas dans le dépôt. Un flower installé par
pip / pipx / uv **n'a pas** cet emplacement — il vit dans site-packages, il n'y a pas de « racine de
dépôt » — donc ces modes d'installation doivent utiliser le fichier d'identifiants global décrit
ci-dessous.

## Premier lancement : configurer les identifiants

Les trois points d'entrée qui lancent vraiment un run — `go`, `run`, `once` — appellent tous
`ensure_credentials()` au démarrage (`cli.py:1013`, `:981`, `:1046`), avec deux contrôles :

1. **Existent-ils** — parcours de l'ordre de priorité ; s'il ne trouve rien, il vous demande sur
   le champ.
2. **Fonctionnent-ils** — une vraie requête à l'API. Une requête minimale avec `max_tokens=16`
   (`env.py:120-123`), quasiment gratuite. Un token expiré ou une adresse de passerelle mal écrite
   ne se détectent pas en regardant les variables d'environnement ; sans cette sonde, ça explose
   plusieurs minutes plus tard.

Sans identifiants, le premier `flower` s'arrête sur cet écran (`cli.py:1179-1209`) :

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

La question 1 est obligatoire ; la laisser vide affiche en rouge `没给 token,取消。` puis quitte.
Les questions 2 et 3 acceptent un simple retour chariot. Avec le point de terminaison officiel,
laissez la question 2 vide ; pour une passerelle tierce, indiquez son adresse racine, **sans `/v1`**
— la sonde de flower tape sur `<BASE_URL>/v1/messages` (`env.py:162`).

Les clés écrites en fonction de vos réponses (`cli.py:1199-1207`) :

| Ce que vous saisissez | Clé écrite dans `.env` |
|---|---|
| Token commençant par `sk-ant-` | `ANTHROPIC_API_KEY` |
| Autre token | `ANTHROPIC_AUTH_TOKEN` |
| Adresse de passerelle non vide | `ANTHROPIC_BASE_URL` |
| Nom de modèle non vide | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` **écrites toutes les trois ensemble** |

Le fichier se trouve en `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), il est
**réécrit intégralement**, puis passé en `chmod 0o600` (`cli.py:1157-1168`). C'est le fichier du
« configurer une fois, valable partout » — plus besoin de reconfigurer en changeant de répertoire de
projet. Le sens de chaque variable est décrit dans
[Configuration](../reference/config.md#环境变量).

### Si Claude Code est déjà installé sur la machine, il ne posera peut-être aucune question

La recherche d'identifiants a un **dernier repli** : lire `~/.claude/settings.json`, puis
`~/.claude/settings.local.json`, et récupérer 9 clés d'identifiants dans leur bloc `env`
(`env.py:56-75`, `:109-111`). Qui a déjà configuré Claude Code sur sa machine peut lancer `flower`
directement et se mettre au travail : l'écran de configuration n'apparaît jamais — c'est exactement
ce qu'annonce `install.sh:77`.

!!! warning "La phrase du produit « flower ne lit pas ~/.claude/settings.json » est fausse"
    Quand aucun identifiant n'est trouvé, la dernière ligne de l'erreur imprimée par flower est
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, cette phrase est en `:192`). **Le code fait foi : il les lit.**
    `env.py:56-75` va explicitement lire le bloc `env` de ces deux fichiers ; il n'en prend
    simplement que 9 clés d'identifiants et ne reprend aucun autre réglage. En lisant cette phrase,
    n'en concluez pas que la configuration Claude Code de la machine est ignorée. La chaîne complète
    est dans
    [Configuration · Ordre de priorité de recherche des identifiants](../reference/config.md#凭证查找优先级).

### Quand vous voulez reconfigurer

La sous-commande `flower setup` est bien enregistrée (`cli.py:1147-1149`), mais elle a été oubliée
dans `_CMDS` (`cli.py:758`) ; du coup `flower setup` est réécrit en `flower go setup` — « setup »
est traité comme une demande et part dans un workflow complet.
**Aucune écriture en ligne de commande ne permet actuellement d'atteindre cette sous-commande**,
alors même que plusieurs messages d'erreur vous invitent encore à la lancer. Pour changer les
identifiants :

```bash
$EDITOR ~/.config/flower/.env
```

Ou bien supprimez le token de ce fichier et relancez `flower` — le contrôle « identifiants
manquants » reposera la question (à condition qu'il n'y en ait nulle part ailleurs, par exemple dans
`~/.claude/settings.json`). Quand les identifiants sont rejetés (HTTP 401 / 403), le même écran
s'ouvre également sur-le-champ pour reconfigurer, avec une seule chance (`cli.py:1229-1244`).

## Vérifier que c'est bien installé

Deux niveaux, du moins cher au plus cher.

**Premier niveau — la commande existe (gratuit)** :

```bash
flower --help
```

Voir ces quelques lignes signifie que le console script est installé et présent dans le PATH :

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Deuxième niveau — identifiants, point de terminaison et binaire natif fonctionnent (quelques
centimes)** : le vrai run le moins cher est `once` — un seul agent, avec par défaut les trois seuls
outils en lecture `Read` / `Glob` / `Grep`, sans [goal guard](../reference/glossary.md#目标看守),
sans [workbench](../reference/glossary.md#工作台) :

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` imprime la configuration effective **avant** de démarrer, en ne gardant que les 4 premiers
caractères du token (`cli.py:1257-1259` ; `env.py:197-211`) :

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Ces lignes confirment que vous n'êtes pas connecté à la mauvaise passerelle. Suivent la sonde
d'identifiants et le run réel :

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Pas d'en-tête de step.** `once` passe par `_run_once` → `rt.run()`, sans passer par `_drive` /
`Workflow.run`, et `Event("step", …)` n'est émis qu'en `workflow/base.py:220` — donc les lignes de
séparation du genre `== 步骤名 ===== 1/1` n'apparaissent pas sous `once` ; seuls `go` / `run` les
ont.

**L'apparition de la ligne `+ 完成` vaut validation** : elle prouve trois choses à la fois — les
identifiants fonctionnent, le point de terminaison est joignable, et le binaire natif contenu dans
la wheel `claude-agent-sdk` s'exécute sur cette machine. Si sous `- 验一下凭证…` vous voyez
`! 凭证被拒` ou `! 网关地址或模型名不对`, allez voir le tableau de dépannage plus bas.

!!! note "La durée et le coût cumulé de `once` s'affichent à 0"
    `once` crée un nouveau renderer pour chaque événement (`cli.py:1060`, `:579-581`), donc `用时`
    vaut toujours `0:00` et le `累计 $` de la ligne d'état ne s'accumule jamais — **le coût du step
    unique est réel, la durée non**.

    Le `1 轮 · $0.1741` ci-dessus est une **mesure réelle et sourcée** : le 2026-09-06, dans un
    conteneur Linux/arm64, une requête réelle émise via `cloud.infini-ai.com/maas`
    (`docker/README.md:24-25`), c'est-à-dire le **prix plancher d'un tour** en Opus 5 + fenêtre 1M.
    La commande ci-dessus, chez vous, doit lire le dépôt : il y aura plus de tours et le coût sera
    un peu au-dessus de ce plancher. Les comptes complets sont dans `runs/manifest.json`, voir
    [Configuration · Disposition sur le disque](../reference/config.md#磁盘布局).

## Quand l'installation échoue

| Symptôme | Cause | Que faire |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Ni `python3` ni `python` ne satisfont 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, puis relancer le script |
| Le script dit que c'est installé, mais `flower: command not found` | Installé dans un répertoire absent du PATH | Voir « Comment la commande `flower` arrive dans le PATH » ci-dessus. Sur le chemin `pip --user`, c'est `~/Library/Python/3.X/bin` sous macOS |
| `安装失败。手动试:uv tool install git+https://…` | Tous les chemins ont échoué, en général parce que le réseau vers GitHub ou PyPI est coupé | Lancez la commande manuellement comme indiqué pour voir l'erreur réelle |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 lignes) | Pas d'identifiants en environnement non interactif (pipe, CI, `nohup`) — l'écran de configuration ne s'y affiche pas, sortie immédiate | Lancez d'abord `flower` une fois dans un vrai terminal pour configurer, ou écrivez directement `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | Token expiré ou mal saisi | Dans un terminal interactif, il propose de reconfigurer sur-le-champ ; en non interactif, il quitte |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` ou nom de modèle incorrect | Écrivez le BASE_URL jusqu'à la racine de la passerelle, sans `/v1` ; utilisez les noms de modèles propres à la passerelle |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Ce n'est pas un problème d'identifiants** ; flower refuse délibérément de vous faire reconfigurer, il démarre normalement et laisse faire la couche [resilience](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Exécution dans un pipe ou en CI | Ajoutez `--timeout 0` pour qu'il décide seul, sans attendre personne |
| `flower setup` démarre et demande « quoi faire » | `setup` a été oublié dans `_CMDS` (`cli.py:758`) | Modifiez directement `~/.config/flower/.env`, voir « Quand vous voulez reconfigurer » ci-dessus |

## Étapes suivantes

- [Démarrage rapide](quickstart.md) — entrez dans un répertoire de projet et menez à bien un premier vrai travail.
- [Configuration](../reference/config.md) — toutes les variables d'environnement, la priorité des identifiants, la syntaxe `.env`, ce qui reste sur le disque.
- [Ligne de commande](../reference/cli.md) — toutes les sous-commandes et options.
- [Déploiement](../reference/deploy.md) — exécution en conteneur, distribution de capacités métier via plugin.
- [Glossaire](../reference/glossary.md) — le sens exact de chaque terme de la documentation.
