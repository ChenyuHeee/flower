# Configuration

flower n'a pas de format de fichier de configuration, ni de sous-commande de configuration qui aboutisse vraiment — toute la configuration passe par des **variables d'environnement**, des **fichiers `.env`**, plus une poignée d'objets de politique que seule l'API Python permet de fournir. Cette page rassemble en un seul endroit ce qui est éparpillé dans cinq fichiers : chaque variable, l'ordre de recherche des identifiants, la syntaxe que `.env` accepte, ce que `setting_sources=[]` isole réellement, ce qu'une exécution laisse sur le disque, ce que chacune des trois couches du session store jette, et comment ça attend quand le réseau tombe. La terminologie suit le [glossaire](glossary.md).

| Vous voulez savoir | Allez voir |
|---|---|
| Quelles variables d'environnement flower reconnaît | [Table complète des variables d'environnement](#环境变量) |
| D'où vient réellement mon token | [Priorité de recherche des identifiants](#凭证查找优先级) |
| Pourquoi cette ligne de `.env` n'a pas pris effet | [Règles de parsing de `.env`](#env-解析) |
| Quoi emporter en changeant de machine | [Le prix de la portabilité](#可移植性) |
| Ce qu'il y a dans `.flower/` et `runs/` | [Disposition sur disque](#磁盘布局) |
| Quels messages ne sont pas réinjectés au modèle | [Les trois couches du session store](#会话存储) |
| Ce qu'il attend quand le réseau est coupé | [Résilience réseau](#韧性) |

## Table complète des variables d'environnement {#环境变量}

Quatre groupes : les identifiants et endpoints que flower lit directement, la sélection de modèle, la recherche de chemins, et ce que flower **écrit vers** le sous-processus agent. Le dernier groupe, vous n'avez pas à le définir — et si vous le définissez, il sera écrasé.

### Identifiants et endpoints {#凭证变量}

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Clé Anthropic officielle. Si elle est là, la requête part avec l'en-tête `x-api-key` | aucun | **l'une des deux requise**, avec `ANTHROPIC_AUTH_TOKEN` | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token émis par une passerelle. Sans `ANTHROPIC_API_KEY`, on utilise `authorization: Bearer` | aucun | idem | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | Racine de l'endpoint API. Une passerelle tierce y met sa propre adresse, **sans `/v1`** — la sonde assemble `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | non | `env.py:151`, `:162`, `:210` ; `resilience.py:70` |

Si aucune des deux n'est définie (ou si les deux sont des chaînes vides), `check_credentials()` renvoie ce message d'erreur de quatre lignes, et `Runtime.__init__` lève un `RuntimeError` (`env.py:184-194` ; `runtime.py:156-158`).

### Sélection de modèle {#模型变量}

flower n'en lit que trois pour ses propres décisions ; les autres sont chargées et transmises telles quelles au SDK.

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nom du modèle principal. Détermine aussi la valeur par défaut de la fenêtre de [handoff](glossary.md#换代) : nom contenant `1m` ou ne contenant pas `haiku` → 1 000 000 ; contenant `haiku` → 200 000 | aucun (décidé côté endpoint) | non | `env.py:153` ; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapping de modèle pour le palier opus. Si `ANTHROPIC_MODEL` est vide, le calcul de fenêtre retombe dessus | aucun | non | `agent.py:78` ; `cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapping de modèle pour le palier sonnet. flower ne la lit pas lui-même, il se contente de la charger et de l'emprunter | aucun | non | `env.py:34` ; `cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapping de modèle pour le palier haiku. **La sonde d'identifiants l'utilise en priorité** | la sonde retombe sur `ANTHROPIC_MODEL`, puis sur `claude-3-5-haiku-20241022` | non | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Modèle utilisé par les [subagents](glossary.md#subagent). flower ne l'interprète pas, c'est le SDK qui la consomme | aucun | non | `env.py:35` ; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Palier de réflexion. Idem : chargée, jamais interprétée | aucun | non | `env.py:35` |

Si `flower setup` a renseigné un nom de modèle, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` et `ANTHROPIC_DEFAULT_SONNET_MODEL` sont **écrites toutes les trois ensemble** (`cli.py:1204-1206`).

### Chemins et recherche {#路径变量}

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `FLOWER_ENV` | Désigne un chemin de fichier `.env`, placé **avant** tous les autres fichiers | aucun | non | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Détermine l'emplacement du fichier d'identifiants global `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | non | `env.py:41-42` |
| `HOME` | Source de `Path.home()` ; les deux chemins `~/.config` et `~/.claude` en dérivent | fourni par le système | non | `env.py:41`, `:67` |

### Ce que flower écrit pour le sous-processus agent {#写出的变量}

Ces trois-là sont générées par `CompactPolicy.env()` puis injectées dans `ClaudeAgentOptions.env` (`agent.py:48-58`, `:241-245`) ; elles contrôlent la [compaction](glossary.md#压缩) intégrée au harness. **Les définir dans votre shell n'a aucun sens** — ce qui compte, c'est l'exemplaire que flower transmet au sous-processus.

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` désactive la compaction automatique. **Forcée** quand le [handoff](glossary.md#换代) est actif — avec les deux mécanismes en parallèle, impossible de dire qui a fait retomber le contexte | le handoff est actif par défaut, donc en pratique toujours `1` | non (écrite par flower) | `agent.py:51` ; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` désactive aussi `/compact`. Écrite uniquement avec `CompactPolicy(mode="off")` | non écrite | non (écrite par flower) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Fenêtre de la compaction automatique (tokens). Écrite uniquement avec `CompactPolicy(window=N)` | non écrite | non (écrite par flower) | `agent.py:56-57` |

### Ce que lit le wrapper conteneur {#容器变量}

Ces deux-là ne sont pas lues par flower lui-même mais par le wrapper shell `docker/flowerbox`. Usage complet dans [Déploiement](deploy.md).

| Variable | Rôle | Défaut | Requis | Source |
|---|---|---|---|---|
| `FLOWER_HOME` | Où trouver le `.env` passé à `--env-file` | le répertoire parent de l'emplacement du script | non | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Quelle image utiliser | `flower-box` | non | `docker/flowerbox:13` |

**Les clés d'un `.env` ne se limitent pas à celles ci-dessus.** Le parseur charge **toutes** les lignes `k=v` dans `os.environ`, sans liste blanche (`env.py:30`, `:102-107`). Le `KNOWN` formé par ces 9 clés d'identifiants ne sert qu'à deux endroits : la liste blanche appliquée quand on emprunte la configuration `~/.claude` (`env.py:72`), et la portée des champs affichés par `describe()` au démarrage avec `-v` (`env.py:205`).

## Priorité de recherche des identifiants {#凭证查找优先级}

Quand `load_dotenv()` est appelé sans chemin, **tous les fichiers existants** sont lus dans cet ordre (`env.py:45-53`, `:78-112`) :

1. **Les variables d'environnement du processus** — toujours prioritaires. Aucun `.env` ne peut écraser une valeur déjà exportée. (`env.py:91`)
2. **Le fichier pointé par `$FLOWER_ENV`** — ce point n'existe que si la variable est définie. (`env.py:48-49`)
3. **`$PWD/.env`** — le répertoire de travail courant. Selon le projet où vous faites `cd`, c'est celui-là qui est lu. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — l'emplacement global, un par utilisateur ; c'est ce que `flower setup` écrit. (`env.py:51`, `:39-42`)
5. **Le `.env` à la racine du dépôt source** — trois niveaux au-dessus de `flower/core/env.py`. N'existe que si vous lancez depuis les sources ; un flower installé via pip / pipx / uv vit dans site-packages, donc ce point disparaît. (`env.py:52`)
6. **Le bloc `env` de `~/.claude/settings.json`, puis de `~/.claude/settings.local.json`** — le repli final, **9 clés d'identifiants seulement**. (`env.py:56-75`, `:109-111`)

**Quel fichier gagne** : le point 3 (`.env` projet) bat le point 4 (`.env` global), le point 4 bat le point 5 (`.env` racine du dépôt), les trois battent le point 6 (config de Claude Code), et aucun ne bat le point 1 (environnement du processus).

L'implémentation est un « **on n'écrase jamais une clé qui a déjà une valeur** » (`env.py:90-93`) : ce qui vient en premier occupe la clé, ce qui vient après ne fait que combler les trous. La priorité se calcule donc **par clé, pas par fichier** — si le `.env` du projet ne définit que `ANTHROPIC_BASE_URL`, le token peut parfaitement venir du fichier global. Pour une même clé, la première valeur rencontrée est définitive.

Le point 6 n'est activé qu'en **recherche automatique**. Si un chemin explicite est donné (`load_dotenv("/path/to/.env")`), seul ce fichier est lu, sans aucun repli (`env.py:86-87`, `:109`).

### Point 6 : emprunter le token de Claude Code {#借用}

`~/.claude/settings.json` puis `~/.claude/settings.local.json` sont lus, on prend le dict `data["env"]` et on y sélectionne ces 9 clés (`env.py:31-36`, `:65-74`) :

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Fichier absent, illisible, ou JSON invalide (`OSError` / `ValueError`) : on renvoie un dict vide et on continue — **un repli qui échoue ne doit pas emporter l'exécution avec lui** (`env.py:62-63`, `:66-69`).

La position tenue dans le code est la suivante : on n'emprunte que le « où trouver le token » ; tout le reste de settings.json (règles de permission, hooks, réglages de modèle) n'est jamais repris, donc cela ne contredit pas la promesse de portabilité de `setting_sources=[]` (`env.py:17-19`, `:59-61`). `install.sh:77` en fait même un argument de vente : qui a déjà configuré Claude Code localement ne verra jamais l'écran de configuration.

!!! warning "Le message d'erreur du produit dit le contraire du comportement réel"
    Quand aucun identifiant n'est trouvé, la dernière ligne de l'erreur affichée par flower est :

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, la phrase est en `:192` ; la même affirmation figure aussi dans `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **Le code fait foi : il les lit.** `env.py:56-75` plus `:109-111` lisent explicitement ces deux fichiers, et `install.sh:77` en fait un argument. Ce texte est aujourd'hui trompeur — sur une machine où Claude Code a été configuré, votre token vient très probablement de là.

## Règles de parsing de `.env` {#env-解析}

Les règles tiennent en une phrase (`env.py:95-107`, 13 lignes) : chaque ligne est `strip`ée, on ignore les lignes vides, celles qui commencent par `#`, et celles sans `=` ; le reste est coupé au **premier** `=` en clé et valeur, chacune `strip`ée, puis la valeur repasse par `.strip("'\"")` — les guillemets simples ou doubles en début et en fin sont retirés, **sans exiger qu'ils soient appariés**.

**Ces formes sont reconnues** :

| Syntaxe | Résultat |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — les espaces autour du `=` sont strippés |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — les guillemets extérieurs sont retirés |
| `KEY=a=b` | la valeur est `a=b` — la coupe se fait au premier `=`, les suivants restent dans la valeur |
| `# commentaire` | ligne entièrement ignorée |
| Ligne vide | ignorée |

**Celles-ci ne le sont pas.** Elles ne provoquent aucune erreur : vous obtenez silencieusement une valeur inattendue.

| Syntaxe | Résultat réel |
|---|---|
| `export KEY=VALUE` | la clé devient `export KEY` ; `KEY` elle-même reste sans valeur |
| `KEY=value # explication` | la valeur est `value # explication` — les commentaires de fin de ligne ne sont pas retirés |
| `KEY=$OTHER` | le littéral `$OTHER`, aucune interpolation de variable |
| Valeur multi-ligne (guillemets sur plusieurs lignes) | traitement ligne par ligne ; la deuxième ligne ne contient pas de `=` et est intégralement ignorée |

**Une valeur vide occupe quand même la clé.** Si `ANTHROPIC_AUTH_TOKEN=` apparaît dans un fichier de priorité haute, `take()` exécute `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` ; les fichiers suivants ne peuvent plus combler le trou puisque « la clé existe déjà » (`env.py:90-93`), tandis que `check_credentials()` teste la véracité et considère une chaîne vide comme non configurée (`env.py:186`). **Résultat : ni identifiant, ni repli.** Si vous ne voulez pas d'une clé, supprimez la ligne entière ; n'en laissez pas une vide.

## Le prix de la portabilité {#可移植性}

Tout le mécanisme tient dans cette ligne de `build_options()` (`agent.py:207`) :

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` est la valeur par défaut de `Runtime`, et **aucune option en ligne de commande ne permet de la désactiver** — il faut passer par l'API Python avec `Runtime(portable=False)`, ce qui donne `["project"]`, c'est-à-dire la lecture du `.claude/` du projet.

### Ce qui est isolé

| Ce qui est isolé | Conséquence |
|---|---|
| Les réglages de `~/.claude/` de la machine hôte | Les règles de permission, hooks et réglages de modèle qui s'y trouvent n'ont aucun effet. **Les identifiants sont la seule exception**, voir [emprunt](#借用) |
| Le `.claude/` du projet | Idem ; lu uniquement avec `portable=False` |

Les capacités métier ne passent pas par là — elles sont distribuées avec le dépôt et chargées via `plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`, `:210-212`), voir [Déploiement](deploy.md). Les instructions métier, elles, sont **appendées** après le system prompt natif de Claude Code, pas substituées (`agent.py:198-202`) : la spécialisation ne se paie pas d'une perte de capacité générale.

### Quoi emporter en changeant de machine

- **Identifiants : un fichier.** Copiez `~/.config/flower/.env`, ou refaites la configuration sur la nouvelle machine. Sans lui, rien ne démarre — rien n'est hérité automatiquement.
- **État de continuité : un répertoire entier.** `runs/` (base de sessions, manifeste, lignage) et `.flower/` (workbench).
- **Mais les chemins doivent correspondre.** `lineage.json` stocke le chemin absolu de l'espace de travail ; s'il ne correspond pas, c'est comme s'il n'existait pas : repli silencieux sur une nouvelle session, **sans erreur** (`lineage.py:65-66`). La raison : le `project_key` du SDK dérive du chemin de l'espace de travail (`/`, `_`, `.` remplacés par `-`, `runtime.py:40-41`) ; si le répertoire change de place, les anciens `session_id` deviennent introuvables.

## Disposition sur disque {#磁盘布局}

Une exécution de flower écrit dans deux arborescences : `<run_dir>/` pour la comptabilité et les sessions, `<workspace>/.flower/` pour le [workbench](glossary.md#工作台). Les deux atterrissent par défaut sous le répertoire courant, mais **leur référence n'est pas la même**.

!!! warning "`runs/` suit le répertoire courant, pas `-w`"
    `-r/--run-dir` vaut `"runs"` par défaut, et `Runtime` lui applique `Path(run_dir).resolve()` (`runtime.py:93-94`) — relativement au **répertoire de travail courant**, pas à l'espace de travail indiqué par `-w`. Si vous lancez `flower -w /path/to/proj` depuis `~`, la base de sessions atterrira dans `~/runs/`, pas dans le projet.

### `<run_dir>/` — par défaut `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript intégral (y compris celui propre à chaque subagent)
  manifest.json      manifeste d'exécution : session_id / coût / retries / cause d'échec par étape, cumulé entre processus
  lineage.json       lignage : nom d'étape → session_id ; c'est lui qui permet de reprendre dans le même répertoire
  aside/             Runtime séparé des questions à l'oracle, avec ses propres sessions.db + manifest.json
  workbench/         uniquement sur les chemins run / once et si -W est fourni
```

| Chemin | Contenu | Source |
|---|---|---|
| `runs/sessions.db` | Transcript intégral. C'est `PruningSessionStore` qui écrit ; les trois couches de politique sont décrites [plus bas](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Tableau JSON, le [manifeste d'exécution](glossary.md#运行清单) **cumulé entre processus**. Champs dans la table ci-dessous | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"nom d'étape": "session_id"}}`. Écrit d'abord en `.tmp` puis `replace` : remplacement atomique | `lineage.py:31`, `:87-97` |
| `runs/aside/` | Runtime séparé de l'[oracle](glossary.md#旁路顾问). **Ses coûts et son lignage ne se mélangent pas au manifeste principal** | `cli.py:632-634` |
| `runs/workbench/` | Emplacement par défaut du workbench avec `Runtime(workbench=True)`, hors de l'espace de travail. Le chemin `go` ne l'utilise pas | `runtime.py:148-151` |

Chaque ligne de `manifest.json` est un `asdict(StepResult)` plus deux correctifs (`runtime.py:44-71`, `:579-582`) :

| Champ | Type | Signification |
|---|---|---|
| `step` | `str` | Nom de l'étape. Quatre formes : `<nom>`, `<nom>#round<N>` (renvoyée pour reprise), `<nom>#retry<N>` (retry ordinaire), `<nom>·判定#<N>` ([juge](glossary.md#判定者)) |
| `session_id` | `str \| None` | La dernière [session](glossary.md#会话) encore vivante pour cette étape |
| `ok` | `bool` | Réussi ou non |
| `cost_usd` | `float` | Ce que l'étape a coûté |
| `num_turns` | `int` | Nombre de tours effectués |
| `text` | `str` | Réponse finale de l'étape |
| `error` | `str \| None` | Cause d'échec. Vaut `killed-by-signal` en cas de SIGHUP / SIGTERM (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Secondes epoch |
| `attempts` | `int` | Nombre réel de tentatives. `>1` signifie qu'il y a eu retry |
| `errors` | `list[str]` | Causes de chaque échec successif. **Seulement ici ; le modèle ne les voit pas** |
| `resumed` | `bool` | Si l'étape a repris au point d'interruption via resume au lieu de repartir de zéro |
| `retired` | `list[str]` | Les session_id brûlés lors du [handoff](glossary.md#换代) de cette étape, dans l'ordre |
| `context` | `int` | Taille de contexte réellement vue par le [thread principal](glossary.md#主线程) au dernier tour |
| `duration_s` | `float` | Ajouté à la main — c'est une `@property`, `asdict()` ne la récupère pas |
| `run` | `str` | Marqueur du processus courant, `YYYYmmdd-HHMMSS-<6 hex>`. **Doit être unique par instance** |

La stratégie d'écriture est **append, pas écrasement** : à chaque flush, le fichier est relu, les lignes dont le `run` correspond au sien sont remplacées par la version à jour, celles des autres sont laissées telles quelles (`runtime.py:564-586`). Plusieurs flower en parallèle dans le même répertoire ne s'écrasent donc pas mutuellement leur comptabilité.

Ce qu'il y a dans `runs/` est de la donnée pure, consultable hors ligne à tout moment avec sqlite3 ou [`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — le workbench {#工作台目录}

```text
.flower/
  INDEX.md      index généré automatiquement, injecté dans le system prompt de l'agent principal
  scripts/      scripts destinés à être rejoués. La première ligne `# desc: une phrase` apparaît dans l'index
  artifacts/    productions longues de plus de 2000 caractères : rapports, données, logs
  notes/        décisions consignées d'une étape à l'autre
  spill/        gros résultats d'outils mis sur disque ; nom de fichier = 16 premiers caractères du sha256 du contenu + `.txt`
```

Les trois sous-répertoires et l'index sont créés par `Workbench` (`workbench.py:73-92`). `INDEX.md` passe par le `system_prompt.append` au niveau de la session, et **les subagents n'en héritent pas** — la règle « les productions longues vont dans `artifacts/` » doit donc être relayée par le [coordinateur](glossary.md#协调者) dans le [brief de tâche](glossary.md#任务书) ; c'est le seul canal.

Le chemin `go` génère systématiquement ceci sous `notes/` :

| Fichier | Contenu | Source |
|---|---|---|
| `notes/需求.md` | Le [brief](glossary.md#需求确认书) gelé, quatre sections : objectif / critères d'acceptation / limites / inconnues et hypothèses | `brief.py:44-45` ; `clarify.py:105` |
| `notes/目标.md` | Les deux sections gelées : objectif / checklist de verdict | `workflow/goal.py:124` |
| `notes/问答记录.md` | Journal en append de toutes les questions-réponses, y compris les entrées de boîte de réception « dites spontanément par l'humain ». **N'entre pas dans le contexte, sert uniquement d'archive** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | Le [document de handoff](glossary.md#交接书). La génération précédente est rangée dans `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | `lineage.json` + `需求.md` + `目标.md` archivés par `--new` / `/new` (**déplacés, pas supprimés**) | `lineage.py:100-117` |

**Avec `--isolate`, le workbench sort du dépôt** : `<répertoire parent du workspace>/.flower-<nom du workspace>/` (`starter.py:47-55`). Le worktree est la copie privée de chaque agent, le workbench est la couche partagée entre agents ; ce qui est partagé ne peut pas vivre à l'intérieur d'un enclos privé. Dans ce cas, les chemins fournis au modèle sont absolus (`workbench.py:69-71`, `:142-145`).

**`spill/` a deux écrivains, avec des algorithmes de destination différents** :

| Qui écrit | Quand | Où | Seuil |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **avant** que le résultat d'outil n'atteigne le modèle | `<racine du workbench>/spill/` (`guard.py:130`) | `spill_threshold`, 4000 caractères par défaut |
| `TrimPolicy` (au `load`) | à la relecture de l'historique avant un resume | `<workspace>/.flower/spill/` — chaîne fixe relative à l'espace de travail (`trim.py:49`, `:303`) | `min_chars`, 2000 caractères par défaut |

Dans la disposition par défaut, c'est le même répertoire. Mais dès que le workbench est déplacé (`-W` qui l'envoie dans `runs/workbench/`, ou `--isolate` qui l'envoie hors du dépôt), les deux divergent — celui de `TrimPolicy` reste toujours dans l'espace de travail, parce que le `Read` de l'agent doit pouvoir l'atteindre.

Ce que `spill_guard` met à la place n'est pas une ligne, c'est une ligne de pointeur plus les **400 premiers caractères** (`guard.py:132-140`). Les appels qui lisent le fichier de spill lui-même sont laissés passer, sinon « lisez le texte complet avec Read » serait une phrase creuse — la lecture repasserait le seuil, serait spillée à son tour, boucle infinie (`guard.py:155-170`).

### Structure des tables de `sessions.db` {#sessions-db}

Trois tables ; les instructions de création sont dans `stores/sqlite.py:27-51` :

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
| `entries` | Une entrée du transcript ; `payload` est le JSON brut | `uid` est l'`uuid` de l'entrée, utilisé comme **clé d'idempotence** : un lot en échec est réessayé 3 fois, et la relecture ne doit pas produire de doublons. Les entrées sans `uuid` (titres, tags, marqueurs de mode) ne sont pas dédupliquées, d'où l'index unique avec `WHERE uid IS NOT NULL` |
| `meta` | Le curseur d'une session | `next_seq` est le prochain numéro de séquence, `mtime` un horodatage en millisecondes **strictement monotone** (`sqlite.py:72-79`) — `list_sessions` et les summaries partagent cette horloge ; sans monotonie, la comparaison ancien/récent du SDK part sur le mauvais chemin rapide |
| `summaries` | Le sidecar de résumé d'un thread principal | **Seuls les transcripts principaux comptent**, pas ceux des subagents (`sqlite.py:122-123`) |

Construction de `store_key` (`sqlite.py:54-58`) : `<project_key>/<session_id>`, avec un `subpath` supplémentaire pour les subagents. Le `project_key` est dérivé par le SDK du chemin de l'espace de travail — `/`, `_`, `.` remplacés par `-`.

Un coup d'œil sur un échantillon réel ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)) :

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Cet exemplaire contient 956 `entries`, 10 `meta`, 4 `summaries` — sur 10 sessions, 4 sont des transcripts principaux et 6 des subagents, et `summaries` égale exactement le nombre de transcripts principaux.

## Les trois couches du session store {#会话存储}

!!! note "Les trois couches sont une chaîne d'héritage, pas une combinaison optionnelle"
    `PruningSessionStore` hérite de `TrimmingSessionStore` qui hérite de `SqliteSessionStore`. `Runtime` construit **toujours** la couche la plus externe (`runtime.py:109-112`) ; ses paramètres de construction n'offrent aucun point d'entrée pour changer de backend. « Désactiver une couche » se fait en mettant l'`enabled` de son objet de politique à `False`, pas en changeant de classe.

`append` (l'écriture) est toujours intégral, pas un mot n'est modifié. Les trois couches n'affectent que `load` (l'exemplaire relu et réinjecté au modèle). L'ordre réel de `load` est :

```text
SqliteSessionStore.load     lit tout depuis la table entries, ordonné par seq
  → TrimmingSessionStore.expire()   résultats Bash périssables → remplacés par « expiré »
  → TrimmingSessionStore.trim()     anciens gros tool_result → spill + remplacement par un pointeur
    → PruningSessionStore.prune()   messages d'erreur synthétiques / anciens appels refusés → entrée retirée et chaîne reconnectée
```

| Couche | Classe | Ce qui est jeté | Critère |
|---|---|---|---|
| 1 | `SqliteSessionStore` | rien | — |
| 2 | `TrimmingSessionStore` | le corps des gros résultats d'outils, les résultats de commandes éphémères expirés | volume + péremption |
| 3 | `PruningSessionStore` | les résidus de coupure réseau, les anciens appels refusés | est-ce une erreur |

La couche 2 fait du [trim](glossary.md#裁剪), la couche 3 du [prune](glossary.md#剪除) — **le trim jette selon le volume et la valeur, le prune jette selon « est-ce une erreur »** ; ne mélangez pas. Signatures complètes dans l'[API Python](api.md).

### `SqliteSessionStore` — les fondations {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implémentation SQLite sans dépendance externe. Pour passer à Postgres / S3 / Redis, il suffit d'implémenter le même protocole ; le SDK fournit la suite de tests de conformité `claude_agent_sdk.testing.session_store_conformance` qui valide directement (`sqlite.py:1-8`).

Outre les méthodes du protocole, trois requêtes **synchrones** à l'usage de flower lui-même :

| Méthode | Retour | Usage |
|---|---|---|
| `projects()` | `list[str]` | Les `project_key` réellement présents en base. Le SDK le dérive du cwd ; confirmez avec ça avant d'interroger, ne devinez pas |
| `has_session(project_key, session_id)` | `bool` | Ne lit qu'une ligne de `meta`, pas le payload. À interroger avant de lancer une [continuité](glossary.md#接续) — un resume sur une session inexistante n'explose qu'une fois le sous-processus démarré, et à ce moment l'argent et le temps sont déjà dépensés |
| `last_context(project_key, session_id, scan=60)` | `int` | Quelle taille de contexte cette session a vue au dernier tour. Ne balaye que les 60 dernières entrées à rebours. `input_tokens` plus les deux `cache_*` sont comptés — ne regarder que le premier donne presque 0 en cas de cache hit, ce qui sous-estime gravement |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Deux règles orthogonales. `TrimPolicy` gère le **volume** :

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Les N derniers `tool_result` gardent leur texte intégral — le contexte en cours d'utilisation ne doit pas être trimé |
| `min_chars` | `int` | `2000` | En dessous, pas de trim. Remplacer par un pointeur coûterait plus de tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Répertoire d'archive, **relatif au workspace**. Il doit être dans l'espace de travail, sinon le `Read` de l'agent ne l'atteint pas |
| `enabled` | `bool` | `True` | Vaut `False` avec `Runtime(trim=False)` (le défaut) |

Le corps trimé est écrit dans `<16 premiers caractères du sha256>.txt`, et la place d'origine est remplacée par `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` gère la **péremption** : les résultats de `git status`, `ls`, `ps` sont courts, ils ne seront jamais candidats au trim par volume, mais leur exactitude se dégrade avec le temps — un `git status` d'il y a 20 tours n'est pas « inutile », il est **trompeur**.

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `enabled` | `bool` | `True` | Dérivé de `Runtime(ephemeral=…)`, **actif par défaut** |
| `keep_recent` | `int` | `6` | Les N derniers gardent leur texte intégral. Bien moins que les 20 de `TrimPolicy` — pour ce genre de contenu, la fenêtre du « récent » est intrinsèquement courte |
| `max_chars` | `int` | `2000` | Au-delà, c'est `TrimPolicy` qui prend le relais pour spill et archivage ; on ne passe pas par ici |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texte de remplacement |

Ne s'applique qu'aux résultats de l'outil **Bash**, et seulement si la commande matche `EPHEMERAL_CMD`. `Read` n'en fait pas partie : le contenu d'un fichier ne se déforme pas assez avec le temps pour induire en erreur, et il peut être précisément la base du raisonnement du modèle (`trim.py:153-160`). Le contenu expiré **n'est pas spillé** — archiver un `git status` périmé n'a aucun sens, il suffit de le relancer.

La fonction de décision est `is_ephemeral(cmd)`, et elle **est en même temps la liste de permissions rendue au coordinateur** : `delegate_guard(allow_glance=True)` utilise la même fonction (`trim.py:63-68`, `:128-150`). Les deux ensembles doivent rester égaux — autoriser sans trimer, et un `git status` périmé occupe le contexte pour toujours ; trimer sans autoriser, et le coordinateur délègue un subagent pour un simple `ls`, 4,3k de coût de démarrage pour quelques dizaines de caractères. Ajouter une commande à la liste blanche, c'est dire ces deux choses à la fois.

**Quand utiliser quoi** :

- Vous voulez seulement que les résidus de coupure réseau n'entrent pas dans le contexte → rien à faire, `Runtime` utilise déjà `PruningSessionStore` par défaut. `trim=False` ne fait que renoncer au trim des gros résultats ; le prune continue.
- Longue exécution, sorties d'outils volumineuses → `trim=True`. Le CLI du chemin `go` l'active déjà par défaut ; `--no-trim` l'inverse.
- Le [coordinateur](glossary.md#协调者) a `glance=True` → `ephemeral` doit rester actif, raison au paragraphe précédent.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Retire les messages synthétiques avec `isApiErrorMessage=true` ou `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Pour un `tool_result` `[Request interrupted …]`, **on remplace le corps, on ne retire pas le bloc** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texte de remplacement pour le point précédent |
| `keep_denials` | `int` | `1` | Conserve les N derniers appels d'outil refusés par le hook de permission ; les plus anciens sont retirés **appel et résultat ensemble** |

`keep_denials` est le seul paramètre de construction de `Runtime` transmis jusqu'à cette couche (`Runtime(keep_denials=N)`). Pourquoi 1 et non 0 : le refus le plus récent est un signal utile, il empêche le modèle de réessayer en boucle la même commande bloquée dans le même tour. **Ne l'augmentez pas** — un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information ; mesuré, il occupe 273 caractères (93 caractères de message de refus plus 180 caractères de commande morte), et il **induit en erreur** : après avoir lu quelques « n'utilise pas Bash directement », le coordinateur observé ne tente même plus un `git status` pourtant autorisé et déclare « Bash est restreint, j'envoie un agent voir » (`prune.py:135-148`).

Trois lignes rouges structurelles ; les franchir fait échouer l'API directement :

1. **Le bloc `tool_result` lui-même doit rester**, seul son `content` peut être remplacé. Un bloc manquant, et c'est « Missing Tool Result Block » (`trim.py:20-22` ; `prune.py:79-92`).
2. **Ne pas toucher aux entrées `isCompactSummary` / `isMeta`** — c'est la seule forme d'existence de l'historique qui a été compacté (`trim.py:179-181`).
3. **Retirer une entrée oblige à raccrocher ses enfants à son parent.** Le transcript est une chaîne simple par `parentUuid` ; le harness remonte depuis la feuille, et là où la chaîne casse, tout l'historique antérieur est perdu (`prune.py:95-122`). D'où `relink()` qui doit recevoir la liste complète **incluant** les entrées à retirer, le filtrage étant fait par elle-même.

**Pas un mot n'est modifié dans le texte d'origine en SQLite** — les trois couches n'affectent que « l'exemplaire réinjecté au modèle » (`trim.py:18` ; `prune.py:8`).

## Résilience réseau {#韧性}

Un workflow long-horizon tourne pendant des heures : le réseau tombera forcément au moins une fois. Le comportement par défaut est mauvais : à l'instant de la coupure, le harness insère dans le transcript un message assistant synthétique (`model="<synthetic>"`, `isApiErrorMessage=true`) dont le corps est `API Error: Can't reach the API server …` ; il devient la feuille de la session, et au resume suivant il est réinjecté comme « la dernière phrase du modèle », qui croit alors discuter d'une panne réseau ; il se retrouve aussi dans `StepResult.text` et se propage, via le workflow, jusqu'au prompt de l'étape suivante (`resilience.py:1-22`).

La couche de [résilience](glossary.md#韧性) fait trois choses, indissociables : sonder, reprendre au lieu de recommencer, tenir l'erreur hors du contexte.

### Paramètres de `Resilience` {#resilience}

| Paramètre | Type | Défaut | Sémantique |
|---|---|---|---|
| `enabled` | `bool` | `True` | Dérivé de `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Nombre maximum de tentatives par [étape](glossary.md#步骤), **première incluse** |
| `base_delay` | `float` | `4.0` | Point de départ du backoff exponentiel, en secondes |
| `max_delay` | `float` | `120.0` | Plafond du backoff, en secondes |
| `probe_timeout` | `float` | `5.0` | Timeout d'une sonde, en secondes |
| `probe_interval` | `float` | `15.0` | Intervalle entre deux sondes pendant une coupure, en secondes |
| `max_offline_wait` | `float` | `3600.0` | Attente maximale hors ligne. 1 heure par défaut — au-delà, ce n'est en général plus une instabilité, c'est un vrai incident |
| `retry_unknown` | `bool` | `True` | Réessayer aussi les erreurs non classifiées. La plupart des erreurs inconnues sont transitoires, et les erreurs fatales sont déjà interceptées à part |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | Ce qu'on dit au modèle à la reprise |

Formule de backoff (`resilience.py:119-121`) :

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Soit une gigue de `±25%`, pour éviter que tous les processus ne se ruent en même temps à l'instant où le réseau revient. Avec les valeurs par défaut : 1er backoff 4 secondes (en pratique 3~5), 2e 8 secondes (6~10), à partir du 5e plafonné à 120 secondes (90~150).

### Stratégie de sonde {#探针}

- **On sonde le host:port de `ANTHROPIC_BASE_URL`**, pas `api.anthropic.com` (`resilience.py:67-72`). Avec une passerelle auto-hébergée, que le second réponde ne dit rien du premier.
- **DNS plus poignée de main TCP, rien de plus** : `getaddrinfo`, puis `connect_tcp`, puis fermeture immédiate. Pas de HTTP, pas d'identifiants, pas un centime (`resilience.py:75-85`). Une sonde doit être gratuite, sinon « sonder toutes les 15 secondes pendant une coupure » devient lui-même la panne.
- Tout échec compte comme injoignable — on ne distingue pas un DNS mort d'un refus TCP.
- `wait_online()` bloque et attend : renvoie `True` si ça passe, `False` au bout de `max_offline_wait`. À la première indisponibilité, une ligne de notification `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, puis une ligne au rétablissement `<host>:<port> 恢复,继续` — **rien entre les deux, pas de flood** (`resilience.py:126-140`).

La sonde d'identifiants exécutée avant le démarrage est autre chose : elle envoie réellement un `POST <BASE_URL>/v1/messages`, `max_tokens=16`, timeout par défaut 20 secondes (`env.py:126-181`). **Ne mettez pas `max_tokens` à 1** — mesuré, un modèle à chaîne de pensée forcée n'a même pas la place de penser, le serveur se débat jusqu'à 30 secondes avant de répondre ; avec 16, il suffit de 3,6 secondes (`env.py:120-123`).

### Classification des erreurs {#错误分类}

`classify(text)` renvoie l'une de trois valeurs. **Le fatal est testé en premier** : un texte de type 401 contient souvent aussi un mot comme « connection », et dans l'ordre inverse on attendrait indéfiniment (`resilience.py:53-64`).

| Classe | Ce qui matche (regex dans `resilience.py:37-50`) | Comportement |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Arrêt immédiat, aucun retry. Réessayer donnerait le même résultat, et chaque essai coûte |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Attendre le retour du réseau, puis reprendre avec resume |
| `unknown` | rien ne matche | Réessayé également quand `retry_unknown=True` (le défaut) |

Distinguer le réessayable du non réessayable est le cœur de cette couche : **une instabilité réseau mérite qu'on attende, une erreur d'identifiant mérite un arrêt immédiat** — attendre pendant une coupure est juste, attendre parce que la clé est fausse, c'est brûler du temps.

### Ce qui est tenu hors du contexte {#错误不进上下文}

1. **Les messages d'erreur synthétiques.** `PruningSessionStore` les retire intégralement au `load` et reconnecte les `parentUuid` (`prune.py:27-32`, `:191-195`). **Ils restent tels quels en SQLite**, ils ne sont simplement pas réinjectés.
2. **Dans le flux d'événements, ils sont `kind="error"` et non `"text"`**, donc ils n'entrent pas dans `StepResult.text` et ne se propagent pas au prompt de l'étape suivante via le workflow (`resilience.py:17-18`).
3. **`resume_prompt` ne contient délibérément aucun détail d'erreur.** Le modèle doit savoir « tu as été interrompu, continue » ; il n'a pas besoin de savoir si c'était `ENOTFOUND` ou `503`. **Ça relève du log, pas du contexte** (`resilience.py:112-113`). Pour le log, regardez le champ `errors` de `manifest.json`.

Reprendre plutôt que recommencer : au moment de l'échec, le `session_id` est déjà connu, on repart du point d'interruption via resume, et ce qui a déjà été dépensé n'est pas perdu.

## Voir aussi {#相关}

- [Ligne de commande](cli.md) — comment chaque option se mappe sur la configuration de cette page.
- [API Python](api.md) — signatures complètes de `Runtime`, des trois stores et de `Resilience`.
- [Déploiement](deploy.md) — exécution en conteneur, distribution des capacités métier par plugin.
- [Glossaire](glossary.md) — le sens exact de chaque terme employé ici.
