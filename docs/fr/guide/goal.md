# Goal guard

Ce n'est pas au worker de dire « c'est fini ». Le [judge](../reference/glossary.md#判定者) est un rôle qui
fixe l'objectif, rend un verdict, et ne met jamais la main à la pâte : avant le départ il transforme le [brief](../reference/glossary.md#需求确认书) en une liste
jugeable, puis, à la fin de chaque tour de travail, il **juge une fois, indépendamment**, et produit un [verdict](../reference/glossary.md#判定) —
objectif atteint, on avance ; pas atteint, on renvoie au travail avec « ce qui manque » ;
jugé infaisable, on s'arrête et on demande à un humain.

## Quel problème cela résout {#解决什么问题}

Le [clarify](clarify.md) bloque **« ce n'est pas ce que tu voulais »**. Cette couche-ci bloque autre chose :
**« ce n'est en fait pas fini, mais il déclare que si »**. Les deux doivent rester séparés, car les modes de défaillance diffèrent :

| | À quoi ressemble l'échec | Quand il apparaît |
|---|---|---|
| Besoin erroné | Chaque livrable est construit sur un besoin faux | Des heures plus tard, tout est à jeter |
| Jugement d'achèvement erroné | Tests à moitié lancés, un endroit corrigé et trois oubliés, « ça devrait aller » | Au moment où tu t'en sers toi-même |

Pourquoi le second cas ne peut pas être confié au worker lui-même : **il a un biais d'optimisme systématique**.
Ce n'est pas de la malhonnêteté — il ne voit pas ses propres angles morts. Il sait ce qu'il a fait, il ne sait pas ce qu'il a manqué.

Le verdict est donc confié à un rôle **qui n'a pas participé au travail et qui tourne dans sa propre [session](../reference/glossary.md#会话)**.
Il ne voit que l'objectif et le terrain ; il ignore combien de fois le worker a essayé et à quel point c'était pénible, donc il ne lui cherche pas d'excuses.
C'est exactement la même raison que pour le clarifier en session séparée.

## Comment s'en servir (code minimal) {#怎么用最小代码}

### Zéro code : ligne de commande {#零代码命令行}

```bash
flower                      # le goal guard est actif par défaut
flower --no-goal            # désactivé : le travail terminé vaut achèvement
flower --rounds 5           # cinq tours de travail au maximum (défaut : 3)
flower --judge-can-run      # laisser le judge exécuter des commandes (verdict plus dur)
```

### Câblage manuel {#自己接线}

Deux fonctions, chacune sa moitié, à ne pas confondre : `goal_step()` **fixe l'objectif** (une étape à part entière),
`with_goal()` est la **boucle de verdict** (elle enveloppe une étape de travail).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # nombre de questions illimité par défaut
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)` :

| Paramètre | Défaut | Description |
|---|---|---|
| `goal_path` | — | Où l'objectif est écrit. À placer sous `notes/` du [workbench](../reference/glossary.md#工作台), pour la même raison que le brief |
| `brief_key` | `"确认需求"` | Depuis quelle clé de `ctx` lire le brief. **S'il est absent, on n'obtient que `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nom de l'étape, et clé correspondante dans `ctx` |
| `spec` / `instructions` | `None` / `""` | Fournir son propre `AgentSpec`, ou ajouter des instructions de domaine au judge |
| `always_set` | `False` | `True` = redéfinir à chaque fois |
| `on_fail` / `retries` | `"stop"` / `0` | Comme pour `Step` |
| `**spec_kw` | — | Transmis à `judge()` : `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` enveloppe une étape de travail dans une boucle avec verdict :

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` est le nombre total de tours, pas le nombre de tours supplémentaires** — il se traduit par `retries = max(0, rounds - 1)`,
donc `rounds=3` autorise au plus trois tours de travail, et `rounds=1` signifie « un tour, un verdict, échec si le verdict ne passe pas ».
Signature complète et sémantique des champs dans [Python API](../reference/api.md).

Trois clés supplémentaires apparaissent dans `ctx` :

```python
ctx[GOAL_KEY]     # "_goal" —— objet Goal ; ctx["设定目标"] en est le markdown
ctx[VERDICT_KEY]  # "_verdict" —— dernier Verdict en date, pour l'UI
ctx[ROUND_KEY]    # "_goal_rounds" —— nombre de tours effectués
```

Le judge est lancé via `ctx["_runtime"]` — `Workflow.run` place le runtime et la sortie d'événements dans `ctx`,
si bien que `gate` peut démarrer son propre agent tout en faisant remonter le déroulé du verdict jusqu'à ton UI
(sinon l'interface reste noire une dizaine de secondes, et on croit que c'est bloqué).

Quand ça ne tourne pas rond, commence par ces boutons :

| Symptôme | Quoi régler |
|---|---|
| Verdict trop laxiste, dit « atteint » alors que non | `--judge-can-run` pour qu'il exécute vraiment ; ou ajouter des critères de domaine via `instructions` |
| Verdict trop sévère, renvoie sans arrêt | Regarde si la liste de vérification de `目标.md` n'est pas plus exigeante que le besoin. **Corrige ce fichier** |
| Tours qui tournent à vide | Le judge aurait dû répondre « inatteignable » mais a répondu « non atteint ». Ajoute des instructions précisant ce qui compte comme infaisable |
| Trop cher | `--rounds 1`, ou `--no-goal` pour tout désactiver |
| Ne pas être interrompu | `--timeout 0` : en cas d'inatteignable, on ne demande à personne, on s'arrête (la raison reste sur le disque) |

## Ce qu'il fait réellement {#它实际做了什么}

### À quoi ressemble un objectif {#目标长什么样}

`goal_step` lit le brief, produit deux sections, et les fige dans `.flower/notes/目标.md` :

```markdown
# Objectif
Faire en sorte que conv.py convertisse du md en html.

# Liste de vérification
- Lancer `python conv.py a.md` produit a.html
- La sortie contient `<h1>`
- Les listes sont converties en `<ul><li>`
```

**La liste de vérification est toute la valeur de cette couche.** « Implémentation complète » n'est pas jugeable ; « quelle commande lancer, quoi observer » l'est.
La liste vient des « critères d'acceptation » du brief, mais doit être réécrite de façon que chaque ligne soit vérifiable sur-le-champ — les lignes floues, le judge les complète.
Les deux sections doivent être non vides (`statement` renseigné, `checks` non vide) pour que ce soit complet ; sinon cette étape ne laisse pas passer.

### La longueur de la liste dépend du nombre de modes de défaillance {#清单的长度由有多少种失败方式决定}

Pas de la rigueur du judge. Pour une tâche du type `git clone && make && ./app`, **trois à cinq lignes suffisent** :
build réussi, ça démarre, c'est utilisable.

**Constaté en vrai** ([HT002](../cases/ht002.md)) : une tâche « installer et lancer ce dépôt » a donné une liste de **15** lignes,
dont **5** seulement vérifiaient « est-ce que ça marche », **6** vérifiaient « le processus a-t-il respecté les règles »
(y compris consulter le mtime de `~/.zshrc`, vérifier si le répertoire `.flower/` avait été modifié — c'est le répertoire du framework lui-même),
et **4** étaient invérifiables par principe.

#### Une limite n'est pas un critère de verdict {#边界不是判定项}

C'est la cause principale de ce cas :

| | Ce que ça contraint | Comment on s'y conforme |
|---|---|---|
| **Limite** | **Comment tu travailles** (« n'installer que dans le répertoire du projet », « ne pas toucher au code métier ») | En **ne franchissant pas la limite**, pas en se justifiant après coup |
| **Critère de verdict** | **Ce qui est livré** (« est-ce que ça tourne », « le résultat est-il correct ») | Par vérification sur place |

Écrire « n'a pas lancé `brew install` » comme critère de verdict revient à ajouter une vérification pour chaque limite ajoutée —
or c'est précisément à l'étape de clarify qu'on encourage à écrire toutes les limites. S'il faut vraiment rendre des comptes, une phrase suffit, pas six lignes.

### Les lignes invérifiables sont signalées dès la définition de l'objectif {#验不了的条目设目标时就会喊}

Pour les lignes marquées `[此环境无法验证:原因]`, `goal_step` émet un avertissement **au moment même où l'objectif est figé** :

```text
  # 4/15 lignes de l'objectif sont invérifiables dans cet environnement —— elles échoueront forcément au verdict et il faudra te demander.
    Il est encore temps de modifier .flower/notes/目标.md :
      · Capture d'écran de l'interface et vérification visuelle [此环境无法验证:屏幕录制未授权]
      · ...
```

**Pourquoi anticiper** : le sort de ces lignes est scellé à l'instant où l'objectif est fixé, elles ne passeront jamais le verdict.
Dans HT002, on a d'abord dépensé **$35.90 de travail + $1.40 de verdict** avant de s'en apercevoir —
en déplaçant la découverte à l'étape de définition de l'objectif, la même information coûte **$0** au lieu de **$37**.

Cela avertit seulement, cela ne bloque pas : on peut choisir de lancer quand même (dans HT002, le choix final a été « accepter ce résultat »).
`Goal.unverifiable` contient cette liste, et le payload de l'événement fournit les données structurées pour l'UI.

### Trois conclusions, pas deux {#三个结论不是两个}

```text
Travail ──> Verdict ──atteint──────> on avance
                  ├─non atteint───> renvoyé avec « ce qui manque », on reprend la même session
                  └─inatteignable─> on s'arrête et on demande : accepter / modifier l'objectif / tu t'es trompé
```

La troisième conclusion est décisive. Avec seulement « atteint / non atteint », un objectif **réellement infaisable** ferait
tourner le coordinator à vide, tour après tour, jusqu'à épuisement du budget — voilà ce qui brûle vraiment de l'argent. Le judge a donc pour consigne explicite :
« un tour de plus n'y changera rien » = inatteignable (condition externe nécessaire absente, besoin contradictoire, critère de verdict tout simplement invérifiable) ;
« pas encore fini » = non atteint.

En cas d'inatteignable, le framework s'arrête et demande :

```text
  ? L'objectif est jugé **inatteignable** : dépendance X manquante, critère de verdict 2 invérifiable
    Que faire ?
     1) Accepter ce résultat et continuer tel quel
     2) Modifier l'objectif
     3) Tu t'es trompé, continue le travail
