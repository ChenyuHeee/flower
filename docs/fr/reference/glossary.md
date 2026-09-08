# Glossaire

Cette page est la référence terminologique de la documentation de flower. Une même chose porte un seul nom sur tout le site ; la correspondance chinois-anglais est figée ici —
les versions traduites suivent cette même table.

Chaque entrée donne trois choses : **ce que le terme désigne**, **ce qu'il est dans le code**, **ce qu'il n'est pas**. La troisième est souvent la plus utile,
car la plupart des malentendus viennent du fait qu'on prend un terme pour un autre.

---

## Framework et run {#框架与运行}

### Long-horizon {#长程}

**long-horizon**

Un run qui s'étend sur des heures ou des jours, sur plusieurs sessions, sur plusieurs redémarrages de processus, et non un simple aller-retour question-réponse. Tous les mécanismes de flower existent
pour empêcher ce type de run de se désagréger en cours de route.

Référence mesurée : [HT001](../cases/ht001.md) a tourné 10.4 heures d'affilée.

### Run {#运行}

**run**

Le processus complet d'un `Runtime`, du début à la fin. Un run peut contenir plusieurs [steps](#步骤), plusieurs [sessions](#会话),
et peut être interrompu puis repris par [continuité](#接续). Les traces d'un run atterrissent dans `runs/manifest.json` et `runs/sessions.db`.

**Ce n'est pas** : un appel API, ni une session.

### Session {#会话}

**session**

Un contexte côté modèle. Elle a son propre `session_id`, peut être resumée, peut être forkée. Un [run](#运行) peut brûler
plusieurs sessions — chaque [handoff](#换代) en ouvre une nouvelle.

### Step {#步骤}

**step** · `Step`

Une unité exécutable dans un [workflow](#流程). Elle reçoit un dictionnaire de contexte, lance un agent, et réécrit le résultat dans le dictionnaire.
`Step` est une classe, voir [API Python](api.md#step).

### Workflow {#流程}

**workflow** · `Workflow`

Un ensemble de [steps](#步骤) enchaînés dans l'ordre, plus la façon dont l'état circule entre eux et les conditions de sortie anticipée.

!!! note "Le framework ne fournit aucun workflow prêt à l'emploi"
    flower ne fournit que des mécanismes. **Le workflow, c'est vous qui l'écrivez.** Voir [Concevoir un workflow](../guide/workflow.md).

---

## Rôles {#角色}

Les rôles sont la répartition du travail que flower impose aux agents. Chaque rôle = un texte de règles injecté + un ensemble d'outils + un ensemble de hooks.
Les cinq rôles sont des fonctions fabriques, voir [API Python](api.md#角色工厂).

### Coordinateur {#协调者}

**coordinator** · `coordinator()`

L'agent qui vit sur le [main thread](#主线程). Il découpe la tâche, distribue le travail, lit les rapports, décide — **mais ne met pas la main à la pâte** :
il n'a ni `Write` ni `Edit`. Ses outils de base sont `Agent`, `TodoWrite`, `Read`
(`roles.py:27`), mais ce n'est pas la liste finale : trois ajouts se font selon les paramètres. `glance=True` (par défaut) ajoute un
`Bash` restreint (juste de quoi faire `git status` / `ls` et autres commandes qui se règlent d'un coup d'œil, filtré par `delegate_guard`) ;
un canal de questions ajoute `inbox` et `ask` ; si les [workers](#执行者) sous ses ordres portent `WebFetch` / `WebSearch`,
ces deux-là sont fusionnés dans sa liste — `allowed_tools` est **au niveau session**, et sans cette fusion le subagent
resterait bloqué sur une validation de permission que personne ne traite (`roles.py:513-526`).

Son rôle est défini comme « quelqu'un qui sait se servir de Claude Code », pas comme un exécutant.

**Ce n'est pas** : un agent plus intelligent. Il tourne par défaut sur le même palier de modèle que le [worker](#执行者) ; ce qu'on économise, c'est du contexte, pas du modèle.

### Worker {#执行者}

**worker** · `worker()`

Le [subagent](#subagent) qui fait réellement le travail : écrire du code, lancer des tests, chercher de la documentation. Ses outils sont
`Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

Le format de réponse est contraint par le texte de règles à quatre sections — **conclusion / preuves / livrables / non vérifié**, pas plus de 30 lignes,
interdiction de coller du contenu de fichier, de la sortie de commande, des logs ou des diffs bruts.

### Clarificateur {#确认者}

**clarifier** · `clarify()`

Le rôle qui tire le besoin au clair avant qu'on ne touche à quoi que ce soit. Il ne fait rien, il pose des questions, jusqu'à ce que ce soit clair (**aucune limite de tours**),
et produit à la fin un [brief](#需求确认书). Voir [Clarification préalable](../guide/clarify.md).

### Juge {#判定者}

**judge** · `judge()`

Le rôle qui tranche la question « est-ce fini ou pas ». Il fait l'une de deux choses : **fixer l'objectif** avant le départ (production de l'objectif + de la checklist de jugement),
ou **juger le tour** à la fin de chaque tour (production d'un [verdict](#判定)). Voir [Gardien d'objectif](../guide/goal.md).

**Point clé** : le juge juge le **livrable**, pas le code source.

Dans [HT001](../cases/ht001.md), ça s'est mal passé une fois : le critère d'acceptation disait « s'exécute directement dans un terminal macOS », le livrable
donnait à l'exécution de `file` un `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`, et le verdict a pourtant été positif.

Deux choses à préciser, sinon cet exemple sera mal lu :

1. **Ce n'est pas le gardien d'objectif qui s'est trompé** — HT001 n'avait pas encore ce mécanisme ; c'est un auditeur dépêché spontanément par le coordinateur qui s'est trompé.
2. **Le juge en configuration par défaut serait très probablement passé à côté lui aussi.** `judge()` a `can_run=False` par défaut, ses outils se limitent à
   `Read/Glob/Grep` — **il ne peut pas exécuter `file`** ; il aurait lu le `Makefile`, constaté qu'il y a bien une branche Darwin,
   puis conclu à l'atteinte de l'objectif.

Ce qui marche vraiment, c'est [HT002](../cases/ht002.md) : le juge y a `judge_can_run` activé, exécute lui-même `file` et `lsof`
pour aller voir sur place, et évite explicitement ce piège. **Donc « juger le livrable » ne tient debout qu'avec `can_run=True`.**

### Oracle {#旁路顾问}

**oracle** · `oracle()`

Une voie latérale en lecture seule. Pendant que le run tourne, vous pouvez lui demander « où en est-on », il jette un œil aux événements récents et au [workbench](#工作台)
avant de répondre. **Ce qu'il dit n'entre pas dans le contexte de ce run** — le questionner n'a aucun effet sur le run, la réponse est jetée après coup.

### subagent {#subagent}

Un concept du Claude Agent SDK : l'agent principal dépêche un sous-agent via l'outil `Agent`. Il a **sa propre
transcript** ; ses appels d'outils et ses tâtonnements y restent consignés, le main thread ne reçoit que le rapport final.

C'est la première couche d'économie de contexte de flower, et de loin la plus rentable. Voir [Économie du contexte](../guide/context.md).

---

## Les quatre mécanismes {#四个机制}

### Clarification préalable {#前置确认}

**clarify**

Tirer le besoin au clair avant de commencer, le figer dans un [brief](#需求确认书), puis exécuter.
Cela bloque le « ce qui a été produit n'est pas ce qu'on voulait ». Voir [Clarification préalable](../guide/clarify.md).

### Brief {#需求确认书}

**brief** · `Brief`

Le document produit par le [clarificateur](#确认者) une fois ses questions posées, **exactement quatre sections**. Les steps suivants le lisent au lieu de redeviner le besoin.

**Ne pas** confondre avec le [task brief](#任务书). Le brief dit « ce que l'humain veut » ; le task brief dit « ce que ce subagent fait cette fois-ci ».

### Task brief {#任务书}

**task brief**

Le texte que le [coordinateur](#协调者) écrit au [worker](#执行者) quand il distribue le travail. **N'y mettre que ce qui est propre à cette tâche** —
ne pas répéter la discipline que l'autre connaît déjà.

Mesuré : 8/8 des task briefs répétaient des règles déjà connues du destinataire ; dans le plus court, sur 521 caractères, environ 120 seulement étaient spécifiques à la tâche,
soit environ 4.8k de contexte permanent gaspillé sur un tour.

### Gardien d'objectif {#目标看守}

**goal guard**

Le [juge](#判定者) évalue de manière indépendante, à la fin de chaque tour, si l'objectif est atteint ; sinon il renvoie le travail.
Cela bloque le « il dit que c'est fini alors que ça ne l'est pas ». Voir [Gardien d'objectif](../guide/goal.md).

### Verdict {#判定}

**verdict** · `Verdict`

Le résultat d'un tour de jugement du [juge](#判定者), **exactement trois sections** : conclusion / motif / non validé.

La conclusion prend trois valeurs : `ACHIEVED` (atteint), `NOT_YET` (pas encore), `UNREACHABLE` (invérifiable dans cet environnement).
**Les deux dernières sont des conclusions distinctes** — « impossible à vérifier ici » ne vaut jamais validation.

### Continuité {#接续}

**continuity**

Relancer dans le même répertoire reprend automatiquement la progression précédente — y compris après un processus tué ou un redémarrage machine.
Cela bloque le « ça a planté au bout de plusieurs heures, on repart de zéro ». Voir [Continuité](../guide/continuity.md).

**Ne pas** confondre avec le [handoff](#换代) : la continuité reprend un run précédent **entre processus** ; le handoff change de session **à l'intérieur d'un même run**.

### Handoff {#换代}

**handoff**

Quand le contexte approche de la saturation, on fait écrire à la session courante un [document de handoff](#交接书) lisible et modifiable par un humain, puis une nouvelle session prend le relais.
Cela bloque le « le contexte est plein, on est compressé en un résumé ». Voir [Handoff](../guide/handoff.md).

**Ce n'est pas** un compact. Voir [compact](#压缩).

### Document de handoff {#交接书}

**handoff document** · `Handoff`

Le document écrit lors d'un handoff, cinq sections : `doing` (ce qui est en cours), `decided` (ce qui a été décidé), `deadends` (les pistes sans issue),
`next` (l'étape suivante), `scene` (l'état des lieux).

**Seuls `doing` et `next` sont obligatoires** — exiger en dur que « les pistes sans issue » soient non vides pousse le modèle à inventer.

### Compact {#压缩}

**compact**

La méthode native de Claude Code : le contexte est plein, on résume la conversation précédente en un paragraphe.

flower **ne l'utilise pas**, il le remplace par le [handoff](#换代). La différence : le résumé est généré par le modèle, illisible et immodifiable, et vous ne savez pas ce qui a été perdu ;
le document de handoff est structuré, écrit sur disque, et vous pouvez l'ouvrir, en changer une ligne et relancer.

---

## Gestion du contexte {#上下文管理}

### Main thread {#主线程}

**main thread**

Le contexte de session dans lequel vit le [coordinateur](#协调者). C'est le seul contexte qui traverse tout le run, donc celui qu'il faut le plus économiser.

Dans le code, le main thread se reconnaît ainsi : les données du hook **ne contiennent pas** d'`agent_id`. Les hooks de subagent portent un `agent_id`.

### Workbench {#工作台}

**workbench** · `Workbench`

Le répertoire de travail sur disque, trois sous-répertoires :

| Répertoire | Contenu |
|---|---|
| `scripts/` | Les scripts qu'on relancera une deuxième fois, avec `# desc: une phrase` en première ligne |
| `artifacts/` | Les productions longues dépassant 2000 caractères |
| `notes/` | Les décisions clés, un fichier par décision |

`INDEX.md` est l'index de ces trois répertoires, **injecté dans le system prompt**, pour que l'agent sache à chaque tour ce dont il dispose.

!!! warning "Deux points d'entrée, deux emplacements par défaut"
    L'emplacement du workbench dépend de la façon dont on le crée, et c'est un piège facile :

    | Mode de création | Racine du workbench |
    |---|---|
    | `Workbench(workspace)` — c'est aussi le chemin emprunté par `starter_flow()` / `wake_state()` | `<espace de travail>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (par défaut `runs/workbench`) |

    La ligne de commande emprunte le premier, donc `flower` produit un `.flower/` ; mais en Python, un
    `Runtime(workbench=True)` direct donne `runs/workbench`. Pour imposer un emplacement, passez une instance
    `Workbench` déjà construite, ne vous fiez pas à la valeur par défaut.

!!! warning "Les subagents n'héritent pas de l'index"
    L'index passe par `system_prompt.append` au niveau session, **les subagents ne le reçoivent pas**. La règle « les productions longues vont dans `artifacts/` »
    doit donc être relayée par le [coordinateur](#协调者) dans le [task brief](#任务书) — c'est le seul canal.

### Spill {#落盘}

**spill**

Quand un résultat d'outil dépasse le seuil (4000 caractères par défaut), le hook `PostToolUse` l'écrit dans
`<racine du workbench>/spill/`, et le contexte ne garde qu'une ligne de chemin.

Le chemin **suit le [workbench](#工作台)**, il n'est pas codé en dur — ce n'est exactement `.flower/spill/` que
si le workbench est à son emplacement par défaut `<espace de travail>/.flower`. Avec l'[isolation](#隔离) activée, ou un workbench pointé hors du dépôt par `home=`,
le spill se déplace avec lui.

**La coupe est faite sur-le-champ**, pas en revenant [compacter](#压缩) une fois le contexte plein.

### Commande éphémère {#一次性命令}

**ephemeral command**

Une commande dont le résultat périme et n'a aucune valeur de conservation — `ls`, `git status`, `ps` et compagnie. Leurs résultats n'entrent pas dans
l'enregistrement persistant de la session. La décision « peut-on laisser le main thread y jeter un œil » et la décision « le résultat sera-t-il coupé » passent par la même fonction,
donc les deux ensembles sont toujours égaux.

### Trim {#裁剪}

**trim** · `TrimmingSessionStore`

Réécrit, **avant le resume**, le lot de messages qui va être renvoyé au modèle (résultats de [commandes éphémères](#一次性命令), sorties d'outils surdimensionnées).

Il ne surcharge que `load()` : **le texte d'origine dans SQLite ne bouge jamais** ; seule la copie envoyée au contexte lors de ce resume est coupée.
Le trim est donc réversible — changez de stratégie, relancez un resume, et vous récupérez l'enregistrement complet.

### Prune {#剪除}

**prune** · `PruningSessionStore`

Tient les **messages d'erreur** hors du contexte. La pile d'erreurs produite pendant les retries d'une coupure réseau n'a pas à occuper le contexte après le resume.

**Ne pas** confondre avec le [trim](#裁剪) : le trim jette selon le volume et la valeur, le prune jette selon « est-ce une erreur ».

---

## Runtime {#运行时}

### Isolation {#隔离}

**isolation**

Les rôles marqués se voient automatiquement attribuer un worktree git séparé, imposé par un hook et non par le prompt.
Plus de collisions quand plusieurs agents modifient le même dépôt en parallèle.

!!! warning "Activer l'isolation impose de sortir le workbench du dépôt"
    Avec l'isolation par worktree, le [workbench](#工作台) doit être pointé hors du dépôt via `home=`, sinon l'agent isolé
    ne peut pas écrire dans le checkout partagé.

### Résilience {#韧性}

**resilience** · `Resilience`

En cas de coupure réseau, attendre au lieu d'échouer et sortir : des sondes DNS + TCP surveillent, et le run reprend par resume une fois le réseau revenu.
Les messages d'erreur produits pendant l'attente sont tenus hors du contexte par le [prune](#剪除).

### Lignage {#血缘}

**lineage** · `Lineage`

Enregistre entre processus « de quelle session ce run a été forké », dans `lineage.json`. La [continuité](#接续) s'en sert pour retrouver où on s'était arrêté.

**Ne pas** confondre avec le [manifeste de run](#运行清单) — celui-ci est `runs/manifest.json` et tient la comptabilité de chaque run.

### Manifeste de run {#运行清单}

**run manifest** · `runs/manifest.json`

La comptabilité de chaque [run](#运行) : combien ça a coûté, combien de temps ça a tourné, quelle taille de contexte. Tous les chiffres des pages de cas s'y recalculent.

### Wake {#唤醒}

**wake** · `wake_state()`

Une **sonde en lecture seule** avant le départ : vérifier si cet espace de travail contient déjà un [brief](#需求确认书) et un objectif,
et donc décider si l'on démarre de zéro ou si l'on est en [continuité](#接续). **Pas un octet n'est écrit.**

`wake_state()` est le seul endroit qui définit l'emplacement du workbench — un programme pilote qui veut savoir où est le brief doit passer par lui.
Reconstruire le chemin à la main et se tromper ne lève aucune erreur, ça échoue silencieusement.

### Événement {#事件}

**event** · `Event`

Le flux de messages du SDK aplati en une structure stable. **La [couche d'interaction](#交互层) ne connaît que `Event`, elle n'importe aucun type du SDK** —
c'est la frontière qui permet de changer d'UI sans toucher au cœur.

### Couche d'interaction {#交互层}

**interaction layer**

La couche d'UI entre l'humain et le run. Par défaut le terminal ; remplaçable par du Web, du TUI, du HTTP, ou un mode entièrement automatique sans surveillance.
Voir [Changer de couche d'interaction](../guide/interaction.md).

### Session store {#会话存储}

**session store** · `SessionStore`

Le backend de persistance des messages de session. Par défaut `SqliteSessionStore` écrit dans `runs/sessions.db`,
et peut être enveloppé des deux couches [trim](#裁剪) et [prune](#剪除).

### Budget {#预算}

**budget** · `max_budget_usd`

Le plafond de dépense d'un run ; au-delà, on s'arrête. Sans lui, un run long-horizon coûte cher — [HT001](../cases/ht001.md) a coûté $171.62.

---

## Portabilité {#可移植性}

### Portable {#可移植}

**portable**

Changer de machine, même comportement. La méthode : `setting_sources=[]` — on ne lit ni le `~/.claude/` de la machine hôte,
ni le `.claude/` du projet. Les capacités métier voyagent avec le dépôt via les [plugins](#plugin), les identifiants viennent du `.env`.

Le prix à payer : **les identifiants doivent être fournis**, il n'y a pas d'héritage automatique de la configuration hôte.

### Append {#叠加}

**append**

Les instructions métier sont ajoutées **après** le system prompt natif de Claude Code, au lieu de le remplacer :

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

La spécialisation ne se paie donc pas d'une perte de capacités générales.

### plugin {#plugin}

Un paquet de capacités métier qui voyage avec le dépôt. Chargé via `plugins=[local]`, le répertoire peut contenir `skills/`, `agents/`,
`hooks/`, `.mcp.json`. Voir [Déploiement](deploy.md#plugin).
