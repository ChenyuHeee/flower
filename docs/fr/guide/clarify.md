# Clarify

Poser clairement la question avant de mettre les mains dedans. Le [clarificateur](../reference/glossary.md#确认者) est un rôle qui ne fait que poser des questions, sans jamais agir ; il interroge jusqu'à ce que ce soit clair, puis produit un [brief](../reference/glossary.md#需求确认书) d'exactement quatre sections, gelé sur disque. Chaque [étape](../reference/glossary.md#步骤) suivante démarre en lisant ce document au lieu de redeviner le besoin — et ce dialogue **n'est jamais entré** dans le contexte en aval.

## Quel problème cela résout {#解决什么问题}

Tout ce que flower nettoie du contexte, ce sont des **traces d'exécution** : péremption temporelle, retrait des appels refusés, retrait des messages d'erreur, spill des gros résultats sur disque. Perdre ces traces n'est pas grave : il suffit de relancer pour les avoir de nouveau.

Il existe une catégorie d'erreur qui n'obéit pas à cette règle : **avoir mal compris l'objectif**. C'est la seule catégorie d'erreur que **le nettoyage du contexte aggrave**. Une fois les traces jetées, ce qui reste est précisément la décision bâtie sur une prémisse fausse — et elle ressemble trait pour trait à une décision correcte : plus rien n'indique que sa prémisse est douteuse.

Le [long-horizon](../reference/glossary.md#长程) amplifie cela au pire : la prémisse fausse tourne pendant des heures, lance une dizaine de [subagents](../reference/glossary.md#subagent), dépose une pile de livrables sur le disque, et ce n'est qu'ensuite qu'elle se révèle. À ce moment-là, ce qui coûte cher ce ne sont pas les tokens, c'est que **chaque livrable a été construit sur le mauvais besoin**. La facture de [HT001](../cases/ht001.md) donne la proportion : l'étape de clarification, **$0.3704 / 5 tours / 0.06h** ; l'étape de travail qui suit, **$171.2476 / 31 tours / 10.44h**.

Il faut donc un canal capable de « s'arrêter et demander », et il doit se trouver **avant** le début du travail.

## Comment s'en servir (code minimal) {#怎么用最小代码}

### Zéro code : la ligne de commande {#零代码命令行}

Allez dans le répertoire du projet et lancez :

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Dans le terminal, les questions apparaissent ainsi :

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Tapez le **numéro** pour choisir une option, ou répondez directement en toutes lettres
- **Entrée = sauter** cette question ; il tranchera seul et consignera son hypothèse dans « 未知与假设 » (inconnues et hypothèses)
- Il ne passe que si les quatre sections sont complètes ; le brief est gelé dans `.flower/notes/需求.md`
- **Une relance ne repose pas tout le questionnaire** — pour re-clarifier, supprimez ce fichier ou ajoutez `--new`

Pour voir seulement ce qu'il demande sans enchaîner sur le travail : `flower --clarify-only`. Pour imposer un quota dur de questions : `--asks 12` (ce n'est qu'avec cette option qu'une ligne `(还能问 N 次)` s'ajoute sous les choix ; par défaut le nombre est illimité et cette ligne n'apparaît pas). Personne devant l'écran : `--timeout 0`. L'implémentation de ce chemin est dans [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Les réponses passent par l'entrée standard : il faut un vrai terminal"
    Dans un pipe, sous `nohup`, en CI, personne ne peut répondre : dès que stdin atteint EOF, la question en cours est traitée comme « entrée fermée » et sautée, puis chaque question suivante attend bêtement tout le `--timeout`. Dans ce cas, donnez directement `--timeout 0` — toutes les questions échouent immédiatement, il tranche seul et écrit ses hypothèses dans « 未知与假设 ».

### Câblage manuel {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # questions illimitées par défaut, attend l'humain 30 minutes
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

Dans `prompt`, n'écrivez que **votre** demande brute, une phrase suffit. Ce qu'il faut demander, c'est le clarificateur qui le décide — quelles questions poser dans votre domaine, le framework ne le sait pas et n'a pas à le savoir. Le `协调者` ci-dessus est un `AgentSpec` que vous fabriquez vous-même avec `coordinator()`, voir [Concevoir un workflow](workflow.md).

Les paramètres de `clarify_step()` :

| Paramètre | Défaut | Description |
|---|---|---|
| `channel` | — | `HumanChannel`. **La même instance** doit aussi être montée sur `Workflow(channel=...)` |
| `brief_path` | — | Où atterrit le brief. Doit se trouver dans le [workbench](../reference/glossary.md#工作台) effectivement monté, voir plus bas |
| `prompt` | — | Votre demande brute. `str` ou `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nom de l'étape, et clé dans `ctx` |
| `spec` | `None` | Fournir votre propre `AgentSpec` ; s'il est donné, `clarify()` n'est plus utilisé |
| `instructions` | `""` | Instructions métier ajoutées après `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = re-clarifier à chaque fois (utile quand le besoin change) |
| `on_fail` | `"stop"` | Que faire si les quatre sections sont incomplètes, comme `Step.on_fail` |
| `retries` | `0` | Nombre de reprises si les quatre sections sont incomplètes |
| `**spec_kw` | — | Transmis à `clarify()` : `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Après l'exécution, `ctx` contient trois choses :

```python
ctx["确认需求"]     # str, version compacte des quatre sections (prompt_block), à insérer tel quel dans les prompts en aval ; clé = nom de l'étape
ctx[BRIEF_KEY]     # "_brief" —— l'objet Brief, à utiliser pour accéder aux sections une par une
ctx[MISSING_KEY]   # "_brief_missing" —— présent seulement si les quatre sections sont incomplètes : quelles sections manquent, pour l'affichage UI
```

Quand ça ne tourne pas rond, commencez par ces boutons :

| Symptôme | Bouton à tourner |
|---|---|
| Trop de questions, trop morcelées | Donner un quota dur à `max_asks` ; écrire dans `instructions` ce qui va de soi dans votre domaine |
| Il se met au travail après trop peu de questions | Nommer dans `instructions` les points qu'il doit impérativement élucider (le nombre est déjà illimité par défaut, régler le quota ne sert à rien) |
| Les quatre sections sont bâclées | Donner dans `instructions` un exemple tiré de votre propre domaine |
| Ça bloque alors que personne ne surveille | `timeout_s=0` |
| Vouloir re-clarifier à chaque fois | `always_ask=True`, ou supprimer le fichier de brief |

## Ce qu'il fait réellement {#它实际做了什么}

### Déclenchement : trois points d'accroche, pas un seul champ nouveau {#触发时机三处接线一个新字段都没加}

`clarify_step()` produit un `Step` ordinaire, avec simplement trois callbacks remplis :

| Point d'accroche | Quand il tourne | Ce qu'il fait |
|---|---|---|
| `Step.when` | Avant d'entrer dans l'étape | Si le brief existe déjà et que les quatre sections sont complètes, **saute** l'étape et l'injecte dans `ctx` |
| `Step.gate` | À la fin de l'étape, avant de passer le résultat en aval | Si les quatre sections ne sont pas toutes remplies, **interdit de continuer** ; si elles le sont, `write()` **gèle** le brief |
| `Step.reduce` | Après passage | Transmet en aval **les quatre sections parsées**, pas le texte brut du modèle |

**Même quand l'étape est sautée, `ctx` est alimenté.** C'est le point qu'on oublie facilement : quand `when` renvoie `False`, le `Workflow` n'exécute pas l'étape et n'écrit donc pas `ctx[step.name]` — c'est pourquoi `clarify_step` injecte le brief existant depuis `when`. Sans cela, une relance donnerait un `KeyError` en aval.

`reduce` transmet `Brief.prompt_block()` et non le texte brut du modèle, parce que ce texte peut contenir tout ce qu'il a écrit en plus (en pratique, il lui arrive de coller tout le code dans sa réponse).

En [continuité](../reference/glossary.md#接续), cette étape ouvre avec une autre phrase — `CLARIFY_RESUME` : « on reprend la clarification laissée en suspens — **ce n'est pas un redémarrage**… ». Sans cette phrase, la reprise renvoie la demande brute comme s'il s'agissait d'une nouvelle tâche, et le clarificateur risque de reposer des questions déjà posées.

### Frontière : le dialogue n'entre pas dans le contexte en aval {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

Le `resume_from` de `clarify_step` reste à `None` par défaut : l'étape suivante est donc une **nouvelle session** qui ne reçoit que le brief. Ce dialogue **n'est jamais entré** dans le contexte du [coordinateur](../reference/glossary.md#协调者) — ce n'est pas « il y est entré puis a été élagué ». La différence est substantielle : ce qui a été élagué est toujours dans `sessions.db` et peut revenir via un resume ; ce qui n'y est jamais entré n'a pas ce problème.

Le dialogue lui-même est **ajouté à `log_path`**. Cette copie n'occupe pas de contexte, ne subit pas le compact, et survit à un changement de machine — même logique que le workbench.

### Chaque section bloque une catégorie d'échec {#四段各挡一类失败}

| Section | Contenu | Conséquence si absente |
|---|---|---|
| **目标** (objectif) | Une phrase : quoi faire, pour qui | On construit autre chose |
| **验收标准** (critères d'acceptation) | Des conditions décidables, une par ligne. « bien fait » ne compte pas ; « lancer `x` produit `y` » compte | Personne ne peut trancher « c'est terminé » |
| **边界** (limites) | **Ce qu'on ne fait explicitement pas** | Dérive de périmètre. Cette section tient **chaque** subagent qui suivra |
| **未知与假设** (inconnues et hypothèses) | Ce qui n'a pas été demandé, ce qui a expiré sans réponse, ce qui a été deviné, une entrée par ligne | **Les prémisses fausses sont enterrées en silence** |

La quatrième section est le fusible d'un run long-horizon. Si l'une des trois premières est fausse, tant que l'hypothèse est écrite explicitement dans la quatrième, celui qui la lit ensuite a une chance de l'arrêter ; enterrée, on ne s'en aperçoit que quelques heures plus tard, quand tous les livrables sont bons à jeter. On ne peut pas éliminer complètement les prémisses fausses, mais on peut les rendre **explicites**.

Le passage n'est accordé que si les quatre sections sont complètes ; celles qui manquent sont signalées par `Brief.missing()` — il renvoie les noms de sections en chinois, directement affichables.

Le parseur est très tolérant sur la forme : `## 目标` / `**目标**` / `目标:` / `3. 边界` sont tous reconnus, le corps de texte collé juste après le titre (`目标: 做一个 X`) aussi, ainsi que les alias courants (`验收条件`→验收标准, `不做什么`→边界, `未知项与假设`→未知与假设) ; si une section apparaît plusieurs fois, la première non vide est retenue. Deux exceptions à connaître :

- `Brief.parse()` **retire d'abord les blocs de code en fences**, et dès qu'il rencontre une fence **non fermée**, il jette tout ce qui suit à partir de là. Si la sortie du modèle est tronquée, plus aucune section suivante n'est parsée → quatre sections incomplètes → `gate` renvoie l'étape à zéro.
- `Brief.load()` traite `"(未填)"` comme vide. Si, en éditant le brief à la main, vous recopiez le texte de remplacement produit par `to_markdown()`, la section est toujours considérée manquante.

### Frontière : ce à quoi le clarificateur peut toucher {#边界确认者能碰什么}

Un clarificateur **sans contrainte** a été mis à l'épreuve (`/tmp/probe_ask.py`, **$0.8908 / 230 s**) : après deux questions, **il s'est mis à écrire du code** ; bloqué par les permissions, il a **collé tout le code dans le corps de sa réponse**. Écrire « n'écris pas de code » dans le prompt n'arrête pas cela — son system prompt contenait déjà une phrase de ce genre. D'où deux mécanismes.

**Un : un hook intercepte ses outils d'écriture.** La liste d'exemption d'approbation de `clarify()` est `mcp__human__ask` plus (quand `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch` ; pas de `Write` / `Edit` / `Bash` / `Agent`. Ce qui applique réellement cette règle, c'est le `whitelist_guard` installé automatiquement par `Runtime` : à partir de la liste d'exemption, il déduit ceux de `Bash` / `Write` / `Edit` / `NotebookEdit` qu'il faut bloquer, et fait `deny` en cas de correspondance. Ce n'est pas « on lui a demandé de ne pas travailler », c'est qu'il **ne peut pas** travailler.

Lui donner la lecture est rentable : un coup d'œil au dépôt économise plusieurs questions, et cette session est jetée après usage, peu importe qu'elle se salisse (`can_read=False` permet même de retirer la lecture).

**Cela doit être un hook, `allowed_tools` ne suffit pas.** Ce dernier est une **liste d'exemption d'approbation, pas une liste blanche exclusive** — le modèle peut parfaitement appeler des outils qui n'y figurent pas. Deux preuves mesurées, toujours valides :

- Dans [HT002](../cases/ht002.md), le [juge](../reference/glossary.md#判定者) de l'étape « fixer l'objectif » a réellement exécuté **11 fois `Bash`**, alors que `judge()` a `can_run=False` par défaut et que `Bash` ne figure pas du tout dans la liste (ce run n'avait pas encore ce hook — aujourd'hui, le même appel serait immédiatement `deny` par `whitelist_guard`, ce qui montre bien que c'est le hook qui l'arrête, pas la liste).
- **Une sonde à $0.1** : on demande à un agent avec `allowed_tools=["Read"]` d'écrire un fichier — `Write` est refusé par la couche de permissions (`"requested permissions to write ... but you haven't granted it yet"`), `Bash` est refusé par la sécurité des chemins (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **Les appels ont bien été émis**, ce sont d'autres couches qui les ont arrêtés.

`clarify()` ne fixe pas explicitement `permission_mode` et hérite du défaut d'`AgentSpec`, `"default"`. Celui de `coordinator()` est `"acceptEdits"` — si quelqu'un transmet cette valeur au clarificateur, cette protection disparaît.

**Deux : le framework ne parse que ces quatre sections et jette tout le reste.** `Brief.parse()` extrait d'abord les blocs de code en fences puis cherche les titres — même collé, le code ne passe pas en aval. C'est la dernière écluse contre « il pollue l'aval ».

### Frontière : le canal de questions {#边界提问通道}

Côté modèle, l'outil de question s'appelle `mcp__human__ask` (paramètre `question`, `options` facultatif). `HumanChannel` est un serveur MCP in-process, et **il enregistre deux outils** — `mcp__human__ask` et `mcp__human__inbox` ; la liste d'exemption du clarificateur ne contient que le premier (la boîte de réception est pour le coordinateur).

```python
HumanChannel(
    on_event=None,        # callback pour une UI en push. Branché automatiquement par Workflow.run quand le canal est monté sur le Workflow
    max_asks=None,        # nombre de questions illimité par défaut
    timeout_s=1800.0,     # 30 minutes. None = attendre indéfiniment ; <= 0 = tout automatique
    log_path=None,        # le dialogue est ajouté à ce fichier, hors contexte
    amend_path=None,      # ce que l'humain dit en cours de run est ajouté à ce fichier (en général le brief lui-même)
    over_budget_text=..., timeout_text=..., declined_text=...,   # formulations des trois cas de non-réponse
)
```

L'état normal d'un agent long-horizon, c'est que **personne ne regarde** ; « s'arrêter et attendre quelqu'un » doit donc pouvoir échouer proprement :

| Réglage | Comportement |
|---|---|
| `timeout_s=1800.0` (défaut) | Attend une demi-heure ; à l'échéance renvoie une phrase d'explication, **pas une erreur** |
| `timeout_s=None` | Attend indéfiniment. À n'utiliser que si quelqu'un surveille à coup sûr (la CLI ne peut pas donner cette valeur, `--timeout` est un float) |
| `timeout_s=0` (négatif idem) | **Tout automatique** : toutes les questions échouent immédiatement, sans faire semblant d'attendre |
| `max_asks=None` (défaut) | **Nombre illimité** — c'est le clarificateur qui juge combien de fois demander |
| `max_asks=N` | Quota dur. Au-delà, l'outil de question **refuse directement**, sans bloquer ni lever d'erreur |
| `max_asks=0` | Questions interdites (CI / sans surveillance) |

Quand `max_asks=None`, `remaining` renvoie `-1` (ni 0 ni l'infini), et le terminal en déduit qu'il ne faut pas afficher « il reste N questions ».

Le texte renvoyé en cas de timeout est exactement :

> Personne n'a répondu. Continue selon ton propre jugement, et écris cette question ainsi que l'hypothèse que tu retiens dans la section « 未知与假设 ». Ne repose pas la question et ne t'arrête pas ici.

Les trois cas de non-réponse (timeout / quota épuisé / humain qui saute la question) pointent tous vers la même action : **écrire l'hypothèse dans la quatrième section**. C'est la raison pour laquelle cette section a quand même du contenu sans surveillance humaine, et la raison pour laquelle un run long-horizon peut continuer. Un quota écrit dans le prompt est une suggestion ; **c'est le compteur dans le canal qui est une garantie**.

Un fait de mécanique vérifié en pratique : dans un handler d'outil MCP in-process, faire `await` sur une future externe **ne provoque pas d'interblocage** — pendant que le handler est suspendu, la boucle d'événements continue de tourner, et une autre tâche ou **un autre thread** peut y déposer la réponse. `answer()` / `decline()` peuvent donc être appelés directement depuis un backend web ou depuis le thread d'entrée d'une TUI (en interne via `loop.call_soon_threadsafe`) : c'est le cas normal, pas un cas limite. Les exceptions levées par les callbacks d'UI sont collectées dans `ui_errors` et **n'interrompent pas le run** — un front-end qui plante ne doit pas emporter trois heures de travail. La liste complète des membres est dans [Python API](../reference/api.md).

!!! warning "Un `max_turns` trop petit vide « interroger jusqu'à ce que ce soit clair » de son sens"
    Le `max_turns` de `clarify()` vaut `None` par défaut (illimité). **Chaque question posée consomme un tour** — le fixer à 16 revient à dire « une dizaine de questions au maximum », et cela s'applique **en silence** : côté canal, `max_asks=None` affiche toujours « illimité », et personne ne voit qui a coupé. Pour laisser les questions libres, **les deux valeurs par défaut, `HumanChannel.max_asks` et `clarify(max_turns=...)`, doivent rester à `None`**.

### Où atterrit le brief : forcément dans le workbench monté {#确认书落在哪必须是挂上去的那个工作台}

L'index du workbench est injecté dans le system prompt : le coordinateur sait dès le départ où se trouve le fichier de besoin, et il lui suffit de transmettre le chemin en distribuant le travail, sans recopier le contenu dans le [brief de tâche](../reference/glossary.md#任务书).

!!! warning "L'index ne va que jusqu'au coordinateur"
    Un subagent a son propre system prompt et **n'hérite pas** de ce fragment au niveau session (mesuré à **$0.2461**, `tests/prelude_live.py`). C'est donc « le coordinateur relaie le chemin », pas « chaque subagent le sait automatiquement ».

Le point clé est de savoir **quel** workbench. Une seule écriture est correcte : le créer soi-même, le monter sur le `Workflow`, et laisser le programme pilote passer le même objet au `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← monté ici
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Deux façons de se tromper, aucune ne lève d'erreur — d'où la prudence requise :

```python
# ✗ Fabriquer un chemin à la main : il est relatif au cwd du processus, et le <run_dir>/workbench
#   créé par Runtime(workbench=True) est un autre répertoire. Le brief est écrit dans A, l'index injecté
#   scanne B —— la promesse ci-dessus est silencieusement caduque.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Vouloir le récupérer depuis le Runtime : impossible en passant par cli.py. Il appelle d'abord main()
#   pour construire le Workflow, et ne crée le Runtime qu'ensuite —— à ce moment-là brief_path est déjà figé.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Si vous écrivez votre propre pilote (sans passer par `cli.py`), créez d'abord le `Workbench`, puis donnez **le même objet** à la fois à `Workflow(workbench=wb)` et à `Runtime(workbench=wb)`. Le point 5 de `tests/trial_offline.py` assère directement que « le brief apparaît dans `prompt_block()` », et le point 11 confirme que cette assertion attrape bien la régression.

### Ce qui a été vérifié, ce qui ne l'a pas été {#验证状态}

**Tout vert hors ligne** (`tests/clarify.py`, **52 points**, sans coût) : les cinq sémantiques du canal de questions (attente bloquante d'une réponse / quota épuisé / échec par timeout / question sautée / réponse depuis un autre thread), le parsing des quatre sections (y compris l'échantillon « il a collé du code »), le fait que le rôle `clarify()` n'a **pas** d'outil d'écriture, et les trois points d'accroche de `clarify_step`.

**Le chemin CLI passe hors ligne** : brief complet préexistant → première étape sautée → canal branché automatiquement sur le thread d'entrée standard → brief injecté dans `ctx` → sortie propre.

**Pas d'essai contre l'API réelle.** La sonde à $0.8908 était bien une **requête réelle**, mais elle mesurait « ce que fait un clarificateur sans contrainte », pas ce chemin-ci.

## Quand ne pas l'utiliser {#什么时候不该用它}

**Le besoin est déjà figé.** Le besoin est écrit dans un fichier, imposé par un système amont, ou bien il s'agit simplement de refaire la même chose — il n'y a rien à demander. Passez le texte du besoin directement à l'étape de travail, ou laissez `clarify_step` en place pour que son `when` la saute (si le brief est là, il ne demande rien de toute façon).

**Personne à qui demander, et vous ne voulez pas qu'il devine.** Avec `timeout_s=0`, toutes les questions échouent immédiatement et la quatrième section se remplit de ses propres hypothèses — c'est voulu, mais la fiabilité de ce brief vaut alors exactement celle de ces hypothèses. En CI, la façon plus propre est `max_asks=0` (interdiction explicite de demander), le besoin étant fourni intégralement de l'extérieur.

**Petit travail ponctuel.** L'étape de clarification coûte de l'argent : dans [HT002](../cases/ht002.md), pour « cloner un dépôt, l'installer et le faire tourner sur macOS », la clarification a coûté **$0.5306 / 9 tours / 0.10h**. Plus le travail est petit, plus la proportion de cette étape est disgracieuse. Le chemin mono-agent `flower once` ne l'inclut pas.

**Changer le besoin ne doit pas relancer le dialogue.** Le brief est une pièce gelée ; à partir du moment où il est écrit sur disque, c'est le fichier qui fait foi — la bonne pratique est de **modifier ce fichier**. `--clarify-only` est un **no-op** dans un répertoire déjà clarifié (ce workflow ne contient que cette étape, et cette étape se saute) ; pour re-clarifier il faut ajouter `--new`, ou passer `always_ask=True` dans votre propre câblage.

**Il ne juge pas si « c'est terminé ».** C'est une autre couche, voir [gardien d'objectif](goal.md). Clarify empêche « on a construit autre chose que ce qui était voulu » ; il n'empêche pas « il dit que c'est fini alors que ça ne l'est pas ».