```

- **Accepter** → l'étape est considérée comme passée, la raison reste au dossier
- **Modifier l'objectif** → on te demande ensuite le nouvel objectif, **ajouté** à la suite de l'ancien (on voit ce qui a changé), puis un tour de plus
- **Tu t'es trompé** (ainsi que toute réponse libre que tu écris) → on renvoie au travail avec ton argument, puis un tour de plus

**Si personne ne répond, ça s'arrête**, ça ne continue pas à tourner à vide — c'est délibéré. Jugé infaisable et personne à qui demander,
continuer revient à brûler de l'argent tour après tour, ce qui est exactement ce qu'il faut éviter. À l'arrêt, un `StepAbort` est levé, la raison est écrite dans
`ctx["_aborted"]`, le fichier d'objectif et `runs/manifest.json` sont là, et l'humain reprend la décision à son retour.

!!! warning ""Pas fait" et "invérifiable ici" sont deux conclusions distinctes"
    Les trois valeurs de `Verdict` sont `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` ne doit jamais être jugé comme un succès** — il emprunte le chemin « on s'arrête et on demande », pas « un tour de plus ».
    Tout ce que le judge écrit du genre « impossible à vérifier / pas vérifiable / vérification impossible / indécidable / unverifiable » est **entièrement** classé en
    `UNREACHABLE`. Traiter « invérifiable ici » comme « atteint », c'est clore le travail sur un « ça a l'air de marcher » ;
    le traiter comme « non atteint », c'est le faire refaire tour après tour une chose invérifiable par nature.

### Verdict ambigu = non atteint {#判定含糊--未达成}

Ordre de reconnaissance de `Verdict.parse` : d'abord la section titrée « conclusion / verdict » ; en l'absence de section titrée,
un contenu entier valant `1` / `true` compte comme atteint, `0` / `false` comme non atteint (quand on demande au judge de « ne renvoyer que 0/1 »,
il est très probable qu'il renvoie effectivement un seul chiffre) ; ensuite on cherche des mots-clés dans le texte de conclusion (mots longs d'abord) ; enfin un `1` / `0` isolé.

**Si rien ne correspond, `state` reste vide, `ok` vaut `False`, et le framework traite le cas comme non atteint.** C'est délibéré :
« impossible de juger » et « c'est fini » sont deux choses différentes ; l'ambiguïté est systématiquement traitée comme non atteint, avec une raison par défaut ajoutée
(« le judge n'a pas rendu de conclusion explicite, traité comme non atteint »).

### On juge le livrable, pas le code source {#判的是产出物不是源码}

!!! warning "Un verdict qui ne lit que le code source ne peut pas juger un livrable"
    Dans [HT001](../cases/ht001.md), le critère d'acceptation disait littéralement « compiler un exécutable autonome, lancé directement dans
    un terminal macOS », et le verdict s'est contenté de lire `Makefile:25-38`, d'y trouver une branche Darwin, et de conclure **succès** —
    le livrable produit était un `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Ce n'est pas le goal guard qui s'est trompé** : ce mécanisme n'existait pas encore dans ce run, et la ligne a été jugée par un
    auditeur indépendant improvisé par le coordinator lui-même. Mais le goal guard aurait raté la même chose — le judge a `can_run=False` par défaut,
    il ne dispose que de `Read` / `Glob` / `Grep`, il **ne peut pas exécuter `file`**, il ne peut donc que lire le `Makefile`, et il
    conclurait pareillement « atteint » en voyant la branche Darwin. Le nœud de cet échec n'est pas « qui juge », mais « sur quelles preuves ».

    Cette leçon a été inscrite dans `JUDGE_RULES` : on juge le **livrable**, on n'accepte pas les inférences du type « il y a une branche macOS
    dans le code source, donc ça doit tourner ».

