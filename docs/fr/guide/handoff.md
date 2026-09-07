# Handoff

Quand le contexte est presque plein, on fait écrire à **la session courante elle-même** un [document de handoff](../reference/glossary.md#交接书) lisible et modifiable par un humain,
puis on ouvre une nouvelle session qui prend le relais. Sans compact. Tout le processus est visible dans le terminal, le document atterrit sur le disque,
modifiable à tout moment — la session qui prend le relais lit exactement ce fichier.

!!! note "Le handoff n'est pas la continuité"
    Le [handoff](../reference/glossary.md#换代) change de [session](../reference/glossary.md#会话) **à l'intérieur d'un même run** ;
    la [continuité](../reference/glossary.md#接续) reprend le [run](../reference/glossary.md#运行) précédent **d'un processus à l'autre**,
    voir [Continuité](continuity.md).

    Les deux s'emboîtent automatiquement, aucun câblage supplémentaire n'est nécessaire : le [lignage](../reference/glossary.md#血缘) enregistre le
    `session_id` **final** de l'étape, et c'est précisément celui qui a pris le relais — donc le prochain réveil se raccroche au successeur,
    pas à la génération brûlée.

## Le problème résolu

L'auto-compact fourni par le SDK se déclenche à **fenêtre − 33k** (mesuré : avec une fenêtre de `200000`, le seuil est `167000` ;
l'algorithme de compression lui-même est dans le binaire du harness, on ne peut pas le modifier, on peut seulement décider s'il se déclenche),
et ce qu'il fait, c'est **résumer l'historique en un paragraphe**.
Il est à contre-courant de tout le reste du framework :

| | Quand la décision est prise | Ce qui reste |
|---|---|---|
| `spill_guard` | à l'instant où l'outil renvoie | le gros résultat part en [spill](../reference/glossary.md#落盘), une ligne de chemin reste dans le contexte |
| Artefact figé (brief / objectif) | à la fin de l'étape concernée | un document, l'étape suivante ne lit que lui |
| **auto-compact** | **seulement une fois le contexte plein, en regardant en arrière** | **un résumé écrit par le modèle lui-même** |

Ce que flower fait d'un bout à l'autre, c'est **décider sur le moment de ce qui doit rester**. Le [compact](../reference/glossary.md#压缩) est le seul endroit où l'on « répare après coup »,
et son produit a quatre défauts :

- **il est généré par le modèle** — ce qui figure dans le résumé dépend du jugement du modèle à cet instant, vous n'y participez pas
- **il est illisible** — il est écrit pour le modèle du tour suivant, pas pour un humain
- **il est immodifiable** — il est à l'intérieur du harness, aucun fichier à ouvrir
- **vous ne savez pas ce qui a été perdu** — vous ne voyez pas ce qui a disparu, et vous ne pouvez pas dire « pas ça » avant que ça disparaisse

Le handoff ramène tout ça dans la même façon de faire : **encore un artefact figé**, de la même forme que le brief et l'objectif —
structuré, écrit sur disque, **vous pouvez l'ouvrir, changer une ligne, et relancer**. Et c'est exactement ce que fait ce projet lui-même —
le `HANDOFF.md` à la racine du dépôt est la même chose, écrite à la main.

## Comment l'utiliser (code minimal)

La ligne de commande active le handoff par défaut :

```bash
flower                       # le handoff est actif par défaut
flower --window 200000       # à donner seulement si la déduction est fausse (défaut : 1 million)
flower --no-handoff          # désactive — retour à l'auto-compact du SDK
```

Dans votre propre code, le handoff est piloté par `Runtime(handoff=…)`, à `True` par défaut :

```python
from flower import HandoffPolicy, Runtime

# défaut : HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# fenêtre explicite (c'est le réglage à toucher quand on change de gateway ou de modèle)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # désactivé, retour à l'auto-compact
```

`Runtime.__init__` est entièrement keyword-only, `workspace` est obligatoire. `handoff` accepte une instance de `HandoffPolicy` ou
un `bool` ; passer un `bool` équivaut à `HandoffPolicy(enabled=…)`.

!!! warning "Handoff activé = auto-compact forcément désactivé"
    `Runtime(handoff=True)` est la **valeur par défaut**, et il fait ceci à l'assemblage de chaque tentative : dès que
    `handoff.enabled` et que `spec.compact is None`, la spec est remplacée par
    `CompactPolicy(mode="no_summary")` — c'est-à-dire l'injection de **`DISABLE_AUTO_COMPACT=1`** dans le sous-processus.

    La raison : si les deux mécanismes tournent en même temps, on ne peut plus dire qui a fait retomber le contexte à un moment donné. Le prix, c'est **l'absence de filet** :
    quand le tour qui écrit le handoff échoue, on ne peut ni s'arrêter, ni faire comme si de rien n'était en poussant jusqu'à la limite dure — d'où l'obligation d'un chemin de dégradation (voir plus bas).

    Pour garder l'auto-compact en secours, il faut donner **explicitement** `AgentSpec(compact=CompactPolicy(mode="auto"))` —
    si la spec le fournit elle-même, on la respecte, on n'écrase pas. Attention : cela **gagne silencieusement** contre les hypothèses du côté handoff.

## Ce qu'il fait réellement

### Déclenchement : deux chemins vers le handoff

**Un. Le niveau atteint le seuil.** Le critère est `_handoff_due` : `handoff.enabled`, **hors du tour qui écrit le handoff**,
`_ctx >= handoff.at`, et l'étape a déjà obtenu un `session_id`. `_ctx` est la taille de contexte réellement vue au dernier tour du
**thread principal** — on ne regarde que le [thread principal](../reference/glossary.md#主线程), le contexte d'un [subagent](../reference/glossary.md#subagent)
relève de sa propre transcript, il se dissipe une fois fini, et ne doit pas forcer un handoff du thread principal.

Au niveau `warn_at`, une alerte d'approche est émise une première fois, une seule fois par génération, sans saturer l'écran.

**Deux. L'API répond directement « ça ne rentre pas ».** Voir la section `is_overflow` plus bas.

Aucun des deux chemins n'est **contraint par `max_attempts`**, et aucun ne **consomme de quota de retry** (`attempt -= 1` en interne) —
un handoff n'est pas un échec.

### Le document de handoff : cinq sections, deux seulement obligatoires

Chaque section bloque une erreur type de celui qui prend le relais :

| Section | Champ | Ce qu'elle bloque |
|---|---|---|
| Ce qui est en cours | `doing` **requis** | ne pas savoir où l'on se trouve |
| Ce qui est déjà décidé | `decided` | rediscuter ce qui a déjà été tranché (avec le **pourquoi**) |
| Les impasses | `deadends` | **la section la plus chère** — voir plus bas |
| L'étape suivante | `next` **requis** | passer une demi-heure à décider quoi faire |
| Le terrain | `scene` | les **chemins** des fichiers clés et des livrables. Des pointeurs, pas du contenu |

`Handoff.missing()` ne vérifie que les deux sections de `REQUIRED = ("doing", "next")`, et `complete()` en est la négation.
**Exiger durement que « les impasses » soit non vide force l'invention** — en début de tâche, cette section doit justement être vide.
Et le verdict de `complete()` a des conséquences : s'il manque une section requise, ce handoff est **intégralement remplacé par un artefact dégradé assemblé mécaniquement**
(voir plus bas), ce qui est bien pire qu'un vrai handoff auquel il manque une section. D'où les trois autres sections optionnelles — utiles si écrites, non bloquantes si absentes.

Dans `to_markdown()`, une section vide s'écrit `(空)` ; l'en-tête de `prompt_block()` dit explicitement au repreneur « vous prenez le relais »,
pour l'empêcher d'aller réclamer du contexte à un humain. Le champ `step` ne sert qu'à l'en-tête du document, il n'entre pas dans l'analyse.

#### Pourquoi « les impasses » est la section la plus chère

Parce que c'est **ce que le repreneur paie le plus cher à redécouvrir**, et ce que le rédacteur oublie le plus facilement.

Le worker a un biais d'optimisme systématique (le [gardien d'objectif](goal.md) démontre la même chose) : il écrit ce qu'il a réussi,
il oublie d'écrire ce qu'il a essayé sans succès. Or c'est le second qui coûte vraiment cher — dans [HT002](../cases/ht002.md), une heure a été perdue à contourner un problème de compilation ;
si la conclusion de cette heure n'est pas écrite, le repreneur refera exactement le même détour.

C'est pourquoi `HANDOFF_PROMPT` consacre un paragraphe entier à ce point, avec le coût mesuré à l'appui.

### À quoi ça ressemble

```text
# 上下文 130.0K/200K · 还有约 20K 到换代

# 上下文 152.0K/200K —— 写交接准备换代
  - 现在在做  在给 Makefile 加 macOS 垫片头,让 sigemptyset 宏不再展开成语法错误。
  - 已定的事  不改业务源码 —— 用户明确说过边界,所以走 Makefile 生成 shim 这条路。
  - 走不通的  -D_ANSI_SOURCE 会把别的宏一起关掉;改 include 顺序无效。
  - 下一步    在干净 clone 上跑一次 make 验证 shim 成立。
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 152.0K 重新开始
```

**Entièrement automatique, sans s'arrêter pour vous attendre** — un run long-horizon ne doit pas se bloquer parce qu'un humain est parti manger.

L'événement est `Event("handoff")`, et `payload["phase"]` prend **trois** valeurs : `near` (approche), `writing` (en cours d'écriture ;
écrire un handoff prend une dizaine de secondes, sans cet événement l'interface semble figée) et `done` (handoff terminé). Le payload de `done` porte aussi
`context`, `window`, `degraded`, `path` et `sections`.

### Calcul des seuils

```python
at      = max(10_000, window - headroom)   # ligne de handoff, plancher à 10k
warn_at = max(1_000, at - 20_000)          # ligne d'alerte d'approche
```

Le plancher de 10k sur `at` est indispensable — plus bas, on n'arrive même plus à écrire le handoff.

Le schéma d'échelle ci-dessous prend `--window 200000` en exemple, **la fenêtre par défaut est 1 million** :

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                     alerte handoff    limite dure
```

Quand `window` n'est pas fourni, `default_window()` le déduit de la **chaîne du nom de modèle**, en ne regardant que les deux variables d'environnement
`ANTHROPIC_MODEL` et `ANTHROPIC_DEFAULT_OPUS_MODEL` :

| Nom du modèle | Fenêtre déduite |
|---|---|
| le nom contient le mot isolé `1m` | `1_000_000` |
| le nom contient `haiku` | `200_000` |
| tout le reste, **ainsi que le cas où aucune des deux variables n'est définie** | `1_000_000` |

Attention à l'ordre : `1m` est testé en premier, donc `claude-haiku[1m]` est déduit à 1 million, pas 200 000.

Pourquoi `headroom` vaut `50_000` : l'auto-compact se déclenche à fenêtre − 33k, le handoff doit passer avant lui ;
et « écrire le handoff » demande encore un tour complet. 50k satisfait ces deux contraintes à la fois.

**`--window` est le réglage à toucher en priorité quand on change de modèle ou de gateway.** Côté SDK, on n'obtient pas la taille de fenêtre de façon fiable, on ne peut que la deviner d'après le nom.
Fenêtre réelle plus grande → handoff trop précoce (du gaspillage, pas une erreur) ; plus petite → trop tard, il faut absolument régler. Une mesure mérite d'être citée :
le gateway de la machine de développement est configuré sur `claude-opus-5[1m]`. En comptant sur 200 000 comme au début, on changeait de génération tous les 150k,
alors qu'il tient en réalité jusqu'à 950k — **un facteur 5** : un travail long-horizon se retrouve haché menu.

`flower -v` permet de voir avant le démarrage la configuration d'identifiants effective (endpoint, nom du modèle, token masqué sauf les 4 premiers caractères).

### `is_overflow` : transformer une erreur dure en handoff immédiat

C'est la condition qui permet **d'oser mettre 1 million comme valeur par défaut de `default_window()`**.

Si la fenêtre est estimée trop grande, le seuil n'est jamais atteint, et l'auto-compact est désactivé — on va donc heurter l'API de plein fouet.
`is_overflow(*texts)` reconnaît ce signal : `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, etc.

Une fois reconnu, on emprunte **le même chemin de handoff**, à ceci près que le handoff de cette génération est forcément dégradé — cette session n'a plus la place
« d'écrire un tour de handoff ». On utilise donc directement l'artefact dégradé assemblé mécaniquement, on passe à une nouvelle session et on continue : **cette étape n'échoue pas**.

Le prix d'une surestimation tombe ainsi de « l'étape échoue » à « le handoff de cette génération est dégradé ».

`is_overflow` est une **fonction de module**, pas une méthode de `Handoff`, et elle est variadique.

### Quand le handoff ne peut pas être écrit : dégrader, pas s'arrêter

Le tour qui écrit le handoff peut lui aussi échouer — réseau coupé, modèle qui déraille, analyse à laquelle il manque une section requise. Comme
l'auto-compact est déjà désactivé, **il n'y a pas de secours** : s'arrêter là revient à heurter la fenêtre.

Ce qu'on fait : assembler mécaniquement un **handoff incomplet** à partir de ce qu'on a sous la main, marquer `doing` avec `[降级:交接没写成]`
(constante `DEGRADED`), fourrer dans `scene` les **1200** premiers caractères de la tâche d'origine, et changer de génération quand même. Le repreneur est explicitement averti
que ce qu'il reçoit est incomplet et qu'il doit aller voir le terrain lui-même. En parallèle, `StepResult.errors` gagne une entrée « handoff dégradé (…) »,
et la raison est consultable dans `manifest.json`.

Cela correspond à la fonction de module `degraded(step, prompt, *, why="")` ; `Handoff.degraded` est une property en lecture seule
qui teste la présence de ce marqueur dans `doing`.

> **Un handoff incomplet vaut infiniment mieux qu'un mur de fenêtre.**

Le tour qui écrit le handoff a deux autres particularités délibérées : il tourne avec `max_budget_usd=None` — **le handoff doit pouvoir être écrit,
il ne peut pas être bloqué par le budget** ; et `on_event=None` — ce tour ne pousse rien vers l'UI.

### Une mine : le tour qui écrit le handoff doit être exempté du seuil

Le handoff s'écrit **après le franchissement** — à ce moment-là, le niveau est par définition au-dessus du seuil. Sans exemption, le
premier message du tour de handoff conclut à nouveau « il faut faire un handoff », et il est interrompu sans avoir écrit un seul mot : **chaque génération produit un artefact dégradé**,
et tout a l'air normal (le chemin de dégradation fonctionne très bien).

Ça a été vécu : au premier vrai run de `tests/handoff_live.py`, **les deux générations de handoff étaient dégradées**. Les tests hors ligne ne l'avaient pas attrapé —
ils remplaçaient `_attempt` en entier, et le faux ne passait pas par ce critère. Le critère a maintenant été remonté dans `Runtime._handoff_due()`,
que les tests hors ligne vérifient directement.

### Un cran d'arrêt contre l'emballement

`max_generations=8`.

!!! danger "Une `window` sous-estimée provoque des handoffs infinis qui brûlent de l'argent"
    Le danger : si **le seuil descend sous le plancher de démarrage du rôle** (mesuré à environ 34k pour le [coordinateur](../reference/glossary.md#协调者),
    rien que le prompt système et l'index du [workbench](../reference/glossary.md#工作台) le consomment), alors chaque nouvelle session franchit le seuil dès sa première parole
    → écrire le handoff, changer de génération, refranchir, **sans fin**. Et comme le handoff ne consomme pas de quota de retry — c'est voulu — le seul cran d'arrêt est
    `max_generations=8`.

    Un long run normal n'atteint jamais 8 générations ; si vous y arrivez, c'est presque certainement que `window` est sous-estimée — le message d'erreur émis à la limite le dit
    directement (« le seuil est très probablement sous le plancher de démarrage de ce rôle, augmentez window, ou `--no-handoff` »).

### Le déroulé complet d'un handoff

```text
干活 (session A)
  |  le thread principal franchit le seuil     <- on ne regarde que le thread principal. Le contexte d'un subagent
  |                                               relève de sa propre transcript, il se dissipe une fois fini :
  |                                               pas de raison de forcer un handoff de la session principale
  |- coupure sur une frontière de message      <- même logique qu'une interruption Ctrl-C : couper proprement,
  |                                               sans déchirer l'état (même prix : les subagents en vol sont
  |                                               perdus. Les 50k de marge sont là pour ça)
  |- un tour de plus dans la même session : écrire le handoff
  |     pourquoi c'est elle qui l'écrit — elle seule a ce contexte. N'importe qui d'autre devrait d'abord tout relire,
  |     et le changement n'aurait servi à rien
  |- figé dans <workbench>/notes/交接-<nom d'étape>.md, la génération précédente déplacée dans notes/archive/交接/
  |- nouvelle session (resume=None, fork=False), prompt = prompt_block() du document de handoff
干活 (session B) continue
```

`HANDOFF_PROMPT` est le prompt qui fait écrire le handoff à la session courante, avec les deux placeholders `{used}` et `{window}`.
**Ce n'est pas un nouveau rôle** — seule la session courante possède ce contexte.

### Le handoff n'est pas un retry : comment la comptabilité est tenue

| Champ | Ce qu'il devient lors d'un handoff |
|---|---|
| `attempts` | **n'augmente pas** — il compte les tentatives échouées |
| `retired[]` | les session_id brûlés par cette étape y sont consignés **dans l'ordre** |
| `session_id` | toujours **celui qui a pris le relais en dernier**, jamais un brûlé |
| `context` | la taille de contexte réellement vue par le thread principal au dernier tour |
| `cost_usd` / `num_turns` | **cumulés** à travers les retries et les handoffs |

Tous ces champs entrent dans `manifest.json` : on peut reconstituer après coup « combien de générations cette étape a brûlées, et combien chacune a coûté ».

### Où atterrit le document

`<workbench>/notes/交接-<nom d'étape sans caractères illégaux>.md` ; la génération précédente, si elle existe, est déplacée vers
`notes/archive/交接/<nom d'étape>-<horodatage>.md`.

**Sans workbench, rien n'est écrit sur disque** — dans ce cas `_handoff_path` renvoie `None`, le document est quand même transmis au repreneur via le prompt,
le handoff se déroule normalement, mais **vous ne pourrez pas retrouver le fichier après coup**. Pour pouvoir le relire ensuite, activez le workbench
(`Runtime(workbench=True)`, ou monté par le [workflow](../reference/glossary.md#流程) lui-même).

## Quand ne pas l'utiliser

- **Vous voulez précisément le compact.** `flower --no-handoff`, ou `Runtime(handoff=False)`.
  Le handoff désactive l'auto-compact au passage ; si vous ne voulez pas de cet effet de bord, ne l'activez pas.
- **Vous voulez les deux en même temps.** Donner explicitement `AgentSpec(compact=CompactPolicy(mode="auto"))` préserve l'auto-compact,
  mais après ça on ne peut plus dire « qui a fait retomber le contexte », et le diagnostic devient difficile. Faites confiance au handoff, ou au compact, pas aux deux.
- **Tâches courtes, travail à un seul tour.** Le handoff ne se déclenchera jamais, le configurer n'a aucun sens — mais rappelez-vous que `Runtime` par défaut
  (`handoff=True`) désactive quand même l'auto-compact.
- **Pas de workbench, mais l'espoir de relire le handoff après coup.** Activez d'abord le workbench, sinon le document n'aura existé que dans le contexte de ce run.
- **Lancer un long run avant d'avoir ajusté `window`.** Si la fenêtre réelle est plus petite que la valeur par défaut, les premières générations produiront toutes des handoffs dégradés,
  et le dégradé est précisément le plus inutile des handoffs. Ajustez d'abord avec `--window`, ou lancez un run court pour lire le nom de modèle dans `-v`.
- **Prendre le handoff pour toute la gouvernance du contexte.** C'est la dernière ligne. Les couches qui coupent sur le moment
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) sont moins chères,
  voir [Économie du contexte](context.md).

## Boutons

| Symptôme | Quoi tourner |
|---|---|
| Handoffs trop fréquents, le travail est sans cesse interrompu | mettre `--window` à la fenêtre réelle du modèle (`-v` montre le nom de modèle effectif) |
| Handoff dès le démarrage, avec un message sur le « plancher de démarrage » | idem, `window` est sous-estimée |
| Les handoffs sont toujours dégradés | regarder `errors` dans `runs/manifest.json`, la raison de la dégradation y est écrite |
| Le repreneur refait toujours le travail de la génération précédente | la section « impasses » du handoff est trop maigre. Vous pouvez éditer ce fichier directement |
| Vous voulez relire un handoff après coup mais le fichier est introuvable | workbench non activé. Le handoff n'a pas été écrit sur disque, il n'est passé que par le prompt |
| Vous voulez simplement le compact | `--no-handoff` |

## Voir aussi

- [Continuité](continuity.md) — reprendre le run précédent d'un processus à l'autre, les deux faces de la même chose que cette page
- [Économie du contexte](context.md) — les couches qui coupent sur le moment
- [Gardien d'objectif](goal.md) — la démonstration du « biais d'optimisme systématique du worker »
- [API Python](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Ligne de commande](../reference/cli.md) — `--window`, `--no-handoff`
- Code source : [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
