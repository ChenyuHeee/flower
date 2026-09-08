# Déploiement et extension

Porter flower ailleurs demande de régler trois choses : le conteneur (enfermer le Bash non
restreint, et au passage vérifier la formule « sans CLI »), le
[plugin](glossary.md#plugin) (les capacités métier suivent le dépôt, sans regarder ce qui est
installé sur la machine hôte), le site de documentation (un push sur `main` publie
automatiquement, `install.sh` est servi depuis le domaine Pages). Les trois sections sont
indépendantes, lisez celle dont vous avez besoin.

## 1. Le conteneur {#一容器}

### Pourquoi un conteneur {#为什么要容器}

**Premièrement, pour enfermer.** L'[exécutant](glossary.md#执行者) qui travaille dispose d'un
**Bash non restreint** — la liste blanche Bash de flower (`delegate_guard`) ne couvre que le
[thread principal](glossary.md#主线程), et celui qu'on envoie au front doit pouvoir lancer les
tests : c'est intentionnel. Dans le conteneur, seul votre répertoire de projet est monté ; le code
source du framework est dans l'image sous `/opt/flower`, et le reste de l'hôte est invisible.

**Deuxièmement, c'est en soi la vérification de la contrainte de
[portabilité](glossary.md#可移植).** L'image ne contient ni le CLI Claude Code, ni Node,
seulement Python et `claude-agent-sdk` — les requêtes partent via le binaire natif embarqué dans
la wheel. Si ça tourne ici, « sans CLI » n'est plus une affirmation sur le papier.

Vérifié en conditions réelles (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0) :

| Ce qui est vérifié | Résultat |
|---|---|
| Présence d'un CLI dans l'image | `claude`, `node`, `npm`, `npx` : **aucun n'existe** |
| Binaire embarqué | `\177ELF` (207M) |
| Requête réelle | émise via `cloud.infini-ai.com/maas` avec réponse obtenue, `$0.1741 / 1 tour` (le plancher d'un tour unique avec Opus 5 + fenêtre 1M, c'est ce prix-là) |
| Propriété des fichiers | un fichier écrit dans `/work` depuis le conteneur appartient à `hechenyu:staff` sur l'hôte, le mapping est correct |
| Visibilité de l'hôte | dans le conteneur, `ls /Users` → `No such file or directory` |

### Ce qu'il y a dans l'image {#镜像里装了什么}

Image de base `python:3.13-slim`, par-dessus laquelle apt n'installe que trois paquets. Chacun a
sa raison :

| Installé | Pourquoi |
|---|---|
| `python:3.13-slim` | il ne faut que Python ≥ 3.10. Pas de Node, pas de CLI claude |
| `git` | `--isolate` doit attribuer un worktree à chaque [subagent](glossary.md#subagent) |
| `ca-certificates` | on passe par une passerelle HTTPS |
| `libstdc++6` | le binaire embarqué du SDK est un fichier unique compilé par Bun, il en a besoin sous Linux ; l'image slim ne l'a pas |

Le code source du framework entre dans l'image par `COPY`, **pas par bind mount** — c'est
pourquoi l'agent dans le conteneur ne peut pas toucher au code source du framework sur l'hôte :

| Chemin dans l'image | Contenu | Provenance |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, avec un `pip install .` sur place | `COPY` |
| `/work` | répertoire de travail (`WORKDIR`), où l'on monte le `$PWD` de l'hôte à l'exécution | `docker run -v` |

Le point d'entrée est `ENTRYPOINT ["flower"]`, `CMD` est vide — lancer le conteneur sans argument
ouvre la saisie interactive (il vous demande ce que vous voulez faire) au lieu d'afficher
`--help`. On évite ainsi d'avoir à mettre une demande en français entre guillemets dans le shell.

### Pourquoi on ne peut pas monter le `.venv` de l'hôte {#为什么不能把宿主的-venv-挂进去}

Le SDK publie une wheel par plateforme, et le binaire embarqué est spécifique à la plateforme :

```text
Hôte       claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
           → _bundled/claude est un Mach-O 64-bit arm64, 191M
Conteneur  claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Monté tel quel, ça ne tourne pas : l'image doit donc faire son propre `pip install`. Inversement,
c'est aussi une preuve de portabilité : même `pyproject.toml`, on change de plateforme, on change
de binaire natif, et pas une ligne du code du framework ne bouge.

### Les deux scripts {#两个脚本}

| Script | Ce qu'il fait |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | construit l'image. `cd` à la racine du dépôt, `docker build -f docker/Dockerfile -t flower-box .` ; quand `FLOWER_MIRRORS=1` (défaut), tire d'abord `python:3.13-slim` depuis un miroir de registry puis le retag, et ajoute les `--build-arg` pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | lance un run. Vérifie le fichier d'identifiants → vérifie que `$PWD` peut bien être monté → détermine s'il y a un TTY → `docker run` |

Les réglages de `docker/build` passent tous par des variables d'environnement :

| Variable | Défaut | Sémantique |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | tag de l'image |
| `FLOWER_MIRRORS` | `1` | `0` = aucun miroir substitué, tout passe par l'amont |
| `FLOWER_REGISTRY` | `dockerproxy.net` | tire l'image de base depuis là puis la retag en `python:3.13-slim`, pour que le `FROM` tape en local |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | passé à `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | passé à `--build-arg APT_MIRROR` |

Les trois dernières n'ont d'effet que si `FLOWER_MIRRORS=1` — la branche `FLOWER_MIRRORS=0` ne
définit tout simplement aucun build-arg.

`docker/flowerbox` en reconnaît deux :

| Variable | Défaut | Sémantique |
|---|---|---|
| `FLOWER_HOME` | un niveau au-dessus de l'emplacement du script (donc la racine du dépôt) | où chercher le `.env`. Si `$FLOWER_HOME/.env` est introuvable, sortie 1 immédiate |
| `FLOWER_IMAGE` | `flower-box` | quelle image lancer |

`FLOWER_HOME` est déduit de l'emplacement du script lui-même, aucun chemin n'est codé en dur : le
dépôt fonctionne quel que soit l'endroit où on l'a cloné.

### Construire l'image et lancer le conteneur {#跑起来}

```bash
docker/build                          # une seule fois suffit
cd ~/un-projet-quelconque             # doit être sous $HOME, voir la frontière de montage ci-dessous
/path/to/flower/docker/flowerbox      # sans argument → il vous demande quoi faire, pas de guillemets à poser
```

Si le réseau vers pypi.org / Docker Hub fonctionne normalement, la construction se fait ainsi :

```bash
FLOWER_MIRRORS=0 docker/build
```

Les arguments de `flowerbox` sont exactement ceux de `flower` — il colle `"$@"` tel quel derrière
l'`ENTRYPOINT`. `--clarify-only`, `--asks N`, `--timeout 秒`, `--isolate`, `-v` passent tous ;
tableau complet dans [ligne de commande](cli.md) :

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "fais-moi un X"
```

Ce qui est réellement exécuté, c'est cette ligne (`-t` n'est ajouté qu'en présence d'un TTY, voir
plus bas) :

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Frontière de montage et persistance {#挂载边界与持久化}

```text
Hôte $PWD  ──monté──>  /work       ← l'agent travaille ici, les productions restent sur l'hôte
Dans l'image           /opt/flower ← code source du framework, **non monté**, impossible d'atteindre celui de l'hôte
```

Lancer depuis un sous-répertoire du dépôt comme `flower/human-test/HT001` est donc sans danger :
seul `HT001` est monté, le code source du framework est hors du périmètre de montage.

| Quoi | Survit à la sortie ? | Pourquoi |
|---|---|---|
| tout ce qui est sous le `$PWD` de l'hôte, y compris `runs/` et l'[établi](glossary.md#工作台) `.flower/` | oui | c'est précisément le répertoire monté comme `/work` |
| ce qui est écrit ailleurs dans le conteneur | non | `--rm`, le conteneur est supprimé à la sortie |
| identifiants | n'entrent pas dans les couches de l'image | ils passent par `--env-file` ; `.env` est exclu par `.dockerignore`, donc même un `COPY . .` ne les embarque pas |

!!! danger "Le répertoire du projet doit être sous `$HOME`, sinon les productions sont perdues silencieusement"
    **colima ne monte par défaut que `$HOME` dans la VM** (`mount | grep virtiofs` → `mount0 on /Users/<vous>`).
    Lancé depuis un endroit comme `/tmp`, le `-v` crée un **répertoire vide** dans la VM : ce qu'on
    y écrit reste à jamais invisible depuis l'hôte, **et sans la moindre erreur** — productions,
    [brief](glossary.md#需求确认书), `runs/`, tout est perdu. C'est arrivé une fois :
    un run `once` s'est terminé, $0.17 dépensés, et `runs/` n'existait tout simplement pas sur l'hôte.

    `flowerbox` bloque désormais ce cas : si `$PWD` est sous `$HOME`, il laisse passer ; sinon, il
    écrit un fichier sonde dans `$PWD`, puis lance un conteneur pour tester réellement
    `test -f /work/<sonde>` (ce qui passe aussi si vous avez configuré un montage supplémentaire).
    En cas d'échec, sortie 1 avec l'indication `colima start --mount '<chemin>:w'`. La sonde
    nécessite de lancer un conteneur, donc `docker/build` doit avoir été fait au préalable.

### Comment les identifiants entrent dans le conteneur {#凭证}

Via `docker run --env-file`, **jamais dans les couches de l'image**. `flowerbox` lit
`$FLOWER_HOME/.env`, c'est-à-dire par défaut le `.env` à la racine du dépôt :

```bash
cp .env.example .env       # remplissez le token ; .env est déjà gitignoré
```

Attention : `flower setup` écrit dans `~/.config/flower/.env`, et **`flowerbox` ne regarde pas ce
chemin**. Si vous avez déjà configuré via `setup` et ne voulez pas dupliquer, pointez
`FLOWER_HOME` dessus :

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Noms des clés, ordre de priorité, comment renseigner la passerelle : voir
[configuration](config.md).

!!! warning "Sans TTY, une question bloque jusqu'au `--timeout`"
    `flowerbox` n'ajoute `-t` que si `[ -t 0 ]` — `docker run -t` dans un pipe ou en CI renvoie
    directement « the input device is not a TTY » ; `-i` est toujours nécessaire, sinon stdin
    n'entre pas du tout.

    Les réponses aux questions passent par l'entrée standard. Sans TTY, `input()` lève un
    `EOFError` dès le premier appel → la question courante est traitée comme « entrée fermée » et
    ignorée, et **le thread de réponse sort immédiatement** : à partir de la deuxième question,
    plus personne ne répond, et il ne reste qu'à attendre l'expiration complète du `--timeout`
    (1800 secondes par défaut). En mode non surveillé, il faut explicitement `--timeout 0`. Le
    script affiche un rappel dès qu'il détecte l'absence de TTY.

### git submodule {#git-submodule}

`.gitmodules` ne contient qu'une entrée :

| path | url | c'est quoi |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | le dépôt de code **produit par** le run [HT001](../cases/ht001.md), conservé pour archive |

Un `git clone` ordinaire ne le récupère pas : `human-test/HT001` est alors un répertoire vide (le
`-` en tête de `git submodule status` correspond à cet état). Faut-il s'en occuper :

| Ce que vous voulez faire | Faut-il l'initialiser |
|---|---|
| lancer flower, construire l'image | **non**. `.dockerignore` exclut `human-test/`, et de toute façon le `Dockerfile` ne `COPY` que `pyproject.toml` / `flower` / `examples` |
| parcourir en local le code produit par HT001 | oui : `git submodule update --init human-test/HT001`, ou d'emblée `git clone --recurse-submodules` |

### Réseau en Chine : pourquoi tous ces remplacements de miroirs {#国内网络为什么有那一堆镜像替换}

Quand on installe tout ça derrière le pare-feu, ce qui est lent n'est pas la bande passante mais
les liaisons internationales. Le `docker/build` par défaut a déjà remplacé tout ce qui devait
l'être, et `FLOWER_MIRRORS=0` coupe tout d'un coup. Ci-dessous les mesures et le détail des quatre
remplacements — inutile de lire si votre réseau n'a pas ce problème.

??? note "Tableau de vitesses mesurées et les quatre remplacements (2026-09-06, macOS/arm64)"

    | Source | Vitesse |
    |---|---|
    | `pypi.org` (index) | 32 KB/s |
    | `files.pythonhosted.org` (fichiers de paquets) | **284 B/s** |
    | `github.com` (asset de release en direct) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (dans la VM) | 26 KB/s |
    | `download.docker.com` | **injoignable** (HTTP 000) ; 4 KB/s dans la VM |
    | `mirrors.tuna.tsinghua.edu.cn` | **injoignable** |
    | `mirrors.aliyun.com/pypi` (**fichiers de paquets**) | 1.4 MB/s (hôte) / 152 KB/s (dans la VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (dans la VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (proxy GitHub) | **2.5 MB/s** |
    | `gh-proxy.com` (proxy GitHub) | 1.5 MB/s |
    | `dockerproxy.net` (proxy Docker Hub) | utilisable (renvoie directement le manifest) |

    En mesurant, ne confondez pas la **page d'index** avec les fichiers de paquets :
    `mirrors.aliyun.com/pypi/simple/` affiche 7.4 MB/s sur cette page, alors que la wheel réelle de
    95.9 MB ne fait que 1.4 MB/s (152 KB/s dans la VM — le réseau en espace utilisateur de colima a
    ses pertes). Estimez les durées sur les chiffres des fichiers de paquets.

    **Remplacement 1 — l'image de VM de colima.** colima n'utilise pas une image cloud Ubuntu
    ordinaire, mais sa propre image sur mesure **avec docker préinstallé** (un asset de release de
    `abiosoft/colima-core`) : au démarrage de la VM, pas besoin d'installer docker via apt, ce qui
    contourne le `download.docker.com` injoignable. Téléchargez-la vous-même puis passez-la avec
    `--disk-image` :

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # Vérification : le digest vient de l'API GitHub. Ne sautez pas cette étape — c'est ce qui va tourner comme VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    Le proxy coupe le flux en cours de route (curl 56 constaté) ; avec `-C -` il suffit de relancer
    quelques fois pour reprendre là où ça s'est arrêté.

    **Remplacement 2 — apt dans la VM.** Même avec l'image où docker est préinstallé, le script de
    boot de lima `30-install-packages.sh` lance quand même un `apt-get update` pour installer
    `rsync` — il tape `ports.ubuntu.com` (26 KB/s) et `download.docker.com` (4 KB/s), ce qui bloque
    plusieurs dizaines de minutes.

    Traitement (**lisez `/mnt/lima-cidata/boot.sh` avant d'agir** : pour un script de boot en
    échec, il se contente d'un `WARNING` + `CODE=1` puis continue, et il écrit **toujours**
    `/run/lima-boot-done` à la fin — faire échouer cette étape est donc sans danger) :

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
      pkill -f "apt-get update"          # boot.sh ira jusqu au bout et écrira le marqueur de fin
    '
    # colima start sort alors normalement ; ensuite on rattrape rsync (maintenant à 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Profitez-en pour ajouter `127.0.0.1 lima-colima` au `/etc/hosts` de la VM, ce qui fait
    disparaître la série d'avertissements `sudo: unable to resolve host`.

    **Remplacement 3 — l'image de base.** `docker/build` tire d'abord `python:3.13-slim` depuis
    `dockerproxy.net` puis le retag, pour que le `FROM` du Dockerfile tape en local. Mesuré :
    `dockerproxy.net` renvoie directement le manifest (HTTP 200) ; `docker.1ms.run` /
    `docker.m.daocloud.io` renvoient 401, `hub.rat.dev` 302, `docker.xuanyuan.me` 403.

    **Remplacement 4 — apt et pip dans le conteneur.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) et
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Notez que `PIP_INDEX_URL`
    est aussi une variable d'environnement que pip reconnaît lui-même : dès que l'`ARG` est déclaré,
    le pip du RUN la lit — pas besoin d'écrire explicitement `--index-url`.

    La préparation, une fois pour toutes, prend environ 25 minutes dans les conditions réseau
    ci-dessus, l'essentiel étant les 364 MB de l'image de VM et les 95.9 MB de la wheel du SDK.
    Ensuite, le démarrage de `flowerbox` se compte en secondes.

## 2. plugin {#plugin}

### Ce qu'est un plugin, et comment le SDK le charge {#它是什么}

C'est le **paquet de capacités métier** qui suit le dépôt. Le code du framework ne contient aucune
connaissance métier ; toute la connaissance métier vit dans le répertoire `plugin/` à la racine du
dépôt, clonée avec le code, relue avec le code, taguée avec le code.

Côté SDK, le câblage tient en deux lignes dans `build_options()`, dans
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) :

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Combiné à `setting_sources=[]` (traité séparément plus bas), c'est ce qui permet à flower d'être à
la fois [portable](glossary.md#可移植) et « au fait de votre métier » : il ne demande pas ce qui
est installé sur la machine hôte, il ne connaît que ce seul répertoire apporté par le dépôt.

### Disposition des répertoires {#目录布局}

| Chemin | Contenu | Quand ça s'applique | Qui décide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | l'identité du paquet : `name`, `description`, `version`, `author` | lu une fois au chargement | — |
| `plugin/skills/<name>/SKILL.md` | connaissance métier, chargée à la demande | **probabiliste** — utilisée si le modèle la juge pertinente | le modèle |
| `plugin/agents/<name>.md` | subagent, fenêtre de contexte indépendante | délégation par le modèle, ou désignation explicite dans le [workflow](glossary.md#流程) | le modèle / vous |
| `plugin/hooks/hooks.json` | interception d'appels d'outils | **déterministe** — dès que ça correspond, ça s'exécute | le code |
| `plugin/.mcp.json` | branchement d'outils externes | enregistrés comme outils, au même titre que les outils intégrés | le modèle |

**La différence entre probabiliste et déterministe est le critère de choix, pas une nuance de
vocabulaire :**

- un skill est **de la connaissance posée là**. Le modèle voit sa `description` et ne va la lire
  que s'il la juge pertinente pour la tâche en cours. Le jugement de pertinence est fait par le
  modèle, donc la même demande lancée deux fois peut l'utiliser une fois et pas l'autre.
- un hook est **du code**. Il s'exécute dès que l'événement correspond, indépendamment de ce que
  le modèle veut ou sait. Le [déversement](glossary.md#落盘) et l'[isolation](glossary.md#隔离) de
  flower sont des hooks, précisément parce qu'ils ne peuvent pas « s'appliquer parfois ».

Le critère est donc unique : **est-ce que cette chose doit arriver à chaque fois ?** Si oui —
écrivez un hook. Si c'est seulement « bon à savoir » — écrivez un skill. Écrire en skill une chose
obligatoire, c'est parier la discipline sur un jugement unique du modèle.

Aujourd'hui, le `plugin/` du dépôt ne contient que deux choses :
`.claude-plugin/plugin.json` et `skills/example/SKILL.md`. `agents/`, `hooks/`, `.mcp.json`
**n'existent pas encore** — créez-les vous-même si vous en avez besoin, avec exactement les noms
de répertoires du tableau ci-dessus.

### Écrire un skill : exemple complet {#写一个-skill完整例子}

Prenons « générer les notes de version », de zéro jusqu'à la confirmation que ça marche.

**Première étape : créer le répertoire.** Le nom du répertoire est le nom du skill, identique au
`name` du frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Deuxième étape : écrire `plugin/skills/release-notes/SKILL.md`.** Le nom du fichier doit être
`SKILL.md`, en majuscules. Le format est un frontmatter YAML + un corps Markdown ; le frontmatter
a deux champs :

| Champ | Rôle |
|---|---|
| `name` | l'identifiant du skill. Identique au nom du répertoire |
| `description` | **le modèle ne se base que sur cette ligne pour le choisir**. Écrivez clairement « quand l'utiliser », pas « ce que c'est » |

Un fichier minimal directement utilisable :

````markdown
---
name: release-notes
description: À utiliser pour rédiger des notes de version. Quand l'utilisateur dit « écris les release notes », « qu'est-ce qui a changé dans cette version », « on publie ».
---

# Notes de version

## Où prendre la matière

```bash
git describe --tags --abbrev=0        # tag précédent
git log --oneline <上一个 tag>..HEAD   # les commits de cette version
```

## Format de sortie

Trois sections, chacune une liste à puces, une ligne par entrée, décrivant des changements
perceptibles par l'utilisateur, jamais les refactorings internes :

- **Nouveautés** — ce que cette version permet de faire et qu'on ne pouvait pas faire avant
- **Corrections** — ce qui a été corrigé, symptôme décrit en une phrase
- **Ruptures de compatibilité** — ce qu'il faut modifier à la main pour monter de version. S'il n'y en a pas, on omet toute la section

## Limites

- N'inventez pas le numéro de version, lisez-le dans le champ `version` de `pyproject.toml`.
- Si vous ne savez pas si un commit est perceptible par l'utilisateur, listez-le et posez la question, ne décidez pas à sa place.
````

Le corps n'a pas de format imposé — c'est juste un texte lu dans le contexte. Suivez la manière de
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md) :
dire clairement **quand l'utiliser**, **les étapes**, **la forme du résultat**, **où sont les
limites** est plus utile qu'empiler des connaissances de fond.

**Troisième étape : confirmer qu'il est bien chargé.** On ne vérifie qu'une chose certaine — le
répertoire existe-t-il, oui ou non :

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Ce n'est que si ça affiche `/path/to/flower/plugin True` que le `if` de `build_options()` sera
pris. Si ça affiche `False`, ce n'est pas chargé, et **aucune erreur ne sera levée à l'exécution** :
voir l'avertissement ci-dessous.

**Ne prenez pas « je lance une demande et je regarde si le skill `example` a été invoqué » pour une
vérification.** Un skill est probabiliste : si le modèle ne l'a pas appelé, ça peut être qu'il
n'est pas installé, ou simplement qu'il n'a pas jugé la tâche concernée — ce signal ne distingue
pas les deux cas. De plus, `build_options()` ne définit jamais l'option `skills=` du SDK au niveau
de la session ; savoir si les skills du plugin apparaissent réellement dans la liste des options du
coordinateur n'a jamais été vérifié en pratique. Le `True`/`False` de `PLUGIN_DIR` ci-dessus est
certain : utilisez celui-là.

Pour désigner nommément les skills ouverts à un [exécutant](glossary.md#执行者) donné, utilisez
`worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)) ;
le nom est le `name` du `SKILL.md`, et le SDK accepte aussi la forme qualifiée
`nom_du_plugin:nom_du_skill`.

!!! warning "Un flower installé n'a pas de `plugin/` — aucune des trois méthodes d'installation"
    `PLUGIN_DIR` remonte de trois niveaux depuis `flower/core/agent.py` puis descend dans `plugin/`.
    Lancé depuis un checkout des sources, c'est bien le `plugin/` de la racine du dépôt ; mais la
    wheel n'empaquette que le répertoire `flower` (dans `pyproject.toml` :
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), donc une fois installée dans
    site-packages, `site-packages/plugin` n'existe pas et `PLUGIN_DIR.is_dir()` est faux —
    **passage silencieux, ni erreur, ni avertissement**.

    **Ce n'est pas un problème de conteneur, la portée est bien plus large.** Chacun des chemins
    d'`install.sh` — `uv tool install`, `pipx install`, bootstrap de uv puis uv, et le repli
    `pip install --user` — installe la wheel. Autrement dit, **avec un flower installé en une
    ligne, le paquet de capacités métier est systématiquement inactif, en silence**. Le conteneur
    n'est qu'une instance du même problème : `docker/Dockerfile` ne `COPY` que `pyproject.toml`,
    `flower/` et `examples/`, `plugin/` n'entre pas dans l'image.

    Consigné dans l'[issue #15](https://github.com/ChenyuHeee/flower/issues/15). Après
    installation, lancez d'abord la commande `PLUGIN_DIR` ci-dessus pour vérifier : si elle affiche
    `False`, cette installation n'a pas le paquet de capacités métier. Pour utiliser les capacités
    métier, il faut aujourd'hui lancer depuis un checkout des sources.

