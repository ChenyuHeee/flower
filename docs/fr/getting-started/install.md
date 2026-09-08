# Installation

Installer flower ne demande que Python ≥ 3.10. La seule dépendance d'exécution est `claude-agent-sdk` — le binaire natif qui émet les requêtes se trouve dans son wheel, donc **pas besoin de Node, ni du CLI Claude Code**. Cette page déroule tout depuis zéro : installation en une ligne, installation depuis les sources, première configuration des identifiants, et une commande qui prouve que « c'est bien installé ». Une fois que ça tourne, passez au [Démarrage rapide](quickstart.md).

## Avant d'installer : vérifier Python {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Une sortie du type `True 3.13.7` suffit. Si ça affiche `False`, ou s'il n'y a pas de `python3` du tout, installez-en un d'abord (`brew install python` / `apt install python3`), sinon le script d'installation sortira immédiatement.

| Nécessaire | Pas nécessaire |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5` ; `install.sh:22-31` le revérifie aussi) | Node.js |
| Un accès réseau vers l'endpoint API | Le CLI Claude Code |
| Une API key ou un token de passerelle (à fournir après l'installation) | Les réglages dans le `~/.claude/` de la machine hôte (les identifiants sont la seule exception, voir plus bas) |

Nom du paquet : `flower`, version `0.1.0`, unique dépendance d'exécution `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). `mkdocs-material` ne sert qu'à construire le site de documentation en CI ; il n'est pas nécessaire pour faire tourner flower.

## Installation en une ligne {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Une fois l'installation terminée, le terminal doit ressembler à ceci (couleurs omises) :

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

L'essentiel est cette ligne `== 装好了 <chemin absolu>` — c'est le résultat d'un `command -v flower` que le script exécute lui-même (`install.sh:60-61`). Si un chemin s'affiche, c'est que `flower` est bien dans le PATH.

### Ce que fait réellement l'installeur {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) ne fait que trois choses : choisir un installeur d'outils Python, installer depuis GitHub, et vous dire quoi faire ensuite. **Il ne touche pas à un seul caractère de vos identifiants** (`install.sh:7-8`). La source d'installation est fixée à `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

L'installeur essaie dans l'ordre et s'arrête à la première méthode qui réussit (`install.sh:33-57`) :

| Ordre | Condition de déclenchement | Commande effective | Où atterrit l'exécutable |
|---|---|---|---|
| 1 | `uv` est dans le PATH | `uv tool install --force <REPO>` | Le répertoire tool bin de uv, en général `~/.local/bin/flower` |
| 2 | Pas de `uv`, mais `pipx` présent | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Ni l'un ni l'autre | D'abord `curl -LsSf https://astral.sh/uv/install.sh \| sh` pour installer uv ; si ça marche, on revient au cas 1 | Idem cas 1 |
| 4 | uv n'a pas pu être installé au cas 3 | `python3 -m pip install --user --upgrade <REPO>` | Le répertoire de scripts utilisateur — **sur macOS, ce n'est pas `~/.local/bin`** |

Les quatre cas installent le même console script : `flower = "flower.cli:main"` (`pyproject.toml:12`). Après installation, on peut aussi l'appeler par `python -m flower.cli`, avec le même effet (`cli.py:1451-1452`).

!!! warning "Relancer le script d'installation écrase de force, sans confirmation"
    Les trois commandes d'installation portent respectivement `--force`, `--force` et `--upgrade` (`install.sh:37`, `:40`, `:54`). Relancer, c'est écraser directement l'installation existante — c'est exactement comme ça qu'on met à jour, mais ne comptez pas sur lui pour vous poser la question avant.

### Comment la commande `flower` arrive dans le PATH {#flower-命令怎么上-path}

