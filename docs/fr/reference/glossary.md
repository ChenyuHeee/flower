# Glossaire

Cette page est la référence terminologique de la documentation flower. Une même chose porte un seul nom sur tout le site ; la correspondance chinois-anglais est figée ici — les versions traduites suivent la même table.

Chaque entrée donne trois choses : **ce que le terme désigne**, **ce qu'il est dans le code**, **ce qu'il n'est pas**. La troisième est souvent la plus utile, parce que la plupart des malentendus viennent du fait qu'on a pris un terme pour un autre.

---

## Framework et exécution

### Long-horizon {#长程}

**long-horizon**

Un run qui s'étale sur plusieurs heures à plusieurs jours, sur plusieurs sessions, à travers des redémarrages de processus — pas un échange question-réponse. Tous les mécanismes de flower existent pour empêcher ce type de run de se désagréger en cours de route.

Référence mesurée : [HT001](../cases/ht001.md) a tourné 10.4 heures d'affilée.

### Run {#运行}

**run**

Le processus complet d'un `Runtime`, du début à la fin. Un run peut contenir plusieurs [steps](#步骤), plusieurs [sessions](#会话), et peut être interrompu puis repris via la [continuité](#接续). Les traces d'un run atterrissent dans `runs/manifest.json` et `runs/sessions.db`.

**Ce n'est pas** : un appel d'API, ni une session.

### Session {#会话}

**session**

