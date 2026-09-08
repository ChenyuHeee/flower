# Configuration

flower n'a pas de format de fichier de configuration, et aucune sous-commande de configuration qui aille vraiment jusqu'au bout — toute la configuration passe par des **variables d'environnement**, un **fichier `.env`**, plus une poignée d'objets de politique qui ne se donnent que depuis Python. Cette page rassemble en un seul endroit ce qui est éparpillé sur cinq : chaque variable, l'ordre de recherche des credentials, la syntaxe reconnue par `.env`, ce que `setting_sources=[]` isole exactement, ce qu'un run laisse sur le disque, ce que chacune des trois couches du session store jette, et comment ça attend quand le réseau tombe. Les termes suivent le [glossaire](glossary.md).

| Ce que vous cherchez | Où |
|---|---|
| Quelles variables d'environnement flower lit | [Table complète des variables d'environnement](#环境变量) |
| D'où vient réellement mon token | [Priorité de recherche des credentials](#凭证查找优先级) |
| Pourquoi cette ligne du `.env` n'a pas pris effet | [Règles de parsing `.env`](#env-解析) |
| Quoi emporter en changeant de machine | [Le prix de la portabilité](#可移植性) |
| Ce qu'il y a dans `.flower/` et `runs/` | [Disposition sur disque](#磁盘布局) |
| Quels messages ne sont pas redonnés au modèle | [Les trois couches du session store](#会话存储) |
| Ce qu'il attend quand le réseau est coupé | [Résilience hors ligne](#韧性) |

## Table complète des variables d'environnement {#环境变量}

Cinq groupes : les credentials et endpoints que flower lit directement, la sélection de modèle, la recherche de chemins, les interrupteurs de comportement, et celles que flower **écrit pour** le sous-processus agent. Ce dernier groupe n'est pas à régler — si vous le réglez, il sera écrasé.

### Credentials et endpoints {#凭证变量}

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Clé Anthropic officielle. Si elle est là, les requêtes partent avec l'en-tête `x-api-key` | aucun | **l'une des deux requise** avec `ANTHROPIC_AUTH_TOKEN` | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token émis par une passerelle. Sans `ANTHROPIC_API_KEY`, utilise `authorization: Bearer` | aucun | idem | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | Racine de l'endpoint API. Une passerelle tierce y met sa propre adresse, **sans `/v1`** — la sonde construit `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | non | `env.py:151`、`:162`、`:210` ; `resilience.py:70` |

Si aucune des deux n'est réglée (ou si les deux sont des chaînes vides), `check_credentials()` renvoie ce message d'erreur de quatre lignes et `Runtime.__init__` lève un `RuntimeError` (`env.py:184-194` ; `runtime.py:156-158`).

### Sélection de modèle {#模型变量}

flower n'en lit que trois pour ses propres décisions ; les autres sont chargées puis transmises telles quelles au SDK.

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nom du modèle principal. Détermine aussi la valeur par défaut de la fenêtre de [passation](glossary.md#换代) : nom contenant `1m` ou ne contenant pas `haiku` → 1 million, contenant `haiku` → 200 000 | aucun (décidé côté serveur) | non | `env.py:153` ; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapping du palier opus. Si `ANTHROPIC_MODEL` est vide, le calcul de fenêtre retombe dessus | aucun | non | `agent.py:78` ; `cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapping du palier sonnet. flower ne la lit pas lui-même, il ne fait que la charger et l'emprunter | aucun | non | `env.py:34` ; `cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapping du palier haiku. **La sonde de credentials l'utilise en priorité** | la sonde retombe sur `ANTHROPIC_MODEL`, puis sur `claude-3-5-haiku-20241022` | non | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Quel modèle pour les [subagents](glossary.md#subagent). flower ne l'interprète pas, c'est le SDK qui la consomme | aucun | non | `env.py:35` ; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Palier de réflexion. Idem, chargée mais non interprétée | aucun | non | `env.py:35` |

Si `flower setup` reçoit un nom de modèle, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` et `ANTHROPIC_DEFAULT_SONNET_MODEL` sont **écrites toutes les trois ensemble** (`cli.py:1383-1385`).

### Chemins et recherche {#路径变量}

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `FLOWER_ENV` | Désigne un chemin de fichier `.env`, placé **avant** tous les autres fichiers | aucun | non | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Détermine l'emplacement du fichier de credentials global `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | non | `env.py:41-42` |
| `HOME` | Source de `Path.home()` ; les deux chemins `~/.config` et `~/.claude` en dérivent | fourni par le système | non | `env.py:41`、`:67` |

### Interrupteurs de comportement {#行为开关}

Ce sont deux issues de secours : la norme est de ne pas les régler ; on les règle pour que flower en fasse une de moins. **N'importe quelle valeur non vide les active**, la valeur elle-même n'est pas interprétée (`update.py:121` ; `cli.py:1413`).

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | Désactive les [mises à jour automatiques](../getting-started/install.md#自动更新). Sans elle, un flower installé par pip / pipx / uv lance au démarrage un thread de fond qui vérifie s'il existe une nouvelle version et l'installe le cas échéant, **effective seulement au prochain `flower`** ; au plus une vérification toutes les 24 heures, l'horodatage étant écrit dans `~/.config/flower/.update` | aucun (mise à jour automatique active) | non | `update.py:32-33`、`:121-124` |
| `FLOWER_NO_PROBE` | Saute la [sonde de credentials](cli.md#第二道-凭证能不能用) du démarrage. En non interactif (pipe / CI / stdin redirigé) la sonde n'a de toute façon pas lieu ; cette variable est l'échappatoire pour les terminaux interactifs | aucun (sonde en interactif) | non | `cli.py:1413` |

Un flower lancé depuis les sources git n'est pas concerné par la mise à jour automatique, et `FLOWER_NO_UPDATE` y est un no-op — l'étape de commande de mise à jour reconnaît un `.git` dans le dépôt et renvoie directement `None` (`update.py:83-87`).

### Ce que flower écrit pour le sous-processus agent {#写出的变量}

Ces trois-là sont produites par `CompactPolicy.env()` puis injectées dans `ClaudeAgentOptions.env` (`agent.py:48-58`、`:241-245`) ; elles contrôlent le [compact](glossary.md#压缩) intégré au harness. **Les régler dans votre shell n'a aucun sens** — ce qui compte est la copie que flower transmet au sous-processus.

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` désactive le compact automatique. **Écrite de force** quand la [passation](glossary.md#换代) est active — avec les deux mécanismes en marche, on ne sait plus lequel a fait retomber le contexte | la passation est active par défaut, donc en pratique toujours `1` | non (écrite par flower) | `agent.py:51` ; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` désactive aussi `/compact`. Écrite uniquement avec `CompactPolicy(mode="off")` | non écrite | non (écrite par flower) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Fenêtre du compact automatique (tokens). Écrite uniquement avec `CompactPolicy(window=N)` | non écrite | non (écrite par flower) | `agent.py:56-57` |

### Ce que lit le wrapper de conteneur {#容器变量}

Ces deux-là ne sont pas lues par flower lui-même, mais par le wrapper shell `docker/flowerbox`. Usage complet dans [Déploiement](deploy.md).

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `FLOWER_HOME` | Où trouver le `.env` passé à `--env-file` | le répertoire parent de l'emplacement du script | non | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Quelle image utiliser | `flower-box` | non | `docker/flowerbox:13` |

**Les clés du `.env` ne se limitent pas à celles ci-dessus.** Le parser charge **toutes** les lignes `k=v` dans `os.environ`, sans liste blanche (`env.py:30`、`:102-107`). L'ensemble `KNOWN` formé par les 9 clés de credentials ci-dessus ne sert qu'à deux endroits : la liste blanche lors de l'emprunt de la configuration `~/.claude` (`env.py:72`), et l'étendue des champs affichés par `describe()` au démarrage avec `-v` (`env.py:205`).

## Priorité de recherche des credentials {#凭证查找优先级}

Sans chemin explicite, `load_dotenv()` lit **tous les fichiers existants** dans l'ordre suivant (`env.py:45-53`、`:78-112`) :

1. **Variables d'environnement du processus** — toujours prioritaires. Aucun `.env` ne recouvre une valeur déjà exportée. (`env.py:91`)
2. **Le fichier désigné par `$FLOWER_ENV`** — présent seulement si la variable est réglée. (`env.py:48-49`)
3. **`$PWD/.env`** — le répertoire de travail courant. Le projet dans lequel vous êtes, celui qui est lu. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — l'emplacement global, un par utilisateur ; c'est celui qu'écrit `flower setup`. (`env.py:51`、`:39-42`)
5. **Le `.env` à la racine du dépôt source** — trois niveaux au-dessus de `flower/core/env.py`. N'existe qu'en exécution depuis les sources ; un flower installé par pip / pipx / uv vit dans site-packages et n'a pas cette entrée. (`env.py:52`)
6. **Le bloc `env` de `~/.claude/settings.json`, puis de `~/.claude/settings.local.json`** — dernier repli, **9 clés de credentials uniquement**. (`env.py:56-75`、`:109-111`)

**Quel fichier gagne** : l'entrée 3 (`.env` du projet) bat l'entrée 4 (`.env` global), l'entrée 4 bat l'entrée 5 (`.env` racine du dépôt), les trois battent l'entrée 6 (configuration de Claude Code), et aucune ne bat l'entrée 1 (environnement du processus).

L'implémentation est « **une clé déjà pourvue n'est pas écrasée** » (`env.py:90-93`) : ceux qui passent en premier occupent les clés, les suivants ne comblent que les trous. La priorité est donc **par clé, pas par fichier** — si le `.env` du projet ne contient que `ANTHROPIC_BASE_URL`, le token peut parfaitement venir du fichier global. La première valeur rencontrée pour une clé donnée est définitive.

L'entrée 6 n'est activée qu'en **recherche automatique**. Un chemin explicite (`load_dotenv("/path/to/.env")`) ne lit que ce fichier, sans aucun repli (`env.py:86-87`、`:109`).

### Entrée 6 : emprunter le token de Claude Code {#借用}

On lit successivement `~/.claude/settings.json` et `~/.claude/settings.local.json`, on prend le dict `data["env"]`, et on y sélectionne ces 9 clés (`env.py:31-36`、`:65-74`) :

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Si le fichier n'existe pas, n'est pas lisible, ou n'est pas du JSON valide (`OSError` / `ValueError`), on renvoie un dict vide et on continue — **l'échec d'un repli ne doit pas emporter le run** (`env.py:62-63`、`:66-69`).

La position prise dans le code : on n'emprunte que « où trouver le token » ; rien d'autre dans settings.json (règles de permission, hooks, réglages de modèle) n'est repris, ce qui ne trahit donc pas la promesse de portabilité de `setting_sources=[]` (`env.py:17-19`、`:59-61`). `install.sh:77` en fait même un argument : qui a déjà configuré Claude Code localement ne verra jamais l'écran de configuration.

!!! warning "Le message d'erreur du produit dit le contraire du comportement réel"
    Quand aucun credential n'est trouvé, la dernière ligne de l'erreur affichée par flower est :

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, la phrase est en `:192` ; la même affirmation apparaît aussi dans `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **Le code fait foi : il le lit.** `env.py:56-75` plus `:109-111` vont explicitement lire ces deux fichiers, et `install.sh:77` en fait un argument de vente. Ce message est actuellement trompeur — sur une machine où Claude Code a été configuré, votre token vient très probablement de là.

## Règles de parsing `.env` {#env-解析}

Les règles sont assez courtes pour être mémorisées (`env.py:95-107`, 13 lignes) : `strip` ligne par ligne, on saute les lignes vides, celles qui commencent par `#`, et celles qui ne contiennent pas `=` ; le reste est coupé au **premier** `=` en clé et valeur, chaque côté est `strip`é, puis la valeur passe encore par `.strip("'\"")` — les guillemets simples ou doubles en tête et en queue sont retirés, **sans exiger qu'ils soient appariés**.

**Reconnu** :

| Écriture | Résultat |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — les espaces autour du signe égal sont strippés |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — les guillemets extérieurs sont retirés |
| `KEY=a=b` | la valeur est `a=b` — coupe au premier `=`, les suivants restent dans la valeur |
| `# commentaire` | ligne entièrement sautée |
| ligne vide | sautée |

**Non reconnu.** Aucune erreur n'est levée, vous obtenez simplement une valeur inattendue en silence :

| Écriture | Résultat réel |
|---|---|
| `export KEY=VALUE` | la clé devient `export KEY` ; `KEY` lui-même reste sans valeur |
| `KEY=value # commentaire` | la valeur est `value # commentaire` — le commentaire de fin de ligne n'est pas retiré |
| `KEY=$OTHER` | littéral `$OTHER`, aucune interpolation de variable |
| valeur multiligne (guillemets sur plusieurs lignes) | traitement ligne par ligne ; la deuxième ligne ne contient pas `=` et est sautée entièrement |

**Une valeur vide occupe quand même la clé.** Si `ANTHROPIC_AUTH_TOKEN=` apparaît dans un fichier prioritaire, `take()` exécute `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` ; les fichiers suivants ne peuvent plus la combler puisque « la clé existe déjà » (`env.py:90-93`), tandis que `check_credentials()` teste la véracité et considère une chaîne vide comme non configurée (`env.py:186`). **Résultat : ni credential, ni repli.** Si vous ne voulez pas d'une clé, supprimez la ligne entière ; n'en laissez pas une vide.

## Le prix de la portabilité {#可移植性}

Tout le mécanisme tient dans cette ligne de `build_options()` (`agent.py:207`) :

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` est la valeur par défaut de `Runtime`, et **aucune option de ligne de commande ne permet de la désactiver** — il faut passer par l'API Python avec `Runtime(portable=False)`, ce qui donne `["project"]`, c'est-à-dire la lecture du `.claude/` du projet.

### Ce qui est isolé {#被隔绝的东西}

| Isolé | Conséquence |
|---|---|
| Les réglages de `~/.claude/` de la machine hôte | Aucune des règles de permission, hooks ou réglages de modèle qui s'y trouvent ne prend effet. **Les credentials sont la seule exception**, voir [emprunt](#借用) |
| Le `.claude/` du projet | Idem, lu seulement avec `portable=False` |

Les capacités métier ne passent pas par là — elles sont distribuées avec le dépôt et chargées via `plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`、`:210-212`), voir [Déploiement](deploy.md). Les instructions métier sont quant à elles **appendées** après le system prompt natif de Claude Code, non substituées (`agent.py:198-202`) : la spécialisation ne se paie donc pas par une perte de capacité générale.

### Quoi emporter en changeant de machine {#换台机器要带什么}

- **Credentials : un fichier.** Copiez `~/.config/flower/.env`, ou reconfigurez-le sur la nouvelle machine. Sans lui, rien ne démarre — rien n'est hérité automatiquement.
- **État de continuité : le répertoire entier.** `runs/` (base de sessions, manifeste, lignage) et `.flower/` (workbench).
- **Mais les chemins doivent correspondre.** `lineage.json` stocke le chemin absolu de l'espace de travail ; s'il ne correspond pas, c'est comme s'il n'existait pas : repli silencieux vers une nouvelle session, **sans erreur** (`lineage.py:65-66`). La raison : le `project_key` du SDK dérive du chemin de l'espace de travail (`/`, `_` et `.` deviennent tous `-`, `runtime.py:40-41`) ; si le répertoire change de place, l'ancien `session_id` devient introuvable.

## Disposition sur disque {#磁盘布局}

Un run de flower écrit deux arbres : `<run_dir>/` pour la comptabilité et les sessions, `<workspace>/.flower/` pour le [workbench](glossary.md#工作台). Les deux sont par défaut sous le répertoire courant, mais **leur référence n'est pas la même**.

!!! warning "`runs/` suit le répertoire courant, pas `-w`"
    `-r/--run-dir` vaut `"runs"` par défaut, et `Runtime` lui applique `Path(run_dir).resolve()` (`runtime.py:93-94`) — relatif au **répertoire de travail courant**, pas à l'espace de travail donné par `-w`. Lancer `flower -w /path/to/proj` depuis `~` fait atterrir la base de sessions dans `~/runs/`, pas dans le projet.

### `<run_dir>/` — par défaut `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript intégral (y compris celui propre à chaque subagent)
  manifest.json      manifeste de run : session_id / coût / retries / cause d'échec par étape, cumulé entre processus
  lineage.json       lignage : nom d'étape → session_id, c'est ce qui permet de reprendre dans le même répertoire
  aside/             Runtime distinct des questions-réponses de l'oracle, avec son propre sessions.db + manifest.json
  workbench/         seulement en chemin run / once et avec -W
```

| Chemin | Contenu | Source |
|---|---|---|
| `runs/sessions.db` | Transcript intégral. L'écrivain est `PruningSessionStore`, les trois couches sont décrites [plus bas](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Tableau JSON, le [manifeste de run](glossary.md#运行清单) **cumulé entre processus**. Champs dans la table ci-dessous | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Écrit d'abord en `.tmp` puis `replace`, remplacement atomique | `lineage.py:31`、`:87-97` |
| `runs/aside/` | Runtime distinct de l'[oracle](glossary.md#旁路顾问). **Coûts et lignage ne se mélangent pas au manifeste principal** | `cli.py:741-743` |
| `runs/workbench/` | Emplacement par défaut du workbench pour `Runtime(workbench=True)`, hors de l'espace de travail. Le chemin `go` ne l'utilise pas | `runtime.py:148-151` |

Chaque ligne de `manifest.json` est un `asdict(StepResult)` plus deux correctifs (`runtime.py:44-71`、`:579-582`) :

| Champ | Type | Signification |
|---|---|---|
| `step` | `str` | Nom d'étape. Quatre formes : `<名>`, `<名>#round<N>` (renvoyée à refaire), `<名>#retry<N>` (retry ordinaire), `<名>·判定#<N>` ([juge](glossary.md#判定者)) |
| `session_id` | `str \| None` | La [session](glossary.md#会话) encore vivante à la fin de cette étape |
| `ok` | `bool` | Réussi ou non |
| `cost_usd` | `float` | Coût de cette étape |
| `num_turns` | `int` | Nombre de tours effectués |
| `text` | `str` | Réponse finale de cette étape |
| `error` | `str \| None` | Cause de l'échec. `killed-by-signal` en cas de mise à mort par SIGHUP / SIGTERM (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Secondes epoch |
| `attempts` | `int` | Nombre réel de tentatives. `>1` signifie qu'il y a eu retry |
| `errors` | `list[str]` | Causes des échecs successifs. **Ici seulement ; le modèle ne les voit pas** |
| `resumed` | `bool` | Repris depuis le point d'interruption par resume, plutôt que refait depuis le début |
| `retired` | `list[str]` | Les session_id brûlés lors des [passations](glossary.md#换代) de cette étape, dans l'ordre |
| `context` | `int` | Taille de contexte réellement vue par le [thread principal](glossary.md#主线程) au dernier tour |
| `duration_s` | `float` | Ajouté à la main — c'est une `@property`, `asdict()` ne la récupère pas |
| `run` | `str` | Marqueur du processus, `YYYYmmdd-HHMMSS-<6 位 hex>`. **Doit être unique par instance** |

La stratégie d'écriture est **ajout sans écrasement** : à chaque flush, le fichier est relu, les lignes dont `run` correspond au sien sont remplacées par les plus récentes, les lignes des autres restent intactes (`runtime.py:564-586`). Plusieurs flower en parallèle dans le même répertoire ne s'écrasent donc pas mutuellement leur comptabilité.

Le contenu de `runs/` est de la donnée pure, consultable hors ligne à tout moment avec sqlite3 ou [`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — le workbench {#工作台目录}

```text
.flower/
  INDEX.md      index généré automatiquement, injecté dans le system prompt de l'agent principal
  scripts/      scripts destinés à resservir. La première ligne `# desc: une phrase` apparaît dans l'index
  artifacts/    productions longues de plus de 2000 caractères : rapports, données, logs
  notes/        décisions consignées d'une étape à l'autre
  spill/        gros résultats d'outil spillés, nom de fichier = 16 premiers caractères du sha256 du contenu + `.txt`
```

Les trois sous-répertoires et l'index sont créés par `Workbench` (`workbench.py:73-92`). `INDEX.md` passe par le `system_prompt.append` au niveau de la session, **dont les subagents n'héritent pas** — la règle « les productions longues vont dans `artifacts/` » doit donc être relayée par le [coordinateur](glossary.md#协调者) dans le [brief de tâche](glossary.md#任务书), c'est le seul canal.

Le chemin `go` produit systématiquement ceci sous `notes/` :

| Fichier | Contenu | Source |
|---|---|---|
| `notes/需求.md` | Le [brief](glossary.md#需求确认书) gelé, quatre sections : objectif / critères d'acceptation / limites / inconnues et hypothèses | `brief.py:44-45` ; `clarify.py:105` |
| `notes/目标.md` | Deux sections gelées : objectif / liste de vérification du verdict | `workflow/goal.py:124` |
| `notes/问答记录.md` | Enregistrement en append de toutes les questions-réponses, y compris les entrées de boîte de réception « dites spontanément par l'humain ». **N'entre pas dans le contexte, sert d'archive** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | [Document de passation](glossary.md#交接书). La génération précédente est rangée dans `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | Les `lineage.json` + `需求.md` + `目标.md` archivés par `--new` / `/new` (**déplacés, pas supprimés**) | `lineage.py:100-117` |

**Avec `--isolate`, le workbench sort du dépôt** : `<répertoire parent du workspace>/.flower-<nom du workspace>/` (`starter.py:47-55`). Le worktree est la copie privée de chaque agent, le workbench est la couche partagée entre agents ; ce qui est partagé ne peut pas vivre dans un enclos privé. Dans ce cas, les chemins donnés au modèle sont absolus (`workbench.py:69-71`、`:142-145`).

**`spill/` a deux écrivains, avec des algorithmes de destination différents** :

| Qui écrit | Quand | Où | Seuil |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **avant** que le résultat d'outil n'entre dans le modèle | `<racine du workbench>/spill/` (`guard.py:130`) | `spill_threshold`, 4000 caractères par défaut |
| `TrimPolicy` (au `load`) | lors du rejeu de l'historique avant un resume | `<workspace>/.flower/spill/` — chaîne fixe relative à l'espace de travail (`trim.py:49`、`:303`) | `min_chars`, 2000 caractères par défaut |

Dans la disposition par défaut, c'est le même répertoire. Mais dès que le workbench est déplacé (`-W` le fait atterrir dans `runs/workbench/`, ou `--isolate` le sort du dépôt), les deux divergent — la copie de `TrimPolicy` reste toujours dans l'espace de travail, parce que le `Read` de l'agent doit pouvoir l'atteindre.

Ce que `spill_guard` met à la place n'est pas une ligne, mais une ligne de pointeur plus les **400 premiers caractères** (`guard.py:132-140`). Les appels qui lisent le fichier spillé lui-même sont laissés passer, sinon « lisez-le avec Read si vous voulez le texte intégral » serait une phrase creuse — on relit, ça dépasse encore le seuil, c'est spillé à nouveau, boucle infinie (`guard.py:155-170`).

### Schéma de `sessions.db` {#sessions-db}

Trois tables, DDL dans `stores/sqlite.py:27-51` :

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| Table | Ce qu'est une ligne | Points clés |
|---|---|---|
| `entries` | Une entrée du transcript, `payload` étant le JSON brut | `uid` est l'`uuid` de l'entrée, utilisé comme **clé d'idempotence** : un lot en échec est réessayé 3 fois, et le rejeu ne doit pas produire de doublons. Les entrées sans `uuid` (titres, tags, marqueurs de mode) ne sont pas dédupliquées, d'où l'index unique avec `WHERE uid IS NOT NULL` |
| `meta` | Le curseur d'une session | `next_seq` est le prochain numéro de séquence, `mtime` un horodatage en millisecondes **strictement monotone** (`sqlite.py:72-79`) — `list_sessions` et les summaries partagent cette horloge ; sans monotonie, la comparaison ancien/nouveau du SDK emprunte le mauvais chemin rapide |
| `summaries` | Le sidecar de résumé d'un thread principal | **Seuls les transcripts principaux comptent**, pas ceux des subagents (`sqlite.py:122-123`) |

Construction de `store_key` (`sqlite.py:54-58`) : `<project_key>/<session_id>`, avec un `subpath` supplémentaire pour les subagents. `project_key` est dérivé par le SDK du chemin de l'espace de travail — `/`, `_` et `.` deviennent tous `-`.

Un coup d'œil sur un échantillon réel ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)) :

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Cet exemplaire contient 956 `entries`, 10 `meta`, 4 `summaries` — sur les 10 sessions, 4 sont des transcripts principaux et 6 sont des subagents, et `summaries` égale exactement le nombre de transcripts principaux.

## Les trois couches du session store {#会话存储}

!!! note "Les trois couches sont une chaîne d'héritage, pas une combinaison optionnelle"
    `PruningSessionStore` hérite de `TrimmingSessionStore` qui hérite de `SqliteSessionStore`. `Runtime` construit **toujours** la couche la plus externe (`runtime.py:109-112`), et ses paramètres de construction n'offrent aucun point d'entrée pour changer de backend. Pour « désactiver une couche », on met `enabled` à `False` sur son objet de politique, on ne change pas de classe.

`append` (écriture) est toujours un enregistrement intégral, sans un mot de modifié. Les trois couches n'affectent que `load` (la copie relue pour être donnée au modèle). L'ordre réel de `load` est :

```text
SqliteSessionStore.load     lit tout depuis la table entries, par seq
  → TrimmingSessionStore.expire()   résultats Bash périssables → remplacés par « expiré »
  → TrimmingSessionStore.trim()     vieux gros tool_result → spill + remplacement par un pointeur
    → PruningSessionStore.prune()   messages d'erreur synthétiques / vieux appels refusés → entrée retirée et chaîne recousue
```

| Couche | Classe | Ce qu'elle jette | Critère |
|---|---|---|---|
| 1 | `SqliteSessionStore` | rien | —— |
| 2 | `TrimmingSessionStore` | le corps des gros résultats d'outil, les résultats de commandes éphémères périmés | volume + péremption |
| 3 | `PruningSessionStore` | les résidus de coupure réseau, les vieux appels refusés | est-ce une erreur |

La couche 2 fait le [trim](glossary.md#裁剪), la couche 3 le [prune](glossary.md#剪除) — **le trim jette selon le volume et la valeur, le prune jette selon « est-ce une erreur »** ; ne les confondez pas. Signatures complètes dans l'[API Python](api.md).

### `SqliteSessionStore` — les fondations {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implémentation SQLite sans dépendance externe. Pour passer à Postgres / S3 / Redis, il suffit d'implémenter le même protocole ; le SDK fournit la suite de tests de conformité `claude_agent_sdk.testing.session_store_conformance` qui permet de vérifier directement (`sqlite.py:1-8`).

En plus des méthodes du protocole, trois requêtes **synchrones** à l'usage propre de flower :

| Méthode | Retour | Usage |
|---|---|---|
| `projects()` | `list[str]` | Les `project_key` réellement présents dans la base. Le SDK les dérive du cwd ; confirmez avec ceci avant d'interroger, ne devinez pas |
| `has_session(project_key, session_id)` | `bool` | Interroge une seule ligne de `meta`, sans lire le payload. À vérifier avant de lancer une [continuité](glossary.md#接续) — un resume sur une session inexistante n'explose qu'après le démarrage du sous-processus, quand l'argent et le temps sont déjà dépensés |
| `last_context(project_key, session_id, scan=60)` | `int` | La taille de contexte vue au dernier tour de cette session. Ne scanne que les 60 dernières entrées à rebours. `input_tokens` plus les deux `cache_*` sont comptés — ne regarder que le premier donne une valeur proche de 0 en cas de cache hit, et sous-estime gravement |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Deux règles orthogonales. `TrimPolicy` gère le **volume** :

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Les N derniers `tool_result` gardent leur texte intégral — le contexte en cours d'utilisation ne doit pas être trimmé |
| `min_chars` | `int` | `2000` | En dessous, pas de trim. Remplacer par un pointeur coûterait plus de tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Répertoire d'archive, **relatif au workspace**. Doit être dans l'espace de travail, sinon le `Read` de l'agent ne peut pas l'atteindre |
| `enabled` | `bool` | `True` | Vaut `False` avec `Runtime(trim=False)` (le défaut) |

Le corps trimmé est écrit dans `<16 premiers caractères du sha256>.txt`, et la position d'origine est remplacée par `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`、`:308-317`).

`EphemeralPolicy` gère la **péremption** : les résultats de `git status`, `ls`, `ps` sont très courts et ne seraient jamais candidats au trim par volume, mais leur justesse se dégrade avec le temps — le `git status` d'il y a 20 tours n'est pas « inutile », il **induit en erreur**.

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converti depuis `Runtime(ephemeral=…)`, **actif par défaut** |
| `keep_recent` | `int` | `6` | Les N derniers gardent leur texte. Bien plus petit que les 20 de `TrimPolicy` — pour ce genre de choses, la fenêtre du « récent » est intrinsèquement courte |
| `max_chars` | `int` | `2000` | Au-delà, l'archivage par spill revient à `TrimPolicy`, pas à cette voie |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texte de remplacement |

Ne s'applique qu'aux résultats de l'outil **Bash**, et la commande doit correspondre à `EPHEMERAL_CMD`. `Read` n'en fait pas partie : le contenu d'un fichier ne se dénature pas avec le temps au point d'induire en erreur, et il peut être précisément la base du raisonnement du modèle (`trim.py:153-160`). Le contenu périmé **n'est pas spillé** — archiver un `git status` périmé n'a aucun sens, il suffit de le relancer.

La fonction de décision est `is_ephemeral(cmd)`, qui est **en même temps la liste des permissions rendues au coordinateur** : `delegate_guard(allow_glance=True)` utilise la même fonction (`trim.py:63-68`、`:128-150`). Les deux ensembles doivent rester identiques — autoriser sans trimmer laisse un `git status` périmé occuper le contexte à jamais ; trimmer sans autoriser fait déléguer un subagent par le coordinateur pour un simple `ls`, 4,3k de coût de démarrage pour quelques dizaines de caractères. Ajouter une commande à la liste blanche, c'est dire ces deux choses à la fois.

**Quand utiliser quoi** :

- Vous voulez seulement que les résidus de coupure réseau n'entrent pas dans le contexte → rien à faire, `Runtime` utilise déjà `PruningSessionStore` par défaut. `trim=False` se contente de ne pas trimmer les gros résultats ; le retrait, lui, a bien lieu.
- Run de longue haleine, sorties d'outil volumineuses → `trim=True`. Le CLI du chemin `go` l'active déjà par défaut ; `--no-trim` le désactive.
- Le [coordinateur](glossary.md#协调者) a `glance=True` → `ephemeral` doit rester actif, raison au paragraphe précédent.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Retire les messages synthétiques marqués `isApiErrorMessage=true` ou `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Pour un `tool_result` contenant `[Request interrupted …]`, **remplace le corps sans retirer le bloc** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texte de remplacement de l'entrée précédente |
| `heal_orphans` | `bool` | `True` | **Ajoute** un résultat synthétique aux appels orphelins qui ont un `tool_use` sans `tool_result` |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | Corps du `tool_result` ainsi ajouté |
| `keep_denials` | `int` | `1` | Conserve les N derniers appels d'outil refusés par le hook de permission ; les plus anciens sont retirés **appel et résultat compris** |

`keep_denials` est le seul paramètre de construction de `Runtime` transmis jusqu'à cette couche (`Runtime(keep_denials=N)`). La raison du défaut 1 plutôt que 0 : le refus le plus récent est un signal utile, il empêche le modèle de retenter en boucle la même commande bloquée dans un même tour. **Ne l'augmentez pas** — un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information, il occupe 273 caractères mesurés (93 caractères de message de refus plus 180 caractères de la commande morte), et il **induit en erreur** : mesuré, après avoir lu quelques « n'utilise pas Bash directement », le coordinateur cesse même d'essayer le `git status` pourtant autorisé et déclare « Bash est restreint, envoyons un agent voir » (`prune.py:135-148`).

`heal_orphans` soigne le cas où **tout resume après une interruption renvoie 400** : l'interruption coupe à une frontière de message, le `tool_use` en vol à ce moment-là peut n'avoir aucun `tool_result` derrière lui, alors que l'API exige la paire. Cette mauvaise histoire reste dans le transcript et ne disparaît pas d'elle-même, si bien que chaque resume ultérieur est rejeté par elle. La réparation consiste à insérer une entrée `user` juste après l'assistant contenant les orphelins, à y compléter d'un coup les résultats de tous ces orphelins, puis à réorienter vers cette nouvelle entrée le `parentUuid` qui pointait sur cet assistant (`prune.py:95-147`). **On complète, on ne supprime pas** : supprimer les orphelins obligerait à recoudre la chaîne parent-enfant, et le même assistant peut contenir d'autres blocs normaux, du texte et du thinking, faciles à emporter au passage (`prune.py:195-204`).

Trois lignes rouges structurelles, dont la violation fait immédiatement échouer l'API :

1. **Le bloc `tool_result` doit rester présent**, seul son `content` peut être remplacé. Un de moins et c'est « Missing Tool Result Block » (`trim.py:20-22` ; `prune.py:79-92`).
2. **Les entrées `isCompactSummary` / `isMeta` sont intouchables** — c'est la seule forme d'existence de l'historique qui a été compacté (`trim.py:179-181`).
3. **Retirer une entrée oblige à rattacher ses enfants à son parent.** Le transcript est une chaîne simple de `parentUuid` et le harness la remonte depuis la feuille ; là où la chaîne casse, tout l'historique antérieur est perdu (`prune.py:95-122`). C'est pourquoi `relink()` doit recevoir la liste complète **incluant** l'entrée à retirer, et fait elle-même le filtrage.

**Le texte original dans SQLite n'est pas modifié d'un caractère** — les trois couches n'affectent que « la copie redonnée au modèle » (`trim.py:18` ; `prune.py:8`).

## Résilience hors ligne {#韧性}

Un workflow long-horizon tourne des heures, le réseau tombera forcément une fois. Le comportement par défaut est mauvais : à l'instant de la coupure, le harness insère dans le transcript un message assistant synthétique (`model="<synthetic>"`, `isApiErrorMessage=true`) dont le corps est `API Error: Can't reach the API server …` ; il devient la feuille de la session, si bien qu'au resume il est redonné comme « la dernière phrase du modèle » et le modèle croit discuter d'une panne réseau ; il se glisse aussi dans `StepResult.text` et se propage le long du workflow jusqu'au prompt de l'étape suivante (`resilience.py:1-22`).

La couche de [résilience](glossary.md#韧性) fait trois choses, aucune facultative : la sonde, la reprise plutôt que le redémarrage, et l'erreur tenue hors du contexte.

### Paramètres de `Resilience` {#resilience}

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `enabled` | `bool` | `True` | Converti depuis `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Nombre maximum de tentatives pour une [étape](glossary.md#步骤), **première incluse** |
| `base_delay` | `float` | `4.0` | Point de départ du backoff exponentiel, en secondes |
| `max_delay` | `float` | `120.0` | Plafond du backoff, en secondes |
| `probe_timeout` | `float` | `5.0` | Timeout d'une sonde, en secondes |
| `probe_interval` | `float` | `15.0` | Intervalle entre sondes pendant une coupure, en secondes |
| `max_offline_wait` | `float` | `3600.0` | Attente maximale hors ligne. 1 heure par défaut — au-delà, ce n'est généralement plus une secousse, c'est un vrai incident |
| `retry_unknown` | `bool` | `True` | Réessayer aussi les erreurs non classifiables. La plupart des erreurs inconnues sont transitoires, et les erreurs fatales sont déjà interceptées séparément |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | Ce qui est dit au modèle lors de la reprise |

Formule de backoff (`resilience.py:119-121`) :

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Soit une gigue de `±25%`, pour éviter qu'une foule de processus ne se rue au même instant dès le rétablissement du réseau. Avec les valeurs par défaut : 1er backoff 4 secondes (3~5 en pratique), 2e 8 secondes (6~10), plafonné à 120 secondes (90~150) à partir du 5e.

### Stratégie de sonde {#探针}

- **On sonde le host:port de `ANTHROPIC_BASE_URL`**, pas `api.anthropic.com` (`resilience.py:67-72`). Avec une passerelle auto-hébergée, la joignabilité du second ne dit rien de celle du premier.
- **Uniquement DNS plus poignée de main TCP** : `getaddrinfo`, puis `connect_tcp`, puis fermeture immédiate. Pas de HTTP, pas de credentials, pas un centime (`resilience.py:75-85`). La sonde doit être gratuite, sinon « sonder toutes les 15 secondes pendant une coupure » devient elle-même la panne.
- Tout échec compte comme injoignable — on ne distingue pas un DNS mort d'un TCP refusé.
- `wait_online()` attend sur place : renvoie `True` dès que ça passe, `False` une fois `max_offline_wait` écoulé. À la première indisponibilité, une notification d'une ligne `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, et au rétablissement une autre ligne `<host>:<port> 恢复,继续` ; **rien entre les deux** (`resilience.py:126-140`).

La sonde de credentials avant le démarrage est une autre affaire : elle envoie réellement un `POST <BASE_URL>/v1/messages` avec `max_tokens=16`, timeout de 20 secondes par défaut (`env.py:126-181`). **Ne mettez pas `max_tokens` à 1** — mesuré, un modèle à chaîne de pensée forcée ne peut même pas y loger sa réflexion, et le serveur se débat jusqu'à 30 secondes avant de répondre ; à 16, il suffit de 3,6 secondes (`env.py:120-123`).

### Classification des erreurs {#错误分类}

`classify(text)` renvoie l'une de trois valeurs. **On teste d'abord le fatal** : un texte de 401 contient souvent aussi un mot comme « connection », et l'ordre inverse ferait attendre indéfiniment (`resilience.py:53-64`).

| Classe | Ce qui matche (regex en `resilience.py:37-50`) | Comportement |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Arrêt immédiat, sans retry. Le résultat serait le même quel que soit le nombre d'essais, et chacun coûte de l'argent |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Attendre le retour du réseau, puis reprendre par resume |
| `unknown` | rien ne matche | Réessayé aussi quand `retry_unknown=True` (le défaut) |

Distinguer le réessayable du non-réessayable est le cœur de cette couche : **une secousse réseau mérite l'attente, un credential erroné mérite l'arrêt immédiat** — attendre pendant une coupure est juste, attendre à cause d'une clé mal écrite ne fait que brûler du temps.

### Ce qui est tenu hors du contexte {#错误不进上下文}

1. **Les messages d'erreur synthétiques.** `PruningSessionStore` les retire entièrement au `load` et recoud le `parentUuid` (`prune.py:27-32`、`:191-195`). **Ils restent tels quels dans SQLite**, ils ne sont simplement pas redonnés.
2. **Dans le flux d'événements, c'est un `kind="error"` et non un `"text"`**, donc il n'entre pas dans `StepResult.text` et ne se propage pas le long du workflow jusqu'au prompt de l'étape suivante (`resilience.py:17-18`).
3. **`resume_prompt` ne contient délibérément aucun détail d'erreur.** Le modèle doit savoir « tu as été interrompu, continue » ; il n'a pas besoin de savoir si c'était `ENOTFOUND` ou `503`. **Cela relève du log, pas du contexte** (`resilience.py:112-113`). Pour le log, voyez le champ `errors` de `manifest.json`.

Reprendre plutôt que recommencer : au moment de l'échec, le `session_id` est déjà obtenu, on reprend au point d'interruption par resume, et le coût déjà payé n'est pas perdu.

## Voir aussi {#相关}

- [Ligne de commande](cli.md) — comment chaque option se projette sur la configuration de cette page.
- [API Python](api.md) — signatures complètes de `Runtime`, des trois stores et de `Resilience`.
- [Déploiement](deploy.md) — exécution en conteneur, distribution des capacités métier par plugin.
- [Glossaire](glossary.md) — le sens exact de chaque terme utilisé ici.