[HT002](../cases/ht002.md) est le run où `judge_can_run` était activé et où le judge a réellement lancé `file` / `lsof`,
il a donc évité ce piège — sa première phrase a été « je ne conclus pas d'après cette réponse. Je vais sur le terrain. » Puis :

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → démarré à 16:10, toujours vivant à 16:15
```

La phrase du prompt de verdict dit la même chose : va voir sur le terrain, coche la liste ligne par ligne, **un critère sans preuve visible
est un critère non passé**.

### « Renvoyer » veut dire continuer, pas recommencer {#打回是接着做不是重头做}

Le renvoi passe par `Step.on_reject` : au tour suivant on fait un **`resume` de la session qui vient d'être rejetée**, avec en prompt le retour du verdict
(`Verdict.feedback()` ne donne que « ce qui manque », pas la solution). Le travail déjà fait, les fichiers lus, les impasses explorées
sont donc toujours dans le contexte ; il ne reste plus qu'à combler l'écart.

La différence est inscrite dans le nom de l'étape, visible d'un coup d'œil dans `runs/manifest.json` :

```text
干活            premier tour
干活#round2     suite après renvoi        ← on_reject actif, resume du tour précédent
干活#retry1     retry ordinaire (repart de zéro)  ← ancien comportement en l'absence de on_reject
```

Le judge, lui, est **toujours dans une nouvelle session** : le gate de `with_goal` appelle directement `Runtime.run`, sans `resume` ;
le nom d'étape porte le numéro de tour (`干活·判定#1`), et un nom suffixé n'entre pas dans la [lineage](../reference/glossary.md#血缘) inter-processus.
Si le gate n'obtient pas `ctx["_runtime"]`, il lève `StepAbort`, **il ne fait pas semblant de passer**.