Quand `command -v flower` ne trouve rien, le script suggère d'ajouter `$HOME/.local/bin` à `~/.zshrc` ou `~/.bashrc` (`install.sh:62-70`) :

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` et `pipx install` déposent tous les deux ici, donc ce conseil est exact pour eux. **Mais pas forcément pour le cas 4 (`pip install --user`)** — le répertoire de ce message est écrit en dur, alors que le répertoire de scripts utilisateur de pip dépend de la plateforme. Sur macOS, c'est `~/Library/Python/3.13/bin`. Vérifiez vous-même :

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

La sortie est par exemple `/Users/you/Library/Python/3.13/bin` — ajoutez ce répertoire-là au PATH, et non `~/.local/bin`, puis rouvrez le terminal ou faites un `source`.

## Installation depuis les sources {#从源码装}

Pour lire le code, modifier le framework, ou lancer les vérifications hors ligne de `tests/`, installez depuis les sources :

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Après ça, `.venv/bin/flower --help` doit afficher les quelques lignes d'usage.

Le shebang de l'exécutable dans le venv est un **chemin absolu**, donc pas besoin d'activer quoi que ce soit : un lien symbolique suffit pour l'utiliser depuis n'importe quel répertoire :

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Si `~/.local/bin` est dans le PATH, taper `flower` depuis n'importe quel répertoire de projet passe par l'interpréteur de ce venv et par ces sources-là.

L'installation depuis les sources ajoute un emplacement d'identifiants supplémentaire : **le `.env` à la racine du dépôt** (5ᵉ position dans l'ordre de recherche, voir [Configuration · Ordre de recherche des identifiants](../reference/config.md#凭证查找优先级)). En développement :

```bash
cp .env.example .env        # renseigner ANTHROPIC_AUTH_TOKEN
```

`.env` est déjà ignoré par `.gitignore`, il n'entrera pas dans le dépôt. Un flower installé via pip / pipx / uv **n'a pas** cet emplacement disponible — il vit dans site-packages, il n'y a pas de « racine de dépôt » — donc avec ce mode d'installation, utilisez le fichier d'identifiants global décrit ci-dessous.

## Mise à jour automatique {#自动更新}

flower itère encore vite, donc **une installation faite via pip / pipx / uv se met à jour toute seule par défaut** : le bug que remonte quelqu'un tournant sur une version d'il y a trois jours est peut-être déjà corrigé, et tout le monde perd son temps. Il n'y a pas de question du type « voulez-vous l'activer ? » — c'est activé par défaut, et si vous voulez le couper, vous posez une variable d'environnement.

Ce qu'il fait (`update.py:116-129`) :

1. À chaque démarrage de `flower`, il interroge une fois, dans un **thread d'arrière-plan**, le dernier commit de `main` sur GitHub (`update.py:70-80`). Le flux principal n'attend pas une seconde — c'est le premier invariant.
2. Si c'est différent du commit installé localement, il rejoue une commande de mise à jour selon le mode d'installation d'origine : `uv tool install --force` si `uv` est là, `pipx install --force` si `pipx` est là, sinon `pip install --user --upgrade` (`update.py:83-93`).
3. **Même une fois installé, il ne remplace pas le processus en cours** — la nouvelle version ne sert qu'au prochain `flower` (`update.py:113`). Se faire remplacer en plein milieu est la catégorie de panne la plus difficile à diagnostiquer.
4. Limitation de débit : une vérification toutes les 24 heures au maximum, l'horodatage étant écrit dans `~/.config/flower/.update` (`update.py:32`, `:36-37`, `:124`).
5. **Tout échec est silencieux**. Pas de réseau, GitHub en panne, installation impossible — rien de tout ça n'interrompt votre travail (`update.py:79`, `:108-110`).

**Une exécution depuis les sources (git) n'est pas concernée.** L'étape de mise à jour regarde d'abord s'il y a un `.git` dans le dépôt ; si oui, elle renvoie directement `None` et ne fait rien (`update.py:83-87`) — votre espace de travail appartient à `git`, pas à elle. Le mode non interactif (stdin qui n'est pas un terminal, par exemple un pipe / la CI) est également entièrement sauté (`update.py:121`).

Pour le désactiver :

```bash
export FLOWER_NO_UPDATE=1
```

N'importe quelle valeur non vide compte (`update.py:33`, `:121`). À utiliser en CI, en environnement hors ligne, ou quand il faut reproduire le comportement d'une ancienne version.

## Premier lancement : configurer les identifiants {#第一次跑配凭证}

Les trois points d'entrée d'exécution `go`, `run` et `once` appellent tous `ensure_credentials()` en début de course (`cli.py:1192`, `:1160`, `:1225`), avec deux contrôles :

1. **Y en a-t-il** — recherche selon l'ordre de priorité ; si rien n'est trouvé, la question vous est posée sur-le-champ.
2. **Sont-ils utilisables** — un vrai appel à l'API. Une requête minimale avec `max_tokens=16` (`env.py:120-123`), qui ne coûte presque rien. Un token expiré ou une adresse de passerelle mal écrite ne se voient pas en regardant les variables d'environnement ; sans sonde, ça n'exploserait que plusieurs minutes plus tard.

En l'absence d'identifiants, le premier `flower` s'arrête sur cet écran (`cli.py:1358-1388`) :

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

La question 1 est obligatoire ; la laisser vide affiche en rouge `没给 token,取消。` puis quitte. Aux questions 2 et 3, une simple entrée suffit. Avec l'endpoint officiel, laissez la question 2 vide ; pour une passerelle tierce, indiquez son adresse racine, **sans `/v1`** — la sonde de flower tape sur `<BASE_URL>/v1/messages` (`env.py:162`).

Les clés écrites après vos réponses (`cli.py:1378-1386`) :

| Ce que vous saisissez | Clé écrite dans `.env` |
|---|---|
| Un token commençant par `sk-ant-` | `ANTHROPIC_API_KEY` |
| Tout autre token | `ANTHROPIC_AUTH_TOKEN` |
| Adresse de passerelle non vide | `ANTHROPIC_BASE_URL` |
| Nom de modèle non vide | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **les trois d'un coup** |

L'emplacement du fichier est `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), **réécrit intégralement**, puis `chmod 0o600` (`cli.py:1336-1347`). C'est le fichier du « configuré une fois, valable partout » — pas besoin de reconfigurer en changeant de répertoire de projet ; la signification de chaque variable est dans [Configuration](../reference/config.md#环境变量).