### Pourquoi `setting_sources=[]` force les capacités métier à passer par le plugin {#setting_sources-为什么逼着领域能力走-plugin}

La même fonction contient aussi cette ligne :

```python
"setting_sources": [] if portable else ["project"],
```

Le défaut du SDK est `None` = les trois sources sont lues : `~/.claude/settings.json`
(utilisateur), `.claude/settings.json` (projet), `.claude/settings.local.json` (local). flower
passe `[]` par défaut, ce qui les **coupe toutes**.

| | Lu ? | Conséquence |
|---|---|---|
| `~/.claude/` (machine hôte) | non | comportement identique en changeant de machine, pas de résultat différent parce que « sur ma machine c'est configuré » |
| `.claude/` du projet | non | ce qui est placé dans `.claude/skills/`, `.claude/agents/` **n'a aucun effet** sous flower |
| `plugin/` | oui | chemin codé en dur dans le code, il suit le dépôt |
| identifiants | ne passent pas par là | il faut apporter son `.env` ; les blocs `env` de `~/.claude/settings.json` et `settings.local.json` ne servent que de tout dernier repli, et **seules 9 clés d'identifiants sont retenues**, voir [configuration](config.md) |

Que `.claude/` n'ait aucun effet **n'est pas un oubli de configuration, c'est la définition de la
contrainte** : dès qu'on lit un seul octet depuis la machine hôte, « comportement identique en
changeant de machine » ne tient plus. Les capacités métier n'ont donc qu'un seul canal — le
`plugin/` qui suit le dépôt.