### Saut et redéfinition {#跳过与重设}

Si le fichier d'objectif existe déjà et est complet, cette étape est **sautée** (comme pour le brief) — quand un run [long-horizon](../reference/glossary.md#长程)
plante et redémarre, il ne faut pas recalculer les conclusions déjà prises. Pour redéfinir, supprime le fichier, ou passe `always_set=True`.

**Exception : au wake, tu as ajouté une phrase.** Cette phrase est ajoutée au brief, et cette étape **redérive donc l'objectif**
(`always_set=True`). Sans redérivation, le judge lirait encore l'ancienne liste figée, et la chose que tu viens d'ajouter n'entrerait
pas du tout dans le verdict — il conclurait « atteint » selon l'ancienne liste. Le coût mesuré de la redérivation est de **$0.41 / 3 minutes**.
Voir [continuity](continuity.md).

### Le judge peut-il exécuter des commandes {#判定者能不能跑命令}

Par défaut **non**. La liste sans approbation de `judge()` comprend les outils de questionnement plus `Read` / `Glob` / `Grep` ;
`Bash` n'est ajouté que si `can_run=True`. L'arbitrage :

- Donner `Bash` (`--judge-can-run` en CLI) → il peut réellement exécuter les commandes d'acceptation, le verdict est plus dur
- Mais il peut alors modifier l'espace de travail → il risque de « corriger vite fait » avant de conclure au succès, et ce verdict n'a plus aucun sens

