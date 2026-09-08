# Économie du contexte

Le contexte du [thread principal](../reference/glossary.md#主线程) est la seule chose qui traverse
un run [long-horizon](../reference/glossary.md#长程) de bout en bout ; ce qu'il contient et ce qu'il
ne contient pas décide jusqu'où ce run peut aller. La forme de flower — le
[coordinateur](../reference/glossary.md#协调者) ne met pas la main à la pâte, les productions longues
vont sur disque, les hooks élaguent sur-le-champ — se déduit entièrement de ce seul point.
Cette page explique pourquoi.

## Le problème résolu {#解决什么问题}

La [compaction](../reference/glossary.md#压缩) attend que le contexte soit plein pour résumer après
coup : elle traite le symptôme. Le vrai problème est ailleurs :
**ce qui est trivial n'aurait jamais dû entrer dans le thread principal.**

La différence est une question de moment. La sortie d'un `pytest` fait couramment des dizaines de
milliers de caractères ; le modèle y jette un œil, en tire une conclusion, et tous les caractères
restants sont réémis à chaque tour ensuite. Quand la fenêtre est pleine, la compaction les résume en
un paragraphe, avec les décisions qui se trouvaient à côté — on économise du volume, on perd le
« pourquoi ça a été décidé ainsi ». Le seuil de déclenchement de l'auto-compact est
**fenêtre − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)) ;
à cet instant, ce qui doit être jeté et ce qui ne doit pas l'être sont déjà couchés côte à côte.

flower s'en occupe en quatre couches, dans l'ordre de priorité — classées par gain :

| Couche | Ce qu'elle fait | Où |
|---|---|---|
| 1. Division du travail | le travail concret est délégué à un [subagent](../reference/glossary.md#subagent), les essais-erreurs vont dans son propre transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | scripts / productions longues / décisions écrits sur disque, index injecté dans le system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill sur-le-champ | le hook `PostToolUse` écrit sur disque les résultats d'outil au-dessus du seuil, ne laisse qu'une ligne de chemin dans le contexte | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim et prune | réécriture de la session avant le resume : résultats périmés, appels refusés, résidus de coupure ne sont plus réinjectés | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Les deux premières couches décident **si une chose entre**, les deux dernières **si ce qui est entré
reste**. L'ordre n'est pas inversible : aussi agressive soit-elle, la couche 4 ne rattrapera jamais
le volume que la couche 1 a laissé passer.

## Utilisation (code minimal) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model vaut "inherit" par défaut

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Ces quelques lignes installent les trois premières couches : `coordinator()` force toujours
`delegate_only=True` (couche 1) ; `workbench=True` crée le
[workbench](../reference/glossary.md#工作台) et injecte l'index dans le system prompt du
coordinateur (couche 2), tout en faisant installer `spill_guard` par le `Runtime` (couche 3). La
couche 4 est là par défaut — le [session store](../reference/glossary.md#会话存储) du `Runtime` est
câblé en dur sur `PruningSessionStore`, aucun paramètre du constructeur ne permet d'en changer.

!!! warning "`workbench=True` n'est pas optionnel"
    Le `delegate_guard` qui empêche le coordinateur d'agir est accroché dans `workbench_hooks`, et
    `workbench_hooks` n'est installé que si le `Runtime` a un workbench ; `whitelist_guard`, lui,
    est sauté à cause de `delegate_only=True`.
    Conclusion : **avec `Runtime(workbench=False)` et `coordinator()`, il n'y a aucun mur devant les
    Bash / Write / Edit du thread principal.**

## Ce qu'il fait réellement {#它实际做了什么}

### Couche 1 : division du travail (le plus gros gain) {#第一层分工省得最多}

Le coordinateur joue « une personne qui sait se servir de Claude Code » : il décompose, délègue, lit
les rapports, décide. Il n'a pas accès à Bash / Write / Edit — ses seuls outils sont `Agent`,
`TodoWrite`, `Read` (plus un `Bash` restreint quand `glance=True`, voir plus bas). Tout le travail
concret est délégué aux [exécutants](../reference/glossary.md#执行者).

**Quand ça se déclenche** : à chaque appel de `Bash|Write|Edit|NotebookEdit` par le thread
principal, le hook `PreToolUse` `delegate_guard` refuse sur-le-champ, et indique la voie —
« délègue à un subagent via l'outil Agent, écris dans la tâche l'objectif et les critères
d'acceptation, et exige qu'il écrive les productions longues dans `.flower/artifacts/` et ne
renvoie que des chemins et des conclusions ». Les subagents passent toujours. Le critère est la
présence ou non de `agent_id` dans les données du hook : **s'il n'y en a pas, c'est le thread
principal**.

**Combien ça économise** : les appels d'outils et les essais-erreurs du subagent **vont dans son
propre transcript** (distingué par `subpath` dans le session store) ; le thread principal ne garde
que cet unique appel `Agent` et le rapport final. Le processus d'essai-erreur n'a pas été
compacté — il n'est **jamais entré** dans le thread principal.

- Mesuré (une tâche qui produit beaucoup de sortie d'outils) : 83 % du transcript se trouve dans le
  subagent ; thread principal 13 entrées, 21K caractères, subagent 105K caractères.
- Mesuré (à l'échelle réelle, un run de 10.4 heures, voir [HT001](../cases/ht001.md)) : les
  subagents portent **97.7 %** des tours et **94.8 %** des caractères de corps ; 1,893 appels
  d'outils concrets contre 32 pour le thread principal (**59:1**). La compaction précoce n'est plus
  le scénario dominant.

Ces deux lignes sont deux mesures différentes : la première est un test à petite échelle plus
ancien, la seconde une re-mesure à l'échelle réelle. Même mécanisme ; plus l'échelle est grande,
plus le gain est grand.

Ce qu'on économise, c'est du contexte, pas de la gamme de modèle : `worker()` vaut
`model="inherit"` par défaut — un exécutant ne doit pas être dégradé.

Le seul coût en sens inverse de la division du travail est le
[mandat de tâche](../reference/glossary.md#任务书) — le texte que le coordinateur écrit en
déléguant : il entre dans le thread principal, et il y reste pour toujours. Mesuré : 8/8 mandats de
tâche répétaient des règles que le destinataire connaissait déjà ; dans le plus court, 521
caractères, seuls environ 120 caractères étaient spécifiques à la tâche, soit environ 4.8k de
contexte permanent gaspillés en un tour. D'où une règle câblée en dur dans `COORDINATOR_RULES` :
**le mandat de tâche ne contient que ce qui est propre à cette tâche**. La seule règle qu'il reste à
transmettre est « où est le workbench + productions longues dans `artifacts/` + ne renvoyer que
chemins et conclusions » — car l'index du workbench n'atteint pas les subagents, et le mandat de
tâche est le seul canal.

### Couche 2 : le workbench (contre la « réécriture à chaque fois ») {#第二层工作台治每次重写}

Trois répertoires sous `.flower/`, qui suivent l'espace de travail :

| Répertoire | Ce qu'on y met | Ce que ça résout |
|---|---|---|
| `scripts/` | scripts de vérification / reproduction qui seront relancés, première ligne `# desc: 一句话` | écrit une fois, relancé directement ensuite. Fini le « perdu à la compaction, réécrit à chaque fois » |
| `artifacts/` | productions longues de plus de 2000 caractères : logs, données, rapports, diffs | seuls les chemins et les conclusions apparaissent dans la conversation |
| `notes/` | décisions clés et raisons, un fichier par décision | compacté, redémarré, changé de machine : les conclusions sont toujours là |

**Quand ça se déclenche** : `INDEX.md` est généré automatiquement (40 entrées au maximum par
défaut) ; `refresh()` est appelé par `index_guard` sur `PostToolUse` quand un `Write` / `Edit` tombe
dans le workbench, et un rafraîchissement a aussi lieu avant le démarrage de chaque étape. Les trois
règles ci-dessus sont injectées dans le system prompt du coordinateur par `prompt_block()` — il sait
dès le départ quels scripts existent déjà, sans dépenser un appel d'outil pour les découvrir.

**Combien ça économise** : mesuré sur un run de 10.4 heures, **61 scripts écrits 95 fois, exécutés
331 fois ; 92 % ont été exécutés plus d'une fois, 0 écrit sans être lancé**. Qualitativement,
`audit-fake-ai-server.py` est réutilisé par 7 scripts.

Si cette couche fonctionne, c'est grâce à une différence : la compaction peut nettoyer le contexte,
**elle ne peut nettoyer ni le disque, ni l'index dans le system prompt**.

!!! warning "L'index n'est pas hérité par les subagents"
    L'index passe par un `system_prompt.append` au niveau session ; un subagent a son propre system
    prompt et **n'en hérite pas** (mesuré, $0.2461, `tests/prelude_live.py`). C'est pourquoi « où
    est le workbench + productions longues dans `artifacts/` » doit être relayé par le coordinateur
    dans le mandat de tâche — c'est le seul canal, pas une redondance.

### Couche 3 : spill sur-le-champ {#第三层当场落盘}

`spill_guard` est un hook `PostToolUse` qui regarde le résultat d'outil **avant qu'il n'entre dans
le modèle** : au-delà de `threshold` (**4000** caractères par défaut), le résultat est
[spillé](../reference/glossary.md#落盘) dans le répertoire `spill/` du workbench et remplacé dans le
contexte par une ligne de pointeur + les **400 premiers caractères**. Le contenu n'est pas perdu, il
n'est simplement plus résident.

**Quand ça se déclenche** : le matcher est `Bash|Read|Grep|Glob|WebFetch|WebSearch` ;
`main_only=False` par défaut, donc les résultats des subagents sont spillés aussi. Il ne remplace
que les **champs de type chaîne** trop longs dans la structure de sortie de l'outil, et ne touche
jamais aux listes (elles peuvent contenir des blocs image), car `updatedToolOutput` doit conserver
la structure de sortie de l'outil d'origine.

**La lecture d'un fichier spillé passe, elle n'est pas spillée à nouveau.** Sinon le « utilise Read
pour lire le texte complet » de la ligne d'indication serait une phrase creuse : la lecture
dépasserait à nouveau le seuil, serait à nouveau spillée, rendrait à nouveau une ligne de pointeur —
boucle infinie. Rencontré en vrai (`tests/handoff_live.py`, à sa première exécution réelle) : le
modèle a essayé cinq formulations pour contourner, a dit lui-même « The spill read loops back on
itself », et a fini par avaler le fichier par tranches de 40 lignes, sept ou huit tours brûlés pour
rien. Le sens du spill est de ne **pas** pousser automatiquement les gros objets dans le contexte ;
s'il décide lui-même de lire le texte complet, c'est son choix.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None ou 0 = ce hook n'est pas installé
```

**Combien ça économise** : sur le run [HT001](../cases/ht001.md), 103 spills, 791.4K caractères
remplacés par des pointeurs de chemin, hors du contexte résident.

### Couche 4 : trim et prune {#第四层裁剪与剪除}

Cette couche est dans le [session store](../reference/glossary.md#会话存储). Le store du `Runtime`
est toujours `PruningSessionStore` (chaîne d'héritage `SqliteSessionStore` ←
`TrimmingSessionStore` ← `PruningSessionStore`) ; il réécrit l'historique à réinjecter dans
`load()` — c'est-à-dire **avant le resume**. Pas un caractère du texte original dans SQLite n'est
modifié. Quatre choses :

**① Péremption temporelle** (`ephemeral`, activé par défaut). Les résultats des
[commandes éphémères](../reference/glossary.md#一次性命令) du type `git status`, `ls`, `cat` voient
leur corps remplacé par une phrase d'explication au bout de quelques tours ; les 6 plus récents sont
conservés. Le contenu périmé **n'est pas spillé** — archiver un vieux `git status` n'a aucun sens,
il suffit de le relancer :

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Mesuré sur un resume live : `expired: 2` ; sur un transcript réel, avec `keep_recent` abaissé à 2,
5 entrées périment.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **désactivé par défaut**). Le corps des
tool_result de `>= 2000` caractères est écrit dans `<workspace>/.flower/spill/`, le contenu du bloc
est remplacé par un pointeur de fichier, les 20 plus récents gardent leur texte original. Attention,
ce répertoire n'est **pas le même** que celui du `spill_guard` de la couche 3 : ce dernier écrit à
la racine du workbench, alors qu'ici il faut écrire dans l'espace de travail, sinon le `Read` de
l'agent n'y accède pas.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True fonctionne aussi
```

**③ [Prune](../reference/glossary.md#剪除) des appels refusés** (`keep_denials`, 1 par défaut). Le
fait même de bloquer pollue le contexte : le message de refus est un `tool_result` qui reste pour
toujours, avec **la commande qui n'a jamais été exécutée**. Mesuré une fois : 273 caractères
(93 caractères de refus + 180 caractères de commande morte) — la commande morte coûte plus cher que
le refus.

Plus grave que les tokens : **c'est trompeur**. Mesuré, après avoir lu quelques « n'utilise pas Bash
directement », le coordinateur n'essayait même plus un `git status` pourtant autorisé et disait
directement « Bash est restreint, j'envoie un agent regarder » — impuissance apprise, et un
démarrage de subagent payé en plus. On en garde 1 par défaut plutôt que 0 : le refus le plus récent
est un signal utile, il empêche le modèle de retenter en boucle la même commande bloquée dans le
même tour. La détection s'appuie sur le marqueur structurel `toolDenialKind: "permission-rule"` posé
par le harness lui-même, pas sur la correspondance de texte — le texte peut changer à tout moment,
le marqueur non. Mesuré en live : 2 refus → 1 retiré, 1 gardé, chaîne intacte, resume normal et le
modèle sait toujours ce qui s'est passé.

**④ Prune des résidus de coupure.** Les messages d'erreur API synthétiques produits pendant les
retries de coupure réseau ne sont pas réinjectés ; un `tool_result` laissé par une interruption est
remplacé par une explication neutre (`[上一轮在此处被中断,该工具结果未产生]`), l'entrée elle-même
étant conservée.

**La ligne rouge lors du retrait** : un `tool_use` et son `tool_result` doivent être retirés
**ensemble** (s'il en manque un, c'est `Missing Tool Result Block`), les autres appels du même
message assistant ne doivent pas être touchés, et la chaîne `parentUuid` doit être reconnectée.

`Runtime(trim=False)` (le défaut) **ne veut pas dire qu'on ne nettoie rien** : cela désactive
seulement le trim des gros résultats ; péremption, appels refusés et résidus de coupure sont
traités comme d'habitude.

### Contre-exemple : le coup d'œil, on le fait soi-même {#反例看一眼的活自己干}

Les trois premières couches disent toutes « délègue », mais il y a un contre-exemple : pour des
commandes comme `git status`, `ls`, `cat`, le résultat fait quelques dizaines de caractères, alors
que **le simple démarrage d'un subagent coûte environ 4.3k de contexte** (mesuré, non amortissable).
Payer ce prix pour un `ls` est une perte nette.

Le coordinateur récupère donc un Bash restreint (`coordinator(..., glance=True)`, activé par
défaut). Le critère n'est pas « la commande est courte », mais **le résultat peut-il périmer** ; et
« autorisé » et « périmé » sont décidés par la même fonction `is_ephemeral()` :

| | Autorisé en direct | Résultat marqué périmé |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ déléguer | — |

Les deux côtés doivent être la même table, sinon l'un ou l'autre pris isolément devient nuisible :
**autorisé sans trim**, un `git status` périmé occupe le contexte pour toujours et sera pris pour
l'état actuel, faussant les décisions ; **trimé sans être autorisé**, le coordinateur doit payer
4.3k pour un `ls`. `tests/glance.py` cloue cet invariant sous forme d'assertion — mesuré, 46
commandes jugées identiquement des deux côtés, dont 10 échantillons adverses.

**Piège (rencontré deux fois)** : le modèle n'écrit pas des commandes uniques, il écrit
`git status -s && echo "--- LOG ---" && git log --oneline -10`. La première version refusait en bloc
toute commande contenant `&&` / `|` / `2>&1`, et **glance devenait complètement inopérant** —
mesuré, les trois tentatives du coordinateur ont été bloquées, il a dû repartir déléguer à un
subagent. Aujourd'hui l'inspection se fait segment par segment : chaque segment doit être dans la
liste blanche pour passer, `git status && rm -rf x` reste bloqué (le second segment n'est pas dans
la table).

### Append, pas remplacement {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Quand `build_options()` compile un `AgentSpec` en options SDK, `instructions` passe par
[`append`](../reference/glossary.md#叠加) — ajouté **après** le system prompt natif de Claude Code,
pas à sa place. Les textes de discipline ci-dessus (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) sont
donc additifs : **la spécialisation ne se paie pas d'une perte de capacité générale.**

L'index du workbench passe par le même canal. Il est là à chaque tour, mais comme il fait partie du
system prompt, il n'occupe pas l'historique de conversation et la compaction ne peut pas l'effacer —
au prix noté plus haut : **il ne va que jusqu'au coordinateur**.

!!! warning "N'utilisez pas `disallowed_tools` pour empêcher le coordinateur d'agir"
    `disallowed_tools` est **au niveau session** et désactive aussi les subagents. Message d'erreur
    mesuré :

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    La bonne méthode tient en deux étapes : ne pas le mettre dans `allowed_tools`, puis n'intercepter
    que le thread principal avec un hook `PreToolUse` basé sur `agent_id`. `coordinator()` fait déjà
    exactement cela — il pose `delegate_only=True`, et `delegate_guard` bloque le thread principal
    tout en laissant passer les subagents.

    `allowed_tools` seul ne suffit pas non plus : c'est une **liste de dispense d'approbation, pas
    une liste blanche exclusive**. Mesuré, le modèle peut appeler des outils qui n'y figurent pas —
    dans une sonde à $0.1, un agent avec `allowed_tools=["Read"]` appelait très bien Write / Bash.
    Ce qui bloque vraiment, c'est le hook.

    **`allowed_tools` est lui aussi au niveau session : la même leçon apprise deux fois.** Un outil
    absent de cette liste doit passer par l'approbation de permission **quand un subagent** l'appelle
    aussi. Sans surveillance, personne n'approuve : il n'y a ni erreur ni arrêt, et le modèle
    retente le même appel en boucle (`toolDenialKind=user-rejected`). Mesuré : `WebFetch`/`WebSearch`
    ajoutés à l'exécutant mais écrits seulement dans `AgentDefinition.tools` — ce run a produit plus
    de vingt user-rejected et pas un seul mot de sortie (`roles.py:513-518`). Le symptôme est plus
    difficile à diagnostiquer qu'avec `disallowed_tools` : ce dernier lève une erreur immédiate,
    l'autre ne ressemble à rien d'anormal à l'écran. C'est pourquoi `coordinator()` fusionne
    désormais les outils web en lecture seule de ses exécutants dans son propre `allowed_tools`
    (`roles.py:523-526`), alors que `Write`/`Edit`/`Bash` **sont volontairement exclus de cette
    fusion** — les fusionner reviendrait à démonter le hook ci-dessus.

## Quand ne pas s'en servir {#什么时候不该用它}

Ces quatre couches économisent toutes des **détails d'exécution**. Les problèmes suivants ne sont
pas résolus par elles, et certains deviennent même plus difficiles à voir à cause d'elles :

1. **L'objectif a été mal compris — ces quatre couches aggravent le cas.** Une fois les détails
   d'exécution jetés, ce qui reste est précisément la décision bâtie sur la prémisse erronée, et
   elle **ressemble trait pour trait à une décision correcte**. Le long-horizon amplifie cela au
   pire : la prémisse erronée tourne pendant des heures, une dizaine de subagents sont lancés, un
   tas de productions atterrit sur le disque, et ce n'est qu'ensuite que le problème apparaît. À ce
   moment-là, ce qui coûte cher, ce ne sont pas les tokens, c'est que chaque production a été
   construite sur le mauvais besoin. Ce qui arrête cela, c'est la
   [clarification préalable](clarify.md), aucune couche de cette page.
2. **Le thread principal continue de croître de façon monotone.** Les quatre couches écrasent la
   pente, pas la direction. Mesuré : en 70 tours, le thread principal est passé de 28.7K à 185.9K,
   pente de 2.2K/tour, sans aucune compaction, consommant 18.6 % d'une fenêtre de 1M, **avec un mur
   extrapolé vers 440 tours**. Franchir ce mur relève du [handoff](handoff.md).
3. **Une fois la compaction complète désactivée, il n'y a plus de filet.** Quand le handoff est
   actif, le `Runtime` force `CompactPolicy(mode="no_summary")` sur le spec, ce qui désactive
   l'auto-compact (si le spec a explicitement fourni `compact`, c'est lui qui est respecté).
   Atteindre la limite est une erreur dure : ces quatre couches doivent donc s'utiliser avec le
   handoff, on ne peut pas se contenter de couper la compaction.
4. **La couche 4 n'agit qu'au resume.** Trim et prune ont lieu dans `load()` ; une session qui tourne
   en continu ne rétrécit pas grâce à eux. Une fois la division du travail ci-dessus en place, cette
   couche est de toute façon peu sollicitée — le thread principal ne contient déjà pas beaucoup de
   résultats d'outils.
5. **Déléguer un simple coup d'œil est une perte nette.** Le démarrage d'un subagent coûte environ
   4.3k, voir la section glance ci-dessus.
6. **Faire le compte du cache avant de réorganiser le contexte.** Mesuré sur un run : 299.4M tokens
   d'entrée, **96.1 % de hit cache** ; les $171 ne tiennent que grâce à cela. Toute optimisation qui
   réécrit l'historique doit d'abord faire ce calcul.
7. **Les résultats d'outil de type image ou document ne sont pas spillés.** `spill_guard` ne modifie
   que les champs chaîne de la structure de sortie, jamais les listes.

Les valeurs par défaut complètes et les signatures des paramètres sont dans
[Python API](../reference/api.md) ; les termes dans le [glossaire](../reference/glossary.md).
