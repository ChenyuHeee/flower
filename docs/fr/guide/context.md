# Économie du contexte

Le contexte du [thread principal](../reference/glossary.md#主线程) est la seule chose qui traverse
un run [long-horizon](../reference/glossary.md#长程) de bout en bout ; ce qu'il contient, et ce qu'il
ne contient pas, décide jusqu'où ce run peut aller. La forme de flower — un
[coordinateur](../reference/glossary.md#协调者) qui ne met pas la main à la pâte, les longues sorties
écrites sur disque, les hooks qui élaguent à la source — découle entièrement de cette seule contrainte.
Cette page explique pourquoi.

## Quel problème ça résout

La [compaction](../reference/glossary.md#压缩) attend que le contexte soit plein pour résumer après
coup : elle traite le symptôme. Le vrai problème est ailleurs :
**le trivial n'aurait jamais dû entrer dans le thread principal.**

La différence est une question de moment. La sortie d'un `pytest` fait facilement des dizaines de
milliers de caractères ; le modèle y jette un œil, en tire une conclusion, et tous les caractères
restants sont renvoyés à chaque tour. Quand la fenêtre sature, la compaction les résume en un
paragraphe avec les décisions voisines — ce qu'on économise, c'est du volume ; ce qu'on perd, c'est
« pourquoi on avait tranché comme ça ». Le seuil de déclenchement de l'auto-compact est
**fenêtre − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)) ;
à cet instant, ce qui devait être jeté et ce qui ne devait pas l'être sont déjà couchés côte à côte.

flower résout ça en quatre couches, l'ordre étant la priorité — classées par ce qu'elles économisent :

| Couche | Rôle | Où |
|---|---|---|
| I. Division du travail | Le travail concret est délégué à un [subagent](../reference/glossary.md#subagent), les essais-erreurs vont dans son propre transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| II. Workbench | Scripts / longues sorties / décisions écrits sur disque, index injecté dans le system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| III. Spill immédiat | Le hook `PostToolUse` spille sur disque les résultats d'outil au-delà du seuil, le contexte ne garde qu'une ligne de chemin | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| IV. Trim et prune | Réécriture de la session avant le resume : résultats périmés, appels refusés, résidus de déconnexion ne sont plus réinjectés | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Les deux premières couches décident **ce qui entre**, les deux dernières **ce qui reste une fois
entré**. L'ordre n'est pas interchangeable : même très agressive, la couche IV ne rattrape jamais
le volume que la couche I a laissé passer.

## Comment l'utiliser (code minimal)

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model vaut "inherit" par défaut

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Ces quelques lignes installent les trois premières couches : `coordinator()` fixe toujours
`delegate_only=True` (couche I) ; `workbench=True` crée le [workbench](../reference/glossary.md#工作台)
et injecte son index dans le system prompt du coordinateur (couche II), tout en faisant installer
`spill_guard` par le `Runtime` (couche III). La couche IV est là par défaut — le
[session store](../reference/glossary.md#会话存储) du `Runtime` est câblé sur `PruningSessionStore`,
aucun paramètre du constructeur ne permet de le remplacer.

!!! warning "`workbench=True` n'est pas une option"
    Le `delegate_guard` qui empêche le coordinateur d'agir est accroché dans `workbench_hooks`, et
    `workbench_hooks` n'est installé que si le `Runtime` a un workbench ; quant à `whitelist_guard`,
    il est court-circuité par `delegate_only=True`.
    Conclusion : **avec `Runtime(workbench=False)` et `coordinator()`, Bash / Write / Edit du thread
    principal n'ont plus le moindre garde-fou.**

## Ce que ça fait réellement

### Couche I : division du travail (la plus grosse économie)

Le coordinateur joue « quelqu'un qui sait se servir de Claude Code » : découper, déléguer, lire les
rapports, décider. Il n'a pas accès à Bash / Write / Edit — ses outils se limitent à `Agent`,
`TodoWrite`, `Read` (plus un `Bash` restreint quand `glance=True`, voir plus bas). Tout le travail
concret part chez les [exécutants](../reference/glossary.md#执行者).

**Quand ça se déclenche** : à chaque appel de `Bash|Write|Edit|NotebookEdit` depuis le thread
principal, le hook `PreToolUse` `delegate_guard` refuse sur-le-champ, et indique la marche à suivre —
« délègue à un subagent avec l'outil Agent, écris dans la tâche l'objectif et les critères
d'acceptation, et exige qu'il écrive les longues sorties dans `.flower/artifacts/` et ne renvoie que
des chemins et des conclusions ». Les subagents passent toujours. Le critère est la présence ou non
d'un `agent_id` dans les données du hook : **pas d'`agent_id` = thread principal**.

**Combien ça économise** : les appels d'outils et les essais-erreurs du subagent **vont dans son
propre transcript** (le session store les distingue par `subpath`), le thread principal ne garde que
cet unique appel `Agent` et le rapport final. Les essais-erreurs ne sont pas compactés : ils
**ne sont jamais entrés** dans le thread principal.

- Mesuré (une tâche qui produit beaucoup de sortie d'outils) : 83 % du transcript se trouve dans le
  subagent, thread principal 13 entrées / 21K caractères, subagent 105K caractères.
- Mesuré (à l'échelle réelle, un run de 10.4 heures, voir [HT001](../cases/ht001.md)) : les subagents
  portent **97.7 %** des tours et **94.8 %** des caractères de corps ; 1,893 appels d'outils concrets
  contre 32 pour le thread principal (**59:1**). La compaction précoce n'est plus le sujet.

Ces deux lignes sont deux mesures distinctes : la première est un test à petite échelle, plus ancien,
la seconde une re-mesure à l'échelle réelle. Même mécanisme ; plus l'échelle grandit, plus il
économise.

Ce qu'on économise, c'est du contexte, pas de la gamme de modèle : `worker()` utilise
`model="inherit"` par défaut — un exécutant ne doit pas être rétrogradé.

Le seul coût inverse de la division du travail, c'est le [brief de tâche](../reference/glossary.md#任务书) —
le texte que le coordinateur rédige en déléguant : il entre dans le thread principal, et y reste pour
toujours. Mesuré : 8/8 briefs répétaient des règles que le destinataire connaissait déjà ; le plus
court, 521 caractères, ne contenait qu'environ 120 caractères spécifiques à la tâche, soit environ
4.8k de contexte permanent gaspillé sur un seul tour. D'où une règle câblée dans `COORDINATOR_RULES` :
**un brief de tâche ne contient que ce qui est propre à cette tâche**. La seule consigne encore
nécessaire est « où est le workbench + les longues sorties vont dans `artifacts/` + ne renvoyer que
chemins et conclusions » — parce que l'index du workbench n'atteint pas les subagents, le brief de
tâche est le seul canal.

### Couche II : le workbench (contre la réécriture permanente)

Trois répertoires sous `.flower/`, qui suivent l'espace de travail :

| Répertoire | Contenu | Problème résolu |
|---|---|---|
| `scripts/` | scripts de vérification / reproduction qui resserviront, première ligne `# desc: une phrase` | Écrit une fois, relancé ensuite. Fini le « perdu à la compaction, réécrit à chaque fois » |
| `artifacts/` | longues sorties au-delà de 2000 caractères : logs, données, rapports, diffs | Seuls le chemin et la conclusion apparaissent dans la conversation |
| `notes/` | décisions clés et leurs raisons, un fichier par décision | Compactée, redémarrée, changée de machine : la conclusion est toujours là |

**Quand ça se déclenche** : `INDEX.md` est généré automatiquement (40 entrées au maximum par défaut) ;
`refresh()` est appelé par le `index_guard` du `PostToolUse` quand un `Write` / `Edit` tombe dans le
workbench, et un rafraîchissement a aussi lieu avant chaque étape. Les trois règles ci-dessus sont
injectées dans le system prompt du coordinateur par `prompt_block()` — il sait donc dès le départ
quels scripts existent déjà, sans dépenser un appel d'outil pour les découvrir.

**Combien ça économise** : mesuré sur un run de 10.4 heures, **61 scripts écrits 95 fois et exécutés
331 fois ; 92 % ont servi plus d'une fois, 0 écrit sans jamais tourner**. Qualitativement,
`audit-fake-ai-server.py` a été réutilisé par 7 scripts.

Si cette couche fonctionne, c'est grâce à une différence : la compaction peut vider le contexte,
**elle ne vide ni le disque, ni l'index dans le system prompt**.

!!! warning "L'index n'est pas hérité par les subagents"
    L'index passe par `system_prompt.append` au niveau de la session ; un subagent a son propre
    system prompt et **n'en hérite pas** (mesuré, $0.2461, `tests/prelude_live.py`). D'où
    l'obligation, pour le coordinateur, de retranscrire « où est le workbench + longues sorties dans
    `artifacts/` » dans le brief de tâche — c'est le seul canal, ce n'est pas de la redondance.

### Couche III : spill immédiat

`spill_guard` est un hook `PostToolUse` qui inspecte le résultat d'un outil **avant qu'il n'atteigne
le modèle** : au-delà de `threshold` (**4000** caractères par défaut), le résultat est
[spillé](../reference/glossary.md#落盘) dans le répertoire `spill/` du workbench, et remplacé dans le
contexte par une ligne de pointeur + les **400 premiers caractères**. Rien n'est perdu, ça ne réside
simplement plus en mémoire.

**Quand ça se déclenche** : le matcher est `Bash|Read|Grep|Glob|WebFetch|WebSearch` ; par défaut
`main_only=False`, donc les résultats des subagents sont spillés aussi. Le hook ne remplace que les
**champs chaîne** trop longs dans la structure de sortie de l'outil, et ne touche jamais aux listes
(elles peuvent contenir des blocs image), parce que `updatedToolOutput` doit conserver la structure
de sortie de l'outil d'origine.

**Lire un fichier de spill est laissé passer et n'est pas re-spillé.** Sinon, le « lis-le avec Read
si tu as besoin du texte intégral » du message de pointeur serait une phrase creuse : on relit, ça
dépasse à nouveau le seuil, c'est à nouveau spillé, on redonne un pointeur — boucle infinie. Rencontré
en vrai (au premier run réel de `tests/handoff_live.py`) : le modèle a essayé cinq formulations pour
contourner, a lui-même écrit « The spill read loops back on itself », et a fini par avaler le fichier
par tranches de 40 lignes, en gaspillant sept ou huit tours. Le spill sert à ne **pas** enfourner
automatiquement les gros objets dans le contexte ; si le modèle décide de lire le texte intégral,
c'est son choix.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None ou 0 = ce hook n'est pas installé
```

**Combien ça économise** : sur le run [HT001](../cases/ht001.md), 103 spills, 791.4K caractères
remplacés par des pointeurs de chemin, zéro résidence en contexte.

### Couche IV : trim et prune

Cette couche vit dans le [session store](../reference/glossary.md#会话存储). Le store du `Runtime` est
toujours un `PruningSessionStore` (chaîne d'héritage `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`) ; dans `load()` — c'est-à-dire **avant le resume** — il réécrit l'historique
qui va être réinjecté. Le texte d'origine dans SQLite n'est pas modifié d'un caractère. Quatre
opérations :

**① Péremption temporelle** (`ephemeral`, activé par défaut). Les résultats des
[commandes éphémères](../reference/glossary.md#一次性命令) comme `git status`, `ls`, `cat` voient leur
corps remplacé par une note après quelques tours ; les 6 plus récents sont conservés. Le contenu
périmé **n'est pas spillé** — archiver un vieux `git status` n'a aucun sens, il suffit de le relancer :

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Mesuré sur un resume en conditions réelles : `expired: 2` ; sur un transcript réel, avec `keep_recent`
abaissé à 2, 5 entrées périmées.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **désactivé par défaut**). Le corps des
`tool_result` de `>= 2000` caractères est spillé vers `<workspace>/.flower/spill/`, le contenu du bloc
est remplacé par un pointeur de fichier, les 20 plus récents gardant leur texte intégral. Attention :
ce répertoire **n'est pas le même** que celui du `spill_guard` de la couche III : ce dernier écrit à
la racine du workbench, alors qu'ici le fichier doit se trouver dans l'espace de travail, sans quoi le
`Read` de l'agent ne peut pas l'atteindre.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True 也行
```

**③ [Prune](../reference/glossary.md#剪除) des appels refusés** (`keep_denials`, 1 par défaut).
Le fait même de bloquer pollue le contexte : le message de refus est un `tool_result`, et il reste
là pour toujours avec **la commande qui n'a jamais été exécutée**. Mesuré : 273 caractères pour une
occurrence (93 caractères de refus + 180 caractères de commande morte) — la commande morte coûte plus
cher que le refus.

Plus grave que les tokens : ça **induit en erreur**. Mesuré, après avoir lu quelques « ne pas utiliser
Bash directement », le coordinateur n'essayait même plus le `git status` pourtant autorisé et
déclarait « Bash est restreint, envoyons un agent voir » — impuissance apprise, avec en prime le coût
d'un démarrage de subagent supplémentaire. On en garde 1 par défaut et non 0 : le refus le plus récent
est un signal utile, il empêche le modèle de retenter en boucle la même commande bloquée dans le même
tour. La détection s'appuie sur le marqueur structurel `toolDenialKind: "permission-rule"` posé par le
harness lui-même, pas sur la correspondance du texte — le texte peut changer à tout moment, le
marqueur non. Mesuré en conditions réelles : 2 refus → 1 retiré, 1 gardé, chaîne intacte, resume
normal, et le modèle sait toujours ce qui s'est passé.

**④ Prune des résidus de déconnexion**. Les messages d'erreur API synthétiques produits pendant les
retries de coupure réseau ne sont pas réinjectés ; un `tool_result` laissé par une interruption est
remplacé par une note neutre (`[上一轮在此处被中断,该工具结果未产生]`), l'entrée elle-même étant
conservée.

**Les lignes rouges du retrait** : un `tool_use` et son `tool_result` doivent être retirés
**ensemble** (s'il en manque un, c'est `Missing Tool Result Block`), les autres appels du même message
assistant ne doivent pas être touchés, et la chaîne des `parentUuid` doit être recousue.

`Runtime(trim=False)` (le défaut) **ne veut pas dire qu'on ne nettoie rien** : ça désactive uniquement
le trim des gros résultats ; péremption, appels refusés et résidus de déconnexion sont traités comme
d'habitude.

### Contre-exemple : les coups d'œil, on les fait soi-même

Les trois premières couches disent toutes « délègue », mais il y a un contre-exemple : des commandes
comme `git status`, `ls`, `cat` produisent quelques dizaines de caractères, alors que **le seul
démarrage d'un subagent coûte environ 4.3k de contexte** (mesuré, non amortissable). Payer ce prix
pour un `ls` est une perte sèche.

Le coordinateur récupère donc un Bash restreint (`coordinator(..., glance=True)`, activé par défaut).
Le critère n'est pas « la commande est courte », mais **est-ce que le résultat va périmer** ; et
« laisser passer » et « périmer » sont décidés par la même fonction, `is_ephemeral()` :

| | Laissé passer, exécuté soi-même | Résultat marqué périmé |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ déléguer | — |

Les deux colonnes doivent venir de la même table, sinon chacune prise isolément devient nuisible :
**laisser passer sans trimmer**, et un `git status` périmé occupe le contexte pour toujours, en plus
d'être pris pour l'état actuel et de fausser les décisions ; **trimmer sans laisser passer**, et le
coordinateur doit payer 4.3k pour un `ls`. `tests/glance.py` cloue cet invariant sous forme
d'assertions — mesuré : 46 commandes, verdicts strictement identiques des deux côtés, dont 10
échantillons adverses.

**Le piège (rencontré deux fois)** : le modèle n'écrit pas une commande unique, il écrit
`git status -s && echo "--- LOG ---" && git log --oneline -10`. La première version rejetait en bloc
toute commande contenant `&&` / `|` / `2>&1`, et **glance devenait totalement inopérant** — mesuré :
les trois tentatives du coordinateur ont été bloquées, il est reparti déléguer à un subagent.
Aujourd'hui, chaque segment est découpé et vérifié séparément : la commande passe si et seulement si
tous les segments sont sur la liste blanche ; `git status && rm -rf x` reste bloqué (le second segment
n'est pas dans la table).

### Append, pas remplacement

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Quand `build_options()` compile un `AgentSpec` en options SDK, `instructions` passe par
[`append`](../reference/glossary.md#叠加) — ajouté **après** le system prompt natif de Claude Code,
pas à la place. Les textes de discipline ci-dessus (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) sont
donc additifs : **la spécialisation ne se paie pas en capacités générales perdues.**

L'index du workbench emprunte le même canal. Il est présent à chaque tour, mais comme il fait partie
du system prompt, il n'occupe pas l'historique de conversation et la compaction ne peut pas l'effacer
— au prix mentionné plus haut : **il ne va que jusqu'au coordinateur**.

!!! warning "N'utilisez pas `disallowed_tools` pour empêcher le coordinateur d'agir"
    `disallowed_tools` est **au niveau de la session** : il désactive aussi les subagents. Erreur
    mesurée, texte d'origine :

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    La bonne méthode se fait en deux temps : ne pas le mettre dans `allowed_tools`, puis utiliser un
    hook `PreToolUse` qui ne bloque que le thread principal en se basant sur `agent_id`.
    `coordinator()` fait déjà exactement ça — il pose `delegate_only=True`, et `delegate_guard`
    bloque le thread principal tout en laissant passer les subagents.

    `allowed_tools` seul ne suffit pas non plus : c'est une **liste de dispense d'approbation, pas une
    liste blanche exclusive**. Mesuré, le modèle peut appeler des outils qui n'y figurent pas — dans
    une sonde à $0.1, un agent avec `allowed_tools=["Read"]` appelait sans problème Write / Bash.
    Ce qui bloque réellement, c'est le hook.

## Quand ne pas l'utiliser

Ces quatre couches économisent toutes du **matériau de terrain**. Les problèmes suivants ne sont pas
résolus par elles, et certains deviennent même plus difficiles à voir à cause d'elles :

1. **L'objectif a été mal compris — ces quatre couches aggravent le cas.** Une fois le matériau de
   terrain évacué, ce qui reste est précisément la décision bâtie sur une prémisse fausse, et elle
   **ressemble exactement à une décision correcte**. Le long-horizon amplifie ça au maximum : la
   prémisse fausse tourne d'abord plusieurs heures, mobilise une dizaine de subagents, dépose une pile
   de produits sur le disque, et n'éclate qu'ensuite. À ce moment-là, ce qui coûte cher, ce ne sont pas
   les tokens, c'est que chaque produit a été construit sur le mauvais besoin. Ce qui arrête ça, c'est
   la [clarification préalable](clarify.md), aucune des couches de cette page.
2. **Le thread principal croît toujours de façon monotone.** Les quatre couches écrasent la pente, pas
   la direction. Mesuré : en 70 tours, le thread principal passe de 28.7K à 185.9K, pente 2.2K/tour,
   aucune compaction sur tout le parcours, 18.6 % d'une fenêtre de 1M consommés, **extrapolation :
   le mur vers 440 tours**. Pour franchir ce mur, c'est le [handoff](handoff.md).
3. **Une fois la compaction complète désactivée, il n'y a plus de filet.** Quand le handoff est actif,
   le `Runtime` force `CompactPolicy(mode="no_summary")` sur le spec, ce qui désactive l'auto-compact
   (sauf si le spec fournit explicitement son propre `compact`, auquel cas il est respecté). Toucher
   la limite est une erreur dure : ces quatre couches doivent donc s'utiliser conjointement au
   handoff, on ne peut pas se contenter de couper la compaction.
4. **La couche IV n'agit qu'au resume.** Trim et prune ont lieu dans `load()` ; une session qui tourne
   en continu ne rétrécit pas grâce à eux. Une fois la division du travail ci-dessus appliquée, cette
   couche est d'ailleurs souvent inutile — le thread principal ne contient de toute façon pas
   beaucoup de résultats d'outils.
5. **Déléguer un simple coup d'œil est une perte sèche.** Démarrage d'un subagent ≈ 4.3k, voir la
   section glance ci-dessus.
6. **Avant de réorganiser le contexte, faites les comptes du cache.** Mesuré sur un run : 299.4M
   tokens d'entrée, **96.1 % de hits de cache** ; les $171 ne tiennent que grâce à ça. Toute
   optimisation qui réécrit l'historique doit d'abord faire ce calcul.
7. **Les résultats d'outils de type image ou document ne sont pas spillés.** `spill_guard` ne modifie
   que les champs chaîne de la structure de sortie, jamais les listes.

Valeurs par défaut complètes et signatures des paramètres dans [Python API](../reference/api.md) ;
vocabulaire dans le [glossaire](../reference/glossary.md).