Comme pour le clarifier, **pas de `Write` / `Edit` / `Agent`**. Ce qui applique cette règle est le hook `whitelist_guard`,
**pas `allowed_tools`** — ce dernier est une **liste de dispense d'approbation, pas une liste blanche exclusive**, le modèle peut toujours appeler des outils qui n'y figurent pas.
Deux preuves mesurées que cela tient encore : dans HT002, le judge de l'étape « 设定目标 » a lancé **11 fois `Bash`**,
alors que `Bash` ne figurait pas du tout dans sa liste de dispense ; et dans la **sonde à $0.1**,
un agent avec `allowed_tools=["Read"]` a tout de même émis des appels `Write` et `Bash`, arrêtés par la couche de permissions et la sécurité des chemins
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Aujourd'hui, ces deux appels seraient immédiatement refusés (`deny`) par le hook —
**ce qui l'arrête, c'est le hook, pas la liste**.

!!! warning "Le judge qui fixe l'objectif n'a pas `Bash` par défaut"
    `goal_step()` **n'a pas de paramètre `can_run`**, il faut passer par `**spec_kw` : `goal_step(ch, goal_path=…, can_run=True)`.
    Sans mention explicite, il n'a pas `Bash`, et la règle de `JUDGE_RULES` « commence par `uname -a` pour savoir où tu es » est inapplicable —
    il peut donc t'écrire une liste tout simplement invérifiable sur cette machine. `with_goal()` est un autre cas :
    il a son propre paramètre `can_run` (défaut : `False`).

### Pourquoi le nombre de tours est plafonné et pas le nombre de questions {#为什么轮数有上限而提问次数没有}

Poser une question ne coûte presque rien, un tour de travail coûte de l'argent réel. Donc :

- **Questions illimitées** (`max_asks=None`) — on demande jusqu'à ce que ce soit clair, le clarifier en juge lui-même
- **Tours plafonnés** (`rounds=3`) — mais le vrai filet de sécurité n'est pas ce nombre, c'est la troisième conclusion « inatteignable » :
  dès qu'elle apparaît, on s'arrête et on demande, sans attendre l'épuisement des tours

## Quand ne pas s'en servir {#什么时候不该用它}

**La tâche est si petite que juger coûte plus de mots que faire.** Cette couche complexifie les problèmes simples, et c'est mesuré :
pour HT002 — « cloner un dépôt, l'installer et le lancer sur macOS » — la liste de vérification a fait 15 lignes,
dont 6 vérifiaient le respect du processus et 4 étaient invérifiables par principe ; ce tour de verdict a coûté à lui seul **$1.4037 / 37 tours / 0.09h**,
et le run entier **$38.2409 / 0.97h**. Quand une tâche n'a que deux ou trois modes de défaillance, `--no-goal` est plus rentable.

**L'objectif ne se met pas sous forme de liste jugeable.** Un travail exploratoire (« regarde un peu de quoi il retourne dans ce dépôt ») n'a pas de critère de « fini » ;
forcer un objectif ne donnera qu'une liste jolie et injugeable. Pour ce genre de travail, `flower once`, ou `--no-goal`.

**Le critère de verdict décisif est invérifiable dans cet environnement.** Le judge a `can_run=False` par défaut, et pour seuls outils
`Read` / `Glob` / `Grep` — **il ne peut pas exécuter `file`**, il ne peut que lire le code source. Dans [HT001](../cases/ht001.md),
le critère « lancé directement dans un terminal macOS » se heurtait au fait que tout le run tournait dans un conteneur Linux :
**aucun judge ne peut vérifier un binaire macOS depuis ce conteneur**, qu'il soit auto-évaluateur ou indépendant.
`--judge-can-run` en sauve une partie (au moins `file` devient exécutable) ; la partie irrécupérable doit être marquée dès la définition de l'objectif
par `[此环境无法验证:…]`, pour emprunter le chemin « on s'arrête et on demande » plutôt que d'espérer que le judge devienne plus malin.

**Sans surveillance et sans interruption possible.** Jugé inatteignable et personne pour répondre, cette étape **s'arrête**, et tout le [workflow](../reference/glossary.md#流程) s'arrête là.
Si ce que tu veux c'est « aller au bout et on verra après », prends `--no-goal` ; si c'est « s'arrêter mais sans attendre », prends `--timeout 0` —
la question tombe immédiatement dans le vide, la raison est écrite sur le disque.

**Il ne se prononce pas sur la justesse du besoin.** La liste de vérification est dérivée du brief ; si le brief est faux, le verdict vérifiera avec précision une chose fausse.
Ça, c'est l'affaire de la couche [clarify](clarify.md).
