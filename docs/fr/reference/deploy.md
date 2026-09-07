# Déploiement et extension

Transporter flower ailleurs suppose de régler trois choses : le conteneur (enfermer un Bash non
restreint, et au passage vérifier la formule « sans le CLI »), les
[plugins](glossary.md#plugin) (les capacités métier voyagent avec le dépôt, sans rien attendre de
la machine hôte) et le site de documentation (un push sur `main` publie automatiquement,
`install.sh` est servi depuis le domaine Pages). Les trois sections sont indépendantes, lisez ce
dont vous avez besoin.

## I. Le conteneur

### Pourquoi un conteneur

**D'abord, pour enfermer.** Le [worker](glossary.md#执行者) qui travaille dispose d'un **Bash non
restreint** — la liste blanche Bash de flower (`delegate_guard`) ne couvre que le
[thread principal](glossary.md#主线程), et les délégués doivent pouvoir lancer les tests : c'est
délibéré. Dans le conteneur, seul votre répertoire de projet est monté ; le code source du
framework est dans l'image sous `/opt/flower`, et le reste de l'hôte est invisible.

**Ensuite, parce que c'est en soi la vérification de la contrainte de
[portabilité](glossary.md#可移植).** L'image ne contient ni le CLI Claude Code, ni Node —
uniquement Python et `claude-agent-sdk` : les requêtes partent via le binaire natif embarqué dans
la wheel. Si ça tourne ici, « sans le CLI » n'est pas une affirmation de papier.

Validé en conditions réelles (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0) :

| Ce qui est vérifié | Résultat |
|---|---|
| Présence d'un CLI dans l'image | `claude`, `node`, `npm`, `npx` **n'existent pas** |
| Binaire embarqué | `\177ELF` (207M) |
| Requête réelle | Émise via `cloud.infini-ai.com/maas` avec réponse obtenue, `$0.1741 / 1 tour` (c'est le plancher d'un tour unique avec Opus 5 + fenêtre 1M) |
| Propriété des fichiers | Un fichier écrit dans `/work` depuis le conteneur apparaît en `hechenyu:staff` sur l'hôte, mapping correct |
| Visibilité de l'hôte | Dans le conteneur, `ls /Users` → `No such file or directory` |

### Ce qui est installé dans l'image

Image de base `python:3.13-slim`, plus trois paquets apt. Chacun a sa raison :

| Installé | Pourquoi |
|---|---|
| `python:3.13-slim` | Il ne faut que Python ≥ 3.10. Pas de Node, pas de CLI claude |
| `git` | `--isolate` doit attribuer un worktree à chaque [subagent](glossary.md#subagent) |
| `ca-certificates` | Passage par une passerelle HTTPS |
| `libstdc++6` | Le binaire embarqué dans le SDK est un fichier unique compilé avec Bun ; il en a besoin sous Linux, et l'image slim ne l'inclut pas |

Le code source du framework entre dans l'image par `COPY`, **pas par bind mount** — l'agent dans
le conteneur ne peut donc pas atteindre le code source du framework sur l'hôte :

| Chemin dans l'image | Contenu | Origine |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, avec un `pip install .` sur place | `COPY` |
| `/work` | Répertoire de travail (`WORKDIR`), sur lequel on monte le `$PWD` de l'hôte à l'exécution | `docker run -v` |

Le point d'entrée est `ENTRYPOINT ["flower"]`, et `CMD` est vide — lancer le conteneur sans
argument ouvre la saisie interactive (il vous demande ce que vous voulez faire) au lieu d'afficher
`--help`. On évite ainsi d'avoir à mettre entre guillemets une demande en langue naturelle dans le
shell.

### Pourquoi on ne peut pas monter le `.venv` de l'hôte

Le SDK publie une wheel par plateforme, et le binaire embarqué est spécifique à la plateforme :

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Le monter ne fonctionne pas, donc l'image doit faire son propre `pip install`. À l'inverse, c'est
aussi une preuve de portabilité : un même `pyproject.toml`, un binaire natif différent selon la
plateforme, et pas une ligne de code du framework à changer.

### Les deux scripts

| Script | Rôle |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Construit l'image. `cd` à la racine du dépôt, `docker build -f docker/Dockerfile -t flower-box .` ; avec `FLOWER_MIRRORS=1` (défaut), tire d'abord `python:3.13-slim` depuis un miroir de registry puis le retague, en ajoutant les `--build-arg` pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Lance une exécution. Vérifie le fichier d'identifiants → vérifie que `$PWD` est montable → détecte la présence d'un TTY → `docker run` |

Les réglages de `docker/build` passent tous par des variables d'environnement :

| Variable | Défaut | Sémantique |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Tag de l'image |
| `FLOWER_MIRRORS` | `1` | `0` = aucun miroir substitué, tout passe par les sources amont |
| `FLOWER_REGISTRY` | `dockerproxy.net` | Tire l'image de base d'ici puis la retague en `python:3.13-slim`, pour que le `FROM` tombe sur la copie locale |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Passé à `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Passé à `--build-arg APT_MIRROR` |

Les trois derniers n'agissent que si `FLOWER_MIRRORS=1` — la branche `FLOWER_MIRRORS=0` ne définit
tout simplement aucun build-arg.

`docker/flowerbox` en reconnaît deux :

| Variable | Défaut | Sémantique |
|---|---|---|
| `FLOWER_HOME` | Un niveau au-dessus du script lui-même (donc la racine du dépôt) | Où chercher `.env`. Si `$FLOWER_HOME/.env` est introuvable, sortie 1 |
| `FLOWER_IMAGE` | `flower-box` | Quelle image lancer |

`FLOWER_HOME` est déduit de l'emplacement du script, sans chemin en dur : le dépôt fonctionne où
qu'il soit cloné.

### Lancer

```bash
docker/build                       # une fois suffit
cd ~/任意项目目录                   # doit être sous $HOME, voir les limites de montage ci-dessous
/path/to/flower/docker/flowerbox   # sans argument → il vous demande quoi faire, pas de guillemets à gérer
```

Si l'accès à pypi.org / Docker Hub est normal, la construction se lance ainsi :

```bash
FLOWER_MIRRORS=0 docker/build
```

Les arguments de `flowerbox` sont exactement ceux de `flower` — il place `"$@"` tel quel derrière
l'`ENTRYPOINT`. `--clarify-only`, `--asks N`, `--timeout secondes`, `--isolate`, `-v` passent tous ;
tableau complet dans [ligne de commande](cli.md) :

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

La commande réellement exécutée est celle-ci (`-t` n'est ajouté qu'en présence d'un TTY, voir plus
bas) :

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Limites de montage et persistance

```text
宿主 $PWD  ──挂载──>  /work       ← l'agent travaille ici, les livrables restent sur l'hôte
镜像内                /opt/flower ← code source du framework, **non monté**, inaccessible depuis l'hôte
```

Il est donc sûr de lancer depuis un sous-répertoire du dépôt comme `flower/human-test/HT001` :
seul `HT001` est monté, le code source du framework est hors du périmètre de montage.

| Élément | Survit à la sortie ? | Pourquoi |
|---|---|---|
| Tout ce qui est sous `$PWD` sur l'hôte, y compris `runs/` et le [workbench](glossary.md#工作台) `.flower/` | Oui | C'est précisément le répertoire monté sur `/work` |
| Ce qui est écrit ailleurs dans le conteneur | Non | `--rm`, le conteneur est supprimé à la sortie |
| Identifiants | N'entrent pas dans les couches de l'image | Passent par `--env-file` ; `.env` est exclu dans `.dockerignore`, donc même un `COPY . .` ne l'embarquerait pas |

!!! danger "Le répertoire de projet doit être sous `$HOME`, sinon les livrables sont perdus silencieusement"
    **colima ne monte par défaut que `$HOME` dans la VM** (`mount | grep virtiofs` → `mount0 on /Users/<vous>`).
    Si vous lancez depuis un endroit comme `/tmp`, `-v` crée un **répertoire vide** dans la VM ;
    ce qui y est écrit n'est jamais visible sur l'hôte, **et aucune erreur n'est levée** —
    livrables, [brief](glossary.md#需求确认书) et `runs/` sont tous perdus. C'est arrivé une fois :
    un `once` terminé, $0.17 dépensés, et `runs/` n'existait tout simplement pas sur l'hôte.

    `flowerbox` bloque désormais ce cas : si `$PWD` est sous `$HOME`, il laisse passer ; sinon il
    écrit un fichier sonde dans `$PWD`, puis démarre un conteneur pour tester réellement
    `test -f /work/<sonde>` (un montage supplémentaire configuré passe aussi le test). En cas
    d'échec, sortie 1 avec l'indication `colima start --mount '<chemin>:w'`. La sonde nécessite de
    démarrer un conteneur, donc il faut avoir fait `docker/build` au préalable.

### Identifiants

Ils passent par `docker run --env-file`, et **n'entrent pas dans les couches de l'image**.
`flowerbox` lit `$FLOWER_HOME/.env`, c'est-à-dire par défaut le `.env` à la racine du dépôt :

```bash
cp .env.example .env       # renseignez le token ; .env est déjà dans le gitignore
```

Attention : `flower setup` écrit dans `~/.config/flower/.env`, et **`flowerbox` ne regarde pas ce
chemin**. Si vous avez déjà configuré via `setup` et ne voulez pas dupliquer, pointez `FLOWER_HOME`
dessus :

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Noms de clés, priorités, configuration de la passerelle : voir [configuration](config.md).

!!! warning "Sans TTY, une question bloque jusqu'au `--timeout`"
    `flowerbox` n'ajoute `-t` que si `[ -t 0 ]` — `docker run -t` échoue immédiatement dans un pipe
    ou en CI avec « the input device is not a TTY » ; `-i` est toujours nécessaire, sans quoi stdin
    n'entre pas du tout.

    Les réponses aux questions passent par l'entrée standard. Sans TTY, `input()` lève un
    `EOFError` dès la première fois → la question courante est traitée comme « entrée fermée » et
    ignorée, et **le thread de réponse se termine**, si bien que plus personne ne prend la deuxième
    question : on attend jusqu'à l'expiration du `--timeout` (1800 secondes par défaut). En mode
    non supervisé, il faut passer explicitement `--timeout 0`. Le script affiche un avertissement
    quand il détecte l'absence de TTY.

### Sous-module git

`.gitmodules` ne contient qu'une entrée :

| path | url | Ce que c'est |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | Le dépôt de code **produit par** le run [HT001](../cases/ht001.md), conservé pour archive |

Un `git clone` ordinaire ne le récupère pas : `human-test/HT001` est un répertoire vide (c'est
l'état signalé par le `-` en tête de `git submodule status`). Faut-il s'en occuper :

| Ce que vous voulez faire | Faut-il l'initialiser ? |
|---|---|
| Lancer flower, construire l'image | **Non**. `.dockerignore` exclut `human-test/`, et le `Dockerfile` ne fait de toute façon que `COPY` `pyproject.toml` / `flower` / `examples` |
| Consulter localement le code produit par HT001 | Oui : `git submodule update --init human-test/HT001`, ou dès le départ `git clone --recurse-submodules` |

### Réseau en Chine : pourquoi toutes ces substitutions de miroirs

Quand on installe tout ça derrière le pare-feu, ce n'est pas la bande passante qui est lente, ce
sont les liaisons internationales. Le `docker/build` par défaut substitue déjà tout ce qu'il faut,
et `FLOWER_MIRRORS=0` désactive l'ensemble d'un coup. Ci-dessous les mesures et l'origine des
quatre substitutions — inutile de lire si votre réseau n'a pas ce problème.

??? note "Table de débits mesurés et les quatre substitutions (2026-09-06, macOS/arm64)"

    | Source | Débit |
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
    | `dockerproxy.net` (proxy Docker Hub) | Fonctionnel (renvoie directement le manifest) |

    En mesurant, ne prenez pas la **page d'index** pour un fichier de paquet :
    `mirrors.aliyun.com/pypi/simple/` sert cette page à 7.4 MB/s, alors que la vraie wheel de
    95.9 MB ne monte qu'à 1.4 MB/s (152 KB/s dans la VM — le réseau en espace utilisateur de colima
    coûte cher). Estimez les temps à partir des chiffres des fichiers de paquets.

    **Substitution 1 — l'image de VM de colima.** colima n'utilise pas une image cloud Ubuntu
    ordinaire, mais sa propre image personnalisée **avec docker préinstallé** (un asset de release
    de `abiosoft/colima-core`) : au démarrage de la VM, pas besoin d'installer docker via apt, ce
    qui contourne le `download.docker.com` injoignable. Téléchargez-la vous-même puis passez-la avec
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

    Le proxy coupe parfois en cours de route (curl 56 en pratique) ; `-C -` reprend le
    téléchargement, il suffit de relancer quelques fois.

    **Substitution 2 — apt dans la VM.** Même avec l'image à docker préinstallé, le script de boot
    de lima `30-install-packages.sh` lance quand même un `apt-get update` pour installer `rsync` —
    il tape `ports.ubuntu.com` (26 KB/s) et `download.docker.com` (4 KB/s), ce qui peut bloquer
    plusieurs dizaines de minutes.

    Traitement (**lisez `/mnt/lima-cidata/boot.sh` avant d'agir** : pour un script de boot en échec
    il se contente d'un `WARNING` + `CODE=1` puis continue, et il écrit **toujours**
    `/run/lima-boot-done` à la fin ; faire échouer cette étape est donc sans danger) :

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
      pkill -f "apt-get update"          # boot.sh ira au bout et écrira le marqueur de fin
    '
    # colima start se termine ensuite normalement ; on installe rsync après coup (1.95 MB/s maintenant)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Au passage, ajoutez `127.0.0.1 lima-colima` au `/etc/hosts` de la VM pour faire disparaître la
    série d'avertissements `sudo: unable to resolve host`.

    **Substitution 3 — l'image de base.** `docker/build` tire d'abord `python:3.13-slim` depuis
    `dockerproxy.net` puis la retague, pour que le `FROM` du Dockerfile tombe sur la copie locale.
    En pratique `dockerproxy.net` renvoie directement le manifest (HTTP 200) ; `docker.1ms.run` /
    `docker.m.daocloud.io` renvoient 401, `hub.rat.dev` 302, `docker.xuanyuan.me` 403.

    **Substitution 4 — apt et pip dans le conteneur.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) et
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Notez que `PIP_INDEX_URL`
    est aussi une variable d'environnement reconnue par pip lui-même : dès que l'`ARG` est déclaré,
    le pip du RUN la lit — pas besoin d'écrire explicitement `--index-url`.

    La préparation ponctuelle prend au total environ 25 minutes dans ces conditions réseau,
    l'essentiel étant les 364 MB de l'image de VM et les 95.9 MB de la wheel du SDK. Ensuite, le
    démarrage de `flowerbox` se compte en secondes.

## II. plugin {#plugin}

### Ce que c'est

Un **paquet de capacités métier qui voyage avec le dépôt**. Le code du framework ne contient aucune
connaissance métier ; toute la connaissance métier est placée dans le répertoire `plugin/` à la
racine du dépôt, clonée avec le code, relue avec le code, taguée avec le code.

Le câblage côté SDK tient en deux lignes, dans `build_options()` de
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) :

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Combiné à `setting_sources=[]` (traité plus bas), c'est ce qui permet à flower d'être à la fois
« [portable](glossary.md#可移植) » et « au fait de votre domaine » : il ne demande pas ce qui est
installé sur la machine hôte, il ne connaît que ce répertoire apporté par le dépôt.

### Structure du répertoire

| Chemin | Contenu | Quand ça s'applique | Qui décide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | Identité du paquet : `name`, `description`, `version`, `author` | Lu une fois au chargement | — |
| `plugin/skills/<name>/SKILL.md` | Connaissance métier, chargée à la demande | **Probabiliste** — utilisée si le modèle la juge pertinente | Le modèle |
| `plugin/agents/<name>.md` | subagent, fenêtre de contexte indépendante | Délégation par le modèle, ou désignation explicite dans le [workflow](glossary.md#流程) | Le modèle / vous |
| `plugin/hooks/hooks.json` | Interception des appels d'outils | **Déterministe** — exécuté dès qu'il y a correspondance | Le code |
| `plugin/.mcp.json` | Raccordement d'outils externes | Enregistrés comme outils, au même titre que les outils intégrés | Le modèle |

**La différence entre probabiliste et déterministe est le critère de choix, pas une nuance de
vocabulaire :**

- une skill est **une connaissance posée là**. Le modèle voit sa `description` et ne va la lire que
  s'il la juge pertinente pour la tâche courante. Ce jugement de pertinence est fait par le modèle :
  la même demande lancée deux fois peut l'utiliser une fois et pas l'autre ;
- un hook est **du code**. Il s'exécute dès que l'événement correspond, indépendamment de ce que le
  modèle veut ou sait. Le [spill](glossary.md#落盘) et l'[isolation](glossary.md#隔离) de flower
  sont des hooks, précisément parce qu'ils ne peuvent pas s'appliquer « parfois ».

Le critère est donc unique : **est-ce que cela doit arriver à chaque fois ?** Si oui — écrivez un
hook. Si c'est seulement « bon à savoir » — écrivez une skill. Mettre une obligation dans une skill,
c'est parier la discipline sur un jugement ponctuel du modèle.

Aujourd'hui, `plugin/` ne contient que deux choses dans le dépôt : `.claude-plugin/plugin.json` et
`skills/example/SKILL.md`. `agents/`, `hooks/` et `.mcp.json` **n'existent pas encore** — créez-les
vous-même si besoin, avec exactement les noms de répertoires du tableau ci-dessus.

### Écrire une skill : exemple complet

Prenons « générer des notes de version », de zéro jusqu'à la confirmation que c'est actif.

**Étape 1 : créer le répertoire.** Le nom du répertoire est le nom de la skill, et doit
correspondre au `name` du frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Étape 2 : écrire `plugin/skills/release-notes/SKILL.md`.** Le nom de fichier doit être
`SKILL.md`, en majuscules. Le format est un frontmatter YAML + un corps Markdown, avec deux champs
dans le frontmatter :

| Champ | Rôle |
|---|---|
| `name` | Identifiant de la skill. Identique au nom du répertoire |
| `description` | **Le modèle ne se base que sur cette ligne pour la choisir**. Écrivez « quand l'utiliser », pas « ce que c'est » |

Un fichier minimal directement utilisable :

````markdown
---
name: release-notes
description: À utiliser pour rédiger des notes de version. Quand l'utilisateur dit « écris les release notes », « qu'est-ce qui a changé dans cette version », « on publie ».
---

# Notes de version

## Où prendre la matière

```bash
git describe --tags --abbrev=0        # le tag précédent
git log --oneline <上一个 tag>..HEAD   # les commits de cette version
```

## Format de sortie

Trois sections, chacune une liste à puces, une ligne par entrée, décrivant des changements
perceptibles par l'utilisateur, sans refactorings internes :

- **Ajouts** — ce que cette version permet de faire et qui n'était pas possible avant
- **Corrections** — ce qui a été corrigé, symptôme en une phrase
- **Ruptures de compatibilité** — ce qu'il faut modifier pour mettre à jour. S'il n'y en a pas, on omet la section entière

## Limites

- Ne pas inventer le numéro de version : le lire dans le champ `version` de `pyproject.toml`.
- En cas de doute sur le caractère perceptible d'un commit, le lister et poser la question ; ne pas décider à la place de l'utilisateur.
````

Le corps n'a pas de format imposé — c'est simplement un texte chargé dans le contexte. Inspirez-vous
de [`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md) :
préciser **quand l'utiliser**, **les étapes**, **la forme de la sortie** et **les limites** est plus
utile qu'accumuler du contexte.

**Étape 3 : confirmer qu'elle est chargée.** Ne vérifiez qu'une seule chose certaine — le
répertoire est-il là ou non :

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Ce n'est que si cela affiche `/path/to/flower/plugin True` que le `if` de `build_options()` sera
pris. Si cela affiche `False`, rien n'est chargé, et **aucune erreur n'est levée à l'exécution** :
voir l'avertissement ci-dessous.

**Ne prenez pas « je lance une demande et je regarde si la skill `example` est invoquée » pour une
vérification.** Une skill est probabiliste : si le modèle ne l'appelle pas, cela peut vouloir dire
qu'elle n'est pas installée, ou simplement qu'il n'a pas jugé la tâche concernée — ce signal ne
distingue pas les deux cas. De plus, `build_options()` ne définit jamais l'option `skills=` de
niveau session du SDK ; savoir si les skills d'un plugin apparaissent réellement dans la liste des
options du coordinateur n'a pas été vérifié en pratique. Le `True`/`False` de `PLUGIN_DIR`
ci-dessus, lui, est certain : servez-vous-en.

Pour activer nommément certaines skills sur un [worker](glossary.md#执行者), utilisez
`worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)) ;
les noms sont ceux du champ `name` de `SKILL.md`, et le SDK accepte aussi la forme qualifiée
`nom-du-plugin:nom-de-la-skill`.

!!! warning "Un flower installé n'a pas de `plugin/` — aucune des trois méthodes d'installation ne l'inclut"
    `PLUGIN_DIR` remonte de trois niveaux depuis `flower/core/agent.py` puis descend dans `plugin/`.
    Lancé depuis un checkout des sources, c'est bien le `plugin/` à la racine du dépôt ; mais la
    wheel n'empaquette que le répertoire `flower` (dans `pyproject.toml` :
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`). Après installation dans
    site-packages, `site-packages/plugin` n'existe pas et `PLUGIN_DIR.is_dir()` est faux — **le
    chargement est ignoré silencieusement, sans erreur ni avertissement**.

    **Ce n'est pas un problème de conteneur, la portée est bien plus large.** Tous les chemins de
    `install.sh` — `uv tool install`, `pipx install`, bootstrap de uv puis uv, et le repli
    `pip install --user` — installent une wheel. Autrement dit, **avec un flower installé en une
    ligne, le paquet de capacités métier est systématiquement désactivé en silence**. Le conteneur
    n'est qu'une instance du même problème : `docker/Dockerfile` ne fait un `COPY` que de
    `pyproject.toml`, `flower/` et `examples/` ; `plugin/` n'entre pas dans l'image.

    Suivi dans l'[issue #15](https://github.com/ChenyuHeee/flower/issues/15). Après installation,
    lancez d'abord la commande `PLUGIN_DIR` ci-dessus pour vérifier : si elle affiche `False`,
    l'installation n'a pas de paquet de capacités métier. Pour utiliser un paquet de capacités
    métier, il faut aujourd'hui lancer depuis un checkout des sources.

### Pourquoi `setting_sources=[]` force les capacités métier à passer par les plugins

La même fonction contient aussi cette ligne :

```python
"setting_sources": [] if portable else ["project"],
```

Le défaut du SDK est `None` = lire les trois sources : `~/.claude/settings.json` (utilisateur),
`.claude/settings.json` (projet), `.claude/settings.local.json` (local). flower passe `[]` par
défaut, ce qui les **désactive toutes**.

| | Lu ? | Conséquence |
|---|---|---|
| `~/.claude/` (machine hôte) | Non | Comportement identique d'une machine à l'autre, pas de résultat différent parce que « ma machine est configurée » |
| `.claude/` du projet | Non | Ce qui est placé dans `.claude/skills/` ou `.claude/agents/` n'a **aucun effet** sous flower |
| `plugin/` | Oui | Chemin en dur dans le code, voyage avec le dépôt |
| Identifiants | Ne passent pas par là | Il faut apporter son `.env` ; les blocs `env` de `~/.claude/settings.json` et `settings.local.json` ne servent que de dernier repli, et **seules 9 clés d'identifiants** sont prises, voir [configuration](config.md) |

Que `.claude/` ne s'applique pas **n'est pas un oubli de configuration, c'est la définition de la
contrainte** : dès qu'on lit un seul octet depuis la machine hôte, « comportement identique d'une
machine à l'autre » ne tient plus. Les capacités métier n'ont donc qu'un seul canal — le `plugin/`
qui voyage avec le dépôt.

Deux réglages (tous deux sur `build_options()`, les valeurs par défaut étant celles de la
portabilité) :

| Paramètre | Défaut | Effet si modifié |
|---|---|---|
| `portable` | `True` | Passer `False` → `setting_sources` devient `["project"]`, le `.claude/` du projet est lu (côté SDK : lire `CLAUDE.md` exige `"project"`). La portabilité est perdue du même coup |
| `use_plugin` | `True` | Passer `False` → `plugin/` n'est plus monté du tout, les capacités métier reposent entièrement sur `AgentSpec.instructions` |

Au passage : `instructions` passe par l'[append](glossary.md#叠加) (`append` du `system_prompt`),
c'est un canal différent des plugins — le premier est présent dans le contexte à chaque tour, le
second est chargé à la demande. Écrivez dans `instructions` les règles courtes et obligatoires, et
dans une skill les connaissances longues et occasionnellement utiles.

## III. Le site de documentation

Le site que vous lisez est construit avec mkdocs-material ; les sources sont dans `docs/` du dépôt,
et un push sur `main` publie automatiquement.

| Élément | Ce que c'est |
|---|---|
| Configuration | `mkdocs.yml`, `docs_dir: docs` |
| Multilingue | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/`… la langue par défaut est `zh` |
| Dépendances | `docs-requirements.txt` (versions figées). **Pas** l'extra `docs` de `pyproject.toml` — la CI installe le premier |
| Construction | `mkdocs build --strict`. Un lien interne cassé ou une nav pointant vers une page inexistante fait échouer la construction, plutôt que de publier silencieusement un 404 |
| Redirections | `hooks/redirects.py`, **après** la construction, écrit des pages relais meta-refresh d'après les URL finales, reliant les anciennes adresses à plat (`/start/`, `/workflow/`, `/case-ht001/`…) aux nouveaux emplacements |
| Déploiement | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publié sur GitHub Pages |

Modifier la documentation en local :

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # prévisualisation locale
mkdocs build --strict         # à lancer avant commit, même commande que la CI
```

La CI se déclenche sur un push vers `main` **et** si les modifications touchent ces chemins ; on
peut par ailleurs déclencher manuellement un `workflow_dispatch` depuis la page Actions :

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Pourquoi `install.sh` est servi depuis Pages

L'étape de construction se termine par cette ligne :

```yaml
- run: cp install.sh site/install.sh
```

Le script d'installation est glissé dans l'artefact du site, il est donc servi depuis le domaine du
site de documentation, et l'installation en une ligne ressemble à ceci :

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

La raison est très concrète : **`raw.githubusercontent.com` est inaccessible en Chine, alors que
`*.github.io` passe** (mesuré). Le script lui-même reste à la racine du dépôt, on en copie
simplement un exemplaire à la publication — pas de contenu en double à maintenir, pas de CDN
supplémentaire.

Ce que fait `install.sh` : choisir un installeur d'outils Python (`uv` > `pipx` > installer `uv` >
`pip --user`), installer flower depuis GitHub, puis indiquer l'étape suivante. Il **ne touche pas
aux identifiants** — le premier `flower` posera la question et stockera dans
`~/.config/flower/.env`.
