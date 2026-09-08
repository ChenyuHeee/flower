# Handoff

Quand le contexte est presque plein, on demande à **la session courante elle-même** d'écrire un [document de handoff](../reference/glossary.md#交接书) qu'un humain peut lire et modifier, puis on ouvre une nouvelle session qui prend le relais. Pas de compact. Tout le processus est visible dans le terminal, le document atterrit sur le disque, modifiable à tout moment — la session qui prend le relais lit exactement ce fichier.

!!! note "Le handoff n'est pas la continuité"
    Le [handoff](../reference/glossary.md#换代) change de [session](../reference/glossary.md#会话) **à l'intérieur d'un même run** ;
    la [continuité](../reference/glossary.md#接续) reprend le [run](../reference/glossary.md#运行) précédent **d'un processus à l'autre**,
    voir [Continuité](continuity.md).

    Les deux s'emboîtent automatiquement, sans câblage supplémentaire : la [lignée](../reference/glossary.md#血缘) enregistre le
    `session_id` **final** de cette étape, et c'est précisément le successeur — donc le prochain réveil reprend sur le successeur, pas sur la génération brûlée.

## Quel problème ça règle {#解决什么问题}

L'auto-compact fourni par le SDK se déclenche à **fenêtre −33k** (mesuré : avec une fenêtre de `200000`, le seuil est `167000` ;
l'algorithme de compact lui-même est dans le binaire du harness, on ne peut pas le changer, on ne peut changer que le fait qu'il se déclenche ou non),
et ce qu'il fait, c'est **résumer l'historique en un paragraphe**.
Il va à contre-courant du reste du framework :

| | Quand la décision est prise | Ce qui reste |
|---|---|---|
| `spill_guard` | à l'instant où l'outil renvoie | le gros résultat est [spillé](../reference/glossary.md#落盘) sur disque, une ligne de chemin reste dans le contexte |
| artefacts gelés (brief / objectif) | à la fin de l'étape | un document, que l'étape suivante est seule à lire |
| **auto-compact** | **ne regarde en arrière qu'une fois le contexte plein** | **un résumé écrit par le modèle lui-même** |

Du début à la fin, flower **décide sur place de ce qui doit rester**. Le [compact](../reference/glossary.md#压缩) est le seul endroit où l'on « répare après coup »,
et son produit a quatre défauts :

- **généré par le modèle** — ce qui figure dans le résumé dépend du jugement du modèle à cet instant, vous n'y participez pas
- **illisible** — il est écrit pour le modèle du tour suivant, pas pour un humain
- **non modifiable** — il est dans le harness, aucun fichier à ouvrir
- **vous ne savez pas ce qui a été perdu** — vous ne voyez pas ce qui disparaît, et vous ne pouvez pas dire « ça, ne le perds pas » avant que ça disparaisse

Le handoff ramène tout ça dans la même façon de faire : **encore un artefact gelé**, de la même forme que le brief et l'objectif —
structuré, écrit sur disque, **vous pouvez l'ouvrir, changer une ligne, et le laisser continuer**. Et c'est exactement ce que fait ce projet pour lui-même —
le `HANDOFF.md` à la racine du dépôt est la même chose, écrite à la main.

## Comment s'en servir (code minimal) {#怎么用最小代码}

En ligne de commande, le handoff est là par défaut :

```bash
flower                       # handoff activé par défaut
flower --window 200000       # à donner seulement si la détection est fausse (défaut : 1 million)
flower --no-handoff          # désactivé — retour à l'auto-compact du SDK
```

Quand vous écrivez votre propre code, le handoff est contrôlé par `Runtime(handoff=…)`, à `True` par défaut :

```python
from flower import HandoffPolicy, Runtime

# Défaut : HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# Fenêtre explicite (c'est le premier réglage à toucher en changeant de passerelle ou de modèle)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # désactivé, retour à l'auto-compact
```

`Runtime.__init__` est entièrement keyword-only, `workspace` est obligatoire. `handoff` accepte une instance de `HandoffPolicy` ou un
`bool` ; avec un `bool`, c'est équivalent à `HandoffPolicy(enabled=…)`.

!!! warning "Handoff activé = auto-compact forcé à off"
    `Runtime(handoff=True)` est **la valeur par défaut**, et voici ce qu'il fait à l'assemblage de chaque tentative : dès que
    `handoff.enabled` et `spec.compact is None`, la spec est remplacée par
    `CompactPolicy(mode="no_summary")` — c'est-à-dire l'injection de **`DISABLE_AUTO_COMPACT=1`** dans le sous-processus.

    La raison : si les deux mécanismes tournent en même temps, impossible de dire qui a fait retomber le contexte à un moment donné. Le prix, c'est **l'absence de filet** :
    quand le tour qui écrit le handoff échoue, on ne peut ni s'arrêter, ni faire comme si de rien n'était en tenant jusqu'au plafond dur ; il faut donc un chemin de dégradation (voir plus bas).

    Pour garder l'auto-compact en filet, il faut donner **explicitement** `AgentSpec(compact=CompactPolicy(mode="auto"))` —
    si la spec le fournit elle-même, on la respecte, on n'écrase pas. Attention : cela **gagne silencieusement** contre les hypothèses du côté handoff.

## Ce qu'il fait réellement {#它实际做了什么}

### Déclenchement : deux chemins vers le handoff {#触发时机两条路进换代}

**1. Le niveau atteint le seuil.** Le critère est `_handoff_due` : `handoff.enabled`, **pas pendant le tour qui écrit le handoff**,
`_ctx >= handoff.at`, et cette étape a déjà obtenu un `session_id`. `_ctx` est la taille de contexte réellement vue au dernier tour du
**main thread** — on ne regarde que le [main thread](../reference/glossary.md#主线程) ; le contexte d'un [subagent](../reference/glossary.md#subagent)
est l'affaire de sa propre transcript, il se dissipe à la fin, il ne doit pas forcer un handoff du main thread.

À `warn_at`, un avertissement d'approche est émis d'abord, une seule fois par génération, sans spammer.

**2. L'API répond directement « ça ne rentre plus ».** Voir la section `is_overflow` ci-dessous.

Aucun des deux chemins **n'est soumis à `max_attempts`**, et aucun **ne consomme de quota de retry** (`attempt -= 1` en interne) —
un handoff n'est pas un échec.

### Le document de handoff : cinq sections, deux seulement obligatoires {#交接书五段必填只有两段}

Chaque section bloque une catégorie d'erreur que commettra le successeur :

| Section | Champ | Ce que ça bloque |
|---|---|---|
| Ce qu'on est en train de faire | `doing` **obligatoire** | ne pas savoir où l'on se trouve |
| Ce qui est décidé | `decided` | rediscuter ce qui est déjà tranché (avec le **pourquoi**) |
| Les impasses | `deadends` | **la section la plus chère** — voir plus bas |
| Prochaine étape | `next` **obligatoire** | passer une demi-heure à décider quoi faire |
| La scène | `scene` | les **chemins** des fichiers clés et des livrables. Des pointeurs, pas du contenu |

`Handoff.missing()` ne vérifie que ces deux sections, `REQUIRED = ("doing", "next")` ; `complete()` en est la négation.
**Exiger que « les impasses » soit non vide forcerait à inventer** — au tout début d'une tâche, cette section doit justement être vide.
Et le verdict de `complete()` a des conséquences : s'il manque une section obligatoire, ce handoff est **entièrement remplacé par un artefact dégradé assemblé mécaniquement**
(voir plus bas), ce qui est bien pire qu'un vrai handoff auquel manque une section. D'où les trois autres sections optionnelles — utiles si écrites, mais elles ne bloquent pas le handoff.

Dans `to_markdown()`, une section vide est écrite `(空)` ; l'en-tête de `prompt_block()` dit explicitement au successeur « tu prends le relais »,
pour l'empêcher d'aller redemander le contexte à quelqu'un. Le champ `step` ne sert qu'à l'en-tête du document, il n'entre pas dans le parsing.

#### Pourquoi « les impasses » est la section la plus chère {#走不通的路为什么最贵}

Parce que c'est **ce que le successeur paiera le plus cher à redécouvrir**, et ce que l'auteur oublie le plus facilement.

Le worker a un biais d'optimisme systématique (le [goal guard](goal.md) démontre exactement la même chose) : il écrit ce qu'il a réussi,
il oublie d'écrire ce qu'il a essayé sans succès. Or c'est ce dernier qui coûte vraiment cher — dans [HT002](../cases/ht002.md), une heure a été passée à tourner autour d'un problème de compilation ;
si la conclusion de cette heure n'est pas écrite, le successeur refera exactement le même tour.

C'est pourquoi `HANDOFF_PROMPT` consacre un paragraphe entier à ce point, en citant ce coût mesuré.

### À quoi ressemble un vrai document de handoff {#长什么样}

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

**Entièrement automatique, ça ne s'arrête pas pour vous attendre** — un run long-horizon ne doit pas se bloquer parce que quelqu'un est parti manger.

L'événement est `Event("handoff")` ; `payload["phase"]` a **trois** valeurs : `near` (approche), `writing` (écriture en cours —
écrire le handoff prend une dizaine de secondes, sans cet événement l'interface a l'air figée) et `done` (handoff terminé). Le payload de `done` porte en plus
`context`, `window`, `degraded`, `path`, `sections`.

### Comment le seuil est calculé {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # ligne de handoff, plancher à 10k
warn_at = max(1_000, at - 20_000)          # ligne d'avertissement d'approche
```

Le plancher de 10k sur `at` est indispensable — en dessous, on n'arrive même plus à écrire le handoff.

Le schéma gradué ci-dessous prend `--window 200000` en exemple ; **la fenêtre par défaut est 1 million** :

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                      alerte handoff     plafond dur
```

Si `window` n'est pas donné, `default_window()` décide à partir de la **chaîne du nom de modèle**, en ne regardant que les deux variables d'environnement
`ANTHROPIC_MODEL` et `ANTHROPIC_DEFAULT_OPUS_MODEL` :

| Nom de modèle | Interprété comme |
|---|---|
| contient le mot isolé `1m` | `1_000_000` |
| contient `haiku` | `200_000` |
| tout le reste, **ainsi que les deux variables non définies** | `1_000_000` |

Attention à l'ordre : `1m` est testé en premier, donc `claude-haiku[1m]` est interprété comme 1 million, pas 200 000.

Pourquoi `headroom` vaut `50_000` : l'auto-compact se déclenche à fenêtre −33k, le handoff doit passer devant lui ;
et « écrire le handoff » demande encore un tour de plus. 50k satisfait les deux à la fois.

**`--window` est le premier interrupteur à régler quand on change de modèle ou de passerelle.** Côté SDK, on n'obtient pas de taille de fenêtre fiable, on ne peut que deviner d'après le nom.
Fenêtre réelle plus grande → handoff trop tôt (du gaspillage, pas une erreur) ; plus petite → trop tard, il faut régler. Une mesure vaut d'être citée :
la passerelle de la machine de développement est configurée sur `claude-opus-5[1m]`. En comptant 200 000 comme au début, on changeait de génération tous les 150 000,
alors qu'elle tient en réalité jusqu'à 950 000 — **un facteur 5** ; un travail long-horizon en serait réduit en miettes.

`flower -v` permet de voir avant le lancement la configuration d'identifiants effective (endpoint, nom du modèle, token masqué sauf les 4 premiers caractères).

### `is_overflow` : transformer une erreur dure en handoff immédiat {#is_overflow把硬错变成当场换代}

C'est ce qui permet **d'oser mettre 1 million comme valeur par défaut de `default_window()`**.

Si la fenêtre est surestimée, le seuil n'est jamais atteint, et l'auto-compact est désactivé — on va donc taper en dur contre l'API.
`is_overflow(*texts)` reconnaît ce signal : `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, etc.

Une fois reconnu, on emprunte **le même chemin de handoff**, sauf que le handoff de cette génération est forcément dégradé — cette session ne peut plus
faire « un tour de plus pour écrire le handoff », on utilise donc directement l'artefact dégradé assemblé mécaniquement, on passe à une nouvelle session et on continue : **cette étape n'échoue pas**.

Le coût d'une surestimation passe ainsi de « cette étape échoue » à « le handoff de cette génération est dégradé ».

`is_overflow` est une **fonction de niveau module**, pas une méthode de `Handoff`, et elle est variadique.

### Quand le handoff ne peut pas être écrit : dégrader, pas s'arrêter {#交接写不出来时降级不是停下}

Le tour qui écrit le handoff peut lui aussi échouer — réseau coupé, modèle qui déraille, parsing où il manque une section obligatoire. Comme
l'auto-compact est déjà désactivé, **il n'y a pas de filet** ; s'arrêter là revient à taper dans la fenêtre.

La méthode : assembler mécaniquement un **handoff incomplet** à partir de ce qu'on a sous la main, marquer `[降级:交接没写成]` dans `doing`
(constante `DEGRADED`), fourrer les **1200** premiers caractères de la tâche d'origine dans `scene`, et faire le handoff quand même. Le successeur est explicitement averti
que ce qu'il reçoit est incomplet et qu'il doit aller voir la scène lui-même. En parallèle, `StepResult.errors` reçoit une entrée de plus, « 交接降级(…) »,
dont `manifest.json` garde la raison.

Cela correspond à la fonction de niveau module `degraded(step, prompt, *, why="")` ; `Handoff.degraded` est une property en lecture seule
qui teste la présence de ce marqueur dans `doing`.

> **Un handoff incomplet vaut infiniment mieux que taper dans la fenêtre.**

Deux autres choix délibérés pour ce tour d'écriture : il tourne avec `max_budget_usd=None` — **le handoff doit pouvoir s'écrire,
il ne doit pas se bloquer sur le budget** ; et `on_event=None` — ce tour ne remonte rien à l'UI.

### Une mine : le tour qui écrit le handoff doit être exempté du seuil {#一颗地雷写交接那一轮必须豁免阈值}

Le handoff s'écrit **après le franchissement de la ligne** — à ce moment, le niveau est par construction encore au-dessus du seuil. Sans exemption,
le premier message du tour d'écriture rejugerait « il faut faire un handoff », il serait interrompu sans avoir écrit un seul mot, **chaque génération produirait un artefact dégradé**,
et tout aurait l'air normal (le chemin de dégradation fonctionne très bien).

C'est arrivé pour de vrai : au premier vrai run de `tests/handoff_live.py`, **les deux générations de handoff étaient dégradées**. Les tests hors-ligne ne l'avaient pas attrapé —
ils remplaçaient `_attempt` en entier, donc le faux ne passait pas par ce critère. Le critère a maintenant été remonté dans `Runtime._handoff_due()`,
que les tests hors-ligne vérifient directement.

### Un verrou anti-emballement {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "Une `window` trop petite = handoffs infinis et facture qui brûle"
    Le danger : **si le seuil est en dessous du plancher de démarrage du rôle** (mesuré à environ 34k pour le [coordinateur](../reference/glossary.md#协调者),
    rien que le prompt système et l'index du [workbench](../reference/glossary.md#工作台) le consomment), alors chaque nouvelle session franchit la ligne dès qu'elle ouvre la bouche
    → écrire le handoff, changer de génération, refranchir la ligne, **sans fin**. Et comme le handoff ne consomme pas de quota de retry — c'est voulu — le seul verrou est
    `max_generations=8`.

    Un long run normal n'atteint pas 8 générations ; si vous y arrivez, c'est presque à coup sûr que `window` est trop petite — le message d'erreur émis à la limite le dit tel quel
    (« 阈值很可能低于这个角色的启动地板,把 window 调大,或 `--no-handoff` »).

### Le déroulé complet d'un handoff {#一次换代的完整过程}

```text
干活(session A)
  |  le contexte du main thread franchit le seuil   <- on ne regarde que le main thread. Le contexte d'un
  |                            subagent est l'affaire de sa propre transcript, il se dissipe à la fin,
  |                            il ne doit pas forcer un handoff de la session principale
  |- coupure sur une frontière de message   <- même logique qu'un Ctrl-C : couper proprement, sans déchirer l'état
  |                            (même prix : les subagents en vol sont perdus. Les 50k de marge sont là pour ça)
  |- un tour de plus sur la même session : écrire le handoff
  |     pourquoi elle-même — elle seule a ce contexte. N'importe qui d'autre devrait d'abord tout relire, autant ne pas changer
  |- gelé dans <工作台>/notes/交接-<步骤名>.md, la génération précédente part dans notes/archive/交接/
  |- nouvelle session (resume=None, fork=False), prompt = prompt_block() du document de handoff
干活(session B) continue
```

`HANDOFF_PROMPT` est le prompt qui demande à la session courante d'écrire le handoff ; il contient deux placeholders, `{used}` et `{window}`.
**Ce n'est pas un nouveau rôle** — seule la session courante possède ce contexte.

### Le handoff ne compte pas comme un retry, comment la comptabilité est tenue {#换代不算重试账怎么记}

| Champ | Ce qu'il devient lors d'un handoff |
|---|---|
| `attempts` | **n'augmente pas** — il compte les tentatives échouées |
| `retired[]` | les `session_id` brûlés par cette étape y sont notés **dans l'ordre** |
| `session_id` | toujours **le dernier successeur**, jamais un brûlé |
| `context` | la taille de contexte réellement vue au dernier tour du main thread |
| `cost_usd` / `num_turns` | **cumulés** à travers retries et handoffs |

Ces champs vont tous dans `manifest.json` : on peut reconstituer après coup « combien de générations cette étape a brûlées, et ce que chacune a coûté ».

### Où atterrit le handoff {#交接落在哪}

`<工作台>/notes/交接-<步骤名去掉非法字符>.md` ; la génération précédente, si elle existe, est déplacée vers
`notes/archive/交接/<步骤名>-<时间戳>.md`.

**Sans workbench, rien n'est écrit sur disque** — `_handoff_path` renvoie alors `None`, le document est quand même transmis au successeur par le prompt,
le handoff a lieu normalement, seulement **personne ne pourra retrouver ce fichier après coup**. Pour pouvoir le relire, il faut activer le workbench
(`Runtime(workbench=True)`, ou bien laisser le [workflow](../reference/glossary.md#流程) en accrocher un lui-même).

## Quand ne pas s'en servir {#什么时候不该用它}

- **Vous voulez justement le compact.** `flower --no-handoff`, ou `Runtime(handoff=False)`.
  Le handoff désactive l'auto-compact au passage ; si vous ne voulez pas de cet effet de bord, ne l'activez pas.
- **Vous voulez les deux en même temps.** Donner explicitement `AgentSpec(compact=CompactPolicy(mode="auto"))` préserve l'auto-compact,
  mais après ça « qui a fait retomber le contexte » devient indécidable, et le diagnostic devient plus dur. Faites confiance au handoff ou au compact, pas aux deux.
- **Tâches courtes, travail en un seul tour.** Le handoff ne se déclenchera jamais, le configurer n'a pas de sens — mais souvenez-vous que `Runtime` a
  `handoff=True` par défaut et coupe donc quand même l'auto-compact.
- **Pas de workbench, mais l'envie de relire le handoff après coup.** Activez d'abord le workbench, sinon le document n'aura existé que dans le contexte de ce run-là.
- **Lancer un long run avant d'avoir accordé `window`.** Si la fenêtre réelle est plus petite que la valeur par défaut, les premières générations de handoff seront toutes dégradées,
  et le dégradé est précisément le handoff le plus inutile. Accordez d'abord avec `--window`, ou faites un run court pour lire le nom du modèle dans `-v`.
- **Prendre le handoff pour toute la gouvernance du contexte.** C'est la dernière ligne. Les couches qui coupent sur place
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) sont moins chères,
  voir [Économie du contexte](context.md).

## Table des symptômes : quel bouton tourner {#旋钮}

| Symptôme | Quel bouton |
|---|---|
| Handoffs trop fréquents, le travail est sans cesse interrompu | mettre `--window` à la vraie fenêtre du modèle (`-v` montre le nom de modèle effectif) |
| Handoff dès l'ouverture, avec un message sur le « plancher de démarrage » | pareil, `window` est trop petite |
| Les handoffs sont toujours dégradés | regarder `errors` dans `runs/manifest.json`, la raison de la dégradation y est écrite |
| Le successeur refait sans arrêt le travail de la génération précédente | la section « impasses » du handoff est trop maigre. Vous pouvez éditer ce fichier directement |
| Impossible de retrouver le fichier de handoff après coup | pas de workbench. Le handoff n'est pas écrit sur disque, il n'est passé que par le prompt |
| Vous voulez juste le compact | `--no-handoff` |

## À lire ensuite {#相关}

- [Continuité](continuity.md) — reprendre le run précédent d'un processus à l'autre : la même chose que cette page, dans l'autre sens
- [Économie du contexte](context.md) — les couches qui coupent sur place
- [Goal guard](goal.md) — l'argument « le worker a un biais d'optimisme systématique »
- [API Python](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Ligne de commande](../reference/cli.md) — `--window`, `--no-handoff`
- Code source : [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