Deux interrupteurs (tous deux sur `build_options()`, avec les valeurs par défaut de la portabilité) :

| Paramètre | Défaut | Effet si on le change |
|---|---|---|
| `portable` | `True` | passer `False` → `setting_sources` devient `["project"]` et le `.claude/` du projet est lu (côté SDK : lire un `CLAUDE.md` exige `"project"`). La portabilité tombe avec |
| `use_plugin` | `True` | passer `False` → `plugin/` n'est plus branché du tout, les capacités métier reposent entièrement sur `AgentSpec.instructions` |

Au passage : `instructions` passe par l'[append](glossary.md#叠加) (le `append` du
`system_prompt`), ce sont deux canaux distincts du plugin — le premier est dans le contexte à
chaque tour, le second se charge à la demande. Une discipline courte et obligatoire va dans
`instructions` ; une connaissance longue et occasionnellement utile va dans un skill.

## 3. Le site de documentation {#三文档站}

Le site que vous lisez est construit avec mkdocs-material ; les sources sont dans `docs/` du
dépôt, et un push sur `main` publie automatiquement.

| Élément | Ce que c'est |
|---|---|
| Configuration | `mkdocs.yml`, `docs_dir: docs` |
| Multilingue | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`… la langue par défaut est `zh` |
| Dépendances | `docs-requirements.txt` (versions figées). **Pas** l'extra `docs` du `pyproject.toml` — la CI installe le premier |
| Construction | `mkdocs build --strict`. Un lien interne cassé ou une nav pointant vers une page inexistante fait échouer la construction, plutôt que de publier silencieusement un 404 |
| Redirections | `hooks/redirects.py`, **après** la construction, écrit des pages-souches meta-refresh selon les URL finales, raccordant les anciennes adresses à plat (`/start/`, `/workflow/`, `/case-ht001/`…) aux nouveaux emplacements |
| Déploiement | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publié sur GitHub Pages |

Modifier la documentation en local :

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # prévisualisation locale
mkdocs build --strict         # à lancer avant de commiter, c'est la commande de la CI
```

La CI se déclenche sur un push vers `main` **et** si les modifications touchent ces chemins ;
sinon on peut lancer manuellement un `workflow_dispatch` depuis la page Actions :

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Pourquoi `install.sh` est publié depuis Pages {#installsh-为什么从-pages-发}

L'étape de construction se termine par cette ligne :

```yaml
- run: cp install.sh site/install.sh
```

Le script d'installation est glissé dans l'artefact du site, il est donc servi depuis le domaine
de la documentation, et l'installation en une ligne ressemble à ceci :

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

La raison est très concrète : **`raw.githubusercontent.com` est inaccessible en Chine, alors que
`*.github.io` passe** (mesuré). Le script lui-même reste à la racine du dépôt, on en fait
simplement une copie à la publication — pas deux contenus à maintenir, pas de CDN supplémentaire.

Ce que `install.sh` fait de son côté : choisir un installeur d'outils Python (`uv` > `pipx` >
installer `uv` > `pip --user`), installer flower depuis GitHub, puis indiquer l'étape suivante. Il
**ne touche pas aux identifiants** — le premier lancement de `flower` les demande et les enregistre
dans `~/.config/flower/.env`.
