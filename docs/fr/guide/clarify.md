# Clarification préalable

Avant de mettre les mains dedans, on tire le besoin au clair. Le [clarificateur](../reference/glossary.md#确认者) est un rôle qui **pose des questions et ne touche à rien**, jusqu'à ce que ce soit clair ; il produit à la fin un [brief](../reference/glossary.md#需求确认书) de très exactement quatre sections, figé sur le disque. Chaque [étape](../reference/glossary.md#步骤) suivante démarre en lisant ce document au lieu de deviner le besoin à nouveau — et cet échange de questions-réponses **n'est jamais entré** dans le contexte en aval.

## Le problème résolu {#解决什么问题}

Tout ce que les mécanismes de nettoyage de contexte de flower éliminent, c'est du **matériel de terrain** : expiration par obsolescence, retrait des appels refusés, retrait des messages d'erreur, [déversement](../reference/glossary.md#落盘) des gros résultats sur le disque. Perdre le matériel de terrain n'est pas grave : il suffit de relancer pour le ravoir.

Il existe une classe d'erreurs qui ne fonctionne pas comme ça : **le mauvais objectif**. C'est la seule classe d'erreurs que **nettoyer le contexte aggrave**. Une fois le matériel de terrain jeté, ce qui reste est précisément la décision bâtie sur la prémisse fausse — et elle ressemble trait pour trait à une bonne décision : rien n'indique que sa prémisse est douteuse.

Le [long-horizon](../reference/glossary.md#长程) amplifie ça au pire : la prémisse fausse tourne d'abord plusieurs heures, lance une dizaine de [subagents](../reference/glossary.md#subagent), pose une pile de livrables sur le disque, et n'est exposée qu'ensuite. À ce moment-là, ce qui coûte cher, ce ne sont pas les tokens : c'est que **chaque livrable a été construit sur le mauvais besoin**. La facture de [HT001](../cases/ht001.md) donne la mesure du rapport : l'étape de clarification du besoin, **$0.3704 / 5 tours / 0.06h** ; l'étape de travail qui suit, **$171.2476 / 31 tours / 10.44h**.

Il faut donc un canal capable de « s'arrêter pour demander », et il doit être **avant** le début du travail.

## Comment s'en servir (code minimal) {#怎么用最小代码}

### Zéro code : la ligne de commande {#零代码命令行}

Dans le répertoire du projet, lancez directement :

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Dans le terminal, les questions ressemblent à ceci :

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Tapez le **numéro** pour choisir une option, ou répondez directement en texte libre
- **Entrée = sauter** la question : il tranche lui-même et consigne son hypothèse dans « inconnues et hypothèses » (`未知与假设`)
- Il ne passe que si les quatre sections sont complètes ; le brief est figé dans `.flower/notes/需求.md`
- **Relancer ne redéclenche pas l'interrogatoire** — pour reclarifier, supprimez ce fichier ou ajoutez `--new`

Voir seulement ses questions sans enchaîner sur le travail : `flower --clarify-only`. Imposer un quota dur aux questions : `--asks 12` (ce n'est qu'avec ce flag qu'une ligne `(还能问 N 次)` s'ajoute sous les options ; sans quota, pas de limite et cette ligne n'apparaît pas). Personne devant l'écran : `--timeout 0`. L'implémentation de ce chemin est dans [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Les réponses passent par l'entrée standard : il faut un vrai terminal"
    Dans un pipe, sous `nohup`, en CI, personne ne peut répondre : dès que stdin atteint EOF, la question en attente est traitée comme « entrée fermée » et sautée, puis chaque question suivante attend pour rien tout le `--timeout`. Dans ce cas, mettez directement `--timeout 0` — toutes les questions retombent immédiatement dans le vide, il tranche lui-même et écrit ses hypothèses dans « inconnues et hypothèses ».

### Câbler soi-même {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # pas de limite de questions par défaut, attend 30 minutes
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

Dans `prompt`, n'écrivez que **votre** demande d'origine, une phrase suffit. Ce qu'il faut demander, c'est le clarificateur qui le décide — quelles questions poser dans votre domaine, le framework ne le sait pas et n'a pas à le savoir. Le `协调者` ci-dessus est un `AgentSpec` que vous fabriquez vous-même avec `coordinator()`, voir [Concevoir un workflow](workflow.md).

Les paramètres de `clarify_step()` :

| Paramètre | Défaut | Description |
|---|---|---|
| `channel` | — | `HumanChannel`. **La même instance** doit aussi être passée à `Workflow(channel=...)` |
| `brief_path` | — | Où le brief atterrit. Doit être dans le [workbench](../reference/glossary.md#工作台) effectivement rattaché, voir plus bas |
| `prompt` | — | Votre demande d'origine. `str` ou `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nom de l'étape, et aussi la clé dans `ctx` |
| `spec` | `None` | Fournir votre propre `AgentSpec` ; s'il est donné, `clarify()` n'est plus utilisé |
| `instructions` | `""` | Instructions métier ajoutées après `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = reclarifier à chaque fois (à utiliser quand le besoin change) |
| `on_fail` | `"stop"` | Où aller quand les quatre sections sont incomplètes, comme `Step.on_fail` |
| `retries` | `0` | Nombre de reprises quand les quatre sections sont incomplètes |
| `**spec_kw` | — | Transmis à `clarify()` : `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Après le passage, `ctx` contient trois choses :

```python
ctx["确认需求"]     # str, version compacte des quatre sections (prompt_block), à insérer directement dans le prompt aval ; clé = nom de l'étape
ctx[BRIEF_KEY]     # "_brief" —— l'objet Brief, à prendre si vous voulez accéder section par section
ctx[MISSING_KEY]   # "_brief_missing" —— présent seulement si les quatre sections sont incomplètes : lesquelles manquent, pour l'affichage UI
```

Quand ça ne tourne pas rond, commencez par ces boutons :

| Symptôme | Bouton à tourner |
|---|---|
| Trop de questions, trop morcelées | Donnez un quota dur à `max_asks` ; écrivez dans `instructions` ce qui va de soi dans votre domaine |
| Il démarre après trop peu de questions | Nommez dans `instructions` les points qu'il doit impérativement élucider (le nombre est déjà illimité par défaut, jouer sur le quota ne sert à rien) |
| Les quatre sections sont remplies à la va-vite | Donnez dans `instructions` un exemple issu de votre propre domaine |
| Ça bloque alors que personne ne surveille | `timeout_s=0` |
| Vous voulez reclarifier à chaque fois | `always_ask=True`, ou supprimez le fichier du brief |

## Ce qu'il fait réellement {#它实际做了什么}

### Déclenchement : trois points de câblage, aucun champ nouveau {#触发时机三处接线一个新字段都没加}

Ce que fabrique `clarify_step()` est un `Step` ordinaire, avec simplement trois callbacks remplis :

| Point de branchement | Quand ça tourne | Ce que ça fait |
|---|---|---|
| `Step.when` | Avant d'entrer dans l'étape | Si le brief existe déjà et que les quatre sections sont complètes, **saute** l'étape et injecte le brief dans `ctx` |
| `Step.gate` | Une fois l'étape terminée, avant de passer le résultat en aval | Si les quatre sections ne sont pas toutes écrites, **interdit de continuer** ; si elles le sont, `write()` pour **figer** |
| `Step.reduce` | Après le passage | Transmet en aval **les quatre sections parsées**, pas le texte brut du modèle |

**Sauter injecte aussi `ctx`.** C'est le point facile à manquer : quand `when` renvoie `False`, `Workflow` n'exécute pas l'étape, et n'écrit donc pas `ctx[step.name]` — c'est pourquoi `clarify_step` injecte le brief existant depuis `when`. Sinon, à la relance, l'aval prendrait un `KeyError`.

`reduce` transmet `Brief.prompt_block()` et non le texte brut du modèle, parce que ce texte peut contenir tout ce qu'il a écrit en plus (en mesure réelle, il colle l'intégralité du code dans sa réponse).

En [continuité](../reference/glossary.md#接续), cette étape change sa phrase d'ouverture — `CLARIFY_RESUME` : « on reprend la clarification du besoin restée inachevée — **ce n'est pas un nouveau départ**… ». Sans cette phrase, la continuité renvoie la demande d'origine comme une tâche neuve et le clarificateur risque de reposer des questions déjà posées.

### Frontière : les questions-réponses n'entrent pas dans le contexte aval {#边界问答不进下游的上下文}

```text
确认需求        session isolée  ────→  un brief figé de quatre sections sur le disque
                                          │
干活 (étape suivante)   nouvelle session (resume_from=None) ◄─┘   ne reçoit que ces quatre sections
```

Le `resume_from` de `clarify_step` garde son défaut `None`, donc l'étape suivante est une **nouvelle session** qui ne reçoit que le brief. Cet échange de questions-réponses **n'est jamais entré** dans le contexte du [coordinateur](../reference/glossary.md#协调者) — ce n'est pas « entré puis élagué ». La différence est de fond : ce qui a été élagué est encore dans `sessions.db` et peut être ramené par un resume ; ce qui n'est jamais entré n'a pas ce problème.

Les questions-réponses elles-mêmes sont **ajoutées à la fin de `log_path`**. Ce fichier n'occupe pas de contexte, n'est pas affecté par le compact, et survit à un changement de machine — c'est la même idée que le workbench.

### Les quatre sections bloquent chacune une classe d'échec {#四段各挡一类失败}

| Section | Contenu | Ce qui arrive si elle manque |
|---|---|---|
| **`目标`** (objectif) | Une phrase : quoi faire, pour qui | On produit autre chose |
| **`验收标准`** (critères d'acceptation) | Des conditions décidables, une par ligne. « c'est bien fait » ne compte pas, « lancer `x` sort `y` » compte | Personne ne peut trancher « c'est fini » |
| **`边界`** (limites) | **Ce qu'on ne fait explicitement pas** | Dérive du périmètre. Cette section tient en bride **chacun** des subagents suivants |
| **`未知与假设`** (inconnues et hypothèses) | Ce qui n'a pas été demandé, ce qui est retombé dans le vide par timeout, ce qui a été deviné, une ligne par entrée | **La prémisse fausse est enterrée en silence** |

La quatrième section est le fusible du long-horizon. Si l'une des trois premières est fausse, tant que l'hypothèse est écrite explicitement dans la quatrième, celui qui la lit ensuite a une chance de bloquer ; si elle est enterrée, on ne s'en aperçoit que quelques heures plus tard, quand tous les livrables sont bons à jeter. Une prémisse fausse n'est pas totalement évitable, mais on peut la rendre **explicite**.

Le passage n'a lieu que si les quatre sections sont complètes ; celles qui manquent sont signalées par `Brief.missing()` — il renvoie les noms de sections en chinois, directement affichables.

Le parsing est très tolérant sur la forme : `## 目标` / `**目标**` / `目标:` / `3. 边界` sont tous reconnus, le corps du texte collé juste après le titre (`目标: 做一个 X`) aussi, et les alias courants aussi (`验收条件`→验收标准, `不做什么`→边界, `未知项与假设`→未知与假设) ; si une même section apparaît plusieurs fois, la première non vide est prise. Deux exceptions à connaître :

- `Brief.parse()` **retire d'abord les blocs de code délimités** ; s'il rencontre une clôture **non fermée**, tout ce qui suit est jeté à partir de là. Quand la sortie du modèle est tronquée, aucune des sections suivantes n'est parsée → quatre sections incomplètes → `gate` renvoie l'étape à zéro.
- `Brief.load()` traite `"(未填)"` comme vide. Si en éditant le brief à la main vous recopiez le texte de remplissage produit par `to_markdown()`, cette section compte toujours comme manquante.

### Frontière : à quoi le clarificateur peut toucher {#边界确认者能碰什么}

Un clarificateur **non contraint** a été exécuté (`/tmp/probe_ask.py`, **$0.8908 / 230 secondes**) : après deux questions, il **s'est mis à écrire du code** ; bloqué par les permissions, il a **collé l'intégralité du code dans le corps de sa réponse**. Écrire « n'écris pas de code » dans le prompt n'arrête pas ça — son system prompt de l'époque contenait déjà une phrase de ce genre. Il y a donc deux mécanismes :

**Un : un hook bloque ses outils d'écriture.** La liste sans approbation de `clarify()` est `mcp__human__ask` plus (quand `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`, sans `Write` / `Edit` / `Bash` / `Agent`. Ce qui applique réellement cette règle, c'est le `whitelist_guard` que `Runtime` installe automatiquement : à partir de la liste sans approbation, il déduit lesquels de `Bash` / `Write` / `Edit` / `NotebookEdit` doivent être bloqués, et `deny` en cas de correspondance. Ce n'est pas « on lui a demandé de ne pas travailler », c'est qu'**il ne peut pas travailler**.

Lui donner la lecture est rentable : un coup d'œil au dépôt économise plusieurs questions, et cette session est jetée après usage, donc la salir ne coûte rien (`can_read=False` permet même de retirer la lecture).

**Ce doit être un hook, `allowed_tools` ne suffit pas.** Ce dernier est une **liste sans approbation, pas une liste blanche exclusive** — le modèle peut tout à fait appeler des outils qui n'y figurent pas. Deux preuves mesurées, toujours valides :

- Dans [HT002](../cases/ht002.md), le [juge](../reference/glossary.md#判定者) de l'étape « 设定目标 » a réellement lancé **11 fois `Bash`**, alors que `judge()` a `can_run=False` par défaut et que `Bash` n'est pas du tout dans la liste (ce run n'avait pas encore ce hook — aujourd'hui le même appel serait `deny` sur le champ par `whitelist_guard`, ce qui montre bien que c'est le hook qui l'arrête et pas la liste).
- **Sonde à $0.1** : on demande à un agent avec `allowed_tools=["Read"]` d'écrire un fichier — `Write` est refusé par la couche de permissions (`"requested permissions to write ... but you haven't granted it yet"`), `Bash` est refusé par la sécurité des chemins (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **L'appel a bien été émis**, il a été arrêté par d'autres couches.

`clarify()` ne fixe pas explicitement `permission_mode` et hérite du défaut d'`AgentSpec`, `"default"`. `coordinator()` a `"acceptEdits"` par défaut — si quelqu'un transmet cette valeur au clarificateur, cette protection disparaît.

**Deux : le framework ne parse que ces quatre sections et jette tout le reste.** `Brief.parse()` extrait d'abord les blocs de code délimités puis cherche les titres — même collé, le code n'atteint pas l'aval. C'est le dernier verrou contre « il pollue l'aval ».

### Frontière : le canal de questions {#边界提问通道}

Côté modèle, l'outil de question s'appelle `mcp__human__ask` (paramètre `question`, `options` facultatif). `HumanChannel` est un serveur MCP in-process qui **enregistre deux outils** — `mcp__human__ask` et `mcp__human__inbox` ; la liste sans approbation du clarificateur ne contient que le premier (la boîte de réception est pour le coordinateur).

```python
HumanChannel(
    on_event=None,        # callback pour une UI en push. Rattaché à un Workflow, Workflow.run le branche automatiquement
    max_asks=None,        # pas de limite par défaut
    timeout_s=1800.0,     # 30 minutes. None = attendre indéfiniment ; <= 0 = tout automatique
    log_path=None,        # les questions-réponses sont ajoutées à ce fichier, hors contexte
    amend_path=None,      # ce que l'humain dit en cours de run est ajouté à ce fichier (en général le brief lui-même)
    over_budget_text=..., timeout_text=..., declined_text=...,   # les formulations des trois retombées dans le vide
)
```

L'état normal d'un agent long-horizon est que **personne ne regarde**, donc « s'arrêter pour attendre quelqu'un » doit pouvoir échouer proprement :

| Réglage | Comportement |
|---|---|
| `timeout_s=1800.0` (défaut) | Attend une demi-heure ; à l'échéance renvoie une phrase d'explication, **pas une erreur** |
| `timeout_s=None` | Attend indéfiniment. À n'utiliser que si vous êtes sûr que quelqu'un surveille (le CLI ne peut pas donner cette valeur, `--timeout` est un float) |
| `timeout_s=0` (négatif idem) | **Tout automatique** : toutes les questions retombent immédiatement dans le vide, sans faire semblant d'attendre |
| `max_asks=None` (défaut) | **Pas de limite** — le nombre de questions est décidé par le clarificateur lui-même |
| `max_asks=N` | Quota dur. Au-delà, l'outil de question **refuse directement**, sans bloquer ni lever d'erreur |
| `max_asks=0` | Interdiction de poser des questions (CI / sans surveillance) |

Quand `max_asks=None`, `remaining` renvoie `-1` (pas 0, et pas l'infini) ; le terminal s'appuie là-dessus pour ne pas afficher « il reste N questions ».

Le texte exact renvoyé sur timeout est :

> Personne n'a répondu. Continue selon ton propre jugement et écris cette question ainsi que l'hypothèse que tu adoptes dans la section « inconnues et hypothèses ». Ne repose pas la question et ne t'arrête pas ici.

Les formulations des trois retombées dans le vide (timeout / quota épuisé / question sautée par l'humain) pointent toutes vers la même action : **écrire l'hypothèse dans la quatrième section**. C'est pour ça que la quatrième section a quand même du contenu sans surveillance, et c'est aussi pour ça qu'un run long-horizon peut continuer. Un quota écrit dans le prompt est une suggestion ; **compté dans le canal, c'est une garantie**.

Un fait de mécanique vérifié en mesure réelle : dans un handler d'outil MCP in-process, `await` sur une future externe **ne provoque pas de deadlock** — pendant que le handler est suspendu, la boucle d'événements continue de tourner, et une autre tâche ou **un autre thread** peut y déposer la réponse. `answer()` / `decline()` peuvent donc être appelés directement depuis un backend web ou depuis le thread de saisie d'une TUI (en interne ça passe par `loop.call_soon_threadsafe`) ; c'est le cas normal, pas un cas limite. Les exceptions levées par les callbacks d'UI sont collectées dans `ui_errors` et **n'interrompent pas le run** — un crash du frontend ne doit pas emporter trois heures de travail. Liste complète des membres dans [l'API Python](../reference/api.md).

!!! warning "`max_turns` trop petit et « questionner jusqu'à ce que ce soit clair » devient un vœu pieux"
    Le `max_turns` de `clarify()` vaut `None` par défaut (illimité). **Chaque question posée est un tour** — le mettre à 16 revient à dire « une dizaine de questions au maximum », et cela prend effet **en silence** : du côté du canal, `max_asks=None` continue d'annoncer « pas de limite », et personne ne voit qui a coupé le robinet. Pour laisser les questions ouvertes, **les deux valeurs par défaut doivent rester à `None`** : `HumanChannel.max_asks` et `clarify(max_turns=...)`.

### Où le brief atterrit : forcément le workbench rattaché {#确认书落在哪必须是挂上去的那个工作台}

L'index du workbench est injecté dans le system prompt : le coordinateur sait dès le départ où est le fichier de besoin et n'a qu'à passer le chemin quand il distribue le travail, sans recopier le contenu dans le [brief de tâche](../reference/glossary.md#任务书).

!!! warning "L'index ne va que jusqu'au coordinateur"
    Un subagent a son propre system prompt et **n'hérite pas** de celui du niveau session (mesuré à **$0.2461**, `tests/prelude_live.py`). C'est donc « le coordinateur relaie le chemin », pas « chaque subagent le sait automatiquement ».

Le point clé est **quel** workbench. Une seule écriture est correcte : le créer soi-même, puis le rattacher au `Workflow`, en laissant le programme pilote donner le même objet à `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← rattaché
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Deux écritures fausses, qui **ne lèvent aucune erreur** — d'où la prudence particulière :

```python
# ✗ Fabriquer un chemin à la main : relatif au cwd du processus, ce n'est pas le même
#   répertoire que le <run_dir>/workbench créé par Runtime(workbench=True). Le brief est
#   écrit dans A, l'index injecté scanne B —— la promesse ci-dessus tombe en silence.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Vouloir le récupérer à l'envers depuis Runtime : impossible en passant par cli.py.
#   Il appelle d'abord main() pour construire le Workflow, et ne crée Runtime qu'ensuite —
#   à ce moment-là brief_path est figé depuis longtemps.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Quand vous écrivez votre propre pilote (sans passer par `cli.py`), créez d'abord le `Workbench`, puis donnez **le même objet** à la fois à `Workflow(workbench=wb)` et à `Runtime(workbench=wb)`. Le point 5 de `tests/trial_offline.py` assère directement que « le brief apparaît dans `prompt_block()` », et le point 11 confirme que cette assertion attrape bien la régression.

### État de la validation {#验证状态}

**Tout vert hors ligne** (`tests/clarify.py`, **52 points**, sans dépense) : les cinq sémantiques du canal de questions (attente bloquante d'une réponse / quota épuisé / retombée par timeout / question sautée / réponse depuis un autre thread), le parsing des quatre sections (dont un échantillon « du code a été collé dedans »), l'**absence** d'outils d'écriture pour le rôle `clarify()`, les trois points de câblage de `clarify_step`.

**Le chemin CLI passe hors ligne** : brief complet préinstallé → première étape sautée → le canal se branche automatiquement sur le thread d'entrée standard → le brief est injecté dans `ctx` → sortie propre.

**Jamais exécuté contre l'API réelle.** La sonde à $0.8908 était une **requête réelle**, mais elle mesurait « ce que fait un clarificateur non contraint », pas le chemin actuel.

## Quand ne pas l'utiliser {#什么时候不该用它}

**Le besoin est déjà un artefact figé.** Le besoin est écrit dans un fichier, imposé par un système en amont, ou bien il s'agit de refaire exactement la même chose — il n'y a rien à demander. Passez directement le texte du besoin à l'étape de travail, ou gardez `clarify_step` et laissez son `when` sauter l'étape (avec le brief présent, il ne demande de toute façon rien).

**Il n'y a personne à qui demander et vous ne voulez pas qu'il devine.** Avec `timeout_s=0`, toutes les questions retombent immédiatement dans le vide et la quatrième section se remplit d'une pile de ses propres hypothèses — c'est voulu, mais la fiabilité de ce brief est exactement celle de ces hypothèses. En CI, la façon plus propre est `max_asks=0` (interdiction explicite de demander), avec un besoin fourni intégralement de l'extérieur.

**Un petit travail ponctuel.** L'étape de clarification coûte de l'argent en soi : dans [HT002](../cases/ht002.md), pour « cloner un dépôt, l'installer et le faire tourner sous macOS », la clarification du besoin a coûté **$0.5306 / 9 tours / 0.10h**. Plus le travail est petit, plus la part de cette étape devient disgracieuse. Le chemin mono-agent `flower once` ne l'inclut pas.

**Changer le besoin ne doit pas passer par une nouvelle conversation.** Le brief est un artefact figé : dès son écriture sur le disque, c'est le fichier qui fait foi — la bonne façon est de **modifier ce fichier**. `--clarify-only` sur un répertoire déjà clarifié est une **opération vide** (ce workflow n'a que cette étape, et cette étape est sautée) ; pour reclarifier, il faut l'associer à `--new`, ou passer `always_ask=True` dans votre câblage.

**Il ne tranche pas « est-ce fini ? ».** C'est une autre couche, voir [gardien d'objectif](goal.md). La clarification préalable bloque « ce n'est pas ce qu'on voulait » ; elle ne bloque pas « il dit que c'est fini alors que ça ne l'est pas ».