### Si Claude Code est déjà installé sur la machine, il se peut qu'aucune question ne soit posée {#本机装过-claude-code-的话可能一个问题都不问}

La recherche d'identifiants a un **dernier repli** : lire `~/.claude/settings.json`, puis `~/.claude/settings.local.json`, et prendre 9 clés d'identifiants dans leur bloc `env` (`env.py:56-75`, `:109-111`). Si Claude Code est déjà configuré sur la machine, lancer `flower` suffit pour commencer à travailler : l'écran de configuration n'apparaît même pas — c'est ce que `install.sh:77` annonce.

!!! warning "La phrase du produit « flower ne lit pas ~/.claude/settings.json » est fausse"
    Quand aucun identifiant n'est trouvé, la dernière ligne de l'erreur affichée par flower est
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, la phrase est en `:192`). **Le code fait foi : il les lit.**
    `env.py:56-75` lit explicitement le bloc `env` de ces deux fichiers ; il n'en prend simplement que 9 clés d'identifiants, et ne reprend aucun autre réglage.
    En lisant cette phrase, n'en concluez pas que la configuration Claude Code de la machine est ignorée. La chaîne complète est dans [Configuration · Ordre de recherche des identifiants](../reference/config.md#凭证查找优先级).

### Quand on veut reconfigurer {#想重新配的时候}

La sous-commande `flower setup` est bien enregistrée (`cli.py:1326-1328`), mais `_CMDS` l'a oubliée (`cli.py:937`) : du coup `flower setup` est réécrit en `flower go setup` — « setup » est traité comme une demande et déclenche un workflow complet. **Aujourd'hui, aucune écriture en ligne de commande ne permet d'atteindre cette sous-commande**, alors que plusieurs messages d'erreur vous invitent encore à la lancer. Pour changer les identifiants :

```bash
$EDITOR ~/.config/flower/.env
```

Ou bien supprimez le token dans ce fichier et relancez `flower` — le contrôle « identifiants manquants » reposera la question (à condition qu'il n'y en ait nulle part ailleurs, par exemple dans `~/.claude/settings.json`). En cas d'identifiants rejetés (HTTP 401 / 403), le même écran s'affiche aussi sur-le-champ pour reconfigurer, avec au plus une seule tentative (`cli.py:1416-1428`).

## Vérifier que l'installation est bonne {#验证装好了没有}

Deux niveaux, du moins cher au plus cher.

**Niveau 1 — la commande est-elle là (gratuit)** :

```bash
flower --help
```