Un contexte côté modèle. Elle a son propre `session_id`, peut être reprise (resume) ou forkée. Un [run](#运行) peut consommer plusieurs sessions — chaque [handoff](#换代) en ouvre une nouvelle.

### Step {#步骤}

**step** · `Step`

Une unité exécutable d'un [workflow](#流程). Elle reçoit un dictionnaire de contexte, lance un agent, réécrit le résultat dans le dictionnaire. `Step` est une classe, voir [API Python](api.md#step).

### Workflow {#流程}

**workflow** · `Workflow`

Un ensemble de [steps](#步骤) enchaînés dans l'ordre, plus la façon dont l'état circule entre eux et les conditions de sortie anticipée.

!!! note "Le framework ne fournit aucun workflow tout fait"
    flower ne fournit que des mécanismes. **Le workflow, c'est vous qui l'écrivez.** Voir [Concevoir un workflow](../guide/workflow.md).

---

## Rôles

Les rôles sont la répartition du travail que flower impose aux agents. Chaque rôle = un texte de règles injecté + un jeu d'outils + un jeu de hooks. Les cinq rôles sont des fonctions fabriques, voir [API Python](api.md#角色工厂).

### Coordinateur {#协调者}

**coordinator** · `coordinator()`

L'agent qui occupe le [thread principal](#主线程). Il découpe la tâche, distribue le travail, lit les rapports, prend les décisions, **mais ne met pas la main à la pâte** — il n'a ni `Bash`, ni `Write`, ni `Edit`. Ses outils sont uniquement `Agent`, `TodoWrite`, `Read`.

Son rôle est celui d'« une personne qui sait se servir de Claude Code », pas d'un worker.

**Ce n'est pas** : un agent plus intelligent. Il utilise par défaut le même niveau de modèle que le [worker](#执行者) ; ce qu'on économise, c'est du contexte, pas du modèle.

### Worker {#执行者}

**worker** · `worker()`

Le [subagent](#subagent) qui fait réellement le travail : écrire du code, lancer les tests, chercher de la documentation. Ses outils sont `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

Le format de réponse est contraint par le texte de règles à quatre sections — **conclusion / preuves / livrables / non vérifié**, pas plus de 30 lignes, interdiction de coller du contenu de fichier, de la sortie de commande, des logs ou des diffs bruts.

### Clarificateur {#确认者}

**clarifier** · `clarify()`

Le rôle qui tire le besoin au clair avant qu'on ne touche à quoi que ce soit. Il ne fait rien, il pose des questions, jusqu'à ce que ce soit clair (**sans limite de tours**), et produit à la fin un [brief](#需求确认书). Voir [Clarification préalable](../guide/clarify.md).

### Juge {#判定者}

**judge** · `judge()`

Le rôle qui tranche la question « est-ce que c'est fini ? ». Il fait l'une de deux choses : **fixer l'objectif** avant le départ (objectif + liste de critères), ou **statuer sur le tour** à la fin de chaque tour (produit un [verdict](#判定)). Voir [Garde d'objectif](../guide/goal.md).

**Point clé** : le juge juge les **livrables**, pas le code source.

[HT001](../cases/ht001.md) s'est fait avoir une fois : le critère d'acceptation disait « s'exécute directement dans un terminal macOS », et l'artefact livré donnait à l'exécution de `file` : `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux` — le verdict a pourtant été « validé ».

Deux points à préciser, sans quoi cet exemple sera mal lu :

1. **Ce n'est pas la garde d'objectif qui s'est trompée** — HT001 n'avait pas encore ce mécanisme ; c'est un auditeur envoyé spontanément par le coordinateur qui s'est trompé.
2. **Un juge en configuration par défaut serait très probablement passé à côté lui aussi.** `judge()` a `can_run=False` par défaut, avec pour seuls outils `Read/Glob/Grep` — **il ne peut pas lancer `file`** ; il aurait lu le `Makefile`, constaté qu'il y a bien une branche Darwin, et conclu à l'atteinte de l'objectif.

Ce qui marche vraiment, c'est [HT002](../cases/ht002.md) : le juge y a `judge_can_run` activé, lance lui-même `file` et `lsof` pour aller voir sur le terrain, et évite explicitement ce piège. **Donc « juger les livrables » ne tient debout que grâce à `can_run=True`.**

### Oracle {#旁路顾问}

**oracle** · `oracle()`

Une voie latérale en lecture seule. Pendant que le run tourne, vous pouvez lui demander « où en est-on ? » ; il jette un œil aux événements récents et au [workbench](#工作台) avant de répondre. **Ce qu'il dit n'entre pas dans le contexte du run** — interroger n'affecte pas le run, la réponse est jetée aussitôt.

### subagent {#subagent}

Notion du Claude Agent SDK : un agent enfant lancé par l'agent principal via l'outil `Agent`. Il possède **son propre transcript** ; ses appels d'outils et ses tâtonnements y sont consignés, et le thread principal ne reçoit que le rapport final.

C'est la première couche d'économie de contexte de flower, et de loin la plus rentable. Voir [Économie du contexte](../guide/context.md).

---

## Les quatre mécanismes

### Clarification préalable {#前置确认}

**clarify**

Tirer le besoin au clair avant d'agir, le geler dans un [brief](#需求确认书), puis exécuter. Ça bloque le « ce qui a été produit n'est pas ce qu'on voulait ». Voir [Clarification préalable](../guide/clarify.md).

### Brief {#需求确认书}

**brief** · `Brief`

Le document produit par le [clarificateur](#确认者) une fois ses questions posées, **exactement quatre sections**. Les steps suivants le lisent au lieu de redeviner le besoin.

**Ne pas confondre** avec le [task brief](#任务书). Le brief, c'est « ce que l'humain veut » ; le task brief, c'est « ce que ce subagent fait cette fois-ci ».

### Task brief {#任务书}

**task brief**

Le texte que le [coordinateur](#协调者) écrit au [worker](#执行者) quand il lui confie du travail. **N'y écrire que ce qui est propre à cette tâche** — ne pas répéter la discipline que l'autre connaît déjà.

Mesuré : 8/8 des task briefs répétaient une discipline déjà connue du destinataire ; dans le plus court, sur 521 caractères, seuls environ 120 caractères étaient propres à la tâche — soit environ 4.8k de contexte permanent gaspillé sur un tour.

### Garde d'objectif {#目标看守}

**goal guard**

Le [juge](#判定者) statue de façon indépendante, à la fin de chaque tour, sur l'atteinte de l'objectif ; s'il n'est pas atteint, il renvoie le travail. Ça bloque le « on dit que c'est fini alors que ça ne l'est pas ». Voir [Garde d'objectif](../guide/goal.md).

### Verdict {#判定}

**verdict** · `Verdict`

Le résultat d'un tour de jugement du [juge](#判定者), **exactement trois sections** : conclusion / motif / non validé.

Trois conclusions possibles : `ACHIEVED` (atteint), `NOT_YET` (pas encore), `UNREACHABLE` (invérifiable dans cet environnement). **Les deux dernières sont des conclusions distinctes** — « impossible à vérifier ici » ne vaut jamais validation.

### Continuité {#接续}

**continuity**

Relancer dans le même répertoire reprend automatiquement la progression précédente — y compris après un processus tué ou un redémarrage machine. Ça bloque le « ça a planté après des heures, on repart de zéro ». Voir [Continuité](../guide/continuity.md).

**Ne pas confondre** avec le [handoff](#换代) : la continuité reprend un run précédent **entre processus** ; le handoff bascule sur une nouvelle session **à l'intérieur d'un même run**.

### Handoff {#换代}

**handoff**

Quand le contexte approche de la saturation, on fait écrire à la session courante un [document de handoff](#交接书) lisible et modifiable par un humain, puis on ouvre une nouvelle session qui prend le relais. Ça bloque le « contexte plein, tout écrasé en un résumé ». Voir [Handoff](../guide/handoff.md).

**Ce n'est pas** le compact. Voir [compact](#压缩).

### Document de handoff {#交接书}

**handoff document** · `Handoff`

Le document écrit lors du handoff, en cinq sections : `doing` (ce qui est en cours), `decided` (ce qui a été décidé), `deadends` (les impasses), `next` (la suite), `scene` (l'état du terrain).

**Seuls `doing` et `next` sont obligatoires** — exiger que « les impasses » soient non vides pousserait le modèle à inventer.

### Compact {#压缩}

**compact**

La méthode native de Claude Code : le contexte est plein, on résume la conversation précédente en un condensé.

flower **ne l'utilise pas**, et lui substitue le [handoff](#换代). La différence : le résumé est généré par le modèle, illisible et non modifiable, et vous ne savez pas ce qui a été perdu ; le document de handoff est structuré, écrit sur disque, et vous pouvez l'ouvrir, corriger une ligne et relancer.

---

## Gestion du contexte

### Thread principal {#主线程}

**main thread**

Le contexte de session dans lequel vit le [coordinateur](#协调者). C'est le seul contexte qui traverse tout le run — donc celui qu'il faut économiser en priorité.

Dans le code, on détecte le thread principal ainsi : les données de hook **ne contiennent pas** d'`agent_id`. Les hooks des subagents portent un `agent_id`.

### Workbench {#工作台}

**workbench** · `Workbench`

Le répertoire de travail sur disque, avec trois sous-répertoires :

| Répertoire | Contenu |
|---|---|
| `scripts/` | Les scripts destinés à être relancés, avec en première ligne `# desc: une phrase` |
| `artifacts/` | Les productions longues, au-delà de 2000 caractères |
| `notes/` | Les décisions clés, un fichier par décision |

`INDEX.md` est l'index de ces trois répertoires, **injecté dans le system prompt** — l'agent sait donc à chaque tour ce qu'il a sous la main.

!!! warning "Deux points d'entrée, deux emplacements par défaut"
    L'emplacement du workbench dépend de la façon dont on le crée ; c'est un piège fréquent :

    | Mode de création | Racine du workbench |
    |---|---|
    | `Workbench(workspace)` — c'est aussi le chemin emprunté par `starter_flow()` / `wake_state()` | `<espace de travail>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (par défaut `runs/workbench`) |

    La ligne de commande passe par le premier, donc `flower` produit un `.flower/` ; mais en Python, un `Runtime(workbench=True)` direct donne `runs/workbench`. Pour imposer un emplacement, passez une instance `Workbench` déjà construite, ne comptez pas sur la valeur par défaut.

!!! warning "L'index n'est pas hérité par les subagents"
    L'index passe par le `system_prompt.append` de la session, **les subagents ne le reçoivent pas**. La règle « les productions longues vont dans `artifacts/` » doit donc être relayée par le [coordinateur](#协调者) dans le [task brief](#任务书) — c'est le seul canal.

### Spill {#落盘}

**spill**

Quand un résultat d'outil dépasse le seuil (4000 caractères par défaut), le hook `PostToolUse` l'écrit dans `<racine du workbench>/spill/` et ne laisse qu'une ligne de chemin dans le contexte.

Le chemin **suit le [workbench](#工作台)**, il n'est pas codé en dur — ce n'est exactement `.flower/spill/` que si le workbench est à son emplacement par défaut `<espace de travail>/.flower`. Avec l'[isolation](#隔离) activée, ou si le workbench est pointé hors du dépôt via `home=`, le spill se déplace avec lui.

**On coupe sur-le-champ**, plutôt que d'attendre la saturation du contexte pour [compacter](#压缩).

### Commande éphémère {#一次性命令}

**ephemeral command**

Une commande dont le résultat périme et n'a aucune valeur de conservation — `ls`, `git status`, `ps` et consorts. Leurs résultats n'entrent pas dans l'enregistrement persistant de la session. La question « peut-on laisser le thread principal y jeter un œil ? » et la question « le résultat sera-t-il rogné ? » sont tranchées par la même fonction : les deux ensembles sont donc toujours égaux.

### Trim {#裁剪}

**trim** · `TrimmingSessionStore`

Réécrit, **avant le resume**, le jeu de messages qui va être renvoyé au modèle (résultats de [commandes éphémères](#一次性命令), sorties d'outils démesurées).

Il ne surcharge que `load()` : **le texte original dans SQLite n'est jamais touché** ; seule la copie envoyée au contexte lors de ce resume est rognée. Le trim est donc réversible — changez de stratégie, refaites un resume, et vous récupérez l'enregistrement complet.

### Prune {#剪除}

**prune** · `PruningSessionStore`

Tient les **messages d'erreur** hors du contexte. La pile d'erreurs produite pendant les retries d'une coupure réseau n'a rien à faire dans le contexte après resume.

**Ne pas confondre** avec le [trim](#裁剪) : le trim jette selon le volume et la valeur, le prune jette selon « est-ce une erreur ou non ».

---

## Runtime

### Isolation {#隔离}

**isolation**

Les rôles marqués sont automatiquement placés dans un worktree git dédié, imposé par hook et non par prompt. De quoi ne pas se marcher dessus quand plusieurs agents modifient le même dépôt en parallèle.

!!! warning "Activer l'isolation implique de sortir le workbench du dépôt"
    Avec l'isolation par worktree, le [workbench](#工作台) doit être pointé hors du dépôt via `home=`, faute de quoi les agents isolés ne pourront pas écrire dans le checkout partagé.

### Résilience {#韧性}

**resilience** · `Resilience`

En cas de coupure réseau, on attend au lieu de sortir en échec : des sondes DNS + TCP surveillent, et le run reprend par resume une fois le réseau revenu. Les messages d'erreur produits pendant l'attente sont tenus hors du contexte par le [prune](#剪除).

### Lignage {#血缘}

**lineage** · `Lineage`

Consigne entre processus « de quelle session ce run est-il forké », dans `lineage.json`. La [continuité](#接续) s'en sert pour retrouver où on en était.

**Ne pas confondre** avec le [manifeste de run](#运行清单) — celui-ci est `runs/manifest.json` et tient la comptabilité de chaque run.

### Manifeste de run {#运行清单}

**run manifest** · `runs/manifest.json`

La comptabilité de chaque [run](#运行) : combien ça a coûté, combien de temps ça a tourné, quelle taille de contexte. Tous les chiffres des pages de cas peuvent être recalculés à partir de là.

### Wake {#唤醒}

**wake** · `wake_state()`

Une **sonde en lecture seule** avant le départ : regarder si cet espace de travail possède déjà un [brief](#需求确认书) et un objectif, pour décider s'il s'agit d'un démarrage à neuf ou d'une [continuité](#接续). **Pas un seul octet écrit.**

`wake_state()` est le seul endroit qui définit l'emplacement du workbench — un programme pilote qui veut savoir où se trouve le brief doit passer par lui. Un chemin reconstitué à la main et faux ne lèvera aucune erreur : il échouera silencieusement.

### Événement {#事件}

**event** · `Event`

Le flux de messages du SDK aplati en une structure stable. **La [couche d'interaction](#交互层) ne connaît que `Event` et n'importe aucun type du SDK** — c'est la frontière qui permet de changer d'UI sans toucher au cœur.

### Couche d'interaction {#交互层}

**interaction layer**

La couche d'UI entre l'humain et le run. Terminal par défaut ; remplaçable par du Web, une TUI, du HTTP, ou un mode entièrement automatique sans surveillance. Voir [Changer de couche d'interaction](../guide/interaction.md).

### Session store {#会话存储}

**session store** · `SessionStore`

Le backend de persistance des messages de session. Par défaut, `SqliteSessionStore` écrit dans `runs/sessions.db` ; on peut l'envelopper des deux couches [trim](#裁剪) et [prune](#剪除).

### Budget {#预算}

**budget** · `max_budget_usd`

Le plafond de dépense d'un run ; au-delà, on s'arrête. Sans lui, un run long-horizon coûte cher — [HT001](../cases/ht001.md) a coûté $171.62.

---

## Portabilité

### Portable {#可移植}

**portable**

Changez de machine, le comportement reste identique. Le moyen : `setting_sources=[]` — on ne lit ni le `~/.claude/` de la machine hôte, ni le `.claude/` du projet. Les capacités métier voyagent avec le dépôt via les [plugins](#plugin), les identifiants sont fournis par le `.env`.

Le prix à payer : **les identifiants doivent être fournis**, rien n'est hérité automatiquement de la configuration de l'hôte.

### Append {#叠加}

**append**

Les instructions métier sont ajoutées **après** le system prompt natif de Claude Code, au lieu de le remplacer :

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

La spécialisation ne se paie donc pas d'une perte de capacités générales.

### plugin {#plugin}

Un paquet de capacités métier qui voyage avec le dépôt. Chargé via `plugins=[local]` ; le répertoire peut contenir `skills/`, `agents/`, `hooks/`, `.mcp.json`. Voir [Déploiement](deploy.md#plugin).
