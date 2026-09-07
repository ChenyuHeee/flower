# Concepts fondamentaux

flower a son propre vocabulaire : exécution, étape, session, coordinateur, exécutant, clarification préalable, gardien d'objectif, continuité, passation.
Cette page les traite tous d'un coup ; une fois lue, vous n'aurez plus à deviner en lisant les autres pages. Cinq minutes de lecture.

On ne parle ici que de concepts, **pas de signatures d'API** — pour les signatures, allez à [Python API](../reference/api.md) ;
pour une définition en une phrase et la correspondance chinois-anglais, au [Glossaire](../reference/glossary.md) ; pour les options de ligne de commande, à la
[Référence CLI](../reference/cli.md).

## Quelle forme a une exécution {#形状}

Trois niveaux, du plus grand au plus petit :

| Terme | Ce que c'est | Où c'est consigné |
|---|---|---|
| [exécution](../reference/glossary.md#运行) run | Le déroulement complet d'un `Runtime`, du début à la fin. En configuration par défaut, une exécution correspond à une invocation de `flower` | `runs/manifest.json` |
| [étape](../reference/glossary.md#步骤) step | Une unité exécutable à l'intérieur d'une exécution : elle reçoit un dictionnaire de contexte, fait tourner un agent, réécrit le résultat dans le dictionnaire. Chaque ligne de tirets `==` à l'écran est une frontière d'étape | Idem, une ligne par étape |
| [session](../reference/glossary.md#会话) session | Un contexte côté modèle. Elle a son propre `session_id`, peut être reprise (resume) ou forkée | `runs/sessions.db` |

L'imbrication n'est pas une correspondance un pour un :

```text
exécution ── l'invocation de flower que vous venez de lancer
 ├── étape Clarifier le besoin ── session A
 ├── étape Fixer l'objectif ──── session B
 └── étape Travailler ────────── session C ──[contexte presque plein]──> session C'
      └── Travailler·verdict#1 ─ session D
```

- **Une étape peut brûler plusieurs sessions.** Quand le contexte est presque plein, elle ne compacte pas : elle écrit un document de passation et ouvre une nouvelle session qui prend le relais —
  c'est la [passation](../reference/glossary.md#换代), et elle a lieu **à l'intérieur d'une même exécution**.
- **Une nouvelle exécution peut se raccrocher à d'anciennes sessions.** Relancez `flower` dans le même répertoire : chaque étape retrouve la session de la fois précédente —
  c'est la [continuité](../reference/glossary.md#接续), qui opère **entre processus**. Elle s'appuie sur `runs/lineage.json`
  pour mémoriser « quel nom d'étape correspond à quel `session_id` ».
- **Le tour de verdict est toujours une session neuve.** Il ne se raccroche à rien et n'entre pas dans le lignage — celui qui juge « est-ce fini ou non » ne peut pas être l'exécutant qui vient de travailler.

Un ensemble d'étapes enchaînées dans l'ordre s'appelle un [workflow](../reference/glossary.md#流程).
`flower` lancé nu utilise le workflow à trois étapes fourni avec le framework : clarifier le besoin → fixer l'objectif → travailler.

## La répartition : le coordinateur ne met pas la main à la pâte {#分工}

**C'est le principe sur lequel tout le framework est bâti.**

Le [coordinateur](../reference/glossary.md#协调者) est l'agent qui vit sur le [thread principal](../reference/glossary.md#主线程).
Il découpe les tâches, délègue, lit les rapports, décide — mais il **n'a accès ni à `Write` ni à `Edit`**,
et son `Bash` suffit tout juste à lancer un `ls`, un `git status`, ce genre de [commande éphémère](../reference/glossary.md#一次性命令) pour jeter un œil
(contrôlé par un hook, pas par une contrainte de prompt, et ces résultats n'entrent pas dans l'historique de session persisté).
Sa table d'outils, c'est `Agent`, `TodoWrite`, `Read`, plus ce `Bash` restreint.

Celui qui travaille vraiment, c'est l'[exécutant](../reference/glossary.md#执行者) — un
[subagent](../reference/glossary.md#subagent) envoyé par l'outil `Agent`.

**Pourquoi cette séparation.** Un subagent a **sa propre transcript** : combien de fichiers il a lus, combien de fois il a lancé les tests,
combien de détours par essais-erreurs, tout est consigné là ; le thread principal ne reçoit que le rapport final. Or le thread principal est le seul contexte qui traverse toute l'exécution,
c'est donc celui sur lequel il faut économiser en priorité.

Mesuré ([HT001](../cases/ht001.md), une exécution de 10.4 heures) :

| | Thread principal | subagent | Part absorbée |
|---|---|---|---|
| Tours de modèle | 70 | 3.0K | 97.7 % |
| Caractères de contenu | 200.1K | 3.6M | **94.8 %** |
| Appels d'outils | 32 | 1,893 | —— |

En moyenne, à chaque délégation, **82 appels d'outils restent totalement invisibles pour le thread principal**. C'est la première couche d'économie de contexte, et la plus rentable ;
démonstration complète dans [Économie du contexte](../guide/context.md).

Deux malentendus fréquents :

- **Le coordinateur n'est pas un agent plus intelligent.** Par défaut, lui et l'exécutant tournent sur le même palier de modèle ; ce qu'on économise, c'est du contexte, pas du modèle.
- **Le format de réponse est contraint.** La réponse d'un exécutant fait exactement quatre sections — conclusion / justification / livrables / non vérifié, 30 lignes maximum,
  interdiction de coller du contenu de fichier, des sorties de commande, des logs ou des diffs bruts. Les choses volumineuses vont dans `artifacts/` du
  [workbench](../reference/glossary.md#工作台) ; la réponse ne donne que le chemin.

flower compte cinq rôles au total, tous construits de la même façon : un texte de règles injecté + un jeu d'outils + un jeu de hooks.

| Rôle | Ce qu'il fait | Ce qu'il a en main |
|---|---|---|
| [coordinateur](../reference/glossary.md#协调者) coordinator | Découpe, délègue, décide | `Agent` `TodoWrite` `Read` + `Bash` restreint |
| [exécutant](../reference/glossary.md#执行者) worker | Écrit du code, lance les tests, cherche de la documentation | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [clarificateur](../reference/glossary.md#确认者) clarify | Avant d'agir, ne fait que poser des questions, jusqu'à ce que ce soit clair | Outils de questionnement + outils en lecture seule, **aucun outil d'écriture** |
| [juge](../reference/glossary.md#判定者) judge | Fixe l'objectif, ou juge si le tour est terminé ou non | Outils de questionnement + `Read` `Glob` `Grep` (pour qu'il puisse lancer des commandes, il faut l'activer explicitement) |
| [oracle](../reference/glossary.md#旁路顾问) oracle | Répond en cours d'exécution à « où en est-on » | `Read` `Glob` `Grep`. **Ce qu'il dit n'entre pas dans le contexte de cette exécution** |

Paramètres et valeurs par défaut des fonctions fabriques : voir [Python API](../reference/api.md#角色工厂).

## Le long-horizon casse à quatre endroits {#四个机制}

Une exécution [long-horizon](../reference/glossary.md#长程) s'étale sur des heures ou des jours, traverse plusieurs sessions, survit à des redémarrages de processus.
Elle ne se disloque que d'un petit nombre de façons, et chacune a son mécanisme :

| Ce que vous craignez | Mécanisme | Ce qu'il fait | Détails |
|---|---|---|---|
| Ce qui sort n'est pas ce que vous vouliez | [clarification préalable](../reference/glossary.md#前置确认) | Avant d'agir, on questionne jusqu'à ce que le besoin soit net, puis on le fige dans un [brief](../reference/glossary.md#需求确认书) ; chaque étape suivante le lit au lieu de deviner à nouveau | [Clarification préalable](../guide/clarify.md) |
| Il dit que c'est fini, ça ne l'est pas | [gardien d'objectif](../reference/glossary.md#目标看守) | À la fin de chaque tour, un juge qui n'a pas participé au travail tranche indépendamment ; si l'objectif n'est pas atteint, ça repart | [Gardien d'objectif](../guide/goal.md) |
| Ça plante après des heures, tout est à refaire | [continuité](../reference/glossary.md#接续) | Relancer dans le même répertoire reprend automatiquement là où on en était — même si le processus a été tué ou la machine redémarrée | [Continuité](../guide/continuity.md) |
| Le contexte sature et tout est écrasé en un résumé | [passation](../reference/glossary.md#换代) | Quand ça sature, la session courante écrit un [document de passation](../reference/glossary.md#交接书) lisible et modifiable par un humain, puis une nouvelle session prend le relais | [Passation](../guide/handoff.md) |

Deux points à retenir séparément :

**Le [verdict](../reference/glossary.md#判定) a trois issues, pas deux.** Atteint, non atteint, **invérifiable dans cet environnement**.
Les deux dernières sont des conclusions différentes — « impossible de vérifier ici » ne vaut jamais un succès : on s'arrête et on demande à un humain.
Et le juge juge le **livrable**, pas le code source : [HT002](../cases/ht002.md) s'est fait avoir une fois —
il n'a regardé que la branche macOS du Makefile et a validé, alors que ce qui était livré était un ELF Linux.

**La passation n'est pas un [compact](../reference/glossary.md#压缩).** Le compact, c'est le modèle qui, dans son coin, résume la conversation précédente en un paragraphe :
illisible, non modifiable, et vous ne savez pas ce qui a été perdu. Le document de passation est structuré, posé sur le disque : vous pouvez l'ouvrir, changer une ligne, et relancer.
flower désactive par défaut l'auto-compact natif et met la passation à la place.

Deux couches de plus n'apparaissent pas dans ce tableau, mais tournent à chaque exécution :

- [spill](../reference/glossary.md#落盘) spill — tout résultat d'outil dépassant 4000 caractères est écrit dans `.flower/spill/`,
  et il ne reste qu'une ligne de chemin dans le contexte. **On rogne sur place**, on n'attend pas la saturation pour compacter après coup.
- [workbench](../reference/glossary.md#工作台) workbench — les trois répertoires `scripts/`, `artifacts/`, `notes/` sous `.flower/`,
  plus un index `INDEX.md` injecté dans le prompt système, pour que l'agent sache à chaque tour ce qu'il a sous la main.
  Sur HT001, il s'est accumulé **61 scripts, exécutés 331 fois**, dont **92 %** ont servi plus d'une fois.

## Ce que flower ne fait pas {#不做什么}

**Un. Il ne fournit pas de workflow clé en main.** Le framework ne s'occupe que des mécanismes : comment tourne une étape, comment économiser le contexte, comment reprendre après une coupure réseau,
comment éviter les collisions quand plusieurs exécutions modifient le même dépôt en parallèle, comment s'arrêter quand il faut demander à un humain. **Le workflow, c'est vous qui l'écrivez.**
Les trois étapes de `flower` lancé nu viennent de
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
assez génériques pour ne contenir aucune hypothèse métier — c'est un point de départ, pas la limite des capacités du framework.
Pour écrire le vôtre, voir [Concevoir un workflow](../guide/workflow.md).

**Deux. Il n'hérite pas de la configuration de la machine hôte.** flower tourne avec `setting_sources=[]` : il ne lit ni le `~/.claude/` de la machine,
ni le `.claude/` du projet. C'est ça, être [portable](../reference/glossary.md#可移植) — comportement identique sur une autre machine.
Les capacités métier arrivent par des [plugins](../reference/glossary.md#plugin) qui voyagent avec le dépôt, pas par ce qui se trouve installé par hasard sur cette machine.

**Trois. Les identifiants doivent être fournis par vous.** C'est le prix du point précédent. flower cherche les identifiants dans un ordre fixe (variables d'environnement du processus →
`$FLOWER_ENV` → `.env` du répertoire courant → `~/.config/flower/.env` → `.env` à la racine du dépôt source),
et en dernier recours emprunte les 9 clés d'identifiants au bloc `env` de `~/.claude/settings.json` —
**il n'emprunte que « où aller chercher le token »** ; rien d'autre dans settings.json n'influence le comportement de l'agent.
Ordre complet et sémantique de chaque variable dans la [Référence de configuration](../reference/config.md).

**Quatre. Il ne remplace pas le prompt système.** Les instructions métier sont [ajoutées à la suite](../reference/glossary.md#叠加)
du prompt système natif de Claude Code, elles ne le remplacent pas. La spécialisation ne se paie donc pas d'une perte de capacité généraliste.

---

Arrivé ici, vous devriez pouvoir lire toutes les sorties du [Démarrage rapide](quickstart.md).
Pour savoir comment régler chacun de ces mécanismes et quand il ne faut pas les utiliser, continuez à partir d'[Économie du contexte](../guide/context.md) ;
si vous voulez juste copier des commandes, allez à la [Référence CLI](../reference/cli.md).