Voir ces quelques lignes signifie que le console script est installé et présent dans le PATH :

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Niveau 2 — identifiants, endpoint et binaire natif tous fonctionnels (quelques centimes)** : le vrai run le moins cher est `once` — un seul agent, avec par défaut les trois outils en lecture seule `Read` / `Glob` / `Grep`, sans [garde-objectif](../reference/glossary.md#目标看守), sans [workbench](../reference/glossary.md#工作台) :

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` imprime la configuration effective **avant** le démarrage, en ne gardant que les 4 premiers caractères du token (`cli.py:1445-1447` ; `env.py:197-211`) :

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Ces lignes confirment que vous n'êtes pas branché sur la mauvaise passerelle. Viennent ensuite la sonde d'identifiants et le run proprement dit :

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Aucun en-tête de step.** `once` passe par `_run_once` → `rt.run()`, sans traverser `_drive` / `Workflow.run`, et `Event("step", …)` n'est émis qu'en `workflow/base.py:220` — donc une ligne de séparation du type `== 步骤名 ===== 1/1` n'apparaît jamais sous `once` ; seuls `go` / `run` en produisent.

**Dès que la ligne `+ 完成` apparaît, c'est validé** ; elle prouve trois choses à la fois : les identifiants fonctionnent, l'endpoint est joignable, et le binaire natif du wheel `claude-agent-sdk` s'exécute sur cette machine. Si vous voyez sous `- 验一下凭证…` un `! 凭证被拒` ou un `! 网关地址或模型名不对`, allez voir la table de dépannage ci-dessous.

!!! note "Avec `once`, la durée et le coût cumulé s'affichent à 0"
    `once` crée un nouveau renderer pour chaque événement (`cli.py:1239`, `:579-581`), donc `用时` vaut toujours `0:00` et le `累计 $` de la ligne d'état ne s'accumule jamais — **le coût de l'étape unique est réel, le temps ne l'est pas**.

    Le `1 轮 · $0.1741` ci-dessus est une **mesure réelle et sourcée** : le 2026-09-06, dans un conteneur Linux/arm64, une requête réelle émise via `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), c'est-à-dire le **prix plancher d'un tour** pour Opus 5 + fenêtre 1M. En lançant vous-même la commande ci-dessus, il faudra lire le dépôt, donc plus de tours, et un coût un peu supérieur à ce plancher.
    Le compte complet est dans `runs/manifest.json`, voir [Configuration · Disposition sur disque](../reference/config.md#磁盘布局).

## Quand ça ne s'installe pas {#装不上的时候}

| Symptôme | Cause | Que faire |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Ni `python3` ni `python` ne satisfont 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, puis relancer le script |
| Le script dit que c'est installé, mais `flower: command not found` | Installé dans un répertoire absent du PATH | Voir « Comment la commande `flower` arrive dans le PATH » plus haut. Par la voie `pip --user`, c'est `~/Library/Python/3.X/bin` sur macOS |
| `安装失败。手动试:uv tool install git+https://…` | Toutes les voies ont échoué, en général un problème réseau vers GitHub ou PyPI | Lancez la commande manuellement comme indiqué, pour voir l'erreur réelle |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 lignes) | Pas d'identifiants en environnement non interactif (pipe, CI, `nohup`) — l'écran de configuration n'y apparaît pas, sortie immédiate | Lancez d'abord `flower` une fois dans un vrai terminal pour configurer, ou écrivez directement `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | Token expiré ou mal écrit | Dans un terminal interactif, il propose de reconfigurer sur-le-champ ; en non interactif, il sort |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` ou nom de modèle incorrect | Écrivez BASE_URL jusqu'à la racine de la passerelle, sans `/v1` ; utilisez les noms de modèles propres à la passerelle |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **Ce n'est pas un problème d'identifiants** ; flower refuse délibérément de vous faire reconfigurer, il démarre normalement et laisse faire la couche [résilience](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Exécution dans un pipe ou en CI | Ajoutez `--timeout 0` pour qu'il tranche seul, sans attendre personne |
| `flower setup` démarre et demande « 要做什么 » | `_CMDS` a oublié `setup` (`cli.py:937`) | Modifiez directement `~/.config/flower/.env`, voir « Quand on veut reconfigurer » plus haut |

## La suite {#下一步}

- [Démarrage rapide](quickstart.md) — entrer dans un répertoire de projet et mener à bien un premier vrai travail.
- [Configuration](../reference/config.md) — toutes les variables d'environnement, la priorité des identifiants, la syntaxe `.env`, ce qui reste sur le disque.
- [Ligne de commande](../reference/cli.md) — toutes les sous-commandes et options.
- [Déploiement](../reference/deploy.md) — exécution en conteneur, distribution de capacités métier via plugin.
- [Glossaire](../reference/glossary.md) — le sens exact de chaque terme de la documentation.
